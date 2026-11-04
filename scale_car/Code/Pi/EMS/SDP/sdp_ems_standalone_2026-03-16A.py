"""
sdp_ems_standalone.py — SDP Energy Management Controller
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-03-16A

Hardware:
    Fuel cell : Horizon H-20 PEM, 20W rated / 24W peak
    Battery   : 2S LiPo, 7.4V nominal, 8000 mAh (update Q_AH if different)
    Bus       : 18V DC (boost regulator output)
    Motor     : up to ~150W (scaled)
    Interface : Ethernet UDP  (Teensy W5500 <-> Pi 5)

Run:
    python3 sdp_ems_standalone.py --cost_j CostToGo_J_scaled.mat \
                                   --drive_cycle drive_cycle.csv

Drive cycle CSV must have columns: time_s, v_mps

Dependencies (install once on Pi):
    pip install scipy numpy --break-system-packages
    (no pyserial needed -- uses UDP sockets from stdlib)
"""

import argparse
import csv
import logging
import signal
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import scipy.io

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("sdp_ems_run.log"),
    ],
)
logger = logging.getLogger(__name__)

# ── Physical constants — H-20 + 2S LiPo + 18V bus ────────────────────────────
SOC_MIN      = 0.30
SOC_MAX      = 0.80
SOC_BINS     = 250
SOC_REF      = 0.55

PDEM_MIN     = -54.0
PDEM_MAX     = 150.0
PDEM_BINS    = 50

P_FC_MAX     =  24.0
P_BATT_MAX   = 125.0
P_BATT_MIN   = -54.0

Em           =   7.4
Q_AH         =   8.0
ETA_FC       =   0.40
Q_LHV_H2    = 120_000
GAMMA        =   0.95
ALPHA        = 500
U_STEPS      = 50

SOC_LOW_ENTER  = 0.32
SOC_LOW_EXIT   = 0.35
SOC_HIGH_ENTER = 0.78
SOC_HIGH_EXIT  = 0.75

TEENSY_IP       = "192.168.1.50"
PI_LISTEN_IP    = "0.0.0.0"
TEENSY_TX_PORT  = 5000
TEENSY_RX_PORT  = 5001
UDP_POLL_TIMEOUT = 0.005

TEENSY_TIMEOUT_MS = 200
CONTROL_HZ        = 20
CONTROL_PERIOD    = 1.0 / CONTROL_HZ

T2P_FMT  = "<BIH" + "f" * 10 + "HHBBB"
T2P_SIZE = struct.calcsize(T2P_FMT)
assert T2P_SIZE == 54

P2T_FMT  = "<BIHfffBBB"
P2T_SIZE = struct.calcsize(P2T_FMT)
assert P2T_SIZE == 22

TEENSY_HEADER = 0xAA
PI_HEADER     = 0xBB

MODE_HYBRID  = 0
MODE_FC_ONLY = 1
MODE_BATT    = 2
MODE_CHARGE  = 3
MODE_SAFE    = 4


@dataclass
class TeensyState:
    timestamp_ms:   int   = 0
    pkt_counter:    int   = 0
    v_actual:       float = 0.0
    V_batt:         float = 7.4
    I_batt:         float = 0.0
    I_charge:       float = 0.0
    V_fc:           float = 0.0
    I_fc:           float = 0.0
    V_bus:          float = 18.0
    P_motor:        float = 0.0
    share_echo:     float = 0.5
    share_actual:   float = 0.0
    droop_FC:       int   = 0
    droop_BT:       int   = 0
    charger_status: int   = 0
    fault_flags:    int   = 0
    received_at_ms: float = field(default_factory=lambda: time.monotonic() * 1000)

    @property
    def SOC(self) -> float:
        v = self.V_batt
        if v >= 8.40: return 1.00
        if v >= 8.10: return 0.90
        if v >= 7.80: return 0.75
        if v >= 7.60: return 0.60
        if v >= 7.40: return 0.50
        if v >= 7.20: return 0.35
        if v >= 7.00: return 0.20
        if v >= 6.60: return 0.10
        return 0.05


@dataclass
class SDPResult:
    P_fc_optimal:   float = 0.0
    P_batt_optimal: float = 0.0
    power_share:    float = 0.0
    feasible:       bool  = False
    soc_clamped:    bool  = False
    solve_time_ms:  float = 0.0


class SDPController:
    def __init__(self, cost_to_go_path: str, alpha: float = ALPHA):
        path = Path(cost_to_go_path)
        if not path.exists():
            raise FileNotFoundError(f"Cost-to-go file not found: {path}")
        mat = scipy.io.loadmat(str(path))
        if "cost_J" not in mat:
            raise KeyError(f"Expected 'cost_J' in {path.name}.")
        self.J         = mat["cost_J"].astype(np.float64)
        self.soc_grid  = np.linspace(SOC_MIN,  SOC_MAX,  SOC_BINS)
        self.pdem_grid = np.linspace(PDEM_MIN, PDEM_MAX, PDEM_BINS)
        self.u_grid    = np.linspace(0, P_FC_MAX, U_STEPS)
        self.alpha     = alpha
        if self.J.shape != (SOC_BINS, PDEM_BINS):
            raise ValueError(f"J shape {self.J.shape} != ({SOC_BINS},{PDEM_BINS}). Use CostToGo_J_scaled.mat.")
        logger.info("SDPController ready | J=%s | P_FC_MAX=%.0fW | SOC=[%.2f,%.2f] | alpha=%.0f",
                    self.J.shape, P_FC_MAX, SOC_MIN, SOC_MAX, self.alpha)

    def step(self, P_dem: float, SOC: float) -> SDPResult:
        t0 = time.perf_counter()
        soc_clamped = SOC < SOC_MIN or SOC > SOC_MAX
        if soc_clamped:
            SOC = float(np.clip(SOC, SOC_MIN, SOC_MAX))
        P_dem_c = float(np.clip(P_dem, PDEM_MIN, PDEM_MAX))
        pd_idx  = int(np.argmin(np.abs(self.pdem_grid - P_dem_c)))
        P_batt   = P_dem - self.u_grid
        SOC_next = SOC - (P_batt / Em) / (3600.0 * Q_AH)
        feasible = ((P_batt >= P_BATT_MIN) & (P_batt <= P_BATT_MAX) &
                    (SOC_next >= SOC_MIN) & (SOC_next <= SOC_MAX))
        if not feasible.any():
            return SDPResult(P_fc_optimal=0.0, P_batt_optimal=P_dem, power_share=0.0,
                             feasible=False, soc_clamped=soc_clamped,
                             solve_time_ms=(time.perf_counter()-t0)*1000)
        idx  = np.where(feasible)[0]
        u_f  = self.u_grid[idx]
        sn_f = SOC_next[idx]
        nsi  = np.array([int(np.argmin(np.abs(self.soc_grid - s))) for s in sn_f])
        fut  = self.J[nsi, pd_idx]
        costs = np.where(np.isinf(fut), np.inf,
                         u_f/(ETA_FC*Q_LHV_H2) + self.alpha*np.abs(sn_f-SOC_REF) + GAMMA*fut)
        bi = int(np.argmin(costs))
        if np.isinf(costs[bi]):
            return SDPResult(P_fc_optimal=0.0, P_batt_optimal=P_dem, power_share=0.0,
                             feasible=False, soc_clamped=soc_clamped,
                             solve_time_ms=(time.perf_counter()-t0)*1000)
        P_fc  = float(u_f[bi])
        share = float(np.clip(P_fc / max(abs(P_dem), 1.0), 0.0, 1.0))
        return SDPResult(P_fc_optimal=P_fc, P_batt_optimal=P_dem-P_fc,
                         power_share=share, feasible=True, soc_clamped=soc_clamped,
                         solve_time_ms=(time.perf_counter()-t0)*1000)


class DriveCycle:
    def __init__(self, csv_path: str, vehicle_mass_kg: float = 5.0):
        self.mass = vehicle_mass_kg
        self._load(csv_path)
        self._start = time.monotonic()

    def _load(self, path: str):
        t, v = [], []
        with open(path) as f:
            for row in csv.DictReader(f):
                t.append(float(row["time_s"]))
                v.append(float(row["v_mps"]))
        self.times  = np.array(t)
        self.speeds = np.array(v)

    def current(self):
        t = time.monotonic() - self._start
        if t >= self.times[-1]: return 0.0, 0.0, True
        i   = max(1, min(int(np.searchsorted(self.times, t)), len(self.times)-1))
        a   = (t - self.times[i-1]) / max(self.times[i]-self.times[i-1], 1e-9)
        v   = float(self.speeds[i-1] + a*(self.speeds[i]-self.speeds[i-1]))
        dt  = max(self.times[i]-self.times[i-1], 0.02)
        P   = float(np.clip(self.mass*v*(self.speeds[i]-self.speeds[i-1])/dt, PDEM_MIN, PDEM_MAX))
        return v, P, False


def _xor(data):
    r = 0
    for b in data: r ^= b
    return r

def build_cmd_packet(ctr, v_sp, share, chg, mode, droop):
    ts = int(time.monotonic()*1000) & 0xFFFFFFFF
    p = struct.pack("<BIHfffBB", PI_HEADER, ts, ctr&0xFFFF,
                    float(v_sp), float(share), float(chg), int(mode), int(droop))
    return p + struct.pack("B", _xor(p[1:]))

def parse_telemetry(data):
    if len(data) < T2P_SIZE: return None
    for s in range(len(data)-T2P_SIZE+1):
        if data[s] != TEENSY_HEADER: continue
        chunk = data[s:s+T2P_SIZE]
        if _xor(chunk[1:-1]) != chunk[-1]: continue
        try:
            (_,ts,ctr,v,Vb,Ib,Ic,Vfc,Ifc,Vbus,Pm,she,sha,dFC,dBT,chg,flt,_) = struct.unpack(T2P_FMT,chunk)
        except struct.error: continue
        return TeensyState(timestamp_ms=ts,pkt_counter=ctr,v_actual=v,V_batt=Vb,
                           I_batt=Ib,I_charge=Ic,V_fc=Vfc,I_fc=Ifc,V_bus=Vbus,
                           P_motor=Pm,share_echo=she,share_actual=sha,
                           droop_FC=dFC,droop_BT=dBT,charger_status=chg,fault_flags=flt,
                           received_at_ms=time.monotonic()*1000)
    return None


def run(args):
    ctrl = SDPController(args.cost_j, alpha=args.alpha)
    dc   = DriveCycle(args.drive_cycle, vehicle_mass_kg=args.mass)

    log_f = open(args.log, "w", newline="")
    log_f.write("t_wall,v_ref,v_actual,SOC,V_batt,V_fc,I_fc,V_bus,"
                "P_dem,P_fc,P_batt,power_share,share_actual,"
                "feasible,soc_clamped,solve_ms,mode,fault_flags\n")

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind((PI_LISTEN_IP, TEENSY_TX_PORT))
    rx.settimeout(UDP_POLL_TIMEOUT)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    teensy_addr = (args.teensy_ip, TEENSY_RX_PORT)

    state = TeensyState()
    pkt_ctr = 0; last_rx = time.monotonic()*1000
    t_start = time.monotonic(); soc_low = False; soc_high = False
    running = [True]
    signal.signal(signal.SIGINT,  lambda s,f: running.__setitem__(0,False))
    signal.signal(signal.SIGTERM, lambda s,f: running.__setitem__(0,False))
    logger.info("SDP EMS running at %d Hz -- Ctrl+C to stop", CONTROL_HZ)

    while running[0]:
        t_loop = time.monotonic()
        try:
            data,_ = rx.recvfrom(128)
            p = parse_telemetry(data)
            if p:
                gap = (p.pkt_counter - state.pkt_counter) & 0xFFFF
                if gap > 1: logger.warning("Dropped %d packets", gap-1)
                state = p; last_rx = state.received_at_ms
        except socket.timeout: pass

        stale = (time.monotonic()*1000 - last_rx) > TEENSY_TIMEOUT_MS
        v_ref, P_dem, done = dc.current()
        if done: break

        soc = state.SOC
        if soc < SOC_LOW_ENTER:   soc_low  = True
        elif soc > SOC_LOW_EXIT:  soc_low  = False
        if soc > SOC_HIGH_ENTER:  soc_high = True
        elif soc < SOC_HIGH_EXIT: soc_high = False

        if stale or state.fault_flags:
            mode = MODE_SAFE; result = SDPResult(power_share=0.5)
        elif soc_low:
            mode = MODE_FC_ONLY; P_fc = min(P_dem, P_FC_MAX)
            result = SDPResult(P_fc_optimal=P_fc, P_batt_optimal=P_dem-P_fc, power_share=1.0, feasible=True)
        elif soc_high:
            mode = MODE_BATT
            result = SDPResult(P_fc_optimal=0.0, P_batt_optimal=P_dem, power_share=0.0, feasible=True)
        else:
            mode = MODE_HYBRID; result = ctrl.step(P_dem=P_dem, SOC=soc)

        pkt = build_cmd_packet(pkt_ctr, v_ref, result.power_share, 0.0, mode, mode==MODE_HYBRID)
        tx.sendto(pkt, teensy_addr)
        pkt_ctr = (pkt_ctr+1) & 0xFFFF

        t_wall = time.monotonic()-t_start
        log_f.write(f"{t_wall:.3f},{v_ref:.3f},{state.v_actual:.3f},{soc:.4f},"
                    f"{state.V_batt:.3f},{state.V_fc:.3f},{state.I_fc:.4f},{state.V_bus:.3f},"
                    f"{P_dem:.2f},{result.P_fc_optimal:.2f},{result.P_batt_optimal:.2f},"
                    f"{result.power_share:.4f},{state.share_actual:.4f},"
                    f"{int(result.feasible)},{int(result.soc_clamped)},"
                    f"{result.solve_time_ms:.4f},{mode},{state.fault_flags}\n")
        log_f.flush()

        if pkt_ctr % 100 == 0:
            logger.info("t=%.1fs SOC=%.3f Vb=%.2fV P_dem=%.1f P_fc=%.1f share=%.2f solve=%.2fms mode=%d",
                        t_wall, soc, state.V_batt, P_dem, result.P_fc_optimal,
                        result.power_share, result.solve_time_ms, mode)

        sleep_t = CONTROL_PERIOD-(time.monotonic()-t_loop)
        if sleep_t > 0: time.sleep(sleep_t)

    tx.sendto(build_cmd_packet(pkt_ctr, 0.0, 0.5, 0.0, MODE_SAFE, False), teensy_addr)
    rx.close(); tx.close(); log_f.close()
    logger.info("Shutdown complete -- log: %s", args.log)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cost_j",      default="CostToGo_J_scaled_2026-03-16A.mat")
    p.add_argument("--drive_cycle", default="drive_cycle.csv")
    p.add_argument("--teensy_ip",   default=TEENSY_IP)
    p.add_argument("--alpha",       type=float, default=ALPHA)
    p.add_argument("--mass",        type=float, default=5.0)
    p.add_argument("--q_ah",        type=float, default=Q_AH)
    p.add_argument("--log",         default="sdp_log.csv")
    args = p.parse_args()
    TEENSY_IP = args.teensy_ip; Q_AH = args.q_ah
    run(args)

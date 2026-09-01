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
    python3 sdp_ems_standalone.py --cost_j CostToGo_J_scaled.mat 
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
try:
    from scipy import io as scipy_io
except ImportError:
    scipy_io = None

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
# IMPORTANT: these must match the parameters used to compute CostToGo_J_scaled.mat
SOC_MIN      = 0.30
SOC_MAX      = 0.80
SOC_BINS     = 250
SOC_REF      = 0.55      # SDP penalty center (midpoint of trained range)

PDEM_MIN     = -54.0     # W  max regenerative / charge power at bus
PDEM_MAX     = 150.0     # W  motor peak power
PDEM_BINS    = 50

P_FC_MAX     =  24.0     # W  H-20 peak (rated 20W; allow 24W short-term)
P_BATT_MAX   = 125.0     # W  max battery discharge at 18V bus
P_BATT_MIN   = -54.0     # W  max battery charge (6.4A * 8.4V)

Em           =   7.4     # V  2S LiPo open-circuit voltage
Q_AH         =   8.0     # Ah battery capacity -- UPDATE to match your actual pack
ETA_FC       =   0.40    # H-20 system efficiency at full power (datasheet: 40%)
Q_LHV_H2    = 120_000   # J/g hydrogen lower heating value
GAMMA        =   0.95    # discount factor
ALPHA        = 500       # SOC penalty weight (increase to 5000 for more FC use)
U_STEPS      = 50

# SOC guard thresholds with hysteresis (inside SDP trained range [0.30, 0.80])
SOC_LOW_ENTER  = 0.32
SOC_LOW_EXIT   = 0.35
SOC_HIGH_ENTER = 0.78
SOC_HIGH_EXIT  = 0.75

# ── UDP network config ─────────────────────────────────────────────────────────
TEENSY_IP       = "192.168.1.50"
PI_LISTEN_IP    = "0.0.0.0"
TEENSY_TX_PORT  = 5000    # Teensy sends telemetry to this port on Pi
TEENSY_RX_PORT  = 5001    # Teensy listens for commands on this port
UDP_POLL_TIMEOUT = 0.005  # s  non-blocking poll

TEENSY_TIMEOUT_MS = 200   # ms -- Pi freezes EMS if no Teensy packet
CONTROL_HZ        = 20
CONTROL_PERIOD    = 1.0 / CONTROL_HZ

# ── Packet format ──────────────────────────────────────────────────────────────
# Teensy -> Pi telemetry: 54 bytes
# header(B1) + timestamp_ms(I4) + pkt_counter(H2) +
# v_actual(f4) + V_batt(f4) + I_batt(f4) + I_charge(f4) +
# V_fc(f4) + I_fc(f4) + V_bus(f4) + P_motor(f4) +
# share_echo(f4) + share_actual(f4) +
# droop_FC(H2) + droop_BT(H2) +
# charger_status(B1) + fault_flags(B1) + checksum(B1)
T2P_FMT  = "<BIH" + "f" * 10 + "HHBBB"
T2P_SIZE = struct.calcsize(T2P_FMT)
assert T2P_SIZE == 54, f"T2P size={T2P_SIZE}, expected 54 -- check packet format"

# Pi -> Teensy commands: 22 bytes
# header(B1) + timestamp_ms(I4) + pkt_counter(H2) +
# v_setpoint(f4) + power_share(f4) + charge_goal(f4) +
# mode_cmd(B1) + droop_enable(B1) + checksum(B1)
P2T_FMT  = "<BIHfffBBB"
P2T_SIZE = struct.calcsize(P2T_FMT)
assert P2T_SIZE == 22, f"P2T size={P2T_SIZE}, expected 22 -- check packet format"

TEENSY_HEADER = 0xAA
PI_HEADER     = 0xBB

MODE_HYBRID  = 0
MODE_FC_ONLY = 1
MODE_BATT    = 2
MODE_CHARGE  = 3
MODE_SAFE    = 4


# ── Data structures ────────────────────────────────────────────────────────────
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
        """
        Estimate SOC from V_batt for a 2S LiPo.
        Replace this lookup with a Coulomb counter if available on Teensy.
        """
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


# ── SDP Controller ─────────────────────────────────────────────────────────────
class SDPController:
    """
    Online SDP policy lookup.
    Loads CostToGo_J_scaled.mat at startup; step() is O(U_STEPS) per call.
    Typical solve time: ~0.15 ms on Pi 5 -- well within 50 ms budget.
    """

    def __init__(self, cost_to_go_path: str, alpha: float = ALPHA):
        path = Path(cost_to_go_path)
        if not path.exists():
            raise FileNotFoundError(f"Cost-to-go file not found: {path}")

        if scipy_io is None:
            raise ImportError(
                "scipy is required to load MATLAB .mat cost-to-go files. "
                "Install it with: pip install scipy numpy --break-system-packages"
            )

        mat = scipy_io.loadmat(str(path))
        if "cost_J" not in mat:
            raise KeyError(
                f"Expected 'cost_J' in {path.name}. "
                f"Found: {[k for k in mat if not k.startswith('_')]}"
            )

        self.J         = mat["cost_J"].astype(np.float64)
        self.soc_grid  = np.linspace(SOC_MIN,  SOC_MAX,  SOC_BINS)
        self.pdem_grid = np.linspace(PDEM_MIN, PDEM_MAX, PDEM_BINS)
        self.u_grid    = np.linspace(0, P_FC_MAX, U_STEPS)
        self.alpha     = alpha

        if self.J.shape != (SOC_BINS, PDEM_BINS):
            raise ValueError(
                f"J shape {self.J.shape} != expected ({SOC_BINS}, {PDEM_BINS}). "
                f"Use CostToGo_J_scaled.mat (real H-20 hardware params)."
            )

        logger.info(
            "SDPController ready | J=%s | inf_entries=%d | "
            "P_FC_MAX=%.0fW | P_BATT=[%.0f,%.0fW] | SOC=[%.2f,%.2f] | alpha=%.0f",
            self.J.shape, int(np.isinf(self.J).sum()),
            P_FC_MAX, P_BATT_MIN, P_BATT_MAX, SOC_MIN, SOC_MAX, self.alpha,
        )

    def step(self, P_dem: float, SOC: float) -> SDPResult:
        t0 = time.perf_counter()

        soc_clamped = SOC < SOC_MIN or SOC > SOC_MAX
        if soc_clamped:
            logger.warning("SOC=%.4f outside [%.2f,%.2f] -- clamping", SOC, SOC_MIN, SOC_MAX)
            SOC = float(np.clip(SOC, SOC_MIN, SOC_MAX))

        P_dem_c = float(np.clip(P_dem, PDEM_MIN, PDEM_MAX))
        pd_idx  = int(np.argmin(np.abs(self.pdem_grid - P_dem_c)))

        # Vectorised over all FC power candidates
        P_batt   = P_dem - self.u_grid
        SOC_next = SOC - (P_batt / Em) / (3600.0 * Q_AH)

        feasible = (
            (P_batt  >= P_BATT_MIN) & (P_batt  <= P_BATT_MAX) &
            (SOC_next >= SOC_MIN)   & (SOC_next <= SOC_MAX)
        )

        if not feasible.any():
            logger.warning(
                "No feasible action: P_dem=%.1fW SOC=%.4f -> battery-only fallback",
                P_dem, SOC,
            )
            return SDPResult(
                P_fc_optimal=0.0, P_batt_optimal=P_dem, power_share=0.0,
                feasible=False, soc_clamped=soc_clamped,
                solve_time_ms=(time.perf_counter() - t0) * 1000,
            )

        idx     = np.where(feasible)[0]
        u_f     = self.u_grid[idx]
        sn_f    = SOC_next[idx]
        nsi     = np.array([int(np.argmin(np.abs(self.soc_grid - s))) for s in sn_f])
        fut     = self.J[nsi, pd_idx]
        W_H2    = u_f / (ETA_FC * Q_LHV_H2)
        soc_pen = self.alpha * np.abs(sn_f - SOC_REF)
        costs   = np.where(np.isinf(fut), np.inf, W_H2 + soc_pen + GAMMA * fut)

        bi = int(np.argmin(costs))
        if np.isinf(costs[bi]):
            logger.warning("All feasible actions have inf future cost -> battery-only fallback")
            return SDPResult(
                P_fc_optimal=0.0, P_batt_optimal=P_dem, power_share=0.0,
                feasible=False, soc_clamped=soc_clamped,
                solve_time_ms=(time.perf_counter() - t0) * 1000,
            )

        P_fc  = float(u_f[bi])
        share = float(np.clip(P_fc / max(abs(P_dem), 1.0), 0.0, 1.0))

        return SDPResult(
            P_fc_optimal=P_fc, P_batt_optimal=P_dem - P_fc,
            power_share=share, feasible=True, soc_clamped=soc_clamped,
            solve_time_ms=(time.perf_counter() - t0) * 1000,
        )


# ── Drive cycle ─────────────────────────────────────────────────────────────────
class DriveCycle:
    def __init__(self, csv_path: str, vehicle_mass_kg: float = 5.0):
        self.mass = vehicle_mass_kg
        self._load(csv_path)
        self._start = time.monotonic()
        logger.info("Drive cycle: %s | duration=%.1fs | v_max=%.2f m/s",
                    csv_path, self.times[-1], self.speeds.max())

    def _load(self, path: str):
        t, v = [], []
        with open(path) as f:
            for row in csv.DictReader(f):
                t.append(float(row["time_s"]))
                v.append(float(row["v_mps"]))
        self.times  = np.array(t)
        self.speeds = np.array(v)

    def current(self):
        """Returns (v_ref_mps, P_demand_W, done_bool)."""
        t = time.monotonic() - self._start
        if t >= self.times[-1]:
            return 0.0, 0.0, True
        i   = max(1, min(int(np.searchsorted(self.times, t)), len(self.times) - 1))
        a   = (t - self.times[i-1]) / max(self.times[i] - self.times[i-1], 1e-9)
        v   = float(self.speeds[i-1] + a * (self.speeds[i] - self.speeds[i-1]))
        dt  = max(self.times[i] - self.times[i-1], 0.02)
        acc = (self.speeds[i] - self.speeds[i-1]) / dt
        P   = float(np.clip(self.mass * v * acc, PDEM_MIN, PDEM_MAX))
        return v, P, False


# ── UDP helpers ────────────────────────────────────────────────────────────────
def _xor(data: bytes) -> int:
    r = 0
    for b in data: r ^= b
    return r

def build_cmd_packet(pkt_ctr, v_sp, power_share, charge_goal, mode, droop_en):
    ts = int(time.monotonic() * 1000) & 0xFFFFFFFF
    payload = struct.pack("<BIHfffBB",
        PI_HEADER, ts, pkt_ctr & 0xFFFF,
        float(v_sp), float(power_share), float(charge_goal),
        int(mode), int(droop_en),
    )
    return payload + struct.pack("B", _xor(payload[1:]))

def parse_telemetry(data: bytes) -> Optional[TeensyState]:
    if len(data) < T2P_SIZE:
        return None
    for s in range(len(data) - T2P_SIZE + 1):
        if data[s] != TEENSY_HEADER:
            continue
        chunk = data[s:s + T2P_SIZE]
        if _xor(chunk[1:-1]) != chunk[-1]:
            logger.debug("Checksum mismatch")
            continue
        try:
            (_, ts, ctr,
             v, Vb, Ib, Ic, Vfc, Ifc, Vbus, Pmot, she, sha,
             dFC, dBT, chg, flt, _) = struct.unpack(T2P_FMT, chunk)
        except struct.error:
            continue
        return TeensyState(
            timestamp_ms=ts, pkt_counter=ctr,
            v_actual=v, V_batt=Vb, I_batt=Ib, I_charge=Ic,
            V_fc=Vfc, I_fc=Ifc, V_bus=Vbus, P_motor=Pmot,
            share_echo=she, share_actual=sha,
            droop_FC=dFC, droop_BT=dBT,
            charger_status=chg, fault_flags=flt,
            received_at_ms=time.monotonic() * 1000,
        )
    return None


# ── Data logger ────────────────────────────────────────────────────────────────
class DataLogger:
    HEADER = (
        "t_wall,v_ref,v_actual,SOC,V_batt,V_fc,I_fc,V_bus,"
        "P_dem,P_fc,P_batt,power_share,share_actual,"
        "feasible,soc_clamped,solve_ms,mode,fault_flags\n"
    )

    def __init__(self, path="sdp_log.csv"):
        self.f = open(path, "w", newline="")
        self.f.write(self.HEADER)
        logger.info("Data log -> %s", path)

    def write(self, t_wall, v_ref, st: TeensyState, res: SDPResult, P_dem, mode):
        self.f.write(
            f"{t_wall:.3f},{v_ref:.3f},{st.v_actual:.3f},{st.SOC:.4f},"
            f"{st.V_batt:.3f},{st.V_fc:.3f},{st.I_fc:.4f},{st.V_bus:.3f},"
            f"{P_dem:.2f},{res.P_fc_optimal:.2f},{res.P_batt_optimal:.2f},"
            f"{res.power_share:.4f},{st.share_actual:.4f},"
            f"{int(res.feasible)},{int(res.soc_clamped)},"
            f"{res.solve_time_ms:.4f},{mode},{st.fault_flags}\n"
        )
        self.f.flush()

    def close(self):
        self.f.close()


# ── Main control loop ──────────────────────────────────────────────────────────
def run(args):
    ctrl = SDPController(args.cost_j, alpha=args.alpha)
    dc   = DriveCycle(args.drive_cycle, vehicle_mass_kg=args.mass)
    dlog = DataLogger(args.log)

    # UDP sockets
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind((PI_LISTEN_IP, TEENSY_TX_PORT))
    rx.settimeout(UDP_POLL_TIMEOUT)

    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    teensy_addr = (args.teensy_ip, TEENSY_RX_PORT)
    logger.info("UDP rx=:%d  tx=%s:%d", TEENSY_TX_PORT, *teensy_addr)

    state     = TeensyState()
    pkt_ctr   = 0
    last_rx   = time.monotonic() * 1000
    t_start   = time.monotonic()
    soc_low   = False
    soc_high  = False

    running = [True]
    def _stop(sig, frame): running[0] = False
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    logger.info("SDP EMS running at %d Hz -- Ctrl+C to stop", CONTROL_HZ)

    while running[0]:
        t_loop = time.monotonic()

        # 1. Receive telemetry
        try:
            data, _ = rx.recvfrom(128)
            parsed = parse_telemetry(data)
            if parsed:
                gap = (parsed.pkt_counter - state.pkt_counter) & 0xFFFF
                if gap > 1:
                    logger.warning("Dropped %d Teensy packets", gap - 1)
                state   = parsed
                last_rx = state.received_at_ms
        except socket.timeout:
            pass

        # 2. Staleness
        stale = (time.monotonic() * 1000 - last_rx) > TEENSY_TIMEOUT_MS
        if stale:
            logger.warning("Teensy stale (%.0f ms)", time.monotonic()*1000 - last_rx)

        # 3. Drive cycle
        v_ref, P_dem, done = dc.current()
        if done:
            logger.info("Drive cycle finished -- shutting down")
            break

        # 4. SOC hysteresis guards
        soc = state.SOC
        if soc < SOC_LOW_ENTER:   soc_low  = True
        elif soc > SOC_LOW_EXIT:  soc_low  = False
        if soc > SOC_HIGH_ENTER:  soc_high = True
        elif soc < SOC_HIGH_EXIT: soc_high = False

        # 5. Mode selection
        if stale or state.fault_flags:
            mode = MODE_SAFE
            if state.fault_flags:
                logger.warning("Fault 0x%02X -> SAFE mode", state.fault_flags)
            result = SDPResult(power_share=0.5)
        elif soc_low:
            mode   = MODE_FC_ONLY
            P_fc   = min(P_dem, P_FC_MAX)
            result = SDPResult(P_fc_optimal=P_fc, P_batt_optimal=P_dem-P_fc,
                               power_share=1.0, feasible=True)
        elif soc_high:
            mode   = MODE_BATT
            result = SDPResult(P_fc_optimal=0.0, P_batt_optimal=P_dem,
                               power_share=0.0, feasible=True)
        else:
            mode   = MODE_HYBRID
            result = ctrl.step(P_dem=P_dem, SOC=soc)

        # 6. Send command to Teensy
        pkt = build_cmd_packet(pkt_ctr, v_ref, result.power_share,
                                0.0, mode, mode == MODE_HYBRID)
        tx.sendto(pkt, teensy_addr)
        pkt_ctr = (pkt_ctr + 1) & 0xFFFF

        # 7. Log
        t_wall = time.monotonic() - t_start
        dlog.write(t_wall, v_ref, state, result, P_dem, mode)

        if pkt_ctr % 100 == 0:
            logger.info(
                "t=%.1fs v=%.2f/%.2f SOC=%.3f Vb=%.2fV Vfc=%.2fV "
                "P_dem=%.1f P_fc=%.1f share=%.2f solve=%.2fms mode=%d",
                t_wall, state.v_actual, v_ref, soc,
                state.V_batt, state.V_fc, P_dem,
                result.P_fc_optimal, result.power_share,
                result.solve_time_ms, mode,
            )

        # 8. Rate limit
        sleep_t = CONTROL_PERIOD - (time.monotonic() - t_loop)
        if sleep_t > 0:
            time.sleep(sleep_t)
        elif sleep_t < -0.005:
            logger.warning("Loop overrun %.1f ms", -sleep_t * 1000)

    # Shutdown: send SAFE command
    tx.sendto(build_cmd_packet(pkt_ctr, 0.0, 0.5, 0.0, MODE_SAFE, False), teensy_addr)
    rx.close(); tx.close(); dlog.close()
    logger.info("Shutdown complete -- log: %s", args.log)


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SDP EMS Standalone -- Pi 5 + Ethernet UDP")
    p.add_argument("--cost_j",      default="CostToGo_J_scaled.mat")
    p.add_argument("--drive_cycle", default="drive_cycle.csv")
    p.add_argument("--teensy_ip",   default=TEENSY_IP)
    p.add_argument("--alpha",       type=float, default=ALPHA,
                   help="SOC penalty weight (default 500; try 5000 for more FC use)")
    p.add_argument("--mass",        type=float, default=5.0,
                   help="Scaled vehicle mass kg (default 5.0)")
    p.add_argument("--q_ah",        type=float, default=Q_AH,
                   help=f"Battery capacity Ah (default {Q_AH} -- update for your pack)")
    p.add_argument("--log",         default="sdp_log.csv")
    args = p.parse_args()
    TEENSY_IP = args.teensy_ip
    Q_AH      = args.q_ah
    run(args)

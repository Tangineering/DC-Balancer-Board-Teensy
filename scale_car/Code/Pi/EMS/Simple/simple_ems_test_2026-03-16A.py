"""
simple_ems_test.py — Rule-Based EMS for Hardware Bring-Up
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-03-16A

PURPOSE:
    Test that Pi <-> Teensy UDP communication works end-to-end
    before deploying SDP. No matrices, no files to load, no scipy.
    Just SOC-based rules and a blinking heartbeat you can see on both sides.

RULES:
    SOC < 0.35  -> FC_ONLY   (power_share = 1.0)
    SOC > 0.75  -> BATT_ONLY (power_share = 0.0)
    Otherwise   -> HYBRID    (power_share scales linearly with SOC)
                   share = 1.0 - (SOC - 0.35) / (0.75 - 0.35)
                   i.e. more FC when SOC is low, more battery when SOC is high

WHAT TO CHECK DURING TEST:
    1. Pi terminal shows received V_batt, V_fc, V_bus, SOC each cycle
    2. power_share changes correctly as SOC changes
    3. No "Teensy stale" warnings when Teensy is running
    4. Ctrl+C sends SAFE mode and exits cleanly
    5. sdp_log_simple.csv is written and has data

Dependencies: none beyond Python stdlib
    (no scipy, no numpy, no pyserial needed)

Run:
    python3 simple_ems_test.py
    python3 simple_ems_test.py --teensy_ip 192.168.1.50  # default
    python3 simple_ems_test.py --hz 10                   # slower rate for debugging
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
from typing import Optional

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("simple_ems_test.log"),
    ],
)
logger = logging.getLogger(__name__)

# ── Network config ─────────────────────────────────────────────────────────────
TEENSY_IP      = "192.168.1.50"
PI_LISTEN_IP   = "0.0.0.0"
TEENSY_TX_PORT = 5000     # Teensy sends here
TEENSY_RX_PORT = 5001     # Teensy listens here
UDP_TIMEOUT    = 0.005    # s

# ── Timing ─────────────────────────────────────────────────────────────────────
CONTROL_HZ     = 20
TEENSY_STALE_MS = 500     # ms before we declare Teensy dead

# ── Packet format (must match Teensy firmware exactly) ─────────────────────────
# Teensy -> Pi: 54 bytes
T2P_FMT  = "<BIH" + "f" * 10 + "HHBBB"
T2P_SIZE = struct.calcsize(T2P_FMT)   # 54

# Pi -> Teensy: 22 bytes
P2T_FMT  = "<BIHfffBBB"
P2T_SIZE = struct.calcsize(P2T_FMT)   # 22

TEENSY_HEADER = 0xAA
PI_HEADER     = 0xBB

MODE_HYBRID  = 0
MODE_FC_ONLY = 1
MODE_BATT    = 2
MODE_SAFE    = 4

# ── SOC thresholds ─────────────────────────────────────────────────────────────
SOC_LOW   = 0.35    # below this -> FC only
SOC_HIGH  = 0.75    # above this -> battery only
# between 0.35 and 0.75 -> hybrid, FC share decreases linearly


# ── Helpers ────────────────────────────────────────────────────────────────────
def xor_checksum(data: bytes) -> int:
    r = 0
    for b in data:
        r ^= b
    return r

def soc_from_vbatt(v: float) -> float:
    """Simple 2S LiPo SOC lookup from voltage."""
    if v >= 8.40: return 1.00
    if v >= 8.10: return 0.90
    if v >= 7.80: return 0.75
    if v >= 7.60: return 0.60
    if v >= 7.40: return 0.50
    if v >= 7.20: return 0.35
    if v >= 7.00: return 0.20
    if v >= 6.60: return 0.10
    return 0.05

def compute_power_share(soc: float) -> tuple[float, int]:
    """
    Core EMS rule. Returns (power_share, mode).
    power_share: 0.0 = all battery, 1.0 = all FC
    """
    if soc < SOC_LOW:
        return 1.0, MODE_FC_ONLY
    elif soc > SOC_HIGH:
        return 0.0, MODE_BATT
    else:
        # Linear ramp: share=1.0 at SOC=SOC_LOW, share=0.0 at SOC=SOC_HIGH
        share = 1.0 - (soc - SOC_LOW) / (SOC_HIGH - SOC_LOW)
        return round(share, 3), MODE_HYBRID


# ── Packet builders ────────────────────────────────────────────────────────────
def build_cmd(pkt_ctr: int, v_sp: float, power_share: float,
              charge_goal: float, mode: int, droop_en: bool) -> bytes:
    ts = int(time.monotonic() * 1000) & 0xFFFFFFFF
    payload = struct.pack(
        "<BIHfffBB",
        PI_HEADER, ts, pkt_ctr & 0xFFFF,
        float(v_sp), float(power_share), float(charge_goal),
        int(mode), int(droop_en),
    )
    return payload + struct.pack("B", xor_checksum(payload[1:]))


def parse_telemetry(data: bytes):
    """Returns parsed fields dict or None on failure."""
    if len(data) < T2P_SIZE:
        return None
    for s in range(len(data) - T2P_SIZE + 1):
        if data[s] != TEENSY_HEADER:
            continue
        chunk = data[s:s + T2P_SIZE]
        if xor_checksum(chunk[1:-1]) != chunk[-1]:
            logger.debug("Checksum mismatch")
            continue
        try:
            (_, ts, ctr,
             v, Vb, Ib, Ic, Vfc, Ifc, Vbus, Pmot, she, sha,
             dFC, dBT, chg, flt, _) = struct.unpack(T2P_FMT, chunk)
        except struct.error:
            continue
        return dict(
            ts=ts, ctr=ctr,
            v_actual=v,
            V_batt=Vb, I_batt=Ib, I_charge=Ic,
            V_fc=Vfc, I_fc=Ifc,
            V_bus=Vbus, P_motor=Pmot,
            share_echo=she, share_actual=sha,
            droop_FC=dFC, droop_BT=dBT,
            charger=chg, faults=flt,
        )
    return None


# ── Main loop ──────────────────────────────────────────────────────────────────
def run(args):
    control_period = 1.0 / args.hz

    # Open UDP sockets
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind((PI_LISTEN_IP, TEENSY_TX_PORT))
    rx.settimeout(UDP_TIMEOUT)

    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    teensy_addr = (args.teensy_ip, TEENSY_RX_PORT)

    logger.info("=" * 60)
    logger.info("Simple EMS Test | %d Hz | Teensy=%s", args.hz, args.teensy_ip)
    logger.info("Waiting for first Teensy packet on port %d...", TEENSY_TX_PORT)
    logger.info("=" * 60)

    # CSV log
    log_f = open(args.log, "w", newline="")
    log_w = csv.writer(log_f)
    log_w.writerow([
        "t_wall", "v_actual",
        "V_batt", "V_fc", "I_fc", "V_bus",
        "SOC", "power_share", "mode",
        "share_echo", "faults", "pkt_ctr"
    ])

    pkt_ctr   = 0
    last_rx   = time.monotonic() * 1000
    t_start   = time.monotonic()
    last_state = {}
    step_count = 0
    dropped    = 0

    running = [True]
    def _stop(sig, frame):
        running[0] = False
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running[0]:
        t_loop = time.monotonic()

        # ── 1. Receive ────────────────────────────────────────────────────────
        try:
            data, addr = rx.recvfrom(128)
            state = parse_telemetry(data)
            if state:
                gap = (state["ctr"] - last_state.get("ctr", state["ctr"])) & 0xFFFF
                if gap > 1 and last_state:
                    dropped += gap - 1
                    logger.warning("Dropped %d packets (total dropped: %d)", gap-1, dropped)
                last_state = state
                last_rx    = time.monotonic() * 1000
        except socket.timeout:
            pass

        # ── 2. Staleness check ────────────────────────────────────────────────
        stale_ms = time.monotonic() * 1000 - last_rx
        stale    = stale_ms > TEENSY_STALE_MS

        if stale and step_count > 0:
            logger.warning("No Teensy packet for %.0f ms -> SAFE mode", stale_ms)

        # ── 3. EMS decision ───────────────────────────────────────────────────
        if not last_state or stale:
            power_share = 0.5
            mode        = MODE_SAFE
            soc         = 0.0
        elif last_state["faults"] != 0:
            power_share = 0.0
            mode        = MODE_SAFE
            soc         = soc_from_vbatt(last_state["V_batt"])
            logger.warning("Fault flags=0x%02X -> SAFE", last_state["faults"])
        else:
            soc         = soc_from_vbatt(last_state["V_batt"])
            power_share, mode = compute_power_share(soc)

        # ── 4. Send command ───────────────────────────────────────────────────
        pkt = build_cmd(
            pkt_ctr    = pkt_ctr,
            v_sp       = 0.0,          # no drive cycle in this test
            power_share= power_share,
            charge_goal= 0.0,
            mode       = mode,
            droop_en   = (mode == MODE_HYBRID),
        )
        tx.sendto(pkt, teensy_addr)
        pkt_ctr = (pkt_ctr + 1) & 0xFFFF

        # ── 5. Log to CSV ─────────────────────────────────────────────────────
        t_wall = time.monotonic() - t_start
        if last_state:
            log_w.writerow([
                f"{t_wall:.3f}",
                f"{last_state['v_actual']:.3f}",
                f"{last_state['V_batt']:.3f}",
                f"{last_state['V_fc']:.3f}",
                f"{last_state['I_fc']:.4f}",
                f"{last_state['V_bus']:.3f}",
                f"{soc:.3f}",
                f"{power_share:.3f}",
                mode,
                f"{last_state['share_echo']:.3f}",
                last_state["faults"],
                last_state["ctr"],
            ])
            log_f.flush()

        # ── 6. Console printout every second ─────────────────────────────────
        step_count += 1
        if step_count % args.hz == 0:
            if last_state:
                mode_str = {
                    MODE_HYBRID:  "HYBRID  ",
                    MODE_FC_ONLY: "FC_ONLY ",
                    MODE_BATT:    "BATT    ",
                    MODE_SAFE:    "SAFE    ",
                }.get(mode, f"MODE_{mode} ")

                print(
                    f"\n[t={t_wall:6.1f}s] "
                    f"V_batt={last_state['V_batt']:.2f}V  "
                    f"V_fc={last_state['V_fc']:.2f}V  "
                    f"I_fc={last_state['I_fc']:.3f}A  "
                    f"V_bus={last_state['V_bus']:.2f}V"
                )
                print(
                    f"            "
                    f"SOC={soc:.3f}  "
                    f"power_share={power_share:.3f}  "
                    f"mode={mode_str}  "
                    f"faults=0x{last_state['faults']:02X}  "
                    f"dropped={dropped}"
                )
                print(
                    f"            "
                    f"share_echo={last_state['share_echo']:.3f}  "
                    f"share_actual={last_state['share_actual']:.3f}  "
                    f"pkt_ctr={last_state['ctr']}"
                )
            else:
                print(f"[t={t_wall:6.1f}s] Waiting for Teensy... "
                      f"(sent {pkt_ctr} cmds, nothing received yet)")

        # ── 7. Rate limit ─────────────────────────────────────────────────────
        elapsed = time.monotonic() - t_loop
        sleep_t = control_period - elapsed
        if sleep_t > 0:
            time.sleep(sleep_t)
        elif sleep_t < -0.003:
            logger.warning("Loop overrun %.1f ms", -sleep_t * 1000)

    # ── Shutdown ───────────────────────────────────────────────────────────────
    print("\nShutting down -- sending SAFE command...")
    safe = build_cmd(pkt_ctr, 0.0, 0.0, 0.0, MODE_SAFE, False)
    tx.sendto(safe, teensy_addr)
    time.sleep(0.1)
    rx.close()
    tx.close()
    log_f.close()
    logger.info("Done. %d steps, %d dropped packets. Log: %s",
                step_count, dropped, args.log)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Simple Rule-Based EMS -- Hardware Bring-Up Test")
    p.add_argument("--teensy_ip", default=TEENSY_IP,
                   help=f"Teensy IP address (default {TEENSY_IP})")
    p.add_argument("--hz",        type=int, default=CONTROL_HZ,
                   help=f"Control loop rate Hz (default {CONTROL_HZ}; use 5 for slow debug)")
    p.add_argument("--log",       default="simple_ems_test.csv",
                   help="Output CSV log file")
    args = p.parse_args()
    run(args)

#!/usr/bin/env python3
"""
hil_plant_sim.py — soft-real-time plant simulator for the Teensy HIL mode (fw v21).

The real Teensy, flashed with -DHIL_SIM=1 -DUSE_ETHERNET=1, is the device under
test.  This script is the PLANT: it integrates a simple mechanical + electrical
model of the scale-car balancer rig, injects the resulting sensor values into the
board over UDP as engineering units, and reads back the board's actuator state
(state machine, ideal-diode switch bitmask, motor-current command, droop MDAC
codes, fault flags) to close the loop.

Nothing about the firmware's control logic is stubbed: detectFaults(), the
sequencing guards, the Youla drive controller and the power-share loop all run
unmodified on the injected values.  That makes this a fault-INJECTION rig — the
`sag` scenario, for instance, exercises the real undervoltage path.

Wire protocol (mirrored from teensy_controller.ino, fw v21 — keep in lockstep):

  Injection frame (host -> Teensy), 40 bytes, little-endian
    0  u8    sync 0xB5
    1  u8    seq (wraps)
    2  f32   V_fc      [V]
    6  f32   V_batt    [V]
   10  f32   V_bus     [V]
   14  f32   V_chg     [V]
   18  f32   V_rgn     [V]
   22  f32   I_fc      [A]
   26  f32   I_batt    [A]
   30  f32   v_actual  [m/s]
   34  f32   I_charge  [A]  simulated Ag105 reg 0x06 reading, already in amps
   38  u8    ag105_status  raw Table 6 status byte
   39  u8    XOR checksum over bytes 1..38

  (The 35-byte fw v21 layout is RETIRED — it was never flashed.  A 35-byte frame
  no longer matches the firmware's length dispatch and is dropped unread, so an
  old simulator against a new flash shows accepts stuck at zero.)

  Observation frame (Teensy -> host), 16 bytes, little-endian
    0  u8    sync 0xB6
    1  u8    seq echo (last accepted injection seq)
    2  u8    mainState
    3  u8    switch_state bitmask (see SW_* below)
    4  u8    aux: bit0 FC_REG_ENABLE, bit1 BT_REG_ENABLE,
                  bit2 MPPT_DISABLE,  bit3 CBAL_DISABLE
    5  f32   current [A] (post-clamp motor-current command)
    9  u16   last MDAC word, FC channel
   11  u16   last MDAC word, BT channel
   13  u16   fault_flags
   15  u8    XOR checksum over bytes 1..14

Stdlib only — socket, struct, time, argparse, csv.  No numpy.

Usage:
    python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 --scenario steady \
            --duration 30 --csv hil_run.csv

REPLAY MODE (--replay PATH.BLG) swaps the simulated plant for a recorded bench
log: the .BLG's rail/current/velocity samples are streamed back at the board as
injection frames, turning a recorded bench incident into a repeatable stimulus.
The plant integrator is BYPASSED — replay is OPEN LOOP, the firmware's commands
do not influence the replayed trajectory.  See docs/HIL_MODE.md "Replay mode".
"""

import argparse
import csv
import json
import os
import socket
import struct
import sys
import time

# ─────────────────────────────────────────────────────────────────────────────
# Protocol constants — must match teensy_controller.ino (fw v21)
# ─────────────────────────────────────────────────────────────────────────────
HIL_SYNC_INJECT = 0xB5
HIL_SYNC_OUTPUT = 0xB6
HIL_INJECT_SIZE = 40
HIL_OUTPUT_SIZE = 16

TEENSY_PORT_DEFAULT = 5001          # local_port in the .ino

SW_FC_BUS, SW_BT_BUS, SW_MOT_PWR = 0x01, 0x02, 0x04
SW_REGEN, SW_FC_CHARGE, SW_BT_SEQ = 0x08, 0x10, 0x20

AUX_FC_REG, AUX_BT_REG = 0x01, 0x02
AUX_MPPT_DISABLE, AUX_CBAL_DISABLE = 0x04, 0x08

# ─────────────────────────────────────────────────────────────────────────────
# Ag105 Table 6 status byte — authoritative values from
# references/Datasheets/Ag105_Table6_I2C_Status_Byte.json (Ag105 DS V1.1, Table 6).
# Bits 0-2 are the GENSTAT enum; bits 3-7 are independent flags.
# ─────────────────────────────────────────────────────────────────────────────
AG105_ST_DISCONNECT = 0x00      # GENSTAT 000 — Battery Disconnect
AG105_ST_LOW_POWER = 0x01       # GENSTAT 001 — Low Power
AG105_ST_CHARGING = 0x02        # GENSTAT 010 — Charging
AG105_ST_FULL = 0x03            # GENSTAT 011 — Fully Charged
AG105_ST_BRINGUP = 0x04         # GENSTAT 100 — Bring-Up Charge
AG105_ST_OC_ERR = 0x05          # GENSTAT 101 — OC/Regulation Error
AG105_ST_THERMAL_SD = 0x06      # GENSTAT 110 — Thermal Shutdown
AG105_ST_TIMEOUT_ERR = 0x07     # GENSTAT 111 — Timeout Error
AG105_FLAG_MPPT_EN = 0x08       # bit 3 — MPPT enabled
AG105_FLAG_PWR_TRACK = 0x10     # bit 4 — charge profile tracking input power
AG105_FLAG_CV = 0x20            # bit 5 — constant-voltage mode
AG105_FLAG_CC = 0x40            # bit 6 — constant-current mode
AG105_FLAG_THERM_LIM = 0x80     # bit 7 — thermal limiting

# Charger model.  The firmware configures the Ag105 for the 2.5 A profile
# (reg 0x00 = 0x01, Ag105_Table4_Charge_Current_Select.json) into a 2S/8.4 V pack.
AG105_I_MAX = 2.5            # A     configured charge-current ceiling
AG105_SETTLE_S = 0.5         # s     matches AG105_SETTLE_MS in the .ino
AG105_TAU_S = 0.4            # s     first-order ramp of the measured current
AG105_V_IN_MIN = 8.0         # V     input rail below which the module cannot charge

# MDAC word format (AD5443): control nibble 0x1 = load-and-update, then a 12-bit code.
MDAC_CMD_LOAD_UPDATE = 0x1000
MDAC_RES = 4095

# ─────────────────────────────────────────────────────────────────────────────
# Calibrated plant constants.
#
# Mechanical: from the fw v14 K_F force-axis correction — see
# controller_design_MIMO/calibration/motor_id_20260815.md and CLAUDE.md's
# fw v14 addendum.  m_eff was confirmed at 3.5 kg by that same round.
# ─────────────────────────────────────────────────────────────────────────────
M_EFF = 3.5          # kg      effective translational mass at the flywheel rim
K_F = 0.7538         # N/A     motor current -> tractive force (PHI 6.86, r_tire 0.033 m)
F_COULOMB = 2.00     # N       thermal Coulomb friction (2.00 +/- 0.42 N)
B_EFF = 0.534        # N*s/m   viscous drag
V_STICTION = 0.02    # m/s     |v| below which the Coulomb term is treated as static

# Electrical.  V_BUS_NOMINAL and the rails below are the .ino's own constants
# (V_BUS_NOMINAL 16.0f; LIMIT_V_BUS_MIN 12.0f; LIMIT_V_BATT_MIN 6.2f; 2S pack
# 7.4-8.4 V; the H-20 fuel cell is a ~13 V-class source with LIMIT_V_FC_MIN 6.0f).
V_BUS_NOMINAL = 16.0     # V   the firmware's own constant; kept for reference

# ── MEASURED bus droop ──────────────────────────────────────────────────────
# Fit of V_bus against I_fc + I_batt over quasi-steady 200 ms blocks of TP0170-0180
# (TP0178 EXCLUDED — that is the handoff-sag log, not a steady operating point),
# ML0165 and ML0169, all fw v16.  Two clearly separated regimes:
#     both sources live   0.0740 +/- 0.004 V/A
#     exactly one live    0.1615 +/- 0.001 V/A   (FC and BT symmetric within 2 %)
# with no-load intercepts landing in 15.943-15.957 V, hence V_BUS_DROOP_V0 = 15.95
# rather than the firmware's nominal 16.0 (which stays above, for reference).
#
# OPEN FINDING, deliberately not hidden: the realized droop is ~4x BELOW the MDAC
# droop-chain design value.  The design predicts R_e = RE_MAX*g = 2.014*0.298
# = 0.60 ohm per channel, i.e. 0.30 V/A with both channels sharing — four times the
# measured 0.074 V/A.  Nothing in the repo explains the discrepancy yet; the hi-fi
# electrical engine (hil_electrical.py) reproduces the DESIGN value by construction,
# so running the same scenario in both modes shows the gap directly.
K_DROOP_BUS_SHARED = 0.074   # V/A  both sources live
K_DROOP_BUS_SINGLE = 0.16    # V/A  exactly one source live
V_BUS_DROOP_V0 = 15.95       # V    measured no-load intercept
# Back-compatible alias: the shared-source value is the common case.
K_DROOP_BUS = K_DROOP_BUS_SHARED

ETA_BOOST = 0.85         # boost-stage efficiency, motor draw -> bus current
I_AUX_A = 0.15           # A     fixed housekeeping load on the bus
C_BUS_F = 470e-6         # F     bus bulk capacitance (decay when no source is closed)
R_BUS_BLEED = 2000.0     # ohm   effective bleed across that capacitance

# ── Source models ───────────────────────────────────────────────────────────
# The fuel-cell polarization model and the battery SOC/OCV model live in
# hil_electrical.py (SOURCE MODELS block) so BOTH electrical modes share one
# instance of each.  See docs/HIL_PLANT.md "Source models".
# (path insert so `python3 tools/hil_plant_sim.py` from the repo root and
#  `from hil_plant_sim import SCENARIOS` from a sibling both resolve the module.)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hil_electrical import (                                   # noqa: E402
    BatterySource, FuelCellSource, ElectricalSim, NoiseConfig,
    BATT_CAPACITY_AH, C_VESC_DEFAULT,
)


def xor_checksum(payload: bytes) -> int:
    """XOR over the given bytes (callers pass the span between sync and checksum)."""
    c = 0
    for b in payload:
        c ^= b
    return c


def pack_inject(seq, v_fc, v_batt, v_bus, v_chg, v_rgn, i_fc, i_batt, v_actual,
                i_charge=0.0, ag105_status=AG105_ST_DISCONNECT) -> bytes:
    body = struct.pack(
        "<B9fB", seq & 0xFF, v_fc, v_batt, v_bus, v_chg, v_rgn, i_fc, i_batt, v_actual,
        i_charge, ag105_status & 0xFF,
    )
    return bytes([HIL_SYNC_INJECT]) + body + bytes([xor_checksum(body)])


def parse_output(data: bytes):
    """Validate and decode a 16-byte observation frame; return a dict or None."""
    if len(data) != HIL_OUTPUT_SIZE or data[0] != HIL_SYNC_OUTPUT:
        return None
    if xor_checksum(data[1:HIL_OUTPUT_SIZE - 1]) != data[HIL_OUTPUT_SIZE - 1]:
        return None
    seq, state, sw, aux = data[1], data[2], data[3], data[4]
    (current,) = struct.unpack_from("<f", data, 5)
    mdac_fc, mdac_bt, faults = struct.unpack_from("<HHH", data, 9)
    return {
        "seq": seq,
        "state": state,
        "switch": sw,
        "aux": aux,
        "current": current,
        "mdac_fc": mdac_fc,
        "mdac_bt": mdac_bt,
        "fault_flags": faults,
    }


def mdac_fraction(word: int) -> float:
    """Recover the 0..1 droop-gain fraction from a raw AD5443 command word."""
    if (word & 0xF000) != MDAC_CMD_LOAD_UPDATE:
        return 0.0
    return (word & 0x0FFF) / float(MDAC_RES)


class Plant:
    """
    First-order plant model.

    Mechanical:
        m_eff * dv/dt = K_F*I_cmd - sign(v)*F_c - b_eff*v
      with a static-friction deadband around v = 0: below V_STICTION the Coulomb
      term opposes the applied force and cannot reverse the velocity within a tick,
      so the body simply stays put until |K_F*I| exceeds F_c.
      Motor force is developed only when MOT_PWR_ENABLE is closed AND the bus is up
      — a VESC with no bus makes no torque.

    Electrical (deliberately simple, and simplified in two places worth naming):
      * The bus is a single droop node: V_bus = V_BUS_NOMINAL - K_DROOP_BUS*I_total
        whenever at least one source is "live" (its ideal-diode bus switch closed AND
        its boost regulator enabled).  With no live source the node decays as an
        RC through R_BUS_BLEED*C_BUS_F.  This models neither the boost dynamics nor
        the RT1987 turn-on transient — HIL here is a controller/sequencing rig, not
        a converter simulator.
      * The FC/BT current split follows the ratio of the two droop MDAC codes.  The
        real split is set by the analog droop network's equivalent resistances, which
        the codes only parametrize; proportional-to-code is a SIMPLIFICATION that
        preserves the sign and monotonicity of the share loop's authority (raise the
        FC code, get more FC current) without claiming the true gain.
      * The Ag105 charger is modelled at the STATUS level only: input power in ->
        settle delay -> "Charging" with a first-order current ramp toward the 2.5 A
        configured ceiling.  There is no battery state of charge, no CV taper and no
        MPPT perturb-and-observe loop; MPPT_DISABLE only clears the tracking flags in
        the status byte.  The I2C transport and the config handshake are not modelled
        at all (the firmware skips them entirely under HIL).
    """

    def __init__(self, electrical=None, soc0=0.7, capacity_ah=BATT_CAPACITY_AH):
        self.v = 0.0          # m/s
        self.v_bus = 0.0      # V
        self.i_fc = 0.0
        self.i_batt = 0.0
        self.v_chg = 0.0
        self.v_rgn = 0.0
        self.i_aux = I_AUX_A
        self.v_bus_offset = 0.0   # scenario-injected bus disturbance [V]
        # ── Source models (shared by both electrical modes) ──────────────────
        # Plant OWNS the two source objects and hands them to the hi-fi engine, so
        # SOC and the fuel-cell double-layer state are integrated exactly once per
        # tick whichever mode is selected.
        self.battery = BatterySource(soc0=soc0, capacity_ah=capacity_ah)
        self.fuel_cell = FuelCellSource()
        # ── Optional high-fidelity electrical engine ────────────────────────
        self.electrical = electrical
        if electrical is not None:
            electrical.fuel_cell = self.fuel_cell
            electrical.battery = self.battery
        # ── Ag105 charger model state ───────────────────────────────────────
        self.i_charge = 0.0           # A   measured charge current (reg 0x06 equivalent)
        self.chg_powered_s = 0.0      # s   time the charger input has been continuously live
        self.chg_fault = False        # scenario-driven charger-input collapse
        # Scenario-driven extra draw on the V-MOT node, i.e. BEHIND MOT_PWR.  This is
        # NOT i_aux (which sits on VBUS): only a load behind the switch loads the
        # switch, which is the whole point of the `scp-inrush` margin case.
        self.i_mot_extra = 0.0
        self.ag105_status = AG105_ST_DISCONNECT

    def step(self, dt, obs):
        """Advance one tick against the last observation frame (None = actuators unknown)."""
        sw = obs["switch"] if obs else 0
        aux = obs["aux"] if obs else 0
        i_cmd = obs["current"] if obs else 0.0
        code_fc = mdac_fraction(obs["mdac_fc"]) if obs else 0.5
        code_bt = mdac_fraction(obs["mdac_bt"]) if obs else 0.5

        fc_live = bool(sw & SW_FC_BUS) and bool(aux & AUX_FC_REG)
        bt_live = bool(sw & SW_BT_BUS) and bool(aux & AUX_BT_REG)
        mot_live = bool(sw & SW_MOT_PWR)

        # ── Mechanical ───────────────────────────────────────────────────────
        bus_up = self.v_bus > 5.0
        f_drive = K_F * i_cmd if (mot_live and bus_up) else 0.0
        if abs(self.v) < V_STICTION:
            # Static-friction deadband: no breakaway until the drive force exceeds F_c.
            if abs(f_drive) <= F_COULOMB:
                f_net = 0.0
                self.v = 0.0
            else:
                f_net = f_drive - (F_COULOMB if f_drive > 0 else -F_COULOMB) - B_EFF * self.v
        else:
            f_sign = 1.0 if self.v > 0 else -1.0
            f_net = f_drive - f_sign * F_COULOMB - B_EFF * self.v
            # Do not let friction alone push the body through zero within one tick.
            v_try = self.v + (f_net / M_EFF) * dt
            if f_drive == 0.0 and (v_try * self.v) < 0.0:
                self.v = 0.0
                f_net = 0.0
        self.v += (f_net / M_EFF) * dt

        # ── Electrical ───────────────────────────────────────────────────────
        # Motor bus draw from mechanical power, through the boost efficiency.
        p_mech = max(0.0, f_drive * self.v)      # regen (negative) is floored at 0 here:
                                                 # the VESC's Battery Regen Max is a torque
                                                 # clip on this rig, not a dump path (see
                                                 # CLAUDE.md 2026-08-17b) — excess energy
                                                 # stays kinetic rather than returning to bus.
        if mot_live and self.v_bus > 1.0:
            i_motor = p_mech / (ETA_BOOST * self.v_bus)
        else:
            i_motor = 0.0
        i_motor += self.i_mot_extra if mot_live else 0.0
        i_total = i_motor + self.i_aux

        if self.electrical is not None:
            # ── Hi-fi delegation ────────────────────────────────────────────
            # Only the ELECTRICAL section is delegated.  The mechanical model above
            # and the Ag105 status logic below stay here, so a scenario behaves the
            # same way in either mode apart from the electrical fidelity itself.
            self.electrical.i_aux = self.i_aux
            # M5 DEVIATION: hi-fi's v_bus_sense_offset is SENSED-RAIL-ONLY (added
            # only in ElectricalSim._rails(), never seen by the node/diode/chopper
            # network) -- an intentional asymmetry against simple mode, where the
            # same scenario offset IS a real algebraic disturbance on V_bus.  See
            # hil_electrical.py's ElectricalSim.__init__ comment and
            # docs/HIL_PLANT.md's scenario table for the full rationale.
            self.electrical.v_bus_sense_offset = self.v_bus_offset
            # L5: self.i_charge here is last TICK's Ag105 current -- this tick's
            # value is computed further down in the Ag105 state machine below,
            # after the electrical substeps have already run.  Deliberate and
            # harmless: one 1 ms tick of lag against a 0.4 s (AG105_TAU_S) charger
            # ramp is not an ordering bug to fix.
            self.electrical.i_charge_into_pack = self.i_charge
            rails = self.electrical.step(dt, {
                "sw": sw, "aux": aux, "i_motor_a": i_motor,
                "code_fc": code_fc, "code_bt": code_bt,
                "i_charge_a": self.i_charge,
            })
            self.v_bus = rails["V_bus"]
            self.i_fc = rails["I_fc"]
            self.i_batt = rails["I_batt"]
            self.v_chg = rails["V_chg"]
            self.v_rgn = rails["V_rgn"]
            v_fc = rails["V_fc"]
            v_batt = rails["V_batt"]
        else:
            # ── Simple droop node ───────────────────────────────────────────
            if fc_live or bt_live:
                # MEASURED droop, mode-aware: the fit separates cleanly into a
                # both-sources-live regime and a single-source regime (see the
                # K_DROOP_BUS_* constants).  The old single source-agnostic
                # 0.35 V/A placeholder is retired.
                k = K_DROOP_BUS_SHARED if (fc_live and bt_live) else K_DROOP_BUS_SINGLE
                self.v_bus = V_BUS_DROOP_V0 - k * i_total + self.v_bus_offset
                # Share split by droop code ratio (see class docstring for the caveat).
                if fc_live and bt_live:
                    denom = code_fc + code_bt
                    frac_fc = (code_fc / denom) if denom > 1e-9 else 0.5
                elif fc_live:
                    frac_fc = 1.0
                else:
                    frac_fc = 0.0
                self.i_fc = i_total * frac_fc
                self.i_batt = i_total * (1.0 - frac_fc)
            else:
                # No source closed: the 470 uF bulk decays through its bleed path.
                tau = R_BUS_BLEED * C_BUS_F
                self.v_bus += (-self.v_bus / tau) * dt
                self.i_fc = 0.0
                self.i_batt = 0.0
            self.v_bus = max(0.0, self.v_bus)

            # Source terminals from the shared source models: the fuel cell's
            # polarization curve + double-layer lag, and the pack's OCV(SOC) with
            # its coulomb count.  Currents are referred to the source side.
            i_fc_src = ElectricalSim._source_current(
                self.i_fc, self.fuel_cell.v_terminal, self.v_bus)
            i_bt_src = ElectricalSim._source_current(
                self.i_batt, self.battery.v_terminal, self.v_bus)
            v_fc = self.fuel_cell.update(dt, i_fc_src)
            # Net pack current: boost draw minus the Ag105's charge current.
            v_batt = self.battery.update(dt, i_bt_src - self.i_charge)

            # Charger input tracks the bus when its path switch is closed, else 0.
            self.v_chg = self.v_bus if (sw & SW_FC_CHARGE) else 0.0
            self.v_rgn = self.v_bus if (sw & SW_REGEN) else 0.0

        # ── Ag105 charger ────────────────────────────────────────────────────
        # Power gating mirrors the firmware's chargerHasPower(): FC_CHARGE closed, or
        # REGEN and MOT_PWR both closed.  The rail actually presented to the module has
        # to be up as well — a closed switch onto a collapsed bus charges nothing.
        chg_path = bool(sw & SW_FC_CHARGE) or (bool(sw & SW_REGEN) and bool(sw & SW_MOT_PWR))
        v_chg_in = self.v_chg if (sw & SW_FC_CHARGE) else self.v_rgn
        chg_powered = chg_path and v_chg_in >= AG105_V_IN_MIN and not self.chg_fault
        if chg_powered:
            self.chg_powered_s += dt
        else:
            self.chg_powered_s = 0.0

        if not chg_powered:
            # Input removed: the module is dark.  0x00 is what the firmware's own failed-read
            # path leaves behind, and it decodes as GENSTAT "Battery Disconnect".
            self.i_charge = 0.0
            self.ag105_status = AG105_ST_DISCONNECT
        elif self.chg_powered_s < AG105_SETTLE_S:
            # Bring-up window (AG105_SETTLE_MS in the .ino).  Report Bring-Up Charge with no
            # current yet, so ag105IsReady() stays false until the module is genuinely up —
            # which is what gates chargingControl()'s MPPT release.
            self.i_charge = 0.0
            self.ag105_status = AG105_ST_BRINGUP
        elif self.battery.soc >= 0.995:
            # The pack is full.  With the SOC model in place (scope extension,
            # 2026-08-27) the charger CAN now reach Fully Charged, which the old
            # SoC-free model never could.  Current tapers to zero and GENSTAT
            # reports 011 (Fully Charged) — the state the firmware's ag105IsReady()
            # and detectFaults() GENSTAT decode both have to handle.
            self.i_charge += (0.0 - self.i_charge) * (dt / AG105_TAU_S)
            self.ag105_status = AG105_ST_FULL | AG105_FLAG_CV
            if aux & AUX_MPPT_DISABLE:
                self.ag105_status |= AG105_FLAG_MPPT_EN | AG105_FLAG_PWR_TRACK
        else:
            # Constant-current charging into the 2S pack, ramped first-order toward
            # the configured 2.5 A ceiling.  The current is fed back into the pack's
            # coulomb count (BatterySource, negative = charge), so a long
            # `charge-cruise` run visibly walks V_batt up the OCV curve.
            self.i_charge += (AG105_I_MAX - self.i_charge) * (dt / AG105_TAU_S)
            self.ag105_status = AG105_ST_CHARGING | AG105_FLAG_CC
            # MPPT_DISABLE is ACTIVE-LOW: pin HIGH releases the tracking loop, pin LOW
            # inhibits it.  Only the two tracking flags follow it; charging continues either
            # way (the firmware asserts it during regen precisely so charging is not disturbed).
            if aux & AUX_MPPT_DISABLE:
                self.ag105_status |= AG105_FLAG_MPPT_EN | AG105_FLAG_PWR_TRACK

        return {
            "V_fc": v_fc,
            "V_batt": v_batt,
            "V_bus": self.v_bus,
            "V_chg": self.v_chg,
            "V_rgn": self.v_rgn,
            "I_fc": self.i_fc,
            "I_batt": self.i_batt,
            "v_actual": self.v,
            "I_charge": self.i_charge,
            "ag105_status": self.ag105_status,
            # Appended (never reordered) for the CSV's new `soc` column.
            "soc": self.battery.soc,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Replay source — a decoded .BLG bench log played back as injection frames.
# ─────────────────────────────────────────────────────────────────────────────
# BLG record field  ->  injection frame field.  The names on the left are the
# decoder's own CSV column names (tools/decode_benchlog.py CSV_FIELDS_V*), read
# from DecodeResult.csv_header at runtime — nothing here is guessed.
REPLAY_FIELD_MAP = [
    ("V_fc",   "V_fc"),
    ("V_batt", "V_batt"),
    ("V_bus",  "V_bus"),
    ("V_chg",  "V_chg"),
    ("V_rgn",  "V_rgn"),
    ("I_fc",   "I_fc"),
    ("I_batt", "I_batt"),
    ("v_act",  "v_actual"),
]

# The BLG record carries NO charge-current and NO Ag105 status field in any
# format version v1-v7 (see decode_benchlog's record tables), so these two
# injection-frame fields are replayed as zeros: I_charge = 0.0 A and
# ag105_status = 0x00, which decodes as GENSTAT "Battery Disconnect" — exactly
# what the firmware's own failed-read path leaves behind.
REPLAY_I_CHARGE = 0.0
REPLAY_AG105_STATUS = AG105_ST_DISCONNECT

# t_us in a BLG is micros() at sample time and wraps every ~71.58 min; the
# decoder already rejects records whose forward modular step is implausible, so
# a modular difference is the correct way to rebuild a monotonic time axis.
_U32 = 1 << 32


def load_replay(path):
    """Decode a .BLG into a replay source.

    Returns (records, header, warnings) where records is a list of
    (t_seconds_from_start, sensors_dict) with sensors_dict shaped exactly like
    Plant.step()'s return value.
    """
    # Lazy import: the decoder is only needed in replay mode, and it lives
    # beside this file rather than on the default path.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from decode_benchlog import decode_blg
    except ImportError as exc:
        raise SystemExit(
            f"[hil] cannot import tools/decode_benchlog.py ({exc}) — replay mode "
            f"needs it to parse the .BLG.  Run from the repo, or put tools/ on "
            f"PYTHONPATH.")

    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise SystemExit(f"[hil] cannot read {path}: {exc}")

    try:
        result = decode_blg(data)
    except ValueError as exc:
        raise SystemExit(f"[hil] {path} is not a decodable .BLG: {exc}")

    cols = result.csv_header.split(",")
    idx = {name: i for i, name in enumerate(cols)}
    missing = [src for src, _ in REPLAY_FIELD_MAP if src not in idx]

    records = []
    prev_us = None
    t_us_accum = 0
    for row in result.csv_rows:
        cells = row.split(",")
        t_us = int(cells[idx["t_us"]])
        if prev_us is None:
            t_us_accum = 0
        else:
            t_us_accum += (t_us - prev_us) & (_U32 - 1)
        prev_us = t_us

        sensors = {}
        for src, dst in REPLAY_FIELD_MAP:
            if src in idx:
                cell = cells[idx[src]]
                # v_sp/v_act are blank when the record's velocity-valid flag
                # (bit1) is clear — the firmware had no trustworthy velocity,
                # so 0.0 m/s is the honest injection value.
                sensors[dst] = float(cell) if cell != "" else 0.0
            else:
                sensors[dst] = 0.0
        sensors["I_charge"] = REPLAY_I_CHARGE
        sensors["ag105_status"] = REPLAY_AG105_STATUS
        records.append((t_us_accum / 1e6, sensors))

    if not records:
        raise SystemExit(f"[hil] {path} decoded to zero records — nothing to replay")

    warnings = []
    if missing:
        warnings.append(
            f"format v{result.header['version']} records carry no "
            f"{', '.join(missing)} field(s) — injected as 0.0")
    warnings.extend(result.warnings)
    return records, result.header, warnings


class ReplaySource:
    """Plays a decoded .BLG back on a wall-clock axis (zero-order hold)."""

    def __init__(self, records, speed=1.0, loop=False):
        self.records = records
        self.speed = speed
        self.loop = loop
        self.span = records[-1][0]      # log duration [s] at 1.0x
        self.i = 0
        self.laps = 0
        self.finished = False

    def sample(self, t):
        """Return (sensors, record_index) for wall-clock time t, or (None, None)
        once a non-looping log has run out."""
        if self.finished:
            return None, None
        tl = t * self.speed
        if self.span > 0:
            if tl > self.span:
                if not self.loop:
                    self.finished = True
                    return None, None
                laps = int(tl // self.span)
                if laps != self.laps:
                    self.laps = laps
                    self.i = 0          # restart the scan for the new lap
                tl -= laps * self.span
        elif tl > 0 and not self.loop:
            self.finished = True
            return None, None
        # Monotonic forward scan (zero-order hold on the most recent sample).
        while self.i + 1 < len(self.records) and self.records[self.i + 1][0] <= tl:
            self.i += 1
        return self.records[self.i][1], self.i


# ═════════════════════════════════════════════════════════════════════════════
# Pi COMMAND PACKET — the firmware's 22-byte command datagram
#
# Layout VERIFIED from teensy_controller/teensy_controller.ino
# processPiCommandPacket(), lines 4806-4852 (and SYNC_BYTE_RX at line 2528).
# Nothing here is guessed; the body of that function is byte-frozen because the Pi
# bridge parses fixed offsets.
#
#    0   u8    sync   SYNC_BYTE_RX = 0xBB                     (.ino:2528, :4810)
#    1   u32   timestamp                                      (.ino:4825-4826)
#    5   u16   pkt_counter_Pi                                 (.ino:4828-4829)
#    7   f32   v_setpoint            constrained +/-20 m/s    (.ino:4842, :4846)
#   11   f32   power_share_setpoint  constrained [0,1]        (.ino:4843, :4847)
#   15   f32   charge_goal                                    (.ino:4844, :4848)
#   19   u8    mode_cmd   0=HYBRID 1=FC_ONLY 2=BATT 3=CHARGE 4=SAFE  (.ino:4850,:4857)
#   20   u8    droop_enable — RESERVED, parsed and discarded  (.ino:4851-4852)
#   21   u8    XOR checksum over bytes 1..20                  (.ino:4812-4814)
#
# The firmware's receiveCommands() drains BOTH frame types off the same socket
# (fw v21 bounded drain loop), so these go to the same address/port as the
# injection frames.
# ═════════════════════════════════════════════════════════════════════════════
SYNC_BYTE_RX = 0xBB
PI_CMD_SIZE = 22

MODE_HYBRID, MODE_FC_ONLY, MODE_BATT, MODE_CHARGE, MODE_SAFE = 0, 1, 2, 3, 4


def pack_pi_command(timestamp_ms, counter, v_setpoint, power_share_setpoint,
                    charge_goal, mode_cmd, droop_enable=0) -> bytes:
    body = struct.pack("<IHfffBB", timestamp_ms & 0xFFFFFFFF, counter & 0xFFFF,
                       v_setpoint, power_share_setpoint, charge_goal,
                       mode_cmd & 0xFF, droop_enable & 0xFF)
    return bytes([SYNC_BYTE_RX]) + body + bytes([xor_checksum(body)])


class PiCommander:
    """Plays a scenario's pi-command timeline onto the same socket as the injection
    frames, at a fixed rate.

    A timeline is a list of (t_seconds, fields) applied in order; `fields` may set
    any of v_setpoint / power_share_setpoint / charge_goal / mode_cmd /
    droop_enable, and unspecified fields HOLD their previous value — matching the
    firmware, which also holds a field it rejects (.ino:4846-4848).

    Rate: PI_CMD_HZ.  The firmware's Pi watchdog wants regular traffic, and a
    command packet is what marks the link alive (`last_rx_ms`, .ino:4854), so the
    commander keeps sending the held state even between timeline entries.
    """

    PI_CMD_HZ = 50.0

    def __init__(self, timeline, rate_hz=PI_CMD_HZ):
        self.timeline = sorted(timeline or [], key=lambda e: e[0])
        self.period = 1.0 / rate_hz
        self.next_tx = 0.0
        self.idx = 0
        self.counter = 0
        self.sent = 0
        self.state = {"v_setpoint": 0.0, "power_share_setpoint": 0.5,
                      "charge_goal": 0.0, "mode_cmd": MODE_SAFE, "droop_enable": 0}
        self.last_applied = None

    def tick(self, t):
        """Return a packet to send at time t, or None."""
        while self.idx < len(self.timeline) and self.timeline[self.idx][0] <= t:
            self.state.update(self.timeline[self.idx][1])
            self.last_applied = self.timeline[self.idx]
            self.idx += 1
        if not self.timeline or t < self.next_tx:
            return None
        self.next_tx = t + self.period
        self.counter = (self.counter + 1) & 0xFFFF
        self.sent += 1
        return pack_pi_command(
            int(t * 1000.0), self.counter, self.state["v_setpoint"],
            self.state["power_share_setpoint"], self.state["charge_goal"],
            self.state["mode_cmd"], self.state["droop_enable"])


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO REGISTRY
#
# The CLI and (by contract) tools/run_hil_suite.py consume this via
#     from hil_plant_sim import SCENARIOS
# apply_scenario() remains the behaviour dispatcher; this dict is metadata only.
#
#   electrical : "simple" | "hifi" | "any" — which engine the scenario NEEDS.
#                A "hifi" scenario is refused under --electrical simple rather than
#                silently producing a meaningless trace.
#   duration_s : default --duration for this scenario
#   pi_timeline: optional [(t, {field: value})] fed to PiCommander
#   vesc_cap_f : optional override of the VESC input capacitance (hi-fi only)
# ═════════════════════════════════════════════════════════════════════════════
SCENARIOS = {
    "steady": {
        "description": "fixed aux load; the quiescent baseline (H1)",
        "electrical": "any", "duration_s": 30.0,
    },
    "step-load": {
        "description": "+1.2 A aux load step at t = 5 s — a bus disturbance the "
                       "share loop must reject",
        "electrical": "any", "duration_s": 30.0,
    },
    "sag": {
        "description": "-5 V bus disturbance for 1 s at t = 5 s, crossing "
                       "LIMIT_V_BUS_MIN (12.0 V) — the real UV path (H2)",
        "electrical": "any", "duration_s": 30.0,
    },
    "comm-loss": {
        "description": "stops transmitting for 1 s at t = 5 s — hold-then-zero (H3)",
        "electrical": "any", "duration_s": 30.0,
    },
    "drive": {
        "description": "plant only; the operator drives the firmware by hand "
                       "('V', 'D', 'Y') over USB (H4)",
        "electrical": "any", "duration_s": 30.0,
    },
    # ── Charging-path scenarios (the firmware's charging path had NO coverage) ──
    "charge-cruise": {
        "description": "Run state, moderate cruise, charge_goal > 0: FC_CHARGE opens "
                       "on intent, the Ag105 settles to Charging, MPPT released",
        "electrical": "any", "duration_s": 40.0,
        "pi_timeline": [
            (0.5,  {"mode_cmd": MODE_SAFE, "charge_goal": 0.0}),
            (3.0,  {"mode_cmd": MODE_HYBRID}),            # Idle -> Run (.ino:4858)
            (5.0,  {"v_setpoint": 1.2, "power_share_setpoint": 0.5}),
            (8.0,  {"charge_goal": 1.0}),                 # open FC_CHARGE on INTENT
        ],
    },
    "charge-regen": {
        "description": "cruise/brake cycling with charge_goal > 0: MPPT_DISABLE "
                       "asserted during regen, REGEN vs FC_CHARGE mutual exclusion",
        "electrical": "any", "duration_s": 45.0,
        "pi_timeline": [
            (0.5,  {"mode_cmd": MODE_SAFE, "charge_goal": 0.0}),
            (3.0,  {"mode_cmd": MODE_HYBRID}),
            (5.0,  {"v_setpoint": 1.5, "charge_goal": 1.0}),
            (12.0, {"v_setpoint": 0.0}),                  # brake: commanded current
            (18.0, {"v_setpoint": 1.5}),                  # goes negative -> regen
            (25.0, {"v_setpoint": 0.0}),
            (31.0, {"v_setpoint": 1.5}),
            (38.0, {"v_setpoint": 0.0}),
        ],
    },
    "charge-fault": {
        "description": "charging established, then the charger input rail collapses "
                       "— exercises the GENSTAT decode / charger-loss path",
        "electrical": "any", "duration_s": 40.0,
        "pi_timeline": [
            (0.5,  {"mode_cmd": MODE_SAFE, "charge_goal": 0.0}),
            (3.0,  {"mode_cmd": MODE_HYBRID}),
            (5.0,  {"v_setpoint": 1.0, "charge_goal": 1.0}),
        ],
    },
    # ── Source-model scenarios ─────────────────────────────────────────────────
    "soc-depletion": {
        "description": "sustained battery-heavy load: V_batt walks DOWN the OCV "
                       "curve toward LIMIT_V_BATT_MIN — the honest UV_BATT path",
        "electrical": "any", "duration_s": 120.0,
        "pi_timeline": [
            (0.5,  {"mode_cmd": MODE_SAFE}),
            (3.0,  {"mode_cmd": MODE_HYBRID}),
            (5.0,  {"power_share_setpoint": 0.0}),   # all load onto the battery
        ],
    },
    # ── Hi-fi-only scenarios ───────────────────────────────────────────────────
    "handoff-sag": {
        "description": "TP0178/TP0201 class: drive the share to a rail so one source "
                       "goes dark, then perturb — the standby ideal diode picks up "
                       "only REACTIVELY, after the bus has already sagged",
        "electrical": "hifi", "duration_s": 40.0,
        "pi_timeline": [
            (0.5,  {"mode_cmd": MODE_SAFE}),
            (3.0,  {"mode_cmd": MODE_HYBRID}),
            (6.0,  {"v_setpoint": 1.0, "power_share_setpoint": 1.0}),   # FC-only rail
        ],
    },
    "bringup": {
        "description": "from dark: the firmware's staged bring-up (P0-P3) against the "
                       "real RT1987 t_D(ON) + soft-start delays",
        "electrical": "hifi", "duration_s": 30.0,
    },
    "scp-inrush": {
        "description": "RT1987 soft-start foldback MARGIN case: MOT_PWR ramping into "
                       "the high end of the VESC input envelope (0.9 mF) plus the "
                       "470 uF local bulk, under load",
        "electrical": "hifi", "duration_s": 30.0,
        "vesc_cap_f": 0.9e-3,
    },
}

SCENARIO_NAMES = list(SCENARIOS)


def apply_scenario(plant, scenario, t):
    """
    Mutate the plant for the active scenario at time t and return this tick's
    transmit-enable flag.

    The gate is recomputed statelessly from `t` on every call (only "comm-loss"
    ever clears it), so it is a RETURN value, not an in/out parameter — the old
    `tx_enabled` argument was always passed True and immediately overwritten,
    which read as if the flag were latched across ticks. It is not.
    """
    tx_enabled = True
    if scenario == "steady":
        plant.i_aux = I_AUX_A
    elif scenario == "step-load":
        # Aux load step at t = 5 s: a bus-current disturbance the share loop must reject.
        plant.i_aux = I_AUX_A + (1.2 if t >= 5.0 else 0.0)
    elif scenario == "sag":
        # Bus disturbance dip at t = 5 s, 1 s long, deep enough to cross
        # LIMIT_V_BUS_MIN (12.0 V) and exercise the real UV fault path.
        plant.v_bus_offset = -5.0 if 5.0 <= t < 6.0 else 0.0
    elif scenario == "comm-loss":
        # Stop transmitting for 1 s at t = 5 s: exercises the firmware's two-stage
        # hold-then-zero (HIL_STALE_MS 50, HIL_ZERO_MS 250).
        tx_enabled = not (5.0 <= t < 6.0)
    elif scenario == "drive":
        # Plant only.  The operator drives the firmware by hand ('V', 'D', 'Y' ...)
        # over USB serial; this scenario just keeps the plant honest underneath.
        plant.i_aux = I_AUX_A
    elif scenario in ("charge-cruise", "charge-regen"):
        # Nothing to perturb: the stimulus is the pi-command timeline (mode -> Run,
        # a cruise setpoint, charge_goal > 0).  The plant just carries the load.
        plant.i_aux = I_AUX_A
    elif scenario == "charge-fault":
        # Charging is established by the timeline; at t = 20 s the charger's INPUT
        # rail collapses (a connector, the FC path browning out).  The Ag105 goes
        # dark -> GENSTAT "Battery Disconnect", ag105IsReady() drops, and the
        # firmware's charger-loss handling is what is under test.
        plant.chg_fault = t >= 20.0
    elif scenario == "soc-depletion":
        # A heavy sustained bus load so the coulomb count actually moves.  NOTE: at
        # 5 Ah a 3 A draw is a ~100 min run — use --soc0 (e.g. 0.15) and/or
        # --capacity-ah to bring it inside a bench session.  The model is honest
        # rather than accelerated on purpose: an artificially fast SOC ramp would
        # also fake the RC-pair and Rs(SOC) dynamics the UV path sees.
        plant.i_aux = I_AUX_A + (3.0 if t >= 5.0 else 0.0)
    elif scenario == "handoff-sag":
        # The share rail is commanded by the timeline; the perturbation is a load
        # step at t = 20 s, large enough that the FC channel alone cannot hold the
        # bus.  Whether the standby BT diode picks up cleanly or only after a
        # measurable unsourced gap is the whole observation (hi-fi only — the simple
        # droop node has no ideal-diode dynamics and cannot show it).
        plant.i_aux = I_AUX_A + (1.5 if t >= 20.0 else 0.0)
    elif scenario == "bringup":
        # Plant only, from dark.  The operator runs the staged bring-up ('G') and
        # watches P0-P3 against the RT1987 delays.
        plant.i_aux = I_AUX_A
    elif scenario == "scp-inrush":
        # A legitimate SCP-MARGIN case, not the Death-5 stimulus.  Death-5 was a
        # full-bus hot-plug onto a discharged node; that exact case is no longer
        # reproducible, because MOT_PWR carries a 100 nF CSS (~19.8 ms ramp) and the
        # firmware pre-charges the node during bring-up (CLAUDE.md §2, Death 5).
        # What CAN still bind the foldback is MOT_PWR ramping into the TOP of the
        # VESC input envelope (0.9 mF + the 470 uF local bulk) while the node is
        # already drawing: the ramp current is C*dV/dt on ~1.37 mF, and the load —
        # which must sit BEHIND the switch, on V-MOT, not on VBUS — adds directly
        # to it.  Close MOT_PWR after t = 8 s (bench 'M', or a Run entry) to see it.  The event log's scp_cut / sw_ring entries are the
        # observable; an sw_ring with over_absmax True is the boost-death signature.
        plant.i_mot_extra = 6.0 if t >= 8.0 else 0.0
    return tx_enabled


def main(argv=None):
    ap = argparse.ArgumentParser(description="HIL plant simulator for the Teensy balancer board")
    ap.add_argument("--teensy-ip", default="192.168.1.50", help="board IP (default 192.168.1.50)")
    ap.add_argument("--port", type=int, default=TEENSY_PORT_DEFAULT,
                    help=f"board UDP port (default {TEENSY_PORT_DEFAULT})")
    ap.add_argument("--bind-port", type=int, default=0,
                    help="local UDP port to bind (0 = ephemeral; the board learns it from us)")
    ap.add_argument("--scenario", default=None, choices=SCENARIO_NAMES,
                    help="simulated-plant scenario (default steady; not with --replay). "
                         "Use --list-scenarios for descriptions.")
    ap.add_argument("--list-scenarios", action="store_true",
                    help="print the scenario registry and exit")
    ap.add_argument("--electrical", default="simple", choices=["simple", "hifi"],
                    help="electrical engine: 'simple' droop node (default) or 'hifi' "
                         "(tools/hil_electrical.py — TPS61288 average model, RT1987 "
                         "switch state machines, node ODE at an adaptive substep rate)")
    ap.add_argument("--trace-config", default="short", choices=["long", "short"],
                    help="hi-fi parasitic-inductance set: 'long' = as-manufactured "
                         "FastHenry extraction (FC 1.538 nH / BT 3.480 nH), 'short' = "
                         "post-bodge routing (default; TODO(verify) — never extracted)")
    ap.add_argument("--vesc-cap-uf", type=float, default=None,
                    help="hi-fi VESC input capacitance in uF (envelope 200-900, "
                         "default 500; some scenarios override it)")
    ap.add_argument("--soc0", type=float, default=0.7,
                    help="initial battery state of charge, 0-1 (default 0.7)")
    ap.add_argument("--capacity-ah", type=float, default=BATT_CAPACITY_AH,
                    help=f"battery capacity in Ah (default {BATT_CAPACITY_AH})")
    ap.add_argument("--noise", action="store_true",
                    help="hi-fi: apply ADC quantization (and any configured sigmas) to "
                         "the injected values")
    ap.add_argument("--replay", default=None, metavar="PATH.BLG",
                    help="replay a recorded bench log as injection frames "
                         "(bypasses the plant integrator; open-loop stimulus)")
    ap.add_argument("--replay-speed", type=float, default=1.0,
                    help="replay pacing multiplier (default 1.0 = true wall clock)")
    ap.add_argument("--loop", action="store_true",
                    help="replay: repeat the log until --duration elapses")
    ap.add_argument("--duration", type=float, default=None,
                    help="run length in seconds (default 30; replay default = log length)")
    ap.add_argument("--rate", type=float, default=1000.0, help="tick rate in Hz (default 1000)")
    ap.add_argument("--csv", default=None, help="write a per-tick CSV log here")
    ap.add_argument("--dash", action="store_true",
                    help="live terminal dashboard (5 Hz sampled view; suppresses the "
                         "1 Hz status lines while running). Off by default. Requires a tty.")
    args = ap.parse_args(argv)

    if args.list_scenarios:
        print(f"{'scenario':<16} {'engine':<7} {'dur':>6}  description")
        for name, meta in SCENARIOS.items():
            print(f"{name:<16} {meta['electrical']:<7} {meta['duration_s']:>5.0f}s  "
                  f"{meta['description']}")
        return 0
    if args.replay and args.scenario:
        ap.error("--replay and --scenario are mutually exclusive")
    if args.replay_speed <= 0.0:
        ap.error("--replay-speed must be > 0")
    if args.loop and not args.replay:
        ap.error("--loop only applies to --replay")
    scenario = args.scenario or "steady"
    meta = SCENARIOS[scenario]
    if not args.replay:
        if meta["electrical"] == "hifi" and args.electrical != "hifi":
            ap.error(f"scenario '{scenario}' requires --electrical hifi "
                     f"(the simple droop node has no ideal-diode/converter dynamics, "
                     f"so the trace it would produce is meaningless for this test)")
        if args.duration is None:
            args.duration = meta["duration_s"]
    if args.electrical == "hifi" and args.replay:
        ap.error("--electrical hifi has no effect with --replay (the plant integrator "
                 "is bypassed); drop one of them")
    if not 0.0 <= args.soc0 <= 1.0:
        ap.error("--soc0 must be in [0, 1]")
    if args.capacity_ah <= 0.0:
        ap.error("--capacity-ah must be > 0")

    replay = None
    if args.replay:
        records, blg_header, blg_warnings = load_replay(args.replay)
        replay = ReplaySource(records, speed=args.replay_speed, loop=args.loop)
        fw = blg_header.get("fw_version")
        fw_str = "pre-versioning" if fw is None else str(fw)
        print(f"[hil] replay {args.replay}: BLG format v{blg_header['version']}, "
              f"fw_version={fw_str}, {len(records)} records, "
              f"{replay.span:.3f} s of log, speed={args.replay_speed:g}x"
              f"{', looping' if args.loop else ''}")
        print("[hil] WARNING: replay is an OPEN-LOOP stimulus — the firmware's "
              "commands do NOT influence the replayed trajectory.")
        print(f"[hil] WARNING: this log was recorded under fw_version {fw_str}; "
              "the flashed firmware's control law may differ (e.g. a v14 'V' "
              "trace is a different control law than v13 — new coefficients and "
              "a x1.34 DC plant gain), so responses will NOT match the log.")
        for w in blg_warnings:
            print(f"[hil] replay note: {w}")
        if args.duration is None:
            args.duration = replay.span / args.replay_speed
    if args.duration is None:
        args.duration = 30.0

    dt = 1.0 / args.rate
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("", args.bind_port))
    dest = (args.teensy_ip, args.port)

    electrical = None
    if args.electrical == "hifi" and not args.replay:
        c_vesc = (args.vesc_cap_uf * 1e-6) if args.vesc_cap_uf is not None \
            else meta.get("vesc_cap_f", C_VESC_DEFAULT)
        electrical = ElectricalSim(
            trace_config=args.trace_config,
            noise=NoiseConfig() if args.noise else None,
            c_vesc_f=c_vesc)
        print(f"[hil] electrical=hifi trace={args.trace_config} "
              f"C_vesc={c_vesc * 1e6:.0f} uF noise={'on' if args.noise else 'off'}")
    plant = Plant(electrical=electrical, soc0=args.soc0,
                  capacity_ah=args.capacity_ah)
    commander = PiCommander(meta.get("pi_timeline")) if not args.replay else None
    if commander and commander.timeline:
        print(f"[hil] pi-command timeline: {len(commander.timeline)} entries, "
              f"{PiCommander.PI_CMD_HZ:.0f} Hz")
    pi_frames = 0
    obs = None
    seq = 0
    rx_frames = 0
    rx_bad = 0
    tx_frames = 0
    max_overrun = 0.0

    csv_file = None
    writer = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="")
        writer = csv.writer(csv_file)
        header_row = [
            "t", "seq", "V_fc", "V_batt", "V_bus", "V_chg", "V_rgn", "I_fc", "I_batt",
            "v_actual", "I_charge", "ag105_status",
            "state", "switch", "aux", "current", "mdac_fc", "mdac_bt",
            "fault_flags",
        ]
        if replay:
            # Existing schema kept byte-for-byte; replay APPENDS one column so a
            # replay CSV stays parseable by anything that reads the simulated
            # schema, while still naming the source record each row came from.
            # NOTE: `soc` and the hi-fi columns are deliberately NOT added in replay
            # mode — the plant integrator is bypassed, so they would be meaningless,
            # and leaving them out keeps replay_rec at its established column index.
            header_row.append("replay_rec")
        else:
            header_row.append("soc")            # APPEND-only (scope extension)
            if electrical is not None:
                header_row += ["elec_substep_hz", "elec_events"]
        writer.writerow(header_row)

    # M3: open the electrical-events sidecar UP FRONT and stream into it as events
    # happen (drained + flushed every tick, below), instead of writing it only
    # after the main loop returns.  Previously a timeout SIGKILL on a wedged run
    # lost exactly the evidence about why it wedged; now the file on disk is
    # current as of the last completed tick even if the process is killed hard.
    events_path = None
    events_file = None
    events_written = 0          # index into electrical.events already flushed
    elec_events_total = 0       # cumulative count (electrical.events is TRIMMED
                                 # below to bound RAM on a long run, so this is the
                                 # durable total)
    elec_over_absmax = []       # small list of over-abs-max sw_ring events, kept
                                 # in full (rare) for the exit banner
    if args.csv and electrical is not None:
        events_path = args.csv + ".events.jsonl"
        try:
            events_file = open(events_path, "w", encoding="utf-8")
        except OSError as exc:
            print(f"[hil] could not open {events_path}: {exc}", file=sys.stderr)
            events_path = None

    def _drain_electrical_events():
        """Flush any new ElectricalSim events to the sidecar and bound RAM.

        Called every tick.  electrical.events is TRIMMED after each drain (M3):
        the sidecar file is now the durable record, so there is no reason to also
        keep an ever-growing in-memory copy for the life of a long run."""
        nonlocal events_written, elec_events_total
        if electrical is None:
            return
        new_events = electrical.events[events_written:]
        if not new_events:
            return
        elec_events_total += len(new_events)
        for e in new_events:
            if e.get("kind") == "sw_ring" and e.get("over_absmax"):
                elec_over_absmax.append(e)
            if events_file is not None:
                events_file.write(json.dumps(e) + "\n")
        if events_file is not None:
            events_file.flush()
        del electrical.events[:]
        events_written = 0

    src = f"replay={os.path.basename(args.replay)}" if replay else f"scenario={scenario}"
    print(f"[hil] {src} dest={dest[0]}:{dest[1]} "
          f"rate={args.rate:.0f} Hz duration={args.duration:.1f} s")

    # ── Optional live dashboard ──────────────────────────────────────────────
    # Lightness contract (docs/HIL_MODE.md "Live dashboard"): the loop's ONLY
    # obligation is `dash.snapshot = {...}` — one attribute assignment, atomic
    # under the GIL.  A daemon thread renders at 5 Hz from whatever snapshot is
    # current, so the view is deliberately several ticks behind.  Banners above
    # and the summary below still print normally; the 1 Hz status lines and the
    # in-loop replay note are suppressed/deferred while the screen is owned.
    dash = None
    deferred_notes = []
    if args.dash:
        # Lazy import, same convention as the replay decoder above: the module
        # lives beside this file rather than on the default path.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from hil_dashboard import Dashboard
        except ImportError as exc:
            raise SystemExit(f"[hil] --dash needs tools/hil_dashboard.py ({exc})")
        d = Dashboard()
        if d.start():
            dash = d
    dash_on = dash is not None

    t0 = time.monotonic()
    next_tick = t0
    last_status = t0
    ticks = 0
    tx_enabled = True
    sent_seq = 0        # last seq actually transmitted (CSV column)

    try:
        while True:
            now = time.monotonic()
            t = now - t0
            if t >= args.duration:
                break

            # ── Drain every observation frame waiting on the socket ──────────
            while True:
                try:
                    data, _addr = sock.recvfrom(256)
                except BlockingIOError:
                    break
                except OSError:
                    break
                decoded = parse_output(data)
                if decoded is None:
                    rx_bad += 1
                else:
                    obs = decoded
                    rx_frames += 1

            if replay:
                # Plant integrator BYPASSED: the rails come from the log.  The
                # observation-receive path, CSV logging and status line above/
                # below still run — comparing the firmware's live response
                # against the recorded bench run is the whole point.
                tx_enabled = True
                sensors, rec_idx = replay.sample(t)
                if sensors is None:
                    note = f"[hil] replay: end of log at t={t:.3f}s"
                    if dash_on:
                        deferred_notes.append(note)   # screen is owned; print after stop()
                    else:
                        print(note)
                    break
            else:
                tx_enabled = apply_scenario(plant, scenario, t)
                sensors = plant.step(dt, obs)
                rec_idx = None

            _drain_electrical_events()

            if tx_enabled:
                frame = pack_inject(
                    seq, sensors["V_fc"], sensors["V_batt"], sensors["V_bus"],
                    sensors["V_chg"], sensors["V_rgn"], sensors["I_fc"],
                    sensors["I_batt"], sensors["v_actual"],
                    sensors["I_charge"], sensors["ag105_status"],
                )
                try:
                    sock.sendto(frame, dest)
                    tx_frames += 1
                except OSError as exc:
                    print(f"[hil] send failed: {exc}", file=sys.stderr)
                sent_seq = seq                 # the seq actually on the wire this tick
                seq = (seq + 1) & 0xFF

            # ── Pi command timeline ─────────────────────────────────────────
            # Same socket, same destination: the firmware's receiveCommands()
            # drains both frame types and dispatches by length (fw v21).
            if commander is not None and tx_enabled:
                pkt = commander.tick(t)
                if pkt is not None:
                    try:
                        sock.sendto(pkt, dest)
                        pi_frames += 1
                    except OSError as exc:
                        print(f"[hil] pi command send failed: {exc}", file=sys.stderr)

            if writer:
                # Log the seq that was SENT this tick, not the already-incremented next one
                # (the old code logged seq post-increment, so every CSV row was off by one
                # against the frame it describes and against the firmware's seq echo).
                # On a non-transmitting tick ("comm-loss") there is no frame: log blank.
                row = [
                    f"{t:.6f}", sent_seq if tx_enabled else "",
                    f"{sensors['V_fc']:.4f}", f"{sensors['V_batt']:.4f}",
                    f"{sensors['V_bus']:.4f}", f"{sensors['V_chg']:.4f}",
                    f"{sensors['V_rgn']:.4f}", f"{sensors['I_fc']:.4f}",
                    f"{sensors['I_batt']:.4f}", f"{sensors['v_actual']:.5f}",
                    f"{sensors['I_charge']:.4f}", f"0x{sensors['ag105_status']:02X}",
                    obs["state"] if obs else "",
                    obs["switch"] if obs else "",
                    obs["aux"] if obs else "",
                    f"{obs['current']:.4f}" if obs else "",
                    obs["mdac_fc"] if obs else "",
                    obs["mdac_bt"] if obs else "",
                    obs["fault_flags"] if obs else "",
                ]
                if replay:
                    row.append(rec_idx)
                else:
                    row.append(f"{sensors.get('soc', 0.0):.5f}")
                    if electrical is not None:
                        row.append(f"{electrical.achieved_substep_hz:.0f}")
                        # M3: electrical.events is trimmed on every drain now, so
                        # the durable per-tick total is the tracked cumulative
                        # counter, not len(electrical.events) (which is ~0 most
                        # ticks).
                        row.append(elec_events_total)
                writer.writerow(row)

            ticks += 1

            # ── Dashboard feed: ONE attribute assignment, no I/O, no locks ───
            if dash_on:
                i_fc = sensors["I_fc"]
                i_bt = sensors["I_batt"]
                i_tot = i_fc + i_bt
                dash.snapshot = {
                    "t": t, "source": src, "mode": args.electrical,
                    "rate_hz": (ticks / (now - t0)) if now > t0 else None,
                    "tx": tx_frames, "rx": rx_frames, "bad": rx_bad, "pi": pi_frames,
                    "v_sp": commander.state["v_setpoint"] if commander and commander.timeline else None,
                    "v_act": sensors["v_actual"],
                    "share_sp": (commander.state["power_share_setpoint"]
                                 if commander and commander.timeline else None),
                    # Share is undefined at negligible source current — the
                    # ratio is all noise below ~50 mA.
                    "share_act": (i_fc / i_tot) if i_tot > 0.05 else None,
                    "V_bus": sensors["V_bus"], "I_tot": i_tot,
                    "I_fc": i_fc, "I_bt": i_bt,
                    "I_chg": sensors["I_charge"], "ag105": sensors["ag105_status"],
                    "state": obs["state"] if obs else None,
                    "switch": obs["switch"] if obs else None,
                    "aux": obs["aux"] if obs else None,
                    "I_cmd": obs["current"] if obs else None,
                    "faults": obs["fault_flags"] if obs else 0,
                    "hifi_hz": electrical.achieved_substep_hz if electrical else None,
                    "hifi_events": elec_events_total,
                    "hifi_chopper_w": electrical.chopper_peak_w if electrical else None,
                }

            # ── 1 Hz status line (and CSV flush, M3) ─────────────────────────
            if now - last_status >= 1.0:
                last_status = now
                # M3: flush at ~1 Hz so a hard-killed run's CSV is current on disk
                # up to the last completed second, not just at clean exit.
                if csv_file:
                    csv_file.flush()
                if dash_on and dash.error is None:
                    pass                # the dashboard owns the screen
                elif obs:
                    print(f"[hil] t={t:6.2f}s  state={obs['state']:2d} "
                          f"sw=0x{obs['switch']:02X} aux=0x{obs['aux']:02X} "
                          f"I_cmd={obs['current']:+6.2f}A  faults=0x{obs['fault_flags']:04X} "
                          f"| v={sensors['v_actual']:5.2f} m/s V_bus={sensors['V_bus']:5.2f}V "
                          f"I_fc={sensors['I_fc']:5.2f} I_bt={sensors['I_batt']:5.2f} "
                          f"I_chg={sensors['I_charge']:4.2f} chg=0x{sensors['ag105_status']:02X}"
                          + (f" soc={sensors['soc'] * 100:4.1f}%" if not replay else "")
                          + (f" | elec {electrical.achieved_substep_hz / 1e3:5.1f} kHz "
                             f"({electrical._n_sub} sub/tick) ev={elec_events_total}"
                             if electrical is not None else ""))
                else:
                    print(f"[hil] t={t:6.2f}s  no observation frames yet "
                          f"(tx={tx_frames}) — is the board flashed with -DHIL_SIM=1?")

            # ── Drift-corrected scheduling ───────────────────────────────────
            next_tick += dt
            slack = next_tick - time.monotonic()
            if slack > 0:
                time.sleep(slack)
            else:
                overrun = -slack
                max_overrun = max(max_overrun, overrun)
                if overrun > 0.25:
                    # Badly behind (host stall): resynchronize rather than spin
                    # through a burst of catch-up ticks the plant cannot honour.
                    next_tick = time.monotonic()
    except KeyboardInterrupt:
        if dash is not None:
            dash.stop()                 # restore the terminal before printing
            dash_on = False
        print("\n[hil] interrupted")
    finally:
        if dash is not None:
            dash.stop()                 # idempotent
            dash_on = False
        for note in deferred_notes:
            print(note)
        # M3: final drain so a break/exception on the last tick cannot lose the
        # handful of events accumulated since the previous drain.
        _drain_electrical_events()
        if events_file is not None:
            try:
                events_file.close()
            except OSError:
                pass
        if csv_file:
            csv_file.close()
        sock.close()

    elapsed = time.monotonic() - t0
    achieved = ticks / elapsed if elapsed > 0 else 0.0
    print(f"[hil] done: {ticks} ticks in {elapsed:.2f}s -> {achieved:.1f} Hz achieved "
          f"(target {args.rate:.0f} Hz), max overrun {max_overrun * 1e3:.2f} ms")
    print(f"[hil] tx={tx_frames} frames, rx={rx_frames} frames, {rx_bad} malformed")
    if commander is not None and commander.timeline:
        print(f"[hil] pi commands sent: {pi_frames} "
              f"(timeline entries applied: {commander.idx}/{len(commander.timeline)})")
    if not replay:
        print(f"[hil] battery: SOC {args.soc0 * 100:.1f}% -> "
              f"{plant.battery.soc * 100:.1f}% "
              f"({args.capacity_ah:g} Ah), V_batt {plant.battery.v_terminal:.3f} V; "
              f"fuel cell {plant.fuel_cell.v_terminal:.3f} V at "
              f"{plant.fuel_cell.i:.3f} A")
    if electrical is not None:
        summ = electrical.summary()
        # M3: electrical.events is trimmed on every drain, so the durable totals
        # for this exit summary are the tracked counters, not summ['events'] /
        # electrical.events (which reflect only whatever has accumulated since the
        # last drain — near-empty on a normal exit).
        print(f"[hil] electrical(hifi): {summ['achieved_substep_hz'] / 1e3:.1f} kHz "
              f"achieved substep rate ({summ['substeps_per_tick']} substeps/tick, "
              f"trace={summ['trace_config']}), {elec_events_total} events")
        if summ.get("numeric_fault"):
            print("[hil] *** numeric_fault: the electrical solve produced a "
                  "non-finite node value at least once this run (see the "
                  "'numeric_fault' events in the sidecar) — treat this run's "
                  "electrical trace as suspect ***")
        if elec_over_absmax:
            print(f"[hil] *** {len(elec_over_absmax)} switching event(s) with an "
                  f"estimated ring peak ABOVE the 20 V abs-max — the boost-death "
                  f"signature; worst "
                  f"{max(e['peak_v'] for e in elec_over_absmax):.2f} V ***")
        if events_path:
            print(f"[hil] {elec_events_total} electrical events -> {events_path}")
    if replay:
        print(f"[hil] replay: {args.replay} at {args.replay_speed:g}x, "
              f"reached record {replay.i}/{len(replay.records) - 1}, "
              f"laps={replay.laps + 1 if args.loop else 1}")
    if args.csv:
        print(f"[hil] CSV written to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

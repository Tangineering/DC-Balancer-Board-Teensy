"""Sim 6: regen power per hard brake against the charger capacity (J.2 item 74 ruling basis).

Mechanical motor model plus a one-node V-MOT energy balance; no circuit simulation. It estimates the regen power and
energy that the VESC delivers to V-MOT in a hard brake when no VESC over-voltage cut interrupts the brake, and it
compares that power with the charger-capacity corners of sim 2 (`../chopper/run.py`, CHARGERS). Below the charger
capacity the VINDPM loop holds V-MOT near VINDPM and no U101 OVP corner can trip; above it the excess energy charges
the V-MOT node towards the chopper onset.

Sources (every constant):
- M_EFF 3.5 kg, K_F 0.7538 N/A, F_COULOMB 2.00 N, B_EFF 0.534 N s/m: `tools/hil_plant_sim.py` lines 331-334.
- R_PH 22.6 mOhm: `docs/VESC_MOTOR_INTEGRATION.md` section 2 (from `motor_id_20260815.md`).
- P_e = 0.97 (0.9 K_F I v - 1.5 I^2 R_PH): `docs/reviews/charger_eval_2026-11-05/round2/regen_dynamics.md` section 1.2.
  Gear efficiency 0.9 and inverter efficiency 0.97 are TODO(verify) assumptions of that document.
- I_BRAKE 12 A: MOTOR_I_CMD_MAX (`teensy_controller/teensy_controller.ino` line 3649), the rail of the measured hard
  brakes (regen_dynamics.md section 1.1). The State-98 'T' ramp allows 25 A (TRAP_I_ABS_MAX, ino line 5235): Part F.
- Measured events (start and end speed): regen_dynamics.md section 1.1 table.
- Charger capacity corners (P_in, I clamp, VINDPM): `../chopper/run.py` CHARGERS (lines 141-150), exact expressions.
- VINDPM loop gain 10 A/V: `../chopper/RESULTS.md` section 3 item 7 (an assumption of sim 2).
- OVP rising minimum with pin leakage 21.588 V and without 22.149 V: `../efuse_decay/results/a_bands_corners.csv`
  (sim 5) and `../chopper/RESULTS.md` section 5.8.
- V-MOT capacitance 0.4 mF (C_VMOT_MIN) and 0.97 mF (HIL default): `../chopper/RESULTS.md` section 3 item 2.
- Staged absorption before T3 (Part E): design document FR-41 r5 and the FC-window text above it
  (`docs/charger_bq25798_wiring_design_2026-11-05.md` lines ~2698-2736): H1 rise maximum 18.05 V; until T3 lands
  (FR-07 latency 1.5 ms) IINDPM = min(0.90 A, G) with G >= 0.30 A; at 400 kHz the ramp reaches 0.85-0.90 A by the H1
  rise, at the 100 kHz fallback IINDPM at the earliest H1 rise is 0.300-0.890 A (the counted degraded mode).
- Drive cycles: `references/drive_cycles/*.csv` (time_s, v_mps).

Run with the miniforge Python. Prints ASCII only and writes only inside this folder.
"""
import csv
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))

M_EFF = 3.5
K_F = 0.7538
F_COULOMB = 2.00
B_EFF = 0.534
R_PH = 0.0226
ETA_GEAR = 0.9      # TODO(verify) regen_dynamics.md section 1.2
ETA_INV = 0.97      # TODO(verify) regen_dynamics.md section 1.2
I_BRAKE = 12.0
I_TRAP = 25.0
V_NODE = 19.0       # node voltage used only to convert power to current for Table 2
DT = 1e-5
K_VINDPM = 10.0     # A/V, sim 2 assumption
V_H1_RISE = 18.05
VINDPM_FC = 14.5    # FC image VINDPM before T3 (design document line 2648)
I_REGEN_BATT_MAX = 1.5  # VESC Battery Current Regen Max, SET 1.5 A (docs/VESC_MOTOR_INTEGRATION.md line 231)

CHARGERS = {        # sim 2 run.py CHARGERS, exact expressions
    "lo": dict(p=18.8, ilim=1.328, vindpm=19.38),
    "nom": dict(p=8.0 * 2.50 / 0.92, ilim=1.70, vindpm=19.0),
    "d310": dict(p=21.76, ilim=1.328, vindpm=19.0),
    "hi": dict(p=8.32 * 3.10 / 0.90, ilim=1.70, vindpm=18.62),
}
OVP_MIN_LEAK = 21.588
OVP_MIN_NOLEAK = 22.149
C_NODE = {"0.4mF": 0.4e-3, "0.97mF": 0.97e-3}

EVENTS = [  # name, v0, v1, node energy 0.97 mF, node energy 4 mF (regen_dynamics.md section 1.1)
    ("ML0151 41.36", 2.67, 1.55, 0.197, 0.81),
    ("ML0157 47.30", 3.00, 1.90, 0.193, 0.80),
    ("ML0165 22.64", 3.00, 2.38, 0.095, 0.39),
    ("ML0165 28.55", 2.49, 1.43, 0.191, 0.79),
    ("ML0195 33.20", 2.00, 0.99, 0.180, 0.74),
    ("YP0166 21.97", 3.00, 1.53, 0.283, 1.17),
    ("YP0196 21.97", 1.99, 1.00, 0.183, 0.75),
    ("YP0198 21.98", 1.98, 1.00, 0.131, 0.54),
]
REF_STEPS = [("step 2->1", 2.0, 1.0), ("step 3->1", 3.0, 1.0)]

# Part E staged-absorption modes: (name, IINDPM before T3 (A), T3 latency (s)); "full" = capacity from onset
MODES = [
    ("full", None, 0.0),
    ("400kHz", 0.85, 1.5e-3),
    ("100kHz", 0.30, 1.5e-3),
    ("100kHz_2ms", 0.30, 2.0e-3),
]


def p_e(v, i, eg=ETA_GEAR, ei=ETA_INV):
    """Electrical regen power at V-MOT (W) for brake current i (A, positive) at speed v (m/s)."""
    return ei * (eg * K_F * i * v - 1.5 * i * i * R_PH)


def brake_p(v, i_cmd, v_node, eg=ETA_GEAR, ei=ETA_INV, vesc_cap=True):
    """Regen power at V-MOT and the effective brake current. With vesc_cap, the VESC limits its battery-side regen
    current to I_REGEN_BATT_MAX at the node voltage by lowering the motor current (smaller root of Equation 1)."""
    p = p_e(v, i_cmd, eg, ei)
    if vesc_cap:
        pmax = I_REGEN_BATT_MAX * v_node
        if p > pmax:
            b = eg * K_F * v
            disc = b * b - 6.0 * R_PH * pmax / ei
            if disc >= 0:
                return pmax, (b - math.sqrt(disc)) / (3.0 * R_PH)
    return p, i_cmd


def drag(v):
    return F_COULOMB + B_EFF * v


def cap_power(ch, v_node):
    """Charger input power capacity at node voltage v_node: min(P_in, I clamp x V)."""
    return min(ch["p"], ch["ilim"] * v_node)


def railed_brake(v0, v1, chs=(), eg=ETA_GEAR, ei=ETA_INV, i_brake=I_BRAKE, vesc_cap=True, excess_only=False):
    """Continuous brake at i_brake from v0 to v1. Returns duration, peak/mean power, energy, excess energy per charger
    (capacity evaluated at the charger's VINDPM). The VESC regen cap uses the node voltage: the charger's VINDPM for a
    single charger, else V_NODE. excess_only stops once the power falls below the (single) charger capacity, since P
    falls monotonically with the speed."""
    caps = [cap_power(ch, ch["vindpm"]) for ch in chs]
    vn = chs[0]["vindpm"] if len(chs) == 1 else V_NODE
    v, t, e, pk = v0, 0.0, 0.0, 0.0
    ex = [0.0 for _ in caps]
    while v > v1:
        p, i_eff = brake_p(v, i_brake, vn, eg, ei, vesc_cap)
        if p <= 0:
            break
        if excess_only and p <= caps[0]:
            break
        e += p * DT
        pk = max(pk, p)
        for k, cap in enumerate(caps):
            if p > cap:
                ex[k] += (p - cap) * DT
        v -= (K_F * i_eff + drag(v)) / M_EFF * DT
        t += DT
    return t, pk, (e / t if t > 0 else 0.0), e, ex


def node_energy(c, v_from, v_to):
    return 0.5 * c * (v_to * v_to - v_from * v_from)


def v_threshold(p_cap, eg=ETA_GEAR, ei=ETA_INV, i_brake=I_BRAKE):
    """Speed above which the railed-brake power exceeds p_cap (P_e is linear in v at fixed I)."""
    a = ei * eg * K_F * i_brake
    b = ei * 1.5 * i_brake * i_brake * R_PH
    return (p_cap + b) / a


def first_trip_energy(ch, c, v_ovp, eg=ETA_GEAR, ei=ETA_INV, i_brake=I_BRAKE, lo=1.0, hi=6.0, vesc_cap=True):
    """Lowest start speed (bisection, 1 mm/s) whose excess energy reaches the node energy VINDPM -> v_ovp; None if
    no start speed up to 6 m/s trips (for example when the VESC regen cap lies below the charger capacity)."""
    need = node_energy(c, ch["vindpm"], v_ovp)

    def trips(v0):
        return railed_brake(v0, 0.5, (ch,), eg, ei, i_brake, vesc_cap, excess_only=True)[4][0] >= need
    if not trips(hi):
        return None
    while hi - lo > 1e-3:
        mid = 0.5 * (lo + hi)
        if trips(mid):
            hi = mid
        else:
            lo = mid
    return round(hi, 3)


def transient(v0, ch, c, mode, eg=ETA_GEAR, ei=ETA_INV, i_brake=I_BRAKE, v_stop=0.5, record=False):
    """Coupled brake and V-MOT node from the brake onset. 'full': node starts at VINDPM with full capacity.
    Staged modes: node starts at the H1 rise maximum 18.05 V with the brake at its start-speed power (conservative: the
    real node needs >= 0.74 ms to climb there, during which the ramp proceeds) and IINDPM limited until T3 lands.
    Charger draw = max(0, min(IINDPM(t), cap_power/V, K_VINDPM (V - VINDPM(t)))), with VINDPM(t) the FC-image 14.5 V
    before T3 and the regen-image VINDPM after it. The VESC regen cap applies at the node voltage. Housekeeping and
    chopper ignored."""
    name, i_pre, t_pre = mode
    vn = ch["vindpm"] if i_pre is None else V_H1_RISE
    v, t, vmax = v0, 0.0, vn
    tr = []
    while v > v_stop and t < 1.5:
        dt = 1e-6 if t < 5e-3 else 1e-5
        p, i_eff = brake_p(v, i_brake, vn, eg, ei)
        if p <= 0:
            break
        i_in = p / vn
        pre = i_pre is not None and t < t_pre
        lim = i_pre if pre else 1e9
        vindpm = VINDPM_FC if pre else ch["vindpm"]
        i_chg = max(0.0, min(lim, cap_power(ch, vn) / vn, K_VINDPM * (vn - vindpm)))
        vn += (i_in - i_chg) / c * dt
        vmax = max(vmax, vn)
        v -= (K_F * i_eff + drag(v)) / M_EFF * dt
        t += dt
        if record and (t < 5e-3 or int(t / dt) % 10 == 0):
            tr.append((t, vn))
    return (vmax, tr) if record else vmax


def first_trip_transient(ch, c, mode, v_ovp, eg=ETA_GEAR, ei=ETA_INV, i_brake=I_BRAKE, lo=1.0, hi=6.0):
    def trips(v0):
        return transient(v0, ch, c, mode, eg, ei, i_brake) >= v_ovp
    if trips(lo):
        return lo
    if not trips(hi):
        return None
    while hi - lo > 2e-3:
        mid = 0.5 * (lo + hi)
        if trips(mid):
            hi = mid
        else:
            lo = mid
    return round(hi, 3)


def write_csv(name, rows):
    with open(os.path.join(HERE, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    out = {"chargers": {k: dict(ch, p=round(ch["p"], 4)) for k, ch in CHARGERS.items()}}
    chs = list(CHARGERS.values())

    # Part A: measured events and reference steps, continuous railed brake (no fault-stop gap)
    rows_a = []
    for name, v0, v1, e97, e4 in EVENTS + [(n, a, b, None, None) for n, a, b in REF_STEPS]:
        t, pk, pm, e, ex = railed_brake(v0, v1, chs)
        ke = 0.5 * M_EFF * (v0 * v0 - v1 * v1)
        t_over_lo = max(0.0, (v0 - v_threshold(cap_power(CHARGERS["lo"], CHARGERS["lo"]["vindpm"]))) /
                        ((K_F * I_BRAKE + drag(v0)) / M_EFF))
        rows_a.append(dict(event=name, v0=v0, v1=v1, t_brake_s=round(t, 4), p_peak_W=round(pk, 3),
                           p_mean_W=round(pm, 3), i_peak_19V_A=round(pk / V_NODE, 3),
                           i_mean_19V_A=round(pm / V_NODE, 3), e_vmot_J=round(e, 3), ke_drop_J=round(ke, 3),
                           e_frac_ke=round(e / ke, 3), t_above_lo_ms=round(1e3 * t_over_lo, 2),
                           e_node_meas_097_J=e97, e_node_meas_4_J=e4,
                           **{"e_excess_%s_mJ" % k: round(1e3 * x, 4) for k, x in zip(CHARGERS, ex)}))
    write_csv("results_events.csv", rows_a)

    # Part B: railed brake from v0 (0.01 m/s steps) to 1.0 m/s; excess energy above each charger corner
    v0s = [round(1.5 + 0.01 * k, 2) for k in range(301)]  # 1.5..4.5 m/s
    rows_b = []
    for v0 in v0s:
        t, pk, pm, e, ex = railed_brake(v0, 1.0, chs)
        r = dict(v0=v0, p_peak_W=round(pk, 3), e_vmot_J=round(e, 4))
        for k, x in zip(CHARGERS, ex):
            r["e_excess_%s_mJ" % k] = round(1e3 * x, 4)
        rows_b.append(r)
    write_csv("results_speed_sweep.csv", rows_b)

    thresholds = {}
    for k, ch in CHARGERS.items():
        need = {cn: {"leak": node_energy(c, ch["vindpm"], OVP_MIN_LEAK),
                     "noleak": node_energy(c, ch["vindpm"], OVP_MIN_NOLEAK)} for cn, c in C_NODE.items()}
        first = {"%s_%s" % (cn, lk): first_trip_energy(ch, C_NODE[cn], OVP_MIN_LEAK if lk == "leak" else OVP_MIN_NOLEAK)
                 for cn in C_NODE for lk in ("leak", "noleak")}
        pcap = cap_power(ch, ch["vindpm"])
        first["0.4mF_leak_no_vesc_cap"] = first_trip_energy(ch, C_NODE["0.4mF"], OVP_MIN_LEAK, vesc_cap=False)
        thresholds[k] = dict(p_cap_W=round(pcap, 4), vindpm_V=ch["vindpm"],
                             vesc_cap_at_vindpm_W=round(I_REGEN_BATT_MAX * ch["vindpm"], 3),
                             v_power_exceeds_mps=round(v_threshold(pcap), 4),
                             node_energy_needed_mJ={cn: {lk: round(1e3 * x, 3) for lk, x in d.items()}
                                                    for cn, d in need.items()},
                             first_v0_reaching_ovp_mps=first)
    out["thresholds"] = thresholds

    # Part C: drive cycles under ideal setpoint tracking on a 1 ms linear interpolation of the profile
    rows_c = []
    dc_dir = os.path.join(REPO, "references", "drive_cycles")
    for fn in sorted(os.listdir(dc_dir)):
        if not fn.endswith(".csv"):
            continue
        with open(os.path.join(dc_dir, fn)) as f:
            rd = list(csv.DictReader(f))
        t = [float(r["time_s"]) for r in rd]
        v = [float(r["v_mps"]) for r in rd]
        pk, tpk, vpk, ipk, eraw = 0.0, None, None, 0.0, 0.0
        pk_ub, ex_lo_ub, ex_lo, ex_nom_ub = 0.0, 0.0, 0.0, 0.0
        cap_lo = cap_power(CHARGERS["lo"], CHARGERS["lo"]["vindpm"])
        cap_nom = cap_power(CHARGERS["nom"], CHARGERS["nom"]["vindpm"])
        n_brakes_hi = 0
        for j in range(len(t) - 1):
            seg = t[j + 1] - t[j]
            if seg <= 0:
                continue
            a_dec = (v[j] - v[j + 1]) / seg
            a_prev = (v[j - 1] - v[j]) / (t[j] - t[j - 1]) if j > 0 and t[j] > t[j - 1] else 0.0
            if (M_EFF * a_dec > drag(v[j]) and v[j] > 3.0
                    and not (j > 0 and M_EFF * a_prev > drag(v[j - 1]))):
                n_brakes_hi += 1
            n = max(1, int(round(seg / 1e-3)))
            h = seg / n
            for q in range(n):
                vm = v[j] + (v[j + 1] - v[j]) * (q + 0.5) / n
                f_brake = M_EFF * a_dec - drag(vm)
                if f_brake <= 0 or vm <= 0:
                    continue
                i = min(f_brake / K_F, I_BRAKE)
                p = max(0.0, p_e(vm, i))
                eraw += p * h
                ex_lo += max(0.0, p - cap_lo) * h
                if p > pk:
                    pk, tpk, vpk, ipk = p, t[j] + (q + 0.5) * h, vm, i
                p_ub = max(0.0, p_e(vm, i, 1.0, 1.0))
                pk_ub = max(pk_ub, p_ub)
                ex_lo_ub += max(0.0, p_ub - cap_lo) * h
                ex_nom_ub += max(0.0, p_ub - cap_nom) * h
        rows_c.append(dict(cycle=fn, v_max=max(v), p_peak_W=round(pk, 3),
                           t_at_peak_s=None if tpk is None else round(tpk, 3),
                           v_at_peak_mps=None if vpk is None else round(vpk, 3), i_brake_at_peak_A=round(ipk, 3),
                           e_regen_total_J=round(eraw, 3), e_excess_lo_mJ=round(1e3 * ex_lo, 3),
                           p_peak_eta1_W=round(pk_ub, 3), e_excess_lo_eta1_mJ=round(1e3 * ex_lo_ub, 3),
                           e_excess_nom_eta1_mJ=round(1e3 * ex_nom_ub, 3), decels_from_above_3mps=n_brakes_hi))
    write_csv("results_drive_cycles.csv", rows_c)

    # Part D: efficiency sensitivity; the 3.00 m/s measured brake (ML0157) and the first start speed whose excess
    # reaches the OVP minimum (0.4 mF, leak corner)
    rows_d = []
    for eg, ei in ((0.8, 0.97), (0.9, 0.97), (1.0, 0.97), (1.0, 1.0)):
        t, pk, pm, e, ex = railed_brake(3.00, 1.90, chs, eg, ei)
        r = dict(eta_gear=eg, eta_inv=ei, p_peak_3mps_W=round(pk, 3), e_3to190_J=round(e, 3))
        for k, x in zip(CHARGERS, ex):
            r["e_excess_3mps_%s_mJ" % k] = round(1e3 * x, 3)
        for k, ch in CHARGERS.items():
            pcap = cap_power(ch, ch["vindpm"])
            r["v_power_exceeds_%s_mps" % k] = round(v_threshold(pcap, eg, ei), 4)
            r["need_%s_mJ" % k] = round(1e3 * node_energy(C_NODE["0.4mF"], ch["vindpm"], OVP_MIN_LEAK), 3)
            r["first_v0_ovp_%s_mps" % k] = first_trip_energy(ch, C_NODE["0.4mF"], OVP_MIN_LEAK, eg, ei)
        rows_d.append(r)
    write_csv("results_efficiency.csv", rows_d)
    out["efficiency"] = rows_d

    # Part E: staged absorption before T3 (FC-window brake). Peak V-MOT of the 3.00 m/s brake, and the first start
    # speed reaching the 21.588 V OVP minimum, per charger corner, capacitance, mode and efficiency.
    rows_e = []
    for eg, ei in ((0.9, 0.97), (1.0, 1.0)):
        for cn, c in C_NODE.items():
            for mode in MODES:
                r = dict(eta_gear=eg, eta_inv=ei, c=cn, mode=mode[0])
                for k, ch in CHARGERS.items():
                    r["vmax_3mps_%s_V" % k] = round(transient(3.00, ch, c, mode, eg, ei), 3)
                    r["first_v0_ovp_%s_mps" % k] = first_trip_transient(ch, c, mode, OVP_MIN_LEAK, eg, ei)
                rows_e.append(r)
    write_csv("results_staged.csv", rows_e)
    out["staged"] = rows_e

    # Part F: the State-98 'T' braking ramp at 25 A (TRAP_I_ABS_MAX), nominal efficiencies, energy criterion
    rows_f = []
    for k, ch in CHARGERS.items():
        pcap = cap_power(ch, ch["vindpm"])
        rows_f.append(dict(charger=k, v_power_exceeds_25A_mps=round(v_threshold(pcap, i_brake=I_TRAP), 4),
                           first_v0_ovp_25A_04mF_leak_mps=first_trip_energy(ch, C_NODE["0.4mF"], OVP_MIN_LEAK,
                                                                            i_brake=I_TRAP),
                           p_25A_at_3mps_W=round(p_e(3.0, I_TRAP), 3), p_25A_at_2p5mps_W=round(p_e(2.5, I_TRAP), 3),
                           vesc_cap_at_vindpm_W=round(I_REGEN_BATT_MAX * ch["vindpm"], 3)))
    write_csv("results_trap25A.csv", rows_f)
    out["trap25A"] = rows_f

    out["events"] = rows_a
    out["drive_cycles"] = rows_c
    with open(os.path.join(HERE, "summary.json"), "w") as f:
        json.dump(out, f, indent=1)

    # Figure: (a) peak power vs start speed; (b) excess energy vs the node energy per corner; (c) staged transient
    styles = {"lo": ("#7F7F7F", "--"), "nom": ("#2F6B2A", "-."), "hi": ("#7030A0", "--")}
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(16.5, 4.8))
    ax1.plot([r["v0"] for r in rows_b], [r["p_peak_W"] for r in rows_b], color="#1F4E79", lw=1.8,
             label="12 A brake, efficiency 0.9 / 0.97")
    ax1.plot([r["v0"] for r in rows_b], [brake_p(r["v0"], I_BRAKE, V_NODE, 1.0, 1.0)[0] for r in rows_b],
             color="#1F4E79", lw=1.2, ls=":", label="12 A brake, efficiency 1.0 / 1.0")
    ax1.axhline(I_REGEN_BATT_MAX * V_NODE, color="#C00000", lw=0.9, ls=":")
    ax1.text(1.52, I_REGEN_BATT_MAX * V_NODE - 1.3, "VESC regen limit 1.5 A x 19 V = 28.5 W", fontsize=8.5,
             color="#C00000")
    ev = [r for r in rows_a if not r["event"].startswith("step")]
    ax1.scatter([r["v0"] for r in ev], [r["p_peak_W"] for r in ev], color="#C55A11", zorder=3, s=26,
                label="measured hard brakes (start speed)")
    for k in ("lo", "nom", "hi"):
        c, ls = styles[k]
        pcap = thresholds[k]["p_cap_W"]
        ax1.axhline(pcap, color=c, ls=ls, lw=1.1)
        ax1.text(1.52, pcap + 0.35, "charger %s %.1f W (v0 > %.2f m/s)" % (k, pcap, thresholds[k]["v_power_exceeds_mps"]),
                 fontsize=8.5, color=c)
    ax1.set_xlabel("brake start speed v0 (m/s)")
    ax1.set_ylabel("peak regen power at V-MOT (W)")
    ax1.set_xlim(1.5, 4.5)
    ax1.set_ylim(0, 34)
    ax1.grid(alpha=0.3)
    ax1.legend(loc="lower right", fontsize=8)
    ax1.set_title("(a) peak regen power vs charger capacity", fontsize=10)

    for k in ("lo", "nom", "hi"):
        c, ls = styles[k]
        ax2.semilogy([r["v0"] for r in rows_b], [max(r["e_excess_%s_mJ" % k], 1e-4) for r in rows_b], color=c,
                     ls=ls, lw=1.6, label="excess above charger %s" % k)
        need = thresholds[k]["node_energy_needed_mJ"]["0.4mF"]["leak"]
        ax2.axhline(need, color=c, lw=0.9, ls=":")
    ax2.text(1.55, 50.0, "dotted: node energy VINDPM -> 21.588 V\nlo %.1f / nom %.1f / hi %.1f mJ"
             % tuple(thresholds[k]["node_energy_needed_mJ"]["0.4mF"]["leak"] for k in ("lo", "nom", "hi")),
             fontsize=8)
    ax2.set_xlabel("brake start speed v0 (m/s)")
    ax2.set_ylabel("regen energy above charger capacity (mJ)")
    ax2.set_xlim(1.5, 4.5)
    ax2.set_ylim(1e-2, 1e4)
    ax2.grid(alpha=0.3, which="both")
    ax2.legend(loc="lower right", fontsize=8)
    ax2.set_title("(b) excess energy vs node energy to the OVP minimum, 0.4 mF", fontsize=10)

    mcol = {"full": "#1F4E79", "400kHz": "#2F6B2A", "100kHz": "#C00000", "100kHz_2ms": "#C55A11"}
    for mode in MODES:
        vmax, tr = transient(3.00, CHARGERS["nom"], C_NODE["0.4mF"], mode, record=True, v_stop=1.9)
        ax3.plot([1e3 * a for a, _ in tr], [b for _, b in tr], color=mcol[mode[0]], lw=1.4,
                 label="%s (peak %.2f V)" % (mode[0], vmax))
    ax3.axhline(OVP_MIN_LEAK, color="k", lw=0.9, ls="--")
    ax3.text(0.3, OVP_MIN_LEAK + 0.08, "OVP rising minimum 21.588 V", fontsize=8)
    ax3.set_xlim(0, 20)
    ax3.set_ylim(17.5, 22.5)
    ax3.set_xlabel("time from brake onset (ms)")
    ax3.set_ylabel("V-MOT (V)")
    ax3.grid(alpha=0.3)
    ax3.legend(loc="lower right", fontsize=8)
    ax3.set_title("(c) 3.00 m/s brake, nominal charger, 0.4 mF, staged absorption", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig_regen_vs_charger.png"), dpi=150)

    print("Chargers (P_cap at VINDPM):", {k: d["p_cap_W"] for k, d in thresholds.items()})
    print("Part A (railed brake, no cut):")
    for r in rows_a:
        print("  %-14s %.2f->%.2f t=%.3f s Ppk=%.2f W Pmean=%.2f W Ipk19=%.3f A E=%.3f J E/KE=%.3f t>lo=%.2f ms "
              "exc_lo=%.4f mJ" % (r["event"], r["v0"], r["v1"], r["t_brake_s"], r["p_peak_W"], r["p_mean_W"],
                                  r["i_peak_19V_A"], r["e_vmot_J"], r["e_frac_ke"], r["t_above_lo_ms"],
                                  r["e_excess_lo_mJ"]))
    print("Part B thresholds (energy criterion, bisection 1 mm/s):")
    for k, d in thresholds.items():
        print("  %-5s Pcap %.3f W VINDPM %.2f V  v(P>cap) %.4f m/s  need(0.4mF leak) %.3f mJ  first v0 %s"
              % (k, d["p_cap_W"], d["vindpm_V"], d["v_power_exceeds_mps"],
                 d["node_energy_needed_mJ"]["0.4mF"]["leak"], d["first_v0_reaching_ovp_mps"]))
    print("Part C drive cycles (ideal tracking, 1 ms grid):")
    for r in rows_c:
        print("  %-28s vmax %.2f Ppk %.3f W at t=%s v=%s I=%.2f A E=%.3f J exc_lo %.3f mJ | eta1: Ppk %.3f W "
              "exc lo/nom %.3f/%.3f mJ | decels from >3 m/s: %d"
              % (r["cycle"], r["v_max"], r["p_peak_W"], r["t_at_peak_s"], r["v_at_peak_mps"], r["i_brake_at_peak_A"],
                 r["e_regen_total_J"], r["e_excess_lo_mJ"], r["p_peak_eta1_W"], r["e_excess_lo_eta1_mJ"],
                 r["e_excess_nom_eta1_mJ"], r["decels_from_above_3mps"]))
    print("Part D efficiency sensitivity (0.4 mF, leak corner):")
    for r in rows_d:
        print("  eg %.2f ei %.2f Ppk(3.0) %.3f W E %.3f J exc lo/nom/hi %.3f/%.3f/%.3f mJ first v0 lo/nom/d310/hi "
              "%s/%s/%s/%s" % (r["eta_gear"], r["eta_inv"], r["p_peak_3mps_W"], r["e_3to190_J"],
                                r["e_excess_3mps_lo_mJ"], r["e_excess_3mps_nom_mJ"], r["e_excess_3mps_hi_mJ"],
                                r["first_v0_ovp_lo_mps"], r["first_v0_ovp_nom_mps"], r["first_v0_ovp_d310_mps"],
                                r["first_v0_ovp_hi_mps"]))
    print("Part E staged absorption (21.588 V):")
    for r in rows_e:
        print("  eg %.1f ei %.2f %-6s %-10s Vmax(3.0) lo/nom/hi %.3f/%.3f/%.3f V  first v0 lo/nom/d310/hi %s/%s/%s/%s"
              % (r["eta_gear"], r["eta_inv"], r["c"], r["mode"], r["vmax_3mps_lo_V"], r["vmax_3mps_nom_V"],
                 r["vmax_3mps_hi_V"], r["first_v0_ovp_lo_mps"], r["first_v0_ovp_nom_mps"],
                 r["first_v0_ovp_d310_mps"], r["first_v0_ovp_hi_mps"]))
    print("Part F 25 A 'T' ramp:")
    for r in rows_f:
        print("  %-5s v(P>cap) %.4f m/s first v0 %s P(3.0) %.2f W P(2.5) %.2f W"
              % (r["charger"], r["v_power_exceeds_25A_mps"], r["first_v0_ovp_25A_04mF_leak_mps"],
                 r["p_25A_at_3mps_W"], r["p_25A_at_2p5mps_W"]))


if __name__ == "__main__":
    main()

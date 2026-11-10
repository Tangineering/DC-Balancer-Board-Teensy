"""bt8_transient_sim.py - battle-test round 8, transient-simulation lens, against detailed_design_IC1.md revision 11.

Stdlib only. Run from the repo root:  .venv_hil/Scripts/python.exe docs/reviews/battery_isolation_2026-11-07/calc/bt8_transient_sim.py
Inputs are values stated in IC1 rev 11 (section/figure cited at each constant), in earlier calc scripts (cited), or
in the repo's own tools (tools/drive_ripple.py, tools/hil_plant_sim.py, teensy_controller/drive_controller_coeffs.h).
ASSUMED marks a value with no primary in the repo.

Sections
  1  Revision-8 LB-entry resistors (R_MS3, R_VC1c, R_BL3/R_BL2, R_PGL): thresholds, timing, leakage, tolerance.
  2  Fixed window split r 0.85 (code 718): steady point, the eFuse start on the FC-only bus, and the C_DV fallback.
  3  D-s exit on a traction request: the 0 A hold (43-62 ms) against the fw v37 drive law, held vs running state.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))


def hdr(n, s):
    print("=" * 110)
    print(f"[{n}] {s}")
    print("=" * 110)


# ============================================================================================================ 1
hdr(1, "Revision-8 LB-entry resistors")
R_MS1, R_MS2, R_MS3 = 100e3, 16.2e3, 22e3          # IC1 Fig. 2 / Fig. 6
VREF_LO, VREF_HI = 1.242 * 0.99, 1.242 * 1.01       # TLV3011B ref +/-1 % (calc6 s4 window 8.69-9.15 V reproduced below)
for ib in (10e-12, 1e-9, 10e-9):                     # 10 pA typ (IC1 5.3 item 3); 1 nA, 10 nA ASSUMED stress values
    shift_node = ib * R_MS3 * (R_MS1 + R_MS2) / R_MS2
    print(f"  U_MS input bias {ib*1e9:6.3f} nA through R_MS3: node-threshold shift {shift_node*1e3:7.3f} mV")
for cin in (5e-12, 15e-12):                          # IN+ capacitance incl. pad, ASSUMED
    print(f"  R_MS3 x C_in {cin*1e12:4.0f} pF = {R_MS3*cin*1e9:6.1f} ns (exit-hold-check sample 150 us; drain slope effect nil)")
# drain to the U_MS crossing with R_MD 15 ohm || R_MB 3.3k || R_MS 116.2k, from 21.5 V and 15.95 V
r_par = 1 / (1 / 15 + 1 / 3.3e3 + 1 / 116.2e3)
for v0 in (21.5, 15.95):
    for c in (47e-6, 100e-6, 221e-6):
        t = r_par * c * math.log(v0 / 9.17)
        print(f"  dump {v0:5.2f} V -> 9.17 V, C_mod {c*1e6:4.0f} uF: {t*1e3:5.2f} ms (+ ~0.0002 ms R_MS3) vs T_drain,max 10 ms")
# open R_MS2 (row F56) with R_MS3: IN+ clamp current
for vn in (13.5, 21.5):
    print(f"  open R_MS2, node {vn:4.1f} V: IN+ clamp current {(vn-3.6)/(R_MS1+R_MS3)*1e3:5.3f} mA (rev 7 text: up to 0.215 mA)")
# VC1 tap in a pack-negative open (D_VC1 clamps VC1 to -V_F)
for vf in (0.25, 0.40, 0.55):
    print(f"  pack-negative open, D_VC1 V_F {vf:4.2f} V: pin 20 = {-vf/2:+.3f} V (pad abs min -0.5 V); BQ29200 VC1 {-vf:+.2f} V vs -0.3 V")
# BAL_OK worst case
R1, R3 = 150e3, 47e3
for r2 in (82e3, 100e3):
    for tol in (0.0, 0.01):
        r2w, rtop = r2 * (1 - tol), (R1 + R3) * (1 + tol)
        rth = r2w * rtop / (r2w + rtop)
        vmin = (2.0 + 5e-6 * rth) * (r2w + rtop) / r2w
        print(f"  BAL_OK R_BL2 {r2/1e3:4.0f}k tol {tol*100:.0f} %: VBAL+ for VIH 2.0 V with 5 uA leakage = {vmin:5.2f} V "
              f"(entry floor LIMIT_V_BATT_MIN 7.4 V: margin {7.4 - vmin:+.2f} V)")
# PROFILE gate
for voh in (2.9, 3.3):
    vg = voh * 100e3 / (100e3 + 22e3 + 1e3)
    print(f"  PROFILE VOH {voh:.1f} V: Q_CS/Q_MP gate {vg:.2f} V vs BSS138 VGS(th) max 1.5 V (overdrive {vg-1.5:.2f} V); "
          f"gate tau (23k x 100 pF ASSUMED) {23e3*100e-12*1e6:.1f} us")

# ============================================================================================================ 2
hdr(2, "Fixed window split r 0.85 at code 718: steady point and eFuse start on the FC-only bus")
K_DROOP, RE_MAX, V0 = 0.30, 2.0136, 15.95           # ino:3098; setDroopMdac; hil_plant_sim V_BUS_DROOP_V0
g = K_DROOP / (RE_MAX * 0.85)
print(f"  g_FC {g:.4f}; firmware code (uint16_t)(g*4095) = {int(g*4095)} (IC1 states 718)")
R_PATH, OC_FC, INA0 = 0.064, 1.4, 0.10              # bt7 s1; ino OC_FC; INA253A1 zero (calc11)
for lab, R in (("design chain", RE_MAX * g), ("bench-scaled", 0.16 * g / 0.298), ("bench floor 0.16 V/A, no g-scaling (ASSUMED bound)", 0.16)):
    for p_in, aux in ((13.0, 0.02), (14.05, 0.15)):
        vb = V0
        for _ in range(200):
            vc = vb - R_PATH * p_in / vb
            vb = 0.5 * vb + 0.5 * (V0 - R * (p_in / vc + aux))
        ifc = p_in / vc + aux
        print(f"  {lab:46s} R {R:5.3f}: P_in {p_in:5.2f} W aux {aux:.2f}: V_bus {vb:5.2f} V_chg {vc:5.2f} I_fc {ifc:5.3f} A "
              f"| SC-1(a) margin {vc-13.0:+.2f} V | OC_FC margin {OC_FC-ifc-INA0:+.3f} A")
print("  eFuse start (entry step 6) on the FC-only bus: I_fc = aux + C_mod x slew (+ module start current if it overlaps)")
worst = []
for c in (47e-6, 100e-6, 150e-6, 221e-6):           # S0-11 acceptance 47-221 uF
    for sl in (4.17e3, 5.79e3):                      # V/s at C_DV 10 nF (IC1 7.5)
        for aux in (0.02, 0.15):
            ii = c * sl
            ifc = aux + ii
            v = V0 - RE_MAX * g * ifc - R_PATH * ii
            flag = "OC_FC (with INA zero)" if ifc + INA0 > OC_FC else ""
            if ii > 0.6:
                flag += " ; S0-11 inrush > 0.6 A"
            worst.append((ifc, c, sl, aux))
            if aux == 0.15:
                print(f"    C_mod {c*1e6:4.0f} uF slew {sl/1e3:4.2f} V/ms aux {aux:.2f}: inrush {ii:5.3f} A, I_fc {ifc:5.3f} A, "
                      f"V_chg dip to {v:5.2f} V  {flag}")
cmax = 0.6 / 5.79e3
print(f"  inrush <= 0.6 A at the max slew 5.79 V/ms holds only for C_mod <= {cmax*1e6:5.1f} uF; S0-11 accepts up to 221 uF")
cdv = 10e-9 * 5.79e3 / (0.6 / 221e-6)
sl_min = 4.17e3 * 10e-9 / cdv
print(f"  fallback 'raise C_DV': C_DV >= {cdv*1e9:5.1f} nF for 0.6 A at 221 uF; min slew {sl_min/1e3:4.2f} V/ms; ramp 0 -> 15.95 V "
      f"{15.95/sl_min*1e3:4.1f} ms + UVLO delay 1.24 ms (scaled with C_DV? TODO(verify: SLVSE94G)) = {15.95/sl_min*1e3+1.24:4.1f} ms")
print("   vs the ERR_MOD_DUMP_ON sample 10 ms after chargerHasPower() (IC1 Table 16 states 'ramp at most about 5 ms')")
print("   vs the regen-pulse budget (eFuse 4.4-5.6 ms of the 5.3-6.4 ms chain, calc4 s11) - Stage 2 only")
for istart in (0.45, 0.97):                          # module input at the sample, Table 8a allowance (IC1 9.7 step 6)
    for c in (47e-6, 100e-6):
        ifc = 0.15 + c * 5.79e3 + istart
        print(f"  overlap: module start {istart:.2f} A during the ramp, C_mod {c*1e6:3.0f} uF, aux 0.15: I_fc {ifc:5.3f} A "
              f"{'> OC_FC' if ifc + INA0 > OC_FC else '<= OC_FC'} (gate C-3 measures; a 65-170 ms start never overlaps)")

# ============================================================================================================ 3
hdr(3, "D-s exit on a traction request: 0 A hold against the fw v37 drive law")
import drive_ripple as dr            # noqa: E402
import hil_plant_sim as hps          # noqa: E402
co = dr.repo_drive_coeffs()
pl = dr.hil_plant_params()
print(f"  coeffs {co['source']} TS {co['TS_US']} us, I rail +/-{co['I_MAX']}; plant m_eff {pl['m_eff']}, k_f {pl['k_f']}, b {pl['b_lin']}")


def run(v_target, hold_s, mode, ramp=None, T=4.0, dt=1e-3):
    n = co["NSTATES"]
    ad, bd, cd, dd, lv = co["AD"], co["BD"], co["CD"], co["DD"], co["L"]
    imin, imax = co["I_MIN"], co["I_MAX"]
    x = [0.0] * n
    v, cut, held = 0.0, True, 0.0
    cmd_hist = [0.0, 0.0, 0.0]
    vh = [0.0, 0.0, 0.0]
    vmax, imaxseen, ipk_first = 0.0, 0.0, 0.0
    t_rel = 0.05 + hold_s
    for k in range(int(T / dt)):
        t = (k + 1) * dt
        sp = 0.0 if t < 0.05 else (v_target if ramp is None else min(v_target, (t - 0.05) * ramp))
        i_cmd = cmd_hist[-2]
        f = pl["k_f"] * i_cmd
        if abs(v) < hps.V_STICTION and abs(f) <= hps.F_COULOMB:
            v = 0.0
        else:
            v += (f - math.copysign(hps.F_COULOMB, v if abs(v) >= hps.V_STICTION else f) - pl["b_lin"] * v) / pl["m_eff"] * dt
        vh.append(v); vh.pop(0)
        if k % 2 == 0:
            holding = 0.05 <= t < t_rel
            if abs(sp) < dr.V_SP_ZERO_THRESH_MPS or (holding and mode == "reset"):
                if not cut:
                    x = [0.0] * n
                cut = True
                held = 0.0
            else:
                cut = False
                e = sp - vh[-2]
                u = dd * e + sum(cd[j] * x[j] for j in range(n))
                uc = max(imin, min(imax, u))
                x = [bd[i] * e + lv[i] * (uc - u) + sum(ad[i][j] * x[j] for j in range(n)) for i in range(n)]
                held = 0.0 if holding else uc        # mode 'run': controller unaware of the override
        cmd_hist.append(held); cmd_hist.pop(0)
        vmax = max(vmax, v)
        imaxseen = max(imaxseen, abs(i_cmd))
        if t_rel <= t < t_rel + 0.1:
            ipk_first = max(ipk_first, abs(i_cmd))
    return vmax, imaxseen, ipk_first


for vt, ramp in ((1.0, None), (2.0, None), (1.0, 1.0)):
    base = run(vt, 0.0, "run", ramp)
    for hold in (0.043, 0.062):
        r_run = run(vt, hold, "run", ramp)
        r_rst = run(vt, hold, "reset", ramp)
        lab = f"step 0->{vt} m/s" if ramp is None else f"ramp {ramp} m/s2 to {vt}"
        print(f"  {lab:20s} hold {hold*1e3:4.0f} ms | no hold: v_pk {base[0]:.3f} (os {100*(base[0]/vt-1):5.1f} %) I_pk {base[1]:5.2f} A"
              f" | held, law running: v_pk {r_run[0]:.3f} (os {100*(r_run[0]/vt-1):5.1f} %) I at release {r_run[2]:5.2f} A"
              f" | held, law reset: v_pk {r_rst[0]:.3f} (os {100*(r_rst[0]/vt-1):5.1f} %) I at release {r_rst[2]:5.2f} A")
print("  Bus-side: the release current is a motor-phase current at near-zero speed; it is bounded by the 12 A rail in every")
print("  case, so no bus or switch rating is reached. The held-law-running row is a launch-quality item of ruling OR-2'.")

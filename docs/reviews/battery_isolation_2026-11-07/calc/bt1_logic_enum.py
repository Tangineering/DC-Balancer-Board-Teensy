"""Battle-test round 1, logic/sequencing lens: exhaustive enumerator of the IC1 rev-3 control network.

Target: detailed_design_IC1.md revision 3 (sections 5.1-5.3, 6, 9, 10, 11).
Stdlib only. Run: python bt1_logic_enum.py > bt1_logic_enum_output.txt

Model (all from the design text; line refs are to detailed_design_IC1.md):
  * Teensy GPIO p33,p35,p10,p28,p29,p30,p31,p32 in {L,H,Z}; p34 (pump) in {T(toggling),L,H,Z}; p20 in {L(WDOG asserted),Z}.
    Z = high-Z with the board pulls of Fig. 2/5 (R_P33, R_P34, R_P35, R_P10 10k to GND; RT1987 EN bodge 10k pull-downs).
  * p33 Z is NOT a logic LOW: R_N1 10k (3V3) -> D_N33 BAT54 -> pin 33 -> R_P33 10k (GND) forms a divider (Fig. 2, l.262-268).
  * FF1: /CLR = N1 (wired-AND of eq. 1, l.520), CLK = p33 via 1k/1nF, D=/PRE=3V3.
  * Pump: PUMP_OK = 1 only while p34 toggles AND U_PD has 5V (U_PD VCC = 5V, l.274); otherwise it falls in 43-76 ms.
  * VOK channel k (Fig. 4): OKk_N open-drain pulled up by R_UPk to the LB 5V tap; LOW = OK.
    Q_RGk clamps EN_RG while OKk_N is HIGH. VOK = NOR(OK1_N, OK2_N) (U_NOR at 3V3).
  * EF_EN = FF1.Q AND PUMP_OK AND (VOK OR FCQ) (eq. 5); R_SDP holds SHDN low when U_AND is unpowered.
  * S_GNDk ON = NOT(FF1Q_SB AND NOT UC1trip) AND VBT_T present (gate supply, Fig. 1, l.230, 247).
  * S_CHG ON = FF1Q_SB AND NOT Gk high AND VBT_T present (eq. 7).
  * SGk_ON (LB) = HIGH when Q_Rk pulls SGk_RB LOW; an open SB cable reads LOW (= "not enhanced") (Fig. 5).
  * X = FF1./Q OR SG1_ON OR SG2_ON; D-BT-SQ on = p32 AND NOT X (eq. 8).
  * D-BT-EN on = p28 AND NOT FCQ (eq. 9); D-BC-RG on = p30 AND OK1 AND OK2 (eq. 10); D-BC-FC on = p31; D-MT-EN on = p29.
Invariants:
  (a) charger powered AND pack bonded (S_GND channel ON)                    -> violation
  (a') ML0227 configuration = charger powered AND bonded AND D-BT-SQ on     -> violation (sense bypassed)
  (b) loop = charger fed from VBUS (D-BC-FC, or D-MT-EN->V-MOT->D-BC-RG with V-MOT not above VBUS)
            AND charger powered AND D-BT-SQ on AND D-BT-EN on              -> violation
"""
import itertools, math

# ----------------------------------------------------------------------------------------------
# 0. Analog facts used by the logic model
# ----------------------------------------------------------------------------------------------
print("=" * 94)
print("Section 0: analog facts that decide logic levels")
print("=" * 94)
V33 = 3.3
for vf in (0.20, 0.25, 0.32):          # BAT54 V_F range at ~0.15 mA (BAT54LT1/D: 0.24 V typ @0.1 mA, 0.32 V max @1 mA)
    i = (V33 - vf) / 20e3               # R_N1 10k + R_P33 10k
    p33 = i * 10e3
    n1 = p33 + vf
    print(f"  p33 Hi-Z, BAT54 VF {vf:.2f} V: pin33/CLK = {p33:.3f} V, N1(/CLR) = {n1:.3f} V "
          f"(LVC VIL max 0.8 V, VIH min 2.0 V at VCC 2.7-3.6 V: UNDEFINED band; TODO(verify: SCES794G))")
print("  -> with the pin released, FF1 /CLR is NOT asserted and CLK sits at the input threshold; only PUMP_OK")
print("     (43-76 ms after the last pump edge) or another clear source makes N1 a valid LOW.")

# Ladder settling (Fig. 5: R = 20.0k, 2R = 40.2k, C_LA/C_LB 100 nF; calc ic1_rev3 section 7: tau 2.0 ms)
tau = 20e3 * 100e-9
step = 3.3 / 32
print(f"\n  Ladder output tau = R x C = {tau*1e3:.1f} ms; decode window +/-30 mV (design 7.7)")
for name, w in (("ladder A bit0 FF1.Q", 1), ("ladder A bit1 EF_EN", 2), ("ladder B bits0+1 SG1+SG2", 3),
                ("ladder B bits2+3 OK1+OK2", 12), ("ladder A bit4 UC1_N", 16), ("ladder B bit4 UC2_N", 16)):
    dv = w * step
    t = tau * math.log(dv / 0.030)
    print(f"  {name:28s}: step {dv*1e3:6.0f} mV -> within 30 mV after {t*1e3:4.1f} ms "
          f"(design confirms within 1 ms (9.3 step 4-6) / 2 ms (9.5 step 4, 12.4 item 4))")

# VBUS-tap open on a VOK channel (Fig. 4): BT_k node = REF x R_B2 / (R_O + R_B2)
REF, R_O, R_B2, R_M1, R_M2, R_M3 = 1.242, 301e3, 14.9e3, 99.8e3, 13.6e3, 715.0
bt_open = REF * R_B2 / (R_O + R_B2)
vmot_assert_open = bt_open * (R_M1 + R_M2) / R_M2   # NOT OK -> Q_H on -> R_M3 shorted
print(f"\n  VBUS tap open (R_Bk1a lifted): BT_k = {bt_open*1e3:.1f} mV -> channel asserts OK at V-MOT > "
      f"{vmot_assert_open:.2f} V (i.e. at any live bus)")

# Loop gain when VOK is falsely TRUE with BT_BUS closed (regen window between pulses, V-MOT = VBUS)
print("\n  Bus-fed loop with BT_BUS closed (Ag105 regulates NET pack current through its sense):")
print("    P_chg = (I_set + I_L + s*P_aux/(Vp*eta_b)) * Vp/eta / (1 - s/(eta*eta_b))")
Vp, eta, eta_b, I_set, I_L, P_aux, VBUS = 7.8, 0.88, 0.90, 1.75, 0.6, 16.0 * 0.15, 16.0
for s in (0.15, 0.5, 0.79, 0.85):
    den = 1 - s / (eta * eta_b)
    if den <= 0:
        print(f"    BT share s={s:.2f}: loop gain >= 1 -> unbounded until eFuse I_OL / Ag105 2.5 A ceiling")
        continue
    p = (I_set + I_L + s * P_aux / (Vp * eta_b)) * Vp / eta / den
    print(f"    BT share s={s:.2f}: P_chg = {p:5.1f} W = {p/VBUS:4.2f} A at {VBUS} V "
          f"(eFuse I_OL 1.84-2.16 A -> latch-off <= 233 ms if above)")

# ----------------------------------------------------------------------------------------------
# 1. Static network enumerator
# ----------------------------------------------------------------------------------------------
X = "X"   # unknown logic level

def AND(*a):
    if any(v == 0 for v in a): return 0
    if all(v == 1 for v in a): return 1
    return X

def OR(*a):
    if any(v == 1 for v in a): return 1
    if all(v == 0 for v in a): return 0
    return X

def NOT(a):
    return X if a == X else 1 - a

def lvl(p):         # GPIO with a pull-down, as seen by a gate/EN through its resistor
    return {"L": 0, "H": 1, "Z": 0}[p]

def evaluate(g, c, fault, ff1_prev, pump_prev):
    """One settled evaluation. Returns dict of states. g: GPIO dict; c: conditions; fault: string."""
    v33 = 0 if fault == "3V3_LB_open" else 1
    v5 = 0 if fault == "5V_LB_open" else 1
    vbtt = 0 if fault in ("F_T_open", "C_VT_short") else 1
    cable = 0 if fault == "SB_connector_open" else 1

    # pump: toggling + 5V driver; 'transient' keeps the previous level for up to 43-76 ms
    pump_live = 1 if (g["p34"] == "T" and v5 and v33) else 0
    pump_ok = pump_live if c["settled"] else (1 if pump_live else pump_prev)

    # comparators (3V3). currents: chg_hi > U_C2 trip, dis_hi > U_C1 trip
    uc1_trip = 1 if (c["ipack"] == "dis_hi" and v33) else 0
    uc2_trip = 1 if (c["ipack"] == "chg_hi" and v33) else 0
    fcq = lvl(g["p31"])
    d5_trip = 1 if (c["ibt"] == "hi" and fcq and v33) else 0   # armed after 10 ms; settled view
    bq = c["bq_ovp"]
    p20_low = 1 if g["p20"] == "L" else 0

    # N1 wired-AND; p33 Z -> X contribution (analog 1.5-1.8 V)
    p33_src = {"L": 0, "H": 1, "Z": X}[g["p33"]]
    hard_low = pump_ok == 0 or uc1_trip or uc2_trip or d5_trip or bq or p20_low
    if hard_low or p33_src == 0:
        n1 = 0
    elif p33_src == X:
        n1 = X
    else:
        n1 = 1
    if not v33:
        n1 = 0
    # FF1
    if n1 == 0:
        ff1 = 0
    else:
        clk_edge = {"L": 0, "H": c["p33_edge"], "Z": X}[g["p33"]]
        if n1 == X:
            ff1 = X if (ff1_prev == 1 or clk_edge != 0) else 0
        else:
            ff1 = 1 if (ff1_prev == 1 or clk_edge == 1) else (X if clk_edge == X else 0)
    if fault == "FF1_stuck_high":
        ff1 = 1
    ff1q_sb = AND(ff1, v33, cable)          # open cable -> Q_A on R_PA -> LOW

    # VOK channels
    def ok_k(k):
        if not v5:
            return 1                           # OKk_N pulled to a dead rail = LOW = "OK"
        vm = c["vmot"]                        # 'above' (> assert), 'band' (between release and assert), 'bus' (= VBUS)
        tap_open = (fault == "VBUS_tap_pad_lift") or (fault == "VBUS_tap_open_ch1" and k == 1)
        if tap_open and c["vmot_live"]:
            return 1
        if vm == "above": return 1
        if vm == "band": return c["ok_hold"]  # hysteresis: holds previous
        return 0
    ok1, ok2 = ok_k(1), ok_k(2)
    vok = AND(ok1, ok2, v33)
    if fault == "U_NOR_stuck_high": vok = v33

    src = OR(vok, fcq)
    ef_en = AND(ff1, pump_ok, src, v33)
    efuse_on = OR(ef_en, 1 if fault == "eFuse_FET_short" else 0)

    # power-path switches
    d_mt = lvl(g["p29"])
    d_bc_fc = lvl(g["p31"]) or (1 if fault == "D_BC_FC_short" else 0)
    en_rg = AND(lvl(g["p30"]), ok1, ok2)
    d_bc_rg = OR(en_rg, 1 if fault == "D_BC_RG_short" else 0)
    d_bt_en = AND(lvl(g["p28"]), NOT(fcq))
    if fault == "D_BT_EN_short": d_bt_en = 1

    # VCHG-IN feed and its source
    vmot_from_bus = (c["vmot"] in ("bus",)) and d_mt and c["vbus_up"]
    vmot_regen = c["vmot"] in ("above", "band")
    fed_bus_fc = 1 if (d_bc_fc and c["vbus_up"]) else 0
    fed_bus_rg = d_bc_rg if vmot_from_bus else 0
    fed_regen = d_bc_rg if vmot_regen else 0
    vchg_in_fed = OR(fed_bus_fc, fed_bus_rg, fed_regen)
    fed_from_bus = OR(fed_bus_fc, fed_bus_rg)

    hold_up = 1 if (fault == "stage3_C_HU" and c["chu_charged"]) else 0
    charger_powered = OR(AND(efuse_on, vchg_in_fed), hold_up)

    # SB
    g_high = AND(NOT(AND(ff1q_sb, NOT(uc1_trip))), vbtt)       # S_GND gates enhanced
    if fault == "S_GND1_short": sgnd_on = 1
    else: sgnd_on = g_high
    s_chg = AND(ff1q_sb, NOT(g_high), vbtt)
    sg_on = AND(g_high, cable, v33)                              # readback (LB)
    xlock = OR(NOT(ff1), sg_on)
    if fault == "X_open": xlock = 0
    d_bt_sq = AND(lvl(g["p32"]), NOT(xlock))

    bonded = sgnd_on
    viol_a = AND(charger_powered, bonded)
    ml0227 = AND(charger_powered, bonded, d_bt_sq)
    loop = AND(charger_powered, fed_from_bus, d_bt_sq, d_bt_en)
    return dict(n1=n1, ff1=ff1, pump_ok=pump_ok, vok=vok, ef_en=ef_en, efuse=efuse_on, chg=charger_powered,
                bonded=bonded, s_chg=s_chg, d_bt_sq=d_bt_sq, d_bt_en=d_bt_en, d_bc_rg=d_bc_rg,
                viol_a=viol_a, ml0227=ml0227, loop=loop, uc2=uc2_trip, uc1=uc1_trip, sg_on=sg_on)

FAULTS = ["none", "5V_LB_open", "3V3_LB_open", "VBUS_tap_pad_lift", "VBUS_tap_open_ch1", "SB_connector_open",
          "F_T_open", "C_VT_short", "eFuse_FET_short", "U_NOR_stuck_high", "D_BC_RG_short", "D_BC_FC_short",
          "D_BT_EN_short", "X_open", "S_GND1_short", "FF1_stuck_high", "stage3_C_HU"]
PIN3 = ("L", "H", "Z")
pins = ["p33", "p35", "p10", "p28", "p29", "p30", "p31", "p32"]

def conditions():
    # pre-trip states only (ipack normal, BT current low, no OVP): the trips are the bounds, not the states
    for vmot, settled, vbus_up, p33_edge, ff1_prev, pump_prev, chu in itertools.product(
            ("above", "band", "bus"), (True, False), (1, 0), (0, 1), (0, 1), (0, 1), (0, 1)):
        yield dict(vmot=vmot, settled=settled, ipack="normal", ibt="lo", bq_ovp=0, vbus_up=vbus_up,
                   ok_hold=1 if vmot != "bus" else 0, p33_edge=p33_edge, vmot_live=1, chu_charged=chu), ff1_prev, pump_prev

print("\n" + "=" * 94)
print("Section 1: exhaustive static enumeration (GPIO x conditions x single fault)")
print("=" * 94)
summary = {}
examples = {}
n_states = 0
for fault in FAULTS:
    cnt = {"viol_a": 0, "ml0227": 0, "loop": 0}
    for combo in itertools.product(PIN3, PIN3, PIN3, PIN3, PIN3, PIN3, PIN3, PIN3):
        g = dict(zip(pins, combo))
        # prune pins irrelevant to the invariants (p35/p10 only inject trips -> safe direction)
        if g["p35"] != "L" or g["p10"] != "L":
            continue
        for p34 in ("T", "Z"):          # static L/H behave as Z for PUMP_OK (C_P1 coupling)
            for p20 in ("Z",):          # p20 LOW only adds a clear source (safe direction)
                g2 = dict(g, p34=p34, p20=p20)
                for c, ff1_prev, pump_prev in conditions():
                    # a not-settled state is only meaningful with a previously HIGH pump
                    if not c["settled"] and not pump_prev:
                        continue
                    if c["ipack"] != "normal":
                        continue      # trips are the bound; the pre-trip state is the reachable one
                    r = evaluate(g2, c, fault, ff1_prev, pump_prev)
                    n_states += 1
                    for k in cnt:
                        if r[k] == 1:
                            cnt[k] += 1
                            key = (fault, k)
                            if key not in examples:
                                examples[key] = (g2, c, ff1_prev, pump_prev, r)
    summary[fault] = cnt
print(f"  evaluated {n_states} (GPIO, condition, fault) states")
print(f"  {'fault':22s} {'(a) powered&bonded':>20s} {'ML0227 config':>14s} {'(b) bus loop':>13s}")
for f, cnt in summary.items():
    print(f"  {f:22s} {cnt['viol_a']:>20d} {cnt['ml0227']:>14d} {cnt['loop']:>13d}")

print("\n  First counterexample per (fault, invariant):")
for (f, k), (g, c, fp, pp, r) in examples.items():
    gs = " ".join(f"{p}={g[p]}" for p in ("p33", "p34", "p28", "p29", "p30", "p31", "p32", "p20"))
    cs = f"vmot={c['vmot']} vbus_up={c['vbus_up']} settled={c['settled']} ff1_prev={fp} pump_prev={pp} chu={c['chu_charged']}"
    rs = " ".join(f"{x}={r[x]}" for x in ("ff1", "pump_ok", "vok", "ef_en", "chg", "bonded", "d_bt_sq", "d_bt_en"))
    print(f"  [{f} / {k}] {gs} | {cs} | {rs}")

# ----------------------------------------------------------------------------------------------
# 2. Unpowered / reset / hang defaults (claim (c))
# ----------------------------------------------------------------------------------------------
print("\n" + "=" * 94)
print("Section 2: reset / hang defaults (all GPIO Z, pump stopped)")
print("=" * 94)
gz = {p: "Z" for p in pins}; gz.update(p34="Z", p20="Z")
for label, ff1_prev, pump_prev, settled in (("warm reset from Idle (FF1 clear, PUMP_OK still H), t < 43-76 ms", 0, 1, False),
                                            ("warm reset mid-window (FF1 set, PUMP_OK still H), t < 43-76 ms", 1, 1, False),
                                            ("after PUMP_OK falls (t > 76 ms)", 1, 1, True)):
    for vmot in ("above", "bus"):
        c = dict(vmot=vmot, settled=settled, ipack="normal", ibt="lo", bq_ovp=0, vbus_up=1, ok_hold=0, p33_edge=1,
                 vmot_live=1, chu_charged=0)
        r = evaluate(gz, c, "none", ff1_prev, pump_prev)
        print(f"  {label:66s} vmot={vmot:5s}: N1={r['n1']} FF1={r['ff1']} EF_EN={r['ef_en']} bonded={r['bonded']} "
              f"chg={r['chg']}")
print("  FF1=X means the latch state is not determined by the design: /CLR sits at 1.78-1.80 V and CLK at")
print("  1.50-1.55 V. The release of pin 33 from a driven LOW is itself a slow rising CLK edge. The table 12 row")
print("  'Unpowered, reset, hung: p33 Z (pull-down), FF1 clear' and HR5 'FF1 needs a pin-33 edge' are not met")
print("  until PUMP_OK falls (43-76 ms).")

# ----------------------------------------------------------------------------------------------
# 3. Firmware sequence replay with reset/hang injection
# ----------------------------------------------------------------------------------------------
print("\n" + "=" * 94)
print("Section 3: firmware sequences (design 9.3-9.9) with checks after every step")
print("=" * 94)
BASE = dict(p33="L", p34="T", p35="L", p10="L", p28="H", p29="H", p30="L", p31="L", p32="H", p20="Z")
SEQS = {
    "9.5 regen entry/hold/exit": [("p10", "L"), ("p5", "H"), ("p33", "H"), ("confirm", 2), ("p30", "H"),
                                  ("hold", "vmot=above"), ("hold", "vmot=bus"), ("p30", "L"), ("p33", "L"),
                                  ("confirm", 2), ("p5", "L")],
    "9.7 FC entry/exit": [("p10", "H"), ("p5", "H"), ("p33", "H"), ("confirm", 2), ("p28", "L"), ("p30", "L"),
                          ("p31", "H"), ("hold", "vmot=bus"), ("p31", "L"), ("p33", "L"), ("confirm", 2),
                          ("p28", "H"), ("p10", "L"), ("p5", "L")],
    "9.9 + ino State 99 phases (from an FC window)": [("p31", "L"), ("p30", "L"), ("p33", "L"),
                                                     ("p27", "L"), ("p28", "L"), ("p31", "H"),   # ino:8306-8316
                                                     ("wait", 10), ("p31", "L"), ("p30", "H"), ("p29", "L"),  # :8324-8325
                                                     ("wait", 10), ("p30", "L"), ("p34", "L")],
}
for name, seq in SEQS.items():
    print(f"\n  {name}")
    for fault in ("none", "eFuse_FET_short", "SB_connector_open", "stage3_C_HU", "VBUS_tap_pad_lift", "5V_LB_open"):
        g = dict(BASE); ff1 = 0; vmot = "bus"; chu = 0; bad = []
        if name.startswith("9.9"):
            g.update(p33="H", p28="L", p31="H"); ff1 = 1; chu = 1
        for i, (k, v) in enumerate(seq):
            if k in g:
                edge = 1 if (k == "p33" and g[k] != "H" and v == "H") else 0
                g[k] = v
            else:
                edge = 0
            if k == "hold":
                vmot = v.split("=")[1]
                chu = 1
            c = dict(vmot=vmot, settled=True, ipack="normal", ibt="lo", bq_ovp=0, vbus_up=1, ok_hold=1 if vmot == "above" else 0,
                     p33_edge=edge, vmot_live=1, chu_charged=chu)
            r = evaluate(g, c, fault, ff1, 1)
            ff1 = r["ff1"] if r["ff1"] != X else 1
            for inv in ("viol_a", "ml0227", "loop"):
                if r[inv] == 1:
                    bad.append(f"step {i} {k}={v}: {inv}")
        print(f"    fault {fault:18s}: " + ("no violation" if not bad else "; ".join(bad[:4])))
print("\n  Notes: the 9.9 trace reproduces the ino State-99 phases 0-2 (ino:8299-8331), which design 9.9 step 4")
print("  keeps ('run the existing drains'): FC_CHARGE and REGEN are raised again AFTER pin 33 is LOW, i.e. in the")
print("  bonded mode. stage3_C_HU models C_HU on VCHG-IN_M still above the Ag105 UVLO at the bonding instant.")

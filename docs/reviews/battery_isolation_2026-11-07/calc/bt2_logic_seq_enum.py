"""Battle-test round 2, LOGIC / SEQUENCING lens: exhaustive model check of the IC1 revision-4 control network.

Target: detailed_design_IC1.md revision 4 (sections 5.1-5.3, 6, 8, 9, 10, 11, 12).
Stdlib only. Run: python bt2_logic_seq_enum.py > bt2_logic_seq_enum_output.txt

Hardware model (design section 6, equations 1-13; Figures 1-6):
  GPIO p33,p35,p10,p28,p29,p30,p31,p32 in {L,H,Z}; p34 in {T (toggling), S (static)}; p20 in {L (WDOG1_B), Z}.
    Z = high-Z with the board pulls (R_P33/R_P34/R_P35/R_P10 10k to GND at the buffer inputs; 10k RT1987 EN bodges).
    rev 4: p33 Z -> U_P33 input 50 mV -> P33B LOW -> N1 LOW (calc4 section 6). Z therefore reads L everywhere.
  N1 = P33B & PUMP_OK & UC1_N & UC2_N & p20 & !(D5trip & FCQarmed) & !BQ_OUT   (eq. 1)
  FF1: cleared while N1 L; set by a P33B rising edge (5.6-9.9 us later) while N1 H; else hold   (eq. 2)
  PUMP_OK = p34 toggling & 5V & 3V3   (eq. 3)
  CHk = OKk & BPk; VOK = CH1 & CH2   (eq. 4; OKk = V-MOT above the assert level; BPk = bus >= 9.3-9.8 V)
  EF_EN = FF1 & PUMP_OK & (VOK | FCQ); FCQ = p31   (eq. 5)
  S_GND ON = !(FF1Q_SB & !UC1trip); S_CHG ON = FF1Q_SB & S_GND gates low   (eq. 6, 7)
  X = !FF1 | SG1_ON | SG2_ON; D-BT-SQ = p32 & !X   (eq. 8)
  D-BT-EN = p28 & !FCQ ; D-BC-RG = p30 & OK1 & OK2 & BP1 & BP2 ; D-BC-FC = p31 ; D-MT-EN = p29   (eq. 9-12)
  Charger powered = EF_EN & VCHG-IN >= eFuse UVLO (12.38-12.88 V rising)   (section 5.3)
Invariants:
  (a)  charger powered AND pack bonded (S_GND ON)
  (a') (a) AND D-BT-SQ conducting = the ML0227 configuration (sense bypassed, module fed)
  (b)  loop: charger powered AND fed from VBUS (D-BC-FC with the bus up, or D-MT-EN -> V-MOT -> D-BC-RG with V-MOT
       not above VBUS) AND D-BT-SQ AND D-BT-EN
"""
import itertools, math

def hdr(t):
    print("\n" + "=" * 100 + "\n" + t + "\n" + "=" * 100)

# ------------------------------------------------------------------------------------------------
# Section 1: combinational exhaustive enumeration (steady state after every edge has settled)
# ------------------------------------------------------------------------------------------------
LV = ("L", "H", "Z")
FAULTS = [
    None,
    "EFUSE_FET_SHORT",      # F11: charger powered whenever VCHG-IN is fed
    "U_AND_STUCK_H",        # F13b
    "U_OR_STUCK_H",         # SRC always true (not a Table-14 row)
    "U_VA_STUCK_H",         # F15c
    "CH1_STUCK_OK",         # F15b (one channel permits at bus level)
    "FF1_Q_STUCK_H",        # F7
    "FF1Q_SB_STUCK_L",      # U_BF stuck LOW or FF1Q_SB grounded: bonded while FF1 is set (F33 class)
    "U_P33_STUCK_H",        # F32
    "Q_X1_OPEN",            # F16b
    "Q_X2_OPEN",            # F6
    "DBTEN_SHORT",          # F16
    "DBCFC_SHORT",          # F17
    "DBCRG_SHORT",          # F15
    "FCQ_TAP_OPEN",         # M6 pin-31 tap open (not a Table-14 row)
]

def hw(g, env, ff1_prev, fault):
    """Return the settled hardware state for one GPIO vector and environment."""
    p = {k: (v == "H") for k, v in g.items() if k not in ("p34", "p20")}
    v3, v5 = env["v3"], env["v5"]
    if not v3:                       # Teensy and LB share the 3V3 rail: every GPIO is Z, all LB logic dead
        p = {k: False for k in p}
    pump_ok = v3 and v5 and g["p34"] == "T"
    p33b = (p["p33"] or fault == "U_P33_STUCK_H") and v3
    p33b_prev = env["p33_prev_H"] or fault == "U_P33_STUCK_H"
    inj_uc1 = p["p35"] and p["p10"]
    inj_uc2 = p["p35"] and not p["p10"]
    uc1 = env["uc1"] or inj_uc1
    uc2 = env["uc2"] or inj_uc2
    fcq = p["p31"] and fault != "FCQ_TAP_OPEN"
    d5 = (env["d5"] or p["p35"]) and fcq          # Q_D5 conducts only with FCQ armed
    wd = g["p20"] == "L"
    n1 = v3 and p33b and pump_ok and not uc1 and not uc2 and not wd and not d5 and not env["bq"]
    if not n1:
        ff1 = False
    elif p33b and not p33b_prev:
        ff1 = True
    else:
        ff1 = ff1_prev
    if fault == "FF1_Q_STUCK_H":
        ff1 = True
    if not v3:
        ff1 = False                     # U_BF output high-Z (Ioff): Q_A gates on R_PA -> bonded
    ff1q_sb = ff1 and fault != "FF1Q_SB_STUCK_L"
    ok = env["vmot_above"]
    bp = env["bus"]
    ch1 = v3 and ((ok and bp) or fault == "CH1_STUCK_OK")
    ch2 = v3 and ok and bp
    vok = (ch1 and ch2) or (fault == "U_VA_STUCK_H" and v3)
    src = vok or fcq or (fault == "U_OR_STUCK_H" and v3)
    ef_en = (ff1 and pump_ok and src) or (fault == "U_AND_STUCK_H" and v3)
    # clamps: Q_RG1/Q_RB1 from channel 1, Q_RG2/Q_RB2 from channel 2 (unpowered comparators release -> pull-ups dead)
    clamp_ok = (ch1 and ch2) if v3 else True
    en_rg = (p["p30"] and clamp_ok) or fault == "DBCRG_SHORT"
    en_fc = p["p31"] or fault == "DBCFC_SHORT"
    en_mt = p["p29"]
    q_x1 = fcq and fault != "Q_X1_OPEN"
    en_be = (p["p28"] and not q_x1) or fault == "DBTEN_SHORT"
    sgnd_on = (not ff1q_sb) or uc1
    sg_on = sgnd_on
    x = ((not ff1) or sg_on) and fault != "Q_X2_OPEN" and v3
    en_sq = p["p32"] and not x
    vmot_feeds = en_rg and (ok or en_mt)          # V-MOT live from regen or from VBUS via D-MT-EN
    vchg_fed = (en_fc and env["bus"]) or (en_rg and vmot_feeds and (env["bus"] or ok)) or env["resid"]
    efuse_on = ef_en or fault == "EFUSE_FET_SHORT"
    chg_pwr = efuse_on and vchg_fed
    bus_feed = (en_fc and env["bus"]) or (en_rg and en_mt and not ok and env["bus"])
    a = chg_pwr and sgnd_on
    a2 = a and en_sq
    b = chg_pwr and bus_feed and en_sq and en_be
    return dict(ff1=ff1, ef_en=ef_en, sgnd=sgnd_on, sq=en_sq, be=en_be, rg=en_rg, fc=en_fc, chg=chg_pwr,
                a=a, a2=a2, b=b, pump=pump_ok)

def fw_allowed(g, st):
    """Firmware rules of rev 4: REGEN and FC_CHARGE refused unless FF1.Q reads HIGH (section 12.4 item 7)."""
    if (g["p30"] == "H" or g["p31"] == "H") and not st["ff1"]:
        return False
    return True

hdr("Section 1: exhaustive combinational enumeration (fault-free, then single faults)")
pins = ("p33", "p35", "p10", "p28", "p29", "p30", "p31", "p32")
envs = []
for v3, v5, vmot, bus, resid, p33prev, ff1prev in itertools.product((1, 0), (1, 0), (0, 1), (1, 0), (0, 1), (0, 1), (0, 1)):
    for trip in ("none", "uc1", "uc2", "d5", "bq"):
        envs.append(dict(v3=v3, v5=v5, vmot_above=vmot, bus=bus, resid=resid, p33_prev_H=p33prev,
                         ff1_prev=ff1prev, uc1=trip == "uc1", uc2=trip == "uc2", d5=trip == "d5", bq=trip == "bq"))
gvecs = []
for combo in itertools.product(LV, repeat=len(pins)):
    for p34 in ("T", "S"):
        for p20 in ("L", "Z"):
            g = dict(zip(pins, combo)); g["p34"] = p34; g["p20"] = p20
            gvecs.append(g)
print(f"  GPIO vectors {len(gvecs)}, environments {len(envs)}; states per fault {len(gvecs)*len(envs):,}")
print(f"  {'fault':18s} {'(a) hw-only':>12s} {'(a) fw-legal':>13s} {'(a\') fw-legal':>14s} {'(b) hw-only':>12s} {'(b) fw-legal':>13s}  example (fw-legal)")
results = {}
for fault in FAULTS:
    na = na_fw = na2_fw = nb = nb_fw = 0
    ex = None
    for g in gvecs:
        for env in envs:
            st = hw(g, env, env["ff1_prev"], fault)
            if st["a"]:
                na += 1
            if st["b"]:
                nb += 1
            if fw_allowed(g, st):
                if st["a"]:
                    na_fw += 1
                    if ex is None and not env["resid"]:
                        ex = (g, env, "a")
                if st["a2"]:
                    na2_fw += 1
                if st["b"]:
                    nb_fw += 1
                    if ex is None or ex[2] != "b":
                        if not env["resid"]:
                            ex = (g, env, "b")
    results[fault] = (na, na_fw, na2_fw, nb, nb_fw)
    exs = "-"
    if ex:
        g, env, kind = ex
        exs = (f"{kind}: " + " ".join(f"{k}={g[k]}" for k in ("p33", "p28", "p29", "p30", "p31", "p32", "p34"))
               + f" vmot_above={env['vmot_above']} bus={env['bus']} 3V3={env['v3']}")
    print(f"  {str(fault):18s} {na:12,d} {na_fw:13,d} {na2_fw:14,d} {nb:12,d} {nb_fw:13,d}  {exs}")
print("""
  Reading: 'hw-only' counts every GPIO vector, including those firmware refuses; 'fw-legal' applies the rev-4
  refusal (REGEN / FC_CHARGE HIGH only while FF1.Q reads HIGH). 'resid' = board-side VCHG-IN still charged above
  the eFuse UVLO from a previous window (C-D8/C-D10, 20 uF).
  Fault-free: (a), (a') and (b) are UNREACHABLE in every steady state, for every GPIO vector including high-Z,
  with 3V3 or 5V absent, and with any comparator trip. The proof is structural: EF_EN needs FF1.Q and the bond
  needs NOT FF1Q_SB (eq. 5, 6); the FC feed and the BT_BUS clamp are the same pin-31 net (FCQ -> Q_X1), and the
  regen feed is clamped by the same VOK terms that require V-MOT above VBUS.
  Single faults that reach (a) in a firmware-legal steady state: the eFuse bypass class (EFUSE_FET_SHORT,
  U_AND_STUCK_H) only through a still-charged VCHG-IN, and FF1Q_SB_STUCK_L (bonded while FF1 is set, F33 class).
  Steady-state (b) needs a D-BT-EN short in an FC window (F16, D5 cuts it) or a D-BC-RG short with V-MOT at the
  bus and the eFuse on. The steady-state model cannot see the transient cases; sections 2-4 treat them.""")

# ------------------------------------------------------------------------------------------------
# Section 2: timed exits - does the charger input disappear before the bond conducts? (invariant d)
# ------------------------------------------------------------------------------------------------
hdr("Section 2: exit timing - charger input removal against bond conduction (invariant d)")
# Bond: S_GND gate rises toward ~0.85 x VBT (eq. 14: 6.3 V at 7.4 V) with tau 88-114 us (Table 11);
# conduction starts at V_GS(th) 1.2-2.3 V (SLPS632 section 5.1).
vfin = 6.3
t_bond = []
for tau in (88e-6, 114e-6):
    for vth in (1.2, 2.3):
        t_bond.append(tau * math.log(vfin / (vfin - vth)))
tb_min, tb_max = min(t_bond), max(t_bond)
print(f"  S_GND conduction after FF1 clear: {tb_min*1e6:.1f}-{tb_max*1e6:.1f} us (tau 88-114 us, V_th 1.2-2.3 V, final 6.3 V)")
print("  eFuse FET off after EF_EN falls: 0.8-1.5 us (SLVSE94G tSD(dly)) -> the eFuse is always off first.")
print("  But the eFuse output node still holds C_EO 1 uF plus the Ag105's own input capacitance C_mod, which is NOT")
print("  given (Ag105 DS; design section 7.5 'gate S0-11'). The module keeps converting until VCHG-IN_M < 11 V (DS p.19):")
print(f"  {'C_mod':>8s} {'V0':>6s} {'P_in':>6s} {'t_run':>9s} {'overlap with bond':>18s} {'E (ML0227 config, sense bypassed)':>34s}")
for cmod in (0.0, 10e-6, 47e-6, 100e-6, 470e-6):
    for v0, pin in ((13.82, 14.8), (18.0, 22.4), (21.4, 22.4)):
        c = 1e-6 + cmod
        e = 0.5 * c * (v0**2 - 11.0**2)
        t = e / pin
        ov = max(0.0, t - tb_min)
        print(f"  {cmod*1e6:6.0f}uF {v0:6.2f} {pin:6.1f} {t*1e6:7.1f}us {ov*1e6:16.1f}us {e*1e3:30.2f} mJ")
print("""  D-BT-SQ stays enabled 0.3-0.7 ms after FF1 clears (X charge, Table 11) plus the RT1987 turn-off time
  (TODO(verify: RT1987 DS-00)), so any C_mod above about 4 uF puts the module in the ML0227 configuration
  (fed, bonded, output path closed) for the overlap above. The charge is capped by the stored energy (<= 0.11 J at
  470 uF / 21.4 V). Invariant (d) as written ('charger input removed before the bond closes') holds only for the
  eFuse FET, not for the module input, unless C_mod <= ~4 uF (S0-11 must measure it) or the Stage-3 dump FET
  (Q_HU/R_HU, keyed to FF1./Q) is fitted in every stage.""")

# 3V3 slow collapse (brownout band): U_BF and U_AND outputs track VCC; LVC is unspecified below 1.65 V.
hdr("Section 2b: 3V3 slow collapse inside a window (HR5 'with 3V3 absent' claim)")
qa_vth = (0.8, 1.5)         # BSS138 V_GS(th) min/max (BSS138/D p.2)
ra, rp = 4.7e3, 100e3      # R_GAk, R_PAk
vshutf_min = 0.8            # SLVSE94G V_SHUTF min (design Table 7)
k_sd = 22e3 / 23e3          # R_SD 1k into R_SDP 22k
for vth in qa_vth:
    vcc_bond = vth / (rp / (ra + rp))
    print(f"  Q_A V_th {vth:.1f} V: S_GND bond begins when 3V3 falls below {vcc_bond:.2f} V (U_BF HIGH = VCC)")
print(f"  eFuse turns off only when SHDN = 0.957 x 3V3 < V_SHUTF (>= 0.8 V): 3V3 below {vshutf_min/k_sd:.2f} V at the")
print("  minimum threshold; V_SHUTF max is not stated in the design (TODO(verify: SLVSE94G section 6.5)).")
print("""  With Q_A at the high end of V_th and V_SHUTF at its minimum, 3V3 between 0.84 V and 1.57 V gives
  bonded + eFuse ON. In that band U_AND (FF1.Q, PUMP_OK, SRC all tracking VCC) can keep EF_EN at VCC level;
  LVC behaviour below 1.65 V is unspecified. D-BT-SQ follows pin 32 (Teensy, also collapsing) and the RT1987
  EN threshold (TODO(verify: RT1987 DS-00)). The duration equals the 3V3 fall time through that band (rail
  capacitance / load; not in the design). Section 9.10 and Table 13 treat '3V3 lost' as a step to 0 V (Ioff),
  so the claim 'eFuse off ... with 3V3 absent' is proven only for the absent rail, not for the collapse.""")

# ------------------------------------------------------------------------------------------------
# Section 3: firmware sequences, step by step, with the invariants checked after every step
# ------------------------------------------------------------------------------------------------
hdr("Section 3: firmware sequences (design sections 9.2-9.10) - invariant check after every step")

def run(name, steps, env0, fault=None, extra=None):
    g = dict(p33="L", p35="L", p10="L", p28="L", p29="L", p30="L", p31="L", p32="L", p34="T", p20="Z")
    env = dict(env0)
    ff1 = False
    viol = []
    prev33 = False
    for i, (desc, gset, eset) in enumerate(steps, 1):
        g.update(gset); env.update(eset)
        env["p33_prev_H"] = prev33
        st = hw(g, env, ff1, fault)
        ff1 = st["ff1"]
        prev33 = (g["p33"] == "H")
        tags = [k for k in ("a", "a2", "b") if st[k]]
        if tags:
            viol.append(f"step {i} ({desc}): {','.join(tags)}")
    print(f"  {name:62s} fault={str(fault):16s} -> {'no violation' if not viol else '; '.join(viol)}")

base = dict(v3=1, v5=1, vmot_above=0, bus=1, resid=0, uc1=False, uc2=False, d5=False, bq=False)
boot = [("reset: all Z", dict(p33="Z", p34="S", p28="Z", p29="Z", p30="Z", p31="Z", p32="Z"), {}),
        ("setup LOW block", dict(p33="L", p28="L", p29="L", p30="L", p31="L", p32="L"), {}),
        ("self-test pump", dict(p34="T", p32="H"), {}),
        ("st4 latch", dict(p33="H"), {}),
        ("st6 U_C2 inj", dict(p10="L", p35="H"), {}),
        ("st6 re-edge", dict(p33="L"), {}), ("st6 re-edge H", dict(p33="H"), {}),
        ("st6 release", dict(p35="L", p33="L"), {}),
        ("st7 latch", dict(p33="H"), {}), ("st7 U_C1 inj", dict(p10="H", p35="H"), {}),
        ("st7 release", dict(p35="L", p10="L", p33="L"), {}),
        ("st8 latch", dict(p33="H"), {}), ("st8 pump stop", dict(p34="S"), {}),
        ("st8 restart", dict(p34="T", p33="L"), {}),
        ("bring-up", dict(p28="H", p29="H"), {})]
regen = [("idle/run bonded", dict(p28="H", p29="H", p32="H", p34="T"), {}),
         ("1 p10 L", dict(p10="L"), {}), ("3 p33 H", dict(p33="H"), {}),
         ("6 p30 H", dict(p30="H"), {}),
         ("hold: VOK asserts", {}, dict(vmot_above=1)),
         ("hold: VOK releases", {}, dict(vmot_above=0, resid=1)),
         ("hold: next pulse", {}, dict(vmot_above=1)),
         ("exit 1 p30 L", dict(p30="L"), {}), ("exit 2 p33 L", dict(p33="L"), {}),
         ("bonded, VCHG-IN residual", {}, dict(vmot_above=0))]
fc = [("idle bonded", dict(p28="H", p29="H", p32="H", p34="T"), {}),
      ("1 p10 H", dict(p10="H"), {}), ("3 p33 H", dict(p33="H"), {}),
      ("5 BT_BUS drop", dict(p28="L"), {}), ("6 FC_CHARGE", dict(p31="H"), {}),
      ("exit 1 FC_CHARGE L", dict(p31="L"), dict(resid=1)), ("exit 2 p33 L", dict(p33="L"), {}),
      ("exit 3 BT_BUS H", dict(p28="H", p10="L"), {})]
s99 = [("FC window open", dict(p28="L", p29="H", p31="H", p32="H", p33="H", p34="T", p10="H"), {}),
       ("9.9-1 FC_CHARGE/REGEN L", dict(p31="L", p30="L"), dict(resid=1)), ("9.9-2 p33 L", dict(p33="L"), {}),
       ("phase 2", {}, {}), ("phase 3 pump stop", dict(p34="S"), {})]
reset_mid = [("FC window open", dict(p28="L", p29="H", p31="H", p32="H", p33="H", p34="T", p10="H"), {}),
             ("Teensy reset: all Z", dict(p33="Z", p34="S", p28="Z", p29="Z", p30="Z", p31="Z", p32="Z", p10="Z"), dict(resid=1))]
hang_mid = [("regen window, VOK", dict(p28="H", p29="H", p30="H", p32="H", p33="H", p34="T"), dict(vmot_above=1)),
            ("hang: pins static, pump stops", dict(p34="S"), {}),
            ("43-76 ms later", {}, {})]
for fault in (None, "EFUSE_FET_SHORT", "U_AND_STUCK_H", "FF1Q_SB_STUCK_L", "U_P33_STUCK_H", "Q_X1_OPEN", "Q_X2_OPEN", "DBTEN_SHORT", "DBCFC_SHORT"):
    run("Boot + boot self-test (9.3) + bring-up", boot, base, fault)
    run("Regen window entry/hold/exit (9.5)", regen, base, fault)
    run("FC window entry/exit (9.7)", fc, base, fault)
    run("State 99 from an FC window (9.9)", s99, base, fault)
    run("Teensy reset mid FC window (9.10)", reset_mid, base, fault)
    run("Loop hang mid regen window (9.10)", hang_mid, base, fault)
print("""  Notes: steady-state steps only (see sections 2 and 4 for the transient overlaps). 'resid' marks the board-side
  VCHG-IN (C-D8/C-D10) still above the eFuse UVLO after a feed is dropped. With the fault-free network no step of
  any sequence reaches (a), (a') or (b). The eFuse-bypass faults reach (a) on the first bonded step after any exit
  while VCHG-IN is still charged (the 20 uF board side, plus the RT1987 turn-off time, TODO(verify: RT1987 DS-00)).""")

# ------------------------------------------------------------------------------------------------
# Section 4: counterexample traces outside the steady-state model
# ------------------------------------------------------------------------------------------------
hdr("Section 4: counterexample traces")

print("""
 4.1 State 99 under PACK_RETURN_CHANGEOVER as specified in design 9.9 step 3
     ('skip the State-99 FC_CHARGE and REGEN drain phases (ino:8299-8327) and go directly to phase 2').
     The cited range is the whole of ino case 0 and case 1. It contains, besides the two drains:
        ino:8306  commandMotorCurrent(0)                         (the only motor zero on the fault path;
                                                                  triggerFault() ino:7064-7076 does not zero it)
        ino:8308-8309 writeBusSwitch(FC_BUS_ENABLE, LOW) / (BT_BUS_ENABLE, LOW)
        ino:8313-8315 shareIsoFC / shareSpCutFC / shareSpCutBT reset
        ino:8325  digitalWrite(MOT_PWR_ENABLE, LOW)              (the State-99 MOT_PWR teardown of Death 5)
     Phase 2 (ino:8329-8340) then writes REGEN L, MPPT L, FC_REG_ENABLE L, BT_REG_ENABLE L.""")
trace = [
    ("t0   Run cruise, motor command +I, FC_BUS H, BT_BUS H, MOT_PWR H, both boosts ON, bonded", "ok"),
    ("t0   fault -> triggerFault() -> mainState 99 (no pin writes)", "ok"),
    ("t0+  9.9 step 1-2: FC_CHARGE L, REGEN L, pin 33 L (already bonded)", "ok"),
    ("t0+  9.9 step 3: skip ino:8299-8327 -> phase 2: FC_REG L, BT_REG L", "VIOLATION"),
    ("     result: FC_BUS H and BT_BUS H onto two DISABLED boosts; MOT_PWR H; VESC still holds +I", "VIOLATION"),
    ("     path: pack -> VBT -> BT boost L/body diode -> BT_BUS (D-BT-EN forward) -> VBUS -> D-MT-EN -> V-MOT -> VESC", "VIOLATION"),
    ("t0+1 phase 3: pump stops; State 99 latched in that configuration until power cycle", "VIOLATION"),
]
for s, tag in trace:
    print(f"     {tag:9s} {s}")
print("""     Rule broken: CLAUDE.md section 2 and the ino:8251-8255 contract ('closes every path and disables the boosts
     LAST, so no energized path ever points into a disabled converter'). Design 9.9 step 3 also says 'Phase 0
     already has both bus switches LOW', which contradicts its own skip range. The new State-99 host test of
     section 12.11 checks only 'FC_CHARGE and REGEN never HIGH after pin 33 goes LOW'; it would pass this trace.
     The existing suite pins MOT_PWR LOW at t0+10 ms (test_main.cpp:22547), so implementing the skip forces an
     edit of exactly the test that would have caught it.""")

print("""
 4.2 FC charge window in Run (State 2, cruise) - reachable under IC1 Stage 1
     Design 9.7: 'The FC window is permitted only at standstill'. But section 12.2 item 4 requires
     FC_CHARGE_ALLOWED 1 for Stage 1, and section 12.4 item 6 keeps chargingControl()'s window policy and only
     wraps assertFcChargeEnable() with the mode manager. chargingControl()'s State-2 cruise branch opens a window
     whenever charge_goal > 0 (ino:15503-15506: FC_CHARGE_ALLOWED && fcChgEntryOk && ag105VbatnIsolatedFlag &&
     FC_BUS HIGH). No IC1 entry condition, refusal (12.4 item 7 admits CHG_FC in any main state) or host test
     (12.11) excludes State 2. Trace:""")
fc_bus = (0.965, 1.075)    # calc4 section 8 (eta 0.88, pack 7.4-8.4 V, includes 0.15 A aux)
p_max, oc_fc, vbus = 1.247, 1.40, 16.0
for t, s in [
    ("t0", "State 2 cruise, Pi charge_goal > 0, bonded, BT_BUS H"),
    ("t1", "chargingControl() (50 Hz) -> mode manager CHG_ENTERING: pin 33 H, settled confirm, sense check"),
    ("t2", "BT_BUS dropped (9.7 step 5); assertFcChargeEnable(true): FCQ H -> Q_X1 clamps D-BT-EN in hardware"),
    ("t3", "Ag105 starts; bus = FC only; traction continues (no traction-exit rule for FC windows, 9.6 is regen-only)"),
]:
    print(f"     {t:3s} {s}")
for ib in fc_bus:
    head_pmax = (p_max - ib) * vbus
    head_oc = (oc_fc - ib) * vbus
    print(f"     charger + aux on the bus {ib:.3f} A: traction headroom {head_pmax:4.1f} W to P_MAX 1.247 A, "
          f"{head_oc:4.1f} W to OC_FC 1.4 A (single sample -> State 99)")
print("""     Any cruise traction above about 2.7-5.3 W saturates the H-20 (P_MAX) and above 5.2-7.0 W latches OC_FC; with
     the D-BT-EN clamp in hardware the firmware cannot bring BT back without first closing the window. In
     addition the [RER] regen arm (1 kHz) can fire inside CHG_FC; the refusal rule admits REGEN HIGH in CHG_FC,
     and no transition CHG_FC -> CHG_REGEN is specified. The chargingControl() else-branch also writes
     REGEN_ENABLE LOW every 50 Hz period outside its own window (ino:15524), so the two owners of pin 30 disagree
     whenever the 1 kHz [RER] arm and the 50 Hz brake detection disagree.""")

print("""
 4.3 eFuse bypass (F11, U_AND_STUCK_H, F35, F36-M2) at a VOK release in a regen window
     Fault-free: VOK release -> EF_EN L -> eFuse off in ~18-38 us (Table 11), before V-MOT reaches VBUS (62-124 us).
     With the eFuse bypassed the only cut is the four clamps -> D-BC-RG EN LOW -> RT1987 turn-off, whose time is
     NOT specified (Table 11 'TODO(verify: RT1987 DS-00)'). Once V-MOT falls to VBUS, D-MT-EN conducts and the
     charger is fed from the bus while D-BT-SQ and D-BT-EN are on (BT_BUS may stay closed in a regen window):
     invariant (b) for t_off(D-BC-RG) on EVERY pulse, plus the 20 uF board-side VCHG-IN energy.
     Detection: ERR_EFUSE_BYPASS needs 'an I2C ACK with EF_EN L', i.e. VCHG-IN fed while EF_EN is LOW. Rev 4
     refuses every feed in the bonded mode (12.4 item 7) and feeds only with EF_EN HIGH in windows, so in service
     the condition never occurs except at these same transients; pin 38 reads the board side (12.5 item 1), and
     IMON is a test point only. The fault is therefore latent until gate C-2 is repeated.""")

print("""
 4.4 Run command arriving during the Idle-entry self-test (9.3, ~420 ms)
     Steps 4, 5, 7 and 8 hold pin 33 HIGH (charge mode) for up to 2 ms each and step 8 for up to 90 ms. Nothing in
     9.3 or 12.4 holds the State 1 -> 2 transition or the motor command during the self-test (only steps 6-7 check
     |I_PACK1| <= 0.5 A, and only before they start). A Pi Run command in that interval puts traction current
     through the Ag105 sense in reverse until U_C1 trips at 2.52-3.50 A; the trip then fails step 4 (expects FF1.Q H)
     -> ERR_CHG_SELFTEST (reboot-only, every window refused), or, in step 8, is indistinguishable from the pump
     clear the step expects. 9.6 holds the motor only inside regen windows.""")


print("""
 4.5 D-BC-FC power-stage short (Table 14 row F17) inside a regen window: invariant (b) on a SINGLE fault
     F17 claims 'Charge mode: eFuse needs VOK or FCQ -> Benign'. But a regen window IS the VOK case: VCHG-IN is
     tied to VBUS through the short, BT_BUS may stay closed (Table 12 regen row), D-BT-SQ is on, so at every VOK
     assert the eFuse feeds the charger from the BUS (section 3 trace above, and section 1: 1,296 fw-legal states).
     Sequence per pulse: V-MOT crosses the assert level -> EF_EN H -> eFuse ramps from VCHG-IN = VBUS (no RT1987
     delay on this path) -> charger draws from VBUS -> BT boost refills VBUS from VBT -> charger output -> VBT.
     V-MOT is not loaded by the charger, so VOK stays asserted; only when D-BC-RG turns on (t_D_ON 8 ms typical,
     no maximum) does V-MOT dump into VBUS through D-BC-RG + the short and fall toward VBUS, release VOK, and cut
     the eFuse; the clamps then turn D-BC-RG off and the next rise repeats the cycle for the whole window
     (up to 30 s).
     Loop gain: the Ag105 regulates the PACK current I_p (sense intact, charge mode) and supplies I_o = I_p + I_L;
     I_L includes the BT-boost input that feeds the charger. With BT share s on the bus:""")
eta_c, eta_b, vchg, vbt = 0.88, 0.90, 8.0, 7.4
k = vchg / (eta_c * eta_b * vbt)
print(f"     dI_L/dI_o = s x V_out / (eta_chg x eta_bt x V_bt) = s x {k:.3f}  (eta_chg 0.88 DS p.20; eta_bt 0.90 ASSUMED)")
for s in (0.25, 0.5, 0.75, 1.0):
    g = s * k
    io = 1.75 / (1 - g) if g < 1 else float("inf")
    sat = io > 2.5
    print(f"     s = {s:.2f}: loop gain {g:.2f} -> I_o = 1.75 / (1 - g) = {('inf' if io == float('inf') else f'{io:.2f} A'):>8s}"
          f" {'-> saturates at the module limit (>= 2.5 A rated)' if sat else ''}")
for iol in (1.84, 2.16):
    print(f"     eFuse I_OL {iol:.2f} A at VBUS 16 V = {iol*16:.1f} W in -> I_o up to {iol*16*eta_c/vchg:.2f} A before the eFuse limits")
print("""     Bounds that do NOT act: U_C2 (pack current stays regulated at 1.75 A < 2.65 A), the eFuse I_OL (1.42 A of
     input at a 2.5 A output < 1.84 A), G1/G2 (not applied in regen windows, 12.7 items 3-4), ERR_PROFILE_OC
     (I_p is still 1.75 A). The only bound is the VOK duty cycle. F17's own detection column names 'V_chg with
     FC_CHARGE and REGEN LOW', but Table 16 has no fault for it, so the short is latent and the first regen window
     after it runs the loop. The same unfed-V_chg check would also expose F15 (D-BC-RG short: VCHG-IN = V-MOT = VBUS
     in the bonded mode) before any window.
     Magnitude: the loop current flows only once the module is converting. In the isolated interval (VOK assert
     to D-BC-RG on, t_D_ON 8 ms typical, no maximum) a cold module at the measured 65-170 ms start (facts_prior
     section 6) draws little; once D-BC-RG conducts, regen holds V-MOT above the release level only at a regen
     current of roughly (0.112-0.16 V) / R_path, and at that power regen, not the BT boost, feeds the charger.
     The loop is therefore large in exactly the configurations the design is aiming for: a module that starts
     within the pulse (the S0-6 GO case, 5.3-6.4 ms allowance on the 19 ms pulse) or one kept powered across
     VOK releases (Stage 3 C_HU). Per isolated interval, at the module limit: up to about 22.7 W x 8 ms = 0.18 J;
     with Stage 3 the module is warm at every assert, so the loop forms on every pulse of every window.""")

hdr("Section 5: invariant verdicts")
print("""  (a) charger powered AND bonded: PROVEN unreachable in every steady state of the fault-free network, all GPIO
      vectors incl. high-Z, rails absent, any trip (section 1). Transient: holds for the eFuse FET (0.8-1.5 us vs
      >= 18.6 us bond) but NOT for the module input unless C_mod <= ~4 uF (section 2); slow 3V3 collapse band
      0.84-1.57 V not covered (section 2b). Single faults: eFuse-bypass class with a charged VCHG-IN; FF1Q_SB stuck
      LOW (entry confirmation catches it, cable-open F33 does not - already adjudicated).
  (b) loop: PROVEN unreachable fault-free (FC feed and BT clamp share the pin-31 net; regen feed clamped by VOK).
      Single fault: D-BC-FC short gives (b) at every VOK assert in a regen window, at the module output limit (4.5);
      eFuse bypass gives (b) for the unspecified RT1987 turn-off time at every VOK release (4.3),
      latent in service; D-BT-EN short in an FC window bounded by D5 (F16).
  (c) unpowered / reset / hang defaults: PROVEN for reset (FF1 clears at once) and hang (43-76 ms); every RT1987 EN
      on its pull-down at reset. State 99 as specified (4.1) is NOT a safe latched default.
  (d) every exit removes charger input before the bond: holds for the eFuse switch; module input residual as (a).""")

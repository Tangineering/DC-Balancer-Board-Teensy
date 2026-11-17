# Phase C notes: doc_fw (firmware-facing sections of the design document, 2026-11-15)

Scope: `docs/charger_bq25798_wiring_design_2026-11-05.md` sections B.9, D.2-D.5, F and G, the r9-26 summary row, and
`hardware/charger_evm_r8/decisions_2026-11-12/round2/dec2_firmware_rules_2026-11-12.md`. Every change is an exact-match
scripted replacement with a count check. Superseded text is kept in the form (**Superseded 2026-11-15, REVIEW <ID>:** "old
text"). CRLF endings are kept (0 bare LF), and every table row has its header's pipe count. The design document grew
from 4680 to 4682 lines (FR-50 and FR-51 are new rows, and the REG17 row is new; the poll-schedule line pair merged into
one line). No pin, net, copper, value, fitted part, CLAUDE.md, `.ino`, CSV or WORK_QUEUE file was changed.

## 1. Status per finding

| ID | Status | Where | Change and evidence |
|---|---|---|---|
| R2-FW-0 (S2) | FIXED (requirement); value and response left to the operator | new FR-50; FR-22 (xxxiv); D.5 item (8); B.9 | FR-50 restates the single-sample OV_CHG latch (`teensy_controller.ino`:2285 `LIMIT_V_CHG_MAX 24.0f`, :7436, outside any `BENCH_TEST` guard) for REGEN held HIGH: V_chg = 0.994 x V-MOT, so V-MOT > 24.15 V latches State 99 mid-brake. Levels: U101 OVP 21.588-25.019 V rising / 19.899-22.927 V falling as fitted, 23.256-26.863 / 21.439-24.614 V with lever (a); BQ25798 VBUS 24 V recommended (SLUSDV2C 6.3 p.7), VBUS_OVP 25.2-26.2 V rising and 24.0-24.8 V falling (6.5 p.9), 30 V absolute maximum (6.1 p.7); C-D8/C-D10 35 V; RT1987 VOUT 40 V; VESC cut unknown; pin-38 full scale 29.27 V (`SCALE_V_CHG`, ino:2030). It lists threshold, response (State 99, charger-only trip, flag) and filter (one sample or N-sample dwell) as TODO(decide: J.2 item 74). Interim: the code stays unchanged. Host test (xxxiv) |
| R2-FW-1 | FIXED (detection and flag); recovery RECORDED as an operator decision | new FR-51; FR-08; FR-23 EX2; FR-22 (xxx) and (xxxv) | Detection: EX2 NACK (or ACK with VBUS_PRESENT_STAT = 0 and no D-BT-SQ short) with V_chg in 10.76-19.50 V (UVLO rising max 10.548 V + 2 %; OVP falling min 19.899 V - 2 %) sets `CHG_EFUSE_LATCHED`; P5/QUAL LOW, REGEN unchanged, no State 99. T1 keeps the flag until V_chg < 8.0 V or FLT HIGH. Options (A) wait for Idle, (B) in-Run recovery with a retry cap, both TODO(decide: operator). TCKE1401NM DS Rev. 3.0 section 7.15 Table 7.3 p.11, section 7.11 Table 7.2, section 7.5 p.7, Table 10.3 (tCL_PLIM 130-190 ms, tCL_PLIM_FLAG 1.0-3.5 ms) |
| R2-FW-2 | FIXED | G.1 poll schedule and ADC row; FR-20 | REG35-36 and REG41 are no longer polled in Run (REG2F = 0x3E disables them; SLUSDV2C 7.3.10 p.47, Table 7-56 p.114). The T-B-16 diagnostic mask is REG2F = 0x3C (IBUS, IBAT, TDIE; 18 ms scan). `chg_vbus_mv` carries V_chg. The T-B-16 row (section I, doc_hw) still says TODO(design: G.1); G.1 now answers it |
| R2-FW-3 | FIXED | G.1 ADC row; FR-23 EX1; FR-48(a); FR-22 (xxxvii) | REG2E = 0xA0 in Run, 0xE0 one-shot, 0x60 after the clear (Table 7-55 p.113: bit 7 ADC_EN, bit 6 ADC_RATE, bits 5-4 ADC_SAMPLE, reset 30h). tADC_CONV 6 ms at 10b (6.5 p.16). The EX1 one-shot TODO is closed by section 7.3.10 p.47 (ADC_EN clears after a 1-shot). The L.8 CHG-R1-03 TODO (section L) is not mine |
| R2-FW-4 | FIXED (proposal text only) | D.5 r9-25 table, item (7) | Lists `CLAUDE.md`:145, :153-155, :157-158, :295, :354, :989-990 and :1034 with the replacement intent. `CLAUDE.md` not edited |
| R2-FW-5 | FIXED | FR-02; FR-20; FR-22 (xxxix) | `FAULT_I2C_CHARGER` 0x0800 and `FAULT_CHARGER_STAT` 0x1000 retired (reserved); `ERR_I2C_CHARGER` 0x0C and `ERR_CHARGER_STAT` 0x0D stay allocated (append-only enum, ino:2457-2458) and unused; no BQ25798 NACK enters State 99. I2C-dead rule: 3 consecutive NACK frames (provisional, TODO(calibrate: T-B-20)) set `CHG_I2C_DEAD`. Offset 51 bits: 7:5 CHG_STAT (REG1C, Table 7-37 p.87), 4 PG_STAT (REG1B bit 3, Table 7-36 p.85), 3 VINDPM_STAT (REG1B bit 6), 2 IINDPM_STAT (REG1B bit 7), 1 REG20/REG21 fault, 0 image verified |
| R2-FW-6 | FIXED in B.9 | B.9 | QUAL raised at the first VBUS_PRESENT_STAT = 1 after EN_CHG = 0 and REG11 = 0 read back, dropped at PG_STAT + 50 ms (FR-04). **Records agent:** README line ~321 "QF (QUAL HIGH, raised only on PG_STAT = 1)" still needs the same correction |
| R2-FW-7 | FIXED | FR-01; B.9; FR-22 (xxxvi) | Pins 22, 24-26, 38-41 `INPUT_DISABLE` before the timer; keeper error 0.079 V (V_chg, V_rgn) and 0.046 V (V_bus, 46.4/10 kOhm, ino:2028) at 1 uA |
| R2-FW-8 | FIXED | G.1 never-write list; new REG17 row; REG18 row | REG18 decode from Table 7-34 p.83 (reset by WD and REG_RST); REG17 not written, POR 0x7A (Table 7-33 p.82: VSET 3h = VREG - 400 mV, ISETH 3h unchanged, ISETC 1h = 20 %); writing it with an NTC fitted is TODO(decide: firmware round with EM18). REG47 = DPDM driver (Table 7-69 p.127). **Not mine:** B.5 (line ~2081) still groups REG47 under "OTG/backup never-write rules" |
| R2-FW-9 | FIXED | FR-28; FR-22 (xl) | Feed in a loop-context block entered per FR-45 tick-counter advance; the timer sets its own stage bits and never feeds |
| R2-FW-10 | FIXED in D.3 | D.3 row-22 proposed text and prose | Band 17.58-38.22 uA/A at 0.6-1 A, unspecified below 0.6 A (TCKE1401NM Table 10.2). **Records agent:** HANDOFF.md:303-305 still says "The CSV half is done (r9-11)"; it should say that row 22 is the one pending CSV edit |
| R2-FW-11 | FIXED | dec2 decision 4b(ii) | Replaced by the F.3 T16 signature; V_chg is upstream of U101 (cr.net, DD FR-30) |
| R2-FW-12 | FIXED (items 3, 4); items 1, 2 done by doc_hw | D.4; dec2 section 3 | D.4 row list adds 10, 16, 17, 23 (r9-11 freed-pin rows) and notes the pending row 22. The rules-file T-B sentence now points to the FR-22 host test and proposes a T-B-15 step to the section I owner |
| R2-LOG-2 | FIXED in F.4 | F.4 hang paragraph | < 17.0 uA (sim 4 section 5.3). B.1 and J.2 item 69 were done by doc_hw |
| R2-DOC-4 | FIXED in FR-12 | FR-12(b1) | The 9.46-10.14 V band lives only inside the superseded r8 text; the live (b1) text now states 9.055-10.548 / 8.203-9.934 V and closes the Table 10.1 layout TODO (H.15) |
| R2-DOC-5 | FIXED, with a new result | F.5 T10 step 2 | "the last 40-100 ms" -> 55-181 ms on the H.21(g) hand basis. Recomputed on the sim 5 basis (appendix A): 16.0 -> 8.0 V takes 0.083-4.39 s (0.083-1.38 s with EVM draw >= 0.391 mA). An RT1987 sourced leak above 98.5 uA prevents proof (b). The H.21(g) row (section H, doc_hw) still says 55-181 ms and its Check column still says "FR-08(b) uses proof (c)": TODO(recalc: H.21(g) on the sim 5 basis) |
| R2-SIM-5 | RECORDED (no instance in my sections) | - | The 4.01 s figures are in H.21/H.23(q), fixed by doc_hw. FR-12 contains no 4.01 s figure |
| R2-INT-4 / R2-INT-5 / R2-INT-2 (D.4 instances) | FIXED | D.4 record | SSQ -G-S, workshop-stock J-TAP harness, nine-wire W5 bundle, no positions 11/13 |
| R2-LOG-0 / R2-SIM-1 (F.3 instance) | FIXED | F.3 T2 row | Sim 4 section 5.6a: 5-30 us, 1.810 V, 50.7 us |

## 2. Open items left for the operator (not decided here)

- FR-50: the `LIMIT_V_CHG_MAX` value, the response (State 99, charger-only trip or flag) and the filter; tie to J.2 item 74.
- FR-51: recovery of a latched U101 inside a Run (options A and B).
- REG17 image with a pack NTC fitted (EM18, T-E-09): firmware-round decision.
- The I2C-dead 3-frame count is provisional (TODO(calibrate: T-B-20)).

## 3. For the later agents

- J.2 item 74 (section J, doc_hw) should cite FR-50 as the firmware consequence of its ruling.
- Section I: T-C-04 needs a latched-U101 step for FR-51 (TODO(design: section I)); T-B-15 could add the CHG_STAT-after-
  termination-then-P5-LOW step; the T-B-16 TODO(design: G.1) can now cite G.1 (REG2F = 0x3C, 18 ms).
- Section H: H.21(g) decay 55-181 ms and its Check column "proof (c)" are stale against F.5 (see R2-DOC-5).
- Section L: L.8 CHG-R1-03 TODO(verify: SLUSDV2C Table 7-55) is closed by section 7.3.10 p.47.
- Section B.5: REG47 is the DPDM driver, not OTG/backup.
- README Table 5.x (QUAL wording) and HANDOFF.md:303-305 (row 22) as stated above.
- New numbers: T10 proof (b) decay 0.083-4.39 s (sim 5 basis); RT1987 leak limit 98.5 uA; FR-51 window 10.76-19.50 V
  (21.01 V upper bound with lever (a)); OV_CHG mid-brake latch above V-MOT 24.15 V; pin-38 full scale 29.27 V.

## Appendix A. T10 proof (b) recompute script (scratch, phase C)

```python
"""Scratch recompute (phase C doc_fw, R2-DOC-5): F.5 T10 proof (b) decay, VCHG-IN 16.0 V -> 8.0 V.

Physics and parameter sets copied from hardware/charger_evm_r8/sim/efuse_decay/run.py (sim 5 part b,
b_ode_t(), lines 281-330 and 411-486): C_in 17.0/28.4 uF, R_div38 88.7k || R_str 961.0k, C_evm 51.4 uF x 0.40/1.00,
I_evm 0..2.31 mA, U101 IQ 0/0.5/1.2 mA, body diode Vf 0.40/0.55/0.70 V at 1 mA (ideality 1, 27 C),
RT1987 sourced leak 0..120 uA below 15.9 V. U101 FET closed above the UVLO falling threshold
(sim 5 Table 1 corners 8.203 / 9.28 typical / 9.934 V), open below it (two nodes coupled by the body diode).
"""
import math
from scipy.integrate import solve_ivp

C_IN = (17.0e-6, 28.4e-6)
RP = 1 / (1 / 88.7e3 + 1 / 961.0e3)
C_EVM = (51.4e-6 * 0.40, 51.4e-6)
I_EVM = {"zero": 0.0, "0.1mA": 0.1e-3, "0.2mA": 0.2e-3, "floor": 0.391e-3, "typ": 1.08e-3, "max": 2.31e-3}
IQ = (0.0, 0.5e-3, 1.2e-3)
VF = (0.40, 0.55, 0.70)
UVLOF = (8.203, 961.0 / 116.0 * 1.12, 9.934)
ISRC = (0.0, 120e-6)
VT = 8.617333262e-5 * 300.15
V0, VSTOP, VBUS = 16.0, 8.0, 15.9


def t_case(cin, cev, iev, iq, vf, uvf, isrc):
    isd = 1e-3 / (math.exp(vf / VT) - 1.0)

    def src(v):
        return isrc * 0.5 * (1 + math.tanh((VBUS - v) / 0.01)) if isrc > 0 else 0.0

    ct = cin + cev
    # phase A: FET closed, one node
    ev = lambda t, y: y[0] - uvf
    ev.terminal, ev.direction = True, -1
    s = solve_ivp(lambda t, y: [(-y[0] / RP - iq - iev + src(y[0])) / ct], (0, 120), [V0], events=ev,
                  rtol=1e-10, atol=1e-10, max_step=0.005)
    if not len(s.t_events[0]):
        return float("inf")
    t1 = s.t_events[0][0]
    if uvf <= VSTOP:
        return t1

    # phase B: FET open, body diode VOUT -> VIN
    def f(t, y):
        vin, vev = y
        idd = isd * (math.exp(min((vev - vin) / VT, 200.0)) - 1.0)
        tq = 0.5 * (1 + math.tanh((vin - 4.7) / 0.2))
        te = 0.5 * (1 + math.tanh((vev - 3.5) / 0.2))
        return [(-vin / RP - iq * tq + idd + src(vin)) / cin, (-iev * te - idd) / cev]

    e8 = lambda t, y: y[0] - VSTOP
    e8.terminal, e8.direction = True, -1
    s2 = solve_ivp(f, (0, 120), [uvf, uvf], method="Radau", events=[e8], rtol=1e-9, atol=1e-9)
    if not len(s2.t_events[0]):
        return float("inf")
    return t1 + s2.t_events[0][0]


rows = []
for cin in C_IN:
    for cev in C_EVM:
        for ik, iev in I_EVM.items():
            for iq in IQ:
                for vf in VF:
                    for uvf in UVLOF:
                        for isrc in ISRC:
                            rows.append((t_case(cin, cev, iev, iq, vf, uvf, isrc), cin, cev, ik, iq, vf, uvf, isrc))


def summ(label, sel):
    r = [x for x in rows if sel(x)]
    lo, hi = min(r), max(r)
    print("%-48s n=%4d  min %.4f s  max %.4f s" % (label, len(r), lo[0], hi[0]))
    print("    min case:", lo[1:])
    print("    max case:", hi[1:])


summ("all", lambda x: True)
summ("no RT1987 leak", lambda x: x[7] == 0)
summ("I_evm >= floor, no leak", lambda x: x[3] in ("floor", "typ", "max") and x[7] == 0)
summ("I_evm >= floor", lambda x: x[3] in ("floor", "typ", "max"))
summ("I_evm >= typ, no leak", lambda x: x[3] in ("typ", "max") and x[7] == 0)
summ("I_evm zero", lambda x: x[3] == "zero")
# hand check of the H.21(g) estimate: 30 uF x 8 V / 4.4 mA, 57 uF x 8 V / 2.52 mA
print("hand: %.1f ms, %.1f ms" % (30e-6 * 8 / 4.4e-3 * 1e3, 57e-6 * 8 / 2.52e-3 * 1e3))
```

Output (the last four lines are the RT1987 leak sensitivity at 20, 45 and 90 uA and the 8.0 V hold limit):

```
all                                              n=1296  min 0.0827 s  max inf s
    min case: (1.7e-05, 2.0560000000000003e-05, 'max', 0.0012, 0.4, 8.203, 0.0)
    max case: (2.84e-05, 5.14e-05, 'zero', 0.0, 0.7, 9.934, 0.00012)
no RT1987 leak                                   n= 648  min 0.0827 s  max 4.3871 s
    min case: (1.7e-05, 2.0560000000000003e-05, 'max', 0.0012, 0.4, 8.203, 0.0)
    max case: (2.84e-05, 5.14e-05, 'zero', 0.0, 0.4, 8.203, 0.0)
I_evm >= floor, no leak                          n= 324  min 0.0827 s  max 1.3797 s
    min case: (1.7e-05, 2.0560000000000003e-05, 'max', 0.0012, 0.4, 8.203, 0.0)
    max case: (2.84e-05, 5.14e-05, 'floor', 0.0, 0.7, 9.934, 0.0)
I_evm >= floor                                   n= 648  min 0.0827 s  max inf s
    min case: (1.7e-05, 2.0560000000000003e-05, 'max', 0.0012, 0.4, 8.203, 0.0)
    max case: (2.84e-05, 5.14e-05, 'typ', 0.0, 0.7, 9.934, 0.00012)
I_evm >= typ, no leak                            n= 216  min 0.0827 s  max 0.8899 s
    min case: (1.7e-05, 2.0560000000000003e-05, 'max', 0.0012, 0.4, 8.203, 0.0)
    max case: (2.84e-05, 5.14e-05, 'typ', 0.0, 0.7, 9.934, 0.0)
I_evm zero                                       n= 216  min 0.2122 s  max inf s
    min case: (1.7e-05, 2.0560000000000003e-05, 'zero', 0.0012, 0.7, 9.278620689655174, 0.0)
    max case: (2.84e-05, 5.14e-05, 'zero', 0.0, 0.7, 9.934, 0.00012)
hand: 54.5 ms, 181.0 ms
2e-05 5.133143083620105 (2.84e-05, 5.14e-05, 'zero', 0.0, 0.4, 8.203)
4.5e-05 6.5633097469968735 (2.84e-05, 5.14e-05, 'zero', 0.0, 0.4, 8.203)
9e-05 15.97454065004862 (2.84e-05, 5.14e-05, 'zero', 0.0, 0.4, 9.934)
Veq 120uA 9.744578450985996 isrc for 8V 9.851631908231632e-05
```

## Addendum (phase C fix round, 2026-11-15)

H.21 and T-D-11 now follow the F.5 T10 sim 5 decay; the r9-26 row names the fix round. See `notes_phaseC_fix1.md`.

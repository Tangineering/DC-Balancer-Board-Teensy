"""Build the round 1-6 findings ledger for the custom charger board (Path A-C).

Input : cb/digest_study_reviews.md section 3 table (203 keys, generated from review_loop.md).
Output: cb/ledger_table.md and printed counts.
Status: CLOSED / KEPT / CHANGED. Default from the digest CB column (Y->CLOSED, N->KEPT,
P->CHANGED); every departure from that default is an explicit override below with its reason.
"""
import re, sys, pathlib, collections

CB = pathlib.Path(sys.argv[1])
rows = []
pat = re.compile(r"^\| (\d) \| (\d+) \| `([^`]+)` \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([YPN]) \|$")
for line in (CB / "digest_study_reviews.md").read_text(encoding="utf-8").replace("P(fail|load)", "P(fail\u2223load)").splitlines():
    m = pat.match(line.strip())
    if m:
        rows.append(dict(rnd=int(m[1]), n=int(m[2]), key=m[3], sev=m[4].strip(), issue=m[5].strip(),
                         disp=m[6].strip(), tag=m[7].strip(), cb=m[8]))
assert len(rows) == 203, len(rows)

DEFAULT_STATUS = {"Y": "CLOSED", "N": "KEPT", "P": "CHANGED"}

CLOSED_BY_TAG = {
    "a": "The 0.3 m EVM leads W1-W8 do not exist on the CCB ([SCH] 5.2 item 3)",
    "b": "The EIB, the W5 ribbon and the E-leads do not exist; the stages sit on the CCB ([SCH] 6.1)",
    "c": "There is no EVM; the modified part has no CCB footprint ([SCH] 7.2)",
}
KEPT_BY_TAG = {
    "e": "BQ25798 behaviour; the CCB uses the same IC and the same register image ([FW] 5.5.1)",
    "f": "Firmware requirement; the CCB removes no FR obligation ([FW] 5.3)",
    "g": "MB or system fact; the CCB connects to the same MB nets through the same taps ([SCH] 5.2 item 4)",
    "d": "Carrier logic; it carries over with unchanged topology and values ([SCH] 5.1)",
    "d-mech": "Header and MB-interface mechanics; any board in the 22 holes inherits them ([MCH] 1.3)",
    "doc": "Documentation rule; it applies to the CCB documents in the same way",
}
KEPT_PRIORITY = ["e", "f", "g", "d", "d-mech", "doc"]

OV = {
 # ---- CLOSED, with a note where a successor rule exists
 "eib-wireoff-releases-converter": ("CLOSED", "No lead can lift; the two-switch release Q403 + Q401 is kept, and a cracked on-board trace reads LOW through R467-R470 ([SCH] 6.1, 6.2)"),
 "readback-misses-evm-side": ("CLOSED", "U403/U404 sense the U501 ILIM_HIZ and /CE pins on their own traces ([SCH] 6.1; [LAY] 3.6.2 item 2)"),
 "evm-jp14-feed-joint-floating": ("CLOSED", "No R21, JP13 or JP14 footprint; rule 4.2.1 allows only Q403 + R455 between REGN and ILIM_HIZ ([SCH] 7.2 EM3)"),
 "cr-power-pad-coords-on-pin-column": ("CLOSED", "The W1/W2 power-lead pads are deleted; pad 10 and pins 18/19 connect by copper ([SCH] 5.2 item 3; [LAY] 3.3.3). Digest CB: P"),
 "cr-eib-3v3-feed-unprotected-short": ("CLOSED", "No CR-to-EIB 3V3 feed exists; the ex-EIB stages share the one rail behind R375 ([SCH] 5.2 item 2). Digest CB: P"),
 "eib-e1-regn-adjacent-to-ilim-feed": ("CLOSED", "No E-pad row; the successor is [LAY] 3.6.2 item 4 (no part between REGN and ILIM_HIZ except Q403 + R455)"),
 "j101-mated-socket-envelope": ("CLOSED", "No J101; the option-K socket envelope is the new item N-24 (T-K-04)"),
 # ---- CHANGED: still applies, altered form
 # The next five keys were CLOSED until 2026-11-10 (review run 001, finding CCB-R1-17): each still has an on-board
 # cause or a re-derived fix, which is the CHANGED definition, not the CLOSED one.
 "ribbon-4-5-stat-sink-abs-max": ("CHANGED", "No ribbon; the on-CCB causes are a STAT-to-CE_DRV or STAT-to-3V3 trace or solder-bridge short (FR-22, T-C-05) and a pin-6 OUTPUT HIGH firmware fault. R475 1.00 kOhm is kept and holds the STAT sink to 3.06-3.30 mA against the 6 mA abs max; 41 mA without it ([SCH] 6.1). Digest CB: Y"),
 "ribbon-adjacent-short-stat-cedrv": ("CHANGED", "As ribbon-4-5-stat-sink-abs-max; the pin-6-to-CE_DRV short case is kept in FR-22 and T-C-05 ([SCH] 6.1). Digest CB: Y"),
 "tlv3012-ribbon-driver-short-current": ("CHANGED", "R264/R265 deleted; the off-board conductor is now the tap wire F13/F20, and a short to GND draws 3.18-3.30 mA through R325/R348 1.00 kOhm alone, inside the TLV3012B 10 mA limit ([SCH] 6.1). Digest CB: Y"),
 "ground-loops-parallel-returns": ("CHANGED", "The lead and ribbon returns are gone, but the CCB plane joins pads 4 and 14/15 in parallel with the MB GND pour, and the split depends on the MB copper ([SCH] 10.1; [SCH] 10.2 item 5; [SCH] 10.3). T-F-11 is re-scoped to the one-plane partition; T-K-17 measures the pin 4/14/15 currents. Tap shields stay bonded at the board end. Digest CB: Y"),
 "a6-w2-not-beside-star-pads": ("CHANGED", "No W2; the battery return reaches pads 14/15 through the plane, in parallel with the MB GND pour, as ground-loops-parallel-returns ([SCH] 10.2 item 2; [SCH] 10.3). Digest CB: Y"),
 "eib-e6-e7-ce-stat-bridge": ("CHANGED", "The lead bridge is gone; an adjacent-trace or solder-bridge short between the pin-6 and CE nets replaces it as an FR-22 case ([FW] 5.3 FR-22). Digest CB: Y"),
 "t-a-04-criterion-not-datasheet": ("CHANGED", "T-A-04 now checks the CCB's own 50 V X7R parts against the SLUSDV2C effective-capacitance minima at 23.6 V ([SCH] O-1; [BOM] B-4). Digest CB: Y"),
 "bom-26awg-wire-quantity": ("CHANGED", "The lead wire disappears; the wire line shrinks to the taps only ([BOM] 4.4). Digest CB: Y"),
 "efuse-out-schottky-missing": ("CHANGED", "D303 loses its main case (far-end short on 0.3 m leads) but stays fitted; fit or DNP and its leakage beside the LM1084 are open ([SCH] 3.2 item 2, O-12)"),
 "efuse-out-schottky-missing-reopen": ("CHANGED", "As efuse-out-schottky-missing; T-C-04 runs again on the CCB ([SCH] O-12)"),
 "tc04-out-spike-criterion-unattainable": ("CHANGED", "The OUT loop inductance falls to the copper value; the T-C-04 OUT criterion is re-derived for the CCB ([SCH] 3.2 item 2)"),
 "ilim-band-leakage-omitted": ("CHANGED", "R523 49.9 kOhm stays as a BOM choice; the H.4 band is re-derived with on-board leakage ([SCH] O-11)"),
 "raise-latency-i2c-budget": ("CHANGED", "FR-07 caps stay; the on-board bus (no W7) can only add margin ([FW] 5.2 FR-07, 5.3 item 1)"),
 "t3-latency-blocking-i2c": ("CHANGED", "As raise-latency-i2c-budget"),
 "ff-reversal-hold-unattainable-at-100khz": ("CHANGED", "The 100 kHz fallback is less likely without W7; the SCL rise time on the CCB decides it (TODO(measure), [FW] 5.3 item 1)"),
 "run-quiescent-draw-unaccounted": ("CHANGED", "The 55-78 mW Run budget is re-booked for the merged rail and the deleted series parts (TODO(calc), T-K-05)"),
 "run-quiescent-draw-unaccounted-reopen": ("CHANGED", "As run-quiescent-draw-unaccounted"),
 "h15-3v3-load-understated": ("CHANGED", "The 1.82 mA EIB share and the CR load merge onto R375; the logic quiescent budget is re-computed (T-K-05 TODO(calc))"),
 "open-input-failsafe": ("CHANGED", "No removable conductor inside the charger chain; R467-R470 stay for cracked traces and joints on a moving vehicle ([SCH] 6.1). Tap inputs keep their biases"),
 "eib-pin8-backpower-unpowered-outputs": ("CHANGED", "No separate EIB rail; the BAV199 back-feed into the merged rail remains and R474 holds it at 0.3-0.45 V ([SCH] 6.1)"),
 "evm-input-cap-figure": ("CHANGED", "The VCHGOUT ceramic total is the CCB's own, 51.3 uF nominal; the no-electrolytic rule stays ([SCH] 7.2 EM24)"),
 "ce-pullup-link-sense-divider-fails-low": ("CHANGED", "Links L1/L2 disappear; R472/R472b keep separate pads and vias ([SCH] rule 4.2.3; [LAY] 3.6.2 item 3)"),
 "u203-threshold-ignores-sense-offset": ("CHANGED", "U403 threshold re-derived for the CCB divider values ([FW] 5.4 row 33)"),
 "input-path-ir-drop-omitted": ("CHANGED", "R_PATH_RG loses W1/W2, EVM R2 and JP3; the CCB value is TODO(calc: H.19); tests keep 0.19 ohm as a bound ([SCH] 3.2 item 3; [TST] G4)"),
 "efuse-cluster-no-room-at-pad10": ("CHANGED", "The eFuse cluster now competes with the power stage; utilisation is 101 % as drawn ([LAY] 3.2.3, L-1)"),
 "efuse-cluster-no-room-at-pad10-reopen": ("CHANGED", "As efuse-cluster-no-room-at-pad10; the congested region is x 33-41, y 56-67 ([LAY] 3.2.3)"),
 "carrier-no-buildable-layout": ("CHANGED", "Re-opened: the CCB books 1532 mm2 against 1514 mm2 usable (101 %); the remedies reach 78-86 % ([LAY] 3.2.3). Digest CB: N"),
 "carrier-no-buildable-layout-reopen": ("CHANGED", "As carrier-no-buildable-layout; the courtyard DRC of the capture is the gate ([LAY] L-1)"),
 "carrier-copper-unspecified": ("CHANGED", "Stack moves from 2 oz outer to 1 oz outer (B1) or 2 oz inner (B2), because the RQM land pattern has 0.2 mm gaps; current capacity moves to width ([LAY] 3.1.3). Digest CB: N"),
 "cr-and-mb-battery-path-copper-sized-below-ichg": ("CHANGED", "CCB side re-sized: >= 2.5 mm pours at 1 oz, >= 5 vias of 0.3 mm per transition ([LAY] 3.1.4-3.1.5). The MB VBT part stays (T-A-06c, T-F-16). Digest CB: N"),
 "cr-coordinate-convention-mirror-ambiguity": ("CHANGED", "The tab removes the CR pin-11 chamfer corner; the marker moves to (38.90, 76.40) and pin_identity_check.py must run again ([MCH] 1.8; [TST] OT-7). Digest CB: N"),
 "pm4-header-solder-sequence-ambiguous": ("CHANGED", "Option K (socket strips in the MB) and the bonded feet replace the PM4 solder sequence; seat heights move to T-K-04 ([MCH] 1.3.4, 1.4). Digest CB: N"),
 "pm4-header-solder-sequence-ambiguous-reopen": ("CHANGED", "As pm4-header-solder-sequence-ambiguous"),
 "b8-netlist-omits-cr-holes-pads": ("CHANGED", "A new pin-level netlist replaces B.8 ([SCH] 8); BAV199 and SOT-23 pinnings are still TODO(verify) ([SCH] O-9). Digest CB: N"),
 "d103-fallback-contradicts-criteria": ("CHANGED", "D303 criteria stay; whether D303 is fitted at all is re-opened ([SCH] O-12). Digest CB: N"),
 "fallback2-pack-unfused-on-w3-and-bridge-rating": ("CHANGED", "W3 is gone; the fallback-2 fused MB link C-D12 -> C-D11 remains, with VCHG now on CCB copper"),
 "cr-end-strain-relief-anchor": ("CHANGED", "W1-W4 strain relief disappears; tap-lead strain relief within 30 mm stays ([MCH] 1.7.2 item 4)"),
 "ina253-adc-offset-from-charger-return": ("CHANGED", "The return moves from W2 to pads 4/14/15; the MB-GND drop that shifts the ADC remains (T-F-04c, T-F-15)"),
 # ---- KEPT where the digest said P
 "cr-3v3-single-tap-backpower": ("KEPT", "The CCB rail is still fed from one tap T6 through R375; I2C still runs on the MB pull-ups RSDA/RSCL 2.7 kOhm (PM9), R345/R346 DNP ([SCH] 7.2 EM6). Digest CB: P"),
 "tb03-ce-pass-criterion": ("KEPT", "R472/R472b 47.0 kOhm and the /CE >= 3.0 V criterion are unchanged ([SCH] 6.1; T-K-10). Digest CB: P"),
 "ilim-sense-threshold-above-hiz-vil": ("KEPT", "U403 keeps the 0.587-0.650 V threshold below VIL_ILIM_HIZ 0.75 V ([SCH] 6.1). Digest CB: P"),
 "u203-stuck-held-latent-no-entry-test": ("KEPT", "U403 is kept, so its stuck-held latent fault and the T1 step-6 pin-33 proof remain ([SCH] 6.1). Digest CB: P"),
 "imon-vchg-ground-offset-under-charge-current": ("KEPT", "IMON (pin 22) and V_chg (pin 38) still ride the MB-GND drop; T-F-15 still applies ([SCH] 10.4 item 2). Digest CB: P"),
 # ---- KEPT with a specific reason
 "chg-header-strips-10-12": ("KEPT", "The CCB uses the same 1x10 + 1x12 strips; option K adds matching socket strips ([MCH] 1.3.4)"),
 "cr-bottom-over-mb-power-traces": ("KEPT", "Flush tails, no underside parts over MB power copper + 1 mm, polyimide sheet; L4 must now also shield the switch nodes ([MCH] 1.3.5, 1.5; [LAY] 3.1.1)"),
 "bom-mpns-incomplete": ("KEPT", "Re-opened on the CCB BOM: C511/C512/C529-C531, socket strips, adhesive and the snubber have candidate or no MPNs ([BOM] 3.3)"),
 "efuse-ovp-above-bq-rating": ("KEPT", "eFuse OVP 22.61-23.63 V stays and is now the only input OV device in front of U501, since the ACFET pair is omitted ([SCH] 2.1 D2)"),
 "qual-window-single-barrier": ("KEPT", "The QUAL one-shot carries over as U311 (BQ25798-specific) ([SCH] 5.1)"),
 "p5-static-arm-hang": ("KEPT", "Heartbeat monostable U313 and ARM_OK carry over ([SCH] 5.1); T-K-09 step 3 re-proves them with the converter switching"),
 "ilim-clamp-por-adc-error-omitted": ("KEPT", "T-B-23 stays; T-K-10 gates it because the POR ADC samples the ILIM_HIZ pin under switching"),
 "vreg-corruption-no-fixed-pack-ovp": ("KEPT", "The BQ29200 OUT -> U323 -> OVN term and ARM_OK' (U322) carry over; tap T22 and PM11 stay ([SCH] 5.1)"),
 "tc04-in-spike-criterion-omits-mb-vchgin-ratings": ("KEPT", "The eFuse IN side (C302a/b/c, D307) and the MB VCHG-IN end are unchanged; the three-point T-C-04 scope stays ([SCH] 3.1)"),
 "imon-bypass-cap-against-datasheet": ("KEPT", "C305 stays DNP on the same eFuse network ([SCH] 3.1; [BOM] 1.1)"),
 "fcc-rgn-lvc-threshold-vs-rt1987-en-band": ("KEPT", "Comparators U319-U321 (FCC_OFF, FCC_ON, RGN_ON) carry over on the same MB EN taps ([SCH] 5.1)"),
 "pin38-39-adc-overvoltage-on-vmot-excursion": ("KEPT", "Pins 38/39 sense the same MB nodes; FR-49 stays ([FW] 5.2)"),
 "dbtsq-short-unfused-pack-on-vchg": ("KEPT", "D-BT-SQ stays on the MB; a short still puts the pack on VCHG, now on CCB copper; FR-48 stays"), "tps26630-pwp-alternate-nonexistent": ("KEPT", "Resolved in round 3; the CCB uses the same TPS26630RGER ([BOM] 2)"),
}
keys = {r["key"] for r in rows}
missing = [k for k in OV if k not in keys]
assert not missing, missing

out = []
cnt = collections.Counter(); cnt_round = collections.defaultdict(collections.Counter)
cnt_sev = collections.Counter(); departures = []
for r in rows:
    tags = [t.strip() for t in r["tag"].split(",")]
    if r["key"] in OV:
        st, why = OV[r["key"]]
    else:
        st = DEFAULT_STATUS[r["cb"]]
        if st == "CLOSED":
            why = CLOSED_BY_TAG[next(t for t in tags if t in CLOSED_BY_TAG)]
        elif st == "KEPT":
            why = KEPT_BY_TAG[next(t for t in KEPT_PRIORITY if t in tags)]
        else:
            raise SystemExit("P without override: " + r["key"])
    if st != DEFAULT_STATUS[r["cb"]]:
        departures.append((r["key"], r["cb"], st))
    cnt[st] += 1; cnt_round[r["rnd"]][st] += 1
    sevc = "blocker" if r["sev"].startswith("blocker") else ("major" if r["sev"].startswith("major") else "minor")
    cnt_sev[(sevc, st)] += 1
    out.append(f"| {r['rnd']} | {r['n']} | `{r['key']}` | {r['sev']} | {r['tag']} | **{st}** | {why} |")

hdr = ("| Rnd | # | Key | Severity | Tag | Path A-C status | Reason (source) |\n"
       "|---|---|---|---|---|---|---|")
(CB / "ledger_table.md").write_text(hdr + "\n" + "\n".join(out) + "\n", encoding="utf-8")
print("total", len(rows), dict(cnt))
for k in sorted(cnt_round): print("round", k, dict(cnt_round[k]))
print("by severity", {f"{a}/{b}": v for (a, b), v in sorted(cnt_sev.items())})
print("departures from digest CB:", len(departures))
for d in departures: print("  ", d)

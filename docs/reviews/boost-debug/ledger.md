# Ledger — boost-debug (docs/boost-bringup-debug.md)

Re-raise rule: settled items reopen only with new evidence, stated explicitly.

## Active findings

| ID | Status | Finding | Rationale |
|---|---|---|---|
| BOOST-R1-F1 | accepted (major) | Open-loop settle (any fixed value) cannot evidence precharge completion | Measured chain 19.3 ms LB vs 20 ms (3.5% margin, typ-only/no-max spec); ~33 ms with 100 nF CSS → ADC gate on V_bus+V_rgn with timeout is the only variant |
| BOOST-R1-F2 | accepted (major) | CSS 100 nF fix guarantee is bounded, not "any scenario"; SOA claim unsupported | Bound ≤2.9 mF worst-case CSS; measured node 0.4–0.6 mF (6–8× margin); VESC-attached C unmeasured; RT1987 DS §18 has no SOA data |
| BOOST-R1-F3 | settled-caveat (major defect) | Overshoot-arithmetic corners unsupported; empirical coefficient 0.10–0.19 V/A; mechanism OPEN | 12 V corner never occurs (VIN readable in-capture 8.2–8.7 V); both linear and slew models over-predict centre-to-centre parks; COMP probe decides |
| BOOST-R1-F4 | rejected (minor residue) | "Record overstates stress 4×" — backwards | 7–9 A photometrically confirmed 3×; low figure was a rewound-chat artifact (operator ruling); residue: CH2 BW-limit + ∫I dt conventions adopted |
| BOOST-R1-F5 | accepted (major) | Deep dip is NOT an SCP cut — it is the RT1987 soft-start completing (A1), depth set by source/converter limiting (A2); VIN-UVLO alternative also refuted | Conduction 1.77 ms (7× timer), VBUS ramps monotonically DURING the dip, terminates at ΔV→0, no 64 ms retry; VOUT floor 9.68 V > 8.1 V passthrough kills UVLO |
| BOOST-R1-F6 | accepted (minor) | Historic "body-diode pre-charge" = live D-BT-EN conduction into 40 µF-only node (pre-Death-5 firmware); "no pre-charge" scoped to current config | Pixel-proven capture identity + git archaeology; Death-4 conclusion strengthened; wording fixes only |
| BOOST-R1-F7 | accepted (major) | 18.0 V windowed OV threshold fails the tolerance stack | Reading 18.0 → true ≤18.47 V > 18.3 V OVP min and 18 V rec-max (±2% uncalibrated ADC ref dominates ±0.1% dividers); 17.5 V is the max legal window; no window rides out the parks |
| BOOST-R1-F8 | accepted (major) | C_OUT-independence is linear-regime-only; C_C lever has NO share-plant collateral | DS Eq. 12 has no C_C (f_c <0.1%, τ_r <0.1 µs; cost 5–11° of 76–79° PM); both cap levers re-opened as secondary mitigations; CSS-first decision unchanged |
| BOOST-R1-F9 | accepted (minor) | Bleed bullet: unstated assumptions, mis-attributed mechanism, omitted standing dissipation | 6.4 mA ≈ 0.8 ADC LSB is the real share protection; 95–113 mW continuous in Idle/Run/Finish; largely obsoleted by N1 |
| BOOST-R1-F10 | accepted (minor) | Bus ADC path unfiltered/uncalibrated (±0.26 V at 17.5 V), unrealized exposure | All precise voltages scope-sourced; TODO: raw-count logging + 3-point calibration |
| BOOST-R1-F11 | settled-caveat (minor) | 2/8 boundary leaks real ("Confirmed:" over SS-inferred bullet; "any scenario") | Others already hedged by supersession convention; folded into F2/F5 fixes |
| BOOST-R1-N1 | accepted (major) | Park decays ~113 V/s → ~1.5 ms above 17.0 V → persistence filter viable | Flips the doc's "persistence would NOT ride it out"; gate on one decay-confirmation run + masked-fault test |
| BOOST-R1-N2 | accepted (major, pending one run) | OV-ADC node (VBUS 16.85 V peak) vs cursor node (boost-local 17.23 V) discrepancy | Trip margins possibly misjudged; raw-count logging run required before trusting firmware voltage limits |
| BOOST-R1-N3 | accepted (major) | Dip #1 violates charge conservation 14–300× → only ring / CH2 CM-artifact candidates survive | Excludes SCP clamp AND UVLO race; zoomed 20–50 µs/div single-shot is the top bench priority |
| BOOST-R1-N4 | accepted (major, merged into F1) | Fixed settle scales with fitted CSS (~33 ms at 100 nF) | Same fix as F1 (ADC gate) |
| BOOST-R1-N5 | accepted (minor, UNCONFIRMED) | Historic connects plausibly already ISCP-clamped amps-class events | Edge 4.5× faster than gate-ramp prediction; historical hypothesis only |
| BOOST-R1-N6 | accepted (minor) | Scope-metrology conventions (div×scale, trace-centre, chronology, calibration chain) | Adopted into bench-incident conventions; prevents the two errors corrected this run |

## Notes

- Codex round-1 alternatives: **A1 adopted** (deep-dip mechanism, rank 1), **A2 adopted as
  complement** (dip depth), **A3 rejected** (charge conservation; withdrawn by Codex in
  round 2).
- Operator ruling 2026-08-03: the "1.5–1.9 A" text was a rewound-chat-branch artifact
  (K_sns A3-scale unit slip); corrected in the doc; Codex's citation of it was accurate.
- Accepted doc fixes APPLIED 2026-08-03 (operator-approved): header retitle, SCP-bullet and
  timeline supersessions, CSS bounded-guarantee rewrite, conclusions rewrite (ADC gate),
  dual-channel scoping + Confirmed/Inferred split, overshoot-arithmetic scope correction,
  compensation-verdict scoping (C_C/C_OUT re-opened), capture-5 VBUS-reading correction
  (VIN-UVLO retired), UVLO-race refutation, plan-refinement rewrites (18.0 V withdrawn,
  persistence revived, bleed obsoleted, ADC TODO), F6 history corrections (Death-4 row/bullet,
  2-VBUS caption, Ruled-OUT scoping, L54 OVP), park decay supersessions, metrology-conventions
  section + bench-incident skill update. Firmware changes remain unimplemented.
- Bench evidence 2026-08-03 (capture 8, first `G` at CSS = 100 nF): **F1/N4 CONFIRMED**
  in-system (connect completes at 28.3 ms ≈ tD_ON + tON prediction 27.8 ms; ADC gate mandatory,
  now unblocked). **F2's guarantee reasoning partially revised**: the linear-gate-ramp ~26 mA
  inrush model is dead — conduction onset still dumps ~2/3 of the node charge at foldback-class
  ~7 A (sub-ms); CSS bounds the duration/handoff, not the onset current. Retry loop eliminated;
  park now ~17.0 V trace-centre (below the 17.5 V limit). New open item: flat ~0.5–0.9 V
  VOUT−VBUS post-connect differential (fits neither enhanced-diode nor parked-decay model).
- Bench evidence 2026-08-03 (capture 9, VESC attached, D-BT = 100 nF / D-MT = 5.6 nF): first
  observed **SCP-cut + 64 ms retry** (65 ms gap ≈ tSCP_RST) — refines F5 (capture-5 deep dip
  remains a non-cut; cuts do occur at larger node size). **F3 datapoint:** 10 A cut-release →
  ~18 V park (0.21 V/A empirical holds; linear-vs-slew still open). **N2/protection gap:** the
  18 V event is on the boost-local node — invisible to the BUS ADC; firmware cannot protect
  against cut-release parks. **Topology RESOLVED (operator): 470 µF on V-MOT, bus-side lean
  RETRACTED** (circular reasoning — currents inferred from assumed C; widths unresolvable at
  those timebases). Cut-vs-complete now read as onset peak vs the 8.5 A low-VOUT foldback
  (UNCONFIRMED). **F2 partially discharged:** first in-system VESC bound C_VESC ≈ 0.2–0.9 mF
  from the dip-2 charge (bounded in-system only — a proper measurement is still wanted; large
  enough to flip the connect into cut/retry). Capture-8 validation completed: no trip,
  >4 clean `G`s (no-VESC config).

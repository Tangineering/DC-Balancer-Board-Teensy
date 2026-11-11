# Review round 7: dispositions (brief for the fix round)

Findings with verifier verdicts: `work/r7_review7_findings.json` (60 verified, 33 confirmed, 27 partially confirmed, 0 refuted;
7 nits unverified). Every finding is applied unless stated otherwise; where the verifier's `fix` differs from the reviewer's,
the verifier's fix is the default. Decisions that settle conflicts between fixes:

## D-F1 Feet (foot-height-stackup-unbounded, foot-height-ignores-cr-side-bond-line, foot-bed-stackup-omits-bond-line,
foot-bond-thickness-assumption-dropped, foot-placement-*, bed-injection-process, ft2-bed-uninspectable-and-unfillable,
ta09-pull-overloads-psa-path, feet-not-justified-by-own-numbers, vibration-figures-not-bounds, tap-pads-over-ft1-*)

- Controlled CR-side bond: 0.05 mm acrylic transfer tape (TODO(verify: tape datasheet, temperature rating)); h_f = 2.54 - t_bed -
  t_bond = 2.19 mm; block tolerance +0/-0.05 mm. Tolerance budget printed in H.23(i) (header body +-0.13 mm TODO(verify: Samtec
  TSW drawing), CR local bow 0.118 mm, block, tape).
- Measured gate PM4 (2d) after the foot is taped and BEFORE the 22 joints are soldered: dry-seat, 0.05 mm feeler does not enter under
  any header body; 0.15 mm feeler enters and 0.45 mm does not under each foot (FT2 from its -y/+-x sides). Record; fail = re-make the foot.
- Placement aid: CR bottom silkscreen outline of each foot body (and fill-hole ring for FT2); orientation stated.
- Bed: a flowable neutral-cure (alkoxy) silicone only (no oxime, no acetoxy, no paste); FT2 filled through the 1.0 mm hole until it
  appears at the foot edges (visible from -y/+-x); inspection by that witness.
- T-A-09 pull reduced so the bed stress stays inside the service range (state the computed value), or replaced by a push-down
  check; tab Y grip point stated.
- Tap pads over FT1 (F18, F21): taps soldered before T-A-09 is re-run, or T-A-09 runs after PM6: state the order.
- Feet stay fitted by default (operator constraint), but the design text states their effect honestly (8-19 % pin-load cut at 30 g;
  larger share of a tip push; ORDER OF MAGNITUDE, bed confinement not modelled).
- T-A-06 ">= 1.5 mm air" criterion gets an r7 exception for FT1/FT2 and a numeric gap criterion for the dry fit.

## D-F2 W leads (w-leads-cross-unfused-vchgin, w-leads-and-ribbon-cross-pin10-vchgin-post, w-lead-unsupported-span-over-mb,
chassis-tie-30mm-*, chassis-tie-0p02mm-*, w1-w4-over-tap-field, w-band-over-mb-bodges, w5-w3w4-channel-and-crush,
usb-corridor-width-is-receptacle, w5-cable-exceeds-route-max-untested, w5-build-max-semantics)

- A defined CR-top/MB dressing path replaces the straight hole-to-(56, 68.3) segment: every W lead stays >= 2 mm in plan from the
  pin-10 joint, the IN strip (C102a/b/c, R102, D107), the U101 courtyard, the +x pocket, every 1x10 post tip and every tap pad; it
  never lies over the tab X tap field. r7_calc designs the path (e.g. +y on the footprint, across tab Y, +x at the tab Y/tab X
  level) and recomputes the route maxima.
- The CR-top tips of pins 7-10 get a cured RTV dome or Kapton patch (PM4); T-F-12 inspects it.
- Strain relief rule restated: unsupported lead length between anchors <= 30 mm along the lead; anchors = RTV beads on the CR and
  MB-bonded adhesive tie bases on part-free MB mask (positions computed, with tolerance), chassis tie as an extra anchor not
  distance-limited. The 0.02 mm-margin chassis-tie rule is superseded.
- A polyimide strip under the leads where they cross MB parts (SNS-FC) and untented non-GND vias; T-F-12 covers the whole path.
- W5: fixed 0.30 m factory cable; the slack is a defined service loop anchored on the EVM plate; its fold is supported by an RTV
  bead to an insulating spacer on the CR; the "route maximum" is a minimum-fit check for W5.
- USB corridor: the corridor width is the receptacle silkscreen; the plug overmold width is TODO(measure: MS2); W3/W4 and W5 do not
  share the 4.97 mm channel (route around or give the measured clearance).

## D-F3 W1/W2 length vs the hard short (hard-short-shorter-w1w2-not-bounded)

- W1/W2 keep a fixed build length of 0.30 m +- 10 mm (the r3-r6 H.5/H.19/T-C-04 basis stays valid; the slack is an anchored
  service loop). Shorter W1/W2 are NOT adopted: at the 181.6 mm route the in_spike model gives 34.9 V / 73 A at turn-off, 1.1 V
  below D107 VBR(min) 36 V. W3/W4, W6 and W7 use the route maxima after MS2. Record the 181.6 mm numbers in H.5 as the reason.
  This is the r7 answer to "how much does the extension shorten the leads" for W1/W2: it does not, by design.

## D-F4 Tab X tap assignment (tabx-tap-pad-adjacency-unanalysed, tap-adjacency-hv-taps-next-to-teensy-pins, t8-*,
dressed-length-path-crosses-pads, a4-dressing-rule-vs-calc-path, pm3-t2-away-from-tab-x-contradiction,
tf12-r7-tap-isolation-criterion-unattainable)

- r7_calc reruns the assignment with adjacency exclusions (no two of T3/T4/T5 orthogonally adjacent; T6/F07 beside R175 with no GND
  or EN neighbour; T10 not beside T21; T1/T2 HV divider taps not beside a raw Teensy-pin pad; keep T1/T7b and T17/T17r pairs) and
  prints an adjacency check plus an adjacent-pad short table (consequence and detector per pair), including the residual row.
- Dressed lengths are computed on a path the dressing rule allows; residual taps (T8 etc.) are checked for LM1084 crossing too.
- T-F-12 tap isolation criterion restated to what is attainable (per-pair values or ">= 1 MOhm except designed paths").

## D-F5 Regions (low-y-band-overbooked, comparator-band-near-mb-bt-boost, thermal-rule-misses-comparator-band,
r175-thermal-band-no-derating, ms4-survey-misses-co5v-joint-and-comparator-region, f101-r172-derating-input-not-measured,
r7-table-omits-tab-y-allocation, ta06-l4-mask-criterion-*)

- H.23(e2): per-region booking (footprint low-y band, footprint interior, tab X, tab Y) <= 75 % each; the band keeps the
  comparators and the residual pads; the 0.1 % dividers sit in the interior directly beside the band (shortest divider-to-input
  run) - r7_calc places and books them; U123/D108/R178/R179 and decouplers go where the booking passes. H.23(f) re-run for the
  interior's loop-facing corner; the comparator band's distance to the MB BT boost output loop and the 5V copper printed.
- MS4 adds measurement points at the comparator band and the CO-5V joint; R175 gets a derating check (T-A-05).
- T-A-06 L4 mask criterion allows the openings of the double-sided CR's bottom pads.

## D-F6 Electrical leftovers (r276-shared-e8-budget-tc16-criterion, tc16-bridged-run-no-abort-loose-pass,
e1-dressing-vs-90mm-and-fault-limit, eib-epads-inside-usb-corridor-band, evm-eib-not-one-rigid-body,
evm-plate-mount-untested-in-vibration, g1-distance-rationale-misquantified)

- Apply the verifier fixes (T-C-16 abort limit and a criterion tied to the prediction; E3/E4 pickup through the shared E8;
  E1 dressing route that meets 90 mm and the /CE-pad distance; "one rigid body" restated as "on one plate"; EVM plate retention spec
  and a post-run re-check; G1 rationale re-quantified).

## D-H Operator statement 2026-11-10: no maximum height constraint for the MB and its PCBs

Applied after the review-7 fix round as its own patch: the 13.14 mm Ag105 envelope and lid clearance stop being limits
(W5 fold gate, MS1 height part, MS2 lid item, J.2 W5 stack item); every rejection that rested on height is re-assessed
against its remaining reasons and the outcome recorded; the mezzanine option loses its height objection.

## D-F7 Procedure and documentation (pm4-seating-fixture-undefined, pm4-step3-props-unspecified, ta08-gates-circular-or-unexecutable,
ta08-ms2-no-pass-criterion, ms1-mass-after-removal-gates-removal, ms5-tf18-criteria-not-measurable,
tf18-accelerometer-mass-loading-and-soft-criteria, supporting-files-table-incomplete, bottom-rule-superset-claim,
sheet-trims-ignore-pads, nits)

- Apply the verifier fixes. Sheet trims also clear MB pads by >= 0.5 mm (r7_calc recomputes the trims).

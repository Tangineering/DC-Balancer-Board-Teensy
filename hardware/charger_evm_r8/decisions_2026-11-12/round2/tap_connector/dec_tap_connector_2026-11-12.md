# Tap connector decisions with the operator (2026-11-12)

Source: the dec-tap-connector session. Inputs: DESIGN_STATE_2026-11-12.md section 4 item 6, cr_tap_review_2026-11-12.md,
outline_change_2026-11-12/leads.md and its independent check, ramifications/check_1-3.json, DD A.4 and A.8.
No repo file was edited. Pin-order search scripts: order.py and enum25.py in this folder (run from this folder with
miniforge python; enum25.py loads order.py).

## 1. Decisions (operator's words)

| Item | Decision | Operator's words |
|---|---|---|
| Size | 2 x 5, all 10 positions used, no spare | first chose "2x6, 2 empty", then: "I am revising my previous decision. Let's use Micro-Fit 3.0 2x5, as there are cable assemblies in stock for this configuration." |
| Family | Molex Micro-Fit 3.0, dual row, 3.00 mm | same quote |
| Cable | Molex 2147581101 (in stock) | "Molex 2147581101. Note that I will not use TSW pins specifically for the far ends- I will use the existing generic .100" pin crimp terminals I have in my workshop. Don't worry about this" |
| Mount | THT header on the CR, hand-soldered last | "THT, hand-soldered last" |
| Crimp tools owned | DuPont/Dubox crimper only (no Micro-Fit tool; the pre-made assembly avoids the need) | multiple-choice answer |
| Pin order | the map in section 2, conditional on dec2-gate | "Accept, conditional (Recommended)" |
| Placement | left to the design owner | "Leave to the design owner" |

## 2. Cavity map (accepted, conditional on dec2-gate)

Columns 1-5 along the header; rows A and B. Physical pin numbers: TODO(verify: Molex 43045 header and 43025 housing
drawings) at layout time. The Micro-Fit polarization excludes a 180-degree flip. A flip would put the T6 wire on the
T10 circuit, which is the T10-T6 short case.

```
         col1   col2   col3   col4   col5
row A:   T1     T7b    T17r   T5     T13
row B:   T6     T2     T17    T16    T10
```

The map meets these hard rules:
- T5 is not beside T6. A T5-T6 short defeats the FCC_ON AND NOT FCC_OFF agreement term (SAFETY-1).
- T10 is not beside T6. A short holds QUAL HIGH.
- T5 is not beside T10. A short ties two push-pull outputs onto one EN net (the old extended exclusion set).
- T1 and T2 are not beside T5 or T10. A 10 kOhm V-MOT or VBUS feed would lift a high-Z EN or QUAL pin at MCU reset.
- T1/T7b and T17/T17r are on adjacent positions (the twisted pairs).

A search of all 1664 feasible 2 x 5 maps (mirror images counted once) found none with fewer than two severity-2 pairs.
In every one, T13 separates T5 from T10. For comparison:
- 2 x 6 with two EMPTY cavities reaches severity 1 only (weighted sum 6.5 against 11.5).
- 2 x 6 with GND guards scores 11.5, no better than 2 x 5. R175 sits at the CR end, so T6 beside GND shorts the Teensy
  3V3 with no limiting resistor. T17 beside GND also passes proof (d) falsely.

The severity weights are this session's judgement: 1 = announces itself; 2 = reset-time or readback hazard;
3 = silently masks a protection.

## 3. Adjacent-pair short table (13 orthogonal pairs; 40 ohm i.MX driver = ASSUMPTION as in DD A.8)

| Pair | Consequence | Detector |
|---|---|---|
| T1-T7b | R170 carries <= 2.0 mA; H1 IN+ = 0 V; no regen release (safe) | H1 against V-MOT (T-C-02) |
| T7b-T17r | GND-GND; none | - |
| T17r-T5 | pin 31 HIGH sinks into GND (~80 mA driver contention); FC_CHARGE EN held LOW; no FC window (safe) | the FC window does not open (V_chg, CHG_IIN) |
| **T5-T13 (sev 2)** | In normal operation, pin 34 reads the pin-31 level and U102 contends through R126 (<= 3.3 mA). During an MCU reset (pin 31 high-Z) with a brake in progress, U102 HIGH drives the EN net through R126 (1 kOhm) against the 10 kOhm EN bodge. The net rises to ~3.0 V, above the VEN_R max of 1.4 V, so FC_CHARGE closes during the reset | readback plausibility; T-F-12 before power-up |
| T6-T2 | R171 back-feeds <= 2.0 mA into the Teensy 3V3; UVB and H1 IN- see 3.3 V; UVB drops | announces (UVB LOW, T-C-02) |
| T2-T17 | VBUS drives pin 22 through R171: ~1.3 mA clamp injection, TODO(verify: i.MX RT1062 injection limit); pin 22 reads full scale; UVB drops | announces (CHG_IIN implausible, UVB LOW) |
| T17-T16 | With FLT released, the pin-35 pull-up raises pin 22 (it reads current). With FLT asserted, both pins read LOW and the eFuse is already off | announces (CHG_IIN implausible) |
| T16-T10 | pin 35 reads the QUAL level, so it shows an eFuse fault while QUAL is LOW. An asserted FLT sinks pin 10 through R106s (<= 3.4 mA). A real eFuse fault is masked only while QUAL is HIGH | announces (FR-08) |
| T1-T6 | R170 back-feeds <= 1.64 mA into 3V3 (19.7 V V-MOT); H1 IN+ sees 3.3 V, so H1 never asserts; no regen release (safe) | H1 against V-MOT (T-C-02) |
| T7b-T2 | VBUS shorts to GND through R171 (<= 2 mA); UVB drops | announces (UVB LOW) |
| T17r-T17 | pin 22 reads 0 A, so proof (d) passes falsely. The pair is twisted, so this risk is the same in any connector | needs a firmware CHG_IIN vs I2C IBUS cross-check (group 3) |
| T5-T16 | as DD A.8 row F06-F17: pin 35 reads "fault" whenever pin 31 is LOW; R106s limits the FLT current | announces (FR-08) |
| **T13-T10 (sev 2)** | In normal operation, pin 34 reads the QUAL level and U102 contends (<= 3.3 mA). During an MCU reset (pin 10 high-Z) with a brake in progress, U102 lifts QUAL. With P5 LOW and FCC_OFF true, the gate releases. This is the QUAL-stuck-HIGH case of DESIGN_STATE 3.1, bounded to the reset | readback plausibility; T-F-12 |

Whether the two severity-2 pairs matter depends on the pin 10 and pin 31 states during reset (keeper, FR-49, T-D-01;
group 3).

## 4. Open-lead table (one cavity open or unplugged)

| Tap | Effect | Detected? |
|---|---|---|
| T1 | its divider pulls H1 IN+ to 0 V; no regen release (safe); the regen harvest is lost | H1 readback against V-MOT/V_rgn |
| T7b | shield unbonded; noise only | no |
| T2 | UVB drops and with it H1q; no regen release (safe) (DD A.4) | yes, UVB LOW |
| T5 | ~1.0 V at the tap (R187 3.30 MOhm against the U120 1.45 MOhm divider); FCC_OFF and FCC_ON both read LOW: no qualification, no FC window (safe) (check_3) | function lost |
| T6 | the CR and EIB 3V3 is lost and the gate is unpowered. The r4 design intends this to be fail-safe; re-confirm on the reduced gate (dec2-gate) | plausibility signature only (check_3) |
| T10 | the R123 47 kOhm pull-down holds QUAL LOW; qualification never releases (safe) | qualification read fails |
| **T13** | pin 34 (INPUT_PULLDOWN) reads "no brake", so FR-07 never posts the raise. Hardware H1 AND UVB can still release | **no** (needs an FR-08(d) cross-check of H1 against CHG_IIN) |
| **T16** | pin 35 (INPUT_PULLUP) reads "no fault"; an eFuse fault is masked (FR-23, FR-48 blind) | **no** |
| **T17** | pin 22 floats or sits near 0 V; proof (d) passes falsely and FR-11 is blind (check_1 1.1) | **no** (needs a pull at pin 22 or a cross-check against I2C IBUS) |
| T17r | shield unbonded; noise only | no |

A partly mated plug behaves as the open case for each cavity. A contact bent against its neighbour behaves as the
section 3 row for that pair.

## 5. Open TODOs

- TODO(verify: Molex 2147581101): circuits and rows, single or double ended, wire gauge, length, housing P/N. The Molex,
  Digi-Key and Mouser pages did not load in this session.
- TODO(verify: Molex): the mating THT 2 x 5 Micro-Fit header P/N (43045 series). Also its orientation (vertical or
  right-angle, which follows from the placement), its PCB pegs or locks, and the cavity numbering that the map uses.
- Far ends: the operator's own .100" crimp terminals go into J1/J2, replacing TSW-101-07-G-S, so the 30-off BOM row can
  shrink. R170 and R171 stay soldered at the C-D6 and C-D2 joints. Check that the assembly's wire gauge suits those
  joints (A.4 assumed 26 AWG).
- Twist T1/T7b and T17/T17r by hand on the assembly, because the off-the-shelf wires are discrete.
- Placement (design owner) constraints:
  - Put the header on the +x side, because every far end lies at +x.
  - Keep the T2 run short to C-D2 (x 67.4-69.7, y 69.9).
  - Keep each run inside its A.4 maximum: T1 0.15 m to C-D6 at (97.8, 17.9); T2 0.10 m; J1 taps 0.12 m; J2 taps 0.15 m.
  - Leave finger access to the latch.
  - Add a PM step: unplug the tap plug before lifting the CR.
  - Count the THT tails in the 11.05 mm CR-to-MB bottom clearance.
- If dec2-gate adds a pin rule, edit HARD or the cost table in order.py and re-run order.py and enum25.py.
- Firmware (group 3): the open-T17, open-T13 and open-T16 rows; the false proof (d) from a T17-T17r short; the pin 10 and
  pin 31 reset states that decide the two severity-2 pairs.
- T-F-12 becomes a cavity-to-cavity check on the mated harness. Keep the R175 bypass check (68 ohm) wherever R175 sits.
- Design doc and BOM rows to change:
  - DD A.4: heading, termination and lengths.
  - DD A.8: the pad table becomes a header row, the section 3 table replaces the F-pad short table, and H.23(g) is re-run.
  - DD E: the header, the assembly and the terminals.
  - LAYOUT_DECISIONS: D-05, D-08, D-31 and the section 4 footprint row.

# 2026-11-04 `J` incident: an adversarial re-check, and the hazards a common-ground charger swap leaves behind

Scope: Path A (desolder the Ag105, wire a high-side-sense / common-ground charger EVM onto the Ag105 pads of
board rev 20260622) and Path B (a re-spin) are compared as equals. Both need the same incident facts.
Tags: **MEASURED** means read directly from ML0227 (decoded here with `tools/decode_benchlog.py`), from the
serial record in `docs/boost-bringup-debug.md`, or from the .brd/.sch XML. **DATASHEET** means read in a
primary source; the citation is given. **UNCONFIRMED** means an inference or estimate.

Sources read: `docs/boost-bringup-debug.md` 2026-11-04 entries (lines 1522-1660); Ag105 datasheet V1.1
Nov 2021 (`references/Datasheets/AG105_Silvertel.pdf`, copied to `datasheets/AG105_datasheet_V1.1-Nov2021.pdf`;
Silvertel gives no literature number); RT1987 datasheet RT1987_DS-00 Sep 2024 (copied to
`datasheets/RT1987_datasheet_DS-00.pdf`); `references/Scale Car Board PCB 20260625.brd` (Eagle XML);
`logs/ML0227.BLG` (decoded to `ml0227.csv` in this folder).

---

## (a) Does "the VBat- to GND tie bypasses the current sense" fit every observation?

### What the datasheet says (DATASHEET)
- Ag105 DS p.3, Fig. 1 (block diagram): the "Current Sense" block sits between **Bat-** and the
  **Load- / Vin-** node. The Buck-Boost converter is referenced to Vin-.
- Ag105 DS p.4, Table 2: VBat- (pins 14, 15) "Must NOT be connected directly to the GND pin". VLoad- (pins 16, 17)
  is "Internally connected to Vin-". So VBat- differs from Vin- only by the sense element's drop. On this board an
  external tie therefore **puts a parallel path across the sense element**. It does not short an energised node.
- Ag105 DS p.6, "Battery Detection": in a **Bring-Up** charge "the output is gradually ramped while the Ag105
  monitors the current draw". Normal charging begins only once 10 % of the set charge current is seen
  (0.25 A at the 2.5 A setting). With no current draw the module reports battery disconnect and repeats the cycle.
- Ag105 DS p.18, "Over current Protection": it trips at "200 mA above the set charge current". p.19 covers the
  output short-circuit and partial-short behaviour. **These protections read the same current sense**, so on this
  board the module had no working output-current limit at all. Its only remaining stop is the input UVLO,
  11 V (DS p.19, Recommended Operating Conditions, VLOCK).
- Ag105 DS p.11, "Over Current/Regulation error" (status 0x05): "a voltage or current behaviour that is not
  expected from a battery". Charging stops and the module goes back to battery detection.

### How the hypothesis fits each observation
| Observation | Source | Fit with sense bypass | Note |
|---|---|---|---|
| r05 (Ag105 V_batt) climbs from ~2 V at ~0.64 V/s with reg 0x06 = 0 and the sources idle | serial, MEASURED | Fits. This is the Bring-Up output ramp into an open node (C-D11, 10 µF, needs only ~6 µA) | The open node comes from **D-BT-SQ blocking**, not from the GND tie (see A2) |
| r05 = 4.93 V while the pack is at 7.7 V | serial, MEASURED | Fits. It is a point ~4.5 s into the same climb | Explained by D-BT-SQ, not by the tie |
| The ramp starts on the **first line where r05 (7.744 V) exceeds the pack (7.67 V)** | serial, MEASURED | **Strong fit.** D-BT-SQ forward-biases and current reaches the pack, but it returns through the GND pour instead of through the shunt. The module sees no current draw and keeps ramping its output voltage | A working sense would have stopped the ramp at 0.25 A |
| Bus current (I_fc + I_batt) rises near-linearly at ~10.6 A/s in total to ~11.4 A in 1.02 s, with no plateau | ML0227, MEASURED (23.70 to 24.72 s) | Fits: a voltage ramp of ~0.45 V/s into a loop of a few tens of mΩ gives a linear current ramp | 0.45 V/s is the measured r05 slope over the ramp (7.74 to 8.19 V) |
| reg 0x06 reads 0.011-0.033 A throughout, though not stuck (it varies); reg 0x07 tracks V_in correctly (15.79 to 14.10 V) | serial, MEASURED | Fits: the internal shunt carries only a small share of the return current, possibly offset further by pour gradients. The I2C reads were live | The share (~0.1-0.3 %) cannot be checked without the module's internal shunt value, `TODO(verify: Silvertel)`. UNCONFIRMED |
| Current did enter the charger input | ML0227, MEASURED: V_bus - V_chg rises from a 0.096 V idle offset to 0.622 V at 9.9 A | Fits | Contaminated by ground shift, see (c) |
| Board V_batt rises 7.669 to 7.747 V (100 ms means) while the BT boost draws 3.8 A bus-side, then falls back to 7.72 V | ML0227, MEASURED | Fits. The charger output feeds node VBT, which supplies both the pack and the BT boost input. The pack sees only the net current | Below |
| Status 0x05 after the collapse, regs unreadable for 4.4 s, then a second Bring-Up from ~2 V at the same slope | serial, MEASURED | Fits: the output collapsed (input below UVLO), then detection restarted | The event was set to repeat about every 15 s (UNCONFIRMED) |
| "Max I_charge 1.408 A" | serial summary, MEASURED | Neutral: one 10 ms read, probably during the collapse | — |

**Energy balance (UNCONFIRMED; depends on the pack-R estimate and an assumed boost efficiency).**
The pack plus connector resistance, as the board ADC sees it, comes from the collapse instant (24.729 s),
when the charger was below UVLO and the pack alone fed the BT boost: (7.669 - 7.267 V) / 16.46 A ≈
**24 mΩ** (MEASURED inputs, UNCONFIRMED R). At 24.4 s:
- BT boost pack-side draw ≈ 3.76 A × 15.36 V / 7.75 V / 0.9 ≈ 8.3 A.
- Net pack current ≈ +0.078 V / 0.024 Ω ≈ +3.2 A.
- So the Ag105 output ≈ 11.5 A, from about 113 W of input. Efficiency ≈ 82 %.

At 24.6 s the same calculation gives ≈ 12.8 A out of about 148 W in (η ≈ 70 %). The cross-check (r05 - V_batt ≈
0.43 V across D-BT-SQ plus copper of 20-35 mΩ) gives 12-21 A.

Conclusion: **the Ag105 delivered roughly 11-13 A, which is 4.6-5× its 2.5 A setting, with 15-45 W of loss for under
1 s.** The power went into the pack and the BT boost input, and partly into heat. This rules out a "power went
nowhere" alternative.

### Alternatives tested
- **A2. D-BT-SQ fitted backwards: REFUTED.** In the .brd (MEASURED), D-BT-SQ pads 10 and 11_12 (RT1987 VIN) are on
  net VCHG (the Ag105 VBAT+) and pad 1_2 (VOUT) is on VBT (the pack, J-BT pin 1). It conducts charger to pack
  and blocks pack to charger (RT1987 DS-00 §17.6, TRCB; VFWD 35 mV, VFRC -50 mV, p.7). A reversed part would
  hold VCHG near pack - 35 mV from the start. Instead r05 climbed from 2 V. The orientation is as designed.
  D-BT-SQ explains the 2 V climb and the 4.93 V reading. It is **not causal for the runaway**: with a working
  sense the module would have seen 0.25 A at contact and started normal CC charging.
- **A3. BT boost return current crossing the Ag105's internal VBat-/Vin- shunt path: NOT EXPLANATORY,
  possible secondary offset.** The BT boost return runs J-BT pin 2 (11.7, 19.6 mm) → pour → REG-BT
  (45.5, 20.6). The Ag105 GND pads are at VIN- (46.0, 46.7) and VBAT-1/2 (21.0, 56.9 / 54.3), 25-35 mm off that path.
  Before the ramp the BT boost carried ~16 mA, so it cannot cause anything there. During the ramp a pour gradient
  between the VBAT- and VIN- pads (25 mm apart, on opposite rows of the module) can offset reg 0x06 in either
  direction. It cannot produce the voltage ramp.
- **A4. Ag105 internal short (VIN+ to VBAT+): REFUTED.** VCHG-IN was live for 11.7 s before the ramp
  (V_chg 15.83 V from log t 12.0 s) without conduction. The ramp began exactly at the pack crossing, and the module
  later ran a normal second Bring-Up.
- **A5. A bench-supply fault unrelated to the board: REFUTED.** The dropout came at the top of a load ramp the board
  drove, at ~9 A terminal current (estimated).
- **A6. A circulating loop through the BT boost, as an alternative: it is not an alternative, it is part of the same
  mechanism.** Bus → D-MT-EN → V-MOT → D-BC-RG → VCHG-IN → Ag105 → VCHG → D-BT-SQ → VBT → (pack, BT boost) → bus.
  The loop is lossy, so it cannot sustain itself. The FC bench supply provided ~half the bus power (the droop
  split; gFC = gBT = 0 throughout, MEASURED). When the supply dropped out, the BT boost hit 16.46 A, the bus fell
  to 6.84 V, and the Ag105 fell below its 11 V UVLO, which ended the event. **The terminating mechanism was the
  Ag105 input UVLO, not any current limit.**
- **A7. The board V_batt rise is a ground-shift artefact: PARTLY possible.** The BT divider (R1-BT 16.2k /
  R2-BT 10k at (31.5, 22.6), next to the BT boost return path) amplifies a ground shift at its R2 end by
  R1/R2 = 1.62. The magnitude is uncertain by about ±0.03 V. The conclusion does not change: the V_bus - V_chg drop
  and r05 > pack prove the current flowed independently.
- **A8. No RT1987 limited the current.** RT1987 DS-00 §17.5: short-circuit current limiting runs **only during
  soft-start** ("Both the SCP current limit and shutdown functions are disabled after tON"). No device in the
  path has a steady-state current limit (DATASHEET).

**Verdict (a): the sense-bypass mechanism fits every observation, both qualitatively and roughly in numbers.** No
tested alternative fits better. It is still UNCONFIRMED by direct measurement: the VBAT+ current was never
clamped, and Silvertel has not confirmed the internal shunt placement. The datasheet block diagram and the pin text
make it the expected behaviour, not merely a plausible one.

---

## (b) Worst case with a properly sensing, common-ground charger fed from the bus (the R3 case)

The loop is now **bounded by the charger's own regulated charge current I_c**, plus its input-current limit if it
has one, provided the sense really sits in BAT+ or on the input side with input GND = BAT- copper.
All figures below are UNCONFIRMED estimates. η_c (charger) = 0.88, from the Ag105 typical (DS p.20) as a
placeholder; η_b (TPS61288) = 0.90 is assumed, not verified.

- **Bus load step:** P_in = 8.4 V × I_c / η_c. At I_c = 2.5 A that is 23.9 W, or **1.46-1.5 A at 16 V**. Each
  channel carries ~0.75 A at a 50/50 droop split, all of it on BT when the battery-only selector is in effect. This
  is inside each boost's authority. Bus sag ≈ k_d × ΔI ≈ 0.3 Ω × 0.75 A ≈ 0.2-0.45 V (k_d 0.300 in ML0227).
- **Energy waste:** with BT as the only source the pack has a net loss of 23.9/0.9 - 21 ≈ **5.5 W**, which ends up as
  heat (~2.9 W in the charger, ~2.7 W in the boost). That is ~330 J per minute: a pure heater, not a hazard.
  With the FC sharing the bus, part of the charge energy is FC energy recycled through two conversions.
  **The R3 rule becomes an efficiency rule rather than a safety rule, but only if I_c is bounded in hardware.**
- **The bound is only as good as the configured limit.** If a register default or a firmware error sets I_c to
  the part's maximum, the loop power scales with it. A 5 A limit gives ~47 W (2.9 A bus-side); 8 A gives ~75 W
  (4.7 A bus-side), which is approaching the incident's ~85 W supply-side dropout. **Requirement:** a charge or
  input current ceiling set in **hardware** (sense resistor or ILIM resistor on the EVM) at no more than ~2.5-3 A, so
  that no I2C default or firmware error can exceed it. The candidate's power-on register defaults and its
  watchdog behaviour are UNVERIFIED and must be read from its datasheet.
- **Interaction with the firmware UV backoff:** `AG105_CHG_BACKOFF_V` 12.8 V / 15 ms closes FC_CHARGE only, and
  `LIMIT_V_BUS_MIN` 12.0 V / 20 ms latches UV_BUS (`teensy_controller.ino` lines 2163-2193 and 2597-2599). In the
  incident the bus held at ≥ 15.05 V until the source failed, then collapsed in ~4 ms. **The voltage-based guards
  were blind**, because the stiff, droop-shared sources held the bus up while the load ran away. With a bounded
  charger the sag is only 0.2-0.5 V, so neither threshold is approached.
  **Remaining hazard:** in an FC-charge window the bus is FC-only (BT_BUS and REGEN LOW, enforced by
  `assertFcChargeEnable()`). A 1.46 A charger load exceeds the H-20's 1.247 A bus-equivalent ceiling (CLAUDE.md,
  2026-09-09 addendum), and the H-20 purges to ~1 V. The Ag105's input-threshold MPPT used to act as the input
  voltage regulator. **The replacement needs an equivalent input-voltage regulation loop (VINDPM, or similar), set
  above the backoff level (for example ≥ 13.3 V, which is backoff + 0.5 V; a recommendation, UNCONFIRMED).** It then
  throttles itself before the firmware backoff and the UV latch act. A charger with no input-voltage regulation
  drags the FC-only bus into UV_BUS.
- **fw v37 rev 2 `J` guards need re-tuning for a healthy charger:**
  - G1 (bus-side I_fc + I_batt > 1.0 A for 5 ms) would trip on a correct 2.5 A charge (~1.46 A bus-side). Note that
    G1 would have tripped ~1 s before the incident's dropout (the total crossed 1.0 A at ~23.75 s, MEASURED).
  - G2 (unaccounted bus power > 3 W) depends on reading charge current from the charger. It reads Ag105 reg 0x06
    today, so a new charger needs its own current read before G2 means anything.
- **Hot-plug and inrush (a Death-5 class concern):** RT1987 DS-00 §17.3 gives tON = VIN/35 × (CSS/0.0023 - 100) µs.
  With CSS = 5.6 nF (C-DC8, C-DC10; BOM "C-DS"), tON ≈ 1.07 ms 10-90 % at 16 V, which is ≈ 12 V/ms. Inrush is
  ≈ C_in × 12 V/ms:
  - today: 20 µF (C-D8 + C-D10) gives 0.24 A.
  - an EVM with 100 µF gives 1.2 A.
  - an EVM with 330 µF gives 4 A. The start-up current limit is 2.5-8.5 A with a 250 µs timer (§17.5), so this
    risks SCP retries every 64 ms and a hot-plug step into the boosts.
  **Measure the candidate EVM's input capacitance and keep it ≤ ~100 µF, or increase CSS.**
- **V-MOT drain (new, real):** in the R3 / REGEN configuration the charger draws from V-MOT. If MOT_PWR (D-MT-EN)
  opens while REGEN is still closed, 1.5 A drains the 470 µF CAL node at ~3.2 V/ms. The next MOT_PWR re-close is then
  a full-bus hot-plug onto a drained node, which is the Death-5 mechanism. `motPwrHotPlugUnsafe()` must account
  for a charger load on V-MOT, or REGEN must drop before MOT_PWR.
- **Back-feed into the boosts by a bidirectional charger (OTG / reverse mode): blocked by hardware.** In the .brd
  (MEASURED), D-BC-FC VIN = VBUS, D-BC-RG VIN = V-MOT, and both VOUTs = VCHG-IN. An ideal diode blocks
  VCHG-IN → bus. On the battery side, D-BT-SQ blocks pack → charger, so reverse mode has no source anyway.
  Disable OTG anyway.
- **D-BT-SQ hides the pack from the new charger.** The charger's BAT pin sees only C-D11 (10 µF) until its output
  exceeds the pack. Any battery-detection or NVDC (SYS/BATFET) logic must tolerate that.
  `TODO(verify: candidate datasheet)` for each candidate. The CV loop regulates VCHG, so the pack ends ~35 mV + I×R_on
  below the setpoint, which is a safe undercharge. The EVM's input must also tolerate VCHG-IN up to the chopper
  clamp (~21.4 V true) plus transients. The C-D8 and C-D10 capacitors are 25 V X7R 0805 (BOM).

---

## (c) Other ground-return problems a new charger could hit

The board is **2-layer, with GND as a full-board solid pour on both Top and Bottom** (rank 3, thermals="no", 288 GND
vias). Copper is 0.035 mm (1 oz) per `mtCopper` in the design rules; the ordered weight is UNVERIFIED. Sheet
resistance ≈ 0.49 mΩ/sq per layer, ≈ 0.25 mΩ/sq for the two in parallel. **There is no sense element or switch in
the pack negative anywhere** (MEASURED): J-BT pin 2, the Ag105 VIN- and VBAT-1/2, REG-BT GND and the BQ29200 VSS
are all on net GND. The INA253s sit high-side on VBUS-FC and VBUS-BT.

- **Charger GND pad vs the pack negative (UNCONFIRMED estimate):**
  - J-BT (11.7, 19.6) to the VBAT- pads (21.0, ~55.6) is ~37 mm; to VIN- (46.0, 46.7) it is ~44 mm. Through a pour
    10-20 mm wide (cut by VBT traces and pours), that is ≈ 1-2 mΩ including spreading resistance.
  - The charger's own 2.5 A return gives ≈ 2.5-5 mV. That drop **is in the safe direction**: return current flows
    from J-BT to the charger GND, so the charger's ground sits below the pack negative and the pack is slightly
    undercharged.
  - The BT boost return (J-BT ↔ REG-BT) runs along y ≈ 15-21 mm, away from the charger pads. Its share of the
    common pour near J-BT is ~0.1-0.5 mΩ × up to 15 A, about 1-7 mV, of either sign.
  - The worst-case CV error is ≈ 0.2 % of 8.4 V, which is negligible, and the BQ29200 OVP stays the backstop.
  - With high-side or input-side sensing, **these drops do not enter the current measurement at all.**
- **Wiring the EVM:** route its input GND to the VIN- pad and its BAT- to the VBAT- pads, each with a short heavy
  lead. The EVM's GND copper then parallels the 25 mm of board pour between those pads. With high-side sensing this
  is harmless; it only moves the CV reference by a few mV.
- **Ground shift amplified in the board's rail ADCs (MEASURED geometry, UNCONFIRMED magnitude).** A divider whose
  R2 ground pad sits ΔV_g away from the Teensy's ground reads V + ΔV_g × R1/R2. The gains are:
  - CHG: 78.7k / 10k = **7.87×**, at R2-CHG (71.4, 5.8), near D-BC-RG and the motor/VESC return region.
  - BUS: 4.64×.
  - FC: 2.74×.
  - BT: 1.62×, at R2-BT (31.5, 22.6), on the BT boost return path.

  In ML0227 the "resistance" of D-MT-EN + D-BC-RG plus traces, computed from V_bus - V_chg, **rises from 35 to
  53 mΩ** over the ramp (3.6 to 9.9 A). Some of that is the RT1987 regulation floor (2 × 35 mV) and heating, but a
  few mV of pour shift × 7.87 is enough to explain it. **Treat V_chg, and any firmware guard built on it, as
  ±0.1-0.3 V uncertain under heavy return current.** Keep it as a relative indicator, not a precision measurement.
- **INA253 output reference:** the INA253A1 runs at 100 mV/A with its output referenced to its own GND pin
  (SNS-BT at (55.1, 23.6), beside the BT return path; the Teensy is at (97, 60)). The error is 10 mA per mV of
  ground shift. That is minor, but it matters for G1/G2-type thresholds near 1 A and for the share loop at light
  load.
- **Pack negative bonded at two points (pre-existing; a charger adds return current):**
  - J-BL pin 3 (the balance lead's negative) is on GND at (11.4, 45.7), 26 mm from J-BT pin 2. The thin balance
    lead therefore parallels the pour and carries tens to hundreds of mA of circulating current (UNCONFIRMED). That
    is benign.
  - **If the J-BT negative screw terminal ever loosens, the whole pack return (up to ~15 A) moves onto the balance
    lead.** That is a fire hazard independent of which charger is fitted. Check the J-BT torque and consider a fuse
    or PTC in the balance negative.
  - The BQ29200 VSS sits between the two bond points (BAL at (24.4, 29.5)). A few mV of offset is negligible
    against its OVP threshold (BQ29200 threshold variant not re-verified in this pass).

---

## (d) Possible damage to check before ANY new charger is wired (Path A), and before Path B reuses parts or learnings

Stress figures come from ML0227 (MEASURED currents; durations from the 1 kHz log). Ratings are from RT1987 DS-00 p.6:
8 A continuous, 20 A peak for 10 ms at 2 % duty, OTP at 140 °C.

| Item | What it saw | Over rating? | Check before wiring |
|---|---|---|---|
| **FC channel** (REG-FC, D-FC-EN, SNS-FC) | ~5.9 A bus-side, so ≈ 10.6 A estimated at the FC boost input near the 15 A switch limit; then input collapse 9.3 → 2.1 V in 4 ms. **Exactly 0 A for 6 s afterwards** (0 of ~5 500 samples), while BT idled at 32 mA against 24 mA total before | Ambiguous. At idle the split is extremely sensitive: ~10 mV of boost setpoint shift moves a ~30 mA load fully onto BT (k_d 0.3 Ω). So "0 A at idle" is **not** proof of damage (UNCONFIRMED) | (1) Under a 1-2 A bus load with both sources, I_fc should carry about half. (2) FC-only (BT_BUS off) at ~0.5 A: bus holds and I_fc ≈ load means OK; bus holds but I_fc = 0 means SNS-FC / ADC damage; bus collapses means FC boost or D-FC-EN damage. (3) With FC_BUS off, measure VOUT-FC (before D-FC-EN) to confirm the FC boost regulates |
| **D-BT-SQ** | Charger output ≈ 11-13 A (UNCONFIRMED) for ~0.3-0.5 s | Yes, above 8 A continuous and far past the 10 ms peak window | With the Ag105 removed and the pack connected: (1) BT_SEQ HIGH, VCHG floating should read ≈ 0 V (reverse blocking intact; VCHG ≈ pack means a shorted FET). (2) Inject 1-2 A from a current-limited supply into the VCHG pads above the pack voltage: VCHG - VBT should be ≈ 35 mV + 20 mΩ × I (≈ 60-75 mV at 2 A). (3) BT_SEQ LOW should give 0 A (EN control works) |
| **D-BC-RG, D-MT-EN** | Charger input current ~8-11.4 A for ~0.2 s above 8 A; measured path chord resistance rose 35 → 53 mΩ | Yes, moderately; heating plausible | Same three checks: EN off means VCHG-IN ≈ 0; forward drop at a known current (≈ 2 × (35 mV + 20 mΩ × I) plus trace); reverse blocking with VCHG-IN driven above V-MOT through a current-limited supply. OTP was cleared by the power cycle either way (DS §17.8 says EN toggle or power cycle; Table 1 says auto-restart, so the datasheet disagrees with itself) |
| D-BC-FC | Not in the current path (FC_CHARGE LOW) | No | EN control and reverse blocking only (it becomes the FC-charge path) |
| D-BT-EN, REG-BT, L-BT, SNS-BT | 16.46 A for ~3 ms with the bus at 6.84 V; the boost probably passed input straight through | D-BT-EN is within the 20 A / 10 ms peak; the INA253 rating at 16.5 A was not verified in this pass | The post-incident staged `G` passed (operator report). Scope the switch node once under a ~2 A load |
| **Ag105 pads (the Path A interface)** | — | — | The VIN-, VBAT-1 and VBAT-2 pads are solid-connected to **both** full pours with no thermal relief, on a 1.66 mm board with 1.1 mm holes, so desoldering the DIL module risks lifted pads and barrel damage. VCHG-IN uses traces on both layers (65.7 mm top, 44.6 mm bottom of 1.524 mm). **Cut the module pins and remove them one by one.** Afterwards check top-to-bottom barrel continuity on VIN+, VBAT+1/2 and the GND pads, and check the SDA, SCL, STAT and MPPTD pads |
| Ag105 module | ~11-13 A out for ~1 s, 15-45 W loss (UNCONFIRMED); it later ran a second Bring-Up | Yes, heavily | It is being removed. Do not reuse it without testing |
| Pack | +2-3 A net charge, a ~15 A discharge pulse, V ≤ 7.80 V | No | Check cell balance on J-BL; confirm the BQ29200 never tripped |
| Bench FC supply | ~9 A at its terminal, then dropout | Unknown | Record its OCP / CC setting and what latched (the open item in the debug-doc entry) |
| C-D8, C-D10 (VCHG-IN, 25 V) | ≤ 16.2 V | No | — |

**What remains after a correct charger swap (summary):**
1. The loop is bounded only by the charger's limit, so the ceiling must be set in hardware.
2. The FC-only bus in charge windows needs input-voltage regulation in the charger.
3. EVM input capacitance against the RT1987 soft start (CSS 5.6 nF).
4. The V-MOT drain and MOT_PWR re-close hot-plug in the REGEN path.
5. D-BT-SQ hiding the pack from the charger's battery detection.
6. The `J` G1/G2 guards must be re-tuned, and G2 re-pointed at the new charger's current read.
7. V_chg ADC ground-shift amplification of 7.87×.
8. The two-point pack-negative bond through the balance lead.

None of these is the incident mechanism. **A common-ground charger with high-side or input-side sensing removes the
incident's root cause** (unregulated output with no working OC protection), on the assumption, still UNCONFIRMED,
that the sense-bypass mechanism is the true one. Its effect is to turn the R3 loop from runaway into a bounded
5-6 W heater at 2.5 A.

## Open measurements that would confirm or kill (a)
1. On the bench with the pads exposed (Path A): measure the Ag105's VBat- to Vin- resistance (pins 14/15 to 16/17)
   out of circuit. A few to tens of mΩ means the shunt; it should also be compared against 25 mm of the board pour.
2. Ask Silvertel (`TODO(verify: Silvertel)`) for the shunt location and value.
3. Before trusting any replacement, run the first powered charge with a clamp on the charger's BAT+ lead and the
   scope on V_bus, VCHG-IN and VCHG, at a hardware-limited ≤ 1 A setting.

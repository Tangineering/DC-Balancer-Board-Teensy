# V_rgn reads ~0.85 x true: investigation, history, and the chopper trip question (2026-11-05)

Analysis only. No firmware, plant-model or hardware change was made. Reproduce the numbers with
`python3 tools/rgn_ratio_scan.py` (every bench BLG) and, for the Pi bags,
`tools/rosbag_analysis/scout_bags.py <bag> --npz` then index 6 (`V_bus`) / 7 (`V_rgn`) of
`/vehicle_state`.

Supersedes the "V_rgn reads 0.85 x true, so the 18.1 V clamp is ~21.4 V true" reading in
`docs/reviews/fw36_regen_2026-11-04/README.md` item 6, `docs/fw37_planning_2026-11-04.md`
section 3.4 item 3 and `.claude/skills/rosbag-agent-analysis/references/bag-conventions.md`
item 11. The 0.85 ratio itself stands. What changes is (a) where the error sits and (b) the
conclusion that 18.1 V is the clamp level. **The chopper has never been shown to trip.**

> **UPDATE (2026-11-05, later): multi-agent root-cause investigation, section 7.** The leak is
> NOT linear. The logs show a knee-type sink on the RGN-V node: almost nothing below about
> 1.2 V at the node, then rising at roughly 9-15 kOhm. Three things follow. The wrong-resistor,
> contamination-as-a-resistor, ADC, firmware and swapped-pinout explanations are all refuted.
> The sink is most likely in the TL431's REF path (an open cathode joint or open R-G, or a
> damaged input stage), with a damaged Teensy pin-39 pad as the main alternative. The safety
> picture is also worse than section 5a's resistive case: the chopper trips at about 30 V or
> more, or never, and the logged regen peaks were probably **at least ~24-26 V true**, not ~21.5 V.

---

## 1. What pin 39 measures

Schematic sheet 4 ("22V CHOPPER CIRCUIT", grid 5C). `RGN-V/3.6C` is the tap of the
**chopper's own feedback divider**: R1-SNT 78.7 kOhm (0402, 0.1 %) from V-MOT to the tap,
R2-SNT 10 kOhm (0603, 0.1 %) from the tap to GND. The **TL431 REF pin** (U-SNT pin 2) sits on
the same net. The TL431 cathode (pin 1) drives the BSP170P gate node VG through R-G 220 Ohm. VG is
pulled up to V-MOT by R-GS 3.3 kOhm and clamped 12 V below V-MOT by Z-SNT. The dump is
R-SHUNT 47 Ohm, 20 W. CAL 470 uF and C-D6 10 uF sit on V-MOT.

So `SCALE_V_RGN` (`teensy_controller.ino:2032`, 3.3 x 88.7/10 / 4095) treats a loaded control
node as a bare sense divider. Anything that draws current from the TL431 REF net, including the
TL431 itself and the Teensy pad, reads as a low V_rgn.

Design trip, from the BOM values: the TL431 starts sinking when REF reaches V_ref = 2.495 V,
which puts V-MOT at **2.495 x 88.7 / 10 = 22.13 V** (the 22.1 V design trip). *Resolved
2026-11-05 (operator): the 19.91 V figure first quoted for this analysis came from an
**earlier design** with R1-SNT = 69.8 kOhm (2.495 x 79.8 / 10 = 19.91 V). The 20260622 BOM
and schematic, and the board, carry **78.7 kOhm**, so the nominal trip is 22.1 V.* That also
fits the measurement: a 69.8 kOhm R1 would make V_rgn read 1.11 x V_bus, not 0.85x.

## 2. The error: size, and where it is not

ML0226 (fw v37, 2026-11-04, 422 s, 369 521 records, V_chg = 0 throughout, no regen event):

- V_rgn/V_bus = **0.8479** median, 1-99 % range 0.8469-0.8487. That holds from standstill to
  2.1 m/s and 12 A commands. V_bus spans only 15.79-15.96 V.
- At 15.93 V the tap should be at 1.796 V. It reads 1.522 V, which is 274 mV (339 counts) low.
  Current balance through the divider: **31-33 uA is being drawn off the node** at that voltage.
  That is the same as about 50 kOhm from the tap to GND, or an effective R1 of about 94 kOhm.

Ruled out:

- **The ADC chain.** V_chg (pin 38) has the identical 78.7k/10k divider and the same
  `analogRead` path, and is read on the line just before V_rgn (`.ino:7032-7033`). It reads
  **0.994 x V_bus** whenever the charger path is fed (ML0227). V_bus (8.2 kOhm source) and V_fc
  also read correctly.
- **Carry-over from the previous ADC channel.** In ML0227, V_rgn/V_bus = **0.84739 with V_chg
  at 0 V and 0.84739 with V_chg at 15.8 V** (10 556 and 18 816 samples).
- **A swapped TL431 pinout.** The footprint is Ultra Librarian's for TI's own TL431BIDBZR. If
  REF had landed on VG, the TL431 would pull the gate down and the 47 Ohm dump would conduct
  continuously: about 5 W and about 0.34 A of standing bus load. The idle bus load is 0.008 A.
- **A wrong resistor value on its own** (now refuted outright by the small-signal gain, section 7).
  0.1 % thin film cannot produce the 2 % drift between
  sessions shown in section 3.

Remaining candidates, not yet separated:

1. **The TL431 REF pin leaks, or the TL431 is damaged.** A healthy part draws a few uA into REF
   (`TODO(verify: TI TL431 datasheet)`: no TL431 datasheet is in `references/Datasheets`).
2. **The Teensy pin-39 pad leaks**, for example ESD-structure damage. This would explain why
   pin 38 on an identical divider is clean.
3. A resistor fault or a contamination leak on R1-SNT/R2-SNT. Disfavoured by the temperature
   drift.

Whether the leak is a fixed fraction or grows with voltage cannot be told from the logs. V-MOT
is only ever steady at about 15.9 V; every lower reading is a single sample on a collapse, with
the 470 uF still holding the node up.

## 3. History: present from the first log, temperature-dependent, no step

V_rgn first appears in the BLG format at v3, with fw v5. PS/TP0001-WP0073 (fw v3-v4) have no
V_rgn column. SY0001 reads exactly 1.000 because it is synthetic (`docs/HIL_REPLAY_LOGS.md`
section 3f) and is excluded. 132 bench logs and 21 Pi bags have a usable ratio:

| Period | Logs | fw | V_rgn / V_bus |
|---|---|---|---|
| 2026-08-12 | TP0074-WP0101 (first V_rgn log: TP0074 = **0.8365**) | v5 | 0.835-0.837 |
| 08-12/13 | TP0102-WP0124 | v6 | 0.836-0.838 |
| 08-16 | TP0125-TP0134 | v8 | 0.839-0.840 |
| 08-16 | ML0135-ML0145 | v9-v12 | 0.834-0.837 |
| 08-16 | ML0146-YP0152 | v14 | 0.843 |
| 08-17 | ML0153-TP0180 | v14-v16 | 0.835-0.838 |
| 08-17 | ML0182-ML0183 | v17 | 0.841 |
| 08-25 | ML0194-ML0203 | v18 | 0.845-0.847 |
| 08-25 | YP0204-YP0214 | v18-v19 | 0.849-0.852 |
| 09-07 .. 10-30 | 21 Pi bags | not recorded in telemetry (v28-v35 era) | 0.849-0.854 |
| 11-04 | ML0226, ML0227 | v37 | 0.848 |

- **Not firmware.** The ratio moves 0.836 -> 0.843 -> 0.836 between sessions on the same fw
  v14, and the pin-39 read has not changed since it was added.
- **It drifts with warm-up.** Correlating each log's ratio with its BLG `start_millis` (time
  since boot) gives correlations of -0.80 to -0.97 in 7 of 8 sessions. The ratio falls 0.15-0.3 %
  over 5-15 min of uptime (ML0164 -> TP0180: 0.8375 -> 0.8346 over 15 min). The longer the board
  is on, the more current is drawn off the node. That points to a semiconductor junction leak
  (candidates 1 and 2), not a resistor.
- **It shifts slowly over the weeks**, from about 0.835 in mid-August to about 0.85 from late
  August, consistent with ambient temperature or ageing. There is no single before/after event.
  Neither the August boost deaths nor the 2026-11-04 `J` incident moved it: ML0227 reads 0.8474
  through and after the incident. If a part is damaged, it was damaged before 2026-08-12 or
  fitted that way.

## 4. Consequences that do not depend on the root cause

- **The bring-up hot-plug gate (P3) margin is thin.** It requires
  `V_rgn >= V_bus - MOT_HOTPLUG_MARGIN` (3.0 V, `.ino:13001`). A connected node shows a gap of
  2.40 V (0.850) to 2.65 V (0.834), so only 0.35-0.6 V is left before a healthy connect is
  refused as `ERR_MOT_HOTPLUG`. The gap widens as the board warms.
- **`LIMIT_V_RGN_MAX` (28 V reading) is not 28 V.** At a fixed 0.85 ratio it is about 33 V
  true, above the RT1987's 32 V. If the leak grows with voltage, it is higher still.
- **18.1 V is not the chopper trip.** See section 5. `V_CHOPPER_TRIP` 18.1 V in
  `docs/HIL_PLANT.md` section 3 and `docs/PSCAD_SIM_DESIGN.md` B8 was taken from the peak
  reading, not from a clamp.

## 5. Has the chopper trip ever been reached?

**Peak data.** The highest V_rgn reading in any bench log is **18.220 V** (ML0195 / YP0196).
In any Pi bag it is **18.263 V** (rosbag_sweep-noclip_2026-10-30_01-30-16). Nine logs and one bag
exceed 17.5 V, all during regen bursts (`I_cmd` = -12 A). 18.263 V on the pin corresponds to
**2.059 V at the node**.

At full 1 kHz resolution each burst rises over 24-58 ms at 0.02-0.34 V/ms (in reading units). It
reaches a **rounded peak** and then falls almost linearly at about 0.02 V/ms. Peaks land
anywhere from 17.0 V to 18.26 V. No log shows a flat top or a fixed ceiling.

The answer depends on where the leak is, which the DMM check in section 6 decides.

**Case A: the leak is on the node** (candidates 1 and 3, and 2 as well, since a leaking pad
loads the same net). The V_rgn reading is then the true REF voltage scaled by 8.87. The TL431
regulates REF at 2.495 V whatever loads it, so a tripped chopper reads **22.13 V**. The
observed maximum puts REF at 2.059 V, **436 mV below V_ref**. In this case **the chopper has
never tripped in any log or bag, whatever the nominal V-MOT figure.** A side effect: the real
V-MOT trip is raised (section 5a).

### 5a. Effective trip point in case A

The chopper trips when the node reaches V_ref = 2.495 V. At that point R2-SNT carries 249.5 uA
and the leak carries I_leak(2.495 V), so

    V_trip = 2.495 x (1 + 78.7/10) + I_leak(2.495 V) x 78.7 kOhm
           = 22.13 V + 78.7 V per mA of leak at the trip.

Only one point on the leak curve is known: **29.5-33.6 uA at a node voltage of 1.50-1.53 V**
(15.9 V bus; the range is the session/warm-up spread, ratio 0.854 -> 0.834). The node has to
rise another ~0.97 V to reach the trip, and the trip depends entirely on how the leak grows over
that step:

| Leak behaves like | Leak at 2.495 V | Effective V-MOT trip |
|---|---|---|
| Constant current (saturated source) | 29.5-33.6 uA | **24.4-24.8 V** |
| Resistor to GND (fixed ratio, about 45-52 kOhm) | 48-56 uA | **25.9-26.5 V** (22.13 V / ratio) |
| Junction leak (grows exponentially; e.g. x2 per 0.2 V) | ~0.9 mA | **~90 V, i.e. no trip** before something else gives way |

The warm-up drift in section 3 shows the leak is temperature-dependent, which makes the
junction-like case plausible, and every case trips higher on a warm board. Compare with the
limits on V-MOT: the RT1987 is rated to 32 V operating and 40 V absolute maximum
(`references/Datasheets/RT1987_DS-00.pdf`, sections 10 and 12). The first two cases still clamp
inside that range; the third does not clamp at all. Until the leak's voltage dependence is
measured, **in case A the board has no assured V-MOT overvoltage clamp.**

Firmware gives no backstop in case A either. `LIMIT_V_RGN_MAX` (28 V reading) needs the node at
28 / 8.87 = 3.16 V. A working chopper holds the node at 2.495 V (a 22.13 V reading), and a leak
that stops the chopper tripping also pulls the node down. Either way the reading cannot get to
28 V, so `FAULT_OV_RGN` cannot fire.

Measuring the curve: bench trip test (section 6, step 5), or a DMM on the node at two or three
V-MOT levels from a current-limited supply, with the VESC disconnected.

**Case B: the node is correct and the error is between the node and the ADC result** (the DMM
reads 1.80 V at the node while firmware reads 1.52 V). True V-MOT is then reading / ratio.

- Against **22.13 V**: the true peaks are 21.47-21.66 V (each log's own ratio). The worst case
  is 18.113 / 0.8361 = 21.66 V (ML0157), with REF at 2.442 V, 53 mV below V_ref. **Not
  reached**, by 0.5-0.7 V. That is 2.1 % below, against the TL431B's +/-0.5 % reference
  tolerance (`TODO(verify: TI TL431 datasheet)`).
- **No conduction at any level** (independent check, also excludes the superseded 19.91 V
  design trip, which the case-B true peaks would have exceeded by 1.6-1.8 V):
  1. **No conduction signature.** Taking the old 19.91 V level as the worked example, the dump
     would take 19.91 / 47 = 0.42 A (0.46-0.47 A at 21.5-22.1 V) as soon as it turned on.
     V-MOT capacitance is at least 480 uF (CAL + C-D6) and at most about 1.4 mF:
     the ML0215-ML0217 dark-node decay time constant of 105-122 s, divided by the 88.7 kOhm
     divider alone, bounds it from above, and every other load only lowers that estimate. So
     the rise rate would have dropped by at least 0.30 V/ms true (0.25 V/ms in reading units)
     within a sample or two of crossing a reading of 19.91 x 0.846 = 16.85 V. Observed: YP0196
     *speeds up* through 16.4-16.9 V (0.09 -> 0.14 V/ms). YP0198 continues at 0.05-0.11 V/ms.
     ML0151's slope eases from 0.32 to 0.12 V/ms over 16.5-17.5 V and then **rises back to
     0.20 V/ms at the 18.2 V peak**, which is not possible with 0.42-0.46 A leaving through a
     dump held on above the trip. There is no consistent slope break at one reading level
     across the bursts.
  2. **The peak shape.** A rounded peak followed by a slow linear fall matches the regen source
     tailing off (the VESC's regen is cut back after about 0.4 s,
     `docs/reviews/fw36_regen_2026-11-04/README.md` item 8), not a clamp.

  Caveat: the regen source current during a burst is not measured, so point 1 is strong
  supporting evidence, not proof.

**Conclusion.** There is no evidence the chopper has ever conducted. In case A that is certain
(REF never came within 436 mV of V_ref). In case B the true peaks (21.47-21.66 V) stayed 0.5-0.7 V
below the 22.1 V design trip, and the burst traces show no conduction signature at any level. Every regen peak recorded to date is the VESC's regen
limit, not the chopper.

*Section 7 supersedes parts of section 5/5a. The constant-current and resistor rows of the 5a
table are refuted by the data. The measured curve is the knee type, which puts the trip at about
30-33 V if the curve stays linear, or no trip at all. The conclusion above, "every regen peak is
the VESC's regen limit", is weakened: the 18.1-18.3 V reading ceiling may instead be the sink's
own soft clamp near 2 V at the node.*

## 6. Next steps (bench, in order)

1. **DMM on the RGN-V node** (R2-SNT top, or TL431 pin 2) with MOT_PWR closed at about 15.9 V,
   **after a 10-15 min warm-up** (the worst case).
   - About 1.52 V: case A, the node is really loaded.
   - About 1.80 V: case B, the error is in the pin/ADC path.
2. **Case A:** lift the pin-39 connection. If the node recovers to 1.80 V, the Teensy pad is
   leaking; if not, swap U-SNT (the TL431).
3. **Measure R1-SNT and R2-SNT out of circuit** (expect 78.7 k / 10 k, the 22.1 V design;
   the operator confirms 78.7 k is on the BOM and schematic) and confirm the TL431 grade.
4. **Optional firmware check:** `pinMode(RGN_VOLTAGE, INPUT_DISABLE)` before reading, to rule
   out the i.MX pad keeper. Pin 38 reading correctly makes this unlikely.
5. **Bench trip test,** only once 1-3 are done: raise V-MOT slowly from a current-limited supply
   with the VESC disconnected, and record the V-MOT voltage at which the dump starts drawing
   current. This is the only direct measurement of the trip.

Until the cause is fixed:

- Report V_rgn in ADC counts. Apply the 1/0.85 correction only near 16 V, the only voltage at
  which it has been measured.
- Do not use 18.1 V as the chopper trip in the plant models.
- Treat `MOT_HOTPLUG_MARGIN` (3.0 V) as marginal.

## 7. Root-cause investigation (2026-11-05, multi-agent)

Eight independent investigators, a synthesizer and three adversarial reviewers (physics/datasheet,
data re-analysis, devil's advocate) worked from the logs, the TL431 / BSP170P / BZT52C / RT1987
and i.MX RT1060 datasheets, the Teensy core source, the Eagle board file / Gerbers / PnP, and the
repo history. Full record, the per-agent outputs and their scripts:
`docs/reviews/vrgn_rootcause_2026-11-05/` (README.md, workflow_result.json, agent_work/).

### 7.1 What the data establish (measured)

1. **V-MOT really equals V_bus.** In ML0227 (J session, REGEN + MOT_PWR closed, ~0 A) V_chg reads
   V-MOT through the regen path at 15.834 V against V_bus 15.924 V. Over the same samples V_rgn
   reads 0.847-0.852 x V-MOT. A pre-retune scope capture also shows V-MOT overlaying V_bus
   (`references/scope_captures/12-Vbus yellow-Vmot blue-Ibat purple-P0.3.jpg`).
2. **The small-signal gain is far below the static ratio.** dV_rgn/dV_bus over natural bus
   fluctuations is **0.48-0.65** (13+ bench sessions, coherence ≥ 0.9, zero phase below ~8 Hz;
   Pi bags 0.46-0.55; ML0226 0.649, rechecked by the data reviewer). The static ratio over the
   same span is 0.834-0.852. A resistor, contamination acting as a resistor, ADC gain/Vref, or
   a scale error would make the two equal. A constant current, an offset or reverse-junction
   leakage would give 1.0. **Only a sink whose conductance rises with node voltage gives a gain
   below the ratio.** Ground shift between the R2-SNT return and the Teensy AGND is ruled out by
   regressing V_rgn jointly on V_bus and load current (ML0203: a ratio-plus-ground fit is 7x
   worse).
3. **Leak I-V from motor-load bus dips.** TP0115, TP0178, TP0201 and TP0209 dip the bus
   15.9 -> 12.2 V for 5-8 ms with MOT_PWR closed and the motor loading V-MOT. All four give the
   same curve, I = (V_node - V_on)/R with **V_on 1.19-1.25 V, R 9.2-9.5 kOhm**, rms about 1 uA.
   That is 6-8x better than a resistor to GND or a constant current. The ML0227 load ramp and the
   J-ramp brackets agree, and give about 0 +/- 3-7 uA at a node voltage of 0.7-1.0 V (single
   1 kHz samples, lower confidence). Caveats from the reviewers: all four dips are the same
   stimulus (a source-less handoff collapse). The November small-signal gain implies a local
   slope nearer 13-17 kOhm, so either the slope changed or the gain estimate carries a bias
   from V-MOT = V_bus - I x R_on. Either way the curve is a knee with a few-k to ~15 k slope.
4. **Warm-up.** The leak, referred to a node voltage of 1.50 V, rises by 1.04 +/- 0.04 uA (3 %)
   with tau 5.4 +/- 0.4 min after power-up, independent of load. That is a ~10 mV knee shift (a
   forward-junction signature, -2 to -4 mV/C over a few degC). It is too small for reverse
   leakage (x2 per ~10 C) and too large for resistor TCR. Across sessions the leak stepped
   down about 10 % between 08-17 and 08-25 and has been flat since (26.8-29.6 uA). No recorded
   event explains the step.
5. **The node returns to the same ratio within 0.0007 after every regen burst** (2.05 V at the
   node for ~240 ms). There is no latch or hysteresis.

### 7.2 What is ruled out

| Mechanism | Why |
|---|---|
| Wrong/drifted R1-SNT or R2-SNT, ohmic contamination (~50 k), ADC gain or Vref, firmware scaling or logging | Linear: predicts gain = ratio (7.1 item 2). Also: `SCALE_V_RGN` = `SCALE_V_CHG` (`.ino:2030/2032`), and logged values sit on integer ADC counts |
| ADC carry-over, settling, ADC1/ADC2 mismatch | Pins 38/39 are adjacent channels 1/2 on the **same ADC2** with identical settings; sampling settles in ~87 time constants; pin 38 reads 0.994 |
| i.MX keeper, pull-down, in-spec input leakage | Keeper 105-175 kOhm (≤ 14.5 uA), pull-down ≤ ~22 uA, IIN ≤ 1 uA (IMXRT1060CEC Rev 4 Table 22); `analogRead` clears the keeper; the firmware configures neither pad |
| Healthy TL431 REF current | 2 typ / 4 max uA (+ ≤ 2.5 uA over temperature) gives a ratio ≥ 0.968; REF current *falls* as a healthy part warms (TI Fig 6-2), the opposite of the logs |
| Swapped pinout (TL432 / CJ431-style substitute) | REF fed from V-MOT via R-GS/R-G pulls VG onto the 12 V zener (Vz 11.4-12.7 V, `BZT52C_Diodes.pdf`). Q-SNT would turn hard on and the dump would draw 0.34 A continuously (idle measures 0.008-0.03 A; post-peak decay bounds the V-MOT load to 7-20 mA). REF current 4-13 mA, over the 10 mA abs max. The tap would clamp flat instead of tracking. The design data are correct: the board file, Gerbers and PnP map U-SNT pad 1 to R-G, pad 2 to RGN-V, pad 3 to GND = TI DBZ pinout (SLVS543S Table 5-1) |
| Layout leak or short | RGN-V is one top-copper island (tap, U-SNT pad 2, a single 0.254 mm trace without vias, Teensy pin 39, J2 pins 35/36), next only to the GND pour and R1-SNT's own pad. CHG-V has comparable GND-pour exposure and reads correctly |
| BSP170P gate / zener / R-GS path | Not on the RGN-V net. With the chopper off, VG ≈ V-MOT, so the zener sees ~0 V (IR 0.1 uA at 8 V) |
| Chopper oscillation or aliasing | No spectral signature; phase flat; noise at the ADC floor |

Case A (the node is genuinely loaded) is therefore **~0.9+**. The only case-B survivor needs
two independent defects: a series break before pin 39 plus a nonlinear sink at the pad.

### 7.3 Where the sink is (ranked; remote data cannot separate these sites)

| Site | Probability | For | Against |
|---|---|---|---|
| **TL431 REF path, cathode effectively open** (U-SNT pin 1 joint open or cracked, or R-G 0402 open or tombstoned) | ~0.30 | TI Fig 8-2: Q1's collector ties to CATHODE, so with it open the part powers its internal bias through REF: a two-junction-plus-resistor I-V. An ordinary assembly defect, present from the first log. The chopper could then **never** trip | The magnitude is an order-of-magnitude estimate. The physics reviewer expects a lower slope (~3.5-4 k) from parallel internal paths unless the floating node self-biases |
| **TL431 internal damage, cathode connected** (input NPN beta ~1, or the PNP-clamp / Darlington path in Fig 8-2 conducting) | ~0.25 | Matches the knee (~2 Vbe) and the few-k to 10 k slope. The Darlington path gives 2 Vbe + 10.15 k directly | Needs an ESD or handling event: R1 limits REF to < 0.5 mA even at 40 V, so there is no in-circuit overstress route. Typical ESD damage shows as leakage or a short, not a clean loss of gain |
| **Damaged Teensy pin-39 pad** (ESD structure leaking to VSS) | ~0.20-0.28 | Pin-specific, so it fits pin 38 being clean. Exposure route: V-MOT holds charge (tau 105-122 s) behind the RT1987, so pin 39 can back-inject ~0.15 mA into a browned-out Teensy (the 2026-07-08 brownout, `docs/boost-bringup-debug.md:188`); NXP forbids driving I/O with NVCC off. The Teensy is socketed and handled | A damaged CMOS pad has no natural 2-Vbe knee. The thermal and reboot arguments are neutral (the devil's-advocate reviewer showed the reboot-continuity point does not discriminate) |
| Flux / ionic residue under U-SNT (pad 2 to pad 3, 0.53 mm) or around R2-SNT | ~0.08 | Onset near ~1.2 V; node-specific (CHG-V has no SOT-23); the SNT cluster sits 4-8 mm from the hand-soldered J-M terminal; the 08-17 -> 08-25 step could be cleaning or reheat | 31 uA needs heavy residue; the slope stays stable rather than drifting with humidity; no assembly or cleaning record |
| Other (case-B series break + pad sink, J2 35/36 bridging, unknown) | ~0.08 | Not excluded remotely | Needs two defects, or has no geometric neighbour other than GND |

All three reviewers agreed on the class and the node. They disagreed on the split inside the
TL431 family, and on TL431 vs pad: **on log data alone, TL431 vs pad is roughly 60:25**, and it
rests on the datasheet-topology analogy, not on a measurement. The cheapest discriminators are
lab steps 2 and 3 below.

### 7.4 Safety implications (assuming case A)

- **The chopper does not clamp at 22.1 V.** If the knee curve stays linear above the measured
  1.29-1.53 V node range, the trip is **~30-33 V**: 22.13 V + 78.7 k x I(2.495 V). With an open
  cathode or open R-G it **never trips**. The physics reviewer adds that the Fig 8-2 Darlington
  path may steepen into a soft clamp near ~1.8-2 V at the node. That puts the 18.1-18.3 V
  reading ceiling within reach of the **sink's own clamp**, so the true V-MOT at those peaks is
  **≥ ~24-26 V and unbounded** by this measurement. The board has no verified V-MOT clamp below
  the RT1987's 32 V operating limit.
- Ratings at stake: CAL 470 uF and C-D6 10 uF are **35 V** parts (BOM csv lines 30, 81); the
  RT1987 is rated 32 V operating / 40 V absolute maximum. POVP is grounded, so its VIN OVP is the
  33 V option, latch-off with no restart (RT1987_DS-00 Electrical Characteristics; relevant to
  D-BC-RG, whose VIN is V-MOT). Check your VESC's own input-voltage limit against ≥ 25 V (an
  online source puts the VESC EDU firmware limit HW_LIM_VIN at 27 V; this unit's hardware and
  firmware are unverified). **Until fixed, keep vehicle regen mild.**
- **Do not apply the planned fixed V_rgn correction** (x 1/0.8505,
  `docs/reviews/fw36_regen_2026-11-04/README.md:153`). The error is nonlinear: a fixed factor
  reads correctly only near 15.9 V, under-reads increasingly above it, and over-reads below
  ~14 V. `FAULT_OV_RGN` (28 V reading) is unreachable, and any V_rgn-based OV or regen logic is
  unreliable.
- `MOT_HOTPLUG_MARGIN` 3.0 V was chosen on 2026-07-08, five weeks before the first V_rgn log,
  and never calibrated. It works today only because the gap is ~2.4-2.6 V.

### 7.5 Remote checks still possible (no PCB access needed)

1. **VESC `inpVoltage` vs V_rgn** (State-98 `U` watch / `E`): at idle it should match V_bus. In a
   regen burst, case A predicts ≥ ~25 V true at an 18.2 V V_rgn reading; the linear/case-B view
   predicts ~21.4 V. This is the best remote case A/B discriminator, and it also bounds the
   true peaks. It needs the board powered.
2. **In-situ incremental impedance:** briefly enable the i.MX internal pull-up on pin 39 (and
   on pin 38, unfed, as the calibration) and record the ADC shift. A loaded node shows ~5-6 kOhm
   effective source impedance instead of 8.87 kOhm.
3. **Die-temperature test:** log `tempmonGetTemp()` beside V_rgn while switching the ARM clock
   between 150 and 816 MHz for several minutes each. If the ratio tracks die temperature, that
   implicates the pad; no response points off-chip.
4. **Ask the operator:** who assembled the board, with what flux and cleaning; whether U-SNT came
   from the DigiKey TI reel; any rework, cleaning or Teensy re-seat between 08-17 and 08-25 or
   before 08-12; any photo of U-SNT (pin 1 joint, marking) and R-G.

### 7.6 Lab plan (cheapest decisive first; supersedes section 6's order)

1. (2 min, powered, MOT_PWR closed, ~15.9 V, after a 10-15 min warm-up) DMM the node at R2-SNT
   top / U-SNT pin 2 and at the Teensy pin-39 header.
   - Both ~1.52 V: case A.
   - R2 top 1.80 V with pin 39 at 1.52 V: series break plus pad sink.
   - 1.80 V at both: ADC path.

   In the same session, measure across R-GS (should be ~0 V; 11-13 V would mean a swapped part)
   and touch-check R-SHUNT (should be at ambient).
2. (1 min, same state) DMM **U-SNT pin 1 on the device lead** and **the VG side of R-G**, both to
   GND. Both ~V-MOT: cathode connected. Device pin ~0.9 V with VG at V-MOT: open joint or open
   R-G. Unpowered, R-G should read ~220 Ohm from U-SNT pin 1 to VG. **This splits the two TL431
   variants.**
3. (5 min, no solder) **Unplug the Teensy** from J1/J2. Feed V-MOT from a current-limited supply
   with the VESC disconnected and DMM the node. Recovery to V-MOT / 8.87 means the pad; still
   loaded means a board-side sink. Alternatively, fit the spare HIL Teensy and log the ratio.
4. (10 min, Teensy out, V-MOT ≤ 20 V) Sweep V-MOT 8-18 V and DMM the node. The knee model
   predicts the ideal 0.902 / 1.127 V at 8 / 10 V, then ~1.28-1.30 V at 12 V, 1.39-1.42 at 14,
   1.50-1.53 at 16 and ~1.63 at 18 V. A constant ratio would contradict section 7.1.
5. (5 min) Freeze-spray, separately, U-SNT, the R1/R2-SNT area and the Teensy while watching the
   node. Under the junction model, cooling the sink raises the node ~2 mV/degC.
6. (15 min) If the sink is board-side: clean with IPA and re-measure. If no recovery, reflow U-SNT
   pin 1 and R-G, or replace U-SNT with a new TL431BIDBZR. Expect 1.796 V at 15.93 V. Curve-trace
   the removed part (REF to anode, cathode at ~15 V through ~3.5 k): a damaged part draws ~30 uA
   at 1.5 V with a ~1.2 V knee, a new part < 1 uA.
7. (last, only after the sink is removed) The chopper trip test (section 6 step 5): expect
   ~22.1 V. **Do not ramp past ~28 V with the original part fitted.** Do not bridge SOT-23 pins
   1-2 with a probe: that turns the dump on (~0.34 A, 5.4 W).


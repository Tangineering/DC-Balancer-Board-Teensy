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
- **A wrong resistor value on its own.** 0.1 % thin film cannot produce the 2 % drift between
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
| Resistor to GND (fixed ratio, about 47-56 kOhm) | 48-53 uA | **25.9-26.5 V** (22.13 V / ratio) |
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

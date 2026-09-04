# The droop-authority gap: designed 2.014 Ω per unit MDAC gain against a realized 0.45–0.54 Ω (2026-09-03)

## 1. Scope and verdict

This note resolves the standing open finding recorded at `tools/hil_electrical.py:155-198`
and `tools/hil_plant_sim.py:452-495`: the bus droop realized on the board is approximately
one quarter of the value the MDAC droop chain predicts. The analysis is a desk analysis. No
bench was available, so every number comes from the design documents, the schematic, the
firmware constants, or an existing fit of recorded bench logs.

The verdict is stated first. **The deficit is a near-proportional factor of 4.0 to 4.7 on the
droop term alone, and it localizes to the MDAC-plus-op-amp gain block.** The rest of the chain
is confirmed by an independent measurement: the fuel-cell-boost feedback divider, the injection
resistor and the regulator reference are all corroborated by the no-load intercept of the same
bench fits, to better than 0.2 %. The INA253 variant mixup, the RD1 retune, the op-amp output
ceiling and the reference point of the two figures are each refuted or bounded below the
observed factor. The realized gain from the current-sense output to the op-amp output is
**1.11 to 1.33 V/V per unit commanded code fraction, against 5.02 designed**.

The residual uncertainty is the mechanism inside that block. Two mechanisms remain open, and one
bench measurement separates them (section 8).

---

## 2. The designed chain, constant by constant

| Symbol | Value | Source |
|---|---|---|
| `K_sns` | 0.1 V/A | `teensy_controller/teensy_controller.ino:2206`; INA253A1IPWR fitted (CLAUDE.md §5) |
| `A_v` | 5.02 = 1 + 40.2 k/10 k | `.ino:2207`; schematic `ROP2-FC` 40.2 kOhm, `ROP1-FC` 10 kOhm |
| MDAC gain | `g = D/4096`, 12-bit | `.ino:1937` (`MDAC_res` 4095), AD5443YRMZ |
| `R_D1` | 215 kΩ (bodged) | 2026-07-11 retune, `docs/boost-bringup-debug.md:232`; the schematic prints `237kOhm` |
| `R_D2` | 10 kΩ | schematic `RD2-FC` |
| `R_inj` | 53.6 kΩ | schematic `RINJ-FC` |
| `V_ref` (FB) | 0.6 V | `tools/hil_electrical.py:102` |
| `R_f` | 0.033 Ω = 0.010 + 0.021 + 0.002 | `tools/hil_electrical.py:203` |
| `K_DROOP` | 0.30 Ω | `.ino:2217` |
| gain map | `g = K_DROOP/(RE_MAX·r)` | `.ino:10905-10906` |

Feedback-node superposition (`controller_design/system_model.md:63-73`) gives

    V_out = V_ref·(1 + R_D1/R_D2 + R_D1/R_inj) − (R_D1/R_inj)·V_op
    V_op  = A_v·g·K_sns·I_out
    R_e(g) = K_sns·A_v·(R_D1/R_inj)·g = 0.1 × 5.02 × 4.0112 × g = 2.0136·g  [Ω]
    V_0    = 0.6 × 26.5112 = 15.9067 V

At the share ratio `r` = 0.5 the firmware commands `g` = 0.30/(2.014 × 0.5) = 0.29791, so the
designed single-source bus slope is 2.014 × 0.29791 + 0.033 = **0.6330 Ω**. This reproduces
`DROOP_DESIGN_SINGLE_OHM` = 0.63287 (`hil_electrical.py:208`).

---

## 3. The realized chain, from 39 bench slope fits

`docs/modeling/asymmetry_fit_20260901/fit_summary.json`, key `per_channel_droop`, holds 39
single-source least-squares fits of `V_bus` against one channel's current, taken from the SD
bench logs (`TP0004`–`TP0120`, `WP0040`–`WP0100`) by
`tools/benchlog_analysis/asymmetry_fit.py:380-417`. Each fit reports the commanded MDAC gain
`g_cmd`, the slope `R_meas_ohm` and its standard error. The commanded gain spans 0.184 to 0.441,
so the set resolves the *slope against `g`*, which the two end-to-end anchors (0.16 V/A single,
0.074 V/A shared) cannot.

Weighted fits of `R_meas` against `g_cmd`, weights 1/se²:

| model | result | χ²/dof | deficit vs design |
|---|---|---|---|
| `R = m·g + b`, both free | m = 0.535 ± 0.026, b = −0.0201 ± 0.0064 | 382/37 | slope 3.76 |
| `R = m·g`, b forced 0 | m = 0.4549 ± 0.0063 | 484/38 | 4.43 |
| `R = m·g + 0.033`, b forced to the series floor | m = 0.3226 ± 0.0094 | 1096/38 | 6.24 |
| `R = c·g^n` | c = 0.5314, n = 1.108 ± 0.053 | 404/37 | 3.79 at g = 1 |

Per channel, the free affine slopes are 0.536 ± 0.016 (FC) and 0.590 ± 0.032 (BT); the median
of `R_meas/g_cmd` over all 39 fits is 0.448, range 0.373 to 0.512. The deficit is therefore
**4.0 to 4.7**, weakly dependent on `g`: expressed against the commanded share ratio it is 5.2
at `r` = 0.85 (`g` = 0.175), 4.5 at `r` = 0.5, and 4.0 at `r` = 0.15 (`g` = 0.993).

The fitted no-load intercepts of the same 39 windows lie in 15.9118 to 15.9343 V, against the
designed `V_0` = 15.9067 V. This is the independent confirmation of section 4.

---

## 4. Candidate table

| # | Candidate | Verdict | Arithmetic |
|---|---|---|---|
| 1 | INA253 A1 fitted where A3 was intended | **Does not explain** | Two independent refutations, below |
| 2 | The RD1 = 215 k retune not propagated | **Does not explain** | 237 k → 215 k changes `R_D1/R_inj` from 4.4216 to 4.0112, a 9.3 % effect. Every constant in `system_model.md:364`, `hil_electrical.py:123` and the `.ino` already carries 215 k, and the fitted intercepts confirm it |
| 3 | OPA197 moved to the 5 V rail | **Partially, at the floor only** | The 4.9 V ceiling is never approached: the largest commandable `V_op` is 5.02 × 0.993 × 0.1 × 1.4 A = 0.70 V. The *floor* is live — `V_op` sits 29 to 211 mV above the amplifier's own negative rail over the bench windows, and a floor effect predicts exactly the observed negative apparent intercept and the exponent above 1 |
| 4 | AD5443 reference and full scale | **Leading, unresolved** | The schematic wires the DAC in voltage-switching mode, not as an I-V converter (section 5). The datasheet prints no transfer equation for that mode, and characterizes nothing below `V_REF` = 2 V. The `D/4096` tap gain is the least-verified link in the chain |
| 5 | TPS61288 FB-node impedance and loading by `R_inj` | **Does not explain** | The superposition already carries `R_inj` as a third arm; `h_2/h_1 = R_D1/R_inj` exactly (0.151302/0.037720 = 4.0112). The intercept confirms the whole arm |
| 6 | Reference point of the two figures | **Consistent, but the floor treatment is not** | Both are bus-referred slopes against the firmware-reported current, so they are comparable. However `DROOP_SCALE` subtracts `R_f` = 0.033 Ω from the measured side, and the bench data prefers an apparent intercept of −0.020 Ω over +0.033 Ω by χ² 382 against 1096 |

### 4.1 Why candidate 1 fails, twice

First, from the documents. The 0.633 Ω design figure is derived with `K_sns` = 0.1 V/A at every
site that states it: `system_model.md:55` and `:80`, `hil_electrical.py:120`, `.ino:2206`. No
document derives it with 0.4 V/A. The factor of 4 is a coincidence of the A3/A1 ratio, not a
provenance.

Second, and decisively, the bus-referred droop expressed against the *firmware-reported* current
is exactly invariant to the sense gain. Let `K_true` be the fitted part's true gain. Then

    dV/dI_true = K_true·A_v·(R_D1/R_inj)·g          and    I_rep = (K_true/0.1)·I_true
    dV/dI_rep  = K_true·A_v·(R_D1/R_inj)·g · (0.1/K_true) = 0.1·A_v·(R_D1/R_inj)·g

The `K_true` cancels. A wrong sense variant moves the reported current and the realized droop by
the same factor, so it cannot appear in this measurement at all, in either direction.

---

## 5. Where the deficit sits

Sections 3 and 4 leave one product to absorb the whole factor. With `R_D1/R_inj` = 4.0112
confirmed by the intercepts, the realized value of `K_sns·A_v` is

    proportional model:  0.4549 / 4.0112 = 0.1134 V/A     (A_v,eff = 1.134 at K_sns = 0.1)
    free affine model:   0.5352 / 4.0112 = 0.1334 V/A     (A_v,eff = 1.334 at K_sns = 0.1)

against 0.1 × 5.02 = 0.502 V/A designed. The gain block between the current-sense output and the
op-amp output delivers between 1.11 and 1.33 V/V per unit commanded code fraction where 5.02 was
designed.

The schematic explains why this block is the weak point. Read from the EAGLE source
(`references/Scale_Car_Board_20260624.sch`) and the PDF sheets 1 and 2, the AD5443 is wired in
**voltage-switching mode**, not in the datasheet's standard current-output configuration:

- `SNS-FC.OUT` (INA253 pin 13) drives `MDAC-FC.IOUT1` (pin 1) on net `FC-CURR`.
- `MDAC-FC.IOUT2` (pin 2) and `MDAC-FC.GND` (pin 3) are grounded.
- `MDAC-FC.VREF` (pin 9) is the *output*, and drives `OP-FC.+IN` on a two-member net.
- `MDAC-FC.RFB` (pin 10) is tied to the op-amp output `VDROOP-FC`, which is also `ROP2-FC.2`
  and `RINJ-FC.1`.
- `OP-FC` is a non-inverting stage, `ROP1-FC` 10 kOhm from `−IN` to ground and `ROP2-FC`
  40.2 kOhm from `−IN` to the output. No other component touches the stage.

Two mechanisms are consistent with the measurement, and the arithmetic cannot separate them:

**M-A, the op-amp stage does not realize 5.02.** A realized `A_v` between 1.11 and 1.33 is what
the data implies directly. A unity-gain follower (`A_v` = 1, which is what the stage becomes if
`ROP1` is open) predicts a slope of 0.4011 Ω against the proportional fit's 0.4549 ± 0.0063.
A decade error on `ROP2` — 4.02 kΩ fitted where 40.2 kΩ was specified, the EIA `4021`/`4022`
slip — gives `A_v` = 1.402 and a slope of 0.5623 Ω, against the free affine fit's
0.535 ± 0.026. Both bracket the measurement, and both would affect the two channels identically,
which is what is observed (FC 0.536, BT 0.590).

**M-B, the DAC tap does not realize `D/4096`.** An attenuation of about 3.8 at the `VREF` node
produces the same bus behaviour with `A_v` = 5.02 intact. Four facts from
`references/Datasheets/ad5426_5432_5443.pdf` (Rev. H) keep this open:

1. The Voltage Switching Mode section (p. 17, Figure 44) prescribes the wiring the board uses —
   `V_IN` to `IOUT1`, `IOUT2` to AGND, output at `VREF`, buffered by an op amp — but **prints no
   transfer equation for it**. The `g = D/2^n` gain asserted at `system_model.md:56` and
   `:372` is not sourced from the datasheet; the datasheet's `V_OUT = −V_REF × D/2^n` (p. 15)
   is stated for current mode only. `system_model.md:372` already carries the matching
   `TODO(verify)`.
2. The same section states that in this mode "the full range of multiplying capability of the
   DAC is lost", and that unequal source-drain drive on the ladder switches "degrades the
   linearity of the DAC". No threshold voltage and no numbers are given.
3. **Every static specification is taken at `V_REF` = 10 V.** The only figures that sweep the
   reference (INL and DNL versus reference voltage, p. 9) start at 2 V. The board runs this
   ladder at 3 to 62 mV at the tap and 5 to 140 mV at `IOUT1` — two to three decades below
   anything the datasheet characterizes.
4. The board deviates from Figure 44 on one connection. The internal `R_FB` resistor
   (value `R`, 8/10/12 kΩ min/typ/max, p. 15) has its far end on the `IOUT1` node; Figure 44
   ties the `RFB` pin back to the `V_IN`/`IOUT1` node, which shorts it. The board ties `RFB`
   to the op-amp output instead. At DC this places `R` across `V_op − V_IN`, drawing at most
   10 µA from the INA253 output, and it does not touch the `VREF` tap — so it is benign for the
   gain, but it is an undocumented deviation and is recorded here.

Neither the ±20 % ladder tolerance (p. 3), nor the ±10 mV maximum gain error at
`V_REF` = 10 V (p. 3), nor the ±10 nA output leakage (0.1 mV across 10 kΩ) approaches a factor
of four.

M-A and M-B are indistinguishable in every recorded bench log, because every log observes only
the bus.

---

## 6. What this implies for the constants

**Firmware.** `K_sns` = 0.1 V/A is correct for the fitted parts and, per section 4.1, is not the
gap. `RE_MAX` = 2.014 Ω is the *designed* maximum electronic droop and is not realized;
the realized value is 0.45 to 0.54 Ω. `K_DROOP` = 0.30 Ω is a *design intent*, not a measured
resistance: the board realizes 0.068 to 0.080 Ω. The `g = K_DROOP/(RE_MAX·r)` mapping is
internally consistent and is not itself at fault; what it produces is a droop about 4.5 times
weaker than the label. Two consequences follow, and neither is a defect that a firmware change
should chase before section 8 is executed:

1. The `g ≤ 1` bound and the `[DROOP_R_MIN, DROOP_R_MAX]` = [0.15, 0.85] band are set by
   `RE_MAX`; at the realized authority the band is far narrower in droop terms than the firmware
   believes, and the whole band lives inside a 0.07 to 0.51 Ω span.
2. The share loop is a closed loop with integral action, so it finds the ratio that delivers the
   commanded share regardless of the absolute droop. The gap costs *authority and stiffness*, not
   share accuracy.

**Plant constants.** `DROOP_SCALE["measured"]` = (0.16 − 0.033)/(0.63287 − 0.033) = 0.21171 is
arithmetically correct for what it claims, but its premise is not supported: it subtracts the
0.033 Ω series floor from the measured side, and the 39-window fit prefers an apparent intercept
of −0.020 Ω. The bench-implied per-channel law is

    free affine:    R_single(g) = 0.535·g − 0.020    →  k_d,eff = 0.0797 Ω,  R_f,eff = −0.020 Ω
    proportional:   R_single(g) = 0.4549·g          →  k_d,eff = 0.0678 Ω,  R_f,eff =  0

against `--droop measured`'s implied pair `k_d` = 0.0635 Ω with `R_f` = +0.033 Ω.

**The split law.** `docs/modeling/governor_split_law_20260903.md` §2 depends on the *ratio*
`k_d/R_f`, which is 9.09 under `--droop design`, 1.92 under `--droop measured` and 0 to −4.0
under the bench per-channel fits. The three disagree materially away from `r` = 0.5. At
`r` = 0.20 and `I_tot` = 2.0 A, with the M2 asymmetry parameters, the delivered share is 0.2235
(design), 0.2558 (`--droop measured`) and 0.1869 (bench affine); at `r` = 0.75 and 1.2 A it is
0.7571, 0.7237 and 0.7962. The §5.1 validation of the split law is against campaign F, which is
an HIL campaign whose currents come from the simulated plant at `--droop design`; it therefore
validates the law's algebra, not its constants. The §5.2 CAL-1 validation is bench data but sits
at `r` = 0.5, where the law is insensitive to the magnitude of `k_d`.

---

## 7. What remains uncertain

- The mechanism inside the gain block (M-A against M-B). Nothing in the repository observes any
  node between the INA253 output and the feedback node.
- The apparent negative intercept. Across the 39 windows the fitted `V_0` correlates with `g_cmd`
  at +0.504, with a slope of +0.054 V per unit `g`; at the windows' current level of roughly
  0.5 A that drift alone maps to +0.108 Ω per unit `g` of apparent slope. The intercept and the
  superlinearity are therefore not established independently of that confound, which is why the
  deficit is quoted as a range and not as a single number.
- The shared-regime residual. The bench pair 0.1615/0.0740 V/A has a ratio of 2.182 where a
  parallel Thevenin pair gives exactly 2.000. The per-channel law above predicts 0.1394 single
  and 0.0697 shared, that is −14 % and −6 % against the two anchors, and does not close the ratio
  either. The two anchors come from a different log set (TP0170–0180, ML0165, ML0169) than the 39
  windows.
- Whether the DAC's `D/4096` tap gain holds in this configuration at tens of millivolts. The
  datasheet neither prints the equation nor characterizes the part there, so this cannot be
  closed from documents. `TODO(verify: bench, ad5426_5432_5443.pdf p. 17)`.
- The OPA197 input offset voltage acts on a tap of 3 to 62 mV. At the 500 µV maximum the
  amplifier contributes up to 2.5 mV at `V_op` and 10 mV at `V_0`, which is the scale of the
  22 mV spread seen in the 39 fitted intercepts. This is an offset, not a slope, so it does not
  enter the deficit; it is recorded because it bounds how tightly `V_0` can ever be pinned.

---

## 8. The one bench measurement that settles it

**Measure the three DC node voltages of one droop chain simultaneously, at a known steady current
and a known commanded MDAC code.**

Procedure:

1. Put the board in State 98 and open one source only, so that the channel under test carries
   the whole bus current.
2. Command a known droop code. Use `g` = 0.500 (`r` = 0.298 through the firmware map, or the
   open-loop droop command).
3. Hold a steady load current of 1.000 A on that channel. Read the current from the channel's
   own telemetry.
4. Measure three DC voltages against board ground with a 6.5-digit meter: `FC-CURR` (INA253
   pin 13), the `MDAC-FC.VREF` / `OP-FC.+IN` net (schematic net `N$7`), and `VDROOP-FC`
   (`OP-FC.OUT`).

Expected values at 1.000 A and `g` = 0.500:

| node | design | M-A, `A_v` = 1 | M-A, `A_v` = 1.402 | M-B, tap short by 3.8 | candidate 1 alive |
|---|---|---|---|---|---|
| `FC-CURR` | 0.1000 V | 0.1000 V | 0.1000 V | 0.1000 V | 0.4000 V |
| `N$7` (DAC tap) | 0.0500 V | 0.0500 V | 0.0500 V | 0.0132 V | 0.2000 V |
| `VDROOP` | 0.2510 V | 0.0500 V | 0.0701 V | 0.0663 V | 1.0040 V |
| implied bus droop | 1.007 Ω | 0.201 Ω | 0.281 Ω | 0.266 Ω | 1.007 Ω |

The first node settles candidate 1 outright. The ratio `N$7`/`FC-CURR` settles the DAC tap
against its commanded code. The ratio `VDROOP`/`N$7` settles the op-amp stage gain. One reading
of the three separates every hypothesis in this note.

If the meter cannot be trusted at tens of millivolts, repeat at `g` = 1.000 and 1.400 A, where
the design predicts `FC-CURR` = 0.140 V, `N$7` = 0.140 V and `VDROOP` = 0.703 V.

**Secondary, unpowered:** ohm `ROP1-FC`, `ROP2-FC`, `ROP1-BT` and `ROP2-BT` out of circuit.
Expect 10 kΩ and 40.2 kΩ. A reading of 4.02 kΩ on either `ROP2` confirms M-A directly.

---

## 9. Sources

- `controller_design/system_model.md` §2 (lines 49–90), §6e, §8 (line 364 ff.)
- `teensy_controller/teensy_controller.ino:1937`, `:1946`, `:2204-2220`, `:10905-10906`
- `tools/hil_electrical.py:102`, `:118-132`, `:155-228`
- `tools/hil_plant_sim.py:452-500`
- `docs/modeling/asymmetry_fit_20260901/fit_summary.json`, key `per_channel_droop`
- `tools/benchlog_analysis/asymmetry_fit.py:41-56`, `:380-417`
- `docs/modeling/governor_split_law_20260903.md` §2, §5
- `docs/boost-bringup-debug.md:232` (the 2026-07-11 RD1 retune)
- `references/Scale Car DC Balancer Board Schematic 2026-06-22.pdf`, sheets 1 and 2, and the
  EAGLE source `references/Scale_Car_Board_20260624.sch`
- `references/Datasheets/ad5426_5432_5443.pdf`, `OPA197IDR.pdf`, `INA253A1IPWR.pdf`

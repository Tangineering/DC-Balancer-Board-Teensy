# Bench Calibration Manual — Droop Power-Share Controller

Step-by-step procedures for measuring every `TODO(calibrate)` value the controller
design depends on (`system_model.md` §8, `controller_synthesis.md` §8), using only
State 98 of the shipped firmware, two bench supplies, an electronic load, a DMM, and
a scope. Section 8 maps each measured number to the file/constant it updates and the
regeneration sequence.

**What gets measured:**

| # | Quantity | Symbol | Assumed today | Procedure |
|---|---|---|---|---|
| 1 | No-load setpoint per channel | $V_{0,FC}, V_{0,BT}$ | 15.91 V each (RD1 = 215 k retune) | CAL-1 |
| 2 | Setpoint mismatch | $\Delta V_0$ | ±0.40 V budget | CAL-1 (+ CAL-2 cross-check) |
| 3 | Realized droop resistance vs MDAC gain | $R_e(g)$, i.e. $R_{e,max}$ | 2.014 Ω at $g=1$ | CAL-1 |
| 4 | TPS61288 FB reference | $V_{ref}$ | 0.6 V | CAL-1 (inferred) + datasheet |
| 5 | Static share map | $\alpha(r)$, slope ≈ 1 | exact by design | CAL-2 |
| 6 | Converter/droop-path lag | $\tau_r$ | 100 µs (20–300) | CAL-3 |
| 7 | Command-to-hardware latency | part of $T_d$ | < 0.1 ms assumed | CAL-3 |
| 8 | Droop scale decision | $k_d$ (`K_DROOP`) | 0.30 Ω | CAL-4 |
| 9 | Bus capacitance (optional) | $C_{bus}$ | 0.5–1 mF (Run) | CAL-5 |
| 10 | Share noise floor (optional) | σ(α) | LSB/$I_{tot}$ model | CAL-5 |

---

## 1. Equipment

- **PSU-A ("fuel cell")** → J-FC: 9–12 V, ≥ 5 A, current limit available.
- **PSU-B ("battery")** → J-BT: 8.0 V, ≥ 8 A. **Stiff** — it also powers the Teensy
  through the LM1084 (logic baseline ~0.25 A). A soft/current-starved supply here is
  the brownout/motorboating failure mode from the debug history. Do not use a 9 V
  battery for calibration.
- **Electronic load** on the VESC terminal J-M (V-MOT), **CC mode** (not CP — CP
  emulates the destabilizing constant-power load; CC gives clean fits). Resistor
  alternative: 10 Ω / ≥ 50 W (≈ 1.6 A at 16 V), two in parallel for ≈ 3.2 A.
  **Disconnect the VESC** for all calibration work.
- **DMM** (the ADC's V_bus LSB is ~4.5 mV; use the DMM at the terminals for V₀ fits).
- **Scope**, ≥ 2 ch, for CAL-3 only. Probe points: `FC-CURR` (Teensy pin 40 on header
  J2 — the INA253 analog output, 0.1 V/A) and `CS-MDAC-FC` (pin 36) as the timing
  reference.
- USB serial terminal to the Teensy (State 98 commands; `H` prints the command list).

## 2. Safety rules (from the boost-death history — do not skip)

1. **Never enable a bus switch (`1`/`2`) or `MOT_PWR` (`3`) onto a discharged node at
   full bus.** Always start the power stage with `G` (guarded bring-up: switches →
   settle → boosts, motor node pre-charged). The firmware guards refuse the known-bad
   orders, but treat the guards as the backstop, not the procedure.
2. PSU-B must comfortably exceed the logic baseline (≥ 1 A headroom above the test
   current) at all times — a sagging VBT reboots the Teensy mid-test.
3. Confirm the **BT-boost bodge caps** (10 µF + 0.1 µF at the BT TPS61288 output) are
   present before any BT-channel work.
4. Keep V_bus below 17.0 V (the FW OV limit at the 16 V nominal; HW OVP is 19 V with little margin to the
   20 V SW abs-max).
5. Current limits: set PSU-A limit ≈ 5 A, PSU-B limit ≈ 8 A. Remember a supply
   current limit does **not** bound boost self-destruction energy — the sequencing
   rules above are the real protection.

## 3. Common setup (start of every session)

1. Flash the firmware with `BENCH_TEST=1` (default) — boots to Idle, power stage dark.
2. PSU-B on first (Teensy boots), then PSU-A. Open the serial terminal.
3. `T` → State 98. `S` → confirm all switches LOW, rails sane.
4. `G` → guarded bus bring-up. `S` → expect `V_bus ≈ 15.8–15.9 V`, `MOT_PWR = 1`,
   both bus switches ON, both boosts ON.
5. E-load connected at J-M, initially 0 A / off.

The `O` command (open-loop droop write) is the calibration workhorse: it maps a typed
ratio r directly to MDAC gains `g_F = K_DROOP/(RE_MAX·r)`, `g_B = K_DROOP/(RE_MAX·(1−r))`
with no feedback, and prints the gains it wrote. `S` prints V_bus, I_fc, I_batt.

---

## CAL-1 — Per-channel V–I lines → V₀, ΔV₀, Rₑ(g), V_ref

*Principle:* with one source alone on the bus, $V_{bus} = V_0 - R_e(g)\,I$. A straight-line
fit of V_bus vs I gives the intercept $V_0$ (the no-load setpoint, no zero-load
measurement needed) and the slope $R_e(g)$ (the whole droop chain gain, end to end).

**FC channel:**
1. From the §3 state, isolate FC: `2` (BT_BUS OFF — safe; the RT1987 fully isolates
   the still-running BT boost).
2. `O` → `0.5` (both MDACs at g = 0.2980; predicted $R_e = 2.0136 × 0.2980 = 0.600\ Ω$).
3. Step the e-load through **0.2 / 0.5 / 0.8 / 1.2 / 1.6 / 2.0 A**. At each point,
   after ~2 s, record: DMM V_bus at the load terminals, and `S` readouts of `I_fc`,
   `V_bus` (the ADC copies double as a scale-factor check).
4. Least-squares fit → **V₀_FC** (intercept) and **Rₑ_FC@0.5** (slope).
5. Repeat step 2–4 with `O` → `0.3` (g_F = 0.4966, predicted 1.000 Ω) to confirm the
   slope scales linearly with g. Two points in g are enough.

**BT channel:** `2` (BT_BUS back ON), then `1` (FC_BUS OFF), repeat steps 2–4.
(Re-enabling a switch with the bus held up by the other source is safe — both sides
are near the same voltage; the hot-plug guard only fires on a *discharged* bus.)

**Restore:** `1` (FC back ON).

**Results and how to read them:**
- $\Delta V_0 = V_{0,FC} - V_{0,BT}$. Expect within the ±0.40 V budget; record sign.
- Slope vs prediction calibrates the chain: $R_{e,max}^{meas} = \text{slope}/g$.
  If it differs from 2.014 Ω by more than ~5 %, the K_sns·A_v·R_D1/R_inj product is
  off (most likely suspect first: check the fit, then A_v and the resistor values).
- $V_{ref}^{inferred} = V_0 / 26.511$ (RD1 = 215 k). Datasheet (verified, §7.5): 0.588–0.612 V,
  0.600 typ — the ±2 % spread is exactly why the per-board ΔV₀ measurement matters
  more than the datasheet budget; the CAL-1 value supersedes it in `K_SET`.
- Sanity: the two `S`-vs-DMM voltage pairs validate `SCALE_V_BUS` (and `SCALE_I`
  against the e-load current setting).

## CAL-2 — Static share map α(r) → slope, ΔV₀ cross-check

1. Both channels on (§3 state), e-load **2.0 A CC**.
2. `O` sweep: r = 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.85. At each,
   record `I_fc`, `I_batt` from `S`; compute α = I_fc/(I_fc+I_batt).
3. Repeat the sweep at **1.0 A** and **3.0 A**.
4. Fit α = r + ΔV₀·r(1−r)/(k_d·I_tot) with ΔV₀ as the only free parameter
   (k_d = 0.30). Checks:
   - slope ≈ 1 in the mid-range (0.3–0.7) at 3 A (mismatch term flattest there);
   - fitted ΔV₀ agrees with CAL-1's direct difference;
   - the offset scales as 1/I_tot across the three load levels.
   - If α pins near 0 or 1 at the sweep edges at 1 A: that is the RT1987 diode
     clamp region predicted by the model (§3) — note the (r, I_tot) boundary.

## CAL-3 — Dynamics: τ_r and hardware latency (scope)

1. Both channels on, e-load **2.0 A CC**. Scope CH1 = `FC-CURR` (pin 40), ~50 mV/div,
   offset to the standing level; CH2 = `CS-MDAC-FC` (pin 36); single-shot trigger on
   CH2 **rising** edge (end of the SPI write).
2. `O` → 0.3, arm the scope, then `O` → 0.7. The FC current steps by
   Δα·I_tot ≈ 0.8 A → **80 mV** on CH1.
3. Measure on the capture:
   - **hardware latency** = CH2 rising edge → 10 % of the CH1 movement. Expect
     ≤ ~50 µs. This is the only *measured* piece of $T_d$ — the rest
     (ZOH $T_s/2$ + one-sample latch ≈ 1.5 ms worst) is architectural and already
     modeled.
   - **τ_r** = exponential time constant of the CH1 settle (or (10→90 %)/2.2).
     Expect within the modeled 20–300 µs. Note any overshoot/ringing (bus
     interaction) — shape, not just number.
4. Repeat 5× in each direction (0.7→0.3 too); take the slowest τ_r seen. Capture
   **both channels** (trigger on `CS-MDAC-BT`, pin 37, for the BT edge): both now run
   R_C = 61.2 k (BT bodged from 27.4 k to match FC — schematic not yet updated), so
   the two lags should be near-identical; expect ~10–40 µs per `system_model.md` §6e.
5. **Converter-ringing check (BT operating floor):** with PSU-B at 7.4 V (the system's
   battery floor — the pack is kept at 7.4–8.4 V) and the BT channel at the maximum
   planned per-channel current, watch VOUT-BT for sustained ringing after the step.
   §6e predicts the R_C bodge leaves ≥ 30 % RHP-zero margin over this envelope
   (guideline OK to 3.6 A/channel at worst-case derating, 4.8 A counting the bodge
   caps), so this is a confirmation check. Ringing would be a converter-loop finding,
   not a share-loop problem — if seen, note the (V_in, I) boundary.
6. If τ_r > 300 µs or latency > 200 µs: widen `TAUR_SET` / `TD_SET` in
   `synthesize_controller.py` accordingly before regenerating (the current design
   tolerates up to 2 ms total delay with margin, so this is bookkeeping, not alarm).

## CAL-4 — k_d decision (bus sag + authority span)

1. Both channels on, `O` → 0.5. Record V_bus at 0.5 A and at the maximum planned
   vehicle bus current (e-load). Sag slope should be ≈ k_d = 0.30 Ω (plus supply/wire
   drops). Verify the sagged V_bus stays above the VESC minimum input and the
   firmware UV limit at max current.
2. From CAL-2's fitted ΔV₀: the achievable share span is
   $[0.15, 0.85] \mp \Delta V_0 r(1-r)/(k_d I_{tot})$ at the operating currents.
   Confirm this covers what the EMS will request.
3. Decision: keep 0.30 Ω unless (a) sag at max current is unacceptable → lower k_d,
   or (b) measured ΔV₀ ≫ budget and the span shrinks too much → raise k_d by
   narrowing the r clamp (hard bound $k_d \le R_{e,max}\,r_{min}$; update both
   `K_DROOP` and `DROOP_R_MIN/MAX` together).

## CAL-5 — Optional: C_bus and share noise floor

- **C_bus:** with a load step (e-load transient 0.5 → 2 A), fit the V_bus settle
  time constant τ = C_bus·(k_d ∥ R_load). Only enters the model weakly (§6a) —
  measure once for the record.
- **Noise:** fixed 1 A load, fixed r = 0.5; log ~60 `S` snapshots (or UDP telemetry);
  σ(α) should be ≈ 8.06 mA/I_tot ≈ 0.8 % at 1 A. If much larger, look at switching
  ripple aliasing → consider lowering the prefilter corner (raise `TAUF`) and
  resynthesize.

---

## 8. Where every number goes + regeneration

| Measured | Update |
|---|---|
| $V_{0}$, $V_{ref}$ | `system_model.md` §8 (clear TODO); no code change |
| $R_{e,max}^{meas}$ | `RE_MAX` in `teensy_controller.ino` (replace the derived expression's value or its factors) **and** `RE_MAX` in `test_main.cpp`'s expectation; `system_model.md` §8 |
| $\Delta V_0$ | `system_model.md` §5a/§8; tighten/widen `K_SET` in `synthesize_controller.py` via the gain formula $1 + \Delta V_0(1-2r)/(k_d I_{tot})$ |
| $\tau_r$, latency | `TAUR_NOM`/`TAUR_SET`, `TD_NOM`/`TD_SET` in `synthesize_controller.py` |
| $k_d$ | `K_DROOP` (+ `DROOP_R_MIN/MAX` if the span changed) in `teensy_controller.ino`; `system_model.md` §4/§8 |
| $C_{bus}$, σ(α) | `system_model.md` §8 record; `TAUF` only if noise demands |

**Regeneration sequence (controller_synthesis.md §7):**
1. `synthesize_controller.py` → regenerates `share_controller_coeffs.h`,
   `reference_vectors.h`, metrics; every gate re-runs.
2. `cd test && mingw32-make` (MSYS2) → 316+6 tests, including the C++-vs-Python
   replay against the NEW coefficients.
3. `droop_plant.m` in MATLAB → `MATLAB_validation.txt` must end `VERDICT: PASS`.
4. Flash (`BENCH_TEST=1`), then closed-loop bench check: §3 setup, e-load 2 A,
   `P` → 0.5, then `P` → 0.7: the 500 ms status prints should show α settling onto
   the setpoint within 1–2 prints, no oscillation, gains off the rails. Then a full
   `R` power-share profile run.

## 9. Record sheet template

```
Date/operator: ____________  Board S/N: ____  Firmware: BENCH_TEST=1, commit ____
PSU-A: ____ V, limit ____ A     PSU-B: ____ V, limit ____ A    Load: __________

CAL-1  FC r=0.5: (I, V): (0.2, ____)(0.5, ____)(0.8, ____)(1.2, ____)(1.6, ____)(2.0, ____)
       FC r=0.3: (0.2, ____)(0.5, ____)(1.0, ____)(1.5, ____)
       BT r=0.5: (0.2, ____)(0.5, ____)(0.8, ____)(1.2, ____)(1.6, ____)(2.0, ____)
       V0_FC = ______ V (pred. 15.91)   V0_BT = ______ V   dV0 = ______ V
       Re@g=0.2980: FC ______ Ω  BT ______ Ω  → Re_max = ______ Ω (pred. 2.014)
       Vref inferred = ______ V (pred. 0.600)

CAL-2  I_tot = 2 A: alpha at r = .15/.2/.3/.4/.5/.6/.7/.8/.85:
       ____/____/____/____/____/____/____/____/____
       (repeat 1 A, 3 A)     fitted dV0 = ______ V   slope(0.3–0.7, 3 A) = ______

CAL-3  hw latency: __/__/__/__/__ µs (worst ____)   tau_r: __/__/__/__/__ µs (worst ____)
       overshoot/ringing notes: ________________________________

CAL-4  V_bus @ 0.5 A: ______   @ ____ A: ______   sag slope: ______ Ω (pred. ~0.30)
       k_d decision: ______ Ω   r span: [____, ____]
```

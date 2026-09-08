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

## CAL-6 — Two-axis minority-dropout boundary (per channel direction)

**Purpose.** Locate the commanded operating point at which the minority channel loses
conduction, as a function of total current and commanded share, for each minority direction.
The result decides which law the share governor should enforce. Three candidate laws predict
different boundaries; the grid below separates them through the dependence on $I_{tot}$.

| Law | Boundary in commanded share $r_{edge}$ | Signature across totals |
|---|---|---|
| Constant minority current (today: `SHARE_MINORITY_I_MIN_A`) | $I_{min}/I_{tot}$ | $r_{edge}$ falls as $1/I_{tot}$ |
| Constant MDAC gain (minority source too soft) | constant $r$ ($g = K_{DROOP}/(R_{e,max}\,r)$ constant) | $r_{edge}$ flat in $I_{tot}$ |
| Conduction margin $D = k_d I_{tot}$ | no boundary in $r$; a threshold in $I_{tot}$ alone | dropout below one total at every $r$ |

Background and evidence: `docs/modeling/low_current_share_stability_20260903.md`; the fw v3–v6
sweeps in `docs/share_sweep_whitepaper` (conclusions 11 and 15). The existing brackets are
(0.245, 0.29] A for the FC-minority direction at 1.63 A total, and (0.381, 0.399) A for the
BT-minority direction at 1.6–1.7 A, with BT dropouts at 0.55–1.04 A in the `W` cluster.

### CAL-6.1 Prerequisites

1. **Lowered floor build.** The production floor clips every setpoint below $0.30/I_{tot}$, so
   the sweep cannot reach the boundary on the production constant. Build the bench firmware with
   `SHARE_MINORITY_I_MIN_A` = **0.10 A** (a `BENCH_TEST` override; the constant is `constexpr`
   and its `static_assert`s against the fw v26 ceilings still hold at 0.10 A). Record the commit.
   Note: at 0.10 A the fw v19 handoff thresholds (`SHARE_HANDOFF_MIN_A` 0.15 A,
   `SHARE_HANDOFF_LIVE_A` 0.20 A) sit above the floor, so the reduced handoff slew rate engages on
   channels the governor considers healthy. This slows the reference walk to 0.002 per tick for at
   most 175 ticks per dark event. It does not change the boundary; record it in the run notes.
2. **Bus undervoltage fault armed.** `FAULT_UV_BUS` is armed under `BENCH_TEST` from fw v4. Confirm
   on the first collapse that the board latches State 99; the fw v3 sweep ran 64 collapses with no
   fault.
3. **Sources.** For the FC-minority half, use PSU-A and PSU-B per §3. For the BT-minority half,
   run the ladder twice: once with PSU-B, once with the **2S pack** on J-BT. The bench supply's
   1.0–1.35 Ω source impedance is the leading suspect for that direction's failures (whitepaper
   conclusion 18). Keep the USB serial link connected throughout; a log that truncates with no
   trailer record is the MCU-brownout signature (`WP0072`/`WP0073`).
4. **Logger idle.** Send `K`. When the status shows no open file, continue. The sweep refuses to
   start under plot mode; send `L` if the plotter stream is on.
5. Safety rules §2 apply unchanged. Each reconnect after a dropout is a load-dump-class event on
   the boost; **do not repeat a point that collapsed the bus.**

### CAL-6.2 Total-current calibration (once per session)

The trapezoid commands motor phase current, and the bus draw that results is bench-specific.
Measure the mapping before you choose setpoints; do not use the CAL-1 table (2/3/4/5 A →
0.145/0.452/0.935/1.346 A) except as a starting guess.

1. Complete §3 steps 1–4 (`T` → State 98, `G` bring-up, `S` shows both bus switches ON).
2. Send `P` and enter `0.5`.
3. For each command in the list, send it, wait for `[TP] Trapezoid complete`, and wait 10 s:

```
T 3 5 0.5
T 3.5 5 0.5
T 4 5 0.5
T 4.5 5 0.5
T 5 5 0.5
T 6 5 0.5
T 6.7 5 0.5
```

4. Decode each `TPnnnn.BLG` (`tools/decode_benchlog.py`). Record the plateau mean of
   `I_fc + I_batt` as $I_{tot}$ against its $I_{cmd}$ in the record sheet. Targets are
   0.45, 0.7, 0.94, 1.15, 1.35, 1.63 and 2.0 A. If a plateau misses its target by more than
   0.1 A, adjust $I_{cmd}$ and repeat that line.

Note: `T` accepts any peak up to 25 A, a hold of 0 s or more, and a rate above 0 A/s. The
0.5 A/s rate matches the fw v3–v6 sweeps, so the new brackets are comparable to the old ones.

### CAL-6.3 Closed-loop ladder

Each `T` line runs one trapezoid per listed setpoint, each to its own `TPnnnn.BLG`, with the
share loop closed and a 10 s motor cool-off between runs. The list syntax is
`[dwell_s,r1,r2,...]` with the square brackets typed literally; at most 16 setpoints per line;
setpoints must be within 0.0–1.0. The sweep returns the share to 0.5 on completion.

Setpoint arithmetic. For a minority-current target $I_m$ at the measured total $I_{tot}$:

- FC minority: $r = I_m / I_{tot}$
- BT minority: $r = 1 - I_m / I_{tot}$

Keep every $r$ inside $[0.15, 0.85]$. A setpoint outside the band is a switch cut through the
setpoint latch, not a droop point, and must not be listed. The minority targets are 0.40, 0.30,
0.25, 0.20, 0.15 and 0.10 A; drop any target whose $r$ leaves the band at that total. Order each
list from the safest setpoint to the most aggressive.

Worked lines for the CAL-1 mapping (recompute from CAL-6.2 before use):

```
FC minority, I_tot ~ 0.45 A (I_cmd 3):   T 3 5 0.5 [10,0.44,0.33,0.22]
FC minority, I_tot ~ 0.94 A (I_cmd 4):   T 4 5 0.5 [10,0.43,0.32,0.27,0.21,0.16]
FC minority, I_tot ~ 1.35 A (I_cmd 5):   T 5 5 0.5 [10,0.30,0.22,0.19,0.15]
FC minority, I_tot ~ 1.63 A (I_cmd 6):   T 6 5 0.5 [10,0.25,0.18,0.15]
BT minority, I_tot ~ 0.94 A (I_cmd 4):   T 4 5 0.5 [10,0.57,0.68,0.73,0.79,0.84]
BT minority, I_tot ~ 1.35 A (I_cmd 5):   T 5 5 0.5 [10,0.70,0.78,0.81,0.85]
BT minority, I_tot ~ 1.63 A (I_cmd 6):   T 6 5 0.5 [10,0.75,0.82,0.85]
```

Check of the lines against the goals: at 0.45 A the 0.10, 0.15 and 0.20 A targets give
$r$ = 0.22, 0.33 and 0.44, and the 0.25 A target gives 0.56, which makes the battery the minority
and is excluded; at 1.35 A the 0.20 A target gives $r = 0.148$, below the band, so the list ends
at the 0.15 band edge (0.20 A); at 1.63 A the 0.25 A target lands at
$r = 0.153$, on the band edge, and reproduces `TP0016`; the BT lines are the mirror images, and
0.85 at 1.63 A commands a 0.245 A battery minority, the mirror of that same point.

Procedure per line:

1. Send `S`. When both bus switches read ON and `V_bus` is 15.8–15.9 V, send the `T` line.
2. Watch the `[PS]` and `[TSWEEP]` status prints. When a run collapses the bus and the board
   has not latched, send `X`. Record the failing setpoint. Do not re-run it.
3. `X` during a trapezoid or a sweep cancels the sweep, zeroes the motor and returns the share to
   0.5; it does **not** park the switches (the `T` design choice). Send `S`; when both bus
   switches still read ON and `V_bus` has recovered, continue with the next line.
4. When the board latches State 99 (`FAULT_UV_BUS`), it stays latched until a power cycle.
   Power-cycle PSU-B and PSU-A per §3 step 2, send `T`, `S`, then `G`, and continue from the next
   line. Record the latch and the setpoint that caused it.
5. When a line completes naturally, the switches stay as they are; continue with the next line.
6. After the coarse ladder, bisect once at each total between the last clean and the first
   failing setpoint (one extra `T` line with a single-entry list). This closes the bracket from
   about 50 mA to about 20 mA of minority current.

Note: the ramp-down of every run is a continuous scan of $I_{tot}$ at fixed $r$. `TP0016`
ignited on its ramp-down, not on its plateau. For a run that drops out on the ramp, the total
current at the first dropout is a boundary point at that $r$; record it with the plateau result.

### CAL-6.4 Open-loop control block

This block separates a loop failure from a plant failure. Run it at two totals (about 0.45 A
and 1.35 A) in the FC-minority direction, and at 1.35 A in the BT-minority direction.

1. Send `A` and enter the $I_{cmd}$ for the total. The motor runs at fixed current.
2. Send `O` and enter the same $r$ as the closed-loop point under test. The MDACs take the ratio
   directly; the share controller is off (`powerBalanceLive` is cleared).
3. Send `K 1`. Hold for 10 s. Send `K 0`.
4. Repeat steps 2–3 for the next $r$ in the ladder. When a point collapses the bus and the board
   has not latched, send `X` (this zeroes the motor and leaves the switches as they are). When
   the board latches State 99, recover as in CAL-6.3 step 4.
5. To leave the block, send `A` and enter `0`, then send `P` and enter `0.5`.

Note: `O` accepts 0.0–1.0, and a ratio outside $[0.15, 0.85]$ opens the starved channel's bus
switch exactly as the closed loop would. Stay inside the band. `A` clamps at ±12 A.

A point that conducts in this block and cycles in CAL-6.3 fails in the loop, not in the plant;
the fw v3 `TP0016` result is confounded in exactly this way (the ratio parked on the
`DROOP_R_MIN` rail inside the cutoff hysteresis).

### CAL-6.5 Scoring and the discriminating columns

Decode every log. Score each run over its plateau with the hysteretic minority-dropout counter
(`tools/benchlog_analysis`): a channel below 20 mA while the other channel carries the total is
one dropout. A point is **clean** when it has zero dropouts, a bus minimum above 15.5 V, and a
`share_act` standard deviation below 0.03. Record for every point:

| Column | Source |
|---|---|
| achieved $I_{tot}$ | plateau mean of `I_fc + I_batt` |
| achieved minority current | plateau mean of the minority channel |
| commanded $r$ | `share_sp`, or $g_{BT}/(g_{FC}+g_{BT})$ from the log |
| MDAC gain $g$ | $0.149 / r$ (FC minority) or $0.149/(1-r)$ (BT minority) |
| depression $D$ | $0.30\,\Omega \times I_{tot}$ (design scale) |
| effective offset $\Delta V_0 / k_d$ | `tools/probes/lowcurrent_blg_offset.py` |
| verdict | clean / dropout on plateau / dropout on ramp at $I_{tot}$ = … |

Plot the failing and clean points in the ($I_{tot}$, minority current) plane per direction and
read the law from the table at the top of this section. Also compute the two-source bus droop
slope from the plateau `V_bus` against $I_{tot}$ across the ladder; this is a fourth reading of
the design-versus-measured droop gap (`docs/HIL_PLANT.md` §4.2), which sets the realized $D$.

### CAL-6.6 Second pass with the scheduled droop scale

Run this pass only when CAL-6.5 supports the margin law. Flash the bench build with the
load-scheduled $k_d$ (`WORK_QUEUE.md` §7c) and `SHARE_MINORITY_I_MIN_A` = 0.15 A. Repeat the
FC-minority lines at 0.45, 0.7 and 0.94 A with the target list reduced to 0.20, 0.15 and 0.12 A.
The question per point is whether a channel commanded at $D / R_{e,max}$ = 0.15 A holds
conduction with $D$ held at 0.30 V. Record the plateau `V_bus` on every run: the scheduled
build must show a constant 0.30 V (design scale) depression below 1 A instead of a slope.

**Scale.** Seven totals, three to six points each, two directions plus the pack repeat, the
open-loop block and the bisections: about 90 runs of 30 s plus cool-off, roughly 90 minutes.

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

CAL-6  build: SHARE_MINORITY_I_MIN_A = ____ A, commit ____   BT source: PSU-B / pack
       I_cmd -> I_tot (A): 3:____ 3.5:____ 4:____ 4.5:____ 5:____ 6:____ 6.7:____
       FC minority — last clean / first dropout (minority A, r, g, D) per total:
         0.45: ____/____   0.70: ____/____   0.94: ____/____   1.15: ____/____
         1.35: ____/____   1.63: ____/____   2.00: ____/____
       BT minority — same columns:
         0.45: ____/____   0.70: ____/____   0.94: ____/____   1.15: ____/____
         1.35: ____/____   1.63: ____/____   2.00: ____/____
       open-loop block (conducts / cycles): 0.45 FC ____  1.35 FC ____  1.35 BT ____
       bus droop slope across the ladder: ______ V/A (design 0.30; measured 0.074/0.16)
       law supported: constant-current / constant-g / margin      D at boundary: ______ V
```

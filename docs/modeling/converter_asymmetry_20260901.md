# Converter asymmetry of the FC and BT boost chains

**Date:** 2026-09-01 · **Scope:** WORK_QUEUE.md §1 item 6 · **Status:** measurement round.
This document quantifies the static open-loop asymmetry between the fuel-cell (FC) and
battery (BT) boost chains from the SD-card bench-log corpus. It recommends a plant
parameterization for a following round, which adds the asymmetry to the `Boost` model in
`tools/hil_electrical.py`. This document does not implement that change.

Tooling: `tools/benchlog_analysis/asymmetry_fit.py` (numpy only; run under
`.venv_benchlog/Scripts/python.exe`). Outputs:
`docs/modeling/asymmetry_fit_20260901/{windows.csv, fit_summary.json, *.png}`.
Checks: `tools/benchlog_analysis/test_asymmetry_fit.py`.

---

## 1. The problem

The hi-fi HIL plant instantiates two identical `Boost` objects
(`hil_electrical.py:1504-1507`). A commanded droop ratio of 0.50 therefore delivers a share
of exactly 0.50. The real chains differ, so the share controller must hold the commanded
ratio off the setpoint to deliver it. The size of that offset is the quantity fitted here.

## 2. Derivation

Each channel is a Thevenin source behind a droop resistance, sharing one bus
(`controller_design/system_model.md:105-110`):

$$V_{bus} = V_{0F} - R_F I_F = V_{0B} - R_B I_B, \qquad I_F + I_B = I_{tot}$$

The firmware commands the droop gains
$g_F = k_d/(R_{E,max}\, r)$ and $g_B = k_d/(R_{E,max}(1-r))$
(`teensy_controller/teensy_controller.ino:10534-10535`), with $k_d = K_{DROOP} = 0.30\ \Omega$
and $R_{E,max} = 2.014\ \Omega$ (`.ino:2166-2167`). The commanded ratio is therefore
recovered exactly from the logged gains, with no calibration constant:

$$r_{cmd} = \frac{g_B}{g_F + g_B}$$

If each channel realizes its commanded droop up to a per-channel scale $s_x$, then
$R_F = k_d s_F / r$ and $R_B = k_d s_B / (1-r)$. Substituting gives the generalized static
law used throughout this document:

$$\alpha \equiv \frac{I_F}{I_{tot}}
 = \underbrace{\frac{r}{\rho(1-r)+r}}_{\text{droop-scale mismatch}}
 + \underbrace{\frac{A\, r(1-r)}{(\rho(1-r)+r)\, I_{tot}}}_{\text{voltage mismatch}},
\qquad \rho \equiv \frac{s_F}{s_B}, \quad A \equiv \frac{\Delta V_0}{k_d\, s_B}$$

with $\Delta V_0 \equiv V_{0F} - V_{0B}$. Setting $\rho = 1$ and $s_B = 1$ recovers the
model of `system_model.md:189-203` exactly,
$\alpha = r + \Delta V_0\, r(1-r)/(k_d I_{tot})$. This equivalence is pinned by test.

Three candidate models are fitted:

- **M0 (null):** $\alpha = r$. The plant as currently modelled.
- **M1:** $\Delta V_0$ only ($\rho = 1$). One parameter, linear through the origin in
  $x = r(1-r)/(k_d I_{tot})$.
- **M2:** $\Delta V_0$ and $\rho$. Two parameters, fitted by grid seed plus Gauss-Newton.
- **M3:** M2 plus a sense-path zero offset. Treated analytically in §7, not fitted, because
  it is near-collinear with the $\Delta V_0$ term over the achieved coverage.

## 3. Window selection

A window is 0.5 s of contiguous samples (about 440 ticks at the ~1.13 ms log period).
Windows are non-overlapping. A window is accepted only when all of the following hold. The
governor rules are transcribed from `.ino:10190-10270`.

| Rule | Threshold | Why |
|---|---|---|
| No fault flag set | `fault_flags == 0` | a latched fault changes the topology |
| Droop MDACs driven, one loop mode throughout | `flags` bit0 set; bit2/bit3 constant | mixed and HOLD ticks are not one operating point |
| Both channels conducting | $I_F, I_B \ge 0.05$ A | a dark channel is a single-source point |
| Above the closed-loop entry | $\min I_{tot} > 0.60$ A | below it the loop runs open-loop or held |
| Commanded ratio stationary | $\mathrm{ptp}(r_{cmd}) \le 0.015$ | the MDAC split must not be moving |
| Setpoint constant and in band | $\mathrm{ptp} = 0$; $0.15 \le sp \le 0.85$ | out-of-band setpoints latch a channel off the bus |
| Governor clip unambiguous | $\lvert sp - lo\rvert \ge 0.02$ when the clip binds | see below |
| Load not ramping | $\sigma(I_{tot})/\bar{I}_{tot} \le 0.12$ and half-mean drift $\le 6\ \%$ | separates ADC noise from a trapezoid ramp |
| Share not drifting | half-mean difference of $\alpha \le 0.010$ | the loop has settled |
| Closed loop converged | $\lvert \bar\alpha - sp_{gov}\rvert \le 0.02$ | the loop delivers its governed reference |

**Governed setpoint.** The governor clips the effective setpoint so the minority channel
current stays at or above `SHARE_MINORITY_I_MIN_A` = 0.30 A: $lo = 0.30/\bar{I}_{tot}$
(clamped to 0.5), $hi = 1 - lo$. Windows are not rejected when the clip binds; the clipped
value $sp_{gov}$ is used, because that is what a converged loop delivers. The governor
filters the total at `SHARE_GOV_FILT_ALPHA` = 0.05 per tick (~20 ticks), far shorter than a
window, so the window mean substitutes for the filter state. Windows where that substitution
could flip the clip state — the raw setpoint within 0.02 of $lo$ — are rejected
(13 windows).

**Separation of noise from drift.** A first pass rejected every candidate on a
peak-to-peak test of $I_{tot}$. The rejection was an artifact: $\sigma/\bar{I} \approx 6\ \%$
with $\mathrm{ptp}/\sigma \approx 5$ over 440 samples, so the peak-to-peak of a perfectly
flat plateau reaches 28 %. The accepted tests therefore use the standard deviation for noise
and a half-mean difference for drift. The same correction was applied to $\alpha$.

## 4. Corpus

211 run directories were scanned; 75 contributed at least one window; 385 windows were
accepted.

| Firmware | Runs scanned | Windows accepted | Note |
|---|---|---|---|
| unversioned (TP0004–TP0013) | 13 | 30 | hand-run share ladder, pre-versioning |
| 3 | 27 | 108 | TP0014–TP0038 automated ladder |
| 4 | 33 | 87 | TP0041–TP0068 |
| 5 | 28 | 106 | TP0074–TP0094 |
| 6 | 23 | 54 | TP0102–TP0120, 19-point ladder |
| 8, 9, 11, 12, 14, 16, 18, 19, 21 | 87 | 0 | see below |

**Why the fw ≥ 8 corpus yields nothing.** Of 4313 candidate windows in those runs, 2485 fail
the loop-mode test (drive-focused ML runs never hold one share mode for 0.5 s) and 1773 fail
the 0.60 A total-current gate. The later TP ladders (fw 16, 18, 19) sweep the *cut* path with
out-of-band setpoints such as 0.00 and 0.12, which the selection rejects by construction. The
asymmetry corpus is therefore structurally the fw 3–6 share-sweep era. This is a confound
that cannot be removed from existing data: the fit's stability is demonstrated across fw 3–6
only, and a fw ≥ 24 confirmation run is a bench item (§9).

Aggregate rejection tally across the whole corpus: 4042 below 0.60 A, 2718 mixed or idle
loop mode, 670 non-stationary $r_{cmd}$, 358 dark channel, 107 ramping load, 18 out-of-band
setpoint, 14 fault flag set, 13 ambiguous governor clip, 7 unconverged closed loop, 3 moved
setpoint.

**Coverage.** $r_{cmd} \in [0.175, 0.811]$; $I_{tot} \in [0.97, 2.30]$ A. The load lever
$1/I_{tot}$ therefore spans only a factor 2.36 ([0.435, 1.029] A⁻¹). That narrow span is the
dominant limit on separating $\Delta V_0$ from $\rho$ (§6).

**Bodge exposure.** Every contributing run post-dates the 2026-07-10 RC-BT compensator bodge
(fw v3 is dated 2026-08-11, `docs/firmware-versions.md:25`), so no window straddles it and
the fit describes the post-bodge board. Every contributing run pre-dates the 2026-08-16
encoder reroute and pull-up bodges (fw v6 is dated 2026-08-12). Neither bodge touches the
static split in any case: the compensator sets the BT voltage-loop crossover, and the encoder
front end is not in the droop network.

## 5. Results

**No-asymmetry is rejected.** The null model M0 ($\alpha = r$) has an RMS residual of
0.0224 share. M1 reduces it to 0.0133, a 41 % reduction on one parameter.

### 5.1 M1 — voltage mismatch only

$$\boxed{\Delta V_0 = +0.0444\ \text{V}, \quad \text{CI}_{95} = [+0.0415, +0.0473]\ \text{V}}$$

(bootstrap over windows, 2000 draws; RMS 0.0133; n = 385). The sign convention is
$\Delta V_0 = V_{0F} - V_{0B}$, so the **fuel-cell chain regulates high**: at any load the FC
channel delivers more than its commanded share.

This agrees with the independent 4-point open-loop CAL-1 sweep
(`controller_design/calibration/dv0_sweep_20260811.csv`), which fitted +0.054 V over all
four points and +0.024 V excluding the light-load outlier, and adopted +0.05 V with the same
sign. The present figure is 11 % below the adopted value and lies inside its stated
±0.10 V envelope. Both figures are referenced to the *nominal* $k_d = 0.30\ \Omega$; §8
shows why that qualifier matters.

Stratified by firmware:

| Firmware | n | $\Delta V_0$ (V) | CI₉₅ (V) | RMS |
|---|---|---|---|---|
| 3 | 108 | +0.0451 | [+0.0404, +0.0500] | 0.0117 |
| 4 | 87 | +0.0442 | [+0.0387, +0.0502] | 0.0126 |
| 5 | 106 | +0.0485 | [+0.0422, +0.0553] | 0.0136 |
| 6 | 54 | +0.0498 | [+0.0407, +0.0587] | 0.0163 |

All four confidence intervals overlap, and the spread (+0.0442 to +0.0498, a 13 % range) is
inside each interval's own width. The asymmetry is stable across the firmware versions
available, as a hardware property should be. No drift-flagged confound is visible.

Stratified by loop mode:

| Mode | n | firmware | $\Delta V_0$ (V) | CI₉₅ (V) |
|---|---|---|---|---|
| closed (flags bit2 set) | 160 | 5, 6 | +0.0490 | [+0.0439, +0.0545] |
| legacy (pre-bit2 logs) | 225 | unversioned, 3, 4 | +0.0420 | [+0.0386, +0.0450] |

**The mode split is not independent of the firmware split, and must not be read as
one.** The `flags` bit2/bit3 loop-mode bits were introduced with BLG record format v3 in
fw v5 (`docs/firmware-versions.md:27`), so every `legacy` window comes from the
unversioned/fw-3/fw-4 era and every `closed` window from fw 5–6. The two intervals are
marginally disjoint (a gap of 0.0011 V, 2.5 % of the estimate), but that gap is equally
described as fw 3–4 versus fw 5–6 and the data cannot separate the two explanations.
It is small against the model's own 0.0133 RMS. Listed as a TODO(verify) in §9.

### 5.2 M2 — voltage mismatch plus per-channel droop scale

$$A = +0.0451\ (\text{CI}_{95}\ [+0.0032, +0.0810]), \qquad
\rho = s_F/s_B = 0.9434\ (\text{CI}_{95}\ [0.9205, 0.9636])$$

RMS 0.01306, against M1's 0.01325 — a 1.5 % improvement for one extra parameter. The F
statistic is 11.5 on (1, 383) degrees of freedom, nominally significant, and the $\rho$
interval excludes 1. However the interval on $A$ spans almost a factor of 25 and nearly
reaches zero, which is the signature of a near-collinear pair rather than two separately
identified parameters.

**The two mechanisms are nearly degenerate over this corpus.** Both raise $\alpha$ above $r$
in the same direction and with similar curvature in $r$; they are separated only by the
$1/I_{tot}$ factor, and $1/I_{tot}$ spans a factor of 2.36. M2 accordingly shifts most of the
explained deviation from the voltage term into the droop-scale term ($\rho < 1$ alone raises
$\alpha$ above $r$) while barely improving the fit.

**Model choice: M1 for the plant, with $\rho$ carried as a separate measured input.** M1 is
adopted because it is the parameterization the controller design and CAL-1 already use, it
is identified with a 6.5 % relative interval, and M2's extra parameter buys 1.5 % of
residual. The per-channel scale mismatch is nevertheless real — but it is measured far more
directly by §6 than by M2's regression, and that direct measurement is what §8 uses.

## 6. Per-channel droop, measured two ways

Two independent regimes in the corpus measure the per-channel droop. Both regress the bus
voltage on a channel's own current, within one run, using $V_{bus} = V_{0x} - R_{ex} I_x$.
Grouping by run matters: $V_{0x}$ moves between runs with the supply setting and pack state,
and pooling runs fits a between-run voltage spread as if it were droop. An initial pooled
version returned scattered slopes; the per-run version below is the corrected one.

**Two different ratio quantities are in play, and they must not be swapped.**

- The **bus-referenced** resistance $R_{ex}$ is what a slope measures directly, and it is what
  the parallel-network identity of §8 consumes. It contains the unscalable series copper
  `DROOP_FIXED_SERIES_OHM` = 0.033 Ω (`Boost.R_OUT` 0.010 + `RT_R_ON` 0.021 + `R_SHUNT` 0.002,
  `hil_electrical.py:203`), which the droop code does not set.
- The **commanded-part scale** $s_x = (R_{ex} - 0.033)/(R_{E,max}\,g_x)$ is what a plant
  `droop_scale` parameter needs, because that parameter multiplies the MDAC droop term alone.
  Forming $s$ without subtracting the fixed series term inflates it and biases the ratio
  toward 1; the corrected values below are lower than an uncorrected form by 0.06–0.07.

### 6.1 Shared regime (both channels conducting)

From the 385 accepted windows, grouped by run and commanded gain (39 groups; ≥ 4 windows and
≥ 0.15 A of span each).

| Channel | Groups | $R_e$ (Ω), median | CI₉₅ | $s$ corrected | CI₉₅ | $s$ uncorrected |
|---|---|---|---|---|---|---|
| FC | 24 | 0.0863 | [0.0798, 0.1085] | **0.129** | [0.116, 0.156] | 0.204 |
| BT | 15 | 0.1099 | [0.0991, 0.1248] | **0.168** | [0.155, 0.176] | 0.238 |

$s_F/s_B = 0.768$, CI₉₅ [0.669, 0.949].

**Leverage disclosure.** These groups are thin: 4–7 windows per FC group, 5–8 per BT group,
with current spans of only 0.150–0.335 A against slopes of ~0.09–0.11 Ω. The median slope
standard error is 0.0028 Ω (FC) and 0.0038 Ω (BT), i.e. 3.2 % and 3.4 % of the slope. This
estimator is the weakest of the three ratio estimates and is reported for reconciliation, not
as the recommendation.

### 6.2 Single-source regime (exactly one channel conducting)

The shared-regime selection rejects these windows as `channel_dark`. They are the direct
measurement of a channel's own droop, with no parallel partner to disentangle, and the corpus
contains **both channels** — the earlier draft's assumption that only one was available was
wrong. 236 single-source windows were extracted (dark channel ≤ 0.02 A, live channel ≥ 0.30 A,
gain stationary to 1 %), yielding fits on 10 FC runs and 8 BT runs across fw 3–19.

| Channel | Runs | $K$ (Ω), median | CI₉₅ | median SE | $\bar g_{cmd}$ | $s$ corrected | CI₉₅ | median span |
|---|---|---|---|---|---|---|---|---|
| FC | 10 | 0.1525 | [0.1167, 0.2054] | 0.0023 | 0.325 | **0.1806** | [0.157, 0.194] | 1.02 A |
| BT | 8 | 0.1396 | [0.1219, 0.1583] | 0.0020 | 0.275 | **0.1941** | [0.177, 0.212] | 0.58 A |

$$s_F/s_B = 0.930, \quad \text{CI}_{95}\ [0.834, 1.079]$$

FC runs: TP0009, TP0038, TP0066–68, TP0086–87, TP0113–14, TP0202. BT runs: TP0011, TP0014,
TP0085, TP0112, TP0170–71, TP0199, TP0211. Note the two channels are commanded at different
gains (0.325 versus 0.275), which is exactly why the comparison must be made on $s$ and not on
the raw slopes: the raw ratio $K_F/K_B = 1.092$ has the opposite sign to the normalized one.

### 6.3 Reconciling the three ratio estimates

| Estimator | $s_F/s_B$ | CI₉₅ | Excludes 1? | Independence |
|---|---|---|---|---|
| M2 regression on the share ratio (§5.2) | 0.943 | [0.921, 0.964] | yes | shares the share-ratio data with M1 |
| Shared-regime per-channel slopes (§6.1) | 0.768 | [0.669, 0.949] | yes | thin groups, 3 % slope SE |
| **Single-source direct (§6.2)** | **0.930** | **[0.834, 1.079]** | **no** | independent regime, 1 A spans |

All three intervals mutually overlap, so the estimates are consistent. The two with the
cleanest leverage — M2 and the single-source fit — agree closely at 0.93–0.94. The
shared-regime estimate is the outlier at 0.768 but its interval reaches 0.949.

**Conclusion: the FC channel realizes roughly 6–7 % less droop than BT, and the evidence is
suggestive rather than decisive.** The single-source interval, which is the estimator the
plant recommendation is taken from, *includes* 1.000; only M2's does not, and M2 measures the
mismatch through the same data that fits $\Delta V_0$.

**The ~4× K_DROOP open finding is reproduced independently.** Both channels realize about one
fifth of the commanded droop resistance ($s \approx 0.13$–$0.19$). This corroborates the
standing finding at `hil_electrical.py:154-228` and `docs/HIL_PLANT.md:368-443` from a
different measurement than the one that raised it. It does not explain it.

**These intercepts cannot resolve $\Delta V_0$.** The single-source intercepts are
$V_{0F} = 15.9345$ V and $V_{0B} = 15.9407$ V. That 6 mV difference is not evidence against
§5.1's 44 mV: the two regimes load the shared node differently, the runs are months apart, and
the shared-regime intercepts (15.9259 / 15.9254 V) are extrapolations with standard errors of
tens of millivolts. The intercept route is not sensitive enough; the share-ratio route is.

## 7. The M3 near-collinearity — sense-path offsets

The measured INA253A1 zero offsets are $\delta_F = +0.0199$ A and $\delta_B = +0.0002$ A
(`hil_electrical.py:395-421`, 201-log medians); the plant injects the rounded defaults
$\{0.020, 0.0\}$ (`hil_electrical.py:415-421`), and it is the **injected** values that the
equivalence below must use.

### 7.1 The sense arm

A pair of zero offsets shifts the *measured* share by

$$\Delta\alpha_{meas} = \frac{\delta_F - \alpha(\delta_F + \delta_B)}{I_{tot}}$$

At $r = 0.5$ the equivalent voltage mismatch is

$$\Delta V_0^{sense} = \frac{k_d(\delta_F - \tfrac12(\delta_F+\delta_B))}{0.25} = +0.0120\ \text{V}$$

**27 % of the fitted +0.0444 V, in the same sign.**

This term is **near-collinear** with, not exactly degenerate from, the $\Delta V_0$ term. The
two share the $1/I_{tot}$ factor, but their $r$ dependence differs: the sense term is linear in
$\alpha$ while the $\Delta V_0$ term goes as $r(1-r)$. In principle a wide enough $r$ sweep
separates them. Over the achieved coverage ($r \in [0.175, 0.811]$, $1/I_{tot}$ spanning
2.36×) they are not separable, and no attempt is made here.

### 7.2 The electrical arm, and why the recommendation is conditional

The INA253 output **is** the droop injection node — the droop resistance is
$R_e = K_{sns} A_v (R_{D1}/R_{inj}) g$, so the INA output voltage drives the FB summing node
directly. A zero offset is therefore **also a genuine electrical shift of that channel's
regulated $V_0$**, not only a measurement artifact, and it acts in the **opposite sign**: an
apparent positive current pushes the regulator to droop *down*.

Its magnitude is bounded by the same droop chain: $\Delta V_0^{elec} = -R_{E,max} g\, \delta_F$,
which at $g \approx 0.3$ is **−0.0121 V** if the commanded droop is realized, and **−0.0022 V**
at the realized scale $s \approx 0.18$ measured in §6.2. The realized figure is the physically
relevant one, but the chain that makes it 5× smaller is the same unexplained ~4× gap, so the
bound is stated as a range rather than a value.

**The two arms partially cancel**, at between −0.0022 V and −0.0121 V against the sense arm's
+0.0120 V. The recommendation in §9 **assumes the sense arm alone** and does not net the
electrical arm out. This is stated as an assumption, not a result: netting them would change
the recommended value by up to 0.0120 V (37 % of it) and the sign of the net is not
established. TODO(verify) in §9.

## 8. Does the per-channel mismatch explain the +8.1 % shared-regime residual?

**No — and the earlier draft's claim that it did was wrong.** The correction has two parts.

**The corpus contains both single-source channels.** §6.2 measures FC and BT single-source
droop directly, on 10 and 8 runs. The earlier §8 branched on "which channel was the bench
single-source regime measured on" and treated the answer as an open TODO. That question is
retired: the bench anchor 0.1615 V/A is a pooled both-channel figure, and the FC-versus-BT
dichotomy was false.

**With a pooled single anchor the mismatch is a second-order effect.** Constructing the shared
regime at $r = 0.5$ from the measured scales ($s_F = 0.1806$, $s_B = 0.1941$), each channel
commands $g = k_d/(R_{E,max}\cdot 0.5)$, so

$$R_F = 0.033 + 0.600 s_F = 0.1414\ \Omega, \qquad R_B = 0.033 + 0.600 s_B = 0.1495\ \Omega$$
$$R_F \parallel R_B = 0.07265\ \Omega, \qquad \text{pooled single} = \tfrac12(R_F+R_B) = 0.14545\ \Omega$$
$$\text{predicted ratio} = 0.14545/0.07265 = \mathbf{2.0016}$$

against the bench 0.1615/0.0740 = 2.1824. Replacing the two channels by their mean and
repeating gives a shared resistance of 0.07271 Ω. **The entire effect of the measured
mismatch on the shared regime is −0.078 %** — the parallel combination of two near-equal
resistances is insensitive to their difference to first order, so a 7 % channel mismatch moves
the shared value by less than a tenth of a percent.

The earlier draft, and the review finding that corrected it, both applied the identity
$1 + R_{\bar x}/R_x$, which is the ratio of a **single named channel** to the shared pair. That
identity is the right one only if the bench anchor was measured on one channel; with the anchor
established as pooled, the correct identity is $\tfrac12(R_F+R_B)/(R_F \parallel R_B)$, which is
$(1+x)^2/(2x)$ in the resistance ratio $x$ and is stationary at $x = 1$. Reported for
completeness, the single-named-channel branch gives 2.058 (FC) or 1.946 (BT) — still short of
2.1824 from either side.

**Conclusion: the +8.1 % residual is not explained by converter asymmetry and remains open.**
It is not attributed here. The per-channel mismatch is real (§6.3) and belongs in the plant for
its own sake, but it is not the mechanism behind the ratio discrepancy, and it should not be
cited as such.

## 9. Recommended plant parameterization

> ### Plant parameterization adopted (2026-09-01, added after the plant round)
>
> **The plant injects the M2 CONSISTENT PAIR, not the §9.1/§9.2 recommendation below.**
> §9.1 recommends M1's $\Delta V_0 = +0.0444$ V and §9.2 recommends a `droop_scale_fc`
> of 0.930 taken from the single-source estimator (§6.3). Those two are from **different
> fits** and combining them double-counts: M1 pins $\rho = 1$ by construction, so its
> $\Delta V_0$ has already absorbed whatever droop-ratio mismatch the corpus contains,
> and re-applying $\rho$ on top applies the same physical asymmetry twice.
>
> Adopted instead, from `asymmetry_fit_20260901/fit_summary.json`, `M2.params`:
>
> | Parameter | Adopted | CI₉₅ | Recommended below |
> |---|---|---|---|
> | $\Delta V_0$ at $s_B = 1$ | **+0.013522 V** | [+0.00097, +0.02429] | +0.0444 V (M1) |
> | $\rho = s_F/s_B$ → `droop_scale_fc` | **0.9434** | [0.9205, 0.9636] | 0.930 (§6.3) |
>
> Validated against CAL-1 ($\alpha$ = 0.5354 / 0.5262 / 0.5327 at $I_{tot}$ = 0.452 /
> 0.935 / 1.346 A, commanded $r = 0.5$), RMS share error: **0.0402** for the
> M1-plus-separate-$\rho$ combination, **0.0253** for M1 alone, **0.0063** for the M2
> pair. The decisive evidence is the shape rather than the RMS — CAL-1's deviation from
> $r$ is **flat in $I_{tot}$**, which is the $\rho$ signature, whereas a voltage mismatch
> deviates as $1/I_{tot}$. The HIL engine reproduces CAL-1 at RMS 0.0064 in `design` mode.
>
> Two consequences worth recording against §9.2's caution. Under the consistent pair the
> $\rho$ interval **excludes 1.000**, so the droop mismatch is significant where the
> single-source estimate was not. And the sense arm of §7.1 (+0.0120 V) is **comparable
> to the whole adopted voltage term**, so a run injecting the measured INA offsets is left
> with a residual near zero; the plant clamps the effective $\Delta V_0$ at $\ge 0$ rather
> than inverting the fitted sign on two near-equal numbers with overlapping intervals.
>
> Implementation notes that do not change this document's fit: the injected voltage is
> scaled by the plant's `--droop` mode scale (the reported $\Delta V_0$ is a lumped
> $A\,k_d$ at the **design** droop, so the share deviation, not the voltage, is the
> invariant), and the sense-arm correction is applied from the INA offsets a run actually
> injects rather than from the presence of a noise model. See `docs/HIL_PLANT.md` §4.4a.


For the following round, in `tools/hil_electrical.py`'s `Boost` model
(`hil_electrical.py:1342-1427` for the class, `:1504-1507` for the two instantiations).

### 9.1 Voltage mismatch — the value depends on `--noise`

`NoiseConfig` is constructed **only when `--noise` is passed** (`hil_plant_sim.py:7912`:
`noise=NoiseConfig() if args.noise else None`). A default run injects **no** INA zero offset,
so a plant parameterized at the offset-corrected value would under-model the asymmetry by 27 %.
Both numbers are therefore required:

| Run mode | $\Delta V_0$ to inject | CI₉₅ | Rationale |
|---|---|---|---|
| **default (no `--noise`)** | **+0.0444 V** | [+0.0415, +0.0473] | the as-fitted value; nothing else supplies the sense contribution |
| **`--noise`** | **+0.0324 V** | [+0.0295, +0.0353] | = 0.0444 − 0.0120; `NoiseConfig` injects the rest |

As antisymmetric per-channel offsets about the nominal $V_0$: `v0_offset_fc` = +0.0222 V /
`v0_offset_bt` = −0.0222 V by default, and ±0.0162 V under `--noise`. Implement this as a
function of the resolved noise setting, not as a constant, or one of the two modes is wrong.

**Sign convention, stated once:** $\Delta V_0 = V_{0F} - V_{0B} > 0$ means the FC chain
regulates high and over-delivers current at every load.

**Assumption carried:** both values treat the INA offset as a **sense artifact only**. §7.2
shows the same offset is also an electrical $V_0$ shift of between −0.0022 V and −0.0121 V, of
opposite sign, which is not netted out here.

### 9.2 Per-channel droop scale

| Parameter | Value | CI₉₅ | Source |
|---|---|---|---|
| `droop_scale_fc` | **0.930** | [0.834, 1.079] | §6.2, single-source direct |
| `droop_scale_bt` | **1.000** | — | reference channel |

Taken from the single-source estimator (§6.3), because that is the regime `--droop measured` is
anchored on and it needs no parallel-partner disentangling. Two cautions. First, these are a
**ratio**: they multiply whatever droop the selected `--droop {design,measured}` mode already
realizes, and setting BT to 1.000 keeps the existing anchor where it is. Second, **the interval
includes 1.000** — the mismatch is a best estimate, not a significant one. Adopting it should be
recorded as such, and it should not be used to argue anything about the +8.1 % residual (§8).

### 9.3 Commanded ratio required for a delivered share of 0.50

M1 with the as-measured $\Delta V_0 = +0.0444$ V, since this table describes what the firmware
must command against the board it actually sees.

| $I_{tot}$ | required $r_{cmd}$ | offset from 0.50 |
|---|---|---|
| 0.5 A | 0.4275 | −0.0725 |
| 1.0 A | 0.4632 | −0.0368 |
| 2.0 A | 0.4815 | −0.0185 |

The 0.5 A row is an extrapolation: it lies below the 0.60 A closed-loop entry threshold and
below the 0.97 A minimum of the accepted corpus. It is included because it is the regime the
controller's actuator-range budget is written against, and it should be read as such.

### TODO(verify)

- `TODO(verify: teensy_controller.ino sensor path)` — whether the firmware subtracts the INA
  zero offsets before computing the share. §7.1's 27 % correction is conditional on it not.
- `TODO(verify: the INA injection-node sign)` — the electrical arm of §7.2. Settling it, and
  the realized-versus-commanded droop scale it depends on, would net the two arms and could
  move the recommended $\Delta V_0$ by up to 0.0120 V.
- `TODO(calibrate)` — an open-loop feedforward bench run above 0.60 A with an in-band setpoint.
  It would give the direct $\alpha - r_{cmd}$ deviation, which this corpus does not contain
  (§5.1), and would break the M1/M2 near-collinearity if run across ≥ 4× of load range.
- `TODO(verify)` — the 2.5 % closed-versus-legacy gap in $\Delta V_0$ (§5.1), which is
  confounded one-for-one with fw 3–4 versus fw 5–6 and cannot be separated by this data.
- `TODO(calibrate)` — a fw ≥ 24 repeat. The shared-regime fit rests entirely on the fw 3–6 era
  (§4); the asymmetry should be re-measured on the current flash before it is treated as
  settled. The single-source fits already span fw 3–19 and show no drift.
- **Retired:** the earlier "which channel was the bench single-source regime measured on"
  item. The corpus answers it — both are present, the anchor is pooled (§8).

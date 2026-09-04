# Step 0 of the margin-referred share governor: does one margin floor separate the bench dropouts?

## 1. Scope

`docs/modeling/low_current_share_stability_20260903.md` section 4.2 proposes replacing the
share governor's minority-current floor `SHARE_MINORITY_I_MIN_A` with a **conduction margin**
`M`, estimated online from the standing offset `d_hat = share_sp - r`. That note names one
prerequisite that costs no firmware and no bench time: compute `M` from the existing bench
logs on the runs that dropped a channel and on their clean neighbours, and test whether a
single floor `M_floor` separates the two classes. This report answers that test.

This report covers the eight bench logs named in section 2 of the exploration note. It does
not measure the two-axis dropout boundary, and it does not evaluate the load-scheduled droop
scale of section 4.1. Firmware behaviour is outside its scope: no firmware, controller
coefficient, or model constant changes as a result of it.

The probe that produces every number is `tools/probes/probe_share_margin_step0.py`. It is
stdlib-only and reproduces bit-identical output under both project interpreters.

## 2. Data

Table 1 lists the eight logs, the firmware that wrote each one, and the dropout census the
probe derives from it. A dropout event is a run of ticks with one channel below 0.02 A while
the source total is at or above 0.30 A, ending when that channel recovers above 0.05 A. This
is the hysteresis convention of
`.claude/skills/benchlog-agent-analysis/references/log-conventions.md`. Events whose onset
falls within 0.25 s of the previous event's recovery belong to one limit-cycle burst; only the
burst-leading event is a first passage, and only first passages are scored.

Table 1. Log inventory and dropout census.

| log | role | fw | BLG | duration (s) | FC events | BT events | first passages | survived ticks | V_bus min (V) |
|---|---|---|---|---|---|---|---|---|---|
| TP0016 | dropout | 3 | 2 | 14.97 | 139 | 37 | 2 | 842 | 8.199 |
| TP0017 | clean | 3 | 2 | 14.97 | 0 | 0 | 0 | 6797 | 15.730 |
| WP0073 | dropout | 4 | 2 | 18.48 | 0 | 28 | 1 | 7429 | 0.000 |
| WP0071 | clean | 4 | 2 | 39.97 | 0 | 0 | 0 | 19692 | 15.771 |
| WP0100 | dropout | 5 | 3 | 39.96 | 0 | 28 | 1 | 19107 | 15.549 |
| WP0095 | clean | 5 | 3 | 39.97 | 0 | 0 | 0 | 22821 | 15.699 |
| TP0105 | dropout | 6 | 4 | 14.97 | 1 | 0 | 1 | 5758 | 15.785 |
| TP0115 | dropout | 6 | 4 | 14.97 | 1 | 5 | 1 | 6329 | 12.194 |

WP0073 carries no trailer and stops at record 15931 of a full 33.5 MB pre-allocation, which
is the MCU-stop signature; its final `V_bus` sample of 0.000 V belongs to the stop, not to a
bus event. The five firmware versions span the fw v3 to fw v6 governor era. The fw v26
governor that the exploration note describes is not represented in any of them.

## 3. Method

### 3.1 The commanded droop ratio

The firmware writes the two AD5443 gain codes as `gFC = K_DROOP/(RE_MAX*r)` and
`gBT = K_DROOP/(RE_MAX*(1-r))` (`teensy_controller.ino:10905`). The quotient

    r = gBT / (gFC + gBT)

therefore returns the commanded ratio identically, independent of both `K_DROOP` and
`RE_MAX`. The probe verifies this against the alternative reconstruction
`K_DROOP/(RE_MAX*gFC)` on every tick of every log; the worst disagreement over all 170 907
ticks is **1.27e-07**, which is the float32 resolution of the logged gains. The convention is
confirmed. Every log's header also reports `K_DROOP = 0.300 ohm`, which the probe asserts.

### 3.2 The split law and the conduction margin

Each source is a Thevenin voltage behind its channel resistance, with a series resistance that
no droop command scales (`docs/modeling/governor_split_law_20260903.md` section 2):

    R_FC = rho * k_d / r      + R_f
    R_BT =       k_d / (1 - r) + R_f
    dV0  = V_0F - V_0B

The minority channel's **conduction margin** is its own no-load voltage minus the bus voltage
that would obtain if it carried no current:

    M_FC = dV0 + R_BT * I_tot            (fuel cell in the minority)
    M_BT = R_FC * I_tot - dV0            (battery in the minority)

The offset is estimated by inverting the split law at the same operating point,

    dV0_hat = I_tot * (x * R_FC - (1 - x) * R_BT)

with `x` either the delivered share `alpha = I_fc / I_tot` or the commanded setpoint
`share_sp`. The second choice is the note's online estimator, since integral action drives
`alpha` toward `share_sp` and the offset then appears as `d_hat = share_sp - r`.

Three droop realizations are scored, and a fourth is reported as a sensitivity:

| label | k_d (ohm) | rho | R_f (ohm) | source |
|---|---|---|---|---|
| (i) design | 0.300000 | 1.0000 | 0.000 | `.ino` `K_DROOP` |
| (ii) measured | 0.063514 | 1.0000 | 0.000 | `k_d * DROOP_SCALE["measured"]`, 0.211713 |
| (iii) split law | 0.300000 | 0.9434 | 0.033 | `governor_split_law_20260903.md` |
| (iv) measured + split law | 0.063514 | 0.9434 | 0.033 | sensitivity only |

### 3.3 Classification

A **FAIL point** is the last tick before a first-passage event at which the channel that is
about to go dark still carried at least 0.05 A. It is the margin at which conduction was
actually lost.

A **survived tick** has both channels at or above 0.05 A and a total at or above 0.30 A, and
lies at least 1.0 s away from every dropout event in the same log. A survived tick is
**sustained** when it sits at the centre of 0.20 s of uninterrupted two-channel conduction;
sustained ticks are reported as 0.20 s window means, so that a single noisy sample cannot set
a record. A FAIL point is an instant and is reported instantaneously. This asymmetry biases
the test **toward** separation, because the survived side is averaged and the fail side is
not.

A single floor separates if and only if the largest FAIL margin lies below the smallest
sustained survived margin.

## 4. Results

### 4.1 What the margin is

The two Thevenin equations, solved at any operating point where both channels conduct, give
the exact identity

    M_minority = (R_FC + R_BT) * I_minority

The probe confirms it numerically: the largest residual over all 88 781 scored records is
**8.9e-16 V**. The margin is therefore the minority **current** rescaled by the series droop
sum, and the whole of its discriminating content sits in that factor. Over the eight logs the
factor spans **1.200 to 2.353 ohm** under realization (i) and **1.232 to 2.399 ohm** under
(iii): a range of 1.96, so `M` and `I_minority` can order two operating points differently by
at most a factor of two.

Realizations (i) and (ii) differ only by the scalar 0.211713 applied to `k_d` with `R_f = 0`,
so `M_ii = 0.211713 * M_i` exactly at every point. **No separation verdict can differ between
them.** Only the series floor `R_f` of realization (iii) can reorder anything, and it moves
the overlap factor by at most 0.17.

### 4.2 The first passages

Table 2 gives the six first passages. `dr/dt` is the commanded-ratio slew over the 20 ms
before the boundary; the controller-path limiter's ceiling is 0.02 per tick, that is 17.24/s at the
measured 1.160 ms median loop period. "Quiet" marks a passage with no dropout of either channel in
the preceding second.

Table 2. First-passage points, realization (i) with `x = alpha`.

| log | dir | quiet | t (s) | I_tot (A) | r | alpha | sp | I_minority (A) | V_bus (V) | dr/dt (1/s) | M_i (V) | M_iii (V) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TP0016 | FC | yes | 6.136 | 1.3538 | 0.1506 | 0.1250 | 0.150 | 0.1692 | 15.830 | -0.06 | 0.3969 | 0.3890 |
| TP0016 | BT | no | 11.268 | 0.9187 | 0.7265 | 0.5965 | 0.150 | 0.3707 | 15.876 | 16.12 | 0.5597 | 0.5755 |
| WP0073 | BT | yes | 16.985 | 1.6842 | 0.6503 | 0.6555 | 0.780 | 0.5802 | 15.803 | 14.77 | 0.7655 | 0.7886 |
| WP0100 | BT | yes | 16.978 | 1.8535 | 0.5755 | 0.6043 | 0.850 | 0.7333 | 15.826 | 11.33 | 0.9005 | 0.9273 |
| TP0105 | FC | yes | 4.757 | 0.7172 | 0.1500 | 0.1910 | 0.150 | 0.1370 | 15.903 | 0.00 | 0.3223 | 0.3159 |
| TP0115 | BT | no | 4.425 | 0.6769 | 0.8500 | 0.8810 | 0.850 | 0.0806 | 15.908 | 0.00 | 0.1896 | 0.1933 |

Three of these are driven by a commanded share step: TP0016/BT, WP0073/BT and WP0100/BT all
sit at 11.3 to 16.1 /s of ratio slew, that is at 66 % to 94 % of the limiter's ceiling. In WP0073
and WP0100 the setpoint stepped from 0.350 to 0.780 and to 0.850 respectively, the loop slewed
`r` upward, and the battery went dark partway through the slew at 0.58 A and 0.73 A of
delivered battery current. Only **two** first passages on record are quasi-static, TP0016/FC
and TP0105/FC, and both are in the fuel-cell direction. There is **no quasi-static
battery-minority first passage in the bench record at all.**

Two of the exploration note's quoted figures need restating against the measured first
passage. TP0016's dropout occurred at a total of **1.354 A**, not the profile plateau 1.63 A;
the commanded minority there was `0.150 * 1.354 = 0.203 A` and the delivered minority
**0.169 A**, not 0.245 A. WP0100's boundary battery current is **0.733 A**, against the note's
0.69 A.

### 4.3 The offset estimator

Table 3 gives the two offset estimates at each first passage.

Table 3. Standing offset and the recovered `dV0_hat`.

| log | dir | t (s) | d_hat = sp - r | alpha - r | dV0_hat (i, alpha) | dV0_hat (i, sp) | dV0_hat (iii, alpha) | dV0_hat (iii, sp) |
|---|---|---|---|---|---|---|---|---|
| TP0016 | FC | 6.136 | -0.0006 | -0.0256 | -0.0813 | -0.0019 | -0.1339 | -0.0561 |
| TP0016 | BT | 11.268 | -0.5765 | -0.1300 | -0.1804 | -0.7997 | -0.1873 | -0.8242 |
| WP0073 | BT | 16.985 | 0.1297 | 0.0052 | 0.0115 | 0.2881 | 0.0000 | 0.2850 |
| WP0100 | BT | 16.978 | 0.2745 | 0.0289 | 0.0657 | 0.6248 | 0.0454 | 0.6211 |
| TP0105 | FC | 4.757 | 0.0000 | 0.0410 | 0.0692 | 0.0000 | 0.0391 | -0.0287 |
| TP0115 | BT | 4.425 | 0.0000 | 0.0310 | 0.0493 | 0.0000 | 0.0544 | 0.0041 |

Two properties of the online estimator follow, and both are adverse.

First, `d_hat` is **structurally zero at every quasi-static rail failure**. At TP0016/FC,
TP0105/FC and TP0115/BT the ratio sits exactly on a band rail (`r` = 0.1500 or 0.8500) and the
setpoint sits on the same rail, so `d_hat` is 0.0000 to within 6e-04. The governor pins `r` at
the rail whenever the setpoint is outside the band or the minority clip binds, and by the
exploration note's own Table 1 the SDP and DP policies command a band edge on 100 % of ticks.
The estimator therefore returns no offset precisely on the policies for which the governor
owns the whole cycle.

Second, the recovered `dV0_hat` spans **-0.824 V to +0.625 V** across the six passages,
against the plant's fitted constant `ASYM_DV0_V = 0.013522 V` (`tools/hil_electrical.py`).
The spread of 1.449 V is 107 times the fitted value. A quantity that is by construction a static voltage
mismatch is absorbing droop-scale error and slew transient instead. The `x = share_sp`
estimator is the worse of the two: it breaks the exact identity of section 4.1 by
`(R_FC + R_BT) * I_tot * (share_sp - alpha)`, which reaches **0.619 V** at TP0016/BT and
**-0.559 V** at WP0100/BT.

### 4.4 The separation test

Table 4 gives, per log and direction, the deepest sustained two-channel hold: the 0.20 s
window with the smallest minority current that the board held without losing a channel.

Table 4. Deepest sustained hold, 0.20 s window means.

| log | dir | sustained ticks | t (s) | I_minority (A) | I_tot (A) | r | M_i (V) | M_ii (V) | M_iii (V) |
|---|---|---|---|---|---|---|---|---|---|
| TP0016 | FC | 551 | 4.429 | 0.2044 | 0.4511 | 0.4181 | 0.2520 | 0.0533 | 0.2572 |
| TP0017 | FC | 6236 | 11.978 | 0.1940 | 0.5536 | 0.3360 | 0.2608 | 0.0552 | 0.2638 |
| TP0017 | BT | 5 | 4.910 | 0.2442 | 0.4518 | 0.4197 | 0.3008 | 0.0637 | 0.3071 |
| WP0073 | FC | 3840 | 7.640 | 0.1993 | 0.3989 | 0.4415 | 0.2425 | 0.0513 | 0.2479 |
| WP0073 | BT | 2709 | 7.638 | 0.1996 | 0.3987 | 0.4414 | 0.2429 | 0.0514 | 0.2484 |
| WP0071 | FC | 7694 | 8.023 | 0.2112 | 0.4220 | 0.4438 | 0.2567 | 0.0544 | 0.2626 |
| WP0071 | BT | 4496 | 8.022 | 0.2105 | 0.4215 | 0.4439 | 0.2558 | 0.0541 | 0.2616 |
| WP0100 | FC | 5510 | 28.983 | 0.0966 | 0.4157 | 0.2122 | 0.1734 | 0.0367 | 0.1720 |
| WP0100 | BT | 7219 | 27.110 | 0.1357 | 0.4240 | 0.6181 | 0.1725 | 0.0365 | 0.1777 |
| WP0095 | FC | 9236 | 30.822 | 0.1418 | 0.4264 | 0.3000 | 0.2026 | 0.0429 | 0.2039 |
| WP0095 | BT | 9844 | 27.080 | 0.1391 | 0.4457 | 0.6255 | 0.1781 | 0.0377 | 0.1835 |
| TP0105 | FC | 5012 | 12.033 | 0.2307 | 0.4517 | 0.4719 | 0.2777 | 0.0588 | 0.2846 |
| TP0105 | BT | 242 | 12.032 | 0.2213 | 0.4524 | 0.4719 | 0.2664 | 0.0564 | 0.2731 |
| TP0115 | FC | 154 | 12.423 | 0.2311 | 0.4572 | 0.4335 | 0.2823 | 0.0598 | 0.2885 |
| TP0115 | BT | 5690 | 12.421 | 0.2260 | 0.4569 | 0.4335 | 0.2761 | 0.0585 | 0.2822 |

Table 5 sets the two classes against each other. The **overlap factor** is the largest FAIL
value divided by the smallest sustained survived value: 1.0 means the classes just touch, and
any value above 1.0 means no single threshold separates them. `gap_A` converts a voltage gap
through the identity of section 4.1 at the median FAIL operating point, so the current row and
the margin rows are directly comparable.

Table 5. Separation test, `x = alpha`, 0.20 s window means on the survived side.

| discriminant | dir | max FAIL | min sustained | gap | gap (A-equivalent) | overlap | verdict |
|---|---|---|---|---|---|---|---|
| I_minority (A) | FC | 0.1692 | 0.0966 | -0.0726 | -0.0726 | 1.75 | overlap |
| M (V), (i) design | FC | 0.3969 | 0.1734 | -0.2235 | -0.0951 | 2.29 | overlap |
| M (V), (ii) measured | FC | 0.0840 | 0.0367 | -0.0473 | -0.0951 | 2.29 | overlap |
| M (V), (iii) split law | FC | 0.3890 | 0.1720 | -0.2170 | -0.0942 | 2.26 | overlap |
| I_minority (A) | BT | 0.7333 | 0.1357 | -0.5976 | -0.5976 | 5.40 | overlap |
| M (V), (i) design | BT | 0.9005 | 0.1724 | -0.7281 | -0.5147 | 5.22 | overlap |
| M (V), (ii) measured | BT | 0.1907 | 0.0365 | -0.1541 | -0.5147 | 5.22 | overlap |
| M (V), (iii) split law | BT | 0.9273 | 0.1777 | -0.7496 | -0.5149 | 5.22 | overlap |
| I_minority (A) | both | 0.7333 | 0.0966 | -0.6367 | -0.6367 | 7.59 | overlap |
| M (V), (i) design | both | 0.9005 | 0.1724 | -0.7281 | -0.3777 | 5.22 | overlap |
| M (V), (ii) measured | both | 0.1907 | 0.0365 | -0.1541 | -0.3777 | 5.22 | overlap |
| M (V), (iii) split law | both | 0.9273 | 0.1720 | -0.7553 | -0.3923 | 5.39 | overlap |

Every cell overlaps, in every realization and in both directions. The margin helps only in the
pooled, cross-direction case, where it reduces the A-equivalent overlap from 0.637 A to
0.378 A, a 41 % improvement over the incumbent current floor but still an overlap factor of
5.22, where separation requires 1.00 or less. In the fuel-cell direction taken alone the
margin is **worse** than the raw minority current, 0.095 A of A-equivalent overlap against 0.073 A.
The fuel-cell rows are already the quasi-static case: TP0016/FC and TP0105/FC are the only
fuel-cell first passages and both are quasi-static, so restricting the FAIL class to
quasi-static passages reproduces those rows exactly.

Under the note's online estimator `x = share_sp` the test is worse still. On per-tick values,
the largest FAIL margin is 1.1791 V under realization (i) against a smallest sustained
survived margin of 0.0635 V, an overlap of 1116 mV where the `x = alpha` estimator overlaps by
805 mV.

### 4.5 The decisive single observation

The refutation does not depend on comparing runs. Inside TP0016 alone:

- at t = 4.429 s the fuel cell held **0.2044 A** as the minority against a total of 0.4511 A
  at `r` = 0.4181, giving `M_i = 0.2520 V`, and it held it for the full 0.20 s window;
- at t = 6.136 s the same channel lost conduction at **0.1692 A** instantaneous, or 0.2027 A
  averaged over the 0.20 s before the boundary, against a total of 1.3538 A at `r` = 0.1506,
  giving `M_i = 0.3969 V` at the boundary sample and 0.4582 V on the 0.20 s mean.

The minority current is the same to within 1 % on the 0.20 s means, while the margin the
theory says should govern is **57 % to 82 % larger at the failure than at the hold**. The
margin moved decisively in the safe direction and the channel dropped out anyway.

WP0100 supplies the cross-run counterpart: between t = 27.5 s and t = 31.5 s the fuel cell
carried a mean of **0.107 A** as the minority, with a minimum sample of 0.0322 A, against a
total of about 0.42 A, for 4.0 s and with zero dropouts, in the same run that lost the battery
28 times.

### 4.6 The direct observables

The bus voltage does not discriminate either. Every first passage occurred with the bus
between **15.803 V and 15.908 V**, while sustained two-channel holds ran as low as **15.699 V**
(fuel-cell minority) and **15.712 V** (battery minority) without losing a channel. The bus was
therefore higher at every failure than at the lowest surviving hold. The 8.199 V minimum of
TP0016 and the 12.194 V minimum of TP0115 occur **after** their first passages, inside the ensuing limit
cycle, and are consequences of the collapse rather than precursors of it.

## 5. Verdict

**No single margin floor separates the dropout runs from their clean neighbours, under any of
the three droop realizations, in either direction, and with either offset estimator.** The
smallest overlap achieved by any margin is a factor of **2.26**, in the fuel-cell direction
under realization (iii); the pooled figure is **5.22**. The section 4.2 hypothesis, as a
one-parameter replacement for the current floor, is refuted by the existing bench record.

Three findings sharpen that verdict.

1. The margin is algebraically the minority current times the series droop sum, which over
   this corpus spans a factor of 1.96. A quantity that differs from the incumbent variable by
   at most a factor of two cannot repair an overlap of 5 to 8.
2. Realization (ii) is a pure rescaling of realization (i), so the unexplained factor-of-four
   droop discrepancy cannot change any separation verdict. Only the series floor `R_f` can,
   and it is worth at most 0.17 in the overlap factor.
3. The online estimator `d_hat = share_sp - r` is identically zero at every quasi-static rail
   failure on record, because the governor pins `r` at the same band rail the setpoint sits on.
   It carries no information in exactly the regime it was proposed for.

The bench record does support one narrower statement: the failures cluster by **mechanism**,
not by margin. Three of six first passages occur at 66 % to 94 % of the ratio slew ceiling
during a commanded share step, at delivered minority currents of 0.37 A to 0.73 A, far above
any plausible static floor. The other three occur at rails, at 0.08 A to 0.17 A. A static
margin governor addresses neither population.

## 6. Limits

1. **Firmware heterogeneity.** The eight logs span fw v3 to fw v6, five distinct governor and
   share-law eras. `SHARE_MINORITY_I_MIN_A`, the open-loop gate and the slew limiter all moved
   inside that span. The fw v26 governor is not represented.
2. **Bench battery source.** The exploration note records the bench battery source impedance
   as 1.01 to 1.35 ohm, against a far stiffer vehicle pack. Every battery-minority first
   passage in Table 2 carries that confound, and all four of them set the pooled overlap
   factor.
3. **Sample size.** Six first passages, of which two are quasi-static and both are fuel-cell.
   There is no quasi-static battery-minority first passage on record, so the battery
   direction's static boundary is untested rather than measured.
4. **Detection floor.** The 0.30 A total gate excludes one TP0115 battery event at 0.234 A of
   total. Below that total a minority current is a handful of the 8.06 mA ADC counts and
   cannot be distinguished from noise, so the compressed-cycle regime is invisible to this
   method.
5. **Asymmetric statistics.** The survived class is reported as 0.20 s window means and the
   FAIL class instantaneously. This biases the test toward separation, and separation still
   fails.
6. **Model provenance.** `rho` = 0.9434 and `R_f` = 0.033 ohm are the offline plant's
   constants, fitted on hardware of the same board but not on these runs. `DROOP_SCALE`
   0.211713 derives from a single-source bus-droop measurement of 0.16 V/A whose factor-of-four
   discrepancy against the design value is an open item of `docs/HIL_PLANT.md` section 4.2.
7. **WP0073 truncation.** The log has no trailer and stops mid-run; its dropout burst is
   complete but the run's later behaviour is unrecorded.

## 7. What to measure next

The exploration note's section 5 item 1, the two-axis dropout-boundary sweep, remains the only
route, and this report adds three requirements to it.

1. **Sweep both axes at fixed slew.** Three of six recorded first passages are slew-driven.
   A sweep that steps the setpoint at the limiter's ceiling measures a slew boundary and calls
   it a static one. Hold `dr/dt` below 1 /s to fix the static boundary, then repeat at the
   ceiling to size the dynamic one.
2. **Produce a quasi-static battery-minority passage.** None exists. Without one the direction
   asymmetry of the exploration note's item 2 rests entirely on slew-driven events taken on the
   1.01 to 1.35 ohm bench source.
3. **Instrument the ratio, not only the current.** The two variables tested here are
   algebraically related through the series droop sum, so neither can separate a boundary that
   depends on something else. The candidates the data leave open are the per-channel
   conduction state of the RT1987 pass device and the light-load mode of the TPS61288, and
   neither is observable in the present bench-log record.

Resolving the factor-of-four droop discrepancy is worth doing for the reasons the exploration
note gives, but it cannot change this report's verdict: realization (ii) rescales the margin
and reorders nothing.

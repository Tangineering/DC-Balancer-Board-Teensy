# Droop Power-Share Plant Model

**Purpose.** Derive the SISO plant model $G_P$ for the **Power Balance Controller** (the
`PI_Controller_Power(shareError)` block in `teensy_controller.ino`), so that a robust
H∞ / Youla-H controller can be synthesized to replace the existing PI. The design method
follows *A Practical Youla Gain-Tuning Framework for H∞ Controller Realization*
(Tan, Yadav, Assadian, 2026) — see `references/`.

**Authoritative sources used** (values cited per item in §8):

- `references/Scale Car DC Balancer Board Schematic 2026-06-22.pdf`, sheets 1–2
  (FC / BT "BOOST+DROOP" channels) and sheet 4 (power routing / bus capacitance).
- `teensy_controller/teensy_controller.ino` — `powerBalance()`, `setDroopMdac()`,
  ADC scaling, loop timing.
- `references/DC Controller-SISO 2026-06-09.pdf` — control architecture context.
- `references/DC Controller-DroopCircuit 2026-06-09.pdf` — droop circuit signal path.
- Component datasheets in `references/Datasheets/`.

---

## 1. Scope, signals, and control objective

From the SISO architecture diagram, the Power Balance Controller is one loop in a cascade:

| Signal | Symbol | Range | Source |
|---|---|---|---|
| Reference: requested power share | $\alpha_{req}$ | $[0,1]$ | EMS on Raspberry Pi (UDP, ≤ 50 Hz update) |
| Measured output: actual share | $\alpha_{act} = \dfrac{|I_{FC}|}{|I_{FC}|+|I_{BT}|}$ | $[0,1]$ | `FC_CURRENT` / `BT_CURRENT` ADC (pins 40/41) |
| Control input: droop ratio | $r$ | $[0.01,\,0.99]$ (firmware clamp) | Controller output, mapped to two MDAC codes |
| Physical actuators | $g_F,\,g_B$ | $[0,\,4095/4096]$ | AD5443 MDAC gains via SPI |

The controller is SISO: it outputs the single ratio $r$; both MDAC gains are derived from
it (K_bat computed "linearly" from K_fc per the architecture note — in the firmware,
$g_F = f(r)$ and $g_B = f(1-r)$, see §4).

**Note on the share convention.** The architecture PDF says $\alpha = P_{fc}/P_{bat}$; the
firmware actually implements the *fraction* $\alpha = I_{fc}/(I_{fc}+I_{bt})$
(`powerBalance()`), which is bounded on $[0,1]$ and better conditioned. This model uses the
firmware convention. (Because both converters regulate to the same bus voltage, the current
fraction equals the *output-side* power fraction; input-side power fractions differ by the
two converters' efficiencies.)

**Objective.** Track $\alpha_{req}$ with zero steady-state error ($T(0)=1$, the Youla-H
condition), reject the disturbances of §5 (no-load-voltage mismatch, load transients),
tolerate the plant uncertainty of §6, and keep MDAC activity smooth (limit $\|Y\|_\infty$).

---

## 2. One channel: droop hardware signal chain

Each source (FC, BT) is a TPS61288 boost whose output voltage is *drooped* in analog
hardware proportionally to its own output current. Signal path (schematic sheets 1–2):

```
I_out ──▶ INA253A1 (K_sns = 0.1 V/A) ──▶ V_droop
V_droop ──▶ AD5443 MDAC, voltage-switching mode (gain g ∈ [0,1], 12-bit, SPI) ──▶
        ──▶ OPA197 non-inverting amp (A_v = 1 + R_op2/R_op1 = 1 + 40.2k/10k = 5.02) ──▶ V_op
V_op ──▶ R_inj = 53.6 kΩ ──▶ regulator FB node (divider R_D1 = 215 kΩ / R_D2 = 10 kΩ)
         (R_D1 bodged 237 k → 215 k on BOTH channels, 16 V bus retune 2026-07-11 —
          schematic still shows 237 k)
```

The regulator servos its FB node to $V_{ref}$. KCL at the FB node (FB pin current ≈ 0):

$$\frac{V_{out}-V_{ref}}{R_{D1}} + \frac{V_{op}-V_{ref}}{R_{inj}} = \frac{V_{ref}}{R_{D2}}$$

$$\boxed{\;V_{out} = \underbrace{V_{ref}\Big(1 + \tfrac{R_{D1}}{R_{D2}} + \tfrac{R_{D1}}{R_{inj}}\Big)}_{V_0\ \text{(no-load setpoint)}} \;-\; \frac{R_{D1}}{R_{inj}}\,V_{op}\;}$$

With $V_{op} = A_v\, g\, K_{sns}\, I_{out}$, each channel is a Thevenin source with an
**electronically programmable output resistance**:

$$V_{out} = V_0 - R_e(g)\, I_{out}, \qquad
\boxed{\;R_e(g) = K_{sns}\, A_v\, \frac{R_{D1}}{R_{inj}}\; g\;}$$

Numerically (schematic values, $V_{ref} = 0.6$ V — see TODO in §8):

- $R_{D1}/R_{D2} = 21.5$, $\;R_{D1}/R_{inj} = 215/53.6 = 4.0112$
- $V_0 = 0.6 \times 26.511 = 15.91\ \text{V}$ — the 16 V bus-retune target (Death-5 headroom plan) ✓
- $R_{e,max} = R_e(1) = 0.1 \times 5.02 \times 4.0112 = \mathbf{2.014\ \Omega}$
- MDAC resolution: $\Delta R_e = R_{e,max}/4096 = 0.492\ \text{mΩ per LSB}$

Both channels use identical $R_{D1}, R_{D2}, R_{inj}, R_{op1}, R_{op2}$ values, so
$V_{0,F} = V_{0,B}$ **nominally**; mismatch is a tolerance effect (§5). The INA253's
internal 2 mΩ shunt adds a fixed physical droop that is ~0.1 % of $R_{e,max}$ — neglected.

Cross-checks against the firmware: $A_v = 5.02$ matches `const float A_v = 5.02f`;
$V_0 = 15.91$ V matches the firmware's `V_BUS_NOMINAL = 16.0f` (retune executed 2026-07-11). The firmware's
`k_eq = 0.45 Ω` does **not** include the $R_{D1}/R_{inj}$ injection factor — see §4.

---

## 3. Two sources in parallel: static share plant

Both Thevenin sources feed VBUS through RT1987 ideal diodes (≈ 0 Ω when on,
blocking when reverse). With both conducting and total load current $I_{tot}$:

$$V_{bus} = V_{0F} - R_F I_F = V_{0B} - R_B I_B, \qquad I_F + I_B = I_{tot}$$

$$I_F = \frac{\Delta V_0 + R_B\, I_{tot}}{R_F + R_B}, \qquad \Delta V_0 \equiv V_{0F} - V_{0B}$$

**Droop-ratio mapping.** Choose a *design droop scale* $k_d$ (Ω) and command

$$R_F = \frac{k_d}{r}, \qquad R_B = \frac{k_d}{1-r}$$

Then $R_F + R_B = \dfrac{k_d}{r(1-r)}$ and $R_F \parallel R_B = k_d$ (independent of $r$!), giving

$$\boxed{\;\alpha \;=\; \frac{I_F}{I_{tot}} \;=\; r \;+\; \underbrace{\frac{\Delta V_0\, r(1-r)}{k_d\, I_{tot}}}_{d\ \text{(output disturbance)}}\;}$$

Key structural facts for the control design:

1. **Nominal static gain is exactly 1** ($\alpha = r$ when $\Delta V_0 = 0$), by
   construction of the $k_d/r$ mapping. This is why the legacy PI with $K_p = K_i = 1$
   was plausible.
2. **Setpoint-voltage mismatch enters as an additive output disturbance**
   $d = \Delta V_0\, r(1-r) / (k_d I_{tot})$. It is worst at $r = 0.5$ and at light load,
   and scales inversely with the droop strength $k_d$. Integral action (enforced by
   Youla-H, $T(0)=1$) rejects it at DC but it consumes actuator range: the steady-state
   $r$ must offset $d$.
3. **The disturbance perturbs the plant gain:**
   $\dfrac{\partial \alpha}{\partial r} = 1 + \dfrac{\Delta V_0 (1-2r)}{k_d\, I_{tot}}$ —
   treat as parametric gain uncertainty $K \in [1-\delta,\, 1+\delta]$ (quantified §6).
4. **Load current is a disturbance input**: variations in $I_{tot}$ (drive transients,
   $P_{dem}$) modulate $d$. Bandwidth of this disturbance ≈ vehicle/motor dynamics
   (≲ 10 Hz), well inside the intended control band, again handled by integral action +
   low-frequency $S$.

**Validity limits (model becomes nonlinear/degenerate):**

- **Diode clamp:** if $\Delta V_0 + R_B I_{tot} < 0$ (or the mirror condition), one RT1987
  blocks and $\alpha$ clamps to 0 or 1 — occurs at extreme $r$ + large mismatch + light
  load. The controller's anti-windup must handle this saturation.
- **$I_{tot} \to 0$:** $\alpha$ undefined; the firmware already returns early when
  $|I_F|+|I_B| < 10^{-6}$ A and must **hold the controller state** (the current code
  skips the PI entirely — preserve this behavior).
- **FC-charge cruise:** `BT_BUS_ENABLE` LOW removes the battery from the bus → plant
  degenerates to $\alpha \equiv 1$. The EMS commands $\alpha_{req} \approx 1$ there by
  design; the controller integrator should be frozen or the loop bypassed in that mode.

---

## 4. Actuator mapping, saturation, and the current-firmware defect

The firmware maps $r$ to MDAC gains as `g = k_eq / r / K_sns / A_v` — i.e. it assumes
$R_e = g\,K_{sns} A_v$ and omits the injection-divider factor $R_{D1}/R_{inj} = 4.42$.
Writing the mapping against the true hardware constant:

$$g_F = \frac{k_d}{R_{e,max}\; r}, \qquad g_B = \frac{k_d}{R_{e,max}\,(1-r)}, \qquad
R_{e,max} = 2.014\ \Omega$$

**Constraint: $g \le 1$.** This bounds the usable ratio range:
$k_d \le R_{e,max} \cdot \min(r_{min},\, 1-r_{max})$.

| Ratio span | max $k_d$ | Comment |
|---|---|---|
| $r \in [0.10, 0.90]$ | 0.201 Ω | wide authority, weak droop |
| $r \in [0.15, 0.85]$ | 0.302 Ω | **recommended span — use $k_d = 0.30$ Ω** (bound 0.3020; 0.30 leaves margin, max $g = 0.993$) |
| $r \in [0.20, 0.80]$ | 0.403 Ω | strong droop, narrow authority |

**Defect in the current constants:** with `k_eq = 0.45` the firmware computes
$g_F = 0.45/(0.502\, r) = 0.896/r$, which **exceeds 1 (and is clamped by
`setDroopMdac`) for all $r < 0.896$** — i.e. over almost the whole commanded range both
MDACs sit pinned at full scale, $R_F = R_B = R_{e,max}$, and the achieved share is stuck
at ≈ 0.5 regardless of $r$. The plant seen by the legacy PI is therefore *zero-gain* over
most of its range. (The code comment at `applyOpenLoopDroop()` acknowledges the constants
are pre-calibration.) **The new controller design must fix the mapping**: use
$g = k_d / (R_{e,max}\, r)$ with $k_d$ from the table above, and treat the residual
$r$-clamp as the actuator saturation in the anti-windup scheme.

**Trade-off in choosing $k_d$** (bench decision, see §9):

- Larger $k_d$ → smaller mismatch disturbance $d \propto 1/k_d$, stiffer sharing —
  but narrower $r$ authority and larger droop voltage excursion
  ($\Delta V_{bus} = k_d I_{tot}$ at $r=0.5$; e.g. 0.30 Ω × 6 A = 1.8 V bus sag).
- Smaller $k_d$ → wide authority, small bus sag — but mismatch/quantization dominate.

**Quantization:** 12-bit MDAC → worst-case share granularity near the range edges;
at $r = 0.15$, one LSB in $g_F$ moves $r$ by $\approx r^2 R_{e,max}/(k_d\cdot 4096)
\approx 3.7\times10^{-5}$ — negligible vs. the sensor noise floor (§5). Ripple of one
LSB is invisible; MDAC quantization can be ignored in the linear model.

---

## 5. Disturbance and noise budget

**5a. No-load voltage mismatch $\Delta V_0$** (the dominant static disturbance).
$V_0 = V_{ref}(1 + R_{D1}/R_{D2} + R_{D1}/R_{inj})$. Channel-to-channel difference budget:

| Contributor | Tolerance | Effect on $V_0$ |
|---|---|---|
| $V_{ref}$ (TPS61288 FB accuracy) | ±2 % (DS §7.5: 0.588–0.612 V, full process/temp spread) | ±2 % |
| $R_{D1}, R_{D2}, R_{inj}$ (assume 1 %) | ±1 % each | ±1.3 % (RSS of sensitivities) |
| **Channel difference (RSS × √2)** | | **≈ ±3.4 % → ΔV₀ ≈ ±0.6 V worst-case budget** |

The ±2 % $V_{ref}$ term is the full min/max spread; two parts from the same reel at the
same board temperature will correlate far tighter (the DS temp-drift curve is ~0.4 %
over −50…125 °C), so the **measured** per-board ΔV₀ (CAL-1) is expected well inside
the budget — and it, not the budget, feeds the final K uncertainty set. Note the
worst-case budget slightly exceeds the synthesized corner set ($K \in [0.55, 1.45]$ at
the r-range edges and 2 A); the direction that grows (low gain) is the benign one, and
the high-gain side sits against an 18.5 dB gain margin — but tighten `K_SET` from the
CAL-1 measurement rather than the budget.

Resulting output disturbance at $r=0.5$, $k_d = 0.30\ \Omega$, taking a *likely*
per-board ΔV₀ of ±0.4 V (the ±0.6 V worst-case budget scales these ×1.5):
$d = 0.40 \times 0.25 / (0.30\, I_{tot}) = 0.33 / I_{tot}$ — e.g. **0.17 share at
2 A**, 0.06 at 6 A. This is large: it is the main reason the loop needs true integral
action, and it sets how much $r$-authority margin the saturation limits must leave.
$\Delta V_0$ is essentially DC (drifts with temperature only).

**5b. Measurement noise / quantization.** $I$ measured via INA253A1 → 12-bit ADC:
1 LSB = $3.3/4095/0.1 = 8.06$ mA (`SCALE_I`). Share quantization ≈
$\text{LSB}/I_{tot}$: 0.4 % at 2 A, 1.6 % at 0.5 A. Add INA253A1 zero-current offset
(±10s of mA class, unipolar mode → clipped at zero; TODO(verify) §8) and boost-converter
current ripple aliasing (loop samples asynchronously to the ~500 kHz switching). Model as
output noise $n$ with σ scaling as $1/I_{tot}$; motivates a measurement prefilter (§7)
and a $W_d$/$W_u$ rolloff in synthesis.

**5c. Load transients.** $I_{tot}$ steps with motor current (VESC). Enters through $d$
(5a) and, during the transient, through the bus-capacitance redistribution path (§6).
Spectrum ≲ 10 Hz (vehicle dynamics) with fast edges from the VESC current loop.

---

## 6. Dynamics

The share loop is deliberately the *slow outer loop* over fast analog hardware:

| Element | Dynamics | Time scale |
|---|---|---|
| INA253A1 sense | 1-pole, BW ≈ 350 kHz (TODO(verify)) | 0.5 µs |
| AD5443 + OPA197 injection | analog, > 100 kHz | µs |
| TPS61288 voltage loop tracking a FB-node step | closed-loop BW ≈ compensator-set crossover $f_c$ (see §6e; $R_C$ = 61.2 k **both channels** — BT bodged from the schematic's 27.4 k post-manufacturing to match FC; $C_C$ = 2 nF) | lump as $\tau_r \approx$ 20–300 µs, TODO(calibrate); §6e predicts 7–25 µs |
| Bus capacitance redistribution | pole at $1/[C_{bus}(k_d \parallel R_{L})]$ | 50–500 µs (see below) |
| Digital loop: ADC read → control → SPI write, ZOH | sample period $T_s$ + latency | **dominant** |

**6a. The share statics are (nearly) instantaneous.** A key structural result: with
$\Delta V_0 = 0$, both source currents share the same factor $(V_0 - V_{bus})$, so

$$\alpha(t) = \frac{(V_0 - V_{bus}(t))/R_F}{(V_0-V_{bus}(t))(1/R_F + 1/R_B)} = \frac{G_F}{G_F+G_B} = r$$

*at every instant*, regardless of the bus-voltage transient. The bus pole
($\tau_b = C_{bus}\,(R_F \parallel R_B \parallel R_{L}) = C_{bus}(k_d \parallel R_L)$,
with $C_{bus} \approx$ 30–80 µF in Idle and ≈ 500–1000 µF in Run when the 470 µF V-MOT
node + VESC input caps are connected through `MOT_PWR_ENABLE`) appears in the share
response **only through the mismatch term**, with residue proportional to
$\Delta V_0/(k_d I_{tot})$ — a small, uncertain parasitic. It is covered by the
uncertainty weight rather than modeled explicitly. (Verified numerically in
`validate_model.py`.)

**6b. Constant-power-load caveat (bus stability, not share stability).** The VESC is a
CPL with incremental resistance $-V_{bus}^2/P$. The droop bus is stable iff
$k_d < V_{bus}^2/P$ — at 50 W that bound is 5.1 Ω, an order of magnitude above the
recommended $k_d = 0.30$ Ω. Not a binding constraint; record it as a design check.

**6c. Sampling and delay — the dominant dynamics.** Recommendation for the new
controller: run the share loop at a **fixed rate $T_s = 1$ ms (1 kHz)** instead of the
current free-running loop tick (integrator gated at 50 µs). Rationale: the EMS reference
arrives at ≤ 50 Hz; the target closed-loop bandwidth (§7) is ~5–10 Hz; 1 kHz gives ≥ 20×
oversampling, makes the delay model deterministic, and leaves the fast loop tick for
`detectFaults()`/motor control. Loop delay budget:

$$T_d = \underbrace{T_s/2}_{\text{ZOH}} + \underbrace{T_s}_{\text{compute-to-apply latch}} + \underbrace{\ll 0.1\ \text{ms}}_{\text{ADC+SPI}} \approx 1.5\ \text{ms (worst)},\ \ 1.0\ \text{ms (nominal)}$$

**6d. Resulting design plant** ($r \to \alpha_{act}$, continuous-time for synthesis):

$$\boxed{\;G_P(s) = \frac{K\, e^{-T_d s}}{(\tau_r s + 1)(\tau_f s + 1)}\;}$$

| Parameter | Nominal | Range | Physical origin |
|---|---|---|---|
| $K$ | 1 | $[0.75,\ 1.25]$ | mismatch gain term §3(3): holds for $r \in [0.3, 0.7]$ at $I_{tot} \ge 2$ A. At the $r$ range edges with the full ±0.4 V mismatch budget it widens to $[0.55,\ 1.45]$ — either design to the wide set, or tighten after the §9 bench measurement of $\Delta V_0$ |
| $T_d$ | 1.0 ms | $[0.5,\ 2.0]$ ms | ZOH + latency at $T_s = 1$ ms |
| $\tau_r$ | 100 µs | $[20,\ 300]$ µs | converter loop lag, lumped with INA/bus parasitics |
| $\tau_f$ | 0.8 ms | design choice | optional 200 Hz measurement prefilter (§7); set $\tau_f = 0$ if not fitted |

For synthesis, replace $e^{-T_d s}$ with a 2nd-order Padé approximant (see
`droop_plant.m`); for μ/disk-margin checks, sweep the corner combinations. The plant is
**delay-dominated with near-unity gain** — the same "easy plant, but H∞ still leaves
$T(0) \ne 1$" situation as the alternate system (Eq. 12) of the Youla-H paper, so the
post-synthesis gain tuning step is directly applicable.

**6e. Converter-loop detail (TPS61288 DS §9.2.2.5) — why the $\tau_r$ lump is
sufficient.** The TPS61288 is a constant-off-time peak-current-mode boost with external
compensation; its small-signal loop is Eq. 7–14 of the datasheet ($K_{COMP}=13.5$ A/V,
$G_{EA}=180$ µS, $f_{SW}=500$ kHz). Inverting DS Eq. 12, the voltage-loop crossover is
$f_c = R_C(1{-}D)V_{ref}G_{EA}K_{COMP} / (2\pi V_{OUT}C_O)$. With the board values
($R_C = 61.2$ k **both channels** after the post-manufacturing BT bodge — schematic
still shows 27.4 k on BT — $L=2.2$ µH, $C_O = 3{\times}22$ µF, evaluated at 30 µF
derated / 66 µF nominal, and $V_{OUT} = 15.91$ V after the RD1 = 215 k retune):

| Channel | $f_c$ (derated / nominal $C_O$) | equiv. $\tau_r = 1/2\pi f_c$ |
|---|---|---|
| FC ($V_{in}$ 9–12 V) | 16.8–22.5 / 7.7–10.2 kHz | 7–21 µs |
| BT ($V_{in}$ **7.4–8.4 V** — system operating floor, decision 2026-07-10), $R_C$ = 61.2 k | 13.8–15.7 / 6.3–7.1 kHz | 10–25 µs |
| *(BT pre-bodge, 27.4 k — for the record)* | *6.2–7.0 / 2.8–3.2 kHz* | *23–57 µs* |

Adequacy of the first-order lump, quantitatively:
1. **Time-scale separation is ≳ 2.5 decades.** The share loop crosses at ~110 rad/s
   (17.5 Hz); the converter loops cross at 6–22 kHz. Even the *slowest modeled*
   $\tau_r = 300$ µs contributes only 1.9° of phase at the share crossover (the
   predicted 7–25 µs contribute < 0.2°). The share-loop design is insensitive to the
   entire plausible $\tau_r$ range — which is why it is lumped, and why the 60-corner
   sweep over [20, 300] µs passes with near-identical margins.
2. **What the lump omits lives far out of band.** The converter's RHP zero
   ($f_{RHPZ} = R_O(1{-}D)^2/2\pi L$ = 31–330 kHz over the 2–8 A load envelope with
   the 7.4 V BT floor and 16 V bus) and any
   resonant peaking at $f_c$ from thin converter phase margin sit where the share loop
   gain is ≤ −49 dB ($|L| \approx k_I/\omega$ at 31 krad/s, before the prefilter and
   controller rolloff). A +10 dB converter-resonance peak would still be −39 dB in the
   share loop. These affect the converter's own output ringing (bench-visible, CAL-3),
   not share-loop stability.
3. **PFM at light load** (per-channel current below ~0.5–0.6 A) slows the converter
   loop and is unmodeled — but even a 1 ms effective lag costs 6.3° at the share
   crossover, less than the phase already budgeted by the $T_d = 2$ ms delay corner
   (12.6°); and the loop is frozen near zero current anyway.
4. **Bodge rationale and margins (7.4 V BT floor, 16 V bus).** Matching $R_C$ makes
   the two channels' closed-loop lags symmetric (~14–17 kHz each at derated $C_O$),
   which is the assumption behind the single shared $\tau_r$ in $G_P$. With the
   battery held to **7.4–8.4 V** (system operating decision, 2026-07-10 — enforce
   eventually via `LIMIT_V_BATT_MIN`), the DS guideline $f_c \le f_{RHPZ}/5$ holds on
   the BT channel for per-channel currents up to **3.6 A** at worst-case cap derating
   (30 µF), or **4.8 A** counting the 10 µF bodge caps at the BT output; FC clears it
   up to 4.4 A. Against this car's ≤ ~3 A per channel that is ≥ 20 % frequency
   margin (the 16 V retune raised every $f_c$ by ~(17.5/15.9)², consuming some of the
   RHPZ margin the 7.4 V floor bought — still clear). The deep-discharge caution that
   motivated the original 27.4 k is retired by the operating floor. CAL-3 step 5
   keeps a confirmation ringing check at the floor (7.4 V, max current).

**Empirical companion:** the time-scale-separation argument above is verified
quantitatively in `full_order_validation.md` — an independently constructed full-order
model (complete DS §9.2.2.5 dynamics, 11 states, `tps61288_full_model.py` +
`full_order_model.m`) deviates from this simplified plant by < 4 % nominally and < 6 %
across a 432-point operating envelope in the design band, and the shipped controller's
closed-loop behavior on it is indistinguishable from the design predictions.

---

## 7. Design targets (inputs to weight selection)

| Requirement | Value | Rationale |
|---|---|---|
| $T(0) = 1$ (strict) | exact | Youla-H gain condition; rejects the DC mismatch disturbance $d$, eliminates ramp-following bias when EMS blends $\alpha_{req}$ |
| Closed-loop bandwidth $\omega_c$ | 30–60 rad/s (5–10 Hz) | track EMS steps in < 100 ms; ≥ 20× below the 1 kHz sample rate and ≥ 10× below the $1/T_d$ delay limit (≈ 660 rad/s) |
| $\|S\|_\infty$ | < 6 dB ($M_2 > 0.5$) | robustness vs. the §6d parameter ranges |
| $Y$ high-frequency rolloff | ≥ 20 dB/dec above ~300 rad/s | limit MDAC jitter from the $1/I_{tot}$-scaled sensor noise (§5b) |
| Actuator limits | $r \in [r_{min}, r_{max}]$ per §4 table | anti-windup on the discrete controller; freeze integrator when $I_{tot} \approx 0$ or BT off-bus (§3) |

Weight starting points (MATLAB `makeweight`, mirroring the paper's Appendix A):
`Wp = makeweight(1e4, 40, 0.707)`, `Wd = makeweight(0.707, 40, 1e3)`,
`Wu = makeweight(0.707, 400, 1e4)` — then iterate; the Youla-H step absorbs the
$T(0)$ residual whatever the final weights are.

Implementation form: discretize $G_{C,YH}$ at $T_s = 1$ ms (Tustin), realize as a
biquad cascade / difference equation replacing `PI_Controller_Power()`, with output
clamp to $[r_{min}, r_{max}]$ and clamping (conditional-integration) anti-windup
consistent with the existing firmware pattern.

---

## 8. Parameter table (single source of truth)

| Symbol | Value | Units | Source |
|---|---|---|---|
| $V_{ref}$ | 0.6 (**verified**: TPS61288 DS §7.5, 0.588/0.6/0.612 V — ±2 % spread feeds the ΔV₀ budget §5a; per-board value still measured in CAL-1) | V | TPS61288LRQQR.pdf §7.5 |
| $R_{D1}$ | **215 k** (bodged from 237 k, both channels, 2026-07-11 — schematic still shows 237 k) | Ω | 16 V bus retune; schematic sheets 1–2 (`RD1-FC`/`RD1-BT`) carry the old value |
| $R_{D2}$ | 10 k | Ω | Schematic (`RD2-*`) |
| $R_{inj}$ | 53.6 k | Ω | Schematic (`RINJ-*`) |
| $R_{op1}, R_{op2}$ | 10 k, 40.2 k | Ω | Schematic (`ROP1/2-*`) → $A_v = 5.02$ |
| $K_{sns}$ | 0.1 | V/A | INA253A1IPWR.pdf (A1 variant fitted; 0.4 if respun with A3) |
| $R_{e,max}$ | 2.014 | Ω | derived: $K_{sns} A_v R_{D1}/R_{inj}$ |
| $V_0$ | 15.91 | V | derived (16 V retune target) |
| $k_d$ | 0.30 (proposed) **TODO(calibrate)** | Ω | §4 trade table; bench decision. Hard bound $k_d \le R_{e,max}\, r_{min} = 0.3020$ Ω for $r_{min}=0.15$ |
| MDAC | 12-bit, gain $D/4096$ | — | ad5426_5432_5443.pdf, voltage-switching mode. **TODO(verify): input-voltage linearity limit in this mode ($V_{droop} \le 1.5$ V at 15 A — check datasheet allows it)** |
| $C_{bus}$ (Idle / Run) | ~30–80 µ / ~500–1000 µ **TODO(calibrate)** | F | Schematic sheet 4 (RT1987 10 µF ceramics ×n, 470 µF V-MOT electrolytic, VESC input caps unknown) |
| $\tau_r$ | 100 µ **TODO(calibrate: bench step test §9)** | s | TPS61288 closed-loop estimate |
| $T_s$ | 1 m (proposed) | s | §6c |
| ADC | 12-bit, 3.3 V, `SCALE_I` = 8.06 mA/LSB | — | firmware §5 of CLAUDE.md |
| $\Delta V_0$ budget | ±0.40 **TODO(calibrate: measure per board)** | V | §5a tolerance RSS |
| INA253A1 offset, BW | — **TODO(verify: INA253A1IPWR.pdf)** | | affects light-load noise floor |
| OPA197 output ceiling | ~4.9 (5 V rail bodge) | V | headroom check §4: not binding for $g\,I \le 9.8$ A |

## 9. Bench identification & calibration plan

The model above is credible for *structure*; three numbers should be measured before
final synthesis (all doable in **State 98** with the existing `O` open-loop droop
command + `S` status dump):

1. **Static map & $\Delta V_0$:** with a fixed resistive load on VBUS, sweep open-loop
   $r$ (command `O`) over $[r_{min}, r_{max}]$, log $I_{FC}, I_{BT}$ → fit
   $\alpha = r + \Delta V_0 r(1-r)/(k_d I_{tot})$ for $\Delta V_0$ and confirm slope ≈ 1.
   Repeat at 2–3 load currents. This also validates the corrected $g$ mapping (§4).
2. **Step response / $\tau_r$, $T_d$:** toggle $r$ between two values, capture
   $I_{FC}(t)$ on a scope from the INA253 analog outputs (`FC-CURR` node) — the
   settle gives $\tau_r$; the command-to-first-movement gives the true $T_d$.
3. **$k_d$ selection:** verify bus sag $k_d I_{tot}$ at max load is acceptable to the
   VESC input, and that the achieved share span covers the EMS's requested range.

Update this file and `droop_plant.m` with measured values; keep the `TODO(calibrate)`
markers until then, per project convention.

## 10. File map

| File | Role |
|---|---|
| `system_model.md` | this document — derivation + parameter source-of-truth |
| `droop_plant.m` | MATLAB: builds $G_P$ (nominal + corners), weight templates, H∞ synthesis + Youla-H gain tuning (paper Appendix A flow), discretization for firmware |
| `validate_model.py` | stdlib-Python numerical check of §3/§6a claims (exact statics, instantaneous nominal share, mismatch-path bus pole, MDAC saturation audit) |
| `figures/droop_signal_chain.svg` | per-channel droop hardware block diagram (thesis figure) |
| `figures/control_loop_model.svg` | linearized SISO design loop with disturbance/noise entry points (thesis figure) |
| `figures/step_response_*.csv` | outputs of `validate_model.py` |

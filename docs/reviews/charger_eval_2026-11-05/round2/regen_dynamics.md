# Regen dynamics and capture analysis (round 2, 2026-11-05)

Scope: what a regen event on this rig really delivers at V-MOT, and what an always-powered
replacement charger (operator ruling 3, 2026-11-05) must do to capture it. Data: 9 BLG logs at
1 kHz with real regen (ML0151, ML0157, ML0165, ML0195, YP0166, YP0196, YP0198, YP0204, YP0214;
`logs/<name>/<name>.csv`, all fw v16-v19 era, State 98 `D`/`Y` profiles) and the RegenTest_v2
rosbag (`logs/rosbags/rosbag_sweep-noclip_2026-10-30_01-30-16`, 50 Hz, fw <= v35). Scripts and
figures are beside this file (`bursts.py`, `decel.py`, `events.py`, `capsim.py`, `grid.py`,
`taumax.py`, `figs.py`; `fig1`-`fig4` PNG). The repository was not modified.

Scale convention: V-MOT = `V_rgn / 0.8505` (the pin-39 0.85x artefact, per-bag median ratio
0.849-0.854, `docs/reviews/fw36_regen_2026-11-04/README.md` item 6). The ratio was measured
only at ~16 V, so values near 21 V carry an unquantified calibration error. The scope check in
section 7 settles it.

---

## 0. Headline

1. **The regen "burst" seen so far is not a property of the braking event. The VESC stops it.**
   Every hard decel shows one pattern, in the BLGs and in the bag alike (fig1): a regen pulse
   that charges V-MOT from 15.9 V to **21.20-21.47 V in 19-47 ms**, a sharp peak (no clamp
   plateau), then a **linear decay at 14-20 V/s** with **no regen current at all**, then a second
   pulse **0.523-0.562 s** after the first (mean 0.535 s, 8 events). All of this happens while
   `I_cmd` stays railed at -12 A. A fixed cut-off voltage plus a fixed re-arm time match a VESC
   over-voltage fault with the VESC's fault-stop timer. That reading is **UNCONFIRMED**. It comes
   from my reading of the VESC firmware: a FAULT_CODE_OVER_VOLTAGE trips when the input exceeds
   `l_max_vin`, and the default fault stop time is 500 ms (recollection, not a primary source).
   It is checkable in minutes (section 7, M-R0).
2. **The TL431/BSP170P chopper dissipated ~0 J in every recorded event.** The peaks
   (21.2-21.5 V true) sit below the chopper's design point of 2.495 x (1 + 78.7k/10k) = 22.13 V
   (BOM: U-SNT TL431BIDBZR, R1-SNT 78.7k, R2-SNT 10k). The peak is a cusp, not a plateau, and the
   post-peak excess sink lasts about 5 ms at about 7 mA (C = 0.97 mF scaling), so it is under
   about 1 mJ. The energy that reached the node went into the node capacitance and was then
   consumed by the VESC's own housekeeping during the fault stop. The braking energy that was
   never converted stayed kinetic and was lost to friction during the 0.5 s coast.
3. **Energy that reached V-MOT per hard decel, measured: C x (134-292) J/F**, i.e. **0.13-0.28 J
   at C = 0.97 mF** (HIL nominal) and **0.54-1.17 J at C = 4 mF** (the value two weak checks point
   to, section 2). The node capacitance is the single largest unknown in this analysis.
4. **The energy available if the VESC is not cut off is set by mechanics.** Model at the
   firmware's -12 A rail: **2 -> 1 m/s: 2.09 J electrical at V-MOT, 1.81 J into the pack
   (215 mC at 8.4 V), peak 11.1 W, 0.30 s.** **3 -> 1 m/s: 6.32 J / 5.55 J (661 mC), peak
   18.9 W, 0.58 s.** Gentler braking at 5 A (2 -> 1 m/s) gives 2.17 J / 1.83 J over 0.53 s: more
   energy, because copper loss falls with I squared. That is about **10x what reaches the node
   today**.
5. **An always-powered charger with its input threshold below the VESC cut-off removes the
   cut-off, but only if it responds before V-MOT climbs from Vth to ~21.35 V.** Missing that
   window is a cliff, not a gradual loss: the VESC trips, coasts for 0.53 s, and the event drops
   to 6-40 % capture. **Required warm-response spec, section 5.**
6. **A cold-start charger cannot catch the first pulse on this rig.** The VESC cuts out 19-47 ms
   after brake onset, before any cold path is ready (65-170 ms, round 1). On a 2 -> 1 m/s step it
   captures 36-40 % (C = 0.97 mF), and only because braking resumes after the 0.53 s fault stop
   with the charger by then warm. On decels shorter than ~0.55 s it captures only the
   node-capacitance energy above Vth.

---

## 1. Measured regen events (per decel)

### 1.1 The pulse (1 kHz BLG)

`C dV/dt` during the rise is 0.1-0.3 A at C = 0.97 mF (`zoom.png`). It stops abruptly at the peak
and becomes a constant -13 to -20 mA·(C/0.97 mF) sink. Onset is **within ~5 ms of `I_cmd`
stepping negative** (YP0196 at 21.968 -> 21.973 s). This corrects fw37_planning section 3.2
("0.08-0.12 s after the setpoint falls"). That figure is the setpoint-to-current chain seen at
50 Hz, not the electrical onset.

| Event | Pulses | Peak V per pulse | Rise (s) | Spacing (s) | v0 -> v (m/s) | KE drop (J) | Time above bus (s) | Node energy, C = 0.97 mF (J) | C = 4 mF (J) |
|---|---|---|---|---|---|---|---|---|---|
| ML0151 41.36 | 2 | 21.41, 21.33 | 0.026, 0.032 | 0.529 | 2.67 -> 1.55 | 8.28 | 0.73 | 0.197 | 0.81 |
| ML0157 47.30 | 2 | 21.30, 21.25 | 0.021, 0.019 | 0.527 | 3.00 -> 1.90 | 9.39 | 0.68 | 0.193 | 0.80 |
| ML0165 22.64 | 1 | 21.21 | 0.019 | - | 3.00 -> 2.38 | 5.79 | 0.34 | 0.095 | 0.39 |
| ML0165 28.55 | 2 | 21.29, 21.20 | 0.027, 0.035 | 0.534 | 2.49 -> 1.43 | 7.26 | 0.72 | 0.191 | 0.79 |
| ML0195 33.20 | 2 | 21.42, 20.50 | 0.040, 0.053 | 0.546 | 2.00 -> 0.99 | 5.27 | 0.50 | 0.180 | 0.74 |
| YP0166 21.97 | 3 | 21.32, 21.24, 20.94 | 0.025, 0.019, 0.032 | 0.531, 0.523 | 3.00 -> 1.53 | 11.60 | 0.81 | 0.283 | 1.17 |
| YP0196 21.97 | 2 | 21.42, 20.62 | 0.040, 0.074 | 0.544 | 1.99 -> 1.00 | 5.23 | 0.49 | 0.183 | 0.75 |
| YP0198 21.98 | 2 | 21.40, 17.87 | 0.047, 0.019 | 0.562 | 1.98 -> 1.00 | 5.13 | 0.48 | 0.131 | 0.54 |

(Source: `events.json`. Node energy = C x sum of 0.5(Vpk^2 - Vbus^2). KE uses M_EFF 3.5 kg
(`tools/hil_plant_sim.py:331`). "Rise" runs from bus +0.15 V to the last sample above
40 V/s. Speeds are a median-filtered `v_act`. ML0151-ML0165 predate the fw v18 encoder fixes,
so treat their speeds as approximate.)

- **Pulse end classes.** Every pulse with `I_cmd` on the rail that reaches > 20.9 V ends there
  and is followed by the sink slope (14.2-20.1 V/s) ("OV-cut?" in `decel.py`). Pulses on smaller
  commands (Y-profile step-downs at -2 to -6 A) peak at 17.1-19.5 V and end when the command ends.
- **The bag** shows the same thing at 50 Hz on fw <= v35 (fig1, bottom panel). First pulses peak
  at 21.19-21.47 V. The decay lasts 0.34-0.42 s. Second pulses come 0.54-0.56 s later and peak at
  16.8-19.0 V; they end when the drive controller reverses the command.
- **Second-pulse dV/dt** is 58-152 V/s against 107-252 V/s for the first, i.e. less regen power
  at the lower speed. Consistent.

### 1.2 Regen current and power at the motor node

| Quantity | C = 0.49 mF (board only: CAL + C-D6/7) | C = 0.97 mF (HIL default, `C_VESC_DEFAULT` 0.5 mF) | C = 4 mF (indicated, section 2) |
|---|---|---|---|
| Pulse current into node (mean / peak) | 0.03-0.06 / 0.15 A | 0.06-0.12 / 0.3 A | 0.25-0.5 / 1.2 A |
| Pulse power (mean, ~19 V) | 1.2-2.3 W | 2.4-4.6 W | 10-19 W |
| Sink after cut (VESC housekeeping + dividers) | 8 mA | 16.5 mA | 68 mA |
| Electrical energy per hard decel | 0.07-0.14 J | 0.13-0.28 J | 0.54-1.17 J |
| Chopper dissipation | ~0 (< 1 mJ) | ~0 | ~0 |

Mechanical cross-check, from the motor model in `capsim.py`: P_e = 0.97·(K_F·I·v·0.9 -
1.5·I^2·R_ph), with K_F 0.7538 N/A (`hil_plant_sim.py:332`) and R_ph 22.6 mOhm
(`docs/VESC_MOTOR_INTEGRATION.md` section 2, from `motor_id_20260815.md`). Gear efficiency 0.9
and inverter efficiency 0.97 are TODO(verify) assumptions. At 2 m/s and 12 A this gives 11.1 W.
That matches the measured node power only if C is about 4 mF.

---

## 2. V-MOT node capacitance

- Board: **CAL 470 µF / 35 V** Al-el (BOM, EEE-FN1V471UP, 80 mOhm) plus **C-D6 and C-D7, 10 µF /
  35 V X7R 1206** (BOM line "Ideal diode larger power caps"; netlist check on
  `references/Scale_Car_Board_20260624.sch`: net V-MOT = C-D6.1, C-D7.1, CAL.1, Q-SNT.SOURCE). At
  ~20 V bias the X7R parts derate to roughly 5 µF each (TODO(verify): TDK curve), so the board
  contributes about **0.48 mF**.
- VESC Six EDU input capacitance: **unmeasured anywhere in the project**
  (`docs/boost-bringup-debug.md:385-392`, "Open qualification"). The HIL uses 0.5 mF
  (0.2-0.9 mF envelope, `tools/hil_electrical.py:459`).
- Two weak indications point to about 4 mF total:
  1. Mechanics during the pulse on the two cleanest decels. YP0196 decelerates at 3.73 m/s^2 in
     the pulse against 1.15 m/s^2 coasting, i.e. ~9.0 N, which is the -12 A rail. That implies
     ~10.6 W electrical over 40 ms, i.e. C ≈ 4.1 mF. ML0195 gives C ≈ 3.7 mF. The other decels'
     30-50 ms decel fits are too noisy to use.
  2. The bring-up capture-5 park decay of 113 V/s on ~590 µF implies a VESC + divider sink of
     ~67 mA (`docs/boost-bringup-debug.md:306`). The same sink against the 17 V/s regen decay
     gives C ≈ 3.9 mF. This is circular if capture 5 already included the VESC caps.
- **Verdict:** C is between 0.48 mF and about 5 mF, and the evidence leans toward several mF. It
  is the first thing to measure (M-R1). Every timing requirement below scales about linearly with
  it.

**Does adding capacitance help?**

- **Yes, for warm capture.** It buffers the gap between Vth and the VESC cut-off. Each added mF
  holds 0.5·C·(21.35^2 - 19^2) = 47 mJ at Vth 19 V, which is ~4 ms of an 11 W surplus, and the
  allowed response time τ grows in proportion (fig4).
- **Barely, for the present no-charger case.** It raises the stored pulse energy, but that
  energy is still consumed by the VESC's own sink.
- **Yes, for cold capture, only with very large C.** At 10 mF the node would hold 0.5 J above
  Vth until a 65-170 ms cold charger arrives.
- **Cost (Death-5 rule).** D-MT-EN soft-starts the node at **0.65 A per mF** with CSS 100 nF;
  demand reaches 1 A at 1.55 mF and the 2.5 A typical ramp-start clamp at 3.87 mF
  (`docs/boost-bringup-debug.md:383-392`). If the VESC already brings the node to ~4 mF, there is
  **no inrush headroom left**. Added C therefore needs CSS on D-MT-EN scaled in proportion, plus
  a re-check of the pre-charge sequence. Do not add C before M-R1.

---

## 3. Capture model

`capsim.py` (time step 20 µs):

- **Mechanics.** M 3.5 kg, F = 2.00 + 0.534·v N (`hil_plant_sim.py:331-334`).
- **VESC.** Commanded braking current (12 A or 5 A, 5 ms ramp) until v reaches the target. P_e as
  in section 1.2, limited by Battery Current Regen Max 1.5 A (`docs/VESC_MOTOR_INTEGRATION.md:231`).
  **Over-voltage cut at 21.35 V (mean measured peak), then 0.53 s with no current and no braking
  force.**
- **Node.** C, sink = C·17 V/s (measured), the TL431 shunt above 22.13 V limited to V/47 Ohm, and
  the MOT_PWR ideal diode holding V-MOT >= V_bus 15.9 V.
- **Warm charger.** Input capability a(t) rises first-order with τ toward
  P_in,max/V = I_ceil·8.4 V/(0.9·V) from the moment V-MOT exceeds Vth. Input regulation draws only
  what holds V-MOT at Vth (1 ms loop). Pack energy = 0.9 x input energy (efficiency 0.9 is
  TODO(verify) per candidate).
- **Cold charger.** No current until (V-MOT > V_bus + 0.3 V) + L, then the same ramp with
  τ = 5 ms.
- **Fraction** = pack energy / pack energy of an ideal instantaneous sink with unlimited ceiling
  and no VESC cut-off, at the same C.

The no-charger case reproduces the bench pattern (fig2, blue): cut at 21.35 V after ~10 ms,
linear decay, second pulse at 0.53 s. The model's rise is ~10 ms at C = 0.97 mF against 19-47 ms
measured, which is the C discrepancy of section 2.

### 3.1 Capture fraction, warm, C = 0.97 mF (% of ideal; VESC trips in parentheses)

2 -> 1 m/s at 12 A (ideal 1.81 J pack). Rows are τ in ms; columns are Vth 18.0 / 18.5 / 19.0 / 19.5 V.

| τ (ms) | I_ceil 1.0 A | 2.0 A | 2.5 A | 3.0 A |
|---|---|---|---|---|
| 1 | 98 / 97 / 97 / 96 (0) | 98 / 97 / 97 / 96 (0) | 98 / 97 / 97 / 96 (0) | 98 / 97 / 97 / 96 (0) |
| 5 | 43 / 40 / 38 / 37 (1) | 98 / 97 / 97 / 96 (0) | 98 / 97 / 97 / 96 (0) | 98 / 97 / 97 / 96 (0) |
| 20 | 40 / 39 / 38 / 6 | 40 / 39 / 38 / 37 (1) | 98 / 97 / 38 / 37 | 98 / 97 / 97 / 37 |
| 50 | 39 / 9 / 6 / 5 | 40 / 39 / 38 / 37 (1) | 40 / 39 / 38 / 37 (1) | 40 / 39 / 38 / 37 (1) |
| 100 | 9 / 7 / 5 / 4 (2) | 39 / 38 / 37 / 6 | 39 / 38 / 38 / 37 (1) | 40 / 39 / 38 / 37 (1) |

3 -> 1 m/s at 12 A (ideal 5.55 J pack; peak regen 18.9 W):

| τ (ms) | 1.0 A | 2.0 A | 2.5 A | 3.0 A |
|---|---|---|---|---|
| 1 | 32 / 32 / 31 / 31 (2) | 99 / 99 / 99 / 98 (0) | 99 / 99 / 99 / 98 (0) | 99 / 99 / 99 / 98 (0) |
| 5 | 32 / 14 / 13 / 12 | 60 / 59 / 59 / 59 (1) | 99 / 99 / 59 / 59 | 99 / 99 / 99 / 59 |
| 20 | 14 / 13 / 12 / 12 (3) | 32 / 31 / 31 / 12 | 32 / 31 / 31 / 30 (2) | 60 / 59 / 31 / 30 |
| 50 | 14 / 13 / 12 / 3 | 32 / 31 / 13 / 12 | 32 / 31 / 31 / 30 (2) | 32 / 31 / 31 / 30 (2) |
| 100 | 14 / 13 / 4 / 3 | 14 / 13 / 13 / 12 | 32 / 31 / 13 / 12 | 32 / 31 / 31 / 12 |

2 -> 1 m/s at 5 A (ideal 1.83 J): 95-97 % up to τ = 20 ms at every ceiling; at 2.5 A, up to
τ = 50 ms; at 3.0 A and Vth <= 18.5 V, up to τ = 100 ms.

Cold start (L = 65 / 170 ms, 2.5 A, Vth 19 V): **37 / 36 %** (2 -> 1 m/s, 12 A), **59 / 58 %**
(3 -> 1 m/s), **40 / 39 %** (5 A). At C = 4 mF: 20 / 13 %, 51 / 49 %, 80 / 14 %. Full grids, incl.
C = 0.49 / 2 / 4 mF, are in `grid.json`; fig3 plots them.

Reading the tables:

1. **The ceiling has to cover the peak regen power at Vth, or the VESC trips.** A 1.0 A ceiling
   (9.3 W in) fails any 12 A brake above ~1.6 m/s. 2.0 A covers 2 m/s. **2.5 A covers 3 m/s with
   margin (23.3 W in against 18.9 W peak).** 3.0 A adds response-time margin only.
   - Alternative: set the VESC's **Battery Current Regen Max to at most the charger's input
     capability at Vth**: 0.49 / 0.98 / 1.23 / 1.47 A for ceilings of 1.0 / 2.0 / 2.5 / 3.0 A at
     19 V.
   - The VESC then limits braking torque instead of tripping. The uncaptured braking stays
     kinetic, which is a drivability cost and not a hazard.
2. **Vth matters little for energy.** Vth 18.0 -> 19.5 V costs 1-2 % at C = 0.97 mF and up to 8 %
   at 4 mF (housekeeping draw at the higher node voltage). It matters for timing: a lower Vth
   leaves a larger buffer before 21.35 V. **The safety floor sets it** (> 17.5 V firmware OV,
   > 18.3-19.5 V TPS61288 OVP for the failed-FB case, round 1 spec section 2.2).
3. **V-MOT behaviour with input regulation.** While P_e is below the input ceiling, V-MOT
   plateaus at Vth for the whole braking (fig2, orange) instead of cutting at 21.35 V. The chopper
   was not dissipating before either; below its 22.13 V knee it stays off. If P_e exceeds the
   ceiling, V-MOT climbs at (P_e/V - a)/C and the VESC trips.

---

## 4. Raising the VESC cut-off: a cheap lever, if M-R0 confirms the mechanism

If the cut is the VESC's `l_max_vin` setting, raising it above the chopper knee changes the
picture. VESC Six EDU `HW_LIM_VIN` is 5.5-27 V (`docs/VESC_MOTOR_INTEGRATION.md` section 2,
hwconf `trampa/vesc_edu`). Example setting: 24 V. The chopper then becomes the transient buffer,
as its "22V CHOPPER CIRCUIT" design intends: it absorbs up to 22.13/47 = 0.47 A (10.4 W).
Modelled with V_OV = 24 V at C = 0.97 mF:

- **2 m/s brakes never trip, with any τ or with no charger at all.** With no charger the chopper
  burns 1.87 J. With τ = 100 ms the charger captures 88 % and the chopper burns 0.18 J.
- 3 m/s at 12 A: allowed τ rises from 4.5 ms to 63-75 ms (2.5 A ceiling).
- 5 A brakes: never trip.
- Cold start, L = 65 ms: 70 % / 57 % / 85 % (2 m/s 12 A, 3 m/s 12 A, 5 A), against 37 / 59 / 40 %.

Constraints:

| Part | Rating | Comment |
|---|---|---|
| C-D8 / C-D10 on VCHG-IN | 25 V | Round 1 already says replace with >= 35 V. Mandatory here, because REGEN is closed through Run in the always-powered design |
| RT1987 | 32 V recommended max | OK |
| BSP170P | 1.8 W (Ta) | A linear shunt peaks at V^2/(4·47) = 2.6 W inside the FET at mid-current, so it is transient only. Repeated 1.9 J events need a thermal check, TODO(verify: BSP170P SOA) |
| `LIMIT_V_RGN_MAX` | 28 V raw, ~32.9 V true | Re-derive anyway (fw36 review item 6) |

This is a VESC Tool setting, not a board change.

---

## 5. Required warm-response spec for the charger

**Definition (how to measure it on the EVM, M1 of fw37 planning, adapted):**

1. Configure ICHG = I_ceil and VINDPM/UVCL/MPPT = Vth.
2. Feed the input from a stiff supply 0.5 V below Vth. The charger is enabled but idle: not
   suspended, not Hi-Z.
3. Step the supply to Vth + 1.0 V.
4. **τ_warm** = time from the step to battery current reaching 63 % of ICHG, with no
   input-detect or deglitch restart.

The 10-90 % rise is ~2.2·τ_warm.

**Bound:** τ_max ≈ C·(V_cut - Vth) / (A·[x + (1-x)·ln(1-x)]), where A = input capability at Vth
and x = I_regen/A. For a loop-type charger whose current tracks the demand rather than ramping to
its ceiling, the conservative form is τ_max = C·(V_cut - Vth)/I_regen. Simulated τ_max, with no
VESC trip (`taumax.json`, fig4), at **Vth 19.0 V, ceiling 2.5 A**:

| Braking case | C = 0.49 mF | C = 0.97 mF | C = 2 mF | C = 4 mF |
|---|---|---|---|---|
| 3 -> 1 m/s, 12 A (19 W) | 2.5 ms | **4.5 ms** | 10 ms | 23 ms |
| 2 -> 1 m/s, 12 A (11 W) | 8.2 ms | **17 ms** | 41 ms | 114 ms |
| 2 -> 1 m/s, 5 A (5.8 W) | 34 ms | **73 ms** | 187 ms | > 300 ms |

Conservative loop-type bound at C = 0.97 mF: 2.3 / 4.0 / 7.9 ms for the same three rows.

**Required spec (unmodified board, VESC cut-off as found, nominal C):**

- **τ_warm ≤ 4 ms** (10-90 % ≤ 9 ms) for hard braking up to 3 m/s.
- **≤ 2 ms** if C turns out to be board-only (0.5 mF).
- It relaxes to about 20 ms if C ≈ 4 mF is confirmed, or to ~60 ms (3 m/s) / unlimited (2 m/s)
  if the VESC cut-off is moved above the chopper (section 4).

**Also required:**

- **Ceiling ≥ 2.5 A** at 8.4 V (input ≥ 23 W at Vth), or the VESC regen current limited to
  input capability.
- **No input-detect deglitch, POR or soft-start restart when V-MOT crosses Vth.** The charger
  stays switching-ready from boot through Run. A charger that re-runs a 50 ms+ CHRG_OK/adapter
  deglitch or a battery detect per crossing behaves like the cold case (36-60 %, or ~0 on short
  decels).
- **Input operating range to ≥ 24 V without OVP drop-out** if section 4 is adopted. Abs max
  ≥ 30 V (round 1 spec).
- **Cold start (65-170 ms) is not a viable regen mode on this rig.** The VESC trips in
  19-47 ms.

---

## 6. Can the EMS measure and use regen at these magnitudes?

Magnitude:

- With a warm charger: ~0.2 C (1.8 J) per 2 -> 1 m/s hard decel, ~0.66 C (5.5 J) per
  3 -> 1 m/s.
- Against a 5 Ah pack (`BATT_CAPACITY_AH` 5.0, TODO(verify), `tools/hil_electrical.py:975`) that
  is a ΔSoC of 1.2e-5 to 3.7e-5 per decel.
- Against ~890 J of FC energy per 61 s cycle (round 1), 0.2-0.6 % per decel. A cycle with 5-10
  hard decels would recover ~1-5 % of FC energy.
- Today's no-charger node energy (0.13-0.28 J at nominal C) is 10x smaller.
- **Regen exists only when commanded decel exceeds coast-down**, (2.00 + 0.534 v)/3.5 =
  0.65-1.03 m/s^2 at 0.5-3 m/s. The UDDS-scaled bench cycles never brake (fw36 review), so the
  research cycles must include decels steeper than coast-down, or use HIL drag compensation.

Measurement paths:

| Instrument | Resolution / rate | What it gives for a 0.3 s, ~0.7-1.1 A (pack-side) burst |
|---|---|---|
| Ag105 reg 0x06 (now) | 0.011 A/count (`Ag105_Table7_I2C_Parameters.json`), 50 Hz poll | adequate, but Ag105 is being replaced |
| BQ25713 ADCIBAT | 64 mA LSB charge (SLUSD83C register map 29/28h, p.35); ~10 ms conversion (ADC_CONV, p.50) | ~11-17 counts at peak; ±32 mA/sample → ~1-2 mC random error on 200 mC (≈1 %); OK for hard decels, blind to today's 10-40 mA pulses |
| BQ25720 ADCIBAT | 64 mA LSB (SLUSDU3 p.41); 25 ms per channel (p.70) | 25 ms x channels → 2-4 samples per burst: marginal |
| BQ25798 IBAT_ADC | 1 mA LSB (SLUSDV2C p.17, REG33 p.117); 6-24 ms (p.16) | good resolution, rate-limited |
| LTC4015 IBAT + coulomb counter | 1.465 µV/RSNSB (Rev B Table 4, p.20) = 366 µA at the DC2039A's 4 mOhm (DC2039A manual p.3); 7 channels x ~1.6 ms (p.20); hardware QCOUNT (p.39) | best: integrates the burst in hardware, no sampling gap |
| VESC `avgInputCurrent` (`getVescValues`, State 98 `E`/`U`, ino ~9687) | VESC-side, blocking up to 100 ms per poll | motor-side ground truth for bench characterization only, not for the 1 kHz loop |
| Teensy INA253 FC/BT | unipolar, boost forward only | **cannot see regen** (CLAUDE.md section 5) |

**Verdict.** Yes, with a warm charger that captures the mechanics-limited energy and a charger
current ADC of ≤ ~64 mA LSB at ≥ 50 Hz. A hardware coulomb counter (LTC4015) is better.

- At ~1 % per-decel measurement error, the EMS can attribute regen charge per event and
  calibrate a regen term in the SoC model (the walk/DP regen chain, `tools/regen_power.py`,
  currently assumes ETA_REGEN 0.80 and the 1.5 A clip, both TODO(verify)).
- On the as-found VESC cut-off with a slow or cold charger, the signal is 10-40 mC per event.
  That is below a 64 mA-LSB ADC's useful range and is effectively unusable.

---

## 7. Measurements that settle the open items (none need the replacement charger)

| ID | Measurement | Settles |
|---|---|---|
| **M-R0** | State 98 `U` watch (2 Hz fault-code poll, ino 9438/4953) during a `D`/`V` 2 -> 1 m/s step. Plus VESC Tool: read **Maximum Input Voltage (`l_max_vin`)**, **Fault Stop Time**, and the `faults` terminal log | Whether the 21.35 V / 0.53 s cut is FAULT_CODE_OVER_VOLTAGE (headline 1); whether section 4 is available |
| **M-R1** | VESC disconnected, then connected: LCR or known-R decay on V-MOT | Node C (sections 2, 5) |
| **M-R2** | Scope V-MOT true and pin 39 on a hard decel | The 0.85 scale at 21 V; true cut level |
| **M-R3** | **Bench electronic load in CV mode on V-MOT** at Vth = 19 V, current limit 1.3 A (emulates the always-powered charger at 2.5 A) | Whether V-MOT then plateaus and braking continues (the H-V hypothesis); the real available regen power and energy before any charger is bought |
| **M-R4** | EVM warm step test (section 5 definition) | τ_warm per candidate |

M-R3 is the decisive pre-purchase test. If the VESC keeps regenerating with the node held at
19 V, the mechanics-limited numbers apply. If it still delivers only the 30-50 ms pulse (a
non-voltage cause, hypothesis H-T), the capturable energy is ~C·ΣΔV·Vth ≈ 10 mC at V-MOT
(0.17 J, 20 mC pack-side at C = 0.97 mF; 0.7 J at 4 mF) per decel, whatever charger is fitted.

## missing_primaries

- **VESC firmware / VESC Six EDU hwconf** (`vedderb/bldc`): the `l_max_vin` default for EDU, the
  over-voltage fault behaviour in current control, and the `m_fault_stop_time_ms` default
  (recalled as 500 ms, unverified). The headline mechanism rests on these. M-R0 also answers it
  from the device itself.
- **VESC Six EDU input capacitance** (Trampa schematic or manual): not in the repo.
- **Charger warm-response / VINDPM-loop transient data**: not specified in the datasheets read
  for this task (BQ25713/20/98, LTC4015 checked for ADC and range figures only). M-R4 must
  measure it.
- **TDK C3216X7R1V106K DC-bias curve** (C-D6/7 effective C) and **BSP170P SOA** (chopper duty if
  section 4 is adopted).

# Bond Graph — Scale Car DC Balancer Board (Rev 20260622)

A first-pass **bond graph** of the power flow on the DC balancer board, intended as the
starting point for a physical/dynamic model of the plant the firmware controls. This is a
*modeling document only* — it does not change any firmware. Companion diagram:
[`bond-graph-diagram.svg`](bond-graph-diagram.svg).

> **Scope.** This captures the **power (energy-transport) structure** of the board: the fuel
> cell and battery sources, the two boost converters, the ideal-diode/switch power paths, the
> VBUS node, the motor/VESC/vehicle drivetrain, the regen path + braking chopper, and the
> Ag105 charger return to the battery. Control loops (droop PI, motor PI, MPPT) appear as
> **signal/activated bonds**, not power bonds.

---

## 1. Why a bond graph (and what it buys us)

A bond graph is a domain-independent way to write the dynamics of a system that moves power
between electrical and mechanical domains. Every bond carries a power pair **(effort `e`,
flow `f`)** with `power = e·f`:

| Domain | effort `e` | flow `f` |
|--------|-----------|----------|
| Electrical | voltage `V` [V] | current `i` [A] |
| Mechanical (rotation) | torque `τ` [N·m] | angular velocity `ω` [rad/s] |
| Mechanical (translation) | force `F` [N] | velocity `v` [m/s] |

This board is *exactly* the kind of system bond graphs are good for: it spans three domains
(two electrical sub-domains either side of the boost converters, plus motor rotation and
vehicle translation), and energy flows **bidirectionally** (traction vs. regen). One graph
gives us:

- a single state-space model (the `I` and `C` elements are the states),
- explicit, auditable energy paths — which matters here because the open hazards
  (back-feed, boost-on-collapsing-rail) are **energy-routing** failures, and
- a clean mapping from the firmware **state machine** to **switched bond-graph modes**
  (§6) — each power-path switch is a bond that the MCU opens/closes, so each firmware state
  is a distinct causal topology.

---

## 2. Bond-graph element legend

Standard nine-element set, plus the modulated/switched elements this board needs:

| Symbol | Element | Role here |
|--------|---------|-----------|
| `Se`   | effort source | fuel-cell OCV, battery OCV(SOC), road grade |
| `Sf`   | flow source | (not used; sources are modeled as `Se`+`R`) |
| `I`    | inertia (stores flow energy) | boost inductors, motor rotor inertia, vehicle mass / bench flywheel |
| `C`    | compliance (stores effort energy) | converter caps, VBUS cap, V-MOT bulk cap, battery charge store |
| `R`    | resistance (dissipates) | source internal R, DCR/ESR, switch Rds(on), winding R, friction, aero drag, brake chopper |
| `TF`   | transformer | gearbox ratio, wheel radius (rotation↔translation) |
| `MTF`  | **modulated** transformer | each boost converter (modulus = `1−D`, set by droop), the VESC inverter, the Ag105 charger |
| `GY`   | gyrator | the motor (electrical↔mechanical via `kₜ`) |
| `MR`   | **modulated** resistor / switch | the 6 RT1987 ideal-diode power-path switches, the braking chopper |
| `0`    | 0-junction (common **effort**) | a voltage node — flows sum to 0 (KCL) |
| `1`    | 1-junction (common **flow**) | a series current loop / shared velocity — efforts sum to 0 (KVL) |

Bonds are drawn with a **half-arrow** (power-flow direction). **Signal/activated bonds**
(full arrow, no power) carry sensor readings and actuator commands to/from the MCU.

---

## 3. Word bond graph (top-level power flow)

```
   FUEL CELL ──[FC boost]──╮                                    ╭──> VESC ──> MOTOR ──> WHEEL/VEHICLE
                           ├─(FC_BUS)─╮                  (MOT_PWR)│         (GY)        (gearbox+road)
                           │          ▼                          │
                           │        V B U S  ─────────(MOT_PWR)──┤
   BATTERY ───[BT boost]───┤        (0-jcn) ──(FC_CHARGE)──╮     │
      │  ▲                 ├─(BT_BUS)─╯                     ▼     ▼ (regen)
      │  │ (charge return,                              CHARGER  REGEN NODE
      │  │  via BT_SEQUENCE)                            (Ag105)  + BRAKE CHOPPER (TL431/47Ω)
      │  ╰──────────────────────<────────────────────────┤  ▲       │
      │                          (charge current)        ╰──(REGEN)─╯
      ╰──> LOGIC LDO (always-on tap)
```

Power normally flows **left→right** (sources → VBUS → motor). During braking it flows
**right→left** (motor → regen node → charger → battery), with the **braking chopper** as the
primary fast clamp dumping surplus to heat.

---

## 4. Detailed acausal bond graph (textual junction structure)

Notation: `0`/`1` are junctions; `┊` / arrows are bonds; `‹sig›` marks a modulating signal
bond from the MCU. Each junction is annotated with its physical node.

### 4.1 Fuel-cell source + boost branch

```
Se:V_fc,oc ─┐                         ‹sig D_fc›  (droop: MDAC→OPA197 injects V_op)
            1₍fc,in₎ ── R:R_fc,int           │
            │ ‖ I:L_fc (2.2 µH)              ▼
            │ ‖ R:DCR_fc (4.65 mΩ + 2 mΩ INA shunt)
            │
           MTF : (1 − D_fc)        ← averaged boost conversion ratio
            │
            0₍fc,out₎ ── C:Cout_fc (3×22 µF ≈ 30 µF derated)
            │
           MR:SW_FC_BUS  ‹GPIO 27 FC_BUS_ENABLE›   (RT1987: Rds(on) | open)
            │
            └────────────────────────────►  0_VBUS
```

### 4.2 Battery source, boost branch, and battery terminal node

The battery terminal `0₍bat₎` is a hub: the boost discharges from it, the charger returns
into it (through `BT_SEQUENCE`), and the logic LDO taps it.

```
Se:V_bat,oc(SOC) ─┐
                  1₍bat,int₎ ── R:R_bat,int
                  │ ‖ C:Q_soc  (charge store ≈ pack capacity; slow state)
                  │
                  0₍bat₎  ───────────────────────────────────────────────╮
                  │              │                  │                     │
            MR:SW_BT_SEQ   R:R_logic(LDO)    [from charger:               │
            ‹GPIO 32›      (always-on)        charge current in]          │
                  │                                                       │
                  1₍bt,in₎ ── I:L_bt (2.2 µH) ── R:DCR_bt                 │
                  │                                              MR:BQ29200 OVP clamp
                 MTF : (1 − D_bt)   ‹sig D_bt›                  ‹GPIO 9 CBAL_DISABLE›
                  │
                  0₍bt,out₎ ── C:Cout_bt (≈30 µF)
                  │
                 MR:SW_BT_BUS  ‹GPIO 28 BT_BUS_ENABLE›
                  │
                  └────────────────────────────►  0_VBUS
```

### 4.3 VBUS node

```
        ┌──────────── 0_VBUS  (common effort = V_bus, ≈17.5 V nominal) ───────────┐
 (from FC_BUS) ──►│  ‖ C:C_bus (≈30–40 µF, RT1987 ceramics)                        │
 (from BT_BUS) ──►│                                                                │
                  │── MR:SW_MOT_PWR ‹GPIO 29› ──►  0_VMOT   (motor/regen path)     │
                  │── MR:SW_FC_CHARGE ‹GPIO 31› ─►  0_CHG   (FC→charger path)       │
        └─────────────────────────────────────────────────────────────────────────┘
```

### 4.4 Motor / VESC / drivetrain branch (bidirectional)

```
0_VMOT ── C:C_mot (470 µF bulk + ESR 80 mΩ)        ‹sig D_m  (VESC current cmd)›
  │                                                        │
 MTF : VESC(D_m)   ← averaged inverter, bidirectional (traction ⇄ regen)
  │
  1₍arm₎ ── R:R_a (winding)  ‖ I:L_a (winding L, often negligible)
  │
 GY : kₜ          ← motor constant (τ = kₜ·i ; e_bemf = kₜ·ω)   TODO(calibrate)
  │
  1₍ω₎ ── I:J_rotor  ‖ R:b_visc (bearing/viscous)
  │
 TF : N_gear        ← gearbox ratio                              TODO(calibrate)
  │
 TF : r_wheel       ← wheel radius (rotation→translation)        TODO(calibrate)
  │
  1₍v₎ ── I:m_veh  ‖ R:R_roll (rolling)  ‖ R:R_aero(v) (∝v², nonlinear)  ‖ Se:F_grade
```

> **Bench vs. vehicle load.** On the dyno the translation sub-graph (`TF:r_wheel` →
> `1₍v₎`) is replaced by a **flywheel**: `1₍ω₎ ── I:J_flywheel ‖ R:b`. The encoder
> (`ENC_A`/`ENC_B`) measures `ω` at this flywheel — that is the `v_actual` the motor PI
> closes on. Keep both load models; select by build target.

### 4.5 Regen node + braking chopper + charger (Ag105)

```
   (motor regen power, right→left through MTF:VESC) ──►  0_VMOT / 0_RGN
                                                          │
                          MR:CHOPPER  ‹hardware, NOT MCU› │   TL431 ref + BSP170P + R:47 Ω 20 W
                          (fast primary clamp to GND;     │   — voltage-triggered, dumps surplus to heat
                           absorbs the regen spike)       │
                                                          │
                          MR:SW_REGEN ‹GPIO 30 REGEN_ENABLE›
                                                          │
                                                          ▼
   (from VBUS via SW_FC_CHARGE) ─────────────────────►  0_CHG ── C:CAL (470 µF, ESR 80 mΩ)
                                                          │
                                          MTF : Ag105(D_chg)  ‹sig MPPT_DISABLE GPIO 5›
                                          (MPPT buck charger; slow perturb-&-observe)
                                                          │
                                                          ▼  charge current
                                                  back to 0₍bat₎ (via SW_BT_SEQ)
```

`SW_FC_CHARGE` and `SW_REGEN` (and `SW_BT_BUS`) are **mutually exclusive** by the sequencing
rules — only one charger source path is ever closed. That makes `0_CHG` a single-source node
at any instant (see §6).

---

## 5. Control = signal bonds (the MCU layer)

These carry **information, not power** (full-arrow activated bonds). They are what the
firmware reads and writes; in the state-space model they are the inputs/outputs.

**Sensed (plant → MCU):**

| Signal | Source element | Firmware use |
|--------|---------------|--------------|
| `i_fc`, `i_bt` | INA253A1 across boost outputs (0.1 V/A) | `powerBalance()` power-share PI |
| `V_fc`, `V_bt`, `V_bus`, `V_chg`, `V_rgn` | resistor-divider taps (ADC) | fault detection, telemetry |
| `ω` (`v_actual`) | quadrature encoder at flywheel | `motorControl()` speed PI |
| `I_charge`, GENSTAT | Ag105 I2C reg `0x06` / status byte | charge telemetry, readiness |

**Commanded (MCU → plant), i.e. the modulating signals on the `MTF`/`MR` elements:**

| Signal | Modulates | Element |
|--------|-----------|---------|
| `D_fc`, `D_bt` (droop gains `K_fc`/`K_bat`) | boost conversion ratio | `MTF:(1−D_fc)`, `MTF:(1−D_bt)` via AD5443 MDAC → OPA197 → regulator FB |
| `D_m` (VESC current command) | inverter ratio | `MTF:VESC` |
| `MPPT_DISABLE` (GPIO 5, active-LOW) | MPPT loop on/off | `MTF:Ag105` |
| 6× path-switch GPIOs (27–32) | open/close power paths | the six `MR:SW_*` |
| `CBAL_DISABLE` (GPIO 9) | OVP clamp enable | `MR:BQ29200` |

> The droop loop is **analog and fast** (INA253 → R_DROOP → OPA197 injects into the boost
> feedback node); the MCU only *trims* it by writing the MDAC gain. In bond-graph terms the
> inner droop dynamics live inside `MTF:(1−D)`; the MCU PI sets the modulus set-point. Model
> the droop as a fast inner loop and the power-share PI as the slow outer loop (two-time-scale
> separation) — this matches the SISO architecture in
> `references/DC Controller-SISO 2026-06-09.pdf`.

---

## 6. Switched bond graph ↔ firmware states

The six `MR:SW_*` switches mean this is a **hybrid (switched) bond graph**: causality and the
active topology change with the switch vector. Each firmware state is a distinct mode. Build
and analyze the causal graph **per mode** — `1` = path closed (low-R bond), `0` = open
(bond removed).

| Switch / boost | Init(0) | Idle(1) | Run-cruise(2) | Run-regen(2) | Finish(3) | Error(99) |
|----------------|:--:|:--:|:--:|:--:|:--:|:--:|
| FC boost (`MTF_fc`) | on¹ | on | on | on | on | off² |
| BT boost (`MTF_bt`) | on¹ | on | on | on | on | off² |
| `FC_BUS_ENABLE` (27) | on¹ | on | on | on | on | off |
| `BT_BUS_ENABLE` (28) | on¹ | on | on | **off** | on | off |
| `MOT_PWR_ENABLE` (29) | off | off | **on** | **on** | off | off |
| `REGEN_ENABLE` (30) | off | off | off | **on** | off | off |
| `FC_CHARGE_ENABLE` (31) | off | off | on³ | **off** | off | off |
| `BT_SEQUENCE_ENABLE` (32) | →on | on | on | on | on | off |

¹ Production bring-up: bus switches first, then boosts (gentle bus charge). Under `BENCH_TEST`
the whole power stage stays **off** in Init. ² Error tears the bus down (latched).
³ FC-charge opens on *intent* (`charge_goal>0`) to power the charger; MPPT release is gated on
readiness. **`FC_CHARGE` and `REGEN`/`BT_BUS` are never closed together** — that mutual
exclusion is what keeps `0_CHG` single-sourced and is enforced by `assertFcChargeEnable()`.

**Modeling implication:** the dangerous transitions are *mode changes*, not steady states —
e.g. closing `BT_BUS` onto a discharged `0_VBUS` while `MTF_bt` is already delivering current
is the open hardware fault (boost dies). A switched bond graph makes this explicit: the
`I:L_bt` inductor current is a **state that cannot jump**, so closing `SW_BT_BUS` forces an
instantaneous redistribution into `C_bus`/`C_mot` — the transient that the model must capture
(see [`boost-bringup-debug.md`](../boost-bringup-debug.md)).

---

## 7. Causality notes (how to assign before deriving equations)

1. **Sources `Se`** fix effort-out causality (FC/battery OCV, grade force).
2. **`I` elements prefer integral causality** — state = flow: inductor currents `i_L,fc`,
   `i_L,bt`, armature `i_a`, and the mechanical momenta `J·ω`, `m·v`. These are the
   **independent energy states**.
3. **`C` elements prefer integral causality** — state = effort: `V_Cout`, `V_bus`, `V_mot`,
   `V_CAL`, and the slow `Q_soc`.
4. **Switches change causality.** When an `MR:SW_*` opens, the inductor/segment it fed loses
   its prescribed-current partner → potential **causal conflict / derivative causality** on
   the adjacent `C`. This is the formal signature of the hot-plug hazard and of the
   disabled-boost back-feed: the model will *demand* an impulsive current unless a parasitic
   `R`/`C` is present to absorb it. Keep the small ceramic `C`s and switch `Rds(on)` in the
   model precisely so these transients stay finite.
5. **Two-time-scale:** the boost/droop electrical states (µs–ms) are far faster than the
   mechanical states (100s of ms–s). For control design, the inner electrical loop can be
   reduced to a quasi-static `MTF` (algebraic) while retaining the mechanical `I`s.

---

## 8. Element / parameter table (with sources)

Values pulled from the BOM, schematic, README/CLAUDE notes, and datasheets. `TODO(calibrate)`
follows the project convention for unmeasured values — do **not** treat those as final.

| Element | Symbol | Value | Source |
|---------|--------|-------|--------|
| FC source EMF | `Se:V_fc,oc` | ~12 V OC → 7.8 V @ 2.6 A (H-20 U-I curve) | High-Level PDF; `Ag105`/FC notes |
| FC internal R | `R_fc,int` | ≈ (12−7.8)/2.6 ≈ 1.6 Ω avg (nonlinear) | derived from U-I curve `TODO(calibrate)` |
| Battery EMF | `Se:V_bat,oc(SOC)` | 2S: 6.0 min / 7.4 avg / 8.4 max V | High-Level PDF; CLAUDE §3 |
| Battery internal R | `R_bat,int` | tens of mΩ | `TODO(calibrate)` |
| Battery charge store | `C:Q_soc` | = pack capacity (slow) | `TODO(calibrate)` |
| Boost inductor (×2) | `I:L_fc`,`I:L_bt` | **2.2 µH**, 15 A, DCR 4.65 mΩ | BOM "Regulator inductors" L-FC/L-BT (Eaton HCM1A1305V3-2R2) |
| Boost output cap (×2) | `C:Cout_fc`,`Cout_bt` | 3×22 µF = 66 µF nom (**≈30 µF DC-derated**) | BOM "Output capacitor" C4A/B/C |
| Boost input cap | `C:Cin` | 10 µF + 2.2 µF + 0.1 µF | BOM C1/C2/C3 |
| Current-sense shunt (×2) | `R` in `DCR` | INA253A1 **2 mΩ** internal shunt, **0.1 V/A** | INA253A1IPWR.pdf; CLAUDE §5 |
| VBUS cap | `C:C_bus` | **≈30–40 µF** ceramics | README; CLAUDE bring-up addendum |
| V-MOT / regen bulk cap | `C:C_mot` | **470 µF**, ESR 80 mΩ | BOM "Charging path capacitor" CAL (⚠ see §9 node-placement note) |
| Charger input cap | `C:CAL` | (same 470 µF — placement TBD) | BOM CAL |
| Path switches (×6) | `MR:SW_*` | RT1987, back-to-back FETs, CSS 5.6 nF → tON≈1.17 ms, OVP≈33 V | RT1987_DS-00.pdf; BOM D-FC…B-BSQ |
| Boost converter (×2) | `MTF:(1−D)` | TPS61288, 4.5–18 Vin, 15 A, HW OVP 19 V, abs-max SW/VOUT 20 V | TPS61288LRQQR.pdf; BOM BST-FC/BT |
| Brake chopper | `MR:CHOPPER` + `R:47 Ω` | TL431 + BSP170P + 47 Ω 20 W; **not firmware-controlled** | BOM R-SHUNT/Q-SNT/U-SNT |
| Charger | `MTF:Ag105` | MPPT, 2S/8.4 V, 2.5 A max, I_chg 0.011 A/count | AG105_Silvertel.pdf; Ag105 Table 7 |
| Cell OVP | `MR:BQ29200` | OVP-only clamp, `CB_EN` hardwired GND | BQ29200_TI.pdf; CLAUDE §4 |
| Logic LDO load | `R:R_logic` | LM1084-5.0, always-on (Teensy + PHY ≈150–250 mA) | LM1084ISX-5p0.pdf; README |
| Motor constant | `GY:kₜ` | `motorConstant` | `TODO(calibrate)` |
| Rotor inertia | `I:J_rotor` | — | `TODO(calibrate)` |
| Gear ratio / wheel r | `TF:N_gear`,`TF:r_wheel` | — | `TODO(calibrate)` |
| Vehicle mass / flywheel | `I:m_veh` / `I:J_flywheel` | — | `TODO(calibrate)` (encoder cpr→speed also unset) |
| Road load | `R:R_roll`,`R:R_aero` | rolling + aero(∝v²) | `TODO(calibrate)` |

---

## 9. Modeling assumptions, open questions, and next steps

**Assumptions baked into this graph:**

1. **Averaged converters.** Each boost (and the VESC inverter and the Ag105) is an averaged
   `MTF` — switching ripple is not modeled. Good for control/energy timescales; for the
   destructive-transient analysis (§6) you must add the switch-level detail (inductor current
   continuity, OVP clamp, parasitic `C`).
2. **Unipolar, 0-referenced INA253** (REF tied to GND): sensed boost current ≥ 0, so the
   forward-only `R` sensing is correct; regen/charge currents flow in the *separate* path and
   are not seen by these sensors. Matches CLAUDE §5.
3. **Single charger source at a time** — enforced by the switch mutual exclusion (§6), so
   `0_CHG` never has two driving branches.
4. **Brake chopper is autonomous** — a voltage-triggered `MR` outside the MCU loop; the
   firmware's `MPPT_DISABLE` strategy assumes the chopper, not the Ag105, catches the fast
   regen spike (CLAUDE §3).

**Open questions to resolve before trusting the model:**

- ⚠ **Where does the 470 µF actually sit?** The BOM labels `CAL` as a *"charging path
  capacitor"* (Battery Charger group), but the bench-debug notes place the 470 µF bulk on the
  **V-MOT / regen node behind `MOT_PWR_ENABLE`**. The graph currently shows `C_mot` there and
  flags `CAL` at `0_CHG`. **These may be the same single cap or two different ones** — confirm
  against the schematic net before assigning the dominant `C`. This directly changes which
  node has the slow pole and where inrush energy lives.
- **FC source curve** — fit `Se:V_fc,oc` + `R_fc,int` (likely nonlinear) to the actual H-20
  U-I data rather than the 1.6 Ω average used above.
- **Battery model fidelity** — is a Thevenin (`Se`+`R`+`C`) enough, or do we need a 2-RC
  (diffusion) model for the regen-charge transients?
- **VESC averaging** — the VESC runs its own fast current loop; decide whether to model it as
  an ideal `MTF` (commanded current = actual) or include its bandwidth as a 1st-order lag.
- **Motor electrical vs. mechanical dominance** — is `I:L_a` (armature inductance) negligible
  vs. the mechanical states? If so, drop it and the motor reduces to `GY:kₜ` + `R_a`.

**Suggested next steps (in modeling order):**

1. Pin down the §9 open questions (esp. the 470 µF placement) from the schematic netlist.
2. Assign causality per **Run-cruise** and **Run-regen** modes (§6) — those are the two we
   most want to simulate — and read off the state-space `A,B` for each.
3. Reduce with the two-time-scale split (§7.5): a quasi-static electrical `MTF` cascade
   feeding the mechanical `I`s, for a control-design plant matching the SISO diagram.
4. Add the switch-level transient model **only** for the bring-up/back-feed hazard study
   (§6), keeping parasitic `C` + `Rds(on)` so the impulses stay finite.
5. Calibrate the `TODO(calibrate)` parameters on the bench (drivetrain constants, source
   curves) and validate against a logged drive cycle (State 98 `D` command telemetry).

---

*Generated as a modeling starting point — no firmware or existing files were modified.
Cross-check every `TODO(calibrate)` and the §9 open questions against the schematic before
relying on the model.*

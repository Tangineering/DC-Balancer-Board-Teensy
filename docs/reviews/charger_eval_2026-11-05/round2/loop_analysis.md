# Loop and runaway state analysis: always-powered replacement charger (Path A, board rev 20260622)

Round 2, 2026-11-05. This analysis does not depend on a specific IC. It covers the "always-powered" design that the operator accepted on
2026-11-05 (rulings 1-5). REGEN (D-BC-RG, pin 30) stays closed through Run. The charger's input-voltage regulation threshold
sits between the bus maximum and the regen clamp. The threshold moves below the bus for FC charging. Independent backstops
are layered on top.

Scratch only. Calculator: `.../charger_eval/r2/comp_calc.py`. WDT_T4 source fetched to `.../charger_eval/r2/wdt/`.

## 0. Verdict

1. **The charger threshold alone cannot be the interlock.** Every primary-read TI NVDC charger sets its input-voltage
   threshold at POR from the voltage it sees, minus an offset:
   - BQ25713: "VBUS at no load - 1.28 V" (SLUSD83C §9.3.3.2, PDF p.25).
   - BQ25720: same (SLUSDU3, PDF p.28).
   - BQ25798: VBUS0 - 1.4 V (SLUSDV2C §7.3.4.4, PDF p.27).
   - BQ25773: default register value 3.2 V (SLUSEK7, PDF p.39).

   An always-powered charger re-boots on V-MOT at bus level after every brown-out, mode change or input glitch. Its threshold
   then lands about 1.3-1.4 V BELOW the bus, or at 3.2 V. The VINDPM/MPPT/UVCL setting is a **soft layer**. It is valid only
   after the host has written it and read it back in the current power cycle.
2. **One hardware comparator makes the regen-path loop physically impossible.** It compares V-MOT against VBUS, which means
   it measures directly across D-MT-EN. The loop needs D-MT-EN to conduct, which needs V-MOT < VBUS (RT1987 DS-00 §17.6,
   PDF p.16). Gate the charger's hard inhibit with "V-MOT > k x VBUS", k = 1.067, about 0.75 V of worst-case guard. Then
   the charger can only convert while the bus *cannot* feed V-MOT. This holds whatever the threshold register holds, whatever
   the firmware does, and whether the MCU runs, hangs or resets.
3. **The FC-charge window needs its own hardware permit, and that permit must be physical.** Proposed:
   FC_CHARGE net HIGH AND BT_BUS net LOW AND REGEN net LOW AND measured BT-boost current < about 0.2 A (INA253 output on
   the pin-41 net). The bus in that window is FC-only, so a pack -> bus path needs D-BT-EN to conduct. The current term
   catches a shorted D-BT-EN or a mis-read EN net. Today the FC window is protected only by `assertFcChargeEnable()` and by
   `FAULT_SWITCH_CONFLICT`. **That fault check is compiled out in BENCH_TEST builds** (`#if !BENCH_TEST`,
   `teensy_controller.ino` ~7413), and the bench currently runs BENCH_TEST 1.
4. **Runaway is a charger property, and the board can bound it.** The circular loop can only run while the charger converts.
   The charge current is bounded only by the charger's own sense. Required:
   - a high-side or input-side sense (R-GND, spec.md §0.3);
   - a **hardware** current ceiling (ILIM/sense resistor), not a register default (BQ25713 input-limit default 3.25 A,
     §9.3.3.2, PDF p.25);
   - a POR default of no charging.

   Under those conditions:
   - In regen mode, charge power is self-limiting. Pulling V-MOT down trips the comparator.
   - In FC mode, `OC_FC` (1.4 A bus-side, single sample, fw `LIMIT_I_FC_MAX`) bounds it.
5. **Minimal set that makes the loop impossible (§8):**
   - H1, the V-MOT/VBUS comparator.
   - H2, the physical FC-window permit.
   - H3, an inhibit stage biased from the charger's own regulator, so a dead 3.3 V logic supply reads as "inhibit".
   - C1-C4, the charger-intrinsic requirements: a hard-inhibit pin, a high-side sense with a hardware ceiling, a POR default
     of no charge, and no autonomous restart from NV settings.

   On top of these: a firmware sequencer and monitor (F1-F3), the ported `J` guards G1-G3 with the trip latch, and the
   **Teensy RTWDOG hardware watchdog, recorded as REQUIRED FUTURE WORK (§10)**. The firmware and watchdog layers do not
   carry the loop proof. They carry overcharge, stale-state and detection duties.
6. **One timing requirement remains, and it is not a probability argument.** After H1 trips, the charger's input current
   must stop within **about 290 µs** (worst case: 1.5 A input, 0.4 mF on V-MOT; §4.3). Otherwise D-MT-EN carries bus
   current for the remainder. Even then the event is a single bounded pulse. The hysteresis cannot be re-crossed by bus
   energy, so it cannot sustain. The charger's inhibit-to-input-current-zero latency is not in any datasheet read. It is a
   bench gate (§11, M2).

## 1. Sources

| Tag | Document (all read this round from `.../charger_eval/datasheets/` unless noted) |
|---|---|
| [RT] | Richtek RT1987 DS-00, Sep 2024: EC table PDF p.7; §17.1-17.7 PDF p.14-16 |
| [TPS] | TI TPS61288 SLVSFP3C: VREF 0.588/0.600/0.612 V and VOVP 18.3/19/19.5 V, hysteresis 600 mV (PDF p.6); §8.3.4 (PDF p.11) |
| [TLV] | TI TLV3011/TLV3012/TLV301xB SBOS300C, Apr 2023: EC B-version (PDF p.8-9); switching (PDF p.10); §9.4.4-9.4.5 fail-safe and POR (PDF p.22) |
| [713] | TI BQ25713 SLUSD83C: VINDPM range and accuracy (PDF p.12); ACOV (PDF p.15); ILIM_HIZ thresholds (PDF p.18); watchdog (PDF p.19, §9.3.10.1 PDF p.30); §9.3.3.2/§9.3.3.4 (PDF p.25); ChargeCurrent POR 0 A (PDF p.56) |
| [720] | TI BQ25720 SLUSDU3: VINDPM range and accuracy (PDF p.11); default VINDPM (PDF p.28) |
| [773] | TI BQ25773 SLUSEK7: VINDPM accuracy +/-1 % at 18.000 V (PDF p.12); default 3.2 V (PDF p.39) |
| [798] | TI BQ25798 SLUSDV2C: VINDPM range 3.6-22 V and accuracy +/-2 % at 18.6 V (PDF p.12); default VINDPM (PDF p.27); default charge current 1 A (revision history, PDF p.142-143) |
| [650] | TI BQ24650 SLUSA75B: MPPSET +/-0.6 %; MPPSET < 75 mV disables charge (PDF p.4, p.7) |
| [756] | TI BQ25756 SLUSEN5A: VAC_DPM accuracy +/-2 % (PDF p.10) |
| [BQ29] | TI bq29200 SLUSA52C: OUT goes low -> high at timer expiry (PDF p.8) |
| [WDT] | tonton81/WDT_T4 `Watchdog_t4.tpp` and `.h` (GitHub master, fetched 2026-11-05) |
| [SCH] | `references/Scale_Car_Board_20260624.sch`, parsed: nets VBUS, V-MOT, VBT, VCHG-IN, VCHG, RGN-V, BUS-V, VBUS-BT |
| [BOM] | `references/Scale Car Design PCB BOM 20260622.csv`: RD1 +/-0.1 % (as designed, 237 k), TL431BIDBZR +/-0.5 %, R1-SNT 78.7 k +/-0.1 %, CAL EEE-FN1V471UP 470 µF/35 V |
| [FW] | `teensy_controller/teensy_controller.ino` at tree tip (fw v37 rev 2), located by grep |
| [SPEC] | round-1 `docs/reviews/charger_eval_2026-11-05/spec.md` |
| [P37] | `docs/fw37_planning_2026-11-04.md` §3.2 (regen burst profile) |

"typ only" = the datasheet gives a typical value with no min or max. Such a value is never used as a guarantee below.

## 2. Topology: every directional element between the energy stores

Net membership from [SCH]:

| Element | Pins | Conducts | Blocks | Basis |
|---|---|---|---|---|
| FC boost REG-FC + SNS-FC + **D-FC-EN** (RT1987, EN pin 27 FC_BUS) | VFC -> VOUT-FC -> VBUS-FC -> VBUS | FC -> VBUS when EN high and VBUS-FC > VBUS | VBUS -> FC always (ideal diode); both ways when EN low | [RT] §17.6 p.16; "completely isolates VIN and VOUT when disabled", §17 p.14 |
| BT boost REG-BT + SNS-BT + **D-BT-EN** (EN pin 28 BT_BUS) | VBT -> VOUT-BT -> VBUS-BT -> VBUS | pack -> VBUS when EN high. With REG-BT disabled, the TPS61288 body-diode passthrough still gives VOUT-BT ~ VBT - Vd, so the pack can feed VBUS whenever VBUS < ~VBT | VBUS -> BT boost; both ways when EN low | [RT]; CLAUDE.md §2 passthrough hazard |
| **D-MT-EN** (EN pin 29 MOT_PWR) | VBUS -> V-MOT | bus -> motor node only when VBUS > V-MOT (regulates VIN - VOUT = 35 mV typ only) | **V-MOT -> VBUS always**. This is why regen never back-feeds the boosts | [RT] §17.6 p.16 |
| **D-BC-RG** (EN pin 30 REGEN) | V-MOT -> VCHG-IN | V-MOT -> charger input | VCHG-IN -> V-MOT | [RT] |
| **D-BC-FC** (EN pin 31 FC_CHARGE) | VBUS -> VCHG-IN | VBUS -> charger input | VCHG-IN -> VBUS | [RT] |
| Charger | VCHG-IN -> VCHG | input -> output when converting (VIN-/VBAT- = GND) | IC-dependent | - |
| **D-BT-SQ** (EN pin 32 BT_SEQ) | VCHG -> VBT | charger -> pack | pack -> VCHG (TRCB, no fault flag; auto-restart without soft-start) | [RT] §17.4 Table 1 p.15 |
| LM1084 -> 5 V -> Teensy 3V3 | VBT -> 5 V | pack -> logic | - | [SCH] REG-5V INPUT on VBT |
| TL431/BSP170P chopper, R-SHUNT 47 Ω | V-MOT -> GND | above about 21.4 V true (design 22.13 V) | - | [SCH] RGN-V = TL431 REF; [SPEC] §2.1 B |

Consequences that the proofs below rely on:

- **VCHG-IN is a sink-only node.** D-BC-RG and D-BC-FC both block reverse current, so the charger can never source into
  V-MOT or VBUS while both RT1987s are healthy.
- **The pack can reach VBUS only through D-BT-EN.** Bus energy can reach the charger only through D-BC-FC, or through
  D-MT-EN followed by D-BC-RG.
- Motor energy can reach the charger only through D-BC-RG. It can never reach VBUS (D-MT-EN blocks V-MOT -> VBUS).

## 3. Definitions: what is forbidden

**Loop L-R (regen path):** pack -> BT boost -> D-BT-EN -> VBUS -> **D-MT-EN** -> V-MOT -> D-BC-RG -> charger -> D-BT-SQ -> pack.
Necessary conditions, all at once:
- BT_BUS = 1 (or D-BT-EN shorted);
- MOT_PWR = 1 (or D-MT-EN shorted);
- REGEN = 1;
- BT_SEQ = 1;
- **D-MT-EN conducting, which needs V-MOT < VBUS;**
- the charger converting.

**Loop L-F (FC path):** pack -> BT boost -> D-BT-EN -> VBUS -> **D-BC-FC** -> charger -> D-BT-SQ -> pack.
Necessary conditions:
- BT_BUS = 1 (or D-BT-EN shorted);
- FC_CHARGE = 1;
- BT_SEQ = 1;
- the charger converting with VIN above its threshold.

**Runaway:** charge current above the configured ceiling. Necessary conditions: the charger's current sense is bypassed or
mis-scaled, or no hardware ceiling exists and a register asks for more, or the charger IC has failed. The 2026-11-04
incident was this case: the Ag105's Bat- sense was paralleled by the board GND (spec.md §0.3).

Bus-fed charging *without* the pack in the loop (FC window, BT_BUS = 0) is the intended FC-charge mode. It is not a loop.

## 4. Analysis item 1: regen mode with BT_BUS closed (normal Run)

### 4.1 Is the charger's input energy guaranteed to come only from the motor?

Yes, if and only if the charger converts only while V-MOT > VBUS:

- D-MT-EN conducts bus -> V-MOT only while VBUS - V-MOT exceeds its forward regulation point. That point is 35 mV typ only
  ([RT] p.7, §17.6 p.16), with no min.
- Conservatively, take conduction onset at V-MOT = VBUS (0 mV).
- While V-MOT > VBUS, D-MT-EN is reverse-biased. The ideal-diode gate drive is forced off, and the fast reverse comparator
  trips at VIN - VOUT < -50 mV typ within 0.5 µs typ ([RT] p.7, p.16).
- The bus therefore delivers no charge to V-MOT, so all energy drawn from V-MOT comes from the VESC (regen).
- One exception: a one-shot capacitor residue, if VBUS was higher earlier and later fell. Example: a 17.2 V bus park
  followed by a return to 15.9 V leaves CAL at 17.2 V. That is at most 1/2 x 470 µF x (17.2² - 16.8²) ≈ 3 mJ above the
  comparator trip. It cannot be replenished without a new bus excursion, so it is not a loop.

### 4.2 Can VINDPM pull V-MOT down to VBUS when regen current < charge current?

**In steady state, no.** An input-voltage regulation loop reduces input current to hold VIN at the threshold
([650] §8.3.2: "stays in the input voltage regulation loop while the output current is zero"). If regen supplies less than
the charger wants, V-MOT settles AT the threshold and does not fall through it. The required ordering is:

```
VBUS_max  <  H1 falling trip (worst min)  <  H1 rising trip (worst max)  <  VINDPM_min  <  VINDPM_max  <  clamp_min
```

Quantified (`comp_calc.py`):

| Quantity | Value | Basis |
|---|---|---|
| VBUS no-load setpoint | 15.91 V (measured 15.9 V) | fw `V_BUS_NOMINAL` comment, RD1 bodge 215 k |
| VBUS steady-state worst max | **16.23 V** (VREF +2 %); **16.39 V** if the bodged 215 k RD1 is a 1 % part | [TPS] VREF 0.612/0.600 (p.6); bodge resistor tolerance TODO(verify) |
| VBUS transient (load-dump park) | 17.0-17.2 V, decaying, ≤ about 5 ms above 17.0 V | fw comment at `LIMIT_V_BUS_MAX` (2026-08-03 capture metrology). **Regen onset is itself a bus load dump**: the Run-time overshoot is unmeasured (M4) |
| Firmware OV latch | 17.5 V, 10 ms persistence | fw `LIMIT_V_BUS_MAX`, `OV_BUS_PERSIST_MS` |
| TPS61288 HW OVP | 18.3 / 19 / 19.5 V, 600 mV hysteresis | [TPS] p.6 |
| Chopper clamp | design 22.13 V (21.98-22.28 V from TL431B +/-0.5 % and 0.1 % R1-SNT); **measured 21.4 V true** (uncalibrated 0.85x ADC) | [BOM]; [SPEC] §2.1 B |
| VINDPM setpoint proposed (regen) | **19.0 V** | this analysis |
| VINDPM accuracy at about 19 V | BQ25713/BQ25720 -3 %/+2 % (18.688 V row) -> 18.43-19.38 V; BQ25773 +/-1 % (18.000 V row) -> 18.81-19.19 V; BQ25798 +/-2 % (18.6 V row) -> 18.62-19.38 V; BQ24650 MPPSET +/-0.6 % plus divider -> about 18.85-19.15 V; BQ25756 +/-2 % | [713] p.12, [720] p.11, [773] p.12, [798] p.12, [650] p.7, [756] p.10 |
| VINDPM range ceiling | BQ25713/BQ25720 **19.52 V max**; BQ25798 22 V | [713] p.12, [720] p.11, [798] p.12. A threshold above the TPS61288 OVP max (19.5 V) is therefore **not available** on BQ25713/BQ25720 |
| H1 trip at VBUS 15.9 V (0.1 % resistors, Vos +/-9 mV, internal hysteresis 2-8 mV) | rise 17.13 V (max 17.29 V), fall 16.82 V (min **16.66 V**, guard 0.76 V) | §9 circuit |
| H1 trip at VBUS 16.39 V | rise max 17.83 V, fall min 17.19 V (guard 0.79 V) | same |
| H1 trip at VBUS 17.2 V | rise max 18.70 V, fall min 18.05 V | same |

Margins with the BQ25713 worst case (the widest of the candidates):

| Margin | Value | Result |
|---|---|---|
| VINDPM_min 18.43 V vs VBUS steady max 16.39 V | 2.04 V | pass |
| vs the transient park 17.2 V | 1.23 V | pass |
| vs the firmware OV latch 17.5 V | 0.93 V | pass |
| vs the TPS61288 OVP min 18.3 V | **0.13 V** | VINDPM alone does not cover a failed-FB boost (§7). H1 does |
| H1 rise max 17.83 V vs VINDPM_min 18.43 V (steady bus) | 0.60 V | Absorption never chatters the comparator |
| During a 17.2 V bus park, H1 rise max 18.70 V vs VINDPM_min 18.43 V | can exceed it | A burst that *starts* inside a park may be withheld until the park decays (≤ 5 ms). Safe direction. An absorption already running continues (fall min 18.05 V < 18.43 V) |
| VINDPM_max 19.38 V vs clamp 21.4 V | 2.0 V | pass. BQ25713 ACOV (25-27 V rising, [713] p.15) does not stop the charger at the clamp |
| D-BC-RG and trace drop | 35 mV typ + I x (20 mΩ + about 35 mΩ) | VINDPM is sensed at VCHG-IN, so V-MOT sits *above* VINDPM by this drop. Favourable, ignored |
| Ripple | V-MOT ripple (VESC PWM through CAL) unmeasured | H1 has 0.30 V of designed hysteresis and a 24 µs RC filter. Scope V-MOT (M4) |

### 4.3 The transient case: regen stops faster than the VINDPM loop responds

> **Superseded in part (critic round, 2026-11-05):** the table below uses an H1 fall trip of 17.0 V from an earlier divider
> design. With the final dividers the worst-case fall trip is 16.62 V at a 15.9 V bus and 17.15 V at 16.39 V, D-MT-EN conducts
> at VBUS - 35 mV, and the divider lag, comparator and gate RC come off the budget: the charger allowance is 117-194 µs, not
> 290-340 µs. See `calc/comp_calc.py` (critic-fix block) and the study section 2.5. Also, the INA253 zero-current output (line ~377 and
> §11 TODO) is now read: Swing to GND up to 10 mV = 0.1 A (SLOS954A §7.5), so a firmware trip near 50 mA is not achievable;
> see study section 2.3.

When the VESC current steps to zero (VESC fault, `setCurrent(0)`, State 99), the charger keeps drawing its input current
for the VINDPM loop's response time. V-MOT falls at I_in / C_VMOT:
- C_VMOT ≥ about 0.4 mF (CAL 470 µF -20 % plus C-D6/C-D7 plus VCHG-IN 20 µF; VESC input capacitance not counted, M5).
- At I_in = 1.5 A that is 3.75 V/ms.
- VINDPM loop bandwidth is not specified in any TI datasheet read (TODO(verify) per IC; M2).

| I_in | VINDPM_min 18.43 -> H1 fall 17.0 V | H1 fall 17.0 -> VBUS 15.9 V |
|---|---|---|
| 0.5 A | 1144 µs | 880 µs |
| 1.0 A | 572 µs | 440 µs |
| 1.5 A | 381 µs | **293 µs** |

**Requirement:** H1 propagation (TLV3012B 4 µs max, [TLV] p.10) plus logic (ns) plus **charger inhibit-to-input-current-off
latency ≤ about 290 µs** at a 1.5 A input limit, scaling as 1/I_in. If the charger is slower:
- D-MT-EN conducts bus current into the charger for the excess time only.
- After the inhibit takes effect, V-MOT cannot climb back above the H1 rising trip on bus energy (D-MT-EN only delivers up
  to VBUS).
- So the overshoot is a single bounded pulse, worst case I_in x (t_inh - 0.29 ms), per regen event. It is never a
  sustained loop.

A lower input-current limit in regen mode widens the budget proportionally. The burst average is about 0.2 A into the pack
([P37] §3.2).

## 5. Analysis item 2: the FC-charge window (BT_BUS off)

- Switch vector: FC_REG 1, BT_REG 1, FC_BUS 1, **BT_BUS 0**, MOT_PWR 1, **REGEN 0**, FC_CHARGE 1, BT_SEQ 1. REGEN 0 is a CSV
  rule (row 31) and is enforced by `assertFcChargeEnable()` ([FW] 12743).
- VBUS is FC-only. With D-BT-EN disabled it isolates both ways ([RT] p.14). The pack can feed VBUS only if D-BT-EN
  conducts. **L-F is impossible while D-BT-EN is truly off.** L-R is also impossible: REGEN 0, and the bus is FC-only anyway.
- The charger threshold is moved below the bus, about 13.5 V ([SPEC] §4, window 13.0-14.0 V, above `LIMIT_V_BUS_MIN`
  12.0 V). The charger therefore draws from the FC by design. **Nothing in the charger prevents L-F if BT_BUS closes.**
  The only barrier is the switch state.
- Today that barrier is firmware only:
  - the `assertFcChargeEnable()` ordering;
  - the State 98 `'2'` refusal ([FW] ~8659);
  - the `FAULT_SWITCH_CONFLICT` check ([FW] ~7413), **compiled out under BENCH_TEST** (`#if !BENCH_TEST`). The bench
    currently runs BENCH_TEST 1 (CLAUDE.md 2026-11-04 addendum).
- That check reads the commanded pin levels with `digitalRead`, not the RT1987 state, so a shorted D-BT-EN is invisible to
  it.
- **Hardware permit H2 (§8):** the charger may convert through the FC path only while all four hold: FC_CHARGE net HIGH,
  BT_BUS net LOW, REGEN net LOW, and **measured BT-boost forward current < I_th ≈ 0.2 A**. The current term is an INA253
  pin-41 net comparator. It is the physical proof that the pack is not feeding the bus. It covers a shorted D-BT-EN, a BT_BUS
  net sitting in the band between the RT1987's VEN_F min 0.6 V and a logic gate's VIL, and the TPS61288 passthrough case
  (REG-BT disabled, VBUS < VBT - Vd; passthrough current also flows through SNS-BT, [SCH] VOUT-BT -> SNS-BT -> VBUS-BT).
- **Timing margin built into the RT1987:**
  - If firmware raises BT_BUS while FC_CHARGE is HIGH, H2 drops the permit within gate delays. D-BT-EN cannot conduct for
    tD_ON = 8 ms typ ([RT] p.7), so the charger is inhibited before the pack connects.
  - In the other direction (BT_BUS falling, then FC_CHARGE rising), D-BC-FC itself waits tD_ON 8 ms before VCHG-IN sees the
    bus.
  - The RT1987 **turn-off** delay after EN low is not specified in DS-00 (§6). Firmware today waits 100 µs and calls it
    "confirmed sufficient" ([FW] 12772). Measure it (M3). The H2 current term makes it non-critical.
- Runaway in FC mode: bounded by the charger's hardware input ceiling (≤ 1.0 A, [SPEC] §2.1 A) and backstopped by `OC_FC`
  (1.4 A bus-side single sample -> State 99, which opens FC_CHARGE).

## 6. Analysis item 3: transitions between regen mode and FC mode

Invariants:

- **(I-1)** The charger's hard inhibit (pin 5, P5) is LOW across every switch change. P5 is a static "mode armed and
  verified" line, not a per-burst control. H1/H2 provide the dynamic gating.
- **(I-2)** A low (FC) threshold is written only while REGEN = 0 and BT_BUS = 0 and FC_CHARGE = 1. A high (regen) threshold
  is written before FC_CHARGE drops, while the charger is still powered from the FC path.
- **(I-3)** P5 rises only after a readback of every safety register (threshold, input limit, charge current, CV, cell count)
  in the **current power cycle of the charger**. Any input-path change counts as a possible POR (§0.1).
- **(I-4)** No mode transition starts while H1 = 1 or V_rgn > V_bus + margin (a burst in progress). Defer it.

**Regen mode -> FC window**

| # | Action | Why |
|---|---|---|
| 1 | P5 LOW; wait ≥ the charger inhibit latency (M2); check H1 readback = 0 | Charger hard-off before any path change |
| 2 | REGEN LOW | CSV row 31. The charger input decays and may POR, which is acceptable because P5 is LOW |
| 3 | BT_BUS LOW (existing S2 order: restore FC to the bus first if the share loop has it cut) | Removes the pack from the bus |
| 4 | Wait ≥ the RT1987 turn-off time (M3; 100 µs today) | DS-00 gives no turn-off figure |
| 5 | FC_CHARGE HIGH; tD_ON 8 ms + ramp about 1.3 ms ([SPEC] §6) | The charger boots on the FC-only bus |
| 6 | After I2C ACK: write the FC config (threshold 13.5 V, input limit ≤ 1.0 A, charge current), read all back | (I-2), (I-3) |
| 7 | P5 HIGH; hardware H2 grants the permit | Charging starts |

If the charger did not POR during steps 2-5, it still holds the regen threshold (19 V) and stays idle at the 15.8 V bus until
step 6. That is harmless.

**FC window -> regen mode**

| # | Action | Why |
|---|---|---|
| 1 | P5 LOW | (I-1) |
| 2 | Write the regen threshold (19.0 V) and read it back while still FC-powered. On an I2C failure: continue with P5 LOW, and the charger stays inhibited | (I-2) |
| 3 | FC_CHARGE LOW | - |
| 4 | BT_BUS HIGH (share-loop re-entry and hot-plug guards) | Restores two-source operation |
| 5 | REGEN HIGH. The charger boots on V-MOT ≈ VBUS. **POR defaults put the threshold BELOW the bus**, but P5 = 0 and H1 = 0 | This is the reason for H1 |
| 6 | After ACK: read back. If POR defaults are detected, rewrite the regen config and read back | (I-3) |
| 7 | P5 HIGH (regen armed). The charger stays inhibited by H1 until V-MOT > k x VBUS | - |

**Run entry** (from Idle, MOT_PWR already 1): the same steps 5-7.
- The REGEN close hot-plugs VCHG-IN from V-MOT at about 12 V/ms ([SPEC] §6).
- Inrush ≈ C_in x 12 mA/µF comes from CAL, which D-MT-EN then replenishes from the bus.
- It must stay inside the `OC_FC` budget ([SPEC] §6 item 2: ≤ about 50 µF effective on VCHG-IN).

**Run exit / State 3:** P5 LOW, then REGEN LOW.

**Do not:**
- REGEN HIGH with FC_CHARGE HIGH (CSV).
- Write a sub-bus threshold while REGEN = 1. H1 still covers this, but it would remove a layer.
- Leave REGEN HIGH while MOT_PWR opens. The charger would drain V-MOT, and the next MOT_PWR close would be a Death-5
  hot-plug ([SPEC]/round-1 §1.3). With P5 LOW and H1 = 0 the charger no longer drains V-MOT, so this hazard also shrinks.

## 7. Analysis item 4: a failed-FB boost driving VBUS to 18.3-19.5 V

- A boost with a lost FB regulates to its OVP. It stops switching at VOVP (18.3/19/19.5 V) until VOUT drops 600 mV, which
  gives a sawtooth between about 17.7 V and 19.5 V worst case ([TPS] p.6, §8.3.4 p.11).
- The VINDPM layer fails here. The threshold is absolute, 19.0 V +/-3 % (18.43-19.38 V), so a bus at up to 19.5 V can sit
  above it. **If the failed boost is the BT boost, that is exactly L-R powered by the pack.**
- H1 holds. It is relative: at VBUS 19.5 V the falling trip is ≥ 20.52 V (guard 1.02 V), and V-MOT ≈ VBUS - 35 mV, so H1
  reads 0 and the charger is inhibited.
- Firmware: `OV_BUS` latches at 17.5 V after 10 ms, and State 99 opens REGEN/FC_CHARGE. That happens later than H1.
- A failed FC boost in the FC window: the bus is FC-only and BT is out (H2), so the charger only sees a higher input. It
  must tolerate ≥ 19.5 V; [SPEC] §2.2 requires ≥ 23 V operating. `OV_BUS` latches.
- Harvest during a high bus: the H1 rising trip moves above the clamp at VBUS ≥ about 19.6 V, so regen goes to the chopper.
  Safe.

## 8. Minimal backstop set and the impossibility argument

| ID | Element | Function | Fail-safe state | Covers |
|---|---|---|---|---|
| **H1** | Comparator A (TLV3012B): V-MOT x 1/9.879 vs VBUS x 0.10804, i.e. permit while V-MOT > 1.067 x VBUS + 0.30 V hysteresis | Physical proof that D-MT-EN cannot conduct | Output LOW (= inhibit) during POR (TLV3012B push-pull "will be low (sinking)" for up to 1.9 ms, [TLV] §9.4.5 p.22) and when unpowered; fail-safe inputs to 5.5 V with V+ = 0 ([TLV] §9.4.4) | L-R (all causes, including bad or POR thresholds and firmware bugs) |
| **H2** | FC permit: FCC ∧ ¬BTB ∧ ¬RGN ∧ ¬BT_ACTIVE; BT_ACTIVE = comparator B (TLV3012B) on the INA253 BT output > about 20 mV (0.2 A at 0.1 V/A) | Physical proof that the pack is not feeding the bus | Inputs from EN nets with 10 k pull-downs (LOW = not FC mode) | L-F (including D-BT-EN short, EN mis-read, passthrough) |
| **H3** | PERMIT = P5 ∧ (H1 ∨ H2) into the charger's hard-inhibit input, through a stage biased from the **charger's own regulator** (REGN/VDDA) so absent logic = inhibit | Makes "logic dead, charger alive" impossible to read as permit | Charger self-inhibits | 3V3 loss, logic failure modes |
| **C1** | Charger hard-inhibit pin (converter off / Hi-Z / charge-disable), not only a register bit. Examples: BQ257xx ILIM_HIZ < 0.4 V = Hi-Z ([713] p.18, §9.3.3.4 p.25); BQ24650 MPPSET < 75 mV disables charge ([650] p.4, p.7). Register-only inhibits (CHRG_INHIBIT) do not qualify: they need I2C | H3 needs a pin | - | I2C failure |
| **C2** | High-side or input-side current sense, input-return = battery-return (R-GND); **hardware** input and charge ceilings (ILIM/sense resistor). The register defaults are unsafe as ceilings: BQ25713 input limit 3.25 A ([713] §9.3.3.2); BQ25798 default charge current 1 A | No runaway | - | Runaway |
| **C3** | POR default = no charge until the host enables: hard-inhibit pin default plus a 0 A charge-current reset default (BQ25713 ChargeCurrent POR 0 A, [713] p.56; BQ25798 does NOT meet this alone, 1 A default) | Defence in depth beside H3 | - | POR on every input glitch |
| **C4** | No autonomous restart from NV settings (the Ag105 failure mode, [SPEC] §3.1) | - | - | - |
| **F1** | Firmware monitor at 1 kHz: read back H1 and PERMIT on two spare pins; cross-check H1 against the calibrated ADC prediction (V_rgn vs V_bus; **V_rgn reads 0.85x and must be calibrated first**); in cruise H1 must read 0; a mismatch for > 5 ms sets the trip latch | Detects H1 stuck-high (divider open, comparator fault) | Trip latch: P5 LOW, REGEN LOW, FC_CHARGE LOW | Single faults in H1 |
| **F2** | §6 transition sequencer with invariants I-1 to I-4; `FAULT_SWITCH_CONFLICT` enabled in **all** builds; State 98 `'M'`/pin-5 toggles routed through the same verified-config gate | Keeps the soft layer valid | - | Config and ordering errors |
| **F3** | Port the fw v37 rev 2 `J` guards: G1 (bus-side I_fc + I_batt > 1.0 A / 5 ms in a session), G2 (unaccounted bus power > 3 W / 20 ms; in Run this needs VESC input-power telemetry, rate TODO(verify)), G3 (charger fault-status class), reboot-only trip latch | Detects a loop or runaway that has escaped and bounds its duration | Trip latch | Double faults |
| **W** | MCU hardware watchdog (RTWDOG), **REQUIRED FUTURE WORK**, §10 | Turns a hang into a reset; the pins go high-Z and the pull-downs open every path | All EN LOW | Hang (F1-F3 dead, P5 frozen) |

**The argument:**
- L-R needs D-MT-EN conducting (V-MOT < VBUS) at the same time as the charger converting. With H1 working, the charger is
  permitted only while V-MOT > 1.067 x VBUS - 0.16 V (worst-case guard ≥ 0.73 V at every bus voltage from 15.59 V to 19.5 V).
  The two conditions cannot hold together, apart from the §4.3 latency pulse.
- L-F needs pack current into the bus while FC_CHARGE is on. H2 removes the permit whenever BT current exceeds about 0.2 A,
  and the FC term never permits while BT_BUS or REGEN is commanded HIGH.
- Neither proof uses firmware, I2C, the threshold register or the MCU's state. Every element fails to "inhibit" when
  unpowered or in POR.

**Single-fault table** (one fault, everything else healthy):

| Fault | Effect | Loop possible? |
|---|---|---|
| Threshold mis-programmed / POR default below the bus | H1 = 0 in cruise | No |
| Firmware drives P5 HIGH at the wrong time, or State 98 abuse | H1/H2 still gate | No |
| Teensy hang with P5 = 1, REGEN = 1, BT_BUS = 1 | H1 gates. Charging continues on genuine regen only. Overcharge rests on the charger CV; W resets | No |
| Teensy reset / brown-out | Pins high-Z, 10 k EN pull-downs: every RT1987 off, charger unpowered; P5 pull-down | No |
| I2C dead | Config unverifiable -> F2 keeps P5 LOW. H1/H2 are I2C-independent | No |
| H1 stuck HIGH (VBUS divider open, comparator damage) | Soft layer (threshold above the bus) still prevents draw at bus voltage; F1 detects the mismatch in cruise and trips | Only with a second fault (threshold below the bus); then bounded by C2, detected by F3 |
| H1 stuck LOW | No regen harvest; F1 detects no permit during a measured burst | No (safe) |
| Charger ignores its inhibit (IC fault) | The regen threshold above the bus still blocks bus-voltage draw | Only with a second fault; bounded by C2, F3 trips REGEN |
| D-MT-EN shorted | V-MOT = VBUS always, so H1 never permits. Regen raises the whole bus, which is a separate boost back-feed hazard that firmware sees as V_rgn ≈ V_bus during braking | No |
| D-BT-EN shorted | In regen mode, nothing changes (BT_BUS is closed anyway). In the FC window, H2 current term = 1, so permit is withdrawn | No |
| D-BC-RG shorted | Charger always fed from V-MOT: H1 still governs. In the FC window both inputs come from the FC-only bus | No |
| D-BC-FC shorted | VCHG-IN tied to VBUS both ways. In regen, V-MOT is tied to the bus through D-BC-RG plus the short and cannot rise, so H1 never permits (harvest lost; regen back-feeds the bus: a hazard, not a loop). Detect with a power-on self-test: with FCC = REGEN = 0, V_chg (pin 38) must decay to about 0 | No |
| D-BT-SQ shorted | Pack on the charger output. Its back-feed into VCHG-IN is stopped by D-BC-RG/D-BC-FC (reverse-blocking) | No |
| W disabled or misconfigured | Hang leaves pins frozen; H1/H2/H3 still hold | No (overcharge exposure only) |

## 9. Circuit sketch (carrier or bodge board; values from `comp_calc.py`)

```
 VBUS (D-MT-EN VIN / C-D2 node)              V-MOT (D-MT-EN VOUT / CAL+)
   |                                           |
  RB1 464k 0.1%                               RA1 499k 0.1%
   |                                           |
   +---- IN-  [U1 TLV3012B]  IN+ --------------+---------+-- RH 6.49M --+
   |                                           |         |              |
  RB2 56.2k 0.1%   CB 470p                    RA2 56.2k  CA 470p        |
   |                |                          |         |              |
  GND              GND                        GND       GND             |
                                                                         |
 U1: V+ = 3V3 (Teensy 3V3, J1.29/30), 100 nF; V- = GND; OUT = H1 --------+ (OUT -> RH -> IN+ = positive feedback)
     H1 HIGH = "V-MOT > 1.067 x VBUS" (rise at +0.30 V hysteresis). POR / unpowered = LOW.

 U2: TLV3012B   IN+ = BT_CURRENT net (INA253 SNS-BT OUT, Teensy pin 41 node, 10 pA bias = no load)
                IN- = U2.REF 1.242 V -> 61.9k / 1.00k -> 19.8 mV (+ 100 nF)       OUT = BT_ACTIVE
                V+ = 3V3.  BT_ACTIVE HIGH when I_BT > about 0.2 A (0.11-0.29 A over +/-9 mV Vos; INA253 zero offset TODO(verify: INA253A1IPWR.pdf))

 Logic (3V3, single-gate 74LVC1G, 100 nF each; input nets taken at the Teensy breakout):
   G1 74LVC1G27 NOR3 : BT_BUS_EN net (pin 28), REGEN_EN net (pin 30, J1.43/44), BT_ACTIVE      -> N1
   G2 74LVC1G08 AND  : FC_CHARGE_EN net (pin 31, J1.45/46), N1                                -> H2
   G3 74LVC1G32 OR   : H1, H2                                                                 -> GATE
   G4 74LVC1G08 AND  : GATE, P5 net (pin 5, 47k pull-down on carrier)                         -> PERMIT
   PERMIT and H1 also go to two spare Teensy inputs (e.g. 33, 34 - enter in the IO CSV first) for F1.

 Inhibit stage H3 (charger side; pick by the charger's pin polarity):
   (a) active-HIGH enable pin, pulled down on the charger side: PERMIT -> 1k -> pin.
   (b) active-LOW enable / "pin LOW = Hi-Z" (e.g. ILIM_HIZ, MPPSET):
         Q2 NMOS drain on the pin, source GND, gate -> 100k pull-up to charger REGN/VDDA;
         Q1 NMOS drain on the Q2 gate, source GND, gate = PERMIT via 1k with 100k to GND.
         PERMIT HIGH -> Q1 on -> Q2 off -> pin released (ILIM divider / MPPSET divider sets its normal value).
         PERMIT LOW / logic unpowered -> Q1 off -> Q2 on (biased by the charger's own rail) -> charger inhibited.
```

Checks:

| Check | Result |
|---|---|
| H1 vs the TPS61288 OVP | At VBUS 18.3 V: fall min 19.23 V. At 19.5 V: fall min 20.52 V. The trip tracks the bus, so a failed-FB bus never permits |
| H1 vs the clamp | Rise max stays ≤ 18.70 V for any bus ≤ 17.2 V, below the measured 21.4 V clamp. At VBUS ≥ about 19.6 V the rise trip passes the clamp: harvest lost, safe |
| Input range | IN+ = 3.04 V at V-MOT 30 V and 4.05 V at 40 V. Above V+ + 0.2 V, "IN+ higher than range, IN- within -> output high" ([TLV] §9.4.4 case 3), which is correct, since V-MOT is genuinely above the bus. Fail-safe to 5.5 V means V-MOT up to about 54 V. IN- = 2.11 V at VBUS 19.5 V |
| Filter | Both legs τ ≈ 24 µs (matched, so a common-mode step does not trip). Lag at 3.75 V/ms ≈ 0.09 V, inside the guard |
| Resistor tolerance | 0.1 % parts are required. With 1 % parts the worst falling trip at VBUS 15.9 V drops to 16.14 V (guard 0.24 V) |
| The existing RGN-V divider (R1-SNT/R2-SNT) is NOT reused | It is also the TL431 REF node ([SCH] RGN-V: U-SNT REF, Teensy pin 39). Feedback current from RH would shift the chopper clamp and the ADC reading. The two new dividers add < 0.1 mA load |
| Supply | Teensy 3V3 is derived from the pack (VBT -> LM1084 -> 5 V -> Teensy). It exists whenever the Teensy is alive or in reset, and it falls with the pack. If 3V3 is lost, every RT1987 EN is also low, so the charger is unpowered |
| Residual | The LVC VIL (not read) is higher than the RT1987 VEN_F min 0.6 V ([RT] p.7). A BT_BUS net stuck at 0.6-0.8 V could read "off" while the switch conducts. H2's current term covers this |

## 10. MCU hardware watchdog: REQUIRED FUTURE WORK (operator ruling 5)

The current firmware has no MCU watchdog. Grep finds only the Pi watchdog (`checkPiWatchdog`, [FW] 7463). The
"BOOTING_FROM_WATCHDOG_RESET" string at [FW] ~9651 is a VESC fault-code name. **If Path A is pursued, the following must be
implemented and bench-proven before the first unattended charger session:**

- **Timer:** RTWDOG (WDOG3) on the 32 kHz LPO clock.
  - Resolution 1/32 ms; TOVAL up to 65535 ticks = 2.048 s without the prescaler. Source: [WDT] `begin()` WDT3 branch.
  - **Proposed timeout 100 ms (TOVAL 3200).**
  - Lower bound: the longest legitimate loop stall, to be measured. Candidates: SdFat synchronous write/close; the EEPROM
    commit (fw v28 rev 3, duration TODO(verify: PJRC)); Wire transactions to an unpowered charger (timeout behaviour
    TODO(verify)); Serial bursts.
  - Upper bound: what a frozen pin state may cost. With H1-H3 fitted, that is overcharge on a mis-set CV, a stale
    FC-window load, and an unfinished State-99 teardown, not the loop.
- **Second timer (recommended):** WDOG1 at 1.0 s. Its range is 0.5-128 s in 0.5 s steps ([WDT], WDT1 path:
  `constrain(timeout, 0.5, 128)`, `(timeout - 0.5)/0.5`). It is coarse but independent. **Do not route WDOG1_B to pin 19.**
  [WDT] offers pins 19/20 for WDOG1, and pin 19 is I2C SCL. Pin 20 is spare if a hardware WDOG_B is wanted.
- **Optional EWM** with its output on pin 21 (spare; [WDT] also offers pin 25, which is `BT_VOLTAGE` and must not be used).
  It could feed PERMIT as a fifth AND input, so a hang removes the charge permit before the reset. EWM_OUT polarity and
  reset behaviour are not in [WDT]: RM needed.
- **Feed policy:**
  - Feed exactly once per `loop()` iteration, and only after `detectFaults()`, the F1 monitor and the switch-state writer
    have all run in that iteration.
  - Never feed from an ISR or a timer callback.
  - No feed inside blocking calls: budget them instead.
  - State 98 and State 99 feed the same way. `doState99()` is already non-blocking and phased.
- **What a timeout resets:**
  - A system reset. [WDT] `expired()` reads `SRC_SRSR & SRC_SRSR_WDOG3_RST_B` for RTWDOG, so the cause is visible after
    boot. RTWDOG has no software-reset register, so the library falls back to `SCB_AIRCR` for a manual reset ([WDT]
    `reset()`).
  - Pad states after reset are TODO(verify: i.MX RT1060 RM, IOMUXC reset values). Whether a pad keeper is on by default,
    and its strength, is unknown.
  - The design assumes the 10 kΩ RT1987 EN pull-downs (CLAUDE.md §2) override any keeper and hold every EN below VEN_F min
    0.6 V ([RT] p.7). Each RT1987 also has a 475-985 kΩ internal pull-down ([RT] p.7).
  - P5 has no external pull today ([SPEC] §1). The carrier adds 47 kΩ.
  - Unpowered or POR comparator and logic outputs are LOW, and H3 self-inhibits.
- **Interaction with the 10 k pull-downs:**
  - From reset assertion until `setup()` drives the pins (Teensy boot time TODO(verify: PJRC)), the pull-downs alone hold
    FC_BUS, BT_BUS, MOT_PWR, REGEN, FC_CHARGE and BT_SEQ open.
  - V-MOT is isolated with whatever charge CAL holds. Regen in progress at reset goes to CAL and the chopper. This is the
    same condition as any MOT_PWR open during braking (existing).
  - Boost EN pull state during reset: TODO(verify: SCH). With every RT1987 open, a boost that floats on has no load and no
    back-feed path.
- **After a watchdog reset:**
  - Boot to State 0 and latch a new `ERR_MCU_WDT` (reset cause from SRC_SRSR) into telemetry.
  - Require an operator or Pi acknowledgement before Run.
  - The re-bring-up goes through the existing staged bring-up and `assertMotPwrEnable()`/`motPwrHotPlugUnsafe()` guards
    (V-MOT may be charged or discharged: Death-5 rules).
  - The charger re-configures from POR under P5 LOW (§6).
  - Any protocol field or packet change goes through the protocol-bump procedure.
- **Proof:**
  - Host-native test of the feed policy (a mock RTWDOG counter that must never be fed on an iteration that skipped
    `detectFaults()`).
  - Bench: a State-98 hang key that spins forever with P5, REGEN and BT_BUS HIGH. Scope the EN nets and PERMIT. Pass if the
    reset occurs within 100 ms +/- tolerance, every EN falls below 0.6 V, and PERMIT goes LOW.

## 11. State x mode matrix

Switch vector order: FC_REG, BT_REG, FC_BUS, BT_BUS, MOT_PWR, REGEN, FC_CHARGE, BT_SEQ. Charger states: **U** = unpowered
or Hi-Z-off, **I** = powered and inhibited, **B** = enabled below threshold (≈ 0 A), **C** = enabled and charging.
"Loop path" = whether the physical L-R/L-F graph is closed by the switches. "Blocked by" = what prevents conversion while it
is closed.

| Mode | Switches | Charger states reachable | Loop path closed? | Blocked by | Runaway bound |
|---|---|---|---|---|---|
| Teensy reset / boot | 0 0 0 0 0 0 0 0 (pull-downs) | U | No | No input power | - |
| Init (State 0) | 1 1 staged 1 staged 1(after pre-charge) 0 0 1 | U | No (REGEN = FCC = 0) | - | - |
| Idle (State 1) | 1 1 1 1 1 **0** 0 1 (recommended: REGEN open in Idle) | U | No | - | - |
| Run cruise, two-source | 1 1 1 1 1 1 0 1 | I (H1 = 0); B only if H1 fails | **L-R closed** | **H1** (hard), regen threshold above the bus (soft), P5 policy | C2 |
| Run cruise, battery-only selection | 1 1 0 1 1 1 0 1 | I | **L-R closed** (bus = BT only) | H1 | C2 |
| Run cruise, FC-only selection | 1 1 1 0 1 1 0 1 | I | No (BT out) | - | C2 |
| Run regen burst | as cruise; V-MOT > 1.067 x VBUS | B -> C | Closed by switches, but D-MT-EN reverse-biased | Physics (§4.1); H1 releases only in this condition | Source-limited: drawing more pulls V-MOT to VINDPM, then to the H1 fall trip |
| Run regen, VESC abrupt stop | as cruise | C -> I | Briefly | §4.3 latency budget | Single pulse ≤ I_in x (t_inh - 0.29 ms) |
| Run FC-charge window | 1 1 1 **0** 1 **0** 1 1 | U -> I -> C | No while D-BT-EN is truly off | **H2**, CSV rule, `assertFcChargeEnable()` | C2 (≤ 1.0 A in), `OC_FC` 1.4 A |
| Run FC window + braking | as above | C (from the FC bus) | No | REGEN = 0, so regen goes to CAL/chopper; or transition per §6 when the window closes | - |
| Transitions | §6 | I across every switch change | Momentarily closed in some steps | P5 LOW (I-1) plus H1/H2 | - |
| Finish (State 3) | -> Idle vector | I -> U | No | P5 LOW, then REGEN LOW | - |
| State 98 tests | any the operator requests | any | Can close L-R (`'2'` + `'4'`) and can try L-F (`'5'` + `'2'` refused in fw) | H1/H2 independent of the keys; `'M'`/P5 must go through the F2 verified-config gate | C2, F3 |
| `J` bus-fed charger session as defined in fw v37 rev 2 | REGEN + MOT_PWR with BT_BUS 1 | - | **L-R by construction** (the 2026-11-04 incident had BT supplying 16.5 A) | With H1 fitted it would never charge | **Redefine `J` as an FC-path session with BT_BUS 0 (H2)** |
| State 99 teardown | phased opening ([FW] 8248 ff.) | **P5 LOW first** -> U | No | Replace the "drain into Ag105" phases: with an inhibited charger they drain nothing. Either drop them or keep them as harmless | - |
| Teensy hang | frozen | frozen | Possibly closed | H1/H2/H3 are MCU-independent; W resets | C2 |
| I2C failure | any | I (F2 keeps P5 LOW) | Possibly closed | H1/H2 | C2 |
| 3V3 brown-out | EN nets fall with 3V3 | U / I | No | H3 self-inhibits; RT1987 EN pull-downs | - |

## 12. Bench gates added by this analysis

| ID | Measurement | Pass |
|---|---|---|
| M1 | H1 trip points vs VBUS on the bench (sweep a supply on the V-MOT leg with VBUS live) | Within the §4.2 table; hysteresis 0.25-0.35 V |
| M2 | Charger inhibit-pin -> input current < 10 mA latency, and Hi-Z-exit -> regulated input latency (capture value); whether VINDPM/config survive a Hi-Z cycle and an input brown-out (BQ257xx re-measures VBUS before converter enable, [713] §9.3.3.2; the datasheet does not say whether a host-written VINDPM is kept) | ≤ 290 µs x (1.5 A / I_in_limit); exit ≪ 100 ms; config retained or re-verified by F2 |
| M3 | RT1987 turn-off delay after EN low (D-BT-EN, D-BC-RG), not in DS-00 | Measured; replaces the firmware's 100 µs constant |
| M4 | Scope VBUS and V-MOT through regen onset in Run: bus load-dump overshoot, V-MOT ripple, V-MOT peak vs the clamp | Overshoot < 17.5 V; ripple < hysteresis |
| M5 | VESC input capacitance and regen current fall time (C_VMOT, I_regen dI/dt) | Refines §4.3 |
| M6 | Forced WDT reset with P5/REGEN/BT_BUS HIGH (§10) | All EN < 0.6 V, PERMIT LOW, ERR_MCU_WDT latched |
| M7 | Power-on self-test: with FCC = REGEN = 0, V_chg decays to about 0 (D-BC-FC/D-BC-RG not shorted); in Idle, H1 = 0; with BT_BUS = 0, BT_ACTIVE = 0 | Every boot |
| M8 | Calibrate the V_rgn ADC (0.85x) before F1 is trusted | Error < 1 % |

## 13. Firmware findings incidental to this analysis (fw v37 rev 2)

1. `FAULT_SWITCH_CONFLICT` is inside `#if !BENCH_TEST` (~7413), so it is inactive on the bench build that is flashed today.
2. That check uses `digitalRead()` on output pins, i.e. commanded levels. It cannot see a shorted switch. H2's current term
   can.
3. State 98 `'M'` toggles pin 5 freely. Under Path A, pin 5 becomes the charger permit and must go through the F2 gate.
4. `doState99()` phases 0-1 deliberately drain VBUS and then V-MOT into the charger ([FW] 8248 ff.). With an inhibited
   charger these phases drain nothing. Phase 1 also has REGEN HIGH with MOT_PWR LOW, the round-1 V-MOT-drain pattern.
5. `assertFcChargeEnable()` waits 100 µs between REGEN/BT_BUS LOW and FC_CHARGE HIGH, with the comment "confirmed
   sufficient" ([FW] 12772). DS-00 has no turn-off figure (M3).

## 14. missing_primaries

- **NXP i.MX RT1060 Reference Manual** (RTWDOG, WDOG1/2, EWM chapters; SRC reset-cause register; IOMUXC pad reset
  defaults and keeper strength). Needed for the §10 reset/pad claims. Not fetched (NXP login-gated). The WDT_T4 source was
  used instead and is not an NXP primary.
- **PJRC Teensy 4.1** pad state during reset and the boot time to `setup()`.
- **74LVC1G08/1G27/1G32 datasheets** (VIL/VIH at 3.3 V). Not fetched this round.
- **TL431 datasheet** (the BOM states +/-0.5 % for TL431BIDBZR; the datasheet itself was not read).
- **INA253A1** zero-current output offset (in repo `references/Datasheets/INA253A1IPWR.pdf`; not re-read this round).
- **Panasonic EEE-FN1V471UP** capacitance tolerance (assumed -20 %).
- **VESC input capacitance** and regen-current behaviour on abrupt stop (no document).
- **Richtek RT1987 turn-off delay** (absent from DS-00; ask Richtek or measure).
- **Charger VINDPM loop bandwidth** and inhibit/Hi-Z entry and exit latency for every candidate (absent from the TI
  datasheets read); **LTC4015 (DC2039A) and MP2759** were not covered in this IC-independent round.

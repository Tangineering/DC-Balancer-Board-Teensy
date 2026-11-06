# Path B (board re-spin) evaluated against Path A (EVM on the current board)

Scope: the operator treats a re-spin as an ALTERNATE path to wiring a new charger onto board rev 20260622, not
as a fallback. Both goals apply: regen harvest AND fuel-cell charging, with firmware selecting which is on.
The repo was not modified.

Sources:
- `docs/respin_power_architecture_2026-11-04.md` [RESPIN]
- `docs/fw37_planning_2026-11-04.md` [P37]
- `docs/bq25713_charger_replacement_2026-11-04.md` [BQ13]
- `docs/boost-bringup-debug.md` [DBG]
- `docs/boost-diagnostics-summary.md` [DIAG]
- `docs/PSCAD_SIM_DESIGN.md` OQ-4 [PSCAD]
- CLAUDE.md hardware bodge records and addenda [CLAUDE]
- the BOM CSV [BOM]
- the scratchpad files: `spec.md` [SPEC], `incident.md` [INC], `firmware_impact.md` [FWI], `dossier_*.md` [DOS-<part>]

Labels:
- **ESTIMATE**: engineering judgement, not read from a source. This covers every lead time, cost (other than the BOM
  figure) and schedule in weeks.
- **UNVERIFIED**: not read in a primary source.

---

## 0. Answer first

**Recommendation: run them in sequence. Path A is the de-risking prototype of the B1 charger; the B1-versus-B2 decision
is gated on two measurements.** Do not start B2 layout yet. Do not desolder the Ag105 until the chosen charger has passed
a standalone bench test off the board.

1. **Weeks 0-2: no risk to the board.**
   - Run the board health checks [INC (d)].
   - Buy one EVM from the candidate list that is also a credible B1 IC (section 5.2).
   - Bench it standalone. This gives M1 (cold-start latency), behaviour through an RT1987 standing in for D-BT-SQ,
     zero draw from a stiff 15.8 V source at the R3 threshold, and the hard-off paths.
   - Run the B2 control prototype in firmware only on the current board: the I_fc current command through the MDAC
     ([RESPIN] section 5). This needs an operator exception to "What NOT to change".
2. **Decision gate G1 (end of week 2-3).**
   - If M1 (worst case) plus board overhead is ≤ ~100 ms: B1 meets both goals, so do B1, and optionally Path A on the
     current board for early FC charging.
   - If it is not, regen under R3 on this architecture is tail-only, so the choice is B1 with hardware regen additions
     ("B1+", section 2.4) or B2.
3. **Weeks 3-8.**
   - Path A integration on the current board for FC charging only, if the board passed its health checks.
   - B1 schematic and layout in parallel, using the bench-proven charger.
   - B1 fixes every known board defect (section 2.2), which also yields spare boards.
4. **B2 as a research decision, not a repair.** Commit only if the thesis needs the current-commanded FC / unified
   charge-budget architecture. Even then, build B1 first, or take its fixes into B2. B2 retires the droop-share
   controller, the DP/SDP/HIL calibration of campaigns I/II, and the Youla share-loop paper's hardware basis.

**Can regen harvest physically work on the current board? Yes, but only partially, and the best case is unproven.**
Section 4 gives the arithmetic. Under R3 every burst is a cold start. The board alone adds ~12-20 ms. Every TI NVDC
candidate adds a structural ≥ 50 ms CHRG_OK deglitch, plausibly ~150 ms. BQ24650 adds 1.5 s and LTC4162 adds 2-4 s,
both showstoppers. For the other candidates the timing is unverified. Bursts peak 0.10-0.20 s after onset and are over
by 0.3-0.6 s. So the best case catches the peak and tail of most bursts, and the plausible case catches only the tail.
Energy at stake is ~0.7 J electrical per decel, which is about 0.05 s of the FC's 14.6 W median stack output. On this
rig regen is a capability demonstration and a control-research item, not an energy lever. The only ways to full capture
are:
- an R3 ruling that keeps the charger powered behind a hardware-gated hard-off, or
- a re-spin.

---

## 1. Known board defects and constraints a re-spin can fix

Inventory from the bodge records, the debug log, the planning docs and the spec/incident files. The last column marks
what B1 fixes; B2 fixes the same set plus everything marked B2.

| # | Defect / constraint | Status on rev 20260622 | Source | Fix in re-spin |
|---|---|---|---|---|
| D1 | **Ag105 VBat- tied to PCB GND by design** (pack negative = GND); the Ag105 senses current in Bat-; ML0227 ~11 A runaway | Root cause of the incident (mechanism UNCONFIRMED by direct measurement) | [INC](a), [CLAUDE] 2026-11-04 | B1: charger with high-side sense, or input-side sense, laid out properly. B2: charger retired |
| D2 | **BT boost output-cap hot loop**: C_out 240 mil from the IC vs 40 mil on FC; 4 BT deaths; fixed by 10 µF + 0.1 µF bodge caps at the IC on both boosts | Bodged, validated 2026-07-07 | [DIAG], [DBG] "Board respin items" | Move C_out to IC VOUT/PGND (≤ 40 mil, mirror FC); match the VSW pours; widen VBUS-BT |
| D3 | **RD1 237k → 215k FB retune** (17.5 → 16 V bus), done as a bodge; the BT channel was once found un-bodged | Bodged | [DBG] l.255, l.1852; [CLAUDE] section 6 | Fit 215k on both channels |
| D4 | **RC-BT 27.4k → 61.2k** (matches FC; never-rotated bodge record) | Bodged | [CLAUDE] | Fit 61.2k |
| D5 | **D-MT-EN CSS 5.6 nF → 100 nF** (motor-node pre-charge, Death-5 class); D-FC-CH, D-RG-EN, D-BT-SQ deliberately NOT bodged | Bodged on D-MT-EN only | [DBG] l.1180, l.1221 | Fit 100 nF on D-MT-EN and size CSS on each switch for its downstream capacitance |
| D6 | **10k EN pull-downs on all RT1987s** (default-off during Teensy reset) | Bodged | [CLAUDE] section 2, [SPEC] section 3 | Fit on the schematic |
| D7 | **INA253A1 fitted instead of A3** (0.1 V/A, 4x less resolution; the droop authority was designed around A3) | Fitted wrong variant | [CLAUDE] section 5 | Fit INA253A3, or keep A1 and re-derive. Either way K_SNS, the droop chain and the coefficients must be regenerated (regen-coeffs skill) |
| D8 | **Encoder rerouted pins 2/8 → 14/15, ENC_ENABLE deleted, sensors hardwired** | Bodged; CSV amended | [CLAUDE] bodge record | Route to 14/15 natively. Reverting means changing the firmware, CSV and the literal pin tests together, so keep 14/15 |
| D9 | **Encoder pull-ups 4.7k → 2.2k** | Bodged | [CLAUDE] | Fit 2.2k, or the value chosen with the Schmitt buffer |
| D10 | **74HC14 Schmitt buffer on encoder outputs**; pull-up rail possibly 5 V while Teensy pins 14/15 are not 5 V tolerant | Fitted as a bodge (operator-confirmed 2026-11-04); rail question OPEN | [CLAUDE] 2026-11-04 record, [PSCAD] OQ-4 | Put the buffer on the board, powered from 3.3 V (or a 5 V buffer with a level-safe output) |
| D11 | **OPA197 moved to the 5 V rail** (droop op-amp output ceiling) | Bodged | [CLAUDE] section 7 | Power it from 5 V on the schematic |
| D12 | **V_rgn reads 0.85x true** on pin 39 (TL431 REF loading suspected); V_chg on the same divider reads correctly | Firmware workaround needed (v38) | [P37] 3.4 item 3 | Buffer the divider, or move the TL431 sense off the ADC divider |
| D13 | **Teensy logic supply from the battery only** (LM1084 off VBT) | By design | [RESPIN] section 3 item 5 | OR it from bus and battery (blocks [RESPIN] option 2 today) |
| D14 | **D-BT-SQ orientation question** | **Refuted as a defect**: .brd VIN on VCHG, VOUT on VBT, conducts charger → pack [INC](a) | [P37] R2, [INC] | Re-decide its role (section 2.3): it hides the pack from any charger and wipes charger config on every input cycle [SPEC] section 3 |
| D15 | **BQ29200 OUT (BAL-NOK) goes nowhere**: OVP detects 4.35 V/cell but drives nothing; no hardware overcharge action | By design ("intentionally unused") | [SPEC] section 0.4, [CLAUDE] section 4 | Route OUT to a hardware action (charger CE/ILIM-HiZ, or the D-BT-SQ EN) and to a Teensy pin |
| D16 | **CHARGER_STAT has no pull-up** | Missing | [SPEC] section 3 | Fit a 3.3 V pull-up |
| D17 | **VCHG-IN caps C-D8/C-D10 are 25 V parts** against a ~21.4 V regen clamp with an unmeasured overshoot | Marginal | [SPEC] section 2 | ≥ 35-50 V parts |
| D18 | **Pack negative bonded twice** (J-BT pin 2 and balance J-BL pin 3): a loose J-BT routes the whole pack return through the balance lead | Fire risk, any charger | [INC](c) | Single return; J-BL GND as sense only |
| D19 | **Unipolar battery-channel current sense** (INA253 REF1/REF2 to GND); battery charge current invisible bus-side | By design | [RESPIN] section 2.2 | Bipolar battery-current sense (needed for B2; useful for B1 G2-style guards) |
| D20 | **Braking chopper 47 Ω sinks only ~0.46 A at 21.4 V**; the V-MOT peak above the clamp is unmeasured | By design | [SPEC] section 2 B | Stronger clamp. **Mandatory in B2**, where V-MOT is tied to the bus |
| D21 | **V-MOT is both the motor supply and the regen node**, coupled to the bus by D-MT-EN (closed through Idle/Run since Death 5), so REGEN closed = bus feeds charger (the R3 hazard) | Architecture | [P37] 3.3 | B1+: a separate regen node or a hardware-gated REGEN. B2: removes R3 by construction |
| D22 | **ADC divider ground shift** (gains 7.87x V_chg ... 1.62x V_batt); INA253 ~10 mA/mV ground offset | Layout | [INC](c) | Kelvin ADC ground / star return |
| D23 | No battery-backed RTC (log pairing) | Dropped by operator | [P37] section 5 | Optional coin cell; low value |

Pending mechanical items that are **not** board defects: the 90-slot disc / once-per-rev ripple, and an optional index
sensor for a learned pitch table [P37] 6.4 option 6. If wanted, B1 can add a footprint for an index sensor.

---

## 2. B1: minimal re-spin (same architecture, correct charger, all bodges and defects folded in)

### 2.1 What stays the same

- Two TPS61288 boosts with droop sharing through the AD5443 MDAC and OPA197.
- The six RT1987 path switches.
- The 16 V bus, the Teensy 4.1 pin map (encoder on 14/15), the UDP protocol, the state machine and the share and drive
  controllers.

That is the main asset: **every firmware, HIL and EMS calibration of the last four months carries over**. The exception
is a K_SNS change if the INA253A3 is fitted (D7).

### 2.2 What changes

- **The charger laid out on the board**, with its battery negative on the same copper as its input ground and nothing in
  series ([SPEC] R-GND). It uses the IC chosen in Path A's standalone test (section 5.2).
  - The layout adds: RAC/RSR sense resistors with Kelvin routing; ILIM/HiZ and CE hard-off wired fail-safe (pull to OFF);
    3.3 V I2C pull-ups only; STAT/CHRG_OK pull-up; an NTC footprint; and input caps sized to the RT1987 soft-start budget
    (≤ ~50 µF effective in FC mode; [SPEC] section 6).
- **Defects D2-D13, D15-D18 and D22 fixed** (table above).
- **The D-BT-SQ role re-decided (section 2.3).**
- **Charge-mode threshold select in hardware** ([SPEC] section 4): a FET switches the input-regulation or UVLO divider,
  driven by the FC_CHARGE net. A low or floating net gives the safe regen threshold (19 V).

### 2.3 D-BT-SQ in B1

On rev 20260622, D-BT-SQ sits between the charger output and the pack. That has three costs:
- the charger sees an open 10 µF node instead of a battery;
- the charger loses its I2C config on every input-power cycle;
- the charger's auto-recharge cycles as VCHG decays ([SPEC] section 3; [DOS-LTC4162] battery detection fails behind it).

Options for B1:
- **(a) Put the charger BAT pin directly on the pack** and use the charger's own BATFET (NVDC P-ch BATFET on the
  BQ257xx family; LTC4015 is a controller with external FETs) for battery-side isolation. The battery-sequencing switch
  then moves upstream of the BT boost only. This is the configuration every vendor validates. It keeps the charger logic
  alive from the pack, which preserves its config and shortens the regen cold start: only the VBUS-side deglitch
  remains, not the charger's own POR, as [DOS-BQ25720] notes. **Recommended.**
- **(b) Keep D-BT-SQ.** The cost is all three items above, and battery detection only works on the chargers that
  tolerate an open output.

### 2.4 B1+ (optional): hardware regen additions, if M1 rules out cold-start capture

Each item below is independent and cheap in layout, and each needs its own design note.
- **Hardware REGEN gate.** A comparator drives the D-RG-EN EN pin, true only while V-MOT > V_bus + margin, ANDed with
  the Teensy's REGEN_ENABLE. This turns R3 layer 1 into a hardware layer independent of firmware timing. It removes the
  firmware detection time from the onset (2-3 ms) but not the RT1987 8 ms tD_ON or the charger deglitch.
- **A charger kept powered behind a hardware hard-off.** The charger input is fed from V-MOT through a one-way switch
  that stays closed through Run. A comparator on V-MOT drives the charger's ILIM_HIZ or CE pin, releasing it only above
  ~19 V, with VINDPM at 19 V as the second layer and the firmware detector as the third.
  - This avoids the cold start, so latency becomes the Hi-Z exit plus the converter soft-start (UNVERIFIED; measure).
  - **It needs an explicit R3 ruling:** the bus would carry the charger's quiescent current and would be one comparator
    away from feeding charge power. The operator rejected the firmware-only version of this ([P37] 3.3 "Rejected").
    This hardware version is a different question.
- **A regen buffer capacitor** ([RESPIN] option 3, ~3.3 mF for 0.7 J between 16 and 26 V): this decouples capture from
  the charger speed. But 26 V exceeds the 24 V operating rating of most of the NVDC candidates, and re-closing MOT_PWR
  onto a drained buffer is the Death-5 class. **Not recommended** without a dedicated pre-charge circuit.

### 2.5 What B1 achieves

- **FC charging:** yes, fully. Charging is from the bus through D-FC-CH, with the charger's input current limited to
  ≤ ~1.0 A (the OC_FC 1.4 A single-sample latch and the H-20 1.247 A bus ceiling) [SPEC] section 2 A.
- **Regen:** the same physics as Path A (section 4), unless B1+ is taken or D-BT-SQ option (a) shortens the cold start
  enough. Best case is partial capture.
- **Robustness:** a board with no bodges, matching its schematic, with 4-5 identical copies. **This ends the "only
  working board" single point of failure.**

### 2.6 B1 effort, lead time, cost, risk

**Hardware design (ESTIMATE): ~2-4 engineer-weeks.**
- The schematic edits are local. Layout covers: the charger block on a ~32 x 35 mm area or wherever it fits best; the BT
  C_out relocation; the encoder routing; the supply OR-ing; the clamp.
- Plus a design review, preferably with the adversarial-doc-review skill against the bodge records.

**Fab and assembly (ESTIMATE, UNVERIFIED pricing):**
- A 2-layer prototype with turnkey assembly: ~1-3 weeks plus shipping.
- Component cost: the current BOM is **$149.66 per board** for 111 parts ([BOM] header "Total Assembly Cost").
  - The Ag105 line costs $14.70 [BOM].
  - A charger IC plus FETs, sense resistors and inductor is of the same order as the Ag105 or a few tens of dollars more.
  - PCB plus assembly NRE for 5 boards: low hundreds of dollars.
  - Total for 5 boards, roughly **$1-2k all-in** (ESTIMATE).
- Long poles: charger IC and EVM stock ([BQ13] section 5 item 7: "limited quantities"), the Teensy 4.1, and the TPS61288
  QFN.

**Bring-up risk: moderate. The history is the warning.**
- The first board took ~2 weeks of boost deaths before the hot-loop cause was found: Death 1 on 2026-06-24 through the
  validated fix on 2026-07-07, then Death 5 (motor-node hot-plug) on 07-08 [DBG], [DIAG].
- B1 removes the two known killers in layout: D2 (the hot loop) and D5 (pre-charge, CSS).
- B1 adds a new switching charger, which has its own hot loop and needs its own inductor layout.
- Mitigation: copy the vendor EVM layout for the charger block, and bring it up first with the boosts unpopulated or
  disabled, scope-armed, as [DBG] prescribes.

**Firmware, HIL and EMS:**
- ≈ Path A's 20-29 engineer-days for the new charger driver and Run integration [FWI].
- Plus ~3-8 days for re-spin housekeeping: the CSV and pin-test updates if any pin moves, a K_SNS and coefficient
  regeneration if the INA253A3 is fitted, the removal of bodge records (with a new hardware record for rev 2), the pin 6
  pull-up, and the BAL-NOK input if routed.
- The share loop, governor and drive controller are unchanged.
- The HIL plant needs the new charger model (η, start latency); most of that work is shared with Path A.

**Schedule (ESTIMATE):** design 3-4 weeks → fab 2-3 weeks → bring-up 2-6 weeks. That gives **~8-13 weeks to the first
safe charge on a B1 board**, sooner if the charger driver was already written and proven in Path A.

---

## 3. B2: bidirectional-converter architecture ([RESPIN] option 4)

### 3.1 Architecture

- **A bidirectional pack-to-bus converter forms the 16 V bus in voltage mode.** It replaces the BT TPS61288 and the
  charger.
- **The FC stage becomes current-commanded**, regulating stack current with a CV ceiling of ~17 V and input-voltage
  foldback for purges. Candidates: LT8705A, or the TPS55288 for a prototype (all from search summaries, NOT
  datasheet-verified) [RESPIN] sections 3-4.
- **The motor node conducts onto the bus in both directions.**
- **The chopper stays as the fast clamp.**

### 3.2 What B2 achieves

- **Regen: full capture by construction.** There is no cold start. The converter's voltage loop absorbs the surplus at
  kHz bandwidth, limited only by the pack's CC/CV limit. R3 dissolves:
  - "bus feeds the pack" IS FC charging, an explicit current command;
  - the battery→bus→battery circular path cannot exist through a single converter.
- **FC charging:** a direct I_fc command above the load ([RESPIN] 2.1). Firmware always knows the split.
- **Research value: high.** A stack-current command sets the operating point on the convex H-20 map directly. That is
  exactly the lever the H-20 phase-B work found the droop share controls only indirectly (CLAUDE.md 2026-09-09
  addenda; the full-scale governor penalty is an operating-point effect). The EMS plans in stack current.

### 3.3 What B2 costs and what it newly risks

- **New power stages with no bench history on this project.**
  - Two new controllers (bidirectional plus FC current mode), each with external FETs, compensation, and a current loop
    closed around the H-20's impedance (UNVERIFIED stability).
  - The boost-death history was a layout and hot-loop lesson on ONE known IC. B2 puts two new ones on the board at
    once. ESTIMATE: bring-up risk high.
- **The motor-node switch must conduct in reverse.** Every Death-5 pre-charge and hot-plug rule (`assertMotPwrEnable()`,
  `motPwrHotPlugUnsafe()`) is redesigned. A back-to-back switch held on is not an ideal diode, so the ideal-diode
  OR-ing that protected the bus from V-MOT disappears.
- **Bus overvoltage on a full pack.** If the converter cannot absorb (pack full, faulted, at its limit), regen raises the
  bus directly.
  - Today's chopper sinks ~0.46 A at 21.4 V (D20), which exceeds the TPS61288 OVP of 18.3-19.5 V ([TPS] p.6) if the FC
    stage remains a TPS61288.
  - B2 therefore needs a properly sized clamp and an explicit full-pack regen mode (charge allowance = 0 means the
    chopper dumps).
- **A single bus former.** If the bidirectional converter faults, the bus is held only by the FC stage's CV ceiling,
  and the FC purges to ~1 V ([CLAUDE] fw v30). The Teensy supply OR-ing (D13) becomes mandatory.
- **Bipolar battery current sense and firmware-owned CC/CV** move charge safety into firmware plus converter limits.
  The BQ29200 OUT should drive a hardware action (D15).

**Firmware / HIL / EMS: 63-95 engineer-days [FWI].**
- The share loop is rebuilt around an I_fc command. The Youla share controller and its coefficients are on the "What
  NOT to change" list, so this needs an operator exception.
- The F1 selector, governor (fw v26-v30), charge windows and FC_CHARGE/REGEN semantics are retired or redefined.
- A forced telemetry bump; a new HIL plant, DP/SDP, governor_model and walk; several campaigns to re-calibrate.
- Campaigns I/II and the board-measured H-20 levers no longer describe the hardware.

**Hardware design (ESTIMATE): ~8-14 engineer-weeks.**
- Two new power stages with compensation design.
- Simulation: PSCAD (the repo has PSCAD models and `docs/PSCAD_SIM_DESIGN.md`).
- Layout and review.
- Likely two board spins before it is right. ESTIMATE: 50 % chance of needing a rev-2 fix.

**Fab and cost (ESTIMATE):** same turn time as B1. Components are perhaps +$30-80 per board over B1: two controllers,
~4-8 power FETs, two more inductors, sense resistors, a back-to-back switch, a bigger clamp. Plus the probable second spin.

**Schedule (ESTIMATE):** design 2-3.5 months → fab 2-4 weeks → bring-up 1-2.5 months → firmware/HIL/EMS 3-5 months for
one engineer, partly overlapping. That gives **~5-9 months to integrated regen plus FC charging under EMS control**, and
~4-6 months to the first bench charge.

### 3.4 B2 de-risking on the current board, for free

[RESPIN] section 5: a State-98 I_fc reference mode. It runs a 1 kHz PI on the MDAC FC code, with BT as the bus former
and I_fc below the load (the current board cannot sink a surplus). It measures:
- I_fc step response and tracking;
- stack V/I through a purge with the reference held;
- bus behaviour with one bus former.

This tests B2's EMS control concept and the H-20's response to a current command, with no hardware change, before any
B2 layout commitment. It touches the share path, so it needs an operator exception.

---

## 4. Can regen harvest work on the current board at all? (Path A, and B1 without B1+)

**The R3 constraint is hard.** With MOT_PWR closed through Idle and Run (the Death-5 rule), closing REGEN connects the
16 V bus to the charger input. R3 forbids bus-fed charging in Run [P37] 3.3. So the charger must be unpowered, or
hard-off, until braking lifts V-MOT above the bus. **Every burst is a cold start.**

**The onset chain** (spec section 5; the board overhead is from [SPEC]):

| Stage | Time | Source |
|---|---|---|
| Firmware detects V_rgn > V_bus + margin (1 kHz, needs the D12 0.85x calibration) | 2-3 ms | [SPEC] section 5 |
| D-RG-EN turn-on delay tD_ON | 8 ms | [RT] p.7 via [SPEC] |
| D-RG-EN ramp, CSS 5.6 nF, ~12 V/ms | ~1.4 ms at 21 V | [SPEC] section 6 |
| I2C re-config (the charger lost its settings behind D-BT-SQ) | ~2-3 ms | [SPEC] section 3 |
| D-BT-SQ re-enable, overlapping the charger ramp | 0-8 ms | [SPEC] |
| **Board subtotal** | **~12-20 ms** | |
| Charger: TI NVDC family CHRG_OK VBUS deglitch (BQ25713/20/73) | **≥ 50 ms structural** | [DOS-BQ25720] (doc viewer), [DOS-BQ25713], [DOS-BQ25773] (search text; UNVERIFIED in a read datasheet for 13/73) |
| Charger: possible converter power-up after the deglitch | ~150 ms in one BQ2571x revision (UNVERIFIED for the BQ25720) | [DOS-BQ25713], [DOS-BQ25720] |
| BQ25798 | est. 90-120 ms+ (≈20 ms to I2C + ~30 ms poor-source + ~30 ms post-DPDM + board) | [DOS-BQ25798] (UNVERIFIED) |
| BQ24650 | ≥ 1.54 s (1.5 s charge-enable delay) | [DOS-BQ24650] — showstopper |
| LTC4162 | 2-4 s battery detection, cannot be disabled | [DOS-LTC4162] — showstopper |
| LTC4015, MP2759 | not found in any source read | [DOS-LTC4015], [DOS-MP2759] — UNVERIFIED |

So the onset is **≥ ~62-70 ms in the best case** for the TI NVDC family and **plausibly ~165-190 ms**. The burst
([P37] 3.2): V-MOT rises 0.08-0.12 s after the setpoint falls, peaks at the chopper clamp (~21.4 V true) 0.10-0.20 s in,
and is back at bus level 0.3-0.6 s in. About 0.7 J electrical per decel, ~0.2 A into the pack for ~0.4 s if captured.

**Capture (ESTIMATE; the in-burst energy distribution has not been measured):**
- **Best case (~65-70 ms):** the charger is running before the peak on most bursts and captures the peak and tail.
  Plausibly half or more of each burst's electrical energy, less on the shortest bursts.
- **Plausible case (~170-190 ms):** the charger starts at or after the peak and captures the tail only. Plausibly a
  minority of the energy. On a 0.3 s burst little or nothing is captured.
- **Upper bound on what is at stake:** 0.7 J per decel ≈ 0.05 s of FC output at the 14.6 W median stack power
  (CLAUDE.md 2026-09-09: 14.644 W). Six decels on RegenTest_v2 are ~4 J in total, against ~890 J for 61 s of FC
  operation at that power (derived). **Regen on this rig is worth harvesting for the research claim** (closed-loop
  regen/FC-charge mode selection), **not for range.**

**Levers that do not need a re-spin:**
1. **Lengthen the bursts**: a lower VESC "Battery Current Regen Max", giving gentler, longer braking [P37] 3.2 M1 table.
2. **D-BT-SQ bridged on the current board** ([SPEC] section 3 option): the charger stays alive from the pack and keeps
   its config. This removes the I2C re-config and possibly the charger POR from the chain, but not the VBUS deglitch.
   It costs the firmware's hard battery-side disconnect, and the charger must block BAT → input back-feed.
3. **The R3 ruling on a powered, hardware-gated Hi-Z charger** (section 2.4 bullet 2). That one is achievable as a
   bodge on the current board too: a comparator from V-MOT, wired to J1.43/44 (the REGEN net) and the charger's HiZ
   pin. It is a design note and a ruling, not a quick fix.

**Verdict:**
- **Physically possible, partial, unproven.** M1 on the standalone EVM decides it, before anything touches the board.
- **No candidate surveyed can meet the spec's 30 ms target** under R3 as written. The 100 ms hard maximum is met only in
  the best case of the TI NVDC family, if the 50 ms deglitch is the whole charger delay.
- **FC charging on the current board is unaffected by latency** and is fully achievable with Path A, subject to the
  ≤ ~1.0 A input budget and the FC delivering at all. The FC "was not delivering power on 2026-11-03 (undiagnosed)"
  [CLAUDE] 2026-11-04, and after the incident I_fc read 0 A [INC](d).

---

## 5. Path A vs B1 vs B2

### 5.1 Comparison

Estimates are calendar time for one engineer, ESTIMATE unless cited.

| Criterion | Path A (EVM on the current board) | B1 (minimal re-spin) | B2 (bidirectional) |
|---|---|---|---|
| **Time to first safe charge** | ~3-5 weeks: EVM in stock (days to ~2 weeks) → standalone bench 1 week → minimal driver 4-6 eng-days [FWI] → desolder and integrate. A charge from the bench bus in State 98 (`J`-style, R3 bench exception) comes first; FC charging in Run additionally needs `FC_CHARGE_ALLOWED`, the v38 items and a working FC channel | ~8-13 weeks; ~1-2 weeks less if Path A already proved the driver | ~4-6 months (bench); ~5-9 months integrated |
| **Time to regen harvest** | ~6-10 weeks (v38 interlock, V_rgn calibration, M1) and **partial at best**, possibly tail-only (section 4) | Same physics, ~10-16 weeks; better with D-BT-SQ option (a); **full only with B1+** and an R3 ruling | ~5-9 months, **full capture by construction** |
| **FC charging** | Yes (≤ ~1.0 A input, single-source FC window) | Yes | Yes, as a direct current command |
| **Firmware / HIL / EMS effort** | ~20-29 eng-days [FWI] | ~23-37 eng-days (A's work plus re-spin housekeeping) | ~63-95 eng-days [FWI], plus several campaigns |
| **Hardware effort** | Carrier PCB or flying leads; input cap swap C-D8/C-D10 (D17); a pull-up; a fail-safe pin-5 polarity fix | ~2-4 weeks design | ~8-14 weeks design, likely 2 spins |
| **Cash cost** | EVM ~€179 (BQ25713EVM, DigiKey NL, [BQ13]); other EVMs UNVERIFIED; optional small carrier PCB | ~$1-2k for 5 boards (BOM $149.66 per board [BOM] + PCB/assembly) | ~$2-4k over 1-2 spins |
| **Risk to the only working board** | **Real.** Desoldering a 22-pin DIL module whose GND pads tie to both pours with no thermal relief, with D-BT-SQ, C-D11 and C-D12 underneath [SPEC] section 7, [INC](d), possibly already damaged by the incident. Mitigate: cut pins, remove one at a time, check barrel continuity | **None** (new boards; the old board stays the bench and HIL reference); creates spares | None to the old board; high bring-up risk to the new one |
| **Bring-up risk** | Low to moderate. Known board; the risk is the charger's interaction with the RT1987s and the hot-plug budget (≤ ~50 µF effective input C) | Moderate. Known killers fixed in layout; one new switching stage | High. Two new power stages and a redesigned motor-node path |
| **Keeps the calibrated platform** | Yes | Yes, with the K_SNS rework if A3 is fitted | No: share loop, governor, HIL plant, DP/SDP, campaigns I/II all re-derived |
| **Thesis / research value** | Demonstrates FC charging and (partial) regen on the existing droop-balancer platform; preserves the Youla share-loop paper's hardware basis; the R3 three-layer interlock is a publishable safety pattern | Same plus a clean, schematic-matching board (reproducibility for a thesis appendix) | Highest novelty: stack-current EMS on the convex H-20 map, unified regen/FC charge budget; but a new platform late in a programme, and the droop work becomes historical |
| **What it de-risks for the others** | Chooses and proves the B1 charger IC (latency, VINDPM-at-bus behaviour, D-BT-SQ interaction, I2C driver, guards G1-G4 retuned); measures M1 and the V-MOT overshoot that set B1's ratings (C-D8/C-D10, OVP class) | Gives spare boards on which risky B2 control prototypes (section 3.4) can run without endangering the only board | Nothing for A/B1; its §5 firmware prototype de-risks B2 itself |

### 5.2 Choosing the Path A EVM so that it also prototypes B1

Pick a charger that is a credible board-level B1 IC, not only a convenient EVM. From the Path A ranking:

- **BQ25713 / BQ25720 (TI NVDC buck-boost; scores 6 / 5).**
  - Datasheet facts read for the BQ25713 [BQ13]: ACOV ≥ 25 V min (margin over the 21.4 V clamp), VINDPM 3.2-19.52 V
    (covers the 19.0 V regen threshold), host-terminated charging, 5 s watchdog, Hi-Z pin.
  - Weaknesses: the ≥ 50 ms CHRG_OK deglitch; the 24 V recommended input against the unmeasured V-MOT overshoot; the
    pin-5 off-polarity is not fail-safe on the EVM.
  - **Good B1 candidate.** The NVDC BATFET fits D-BT-SQ option (a).
- **LTC4015 / DC2039A (score 5.5).**
  - Strengths: 35 V class input (UNVERIFIED here), external FETs, a coulomb counter (useful for the SoC EKF), UVCL input
    regulation.
  - Weaknesses: POR defaults believed to be the maximum codes (8 A); start latency unknown [DOS-LTC4015].
  - **Strong B1 candidate if its latency proves short.**
- **BQ25798 (score 5.5).** Compact and integrated (good for a ≤ 32 x 35 mm carrier), but its 24 V operating / 26 V
  VAC_OVP is tight against the regen overshoot, and the VINDPM upper limit is UNVERIFIED.
- **Excluded for regen:** BQ24650 and LTC4162 (cold-start showstoppers), and MP2759 (EVB < 20 V, no I2C).

**Practical recommendation: buy two EVMs, a BQ25713EVM-017 (or BQ25720EVM) and a DC2039A, and run M1 on both standalone.**
The faster one with acceptable behaviour from a stiff 15.8 V source becomes both the Path A integration charger and the
B1 schematic IC. The second EVM's cost (low hundreds of €, UNVERIFIED) is small against a wrong B1 choice.

### 5.3 Combined sequencing (recommended)

| Step | When (ESTIMATE) | Board risk | Output / gate |
|---|---|---|---|
| S0 Board health checks [INC](d): the FC channel under 1-2 A load and FC-only; D-BT-SQ, D-RG-EN and D-MT-EN reverse-block, forward drop and EN control; bench-supply limit record | Week 0-1 | Low (diagnostic) | Is the current board still a valid Path A host? If the FC channel or a switch is damaged, Path A integration loses most of its value and B1 moves up |
| S1 Two EVMs standalone on the bench supply, an RT1987 or diode as the D-BT-SQ stand-in, a 2S pack: CV accuracy, M1 cold-start latency, VINDPM/UVCL ~0 A at a stiff 15.8 V, the Hi-Z / inhibit / watchdog hard-offs, input-C inrush through an RT1987 at 5.6 nF CSS | Weeks 1-3 | None | **Gate G1**: charger IC chosen; regen-feasibility number for this architecture |
| S2 B2 control prototype in firmware ([RESPIN] section 5; operator exception) and HIL leg | Weeks 1-4, parallel | Low (State 98, I_fc < load) | Stack response to a current command and through purges; informs B2 go/no-go |
| S3 Minimal driver (port the J guards G1-G4, a "charger return verified" gate replacing `AG105_VBATN_ISOLATED`) and host tests | Weeks 2-4 | None | Shared by A and B1 |
| S4a Path A integration (carrier PCB on the 22 holes, C-D8/C-D10 → ≥ 35 V, pin 5 fail-safe, STAT pull-up), **only if S0 passed**; FC charging first; regen behind the v38 three-layer interlock and the M1 result | Weeks 4-8 | **Medium** (the desolder) | First FC charge on the vehicle board; first (partial) regen data, including the V-MOT overshoot measurement that fixes B1's ratings |
| S4b B1 schematic and layout with the S1 charger, all of section 1 folded in, D-BT-SQ option (a), B1+ hooks (comparator footprint, threshold-select FET) as no-fit options | Weeks 3-8, parallel | None | Gerbers; adversarial design review against the bodge records |
| S5 B1 fab and bring-up (charger block first, boosts scope-armed per [DBG]) | Weeks 8-14 | None to the old board | Clean boards, spares; the regen path with B1+ populated if G1 said so |
| G2 Decide B2 | After S2 and S5 | - | Commit only on a research-value ruling, with B1 boards as the safe bench and the spare platform |

Why the sequence:
- **Path A's EVM test is the cheapest, zero-risk way to choose the B1 charger and to answer the regen question.**
- **B1 removes the single-board risk** before any further risky experiment (B2 prototypes, regen chopper tests).
- **B2 is a programme-level research bet.** It should be decided on thesis grounds, with B1 boards in hand, not as the
  repair for the Ag105 defect, which B1 already fixes for a fraction of the effort.

**If schedule forces one path only:**
- **B1** gives the best risk-to-value: both goals, partial regen improvable with B1+, no risk to the existing board,
  spares, and the calibrated platform kept.
- **Path A alone** is fastest to an FC charge but carries the desolder risk on a possibly damaged board, and on this
  architecture regen is partial.
- **B2 alone** is the slowest and riskiest, but it is the only path to full regen capture without an R3 compromise.

---

## 6. Operator questions this analysis raises

1. **R3 extension:** is a charger kept powered from V-MOT behind a hardware comparator Hi-Z (charger VINDPM 19 V as
   layer 2, firmware detector as layer 3) acceptable? It is the only route to near-full regen capture without B2.
2. **Thesis timeline and scope:** is a B2 platform change (retiring the droop-share hardware basis) acceptable inside
   the remaining programme, or is regen a demonstration-level goal (B1 / Path A suffice)?
3. **INA253A3 or keep A1 on B1?** A3 changes K_SNS and forces a coefficient regeneration plus HIL re-calibration.
4. **D-BT-SQ in B1:** option (a), charger BAT on the pack with the charger's BATFET, or keep the ideal diode?
5. **BAL-NOK (BQ29200 OUT):** route it to a hardware charge-inhibit in B1? Today nothing in hardware acts on an
   overcharge [SPEC] section 0.4.
6. **Board health (S0) first:** the outcome decides whether Path A integration is worth the desolder risk.
7. Pack datasheet (maximum charge current, protection board), and whether an NTC is fitted. These are needed by every path.

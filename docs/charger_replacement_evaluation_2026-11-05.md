# Charger replacement: decision document (2026-11-05)

**Scope.** This document chooses how to replace the Silvertel Ag105 (BOM `CHG`) on board rev 20260622. It compares two
paths that the operator treats as **alternates, not fallbacks**:

- **Path A:** desolder the Ag105 and wire an off-the-shelf charger evaluation board to its pads on the current board.
- **Path B:** re-spin the board.

It supersedes the single-candidate feasibility note `docs/bq25713_charger_replacement_2026-11-04.md`. Section 4.3 lists
what that note got right and what it got wrong.

**Evidence base.**
- **Board side (primary):** the schematic and board files, BOM, IO CSV, fw v37 rev 2, the Ag105 / RT1987 / TPS61288 /
  BQ29200 datasheets, `docs/boost-bringup-debug.md` (2026-11-04 entries), `logs/ML0227.BLG` (decoded this round), and
  `docs/fw37_planning_2026-11-04.md` section 3.
- **Candidate side: no primary datasheet or EVM user guide was readable this round.** www.ti.com, www.analog.com,
  www.monolithicpower.com, mouser.com, farnell.com and the usual mirrors are outside the session's allowed network
  domains. Every candidate-specific number below is one of:
  - from the 2026-11-04 BQ25713 note (whose author read SLUSD83C and SLUUBT8B in full);
  - a TI or ADI document-viewer snippet surfaced by web search, tagged **[snip]**;
  - recollection, tagged **[REC]**.

  All of these are **UNVERIFIED** until the primary documents are read. That read is gate G0 (section 7).

**Status of the hardware.** Nothing has been ordered, desoldered or changed. fw v37 rev 2 stays on the bench board
(`AG105_VBATN_ISOLATED 0`: no regen charging, `J` hardened). The repo was not modified apart from this file.

---

## 0. Status and recommendation

**Status:** decision document, revised after the critic round of 2026-11-05. Nothing has been ordered and no hardware or
firmware has changed. **The ranking is provisional pending G0.** Every candidate-side number in this section is
UNVERIFIED ([REC] or [snip]). Board-side numbers come from the local primaries listed in section 9.

**Three blockers apply to every candidate:**
1. No candidate datasheet could be read this round, so no part is cleared for integration yet.
2. On this architecture, under R3 (the bus must never feed the charger in Run), **regen harvesting is partial at best
   for every candidate.** Every braking burst is a cold start: 12-20 ms of board overhead plus the charger's own start
   chain, against bursts that peak 0.10-0.20 s after onset and finish by 0.3-0.6 s. No candidate meets the 30 ms target.
   Only the fastest plausible case meets the 100 ms hard limit: the TI NVDC family's ~50 ms input-good deglitch [snip],
   giving ~65-75 ms in total.
   **What regen is worth (estimate, path_b analysis):** about 0.7 J electrical per decel, which is about 0.05 s of the
   FC's 14.6 W median stack output. The six decels on RegenTest_v2 come to about 4 J, against about 890 J for 61 s of FC
   operation, roughly 0.45 %. Unless the operator rules otherwise (question 3 in section 8), regen capture has
   **demonstration value**: it supports the closed-loop regen/FC-charge mode-selection claim, not range.
3. **fw v37 rev 2 has no host-silence stop.** It has no MCU hardware watchdog: grep finds only the Pi watchdog and a
   reset-reason string (ino ~9651). A hung Teensy that has FC_CHARGE or REGEN HIGH and pin 5 HIGH leaves any charger
   without its own host watchdog charging indefinitely, and the LTC4015 has none [REC]. Path A firmware therefore adds
   a Teensy 4.1 hardware watchdog (WDOG/RTWDOG): a hang resets the MCU, the pins go high-Z, and the 10 kΩ RT1987 EN
   pull-downs plus the 47 kΩ pull-down on the pin-5 enable stage make every path safe. **Until that watchdog exists and
   S2.1b passes, the LTC4015 fails the host-silence row of section 2.2.** The BQ25713 meets that row on its own 5 s
   watchdog (SLUSD83C §9.3.10.1, via the 2026-11-04 note).

**Recommendation: select Path A or Path B1 at a shared gate (G1), as parallel options on their own merits, after one
common step that puts no board at risk and serves both.**

**Common step (weeks 0-3):**
- Run the post-incident health checks on the current board (Stage 0, section 7). They cover the FC channel, D-BT-SQ,
  D-BC-RG and D-MT-EN; **the 2S pack that took an estimated 11-13 A of charge for about 1 s in ML0227 (UNCONFIRMED)**;
  the charger-adjacent Teensy pins 5, 6, 18, 19 and 38; and the BQ29200. **Any pack anomaly blocks every charging path,
  on either path.**
- Pass G0 before buying anything. For the LTC4015 these G0 items are make-or-break:
  - **The UVCL register/divider interaction.** The plan assumes `vin_uvcl_setting` can only *lower* the threshold set by
    the UVCLFB divider. If the effective threshold is instead the higher of the two, FC mode at 15.8 V cannot work with
    the 19.2 V divider. The named fallback is a carrier FET that switches a second UVCLFB divider leg and fails safe to
    19.2 V (section 4.1, decision 3).
  - VIN absolute maximum.
  - Battery-detect timing.
  - RSNSB/RSNSI full-scale sense voltages.
  - INFET turn-on timing and slew.
- Buy two candidate EVMs:
  - **ADI DC2039A (LTC4015)**, provisional rank 1. No showstopper was found and no lens refuted it, but "not refuted"
    means only that the lenses had no data. Its claimed strengths are all UNVERIFIED [REC]: a ~35-40 V input class,
    I2C telemetry, and a 1.0 A hardware input ceiling once RSNSI is 32 mΩ (which assumes a 32 mV full scale). Its
    weaknesses: no host watchdog (blocker 3), and regen latency unknown.
  - **TI BQ25713EVM-017**, provisional rank 2. No lens refuted it either. Its 30 V absolute maximum has zero margin, its
    VINDPM ceiling is 19.52 V, and its ≥ 50 ms CHRG_OK deglitch [snip] makes regen marginal. It does have a 5 s host
    watchdog.
- Bench both standalone, off the board, through an RT1987 stand-in. Measure:
  - cold-start latency M1, both with the D-BT-SQ stand-in fitted (S1.6) and with it bridged (S1.6b, gated);
  - input current from a stiff 15.8 V source at the R3 threshold;
  - the hard-off paths;
  - inrush, with the input-FET turn-on step measured separately from the RT1987 ramp;
  - CV accuracy.

Whichever IC passes becomes the charger for whichever path is chosen.

**At G1, choose on these merits:**
- **Path A** (EVM on the current board). Choose it when all of these hold:
  - Stage 0 passes;
  - the chosen EVM passes Stage 1;
  - the operator accepts the desolder risk on the only working board;
  - the priority is the earliest FC charge on the calibrated board.

  First vehicle FC charge comes at about weeks 4-8 (one schedule: section 5.2). Regen comes at about weeks 6-10, and only
  to the extent S1.6 allows.
  - **Path A' variant: D-BT-SQ bridged.** The charger stays alive from the pack, keeps its registers, and takes battery
    detection out of the cold-start chain. The cost is that firmware loses its battery-side hard disconnect against a
    shorted charger high-side FET. Choose A' only if S1.6b shows that bridging is what brings M1 to 100 ms or less, and
    the operator accepts that trade-off (question 4).
- **Path B1** (a minimal re-spin with the S1 charger IC, its BAT pin on the pack with its own BATFET, and every recorded
  bodge folded in). Choose it when any of these hold:
  - regen is a firm goal and S1.6b shows the charger needs its BAT on the pack (B1 gives this without A's
    shorted-FET trade-off);
  - spare boards are wanted for thesis demonstrations and riskier later work;
  - a clean board with every recorded bodge folded in is worth the schedule;
  - nothing should be desoldered from the only working board;
  - Stage 0 finds damage.

  B1 reaches a first safe charge at about weeks 8-14.
- **Path B2** (a bidirectional pack-to-bus converter) is the only route to full regen capture without relaxing R3. It is
  a research-scope decision, not a repair: about 5-9 months, and it retires the droop-share platform. Weigh it against
  the regen value above.

The always-on VCHG-IN comparator and threshold-select FET (called "B1+" below) do not need a re-spin. They can sit on
the Path A carrier. Either way they need an R3 ruling (question 1).

**Conditions on Path A:**
1. Read the primaries (G0) before buying.
2. Confirm input/battery ground continuity on the EVM schematic and with a DMM.
3. Keep D-BT-SQ fitted (the Path A default; A' only by ruling).
4. Put no electrolytic on VCHG-IN. Keep effective capacitance on the RT1987-ramped node (VCHG-IN plus the EVM VIN side,
   upstream of the charger's input FET) at or below about 50 µF; the mockup has ≤ 29 µF. Measure the SYS charge at
   input-FET turn-on separately (S1.1) against the single-sample OC_FC latch.
5. Replace C-D8/C-D10 (25 V) with 50 V parts.
6. Make pin 5 an active-HIGH charger enable, pulled down on the charger side. Amend the IO CSV first.
7. Keep the three-layer R3 interlock and the ported `J` guards. Layer 2, the charger's input threshold, covers normal
   bus regulation and the 17.5 V firmware OV region. **It does not cover a boost with a failed FB:** TPS61288 OVP rises at
   18.3 / 19 / 19.5 V min/typ/max (SLVSFP3C p.6), above the 19.0 V and 19.2 V thresholds. That case rests on layer 1 and
   the `FAULT_OV_BUS` latch.
8. Add a Teensy hardware watchdog, and pass S2.1b before any powered LTC4015 session.
9. Gate charge enable on V_batt and on the charger's own VBAT readback: no enable above about 8.30 V, TODO(calibrate).
   For the LTC4015, fit the local BATSENS fallback resistor. Add a Wire timeout and a bus-clear.
10. Do FC charging first, at standstill or low demand within the H-20 budget. Turning FC charging back on
    (`FC_CHARGE_ALLOWED` is 0 in fw v31-v37) is a firmware/EMS ruling, not an integration step. Enable regen only if
    S1.6 measures 100 ms or less.

---

## 1. Why

### 1.1 Incident (2026-11-04, `J` session, ML0227)

- **Setup.** The charger was fed from the bus through D-MT-EN and D-BC-RG.
- **Bus-side ramp.** The bus side drew a 1 s linear ramp to about 11 A, roughly 170 W. The ramp rose at about 10.6 A/s
  while the Ag105's own battery-voltage reading (reg 0x05) rose about 0.45 V/s.
- **What the charger reported.** Ag105 reg 0x06 (charge current) read 0.011-0.033 A and varied, so it was not stuck.
  Reg 0x07 tracked the input voltage, so the I2C reads were live.
- **Collapse.** The bench FC supply dropped out, the BT boost reached 16.5 A, and the bus fell to 6.84 V in about 4 ms.
- **What the guards saw.** The bus stayed above 15.05 V until the supply failed. Neither the firmware UV backoff
  (12.8 V for 15 ms) nor the UV latch (12.0 V for 20 ms) could have acted.

### 1.2 Mechanism (fits every observation; UNCONFIRMED by direct measurement)

**What the datasheet says** (Ag105 DS V1.1):
- The Ag105 senses current in Bat-, between Bat- and Load-/Vin- (Fig. 1, p.3). VLoad- is internally tied to Vin-
  (Table 2, p.4), and p.4 forbids tying VBat- to Vin-/GND.
- On this board the pack negative **is** PCB GND, so Ag105 VIN- and VBAT- share one node and the sense shunt is
  paralleled.
- Bring-Up charging ramps the output while monitoring current (p.6). The over-current trip (set current + 200 mA, p.18)
  reads the same sense. So on this board the module had **no working output-current limit**: only its 11 V input UVLO
  (p.19) could stop it.

**How the ML0227 trace lines up:**
- The Ag105 climbed from about 2 V at 0.64 V/s with zero current. That is Bring-Up into an open node, because D-BT-SQ
  blocks the pack.
- The ramp began on the first sample where reg 0x05 exceeded the pack: 7.744 V against 7.67 V.
- **Energy balance (UNCONFIRMED):** pack plus connector resistance is about 24 mΩ ((7.669 − 7.267 V) / 16.46 A at
  collapse). That puts the Ag105 output at about 11-13 A, 4.6-5x its 2.5 A setting.

**Alternatives examined:**

| Alternative | Verdict | Reason |
|---|---|---|
| D-BT-SQ fitted backwards | Refuted | In the .brd its VIN pads are on VCHG and VOUT on VBT, so it conducts charger→pack as designed |
| Ag105 internal short | Refuted | Its input was live for 11.7 s without conducting |
| BT-boost return current crossing the Ag105 pads | Not an explanation | That path runs 25-35 mm away |
| RT1987 limiting the current | Not a factor | Its short-circuit limit only works during soft-start (DS-00 §17.5) |

The operator confirmed on 2026-11-04 that VBat- is tied to GND **by design**.

### 1.3 What a swap fixes and what it does not

**Fixes:**
- A charger with high-side (BAT+) or input-side current sense, whose input return and battery return are the same copper,
  removes the root cause.
- With a correctly sensing charger fed from the bus (the R3 case), the loop is bounded by the charger's own limits. At
  2.5 A out that is about a 1.46 A bus-side step, 0.2-0.45 V of droop sag and about 5.5 W of waste. The bound holds
  **only if the current ceiling is set in hardware** (sense or ILIM resistor). A register default allowing 8 A would draw
  about 75 W, close to the roughly 85 W at which the bench supply dropped out.

**Does not fix:**
- **R3.** The bus can still reach the charger through D-MT-EN + D-BC-RG with V-MOT at bus level. The three-layer regen
  interlock (fw37 planning §3.3) stays mandatory. Only B2 removes the hazard by construction.
- **Overcharge protection.** None exists in hardware: BQ29200 OUT goes to the orphan net `BAL-NOK`, and the 8.5 V
  firmware latch acts after the fact. The new charger's CV is the primary overcharge control.
- **D-BT-SQ.** It hides the pack from the charger. Every input-power cycle is a charger POR, which loses its registers and
  presents an open output.
- **Hot-plug (Death-5 class).** An EVM input capacitance against the RT1987's 12 V/ms ramp can latch OC_FC or kill a boost.
- **Draining V-MOT.** If MOT_PWR opens while REGEN stays closed, the charger drains the 470 µF node at about 3.2 V/ms. The
  next MOT_PWR close is then a full-bus hot-plug.
- **Pin 5 off-level during MCU reset.** This must be guaranteed in hardware.
- **Pack-negative double bond.** The pack negative is bonded at J-BT pin 2 and at the balance lead J-BL pin 3. A loose
  J-BT terminal puts the whole return through the balance lead. This is a fire risk with any charger.

---

## 2. Requirements at the Ag105 pads

Condensed from the interface spec written this round. Footprint: CHG at (47.498, 34.544) mm, R180; two rows 25.00 mm apart;
2.54 mm pitch; 1.1 mm drill; outline 32.0 x 34.8 mm.

### 2.1 Pads

| Pad (pin) | Net | Driven by | Range | Required of the replacement |
|---|---|---|---|---|
| VIN+ (10) | VCHG-IN: C-D8, C-D10 10 µF/25 V; R1-CHG 78.7k / R2-CHG 10k → pin 38 | D-BC-FC (VBUS, pin 31) or D-BC-RG (V-MOT, pin 30) | 0 V off; about 15.8 V in FC mode; 15.8-21.4 V+ in regen | Power input. At most about 1.0 A in FC mode |
| VIN- (4), VBAT- (14, 15) | GND | – | 0 | **R-GND:** the input return and battery return must be the same node, with no shunt or FET between them |
| VBAT+ (18, 19) | VCHG: polygon, C-D11 10 µF/25 V, D-BT-SQ VIN | the charger only | 0 idle; VBT + 35-50 mV while charging | CC/CV output that can start into an open or capacitive load. At most 2.5 A |
| SDA (8), SCL (7) | Teensy 18/19; 10 kΩ to 3V3 | Teensy | 0-3.3 V | Open-drain at 3.3 V, 100 kHz, sole device on the bus, no EVM pull-ups to other rails |
| STAT (3) | Teensy 6 (`INPUT`, no pull) | charger | ≤ 3.3 V | Needs a 3.3 V pull-up (`INPUT_PULLUP` or J1.29/30) if open-drain |
| MPPTD (11) | Teensy 5, driven LOW in `setup()` (ino ~6720) | Teensy | 0 / 3.3 V | Becomes an active-HIGH enable with a charger-side pull-down of at most 47 kΩ |
| THERM (13) | J-NTC pin 1 (pin 2 GND) | 10k B3435 NTC (Ag105 p.9) | analog | NTC input; fit a real NTC on the pack, never a fixed resistor on the vehicle |
| 1, 2, 5, 6, 9, 12, 16, 17, 20-22 | unconnected | – | – | Mechanical anchors only |

Bodge points:
- VBT Kelvin point at C-D12.
- 3V3 at J1.29/30 and J2.05/06; 5 V at J2.01/02.
- FC_CHARGE net at J1.45/46, REGEN at J1.43/44, MOT_PWR at J1.41/42.
- Spare Teensy pins: 10, 16, 17, 20-23, 33, 34. **Amend the CSV first.**

### 2.2 Electrical envelope

| Requirement | Value | Basis |
|---|---|---|
| Input operating range, no OVP trip | ≤ 12 V to ≥ 23 V | Regen clamp is about 21.4 V true (design 2.495 x 8.87 = 22.1 V). The 47 Ω chopper sinks only about 0.46 A, so the peak above the clamp is unmeasured |
| Input absolute maximum | ≥ 30 V required, ≥ 36 V preferred | RT1987 OVP (POVP grounded) only acts at ≥ 33 V, so it does not protect the charger. The Ag105 was rated 36 V |
| Input threshold (R3 tier 2) | Regen **19.0 V** (window 18.3-20.0 V, ±3.5 %); FC **13.5 V** (13.0-14.0 V); safe default at POR = the regen value or charging off | Above the 16.0 V regulated bus and the 17.5 V firmware OV; FC threshold above the 12.8 V UV backoff. **Coverage:** layer 2 covers normal regulation and the 17.5 V firmware OV region only. A boost with a failed FB can hold the bus up to its OVP, which rises at 18.3 / 19 / 19.5 V min/typ/max with 600 mV hysteresis (SLVSFP3C p.6), so the bus can sit at about 18.9-19.5 V. That is above 19.0 V (BQ25713 code 247, accuracy window 18.44-19.39 V) and the 19.2 V LTC4015 UVCL. The failed-FB case rests on layer 1 and the `FAULT_OV_BUS` latch (17.5 V, 10 ms persistence). Moving the threshold above it would need about 20.2 V nominal (min > 19.5 V at −3.5 %). The BQ25713 cannot do that (VINDPM ceiling 19.52 V), and on the LTC4015 the window top (~20.9 V) would sit about 0.5 V under the 21.4 V clamp, leaving almost no harvest window |
| Preferred mechanism | Programmable hysteretic input UVLO (hard off). VINDPM-class regulation is acceptable with a bench proof of about 0 A from a stiff 15.8 V source. An input current limit alone is only a bound | fw37 planning §3.3 |
| Charge current | Programmable, 2.5 A capable, down to ≤ 0.25 A | Ag105 parity; regen averages about 0.2 A |
| FC-mode input limit | Hardware ceiling ≤ 1.0 A (backstop) **plus** a dynamic IIN register = FC budget − I_motor − aux | `LIMIT_I_FC_MAX` 1.4 A latches on a single sample (ino 2090); aux 0.10-0.15 A. **The FC alone carries motor plus charger in a window:** `assertFcChargeEnable()` forces BT_BUS LOW (ino ~12762). The H-20 P_MAX is 23.4 W stack, about 1.247 A bus (CLAUDE.md 2026-09-09). Budget for the charger = 1.247 − aux (0.10-0.15) − cruise allowance, so ≈ 1.10 A at standstill and less in cruise. A 1.0 A hardware ceiling therefore bounds the charger only at standstill. In cruise, the bound is firmware (the dynamic IIN) or a restriction of FC charging to standstill / low demand. fw v31-v37 ship `FC_CHARGE_ALLOWED 0` (ino 2616); turning it on is a firmware/EMS ruling |
| CV | 2S 8.400 V, ±0.5 % or better. Compensate for the D-BT-SQ drop (pack ≈ 8.365 V) only if accuracy is ≤ ±0.3 % | RT1987 35 mV / 20 mΩ forward regulation (DS-00 p.7, p.16) |
| Output ripple at VCHG | < about 50 mV p-p | RT1987 fast-reverse comparator trips at −50 mV (analysis, UNVERIFIED) |
| Output current limit | Cycle-by-cycle, independent of battery sense | D-BT-SQ re-closes without soft-start after a reverse block (DS-00 p.15 Table 1) |
| Effective input capacitance | ≤ about 50 µF on the RT1987-ramped node (hard limit about 80 µF), **no electrolytic**. Capacitance behind the charger's input FET (SYS) is not charged by the ramp; see section 4.1 | RT1987 slew = 28 V / (CSS/0.0023 − 100) µs = 12.0 V/ms with 5.6 nF, so inrush = 12 mA/µF. The board's own 20 µF draws 0.24 A. 470 µF would draw 5.6 A (Death-5) |
| No switching during the ramp | About 1.33 / 1.75 ms (0-100 %) at 16 / 21 V, after tD_ON 8 ms | Datasheet tON is 10-90 %: VIN/35 x (CSS/0.0023 − 100) µs (DS-00 §17.3) = **1.07 ms at 16 V, 1.40 ms at 21 V** with 5.6 nF (C-DC8/C-DC10). Use the 10-90 % figures as the bench pass values |
| Regen cold start | Input applied → 90 % of set current: **≤ 30 ms target, ≤ 100 ms hard** | Burst timing (fw37 §3.2) |
| Fail-safe | Charger-side enable defaults OFF; no autonomous charge from stored settings; host-silence stop ≤ about 5 s | Layer 1 (RT1987 EN pull-downs) remains primary, but it needs a live host to open. fw v37 rev 2 has no MCU hardware watchdog, so a charger without its own watchdog (LTC4015 [REC]) fails this row until a Teensy WDOG/RTWDOG is added (S2.1b) |
| State-99 drains | Tolerate ~10 ms FC_CHARGE then REGEN pulses with no latched fault | doState99 phases 1-2 |

---

## 3. Candidate survey and shortlist

### 3.1 Screened and rejected

| Board / part | Reason |
|---|---|
| BQ25731EVM / BQ25730EVM | Passes on paper (26 V operating, 32 V abs max per TI listing, SRP/SRN high-side). But the EVM appears out of stock, and ICHG/VINDPM are UNVERIFIED. BQ25720EVM fills the same niche with stock |
| BQ25703AEVM-732 | Superseded by BQ25713, same envelope |
| BQ25792EVM; Mikroe Charger 25 Click (MIKROE-5839) | Merged into the BQ25798 entry (same register set; Click = form factor) |
| BQ24610EVM / BQ24617 | No input-voltage regulation, so no hardware R3 threshold |
| BQ24630EVM | LiFePO4 algorithm |
| BQ25756(E)EVM, BQ25750EVM, BQ25758(A)EVM, BQ25820EVM | 10 A / 5 mΩ class, oversized; parked as Path B references |
| BQ25672 EVM | EVM existence UNVERIFIED; input range conflicts |
| BQ24725AEVM, BQ24780SEVM-583, BQ25710EVM-017 | No VINDPM / older / SMBus sibling with no advantage |
| BQ25887EVM | 3.9-6.2 V input |
| DC1568A, DC1688A (LT3652) | 2 A ceiling, wrong float |
| DC1484A-A (LT3651-8.4) | No input-voltage regulation found (UNVERIFIED) |
| MAX77960/61 EV kits | Abs max, VINDPM and ICHG UNVERIFIED; USB-C centric |
| DC2069A (LT8490), DC2703A (LT8491) | Oversized, 12 V SLA, slow perturb-and-observe MPPT |
| DC2374B (LTC4013), DC2044A/DC2134A (LTC4020), DC1830A (LTC4000) | Wrong as-built configuration / needs an external front end |
| MAX17702EVKITA, MAX8903, MAX1873, LT3741 demo | Lead-acid / 1-cell / obsolete / not a charger |
| MPS EV2760 (MP2760) | 22 V operating maximum against the 21.4 V clamp |
| MPS EV2619 / EV26123 | 2 A at 24 V |
| Richtek EVB_RT9490 | VAC_OVP default 7 V blocks the input until an I2C write, on every cold start |
| Richtek EVB_RT9492 | Plausible, but abs max and MIVR UNVERIFIED and availability unknown. Revisit if BQ25798 fails its VINDPM check |
| Richtek RT9467 | 1-cell |
| Renesas ISL9241 / ISL9238 / ISL9237 / ISL95522A | ≤ 20-23.4 V operating maximum, out of stock, or no EVB |
| Southchip SC8815 / SC8886S / SC8885S / SC89890 | No official EVB; sense location UNVERIFIED (generic SC8815 modules may sense in the negative leg) |
| Consonance CN3722 modules | IC passes on paper, but primary datasheet unread, conflicting CC formula, module GND continuity UNVERIFIED, no I2C. Low-cost fallback only |
| CN3795 modules | 2 A, abs max UNVERIFIED |
| Injoinic IP2368, IP2326 | USB-PD SoC / 5 V boost |
| MPS EV2672, EV2731, MP2733, MP26029; Halo HL7061/HL7015; Silergy SY69xx; ST EVAL6924D; Microchip MCP73213 / ADM00513; onsemi LC709511 | Wrong input class, 1-cell, ≤ 2 A, linear, obsolete, or unobtainable. ADM00513 also risks a low-side shunt |
| NXP / Toshiba | No 2S, 15-22 V, ≥ 2 A EVB found |
| Generic BQ24650 modules | Merged into BQ24650EVM (backup only after a schematic check of the negative leg) |
| SparkFun Sunny Buddy, DFRobot DFR0535 / DFR0580, Waveshare Solar Power Managers, Mikroe Balancer 5 | 1S, lead-acid, or 5 V boost |
| TP5100 | 20 V abs max (seller-quoted) |
| **XL4015 / LM2596 CC/CV buck modules** | **Low-side shunt in OUT−: the same defect as the Ag105 on this board** |
| Generic AH2167 / SY6912A 2 A modules | 22 V operating maximum, sense UNVERIFIED |
| Genasun GV-5, Victron 75/10 | No 2S profile |
| Adafruit / Seeed / Pololu / Olimex / Vertiq | No 2S high-input charger in these catalogues |

### 3.2 Shortlist, deep-dives and adversarial verdicts

**Method.** Each finalist had one deep-dive and three independent adversarial lenses:
- *electrical* (incident recurrence, abs max, reverse paths);
- *safety* (fail-safe, R3, overcharge, hot-plug);
- *practical* (stock, rework, schedule, value).

The fit score is the deep-dive author's; the lenses mostly argued it downward.

| Rank | Candidate | Fit | Electrical | Safety | Practical | Showstopper status |
|---|---|---|---|---|---|---|
| **1** | **ADI DC2039A (LTC4015)**, sync buck controller, I2C, coulomb counter | 5.5 | not refuted (major) | not refuted (major) | not refuted (major; argues 4-4.5 until primaries read) | **None found, but every number is [REC]; provisional pending G0.** Fails the host-silence row (no host watchdog) until the MCU watchdog is added (S2.1b). The UVCL register/divider interaction is a G0 make-or-break item for FC mode. Regen latency unknown |
| **2** | **TI BQ25713EVM-017 (BQ25713)**, NVDC buck-boost, I2C | 6 | not refuted (major) | not refuted (major) | not refuted (major) | **Conditional:** if M1 exceeds 100 ms, Path A on this part is FC-charging only. Meets host silence on its own 5 s watchdog |
| 3 | TI BQ25798EVM (BQ25798), integrated buck-boost | 5.5 | not refuted | not refuted | **refuted** | Conditional: VINDPM ceiling (needs ≥ 19 V) UNVERIFIED; 24 V operating / 30 V abs max; recommended form factor is a custom carrier (a mini re-spin); ~90-120 ms cold start |
| 4 | TI BQ25720EVM (BQ25720), SMBus | 5 | not refuted | not refuted | **refuted** | Cold start ≥ 50 ms (+150 ms if the sibling delay applies); adds an SMBus port but nothing over BQ25713 here; 12 wk lead, 4-5 units per region |
| 5 | TI BQ25773EVM (BQ25773), 40 V dual-phase | 4 | not refuted | not refuted | **refuted** | 16 A-class over-design; deep-dive mod "tie VSYS to BAT" would **bypass RSR and recreate the incident class** (struck) |
| 6 | MPS EV2759 (MP2759/MP2759A), standalone, no I2C | 5.5 | not refuted | **refuted** | **refuted** | EVB rated "VIN < 20 V"; -01A ships 3S; no I2C means the G2 credit term and G3 are lost (the guard that would catch an ML0227-class fault); no watchdog; charges at POR |
| 7 | TI BQ24650EVM-639, standalone, MPPSET | 5.5 | **refuted** | **refuted (showstopper)** | **refuted** | 1.5 s charge-enable delay on every power-up and re-enable: regen impossible under R3. Only regen route ("always-armed") is the option fw37 §3.3 already rejected. Proposed threshold selector fails unsafe |
| 8 | ADI DC2038A-A (LTC4162-L LAD) | 3 | **refuted** | **refuted (showstopper)** | **refuted (showstopper)** | 2-4 s mandatory battery detection every cycle (UNVERIFIED): regen impossible. FC charging requires bridging D-BT-SQ |

**Common findings across the shortlist:**
- Every TI NVDC part resets VINDPM to about VBUS − 1.28 V at POR, which is permissive toward bus feed. Safety at POR then
  rests on ChargeCurrent POR = 0 plus Hi-Z-until-configured.
- On BQ25720 and BQ25773, VINDPM is re-measured right before converter enable, so the threshold must be written **after**
  enable or Hi-Z exit, then read back.
- Every candidate loses the Ag105's NTC protection unless the THERM path is designed in. BQ2571x/2577x have no TS pin
  (UNVERIFIED).
- Every candidate with a 175 s or longer default watchdog must have the short watchdog written on **every** POR. Behind
  D-BT-SQ, every input cycle is a POR.

---

## 4. Finalist mockups

### 4.1 DC2039A (LTC4015) on the Ag105 pads: rank 1

**Source status.** Every LTC4015/DC2039A number is [REC] or [snip]. No DC2039A schematic was read, so EVM parts are named
by function (`<RSNSB>`). Item 0 of the bench plan is to transcribe against the DC2039A Demo Manual Rev D schematic.

**Design decisions:**
1. RSNSB 4 mΩ → **12 mΩ**: 32 mV / 12 mΩ = 2.67 A ceiling; `ICHARGE_TARGET` = 29 gives 2.50 A, in 83.3 mA steps. Use
   13 mΩ (2.46 A) if the pack is limited below 2.5 A.
2. RSNSI 3 mΩ → **32 mΩ**: 1.00 A hardware input ceiling at POR. This bounds a failed R3 to about 16 W, against about
   170 W in ML0227.
   **The stock 3 mΩ allows about 10.7 A in, the same class as the incident.** Swap and 4-wire-measure it **before the
   board is ever connected to VCHG-IN.**
3. UVCL divider **150 kΩ / 10.0 kΩ, 0.1 %**: 1.2 V x (1 + 15) = **19.20 V** at POR. The register can only lower it
   [REC]: firmware lowers it to 13.50 V (`VIN_UVCL_SETTING` 0x16 = 179) for an FC window. Loss of the register fails
   safe to 19.2 V. **This is a G0 make-or-break item.** If the effective threshold is instead the higher of divider and
   register, the register cannot open an FC window. **Fallback:** split the bottom leg into 10.0 kΩ + 4.64 kΩ in series
   (1.2 V x (1 + 150/14.64) = 13.50 V), with an N-FET across the 4.64 kΩ. Its gate is pulled up to the EVM's INTVCC (FET
   ON gives 19.2 V) and pulled LOW only by an active-HIGH Teensy select through an inverter, mirroring M7. A reset,
   floating or unpowered host therefore leaves 19.2 V. This costs a spare Teensy pin (amend the CSV first). The 1.2 V
   reference is itself [REC].
4. Pin 5 becomes **`CHG_ENABLE`** (active HIGH) through an inverting two-FET stage (M7) that grounds UVCLFB. A LOW,
   floating or reset pin forces "UVCL infinite", so the charger regulates to about 0 A.
   `setup()` already drives pin 5 LOW, so the boot default needs no code change.
5. Pin 6 becomes **`CHG_ALERT`** (open-drain SMBALERT, `INPUT_PULLUP`). It means "alert", not "charging"; readiness
   comes from I2C `CHARGER_STATE`.
6. **D-BT-SQ stays fitted.** This keeps the firmware's battery-side hard disconnect, against the shorted-buck-FET failure
   mode. Cost: a POR and full re-config every burst.
7. BATSENS is Kelvin-sensed at Ag105 pad 18 (the charger's own output), **never at VBT**. Sensing VBT opens the CV loop
   whenever D-BT-SQ blocks, and VCHG then runs toward VIN onto 25 V C-D11.
8. **MPPT stays off** (`mppt_en_i2c` = 0, verified by readback). Per an ADI EngineerZone reply, MPPT overrides UVCLFB,
   which would defeat R3.
9. **Open-BATSENS fallback:** fit about 100 Ω from BATSENS to the EVM-local BAT+, so that an open Kelvin lead
   (150-300 mm on a moving vehicle) falls back to local sensing instead of opening the CV loop. The local point sits
   about 25 mV above pad 18 at 2.5 A, so the fallback errs low (safe). The LTC4015 open-BATSENS behaviour and BATSENS
   input current are UNVERIFIED (G0); bench proof is S1.14.
10. **No repeated top-ups.** Behind D-BT-SQ every input cycle is a POR, so each regen burst and each FC window restarts
    a fresh CC/CV cycle. The max-CV timer (3600 s) and C/x termination never complete across bursts. Firmware therefore
    gates charge enable on V_batt (pin 25) **and** the charger's VBAT readback: no enable above about 8.30 V, with
    re-enable hysteresis TODO(calibrate).

**Wiring (EVM off-board on 150 mm leads, 300 mm absolute; 22-pin header carrier ≤ 32 x 35 mm in the Ag105 holes, with
a ≥ 2.54 mm standoff over D-BT-SQ / C-D11 / C-D12; route away from the LM1084):**

| Ag105 pad | DC2039A (functional) | Wire | Current | Note |
|---|---|---|---|---|
| VIN+ 10 | VIN+ | 20 AWG, twisted with VIN− | ≤ 1.0 A | Loop 10 mΩ → 10 mW |
| VIN− 4 | VIN− / GND | 20 AWG | ≤ 1.0 A | Must be the same copper as BAT− on the EVM (M0) |
| VBAT+ 18+19 | BAT+ | 20 AWG, twisted with BAT− | ≤ 2.5 A | Loop 10 mΩ → 62 mW, 25 mV at 2.5 A |
| VBAT− 14+15 | BAT− | 20 AWG | ≤ 2.5 A | No element in series |
| VBAT+ 18 (second wire) | BATSENS+ | 26-28 AWG, twisted | µA | Kelvin; never to VBT |
| SDA 8 / SCL 7 | SDA / SCL | 26 AWG bundle with GND, 3V3 | – | EVM pull-ups removed, 100 kHz |
| 3V3 (J1.29/30) | DVCC | 26 AWG | < 1 mA | Not the QuikEval 5 V |
| MPPTD 11 | M7 gate input | 26 AWG | µA | `CHG_ENABLE` |
| STAT 3 | SMBALERT | 26 AWG | µA | `INPUT_PULLUP` |
| THERM 13 + J-NTC 2 | NTC / GND | 26 AWG, twisted | µA | 10k B3435 NTC on the pack |

**EVM modifications:**

| # | Change |
|---|---|
| M0 | Confirm VIN−↔BAT− continuity < 5 mΩ, with no jumper, shunt or FET in the path |
| M1 | RSNSB → 12 mΩ 1 % 2512 |
| M2 | RSNSI → 32 mΩ 1 % |
| M3 | CHEM/CELLS straps → Li-ion programmable, 2 cells. Check physically; the factory setting is UNVERIFIED and a 3S strap is a 12.6 V fire path |
| M4 | UVCL divider 150k / 10.0k 0.1 % |
| M5 | Remove the QuikEval/DC590 I2C and SMBALERT pull-ups. Remove or isolate every other on-board SDA/SCL load, including any QuikEval ID EEPROM (UNVERIFIED that one shares the bus; an unpowered device can clamp it). Never connect a DC590 again |
| M6 | DVCC from Teensy 3V3 |
| M7 | On the carrier: Q1 BSS138 (UVCLFB→GND, gate 100k to the EVM's INTVCC and to Q2 drain); Q2 BSS138 (gate = pin 5 via 1k, 47k to GND) |
| M8 | Remove every bulk electrolytic on VIN, SYS and BAT |
| M9 | Keep ≥ 20 µF effective ceramic on SYS (input ripple 0.08-0.16 V p-p at 355 kHz [REC]). Cap the EVM VIN side (upstream of the INFET) at ≤ 10 µF effective. Add a damper at the VIN turret: 10 µF/50 V + 0.15 Ω in series, ∥ 470 nF. Lead + trace ≈ 0.2 µH rings at 65-113 kHz otherwise. The SYS charge is a separate step at INFET turn-on, measured in S1.1 |
| M10 | Confirm no INFET bypass, and the INFET orientation |
| M11 | Keep NTCBIAS 10k; remove any EVM-mounted NTC or fixed resistor |
| M12 | MPPT strap off |
| M13 | ~100 Ω BATSENS → local BAT+ (decision 9) |
| Board | Remove the Ag105 by cutting the pins and taking them one at a time (GND pads have no thermal relief); check barrels. C-D8/C-D10 → 10 µF/50 V X7R 1206. Keep C-D11 (consider 50 V). Keep D-BT-SQ. Amend the IO CSV and add a never-rotated CLAUDE.md bodge record |

**Key computed numbers (estimates; IC parameters [REC]):**

*Inrush during the RT1987 ramp, at 12 mA/µF (only the capacitance upstream of the INFET):*

| Element | Effective C | Inrush |
|---|---|---|
| C-D8 + C-D10 (uprated) | ~12 µF | 0.14 A |
| Damper | ~7 µF | 0.08 A |
| EVM VIN ceramics | ≤ 10 µF | ≤ 0.12 A |
| **Total on the ramped node** | **≤ 29 µF** | **≤ 0.35 A** |

- All-nominal: about 40 µF, 0.48 A, if the EVM VIN ceramics are 10 µF nominal (UNVERIFIED).
- Against the limits: RT1987 start-up limit 2.5 A / 250 µs; OC_FC 1.4 A single sample.

*The SYS step at INFET turn-on (not billed above):* if the INFET turns on after the RT1987 ramp has finished, the RT1987
is already fully on with its protection off ("SCP current limit and shutdown functions are disabled after tON",
DS-00 §17.5). The 20-30 µF of EVM SYS ceramics then charge in a step limited only by the INFET gate slew. In regen it
draws from VCHG-IN plus the 470 µF V-MOT node; in FC mode it draws from the bus, where OC_FC latches on one sample
above 1.4 A. INFET turn-on timing and slew are G0 items, and S1.1 measures this step separately against OC_FC at
FC-mode load. The BQ25713 has the same class of step when ACFET/RBFET turn on after the 50 ms CHRG_OK deglitch [snip].

*CV:*
- 8.400 V is the register maximum (N = 31) and can only be lowered.
- Pack at termination: 8.400 − 0.035 = **8.365 V (−0.42 %)**, not compensable.
- At +1 % CV error the pack reaches 8.449 V, 51 mV under the 8.5 V OV latch. The V_batt ADC error must stay under 51 mV
  (S2.4).

*Charge current and efficiency:*

| Input | Input limit | Charge current | Loss |
|---|---|---|---|
| 16 V (FC) | 1.0 A | 1.75 A (2.5 A not reachable within the FC budget) | ~1.1 W |
| 16 V (FC), recommended until aux is measured | 0.8 A (`IIN` = 50) | 1.39 A | – |
| 21 V (regen) | 1.0 A | 2.35 A | ~1.3 W |
| 21 V, light load (~2 W) | – | – | 85-88 % efficiency (estimate) |

*Thresholds:*

| State | Threshold | Margins |
|---|---|---|
| POR / regen | 19.20 V | +3.2 V over the 16.0 V bus; +1.7 V over firmware OV; 2.2 V below the 21.4 V clamp. **Below** the TPS61288 OVP max (19.5 V, SLVSFP3C p.6), so a failed-FB boost is not covered by this layer (section 2.2) |
| FC | 13.50 V | +0.7 V over the 12.8 V backoff; +1.5 V over the 12.0 V latch |
| Pin 5 LOW | off at any V_IN | – |

*State-99 drain:* ≤ 13 mJ on the switched node, below 19.2 V, so no switching and no latched fault expected.

**Register map, address 0x68 [REC]. Verify every entry before flashing:**

| Register | Value |
|---|---|
| 0x14 CONFIG_BITS | 0x0110 (suspend + meas_sys_on) during config, 0x0010 in run; MPPT bit 3 = 0 always |
| 0x15 IIN | 63 (1.00 A) regen / FC: dynamic, min(50 (0.797 A), budget − I_motor − aux), with the RSNSI ceiling as backstop |
| 0x16 UVCL | 255 (19.2 V) / 179 (13.5 V) |
| 0x1A ICHARGE | 29 (2.50 A); `charge_goal` → 2..29 |
| 0x1B VCHARGE | 31 (4.2000 V/cell) |
| 0x1C C/X threshold | 2048 (0.25 A) |
| 0x1D max CV time | 3600 s |
| 0x29 | 0x0005 (C/x termination + JEITA) |
| 0x0E | 0x0007 (fault alerts) |
| Reads | 0x34 CHARGER_STATE, 0x35 CHARGE_STATUS, 0x39 SYSTEM_STATUS, 0x3B VIN (1.648 mV/LSB), 0x3D IBAT (1.46487 µV / 12 mΩ = 122.07 µA/LSB), 0x3E IIN (45.78 µA/LSB), 0x43 CHEM_CELLS |

Only `EN_LIMIT_ALERTS` = 0x0D was confirmed by a snippet.

**Init per power-up** (lazy, like `pollAg105()`; pin 5 LOW throughout):
1. Probe 0x39. A NAK means retry next tick, with no fault.
2. Read 0x43. Anything other than 2S Li-ion latches the new `ERR_CHG_STRAP` (G6).
3. Write the configuration in suspend.
4. Read back 0x14/15/16/1A/1B and refuse on any mismatch or MPPT = 1.
5. Pin 5 HIGH, then release suspend.
6. Poll IBAT + state at 50 Hz, one transaction per loop tick (≤ 0.5 ms stall).
7. On power loss, clear `ltcConfigured`, set `I_charge` = 0, status 0xFF.

The LTC4015 has **no host watchdog** [REC]. The host-silence stop is pin 5 LOW, then the RT1987s open, and both need a
live host. **A Teensy hardware watchdog (WDOG/RTWDOG) is therefore part of Path A firmware scope.** On a hang it resets
the MCU, the pins go high-Z, and the RT1987 EN pull-downs plus the M7 47 kΩ pull-down make everything safe. The
timeout must exceed the longest legitimate loop stall, TODO(calibrate). Until S2.1b passes, the LTC4015 fails the
section 2.2 host-silence row.

**Cost and time.**
- About USD 190 with one EVM, USD 340 with two. DC2039A about USD 134-176; Mouser about USD 152 with 44 in stock
  (2026-11-05 snapshot, UNVERIFIED).
- About 25-37 engineer-days in total, with a go/no-go after about 5 days (S1.5 + S1.6). This figure covers everything:
  EVM mods and carrier, the Stage 0-3 bench work, and the firmware/HIL/EMS work. The 20-29 eng-days in sections 5.1 and
  6.1 is the firmware/HIL/EMS/Pi share alone. This revision adds about 2-4 eng-days for the MCU watchdog, the I2C
  bus-clear and the V_batt enable gate (estimate).

**Top residual risks:**
1. Every IC number is unverified.
2. Cold-start latency with D-BT-SQ kept (battery detection into a 10 µF node may raise `bat_missing` and exceed 100 ms).
3. UVCL is a regulation floor, not a disconnect.
4. MPPT can defeat R3 in software.
5. Autonomous POR charging (no enable pin): bounded by M1/M2 and held by M7. No host watchdog: needs the MCU watchdog.
6. The CHEM/CELLS strap is the sole overcharge control.
7. A shorted buck high-side FET puts VCHG-IN on VCHG. Only D-BT-SQ plus the OV latch stand in the way.
8. The V-MOT peak above 21.4 V is unmeasured.
9. An open BATSENS lead opens the CV loop unless M13 is fitted (open-lead behaviour UNVERIFIED).
10. The DVCC-from-3V3 SMBus logic may survive a core brown-out and hold SDA low (section 6.1, I2C robustness).

### 4.2 BQ25713EVM-017 on the Ag105 pads: rank 2

Wiring follows the 2026-11-04 note §4, with the corrections in 4.3:

| Ag105 pad | EVM |
|---|---|
| VIN+ | J1 VIN (JP1 on + JP7 top: the board's RT1987s do the input switching) |
| VIN− | J1 GND |
| VBAT+ | J5 BAT |
| – | J6 SYS left open |
| SDA/SCL | J3 |
| STAT | J2 CHRG_OK (3.3 V pull-up) |
| MPPTD | J2 ILIM_control **through an NMOS inverter with a 47k pull-down** (pin 5 HIGH = enable) |

**Mods:**
- 2S: JP2 on, JP3/JP4 off (CELL about 2.7 V).
- Remove the EVM SDA/SCL pull-ups (preferred; leave EVM 3V3 on its own LDO), or remove JP8 and feed J3-3V3 from the
  Teensy. **Inventory every load on EVM 3V3 from the SLUUBT8B schematic first.**
- Depopulate VIN bulk to ≤ 30-40 µF effective ceramic.
- Set the ILIM pin divider in hardware to ≤ 1.0 A, so the bound holds before firmware writes IIN_HOST.
- OTG off (EN_OTG bit and ENZ_OTG pin).
- An **active clamp** on VCHG-IN (zener-referenced FET/SCR at about 24-26 V) until the V-MOT peak is measured. **A plain
  TVS cannot work here:** with V_RWM ≥ 22 V, its clamping voltage is about 35 V at rated current, above the 30 V abs max.
- Board: C-D8/C-D10 → ≥ 35 V.

**Key numbers:**

| Item | Value |
|---|---|
| ChargeCurrent | 64 mA LSB at 10 mΩ; 2.5 A = code 39 (2.496 A), 0.25 A = code 4; POR 0 (SLUSD83C §9.6.3) |
| VINDPM | Code 247 = 19.008 V (0.51 V below the 19.52 V register ceiling); code 161 = 13.504 V. Accuracy −3 %/+2 % [snip] gives 18.44-19.39 V. That clears the 17.5 V firmware OV, but not a failed-FB boost (TPS61288 OVP max 19.5 V); the ceiling rules out a threshold above it (section 2.2) |
| CV | Accuracy about ±0.6 % at 8.4 V [snip]: VCHG 8.35-8.45 V, pack 8.315-8.415 V. **No compensation allowed** |
| Cold start | 50 ms CHRG_OK deglitch [snip] + 12-20 ms board overhead ≈ 65-75 ms (passes 100 ms, fails 30 ms). The "150 ms converter power-up" figure is uncorroborated |
| Input absolute maximum | 30 V (zero margin against the requirement) |
| ACOV | ≥ 25 V min |
| Price and stock | DigiKey DE about EUR 154, NL about EUR 168; TI "limited quantities" (snapshots, UNVERIFIED) |

**Firmware write order on every CHRG_OK rise, from Hi-Z:**
1. WDT 5 s.
2. ChargeVoltage 8.400 V, **with readback**.
3. VINDPM, with readback.
4. IIN_HOST.
5. ChargeCurrent **last** (asserted in firmware).

The IIN default at CHRG_OK is 3.25 A [snip], so this ordering is safety-critical.

### 4.3 The 2026-11-04 BQ25713 note: confirmed and corrected

**Confirmed (no contrary evidence this round):**
- 0-24 V recommended / 30 V absolute maximum.
- ACOV rising 25/26/27 V.
- VINDPM 3.2-19.52 V, 64 mV LSB, reset VBUS − 1.28 V.
- ChargeCurrent 64 mA LSB, POR 0.
- Host-controlled termination.
- Watchdog options 5/88/175 s, default 175 s.
- Address 0x6B.
- 2S strap JP2 on / JP3-JP4 off.
- RAC = RSR = 10 mΩ.
- CHRG_OK open-drain, needs a pull-up.
- The JP8 dead-rail pull-up problem.
- "Charging through D-BT-SQ is expected to work".
- The architecture passes R-GND (SRP/SRN in BAT+, ACP/ACN high-side).

**Corrected:**

| # | Note's claim | Correction |
|---|---|---|
| 1 | VINDPM "~16.5 V vs 15.9 V" as the R3 second layer (§5.3) | **Too low.** The firmware OV is 17.5 V. Regen threshold **19.0 V** (code 247); FC threshold 13.5 V. Even 19.0 V covers only normal regulation and the firmware OV region: a failed-FB boost can hold the bus up to its OVP (18.3 / 19 / 19.5 V, SLVSFP3C p.6), so that case rests on layer 1 and `FAULT_OV_BUS` |
| 2 | Off-switch option "a pull-up on ILIM_control" with the Teensy actively releasing it (§5.1) | **Unsafe with the existing firmware.** Every safe-state write drives pin 5 LOW (setup ~6720, State 99 ~8332, and 7986, 11448, 11472, 11503, 12795, 15304, 15358). Under active-LOW enable each of those becomes an ENABLE. Use only an NMOS inverter with a charger-side pull-down (pin 5 HIGH = enable) |
| 3 | The CMPIN/CMPOUT comparator as a hardware R3 layer (implied by the EVM J4 mention) | **Not independent.** It is on-die, VDDA-powered, re-PORs every input cycle, and its reference/polarity/enable are register bits (UNVERIFIED). An independent layer needs an external comparator on an always-on rail |
| 4 | ACOV "drop-out, no damage" (§2) | **Load-drop hazard:** ACOV disables the converter at the moment V-MOT is highest, removing the charger's load, so V-MOT can rise further toward the 30 V abs max |
| 5 | "TVS if the peak exceeds ~24 V" (implied mitigation) | **Unworkable:** see 4.2. Use an active clamp, required until the peak is measured |
| 6 | Write order | Make it explicit: Hi-Z default until configured, ChargeVoltage with readback, **ChargeCurrent last**. The IIN default is 3.25 A at CHRG_OK, and the NVDC converter may switch with ChargeCurrent 0 to hold SYS, a small bus draw |
| 7 | (omitted) | **Add:** OTG disable; NTC loss (no TS pin, a pack-temperature regression); recommend a BAL-NOK → Hi-Z NMOS hardware OV cut (hardware only; CLAUDE.md's "no BAL-NOK input code" rule still holds) |
| 8 | (omitted) | **Add:** State-99 drain phases no longer bleed energy (the charger does not switch within 10 ms of POR); update the comments |
| 9 | Size (a later dossier claimed the note says the EVM is "far larger than 32 x 35 mm") | The note says no such thing. EVM dimensions are UNVERIFIED |

---

## 5. Path A vs Path B

### 5.1 Comparison

All figures are estimates for one engineer unless cited. The only sourced cost is the BOM's USD 149.66 per board. All
times count from week 0 of the common step and match the one schedule in section 5.2.

**What regen is worth** (estimate, path_b analysis): about 0.7 J electrical per decel, which is about 0.05 s of the
FC's 14.6 W median stack output. RegenTest_v2's six decels come to about 4 J, against about 890 J for 61 s of FC
operation (≈ 0.45 %). Unless the operator rules otherwise (question 3), regen capture is demonstration value: the
research claim, not range. Weigh B2's cost against that.

| Criterion | Path A (EVM on current board, D-BT-SQ kept) | Path A' (as A, D-BT-SQ bridged) | B1 (minimal re-spin) | B2 (bidirectional converter) |
|---|---|---|---|---|
| Time to first safe charge | Weeks 4-8 (S4a) | Weeks 4-8 | Weeks 8-14 (S5; 1-2 fewer if A proved the driver) | ~4-6 months bench, 5-9 months integrated |
| Time to regen harvest | Weeks 6-10, **partial at best** (tail-only if M1 is slow) | Weeks 6-10; latency set by S1.6b (no POR, no battery detect per burst) | Weeks 10-16; partial unless the B1+ additions are fitted | 5-9 months, **full by construction** |
| FC charging | Yes, single-source FC window; within the H-20 budget (standstill / low demand) | Same | Same | Yes, as a direct FC current command |
| Firmware / HIL / EMS effort | ~20-29 eng-days (+2-4 for watchdog, I2C, V_batt gate) | Same, minus the per-burst re-config | ~23-37 eng-days | ~63-95 eng-days plus several campaigns |
| Hardware effort | Carrier or leads; C-D8/C-D10 swap; pull-ups; pin-5 inverter; mounting | As A, plus a D-BT-SQ bridge | ~2-4 weeks design | ~8-14 weeks, likely 2 spins |
| Cash | EVM ~EUR 154-179 (BQ25713) / ~USD 152 (DC2039A) + parts | Same | ~USD 1-2k for 5 boards | ~USD 2-4k |
| Risk to the only working board | **Real**: desoldering a 22-pin module with un-relieved GND pads over D-BT-SQ/C-D11/C-D12, on a board that may be incident-damaged | Same | None; creates spares | None to the old board; high bring-up risk to the new one |
| Bring-up risk | Low-moderate (RT1987 interaction, inrush budget, SYS step) | As A | Moderate (one new switching stage) | High (two new power stages; motor-node switch must conduct both ways, so the pre-charge/hot-plug rules need redesign; bus rises in regen with a full pack, so a clamp is mandatory) |
| Battery-side protection | D-BT-SQ is a firmware hard disconnect against a shorted charger high-side FET | **Lost:** a shorted high-side FET puts VCHG-IN on the pack, with only the charger and the 8.5 V latch in the way | Charger's own BATFET | Converter design |
| Keeps calibrated platform | Yes | Yes | Yes (K_SNS rework and coefficient regeneration if INA253A3 is fitted) | No: share loop, governor, HIL plant, DP/SDP and campaigns I/II re-derived. Needs an operator exception to "What NOT to change" |
| R3 hazard | Remains, firmware + charger threshold (layer 2 does not cover a failed-FB boost) | Same | Remains unless the B1+ additions are fitted | Removed by construction |
| What it teaches the others | Chooses and proves the B1 charger IC; measures M1 and the V-MOT overshoot that set B1's ratings | Measures the BAT-on-pack latency B1 would get | Spare boards for risky B2 prototypes | – |

**B1 scope** (path_b analysis, 23 items). It folds in:
- the Ag105 VBat- tie (fixed by the new charger);
- the BT output-capacitor layout;
- RD1 215k (16 V bus) and RC-BT 61.2k;
- 100 nF CSS on D-MT-EN;
- 10k EN pull-downs;
- INA253 A1 vs A3 (operator choice);
- encoder pins 14/15, 2.2k pull-ups and the 74HC14 (fitted);
- OPA197 on 5 V;
- the V_rgn divider (reads 0.85x);
- Teensy supply OR-ed from bus and battery;
- BQ29200 OUT driving a hardware charge inhibit;
- a STAT pull-up;
- ≥ 35 V charger-input capacitors;
- a single pack-negative bond;
- a stronger braking clamp;
- bidirectional battery current sense.

D-BT-SQ orientation is not a defect (refuted from the .brd); its role is an operator choice. The analysis recommends the
charger's BAT pin directly on the pack with the charger's own BATFET, which keeps registers and removes battery detection
from the cold-start chain.

**B1+** (optional) adds a hardware VCHG-IN comparator holding the charger in Hi-Z, plus a threshold-select FET. That lets
the charger stay powered from V-MOT between bursts. It needs an R3 ruling. These parts are not re-spin-only: they can
sit on the Path A carrier (an always-on rail and a VCHG-IN tap are both available at the Ag105 pads and J1).

### 5.2 Recommended sequencing

| Step | When (estimate) | Board risk | Output / gate |
|---|---|---|---|
| G0 Allow www.ti.com, www.analog.com (and www.monolithicpower.com) in session network settings. Read SLUSD83C, SLUUBT8B, the LTC4015 datasheet, and the DC2039A Demo Manual + schematic | Week 0 | None | Every [REC]/[snip] item in sections 4.1-4.2 confirmed or corrected; R-GND on both EVM schematics |
| S0 Board health checks (Stage 0, section 7) | Weeks 0-1 | Low | Is the current board still a valid Path A host? |
| S1 Two EVMs standalone (Stage 1) | Weeks 1-3 | None | **G1:** charger IC chosen; regen-feasibility numbers with D-BT-SQ kept (S1.6) and bridged (S1.6b); A, A' or B1 chosen |
| S2 Optional B2 control prototype in State 98 (FC current command via the MDAC) + HIL leg | Weeks 1-4, parallel | Low | Informs B2; needs an operator exception |
| S3 Minimal driver + host tests (shared by A and B1) | Weeks 2-4 | None | Ported guards G1-G6 |
| S4a **If Path A / A':** integration, FC charging first, regen behind the v38 interlock (regen weeks 6-10) | Weeks 4-8 | Medium (desolder) | First vehicle charge; V-MOT overshoot measurement |
| S4b **If Path B1:** schematic and layout with the S1 IC, B1+ footprints as no-fit | Weeks 3-8 | None | Gerbers, adversarial design review against the bodge records |
| S5 B1 fab and bring-up (charger block first, boosts scope-armed) | Weeks 8-14 | None to old board | Clean boards and spares |
| G2 B2 decision | After S2 (and S5 if B1) | – | Research-value ruling only |

**How the options compare on their own merits:**
- **B1** has the best risk-to-value: both goals, no risk to the existing board, spares, and the calibrated platform kept.
- **Path A** is fastest to an FC charge. **A'** buys regen latency at the cost of the battery-side hard disconnect.
- **B2** is the only route to full regen without an R3 compromise, for a regen worth about 0.7 J per decel.

---

## 6. Ramifications

### 6.1 Firmware (`teensy_controller/teensy_controller.ino`, HEAD = fw v37 rev 2; line numbers by grep, not built)

**Path A** swaps the driver behind about 10 functions. The rest of the system sees only `I_charge` (float) and
`ag105_status_raw` (byte).

| Area | Lines | Change |
|---|---|---|
| Pins 5, 6 | 1984-1985 | `MPPT_DISABLE` → `CHG_ENABLE` (active HIGH). `CHARGER_STAT` → `CHG_ALERT` (LTC4015) or CHRG_OK (BQ25713, meaning "input good"). **CSV first**, then a never-rotated CLAUDE.md bodge record |
| Ag105 constants | 2453-2484 | Replaced by the new register map |
| MPPT threshold manager | 2487-2580, 3827-3877, 15683-16062 | About 400 lines become a per-power-up threshold write + readback. The EPROM budget and ratchet go; the windowed V_chg idea survives as a readback check |
| Telemetry | 2659, 7637-7700 | v4 / 58 B unchanged if the driver translates status to an Ag105-style byte at offset 51 and puts the new charger current in `I_charge` (offset 19) |
| HIL frames | 4402-4490, 4666, 16081-16105 | Injection offsets 34/38, observation offset 15; unchanged under translation |
| `J` session | 4961-5183, 11204-12110 (~900 lines) | Structure kept; register reads, the as-found latch and the profile write replaced. Termination moves to firmware. Watchdog keepalive added for BQ25713 |
| `chargingControl()` | 15289-15557 | Structure kept (bootstrap on intent, readiness gating); the v38 regen interlock still required |
| `pollAg105()` + I2C transport | 15598-15682, 16064-16230 | Transport rewritten; power gating, lazy config and stale-clear kept |
| Faults | 7435-7449 | GENSTAT latch remapped to the new fault bits; new `ERR_CHG_STRAP` |
| State-98 keys `4`, `N`, `J` | 8581-8864 | Retargeted |
| `doState99()` phases 1-2 | ~8306-8333 | The "bleed into the charger" premise is void; update the comments and decide whether to keep the pulses |
| MCU hardware watchdog (new) | `setup()` / `loop()` | Teensy 4.1 WDOG/RTWDOG armed early in `setup()`, fed once per loop iteration. Timeout above the longest legitimate stall (EEPROM commit, SD close), TODO(calibrate). The reset-reason string at ~9651 already reports a watchdog boot |
| I2C robustness (new) | transport | The firmware sets no Wire timeout today (grep finds none; Teensy 4 Wire library internal timeout behaviour TODO(verify: PJRC)). Add a bounded transaction timeout, plus a 9-clock bus-clear and re-init on any stuck SDA. Reason: the charger loses VIN at the end of every burst while firmware polls at 50 Hz, so a brown-out mid-transaction is routine (about 2.5 % per burst at a 0.5 ms transaction every 20 ms). LTC4015 DVCC fed from the always-on 3V3 may keep its SMBus logic alive through a core brown-out and hold SDA low; the DC2039A QuikEval ID EEPROM may share SDA/SCL (UNVERIFIED); a hung Wire call stalls `detectFaults()` |
| Charge-enable V_batt gate (new) | `chargingControl()` | No enable above about 8.30 V on V_batt or the charger's VBAT readback, hysteresis TODO(calibrate) (section 4.1 decision 10) |
| FC-window IIN (new) | `chargingControl()` | IIN written as budget − I_motor − aux each window; FC windows restricted to standstill / low demand until the EMS ruling. `FC_CHARGE_ALLOWED` stays 0 until that ruling |
| Unchanged | `chargerHasPower()` 16244, `assertFcChargeEnable()` 12743, share loop, governor | – |

**Guards port:**

| Guard | Change |
|---|---|
| G1 bus-side source current | Raise 1.0 A → about 1.6 A for a healthy 1.0 A-in charge, TODO(calibrate) |
| G2 unaccounted power | Credit term now from charger-measured IIN x VIN (LTC4015) or the ADC/IBAT (BQ25713) |
| G3 | Charger fault bits |
| G4 | Reboot-only trip latch, unchanged |
| G5 | `AG105_VBATN_ISOLATED` becomes a "charger return verified" gate (`CHG_RETURN_VERIFIED`), default 0 on real boards, holding REGEN LOW in Run |
| G6 (new) | Cell/strap readback |

The "drop REGEN first, no serial before the pins" ordering stays.

**Effort:**

| Work package | Path A | Path B (B2) |
|---|---|---|
| Minimal bench driver | 4-6 d | 6-10 d |
| Full Run integration | 8-12 d | 25-40 d |
| HIL/EMS model update | 7-10 d + 1 campaign | 25-35 d + several campaigns |
| Pi bridge | 0 with status translation, 1 with v5 | 7-10 d |
| **Total** | **~20-29 eng-days** | **~63-95 eng-days** |

**Path B2** removes the charger code, changes what the FC_CHARGE/REGEN switches mean, and rebuilds the share loop around
an FC current command (operator exception). It also redesigns MOT_PWR pre-charge for a bidirectional switch, moves CV/CC
limits into firmware, needs bidirectional battery sense, and forces a telemetry bump.

### 6.2 Tests

- `test/test_main.cpp` has 499 test functions. 60 are charger/MPPT/`J`-named, and about 1340 lines reference Ag105 symbols.
- **Path A:** rewrite 35-45 functions and delete about 6-10. That covers the 26 `test_mppt_*`, 6
  `test_hil_wiring_pollag105_*`, `test_ag105_*`, `test_poll_ag105`, `test_genstat_fault`, `test_j_*`, and the
  pin/FW_VERSION pins.
- `mock_wire.h` assumes the Ag105's status-byte-first protocol, so it needs a register-addressed responder.
- **New behavioural tests:** write order (ChargeCurrent last / suspend until verified), MPPT readback refusal, strap
  refusal, pin-5 LOW on every stop path before serial, threshold readback before enable, the watchdog armed in
  `setup()` and fed per iteration (mock), the Wire timeout plus bus-clear on a scripted stuck-SDA responder, no enable
  above the V_batt gate, and the dynamic FC-window IIN.
- **Path B2:** additionally the governor harnesses (`gov_ceiling_harness`, `gov_fw28_harness`), selector and hot-plug
  tests.
- Run all three targets per CLAUDE.md §9 plus the encoder harness.

### 6.3 HIL / EMS models

- **Plant and suite:** `tools/hil_plant_sim.py` holds the Ag105 status machine, settle time and current-ramp constant.
  `tools/run_hil_suite.py` has about 11 charge/regen/ftp75c legs plus `charge_edges_safe`.
- **Charger efficiency:** `ETA_CHG_DEFAULT` (`charger_power.py:50`) and `ETA_CHG` (`hil_electrical.py:543`) = 0.88. It is
  already an era key, so Path A is a parameter change followed by DP/SDP/MPC re-solves.
- **The FC-mode charge ceiling changes.** About 1.4-1.75 A with a 1.0 A input ceiling on the LTC4015 mockup, against the
  Ag105's 2.5 A profile, and only at standstill. In cruise the FC alone carries motor plus charger (BT_BUS is forced
  OFF in a window), so the charger gets the H-20 budget (about 1.247 A bus) minus aux minus I_motor. The EMS
  charge-economics constants (lambda, alpha) need re-deriving on that budget, and whether FC charging returns at all
  (`FC_CHARGE_ALLOWED`, 0 in fw v31-v37) is an EMS ruling.
- **Path B2:** new plant layout, DP/SDP, governor and walk.

### 6.4 Pi bridge and protocol

- `teensy_bridge_node_2026-10-31A.py` asserts 58 B (line 86), passes byte 51 through as `/vehicle_state[12]`, and its EKF
  treats `I_charge` as battery-side (lines 217-244). No EMS node decodes the status bits.
- **No bump is forced with status translation.** Recommend folding a charger-type id and `charger_flags` into the
  already-approved v5 bump (fw37 planning §4), so logs show which charger produced byte 51. Use the `protocol-bump`
  skill.
- BLG has no charger field and is unaffected.

### 6.5 Safety rules

- **R3** stays mandatory on Path A and B1: layer 1 firmware detector + layer 2 charger threshold + layer 3 guards. The
  charger threshold is a regulation loop on every shortlisted candidate. It counts as layer 2 only after the S1.5 bench
  proof.
- An always-powered charger at bus level is the option fw37 §3.3 already rejected. Any change needs an explicit operator
  ruling (question 1).
- **Death-5:** no electrolytic on VCHG-IN; ≤ about 50 µF effective on the RT1987-ramped node (VCHG-IN + EVM VIN
  upstream of the input FET); the SYS step at input-FET turn-on happens after the RT1987's SCP is disabled (DS-00 §17.5)
  and is bounded only by the FET slew, so it is measured separately (S1.1) against the OC_FC single-sample latch; no
  switching during the RT1987 ramp; never leave REGEN closed while MOT_PWR opens (V-MOT drain → hot-plug).
- **Host silence:** add the Teensy hardware watchdog (S2.1b). The Pi watchdog does not cover a hung Teensy.
- **Overcharge:** the charger CV is the sole real-time control. Verify the strap/CV by readback before every enable,
  and gate enable on V_batt (about 8.30 V). The hardware backstop is late and slow: BQ29200 VPROTECT is 4.35 V/cell =
  **8.70 V pack** (SLUSA52C p.1, p.5), above the 8.5 V firmware latch. Its delay is set by CD: 9 s/µF nominal
  (6-12 s/µF at 0-60 °C, SLUSA52C p.5) x CBLD 0.33 µF (BOM line 85) ≈ **3.0 s (2.0-4.0 s)**. Recommend BAL-NOK →
  charger Hi-Z in hardware (Path A carrier, or B1). On reachability, the .brd has **no trace, via or test point** on
  BAL-NOK: the net is BAL pad 8 (OUT) alone, on the SON-8 DRB package. A Path A carrier mod therefore needs a fly-wire
  soldered to that pad.
- **Reset window:** the pin-9 level does **not** disable OVP. CB-DISABLE goes to BQ29200 `CB_EN` (schematic pin
  `!CB_EN`), and per SLUSA52C p.1 CB_EN enables or disables cell balancing only; OVP detection and OUT are independent
  of it. A BAL-NOK → Hi-Z cut would therefore stay active through an MCU reset. (Pin 9 has no external pull. During a
  true reset its level is the i.MX RT pad default, UNVERIFIED, until `setup()` applies `INPUT_PULLUP`.)
- **Pin changes go into the IO CSV first.** The board diverges from the 2026-06-22 schematic, so add a never-rotated
  hardware record to CLAUDE.md.

### 6.6 Bench procedures

- Every powered step uses a scope on VCHG-IN and VCHG and a clamp on the battery lead.
- Log events with the `bench-incident` skill into `docs/boost-bringup-debug.md`.
- First vehicle engagement in a BENCH_TEST 1 build with `CHG_RETURN_VERIFIED` 0.
- **Mounting (Path A):** the EVM is off-board on 150-300 mm leads, on a moving vehicle. Plan before Stage 3:
  - a location clear of the drivetrain and wheels, with a cover;
  - mounting on standoffs with vibration-damping grommets, using the EVM's mounting holes (dimensions UNVERIFIED, a G0
    item);
  - strain relief at both ends: carrier and EVM terminals, with leads tie-wrapped to the chassis;
  - the twisted pairs kept apart from the motor phase leads.

  Stage 3 row S3.0 checks lead retention.

---

## 7. Gates and staged bench plan

**Gates:**

| Gate | Pass criterion |
|---|---|
| **G0 Documents** | Primaries read for the chosen EVMs. R-GND confirmed on the EVM schematic. Register map, POR defaults, abs max, input-threshold range/accuracy, start-up timing, input capacitor BOM, EVM dimensions and mounting holes, and every on-board SDA/SCL load (including any QuikEval ID EEPROM) transcribed. **LTC4015 make-or-break:** UVCL register/divider interaction (if the register cannot lower the divider threshold, use the section 4.1 decision-3 fallback), VIN abs max, battery-detect timing, RSNSB/RSNSI full-scale voltages, INFET turn-on timing and slew, open-BATSENS behaviour. **No purchase before G0** |
| **G-S0 Board health** | All Stage 0 rows pass. A board failure means Path A integration is not worth the desolder, so B1 is chosen. **Any pack anomaly blocks every charging path** until the pack is replaced |
| **G1 Path chosen** | S1.0-S1.5, S1.8 and S1.14 pass. S1.6 and S1.6b decide regen: S1.6 ≤ 100 ms means regen is in scope for Path A; S1.6b ≤ 100 ms with S1.6 > 100 ms points to A' (by ruling) or B1; both > 100 ms means FC-only for A, and B1+ additions or B2 for regen |
| **G-S2 Board control** | Stage 2 passes before any Run use |
| **G-S3 Release** | S3.3 V-MOT peak ≤ 30 V and S3.1 zero bus-to-charger energy. Then `CHG_RETURN_VERIFIED` = 1 in a committed build with the CLAUDE.md record |

**Stage 0: pre-integration damage checks** (current board; Ag105 removed only after 0.1-0.4 pass, otherwise decide B1
first)

| # | Check | Pass |
|---|---|---|
| 0.1 | 1-2 A resistive load on the bus, both sources on | I_fc ≈ half the load (±25 %) |
| 0.2 | FC only (BT_BUS off), 0.5 A load | Bus holds and I_fc ≈ load. "Reads 0, bus holds" = sense/ADC damage; "collapses" = FC boost or D-FC-EN damage. Stop on either |
| 0.3 | D-BT-SQ (estimated 11-13 A for 0.3-0.5 s against an 8 A rating) | Reverse blocking: EN LOW with the pack connected and **VCHG loaded with 1 kΩ** (after Ag105 removal only C-D11 remains on VCHG, and a 10 MΩ DMM on a floating node can read volts from leakage alone). Pass VCHG ≤ 0.1 V: the leakage maximum of 60 µA (DS-00 p.7, at VOUT 32 V) gives ≤ 60 mV across 1 kΩ, while a shorted FET reads about pack voltage. Forward drop at 1 A and 2 A: 35-60 mV. EN controls it |
| 0.4 | D-BC-RG, D-MT-EN (8-11.4 A for about 0.2 s) | Same three checks. Soft-start ramp, **10-90 %**, at 16 V: 1.07 ms ±20 % (DS-00 §17.3 formula, 5.6 nF; the tolerance is a bench allowance, not a datasheet figure) |
| 0.5 | Ag105 pads after removal (cut pins, one at a time) | Barrel continuity VIN+, VBAT+, GND to their nets < 0.1 Ω |
| 0.6 | Bench supply | Record current limit and what latched in ML0227 |
| 0.7 | J-BT / J-BL pack-negative bonds | J-BT terminal torque checked |
| 0.8 | Pack: per-cell voltages and balance at rest (balance lead, DMM) | Both cells within the pack datasheet's range; imbalance recorded, pass criterion TODO(calibrate) against a pre-incident reading if one exists |
| 0.9 | Pack internal resistance (DC step, 1-2 A) | Compared with the ~24 mΩ pack-plus-connector estimate from ML0227; a material rise is an anomaly |
| 0.10 | Pack swelling and temperature (visual, calipers, IR at rest and after a 1 A discharge) | No swelling, no hot cell |
| 0.11 | Pack datasheet maximum charge rate (question 8) | Obtained. If 11-13 A for ~1 s exceeds it, the pack is retired regardless of 0.8-0.10 |
| 0.12 | Teensy pins 5, 6, 18, 19 (GPIO) | Pins 5 and 6 drive HIGH/LOW (DMM) and read back correctly as inputs; pins 18/19 idle at 3.3 V with the pull-ups, toggle under a State-98 I2C scan, and show no leakage to GND (> 1 MΩ, power off) |
| 0.13 | Pin 38 divider and ADC (R1-CHG 78.7k / R2-CHG 10k) | Divider ratio measured by DMM; ADC reading within 1 % of DMM at 2 known VCHG-IN levels |
| 0.14 | BQ29200 OUT response (bench cell simulator on the balance lead) | OUT goes high when either cell is above 4.35 V, after a delay consistent with CBLD 0.33 µF (≈ 2.0-4.0 s, SLUSA52C p.5); OUT low below threshold |

**Stage 1: EVM standalone** (bench supply 16 V/1.5 A limit → RT1987 with 5.6 nF CSS → modified EVM → spare RT1987 as
D-BT-SQ stand-in → 2S pack with protection board; current probe on VIN, scope VIN/VCHG; I2C from a spare 3.3 V Teensy)

| # | Test | Pass / fail |
|---|---|---|
| S1.0 | Mods done. VIN−↔BAT− < 5 mΩ. Sense resistors 4-wire within ±2 %. Straps photographed | All yes, else stop |
| S1.1 | Inrush at 16 V and 21 V, ramp and input-FET turn-on measured **separately** | RT1987 ramp: peak ≤ 0.8 A; 10-90 % ramp 1.07 / 1.40 ms ±20 %; no RT1987 SCP retry. **INFET/ACFET turn-on step** (after tON, with the RT1987 fully on and its SCP disabled, DS-00 §17.5): timing relative to the ramp recorded; peak input current with the FC-mode load present (aux plus the S1.9 charge) ≤ 1.4 A minus a margin, TODO(calibrate), so that one 1 kHz sample can never latch OC_FC. Repeat with a 470 µF + bus-level source to represent V-MOT |
| S1.2 | POR, enable LOW, 21 V | I_BAT ≤ 10 mA (LTC4015: UVCLFB < 0.1 V; BQ25713: Hi-Z) |
| S1.3 | Readback of cell/chem, threshold, CV, MPPT/OTG | Exact. Fail on anything other than 2S Li-ion |
| S1.4 | Enable at 21 V, 2.5 A target | CC 2.50 A ±5 % (clamp); IBAT readback within ±3 % of the clamp; I_in at or below the hardware ceiling ±5 % |
| S1.5 | **R3 floor:** stiff 15.8 V, threshold 19.0/19.2 V, enabled, 60 s | Average I_in ≤ 20 mA; I_BAT ≤ 10 mA; VIN oscillation < 0.2 V p-p. **Fail = the candidate cannot provide R3 tier 2** |
| S1.6 | **M1 latency:** input step 0 → 21 V through the stand-in (8 ms tD_ON + 1.75 ms ramp), pack 7.6 V behind the D-BT-SQ stand-in, config at power edge + 20 ms; 20 repeats at 0.5 s bursts | Edge → I_BAT ≥ 90 % of set: ≤ 30 ms target, ≤ 100 ms hard; ≥ 18/20 within the burst. Record `bat_missing` / CHRG_OK events |
| S1.6b | **M1 latency, D-BT-SQ stand-in bridged (gated, G1 input):** as S1.6, with the charger BAT on the pack and the charger kept configured between bursts where the part allows | Same pass criteria. This is the measurement that separates Path A from A' / B1 for regen |
| S1.7 | Abrupt input loss mid-CC, then re-apply | No latched fault; clean restart; VCHG overshoot < 2 V |
| S1.8 | CV / termination near full | Pack 8.36-8.40 V at C/10; never > 8.45 V |
| S1.9 | FC mode: threshold 13.5 V, input limit ≤ 0.8-1.0 A, supply with 2 Ω series | Input ≥ 13.3 V; I_in within limit; no hunting > 0.3 V p-p |
| S1.10 | Software traps: set MPPT (LTC4015) / OTG (BQ25713) | Driver detects on readback and refuses / trips |
| S1.11 | NTC open, then 10k at 25 °C | Open: paused (LTC4015) or documented behaviour. 25 °C: charges |
| S1.12 | Light-load efficiency, 21 V, 0.25 A | Record; ≥ 80 % is a goal, not a gate |
| S1.13 | (BQ25713) watchdog 5 s expiry; Hi-Z on enable LOW | ChargeCurrent → 0 within 5-6 s; Hi-Z stops input draw |
| S1.14 | (LTC4015) open BATSENS mid-charge, near CV, with M13 fitted | VCHG stays ≤ 8.45 V; record behaviour without M13 only if safe (current-limited supply) |
| S1.15 | VIN cut mid-I2C-transaction, 100 times (scripted, spare Teensy) | No Wire call stalls over 1 ms; no latched bus (SDA released or recovered by the bus-clear); clean reconfigure on the next power-up |

**Stage 2: Teensy control on the real board** (State 98, no motor; CSV amended; BENCH_TEST 1; `CHG_RETURN_VERIFIED` 0)

| # | Test | Pass / fail |
|---|---|---|
| S2.1 | Boot / reset / reflash with FC_CHARGE/REGEN LOW | Pin 5 LOW throughout (scope through reset) |
| S2.1b | **Forced hang** (a State-98 test key that spins without feeding the watchdog) with FC_CHARGE or REGEN HIGH, pin 5 HIGH, charger charging at 0.5 A | Watchdog reset; FC_CHARGE/REGEN and pin 5 fall to LOW through the pull-downs; charger input current → 0 within the host-silence requirement (≤ about 5 s; target ≤ the watchdog timeout + RT1987 turn-off) |
| S2.2 | I2C with the charger unpowered | SDA/SCL idle at 3.3 V; no clamp; clean NAK |
| S2.3 | `J` replacement, bus-fed at 0.5 A, attended | G1/G2/G3 silent. Charger IBAT ≈ ΔI_batt ±10 %. Bus-side ≤ 0.9 A. Injected G2 fault trips in ≤ 20 ms with REGEN dropped first |
| S2.4 | V_batt (pin 25) vs DMM at CV | Within 30 mV; no OV_BATT nuisance trip at termination |
| S2.5 | State-99 drain pulses with charger wired | No hang; reconfigures afterwards |
| S2.5b | I2C brown-out on the real board: drop FC_CHARGE mid-poll 100 times | No stall over 1 ms in the loop; bus-clear recovers any stuck SDA; `detectFaults()` cadence unbroken |
| S2.6 | FC window via `assertFcChargeEnable()` (test build with FC charge allowed) | I_fc inrush ≤ 1.0 A; no OC_FC; bus ≥ 13.3 V |

**Stage 3: vehicle integration** (on stands)

| # | Test | Pass / fail |
|---|---|---|
| S3.0 | EVM mounting and leads | EVM in its mounted position, clear of the drivetrain; leads strain-relieved at both ends; pull test on each lead; no chafe after a stands run |
| S3.1 | Run with the v38 interlock, cruise | Charger I_in ≈ 0 whenever V-MOT < threshold; G2 log at baseline (zero bus-to-charger energy) |
| S3.2 | Braking bursts (RegenTest_v2 profile) | ≥ 75 % of bursts reach 90 % current within 100 ms; energy per decel recorded against the ~0.7 J estimate |
| S3.3 | V-MOT peak with the charger loading it | Record. **Fail if > 30 V** |
| S3.4 | Release | `CHG_RETURN_VERIFIED` = 1, committed with the bodge record |

---

## 8. Open questions

**Operator:**
1. **R3:** may a charger stay powered from V-MOT between bursts behind an independent hardware comparator holding it in
   Hi-Z, with the charger threshold as layer 2? This is the only route to near-full regen without B2. fw37 §3.3 rejected
   the variant without the hardware comparator.
2. **Desolder risk:** is risking the only working board acceptable after Stage 0 passes? If not, that settles the G1
   choice for B1, which also stands on its own merits (section 0).
3. Is B2 (retiring the droop-share hardware basis) inside the thesis timeline, or is regen a demonstration-level goal?
4. D-BT-SQ: keep it (this document's Path A default), or put the charger's BAT pin on the pack (B1 recommendation)?
5. BAL-NOK → hardware charge inhibit (Path A carrier or B1)? The BQ29200 trips at 8.70 V pack (4.35 V/cell, SLUSA52C
   p.5), above the 8.5 V firmware latch, after ≈ 3.0 s (2.0-4.0 s) with CBLD 0.33 µF. On Path A it needs a fly-wire to
   BAL pad 8, since the .brd has no trace, via or test point on BAL-NOK. The pin-9 / `CB_EN` level does not disable OVP
   (balancing only), so the cut stays active through an MCU reset.
6. INA253A3 or keep A1 on B1 (A3 forces coefficient regeneration and HIL recalibration)?
7. FC-mode charge ceiling: accept about 1.4-1.75 A (1.0 A input) on Path A?
8. A bench pack datasheet (maximum charge current, protection board), and whether an NTC is fitted on J-NTC. This now
   also gates Stage 0 row 0.11.
9. FC charging: does it return at all (`FC_CHARGE_ALLOWED` is 0 in fw v31-v37), and if so, only at standstill / low
   demand, or in cruise with a dynamic IIN = H-20 budget − I_motor − aux?
10. Where the EVM mounts on the vehicle (section 6.6).

**Measurements:**
- The V-MOT peak above 21.4 V (sets abs max and capacitor class).
- The FC-mode aux and droop budget.
- As-built copper weight; C-D8/C-D10 capacitance under DC bias.
- Teensy reset pad state.
- Whether D-BT-SQ has a second 8 ms tD_ON when it leaves UVLO.
- Thermal effect near the LM1084 (moot if off-board).
- The pack's per-cell voltages, internal resistance and condition after ML0227 (Stage 0 rows 0.8-0.11).

**Vendors** (all `TODO(verify: <doc>)`):
- **LTC4015 (G0 make-or-break first):** UVCL mechanism (register lowers only, or higher-of?), VIN abs max, battery-detect
  timing, RSNSB/RSNSI full-scale voltages, INFET turn-on timing and slew; then SMBus address, POR codes, CV accuracy,
  INTVCC on the DC2039A, MPPT default, open-BATSENS behaviour and BATSENS input current, host watchdog (absence),
  unpowered and brown-out SDA/SCL behaviour with DVCC on. **DC2039A:** schematic R-GND, stock
  RSNSB/RSNSI, CHEM/CELLS factory strap, input/SYS capacitors, INFET bypass, QuikEval ID EEPROM on SDA/SCL, board
  dimensions and mounting holes.
- **BQ25713:** VINDPM accuracy at 19 V, CV accuracy (primary), CMP default bits, the "150 ms converter power-up" claim,
  ChargerStatus address. **SLUUBT8B:** J1-GND = J5-GND, EVM 3V3 loads, VIN capacitor BOM and voltage ratings.
- **Silvertel:** location of the Ag105 current-sense shunt (closes the mechanism); MPPTD-LOW semantics during charging.
- **Richtek RT1987 OVP recovery:** DS-00 is internally inconsistent. The p.7 table says tBLK_OVP "Latch off. No
  restart", Table 1 (§17.4) says "Auto-restart with soft-start at fault removal", and §17.7 says re-enable by toggling EN
  or cycling VIN. `TODO(verify: Richtek)`. With POVP grounded (33 V min) a V-MOT overshoot could latch D-BC-RG off
  silently: **FLTB is not wired to the Teensy** (no FLTB net on any RT1987 in the .sch). Mitigation: firmware toggles
  EN after any suspected OVP, which layer 1 does anyway on every burst.
- **PJRC:** Teensy 4 Wire library timeout behaviour; i.MX RT pad default state during reset (pins 5, 9).

---

## 9. Sources

**Board and repo (read):**
- `references/Scale_Car_Board_20260624.sch` (Eagle XML)
- `references/Scale Car Board PCB 20260625.brd`
- `references/Scale Car Design PCB BOM 20260622.csv`
- Teensy IO CSV
- `teensy_controller/teensy_controller.ino` fw v37 rev 2
- `docs/boost-bringup-debug.md` (2026-11-04)
- `logs/ML0227.BLG`
- `docs/fw37_planning_2026-11-04.md` §3-§4
- `docs/bq25713_charger_replacement_2026-11-04.md`
- `docs/respin_power_architecture_2026-11-04.md`
- `references/EMS/Pi_2026-11-03/teensy_bridge_node_2026-10-31A.py`

**Datasheets (read, primary):**
- Silvertel Ag105 DS V1.1 (Nov 2021): p.3 Fig. 1, p.4 Table 2, p.6, p.9, p.10, p.18, p.19
- Richtek RT1987 DS-00: p.7 (IOUT_LK 45/60 µA, tBLK_OVP, POVP 33 V, VFWD, VFRC, tD_ON, tON), p.14, §17.3 (tON formula),
  §17.4 Table 1, p.16, §17.5 (SCP disabled after tON), §17.7 (OVP re-enable)
- TI TPS61288 SLVSFP3C: p.6 (VOVP 18.3/19/19.5 V, hysteresis 600 mV)
- TI bq29200 SLUSA52C: p.1 (CB_EN = cell balancing enable), p.5-6 (VPROTECT 4.35 V; XDELAY 9 s/µF nominal, 6-12 at
  0-60 °C)
- BOM line 85: CBLD 0.33 µF (BQ29200 CD)

**Candidate documents (NOT read this round; blocked domains):**
- TI BQ25713 SLUSD83C (read in full by the 2026-11-04 note author): https://www.ti.com/lit/ds/symlink/bq25713.pdf
- TI SLUUBT8B BQ2571x EVM UG: https://www.ti.com/lit/ug/sluubt8b/sluubt8b.pdf
- TI BQ25720 SLUSDU3; SLUUC74 (BQ25720/23 EVM UG)
- TI BQ25773 SLUSEK7; BQ25770G SLUSFK8; SLUUCY2; SLUUD24
- TI BQ25798 SLUSDV2 (rev B Jan 2023, rev C Jun 2026): https://www.ti.com/lit/ds/symlink/bq25798.pdf;
  SLUUCB5E: https://www.ti.com/lit/ug/sluucb5e/sluucb5e.pdf
- TI BQ24650 SLUSA75B: https://ti.com/lit/gpn/BQ24650; SLUU444A: https://www.ti.com/lit/pdf/sluu444
- ADI LTC4015 datasheet (Rev B); DC2039A Demo Manual Rev D (www.analog.com)
- ADI LTC4162-L datasheet Rev A; DC2038A Demo Manual Rev 0
- MPS MP2759 datasheet: https://www.farnell.com/datasheets/3632066.pdf;
  EV2759A-Q-00A: https://www.mouser.com/pdfDocs/EV2759A-Q-00A.pdf

**Secondary and tertiary (web-search snippets; UNVERIFIED):**
- TI E2E threads 1253760 (BQ25720 ACOV/abs max), 1069290 / 1361735 / 1223984 / 1442252 / 1120720 / 1263980 / 1567805
  (BQ25798/BQ25792 VINDPM and watchdog), 736482 / 1006381 / 463141 / 798998 (BQ24650)
- ADI EngineerZone 103969 (LTC4015 battery detect; MPPT overrides UVCLFB), 113945 / 111362 / 120107 / 547879 / 539432
  (LTC4162)
- MPS forum t/3775 (MP2759 OVP)
- element14 forum 32191 (BQ24650EVM D1)
- Linux `drivers/power/supply/ltc4162-l-charger.c` (raw.githubusercontent.com/torvalds/linux): register addresses and
  IBAT scaling, read
- Distributor snapshots (DigiKey, Mouser, element14/Farnell, Arrow), 2026-11-05

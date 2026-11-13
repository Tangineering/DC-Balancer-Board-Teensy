# Re-screen of the 2026-11-05 charger candidates for the custom-board form factor (2026-11-10)

## 0. Scope, sources and evidence rules

### 0.1 Scope

This file re-screens every charger that the 2026-11-05 evaluation considered, under one changed constraint: the charger
now sits on a custom PCB that plugs into the 22 Ag105 holes on pin headers and may extend sideways past the
32.0 x 34.8 mm footprint. The charger IC, its power stage and the hardware interlock all go on that board, and reflow
assembly is available. Usable off-the-shelf evaluation-module (EVM) hardware is therefore no longer a screening criterion.

For each part the file separates two classes of reason behind the earlier rejection or downgrade:

- **form-factor reasons**: EVM availability or stock, EVM modifications, EVM input capacitance, EVM pull-up rails, EVM
  jumper defaults, EVM size or off-board mounting, and the as-built configuration of a demo board;
- **IC-intrinsic reasons**: missing telemetry or I2C, restart and detection behaviour, input-voltage-regulation (VINDPM)
  ceiling and power-on-reset (POR) behaviour, sense location, voltage rating, current capability and watchdog behaviour.

Form-factor reasons are void on the custom board. IC-intrinsic reasons stand. A part reopens only when its rejection rested
mainly on form-factor reasons.

### 0.2 Sources

- `docs/charger_replacement_evaluation_2026-11-05.md` (round-2 decision document; sections 0.2-0.4, 1.1-1.3, 2.5, 3.2-3.4,
  6.4) [EVAL].
- The round-1 revision of [EVAL] (commit `5557937`, section 3.1 "Screened and rejected" and section 3.2 shortlist)
  [EVAL-R1].
- Round-2 dossiers in `docs/reviews/charger_eval_2026-11-05/round2/`: `dossier_BQ25798.md`, `dossier_BQ25713.md`,
  `dossier_BQ25773.md`, `dossier_BQ25720.md`, `dossier_A2.md` (BQ25731), `dossier_LTC4015.md`, `dossier_A1.md`
  (BQ25756), `dossier_BQ24650.md`, `dossier_MP2759.md` [R2-<part>].
- Round-1 dossier `docs/reviews/charger_eval_2026-11-05/dossier_ADI_LTC4162_L_LAD__...md` [R1-LTC4162] and
  `path_b_respin.md` section 5.2 [PATHB].

### 0.3 Evidence rules

No datasheet was re-read for this file. Every IC fact below is carried from a round-2 dossier, which cites the primary
datasheet by literature number and page; the citation is repeated in the form "(SLUSxxx p.N via R2)". These facts are
primary-cited but not re-verified in this round. Every fact that comes from round 1 (where no primary was readable) or
from [EVAL-R1] section 3.1 is marked **UNVERIFIED**. No web fetch was made, so there are no blocked fetches from this
task.

Status codes follow [EVAL] section 1.2: P = PROVEN_DATASHEET, C = PROVEN_CALC, B = BENCH_GATE, F = FAIL, U = UNKNOWN,
sys = blocked at system level.

### 0.4 Re-screen categories

| Category | Meaning |
|---|---|
| reopen-finalist | The earlier downgrade rested mainly on form-factor reasons; the IC-intrinsic record is at least as strong as the baseline on one hard requirement. A full dossier is recommended |
| reopen-possible | Form-factor reasons are removed, but an IC-intrinsic question remains open or a primary was never read. Screen it again in the wide search before a dossier |
| unchanged-keep | The part stays in its earlier position (baseline, runner-up or sibling); the custom board removes its EVM conditions but does not change its rank |
| unchanged-reject | The rejection rested on IC-intrinsic reasons that the custom board does not change |

## 1. Cross-cutting consequences of the custom board

### 1.1 Conditions that disappear for every part

The custom board removes the following classes of condition from every round-2 dossier:

1. EVM fail-safe defects: grounded /CE jumpers, EVM pull-up rails fed from VBUS or VBAT that back-power the Teensy, and
   multi-cell jumper defaults (BQ25798 M1-M6, BQ25713 R26, BQ25773 JP4 at 4S, BQ25756 JP13 and 7S divider, MP2759 3S
   straps, LTC4015 on-board PIC master).
2. EVM input capacitance above the RT1987 hot-plug budget (H8). On the custom board the input capacitance is a design
   choice, bounded below only by the datasheet minimum of the IC.
3. Off-board mounting, lead inductance and the two-board split of the round-3 design (carrier plus EVM interface board).
4. EVM stock (H11). IC stock and package replace it as the availability criterion.

### 1.2 Conditions that remain for every part

The custom board does not change the following, because they are set by the motherboard or by the system:

1. **D-BT-SQ stays in series.** The Ag105 VBAT+ pads (18, 19) are VCHG, upstream of the D-BT-SQ ideal diode. A custom board
   in the 22 holes cannot reach the pack except through D-BT-SQ. Every finding that depends on D-BT-SQ (BQ25798 BAT 2.5 V
   hold P1, BATOVP cycling P2, LTC4015 and LTC4162 battery detection, register loss on input cycling) is architectural.
   Bridging D-BT-SQ is a motherboard rework, independent of the custom board.
2. **HR2 purge collapse, the FC input budget and the VESC cut-off (M-R3).** These are system blockers for every candidate
   ([EVAL] section 3.4, section 6.4 item 1).
3. **The warm-response and inhibit-latency unknowns.** No TI, ADI or MPS dossier found a primary figure for warm response
   or inhibit-exit latency ([EVAL] section 0.2). These stay bench gates for every part.
4. **The MCU hardware watchdog** (ruling 5) applies to every part.

### 1.3 The 35 V input-rating requirement against the earlier H6 rule

The 2026-11-10 brief requires an input rating of 35 V or more. [EVAL] H6 required an absolute maximum of 30 V or more, with
36 V preferred. Under the new reading, four parts that passed H6 fail on IC absolute maximum:

| Part | VBUS absolute maximum (via R2) | Against 35 V |
|---|---|---|
| BQ25798 (baseline) | 30 V; 24 V operating (SLUSDV2C p.7 via R2) | Fails |
| BQ25713 | 30 V (SLUSD83C p.9 §8.1 via R2) | Fails |
| BQ25720 | 32 V (SLUSDU3 p.8 via R2) | Fails |
| BQ25731 | 32 V; 26 V operating (SLUSE66A p.8 via R2) | Fails |
| BQ24650 | 33 V VCC (SLUSA75B §7.1 p.5 via R2) | Fails |
| LTC4162-L | 36 V (UNVERIFIED, round-1 web summary) | Passes by 1 V if confirmed |
| LTC4015 | 40 V; OVLO 37.7 V minimum (LTC4015 Rev B p.3-4 via R2) | Passes |
| BQ25773 | 45 V; ACOV 33 V default (SLUSEK7 p.8, p.17 via R2) | Passes |
| MP2759 | 45 V; OVLO 35-37 V (MP2759 DS Rev 1.0 p.5-6 via R2) | Passes |
| BQ25756 | 85 V; 70 V operating (SLUSEN5A via R2) | Passes |

On the custom board a sub-35 V IC can sit behind an input protection stage (eFuse with overvoltage cut-off, or a TVS plus
series switch). The round-3 carrier already carries a TPS26630 eFuse on VCHG-IN ([EVAL] section 0.1a). This is a design
decision for the main document: either the 35 V figure applies to the IC pin, or it applies to the custom-board input with
a protected IC behind it. The baseline BQ25798 passes only under the second reading.

## 2. Re-screen table: round-2 primaries and round-1 dossiers

| Part | 2026-11-05 status | Form-factor part of the earlier reasoning | IC-intrinsic part of the earlier reasoning | New status |
|---|---|---|---|---|
| BQ25798 | Chosen (Path A), FEASIBLE_W_COND | Stock EVM not fail-safe (JP17 /CE to GND, R42 pull-up to EVM LDO, TLV76033 back-powering); 11 EVM mods; off-board mount; EVM 25 V caps; round 1 "practical refuted: custom carrier needed" | 30 V abs max, 24 V operating; POR charges at 1 A with VINDPM = VBUS0 - 1.4 V; ILIM pin possibly sampled only at qualification (P6); /CE holds BAT near 2.5 V (P1); BATOVP cycling (P2); 7-minute poor-source lockout; watchdog field contradictions (P7); ICHG default conflict | unchanged-keep (baseline) |
| BQ25713 | Runner-up, FEASIBLE_W_COND | EVM ILIM pull-up to EVM 3V3; 94.5 µF EVM input C with 33 µF tantalum; C25 16 V part; off-board mount | VINDPM ceiling 19.52 V; VINDPM re-measure "right before the converter is enabled" (retention across Hi-Z exit undocumented, gate B3); AUTO_WAKEUP_EN = 1 at POR (128 mA self-charge); PTM bits; 30 V abs max; 150 ms cold start | unchanged-keep (runner-up, 35 V caveat) |
| BQ25773 | Alternate, FEASIBLE_W_COND; round 1 rank 5 "refuted (practical)" | Round 1: "16 A-class over-design" and an EVM mod that tied VSYS to BAT; round 2: JP4 ships at 4S, 167.6 µF EVM input C, EVM pull-ups to a VBAT/VIN-fed LDO, EVM size | Intrinsically fail-safe POR (CHARGE_CURRENT 0, EN_AUTO_CHG 0, VINDPM 3.2 V); VINDPM 3.2-27 V; FRC_CONV_OFF comparator path with 1 µs deglitch; 45 V abs max; 226 ms cold start; registers persist in battery-only mode; REG0x30 holds EN_PTM beside FRC_CONV_OFF; quasi dual-phase power stage | **reopen-finalist** |
| BQ25720 | FEASIBLE_W_COND, "adds nothing"; round 1 rank 4 "refuted (practical): 12-week lead, 4-5 units per region" | EVM lead time and regional stock; EVM pull-ups; EVM board size | Same 19.52 V VINDPM ceiling as BQ25713; VBUS no-load measurement before converter enable; SMBus 0x09; ADC 25 ms per channel; 32 V abs max | unchanged-reject (sibling, no advantage) |
| BQ25731 (A2) | FEASIBLE_W_COND, "adds nothing"; round 1 screened out | Round 1 rejection rested on "EVM appears out of stock" (UNVERIFIED then; corrected in round 2); round 2: 113.5 µF EVM input C, EVM pull-ups, off-board mount | 19.52 V VINDPM ceiling; 32 V abs max; watchdog expiry loads 256 mA; POR CHRG_INHIBIT = 0; POR ChargeCurrent 0 vs 256 mA contradiction; VINDPM re-measure risk R-1; no BATFET (a simplification) | unchanged-reject (same ceiling as BQ25713; round-1 reason void, round-2 reason stands) |
| LTC4015 | FEASIBLE_W_COND, "plausible"; round 1 rank 1 | DC2039A 120 µF electrolytic (2.3-2.9 A inrush); on-board PIC16F1459 I2C master and DVCC source; UVCL divider at 9 V; board outline unknown, off-board mount; distributor pages unreachable (EVM stock U) | No pin-level inhibit (UVCLFB pull-down is a regulation-loop zero, not converter-off); no host watchdog; leaving `suspend_charger` costs a 2-4 s battery detection; minimum ICHARGE and IIN codes are non-zero; `en_jeita` default overrides ICHARGE_TARGET; UVCL POR = divider maximum (safest POR of all candidates); 40 V abs max; external FETs; coulomb counter | **reopen-finalist** |
| BQ25756 (A1) | FEASIBLE_W_COND, ranked below the TI NVDC parts; round 1 parked as "10 A / 5 mΩ class, oversized" | Round 1: oversized EVM; round 2: stock EVM charges autonomously (JP13, 7S divider, 10 A ICHG, 8 A ILIM); 217 µF EVM input C | Every hard stop restarts cold (12 ms deglitch, about 40 ms SW toggle, typical 145-175 ms); C_IN >= 80 µF after derating is a datasheet requirement; /CE, ILIM_HIZ and ICHG pins are register-defeatable; no zero-current register (ICHG clamped at 400 mA); 40 s minimum watchdog; VAC_DPM 4.2-65 V not reset by watchdog; 85 V abs max | reopen-possible |
| BQ24650 | UNDETERMINED, rejected | EVM 76 x 76 mm off-board; EVM CV 12.6 V; EVM JP2 LED pull-ups to VIN | No I2C, no ADC, no watchdog; no runtime charge-current or input-current control (H5b F); every MPPSET < 75 mV release costs 1.5 s; 33 V abs max | unchanged-reject |
| MP2759 | NOT_FEASIBLE | EVB "VIN < 20 V" note (hot-insertion ringing, not a rating); EVB 63.5 x 63.5 mm; EVB 3S straps; EVB LED pull-ups to 5 V and VIN; stock unknown | No I2C, no ADC (H12 F natively); VLIM off threshold (0.6-1.0 V) shares the pin with the 1.2 V reference; re-enable about 175 ms; charges out of POR; no watchdog; ICC recommended maximum 3 A | unchanged-reject |
| LTC4162-L (round 1 only) | Round 1 rank 8, "showstopper" | DC2038A carries a SAM D21 MCU on the I2C bus; demo board size; EVM input C UNVERIFIED | 2-4 s battery detection per charge cycle that cannot be disabled (UNVERIFIED); no charge-enable pin (UNVERIFIED); 36 V abs max (UNVERIFIED); about 3.2 A maximum at 10 mΩ (UNVERIFIED); primary datasheet never read | reopen-possible (primary read first) |

## 3. Per-part notes

### 3.1 BQ25798 (baseline, unchanged-keep)

The custom board removes every EVM condition of [EVAL] section 4.2 (modifications M1-M7, M9-M11), the EVM interface board
and the off-board leads. It does not remove the IC-intrinsic findings of the panel and critic rounds: P1 (BAT held near
2.5 V with /CE high, SLUSDV2C p.33 via [EVAL]), P2 (BATOVP triangular cycling, SLUSDV2C p.33), P5 (VAC_OVP POR 7 V), P6 (ILIM
pin sampling, §7.3.4.3 p.27 vs pin table p.5), P7 (watchdog reset contradictions, p.25, p.60, p.65, p.70) and C6 (poor-source
lockout, §7.3.4.2 p.27, §7.3.13.1.3 p.51). P1 and P2 are D-BT-SQ consequences and stay architectural (section 1.2). Its 30 V
absolute maximum fails a strict 35 V reading (section 1.3). It stays the baseline against which every reopened part is
scored.

### 3.2 BQ25713 (runner-up, unchanged-keep)

Its downgrade rested on two IC-intrinsic facts: the 19.52 V VINDPM ceiling (SLUSD83C p.12 via R2) and the undocumented
retention of a host-written VINDPM across a Hi-Z exit (§9.3.3.2 p.25 via R2; gate B3). The EVM conditions (R26 pull-up, input
capacitance, C25) were all removable and do not change the rank. The 30 V absolute maximum fails a strict 35 V reading. The
custom board gives no reason to move it above the BQ25798.

### 3.3 BQ25773 (reopen-finalist)

The round-1 rejection ("16 A-class over-design", and a struck EVM modification that tied VSYS to BAT) and most round-2
conditions (JP4 at 4S, 167.6 µF EVM input C, EVM pull-up rail, unknown EVM size) are form-factor reasons. On a custom board
the power stage is sized for 3-4 A, the cell strap is fixed at 2S and the input capacitance is chosen.

Its IC-intrinsic record is the strongest of the TI set on HR5 and on the 35 V requirement:

- POR CHARGE_CURRENT 0, EN_AUTO_CHG 0, no non-volatile memory (SLUSEK7 Table 7-2 p.31, p.63, p.77 via R2);
- POR VINDPM 3.2 V, re-measured only on host request or power-up (§7.3.12 p.39, §7.3.1 p.27 via R2);
- VINDPM 3.2-27 V in 20 mV steps, ±1 % at 18 V (p.12, p.66 via R2), so the regen threshold can sit above the TPS61288
  OVP maximum;
- a µs-class converter-off path: independent comparator plus FRC_CONV_OFF, 1 µs deglitch (§7.3.4 p.30, REG0x30 p.96 via
  R2), in addition to ILIM_HIZ < 0.4 V (p.6, p.20, §7.3.14 p.40 via R2);
- 45 V absolute maximum, ACOV 33 V default (p.8, p.17, p.76 via R2);
- 1 mA-class ADCs for VBUS, IIN, IBAT, VBAT, VSYS (p.15, pp.80-93 via R2).

The intrinsic costs are a 226 ms cold start (§7.3.1 p.27 via R2; always-powered architecture mandatory, as for every TI
part), register persistence in battery-only mode when VCHG exceeds VBAT_UVLO (§7.3.1 p.27 via R2), EN_PTM and SYSOVP_MAX in
the same register as FRC_CONV_OFF (write as a full constant), a watchdog kicked by any CHARGE_CURRENT write (§7.3.26.1 p.47
via R2), and FRC_CONV_OFF pulling CHRG_OK LOW (§7.3.4 p.30 via R2). The layout cost is the largest of the set: a quasi
dual-phase buck-boost with two inductors and seven DFN5x6 FETs on the EVM, including a BATFET (SLUUCY2 BOM via R2).
Whether a single-phase or BATFET-less build is permitted is TODO(verify: SLUSEK7 application section). A full custom-board
dossier is recommended.

### 3.4 BQ25720 (unchanged-reject)

Round 1 rejected the EVM on lead time and regional stock (form-factor). Round 2 kept it as a sibling that adds nothing over
the BQ25713: same 19.52 V ceiling, the same pre-enable VBUS measurement (SLUSDU3 §9.3.7 p.28 via R2), 25 ms per ADC channel,
SMBus. These are IC-intrinsic, so the custom board does not reopen it.

### 3.5 BQ25731 (unchanged-reject)

The round-1 screening reason ("EVM appears out of stock", UNVERIFIED) was form-factor and was already corrected in round 2.
The round-2 reason is IC-intrinsic: the 19.52 V ceiling (SLUSE66A §9.6.21 p.79 via R2), the watchdog that loads 256 mA on
expiry (§9.3.21.1 p.33 via R2), POR CHRG_INHIBIT = 0, and a 32 V absolute maximum. The absence of a BATFET simplifies the
custom board but does not change HR4/HR5 relative to the BQ25713.

### 3.6 LTC4015 (reopen-finalist)

Most of the round-2 conditions were DC2039A conditions: the 120 µF electrolytic, the PIC master and DVCC source, the 9 V
UVCL divider, the unknown outline and off-board mount, and the unreachable distributor pages. All of these are void on the
custom board, where the external FETs, RSNSB and RSNSI, the VC compensation network and the input capacitance are design
choices.

The IC-intrinsic record has one property no TI part has: the UVCL threshold resets at POR to the divider maximum
(VIN_UVCL_SETTING default 0xFF; LTC4015 Rev B p.22, p.60 via R2), so a divider strapped at about 19 V makes every charger
POR regen-only, and the FC window needs a deliberate I2C write. This also covers the HR4 FC-after-POR case without a
mode-switched input ceiling (R2 correction C13). Other intrinsic facts carried from R2: 40 V absolute maximum, OVLO
37.7/38.6/39.5 V (p.3-4, p.41); high-side RSNSI and RSNSB; no soft-start or re-qualification on a UVCL release while VIN
stays 100 mV above BATSENS; estimated inhibit latency 160 µs with the stock VC network and about 7 µs with a 10 nF VC
capacitor (R2 estimate from gm(UVCL) 1.06 mS, p.7, p.42; not a datasheet figure).

The intrinsic costs stand: no pin-level converter-off (the UVCLFB pull-down is a regulation-loop zero), no host watchdog
(register map pp.49-54 via R2), a 2-4 s battery detection on every exit from `suspend_charger` and on every VIN rise
(p.30 via R2), non-zero minimum ICHARGE and IIN codes (p.5, p.60), and `en_jeita` = 1 at POR overriding ICHARGE_TARGET
(p.33, p.60, p.63). The battery detection interacts with D-BT-SQ (section 1.2 item 1); R2 recommended a D-BT-SQ bridge, which
is a motherboard rework. HR1 charge current of 3.1 A or more needs RSNSB of about 10 mΩ or less (32 mV full scale implied by
R2 mod E2: 12 mΩ gives 2.67 A; TODO(verify: LTC4015 Rev B p.22)). A full custom-board dossier is recommended, with the
detection-versus-D-BT-SQ question as its first item.

### 3.7 BQ25756 (reopen-possible)

The round-1 parking reason ("10 A / 5 mΩ class, oversized") and the round-2 EVM conditions (autonomous charging as shipped,
217 µF input C) are form-factor reasons. Its strengths are intrinsic: VAC_DPM 4.2-65 V in 20 mV steps, not reset by the
watchdog (SLUSEN5A via R2), four hardware stop pins, high-side sense on both sides, and an 85 V absolute maximum.

The reason it ranked low is intrinsic and the custom board does not remove it: every hard stop exits cold (typical
145-175 ms, Fig 7-3, Fig 7-7 via R2), so the H1 comparator cannot gate a stop pin per burst. The custom board does make the
R2 options W2 (an analog warm inhibit holding ILIM_HIZ at about 3.0 V inside the 2.0-3.7 V regulation band) and W3 (a
latched detector that trips ACUV) buildable, but both are off-label and W3 departs from the loop-analysis permit formulation.
The C_IN >= 80 µF requirement (§5.3 via R2) remains; on the custom board it can sit behind a dv/dt-limited eFuse, which
turns the H8 conflict into a design item. It also has the BQ25756E sibling (60 V abs max, 36 V operating) and the
round-1 parked siblings in section 4. Re-screen in the wide search; a full dossier only if W2 has a primary basis.

### 3.8 BQ24650 (unchanged-reject)

The EVM size and EVM defaults are void, but the rejection rested on intrinsic facts: no I2C, no runtime charge-current or
input-current control (§8.3.3 via R2), and a 1.5 s delay on every MPPSET release (EC p.9 via R2). The custom board can add
an I2C current monitor for H12, but not runtime current control. The 33 V absolute maximum also fails a strict 35 V
reading. Its resistor-strapped threshold that survives POR is a useful reference property.

### 3.9 MP2759 (unchanged-reject)

The EVB "VIN < 20 V" note, the EVB size and the EVB pull-ups are void. The NOT_FEASIBLE verdict rested on intrinsic facts:
no I2C or ADC, the VLIM off threshold sharing the regulation pin (MP2759 DS Rev 1.0 p.8, p.14, p.18 via R2), a 175 ms
re-enable (EVB p.9 via R2), autonomous charging out of POR (DS p.13 via R2) and no watchdog. The ICC recommended maximum of
3 A (DS p.5 via R2) is also below the 3.1 A requirement. The custom board can carry an I2C monitor and the precision warm
clamp of R2 section 4, but the clamp adds a single-fault loop path 70 mV from full current.

### 3.10 LTC4162-L (reopen-possible, primary first)

The round-1 rejection rested partly on the DC2038A (SAM D21 on the I2C bus, board size) and partly on R3 as written then,
under which every burst was a cold start. R3 has since been replaced by the always-powered architecture ([EVAL] ruling 3),
so a per-burst detection no longer applies if the charger stays in its input-regulation loop between bursts. The remaining
questions are intrinsic and UNVERIFIED: whether detection re-runs on a UVCL release, the absence of an enable pin, a 36 V
absolute maximum, and a charge-current ceiling of about 3.2 A (monolithic). Its primary datasheet was never read. Fetch it
before any further screening.

## 4. Re-screen table: round-1 screened-and-rejected list ([EVAL-R1] section 3.1)

All reasons in this table are round-1 text and UNVERIFIED unless a round-2 dossier later read the primary.

| Board / part | Round-1 reason | Reason class | New status | Note |
|---|---|---|---|---|
| BQ25731EVM / BQ25730EVM | EVM out of stock | Form-factor | unchanged-reject | Reopened in round 2 as A2; see section 3.5 |
| BQ25703A | Superseded by BQ25713 | Intrinsic (same envelope) | unchanged-reject | Same family ceiling |
| BQ25792 | Merged into BQ25798 (same register set) | Neither | unchanged-keep (second source) | Differences from BQ25798 not read: TODO(verify: BQ25792 datasheet). Useful as a stock hedge for the baseline |
| BQ24610 / BQ24617 | No input-voltage regulation | Intrinsic | unchanged-reject | |
| BQ24630 | LiFePO4 algorithm | Intrinsic | unchanged-reject | |
| BQ25756(E), BQ25750, BQ25758(A), BQ25820 | "10 A / 5 mΩ class, oversized" | Form-factor (EVM power rating) | reopen-possible | The custom board sizes the stage. BQ25756 restart behaviour (section 3.7) may be shared; UNVERIFIED for the siblings. Screened in the wide search (screening.md) |
| BQ25672 | EVM existence UNVERIFIED; input range conflicts | Mixed | reopen-possible (low) | Input-range conflict is intrinsic if confirmed; primary not read |
| BQ24725A, BQ24780S, BQ25710 | No VINDPM / older / SMBus sibling | Intrinsic | unchanged-reject | |
| BQ25887 | 3.9-6.2 V input | Intrinsic | unchanged-reject | |
| LT3652 (DC1568A, DC1688A) | 2 A ceiling, wrong float | Intrinsic | unchanged-reject | Below 3.1 A |
| LT3651-8.4 (DC1484A-A) | No input-voltage regulation found | Intrinsic (UNVERIFIED) | unchanged-reject | No I2C |
| MAX77960 / MAX77961 | Abs max, VINDPM, ICHG UNVERIFIED; USB-C centric | Missing primary; EV kit orientation | reopen-possible | Screened in the wide search (screening.md) |
| LT8490 (DC2069A), LT8491 (DC2703A) | Oversized, 12 V SLA, slow P&O MPPT | Mostly demo-board configuration | reopen-possible (LT8491 only) | LT8490 has no I2C (UNVERIFIED). Whether the LT8491 can run a fixed input-voltage regulation without P&O, and its restart behaviour, are UNVERIFIED |
| LTC4013, LTC4020, LTC4000 | Wrong as-built configuration / needs an external front end | Form-factor (demo-board configuration) | reopen-possible (low) | No I2C on any of the three (UNVERIFIED); H12 then needs an added monitor, and H5 runtime current control needs an analog set-point. Screen in the wide search |
| MAX17702, MAX8903, MAX1873, LT3741 | Lead-acid / 1-cell / obsolete / not a charger | Mostly intrinsic | unchanged-reject | Whether "lead-acid" described the MAX17702 IC or its EV kit configuration is UNVERIFIED; screened in the wide search (screening.md: lead-acid controller, no I2C, UNVERIFIED) |
| MP2760 (EV2760) | 22 V operating maximum | Intrinsic | unchanged-reject | |
| MP2619, MP26123 | 2 A at 24 V | Intrinsic | unchanged-reject | Below 3.1 A |
| RT9490 | VAC_OVP POR 7 V blocks the input until an I2C write | Intrinsic, but shared with the baseline | reopen-possible | The BQ25798 has the same 7 V VAC_OVP POR ([EVAL] P5) and was kept by grounding ACDRV. The reason does not separate RT9490 from the baseline |
| RT9492 | Abs max and MIVR UNVERIFIED; availability unknown | Missing primary; EVB availability | reopen-possible | Round 1 named it the fallback if the BQ25798 failed its VINDPM check |
| RT9467 | 1-cell | Intrinsic | unchanged-reject | |
| ISL9241 / ISL9238 / ISL9237 / ISL95522A | <= 20-23.4 V operating, out of stock, or no EVB | Mixed | unchanged-reject | The operating ceiling is intrinsic and below the 35 V requirement; re-check only if a Renesas part with a higher rating appears |
| SC8815 / SC8886S / SC8885S / SC89890 | No official EVB; sense location UNVERIFIED | Form-factor | reopen-possible | On the custom board the sense location is a layout choice where the IC allows high-side sense. Screened in the wide search (screening.md) |
| CN3722 (modules) | Primary unread, no I2C, module GND UNVERIFIED | Intrinsic (no I2C) | unchanged-reject | |
| CN3795 | 2 A | Intrinsic | unchanged-reject | |
| IP2368, IP2326 | USB-PD SoC / 5 V boost | Intrinsic | unchanged-reject | |
| EV2672, EV2731, MP2733, MP26029; HL7061 / HL7015; SY69xx; EVAL6924D; MCP73213; LC709511 | Wrong input class, 1-cell, <= 2 A, linear, obsolete or unobtainable | Mostly intrinsic | unchanged-reject | Which entries were "unobtainable" only is not recorded; the Halo and Silergy entries should be re-checked by the wide search |
| NXP / Toshiba | No 2S, 15-22 V, >= 2 A EVB found | Form-factor (EVB search) | reopen-possible (search item) | Not a specific part |
| Generic BQ24650 modules | Merged into BQ24650 | - | unchanged-reject | |
| SparkFun, DFRobot, Waveshare, Mikroe Balancer 5 | 1S, lead-acid or 5 V boost | Intrinsic | unchanged-reject | |
| TP5100 | 20 V abs max | Intrinsic | unchanged-reject | |
| XL4015 / LM2596 modules | Low-side shunt in OUT- | Module architecture; the ICs are not chargers | unchanged-reject | |
| AH2167 / SY6912A modules | 22 V operating maximum | Intrinsic | unchanged-reject | |
| Genasun GV-5, Victron 75/10 | No 2S profile | Intrinsic | unchanged-reject | |
| Adafruit / Seeed / Pololu / Olimex / Vertiq | No 2S high-input charger | Catalogue | unchanged-reject | |

## 5. Reusable IC-intrinsic facts with primary citations (from the round-2 dossiers)

The figures below are cited in the round-2 dossiers to the primary datasheet page. They were not re-read for this file.

| Part | Fact | Citation (via round-2 dossier) |
|---|---|---|
| BQ25798 | ILIM_HIZ < 0.75 V stops switching, > 1 V resumes | SLUSDV2C §7.3.4.3 p.27; Table 5-1 p.5 |
| BQ25798 | VINDPM 3.6-22 V / 100 mV, ±2 % at 18.6 V; not reset by REG_RST or watchdog | SLUSDV2C p.12, p.62, Table 7-17 p.62, §7.3.4.4 p.27 |
| BQ25798 | Watchdog minimum 0.5 s; STOP_WD_CHG = 1 clears EN_CHG on expiry | SLUSDV2C Table 7-26 p.72, Table 7-20 p.65 |
| BQ25798 | Abs max VBUS 30 V, SYS 23 V, BAT 20 V; VBUS 24 V operating; VBUS_OVP 25.2 V minimum | SLUSDV2C p.7, p.9 |
| BQ25798 | Cold start: REGN about 150 ms after VBUS_PRESENT | SLUSDV2C §7.3.4 step 5 p.26 |
| BQ25713 | VINDPM 3.2-19.52 V / 64 mV, -3/+2 % at 18.688 V; POR "VBUS no-load - 1.28 V" | SLUSD83C p.12, §9.3.3.2 p.25 |
| BQ25713 | Converter power-up 150 ms after VBUS | SLUSD83C §9.3.3 step 5 p.24 |
| BQ25713 | PTM turns ILIM_HIZ low into pass-through | SLUSD83C §9.4.3 p.32 |
| BQ25773 | POR CHARGE_CURRENT 0, EN_AUTO_CHG 0 | SLUSEK7 Table 7-2 p.31, p.63, p.77 |
| BQ25773 | VINDPM 3.2-27 V / 20 mV, ±1 % at 18 V; POR 3.2 V | SLUSEK7 p.12, p.66 |
| BQ25773 | FRC_CONV_OFF with CMP_DEG 1 µs | SLUSEK7 §7.3.4 p.30, REG0x30 p.96 |
| BQ25773 | Converter powers up 226 ms after VBUS > VVBUS_CONVEN | SLUSEK7 §7.3.1 p.27 |
| BQ25773 | Abs max 45 V; ACOV 33 V default | SLUSEK7 p.8, p.17, p.76 |
| BQ25720 | ILIM_HIZ < 0.4 V HIZ, > 0.8 V exit; POR ChargeCurrent 0 A | SLUSDU3 p.6, p.19, §9.6.2 p.45 |
| BQ25731 | Watchdog expiry loads 256 mA; ChargeCurrent POR contradiction | SLUSE66A §9.3.21.1 p.33, Table 9-8 p.42, p.45 |
| BQ25731 | VINDPM 3.2-19.52 V / 64 mV | SLUSE66A Table 9-7 p.40, §9.6.21 p.79 |
| LTC4015 | UVCL POR = divider maximum (0xFF), register can only lower it | LTC4015 Rev B p.22, p.60 |
| LTC4015 | Battery detection 2-4 s, then 1-2 s open/short test | LTC4015 Rev B p.30 |
| LTC4015 | Minimum ICHARGE 1 mV/RSNSB, IIN 0.5 mV/RSNSI (no zero code) | LTC4015 Rev B p.5, p.60 |
| LTC4015 | VIN abs max 40 V; OVLO 37.7/38.6/39.5 V | LTC4015 Rev B p.3-4, p.41 |
| LTC4015 | INFET reverse turn-off -30 mV, t_off 2 µs | LTC4015 Rev B p.6, p.18 |
| BQ25756 | VAC_DPM 4.2-65 V / 20 mV, reset only by REG_RESET or POR | SLUSEN5A §6.5 via A1 |
| BQ25756 | C_IN >= 80 µF after derating | SLUSEN5A §5.3 |
| BQ25756 | Typical /CE-enable to current about 145 ms; VAC plug-in to current about 175 ms | SLUSEN5A Fig 7-7, Fig 7-3 (figure reading) |
| BQ25756 | ICHG_REG clamped low at 400 mA | SLUSEN5A Table 6-10 |
| BQ24650 | MPPSET < 75 mV disables; 1.5 s delay after MPPSET > 175 mV | SLUSA75B p.4, EC p.7, EC p.9 |
| MP2759 | VLIM off 0.6/0.8/1.0 V; reference 1.18/1.20/1.22 V; 170 ms DC/DC delay after ACOK | MP2759 DS Rev 1.0 p.7-8, p.13 |

## 6. Summary for the wide search

1. Two parts reopen as finalists for full custom-board dossiers: **BQ25773** (intrinsically fail-safe POR, 27 V VINDPM,
   45 V rating, µs-class comparator off-path; cost: the hardest power-stage layout of the set) and **LTC4015** (UVCL POR at
   the divider maximum, 40 V rating, external FETs, coulomb counter; cost: no pin converter-off, no host watchdog, and the
   2-4 s battery detection against D-BT-SQ).
2. The following entries reopen for screening only: BQ25756 and its parked siblings (BQ25750, BQ25758(A), BQ25820), LTC4162-L,
   MAX77960/61, LT8491, RT9490, RT9492, the Southchip set, and LTC4013/LTC4020/LTC4000 at low priority.
3. The baseline BQ25798 and the runner-up BQ25713 keep their positions, but both fail a strict 35 V IC-rating reading
   (section 1.3). The main document must decide whether a protected input stage on the custom board satisfies the 35 V
   requirement.
4. No part was rejected in round 2 for a reason that was purely form-factor. The round-1 list holds most of the
   form-factor rejections.

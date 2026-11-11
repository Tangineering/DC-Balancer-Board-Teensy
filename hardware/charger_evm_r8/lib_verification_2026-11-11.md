# Charger carrier r8: footprint and pinout verification against manufacturer drawings

Date: 2026-11-11. Scope: KiCad 9.0 stock footprints in
`C:\Program Files\KiCad\9.0\share\kicad\footprints`, compared pad by pad with the manufacturer
package drawings and land-pattern examples. All dimensions are in millimetres. A "span" is the
distance between the pad centres of opposite rows; "outer" and "inner" are the pad-edge distances
from the package centre line.

## 1. Summary table

| # | Part | Package code | Stock footprint chosen | Pinout verdict | Land-pattern verdict | Source |
|---|------|--------------|------------------------|----------------|----------------------|--------|
| 1 | TPS26630RGER | RGE0024H (VQFN-24, 4 x 4, 0.5) | **Change to** `Package_DFN_QFN:Texas_RGE0024H_VQFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm_ThermalVias` (candidate `VQFN-24-1EP_4x4mm_P0.5mm_EP2.45x2.45mm[_ThermalVias]` is for a different drawing) | Match: 1,2 IN; 3 B_GATE; 4 DRV; 5 IN_SYS; 6 UVLO; 7 OVP; 8 GND; 9 dVdT; 10 ILIM; 11 MODE; 12 SHDN; 13 IMON; 14 FLT; 15 PGTH; 16 PGOOD; 17,18 OUT; 19-24 NC; 25 PowerPAD | Candidate: mismatch on the exposed pad (2.45 x 2.45 versus TI 2.7 x 2.7; smaller than the 2.5 nominal package pad). Texas_RGE0024H: match (EP 2.7 x 2.7; 3 x 3 vias, 0.2 drill, 1.1 pitch = TI "2X (1.1)", "Ø0.2"; four paste windows 1.09-1.17 at 0.675 offset versus TI 4X 1.188 at 0.694); signal pads 0.825 x 0.25 at span 3.925 versus TI 0.58 x 0.24 at span 3.825 (acceptable deviation, 0.05 mm toe and heel extension per side) | references/Datasheets/tps2663.pdf (SLVSE94G), Table 5-1 p. 3-4; §8.3.13 p. 28; Table 8-1 p. 28; Figure 9-18 p. 39; RGE0024H outline p. 52, land pattern p. 53, stencil p. 54 |
| 2 | TLV3012BIDBVR | DBV0006A (SOT-23-6) | `Package_TO_SOT_SMD:SOT-23-6` | Match: 1 OUT, 2 V-, 3 IN+, 4 IN-, 5 REF, 6 V+ | Acceptable deviation: KiCad 1.325 x 0.6 at span 2.275 (outer 1.80, inner 0.475) versus TI 1.1 x 0.6 at span 2.6 (outer 1.85, inner 0.75); pitch 0.95 identical | https://www.ti.com/lit/ds/symlink/tlv3012.pdf (SBOS300C), Figure 5-1 and Table 5-1 p. 3; DBV0006A land pattern p. 38 |
| 3a | SN74LVC3G04DCTR | DCT0008A (SSOP-8) | `Package_SO:SSOP-8_2.95x2.8mm_P0.65mm` | Match: 1 1A, 2 3Y, 3 2A, 4 GND, 5 2Y, 6 3A, 7 1Y, 8 VCC | Acceptable deviation (see §3) | https://www.ti.com/lit/ds/symlink/sn74lvc3g04.pdf (SCES363L), pinout p. 1; DCT0008A outline p. 11, land pattern p. 12 |
| 3b | SN74LVC3G06DCTR | DCT0008A | same | Match: same pinout as 3G04 | Acceptable deviation (see §3) | https://www.ti.com/lit/ds/symlink/sn74lvc3g06.pdf (SCES364J), pinout p. 1; DCT0008A p. 11-12 |
| 3c | SN74LVC2G32DCTR | DCT0008A | same | Match: 1 1A, 2 1B, 3 2Y, 4 GND, 5 2A, 6 2B, 7 1Y, 8 VCC | Acceptable deviation (see §3) | https://www.ti.com/lit/ds/symlink/sn74lvc2g32.pdf (SCES201N), Pin Functions p. 3; DCT0008A p. 17-18 |
| 3d | SN74LVC2G08DCTR | DCT0008A | same | Match: 1 1A, 2 1B, 3 2Y, 4 GND, 5 2A, 6 2B, 7 1Y, 8 VCC | Acceptable deviation (see §3) | https://www.ti.com/lit/ds/symlink/sn74lvc2g08.pdf (SCES198N), Pin Functions p. 3; DCT0008A p. 17-18 |
| 3e | SN74LVC1G123DCTR | DCT0008A | same | Match: 1 A, 2 B, 3 CLR, 4 GND, 5 Q, 6 Cext, 7 Rext/Cext, 8 VCC (no Q-bar pin on this part) | Acceptable deviation (see §3) | https://www.ti.com/lit/ds/symlink/sn74lvc1g123.pdf (SCES586E), Table 4-1 p. 3; DCT0008A p. 23-24 |
| 4 | SN74LVC1G11DCKR | DCK0006A (SC70-6) | `Package_TO_SOT_SMD:SOT-363_SC-70-6` | Match: 1 A, 2 GND, 3 B, 4 Y, 5 VCC, 6 C | Acceptable deviation: KiCad 1.325 x 0.4 at span 1.775 (outer 1.55, inner 0.225) versus TI 0.9 x 0.4 at span 2.2 (outer 1.55, inner 0.65); outer edge identical, heel extends 0.425 under the body | https://www.ti.com/lit/ds/symlink/sn74lvc1g11.pdf (SCES487I), Table 4-1 p. 3; DCK0006A outline p. 27, land pattern p. 28 |
| 5a | SN74LVC1G08DCKR | DCK0005A (SC70-5) | **Prefer** `Package_TO_SOT_SMD:Texas_R-PDSO-G5_DCK-5` (generic `SOT-353_SC-70-5` is acceptable) | Match: 1 A, 2 B, 3 GND, 4 Y, 5 VCC | Texas_R-PDSO-G5_DCK-5: match (0.9 x 0.4 at span 2.2 versus TI 0.95 x 0.4 at span 2.2). SOT-353_SC-70-5: acceptable deviation (1.325 x 0.4 at span 1.775; outer 1.55 versus TI 1.575; inner 0.225 versus 0.625) | https://www.ti.com/lit/ds/symlink/sn74lvc1g08.pdf (SCES217AA), Pin Functions p. 3; DCK0005A outline p. 34, land pattern p. 35 |
| 5b | SN74LVC1G14DCKR | DCK0005A | as 5a | Match: 1 NC, 2 A, 3 GND, 4 Y, 5 VCC | as 5a | https://www.ti.com/lit/ds/symlink/sn74lvc1g14.pdf (SCES218AA), Table 4-1 p. 4; DCK0005A p. 33-35 |
| 5c | SN74LVC1G06DCKR | DCK0005A | as 5a | Match: 1 NC, 2 A, 3 GND, 4 Y, 5 VCC | as 5a | https://www.ti.com/lit/ds/symlink/sn74lvc1g06.pdf (SCES295AB), Table 4-1 p. 3; DCK0005A p. 32-34 |
| 6 | TPS22810DBVR | DBV0006A (SOT-23-6) | `Package_TO_SOT_SMD:SOT-23-6` | Match: 1 VIN, 2 GND, 3 EN/UVLO, 4 CT, 5 QOD, 6 VOUT | Acceptable deviation (identical to row 2; TI 1.1 x 0.6 at span 2.6) | https://www.ti.com/lit/ds/symlink/tps22810.pdf (SLVSDH0C), Pin Functions p. 3; DBV0006A land pattern p. 35 |
| 7 | Nexperia BAV199 | SOT23 | `Package_TO_SOT_SMD:SOT-23` | Match (secondary source): pin 1 A1 = anode (diode 1); pin 2 K2 = cathode (diode 2); pin 3 = K1, A2 = cathode (diode 1) and anode (diode 2). The design assumption (1 = anode of the lower diode, 2 = cathode of the upper diode, 3 = common node) agrees. TODO(verify: Nexperia BAV199 datasheet rev. 01092020, Table "Pinning information", original PDF; nexperia.com refused automated access) | Not compared; TODO(verify: Nexperia SOT23 reflow footprint) | Nexperia BAV199 data sheet rev. 01092020 as mirrored at https://www.radiolocman.com/datasheet/pdf.html?di=176593 (read through a search summary only) |
| 8a | onsemi 2N7002KT1G | SOT-23 CASE 318, STYLE 21 | `Package_TO_SOT_SMD:SOT-23` | Match: STYLE 21 "PIN 1. GATE 2. SOURCE 3. DRAIN" | Acceptable deviation: KiCad 1.475 x 0.6 at span 1.875 (outer 1.675, inner 0.20) versus onsemi 0.95 x 0.56, 2.90 outer-to-outer (outer 1.45, inner 0.50), pitch 0.95 | https://www.onsemi.com/pdf/datasheet/2n7002k-d.pdf (Rev. 20), pin assignment p. 1; CASE 318 issue AU p. 6, STYLE 21 p. 7 |
| 8b | onsemi BSS84LT1G | SOT-23 CASE 318, STYLE 21 | `Package_TO_SOT_SMD:SOT-23` | Match: STYLE 21 "PIN 1. GATE 2. SOURCE 3. DRAIN" | as 8a | https://www.onsemi.com/pdf/datasheet/bss84lt1-d.pdf (Rev. 14), p. 1 and CASE 318 pages |
| 9 | onsemi BAT54HT1G | SOD-323 CASE 477, STYLE 1 | `Diode_SMD:D_SOD-323` | Match: STYLE 1 "PIN 1. CATHODE (POLARITY BAND) 2. ANODE"; KiCad pad 1 = cathode, so pad 1 = cathode, pad 2 = anode | Acceptable deviation: KiCad 0.6 x 0.45 at span 2.10 versus onsemi 0.63 x 0.83 at span 2.23. The KiCad pad is 0.38 narrower than recommended (lead width b 0.25-0.40) | https://www.onsemi.com/pdf/datasheet/bat54ht1-d.pdf (Rev. 9), p. 1; CASE 477 issue K, "Recommended mounting footprint", p. 4 |
| 10a | Diodes B340A-13-F | SMA (DO-214AC) | `Diode_SMD:D_SMA` | Match: "Polarity: Cathode Band"; KiCad pad 1 = cathode | Match: KiCad 2.5 x 1.8 at C = 4.0 (X1 = 6.5, G = 1.5) versus Diodes X 2.50, Y 1.70, C 4.00, X1 6.50, G 1.50; width +0.1 | https://www.diodes.com/assets/Datasheets/ds30891.pdf (DS30891 Rev. 17-2), p. 1 polarity; "Suggested Pad Layout" p. 5 |
| 10b | Littelfuse SMAJ33A | SMA (DO-214AC) | `Diode_SMD:D_SMA` | Match by JEDEC DO-214AC convention: unidirectional "A" parts have a cathode band; pad 1 = cathode. TODO(verify: Littelfuse SMAJ datasheet, polarity and pad layout; littelfuse.com refused automated access) | TODO(verify: Littelfuse SMAJ datasheet, pad layout). The Diodes SMA layout in 10a is the reference until then | https://www.littelfuse.com/series/SMAJ (not readable by the tool) |
| 11 | Samtec FTSH-107-01-L-DV(-K) | 2 x 7, 1.27 SMT | `Connector_PinHeader_1.27mm:PinHeader_2x07_P1.27mm_Vertical_SMD` (no Samtec FTSH footprint exists in the KiCad 9 stock libraries) | Match: odd positions in one row, even in the other, 1 and 2 at the same end (KiCad pad 1 at (-1.95, -3.81), pad 2 at (+1.95, -3.81)) | Acceptable deviation (see §4) | Samtec FTSH-1XX-XX-XXX-DV-XXX-FOOTPRINT rev. H, sheet 1; FTSH-1XX-XX-XXX-DV-XXX-XXX-MKT rev. FQ, sheets 1-2 (suddendocs.samtec.com/prints/) |
| 12 | Samtec TSW-1xx-07-G-S | 2.54 THT | existing 1.1 drill, >= 1.9 pad | Not applicable | Match: a 0.64 square pin has a 0.905 diagonal; a 1.1 hole leaves 0.195 diametral clearance (0.0975 per side at the corners). TODO(verify: Samtec TSW-1XX-XX-XXX-S MKT print, pin size .025 SQ; samtec.com refused automated access to this print) | arithmetic only |

## 2. TPS26630RGER: pin handling notes

The datasheet pin table (Table 5-1) and the functional descriptions specify the following for the
pins that the design leaves open:

- **NC 19-24:** Table 5-1 gives "No connect" with no instruction. Figure 9-18 shows them labelled N.C.
  with no connection. No tie is required.
- **B_GATE (3):** "If external FET is not used then leave B_GATE pin floating." Unconnected is correct.
- **DRV (4):** "Leave this pin floating if external N-FET is not used." Unconnected is correct.
- **IN_SYS (5):** "Short IN_SYS to IN in case blocking FET is not used." §8.3.5 adds "connect IN_SYS
  and IN together". The netlist must therefore join pin 5 to pins 1 and 2.
- **MODE (11):** open is a valid configuration (Table 8-1). For the TPS26630, open selects 1x current
  limiting for tCL_PLIM(dly), then **latch-off**. The latch resets only by a SHDN low-to-high toggle, a
  UVLO low-to-high toggle, or an IN_SYS power cycle. MODE to GND selects auto-retry.
- **SHDN (12):** the datasheet does not state that SHDN may float. The electrical table gives an
  open-circuit voltage V(SHDN) of 2.48 V minimum (I(SHDN) = 0.1 µA) against a 2 V rising threshold,
  so an open SHDN enables the device with 0.48 V margin. However, with MODE open and SHDN open,
  the only latch reset is UVLO or a power cycle. The design must accept this or route SHDN to a
  control.
- **UVLO (6):** "UVLO terminal must not be left floating" (undervoltage-lockout section, p. 20). Connect
  it to GND for the internal 15 V threshold, to IN_SYS to disable UVLO, or to a divider.
- **OVP (7):** connect to GND for the internal default threshold.
- **PowerPAD:** connect to the GND plane; it must not be the only GND connection (pin 8 must also be
  connected).

## 3. DCT0008A land pattern comparison

The TI example board layout (4220784/D) specifies 8 pads of 1.1 x 0.4 at a span of 3.8 (outer edge
2.45, inner edge 1.35), pitch 0.65. The KiCad `SSOP-8_2.95x2.8mm_P0.65mm` footprint has 8 pads of
1.6 x 0.3 (rotated) at a span of 3.4 (outer edge 2.50, inner edge 0.90). The outer edge differs by
0.05. The KiCad pad extends 0.45 further inward under the body (body width 2.9-3.1) and is 0.1
narrower (lead width 0.15-0.30). Pad numbering is counter-clockwise (1-4 down the left, 5-8 up the
right) and agrees with TI. The deviation is acceptable for reflow. A copy of the footprint with
1.1 x 0.4 pads at a 3.8 span would match TI exactly.

## 4. Samtec FTSH-107 details

- **Recommended pad (FOOTPRINT rev. H, Fig. 1):** 2.79 (.110) long by 0.74 (.029) wide, 1.27 pitch,
  6.86 (.270) outer-to-outer. The row-to-row centre distance is therefore 6.86 - 2.79 = 4.07.
- **KiCad stock footprint:** 2.4 x 0.74 at x = ±1.95 (centre distance 3.90, outer 6.30, inner gap 1.50
  versus Samtec 1.28). The pad width and pitch match. The pads are 0.39 shorter than Samtec and the
  outer extent is 0.56 smaller. The deviation is acceptable; a 2.79-long pad at ±2.035 matches Samtec.
- **Body:** width 3.43 (.135 REF); length = positions x 1.27 = 8.89, tolerance +0.13 / -0.36 (MKT
  sheet 1). The maximum is 3.43 x 9.02. The body fits the 3.9 (x) by 9.4 (y) envelope with the KiCad
  orientation (rows along y). The -K body (FTSH-50-CN-07 keying shroud, MKT sheet 2, Fig. 2) shows the
  same .135 [3.43] REF width. TODO(verify: Samtec FTSH MKT sheet 2, Fig. 2, overall -K plan-view
  envelope including the key feature).
- **Alignment holes:** only the -A option uses the .040 [1.02] holes (FOOTPRINT Table 1); -K, -M and -P
  use none.
- **Position removal:** the -K option is a keyed shroud for mating with FFSD and does not remove a pin.
  The polarizing option "-XXX INDICATES POSITION TO BE OMITTED" removes a position, for example a
  trailing "-06" for position 6. It is "NOT AVAILABLE WITH EXX OPTIONS" and "ONLY AVAILABLE WITH -F,
  -FM, -L, -LM PLATING OPTIONS"; the -L plating of this part qualifies. TODO(verify: Samtec order
  configurator, exact string such as FTSH-107-01-L-DV-K-06 and -K compatibility).

## 5. Footprint changes and netlist actions

1. Replace the TPS26630 footprint with
   `Texas_RGE0024H_VQFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm_ThermalVias`; the generic EP2.45 footprint
   undersizes the thermal pad relative to SLVSE94G p. 53.
2. Confirm in the netlist that TPS26630 pin 5 (IN_SYS) is joined to pins 1-2 (IN) and that pin 6
   (UVLO) is not floating.
3. No pinout mismatch was found on any part; no netlist pin assignment changes.

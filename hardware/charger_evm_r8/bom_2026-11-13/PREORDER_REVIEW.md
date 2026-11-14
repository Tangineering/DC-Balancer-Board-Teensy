# Pre-order review of the CR, the EIB and the per-unit BOMs, 2026-11-13

## 1. Scope and method

This record reviews the landed CR (`cr/cr.kicad_pcb` after the operator's routing cleanup, `547dc11`), the landed
EIB (D-63, `f12a546`), their OSH Park packages, the per-unit BOMs of this folder and `digikey_import.csv` before
any order. Five independent reviewers covered the CR BOM against the CR design, the EIB BOM against the EIB design,
the completeness of one build, the Digi-Key file and the fab packages. A second agent re-checked each finding and
tried to refute it. Of 26 findings, 18 were confirmed and 8 partly confirmed, with severity or detail corrected; none
was refuted. This record states the corrected form of each finding.

The order gates are as follows:

- **Bare boards:** sections 3.1 (CR) and 3.2 (EIB).
- **Parts:** section 4.
- **Assembly and build:** section 5.

## 2. Corrected in this round

1. **EVM R272 and R272b (finding SYS-1, also EIB-1 and DK-1).** `gen/bom_split.py` dropped the EVM references of
   the 47.0 kOhm row, which the CR and EIB parts share. `system_bom.csv` now carries EVM R272 and R272b, and the
   Digi-Key line for CRCW060347K0FKEA is 11 (CR 2, EIB 7, system 2). No other row of the 2026-11-11 BOM mixes board
   and rework references.
2. **PLT1M-C quantity (DK-5).** Digi-Key sells PLT1M-C per piece, so quantity 1 bought one tie. The system row and
   the Digi-Key line now give 3 (anchors A1 and A2 and the chassis tie). The row description still reads
   "100-pack", which comes from the 2026-11-11 row.
3. **Stale CR records (FAB-1, FAB-3).** `cr/constraint_check.md` is regenerated from the current board (107 pass,
   0 FAIL). `fab/cr_2026-11-13b_oshpark/README.md` states that its zip supersedes the copper of
   `fab/cr_2026-11-13/`. The hardware README section 9.3 carries the same amendment. The 13b zip matches the current
   board: every Gerber equals a fresh export, the drill file is identical and DRC is 0 / 0 / 0.

4. **Via on J101 pad 9 and the tight mask gaps (items 3.1.1 and 3.1.2, closed by D-65).** The /GND stitching via on J101.9 and the vias 0.076 mm from the C129.1 and J101.11 masks were deleted, and the short In2 via pairs (SDA, SCL, TS_EXT and eight others) were merged onto F.Cu. DRC gives 0 / 0 / 0, the constraint check 108 pass and 0 FAIL, with the D-37 row at "none"; the smallest via gap to an other-net mask opening is 0.110 mm. The full package was re-exported as `fab/cr_2026-11-13c/`.

## 3. Items before the bare-board order

### 3.1 CR

1. **Closed by D-65 (section 2 item 4).** **Via in J101 pad 9 (known; D-37).** A /GND via at (37.50, 46.03), MB frame, overlaps J101 pad 9 (/GND) by
   about 0.2 mm. Under D-37, solder wicks into a via in an SMD pad. Move the via clear of the pad and its mask
   opening, then re-export.
2. **Closed by D-65 (section 2 item 4).** **Mask gap after the cleanup (FAB-2).** Three /GND vias that the cleanup added sit 0.076 mm from the mask
   openings of other nets (C129.1 /CHG_IIN, J101.7 /ILIM_REL_A, J101.11 NC). OSH Park's 4-layer mask alignment
   error is 0.0762 mm. Before the cleanup the minimum was 0.111 mm, and the closure of LAYOUT_DECISIONS section 11
   item 5 (0.115 mm) relied on that value. Move these vias or accept the margin. The vias are tented.
3. **Closed 2026-11-13 (operator connector rulings, README section 4.5):** J101 and J201 are removed and become through-hole wire pads. **J101 part (CR-BOM-1, SYS-4, DK-2; LAYOUT_DECISIONS section 11 item 13).** The board has no pad 6 at J101. The
   Digi-Key line SAM1161-07-ND is the stock 14-pin FTSH-107-01-L-DV, and the FFSD hole-6 plug is not identified,
   so the CR end of W5 has no key. Choose one of these routes:
   - a Samtec order for the position-6-omitted variant, with the Digi-Key line removed;
   - the stock part with pin 6 pulled before reflow;
   - the shrouded -K part at J101 as well, after the envelope check of item 3.2.2.

   With the stock part, pin 6 lands 0.33 mm from a tented /GND via. The -K route changes the footprint, so this
   choice precedes the CR order.
4. **Optional identification (FAB-5).** The CR has no board name, revision or date on any layer.

The current full package is `fab/cr_2026-11-13e/`, exported after D-67 (U101 TCKE1401NM); its copper equals
`fab/cr_2026-11-13d/` (D-66, J101 wire pads). (**Superseded 2026-11-13, D-66 and D-67:** "The full package
`fab/cr_2026-11-13c/` was exported after D-65. If item 3 changes the J101 footprint (-K route), re-run `gen/export.sh cr
<date>` and `gen/fab_readme.py cr <date>`.")

### 3.2 EIB

1. **Closed 2026-11-13 by D-68 (operator ruling 2026-11-13, chat: "Widen clearance"):** the pours keep 0.501 mm from the live E pads on both layers; package `fab/eib_2026-11-13c/`. **E-pad clearance to the AGND pours (EIB-4).** The E pads that carry hand-soldered leads (E1, E2, E3, E5, E7)
   keep 0.20 mm of copper clearance to the AGND pours on both layers, with a 0.05 mm mask expansion. Since D-63 the
   top layer also has a pour. Either increase the pour clearance around the E pads before the order, or add a build
   step: clean the flux, then measure each E pad to AGND before power-up.
2. **Closed 2026-11-13 (operator connector rulings, README section 4.5):** J201 is removed. **J201 -K shroud envelope (EIB-2; section 11 item 13).** The footprint models the plain FTSH body, and the -K key
   envelope is TODO(verify). The nearest fitted parts sit 0.89 mm beyond each body end (R266; R253 and R273). Check
   the Samtec -K drawing against that margin. No collision is established.
3. **Closed 2026-11-13 (operator ruling 2026-11-13, chat: "Order 3"): 3 EIBs, one OSH Park lot; one is fitted per build, two are spares.** **Order quantity (known).** The EIB quantity is not ruled; OSH Park sells boards in multiples of 3 and the E BOM
   asks for 5.
4. **Optional (EIB-5).** The top silkscreen still reads 2026-11-11.

## 4. Items before the parts order

1. **Closed 2026-11-13 (operator connector rulings, README section 4.5):** the W5 ribbon and its key are off the BOM. **J101 and the W5 key.** See item 3.1.3. The W5 key row books 2 plugs, but only the J101-end socket hole 6 can
   take a plug, because J201 has post 6 (EIB-3). One plug and a spare are enough; never plug the J201 end.
2. **J-TAP cable (SYS-2; section 11 item 16).** Distributor listings give Molex 2147561101 as 18 AWG UL 1061 and
   mark it discontinued. A Molex page does not confirm either fact. The far-end terminations and the R170/R171 0805
   joints assume about 26 AWG. Confirm the gauge and the status, then choose a finer cable or 18 AWG terminations
   with strain relief.
3. **Ferrule part numbers (DK-3).** **Updated 2026-11-13 (Digi-Key upload review, README section 4):** closed. Digi-Key sells 3200894 per piece (277-5469-ND), and AI 0,5-8 WH is Phoenix 3200014 (277-2185-ND).  3200894 is the 1000-piece AI 0,75-8 GY pack, and "AI 0,5-8 WH" is a type
   designation, not an order number. Choose the loose-piece order numbers and set the quantities to the sellable
   unit.
4. **Closed 2026-11-13 (operator connector rulings, README section 4.5):** the EVM J8 lead is soldered to the pins, so the KK housing and crimps are off the BOM. **Obsolete KK crimp (DK-7, SYS-7).**  08-50-0114 (WM1114-ND) is listed as obsolete. The 2026-11-11 README names
   08-50-0113 as the drop-in. Order 5 or more, and confirm that the workshop has a KK crimper and a ferrule crimper.
5. **Free-text MPNs (DK-4, DK-6).** **Updated 2026-11-13 (Digi-Key upload review, README section 4):** closed; the wire and tape rows are off the BOM (workshop stock).  The Alpha "297" and "296" bus-wire lines are series numbers, and the 3M 467MP
   line is free text. Digi-Key will not match them. Select the products by hand (the 467MP row links Digi-Key
   product 467MP-0.5-4(5)), or cut the JP3 and JP5 links from wire on hand.
6. **Stock checks (CR-BOM-3, DK-7).** **Updated 2026-11-13 (Digi-Key upload review, README section 4):** C102b is now TDK CNC6P1X7R2A475K250AE (DC-bias check open). TPS26630RGER has no authorized stock (Digi-Key restock 8-Jul-2027); **closed by D-67:** U101 is the Toshiba TCKE1401NM from Mouser, with new R101/R103/R104 values (README sections 4.3 and 4.8).  Confirm stock of C3225X7S2A475K200AB (C102b; flagged NRND or zero stock at
   secondary sources) and TPS26630RGER (U101). For C102b, the fallbacks are GRM32ER72A475KA35L or 2 x 2.2 uF 100 V
   1210, after a DC-bias check of at least 3 uF at 23.6 V.
7. **Unidentified build items (SYS-6, DK-8).** Heat-shrink tubing (EM7, PM6, A.3), the two adhesive tie bases and
   the solder paste have no MPN. Choose them if they join the order.
8. **Second EVM (SYS-5).** Section E orders 2 BQ25798EVM, while the rework set covers one. Confirm that the second
   EVM is an unreworked spare; otherwise add a second rework set.
9. **6-32 screws (known).** The D-60 holes have no screw row; the length depends on the 3D-printed support.

## 5. Items before assembly and the build

1. **Stencil (CR-BOM-2; section 11 item 22).** The stencil row has no thickness or paste. The U101 exposed-pad paste
   coverage is 25 % (four 0.675 mm panes on the 2.7 mm pad), against the 78 % of the TI example at 0.125 mm. Record
   the thickness and the paste, and accept the coverage or close item 22.
2. **D103 fields (CR-BOM-4).** The board and the assembly BOM show D103 as "Schottky 40V SMA" (B340A-13-F
   fallback), while the order is STPS2H100A. Take D103 from the ordered part at assembly.
3. **Polarity marks (FAB-4).** The polarity marks of D103 and D107 and the pin-1 marks of the CR ICs are on F.Fab
   only, which the iBOM hides by default. Enable the fabrication layer in the iBOM during assembly. A reversed D103
   or D107 forward-biases VCHGOUT or VCHGIN to GND.
4. **Lead dressing (SYS-3).** The B1R wedge, the B3/S1/S2 posts and the off-CR support follow the r8 outline. The
   B1R corner is 1.95 mm and the trunk 0.43 mm from hole MH1, inside its 3.6 mm head radius. Do not make these
   parts, or buy the 467MP tape and the tie bases, until the A.3 lead route is re-derived for the D-62 board.
5. **W6 EVM end (SYS-8).** If a pack NTC is fitted, the W6 termination at EVM J7 has no part. Read the J7 type in
   SLUUCB5E and add its mate or a small ferrule.
6. **EVM plate (SYS-7).** The plate, clamps and pads wait on the MS2, MS5 and MS7 measurements.

## 6. Checks that passed

- Every fitted CR and EIB part appears in its BOM exactly once, with the netlist quantity; the DNP parts are absent.
- Every footprint matches the package of its MPN (pad count, pitch, body). The U101, LVC-gate, TLV3012B, BAV199,
  MOSFET and connector pin maps agree with B.8 and the datasheet tables.
- Capacitor voltage ratings exceed their nets with margin; the R175 rating covers the rail short.
- The mating pairs are complete: TSW/SSQ, J102/2147561101, J201/FFSD and J8/KK. The EVM and MB rework sets, the EIB
  standoffs and screws, and the wire spools cover one build. The J-TAP pigtail reaches every tap.
- `digikey_import.csv` holds every Digi-Key row of the three BOMs with the summed quantity. Its encoding and quoting
  are valid. (**Amended 2026-11-13:** the Customer Reference now carries the reference designators, at most 48
  characters; README section 2.3.)
- The CR zip holds the 4 copper layers in the right order, both masks, silkscreens and paste layers, the outline
  and a merged drill file. The drill file has 446 vias, the connector and lead holes and four 3.70 mm NPTH. All zone
  fills are unchanged by the cleanup, so the R9.H25 and R9.H26 copper figures hold.
- The EIB zip is complete for 2 layers. EIB DRC gives 0 / 0 / 0, and the EIB constraint table matches. The D-63
  pours are AGND only, with no via on GND_J.

Vendor pages were not read live: the Digi-Key part numbers and the live stock of every line remain unverified.

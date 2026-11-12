# CR parts and assembly decisions (DESIGN_STATE section 4 item 5), operator session 2026-11-12

Scope: the reduced CR parts list after the tap review (`cr_tap_review_2026-11-12.md`), not the r8 list.
No repo file was edited and nothing was committed. The operator's words are the option labels they selected.

## 1. Facts checked before the questions

- D-31 (LAYOUT_DECISIONS) already removed all three DNP tiers on 2026-11-11: tier 1 C105, R145, R146; tier 2 U112,
  C152, D101, R_KA and R134; tier 3 U117, R160-R163, C127, C124. Item 3 was therefore asked as "re-admit or not".
- SC70 (DCK) is 0.65 mm pitch, the same as DCT. Every logic part already meets the 0.65 mm preferred minimum, so
  moving to DBV (0.95 mm) is a preference for paste printing, not a rule.
- R134 is a pull-down on the FCC tap (T5). It was DNP since r6 on purpose: with it fitted, an open T5 reads "FC charge
  proven off" (DD:669, r6-6). R187 3.30 MOhm makes an open tap read "may be on". T5 is now a plug-in lead.
- The H1*UVB release still exists in the reduced gate, so regen-armed cruise exists and T-B-09 (regen restart after
  VCHG decay, H.7/H.9) is still meaningful. The ramifications inventory lists T-B-09 for retirement; that entry is wrong.
- FR-14(e) (DD:2984) reads: "if T-F-04b fails: fit U117 (hardware FC-current shed into H2c) or restrict windows to
  standstill/coast". H2c and FCI_OK no longer exist.

## 2. Decisions

| # | Item | Operator answer (verbatim label) |
|---|---|---|
| 1 | SMT side | "All top, no fallback (Recommended)" |
| 2a | 0402 parts | "All six to 0603 (Recommended)" |
| 2b | Logic packages | "Single gates to DBV only (Recommended)" |
| 3a | DNP tier 1 (C105, R145, R146) | "Keep all three removed (Recommended)" |
| 3b | B.5 keep-alive (U112) | "Retire B.5, keep T-B-09 (Recommended)" |
| 3c | R134 | "Keep R134 removed (Recommended)" |
| 3d | U117 / FR-14(e) | "Retire U117 and FR-14(e) hw (Recommended)" |
| 4 | Silkscreen and courtyard | "Refdes on silk + 0.25 mm (Recommended)" |

Meaning of each:
1. All SMT on the top side, one stencil, one reflow. No bottom fallback: if a regenerated placement does not fit, escalate
   to the operator. The bottom carries only THT pin bodies and L4 solid GND. R104 moves to the top. D-17, D-18, D-19 and
   D-32 retire.
2a. R101, R103, R104, R105, R106s and C101 become 0603.
2b. Every single-gate part (1G) goes to SOT-23 DBV. A multi-section part with only one section used becomes the 1G part in
   DBV. Parts with two or more sections used (2G08, 2G32, 3G04) stay DCT at 0.65 mm.
3a. C105, R145, R146: stay removed, no footprints.
3b. B.5 deleted with its CR parts. T-B-09 is kept as the test that decides regen capture in regen-armed cruise. On a
   T-B-09 failure the path is fallback 2 (the fused VBT-VCHG link on the MB, B.5 second fallback) or a redesigned
   keep-alive in a later round.
3c. R134: stays removed, no footprint (open T5 stays fail-safe).
3d. U117 and R160-R163, C127, C124 retired; no gate input reserved. FR-14(e) becomes: "if T-F-04b fails, restrict FC
   windows to standstill/coast".
4. Reference designators on silkscreen for all parts (D-12a reversed); courtyards on the IPC-7351 nominal basis,
   0.25 mm excess (D-03 basis reversed from 0.10 mm). Footprints are regenerated.

## 3. Package list changes

Table 1. Passive changes (from `outline_change_2026-11-12/assembly.md` Table 2).

| Ref | Now | New | Note |
|---|---|---|---|
| R101 | CRCW04028K06FKED | CRCW06038K06FKEA | |
| R103 | TNPW040266K5BEED | TNPW060366K5BEEA | <= 5 mm from U101 pins 7-13 |
| R104 | TNPW040249K9BEED (bottom) | TNPW060349K9BEEA (top) | retires D-32 |
| R105 | CRCW040227K4FKED | CRCW060327K4FKEA | |
| R106s | CRCW04021K00FKED | CRCW06031K00FKEA | existing BOM line +1 |
| C101 | GRM155R71H223KA12D | GRM188R71H223KA01D | TODO(verify: Murata) |

Table 2. Logic, conditional on the dec2-gate mapping (policy 2b applied).

| Mapping | Part | Result |
|---|---|---|
| gate.md 5-package mapping | U107 SN74LVC1G11DCKR | SN74LVC1G11DBVR |
| | U106 SN74LVC2G32DCTR (gate A spare) | SN74LVC1G32DBVR |
| | U105 SN74LVC3G04DCTR | with SAFETY-1 (2 sections): stays DCT; without SAFETY-1 (1 section): SN74LVC1G04DBVR |
| | U110 SN74LVC2G32DCTR, U118 SN74LVC2G08DCTR | stay DCT |
| inventory 1b mapping | U109 SN74LVC1G11DCKR | SN74LVC1G11DBVR |
| | U105 (1 section) | SN74LVC1G04DBVR |
| | U106 (1 gate used) | SN74LVC1G32DBVR |
| | U116 (gate 2 spare unless it buffers CE_DRV) | SN74LVC1G08DBVR if one gate used, else stays DCT |
| | U110 | stays DCT |
| all-single-gate mapping (dec2-gate option b) | all | DBV throughout |

Not re-admitted (no footprint, no BOM line): C105, R145, R146, R134, U112, C152, D101, R_KA, U117, R160-R163, C127, C124.
U101 stays TPS26630RGER (already approved, 0.5 mm exception). TLV3012BIDBVR comparators are already DBV.

## 4. Open TODOs

- TODO(verify: TI Pin Functions tables): DBV pinout of each 1G part against its DCK/DCT pinout; re-check B.8 pin by pin.
- TODO(verify: Murata): GRM188R71H223KA01D (22 nF 50 V X7R 0603).
- Correct the ramifications inventory: T-B-09 is kept, not retired. Rewrite its fail branch (no B.5 step; fallback 2 or
  a later keep-alive design). H.7 "keep-alive mandatory if T-B-09 ..." needs the same rewrite.
- Delete B.5 and its BOM/E rows, PM7 (T18 part), the DD:2131 keep-alive build-record line; rewrite FR-14(e).
- Footprint regeneration at 0.25 mm courtyard excess (D-03 rewrite); silkscreen designators (D-12a rewrite), text size
  against OSH Park silk minimums TODO(verify: OSH Park).
- LAYOUT_DECISIONS: D-31 gains the re-admission ruling (none re-admitted); D-17, D-18, D-19, D-32 retire.
- Recompute the area booking with the reduced list, 0603 parts, DBV parts and 0.25 mm courtyards.
- The logic package list is final only when dec2-gate rules the mapping.

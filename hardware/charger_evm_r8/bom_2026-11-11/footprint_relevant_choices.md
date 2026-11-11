# Footprint-relevant part choices (ordering BOM 2026-11-11)

Machine-readable summary for the PCB capture of the carrier (CR) and the EVM interface board
(EIB). Each block lists the chosen MPN, the package, and the land-pattern facts read from the
manufacturer drawing. A value marked `TODO(verify)` was not on the drawing that was read; the
capture must not use a guessed value for it.

```yaml
D103:
  mpn: STPS2H100A
  manufacturer: STMicroelectronics
  status: candidate - T-A-05 datasheet check required
  package: SMA (DO-214AC)
  source: ST STPS2H100 datasheet DocID6115 Rev 8 (June 2013), Table 5 and Figure 20
  body_mm: {E_overall_with_leads: [4.80, 5.35], E1_body_length: [3.95, 4.60], D_body_width: [2.25, 2.90], A1_height: [1.90, 2.45]}
  lead_mm: {b_width: [1.25, 1.65], L_foot: [0.75, 1.50], c_thickness: [0.15, 0.40]}
  recommended_land_mm: {pad_x: 1.40, pad_y: 1.64, gap_between_pads: 2.63, overall_x: 5.43, pad_centre_pitch: 4.03}
  polarity: cathode band

D107:
  mpn: SMAJ33A
  manufacturer: Littelfuse
  status: candidate - T-A-05 datasheet check required
  package: SMA (DO-214AC), unidirectional
  source: Littelfuse SMAJ series datasheet, rev BA.10/21/20, Dimensions table
  body_mm: {A_lead_width: [1.25, 1.65], B_body_length: [3.99, 4.60], C_body_width: [2.40, 2.79], D_height: [1.90, 2.29], E_foot: [0.78, 1.52], G_overall: [4.80, 5.28]}
  recommended_land_mm: {I_pad_y_min: 1.80, J_pad_x_min: 2.10, L_pad_x_min: 2.10, K_gap_max: 2.30}
  note: "The ST and Littelfuse SMA lands differ (pad 1.40 x 1.64 vs >= 2.10 x >= 1.80). A shared SMA footprint must satisfy the courtyard of A.8; pick one land and check both parts in T-A-05."
  polarity: cathode band

C102a:
  mpn: GRM31CR72A105KA01L
  manufacturer: Murata
  status: candidate (section E); NRND flag from distributor listings, see README
  package: 1206 (3216 metric)
  rated_voltage_V: 100
  body_mm: TODO(verify: Murata spec sheet; murata.com returned 403 on 2026-11-11)
  land: standard 1206 land per the capture library; TODO(verify) against the Murata land recommendation

C102b:
  mpn: C3225X7S2A475K200AB
  manufacturer: TDK
  status: candidate (section E "C3225X7S2A475K class"); NRND flag, see README
  package: 1210 (3225 metric); the "200" field of the TDK code is the 2.00 mm thickness class (TODO(verify: TDK datasheet))
  rated_voltage_V: 100
  body_mm: TODO(verify: TDK datasheet)
  note: "Section E budgets C102b as ~2.5 mm tall in the J101 socket-overhang check; confirm the thickness."

J101:
  mpn: FTSH-107-01-L-DV with the polarized-position option, position 6 omitted (exact suffix TODO(verify: Samtec quote))
  manufacturer: Samtec
  status: candidate - T-A-05 datasheet check required
  package: 2 x 7, 1.27 mm pitch, SMT, vertical, unshrouded
  source: Samtec FTSH catalogue sheet F-226
  pitch_mm: 1.27
  rows: 2
  body_length_mm: 8.89   # 7 x 1.27, FTSH formula "No. of positions x 1.27"
  body_width_mm: TODO(verify: Samtec FTSH-1xx-01-x-DV footprint drawing); design estimate ~3.4
  tail_span_overall_mm: 5.84
  post_square_mm: 0.40
  post_length_above_body_mm: 3.05   # lead style -01
  insulator_height_mm: 2.92         # dimension (2.92) on the -DV view, TODO(verify) that it is the body height
  smt_coplanarity_mm: 0.10
  pad_size_mm: TODO(verify: Samtec recommended footprint)
  courtyard_fit: "Body 8.89 mm fits the 9.4 mm (y) body courtyard with 0.255 mm per end. Width fit to 3.9 mm (x) is unconfirmed until the body width is read. The tails (5.84 mm) lie inside the 7.5 mm J101 region (x 37.0-44.5)."
  pin_6: "Omitted at the factory by the FTSH OPTION field -\"XXX\" (polarized position, specify the omitted pin). Not available with -EX options."
  mated_socket_envelope_mm: {length: 13.08, width: 3.05, height: 5.08}   # FFSD: 7 x 1.27 + 4.19

J201:
  mpn: FTSH-107-01-L-DV-K
  manufacturer: Samtec
  status: candidate - T-A-05 datasheet check required
  package: 2 x 7, 1.27 mm pitch, SMT, vertical, keying shroud (-K)
  pitch_mm: 1.27
  body_length_mm: 8.89
  tail_span_overall_mm: 5.84
  shroud_envelope_mm: TODO(verify: Samtec -K drawing)
  pad_size_mm: TODO(verify: Samtec recommended footprint)
  keying: "-K shroud mates with the FFSD notch polarization (-N)."

W5:
  mpn: FFSD-07-D-12.00-01-N
  manufacturer: Samtec
  status: candidate - T-A-05 datasheet check required
  description: 14-way, 1.27 mm IDC socket both ends, 12.00 in (0.305 m), notch polarization, 30 AWG flat cable
  socket_body_mm: {length: 13.08, width: 3.05, height: 5.08}
  insertion_depth_mm: [2.64, 3.17]
  lead_size_accepted_mm: 0.41   # square
  note: "07 pins/row is outside the FFSD standard size list; built to order (Samtec product pages exist for other 07 lengths)."

W5_key:
  mpn: NOT IDENTIFIED
  note: "No FFSD hole plug found on the Samtec sheet; TODO(verify: Samtec)."

CHG_header_strips:
  - {mpn: TSW-110-07-G-S, manufacturer: Samtec, column_x_mm: 45.998, pads: "1-10"}
  - {mpn: TSW-112-07-G-S, manufacturer: Samtec, column_x_mm: 20.998, pads: "11-22"}
  package: single row, through-hole, 2.54 mm pitch, 0.64 mm square post, 2.54 mm plastic body
  pad_and_hole_mm: TODO(verify: Samtec TSW footprint; drawing not read this round)

tap_pins:
  mpn: TSW-101-07-G-S
  manufacturer: Samtec
  package: single 0.64 mm square post, 2.54 mm body; wire-soldered, not PCB-mounted
  land: none (the pin is a wire termination that plugs into J1/J2)
```

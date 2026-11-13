"""Pin-level netlist of the CR (carrier) and the EIB (EVM interface board), transcribed from
docs/charger_bq25798_wiring_design_2026-11-05.md r8, section B.8 (pin -> net), with values and
packages from section E (BOM) and pad geometry from A.8 / A.9.

The CR list also carries the operator decisions of 2026-11-12 (hardware/charger_evm_r8/decisions_2026-11-12/, first
and second rounds): the tap reduction to 10 conductors on one Micro-Fit 3.0 2 x 5 header (J102, J-TAP), the 5-LVC
permit gate of ramifications/gate.md with the agreement term and the U106A CE_DRV buffer, J101 pins 11/13 NC, every
SMT part on the top side, and the six 0402 parts at 0603. Those decisions are not yet in the B.8 text.

Every entry cites its B.8 row in a comment where the transcription is not literal. Net names follow
B.8 verbatim where B.8 names the net; where B.8 names only a pad (F01-F24, W1-W7, E1-E8, J101.n)
the net takes the descriptive name recorded in the LAYOUT_DECISIONS.md net-naming table.

Part tuple: (ref, kind, value, package, {pin: net}, opts)
  kind    : symbol template key (see symbols.py)
  package : footprint key (see footprints.py)
  opts    : dict(dnp=bool, side='F'|'B', mpn=str, mfr=str, note=str); since 2026-11-12 no CR part sets side='B'
A pin mapped to None is an intentional no-connect.
"""

GND = "GND"
V33 = "3V3"


def R(ref, val, pkg, a, b, **o):
    return (ref, "R", val, pkg, {"1": a, "2": b}, o)


def C(ref, val, pkg, a, b, **o):
    return (ref, "C", val, pkg, {"1": a, "2": b}, o)


def bav199(ref, node, **o):
    # B.8: 1 = anode of the lower diode (-> GND), 2 = cathode of the upper diode (-> 3V3), 3 = common node.
    return (ref, "BAV199", "BAV199", "SOT-23", {"1": GND, "2": V33, "3": node},
            dict(mpn="BAV199,215", mfr="Nexperia", **o))


def tlv3012(ref, out, inp, inm, ref_net, dnp=False):
    # B.8: TLV3012 DBV 1 OUT, 2 V-, 3 IN+, 4 IN-, 5 REF, 6 V+.
    return (ref, "TLV3012", "TLV3012B", "SOT-23-6",
            {"1": out, "2": GND, "3": inp, "4": inm, "5": ref_net, "6": V33},
            dict(mpn="TLV3012BIDBVR", mfr="Texas Instruments", dnp=dnp))


def lvc2g(ref, typ, p1, p2, p7, p5, p6, p3, gnd=GND, vcc=V33):
    # SN74LVC2G32/2G08 DCT: 1 1A, 2 1B, 3 2Y, 4 GND, 5 2A, 6 2B, 7 1Y, 8 VCC.
    return (ref, typ, typ, "SSOP-8",
            {"1": p1, "2": p2, "3": p3, "4": gnd, "5": p5, "6": p6, "7": p7, "8": vcc},
            dict(mpn="SN74%sDCTR" % typ, mfr="Texas Instruments"))


def lvc1g11(ref, a, b, c, y):
    # SN74LVC1G11 DBV (SOT-23-6; 2026-11-12 parts/assembly decision 2b: single gates to DBV): 1 A, 2 GND, 3 B, 4 Y,
    # 5 VCC, 6 C. This is the DCK map of B.8 carried over unchanged; TODO(verify: TI SN74LVC1G11 DBV pinout).
    # (superseded 2026-11-12: SC70-6 / SN74LVC1G11DCKR)
    return (ref, "LVC1G11", "SN74LVC1G11", "SOT-23-6",
            {"1": a, "2": GND, "3": b, "4": y, "5": V33, "6": c},
            dict(mpn="SN74LVC1G11DBVR", mfr="Texas Instruments"))


def lvc1g123(ref, a, b, clr, q, cext, rext):
    # SN74LVC1G123 DCT: 1 A, 2 B, 3 CLR, 4 GND, 5 Q, 6 Cext, 7 Rext/Cext, 8 VCC.
    return (ref, "LVC1G123", "SN74LVC1G123", "SSOP-8",
            {"1": a, "2": b, "3": clr, "4": GND, "5": q, "6": cext, "7": rext, "8": V33},
            dict(mpn="SN74LVC1G123DCTR", mfr="Texas Instruments"))


def tap(ref, net, **o):
    return (ref, "TAP", ref, "TAP_1.5", {"1": net}, o)


VISH01 = dict(mfr="Vishay Dale")

# --------------------------------------------------------------------------------------------
# Carrier (CR)
# --------------------------------------------------------------------------------------------
CR = [
    # ---- CHG header (22 Ag105 holes, A.2 / A.8; pins 1-10 column x 45.998, 11-22 column x 20.998).
    #      Mating connector (operator ruling 2026-11-12, cr_decision_mating_connector): Samtec TSW-110/112-07-L-S on
    #      the CR (bodies on the CR underside, tails soldered from the CR top), SSQ-110/112-01-L-S sockets on the MB;
    #      all 22 positions populated, no key. (superseded 2026-11-12: TSW-110/112-07-G-S)
    ("J1", "CHG22", "Ag105 CHG header", "CHG22",
     {"1": None, "2": None, "3": "STAT", "4": GND, "5": None, "6": None, "7": "SCL", "8": "SDA",
      "9": None, "10": "VCHGIN", "11": "CHG_ARM", "12": None, "13": "TS_EXT", "14": GND, "15": GND,
      "16": None, "17": None, "18": "VCHG", "19": "VCHG", "20": None, "21": None, "22": None},
     dict(mpn="TSW-110-07-L-S + TSW-112-07-L-S", mfr="Samtec",
          note="pins 1,2,5,6,9,12,16,17,20,21,22 are mechanical anchors (A.2); all 22 positions populated, no key "
               "(2026-11-12); MB mates SSQ-110-01-L-S + SSQ-112-01-L-S")),

    # ---- Input bulk, TVS, eFuse (B.4, B.8 row C102a/b/c/D107, U101)
    #      2026-11-12 parts/assembly decision 1: every SMT part on the top side (one stencil, one reflow); no part
    #      carries side="B" any more (R104 included; D-17, D-18, D-19, D-32 retire).
    #      Decision 2a: R101, R103, R104, R105, R106s and C101 move from 0402 to 0603.
    C("C102a", "1uF 100V X7R", "C1206", "VCHGIN", GND, mpn="GRM31CR72A105KA01L", mfr="Murata"),
    C("C102b", "4.7uF 100V X7S", "C1210", "VCHGIN", GND, mpn="C3225X7S2A475K", mfr="TDK",
      note="candidate, T-A-04/T-A-05"),
    C("C102c", "100nF 100V X7R", "C0603", "VCHGIN", GND, mpn="GRM188R72A104KA35D", mfr="Murata"),
    ("D107", "D", "TVS 33V SMA", "SMA", {"1": "VCHGIN", "2": GND},
     dict(mpn="SMAJ33A (candidate, T-A-05)", mfr="Littelfuse")),
    ("U101", "TPS26630", "TPS26630RGER", "VQFN24",
     {"1": "VCHGIN", "2": "VCHGIN", "3": None, "4": None, "5": "VCHGIN", "6": "N_UV", "7": "N_OV",
      "8": GND, "9": "N_DVDT", "10": "N_ILIM", "11": None, "12": None, "13": "N_IMON", "14": "N_FLT",
      "15": GND, "16": GND, "17": "VCHGOUT", "18": "VCHGOUT", "19": None, "20": None, "21": None,
      "22": None, "23": None, "24": None, "25": GND},
     dict(mpn="TPS26630RGER", mfr="Texas Instruments")),
    R("R102", "845k 0.1%", "R0805", "VCHGIN", "N_UV", mpn="TNPW0805845KBEEA", **VISH01),
    R("R103", "66.5k 0.1%", "R0603", "N_UV", "N_OV", mpn="TNPW060366K5BEEA", **VISH01),   # was 0402 TNPW040266K5BEED
    R("R104", "49.9k 0.1%", "R0603", "N_OV", GND, mpn="TNPW060349K9BEEA", **VISH01),      # was 0402 bottom (D-32)
    R("R101", "8.06k 1%", "R0603", "N_ILIM", GND, mpn="CRCW06038K06FKEA", **VISH01),      # was 0402 CRCW04028K06FKED
    C("C101", "22nF 50V X7R", "C0603", "N_DVDT", GND, mpn="GRM188R71H223KA01D", mfr="Murata",
      note="TODO(verify: Murata GRM188R71H223KA01D, 22 nF 50 V X7R 0603)"),               # was 0402 GRM155R71H223KA12D
    C("C103", "1uF 50V X7R", "C0805", "VCHGOUT", GND, mpn="GRM21BR71H105KA12L", mfr="Murata"),
    ("D103", "D", "Schottky 40V SMA", "SMA", {"1": "VCHGOUT", "2": GND},
     dict(mpn="selected in T-A-05 (bench fallback B340A-13-F)", mfr="Diodes Inc.")),
    R("R105", "27.4k 1%", "R0603", "N_IMON", GND, mpn="CRCW060327K4FKEA", **VISH01),      # was 0402 CRCW040227K4FKED
    # C105 removed: DNP tier 1 (D-31; SLVSE94G 8.3.9 forbids an IMON bypass capacitor); not re-admitted 2026-11-12
    R("R129", "10.0k 1%", "R0603", "N_IMON", "CHG_IIN", mpn="CRCW060310K0FKEA", **VISH01),
    C("C129", "1.0nF 50V C0G", "C0603", "CHG_IIN", GND, mpn="GRM1885C1H102JA01D", mfr="Murata"),
    # R106 (DNP since r4) is omitted: see LAYOUT_DECISIONS.md D-06 (r8 F17 exposed-copper rule).
    R("R106s", "1.00k 1%", "R0603", "N_FLT", "CHG_EFUSE_FLT", mpn="CRCW06031K00FKEA", **VISH01),  # was 0402

    # ---- U102 H1 comparator
    tlv3012("U102", "H1", "N_H1P", "N_H1M", None),  # B.8: 5 REF nc
    R("R109", "487k 0.1%", "R0805", "T1_VMOT", "N_H1P", mpn="TNPW0805487KBEEA", **VISH01),
    R("R110", "56.2k 0.1%", "R0603", "N_H1P", GND, mpn="TNPW060356K2BEEA", **VISH01),
    C("C106", "470pF 50V C0G", "C0603", "N_H1P", GND, mpn="GRM1885C1H471JA01D", mfr="Murata"),
    R("R113", "6.49M 1%", "R0603", "H1", "N_H1P", mpn="CRCW06036M49FKEA", **VISH01),
    bav199("D104", "N_H1P"),
    R("R111", "442k 0.1%", "R0805", "T2C", "N_H1M", mpn="TNPW0805442KBEEA", **VISH01),
    R("R112", "56.2k 0.1%", "R0603", "N_H1M", GND, mpn="TNPW060356K2BEEA", **VISH01),
    C("C107", "470pF 50V C0G", "C0603", "N_H1M", GND, mpn="GRM1885C1H471JA01D", mfr="Murata"),
    bav199("D105", "N_H1M"),
    # ---- U103 UVB
    tlv3012("U103", "UVB", "N_UVP", "REF103", "REF103"),
    R("R114", "1.00M 0.1%", "R0805", "T2C", "N_UVP", mpn="TNPW08051M00BEEA", **VISH01),
    R("R115", "104k 0.1%", "R0603", "N_UVP", GND, mpn="TNPW0603104KBEEA", **VISH01),
    C("C108", "1.0nF 50V C0G", "C0603", "N_UVP", GND, mpn="GRM1885C1H102JA01D", mfr="Murata"),
    R("R116", "10.0M 1%", "R0603", "UVB", "N_UVP", mpn="CRCW060310M0FKEA", **VISH01),
    bav199("D106", "N_UVP"),
    # ---- 2026-11-12 tap review (cr_tap_review): U104 BT_OK (R140-R144, C140, R128, C112; taps T8/T9), U115 BTB_OFF
    #      (R117-R120, C109, C113; tap T3) and U121 RGN_ON (R190, R191, C133, and the RGN tap R121/R133; tap T4)
    #      removed. U117, R160-R163, C127, C124 stay removed (D-31 tier 3; retired 2026-11-12, no gate input
    #      reserved). R137 (FCI_OK) removed with the old U107 function (permit-gate decision 2, gate.md section 3).
    # ---- FCC tap (T5)
    R("R122", "1.00k 1%", "R0603", "FCC_TAP", "FCC", mpn="CRCW06031K00FKEA", **VISH01),
    # R134 removed: DNP tier 2 (D-31; FCC pull-down, DNP since r6); stays removed 2026-11-12 (open T5 fail-safe)
    # ---- U119 FCC_OFF (output net FCCN)
    tlv3012("U119", "FCCN", "N_FOP", "N_FOM", "REF119"),
    R("R184", "20.0k 1%", "R0603", "REF119", "N_FOP", mpn="CRCW060320K0FKEA", **VISH01),
    R("R185", "10.0k 1%", "R0603", "N_FOP", GND, mpn="CRCW060310K0FKEA", **VISH01),
    C("C130", "100nF 50V X7R", "C0603", "N_FOP", GND, mpn="GRM188R71H104KA93D", mfr="Murata"),
    R("R186", "10.0k 1%", "R0603", "FCC", "N_FOM", mpn="CRCW060310K0FKEA", **VISH01),
    R("R187", "3.30M 1%", "R0603", "N_FOM", V33, mpn="CRCW06033M30FKEA", **VISH01),
    # ---- U120 FCC_ON
    tlv3012("U120", "FCC_ON", "N_FNP", "REF120", "REF120"),
    R("R188", "453k 1%", "R0603", "FCC", "N_FNP", mpn="CRCW0603453KFKEA", **VISH01),
    R("R189", "1.00M 1%", "R0603", "N_FNP", GND, mpn="CRCW06031M00FKEA", **VISH01),
    # ---- BAL input (r6) removed: R178, D108, R179, U123 (T22 input stage) and U122 (ARM_OK AND OVN)
    #      (D-38, operator ruling 2026-11-12; pack-voltage protection moves to firmware). Pad F08 (T22) removed.
    # ---- logic pull-downs and tap series resistors
    R("R108", "47.0k 1%", "R0603", "CHG_ARM", GND, mpn="CRCW060347K0FKEA", **VISH01),   # 47k kept (gate decision 3)
    R("R147", "1.00k 1%", "R0603", "QUAL_TAP", "QUAL", mpn="CRCW06031K00FKEA", **VISH01),
    R("R123", "47.0k 1%", "R0603", "QUAL", GND, mpn="CRCW060347K0FKEA", **VISH01),
    # R124 (FCCEIL, tap T11) and R135/R136 (HB, tap T21) removed (2026-11-12 tap review).
    # ---- permit logic: the 5-LVC mapping of gate.md section 2 plus permit-gate decisions 1-3 (2026-11-12):
    #      release = H1*UVB + FCC_ON*NOT FCC_OFF + QUAL*FCC_OFF*NOT P5;  /CE = NOT P5;  RFC_OFF = FCC_OFF + H1*UVB.
    #      U108, U109, U111 (one-shot), U113 (heartbeat), U114 and U116 and their timing/decoupling parts are removed.
    ("U105", "LVC3G04", "SN74LVC3G04", "SSOP-8",
     # sec 1: FCCNN = NOT FCCN (agreement term, decision 1); sec 2: P5N = NOT CHG_ARM; sec 3 spare (3A -> GND)
     {"1": "FCCN", "7": "FCCNN", "3": "CHG_ARM", "5": "P5N", "6": GND, "2": None, "4": GND, "8": V33},
     dict(mpn="SN74LVC3G04DCTR", mfr="Texas Instruments")),
    # U106 gate A: CE_DRV = CHG_ARM OR GND, push-pull into R130 (decision 3); gate B: RFC_OFF = FCCN OR H1U
    lvc2g("U106", "LVC2G32", "CHG_ARM", GND, "CE_DRV", "FCCN", "H1U", "RFC_OFF"),
    # U107: QF = QUAL AND FCCN AND P5N. Single gate -> SOT-23 DBV (parts/assembly decision 2b, reconciled with gate
    # decision 2). The logical pin map is the DCK map; TODO(verify: TI SN74LVC1G11 DBV pinout) - no TI SN74LVC1G11
    # datasheet is in references/.
    lvc1g11("U107", "QUAL", "FCCN", "P5N", "QF"),
    # U110 gate A: GATE = H1U OR FCCP; gate B: ILIM_REL = GATE OR QF -> R131A/R131B -> J101.7/.8
    lvc2g("U110", "LVC2G32", "H1U", "FCCP", "GATE", "GATE", "QF", "ILIM_REL"),
    # U118 gate A: H1U = H1 AND UVB; gate B: FCCP = FCC_ON AND FCCNN (agreement term, decision 1)
    lvc2g("U118", "LVC2G08", "H1", "UVB", "H1U", "FCC_ON", "FCCNN", "FCCP"),
    # ---- readbacks (B.8 "Readbacks"): only R126 (H1 -> tap T13, pin 34) remains. R127 (H2C_RB, T14), R128
    #      (BTOK_RB, T15) and R125/R148 (ILIM_SENSE/CE_SENSE far-end senses, T12/T20) removed 2026-11-12; the
    #      ILIM_SENSE and CE_SENSE nets no longer exist on the CR (dec2-eib section 4).
    R("R126", "1.00k 1%", "R0603", "H1", "H1_RB", mpn="CRCW06031K00FKEA", **VISH01),
    # ---- ribbon drivers
    R("R130", "100 1%", "R0603", "CE_DRV", "CE_DRV_J", mpn="CRCW0603100RFKEA", **VISH01),
    R("R131A", "100 1%", "R0603", "ILIM_REL", "ILIM_REL_A", mpn="CRCW0603100RFKEA", **VISH01),
    R("R131B", "100 1%", "R0603", "ILIM_REL", "ILIM_REL_B", mpn="CRCW0603100RFKEA", **VISH01),
    R("R132", "100 1%", "R0603", "RFC_OFF", "RFC_OFF_J", mpn="CRCW0603100RFKEA", **VISH01),
    # ---- 3V3 feed (r4)
    R("R175", "68.0 1% 0.25W", "R1206", "T6_3V3", V33, mpn="CRCW120668R0FKEA", **VISH01),
    R("R176", "200 1%", "R0603", V33, "J3V3_1", mpn="CRCW0603200RFKEA", **VISH01),
    R("R177", "200 1%", "R0603", V33, "J3V3_2", mpn="CRCW0603200RFKEA", **VISH01),
    C("C125", "10uF 10V X7R", "C0805", V33, GND, mpn="GRM21BR71A106KE51L", mfr="Murata"),
    # ---- J101 ribbon header (2x7 1.27 mm SMT, position 6 omitted = key). dec2-eib decision 4: stays 2 x 7, pins 11
    #      and 13 not connected (superseded 2026-11-12: 11 ILIM_SENSE, 13 CE_SENSE).
    ("J101", "J2x7K", "W5 header", "J2x7_NOPIN6",
     {"1": "J3V3_1", "2": "J3V3_2", "3": GND, "4": "STAT", "5": "CE_DRV_J", "7": "ILIM_REL_A",
      "8": "ILIM_REL_B", "9": GND, "10": "RFC_OFF_J", "11": None, "12": GND, "13": None,
      "14": GND},
     dict(mpn="FTSH-107-01-L-DV class (T-A-05)", mfr="Samtec")),
    R("R107", "10.0k 1%", "R0603", "STAT", V33, mpn="CRCW060310K0FKEA", **VISH01),
    # R145, R146 removed: DNP tier 1 (D-31; the I2C pull-ups stay on the MB 3V3 side, A.2); not re-admitted 2026-11-12
    # ---- keep-alive option B.5 (U112, C152, D101, R_KA): retired 2026-11-12 (parts/assembly decision 3b).
    # ---- decoupling (B.8 "Decoupling"): one 100 nF per surviving IC (C110 U102, C111 U103, C114 U105, C115 U106,
    #      C116 U107, C119 U110, C126 U118, C131 U119, C132 U120), now on the top side beside its IC. C112, C113,
    #      C117, C118, C120, C121, C122, C123 and C133 removed with their ICs (2026-11-12); C134/C135 removed (D-38).
    *[C(c, "100nF 50V X7R", "C0603", V33, GND, mpn="GRM188R71H104KA93D", mfr="Murata")
      for c in ("C110", "C111", "C114", "C115", "C116", "C119", "C126", "C131", "C132")],
    # ---- power and lead pads (B.8 "Power holes and pads (r5)"): the W leads stay soldered on the CR as THT
    #      pads and unplug at the existing EVM terminals (2026-11-12 lead decision).
    ("W1", "PAD1", "W1 VCHGOUT", "WPTH_1.3", {"1": "VCHGOUT"}, {}),
    ("W2", "PAD1", "W2 GND", "WPTH_1.3", {"1": GND}, {}),
    ("W3", "PAD1", "W3 VCHG", "WPTH_1.5", {"1": "VCHG"}, {}),
    ("W4", "PAD1", "W4 GND", "WPTH_1.5", {"1": GND}, {}),
    #      W6/W7 are plated through-holes (D-45, B.8 r9-4; superseded in r9: SMT pads WSMD_2 / WSMD_3); the footprint
    #      is a placeholder, hole and pad size TODO(verify: 26 AWG / 28 AWG conductor and insulation OD).
    ("W6", "PAD2", "W6 TS_EXT/GND", "WPTH_2", {"1": "TS_EXT", "2": GND}, {}),
    ("W7", "PAD3", "W7 SCL/GND/SDA", "WPTH_3", {"1": "SCL", "2": GND, "3": "SDA"}, {}),
    # ---- J-TAP (refdes J102): one Molex Micro-Fit 3.0 2 x 5 THT header, hand-soldered last, replaces the tap
    #      field F01-F24 (2026-11-12 tap review: 10 conductors kept, 13 pads removed; tap-connector decision).
    #      Cavity map (dec_tap_connector section 2), columns 1-5:
    #        row A: T1  T7b  T17r  T5  T13
    #        row B: T6  T2   T17   T16 T10
    #      Row A column c = pin c, row B column c = pin 5 + c, following the numbering of the placeholder stock
    #      footprint; TODO(verify: Molex 43045 drawing / 43025 housing cavity numbering, header P/N, vertical or
    #      right-angle, pegs). Accepted by the operator 2026-11-12: T5 (A4) is diagonal to T10 (B5); the gate rule
    #      (T5/T6/T10 pairwise non-adjacent including the opposite row) is met, the recommended diagonal clearance
    #      is not. The map is not changed here.
    #      Nets are the former pad nets: T1 = F01, T7b = F02 (shield, GND), T2 = F03, T5 = F06, T6 = F07, T10 = F11,
    #      T13 = F14, T16 = F17, T17 = F18, T17r = F19 (shield, GND).
    ("J102", "MF2x5", "J-TAP Micro-Fit 3.0 2x5", "MF3_2x5",
     {"1": "T1_VMOT", "2": GND, "3": GND, "4": "FCC_TAP", "5": "H1_RB",
      "6": "T6_3V3", "7": "T2C", "8": "CHG_IIN", "9": "CHG_EFUSE_FLT", "10": "QUAL_TAP"},
     dict(mpn="Molex Micro-Fit 3.0 2x5 THT header, 43045 series, TODO(verify: Molex 43045 drawing)", mfr="Molex",
          note="J-TAP; mates cable assembly Molex 2147581101, TODO(verify: Molex 2147581101); polarized; "
               "A1 T1, A2 T7b, A3 T17r, A4 T5, A5 T13, B1 T6, B2 T2, B3 T17, B4 T16, B5 T10")),
]

# --------------------------------------------------------------------------------------------
# EVM interface board (EIB)
# --------------------------------------------------------------------------------------------
AG = "AGND"
EIB = [
    ("U201", "LVC3G06", "SN74LVC3G06", "SSOP-8",
     {"1": "N_CEIN", "2": "Q202_G", "3": "N_RAIN", "4": AG, "5": "Q203_G", "6": "N_RFIN", "7": "nCE_DRV", "8": V33},
     dict(mpn="SN74LVC3G06DCTR", mfr="Texas Instruments")),
    C("C201", "100nF 50V X7R", "C0603", V33, AG, mpn="GRM188R71H104KA93D", mfr="Murata"),
    R("R274", "10.0k 1%", "R0603", V33, AG, mpn="CRCW060310K0FKEA", **VISH01),
    R("R250", "1.00k 1%", "R0603", "CE_DRV_J", "N_CEIN", mpn="CRCW06031K00FKEA", **VISH01),
    R("R267", "47.0k 1%", "R0603", "N_CEIN", AG, mpn="CRCW060347K0FKEA", **VISH01),
    R("R251", "1.00k 1%", "R0603", "ILIM_REL_A", "N_RAIN", mpn="CRCW06031K00FKEA", **VISH01),
    R("R268", "47.0k 1%", "R0603", "N_RAIN", AG, mpn="CRCW060347K0FKEA", **VISH01),
    R("R253", "1.00k 1%", "R0603", "RFC_OFF_J", "N_RFIN", mpn="CRCW06031K00FKEA", **VISH01),
    R("R269", "47.0k 1%", "R0603", "N_RFIN", AG, mpn="CRCW060347K0FKEA", **VISH01),
    ("U202", "LVC1G06", "SN74LVC1G06", "SC70-5", {"1": None, "2": "N_RBIN", "3": AG, "4": "Q201_G", "5": V33},
     dict(mpn="SN74LVC1G06DCKR", mfr="Texas Instruments")),
    C("C202", "100nF 50V X7R", "C0603", V33, AG, mpn="GRM188R71H104KA93D", mfr="Murata"),
    R("R266", "1.00k 1%", "R0603", "ILIM_REL_B", "N_RBIN", mpn="CRCW06031K00FKEA", **VISH01),
    R("R270", "47.0k 1%", "R0603", "N_RBIN", AG, mpn="CRCW060347K0FKEA", **VISH01),
    ("Q203", "PMOS", "BSS84", "SOT-23", {"1": "Q203_G", "2": "REGN", "3": "N_Q203D"},
     dict(mpn="BSS84LT1G", mfr="onsemi")),
    R("R255", "48.7k 1%", "R0603", "N_Q203D", "ILIM_FEED", mpn="CRCW060348K7FKEA", **VISH01),
    R("R271", "47.0k 1%", "R0603", "Q203_G", "REGN", mpn="CRCW060347K0FKEA", **VISH01),
    ("Q201", "NMOS", "2N7002K", "SOT-23", {"1": "Q201_G", "2": AG, "3": "ILIM_HOLD"},
     dict(mpn="2N7002KT1G", mfr="onsemi")),
    R("R252", "47.0k 1%", "R0603", "Q201_G", "REGN", mpn="CRCW060347K0FKEA", **VISH01),
    ("Q202", "NMOS", "2N7002K", "SOT-23", {"1": "Q202_G", "2": AG, "3": "N_Q202D"},
     dict(mpn="2N7002KT1G", mfr="onsemi")),
    R("R257", "59.0k 1%", "R0603", "N_Q202D", "ILIM_HOLD", mpn="CRCW060359K0FKEA", **VISH01),
    R("R254", "47.0k 1%", "R0603", "Q202_G", "REGN", mpn="CRCW060347K0FKEA", **VISH01),
    # EIB DNP set (dec2-eib decision 2, 2026-11-12; r9-2): U203, U204, C203, C204 and R258-R265 are not fitted, so the
    # schematic dnp attribute drives export.sh (BOM, pos and ibom). The copper is unchanged.
    ("U203", "TLV3012", "TLV3012B", "SOT-23-6",
     {"1": "N_U203O", "2": AG, "3": "N_ISP", "4": "N_ISM", "5": "REF203", "6": V33},
     dict(mpn="TLV3012BIDBVR", mfr="Texas Instruments", dnp=True)),
    C("C203", "100nF 50V X7R", "C0603", V33, AG, mpn="GRM188R71H104KA93D", mfr="Murata", dnp=True),
    R("R265", "470 1%", "R0603", "N_U203O", "ILIM_SENSE", mpn="CRCW0603470RFKEA", **VISH01, dnp=True),
    R("R258", "10.0k 1%", "R0603", "ILIM_SNS", "N_ISP", mpn="CRCW060310K0FKEA", **VISH01, dnp=True),
    R("R259", "10.0M 1%", "R0603", "N_ISP", V33, mpn="CRCW060310M0FKEA", **VISH01, dnp=True),
    R("R260", "10.0k 1%", "R0603", "REF203", "N_ISM", mpn="CRCW060310K0FKEA", **VISH01, dnp=True),
    R("R261", "10.0k 1%", "R0603", "N_ISM", AG, mpn="CRCW060310K0FKEA", **VISH01, dnp=True),
    ("U204", "TLV3012", "TLV3012B", "SOT-23-6",
     {"1": "N_U204O", "2": AG, "3": "N_CSP", "4": "REF204", "5": "REF204", "6": V33},
     dict(mpn="TLV3012BIDBVR", mfr="Texas Instruments", dnp=True)),
    C("C204", "100nF 50V X7R", "C0603", V33, AG, mpn="GRM188R71H104KA93D", mfr="Murata", dnp=True),
    R("R264", "470 1%", "R0603", "N_U204O", "CE_SENSE", mpn="CRCW0603470RFKEA", **VISH01, dnp=True),
    R("R262", "1.00M 1%", "R0603", "nCE_SNS", "N_CSP", mpn="CRCW06031M00FKEA", **VISH01, dnp=True),
    R("R263", "1.00M 1%", "R0603", "N_CSP", AG, mpn="CRCW06031M00FKEA", **VISH01, dnp=True),
    R("R275", "1.00k 1%", "R0603", "STAT_E", "STAT", mpn="CRCW06031K00FKEA", **VISH01),
    R("R276", "10.0 1%", "R0603", "REGN_E1", "REGN", mpn="CRCW060310R0FKEA", **VISH01),
    C("C205", "100nF 50V X7R", "C0603", "REGN", AG, mpn="GRM188R71H104KA93D", mfr="Murata"),
    R("R273", "10.0 1%", "R0603", "GND_J", AG, mpn="CRCW060310R0FKEA", **VISH01),
    ("J201", "J2x7", "W5 header", "J2x7_EIB",
     {"1": V33, "2": V33, "3": "GND_J", "4": "STAT", "5": "CE_DRV_J", "6": None, "7": "ILIM_REL_A",
      "8": "ILIM_REL_B", "9": "GND_J", "10": "RFC_OFF_J", "11": "ILIM_SENSE", "12": "GND_J", "13": "CE_SENSE",
      "14": "GND_J"},
     dict(mpn="Samtec FTSH/SHF-107 class (T-A-05)", mfr="Samtec")),
    # E pads (A.9 order top to bottom: E8, -, E3, E4, E2, -, E7, -, E1, -, E5, E6)
    ("E1", "PAD1", "E1 REGN (JP12)", "EPTH_1.0", {"1": "REGN_E1"}, {}),
    ("E2", "PAD1", "E2 ILIM feed", "EPTH_1.0", {"1": "ILIM_FEED"}, {}),
    ("E3", "PAD1", "E3 ILIM hold", "EPTH_1.0", {"1": "ILIM_HOLD"}, {}),
    ("E4", "PAD1", "E4 ILIM sense", "EPTH_1.0", {"1": "ILIM_SNS"}, dict(dnp=True)),   # lead not built (dec2-eib, D-49); pad kept
    ("E5", "PAD1", "E5 nCE drive", "EPTH_1.0", {"1": "nCE_DRV"}, {}),
    ("E6", "PAD1", "E6 nCE sense", "EPTH_1.0", {"1": "nCE_SNS"}, dict(dnp=True)),     # lead not built (dec2-eib, D-49); pad kept
    ("E7", "PAD1", "E7 STAT (TP38)", "EPTH_1.0", {"1": "STAT_E"}, {}),
    ("E8", "PAD1", "E8 AGND (TP49)", "EPTH_1.0", {"1": AG}, {}),
]

BOARDS = {"cr": CR, "eib": EIB}


def nets(parts):
    out = {}
    for ref, kind, val, pkg, pins, o in parts:
        for p, n in pins.items():
            if n is not None:
                out.setdefault(n, []).append("%s.%s" % (ref, p))
    return out


if __name__ == "__main__":
    for b, parts in BOARDS.items():
        ns = nets(parts)
        refs = [p[0] for p in parts]
        assert len(refs) == len(set(refs)), "duplicate ref in %s" % b
        single = {n: m for n, m in ns.items() if len(m) < 2}
        print(b, "parts", len(parts), "nets", len(ns), "single-member nets", single)

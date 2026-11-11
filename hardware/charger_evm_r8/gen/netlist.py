"""Pin-level netlist of the CR (carrier) and the EIB (EVM interface board), transcribed from
docs/charger_bq25798_wiring_design_2026-11-05.md r8, section B.8 (pin -> net), with values and
packages from section E (BOM) and pad geometry from A.8 / A.9.

Every entry cites its B.8 row in a comment where the transcription is not literal. Net names follow
B.8 verbatim where B.8 names the net; where B.8 names only a pad (F01-F24, W1-W7, E1-E8, J101.n)
the net takes the descriptive name recorded in the LAYOUT_DECISIONS.md net-naming table.

Part tuple: (ref, kind, value, package, {pin: net}, opts)
  kind    : symbol template key (see symbols.py)
  package : footprint key (see footprints.py)
  opts    : dict(dnp=bool, side='F'|'B', mpn=str, mfr=str, note=str)
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
    # SN74LVC1G11 DCK: 1 A, 2 GND, 3 B, 4 Y, 5 VCC, 6 C.
    return (ref, "LVC1G11", "SN74LVC1G11", "SC70-6",
            {"1": a, "2": GND, "3": b, "4": y, "5": V33, "6": c},
            dict(mpn="SN74LVC1G11DCKR", mfr="Texas Instruments"))


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
    # ---- CHG header (22 Ag105 holes, A.2 / A.8; pins 1-10 column x 45.998, 11-22 column x 20.998)
    ("J1", "CHG22", "Ag105 CHG header", "CHG22",
     {"1": None, "2": None, "3": "STAT", "4": GND, "5": None, "6": None, "7": "SCL", "8": "SDA",
      "9": None, "10": "VCHGIN", "11": "CHG_ARM", "12": None, "13": "TS_EXT", "14": GND, "15": GND,
      "16": None, "17": None, "18": "VCHG", "19": "VCHG", "20": None, "21": None, "22": None},
     dict(mpn="TSW-110-07-G-S + TSW-112-07-G-S", mfr="Samtec",
          note="pins 1,2,5,6,9,12,16,17,20,21,22 are mechanical anchors (A.2)")),

    # ---- Input bulk, TVS, eFuse (B.4, B.8 row C102a/b/c/D107, U101)
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
    R("R103", "66.5k 0.1%", "R0402", "N_UV", "N_OV", mpn="TNPW040266K5BEED", **VISH01),
    R("R104", "49.9k 0.1%", "R0402", "N_OV", GND, side="B", mpn="TNPW040249K9BEED", **VISH01),
    R("R101", "8.06k 1%", "R0402", "N_ILIM", GND, mpn="CRCW04028K06FKED", **VISH01),
    C("C101", "22nF 50V X7R", "C0402", "N_DVDT", GND, mpn="GRM155R71H223KA12D", mfr="Murata"),
    C("C103", "1uF 50V X7R", "C0805", "VCHGOUT", GND, mpn="GRM21BR71H105KA12L", mfr="Murata"),
    ("D103", "D", "Schottky 40V SMA", "SMA", {"1": "VCHGOUT", "2": GND},
     dict(mpn="selected in T-A-05 (bench fallback B340A-13-F)", mfr="Diodes Inc.")),
    R("R105", "27.4k 1%", "R0402", "N_IMON", GND, mpn="CRCW040227K4FKED", **VISH01),
    # C105 removed: DNP tier 1 (D-31; SLVSE94G 8.3.9 forbids an IMON bypass capacitor)
    R("R129", "10.0k 1%", "R0603", "N_IMON", "CHG_IIN", side="B", mpn="CRCW060310K0FKEA", **VISH01),
    C("C129", "1.0nF 50V C0G", "C0603", "CHG_IIN", GND, side="B", mpn="GRM1885C1H102JA01D", mfr="Murata"),
    # R106 (DNP since r4) is omitted: see LAYOUT_DECISIONS.md D-08 (r8 F17 exposed-copper rule).
    R("R106s", "1.00k 1%", "R0402", "N_FLT", "CHG_EFUSE_FLT", side="B", mpn="CRCW04021K00FKED", **VISH01),

    # ---- U102 H1 comparator
    tlv3012("U102", "H1", "N_H1P", "N_H1M", None),  # B.8: 5 REF nc
    R("R109", "487k 0.1%", "R0805", "T1_VMOT", "N_H1P", mpn="TNPW0805487KBEEA", **VISH01),
    R("R110", "56.2k 0.1%", "R0603", "N_H1P", GND, mpn="TNPW060356K2BEEA", **VISH01),
    C("C106", "470pF 50V C0G", "C0603", "N_H1P", GND, side="B", mpn="GRM1885C1H471JA01D", mfr="Murata"),
    R("R113", "6.49M 1%", "R0603", "H1", "N_H1P", side="B", mpn="CRCW06036M49FKEA", **VISH01),
    bav199("D104", "N_H1P"),
    R("R111", "442k 0.1%", "R0805", "T2C", "N_H1M", mpn="TNPW0805442KBEEA", **VISH01),
    R("R112", "56.2k 0.1%", "R0603", "N_H1M", GND, mpn="TNPW060356K2BEEA", **VISH01),
    C("C107", "470pF 50V C0G", "C0603", "N_H1M", GND, side="B", mpn="GRM1885C1H471JA01D", mfr="Murata"),
    bav199("D105", "N_H1M"),
    # ---- U103 UVB
    tlv3012("U103", "UVB", "N_UVP", "REF103", "REF103"),
    R("R114", "1.00M 0.1%", "R0805", "T2C", "N_UVP", mpn="TNPW08051M00BEEA", **VISH01),
    R("R115", "104k 0.1%", "R0603", "N_UVP", GND, mpn="TNPW0603104KBEEA", **VISH01),
    C("C108", "1.0nF 50V C0G", "C0603", "N_UVP", GND, side="B", mpn="GRM1885C1H102JA01D", mfr="Murata"),
    R("R116", "10.0M 1%", "R0603", "UVB", "N_UVP", side="B", mpn="CRCW060310M0FKEA", **VISH01),
    bav199("D106", "N_UVP"),
    # ---- U104 BT_OK
    tlv3012("U104", "BT_OK", "N_BTP", "N_BTM", "REF104"),
    R("R141", "61.9k 1%", "R0603", "REF104", "N_BTP", side="B", mpn="CRCW060361K9FKEA", **VISH01),
    R("R142", "1.00k SOT", "R0603", "N_BTP", "KELVIN", side="B", mpn="CRCW06031K00FKEA (select-on-test kit)",
      **VISH01),
    R("R143", "100 1%", "R0603", "KELVIN", GND, side="B", mpn="CRCW0603100RFKEA", **VISH01),
    R("R140", "10.0k 1%", "R0603", "BT_CURR", "N_BTM", side="B", mpn="CRCW060310K0FKEA", **VISH01),
    C("C140", "10nF 50V X7R", "C0603", "N_BTM", GND, side="B", mpn="GRM188R71H103KA01D", mfr="Murata"),
    R("R144", "1.00M 1%", "R0603", "BT_CURR", V33, side="B", mpn="CRCW06031M00FKEA", **VISH01),
    # ---- U115 BTB_OFF
    tlv3012("U115", "BTB_OFF", "N_BBP", "N_BBM", "REF115"),
    R("R117", "20.0k 1%", "R0603", "REF115", "N_BBP", side="B", mpn="CRCW060320K0FKEA", **VISH01),
    R("R118", "10.0k 1%", "R0603", "N_BBP", GND, side="B", mpn="CRCW060310K0FKEA", **VISH01),
    C("C109", "100nF 50V X7R", "C0603", "N_BBP", GND, side="B", mpn="GRM188R71H104KA93D", mfr="Murata"),
    R("R120", "10.0k 1%", "R0603", "BTB", "N_BBM", side="B", mpn="CRCW060310K0FKEA", **VISH01),
    R("R119", "10.0M 1%", "R0603", "N_BBM", V33, side="B", mpn="CRCW060310M0FKEA", **VISH01),
    # ---- U117 FCI_OK option (all DNP); R137 fitted
    tlv3012("U117", "FCI_OK", "N_FCP", "N_FCM", "REF117", dnp=True),
    R("R160", "10.0k 1%", "R0603", "REF117", "N_FCP", side="B", dnp=True, mpn="CRCW060310K0FKEA", **VISH01),
    R("R161", "1.18k SOT", "R0603", "N_FCP", GND, side="B", dnp=True, mpn="CRCW06031K18FKEA", **VISH01),
    R("R162", "10.0k 1%", "R0603", "T19_FCI", "N_FCM", side="B", dnp=True, mpn="CRCW060310K0FKEA", **VISH01),
    C("C127", "10nF 50V X7R", "C0603", "N_FCM", GND, side="B", dnp=True, mpn="GRM188R71H103KA01D",
      mfr="Murata"),
    R("R163", "1.00M 1%", "R0603", "FCI_OK", "N_FCP", side="B", dnp=True, mpn="CRCW06031M00FKEA", **VISH01),
    C("C124", "100nF 50V X7R", "C0603", V33, GND, side="B", dnp=True, mpn="GRM188R71H104KA93D", mfr="Murata"),
    R("R137", "0", "R0603", "FCI_OK", V33, side="B", mpn="CRCW06030000Z0EA", **VISH01),
    # ---- RGN / FCC taps
    R("R121", "1.00k 1%", "R0603", "RGN_TAP", "RGN", side="B", mpn="CRCW06031K00FKEA", **VISH01),
    R("R133", "100k 1%", "R0603", "RGN", GND, side="B", mpn="CRCW0603100KFKEA", **VISH01),
    R("R122", "1.00k 1%", "R0603", "FCC_TAP", "FCC", side="B", mpn="CRCW06031K00FKEA", **VISH01),
    # R134 removed: DNP tier 2 (D-31; FCC pull-down, DNP since r6)
    # ---- U119 FCC_OFF
    tlv3012("U119", "FCCN", "N_FOP", "N_FOM", "REF119"),
    R("R184", "20.0k 1%", "R0603", "REF119", "N_FOP", side="B", mpn="CRCW060320K0FKEA", **VISH01),
    R("R185", "10.0k 1%", "R0603", "N_FOP", GND, side="B", mpn="CRCW060310K0FKEA", **VISH01),
    C("C130", "100nF 50V X7R", "C0603", "N_FOP", GND, side="B", mpn="GRM188R71H104KA93D", mfr="Murata"),
    R("R186", "10.0k 1%", "R0603", "FCC", "N_FOM", side="B", mpn="CRCW060310K0FKEA", **VISH01),
    R("R187", "3.30M 1%", "R0603", "N_FOM", V33, side="B", mpn="CRCW06033M30FKEA", **VISH01),
    # ---- U120 FCC_ON
    tlv3012("U120", "FCC_ON", "N_FNP", "REF120", "REF120"),
    R("R188", "453k 1%", "R0603", "FCC", "N_FNP", side="B", mpn="CRCW0603453KFKEA", **VISH01),
    R("R189", "1.00M 1%", "R0603", "N_FNP", GND, side="B", mpn="CRCW06031M00FKEA", **VISH01),
    # ---- U121 RGN_ON
    tlv3012("U121", "RGN_ON", "N_RNP", "REF121", "REF121"),
    R("R190", "453k 1%", "R0603", "RGN", "N_RNP", side="B", mpn="CRCW0603453KFKEA", **VISH01),
    R("R191", "1.00M 1%", "R0603", "N_RNP", GND, side="B", mpn="CRCW06031M00FKEA", **VISH01),
    # ---- BAL input (r6)
    R("R178", "100k 1%", "R0603", "T22_BAL", "N_BAL", side="B", mpn="CRCW0603100KFKEA", **VISH01),
    bav199("D108", "N_BAL"),
    R("R179", "1.00M 1%", "R0603", "N_BAL", V33, side="B", mpn="CRCW06031M00FKEA", **VISH01),
    ("U123", "LVC1G14", "SN74LVC1G14", "SC70-5", {"1": GND, "2": "N_BAL", "3": GND, "4": "OVN", "5": V33},
     dict(mpn="SN74LVC1G14DCKR", mfr="Texas Instruments")),
    ("U122", "LVC1G08", "SN74LVC1G08", "SC70-5", {"1": "ARM_OK", "2": "OVN", "3": GND, "4": "ARM_OKP", "5": V33},
     dict(mpn="SN74LVC1G08DCKR", mfr="Texas Instruments")),
    # ---- logic pull-downs and tap series resistors
    R("R108", "47.0k 1%", "R0603", "CHG_ARM", GND, side="B", mpn="CRCW060347K0FKEA", **VISH01),
    R("R147", "1.00k 1%", "R0603", "QUAL_TAP", "QUAL", side="B", mpn="CRCW06031K00FKEA", **VISH01),
    R("R123", "47.0k 1%", "R0603", "QUAL", GND, side="B", mpn="CRCW060347K0FKEA", **VISH01),
    R("R124", "47.0k 1%", "R0603", "FCCEIL", GND, side="B", mpn="CRCW060347K0FKEA", **VISH01),
    R("R135", "1.00k 1%", "R0603", "HB_TAP", "HB", side="B", mpn="CRCW06031K00FKEA", **VISH01),
    R("R136", "100k 1%", "R0603", "HB", GND, side="B", mpn="CRCW0603100KFKEA", **VISH01),
    # ---- permit logic
    ("U105", "LVC3G04", "SN74LVC3G04", "SSOP-8",
     {"1": GND, "2": None, "3": "CHG_ARM", "4": GND, "5": "P5N", "6": GND, "7": None, "8": V33},
     dict(mpn="SN74LVC3G04DCTR", mfr="Texas Instruments")),
    lvc2g("U106", "LVC2G32", "UF", "H1R", "X", "FCCN", "H1R", "RFC_OFF"),
    lvc1g11("U107", "BT_OK", "X", "FCI_OK", "Y1"),
    lvc1g11("U108", "FCC_ON", "BTB_OFF", "Y1", "H2C"),
    lvc1g11("U109", "H1", "RGN_ON", "W", "H1Q"),
    lvc2g("U110", "LVC2G32", "H1Q", "H2C", "GATE", "GATE", "QQF", "ILIM_PRE"),
    lvc1g123("U111", GND, "QUAL", "P5N", "QQ", "N_CX111", "N_RC111"),
    C("C150", "3.3uF 16V X7R", "C0805", "N_CX111", "N_RC111", side="B", mpn="GRM21BR71C335KA73L", mfr="Murata"),
    R("R150", "100k 1%", "R0603", "N_RC111", V33, side="B", mpn="CRCW0603100KFKEA", **VISH01),
    lvc1g123("U113", GND, "HB", V33, "ARM_OK", "N_CX113", "N_RC113"),
    C("C151", "330nF 16V X7R", "C0603", "N_CX113", "N_RC113", side="B", mpn="GRM188R71C334KA01D", mfr="Murata"),
    R("R151", "100k 1%", "R0603", "N_RC113", V33, side="B", mpn="CRCW0603100KFKEA", **VISH01),
    lvc2g("U114", "LVC2G08", "CHG_ARM", "ARM_OKP", "CE_DRV", "ILIM_PRE", "ARM_OKP", "ILIM_REL"),
    lvc2g("U116", "LVC2G08", "UVB", "FCCEIL", "UF", "FCCN", "UVB", "W"),
    lvc2g("U118", "LVC2G08", "H1", "RGN_ON", "H1R", "QQ", "FCCN", "QQF"),
    # ---- readbacks (B.8 "Readbacks")
    R("R126", "1.00k 1%", "R0603", "H1", "H1_RB", side="B", mpn="CRCW06031K00FKEA", **VISH01),
    R("R127", "1.00k 1%", "R0603", "H2C", "H2C_RB", side="B", mpn="CRCW06031K00FKEA", **VISH01),
    R("R128", "1.00k 1%", "R0603", "BT_OK", "BTOK_RB", side="B", mpn="CRCW06031K00FKEA", **VISH01),
    R("R125", "1.00k 1%", "R0603", "ILIM_SENSE", "ILIM_SENSE_RB", side="B", mpn="CRCW06031K00FKEA", **VISH01),
    R("R148", "1.00k 1%", "R0603", "CE_SENSE", "CE_SENSE_RB", side="B", mpn="CRCW06031K00FKEA", **VISH01),
    # ---- ribbon drivers
    R("R130", "100 1%", "R0603", "CE_DRV", "CE_DRV_J", side="B", mpn="CRCW0603100RFKEA", **VISH01),
    R("R131A", "100 1%", "R0603", "ILIM_REL", "ILIM_REL_A", side="B", mpn="CRCW0603100RFKEA", **VISH01),
    R("R131B", "100 1%", "R0603", "ILIM_REL", "ILIM_REL_B", side="B", mpn="CRCW0603100RFKEA", **VISH01),
    R("R132", "100 1%", "R0603", "RFC_OFF", "RFC_OFF_J", side="B", mpn="CRCW0603100RFKEA", **VISH01),
    # ---- 3V3 feed (r4)
    R("R175", "68.0 1% 0.25W", "R1206", "T6_3V3", V33, mpn="CRCW120668R0FKEA", **VISH01),
    R("R176", "200 1%", "R0603", V33, "J3V3_1", side="B", mpn="CRCW0603200RFKEA", **VISH01),
    R("R177", "200 1%", "R0603", V33, "J3V3_2", side="B", mpn="CRCW0603200RFKEA", **VISH01),
    C("C125", "10uF 10V X7R", "C0805", V33, GND, side="B", mpn="GRM21BR71A106KE51L", mfr="Murata"),
    # ---- J101 ribbon header (2x7 1.27 mm SMT, position 6 omitted)
    ("J101", "J2x7K", "W5 header", "J2x7_NOPIN6",
     {"1": "J3V3_1", "2": "J3V3_2", "3": GND, "4": "STAT", "5": "CE_DRV_J", "7": "ILIM_REL_A",
      "8": "ILIM_REL_B", "9": GND, "10": "RFC_OFF_J", "11": "ILIM_SENSE", "12": GND, "13": "CE_SENSE",
      "14": GND},
     dict(mpn="FTSH-107-01-L-DV class (T-A-05)", mfr="Samtec")),
    R("R107", "10.0k 1%", "R0603", "STAT", V33, side="B", mpn="CRCW060310K0FKEA", **VISH01),
    # R145, R146 removed: DNP tier 1 (D-31; the I2C pull-ups stay on the MB 3V3 side, A.2)
    # ---- keep-alive option (B.5) removed: DNP tier 2 (D-31; operator ruling 2026-11-11). F22 (T18) pad kept.
    # ---- decoupling (B.8 "Decoupling"): every VCC/V+ cap is placed under its IC on the bottom
    *[C(c, "100nF 50V X7R", "C0603", V33, GND, side="B", mpn="GRM188R71H104KA93D", mfr="Murata")
      for c in ("C110", "C111", "C112", "C113", "C114", "C115", "C116", "C117", "C118", "C119", "C120", "C121",
                "C122", "C123", "C126", "C131", "C132", "C133", "C134", "C135")],
    # ---- power and lead pads (B.8 "Power holes and pads (r5)")
    ("W1", "PAD1", "W1 VCHGOUT", "WPTH_1.3", {"1": "VCHGOUT"}, {}),
    ("W2", "PAD1", "W2 GND", "WPTH_1.3", {"1": GND}, {}),
    ("W3", "PAD1", "W3 VCHG", "WPTH_1.5", {"1": "VCHG"}, {}),
    ("W4", "PAD1", "W4 GND", "WPTH_1.5", {"1": GND}, {}),
    ("W6", "PAD2", "W6 TS_EXT/GND", "WSMD_2", {"1": "TS_EXT", "2": GND}, {}),
    ("W7", "PAD3", "W7 SCL/GND/SDA", "WSMD_3", {"1": "SCL", "2": GND, "3": "SDA"}, {}),
    # ---- tap field F01-F24 (B.8 "Tap field"; A.8 r7 assignment)
    tap("F01", "T1_VMOT"), tap("F02", GND), tap("F03", "T2C"), tap("F04", "BTB"), tap("F05", "RGN_TAP"),
    tap("F06", "FCC_TAP"), tap("F07", "T6_3V3"), tap("F08", "T22_BAL"), tap("F09", "BT_CURR"),
    tap("F10", "KELVIN"), tap("F11", "QUAL_TAP"), tap("F12", "FCCEIL"), tap("F13", "ILIM_SENSE_RB"),
    tap("F14", "H1_RB"), tap("F15", "H2C_RB"), tap("F16", "BTOK_RB"), tap("F17", "CHG_EFUSE_FLT"),
    tap("F18", "CHG_IIN"), tap("F19", GND), tap("F20", "CE_SENSE_RB"), tap("F21", "HB_TAP"),
    tap("F22", None),  # T18 pad kept, no CR net after DNP tier 2 (D-31)
    tap("F23", "T19_FCI"), tap("F24", None),
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
    ("U203", "TLV3012", "TLV3012B", "SOT-23-6",
     {"1": "N_U203O", "2": AG, "3": "N_ISP", "4": "N_ISM", "5": "REF203", "6": V33},
     dict(mpn="TLV3012BIDBVR", mfr="Texas Instruments")),
    C("C203", "100nF 50V X7R", "C0603", V33, AG, mpn="GRM188R71H104KA93D", mfr="Murata"),
    R("R265", "470 1%", "R0603", "N_U203O", "ILIM_SENSE", mpn="CRCW0603470RFKEA", **VISH01),
    R("R258", "10.0k 1%", "R0603", "ILIM_SNS", "N_ISP", mpn="CRCW060310K0FKEA", **VISH01),
    R("R259", "10.0M 1%", "R0603", "N_ISP", V33, mpn="CRCW060310M0FKEA", **VISH01),
    R("R260", "10.0k 1%", "R0603", "REF203", "N_ISM", mpn="CRCW060310K0FKEA", **VISH01),
    R("R261", "10.0k 1%", "R0603", "N_ISM", AG, mpn="CRCW060310K0FKEA", **VISH01),
    ("U204", "TLV3012", "TLV3012B", "SOT-23-6",
     {"1": "N_U204O", "2": AG, "3": "N_CSP", "4": "REF204", "5": "REF204", "6": V33},
     dict(mpn="TLV3012BIDBVR", mfr="Texas Instruments")),
    C("C204", "100nF 50V X7R", "C0603", V33, AG, mpn="GRM188R71H104KA93D", mfr="Murata"),
    R("R264", "470 1%", "R0603", "N_U204O", "CE_SENSE", mpn="CRCW0603470RFKEA", **VISH01),
    R("R262", "1.00M 1%", "R0603", "nCE_SNS", "N_CSP", mpn="CRCW06031M00FKEA", **VISH01),
    R("R263", "1.00M 1%", "R0603", "N_CSP", AG, mpn="CRCW06031M00FKEA", **VISH01),
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
    ("E4", "PAD1", "E4 ILIM sense", "EPTH_1.0", {"1": "ILIM_SNS"}, {}),
    ("E5", "PAD1", "E5 nCE drive", "EPTH_1.0", {"1": "nCE_DRV"}, {}),
    ("E6", "PAD1", "E6 nCE sense", "EPTH_1.0", {"1": "nCE_SNS"}, {}),
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

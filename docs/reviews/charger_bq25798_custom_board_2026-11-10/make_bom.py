# Builds bom.csv and the cost roll-up for design document section 4 (deliverable 4, custom BQ25798 charger board, CCB).
# Price kinds: V = verified TI store price 2026-11-10 (1-99 tier); V* = TI store, price of a sibling orderable;
# A3 = round-3 recorded allowance (wiring design section E, unverified); AL = allowance set in design document section 4 (not a quote);
# T = TODO(verify: price), no number.
# Scope: b = per populated board; build = once per build; mb = once per vehicle motherboard; lot = PCB lot.
import csv, json, sys, pathlib
OUT = pathlib.Path(sys.argv[1])
D = "2026-11-10"
TI = "TI store"
def tiurl(fam, opn): return f"https://www.ti.com/product/{fam}/part-details/{opn}"
INV = "https://www.ti.com/storeservices/cart/opninventory?opn="
L = []
def add(ref, q, sp, val, rat, pkg, mpn, mfr, dist, p1, kind, stock, url, cls, r3, scope="b"):
    L.append(dict(ref=ref, q=q, sp=sp, val=val, rat=rat, pkg=pkg, mpn=mpn, mfr=mfr, dist=dist, p1=p1, kind=kind,
                  stock=stock, url=url, cls=cls, r3=r3, scope=scope))
NS = "TODO(verify: stock)"
# ---------------- Power stage (BQ25798-specific) ----------------
add("U501",1,2,"BQ25798 charger","VBUS/PMID/VAC/SW1 30 V abs max","VQFN-HR 29 (RQM) 4x4x1.0","BQ25798RQMR","Texas Instruments",TI,5.038,"V","415146",tiurl("BQ25798","BQ25798RQMR")+" ; "+INV+"BQ25798RQMR","S","EVM U1")
add("L501",1,1,"1.0 uH","Isat >= 6.5 A required; 11.1 A per UG Table 4-1, basis TODO(verify: TDK DS)","7.1x6.5x3.0 mm","SPM6530T-1R0M120","TDK","distributor",3.0,"AL",NS,"","S","EVM L2")
add("C511 C512 C529 C530 C531",5,3,"10 uF X7R","50 V (input side, >= 35 V rule; VBUS/PMID <= 23.63 V eFuse OVP)","1210 (1206 acceptable)","GRM32ER71H106KA12L (candidate, TODO(verify: Murata DS and DC-bias at 23.6 V; T-A-04 gates C_VBUS >= 2 uF and C_PMID >= 4 uF, SLUSDV2C 6.3)); no 0805 fallback (35 V X5R 0805 deleted: outside the 1210/1206 footprint and area plan, DC-bias case not made)","Murata","distributor",1.0,"AL",NS,"","S","EVM C11 C12 C29-C31")
add("C513 C514 C532 C518",4,4,"0.1 uF X7R","50 V (TDK code 1H, TODO(verify: TDK DS)); C513 VBUS, C514 VAC1/VAC2 and C532 PMID are input side: >= 35 V rule, node max 23.63 V eFuse OVP (PMID follows VBUS through the RBFET); C518 SYS is output side (SYS 23 V abs max, SLUSDV2C 6.1) and shares the 0402 MPN","0402","C1005X7R1H104K050BE","TDK","distributor","","T",NS,"","S","EVM C13 C14(+C15) C32 C18")
add("C519 C520 C521 C522 C523",5,3,"10 uF X5R","25 V","0805","C2012X5R1E106K125AB","TDK","distributor","","T",NS,"","S","EVM C19-C23")
add("C538 C539",2,2,"10 uF X5R","25 V","0603","GRT188R61E106ME13D","Murata","distributor","","T",NS,"","S","EVM C38 C39")
add("C506 C508",2,2,"47 nF X7R","25 V","0402","GRM155R71E473KA88D","Murata","distributor","","T",NS,"","S","EVM C6 C8")
add("C535",1,2,"4.7 uF X5R","16 V","0603","GRM188R61C475KAAJD","Murata","distributor","","T",NS,"","S","EVM C35")
add("C536",1,2,"1.0 nF C0G, SDRV to GND","50 V","0402","GRM1555C1H102JA01D","Murata","distributor","","T",NS,"","S","EVM C36 (re-wired, SLUSDV2C rev C)")
add("R515",1,2,"100 Ohm 1 %","-","0603","RC0603FR-07100RL","Yageo","distributor","","T",NS,"","S","EVM R15")
add("R529",1,2,"6.04 kOhm 1 %, PROG 2S 1.5 MHz","-","0603","CRCW06036K04FKEA (candidate, TODO(verify: Vishay range))","Vishay","distributor","","T",NS,"","S","EVM R29 (EVM BOM lists 6.20 k)")
add("R507 R510 (DNP)",0,2,"2.0 Ohm","-","0603","CRCW06032R00JNEA","Vishay","distributor","","T","-","","S","EVM R7 R10")
add("C505 C507 (DNP)",0,2,"2.2 nF C0G","50 V","0603","GRM1885C1H222JA01D","Murata","distributor","","T","-","","S","EVM C5 C7")
add("R541 C541 (DNP)",0,0,"2.0 Ohm + 2.2 uF","C541 >= 50 V","1206/1210","TODO(verify)","-","-","","T","-","","S","EVM RSNUB1 CSNUB1")
add("R506 (DNP)",0,0,"0 Ohm","-","0402","-","-","-","","T","-","","S","new")
# ---------------- Input protection (IC-independent) ----------------
add("U301",1,1,"eFuse 60 V, adjustable OVP","IN abs max 67 V","VQFN-24 (RGE) 4x4","TPS26630RGER","Texas Instruments",TI,4.812,"V*","53000 (RGER)",tiurl("TPS2663","TPS26630RGERG4")+" (price of RGERG4; no RGER part-details page) ; "+INV+"TPS26630RGER","I","U101")
add("R301",1,1,"8.06 kOhm 1 %","-","0402","CRCW04028K06FKED","Vishay","distributor","","T",NS,"","I","R101")
add("R305",1,1,"27.4 kOhm 1 %","-","0402","CRCW040227K4FKED","Vishay","distributor","","T",NS,"","I","R105")
add("R302",1,1,"845 kOhm 0.1 %","limiting element voltage TODO(verify: Vishay TNPW DS)","0805","TNPW0805845KBEEA","Vishay","distributor",0.5,"A3",NS,"","I","R102")
add("R303",1,1,"66.5 kOhm 0.1 %","-","0402","TNPW040266K5BEED","Vishay","distributor",0.5,"A3",NS,"","I","R103")
add("R304",1,1,"49.9 kOhm 0.1 %","-","0402","TNPW040249K9BEED","Vishay","distributor",0.5,"A3",NS,"","I","R104")
add("C301",1,1,"22 nF X7R","50 V","0402","GRM155R71H223KA12D","Murata","distributor","","T",NS,"","I","C101")
add("C302a",1,1,"1.0 uF X7R","100 V","1206","GRM31CR72A105KA01L (candidate)","Murata","distributor",0.3,"A3",NS,"","I","C102a")
add("C302b",1,1,"4.7 uF X7R/X7S","100 V","1210","C3225X7S2A475K class (candidate)","TDK","distributor",0.8,"A3",NS,"","I","C102b")
add("C302c",1,1,"100 nF X7R","100 V","0603","GRM188R72A104KA35D (candidate)","Murata","distributor","","T",NS,"","I","C102c")
add("D307",1,1,"TVS, unidirectional","VRWM >= 30 V, VBR(min) >= 36 V","SMA","SMAJ33A class (MPN selected in T-A-05)","TODO(verify)","distributor",0.5,"A3",NS,"","I","D107")
add("C303",1,1,"1.0 uF X7R","50 V","0805","GRM21BR71H105KA12L","Murata","distributor","","T",NS,"","I","C103")
add("D303",1,1,"Schottky",">= 40 V; IR <= 0.1 mA at 23.6 V / 60 C","SMA","selected in T-A-05; bench-only fallback B340A-13-F","Diodes Inc. (fallback)","distributor",0.5,"A3",NS,"","I","D103")
add("C305 R306 (DNP)",0,0,"footprints","-","0402/0603","-","-","-","","T","-","","I","C105 R106")
# ---------------- Charger interface (BQ25798-specific) ----------------
add("U401",1,1,"triple open-drain inverter","VCC 3.3 V","SSOP-8 (DCT)","SN74LVC3G06DCTR","Texas Instruments",TI,0.830,"V","43837",tiurl("SN74LVC3G06","SN74LVC3G06DCTR"),"S","U201")
add("U402",1,1,"single open-drain inverter","VCC 3.3 V","SC70-5 (DCK)","SN74LVC1G06DCKR","Texas Instruments",TI,0.109,"V","874",tiurl("SN74LVC1G06","SN74LVC1G06DCKR"),"S","U202")
add("Q401 Q402",2,3,"N-MOSFET, logic level","60 V","SOT-23","2N7002KT1G","onsemi","distributor",0.2,"A3",NS,"","S","Q201 Q202")
add("Q403",1,2,"P-MOSFET, |VGS(th)| <= 2.0 V","50 V","SOT-23","BSS84LT1G","onsemi","distributor",0.2,"A3",NS,"","S","Q203")
add("R518",1,1,"5.23 kOhm 1 %","-","0402","CRCW04025K23FKED","Vishay","distributor","","T",NS,"","S","EVM R18")
add("R524",1,1,"30.1 kOhm 1 %","-","0402","CRCW040230K1FKED","Vishay","distributor","","T",NS,"","S","EVM R24")
add("R525 (XOR R526, by T-E-09)",1,1,"10.0 kOhm 1 %, NTC simulator","-","0402","CRCW040210K0FKED","Vishay","distributor","","T",NS,"","S","EVM R25 via JP18")
add("R526 (XOR R525, by T-E-09)",0,2,"0 Ohm, pack NTC link","-","0603","CRCW06030000Z0EA","Vishay","distributor","","T",NS,"","S","EVM J7 / lead W6")
add("R523",1,1,"49.9 kOhm 1 %","-","0603","CRCW060349K9FKEA","Vishay","distributor","","T",NS,"","S","EVM R23 (EM4)")
add("R456",1,1,"200 kOhm 1 %","-","0603","CRCW0603200KFKEA","Vishay","distributor","","T",NS,"","S","R256 (EM5)")
add("C452",1,1,"2.2 nF C0G","50 V","0603","GRM1885C1H222JA01D","Murata","distributor","","T",NS,"","S","C252 (EM5)")
add("R455",1,1,"48.7 kOhm 1 %","-","0603","CRCW060348K7FKEA","Vishay","distributor","","T",NS,"","S","R255")
add("R457",1,1,"59.0 kOhm 1 %","-","0603","CRCW060359K0FKEA","Vishay","distributor","","T",NS,"","S","R257")
add("R521 (DNP)",0,0,"10.0 kOhm","-","0603","-","-","-","","T","-","","S","new")
# ---------------- Comparators ----------------
add("U302 U303 U304 U315 U319 U320 U321 U403 U404",9,2,"comparator + 1.242 V reference, push-pull","V+ 3.3 V","SOT-23-6 (DBV)","TLV3012BIDBVR","Texas Instruments",TI,2.079,"V","29409",tiurl("TLV3012B","TLV3012BIDBVR"),"M (7 I; U403 U404 S)","U102-U104 U115 U119-U121 U203 U204")
add("U317 (DNP)",0,0,"comparator, FCI_OK option","-","SOT-23-6 (DBV)","TLV3012BIDBVR","Texas Instruments",TI,2.079,"V","29409",tiurl("TLV3012B","TLV3012BIDBVR"),"I","U117 (DNP)")
add("R309",1,1,"487 kOhm 0.1 %","-","0805","TNPW0805487KBEEA","Vishay","distributor",0.5,"A3",NS,"","I","R109")
add("R311",1,1,"442 kOhm 0.1 %","-","0805","TNPW0805442KBEEA","Vishay","distributor",0.5,"A3",NS,"","I","R111")
add("R310 R312",2,1,"56.2 kOhm 0.1 %","-","0603","TNPW060356K2BEEA","Vishay","distributor",0.5,"A3",NS,"","I","R110 R112")
add("R314",1,1,"1.00 MOhm 0.1 %","-","0805","TNPW08051M00BEEA","Vishay","distributor",0.5,"A3",NS,"","I","R114")
add("R315",1,1,"104 kOhm 0.1 %","-","0603","TNPW0603104KBEEA","Vishay","distributor",0.5,"A3",NS,"","I","R115")
add("R313",1,1,"6.49 MOhm 1 %","-","0603","CRCW06036M49FKEA","Vishay","distributor","","T",NS,"","I","R113")
add("R341",1,1,"61.9 kOhm 1 %","-","0603","CRCW060361K9FKEA","Vishay","distributor","","T",NS,"","I","R141")
add("R342 (select-on-test kit)",1,0,"0.604 / 0.715 / 0.825 / 1.00 / 1.21 / 1.40 kOhm 1 %, 2 of each per build","-","0603","CRCW0603xxxxFKEA kit","Vishay","distributor","","T",NS,"","I","R142 kit")
add("R343",1,1,"100 Ohm 1 %","-","0603","CRCW0603100RFKEA","Vishay","distributor","","T",NS,"","I","R143")
add("R387",1,1,"3.30 MOhm 1 %","-","0603","CRCW06033M30FKEA","Vishay","distributor","","T",NS,"","I","R187")
add("R388 R390",2,1,"453 kOhm 1 %","-","0603","CRCW0603453KFKEA","Vishay","distributor","","T",NS,"","I","R188 R190")
add("R317 R384",2,1,"20.0 kOhm 1 %","-","0603","CRCW060320K0FKEA","Vishay","distributor","","T",NS,"","I","R117 R184")
add("R316 R319 R459",3,1,"10.0 MOhm 1 %","-","0603","CRCW060310M0FKEA","Vishay","distributor","","T",NS,"","M (R459 S)","R116 R119 R259")
add("R337",1,1,"0 Ohm, FCI_OK link","-","0603","CRCW06030000Z0EA","Vishay","distributor","","T",NS,"","I","R137")
add("R334 R360-R363 C324 C327 (DNP)",0,0,"FCI_OK option parts","-","0603","per WD E","-","-","","T","-","","I","R134 R160-R163 C124 C127")
add("C336 C337 C453 (DNP)",0,0,"100 pF C0G, comparator-input filter footprints at N_FNP, N_RNP, N_CSP; fit per T-K-09 step 5 (design document section 2.5.6)","50 V","0603","GRM1885C1H101JA01D (candidate, TODO(verify: Murata DS))","Murata","distributor","","T","-","","M (C453 S)","new")
add("D304 D305 D306 D308",4,2,"low-leakage diode pair","-","SOT-23","BAV199,215","Nexperia","distributor",0.2,"A3",NS,"","I","D104-D106 D108")
add("C306 C307",2,1,"470 pF C0G","50 V","0603","GRM1885C1H471JA01D","Murata","distributor","","T",NS,"","I","C106 C107")
add("C308 C329",2,1,"1.0 nF C0G","50 V","0603","GRM1885C1H102JA01D","Murata","distributor","","T",NS,"","I","C108 C129")
add("C340",1,1,"10 nF X7R","50 V","0603","GRM188R71H103KA01D","Murata","distributor","","T",NS,"","I","C140")
# ---------------- Logic ----------------
add("U305",1,1,"triple inverter","3.3 V","SSOP-8 (DCT)","SN74LVC3G04DCTR","Texas Instruments",TI,0.818,"V","21705",tiurl("SN74LVC3G04","SN74LVC3G04DCTR"),"I","U105")
add("U306 U310",2,1,"dual OR","3.3 V","SSOP-8 (DCT)","SN74LVC2G32DCTR","Texas Instruments",TI,0.761,"V","1801",tiurl("SN74LVC2G32","SN74LVC2G32DCTR"),"I","U106 U110")
add("U307 U308 U309",3,1,"3-input AND","3.3 V","SC70-6 (DCK)","SN74LVC1G11DCKR","Texas Instruments",TI,0.161,"V","2547",tiurl("SN74LVC1G11","SN74LVC1G11DCKR"),"I","U107-U109")
add("U311 U313",2,1,"retriggerable monostable","3.3 V","SSOP-8 (DCT)","SN74LVC1G123DCTR","Texas Instruments",TI,1.703,"V","2735",tiurl("SN74LVC1G123","SN74LVC1G123DCTR"),"M (U311 S, U313 I)","U111 U113")
add("U314 U316 U318",3,1,"dual AND","3.3 V","SSOP-8 (DCT)","SN74LVC2G08DCTRE4 (DCTR stock 0 on 2026-11-10)","Texas Instruments",TI,0.861,"V","DCTRE4 142215; DCTRG4 5103; DCTR 0",tiurl("SN74LVC2G08","SN74LVC2G08DCTRE4"),"I","U114 U116 U118")
add("U322",1,1,"single AND","3.3 V","SC70-5 (DCK)","SN74LVC1G08DCKR","Texas Instruments",TI,0.069,"V","734408",tiurl("SN74LVC1G08","SN74LVC1G08DCKR"),"I","U122")
add("U323",1,1,"single Schmitt inverter","3.3 V","SC70-5 (DCK)","SN74LVC1G14DCKR","Texas Instruments",TI,0.108,"V","596127",tiurl("SN74LVC1G14","SN74LVC1G14DCKR"),"I","U123")
add("C350",1,1,"3.3 uF X7R, QUAL timing","16 V","0805","GRM21BR71C335KA73L","Murata","distributor","","T",NS,"","S","C150")
add("C351",1,1,"330 nF X7R, heartbeat timing","16 V","0603","GRM188R71C334KA01D","Murata","distributor","","T",NS,"","I","C151")
add("R375",1,1,"68.0 Ohm 1 % 0.25 W","-","1206","CRCW120668R0FKEA","Vishay","distributor","","T",NS,"","I","R175")
add("C325",1,1,"10 uF X7R","10 V","0805","GRM21BR71A106KE51L","Murata","distributor","","T",NS,"","I","C125")
add("R345 R346 (DNP)",0,0,"I2C pull-up footprints","-","0603","-","-","-","","T","-","","I","R145 R146")
# ---------------- Shared values ----------------
add("R307 R318 R320 R329 R340 R385 R386 R458 R460 R461 R474",11,3,"10.0 kOhm 1 %","-","0603","CRCW060310K0FKEA","Vishay","distributor","","T",NS,"","M (R458 R460 R461 S)","R107 R118 R120 R129 R140 R185 R186 R258 R260 R261 R274")
add("R308 R323 R324 R452 R454 R467 R468 R469 R470 R471 R472 R472b",12,3,"47.0 kOhm 1 %","-","0603","CRCW060347K0FKEA","Vishay","distributor","","T",NS,"","M (R4xx and R323 S)","R108 R123 R124 R252 R254 R267-R271 R272 R272b")
add("R321 R322 R325 R326 R327 R328 R335 R347 R348 R475",10,3,"1.00 kOhm 1 %","-","0603","CRCW06031K00FKEA","Vishay","distributor","","T",NS,"","M (R325 R347 R348 R475 S)","R121 R122 R125-R128 R135 R147 R148 R275")
add("R333 R336 R350 R351 R378",5,2,"100 kOhm 1 %","-","0603","CRCW0603100KFKEA","Vishay","distributor","","T",NS,"","M (R350 S)","R133 R136 R150 R151 R178")
add("R344 R379 R389 R391 R462 R463",6,2,"1.00 MOhm 1 %","-","0603","CRCW06031M00FKEA","Vishay","distributor","","T",NS,"","M (R462 R463 S)","R144 R179 R189 R191 R262 R263")
add("C309 C330 C310-C323 C326 C331-C335 C401-C404",26,5,"100 nF X7R","50 V","0603","GRM188R71H104KA93D","Murata","distributor","","T",NS,"","M (C401-C404 S)","C109 C130 C110-C123 C126 C131-C135 C201-C204")
# ---------------- Keep-alive option (DNP) ----------------
add("U312 (DNP)",0,1,"load switch 18 V","-","SOT-23-6 (DBV)","TPS22810DBVR","Texas Instruments",TI,0.492,"V","105",tiurl("TPS22810","TPS22810DBVR"),"I","U112 (DNP)")
add("D301 C352 R392 (DNP)",0,0,"Schottky; 2.2 nF C0G; 680 Ohm 0.25 W","-","SOD-323 / 0603 / 1206","BAT54HT1G; GRM1885C1H222JA01D; CRCW1206680RFKEA","onsemi; Murata; Vishay","distributor","","T","-","","I","D101 C152 R_KA (DNP)")
# ---------------- Header and mechanics ----------------
# r2 (testbench facts, operator statement 2026-11-10): the fan channel needs H_u 5.1-8.1 mm (design document 1.3.2 rule 3),
# so the headers become tall-stack classes S1/S2 (pin length >= 10.8-13.8 mm) and the option-K socket an elevated class (K2/K3).
# The r1 allowance of USD 2.0 per strip (standard TSW) and USD 4.0 per socket strip (SSW) rises to 3.0 and 6.0 (AL, not quotes).
add("H301 pads 1-10",1,1,"1x10 0.64 mm square-pin header, 2.54 mm pitch, tall stack: pin length >= 10.8 mm (H_u 5.1 mm) to >= 13.8 mm (H_u 8.1 mm)","pin current >= 3 A (pins 4, 10) TODO(verify: Samtec, O-10)","TH","TSW-110 long-post lead style (S1) or MTSW-110 movable body (S2), class only; TODO(verify: Samtec drawing, lead style for the chosen H_u)","Samtec","distributor",3.0,"AL",NS,"","I","CHG header pins (TSW-110-07-G-S in r1)")
add("H301 pads 11-22",1,1,"1x12 0.64 mm square-pin header, 2.54 mm pitch, tall stack as pads 1-10",">= 2.0 A (pins 14, 15, 18, 19) TODO(verify: Samtec)","TH","TSW-112 long-post lead style (S1) or MTSW-112 movable body (S2), class only; TODO(verify: Samtec drawing)","Samtec","distributor",3.0,"AL",NS,"","I","CHG header pins (TSW-112-07-G-S in r1)")
add("MB socket strips, option K",2,0,"1x10 + 1x12 elevated female socket strips for 0.64 mm posts, seat height h_k = H_u - 2.54 mm (2.6-5.6 mm)","tail fits the 1.10 mm MB drill TODO(verify: drawing)","TH","ESQ-110 / ESQ-112 elevated class (K2) or Harwin M20 female + long-pin male (K3), candidates only; TODO(verify: Samtec/Harwin drawing, tail, accepted pin range, seat height)","Samtec / Harwin (candidate)","distributor",6.0,"AL",NS,"","I","new (sec_mechanics 1.3.4 option K; SSW class in r1)","mb")
add("F01-F21 tap pins (F22 F23 DNP; F24 spare, no pin)",21,10,"single 0.64 mm male pin, wire soldered","-","TH","TSW-101-07-G-S","Samtec","distributor",0.5,"AL",NS,"","I","Tap pins")
add("Support feet",2,2,"nylon M3 female-female hex spacer (length = H_u from dry fit M3; 5-8 mm for the r2 gap band, standard catalogue lengths), one end bonded to the MB mask, so the top thread is blind; nylon M3 pan-head screw + nylon M3 flat washer from the CCB top","no threadlocker and no nut (blind female thread); thread engagement <= spacer thread depth - 0.5 mm TODO(verify: spacer drawing); tighten to T_s with a torque screwdriver, T_s TODO(verify: nylon screw datasheet; T_s below the bond torsion breakaway of T-K-18)","-","TODO(verify: spacer length after the dry fit; screw length from engagement rule)","-","distributor",1.0,"AL","-","","I","Hardware (6 standoffs become 2 feet)")
add("Foot adhesive",1,0,"epoxy with a datasheet shear strength and solder-mask adhesion; no threadlocker on the foot screws","-","-","TODO(verify: adhesive datasheet)","-","distributor",15.0,"AL","-","","I","new","build")
add("Torque screwdriver (tool, not in the roll-up)",0,0,"adjustable, range covering T_s for M3 nylon screws","-","-","TODO(verify: operator tool availability)","-","distributor","","T","-","","I","new","build")
add("Polyimide sheet",1,1,"0.125 mm polyimide film, silicone PSA, CCB outline + 1 mm including rect A","-","-","no MPN (WD E)","-","distributor",10.0,"A3","-","","I","Polyimide sheet (r5)","build")
add("RTV",1,0,"neutral-cure silicone RTV: tap strain relief and inductor staking","-","-","Dow 3145 / 3140 class (WD E)","Dow (class)","distributor",15.0,"A3","-","","I","Adhesive (r5)","build")
add("Thermocouple",1,0,"fine type-K, Kapton-bondable","-","-","-","-","distributor",15.0,"A3","-","","I","Thermocouple (r6)","build")
# ---------------- Forced air on the testbench (r2; design document 1.6.3, 3.7.2a) ----------------
add("Fan",1,0,"axial DC fan for the low-y inlet, 25-30 mm frame class; >= 3.9-11.8 CFM free-air rating; static pressure above the bare-channel 5.4-12.7 Pa by the duct and obstacle losses (layout_calc_out.txt 8.9; design document 1.6.3); supply voltage matched to the bench supply","not on the LM1084 / CO-5V rail","-","TODO(verify: fan MPN, airflow and static-pressure curve, current)","-","distributor",10.0,"AL","-","","I","new (r2)","build")
add("Fan lead and connector",1,0,"2-wire fan lead with an inline 2-pin connector to the bench supply (or to the optional own regulator); no CCB or MB connector","-","-","TODO(verify: connector MPN)","-","distributor",3.0,"AL","-","","I","new (r2)","build")
add("Fan mount and duct",1,0,"bracket or printed frame holding the fan at the low-y edge, frame edge >= 2.35 mm above the MB; optional side baffles; no contact with MB copper","-","-","no MPN (operator-made)","-","distributor",5.0,"AL","-","","I","new (r2)","build")
add("Fan regulator (DNP option)",0,0,"own regulator for the fan when the bench supply voltage does not match the fan; never the LM1084 / CO-5V rail","-","-","TODO(verify: only if needed)","-","-","","T","-","","I","new (r2)","build")
add("Soak thermocouples",1,0,"lot of 6 fine type-K thermocouples for the fan-on / fan-off soak (U501 top, L1 PGND pour, L501, MB under the cell, inlet air, outlet air; design document 3.7.3a)","-","-","-","-","distributor",20.0,"AL","-","","I","new (r2)","build")
add("Anemometer (tool, not in the roll-up)",0,0,"vane or hot-wire anemometer for the inlet and gap velocity","-","-","TODO(verify: instrument availability)","-","-","","T","-","","I","new (r2)","build")
add("U501 heatsink (DNP option)",0,0,"top-side heatsink on the U501 mould compound, R_sa <= 60 C/W, clear of L501; thermal adhesive or clip","-","-","TODO(verify: heatsink and adhesive datasheets)","-","-","","T","-","","S","new (r2)","b")
add("Gap pad (not fitted)",0,0,"compressed thermal gap pad of r1 (section 3.7.4); superseded by forced air on the testbench (operator statement, 2026-11-10); never booked in r1","-","-","-","-","-","","T","-","","I","r1 option, not fitted","b")
add("Wire",1,0,"26 AWG two colours >= 5 m; 28 AWG Kynar 2 m; 30 AWG Kynar 0.3 m; 28 AWG twisted triple 1 m; 0.5 mm tinned Cu 0.25 m","-","-","-","-","distributor",10.0,"AL","-","","I","Wire (18/20 AWG lead wire deleted)","build")
add("Stencil",1,0,"stainless top-side SMT stencil; U501 apertures per SLUSDV2C p.150","-","-","fab quote TODO(verify)","-","PCB fab",25.0,"AL","-","","S (U501 apertures) / I","new","build")
# ---------------- MB rework parts (IC-independent) ----------------
add("MB C-D8 C-D10 (PM2)",2,2,"10 uF X5R","35 V","0805","GRM21BR6YA106KE43L","Murata","distributor",0.5,"A3",NS,"","I","C (MB)","mb")
add("MB R170 R171 (PM3)",2,2,"10.0 kOhm 0.1 %","-","0805","TNPW080510K0BEEA","Vishay","distributor",0.5,"A3",NS,"","I","R170 R171","mb")
add("MB RSDA RSCL (PM9)",2,2,"2.70 kOhm 1 %","-","0603","CRCW06032K70FKEA","Vishay","distributor","","T",NS,"","I","MB RSDA RSCL","mb")
add("MB R172 F101 (DNP keep-alive)",0,1,"33 Ohm 0.25 W + ~50 mA fast fuse","-","1206 / 0603","CRCW120633R0FKEA + fuse TODO(verify: T-A-05)","-","distributor","","T","-","","I","R172 F101","mb")
add("Overlay wire (PM4 step 1a, conditional)",0,1,"0.5 mm tinned copper 0.05 m","-","-","-","-","-","","T","-","","I","Overlay wire (r6)","mb")
add("Fallback-2 fused link (DNP)",0,0,"SMD fuse >= 5 A + 20 AWG link","-","1206-2410","selected in T-A-05","-","-","","T","-","","I","Fallback-2 fused link","mb")

BASIS = {"V":"verified, TI store 2026-11-10, 1-99 tier","V*":"TI store 2026-11-10, price of the TPS26630RGERG4 page; TODO(verify: TPS26630RGER price)",
         "A3":"round-3 allowance (wiring design E), not verified","AL":"allowance set in design document section 4, not a quote","T":"TODO(verify: price)"}
hdr = ["refdes","qty_per_board","spares_for_5_board_build","value","rating","package","MPN","manufacturer","distributor",
       "unit_price_usd_qty1","unit_price_usd_qty5","price_basis","stock","date_checked","source_url","class_IC","carried_over_from_round3_refdes","scope"]
with open(OUT/"bom.csv","w",newline="",encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(hdr)
    for r in L:
        p = r["p1"]
        w.writerow([r["ref"],r["q"],r["sp"],r["val"],r["rat"],r["pkg"],r["mpn"],r["mfr"],r["dist"],p if p!="" else "TODO(verify: price)",
                    p if p!="" else "TODO(verify: price)",BASIS[r["kind"]],r["stock"],D,r["url"],r["cls"],r["r3"],r["scope"]])
    w.writerow(["CCB PCB",1,0,"L-shaped ~1219 mm2 (31.0 x 42.26 mm bounding box), 4-layer, 1.6 mm, 1 oz outer / 1 oz inner (stack ST1) or 2 oz inner (stack ST2), ENIG (design document section 3.1.3)","-","-",
                "fab quote TODO(verify)","-","PCB fab","70-120 per lot of 5","70-120 per lot of 5","allowance set in design document section 4 (round-3 CR allowance USD 70); not a quote",
                "-",D,"https://docs.oshpark.com/services/four-layer/ (published 1 oz-outer reference, USD 10 per sq in per 3 copies)","I","CR PCB (EIB panel deleted)","lot"])

def build(nboards, spares):
    t = {"V":0.0,"A3":0.0,"AL":0.0}; unp = 0
    for r in L:
        if r["scope"] in ("build","mb"):
            n = r["q"] + (r["sp"] if spares else 0)
        else:
            n = r["q"]*nboards + (r["sp"] if spares else 0)
        if r["ref"]=="Polyimide sheet": n = 1 + (1 if spares else 0)
        if n == 0: continue
        k = "V" if r["kind"].startswith("V") else r["kind"]
        if k == "T": unp += n; continue
        t[k] += n*float(r["p1"])
    return t, unp
out = {}
# Allowances of design document section 4: USD 0.15 per unpriced placement (4.5.1), PCB lot USD 70-120 (4.4.1),
# PCBA service USD 100-250 (4.4.3); Path A round-3 total USD 505-540 (4.5.3). Deltas are min/max of (CCB - Path A).
PASSIVE_USD = 0.15; PCB = (70.0, 120.0); PCBA = (100.0, 250.0); PATH_A = (505.0, 540.0)
# The PCBA allowance includes the stencil (4.4.3), so option P nets out the USD 25 stencil already in AL.
STENCIL = sum(r["q"]*float(r["p1"]) for r in L if r["ref"]=="Stencil")
for nb, sp in ((1,False),(2,True),(4,True),(5,True)):
    t,u = build(nb,sp)
    base = sum(t.values()) + u*PASSIVE_USD
    H = (base+PCB[0], base+PCB[1]); P = (H[0]+PCBA[0]-STENCIL, H[1]+PCBA[1]-STENCIL)
    out[f"{nb}{'+sp' if sp else ''}"] = dict(t={k:round(v,2) for k,v in t.items()}, unpriced=u,
        passives_usd=round(u*PASSIVE_USD,2), parts_excl_pcb_usd=round(base,2),
        option_H_usd=[round(x,2) for x in H], option_P_usd=[round(x,2) for x in P],
        delta_H_vs_path_A_usd=[round(H[0]-PATH_A[1],2), round(H[1]-PATH_A[0],2)],
        delta_P_vs_path_A_usd=[round(P[0]-PATH_A[1],2), round(P[1]-PATH_A[0],2)])
    print(nb, sp, {k:round(v,2) for k,v in t.items()}, "sum", round(sum(t.values()),2), "unpriced items", u)
ti_pb = sum(r["q"]*r["p1"] for r in L if r["kind"].startswith("V") and r["q"]>0 and r["scope"]=="b")
pb_fitted = sum(r["q"] for r in L if r["scope"]=="b" and r["q"]>0 and not r["ref"].startswith(("F01","Support")))
print("TI silicon per board", round(ti_pb,3), "fitted placements per board (header strips counted as 2)", pb_fitted)
# per-board unpriced placements
print("unpriced placements per board", sum(r["q"] for r in L if r["scope"]=="b" and r["kind"]=="T"))
(OUT/"bom_cost.json").write_text(json.dumps(dict(builds=out, ti_per_board=ti_pb, fitted=pb_fitted,
    basis=dict(passive_usd_per_placement=PASSIVE_USD, pcb_lot_usd=PCB, pcba_usd=PCBA, stencil_netted_in_option_P_usd=STENCIL, path_a_usd=PATH_A)), indent=1))

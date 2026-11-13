import itertools
# --- ILIM_HIZ divider on the CCB (Eq.1: V = 1 + 0.8*I) ---
REGN=(4.8,5.2); tol=0.01; leak=1.5e-6
def band(Rt,Rb,Rfc=None):
    out=[]
    for regn in REGN:
        for st,sb,sf in itertools.product((-1,1),repeat=3):
            rt=Rt*(1+st*tol); rb=Rb*(1+sb*tol)
            if Rfc: rf=Rfc*(1+sf*tol); rb=1/(1/rb+1/rf)
            for sl in (-1,1):
                th=rt*rb/(rt+rb); v=regn*rb/(rt+rb)+sl*leak*th
                out.append((v-1)/0.8)
    return min(out),max(out)
Rt,Rb,Rfc=54.9e3,46.4e3,69.8e3
rg=band(Rt,Rb); fc=band(Rt,Rb,Rfc)
print("regen ceiling A: %.3f-%.3f nominal %.3f"%(rg[0],rg[1],(5*Rb/(Rt+Rb)-1)/0.8))
rbp=1/(1/Rb+1/Rfc); print("FC ceiling A: %.3f-%.3f nominal %.3f"%(fc[0],fc[1],(5*rbp/(Rt+rbp)-1)/0.8))
print("divider Thevenin regen %.1f k"%(Rt*Rb/(Rt+Rb)/1e3))
# --- charge capability at the regen threshold floor ---
Vin_floor=19.0*0.98; Vin_nom=19.0
for lab,eta in (("750kHz/2.2uH 20V",0.925),("1.5MHz/1uH 20V",0.91)):
  for ich in (2.5,3.1):
    for vp in (7.4,8.4):
        pin_ichg=ich*vp/eta
        for lab2,cl in (("WD H.4 min 1.33",1.33),("CCB min",rg[0]),("CCB min x0.90 (IINDPM-class tol, UNVERIFIED applicability)",rg[0]*0.90)):
            pin_cl=cl*Vin_floor
            p=min(pin_ichg,pin_cl); ichg_eff=p*eta/vp
            print(f"{lab} ICHG {ich} Vpack {vp}: P_in(ICHG) {pin_ichg:.1f} W; ceiling {lab2}: P_in {pin_cl:.1f} W -> delivered {p:.1f} W, charge {ichg_eff:.2f} A")
# required ceiling for 3.1 A at 8.4 V at floor
for eta in (0.925,0.91):
    print("ceiling needed for 3.1 A @8.4V at %.2f V floor, eta %.3f: %.3f A"%(Vin_floor,eta,3.1*8.4/eta/Vin_floor))
# losses
for eta,lab in ((0.925,"750k 20V"),(0.91,"1.5M 20V"),(0.94,"750k 15V"),(0.93,"1.5M 15V")):
    for vp in (7.4,8.4):
        po=3.1*vp; print(f"loss {lab} 3.1A {vp}V: Pout {po:.2f} W, loss {po/eta-po:.2f} W")
# inductor ripple and peak
for f,L,lab in ((1.5e6,1e-6,"1.5MHz 1uH"),(0.75e6,2.2e-6,"750kHz 2.2uH")):
    for vin in (15.6,19.0,22.28):
        vo=8.4; d=vo/vin; r=vo*(1-d)/(f*L); print(f"{lab} Vin {vin}: ripple {r:.2f} App, peak at 3.21 A {3.21+r/2:.2f} A")
# min on-time: D/fsw
for f in (1.5e6,0.75e6):
    for d in (0.27,0.13): print(f"fsw {f/1e6} MHz D {d}: t_on {d/f*1e9:.0f} ns")
# inrush on the RT1987-ramped node, 12 mA/uF
k=12e-3
for lab,c in (("MB C-D8/C-D10 20 uF + IC directly, datasheet-suggested 2x10+3x10+2x0.1 = 50.2 uF",20+50.2),
              ("MB 20 uF + eFuse IN caps 1.0+4.7+0.1 (WD B.4)",20+5.8),
              ("MB 20 uF + IC directly, reduced: VBUS 1x4.7 + PMID 2x10 + 0.2",20+24.9)):
    print(f"inrush {lab}: {c:.1f} uF -> {c*k:.2f} A; +0.15 aux = {c*k+0.15:.2f} A")
print("eFuse dVdT ramp into 51.4 uF downstream (WD B.4): 0.11 A; total worst overlap", round(25.8*k+0.11+0.15,2))
# FC mode
for iin in (0.74,0.85,0.96):
    for eta in (0.94,0.935):
        print(f"FC: input {iin} A at 15.6 V eta {eta}: charge at 8.4 V {iin*15.6*eta/8.4:.2f} A, at 7.4 V {iin*15.6*eta/7.4:.2f} A")
print("FC ceiling max + aux:", round(fc[1]+0.15,3))
# dropout / internal R
R=8+24+17+11+10 # mOhm RSNS+Q1+Q4+BATFET+DCR assumption 10
print("buck-path R (typ, +10 mOhm DCR assumed) mOhm",R,"drop at 3.21 A V",round(R*3.21e-3,3))
# --- 2026-11-10 adversarial review CIS-R1-04 / CIS-R1-06: one tolerance basis for the delivered charge ---
# Reference-biased regen ceiling band 1.55-1.61 A ([D798] 7.2); ICHG_ACC -6.5/+3.5 % is published at 2 A only
# (SLUSDV2C p.11); its use at 3.1 A is an extrapolation (U). eta 0.925 at 750 kHz.
RB_MIN, RB_MAX, ETA = 1.55, 1.61, 0.925
lim_in = RB_MIN*Vin_floor*ETA/8.4
print("ref-biased input limit at 8.4 V: %.3f A" % lim_in)
for ich in (3.10, 3.32):
    lo = ich*(1-0.065)
    print("ICHG %.2f A: low corner %.3f A, high corner %.3f A, delivered min %.3f A" % (ich, lo, ich*1.035, min(lo, lim_in)))
print("ICHG 3.10 A, absolute -130 mA reading: %.2f A" % (3.10-0.13))
print("-10 %% pin error on the ref-biased minimum: %.3f A" % (RB_MIN*0.9*Vin_floor*ETA/8.4))
print("setting that closes the low corner: %.4f A" % (3.10/0.935))
# FC window after an IINDPM loss with ILIM_HIZ sampled only at a regen qualification (P6 open, S1-B6)
for lab, (a, b) in (("ref-biased", (RB_MIN, RB_MAX)), ("REGN divider", rg)):
    print("FC bound after IINDPM loss, sampled-once branch, %s: %.2f-%.2f A (incl. 0.15 A aux)" % (lab, a+0.15, b+0.15))

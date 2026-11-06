import itertools
R19=383e3
def par(a,b): return a*b/(a+b)
def spread(rb, label):
    lo=9;hi=-9;nom=None
    for vd in (5.7,6.0,6.3):
        for t1,t2 in itertools.product((-0.01,0,0.01),repeat=2):
            v=vd*rb*(1+t2)/(R19*(1+t1)+rb*(1+t2))
            i=(v-1.0)/0.4
            if vd==6.0 and t1==0 and t2==0: nom=(v,i)
            lo=min(lo,v);hi=max(hi,v)
    ilo=(lo-1)/0.4-0.2; ihi=(hi-1)/0.4+0.2
    print(f"{label}: Rbot={rb/1e3:.1f}k Vnom={nom[0]:.3f} Inom={nom[1]:.3f} A; V {lo:.3f}-{hi:.3f}; I(with +/-0.2A pin acc) {ilo:.2f}-{ihi:.2f} A")
    return ilo,ihi
spread(220e3,"stock R27 220k")
spread(127e3,"dossier 127k")
spread(154e3,"REGEN-HIGH R27=154k")
spread(par(154e3,324e3),"FC-LOW 154k||324k")
# regen power at Vth
for ilo in (1.387,1.30):
    print("P_in min at 18.44 V with I=%.2f: %.1f W"%(ilo,ilo*18.44))
# IIN_HOST regen 1.60 A: max per EC row form -> typ 100 mA lower; assume -200mA min
print("IIN_HOST 1.60 A -> 1.40-1.60 A (assumed band, EC rows 0x1E00/0x0A00 are -200/-100/0 mA), P at 18.44V min %.1f W"%(1.40*18.44))
# inrush
C_board=20e-6
for name,C in (("stock EVM",94.47e-6),("depop",51.5e-6),("depop+C25 swap",51.5e-6)):
    I=(C+C_board)*12e3
    print(f"{name}: C_tot {(C+C_board)*1e6:.1f} uF inrush {I:.3f} A + aux 0.15 = {I+0.15:.3f} A")
# FC window budget
for imot in (0.0,0.1,0.2,0.3):
    print("FC window: pin max 1.07 + aux 0.15 + motor %.1f = %.2f A vs OC_FC 1.4"%(imot,1.07+0.15+imot))
# FC charge from IIN_HOST 0.70 A (typ 0.6): charge current
for iin in (0.5,0.6,0.7):
    p=iin*15.9*0.935
    print("FC IIN %.1f A -> P_out %.2f W -> I_chg at 8.0 V %.2f A, at 8.4 V %.2f A"%(iin,p,p/8.0,p/8.4))
# thermal
for vin,eta,pout in ((15.9,0.935,21.0),(19.0,0.925,21.0),(19.0,0.925,24.0)):
    print("Vin %.1f eta %.3f Pout %.1f W -> loss %.2f W"%(vin,eta,pout,pout/eta-pout))
# CV error via D-BT-SQ
for i in (0.1,0.5,2.5):
    d=max(0.035,i*0.020)
    print("I %.1f A: D-BT-SQ drop %.0f mV -> pack at VREG 8.400 nom %.3f V; worst 8.350-%.3f / 8.450-%.3f"%(i,d*1e3,8.4-d,d,d))
# ripple/comparator undershoot budget with regen IIN 1.6 A
C=0.4e-3
for I in (1.2,1.6,2.2):
    print("I_in %.1f A: VINDPM_min 18.43->H1 fall 17.0 %.0f us; 17.0->15.9 %.0f us"%(I,(18.43-17.0)*C/I*1e6,(17.0-15.9)*C/I*1e6))

import itertools
def par(a,b): return a*b/(a+b)
RA1,RA2=499e3,56.2e3   # V-MOT divider (new)
RB1,RB2=464e3,56.2e3   # VBUS divider (new)
RH=6.49e6              # hysteresis, OUT -> IN+
VCC=3.3
def trips(vbus, ra1=RA1,ra2=RA2,rb1=RB1,rb2=RB2,rh=RH,vos=0.0,hint=0.0,voh=VCC,vol=0.0):
    vneg=vbus*rb2/(rb1+rb2)
    # rising: out low (vol). IN+ = Vm*k1 + vol*k2 ; trip when IN+ = vneg + vos + hint/2
    def inp(vm,vout):
        g1,g2,g3=1/ra1,1/ra2,1/rh
        return (vm*g1+vout*g3)/(g1+g2+g3)
    # solve linear
    g1,g2,g3=1/ra1,1/ra2,1/rh
    a=g1/(g1+g2+g3)
    rise=((vneg+vos+hint/2)-vol*g3/(g1+g2+g3))/a
    fall=((vneg+vos-hint/2)-voh*g3/(g1+g2+g3))/a
    return rise,fall
nom_ratio=(RB2/(RB1+RB2))/(RA2/(RA1+RA2))
print("k_nominal (V-MOT/VBUS at trip w/o hyst) = %.4f"%nom_ratio)
for vb in [15.59,15.9,16.4,17.2,17.5,18.3,19.5]:
    r,f=trips(vb,hint=0.005)
    # worst cases: 0.1% resistors, vos +-9mV, hint 2..8mV, VOH 3.1..3.3
    lo=1e9;hi=-1e9
    for s in itertools.product([-1,1],repeat=4):
        t=0.001
        ra1=RA1*(1+s[0]*t);ra2=RA2*(1-s[0]*t);rb1=RB1*(1+s[1]*t);rb2=RB2*(1-s[1]*t)
        for vos in (-0.009,0.009):
            for hint in (0.002,0.008):
                for voh in (3.1,3.3):
                    for rh in (RH*0.99,RH*1.01):
                        rr,ff=trips(vb,ra1*(1 if s[2]>0 else 1),ra2,rb1,rb2,rh,vos,hint,voh,0.0)
                        rr2,ff2=trips(vb,RA1*(1-s[0]*t),RA2*(1+s[0]*t),RB1*(1-s[1]*t),RB2*(1+s[1]*t),rh,vos,hint,voh,0.2)
                        lo=min(lo,ff,ff2);hi=max(hi,rr,rr2)
    print("VBUS %.2f: rise(permit) %.3f  fall(inhibit) %.3f  hyst %.3f | worst fall_min %.3f (guard %.3f V over VBUS)  worst rise_max %.3f"%(vb,r,f,r-f,lo,lo-vb,hi))
# 1% resistors worst case for comparison
lo=1e9
for s in itertools.product([-1,1],repeat=2):
    t=0.01
    r,f=trips(15.9,RA1*(1+s[0]*t),RA2*(1-s[0]*t),RB1*(1-s[1]*t),RB2*(1+s[1]*t),RH,-0.009,0.008,3.1,0)
    lo=min(lo,f)
print("1%% resistors, VBUS 15.9: worst fall_min %.3f"%lo)
# filter caps
for C in (470e-12,1e-9):
    print("C=%g: tau_A=%.1f us tau_B=%.1f us"%(C,par(RA1,RA2)*C*1e6,par(RB1,RB2)*C*1e6))
# input at 30 V V-MOT
print("IN+ at V-MOT 30 V: %.3f V; at 40 V: %.3f V"%(30*RA2/(RA1+RA2),40*RA2/(RA1+RA2)))
print("IN- at VBUS 19.5: %.3f V"%(19.5*RB2/(RB1+RB2)))
# undershoot budget
C=0.4e-3
for I in (0.5,1.0,1.5):
    print("I_in %.1f A: dV/dt %.2f V/ms; time 18.43->17.0 %.0f us; 17.0->15.9 %.0f us"%(I,I/C/1e3,(18.43-17.0)*C/I*1e6,(17.0-15.9)*C/I*1e6))

# ---------------------------------------------------------------------------
# Round-2 critic fixes (2026-11-05, appended; the block above is unchanged).
# (a) CMRR term: TLV3012B Vos +-9 mV is specified at VCM = V- only (SBOS300C sec 6.9);
#     H1 runs at VCM = IN- = VBUS*56.2/520.2 = 1.68-2.11 V. CMRR 54 dB min over the full
#     VCM range (60 dB from (V-)+1.5 V), both specified at VS = 5.5 V only (SBOS300C 6.9);
#     at VS = 3.3 V CMRR is unspecified -> TODO(verify: SBOS300C), 54 dB used.
#     Internal hysteresis 2-8 mV (SBOS300C 6.9 VHYS) was ALREADY in the worst case above
#     (hint loop), so it is not added again.
# (b) Inhibit-latency budget with the final dividers: from the worst-case H1 fall trip to
#     the point where D-MT-EN starts to conduct (V-MOT = VBUS - VFWD, VFWD 35 mV typical
#     only, RT1987 DS-00 EC p.7), minus divider RC lag 24 us, comparator delay and gate RC
#     20 us. Comparator delay: 4 us max is at 100 mV overdrive (SBOS300C 6.10); a
#     3-4 V/ms ramp gives only ~0.3-0.4 mV/us at IN+, so 15 us is allocated (non-B TLV3012
#     is 12-13.5 us typ at 10 mV overdrive, SBOS300C 6.8) -> BENCH (S2-b).
def worst(vb, cmrr_db=54.0):
    vcm = vb*RB2/(RB1+RB2)
    dv_cm = vcm*10**(-cmrr_db/20)
    lo=1e9; hi=-1e9
    t=0.001
    for s in itertools.product([-1,1],repeat=2):
        for sign in (-1,1):
            for vos in (-(0.009+dv_cm),(0.009+dv_cm)):
                for hint in (0.002,0.008):
                    for voh in (3.1,3.3):
                        for vol in (0.0,0.2):
                            for rh in (RH*0.99,RH*1.01):
                                r,f=trips(vb,RA1*(1+sign*s[0]*t),RA2*(1-sign*s[0]*t),
                                          RB1*(1-sign*s[1]*t),RB2*(1+sign*s[1]*t),rh,vos,hint,voh,vol)
                                lo=min(lo,f); hi=max(hi,r)
    return lo,hi,dv_cm
print("\n--- critic-fix block: worst case incl. CMRR (54 dB) ---")
VFWD=0.035; C_VMOT=0.4e-3
LAG_RC=24e-6; T_CMP=15e-6; T_GATE=20e-6
for vb in (15.59,15.9,16.39,17.2,17.5,19.5):
    lo,hi,dv=worst(vb)
    print("VBUS %.2f: CMRR term %.1f mV; worst fall_min %.3f (guard %.3f V); worst rise_max %.3f"%(vb,dv*1e3,lo,lo-vb,hi))
print("VINDPM min 18.62 V (19.0 V -2 %%) - H1 rise max at 16.39 V bus: %.2f V"%(18.62-worst(16.39)[1]))
for I in (1.25,1.40,1.72):
    for vb in (15.9,16.39):
        lo,_,_=worst(vb)
        slew=I/C_VMOT
        t_fall=(lo-(vb-VFWD))/slew
        print("I_in %.2f A, VBUS %.2f: %.2f V/ms; fall-trip -> D-MT-EN conduction %.0f us; charger allowance %.0f us"
              %(I,vb,slew/1e3,t_fall*1e6,(t_fall-LAG_RC-T_CMP-T_GATE)*1e6))
# (c) Mode-switched ILIM_HIZ divider (SLUSDV2C sec 7.3.4.3 Eq.1: V = 1 V + 0.8 ohm x ILIM),
#     REGN 4.8-5.2 V (SLUSDV2C EC), 1 % resistors.
RT,RB,RFC=121e3,100e3,158e3
def ilim(rt,rb,regn): return (regn*rb/(rt+rb)-1.0)/0.8
for name,rb in (("regen",RB),("FC (RFC switched in)",par(RB,RFC))):
    lo=min(ilim(RT*(1+a*0.01),rb*(1+b*0.01),r) for a in(-1,1) for b in(-1,1) for r in(4.8,5.2))
    hi=max(ilim(RT*(1+a*0.01),rb*(1+b*0.01),r) for a in(-1,1) for b in(-1,1) for r in(4.8,5.2))
    print("ILIM %s: %.3f-%.3f A (nominal at 5.0 V: %.3f A)"%(name,lo,hi,ilim(RT,rb,5.0)))
lo_rg=min(ilim(RT*(1+a*0.01),RB*(1+b*0.01),4.8) for a in(-1,1) for b in(-1,1))
print("regen: clamp min x 0.88 (IINDPM_ACC low end, 880/1000 mA at VBUS 9 V, SLUSDV2C EC) x 18.62 V = %.1f W"%(lo_rg*0.88*18.62))
for vp in (7.4,8.4):
    print("ICHG 2.50 A at pack %.1f V, eta 0.91 (Fig 6-4, figure reading): input %.1f W"%(vp,2.5*vp/0.91))
print("ICHG for 23 W input at 7.4 V pack: %.2f A"%(23*0.91/7.4))

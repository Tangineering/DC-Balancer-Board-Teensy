import numpy as np
def brentq(f,a,b,it=200):
    fa=f(a); fb=f(b)
    assert fa*fb<=0,(a,b,fa,fb)
    for _ in range(it):
        m=0.5*(a+b); fm=f(m)
        if fa*fm<=0: b,fb=m,fm
        else: a,fa=m,fm
    return 0.5*(a+b)
R1,R2,RGS,RG,RSH=78.7e3,10e3,3.3e3,220.,47.
VT=0.02585
# ---------- required leak (measured point) ----------
def leak(V,tap): return (V-tap)/R1-tap/R2
for V,rd in [(15.93,1.522*8.87),(6.12,6.08),(12.19,11.44)]:
    tap=rd/8.87; print(f"V={V}: tap={tap:.3f} V, ideal {V*R2/(R1+R2):.3f}, leak needed {leak(V,tap)*1e6:.1f} uA")
for r in (0.834,0.8375,0.8346,0.854):
    tap=r*15.9/8.87; print(f" ratio {r}: leak {leak(15.9,tap)*1e6:.2f} uA")
# ---------- designed orientation, healthy part ----------
Rth=R1*R2/(R1+R2)
for Iref in (2e-6,4e-6,6.5e-6,31.5e-6):
    print(f"designed: Iref={Iref*1e6:.1f} uA -> ratio {1-Iref*Rth/(15.93*R2/(R1+R2)):.4f}")
# ---------- swapped orientation ----------
# REF pin (fp pin1, behind R-G) ; cathode = tap ; anode = GND
# REF->anode : 2 junctions (Q_in B-E + bandgap core) + ~3.28k  (Fig 8-2)
# REF->cathode: Q_in B-C diode (forward when REF>tap)
# cathode sink: Darlington, overdriven, modelled as knee Vk with exp slope (assumption)
def solve(VM,Vk=1.1,Isbc=1e-14,Vth=3.0,Vz=12.0):
    # unknowns: VR (REF pin), Vt (tap). VG from REF current.
    def ibe(VR): # 2 junctions + 3.28k: piecewise
        return max(VR-1.2,0)/3.28e3
    def ibc(VR,Vt): return Isbc*(np.exp(min((VR-Vt)/VT,80))-1)
    def idar(Vt): return 1e-3*np.exp(min((Vt-Vk)/(2*VT),60)) if Vt>0 else 0
    def iref_supply(VR):
        # current available from VM through R-GS (with zener clamp) then R-G
        # VG = VR + I*RG ; I = (VM-VG)/RGS  unless VM-VG>Vz -> VG = VM-Vz
        I=(VM-VR)/(RGS+RG)
        if I*RGS>Vz: I=(VM-Vz-VR)/RG
        return max(I,0)
    def tapKCL(Vt,VR): return (VM-Vt)/R1+ibc(VR,Vt)-Vt/R2-idar(Vt)
    def refKCL(VR):
        Vt=brentq(lambda v:tapKCL(v,VR),-1,VM+1)
        return iref_supply(VR)-ibe(VR)-ibc(VR,Vt)
    if VM<0.05: return dict(VM=VM,tap=0,VR=0,Iref=0,Vgs=0,Idump=0)
    VR=brentq(refKCL,0,VM)
    Vt=brentq(lambda v:tapKCL(v,VR),-1,VM+1)
    I=iref_supply(VR); VG=VM-min(I*RGS,Vz) if I*RGS<=Vz else VM-Vz
    Vgs=VG-VM
    # BSP170P: Vth -2.1/-3/-4 V ; crude square law above threshold, k chosen so Rds ~0.3 at -10V
    vov=max(-Vgs-Vth,0); Idmax=0.5*1.0*vov**2
    Idump=min(Idmax,VM/RSH)
    return dict(VM=VM,tap=Vt,VR=VR,Iref=I,Vgs=Vgs,Idump=Idump)
print("\nswapped orientation (Vk=1.1 V, Vth=3.0 V):")
print(" VM    tap    reading  VR    Iref_mA  Vgs    Idump_A  P_R_W  ratio(tap/ideal)")
for VM in [1,2,3,4,5,6.1,8,10,12.2,15.93,18,20.3,22.13,25,30]:
    s=solve(VM)
    print(f"{VM:5.2f} {s['tap']:6.3f} {s['tap']*8.87:6.2f} {s['VR']:5.2f} {s['Iref']*1e3:7.3f} {s['Vgs']:6.2f} {s['Idump']:7.3f} {s['Idump']**2*RSH:6.2f} {s['tap']/(VM*R2/(R1+R2)):6.3f}")
print("\nsensitivity at 15.93 V:")
for Vk in (0.8,1.1,1.4,1.8):
  for Vth in (2.1,4.0):
    for Vz in (11.4,12.7):
      s=solve(15.93,Vk=Vk,Vth=Vth,Vz=Vz)
      print(f" Vk={Vk} Vth={Vth} Vz={Vz}: tap {s['tap']:.3f} Iref {s['Iref']*1e3:.2f} mA Vgs {s['Vgs']:.2f} Idump {s['Idump']:.3f} A")
# turn-on V-MOT
for Vth in (2.1,3.0,4.0):
    VMs=np.linspace(0.5,10,951)
    on=[v for v in VMs if solve(v,Vth=Vth)['Idump']>250e-6]
    print(f"Vth={Vth}: dump conducts (>250uA) from VM={on[0]:.2f} V")
# fall-slope bound from data
C=(480e-6,1.4e-3); slope=11.9/0.85
print(f"\npost-peak fall {slope:.1f} V/s true -> node net load {C[0]*slope*1e3:.1f}-{C[1]*slope*1e3:.1f} mA; dump at 18-20 V would be {18/47.3:.2f}-{20.3/47.3:.2f} A; RC tau {47*C[0]*1e3:.0f}-{47*C[1]*1e3:.0f} ms")

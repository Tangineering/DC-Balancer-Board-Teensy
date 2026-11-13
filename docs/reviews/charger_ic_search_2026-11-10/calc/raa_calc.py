# RAA489110 CCB calculations (assumed power-stage values marked A)
def loss(Vin,Vout,Iout,f=724e3,Rs1=0.075,Rs2=0.010,RQ1=0.008,RQ2=0.005,RQ4=0.005,RBF=0.005,DCR=0.012,Qg1=8e-9,Qg2=12e-9,tsw=8e-9,tdt=20e-9,Vd=0.7,core=0.10,IQ=2.35e-3):
    eta=0.94
    for _ in range(20):
        Iin=Vout*Iout/eta/Vin
        D=Vout/(Vin*0.98)
        L=dict(
          Q1c=Iout**2*RQ1*D, Q1sw=0.5*Vin*Iout*2*tsw*f, Q2c=Iout**2*RQ2*(1-D),
          dead=2*tdt*f*Vd*Iout, Q4=Iout**2*RQ4, BFET=Iout**2*RBF, Rs2=Iout**2*Rs2,
          Rs1=Iin**2*Rs1, Lcu=Iout**2*DCR, core=core, gate_LDO=(Qg1+Qg2)*f*Vin, IC=IQ*Vin)
        P=sum(L.values()); eta=Vout*Iout/(Vout*Iout+P)
    return eta,P,Iin,L
for Vin in (15.57,18.53,21.5):
  for Vout,I in ((8.4,3.25),(7.4,3.25),(8.4,1.6)):
    e,P,Iin,L=loss(Vin,Vout,I)
    print(f"Vin {Vin:5.2f} Vout {Vout} I {I}: eta {e*100:.1f} % loss {P:.2f} W Iin {Iin:.3f} A")
e,P,Iin,L=loss(18.53,8.4,3.25); print({k:round(v,3) for k,v in L.items()})
Vfs=0.1228
for nm,R in (("Rs1 75m",0.075),):
  print(nm,"ceil nom",Vfs/R,"min",0.98*Vfs/(R*1.01),"max",1.02*Vfs/(R*0.99),"x2",2*Vfs/R)
  print("WOCP",0.200/(R*1.01),0.260/(R*0.99)); print("PROG0.2A",0.004/R, "LSB mA",0.08/R/1e-3*1e-3*1000)
  print("FC 0.90A", 0.90*0.975/1.01, 0.90*1.025/0.99); print("IADP FS",0.1136/R)
print("VIN 19.072", 19.072*3.98/4.096, 19.072*4.22/4.096, "13.568",13.568*3.98/4.096,13.568*4.22/4.096)
print("ICHG 3.248", 3.248*0.965/1.01, 3.248*1.035/0.99)
print("BGATE off t (Q 4.5-7.5nC, 165-250uA) us", [round(q/i*1e6,1) for q in (4.5e-9,7.5e-9) for i in (165e-6,250e-6)])
print("BGATE on t (Q 7.5nC, 15-70uA) us", [round(7.5e-9/i*1e6) for i in (15e-6,40e-6,70e-6)])
print("VSYS OV time 25uF 0.5-0.95V 3.4A us", 25e-6*0.5/3.4*1e6, 25e-6*0.95/3.4*1e6)
print("inrush 27uF",27*0.012, "budget C total", (1.0-0.15)/0.012)

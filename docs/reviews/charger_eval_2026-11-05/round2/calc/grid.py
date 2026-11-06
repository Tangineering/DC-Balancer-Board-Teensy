import numpy as np, json, itertools
from capsim import run
VTH=[18.0,18.5,19.0,19.5]; TAU=[0.001,0.005,0.020,0.050,0.100]; ICL=[1.0,2.0,2.5,3.0]
SC={'S1_2to1_12A':dict(v0=2,v1=1,imot=12),'S2_3to1_12A':dict(v0=3,v1=1,imot=12),'S3_2to1_5A':dict(v0=2,v1=1,imot=5)}
CS=[0.49e-3,0.97e-3,2.0e-3,4.0e-3]
out={}
for sn,sc in SC.items():
  for C in CS:
    ide=run(**sc,C=C,ideal=True)
    key=f'{sn}|C={C*1e3:.2f}'
    rec={'ideal':{k:float(v) for k,v in ide.items() if k!='tr'},'none':{k:float(v) for k,v in run(**sc,C=C,Vth=99).items() if k!='tr'},'warm':{},'cold':{}}
    for Vth,tau,I in itertools.product(VTH,TAU,ICL):
        r=run(**sc,C=C,Vth=Vth,tau=tau,Iceil=I)
        rec['warm'][f'{Vth}|{tau}|{I}']={k:float(v) for k,v in r.items() if k!='tr'}
    for L in [0.065,0.170]:
      for Vth in VTH:
        for I in ICL:
          r=run(**sc,C=C,Vth=Vth,tau=0.005,Iceil=I,mode='cold',L=L)
          rec['cold'][f'{L}|{Vth}|{I}']={k:float(v) for k,v in r.items() if k!='tr'}
    out[key]=rec
    print(key,'ideal Ep %.3f'%ide['Ep'],flush=True)
json.dump(out,open('grid.json','w'))

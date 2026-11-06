import numpy as np, json
from capsim import run, V_PACK, ETA_CHG
def taumax(sc,C,Vth,I,ireg=1.5):
    if run(**sc,C=C,Vth=Vth,tau=1e-4,Iceil=I,ireg_max=ireg)['ov']>0: return 0.0
    lo,hi=1e-4,0.3
    if run(**sc,C=C,Vth=Vth,tau=hi,Iceil=I,ireg_max=ireg)['ov']==0: return hi
    for _ in range(14):
        m=np.sqrt(lo*hi)
        if run(**sc,C=C,Vth=Vth,tau=m,Iceil=I,ireg_max=ireg,dt=4e-5)['ov']==0: lo=m
        else: hi=m
    return lo
SC={'S1 2->1 m/s, 12 A':dict(v0=2,v1=1,imot=12),'S2 3->1 m/s, 12 A':dict(v0=3,v1=1,imot=12),'S3 2->1 m/s, 5 A':dict(v0=2,v1=1,imot=5)}
res={}
for sn,sc in SC.items():
  for C in [0.49e-3,0.97e-3,2.0e-3,4.0e-3]:
    for I in [1.0,2.0,2.5,3.0]:
      row=[taumax(sc,C,V,I) for V in [18.0,18.5,19.0,19.5]]
      res[f'{sn}|{C*1e3:.2f}|{I}']=row
      print(sn,'C %.2f mF Iceil %.1f A  tau_max ms @Vth 18/18.5/19/19.5:'%(C*1e3,I),' '.join('%6.1f'%(x*1e3) for x in row),flush=True)
json.dump(res,open('taumax.json','w'))

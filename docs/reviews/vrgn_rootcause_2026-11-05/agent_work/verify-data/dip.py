import pandas as pd,numpy as np,sys,os
for n in sys.argv[1:]:
    f=f'logs/{n}/{n}.csv'
    if not os.path.exists(f): f=f'/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/{n}.csv'
    d=pd.read_csv(f,usecols=['V_bus','V_rgn','V_chg'])
    vb=d.V_bus.values; vr=d.V_rgn.values
    base=np.median(vb)
    m=(vb<base-1.5)&(vb>9)
    idx=np.where(m)[0]
    if len(idx)==0: print(n,'no dip');continue
    vn=vr*10/88.7
    I=((vb-vn)/78.7e3-vn/10e3)*1e6
    # include near-baseline points from the dip neighborhoods
    sel=np.unique(np.concatenate([np.arange(i-3,i+4) for i in idx]))
    sel=sel[(sel>=0)&(sel<len(vb))]
    x=vn[sel]; y=I[sel]
    A=np.c_[x,np.ones_like(x)]; c=np.linalg.lstsq(A,y,rcond=None)[0]
    r=y-A@c
    R=1e6/c[0]; Von=-c[1]/c[0]
    # proportional (linear resistor to gnd) fit
    k=(x@y)/(x@x); r2=y-k*x
    print(n,'npts',len(sel),'ndip',len(idx),'R_k=%.2f Von=%.3f rms=%.2f | ohmic rms=%.2f | node range %.3f-%.3f'%(R/1e3,Von,r.std(),r2.std(),x.min(),x.max()))

import pandas as pd, numpy as np, sys, glob, os
S=sys.argv[1:]
for n in S:
    f=f'logs/{n}/{n}.csv'
    if not os.path.exists(f): f=f'/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/{n}.csv'
    d=pd.read_csv(f,usecols=['t_us','V_bus','V_rgn','I_cmd'])
    t=d.t_us.values/1e6; vb=d.V_bus.values; vr=d.V_rgn.values
    r=np.where(vb>14,vr/np.maximum(vb,1e-3),np.nan)
    # identify bursts: vr - 0.85*vb > 0.5
    ex=vr-np.nanmedian(r)*vb
    on=ex>0.8
    idx=np.flatnonzero(np.diff(on.astype(int))==1)
    print(n,'median ratio',np.nanmedian(r),'bursts',len(idx))
    for i in idx[:6]:
        pre=r[max(0,i-3000):i-200]; 
        j=i+np.argmax(~on[i:]) if (~on[i:]).any() else len(on)-1
        post=r[j+1500:j+4500]
        seg=vr[i-50:j+50]; dseg=np.diff(seg)
        print(f'  t={t[i]:.2f}s peak rd={vr[i:j+1].max():.3f} node={vr[i:j+1].max()/8.87:.3f}V  ratio pre={np.nanmedian(pre):.4f} post(1.5-4.5s after)={np.nanmedian(post):.4f}  max step={dseg.max():.3f} V/sample')

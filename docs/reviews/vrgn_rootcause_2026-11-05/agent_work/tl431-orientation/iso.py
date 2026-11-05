import glob,os,numpy as np,pandas as pd
S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad'
files=sorted(glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/*/*.csv'))+sorted(glob.glob(S+'/dec/*.csv'))
for f in files:
    try: d=pd.read_csv(f,usecols=['t_us','V_bus','V_rgn','I_fc','I_batt'])
    except Exception as e: continue
    t=d.t_us.values/1e6; vb=d.V_bus.values; vr=d.V_rgn.values
    m=(vr>3.0)&(vr>vb*0.85+0.5)
    if m.sum()<30: continue
    # find contiguous runs
    idx=np.where(m)[0]; br=np.where(np.diff(idx)>5)[0]
    starts=np.r_[idx[0],idx[br+1]]; ends=np.r_[idx[br],idx[-1]]
    for s,e in zip(starts,ends):
        if e-s<30: continue
        dur=t[e]-t[s]
        v0,v1=vr[s],vr[e]
        tau = dur/np.log(v0/v1) if v1<v0 and v1>0 else float('nan')
        print(os.path.basename(f),f"t={t[s]:.2f}-{t[e]:.2f}s rgn {v0:.2f}->{v1:.2f} bus {vb[s]:.2f}->{vb[e]:.2f} tau={tau:.1f}s mean slope={(v1-v0)/dur*1e-3:.5f} V/ms Ibus={np.median(d.I_fc.values[s:e]+d.I_batt.values[s:e]):.3f}")

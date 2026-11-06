import glob,os,numpy as np,pandas as pd
files=sorted(glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/*/*.csv'))
rows=[]
for f in files:
    try: d=pd.read_csv(f,usecols=['t_us','V_bus','V_rgn','I_fc','I_batt','I_cmd','v_act'])
    except Exception: continue
    t=d.t_us.values/1e6; vb=d.V_bus.values; vr=d.V_rgn.values
    ratio=np.nanmedian((vr/vb)[(vb>15)&(vb<16.2)]) if ((vb>15)&(vb<16.2)).sum()>100 else 0.85
    ex=vr-ratio*vb   # excess of reading over connected-node level
    m=(vb>15)&(ex>0.15)&(np.abs(d.I_cmd.values)<0.05)
    if m.sum()<50: continue
    idx=np.where(m)[0]; br=np.where(np.diff(idx)>3)[0]
    for s,e in zip(np.r_[idx[0],idx[br+1]],np.r_[idx[br],idx[-1]]):
        if e-s<50: continue
        tt=t[s:e+1]; vv=vr[s:e+1]
        p=np.polyfit(tt-tt[0],vv,1)
        rows.append((os.path.basename(f),t[s],t[e]-t[s],vr[s],vr[e],ex[s],p[0],ratio))
for r in sorted(rows,key=lambda r:-r[2])[:25]:
    print("%s t0=%.2f dur=%.3fs rgn %.3f->%.3f excess0=%.3f slope=%.4f V/s(reading) ratio=%.4f"%r)
print(len(rows))

import pandas as pd, numpy as np, glob, os
fs=sorted(glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/*/*.csv'))+sorted(glob.glob('/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/*.csv'))
out=[]
for f in fs:
    try: d=pd.read_csv(f,usecols=['t_us','V_bus','V_rgn','V_chg','I_cmd'])
    except Exception as e: continue
    d=d[(d.V_bus>14.5)&(d.V_rgn>10)&(d.V_rgn<d.V_bus)]
    if len(d)<20000: continue
    d['blk']=((d.t_us-d.t_us.iloc[0])//500000).astype(int)
    g=d.groupby('blk').agg(Vb=('V_bus','mean'),Vr=('V_rgn','mean'),n=('V_bus','size'))
    g=g[g.n>400]
    if len(g)<10 or g.Vb.max()-g.Vb.min()<0.04: continue
    b=np.polyfit(g.Vb,g.Vr,1); c=np.corrcoef(g.Vb,g.Vr)[0,1]
    out.append((os.path.basename(f)[:6],len(g),g.Vb.max()-g.Vb.min(),b[0],(g.Vr/g.Vb).median(),c))
for o in out: print('%s blk%4d span%.3f slope %.3f ratio %.4f corr %.3f'%o)
s=np.array([o[3] for o in out if o[5]>0.9]); print('slopes corr>0.9: n',len(s),'median',np.median(s),'IQR',np.percentile(s,[25,75]))

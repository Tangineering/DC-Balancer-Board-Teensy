import pandas as pd, numpy as np, glob, os
fs=sorted(glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/*/*.csv'))+sorted(glob.glob('/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/*.csv'))
seen=set()
for f in fs:
    nm=os.path.basename(f)[:6]
    if nm in seen: continue
    seen.add(nm)
    try: d=pd.read_csv(f,usecols=['t_us','V_bus','V_rgn','V_chg','I_fc','I_batt','I_cmd','gFC','gBT'])
    except Exception: continue
    d=d[(d.V_bus>14.5)&(d.V_rgn>10)&(d.V_rgn<d.V_bus)&(d.V_chg<0.5)]
    if len(d)<20000: continue
    d['It']=d.I_fc+d.I_batt
    d['blk']=((d.t_us-d.t_us.iloc[0])//200000).astype(int)
    g=d.groupby('blk').agg(Vb=('V_bus','mean'),Vr=('V_rgn','mean'),It=('It','mean'),Ic=('I_cmd','mean'),gf=('gFC','mean'),gb=('gBT','mean'),n=('V_bus','size'))
    g=g[g.n>150]
    if len(g)<20 or g.Vb.std()<0.01: continue
    X=np.column_stack([np.ones(len(g)),g.Vb,g.It])
    b,res,rk,sv=np.linalg.lstsq(X,g.Vr,rcond=None)
    # collinearity
    c=np.corrcoef(g.Vb,g.It)[0,1]
    # residual
    r=g.Vr-X@b
    print('%s n%4d corr(Vb,It)=%.3f  b_Vb=%.3f b_It=%.4f V/A  rms %.4f  gstd %.3f'%(nm,len(g),c,b[1],b[2],r.std(),g.gf.std()+g.gb.std()))

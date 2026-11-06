import pandas as pd, numpy as np
import glob,os
for nm in ['ML0203','WP0100','ML0135','WP0121','ML0226','ML0227']:
    f=glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/%s/%s.csv'%(nm,nm))+glob.glob('/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/%s.csv'%nm)
    d=pd.read_csv(f[0],usecols=['t_us','V_bus','V_rgn','V_chg','I_fc','I_batt'])
    d=d[(d.V_bus>14.5)&(d.V_rgn>10)&(d.V_rgn<d.V_bus)]
    if nm!='ML0227': d=d[d.V_chg<0.5]
    d['It']=d.I_fc+d.I_batt
    d['blk']=((d.t_us-d.t_us.iloc[0])//200000).astype(int)
    g=d.groupby('blk').agg(Vb=('V_bus','mean'),Vr=('V_rgn','mean'),It=('It','mean'),n=('V_bus','size'));g=g[g.n>150]
    for name,ratio in [('free',None),('resistor',(g.Vr/g.Vb).median()),('constI',1.0)]:
        if ratio is None:
            X=np.column_stack([np.ones(len(g)),g.Vb,g.It]); y=g.Vr
        else:
            X=np.column_stack([np.ones(len(g)),g.It]); y=g.Vr-ratio*g.Vb
        b,*_=np.linalg.lstsq(X,y,rcond=None); r=y-X@b
        print(nm,name,np.round(b,4),'rms %.5f'%r.std(), ('-> Rg %.2f mOhm'%(b[-1]/7.87*1e3)))

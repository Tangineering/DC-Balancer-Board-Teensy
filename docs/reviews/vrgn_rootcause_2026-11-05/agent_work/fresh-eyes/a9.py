import pandas as pd, numpy as np, glob
for nm in ['ML0203','WP0100','WP0095','WP0122','WP0123','TP0132']:
    f=glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/%s/%s.csv'%(nm,nm))+glob.glob('/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/%s.csv'%nm)
    d=pd.read_csv(f[0],usecols=['t_us','V_bus','V_rgn','V_chg','I_fc','I_batt','I_cmd'])
    d=d[(d.V_bus>14.5)&(d.V_rgn>10)&(d.V_rgn<d.V_bus)&(d.V_chg<0.5)]
    d['blk']=((d.t_us-d.t_us.iloc[0])//200000).astype(int)
    g=d.groupby('blk').agg(Vb=('V_bus','mean'),Vr=('V_rgn','mean'),If=('I_fc','mean'),Ib=('I_batt','mean'),Ic=('I_cmd','mean'),n=('V_bus','size'));g=g[g.n>150]
    rat=(g.Vr/g.Vb).median()
    for name,X,y in [('free+split',np.column_stack([np.ones(len(g)),g.Vb,g.If,g.Ib,g.Ic.abs()]),g.Vr),
                     ('resistor+split',np.column_stack([np.ones(len(g)),g.If,g.Ib,g.Ic.abs()]),g.Vr-rat*g.Vb)]:
        b,*_=np.linalg.lstsq(X,y,rcond=None); r=y-X@b
        print(nm,name,np.round(b,4),'rms %.5f'%r.std())

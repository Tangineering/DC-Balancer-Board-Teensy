import pandas as pd, numpy as np, sys
for f in sys.argv[1:]:
    d=pd.read_csv(f,usecols=['t_us','I_fc','I_batt','V_bus','V_chg','V_rgn','I_cmd','v_act'])
    d=d[(d.V_bus>14)]
    d['blk']=((d.t_us-d.t_us.iloc[0])//500000).astype(int)
    for lab,sel in [('all',d),('Icmd0',d[(d.I_cmd==0)&(d.v_act.abs()<0.01)]),('chg0',d[d.V_chg<0.5]),('chgfed',d[d.V_chg>10])]:
        g=sel.groupby('blk').agg(Vb=('V_bus','mean'),Vr=('V_rgn','mean'),I=('I_fc','mean'),Ib=('I_batt','mean'),n=('V_bus','size'))
        g=g[g.n>400]
        if len(g)<5: print(f[-10:],lab,'few',len(g)); continue
        b=np.polyfit(g.Vb,g.Vr,1)
        print(f[-10:],lab,'blocks',len(g),'Vb range %.3f-%.3f'%(g.Vb.min(),g.Vb.max()),'slope %.3f intercept %.3f'%tuple(b),'ratio med %.4f'%(g.Vr/g.Vb).median(), 'corr',round(np.corrcoef(g.Vb,g.Vr)[0,1],3))

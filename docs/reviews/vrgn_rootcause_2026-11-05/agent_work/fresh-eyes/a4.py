import pandas as pd, numpy as np
d=pd.read_csv('/home/user/DC-Balancer-Board-Teensy/logs/ML0227/ML0227.csv',usecols=['t_us','I_fc','I_batt','V_bus','V_chg','V_rgn','I_cmd'])
d['t']=(d.t_us-d.t_us.iloc[0])/1e6
fed=d[d.V_chg>3]
print('fed n',len(fed),'t',fed.t.min(),fed.t.max())
# bin by V_bus
fed=fed.assign(b=(fed.V_bus*2).round()/2)
g=fed.groupby('b').agg(n=('V_bus','size'),Vb=('V_bus','mean'),Vc=('V_chg','mean'),Vr=('V_rgn','mean'),I=('I_batt','mean'),If=('I_fc','mean'))
g['r_bus']=g.Vr/g.Vb; g['r_chg']=g.Vr/g.Vc; g['chg_bus']=g.Vc/g.Vb
print(g.round(4).to_string())

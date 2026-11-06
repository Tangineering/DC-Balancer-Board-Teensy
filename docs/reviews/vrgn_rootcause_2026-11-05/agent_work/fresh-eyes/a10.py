import pandas as pd, numpy as np, glob,os
sc=pd.read_csv('scan.csv').dropna(subset=['ratio']).set_index('log')
rows=[]
for nm in sc.index:
    f=glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/%s/%s.csv'%(nm,nm))+glob.glob('/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/%s.csv'%nm)
    if not f: continue
    d=pd.read_csv(f[0],usecols=['t_us','V_bus','V_rgn','I_fc','I_batt','I_cmd'])
    d['t']=(d.t_us-d.t_us.iloc[0])/1e6
    q=d[(d.V_bus>15.5)&(d.V_rgn<d.V_bus)&(d.V_rgn>10)&((d.I_fc+d.I_batt)<0.06)]
    if len(q)<2000: continue
    T=d.t.max()
    a=q[q.t<q.t.min()+3]; b=q[q.t>q.t.max()-3]
    ra=(a.V_rgn/a.V_bus).median(); rb=(b.V_rgn/b.V_bus).median()
    P=((d.I_fc+d.I_batt)*d.V_bus).mean()
    rows.append((nm,sc.loc[nm,'uptime_min'],T,ra,rb,(rb-ra)*1e4,P,d.I_cmd.abs().mean()))
r=pd.DataFrame(rows,columns=['log','up','dur','r_start','r_end','d_1e4','P_bus_W','Icmd'])
print(r.round(4).to_string(index=False))
print('corr(d,P)',np.corrcoef(r.d_1e4,r.P_bus_W)[0,1],'corr(d,dur)',np.corrcoef(r.d_1e4,r.dur)[0,1])
print('mean d per log',r.d_1e4.mean(),' frac negative',(r.d_1e4<0).mean())

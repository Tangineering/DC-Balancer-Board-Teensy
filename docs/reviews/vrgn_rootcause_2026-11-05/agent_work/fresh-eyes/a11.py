import pandas as pd, numpy as np, glob
sc=pd.read_csv('scan.csv').dropna(subset=['ratio'])
rows=[]
for nm in sc.log:
    f=glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/%s/%s.csv'%(nm,nm))+glob.glob('/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/%s.csv'%nm)
    if not f: continue
    d=pd.read_csv(f[0],usecols=['V_bus','V_rgn','V_fc','V_batt','V_chg','I_fc','I_batt'])
    q=d[(d.V_bus>15)&(d.V_rgn<d.V_bus)&(d.V_rgn>10)&((d.I_fc+d.I_batt)<0.06)]
    if len(q)<1000: continue
    rows.append((nm,(q.V_rgn/q.V_bus).median(),q.V_bus.median(),q.V_fc.median(),q.V_batt.median(),q.V_chg.median()))
r=pd.DataFrame(rows,columns=['log','ratio','Vbus','Vfc','Vbatt','Vchg'])
print(r.describe().round(3))
for c in ['Vbus','Vfc','Vbatt','Vchg']: print(c,round(np.corrcoef(r.ratio,r[c])[0,1],3))
r['day']=r.log
print(r.groupby(pd.cut(r.Vfc,[-1,1,9,11,13,20])).ratio.agg(['count','median','min','max']))
print(r.to_string(index=False))

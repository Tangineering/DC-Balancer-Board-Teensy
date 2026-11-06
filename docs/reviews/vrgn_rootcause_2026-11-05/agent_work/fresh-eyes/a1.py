import pandas as pd, numpy as np, sys
f=sys.argv[1]
d=pd.read_csv(f,usecols=['t_us','I_fc','I_batt','V_bus','V_fc','V_batt','V_chg','V_rgn','I_cmd','v_act','gFC','gBT'])
s_rgn=3.3*88.7/10/4095; s_bus=3.3*56.4/10/4095
d['crg']=d.V_rgn/s_rgn; d['cbus']=d.V_bus/s_bus; d['cchg']=d.V_chg/s_rgn
print(f,len(d))
print('V_chg counts unique (first10):',np.unique(np.round(d.cchg))[:10], 'frac nonzero',(d.cchg>0.5).mean())
print('rgn counts frac int dev', np.abs(d.crg-np.round(d.crg)).max(), 'bus', np.abs(d.cbus-np.round(d.cbus)).max())
m=(d.V_bus>14)&(d.V_chg<0.5)
x=d[m]
r=x.V_rgn/x.V_bus
print('ratio med',r.median(), 'n',len(x))
# regress rgn counts on bus voltage, I_fc, I_batt, V_fc, V_batt
X=np.column_stack([np.ones(len(x)),x.V_bus,x.I_fc,x.I_batt,x.V_fc,x.V_batt,np.abs(x.I_cmd)])
b,*_=np.linalg.lstsq(X,x.V_rgn,rcond=None)
print('coef [1,Vbus,Ifc,Ibatt,Vfc,Vbatt,|Icmd|]:',np.round(b,4))
for c in ['I_fc','I_batt','V_fc','V_batt','I_cmd','v_act','gFC','gBT','t_us']:
    print(c,'corr with ratio',round(np.corrcoef(x[c],r)[0,1],3),'range',round(x[c].quantile(.01),3),round(x[c].quantile(.99),3))

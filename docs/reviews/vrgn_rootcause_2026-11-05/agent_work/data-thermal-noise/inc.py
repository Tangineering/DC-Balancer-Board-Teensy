import pandas as pd,numpy as np,sys
from scipy import signal
f=sys.argv[1]
d=pd.read_csv(f,usecols=['t_us','V_bus','V_rgn','V_chg','I_fc','I_batt','I_cmd','v_act']).dropna()
t=(d.t_us.values-d.t_us.values[0])*1e-6
b=d.V_bus.values; r=d.V_rgn.values; I=(d.I_fc+d.I_batt).values
print(f, 'N',len(d),'dur',t[-1], 'median ratio',np.median(r/b))
# check uniform sampling
dt=np.diff(t); print('dt med',np.median(dt),'max',dt.max())
fs=1/np.median(dt)
def bp(x,lo,hi):
    sos=signal.butter(2,[lo,hi],btype='band',fs=fs,output='sos')
    return signal.sosfiltfilt(sos,x)
for lo,hi in [(0.05,0.5),(0.2,2),(0.5,5),(1,10),(2,20),(5,50),(20,200)]:
    bb=bp(b,lo,hi); rr=bp(r,lo,hi); ii=bp(I,lo,hi)
    ols=np.dot(bb,rr)/np.dot(bb,bb); rev=np.dot(rr,rr)/np.dot(bb,rr)
    iv=np.dot(ii,rr)/np.dot(ii,bb)
    c=np.corrcoef(bb,rr)[0,1]
    print(f'{lo:5}-{hi:5} Hz sd_b {bb.std()*1e3:6.2f}mV sd_r {rr.std()*1e3:6.2f}mV corr {c:.3f} OLS {ols:.3f} rev {rev:.3f} IV(I) {iv:.3f}  corr(b,I) {np.corrcoef(bb,ii)[0,1]:.3f}')

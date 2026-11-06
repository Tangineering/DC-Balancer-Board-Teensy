import pandas as pd,numpy as np,sys
from scipy import signal
f=sys.argv[1]
d=pd.read_csv(f).dropna(subset=['V_bus','V_rgn'])
t=(d.t_us.values-d.t_us.values[0])*1e-6
fs=1/np.median(np.diff(t))
b=d.V_bus.values; r=d.V_rgn.values; I=(d.I_fc+d.I_batt).values; ifc=d.I_fc.values; ibt=d.I_batt.values
def bp(x,lo,hi):
    sos=signal.butter(2,[lo,hi],btype='band',fs=fs,output='sos'); return signal.sosfiltfilt(sos,x)
for lo,hi in [(0.05,0.5),(0.2,2),(0.5,5)]:
    bb,rr,ii,ff,tt=[bp(x,lo,hi) for x in (b,r,I,ifc,ibt)]
    s=-np.dot(ii,bb)/np.dot(ii,ii)
    # joint regression r ~ b + I
    X=np.c_[bb,ii]; coef,res,_,_=np.linalg.lstsq(X,rr,rcond=None)
    # joint regression b ~ ifc + ibt (droop check)
    c2=np.linalg.lstsq(np.c_[ff,tt],bb,rcond=None)[0]
    # residual of b after I: are there V_bus moves not explained by I?
    bres=bb+s*ii
    print(f'{lo}-{hi}Hz: dVbus/dI={-s:.4f} V/A ; r~b+I: gb={coef[0]:.3f} gI={coef[1]*1e3:.2f} mV/A ; b~Ifc,Ibt {c2[0]:.4f},{c2[1]:.4f}; sd(b resid of I) {bres.std()*1e3:.2f} mV vs sd b {bb.std()*1e3:.2f}; cond corr(b,I) {np.corrcoef(bb,ii)[0,1]:.3f}')

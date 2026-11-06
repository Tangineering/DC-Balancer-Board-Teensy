import numpy as np,pandas as pd
from scipy import signal
R='/home/user/DC-Balancer-Board-Teensy/logs/'
kb=3.3*5.64/4095; kr=3.3*8.87/4095
d=pd.read_csv(R+'ML0227/ML0227.csv'); t=(d.t_us-d.t_us.iloc[0])*1e-6
s=d[(t>13)&(t<23.5)]
fs=1/np.median(np.diff(s.t_us*1e-6))
B=s.V_bus.values/kb; C=s.V_chg.values/kr; Rr=s.V_rgn.values/kr; I=(s.I_fc+s.I_batt).values
print('ML0227 idle, V_chg fed, 13-23.5 s, N',len(s),'fs',round(fs))
for nm,x,k in [('V_bus',B,kb),('V_chg',C,kr),('V_rgn',Rr,kr)]:
    dx=np.diff(x)
    print(f'{nm}: mean {x.mean():.2f} cnt  std {x.std():.3f} cnt  std(diff)/sqrt2 {dx.std()/np.sqrt(2):.3f} cnt  unique {len(np.unique(x))}  node-referred hf noise {dx.std()/np.sqrt(2)*3.3/4095*1e3:.3f} mV  ; in reading volts {dx.std()/np.sqrt(2)*k*1e3:.2f} mV')
# PSD comparisons
for nm,x in [('V_bus',B*kb),('V_chg',C*kr),('V_rgn',Rr*kr)]:
    f,P=signal.welch(x-x.mean(),fs=fs,nperseg=2048)
    bands=[(0.5,5),(5,50),(50,200),(200,440)]
    print(nm,' '.join(f'{a}-{b}Hz:{np.sqrt(np.trapezoid(P[(f>=a)&(f<b)],f[(f>=a)&(f<b)]))*1e3:.2f}mV' for a,b in bands))
# coherence V_chg vs V_bus, V_rgn vs V_bus, V_rgn vs V_chg
for a,b,nm in [(C,B,'chg~bus'),(Rr,B,'rgn~bus'),(Rr,C,'rgn~chg')]:
    f,Cx=signal.coherence(a,b,fs=fs,nperseg=2048)
    print(nm,'coh', ' '.join(f'{x:.2f}' for x in [Cx[(f>0.5)&(f<5)].mean(),Cx[(f>5)&(f<50)].mean(),Cx[(f>50)&(f<200)].mean()]))
# gains in band 0.3-5 Hz
sos=signal.butter(2,[0.3,5],'band',fs=fs,output='sos')
bb,cc,rr=[signal.sosfiltfilt(sos,x) for x in (B*kb,C*kr,Rr*kr)]
print('band 0.3-5Hz sd mV: bus %.2f chg %.2f rgn %.2f'%(bb.std()*1e3,cc.std()*1e3,rr.std()*1e3))
for a,b,nm in [(cc,bb,'chg/bus'),(rr,bb,'rgn/bus'),(rr,cc,'rgn/chg')]:
    print(nm,'OLS %.3f rev %.3f corr %.3f'%(np.dot(a,b)/np.dot(b,b),np.dot(a,a)/np.dot(a,b),np.corrcoef(a,b)[0,1]))

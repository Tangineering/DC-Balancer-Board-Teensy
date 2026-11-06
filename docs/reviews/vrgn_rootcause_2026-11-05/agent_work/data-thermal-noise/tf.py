import numpy as np,pandas as pd,sys
from scipy import signal
R='/home/user/DC-Balancer-Board-Teensy/logs/'
for n in sys.argv[1:]:
    d=pd.read_csv(R+f'{n}/{n}.csv',usecols=['t_us','V_bus','V_rgn','I_cmd']).dropna()
    t=(d.t_us-d.t_us.iloc[0]).values*1e-6; fs=1/np.median(np.diff(t)); tu=np.arange(t[0],t[-1],1/fs)
    b=np.interp(tu,t,d.V_bus); r=np.interp(tu,t,d.V_rgn); ic=np.interp(tu,t,d.I_cmd)
    if (ic<0).any(): 
        k=np.where(ic<0)[0]; print(n,'has regen; truncating before first'); tu,b,r=tu[:max(k[0]-3000,0)],b[:max(k[0]-3000,0)],r[:max(k[0]-3000,0)]
    nps=int(fs*20)
    f,Pxx=signal.welch(b,fs,nperseg=nps,detrend='linear'); _,Pyy=signal.welch(r,fs,nperseg=nps,detrend='linear'); _,Pxy=signal.csd(b,r,fs,nperseg=nps,detrend='linear')
    coh=np.abs(Pxy)**2/(Pxx*Pyy); H1=np.abs(Pxy)/Pxx; H2=Pyy/np.abs(Pxy); ph=np.angle(Pxy,deg=True)
    print(n,'fs',round(fs))
    for a,bb in [(0.05,0.2),(0.2,0.5),(0.5,1),(1,2),(2,4),(4,8),(8,16),(16,32),(32,64),(64,128)]:
        m=(f>=a)&(f<bb)
        if m.sum()==0: continue
        w=coh[m]
        print(f'  {a:5}-{bb:5} Hz coh {w.mean():.2f}  H1 {np.average(H1[m],weights=w):.3f}  H2 {np.average(H2[m],weights=w):.3f}  phase {np.average(ph[m],weights=w):+.1f} deg')

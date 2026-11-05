import pandas as pd,numpy as np,sys
df=pd.read_csv(sys.argv[1])
for (lg,ev),g in df.groupby(['log','ev']):
    h=g[(g.k>=0)&(g.vb<g.base-0.3)]; pre=g[g.k<0]
    x=np.r_[h.node.values,pre.node.values]; y=np.r_[h.leak_uA.values,pre.leak_uA.values]
    a=(x@y)/(x@x); r_res=np.sqrt(np.mean((y-a*x)**2)); r_cc=np.std(y)
    p=np.polyfit(x,y,1); r_lin=np.sqrt(np.mean((y-np.polyval(p,x))**2))
    best=None
    for n in np.arange(1,4.01,0.05):
        for R in np.arange(0,12001,100):
            # V = n Vt ln(I/Is) + I R ; for each (n,R) best lnIs closed form
            I=y*1e-6; z=x-I*R; lnIs=np.mean(np.log(I)-z/(n*0.0257))
            v=n*0.0257*(np.log(I)-lnIs)+I*R; e=np.sqrt(np.mean((x-v)**2))
            if best is None or e<best[0]: best=(e,n,R,lnIs)
    print('%s N=%d | resistor-to-GND: R=%.0fk rms=%.1fuA | const-current: rms=%.1fuA | threshold-linear: Von=%.3fV R=%.2fk rms=%.2fuA | diode(n)+R: n=%.2f R=%.0f Is=%.1e rmsV=%.1fmV'%(lg,len(x),1e3/a,r_res,r_cc,-p[1]/p[0],1e3/p[0],r_lin,best[1],best[2],np.exp(best[3]),best[0]*1e3))

import numpy as np,pandas as pd
p=pd.read_csv('dip_pts.csv')
R1=78.7e3
for n,g in p.groupby('name'):
    g=g.dropna(subset=['leak_fall']) # interpolated points only
    x=g.node.values; y=g.leak.values
    print(n,'N',len(x),'node %.3f..%.3f leak %.1f..%.1f uA'%(x.min(),x.max(),y.min(),y.max()))
    print('   local slope uA/V:',np.round(np.diff(y)/np.diff(x),0))
    # linear threshold
    a,b=np.polyfit(x,y,1); r=y-(a*x+b); print('   lin-threshold: g=%.1f uA/V (1/g=%.2f kOhm) Vth=%.4f V rms=%.3f'%(a,1e3/a,-b/a,r.std()))
    # exp
    c=np.polyfit(x,np.log(y),1); r=y-np.exp(np.polyval(c,x)); print('   exponential: Vs=%.4f V (n=%.1f at Vt=25.9mV) rms=%.3f'%(1/c[0],1/c[0]/0.0259,r.std()))
    c=np.polyfit(np.log(x),np.log(y),1); r=y-np.exp(np.polyval(c,np.log(x))); print('   power: n=%.2f rms=%.3f'%(c[0],r.std()))
    # quadratic threshold (square law) I=k(V-Vt)^2
    best=None
    for Vt in np.linspace(0.5,1.29,400):
        k=np.sum(y*(x-Vt)**2)/np.sum((x-Vt)**4); rr=y-k*(x-Vt)**2; s=rr.std()
        if best is None or s<best[0]: best=(s,Vt,k)
    print('   square-law: Vt=%.3f k=%.1f uA/V^2 rms=%.3f'%(best[1],best[2],best[0]))
    # resistive through origin & constant
    k=np.sum(x*y)/np.sum(x*x); print('   resistive (through 0): R=%.1f k rms=%.2f; constant rms=%.2f'%(1e3/k,(y-k*x).std(),y.std()))
    # extrapolate to node 2.495 under lin & exp
    print('   extrap I(2.495): lin %.0f uA -> Vtrip %.1f V ; exp %.0f uA -> Vtrip %.1f V'%(a*2.495+b,22.13+(a*2.495+b)*1e-6*R1, np.exp(np.polyval(np.polyfit(x,np.log(y),1),2.495)), 22.13+np.exp(np.polyval(np.polyfit(x,np.log(y),1),2.495))*1e-6*R1))

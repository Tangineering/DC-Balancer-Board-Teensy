import numpy as np,pandas as pd
R1=78.7e3;R2=10e3;G=8.87
def leak(vm,vn): return ((vm-vn)/R1 - vn/R2)*1e6
ev=[('TP0115',4.4550),('TP0178',7.4906),('TP0201',7.7020),('TP0209',7.7457)]
allpts=[]
for n,tm in ev:
    d=pd.read_csv(f'/home/user/DC-Balancer-Board-Teensy/logs/{n}/{n}.csv')
    t=(d.t_us-d.t_us.iloc[0]).values/1e6; vb=d.V_bus.values; vr=d.V_rgn.values
    j=np.argmin(abs(t-tm))
    pre=slice(j-400,j-20); base=np.median(vr[pre]/vb[pre]); vbq=np.median(vb[pre]); vrq=np.median(vr[pre])
    # falling branch: from j back while vb decreasing ; rising: j forward
    f0=j
    while vb[f0-1]>vb[f0] and vb[f0-1]<15.95: f0-=1
    r1=j
    while vb[r1+1]>vb[r1] and vb[r1+1]<15.95: r1+=1
    fb=vb[f0:j+1][::-1]; fr=vr[f0:j+1][::-1]   # increasing vb
    rb=vb[j:r1+1]; rr=vr[j:r1+1]
    print(n,'base %.4f  quiescent vb %.3f vr %.3f leak %.2f uA @node %.4f; fall %d samples, rise %d samples; min vb %.3f vr %.3f'%(base,vbq,vrq,leak(vbq,vrq/G),vrq/G,len(fb),len(rb),vb[j],vr[j]))
    for V in [12.4,12.8,13.2,13.6,14.0,14.4,14.8,15.2,15.6]:
        if V<max(fb.min(),rb.min()) or V>min(fb.max(),rb.max()): continue
        a=np.interp(V,fb,fr); b=np.interp(V,rb,rr); m=(a+b)/2
        allpts.append((n,V,m/G,leak(V,m/G),leak(V,a/G),leak(V,b/G),base))
        print('   Vm=%.1f vr_fall %.3f vr_rise %.3f mean %.3f ratio %.4f node %.4f leak %.2f (fall %.2f rise %.2f) uA'%(V,a,b,m,m/V,m/G,leak(V,m/G),leak(V,a/G),leak(V,b/G)))
    allpts.append((n,vbq,vrq/G,leak(vbq,vrq/G),np.nan,np.nan,base))
pd.DataFrame(allpts,columns='name Vm node leak leak_fall leak_rise base'.split()).to_csv('dip_pts.csv')

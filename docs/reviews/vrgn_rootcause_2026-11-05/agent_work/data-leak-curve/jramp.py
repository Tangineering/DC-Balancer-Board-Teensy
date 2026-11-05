import pandas as pd,numpy as np
R1=78.7e3;R2=10e3;G=8.87
d=pd.read_csv('/home/user/DC-Balancer-Board-Teensy/logs/ML0227/ML0227.csv')
t=(d.t_us-d.t_us.iloc[0]).values/1e6
vb=d.V_bus.values; vc=d.V_chg.values; vr=d.V_rgn.values; I=(d.I_fc+d.I_batt).values
def leak(vm,vn): return ((vm-vn)/R1 - vn/R2)*1e6
# quiescent J (REGEN closed, no current)
q=(t>13)&(t<23.6)
vn=vr[q]/G
print('quiescent J: N',q.sum(),'vb %.4f vc %.4f vr %.4f'%(vb[q].mean(),vc[q].mean(),vr[q].mean()))
for x,lab in [(0,'Vm=Vbus'),(0.5,'mid'),(1,'Vm=Vchg')]:
    vm=vb[q]-x*(vb[q]-vc[q]); print('   %s Vm=%.3f node=%.4f leak=%.2f uA ratio=%.4f'%(lab,vm.mean(),vn.mean(),leak(vm,vn).mean(),(vr[q]/vm).mean()))
# ramp: bin by total current
r=(t>23.69)&(t<24.722)
print('ramp bins by I_tot (A): I, vb, vc, vr, node, leak[x=0], leak[x=.5], leak[x=1], ratio vs vm[x=.5]')
rows=[]
for a in np.arange(0,12,1.0):
    m=r&(I>=a)&(I<a+1)
    if m.sum()<10: continue
    vn=vr[m].mean()/G; b=vb[m].mean(); c=vc[m].mean()
    L=[leak(b-x*(b-c),vn) for x in (0,0.5,1)]
    rows.append((I[m].mean(),b,c,vr[m].mean(),vn,*L))
    print('  %5.2f %.3f %.3f %.3f %.4f | %6.2f %6.2f %6.2f | ratio %.4f  (N=%d)'%(I[m].mean(),b,c,vr[m].mean(),vn,*L,vr[m].mean()/(b-0.5*(b-c)),m.sum()))
np.save('jramp_rows.npy',np.array(rows))
# collapse samples
for tt in [24.7258,24.7269,24.7281,24.7292,24.7325,24.7337]:
    i=np.argmin(abs(t-tt)); vn=vr[i]/G
    print('collapse t=%.4f vb=%.3f vc=%.3f vr=%.3f node=%.4f leak[Vm=vb]=%.2f leak[mid]=%.2f leak[Vm=vc]=%.2f ratio range %.3f..%.3f'%(t[i],vb[i],vc[i],vr[i],vn,leak(vb[i],vn),leak((vb[i]+vc[i])/2,vn),leak(vc[i],vn),vr[i]/vb[i],vr[i]/vc[i]))

import pandas as pd,numpy as np
# model: reading(t) = A exp(-t/tau) - V0 ; for each V0 fit log(reading+V0) linear -> A,tau ; pick SSE
sets=[]
for n in ['ML0215','ML0216']:
    d=pd.read_csv(f'/home/user/DC-Balancer-Board-Teensy/logs/{n}/{n}.csv')
    t=(d.t_us.values-d.t_us.values[0])/1e6; v=d.V_rgn.values
    if n=='ML0216': m=v<0.99; t=t[m]-t[m][0]; v=v[m]
    sets.append((n,t,v))
d=np.load('/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/npz/rosbag_sdp_2026-10-27_00-52-58.npz')
t=d['vs_t'];v=d['vs'][:,7]; m=v<2.95
sets.append(('bag1027<2.95',t[m]-t[m][0],v[m]))
for n,t,v in sets:
    best=[]
    for V0 in np.linspace(-1.5,1.5,301):
        y=v+V0
        if (y<=0).any(): continue
        p=np.polyfit(t,np.log(y),1)
        r=v-(np.exp(np.polyval(p,t))-V0)
        best.append((np.sum(r**2),V0,-1/p[0],r.std()))
    best=np.array(best); i=best[:,0].argmin(); N=len(t)
    s2=best[i,0]/N
    # approx 95% interval: delta SSE < 4*s2 (chi2 1dof, with white-noise assumption -> optimistic)
    ok=best[best[:,0]<best[i,0]+4*s2]
    print(n,'N',N,'range %.3f->%.3f'%(v[0],v[-1]),'best V0=%.3f tau=%.1f rms=%.4f; V0 band %.3f..%.3f (white-noise, optimistic)'%(best[i,1],best[i,2],best[i,3],ok[:,1].min(),ok[:,1].max()))
    for V0 in [0,0.3,1.0,2.4]:
        j=np.argmin(abs(best[:,1]-V0)); print('    V0=%.2f: tau=%.1f rms=%.4f'%(best[j,1],best[j,2],best[j,3]))

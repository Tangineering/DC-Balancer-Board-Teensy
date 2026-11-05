import pandas as pd,numpy as np
def loctau(t,v,edges):
    out=[]
    for a,b in zip(edges[:-1],edges[1:]):
        m=(v<a)&(v>=b)
        if m.sum()<20: continue
        p=np.polyfit(t[m],np.log(v[m]),1)
        out.append((a,b,m.sum(),t[m].max()-t[m].min(),-1/p[0]))
    return out
for n in ['ML0215','ML0216','ML0217']:
    d=pd.read_csv(f'/home/user/DC-Balancer-Board-Teensy/logs/{n}/{n}.csv')
    t=(d.t_us.values-d.t_us.values[0])/1e6; v=d.V_rgn.values
    print(n,'dur',t[-1],'vrgn start/end',v[:200].mean(),v[-200:].mean(),'vbus max',d.V_bus.max(),'vchg max',d.V_chg.max(),'vbatt',d.V_batt.median(),'vfc',d.V_fc.median())
    for r in loctau(t,v,[1.4,1.2,1.0,0.8,0.6,0.5,0.4,0.3,0.25,0.2,0.15,0.1,0.05]): print('   %.2f-%.2f n=%d span=%.1fs tau=%.1f'%r)
d=np.load('/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/npz/rosbag_sdp_2026-10-27_00-52-58.npz')
t=d['vs_t'];v=d['vs'][:,7]
print('bag 10-27')
for r in loctau(t,v,[4.8,4.5,4.2,3.9,3.6,3.3,3.1,2.9,2.7,2.5,2.3,2.1,1.9,1.7,1.5]): print('   %.2f-%.2f n=%d span=%.1fs tau=%.1f'%r)

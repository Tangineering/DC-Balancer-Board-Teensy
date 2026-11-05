import os,numpy as np,pandas as pd
R='/home/user/DC-Balancer-Board-Teensy/'; S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/'
G1=1/78.7e3; G2=1/10e3; GP=90e-6
pl=pd.read_csv('perlog.csv')
def load(n):
    c=R+f'logs/{n}/{n}.csv'
    if not os.path.exists(c): c=S+n+'.csv'
    return pd.read_csv(c,usecols=['t_us','V_bus','V_rgn','I_fc','I_batt','I_cmd']).dropna()
def leakser(d,ratio):
    I=d.I_fc+d.I_batt
    m=(I<0.1)&(d.V_bus>15.5)&(np.abs(d.V_rgn-ratio*d.V_bus)<0.15)
    vm=d.V_bus-0.035; vn=d.V_rgn/8.87
    L=((vm-vn)*G1-vn*G2)
    Lref=L-GP*(vn-1.50)
    return m,L*1e6,Lref*1e6,vn
rows=[]
for _,p in pl.iterrows():
    d=load(p.log); m,L,Lr,vn=leakser(d,p.ratio)
    if m.sum()<200: continue
    rows.append(dict(log=p.log,boot=p.boot,t=p.start_min+0.5*p.dur_s/60,L=L[m].mean(),Lref=Lr[m].mean(),vn=vn[m].mean(),sem=Lr[m].std()/np.sqrt(m.sum()/50)))
t=pd.DataFrame(rows); t.to_csv('thermal2.csv',index=False)
print('per-boot fits (Lref at Vn=1.50 V, mean of idle samples):')
for b,g in t.groupby('boot'):
    if len(g)<3: continue
    c=np.polyfit(g.t,g.Lref,1)
    print(f'boot {b:2d} {g.log.iloc[0]}-{g.log.iloc[-1]} n={len(g):2d} uptime {g.t.min():5.1f}-{g.t.max():5.1f} min  Lref {g.Lref.iloc[0]:.2f}->{g.Lref.iloc[-1]:.2f} uA  slope {c[0]*1e3:6.1f} nA/min  corr {np.corrcoef(g.t,g.Lref)[0,1]:+.2f}  rel {100*(g.Lref.iloc[-1]-g.Lref.iloc[0])/g.Lref.iloc[0]:+.2f}%')
# long logs windowed
for n in ['ML0226','ML0145','ML0135','ML0203','ML0157','ML0151']:
    p=pl[pl.log==n].iloc[0]; d=load(n); m,L,Lr,vn=leakser(d,p.ratio)
    tt=(d.t_us-d.t_us.iloc[0])*1e-6
    w=(tt//30).astype(int)
    df=pd.DataFrame(dict(w=w[m],Lr=Lr[m],t=tt[m]))
    g=df.groupby('w').agg(t=('t','mean'),Lr=('Lr','mean'),n=('Lr','size'))
    g=g[g.n>300]
    if len(g)>2:
        c=np.polyfit(g.t/60,g.Lr,1)
        print(n,'start',round(p.start_min,2),'min; 30s windows',len(g),' Lref:',' '.join(f'{x:.2f}' for x in g.Lr),f' slope {c[0]*1e3:.1f} nA/min')

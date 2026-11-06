import glob,os,re,struct,numpy as np,pandas as pd
R='/home/user/DC-Balancer-Board-Teensy/'; S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/'
G1=1/78.7e3; G2=1/10e3
pl=pd.read_csv('perlog.csv')
rows=[]
for _,p in pl.iterrows():
    n=p.log
    c=R+f'logs/{n}/{n}.csv'
    if not os.path.exists(c): c=S+n+'.csv'
    d=pd.read_csv(c,usecols=['t_us','V_bus','V_rgn','I_fc','I_batt','I_cmd']).dropna()
    t=(d.t_us-d.t_us.iloc[0])*1e-6
    I=d.I_fc+d.I_batt
    q=d[(I<0.1)&(d.I_cmd.abs()<0.01)&(d.V_bus>15.5)&(np.abs(d.V_rgn-p.ratio*d.V_bus)<0.15)]
    if len(q)<200: q=d[(I<0.12)&(d.V_bus>15.5)&(np.abs(d.V_rgn-p.ratio*d.V_bus)<0.15)]
    if len(q)<200: continue
    vm=q.V_bus-0.035; vn=q.V_rgn/8.87
    leak=((vm-vn)*G1-vn*G2)*1e6
    for gp in (72,90,113):
        pass
    vnm=np.median(vn)
    L=np.median(leak)
    rows.append(dict(log=n,boot=p.boot,start_min=p.start_min,dur=p.dur_s,nidle=len(q),vbus_idle=np.median(q.V_bus),vn=vnm,leak=L,
        leak_ref_90=L-90*(vnm-1.50)*1e0*1e0 if False else L-90e-6*(vnm-1.50)*1e6, leak_ref_72=L-72*(vnm-1.50), leak_ref_113=L-113*(vnm-1.50),
        Iload=I.mean()))
t=pd.DataFrame(rows); t.to_csv('thermal.csv',index=False)
pd.set_option('display.width',200);pd.set_option('display.max_rows',300)
print(t.to_string(float_format=lambda x:f'{x:.3f}'))

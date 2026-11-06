import glob,os,re,struct,numpy as np,pandas as pd
R='/home/user/DC-Balancer-Board-Teensy/'; S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/'
G1=1/78.7e3; G2=1/10e3
def key(p): return int(re.match(r"([A-Z]+)(\d+)",os.path.basename(p)).group(2))
rows=[]
for blg in sorted(glob.glob(R+'logs/*.BLG'),key=key):
    n=os.path.basename(blg)[:-4]
    if n.startswith('SY'): continue
    h=open(blg,'rb').read(32)
    if h[4]<3: continue
    fw=struct.unpack_from('<H',h,18)[0]; sm=struct.unpack_from('<I',h,8)[0]
    c=R+f'logs/{n}/{n}.csv'
    if not os.path.exists(c): c=S+n+'.csv'
    if not os.path.exists(c): continue
    d=pd.read_csv(c,usecols=lambda x:x in('t_us','V_bus','V_rgn','I_fc','I_batt','I_cmd','V_chg')).dropna(subset=['V_bus','V_rgn'])
    q=d[(d.V_bus>15)&(d.V_bus<18.5)&(d.V_rgn<d.V_bus)&(d.V_rgn>10)]
    if len(q)<100: continue
    I=(q.I_fc+q.I_batt)
    qi=q[I<0.1]
    t=(q.t_us-d.t_us.iloc[0])*1e-6
    vm=q.V_bus-0.035; vn=q.V_rgn/8.87
    leak=(vm-vn)*G1-vn*G2
    rows.append(dict(log=n,fw=fw,start_min=sm/60000,dur_s=(d.t_us.iloc[-1]-d.t_us.iloc[0])*1e-6,n=len(q),
        ratio=np.median(q.V_rgn/q.V_bus), ratio_idle=np.median(qi.V_rgn/qi.V_bus) if len(qi)>100 else np.nan,
        vbus=np.median(q.V_bus), Imean=I.mean(), leak_uA=np.median(leak)*1e6, vn=np.median(vn)))
t=pd.DataFrame(rows)
# boot sessions: new session when start_min decreases
sess=[];s=0;prev=1e9
for sm in t.start_min:
    if sm<prev-0.01: s+=1
    sess.append(s); prev=sm
t['boot']=sess
t.to_csv('perlog.csv',index=False)
pd.set_option('display.width',200);pd.set_option('display.max_rows',300)
print(t.to_string(float_format=lambda x:f'{x:.4f}'))

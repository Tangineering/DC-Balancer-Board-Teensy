import numpy as np,pandas as pd,os,glob
R='/home/user/DC-Balancer-Board-Teensy/logs/'; S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/'
G1=1/78.7e3;G2=1/10e3
pl=pd.read_csv('perlog.csv')
pts=[]
for _,p in pl.iterrows():
    c=R+f'{p.log}/{p.log}.csv'
    if not os.path.exists(c): c=S+p.log+'.csv'
    d=pd.read_csv(c,usecols=['t_us','V_bus','V_rgn','I_cmd','I_fc','I_batt']).dropna().reset_index(drop=True)
    b=d.V_bus.values; r=d.V_rgn.values
    dv=np.r_[0,np.diff(b)]
    m=(b<15.5)&(b>5)&(dv>0.05)   # rising fast: RT1987 forward, V-MOT follows
    for i in np.where(m)[0]:
        vn=r[i]/8.87; L=((b[i]-0.035-vn)*G1-vn*G2)*1e6
        pts.append((p.log,p.boot,i,b[i],r[i],vn,L,dv[i],d.I_cmd.values[i]))
P=pd.DataFrame(pts,columns=['log','boot','i','Vbus','Vrgn','vn','leak','dv','Icmd'])
P.to_csv('curve_pts.csv',index=False)
print(len(P),'rising samples from',P.log.nunique(),'logs')
P['bin']=(P.vn//0.05)*0.05
g=P.groupby('bin').agg(n=('leak','size'),leak_med=('leak','median'),q25=('leak',lambda x:np.percentile(x,25)),q75=('leak',lambda x:np.percentile(x,75)),dv=('dv','median'))
print(g.to_string(float_format=lambda x:f'{x:.2f}'))

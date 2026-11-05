import pandas as pd, numpy as np, glob, os, sys
R1,R2=78.7e3,10e3
rows=[]
for f in sorted(glob.glob('logs/*/*.csv')):
    n=os.path.basename(f)[:-4]
    try: d=pd.read_csv(f,usecols=lambda c:c in('t_us','V_bus','V_rgn','V_chg'))
    except Exception: continue
    if 'V_rgn' not in d or d.V_rgn.max()<1: continue
    vb=d.V_bus.values; vr=d.V_rgn.values
    # smoothness: previous and next V_bus within 0.6 V of this one (quasi-static), 4<Vbus<15.5
    ok=np.zeros(len(vb),bool)
    ok[1:-1]=(vb[1:-1]>4)&(vb[1:-1]<15.0)&(np.abs(vb[2:]-vb[:-2])<1.2)&(vr[1:-1]>0.5)
    # steady reference
    st=(vb>15.6)&(vb<16.1)
    if st.sum()<100: continue
    rat_st=np.median(vr[st]/vb[st])
    for i in np.where(ok)[0]:
        rows.append((n,vb[i],vr[i],rat_st,vb[i+1]-vb[i-1]))
df=pd.DataFrame(rows,columns=['log','vbus','vrgn','ratio_steady','dvb'])
df['ratio']=df.vrgn/df.vbus
df['Vn_true']=df.vbus*R2/(R1+R2)
df['Vn_read']=df.vrgn*R2/(R1+R2)
df['Ileak_uA']=((df.vbus-df.Vn_read)/R1-df.Vn_read/R2)*1e6
df.to_csv(sys.argv[1],index=False)
print(len(df), df.log.nunique())
df['bin']=pd.cut(df.vbus,[4,6,7,8,9,10,11,12,13,14,15])
g=df.groupby('bin').agg(n=('ratio','size'),ratio_med=('ratio','median'),ratio_q25=('ratio',lambda x:x.quantile(.25)),ratio_q75=('ratio',lambda x:x.quantile(.75)),Vn=('Vn_read','median'),I=('Ileak_uA','median'))
print(g.to_string())
fall=df[df.dvb<-0.2]; rise=df[df.dvb>0.2]
for name,x in (('fall',fall),('rise',rise)):
    print(name, x.groupby(pd.cut(x.vbus,[4,6,8,10,12,13,14,15])).ratio.agg(['size','median']).to_string())

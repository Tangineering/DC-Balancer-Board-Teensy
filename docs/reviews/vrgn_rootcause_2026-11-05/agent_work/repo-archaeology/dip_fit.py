import pandas as pd, numpy as np, glob, os, struct
R1,R2=78.7e3,10e3
out=[]
for f in sorted(glob.glob('logs/*/*.csv')):
    n=os.path.basename(f)[:-4]
    try: d=pd.read_csv(f,usecols=lambda c:c in('t_us','V_bus','V_rgn','V_chg'))
    except Exception: continue
    if 'V_rgn' not in d or d.V_rgn.max()<1: continue
    vb=d.V_bus.values; vr=d.V_rgn.values; t=d.t_us.values
    idx=np.where((vb<15.2)&(vb>11.0))[0]
    if len(idx)==0: continue
    for e in np.split(idx,np.where(np.diff(idx)>2)[0]+1):
        if len(e)<4: continue
        s=np.arange(max(e[0]-1,0),min(e[-1]+2,len(vb)))
        if vb[s].min()<10.5: continue   # skip deep collapses (V-MOT decoupled)
        vn=vr[s]*R2/(R1+R2); I=((vb[s]-vn)/R1-vn/R2)*1e6
        k=np.argmin(vb[s]); m=np.ones(len(s),bool); m[k]=False
        if m.sum()<4 or np.ptp(vn[m])<0.08: continue
        p=np.polyfit(vn[m],I[m],1); res=np.std(I[m]-np.polyval(p,vn[m]))
        rg=np.sum(vn[m]**2)/np.sum(vn[m]*I[m]); resR=np.std(I[m]-vn[m]/rg)
        out.append((n,round(t[e[0]]/1e6,2),len(s),round(vb[s].min(),2),round(1e3/p[0],2),round(-p[1]/p[0],3),round(res,2),round(resR,2)))
df=pd.DataFrame(out,columns=['log','t_s','n','vbus_min','Rs_k','V0','rms_knee','rms_Rgnd'])
pd.set_option('display.width',200); print(df.to_string()); print(df[['Rs_k','V0','rms_knee','rms_Rgnd']].describe())

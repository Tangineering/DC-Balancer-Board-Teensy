import glob,os,numpy as np,pandas as pd,sys
S=sys.argv[1]; R1=78.7e3; R2=10e3; G=8.87
out=[]
files=sorted(glob.glob('logs/*/*.csv'))+sorted(glob.glob(S+'/dec/*.csv'))
for f in files:
    nm=os.path.basename(f)[:-4]
    if nm.startswith('SY'): continue
    try: d=pd.read_csv(f,usecols=['t_us','V_bus','V_rgn','I_cmd'])
    except Exception: continue
    vb=d.V_bus.values; vr=d.V_rgn.values; ic=d.I_cmd.values
    base=pd.Series(vb).rolling(200,min_periods=50).median().values
    i=1
    while i<len(vb)-60:
        if base[i]>15.5 and vb[i]<base[i]-0.8 :
            st=i-6; en=min(len(vb),i+40)
            seg=slice(st,en)
            vmin_i=st+np.argmin(vb[seg])
            # baseline ratio from preceding 200 samples
            pre=slice(max(0,i-300),i-5)
            r0=np.median(vr[pre]/vb[pre])
            for k in range(st,en):
                br='down' if k<=vmin_i else 'up'
                out.append((nm,i,k-i,br,vb[k],vr[k],ic[k],r0,base[i]))
            i=en
        else: i+=1
df=pd.DataFrame(out,columns=['log','ev','k','br','vb','vr','icmd','r0','base'])
df['node']=df.vr/G
df['leak_uA']=((df.vb-df.node)/R1-df.node/R2)*1e6
df.to_csv(sys.argv[2],index=False)
ev=df.groupby(['log','ev']).agg(vbmin=('vb','min'),r0=('r0','first'),icmd=('icmd','median'))
print(len(ev)); print(ev.vbmin.describe())
print(ev.groupby('log').size().sort_values().tail(20))

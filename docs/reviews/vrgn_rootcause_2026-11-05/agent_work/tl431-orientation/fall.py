import glob,os,numpy as np,pandas as pd
out=[]
for f in sorted(glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/*/*.csv')):
    try: d=pd.read_csv(f,usecols=['t_us','V_bus','V_rgn'])
    except Exception: continue
    t=d.t_us.values/1e6; vr=d.V_rgn.values
    if vr.max()<16.5: continue
    # peaks above 16.5
    i=0;n=len(vr)
    while i<n:
        if vr[i]>16.5:
            j=i
            while j<n and vr[j]>15.5: j+=1
            seg=slice(i,j); k=i+np.argmax(vr[seg])
            # fall from peak-0.3 to 15.5 crossing
            a=k
            while a<j and vr[a]>vr[k]-0.3: a+=1
            if j-a>20:
                p=np.polyfit(t[a:j]-t[a],vr[a:j],1)
                out.append((os.path.basename(f),t[k],vr[k],p[0]))
            i=j
        else: i+=1
s=np.array([o[3] for o in out])
print(len(out),'falls; slope reading V/s: min',s.min(),'median',np.median(s),'max',s.max())
for o in out[:8]: print(o)

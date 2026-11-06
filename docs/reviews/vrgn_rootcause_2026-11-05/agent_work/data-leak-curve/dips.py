import glob,os,numpy as np,pandas as pd
R1=78.7e3;R2=10e3;G=8.87
S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad'
files=sorted(glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/*/*.csv'))+sorted(glob.glob(S+'/dec/*.csv'))
def leak(vm,vn): return ((vm-vn)/R1 - vn/R2)*1e6
out=[]
for f in files:
    n=os.path.basename(f)[:-4]
    if n.startswith('SY'): continue
    try: d=pd.read_csv(f,usecols=lambda c:c in('t_us','V_bus','V_rgn','V_chg','I_fc','I_batt','I_cmd'))
    except: continue
    if 'V_rgn' not in d: continue
    vb=d.V_bus.values; vr=d.V_rgn.values; t=(d.t_us.values-d.t_us.values[0])/1e6
    I=(d.I_fc+d.I_batt).values; vc=d.V_chg.values
    below=vb<15.0
    idx=np.where(below)[0]
    if len(idx)==0: continue
    segs=np.split(idx,np.where(np.diff(idx)>3)[0]+1)
    for s in segs:
        i0,i1=s[0],s[-1]
        if i0<200 or i1+50>len(vb): 
            pass
        j=s[np.argmin(vb[s])]
        pre=slice(max(0,i0-300),max(1,i0-50))
        base=np.median(vr[pre]/vb[pre]) if i0>60 else np.nan
        dur=t[i1]-t[i0]
        out.append(dict(name=n,t=t[j],dur_ms=dur*1e3,vbmin=vb[j],vr_at=vr[j],vc_at=vc[j],r_at=vr[j]/vb[j],base=base,I_at=I[j],node=vr[j]/G,leak_vb=leak(vb[j],vr[j]/G)))
o=pd.DataFrame(out)
pd.set_option('display.width',250); pd.set_option('display.max_rows',500)
print(o.to_string())
o.to_csv('dips.csv')

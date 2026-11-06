import glob,os,numpy as np,pandas as pd
S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad'
files=sorted(glob.glob('/home/user/DC-Balancer-Board-Teensy/logs/*/*.csv'))+sorted(glob.glob(S+'/dec/*.csv'))
rows=[]
for f in files:
    n=os.path.basename(f)[:-4]
    if n.startswith('SY'): continue
    try: d=pd.read_csv(f,usecols=lambda c:c in('t_us','V_bus','V_rgn','V_chg','I_fc','I_batt','I_cmd'))
    except Exception as e: continue
    if 'V_rgn' not in d: continue
    vb=d.V_bus.values; vr=d.V_rgn.values
    # rolling 51-sample std
    s=pd.Series(vb).rolling(51,center=True).std().values
    sr=pd.Series(vr).rolling(51,center=True).std().values
    q=(s<0.03)&(sr<0.03)&(vb>1)&(vr>0.3*vb)&(vr<1.2*vb)
    lo=q&(vb<15.3)
    rows.append((n,len(d),vb.min(),vb.max(),vr.max(),q.sum(),lo.sum(), np.median((vr/vb)[q&(vb>15.5)]) if (q&(vb>15.5)).any() else np.nan))
    if lo.sum()>0:
        b=np.round(vb[lo]*2)/2
        for bb in np.unique(b):
            m=lo&(np.round(vb*2)/2==bb)
            print('  LOW',n,bb,m.sum(),np.median(vr[m]/vb[m]),np.median(vb[m]),np.median(vr[m]))
r=pd.DataFrame(rows,columns='name n vbmin vbmax vrmax nq nlow ratio16'.split())
pd.set_option('display.width',200); print(r.to_string())
r.to_csv('scan1.csv')

import glob,os,numpy as np,pandas as pd,sys
S=sys.argv[1]
rows=[]
def proc(name,vb,vr,dt_ms):
    # stability: V_bus and V_rgn change < 20 mV over a 50 ms window centered
    n=max(1,int(round(50/dt_ms)))
    if len(vb)<3*n: return
    vb=np.asarray(vb,float); vr=np.asarray(vr,float)
    db=np.abs(vb[2*n:]-vb[:-2*n]); dr=np.abs(vr[2*n:]-vr[:-2*n])
    m=(db<0.02)&(dr<0.02)
    vbc=vb[n:-n][m]; vrc=vr[n:-n][m]
    k=(vbc>1.0)&(vbc<15.0)&(vrc>0.2)
    for a,b in zip(vbc[k],vrc[k]): rows.append((name,a,b))
files=sorted(glob.glob('logs/*/*.csv'))+sorted(glob.glob(S+'/dec/*.csv'))
for f in files:
    nm=os.path.basename(f)[:-4]
    if nm.startswith('SY'): continue
    try: d=pd.read_csv(f,usecols=['V_bus','V_rgn'])
    except Exception: continue
    proc(nm,d.V_bus.values,d.V_rgn.values,1.0)
for f in sorted(glob.glob(S+'/npz/*.npz')):
    z=np.load(f); vs=z['vs']; proc(os.path.basename(f)[:-4],vs[:,6],vs[:,7],20.0)
df=pd.DataFrame(rows,columns=['log','vb','vr'])
df.to_csv(sys.argv[2],index=False)
print(len(df))
if len(df):
  df['bin']=(df.vb).round(0)
  print(df.groupby('bin').agg(n=('vr','size'),logs=('log','nunique'),ratio_med=('vr',lambda x: np.nan),).head(0))
  g=df.assign(r=df.vr/df.vb).groupby('bin').agg(n=('r','size'),nlog=('log','nunique'),rmed=('r','median'),rlo=('r',lambda x:x.quantile(.05)),rhi=('r',lambda x:x.quantile(.95)))
  print(g)
  print(df.assign(r=df.vr/df.vb).groupby('log').agg(n=('r','size'),vbmin=('vb','min'),vbmax=('vb','max'),rmed=('r','median')).sort_values('n',ascending=False).head(30))

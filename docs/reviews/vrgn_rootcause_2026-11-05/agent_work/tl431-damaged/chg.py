import glob,os,numpy as np,pandas as pd,sys
S=sys.argv[1]; rows=[]
for f in sorted(glob.glob(S+'/npz/*.npz')):
    z=np.load(f); vs=z['vs']; vb,vr,vc,sw=vs[:,6],vs[:,7],vs[:,8],vs[:,13]
    m=vc>3
    if m.sum(): rows.append((os.path.basename(f)[:-4],'bag',m.sum(),vc[m].max(),(vc>vb+0.3).sum()))
for f in sorted(glob.glob('logs/*/*.csv'))+sorted(glob.glob(S+'/dec/*.csv')):
    nm=os.path.basename(f)[:-4]
    try: d=pd.read_csv(f,usecols=['V_bus','V_chg','V_rgn'])
    except Exception: continue
    m=d.V_chg>3
    if m.sum(): rows.append((nm,'blg',m.sum(),d.V_chg[m].max(),(d.V_chg>d.V_bus+0.3).sum()))
print(pd.DataFrame(rows,columns=['log','k','n_chg','vchg_max','n_above_bus']).to_string())

import pandas as pd,numpy as np,glob,os
from scipy import signal
R='/home/user/DC-Balancer-Board-Teensy/'; S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/'
pl=pd.read_csv('perlog.csv')
def bp(x,lo,hi,fs):
    sos=signal.butter(2,[lo,hi],btype='band',fs=fs,output='sos'); return signal.sosfiltfilt(sos,x)
def analyze(t,b,r,I,lo,hi,blk=20.0):
    fs=1/np.median(np.diff(t))
    # resample to uniform grid
    tu=np.arange(t[0],t[-1],1/fs)
    b=np.interp(tu,t,b); r=np.interp(tu,t,r); I=np.interp(tu,t,I)
    bb,rr,ii=[bp(x,lo,hi,fs) for x in (b,r,I)]
    n=int(blk*fs); nb=len(bb)//n
    if nb<2: return None
    g=[];gj=[];gI=[]
    for k in range(nb):
        s=slice(k*n,(k+1)*n); B,Rr,II=bb[s],rr[s],ii[s]
        g.append(np.dot(B,Rr)/np.dot(B,B))
        c=np.linalg.lstsq(np.c_[B,II],Rr,rcond=None)[0]; gj.append(c[0]); gI.append(c[1])
    # global
    G=np.dot(bb,rr)/np.dot(bb,bb); cj=np.linalg.lstsq(np.c_[bb,ii],rr,rcond=None)[0]
    corr=np.corrcoef(bb,rr)[0,1]
    # bootstrap of block means
    gj=np.array(gj); 
    return dict(G=G,Gj=cj[0],gI_mVA=cj[1]*1e3,corr=corr,sd_b_mV=bb.std()*1e3,nblk=nb,
                Gj_blk_mean=gj.mean(),Gj_sem=gj.std(ddof=1)/np.sqrt(nb))
rows=[]
for _,p in pl.iterrows():
    n=p.log
    if p.dur_s<30: continue
    c=R+f'logs/{n}/{n}.csv'
    if not os.path.exists(c): c=S+'dec/'+n+'.csv'
    d=pd.read_csv(c,usecols=['t_us','V_bus','V_rgn','I_fc','I_batt']).dropna()
    t=(d.t_us.values-d.t_us.values[0])*1e-6
    for lo,hi in [(0.1,2),(0.5,5)]:
        a=analyze(t,d.V_bus.values,d.V_rgn.values,(d.I_fc+d.I_batt).values,lo,hi,blk=10)
        if a: rows.append(dict(src=n,band=f'{lo}-{hi}',ratio=p.ratio,**a))
for f in sorted(glob.glob(S+'npz/*.npz')):
    z=np.load(f); vs=z['vs']; t=z['vs_t']
    b=vs[:,6];r=vs[:,7];I=vs[:,2]+vs[:,5]
    m=(b>15)&(b<18.5)&(r>10)&(r<b)
    # take longest contiguous connected run
    idx=np.where(m)[0]
    if len(idx)<1000: continue
    brk=np.where(np.diff(idx)>1)[0]; segs=np.split(idx,brk+1); s=max(segs,key=len)
    if len(s)<1000: continue
    for lo,hi in [(0.1,2),(0.5,5)]:
        a=analyze(t[s],b[s],r[s],I[s],lo,hi,blk=10)
        if a: rows.append(dict(src=os.path.basename(f)[7:-4],band=f'{lo}-{hi}',ratio=np.median(r[s]/b[s]),**a))
T=pd.DataFrame(rows); T.to_csv('incall.csv',index=False)
pd.set_option('display.width',250);pd.set_option('display.max_rows',300)
print(T.to_string(float_format=lambda x:f'{x:.3f}'))

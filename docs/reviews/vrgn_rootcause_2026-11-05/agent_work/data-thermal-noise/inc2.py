import pandas as pd,numpy as np,glob,os,sys
from scipy import signal
R='/home/user/DC-Balancer-Board-Teensy/'; S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/'
pl=pd.read_csv('perlog.csv')
LO,HI=0.1,3.0
def blocks(t,b,r,I,clean,fs,blk=10.0):
    sos=signal.butter(2,[LO,HI],btype='band',fs=fs,output='sos')
    out=[]
    n=int(blk*fs)
    # contiguous clean runs
    idx=np.where(clean)[0]
    if len(idx)==0: return out
    brk=np.where(np.diff(idx)>1)[0]
    for s in np.split(idx,brk+1):
        if len(s)<n+int(4*fs): continue
        B,Rr,II=[signal.sosfiltfilt(sos,x[s]) for x in (b,r,I)]
        e=int(2*fs); B,Rr,II=B[e:-e],Rr[e:-e],II[e:-e]   # trim filter edges
        # high-freq noise variance for Deming
        for k in range(len(B)//n):
            sl=slice(k*n,(k+1)*n)
            bb,rr,ii=B[sl],Rr[sl],II[sl]
            if bb.std()<1e-3: continue
            ols=np.dot(bb,rr)/np.dot(bb,bb)
            c=np.linalg.lstsq(np.c_[bb,ii],rr,rcond=None)[0]
            rev=np.dot(rr,rr)/np.dot(bb,rr)
            out.append((ols,c[0],c[1],rev,np.corrcoef(bb,rr)[0,1],bb.std()))
    return out
allr=[]
def summarize(name,o):
    if not o: return
    a=np.array(o); good=a[a[:,4]>0.9]
    if len(good)==0: 
        print(f'{name:40s} blocks {len(a)} none with corr>0.9'); return
    m=np.median(good[:,1]); 
    print(f'{name:40s} blocks {len(a):3d} good {len(good):3d}  OLS med {np.median(good[:,0]):.3f}  joint med {m:.3f} (IQR {np.percentile(good[:,1],25):.3f}-{np.percentile(good[:,1],75):.3f})  rev med {np.median(good[:,3]):.3f}  gI med {np.median(good[:,2])*1e3:.1f} mV/A  sd_b med {np.median(good[:,5])*1e3:.1f} mV')
    allr.append((name,len(good),np.median(good[:,0]),m,np.median(good[:,3])))
for _,p in pl.iterrows():
    n=p.log
    if p.dur_s<14: continue
    c=R+f'logs/{n}/{n}.csv'
    if not os.path.exists(c): c=S+'dec/'+n+'.csv'
    d=pd.read_csv(c,usecols=['t_us','V_bus','V_rgn','I_fc','I_batt','I_cmd']).dropna()
    t=(d.t_us.values-d.t_us.values[0])*1e-6
    fs=1/np.median(np.diff(t)); tu=np.arange(t[0],t[-1],1/fs)
    b=np.interp(tu,t,d.V_bus.values); r=np.interp(tu,t,d.V_rgn.values); I=np.interp(tu,t,(d.I_fc+d.I_batt).values); ic=np.interp(tu,t,d.I_cmd.values)
    bad=(ic<0)|(np.abs(r-p.ratio*b)>0.25)|(b<15)
    k=int(3*fs); bad=np.convolve(bad,np.ones(2*k+1),'same')>0
    summarize(n,blocks(tu,b,r,I,~bad,fs,blk=10.0 if p.dur_s>=25 else 8.0))
for f in sorted(glob.glob(S+'npz/*.npz')):
    z=np.load(f); vs=z['vs']; t=z['vs_t']
    fs=50.0; tu=np.arange(t[0],t[-1],1/fs)
    b,r,I,v=[np.interp(tu,t,x) for x in (vs[:,6],vs[:,7],vs[:,2]+vs[:,5],vs[:,0])]
    m=(b>15)&(r>10)&(r<b)
    if m.sum()<500: continue
    rat=np.median(r[m]/b[m])
    bad=(~m)|(np.abs(r-rat*b)>0.25)
    k=int(3*fs); bad=np.convolve(bad,np.ones(2*k+1),'same')>0
    summarize(os.path.basename(f)[7:-4],blocks(tu,b,r,I,~bad,fs))
pd.DataFrame(allr,columns=['src','ngood','ols','joint','rev']).to_csv('inc2.csv',index=False)

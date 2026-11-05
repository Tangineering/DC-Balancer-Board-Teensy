import numpy as np,glob,os
S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/npz/'
for f in sorted(glob.glob(S+'*.npz')):
    d=np.load(f); t=d['vs_t']; v=d['vs']; n=os.path.basename(f)[7:-4]
    sw=v[:,13].astype(int); vr=v[:,7]
    off=((sw&4)==0)
    if off.sum()<20: continue
    # contiguous segments
    idx=np.where(off)[0]; segs=np.split(idx,np.where(np.diff(idx)>1)[0]+1)
    for s in segs:
        if len(s)<20: continue
        i0=s[0]
        print(n,'seg t=%.2f..%.2f N=%d sw=%s err=%s vr %.3f->%.3f vb %.3f->%.3f; prev sample vb=%.3f vr=%.3f sw=%d'%(t[s[0]],t[s[-1]],len(s),set(sw[s]),set(v[s,15]),vr[s[0]],vr[s[-1]],v[s[0],6],v[s[-1],6],v[i0-1,6] if i0>0 else -1,vr[i0-1] if i0>0 else -1,sw[i0-1] if i0>0 else -1))
        tt=t[s]; vv=vr[s]
        # local slope in bins of reading
        edges=np.array([14,12,10,8,7,6,5,4.5,4,3.6,3.3,3.1,2.9,2.6,2.3,2.0,1.7,1.4,1.1,0.8,0.5])
        out=[]
        for a,b in zip(edges[:-1],edges[1:]):
            m=(vv<a)&(vv>=b)
            if m.sum()<4: continue
            p=np.polyfit(tt[m],vv[m],1)
            out.append('%.1f-%.1f:%.3fV/s,tau%.1f'%(a,b,p[0],-np.mean(vv[m])/p[0] if p[0]<0 else np.inf))
        print('    ',' | '.join(out))

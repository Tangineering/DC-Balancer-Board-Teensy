import numpy as np,glob,os
S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/npz/'
for f in sorted(glob.glob(S+'*.npz')):
    d=np.load(f); t=d['vs_t']; v=d['vs']; n=os.path.basename(f)[7:-4]
    sw=v[:,13].astype(int)
    idx=np.where((sw&8)>0)[0]
    if len(idx)==0: continue
    print(n)
    shown=set()
    for i in idx:
        for j in range(max(0,i-2),min(len(t),i+3)):
            if j in shown: continue
            shown.add(j)
            print('   t=%.2f sw=%2d vb=%.3f vr=%.3f vc=%.3f Ichg=%.3f Ifc=%.2f Ib=%.2f v=%.2f err=%d r_b=%.4f r_c=%.4f'%(t[j],sw[j],v[j,6],v[j,7],v[j,8],v[j,3],v[j,5],v[j,2],v[j,0],v[j,15],v[j,7]/max(v[j,6],1e-3),v[j,7]/max(v[j,8],1e-3)))

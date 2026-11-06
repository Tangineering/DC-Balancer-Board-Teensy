import numpy as np,glob,os,collections
S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/npz/'
for f in sorted(glob.glob(S+'*.npz')):
    d=np.load(f); t=d['vs_t']; v=d['vs']; n=os.path.basename(f)[7:-4]
    sw=v[:,13].astype(int); vb=v[:,6]; vr=v[:,7]; vc=v[:,8]
    mot=(sw&4)>0; rg=(sw&8)>0; fcc=(sw&16)>0
    c=collections.Counter(sw).most_common(6)
    lowq=mot&(vb<15.3)&(vb>1)
    # regen: REGEN closed and V_rgn > 1.0*V_bus*0.86+0.3 (elevated)
    base=np.median(vr[mot&(vb>15.5)]/vb[mot&(vb>15.5)]) if (mot&(vb>15.5)).any() else np.nan
    burst=rg&mot&(vr>base*vb+0.5)
    print(n,'N',len(t),'sw',c,'ratio16 %.4f'%base,'motlow',lowq.sum(),'regen-closed',rg.sum(),'burst&REGEN',burst.sum(),'mot-off&vr>0.5',((~mot)&(vr>0.5)).sum(), 'err',np.unique(v[:,15]))
    if burst.any():
        for i in np.where(burst)[0][:40]:
            print('    t=%.2f sw=%d vb=%.3f vr=%.3f vc=%.3f Ichg=%.3f Ifc=%.2f Ib=%.2f vr/vc=%.4f'%(t[i],sw[i],vb[i],vr[i],vc[i],v[i,3],v[i,5],v[i,2],vr[i]/max(vc[i],1e-3)))
    if lowq.any():
        for i in np.where(lowq)[0][:15]:
            print('    LOW t=%.2f sw=%d vb=%.3f vr=%.3f vc=%.3f r=%.4f err=%d'%(t[i],sw[i],vb[i],vr[i],vc[i],vr[i]/vb[i],v[i,15]))

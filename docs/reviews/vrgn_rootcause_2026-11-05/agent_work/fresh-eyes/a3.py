import numpy as np, glob
for f in sorted(glob.glob('npz/*.npz')):
    z=np.load(f); vs=z['vs']; t=z['vs_t']
    vb=vs[:,6]; vr=vs[:,7]; sw=vs[:,13].astype(int)
    mot=(sw&0x04)>0
    # samples with MOT_PWR set and Vbus in 3..15 and quasi-static (|dVb| small)
    dvb=np.abs(np.gradient(vb))
    m=mot&(vb>2)&(vb<15.2)&(dvb<0.05)
    m2=mot&(vb>15.2)
    if m.sum()>0 or True:
        print(f[4:40], 'n',len(vb),'mot&lowbus quasi',m.sum(), 'ratio hi %.4f'%np.median(vr[m2]/vb[m2]) if m2.sum() else '', end=' ')
        if m.sum():
            vbs=vb[m]; r=vr[m]/vb[m]
            for lo,hi in [(2,6),(6,9),(9,12),(12,14),(14,15.2)]:
                k=(vbs>=lo)&(vbs<hi)
                if k.sum(): print('[%g-%g]n%d r%.3f'%(lo,hi,k.sum(),np.median(r[k])),end=' ')
        print()

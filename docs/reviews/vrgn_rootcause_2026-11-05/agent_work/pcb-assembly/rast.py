import numpy as np, sys
from scipy import ndimage as ndi
from render import layer_mask
x0,y0,x1,y1,ppm=100,14,120,50,100
for fn in ['copper_top.gbr','copper_bottom.gbr']:
    m=np.array(layer_mask(fn,x0,y0,x1,y1,ppm))>0
    lab,n=ndi.label(m)
    def L(x,y): return lab[int((y1-y)*ppm), int((x-x0)*ppm)]
    pts={'RGN trace x114.366 y30':(114.366,30),'R2-SNT tap pad':(112.268,18.997),'U-SNT pad2':(114.366,22.54),'U-SNT pad3':(115.316,20.64),
         'U-SNT pad1':(116.266,22.54),'R1-SNT Vmot pad':(113.284,17.272),'Teensy p39 approx':(104.902,48.006),'J2 35':(107.442,48.006),'J2 36':(109.982,48.006),'CHG trace':(110.0,41.656),
         'pour x116 y30':(116.0,30),'pour x112.5 y30':(112.5,30),'x110 y44':(110,44.2)}
    print('==',fn,n)
    for k,(x,y) in pts.items(): print('  %-22s label %d'%(k,L(x,y)))
    rg=L(114.366,30)
    if rg:
        comp=lab==rg
        dt=ndi.distance_transform_edt(~comp)/ppm
        # nearest other copper
        other=m & ~comp
        d=np.where(other,dt,np.inf)
        idx=np.unravel_index(np.argmin(d),d.shape)
        print('  RGN comp pixels',comp.sum(),' min gap to other copper %.3f mm at x=%.2f y=%.2f label %d'%(d[idx],x0+idx[1]/ppm,y1-idx[0]/ppm,lab[idx]))
        # gaps per neighbouring label
        for l in np.unique(lab[other & (dt<1.0)]):
            print('    neighbour label %d min gap %.3f mm, size %d px'%(l,dt[(lab==l)].min(),(lab==l).sum()))

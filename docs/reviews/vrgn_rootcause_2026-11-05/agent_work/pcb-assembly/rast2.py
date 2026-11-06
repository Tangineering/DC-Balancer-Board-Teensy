import numpy as np
from scipy import ndimage as ndi
from render import layer_mask
x0,y0,x1,y1,ppm=68,2,120,52,50
res={}
for fn in ['copper_top.gbr','copper_bottom.gbr']:
    m=np.array(layer_mask(fn,x0,y0,x1,y1,ppm))>0
    lab,n=ndi.label(m)
    L=lambda x,y: lab[int(round((y1-y)*ppm)), int(round((x-x0)*ppm))]
    seeds={'RGN-V':[(114.366,30),(104.902,48.006),(107.442,48.006),(109.982,48.006)],
           'CHG-V':[(110.0,41.656),(104.902,45.466),(107.442,45.466),(109.982,45.466),(73.4065,5.842),(80.0,21.8),(73.87878,6.893),(96.266,31.496)]}
    for net,ss in seeds.items():
        labs=set(L(x,y) for x,y in ss)-{0}
        big=np.bincount(lab.ravel()); labs={l for l in labs if big[l]<200000}  # drop pour
        comp=np.isin(lab,list(labs))
        other=m&~comp
        dt=ndi.distance_transform_edt(~other)/ppm
        edge=comp & ~ndi.binary_erosion(comp)
        g=dt[edge]
        print(fn,net,'labels',labs,'area mm2 %.2f'%(comp.sum()/ppm**2),'edge px',edge.sum(),'min gap %.3f'%g.min(),
              'edge length within 0.25mm of other copper: %.1f mm'%((g<0.25).sum()/ppm), 'within 0.5: %.1f mm'%((g<0.5).sum()/ppm))

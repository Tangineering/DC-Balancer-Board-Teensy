import xml.etree.ElementTree as ET, math
import numpy as np
from gerbonara import GerberFile
from gerbonara.utils import MM
r=ET.parse("/home/user/DC-Balancer-Board-Teensy/references/Scale Car Board PCB 20260625.brd").getroot()
def segs(name):
    out=[]
    for s in r.iter('signal'):
        if s.get('name')==name:
            for w in s.iter('wire'):
                if w.get('layer')=='1': out.append(tuple(float(w.get(k)) for k in ('x1','y1','x2','y2','width')))
    return out
def pdist(px,py,x1,y1,x2,y2):
    dx,dy=x2-x1,y2-y1; L=dx*dx+dy*dy
    t=0 if L==0 else max(0,min(1,((px-x1)*dx+(py-y1)*dy)/L))
    return math.hypot(px-x1-t*dx,py-y1-t*dy)
D="/home/user/DC-Balancer-Board-Teensy/references/PCB Manufacturing Files/"
for fn in ['copper_top.gbr']:
    g=GerberFile.open(D+fn)
    regions=[]
    for o in g.objects:
        for p in o.to_primitives(MM):
            if type(p).__name__=='ArcPoly': regions.append((p.polarity_dark,np.array(p.outline)))
    for net in ['RGN-V','CHG-V']:
        S=segs(net)
        best=[]
        for k,(dark,pts) in enumerate(regions):
            if not dark: continue
            # min distance region outline vertices/edges to trace centerline minus half width
            dmin=1e9
            # sample edges
            n=len(pts)
            for i in range(n):
                a=pts[i]; b=pts[(i+1)%n]
                for t in np.linspace(0,1,6):
                    px,py=a+(b-a)*t
                    for (x1,y1,x2,y2,w) in S:
                        d=pdist(px,py,x1,y1,x2,y2)-w/2
                        if d<dmin: dmin=d
            best.append((dmin,k,len(pts),pts[:,0].min(),pts[:,0].max(),pts[:,1].min(),pts[:,1].max()))
        best.sort()
        print(net)
        for b in best[:6]: print('  gap %.3f mm region %d npts %d bbox x %.1f-%.1f y %.1f-%.1f'%b)

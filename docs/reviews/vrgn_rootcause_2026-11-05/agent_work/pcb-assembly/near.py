import xml.etree.ElementTree as ET, math, sys
r=ET.parse("/home/user/DC-Balancer-Board-Teensy/references/Scale Car Board PCB 20260625.brd").getroot()
# polygons
for s in r.iter('signal'):
    for p in s.iter('polygon'):
        xs=[float(v.get('x')) for v in p.iter('vertex')]; ys=[float(v.get('y')) for v in p.iter('vertex')]
        print('POLY',s.get('name'),'L',p.get('layer'),'iso',p.get('isolate'),'rank',p.get('rank'),'bbox %.1f-%.1f x %.1f-%.1f'%(min(xs),max(xs),min(ys),max(ys)))

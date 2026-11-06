import xml.etree.ElementTree as ET, sys
r=ET.parse(sys.argv[1]).getroot()
els={e.get('name'):e for e in r.iter('element')}
for n in ['J2','J1','U$1']:
    e=els.get(n); print(n, e.attrib if e is not None else None)
for s in r.iter('signal'):
    if s.get('name') in ('RGN-V','CHG-V','N$36','GND','VG'):
        if s.get('name')=='GND':
            print('GND has U-SNT:', [c.attrib for c in s.iter('contactref') if c.get('element') in ('U-SNT','R2-SNT','R2-CHG','U$1','J2')])
            continue
        print('==',s.get('name'))
        for w in s.iter('wire'): print(' wire',w.get('x1'),w.get('y1'),w.get('x2'),w.get('y2'),'L',w.get('layer'),'w',w.get('width'))
        for v in s.iter('via'): print(' via',v.attrib)
# J2 package pads
for lib in r.iter('library'):
    for p in lib.iter('package'):
        if p.get('name')==els['J2'].get('package') and lib.get('name')==els['J2'].get('library'):
            pads=[(x.get('name'),x.get('x'),x.get('y')) for x in list(p.iter('pad'))+list(p.iter('smd'))]
            print('J2 pkg',p.get('name'),len(pads),pads[:6])

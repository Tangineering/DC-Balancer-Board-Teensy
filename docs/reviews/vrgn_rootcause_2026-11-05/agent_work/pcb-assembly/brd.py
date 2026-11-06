import xml.etree.ElementTree as ET, sys
f=sys.argv[1]
t=ET.parse(f); r=t.getroot()
els={e.get('name'):e for e in r.iter('element')}
for n in ['U-SNT','R1-SNT','R2-SNT','R-G','R-GS','Z-SNT','Q-SNT','R1-CHG','R2-CHG','U$1','R-SHUNT']:
    e=els.get(n)
    if e is not None: print(n, {k:e.get(k) for k in ['library','package','value','x','y','rot']})
# packages
for lib in r.iter('library'):
    for p in lib.iter('package'):
        if p.get('name') in ('DBZ0003A_N',):
            print('LIB',lib.get('name'))
            for s in p.iter('smd'): print(' smd',s.attrib)
# signals touching
want=set(['U-SNT','R1-SNT','R2-SNT','R-G','R1-CHG','R2-CHG','Z-SNT','R-GS','Q-SNT'])
for s in r.iter('signal'):
    crs=[(c.get('element'),c.get('pad')) for c in s.iter('contactref')]
    if any(c[0] in want for c in crs):
        nw=len(list(s.iter('wire'))); nv=len(list(s.iter('via')))
        print('SIG',s.get('name'),crs if len(crs)<15 else crs[:15]+['...%d'%len(crs)],'wires',nw,'vias',nv)

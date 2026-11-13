import sys, math, xml.etree.ElementTree as ET
def rot_of(s):
    s=s or "R0"; return "M" in s, float(s.replace("M","").replace("S","").replace("R","") or 0)
def xf(px,py,ex,ey,rot):
    m,a=rot_of(rot)
    if m: px=-px
    a=math.radians(a); return ex+px*math.cos(a)-py*math.sin(a), ey+px*math.sin(a)+py*math.cos(a)
b=ET.parse(sys.argv[1]).getroot().find("drawing/board")
pk={}
for lib in b.find("libraries"):
    p=lib.find("packages")
    if p is None: continue
    for q in p: pk[(lib.get("name"),q.get("name"))]=q
want=set(sys.argv[2].split(","))
for e in b.find("elements"):
    if e.get("name") not in want: continue
    ex,ey,rot=float(e.get("x")),float(e.get("y")),e.get("rot","R0")
    p=pk[(e.get("library"),e.get("package"))]
    per={}
    for g in p:
        L=g.get("layer"); pts=[]
        if g.tag in("wire","rectangle"): pts=[xf(float(g.get("x1")),float(g.get("y1")),ex,ey,rot),xf(float(g.get("x2")),float(g.get("y2")),ex,ey,rot)]
        elif g.tag=="circle":
            cx,cy=xf(float(g.get("x")),float(g.get("y")),ex,ey,rot); r=float(g.get("radius")); w=float(g.get("width") or 0)/2; pts=[(cx-r-w,cy-r-w),(cx+r+w,cy+r+w)]
        elif g.tag=="pad":
            cx,cy=xf(float(g.get("x")),float(g.get("y")),ex,ey,rot); d=float(g.get("diameter") or 0) or float(g.get("drill"))+0.8; L="pad"; pts=[(cx-d/2,cy-d/2),(cx+d/2,cy+d/2)]
        elif g.tag=="polygon":
            pts=[xf(float(v.get("x")),float(v.get("y")),ex,ey,rot) for v in g.findall("vertex")]
        if g.tag=="wire": 
            w=float(g.get("width") or 0)/2; pts=[(x+s*w,y+t*w) for x,y in pts for s in(-1,1) for t in (-1,1)]
        if pts: per.setdefault(L,[]).extend(pts)
    print(e.get("name"), e.get("package"), "origin", ex, ey, rot)
    for L,pts in sorted(per.items()):
        xs=[q[0] for q in pts]; ys=[q[1] for q in pts]
        print("   layer %-4s x %.3f..%.3f  y %.3f..%.3f" % (L,min(xs),max(xs),min(ys),max(ys)))

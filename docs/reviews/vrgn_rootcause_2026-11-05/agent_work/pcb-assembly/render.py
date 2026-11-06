import sys, math
from gerbonara import GerberFile
from gerbonara.utils import MM
from PIL import Image, ImageDraw
D="/home/user/DC-Balancer-Board-Teensy/references/PCB Manufacturing Files/"
def layer_mask(fn, x0,y0,x1,y1, ppm):
    W=int((x1-x0)*ppm); H=int((y1-y0)*ppm)
    im=Image.new('L',(W,H),0); d=ImageDraw.Draw(im)
    T=lambda x,y: ((x-x0)*ppm, (y1-y)*ppm)
    g=GerberFile.open(D+fn)
    for o in g.objects:
        for p in o.to_primitives(MM):
            col=255 if getattr(p,'polarity_dark',True) else 0
            n=type(p).__name__
            if n=='Line':
                d.line([T(p.x1,p.y1),T(p.x2,p.y2)],fill=col,width=max(1,int(round(p.width*ppm))))
                r=p.width/2*ppm
                for (x,y) in ((p.x1,p.y1),(p.x2,p.y2)):
                    cx,cy=T(x,y); d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=col)
            elif n=='Circle':
                cx,cy=T(p.x,p.y); r=p.r*ppm; d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=col)
            elif n=='Rectangle':
                c,s=math.cos(p.rotation),math.sin(p.rotation)
                pts=[]
                for dx,dy in ((-1,-1),(1,-1),(1,1),(-1,1)):
                    ux,uy=dx*p.w/2,dy*p.h/2
                    pts.append(T(p.x+ux*c-uy*s, p.y+ux*s+uy*c))
                d.polygon(pts,fill=col)
            elif n=='ArcPoly':
                pts=[T(x,y) for x,y in p.outline]
                if len(pts)>2: d.polygon(pts,fill=col)
            else:
                print('skip',n)
    return im
if __name__=='__main__':
    x0,y0,x1,y1,ppm,out=float(sys.argv[1]),float(sys.argv[2]),float(sys.argv[3]),float(sys.argv[4]),float(sys.argv[5]),sys.argv[6]
    top=layer_mask('copper_top.gbr',x0,y0,x1,y1,ppm)
    bot=layer_mask('copper_bottom.gbr',x0,y0,x1,y1,ppm)
    silk=layer_mask('silkscreen_top.gbr',x0,y0,x1,y1,ppm)
    W,H=top.size
    rgb=Image.new('RGB',(W,H),(0,0,0))
    px=rgb.load(); t=top.load(); b=bot.load(); s=silk.load()
    for j in range(H):
        for i in range(W):
            r=g=bl=0
            if b[i,j]: bl=200
            if t[i,j]: r=220; g=60
            if s[i,j]: r=g=bl=255
            px[i,j]=(r,g,bl)
    d=ImageDraw.Draw(rgb)
    # grid every 1mm label every 5mm
    for xm in range(int(x0),int(x1)+1):
        X=(xm-x0)*ppm
        d.line([(X,0),(X,4 if xm%5 else 12)],fill=(0,255,0))
        if xm%5==0: d.text((X+2,12),str(xm),fill=(0,255,0))
    for ym in range(int(y0),int(y1)+1):
        Y=(y1-ym)*ppm
        d.line([(0,Y),(4 if ym%5 else 12,Y)],fill=(0,255,0))
        if ym%5==0: d.text((14,Y-5),str(ym),fill=(0,255,0))
    rgb.save(out)
    top.save(out.replace('.png','_top.png')); bot.save(out.replace('.png','_bot.png'))

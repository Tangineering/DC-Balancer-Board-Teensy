import sys
from render import layer_mask
from PIL import Image, ImageDraw, ImageOps
x0,y0,x1,y1,ppm,out=[float(a) for a in sys.argv[1:6]]+[sys.argv[6]]
ims=[]
for fn,lab in (('copper_top.gbr','TOP Cu'),('copper_bottom.gbr','BOT Cu'),('soldermask_top.gbr','TOP mask openings'),('silkscreen_top.gbr','TOP silk')):
    m=layer_mask(fn,x0,y0,x1,y1,ppm).convert('RGB')
    d=ImageDraw.Draw(m)
    for xm in range(int(x0)+1,int(x1)+1):
        X=(xm-x0)*ppm; d.line([(X,0),(X,m.size[1])],fill=(0,90,0) if xm%5 else (0,200,0))
        if xm%5==0: d.text((X+2,2),str(xm),fill=(0,255,0))
    for ym in range(int(y0)+1,int(y1)+1):
        Y=(y1-ym)*ppm; d.line([(0,Y),(m.size[0],Y)],fill=(0,90,0) if ym%5 else (0,200,0))
        if ym%5==0: d.text((2,Y+2),str(ym),fill=(0,255,0))
    d.text((m.size[0]-110,m.size[1]-14),lab,fill=(255,255,0))
    ims.append(m)
W,H=ims[0].size
o=Image.new('RGB',(2*W+6,2*H+6),(80,80,80))
for k,m in enumerate(ims): o.paste(m,((k%2)*(W+6),(k//2)*(H+6)))
o.save(out)

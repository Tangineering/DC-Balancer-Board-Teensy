import sys, numpy as np
from PIL import Image
im = np.asarray(Image.open(sys.argv[1]).convert('RGB')).astype(int)
sat = np.max(im,2)-np.min(im,2); v=im.mean(2)
gray = (sat<40)&(v>110)
sub = gray[60:840]
cols = sub.mean(0)
xs = np.where(cols>0.85)[0]; print('cols>0.85', xs.min(), xs.max())
for t in (0.5,0.7):
    xs=np.where(cols>t)[0]; print(t, xs.min(), xs.max())
rowsub = gray[:, 210:640].mean(1)
for t in (0.5,0.7,0.85):
    ys=np.where(rowsub>t)[0]; print('rows',t, ys.min(), ys.max())
# profile around edges
print('cols 190-202', [round(c,2) for c in cols[190:203]]); print('cols 643-656',[round(c,2) for c in cols[643:657]])
print('rows 47-58',[round(c,2) for c in rowsub[47:58]]); print('rows 838-850',[round(c,2) for c in rowsub[838:851]])
# outline yellow precise
r,g,b=im[...,0],im[...,1],im[...,2]; yel=(r>150)&(g>150)&(b<120)
for c in range(34,44): print('ycol',c,yel[:,c].sum())
for c in range(1220,1230): print('ycol',c,yel[:,c].sum())
for rr in list(range(12,19))+list(range(900,908)): print('yrow',rr,yel[rr].sum())

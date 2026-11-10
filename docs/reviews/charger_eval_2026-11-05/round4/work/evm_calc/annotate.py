"""Overlay the vector-extracted EVM points (evm_geom.py) and the round-3 px reads on the 300-dpi render of SLUUCB5E Fig 4-1.
usage: python -I annotate.py <p300-15.png> <out.png>"""
import sys
from PIL import Image, ImageDraw
SX, SY = 4.054921, 4.067717          # pt/mm (evm_geom.py)
L, B = 4.73398, 26.7621              # board outline lower-left in form pt (p.15)
K = 300 / 72                          # px per pt at 300 dpi
def px(xm, ym):
    fx, fy = xm * SX + L, ym * SY + B
    return ((fx + 123.0) * K, (792 - (fy + 294.3)) * K)
P = {"J1 VIN1": (6.604, 50.799), "J1 PGND": (6.604, 55.879), "J5 BATTERY": (82.487, 24.193), "J5 BATP": (82.487, 29.273),
     "J5 PGND": (82.487, 34.353), "J7 EXT_TS": (62.894, 6.223), "J7 AGND": (66.394, 6.223), "J8-1": (15.494, 5.954),
     "J8-4": (23.114, 5.954), "TP27": (26.670, 80.009), "TP33": (80.011, 63.499), "TP36": (55.874, 19.710),
     "TP38": (66.041, 59.689), "TP41": (30.480, 21.589), "TP49": (83.440, 79.120), "JP12-1": (39.370, 13.741),
     "JP13-1": (67.438, 67.309), "JP14-2": (71.375, 64.769), "JP17-1": (54.611, 26.796), "JP21-1": (75.312, 64.769),
     "JP21-2": (75.312, 67.309), "L2": (47.372, 53.212), "U1": (47.499, 42.036)}
R3 = {"TP49": (970, 308), "TP33": (941, 441), "JP21 pin1 (r3)": (902, 408), "JP14-2": (869, 432), "TP38": (822, 474),
      "TP27": (490, 300), "JP12": (598, 862), "TP36": (740, 812), "JP17": (727, 752)}
im = Image.open(sys.argv[1]).convert('RGB'); d = ImageDraw.Draw(im)
for n, (x, y) in P.items():
    X, Y = px(x, y); d.ellipse((X - 9, Y - 9, X + 9, Y + 9), outline=(220, 0, 0), width=3)
    d.text((X + 11, Y - 22), n, fill=(220, 0, 0))
for n, (x, y) in R3.items():
    X, Y = x * 2, y * 2; d.line((X - 8, Y - 8, X + 8, Y + 8), fill=(0, 90, 220), width=3); d.line((X - 8, Y + 8, X + 8, Y - 8), fill=(0, 90, 220), width=3)
x0, y0 = px(0, 0); x1, y1 = px(88.9, 88.9)
d.rectangle((x0, y1, x1, y0), outline=(0, 160, 0), width=2)
d.text((x0 + 4, y0 + 6), "origin (0,0) EVM frame, +x right, +y up; red = vector positions; blue x = round-3 reads", fill=(0, 120, 0))
im.crop((int(x0 - 40), int(y1 - 40), int(x1 + 40), int(y0 + 160))).save(sys.argv[2])

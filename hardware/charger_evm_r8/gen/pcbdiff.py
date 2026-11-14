"""Compare two KiCad boards by net name: segments (layer, net, width, endpoints), vias, footprints and zones.

Usage (from the repo root or hardware/charger_evm_r8): python gen/pcbdiff.py <rev>:<path> WT:<path>
  <rev>:<path>  a board at a git revision, e.g. 547dc11^:hardware/charger_evm_r8/cr/cr.kicad_pcb
  WT:<path>     a board in the working tree
Used to measure the post-generation edits in RESPIN_HANDOFF_2026-11-13.md and to check that a rebuilt board keeps them.
"""
import re, sys, math, subprocess, collections
def load(spec):
    if spec.startswith('WT:'):
        return open(spec[3:], encoding='utf-8').read()
    return subprocess.run(['git','show',spec],capture_output=True,text=True,encoding='utf-8').stdout
def top_objs(txt):
    objs=[]; depth=0; start=None; i=0; n=len(txt); instr=False
    while i<n:
        c=txt[i]
        if instr:
            if c=='\\': i+=2; continue
            if c=='"': instr=False
        elif c=='"': instr=True
        elif c=='(':
            depth+=1
            if depth==2: start=i
        elif c==')':
            if depth==2: objs.append(txt[start:i+1])
            depth-=1
        i+=1
    return objs
def parse(spec):
    t=load(spec); o=top_objs(t)
    nets={}; segs={}; vias={}; other=collections.Counter(); fps={}; zones={}
    for s in o:
        k=re.match(r'\((\w+)',s).group(1)
        if k=='net':
            m=re.match(r'\(net (\d+) "(.*)"\)',s); nets[m.group(1)]=m.group(2)
        elif k in('segment','arc'):
            st=re.search(r'\(start ([-\d.]+) ([-\d.]+)\)',s).groups(); en=re.search(r'\(end ([-\d.]+) ([-\d.]+)\)',s).groups()
            w=re.search(r'\(width ([\d.]+)\)',s).group(1); L=re.search(r'\(layer "([^"]+)"\)',s).group(1)
            net=re.search(r'\(net (\d+|"[^"]*")\)',s).group(1)
            net=nets.get(net,net)
            key=(k,L,net,w)+tuple(sorted([tuple(map(float,st)),tuple(map(float,en))]))
            segs[key]=segs.get(key,0)+1
        elif k=='via':
            at=tuple(map(float,re.search(r'\(at ([-\d.]+) ([-\d.]+)\)',s).groups()))
            sz=re.search(r'\(size ([\d.]+)\)',s).group(1); net=re.search(r'\(net (\d+|"[^"]*")\)',s).group(1)
            net=nets.get(net,net); vias[(at,net,sz)]=1
        elif k=='footprint':
            ref=re.search(r'\(property "Reference" "([^"]*)"',s).group(1)
            at=re.search(r'\(at ([-\d. ]+)\)',s).group(1)
            fpid=re.match(r'\(footprint "([^"]*)"',s).group(1)
            # hash without uuids/tstamps
            body=re.sub(r'\(uuid "[^"]*"\)','',s)
            fps[ref]=(at, fpid, hash(body))
        elif k=='zone':
            nm=re.search(r'\(name "([^"]*)"\)',s); nn=re.search(r'\(net_name "([^"]*)"\)',s)
            lay=re.search(r'\(layers? ([^)]*)\)',s).group(1)
            key=(nm.group(1) if nm else '', nn.group(1) if nn else '', lay)
            poly=re.search(r'\(polygon\s*\(pts(.*?)\)\s*\)',s,re.S).group(1)
            body=re.sub(r'\(filled_polygon.*','',s,flags=re.S)
            zones[key]=(hash(poly), hash(body), hash(s))
        else:
            body=re.sub(r'\(uuid "[^"]*"\)','',s)
            other[hash(body)]+=1; other[('kind',k)]+=1
    return nets,segs,vias,fps,zones,other
a,b=sys.argv[1],sys.argv[2]; yf=float(sys.argv[3]) if len(sys.argv)>3 else 100
A=parse(a);B=parse(b)
def nn(nets,x): return nets.get(x,x.strip('"'))
def L(k): return math.dist(k[4],k[5])
rem=[k for k in A[1] if k not in B[1]]; add=[k for k in B[1] if k not in A[1]]
per=collections.defaultdict(lambda:[0,0.0,0,0.0,set(),[]])
for k in rem: p=per[nn(A[0],k[2])]; p[0]+=1; p[1]+=L(k); p[4].add(k[1]+'-'); p[5].append(k)
for k in add: p=per[nn(B[0],k[2])]; p[2]+=1; p[3]+=L(k); p[4].add(k[1]+'+'); p[5].append(k)
print(f"segments: A {sum(A[1].values())} B {sum(B[1].values())}; removed {len(rem)} added {len(add)}")
print(f"track length A {sum(L(k)*v for k,v in A[1].items()):.1f} B {sum(L(k)*v for k,v in B[1].items()):.1f}")
print("net | removed n/len | added n/len | layers | bbox(kicad)")
for n,p in sorted(per.items()):
    xs=[c[0] for k in p[5] for c in (k[4],k[5])]; ys=[c[1] for k in p[5] for c in (k[4],k[5])]
    ws=sorted(set(k[3] for k in p[5]))
    print(f"{n} | {p[0]}/{p[1]:.2f} | {p[2]}/{p[3]:.2f} | {' '.join(sorted(p[4]))} | x{min(xs):.2f}-{max(xs):.2f} y{min(ys):.2f}-{max(ys):.2f} | w{','.join(ws)}")
vr=[k for k in A[2] if k not in B[2]]; va=[k for k in B[2] if k not in A[2]]
print(f"vias: A {len(A[2])} B {len(B[2])}; removed {len(vr)} added {len(va)}")
for tag,lst,nets in (('-',vr,A[0]),('+',va,B[0])):
    for (at,net,sz) in sorted(lst,key=lambda x:(nn(nets,x[1]),x[0])):
        print(f" {tag} via {nn(nets,net)} kicad({at[0]:.3f},{at[1]:.3f}) mb({at[0]:.3f},{yf-at[1]:.3f}) d{sz}")
fpc=[r for r in set(A[3])|set(B[3]) if A[3].get(r)!=B[3].get(r)]
print("footprints changed:",len(fpc))
for r in sorted(fpc):
    a_=A[3].get(r); b_=B[3].get(r)
    print(" ",r, a_[:2] if a_ else 'absent','->', b_[:2] if b_ else 'absent', '(body changed)' if a_ and b_ and a_[:2]==b_[:2] else '')
zc=[z for z in set(A[4])|set(B[4]) if A[4].get(z)!=B[4].get(z)]
print("zones changed:",len(zc))
for z in sorted(zc):
    a_=A[4].get(z); b_=B[4].get(z)
    st='absent-before' if not a_ else 'absent-after' if not b_ else ('outline-changed' if a_[0]!=b_[0] else 'settings-changed' if a_[1]!=b_[1] else 'fill only')
    print("  ",z,st)
ka={k:v for k,v in A[5].items() if isinstance(k,tuple)}; kb={k:v for k,v in B[5].items() if isinstance(k,tuple)}
diffo=sum(1 for k in A[5] if not isinstance(k,tuple) and k not in B[5])+sum(1 for k in B[5] if not isinstance(k,tuple) and k not in A[5])
print("other kinds A",ka," B",kb," other objs differing:",diffo)

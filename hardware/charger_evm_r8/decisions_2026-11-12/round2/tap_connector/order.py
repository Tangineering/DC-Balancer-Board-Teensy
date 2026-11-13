import itertools, sys
C=['T1','T7b','T2','T5','T6','T10','T13','T16','T17','T17r']
GND={'T7b','T17r','G'}
def k(a,b): return frozenset((a,b))
HARD={k('T5','T6'),k('T10','T6'),k('T5','T10'),k('T1','T5'),k('T2','T5'),k('T1','T10'),k('T2','T10')}
cost={}
def s(a,b,c): cost[k(a,b)]=c
for g in GND:
  s('T6',g,3); s('T17',g,3); s('T13',g,1); s('T16',g,1); s('T5',g,1); s('T10',g,1); s('T2',g,0.5); s('T1',g,0.5)
s('T17','T17r',0); s('T1','T7b',0)
for x in ('T1','T2'):
  s(x,'T13',2); s(x,'T16',3); s(x,'T17',1); s(x,'T6',1)
s('T1','T2',1)
s('T6','T16',3); s('T6','T13',2); s('T6','T17',1)
s('T17','T5',3); s('T17','T10',3); s('T17','T13',3); s('T17','T16',1)
s('T5','T13',2); s('T5','T16',1); s('T10','T13',2); s('T10','T16',1); s('T13','T16',2)
def pc(a,b):
  if 'NC' in (a,b): return 0
  if a in GND and b in GND: return 0
  return cost.get(k(a,b),None)
REQ=[('T1','T7b'),('T17','T17r')]
def grid(r,n):
  pos=[(i,j) for i in range(r) for j in range(n)]
  adj={p:[q for q in pos if abs(p[0]-q[0])+abs(p[1]-q[1])==1] for p in pos}
  return pos,adj
def solve(r,n,spares):
  pos,adj=grid(r,n)
  items=C+['S']*spares
  best=[None]; sols=[]
  assign={}
  def partial(p,it):
    add=[]
    for q in adj[p]:
      if q in assign:
        o=assign[q]
        if k(it,o) in HARD: return None
        add.append((it,o))
    return add
  res=[]
  def rec(i,remaining,score):
    if i==len(pos):
      # required adjacency
      inv={v:p for p,v in assign.items()}
      for a,b in REQ:
        if inv[b] not in adj[inv[a]]: return
      # spares: choose NC or G per spare greedily (NC always <= G except never better) -> NC
      res.append((score,dict(assign)))
      return
    p=pos[i]
    for it in sorted(set(remaining)):
      ad=partial(p,it)
      if ad is None: continue
      sc=list(score)
      ok=True
      for a,b in ad:
        if 'S' in (a,b): continue
        c=pc(a,b)
        if c is None: print('missing',a,b); sys.exit()
        if c>=3: sc[0]+=1
        sc[1]+=c
      if best[0] and tuple(sc)>best[0]: continue
      assign[p]=it; rem=list(remaining); rem.remove(it)
      before=len(res)
      rec(i+1,rem,sc)
      if len(res)>before:
        b=min(r_[0] for r_ in res[before:]);
        if best[0] is None or tuple(b)<best[0]: best[0]=tuple(b)
      del assign[p]
  rec(0,items,[0,0])
  if not res: return None,[]
  b=min(tuple(x[0]) for x in res)
  return b,[x[1] for x in res if tuple(x[0])==b]
def show(r,n,a):
  return '\n'.join('  '+' '.join(f"{a[(i,j)]:>5}" for j in range(n)) for i in range(r))
for (r,n,sp) in [(2,5,0),(2,6,2),(1,10,0),(1,11,1),(1,12,2)]:
  b,sols=solve(r,n,sp)
  print(f"== {r}x{n} spares {sp}: best (n_sev3, sum) = {b}, {len(sols)} optimal layouts (incl. mirrors)")
  if sols:
    print(show(r,n,sols[0]))
    # list sev3 pairs
    a=sols[0]; pos,adj=grid(r,n); seen=set()
    for p in pos:
      for q in adj[p]:
        e=frozenset((p,q))
        if e in seen: continue
        seen.add(e); x,y=a[p],a[q]
        if 'S' in (x,y): continue
        c=pc(x,y)
        if c and c>0: print('    pair',x,y,c)

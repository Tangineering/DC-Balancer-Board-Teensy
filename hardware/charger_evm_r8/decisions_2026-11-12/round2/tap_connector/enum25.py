exec(open('order.py').read().split("for (r,n,sp) in")[0])
import itertools
pos,adj=grid(2,5)
edges=sorted({frozenset((p,q)) for p in pos for q in adj[p]},key=sorted)
out={}
for perm in itertools.permutations(C):
  a=dict(zip(pos,perm)); inv={v:p for p,v in a.items()}
  if any(inv[b] not in adj[inv[x]] for x,b in REQ): continue
  bad=False; s3=0; s2=0; tot=0; pairs=[]
  for e in edges:
    p,q=sorted(e); x,y=a[p],a[q]
    if k(x,y) in HARD: bad=True; break
    c=pc(x,y); tot+=c
    if c>=3: s3+=1
    if c>=2: s2+=1
    if c>0: pairs.append((c,x,y))
  if bad: continue
  # canonical under symmetry (flip rows, flip cols)
  vs=[]
  for fr in (0,1):
    for fc in (0,1):
      vs.append(tuple(a[(r^fr, (4-c) if fc else c)] for r in range(2) for c in range(5)))
  key=min(vs)
  out[key]=(s3,s2,tot,sorted(pairs,reverse=True))
rank=sorted(out.items(),key=lambda kv:kv[1][:3])
print(len(out),'feasible layouts up to symmetry')
print("min sev>=2 count:",min(v[1] for v in out.values()), " min sev3:",min(v[0] for v in out.values())); print("layouts with sev>=2<=1:",sum(1 for v in out.values() if v[1]<=1))
for key,(s3,s2,tot,pairs) in rank[:0]:
  print(f"sev3={s3} sev>=2={s2} sum={tot}")
  print('  row A:',' '.join(f"{x:>5}" for x in key[:5])); print('  row B:',' '.join(f"{x:>5}" for x in key[5:]))
  print('  ', [(c,x+'-'+y) for c,x,y in pairs if c>=1])

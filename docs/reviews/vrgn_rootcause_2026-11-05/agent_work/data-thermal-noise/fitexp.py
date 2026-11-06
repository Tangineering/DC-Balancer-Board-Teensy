import numpy as np,pandas as pd
from scipy.optimize import least_squares
t=pd.read_csv('thermal2.csv'); pl=pd.read_csv('perlog.csv').set_index('log')
t['Iload']=t.log.map(pl.Imean)
B=[1,4,5,8,9,10,11,13,14]
g=t[t.boot.isin(B)].copy()
bi={b:i for i,b in enumerate(B)}
def res(p):
    A,tau=p[0],p[1]; a=p[2:]
    return g.Lref.values-(a[[bi[b] for b in g.boot]]+A*(1-np.exp(-g.t.values/tau)))
best=None
for tau0 in [2,5,10,20]:
    r=least_squares(res,[1,tau0]+[30]*len(B),bounds=([0,0.3]+[0]*len(B),[10,200]+[50]*len(B)))
    if best is None or r.cost<best.cost: best=r
p=best.x; J=best.jac; cov=np.linalg.inv(J.T@J)*(2*best.cost/(len(g)-len(p)))
print('A=%.3f+-%.3f uA, tau=%.2f+-%.2f min, rms resid %.3f uA'%(p[0],np.sqrt(cov[0,0]),p[1],np.sqrt(cov[1,1]),np.sqrt(2*best.cost/len(g))))
for b in B: print(' boot',b,'a=%.2f'%p[2+bi[b]],' A/a=%.2f%%'%(100*p[0]/p[2+bi[b]]))
g['resid']=res(p)
print('corr(resid, log mean load)=%.3f'%np.corrcoef(g.resid,g.Iload)[0,1])
c=np.polyfit(g.Iload,g.resid,1); print('resid slope vs load %.3f uA/A'%c[0])
# profile tau
for tau in [1,2,3,5,8,12,20,40]:
    r=least_squares(lambda q: res([q[0],tau]+list(q[1:])),[1]+[30]*len(B))
    print(' tau',tau,'A %.3f'%r.x[0],'rms %.4f'%np.sqrt(2*r.cost/len(g)))

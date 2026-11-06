import numpy as np,pandas as pd,os,sys
R='/home/user/DC-Balancer-Board-Teensy/logs/'; S='/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/'
def run(n,Imax):
    c=R+f'{n}/{n}.csv'
    if not os.path.exists(c): c=S+n+'.csv'
    d=pd.read_csv(c,usecols=['t_us','V_bus','V_rgn','I_fc','I_batt','I_cmd']).dropna()
    I=d.I_fc+d.I_batt
    rat=np.median(d.V_rgn/d.V_bus)
    m=(I<Imax)&(d.I_cmd>=0)&(d.V_bus>15.3)&(np.abs(d.V_rgn-rat*d.V_bus)<0.3)
    # exclude 3 s around any negative I_cmd
    neg=(d.I_cmd<0).values.astype(float); k=3000
    m&=np.convolve(neg,np.ones(2*k+1),'same')==0
    q=d[m]
    # smooth 50 ms to suppress quantization before binning
    g=q.groupby((q.V_bus*1000/4.545).round()).agg(Vb=('V_bus','mean'),Vr=('V_rgn','mean'),n=('V_rgn','size'),I=('I_fc','mean'))
    g=g[g.n>=200]
    if len(g)<3: print(n,'insufficient'); return
    w=np.sqrt(g.n)
    c=np.polyfit(g.Vb,g.Vr,1,w=w)
    # also regress on V_bus and I jointly per sample
    X=np.c_[q.V_bus,(q.I_fc+q.I_batt),np.ones(len(q))]; cj=np.linalg.lstsq(X,q.V_rgn,rcond=None)[0]
    print(f'{n} I<{Imax}: bins {len(g)} Vbus {g.Vb.min():.3f}-{g.Vb.max():.3f}  binned slope {c[0]:.3f}  joint(V_bus,I) slope {cj[0]:.3f} I-coef {cj[1]*1e3:.1f} mV/A  static ratio {rat:.4f}')
for n in sys.argv[1:]:
    for Im in (0.6,1.5,5):
        run(n,Im)

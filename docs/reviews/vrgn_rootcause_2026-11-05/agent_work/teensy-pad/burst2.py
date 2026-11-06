import pandas as pd, numpy as np, sys, os
for n in sys.argv[1:]:
    f=f'logs/{n}/{n}.csv'
    if not os.path.exists(f): f=f'/tmp/claude-0/-home-user-DC-Balancer-Board-Teensy/2dd4079b-96a3-52c6-9594-2aa3f1f11188/scratchpad/dec/{n}.csv'
    d=pd.read_csv(f,usecols=['t_us','V_bus','V_rgn'])
    t=d.t_us.values/1e6; vb=d.V_bus.values; vr=d.V_rgn.values
    k=np.argmax(vr); 
    # find the start: last index before k where vr < 0.85*vb+0.3
    base=np.nanmedian(vr[vb>14]/vb[vb>14])
    i=k
    while i>0 and vr[i]>base*vb[i]+0.3: i-=1
    j=k
    while j<len(vr)-1 and vr[j]>base*vb[j]+0.3: j+=1
    pre=vr[max(0,i-3000):i-100]/vb[max(0,i-3000):i-100]
    post=vr[j+1000:j+5000]/vb[j+1000:j+5000]
    print(f'{n}: peak rd {vr[k]:.3f} (node {vr[k]/8.87:.3f} V) at t={t[k]:.3f}; excursion {t[i]:.3f}-{t[j]:.3f}s; ratio pre {np.median(pre):.4f}, post(+1..5s) {np.median(post):.4f}; Vbus pre {np.median(vb[max(0,i-3000):i-100]):.3f} post {np.median(vb[j+1000:j+5000]):.3f}')
    seg=vr[i:j]; print('   max |step| in excursion', np.abs(np.diff(seg)).max().round(3), ' samples of node>1.70V:', int((seg/8.87>1.70).sum()))

import numpy as np
R1=78.7e3;R2=10e3;G=8.87
rows=np.load('jramp_rows.npy') # I,vb,vc,vr,vn,L0,L5,L1
q=dict(vb=15.9240,vc=15.8341,vr=13.4937)
coll=[(24.7258,13.199,12.266,11.794,4.09+6.36),(24.7269,9.736,8.556,8.721,2.01+8.27),(24.7281,6.990,5.897,6.412,0.01+15.26),(24.7292,6.836,5.761,6.347,16.46)]
def leak(vm,vn): return ((vm-vn)/R1 - vn/R2)*1e6
def node_from(vm,IL): return (vm/R1 - IL*1e-6)/(1/R1+1/R2)
for x in (0,0.25,0.5,0.75,1.0):
    vmq=q['vb']-x*(q['vb']-q['vc']); vnq=q['vr']/G; Lq=leak(vmq,vnq)
    print('x=%.2f quiescent Vm %.3f leak %.2f uA'%(x,vmq,Lq))
    # models predicting node reading given vm
    mods={}
    mods['const']=lambda vm: node_from(vm,Lq)
    mods['resist']=lambda vm: vm*vnq/vmq
    # exponential: fit Vs from ramp end bin
    I,vb,vc,vr,vn=rows[-1][:5]; vm=vb-x*(vb-vc); Le=leak(vm,vn)
    Vs=(vnq-vn)/np.log(Lq/Le) if Le>0 and Le<Lq else np.nan
    def expo(vm,Vs=Vs):
        # solve vn: vn = node_from(vm, Lq*exp((vn-vnq)/Vs))
        v=vm/G
        for _ in range(200): v=0.5*v+0.5*node_from(vm,Lq*np.exp((v-vnq)/Vs))
        return v
    mods['exp(Vs=%.3f)'%Vs]=expo
    # power law
    n=np.log(Lq/Le)/np.log(vnq/vn) if Le>0 else np.nan
    def powl(vm,n=n):
        v=vm/G
        for _ in range(200): v=0.5*v+0.5*node_from(vm,Lq*(max(v,1e-6)/vnq)**n)
        return v
    mods['pow(n=%.2f)'%n]=powl
    for name,f in mods.items():
        rr=[ (f(r[1]-x*(r[1]-r[2]))-r[4])*G for r in rows]
        cc=[ (f(b-x*(b-c))-vr/G)*G for (_,b,c,vr,_) in coll]
        print('   %-16s ramp resid(reading V) max|.|=%.3f  collapse resid: %s'%(name,np.max(np.abs(rr)),' '.join('%+.3f'%c for c in cc)))
    # resistive + ground-shift gamma fitted on ramp
    A=np.array([[r[0]] for r in rows]); y=np.array([r[4]-(r[1]-x*(r[1]-r[2]))*vnq/vmq for r in rows])
    gam=np.linalg.lstsq(A,y,rcond=None)[0][0]
    rr=(A[:,0]*gam-y)*G
    cc=[ ((b-x*(b-c))*vnq/vmq + gam*I - vr/G)*G for (_,b,c,vr,I) in coll]
    print('   resist+gnd(gamma=%.2f mOhm) ramp max|.|=%.3f collapse resid: %s'%(gam*1e3,np.max(np.abs(rr)),' '.join('%+.3f'%c for c in cc)))

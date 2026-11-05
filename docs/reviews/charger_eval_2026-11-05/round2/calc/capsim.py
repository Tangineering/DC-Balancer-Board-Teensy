"""Regen capture model: VESC (H-V: over-voltage cut + 0.53 s fault stop, measured) + V-MOT node + charger.
All constants cited in regen_dynamics.md."""
import numpy as np
M=3.5; FC=2.0; B=0.534; KF=0.7538; RPH=0.0226; ETA_G=0.90; ETA_INV=0.97
V_BUS=15.9; V_OV=21.35; T_FAULT=0.53; V_TL=22.13; R_SH=47.0
SINK_SLOPE=17.0      # V/s measured post-cut decay -> I_q = C*17
I_MOT=12.0; T_IRAMP=0.005; I_REGEN_MAX=1.5
ETA_CHG=0.90; V_PACK=8.4
def pe(I,v): return max(0.0,(KF*I*v*ETA_G-1.5*I*I*RPH)*ETA_INV)
def run(v0=2.0,v1=1.0,C=0.97e-3,Vth=19.0,tau=0.005,Iceil=2.5,mode='warm',L=0.0,ideal=False,
        ireg_max=I_REGEN_MAX,dt=2e-5,T=2.5,trace=False,imot=I_MOT):
    V=V_BUS; v=v0; a=0.0; t=0.0; fault_until=-1; ov=0; on_time=None
    Ep=0.0; Eel=0.0; Esh=0.0; Eq=0.0; Vmax=V; ipk=0.0; tb=0.0; braking=True
    Iq=C*SINK_SLOPE; tr=[]
    Pin_max=Iceil*V_PACK/ETA_CHG
    while t<T:
        # VESC
        I=0.0
        if braking and v>v1 and t>=fault_until:
            I=imot*min(1.0,t/T_IRAMP)
            P=pe(I,v)
            if P>ireg_max*V:   # battery-side regen limit: reduce I
                # solve (KF v ETA_G) I - 1.5 R I^2 = ireg*V/ETA_INV, smaller root
                aa=1.5*RPH; bb=KF*v*ETA_G; cc=ireg_max*V/ETA_INV
                disc=bb*bb-4*aa*cc; I=(bb-np.sqrt(max(disc,0)))/(2*aa); P=pe(I,v)
        elif v<=v1: braking=False
        P=pe(I,v) if I>0 else 0.0
        iv=P/V
        F=KF*I + (FC+B*v)
        v=max(0.0,v-F/M*dt)
        if I>0: tb+=dt
        # charger capability
        if ideal:
            ich=max(0.0,iv-Iq); 
        else:
            powered = (mode=='warm') or (on_time is not None and t>=on_time)
            if mode=='cold' and on_time is None and V>V_BUS+0.3: on_time=t+L
            amax=Pin_max/V
            if powered and V>Vth-1e-3 : a+= (amax-a)*dt/tau
            elif powered: a+= (0-a)*dt/(tau*20)   # slow idle decay of a warm loop
            a=min(a,amax)
            if not powered: ich=0.0
            else:
                need=max(0.0,iv-Iq+C*(V-Vth)/1e-3)   # VINDPM loop: pull node to Vth in ~1 ms
                ich=min(a,need)
        ish=min(10*(V-V_TL),V/R_SH) if V>V_TL else 0.0
        dV=(iv-Iq-ich-ish)/C*dt
        V+=dV
        if (not ideal) and V<Vth and ich>0 and V+1e-9<Vth and iv-Iq>0: pass
        if V<V_BUS: V=V_BUS          # MOT_PWR ideal diode: bus props the node up
        if ideal and V>V_BUS: V=V_BUS+0.0  # ideal sink holds node
        if (not ideal) and V>=V_OV and t>=fault_until:
            fault_until=t+T_FAULT; ov+=1
        Ep+=ETA_CHG*ich*V*dt; Eel+=P*dt; Esh+=ish*V*dt
        Vmax=max(Vmax,V); ipk=max(ipk,ETA_CHG*ich*V/V_PACK)
        if trace and int(t/dt)%25==0: tr.append((t,V,v,iv,ich,I))
        t+=dt
        if not braking and v<=v1 and t>tb+0.8: break
    return dict(Ep=Ep,Eel=Eel,Esh=Esh,ov=ov,Vmax=Vmax,ipk=ipk,tb=tb,Q=Ep/V_PACK,v_end=v,tr=np.array(tr))

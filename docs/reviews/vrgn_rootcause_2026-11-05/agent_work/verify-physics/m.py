import numpy as np
R1,R2=78.7e3,10e3
def leak(vm,vn): return (vm-vn)/R1-vn/R2
print('leak@15.93 node1.522', leak(15.93,1.522)*1e6,'uA')
# incremental gain for slope R
for R in (9.3e3,16.5e3):
  g=1/R; print(R,'gain', (1/R1)/(1/R1+1/R2+g)*(R1+R2)/R2)
# TP0178 two points
v1,i1,v2,i2=1.286,9.0e-6,1.497,32.7e-6
Rs=(v2-v1)/(i2-i1); print('TP0178 chord R',Rs,'Von',v1-i1*Rs)
# diode dynamic resistance contribution for 2 junctions at 20uA, n=1
print('2Vt/I at 20uA',2*0.02585/20e-6)
# trip extrapolation linear
Von,R=1.22,9.3e3
vn=2.495; print('linear trip', vn+R1*(vn/R2+(vn-Von)/R))
for vn in (2.04,2.06): print('reading',vn*(R1+R2)/R2,'true linear',vn+R1*(vn/R2+(vn-Von)/R))
# Darlington-path model: two diodes (Is fit) + 10.15k, then Q_b clamps at 0.6 V across 10k

import sys
src=open(sys.argv[1]).read().split('\nfor Vin')[0]
ns={}; exec(src,ns)
for a in [(18.53,8.4,3.25),(18.53,7.4,3.25),(21.5,8.4,3.25),(15.57,8.4,1.6)]:
    e,P,Iin,L=ns['loss'](*a,f=1050e3)
    print(a, f"eta {e*100:.1f} loss {P:.2f} Iin {Iin:.3f}", {k:round(v,3) for k,v in L.items() if k in('Q1sw','gate_LDO','dead')})
# NTC worst case
for VDD in (4.5,5.5):
  Rpu=47e3; Rs=10e3
  print(VDD, VDD*Rs/(Rpu+Rs)+270e-6*(Rs*Rpu/(Rs+Rpu)), "VIL", VDD-1.2)
print("far side", 270e-6*10e3)
for q in (15e-9,8e-9): print(q, q/165e-6*1e6, q/15e-6*1e3)

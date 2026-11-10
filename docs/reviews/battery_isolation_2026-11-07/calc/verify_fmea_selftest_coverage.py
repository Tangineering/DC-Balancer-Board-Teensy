"""Verifier recompute: injection self-test coverage of U_C1/U_C2/D5 (DD Fig. 3, sec 9.3). Stdlib only."""
V=3.3; MID=1.65; K=0.05  # INA240A3 x 0.5 mOhm = 50 mV/A (DD Fig.3 / Table 7)
par=lambda a,b:a*b/(a+b)
RT2a,RT2b,RI2=10e3,12.1e3,1e3
print("TH2 nominal %.4f V -> trip %.2f A"%(V*RT2b/(RT2a+RT2b),(V*RT2b/(RT2a+RT2b)-MID)/K))
print("TH2 injected, healthy: %.3f V"%(V*par(RT2b,RI2)/(RT2a+par(RT2b,RI2))))
print("TH2 injected, R_T2b open: %.3f V (< SIG2 1.65 -> passes); in service TH2 = 3.300 V > swing 3.10 V"%(V*RI2/(RT2a+RI2)))
print("R_T2b 20k: TH2 %.3f V -> %.2f A"%(V*20/30,(V*20/30-MID)/K))
RF1,RI1=1.5e3,1e3
s=MID*RI1/(RF1+RI1); print("SIG1 injected %.3f V -> passes for any trip up to %.1f A"%(s,(MID-s)/K))
print("D5 R_D5c open: IN+ = %.2f V vs 50.1 mV nominal; BT-CURR at 0.1 V/A needs %.0f A"%(V,V/0.1))
for vin in (16.0,21.47):
  p=2.16*vin; print("eFuse I_OL max 2.16 A at %.2f V: %.1f W in -> %.2f A into 7.4 V pack (eta 0.88)"%(vin,p,p*0.88/7.4))

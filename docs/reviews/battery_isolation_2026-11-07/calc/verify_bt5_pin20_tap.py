"""Verifier recompute for finding 'VC1 tap on pin 20 vs 80 mV ERR_CELL_MISMATCH budget'.
Sources: detailed_design_IC1.md rev 7 lines 354/861/2006/2598 (200k/200k, 41.5 mV worst healthy, 80 mV threshold);
IMXRT1060CEC Rev.4 Table 22 (IIN +/-1 uA, R_keeper 105-175k) as quoted by the finding (not in repo: TODO(verify));
Teensy core 1.62.0 cores/teensy4/analog.c lines 111-119: analogRead() clears PKE when PKE=1, PUE=0."""
R_th = 200e3*200e3/400e3
print(f"R_th = {R_th/1e3:.0f} kOhm")
vth = 3.7/2
for rk in (105e3, 175e3):
    lo = vth*rk/(rk+R_th); hi = vth + (3.3-vth)*R_th/(rk+R_th)
    print(f"keeper {rk/1e3:.0f}k (moot after first analogRead): LOW {1e3*(lo-vth):+.0f} mV, HIGH {1e3*(hi-vth):+.0f} mV")
sens = 2*2*R_th   # V_mismatch per A of pin current: x2 tap gain, x2 in formula
print(f"mismatch sensitivity = {sens*1e-6:.2f} V/uA")
margin = 80e-3 - 41.5e-3
print(f"margin {1e3*margin:.1f} mV -> tolerable uncalibrated leakage drift {margin/sens*1e9:.0f} nA")
print(f"IIN spec 1 uA -> {sens*1e-6*1e3:.0f} mV (x{sens*1e-6/margin:.1f} margin)")
# buffered fix: follower offset e.g. 1 mV -> x2 in V_VC1 -> x2 in formula
for vos in (0.5e-3, 1e-3, 3e-3):
    print(f"buffer Vos {1e3*vos:.1f} mV drift -> mismatch {4*vos*1e3:.1f} mV")
# alternative minimal fix: lower divider impedance, e.g. 20k/20k (10k Thevenin)
for r in (20e3, 10e3):
    rt = r/2; i_vc1 = 4.25/(2*r)
    print(f"divider {r/1e3:.0f}k/{r/1e3:.0f}k: Rth {rt/1e3:.0f}k, 1 uA -> {4*rt*1e-6*1e3:.0f} mV; VC1 load {i_vc1*1e6:.0f} uA")

"""Verifier calc: MS sense wire shorted to SHDN_EF (fmea round 4 finding).
Sources: DD rev 6 Figure 2 (R_SD 1k, R_MS1 100k, R_MS2 16.2k), Figure 6 (R_SDP 22k),
TLV3011B REF 1.242 V; ERR_VCHG_SENSE row (pin 8 HIGH, V_chg < 8 V, 3 iterations);
ic1_rev6_calcs_output s7 (3 iterations = 3.39 ms median); RT1987 t_D_ON 8 ms typ (DD 1090);
D-BC-RG/FC ramp 12 V/ms (DD 1090); R_MD 15 ohm; C_mod 100-221 uF; VCHG-IN bleed tau 0.984 s."""
import math
G = 1/1e3 + 1/22e3 + 1/16.2e3 + 1/100e3
print("S1 joined node (ignoring SHDN -10 uA)")
for ef in (3.3, 0.0):
    for vm in (0, 9, 16, 21.5):
        v = (ef/1e3 + vm/100e3)/G
        print(f"  EF_EN {ef:.1f} V node {vm:5.1f} V -> {v:.3f} V, U_MS {'HIGH' if v>1.242 else 'LOW'}")
print("S2 ERR_VCHG_SENSE rule (a) exposure while EF_EN H precedes the feed")
it_med = 3.39/3
for tdon in (3.0, 5.0, 8.0, 12.0):
    t8 = tdon + 8.0/12.0   # V_chg 0 -> 8 V at 12 V/ms
    print(f"  t_D_ON {tdon:4.1f} ms: pin8 HIGH & V_chg<8 V for {t8:5.2f} ms = {t8/it_med:4.1f} median iterations -> latch {'YES' if t8 >= 3.39 else 'NO'}")
print("  precondition: V_chg < 8 V at EF_EN rise. Unfed upper bound in DD = VBT 8.5 V via R_KA (UNCONFIRMED) -> rule cannot fire")
t = 0.984*math.log(16/8)
print(f"  residual after a 16 V window: VCHG-IN bleed to 8 V takes {t:.2f} s (tau 0.984 s)")
print("S3 healthy U_MS HIGH hold after the feed drop, with module still converting (constant-current approx)")
for C in (100e-6, 221e-6):
    for v0 in (13.5, 16.0, 21.5):
        for imod in (0.0, 0.71, 1.0):
            # integrate dV/dt = -(V/15 + V/3300 + imod)/C
            v, tt, dt = v0, 0.0, 1e-7
            while v > 9.15:
                v -= (v/15 + v/3300 + imod)/C*dt; tt += dt
            print(f"  C {C*1e6:4.0f} uF V0 {v0:4.1f} V I_mod {imod:.2f} A: HIGH for {tt*1e3:.3f} ms")

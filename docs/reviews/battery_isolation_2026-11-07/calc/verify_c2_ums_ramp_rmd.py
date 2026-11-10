"""Verify battle-test finding: C-2 U_MS threshold ramp on VCHG-IN_M with Q_MD on (EF_EN L).
Inputs: detailed_design_IC1.md section 5.3 schematic block (R_MD 15, R_MB 3.3k, R_MS1 100k, R_MS2 16.2k), Table 7."""
R_MD, R_MB, R_DIV = 15.0, 3300.0, 100e3 + 16.2e3
par = lambda *r: 1.0 / sum(1.0 / x for x in r)
Ron = par(R_MD, R_MB, R_DIV)
print("R_parallel dump on  = %.3f Ohm" % Ron)
print("threshold nominal   = %.3f V" % (1.242 * R_DIV / 16.2e3))
for v in (8.69, 9.15, 9.5):
    print("V=%.2f  I_src=%.3f A  P_RMD=%.2f W" % (v, v / Ron, v * v / R_MD))
E = 9.5 ** 3 / (3 * R_MD)  # linear ramp 0..9.5 V over 9.5 s: int (t)^2/R dt
print("ramp energy in R_MD = %.2f J ; x51mJ = %.0f ; x1.71J = %.1f" % (E, E / 0.051, E / 1.71))
for ilim in (0.1, 0.5):
    print("Ilim %.1f A -> node max %.3f V" % (ilim, ilim * Ron))
Roff = par(R_MB, R_DIV)
print("dump off: R=%.0f Ohm, I at 9.5 V = %.2f mA, P_RMB = %.1f mW" % (Roff, 9.5 / Roff * 1e3, 9.5 ** 2 / R_MB * 1e3))
print("dump off + Ag105 idle 18 mA max (DS p.20 row 4): %.1f mA at 9.5 V" % (9.5 / Roff * 1e3 + 18))

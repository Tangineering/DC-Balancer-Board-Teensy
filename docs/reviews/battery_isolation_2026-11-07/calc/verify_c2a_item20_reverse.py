"""Verifier: C-2a item 20 reverse sense / F_VX stress (detailed_design_IC1.md F22b, Table 19 item 20, S0-9/S0-10, F_VX)."""
s0_10 = 17**2*0.5e-3
print("S0-10 I2t = %.4f A2s" % s0_10)
for i in (1, 3, 7):
    for t_it in (1.341e-3, 9.76e-3):
        t = t_it + 5e-3
        i2t = i*i*t
        print("I=%d A t=%.2f ms I2t=%.4f A2s  xS0-10=%.2f  xFVX_melt(3.152,UNVERIFIED)=%.3f  E_sense(R_s 0.074)=%.1f mJ  I/I_DIS=%.2f" % (
            i, t*1e3, i2t, i2t/s0_10, i2t/3.152, i*i*0.074*t*1e3, i/4.0))

#!/usr/bin/env python3
"""Load-scheduled droop-scale authority table and noise-to-jitter budget (2026-09-03).

Part 1: with g = K_DROOP / (RE_MAX r) <= 1 and the minority clip confining r to
[r_lo, 1 - r_lo], r_lo = max(DROOP_R_MIN, I_min / I_tot), the admissible droop
scale is k_d_max = RE_MAX * r_lo.  Prints the design-scale authority k_d * I_tot
today and scheduled, and the r = 0.5 disturbance term d = dV0 r(1-r)/(k_d I_tot).
(Table 4 of docs/modeling/low_current_share_stability_20260903.md.)

Part 2: measured per-channel current sigma -> raw share sigma -> r jitter through
a first-order closed loop at ~110 rad/s (noise-equivalent bandwidth wc/4 Hz out of
the 500 Hz Nyquist band) -> minority-current jitter.  The bound on what current
filtering can buy on SHARE_MINORITY_I_MIN_A.

Run (stdlib only):
    .venv_hil/Scripts/python.exe tools/probes/lowcurrent_droop_schedule_table.py
"""
import math

K_SNS, A_V, RD1_OVER_RINJ = 0.1, 5.02, 215.0 / 53.6     # .ino:2206-2216
RE_MAX = K_SNS * A_V * RD1_OVER_RINJ                     # 2.014 ohm
KD, IMIN, RMIN = 0.30, 0.30, 0.15
DV0 = 0.05                                               # CAL-1 adopted, V
WC_RAD_S, FS_HZ = 110.0, 1000.0                          # share-loop crossover, tick rate
# (I_tot, per-channel sigma) from lowcurrent_blg_noise.py sigma mode, campaign-era logs
MEASURED = ((0.25, 0.023), (0.5, 0.03), (0.7, 0.06), (1.0, 0.06), (1.5, 0.06))


def main():
    print(f"RE_MAX={RE_MAX:.3f} ohm; k_d_max = RE_MAX*r_lo(I_tot), r_lo = max({RMIN}, {IMIN}/I_tot)")
    print(" I_tot   r_lo   k_d_max  auth_now(V)  auth_sched(V)  gain   d_now(r=.5)  d_sched")
    for it in (0.6, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0):
        rlo = max(RMIN, IMIN / it)
        kmax = RE_MAX * rlo
        print(f" {it:4.1f}   {rlo:.3f}   {kmax:.3f}    {KD*it:.3f}        {kmax*it:.3f}      "
              f"{kmax/KD:.2f}x    {DV0*0.25/(KD*it):.3f}        {DV0*0.25/(kmax*it):.3f}")
    att = math.sqrt((WC_RAD_S / 4) / (FS_HZ / 2))
    print(f"\nloop noise attenuation (first-order T at {WC_RAD_S:.0f} rad/s): {att:.2f}")
    for it, sig in MEASURED:
        sig_alpha = sig * math.sqrt(2) / it * 0.5        # ratio noise at r ~ 0.5
        print(f"I_tot {it:.2f}: sigma_I {1e3*sig:.0f} mA -> sigma_alpha(raw) {sig_alpha:.3f} "
              f"-> sigma_r {sig_alpha*att:.4f} -> minority jitter {1e3*sig_alpha*att*it:.1f} mA rms")


if __name__ == "__main__":
    main()

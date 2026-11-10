"""Battle-test round 2, requirements/operability lens, IC1 detailed design revision 4.

Stdlib only. Every input is cited inline; nothing here is a new measurement.
Run: python bt2_requirements_operability.py
"""


def hdr(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78)


# ---------------------------------------------------------------------------
hdr("A. Regen-window open latency (design 9.5 + Table 11) against the first VESC pulse")
# [RER] arm: P_est >= 3.0 W for REGEN_ARM_DWELL_MS 40 ms (docs/regen_enable_redesign.md l.166, l.174;
# design Table 11 row 'Regen entry arm', ruling OR-V). P_est is computed from the COMMANDED current and
# v_actual ([RER] l.24), so with I_cmd railed at -12 A the arm starts at the I_cmd step.
ARM = 40.0
CONF = (2.26, 4.02)          # settled ladder confirmation, median / p99 incl. straddle (design 9.6, calc4 s4)
T_DON = 8.0                  # RT1987 t_D_ON typical, no max (design Table 11)
T_RAMP = 1.07                # D-BC-RG ramp to eFuse UVLO (design Table 11)
T_EF = 1.24 + 3.6            # eFuse turn-on + ramp to 18 V (design 7.5)
ONSET = 5.0                  # pulse onset within ~5 ms of I_cmd stepping negative (regen_dynamics.md 1.1)
for conf in CONF:
    t_in = ARM + conf + T_DON + T_RAMP + T_EF
    print(f"  confirmation {conf:.2f} ms: Ag105 input reaches 18 V at >= {t_in:5.1f} ms after the I_cmd step "
          f"(Ag105 start time NOT included)")
for rise in (19.0, 47.0):
    print(f"  first pulse rise {rise:.0f} ms: V-MOT peaks (VESC stop) at {ONSET + rise:5.1f} ms after the I_cmd step")
print("  -> pin 30 is not yet HIGH (>= 42.3 ms) when the 19-40 ms pulses end; no first pulse can be captured,")
print("     independent of the Ag105 cold-start result (S0-6) and of Stage 3.")

# ---------------------------------------------------------------------------
hdr("B. Share of capturable node energy in the first pulse (regen_dynamics.md section 1.1 table)")
VTH = 18.0   # Ag105 regen-profile threshold (design Table 5; Ag105 DS p.10 default)
events = {   # event: per-pulse peak V (regen_dynamics.md 1.1, events.json)
    "ML0151 41.36": [21.41, 21.33],
    "ML0157 47.30": [21.30, 21.25],
    "ML0165 22.64": [21.21],
    "ML0165 28.55": [21.29, 21.20],
    "ML0195 33.20": [21.42, 20.50],
    "YP0166 21.97": [21.32, 21.24, 20.94],
    "YP0196 21.97": [21.42, 20.62],
    "YP0198 21.98": [21.40, 17.87],
}
lost = []
for C_mF in (0.97, 4.0):
    C = C_mF * 1e-3
    print(f"  C = {C_mF} mF (node energy above {VTH} V per pulse, J; ideal instantaneous Ag105):")
    tot_all = tot_later = 0.0
    for ev, pk in events.items():
        e = [0.5 * C * max(v * v - VTH * VTH, 0.0) for v in pk]
        share1 = e[0] / sum(e)
        tot_all += sum(e)
        tot_later += sum(e[1:])
        if C_mF == 0.97:
            lost.append(share1)
        print(f"    {ev}: pulses {len(pk)}; E/pulse {', '.join(f'{x:.3f}' for x in e)}; "
              f"first-pulse share {100*share1:5.1f} %; reachable after the arm {sum(e[1:]):.3f} J")
    print(f"    all 8 events: {tot_all:.3f} J above 18 V; reachable after the arm {tot_later:.3f} J "
          f"({100*tot_later/tot_all:.1f} %)")
s = sorted(lost)
print(f"  first-pulse share: min {100*s[0]:.1f} %, median {100*(s[3]+s[4])/2:.1f} %, max {100*s[-1]:.1f} %; "
      f"events with zero reachable energy: {sum(1 for x in s if x >= 0.999)} of 8")
print("  Pi bag (fw <= v35): second pulses peak 16.8-19.0 V (regen_dynamics.md 1.1) -> 0-37 % of a first pulse")
print("  above 18 V; some sit below the 16.90-17.24 V VOK assert and never power the charger at all.")

# ---------------------------------------------------------------------------
hdr("C. FC window mean pack current per H-20 purge cycle with the fw v32a cooldown retained")
T_PURGE, D_PURGE = 10.34, 0.14          # facts_prior sec 7
GUARD_PRE = 0.30                        # bt1 calc D assumption (prediction +/-20 ms per edge), ASSUMED
COOLDOWN = 2.0                          # FC_CHG_COOLDOWN_MS 2000 (ino:2634), kept by design 12.4 item 6
ENTRY = 0.005 + 0.020                   # confirmation + BT decay wait max (design 9.7 steps 3, 5)
I_SET = 1.25
for lab, ts in (("cold start 0.065 s (R_KA)", 0.065), ("cold start 0.17 s (R_KA)", 0.17),
                ("Bring-Up 2->7.4 V at 0.64 V/s (no R_KA)", (7.4 - 2.0) / 0.64)):
    # window closes GUARD_PRE before the purge; cooldown runs from the close; reopen when cooldown ends
    t_chg = max(T_PURGE - GUARD_PRE - COOLDOWN - ENTRY - ts, 0.0)
    print(f"  {lab}: {t_chg:5.2f} s charging per {T_PURGE} s cycle -> mean {I_SET*t_chg/T_PURGE:.3f} A "
          f"(design 14.2 / bt1 calc D: about 1.14 A with R_KA)")
print("  Drive-cycle share: FC windows only in State 1 / State 98 (design 9.7, 12.2 item 2, OR-O); a UDDS run")
print("  is State 2 throughout (doState2 leaves only on changeToFin, ino:7955-7957) -> 0 % of the 333 s cycle.")

# ---------------------------------------------------------------------------
hdr("D. Change-set calibration from git (teensy_controller.ino, lines added / removed)")
hist = {
    "fw v28 (9318e16) + revs 2-6": [(603, 137), (364, 10), (220, 8), (152, 19), (302, 23), (275, 18)],
    "fw v37 rounds (db59fb7, e22e5cb, 95cc709)": [(816, 3), (288, 46), (169, 70)],
    "fw v37 rev 2 J guards (da0746c)": [(449, 12)],
}
for k, v in hist.items():
    a = sum(x for x, _ in v)
    r = sum(y for _, y in v)
    print(f"  {k}: +{a} / -{r}")
print("  fw v37 J session (one State-98 mode, 3 guards, latch) = ~1,250 added lines incl. review rounds;")
print("  IC1 = 7-state mode manager + 10-step self-test + ladder decode/EEPROM calibration + 14 faults +")
print("  watchdog round + purge predictor + Idle call site + telemetry v5 + BLG bump + State-98 keys.")

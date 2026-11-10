"""Completeness-critic calculations for detailed_design_IC1.md revision 6.

Every input is a value already stated in detailed_design_IC1.md (section cited per input) or in
teensy_controller/teensy_controller.ino (line cited). No new primary figure is introduced.
Run: python cc_completeness_calcs.py  (stdlib only)
"""

print("=" * 78)
print("Section 1. Idle-entry self-test duration (DD 9.3, Table 11, 7.7)")
print("=" * 78)
loop_med_ms, loop_p99_ms = 1.131, 1.341          # DD Table 11 (facts_firmware section 8)
hang_to_off = (43.0, 76.0)                       # DD 7.4 / Table 11 (calc section 4)
limit_off = 90.0                                 # DD 9.3 steps 2 and 8 wait limit
timed = {"step 2 run": 20.0, "step 2 static hold": 200.0, "step 3 restart": 20.0}
# Settled confirmations (two identical decodes each, DD 7.7): step 1 (1), 2 (1 after run),
# 4 (1), 4b (2), 6 (3), 7 (3), 8 (1), 9 (1), 10 (1) = 14 confirmations.
n_conf = 14
for label, off in (("typ (hang-to-off 43 ms)", hang_to_off[0]),
                   ("max (hang-to-off 76 ms)", hang_to_off[1]),
                   ("limit (90 ms waits)", limit_off)):
    for lname, it in (("median", loop_med_ms), ("p99", loop_p99_ms)):
        t = sum(timed.values()) + 2 * off + n_conf * 2 * it
        print(f"  {label:26s} loop {lname:6s}: {t:6.1f} ms")
print("  -> the 'about 430 ms' of DD 9.3 lies inside 357-458 ms; it had no calc citation.")

print()
print("=" * 78)
print("Section 2. U_MS positive-control deadline (DD 9.5 hold duties, Table 16 ERR_MOD_SENSE (b))")
print("=" * 78)
t_d_on = 8.0                      # ms, RT1987 typical, no maximum (DD 7.8, Table 11)
ramp_rg = 12.0                    # V/ms D-BC-RG ramp (DD 7.8, CSS 5.6 nF)
uvlo_on = (12.38, 12.88)          # V eFuse UVLO rising (DD 5.3, calc4 section 9)
ef_delay = 1.24                   # ms UVLO/SHDN turn-on (DD 7.5, calc section 5)
slew = (4.17, 5.79)               # V/ms eFuse output slew at C_DV 10 nF (DD 7.5)
ums_hi = (8.69, 9.15)             # V U_MS threshold (DD 5.3, calc6 section 4)
v_win = 13.5                      # V window floor / chargerHasPower level (DD 12.5 item 1)
t_13p5 = t_d_on + v_win / ramp_rg
t_uvlo_min = t_d_on + uvlo_on[0] / ramp_rg
t_uvlo_max = t_d_on + uvlo_on[1] / ramp_rg
t_pin8_min = t_uvlo_min + ef_delay + ums_hi[0] / slew[1]
t_pin8_max = t_uvlo_max + ef_delay + ums_hi[1] / slew[0]
print(f"  From VOK assert (EF_EN rise) at t_D_ON {t_d_on} ms:")
print(f"    V_chg reaches 13.5 V at           {t_13p5:6.2f} ms")
print(f"    module node reaches U_MS level at {t_pin8_min:6.2f} - {t_pin8_max:6.2f} ms")
lag = (t_pin8_min - t_13p5, t_pin8_max - t_13p5)
print(f"    lag from V_chg 13.5 V to pin 8 H:  {lag[0]:5.2f} - {lag[1]:5.2f} ms")
for ef_hi in (10.0, 11.0, 12.0):
    sees = ef_hi >= t_pin8_max
    print(f"  EF_EN H interval {ef_hi:4.1f} ms with V_chg >= 13.5 V from {t_13p5:.2f} ms: "
          f"pin 8 HIGH guaranteed = {sees}  -> rev-6 rule would {'not ' if sees else ''}latch ERR_MOD_SENSE")
print("  -> keyed on the EF_EN interval, the rev-6 rule false-latches on a VOK interval of 10 ms up to")
print(f"     about {t_pin8_max:.1f} ms at typical t_D_ON (later with a slower RT1987; t_D_ON has no maximum).")
print("     Keyed on the second settled V_chg >= 13.5 V read (t0), the worst lag is "
      f"{lag[1]:.2f} ms; a 10 ms span after t0")
print(f"     leaves {10.0 - lag[1]:.2f} ms, and with the 9.76 ms worst iteration at least one pin-8 read falls after t0 + {lag[1]:.2f} ms")
print("     whenever the span is >= 10 ms (two reads at most 9.76 ms apart inside it).")
t_vchg12 = t_d_on + 12.0 / ramp_rg
print(f"  ERR_VCHG_SENSE (b): V_chg passes 12 V at {t_vchg12:.2f} ms after EF_EN rise at t_D_ON 8 ms;")
print(f"     the 20 ms EF_EN-H window false-latches only if t_D_ON exceeds {20.0 - 12.0 / ramp_rg:.1f} ms (no RT1987 maximum; V2-0).")

print()
print("=" * 78)
print("Section 3. R_MD dissipation at the regen pulse cadence (DD 5.3 item 1, 14.4)")
print("=" * 78)
c_mod = (100e-6, 221e-6)          # F, DD 5.3 / calc6 section 3
v_node = 21.5                     # V, regen peak node
period = 0.535                    # s, regen pulse spacing (DD 14.4)
win_max = 30.0                    # s, regen window cap (DD 9.5)
for c in c_mod:
    e = 0.5 * c * v_node ** 2
    print(f"  C_mod {c*1e6:5.0f} uF: {e*1e3:5.1f} mJ per dump; mean {e/period:5.3f} W at one dump per "
          f"{period*1e3:.0f} ms; {e*win_max/period:5.2f} J per 30 s window ({int(win_max/period)} dumps)")
print("  -> R_MD needs a repetitive-pulse rating, not only the single 1.71 J probe pulse of Table 7.")

print()
print("=" * 78)
print("Section 4. LB load on the Teensy 3V3 rail, resistive part only (DD Figures 2-5, Table 7)")
print("=" * 78)
v33 = 3.3
pullups_10k = ["R_N1", "R_UC1", "R_UC2", "R_UD5", "R_UIM", "R_SG1", "R_SG2", "R_UP1", "R_UP2",
               "R_BP1", "R_BP2", "R_FLT", "R_UMS"]
i_pu = len(pullups_10k) * v33 / 10e3
dividers = {"R_T1a+R_T1b 22.0k": 22.0e3, "R_T2a+R_T2b 22.1k": 22.1e3, "R_IMa+R_IMb 69.0k": 69.0e3,
            "R_D5b+R_D5c 65.9k": 65.9e3, "R_INV 100k": 100e3, "R_V1 100k (pin 23 leg)": 100e3}
i_div = sum(v33 / r for r in dividers.values())
i_lad = 10 * 0.55e-3              # DD 7.7: about 0.55 mA per bit, 10 bits
total = i_pu + i_div + i_lad
print(f"  {len(pullups_10k)} x 10k pull-ups, all outputs LOW: {i_pu*1e3:5.2f} mA")
print(f"  threshold and bias dividers:          {i_div*1e3:5.2f} mA")
print(f"  ladders (10 bits x 0.55 mA):          {i_lad*1e3:5.2f} mA")
print(f"  resistive total (worst):              {total*1e3:5.2f} mA")
print("  IC quiescent currents (2 x INA240A3, 9 x TLV3011B, 17 LVC/AHCT gates, 2 x LVC244A) are not")
print("  stated in DD Table 7: TODO(verify: SBOS662C, SBOS300C, TI LVC datasheets). Budget reference:")
print("  PJRC 250 mA recommended maximum for external 3.3 V use (facts_board section 6.1), shared with")
print("  the existing SNS/MDAC/pull-up load, which is also not totalled in the study.")

print()
print("=" * 78)
print("Section 5. Fault-code space (DD Table 16; ino:2038-2058, ino:2440-2459)")
print("=" * 78)
new_faults = ["ERR_CHG_SELFTEST", "ERR_CHG_TRIP", "ERR_CHG_ENTRY", "ERR_CHG_EXIT", "ERR_CHG_LADDER",
              "ERR_SGND_OPEN", "ERR_SGND_DEGRADED", "ERR_RET_DEGRADED", "ERR_ISO_MISMATCH",
              "ERR_IPACK_XCHK", "ERR_AG105_CFG", "ERR_IPACK_PLAUS", "ERR_VCHG_FED", "ERR_VOK_STUCK",
              "ERR_VMOT_CAL", "ERR_PROFILE_OC", "ERR_BAL_ABSENT", "ERR_EFUSE_BYPASS", "ERR_MOD_FED",
              "ERR_MOD_SENSE", "ERR_MOD_DRAIN", "ERR_VCHG_SENSE", "ERR_PACKN_RANGE"]
used_flag_bits = 16               # FAULT_* 0x0001..0x8000 all assigned (ino:2038-2058)
last_err = 0x10                   # ERR_HIL_STALE (ino:2459)
print(f"  new IC1 fault conditions in Table 16: {len(new_faults)}")
print(f"  free bits in the 16-bit fault_flags word: {16 - used_flag_bits}")
print(f"  error_code values after 0x{last_err:02X}: 0x{last_err+1:02X}-0x{last_err+len(new_faults):02X} "
      f"(fits the uint8 field)")
print("  -> the IC1 faults need a new flag word (at least 23 bits, i.e. a uint32) in protocol v6.")

print()
print("=" * 78)
print("Section 6. Exit-side cold-module wait for the pin-5 and pin-10 writes (DD 9.5 exit, 12.4 item 2)")
print("=" * 78)
drain = (1.3, 2.9)                # ms dump 21.5 V to 9 V (calc6 section 3)
cold_hold = 20.0                  # ms, DD 12.4 item 2
for lname, it in (("median", loop_med_ms), ("p99", loop_p99_ms)):
    t_conf = 4 * it               # exit confirmation within 4 iterations (DD 7.7)
    t_p5 = drain[1] + cold_hold
    print(f"  loop {lname}: bonded confirmation at <= {drain[1] + 2*it + t_conf:5.1f} ms; "
          f"earliest legal pin-5/pin-10 write {t_p5:5.1f} ms after the feed drop")
print("  -> rev-6 exit step 5 (pin 5 LOW) and FC exit step 4 (pin 10, pin 5 LOW) come before the")
print("     20 ms cold condition of 12.4 item 2 holds; the writes are deferred, traction is not.")

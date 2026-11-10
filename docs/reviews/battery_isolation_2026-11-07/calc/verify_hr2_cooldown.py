"""Verification of battle-test finding 'HR2 overstated' (requirements lens): FC window mean current.
Stdlib only. FC_CHG_COOLDOWN_MS gates re-entry only after the FC_CHG_MAX_MS dwell close
(teensy_controller.ino:15473-15480 set fcChgLockout; ordinary closes at ino:15319 and ino:15522 set only
fcChgClosedMs), so a purge-predicted close is followed by no cooldown."""
T, D, I = 10.34, 0.14, 1.25          # facts_prior sec 7; FC profile 1.25 A (design 9.7 step 1)
PRE = POST = 0.30                    # bt1 calc D assumption
ENTRY = 0.025                        # design 9.7 steps 3 + 5 (5 ms + 20 ms max)
for lab, ts in (("cold 0.065", 0.065), ("cold 0.17", 0.17),
                ("Bring-Up 2->7.4 V", (7.4-2.0)/0.64), ("Bring-Up 2->8.4 V", (8.4-2.0)/0.64)):
    t_ok = max(T - D - PRE - POST - ENTRY - ts, 0.0)          # no cooldown (code as written)
    t_cd = max(T - PRE - 2.0 - ENTRY - ts, 0.0)               # bt2 model (cooldown, pre-guard)
    t_cd2 = max(T - 2.0 - ENTRY - ts, 0.0)                    # cooldown, pre-guard not double-counted
    print(f"{lab:18s} ts {ts:6.3f} s: no-cooldown {I*t_ok/T:.3f} A | bt2 {I*t_cd/T:.3f} A | "
          f"cooldown w/o double count {I*t_cd2/T:.3f} A")

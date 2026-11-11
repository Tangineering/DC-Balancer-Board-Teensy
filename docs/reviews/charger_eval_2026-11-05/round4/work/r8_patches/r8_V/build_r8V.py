"""Build the r8_V patch: apply every verification-round correction to an LF copy of the design in memory, then emit
line-block edits for round4/calc/apply_patches.py."""
import difflib
import json
import os
import re
import sys

DOC = r"C:/Life Ops/School/Thesis/DC-Balancer-round4/docs/charger_bq25798_wiring_design_2026-11-05.md"
OUTDIR = r"C:/Life Ops/School/Thesis/DC-Balancer-round4/docs/reviews/charger_eval_2026-11-05/round4/work/r8_patches/r8_V"
src = open(DOC, encoding="utf-8", newline="").read().replace("\r\n", "\n")
t = src
LOG = []


def R(old, new, n=1, tag=""):
    global t
    c = t.count(old)
    if c != n:
        sys.exit("[%s] count %d != %d for %r" % (tag, c, n, old[:100]))
    t = t.replace(old, new)
    LOG.append(tag)


# ------------------------------------------------------------------ CHG-R1-01
R('''so the switch follows its command (H.23(n)) (**superseded in r8:** "an asserted FLT sinks pin 30 without a series resistor, which pulls the REGEN EN net only toward off"; without R106s the FLT current is 18.4-45.6 mA with the 40 ohm driver and up to 96.2 mA with a 0 ohm driver, and the EN net sits at 1.48-2.65 V, so the switch also stayed as commanded, H.23(n))''',
  '''so the switch follows its command (H.23(n)); without R106s the FLT current would be 18.4-45.6 mA with the 40 ohm driver and up to 96.2 mA with a 0 ohm driver, with the EN net at 1.48-2.65 V, so the r7 switch also stayed as commanded (H.23(n)) (**superseded in r8:** "an asserted FLT sinks pin 30 without a series resistor, which pulls the REGEN EN net only toward off")''',
  tag="01 A.8 F05-F17 marker")
R('''| pins 35 and 16 read one level; an asserted FLT sinks U108 H2C through R127 and R106s (<= 1.719 mA, H.23(n)) (**superseded in r8:** "through R127 (<= 3.3 mA)", 3.377 mA without R106s) | readback plausibility (FR-08/FR-44) |''',
  '''| r8: with FLT released, pins 35 and 16 read the U108 H2C level; with FLT asserted and U108 H2C HIGH, the node sits at 1.60-1.93 V through R127 and R106s, inside the i.MX undefined band (VIL 0.94-1.04 V, VIH 2.19-2.43 V, ASSUMPTIONs), so pins 35 and 16 can read either level (H.23(y) row (1)); an asserted FLT sinks U108 H2C through R127 and R106s (<= 1.719 mA, H.23(n); 3.377 mA without R106s) (**superseded in r8:** "pins 35 and 16 read one level"; "through R127 (<= 3.3 mA)") | readback plausibility (FR-08/FR-44); r8: T-F-12 before power-up is the detector of this pair, because the asserted-FLT level is undefined |''',
  tag="01 A.8 F17-F15 level")
R('''placed behind the pad, holds a powered''',
  '''placed on the tab X bottom beside the F17 pad (A.8 r8 R106s placement; **superseded in r8:** placed behind the pad), holds a powered''',
  tag="01 A.4 T16 placement")
R('''Repeat steps 4 and 5. (7) Remove the bridge. Connect the bridge F06-F17''',
  '''Replace the shunt with the DMM in series, on its DC current range with a resolution of 0.001 mA or better, and read the bridge current on the DMM from here on (r8). Repeat steps 4 and 5. (7) Remove the bridge. Connect the bridge F06-F17''',
  tag="01 T-C-05c step 6 instrument")
R('''connect the bridge F17-F15 at VCHG-IN 8.0 V and measure the shunt current. (9)''',
  '''connect the bridge F17-F15 at VCHG-IN 8.0 V and measure the bridge current. Measure pin 35 and pin 16 (r8). (9)''',
  tag="01 T-C-05c step 8 levels")
R('''with pin 30 HIGH the shunt current is < 0.01 mA (FLT released''',
  '''with pin 30 HIGH the bridge current is < 0.01 mA on the DMM in series (r8: on the 1.00 ohm shunt 0.01 mA is 10 uV, at the resolution of a handheld DMM) (FLT released''',
  tag="01 T-C-05c step 6 criterion")
R('''Step 8: shunt current <= 1.72 mA (H.23(n) 1.719 mA).''',
  '''Step 8: bridge current <= 1.72 mA (H.23(n) 1.719 mA); r8: pin 35 and pin 16 recorded (H.23(y) row (1) predicts 1.60-1.93 V, information).''',
  tag="01 T-C-05c step 8 criterion")
R('''Step 9 changed: replace U101 and repeat T-C-04 |''',
  '''Step 9 changed: replace U101 and repeat T-C-04. **r8:** step 8 pin-35 or pin-16 level outside 1.60-1.93 V: no design change; T-F-12 is the detector for this pair; record the reading and re-run H.23(y) row (1) with the measured pull-up |''',
  tag="01 T-C-05c fail")
TODO_TCL = ("TODO(verify: tps2663.pdf §6.6 tabulates tCL_PLIM and tCL_PLIM_FLT for TPS26632/3/5/6/7 only; tCL_PLIM applies "
            "to the fitted TPS26630 through §8.3.7.1.1 and Table 8-1, the TPS26630 FLT timing in current limit is not "
            "tabulated; T-C-04 measures it)")
R('''FLT asserts 1.09-1.60 ms after current limiting starts (tCL_PLIM_FLT, §6.6);''',
  '''FLT asserts 1.09-1.60 ms after current limiting starts (tCL_PLIM_FLT, §6.6; r8: %s);''' % TODO_TCL,
  tag="01 H.21 TODO")
R('''(the tCL_PLIM maximum is 202 ms, tps2663.pdf (SLVSE94G) §6.6: margin 48 ms, H.23(n)), one REG1B read;''',
  '''(the tCL_PLIM maximum is 202 ms, tps2663.pdf (SLVSE94G) §6.6: margin 48 ms, H.23(n); r8: %s), one REG1B read;''' % TODO_TCL,
  tag="01 FR-23 TODO")
R('''and tCL_PLIM_FLT 1.09-1.60 ms (H.23(n)). This closes''',
  '''and tCL_PLIM_FLT 1.09-1.60 ms (H.23(n); r8: %s). This closes''' % TODO_TCL, tag="01 K TODO")
R('''runs the FR-48(a) check. One read per episode; the episode re-arms''',
  '''runs the FR-48(a) check. One REG1B read per episode; an ACK with VBUS_PRESENT_STAT = 0 adds the four FR-48(a) transactions and the EX1 conversion wait, so an episode issues at most five transactions (r8; **superseded in r8:** "One read per episode"); the episode re-arms''',
  tag="01 FR-23 EX2 total")

# ------------------------------------------------------------------ CHG-R1-03 (EX1)
R('''one ADC_EN one-shot write to REG2E, the REG3B VBAT_ADC read once the conversion has completed (tADC_CONV, SLUSDV2C §6.5), then''',
  '''one ADC_EN one-shot write to REG2E, the REG3B VBAT_ADC read after a fixed wait T_ADC_ONESHOT with no ADC_DONE polling (r8 choice: the transaction count stays fixed and the REG2F/REG30 masks are never rewritten; T_ADC_ONESHOT = 1.5 x the one-shot duration with the default REG2F/REG30 masks in battery-only mode, TODO(calc: enabled channel count x tADC_CONV, TODO(verify: SLUSDV2C §6.5, Tables 7-55 to 7-57)), measured in T-D-15) (**superseded in r8:** "once the conversion has completed (tADC_CONV, SLUSDV2C §6.5)"), then''',
  tag="03 EX1 wait")
R('''at most three transactions follow the poll.''',
  '''at most four transactions follow the poll (the REG2E write, the REG3B read, the REG2E clear write and its REG2E read-back, FR-46), plus the T_ADC_ONESHOT wait (r8; **superseded in r8:** "at most three transactions follow the poll").''',
  tag="03 EX1 cap")
R('''on an ACK the ADC_EN write, the REG3B read and the ADC_EN clear with its REG2E read-back occur in that order (A-07)**''',
  '''on an ACK the ADC_EN write, the REG3B read and the ADC_EN clear with its REG2E read-back occur in that order (A-07), with the REG3B read no earlier than T_ADC_ONESHOT after the write, no ADC_DONE poll and no fifth transaction**''',
  tag="03 FR-22 xxii")
R('''then the REG2E write, the REG3B read and the ADC_EN clear); REG2E reads ADC_EN = 0''',
  '''then the REG2E write, the REG3B read, the ADC_EN clear and its REG2E read-back; r8: record the write-to-read interval against T_ADC_ONESHOT and the REG3B value against V_batt); REG2E reads ADC_EN = 0''',
  tag="03 T-D-15 proc")
R('''ADC_EN still 1 after the read -> fix the FR-48(a) clear write**''',
  '''ADC_EN still 1 after the read -> fix the FR-48(a) clear write; r8: a REG3B value more than 0.2 V from V_batt in case (2), or a read issued before T_ADC_ONESHOT -> re-measure the one-shot duration and set T_ADC_ONESHOT from it**''',
  tag="03 T-D-15 fail")
# rename the FR-23 exceptions (EVM leads E1/E2 keep their names)
R('''**(E1) FR-12(b3) Idle probe:**''', '''**(EX1) FR-12(b3) Idle probe:**''', tag="03 rename")
R('''**(E2) FLT-LOW diagnostic read:**''', '''**(EX2) FLT-LOW diagnostic read:**''', tag="03 rename")
for a_, b_ in (("exception E1", "exception EX1"), ("exception E2", "exception EX2"), ("FR-23 E1", "FR-23 EX1"),
               ("FR-23 E2", "FR-23 EX2"), ("the E2 diagnostic read", "the EX2 diagnostic read")):
    n = t.count(a_)
    if n == 0:
        sys.exit("rename none: " + a_)
    t = t.replace(a_, b_)

# ------------------------------------------------------------------ CHG-R1-02
R('''edge to write complete <= 1.5 ms (r8: the deadline covers the two raising writes only; the FR-46 read-back follows them, G.1 T3 exception, H.23(o)).''',
  '''edge to write complete <= 1.5 ms (r8: the deadline covers the two raising writes only; the FR-46 read-back follows them, G.1 T3 exception, H.23(o)). **r8 queue priority (CHG-R1-02 verification):** a posted raise (T3 and the sag-to-raise re-entry) is serviced before every queued transaction that has not started, including FR-41(iii) ramp writes and their FR-46 read-backs; an in-flight read is aborted at the next byte boundary; an in-flight write completes; the deferred read-backs follow the T3 read-back. The H.23(o) in-flight term (0.50 / 0.35 ms) bounds max(W(REG03-05) 0.470 ms, one byte + STOP 0.100 ms) at 100 kHz; without the rule one FR-41 ramp group ahead of the raise gives 2.329 ms at 100 kHz (H.23(y) row (2)).''',
  tag="02 FR-07 priority")
R('''steps >= 50 mA, each read back, posted at the queue head;''',
  '''steps >= 50 mA, each read back, posted at the queue head behind any pending raise (r8, FR-07 queue priority; a ramp step not yet started when a raise posts is dropped, because the raise writes IINDPM 1.70 A) (**superseded in r8:** "posted at the queue head");''',
  tag="02 FR-41")
R('''edge to write complete <= 1.5 ms with a capped read in flight, no transaction exceeds''',
  '''edge to write complete <= 1.5 ms at 100 kHz with (a) a capped read, (b) a 3-byte write and (c) an FR-41 ramp write with its two field reads queued, each in flight or queued at the H1 edge (r8; **superseded in r8:** "with a capped read in flight"), no transaction exceeds''',
  tag="02 FR-22 xxxiii")
R('''a forced read-back mismatch takes P5 LOW at once; record the pin-34 ISR latency''',
  '''a forced read-back mismatch takes P5 LOW at once; r8: 20 more raises at 100 kHz with the H1 edge during an FR-41 ramp step (brake feed-forward active), the same <= 1.5 ms; record the pin-34 ISR latency''',
  tag="02 T-C-06 proc")
R('''then fix the ISR path or restate FR-07 |''',
  '''then fix the ISR path or restate FR-07; a raise during an FR-41 ramp step > 1.5 ms: apply the FR-07 r8 queue-priority rule (H.23(y) row (2)) |''',
  tag="02 T-C-06 fail")
R('''<= 1.83 ms at 100 kHz, H.23(o) and H.23(x) row (2);''',
  '''<= 1.85 ms at 100 kHz with four t_BUF, H.23(o), H.23(x) row (2) and H.23(y) row (7) (**superseded in r8:** "<= 1.83 ms at 100 kHz", which omitted t_BUF);''',
  tag="02/04 T1 8c read")
R('''with a capped transaction already in flight and t_BUF (H.23(o); ISR latency not included''',
  '''with a capped transaction already in flight and t_BUF, under the FR-07 r8 queue-priority rule (H.23(o), H.23(y) row (2); ISR latency not included''',
  tag="02 G.1 T3 timing")
R('''under the r6 FR-46 group order, which put R(REG01:02) and R(REG06:07) between the two raising writes: 2.329 ms at 100 kHz, H.23(o)).''',
  '''; r8: the r6 FR-46 group order put R(REG01:02) and R(REG06:07) between the two raising writes: 2.329 ms at 100 kHz, H.23(o)).''',
  tag="SWEEP T3 step marker")
R('''(**superseded in r8:** "; read back." ; r8:''', '''r8: the superseded text was "; read back." (**superseded in r8:** "; read back.")''', n=0, tag="noop") if False else None
R('''(**superseded in r8:** 0.5 ms at 400 kHz, 1.35 ms at 100 kHz with the 0.5 ms transaction cap, which counted the two writes only) |''',
  '''(r8: the r7 figure counted the two writes only) (**superseded in r8:** 0.5 ms at 400 kHz, 1.35 ms at 100 kHz with the 0.5 ms transaction cap) |''',
  tag="SWEEP T3 criterion marker")

# ------------------------------------------------------------------ CHG-R1-D01
R('''the request is held and re-raised at the next State-1 entry; a power loss first loses the record, which the rev-3 detector re-learns).''',
  '''r8: the request is held in every State-99 phase; State 99 has no exit to State 1 except a reset in production, which clears the pending request, so a flip learned in a run that ends in State 99 is not persisted and the rev-3 detector re-learns it after the reset; under HIL_SIM, hilWarmReset re-enters State 0 and the request executes at the next admitted Idle only if the warm reset preserves it, TODO(verify: teensy_controller.ino hilWarmReset)) (**superseded in r8:** "the request is held and re-raised at the next State-1 entry; a power loss first loses the record, which the rev-3 detector re-learns").''',
  tag="D01 FR-43 flash")
R('''a commit requested in State 99 stays pending in every phase, phase 3 included, and executes at the next admitted Idle;''',
  '''a commit requested in State 99 stays pending in every phase, phase 3 included, and no flash operation starts while mainState == 99 (r8; **superseded in r8:** "and executes at the next admitted Idle");''',
  tag="D01 FR-43 host test")
R('''(the fw v28 rev 4 State-99 phase-3 allowance is removed:''',
  '''(the fw v28 rev 4 State-99 phase-3 allowance is removed:''', tag="D01 anchor")
R('''neither predicate calls `fcPurgeExposure()` |''',
  '''neither predicate calls `fcPurgeExposure()`. r8: the bench-log abandon-close path (`LOG_CLOSE_DEADLINE_MS`, 2 s) is not yet bound to `sdOpAllowed`, TODO(design: the firmware round decides whether the deadline path waits on the gate or bypasses it, for example a profile close requested while the heartbeat runs in State 98) |''',
  tag="D01 FR-43 deadline")
R('''a commit requested in State 99 phase 3 stays pending and executes at the next admitted Idle.''',
  '''a commit requested in State 99 phase 3 stays pending (S dump: store pending) with zero watchdog resets until the operator resets the MCU (r8; **superseded in r8:** "stays pending and executes at the next admitted Idle").''',
  tag="D01 T-W-01")
R('''State 99 holds the request in every phase; a power loss before then loses the record''',
  '''State 99 holds the request in every phase; the reset that is the only exit from State 99, or a power loss before the next admitted Idle, loses the record (r8; **superseded in r8:** "a power loss before then loses the record")''',
  tag="D01 J.2 33")
R('''(r8: the normal Idle vector with BT_BUS HIGH and read back, FR-43; **superseded in r8:** the next quiescent Idle, which the r5 FC_BUS-LOW term never admitted, CHG-R1-D01)''',
  '''(r8: the normal Idle vector with BT_BUS HIGH and read back, FR-43, which the r5 FC_BUS-LOW term never admitted, CHG-R1-D01; **superseded in r8:** the next quiescent Idle)''',
  tag="SWEEP J.2 33 marker")
R('''and is executed only at the next quiescent Idle.''',
  '''and is executed only at the next admitted Idle (r8, FR-43 `flashWriteAllowed`; **superseded in r8:** quiescent Idle).''',
  tag="D01 T-C-06")
R('''never TRUE in normal Idle, which keeps FC_BUS HIGH, and its "no SD log open" term blocked the SD close it also governed.)''',
  '''.) r8: the r5 predicate was never TRUE in normal Idle, which keeps FC_BUS HIGH, and its "no SD log open" term blocked the SD close it also governed.''',
  tag="SWEEP FR-43 marker")

# ------------------------------------------------------------------ CHG-R1-D04
R('''so OUT crosses 0 V before the FET opens and D103 freewheels a lead current of the order of I_SCP 45 A for < 1 us, clamping''',
  '''so OUT crosses 0 V before the FET opens and D103 freewheels the W1/W2 lead current, r8: up to 130 A at 290 mm at the L' minimum (128 A when the FET opens) for < 1 us (H.5, H.23(p), H.23(y) row (3)) (**superseded in r8:** "D103 freewheels a lead current of the order of I_SCP 45 A for < 1 us"), clamping''',
  tag="D04 B.4 D103 current")
R('''(3) VF at a >= 20 A pulse and at 3 A from the curve. No candidate MPN''',
  '''(3) VF at a >= 20 A pulse and at 3 A from the curve, (4) (r8) a non-repetitive peak current >= 130 A for <= 1 us from the IFSM-versus-pulse-width curve (H.23(p)), TODO(verify: D103 datasheet). No candidate MPN''',
  tag="D04 B.4 D103 criterion 4")
R('''**D103 selection** (VF at a >= 20 A pulse and at 3 A, IFSM >= 75 A, IR at 23.6 V and 60 C from the curves);''',
  '''**D103 selection** (VF at a >= 20 A pulse and at 3 A, IFSM >= 75 A, IR at 23.6 V and 60 C from the curves; r8: a non-repetitive peak >= 130 A for <= 1 us from the IFSM-versus-pulse-width curve, H.23(p));''',
  tag="D04 T-A-05 item")
R('''IFSM >= 75 A and VF at 3 A <= 0.5 V, in that precedence (r3);''',
  '''IFSM >= 75 A and VF at 3 A <= 0.5 V, in that precedence (r3); r8: a non-repetitive peak >= 130 A for <= 1 us (H.23(p));''',
  tag="D04 T-A-05 pass")
R('''D107: if no SMA part meets Vc <= 60 V''',
  '''r8: no SMA D103 meets the 130 A / 1 us pulse: a higher-IFSM Schottky with the OUT strip re-planned and re-checked in T-A-06 (the T-C-04 fail branch). D107: if no SMA part meets Vc <= 60 V''',
  tag="D04 T-A-05 fail")
R('''(output lines 694-697, summary line 856)''',
  '''(output lines 694-698 and the summary row "hard short vs W1 length (D-F3)") (**superseded in r8:** "(output lines 694-697, summary line 856)")''',
  tag="D04 H.23(p) cite")
R('''lower bound with the strand-bundle radius and the helix factor at a 20 mm pitch,''',
  '''lower bound with the strand-bundle radius and the helix factor evaluated at OD max and a 20 mm pitch (conservative: with k at OD min L' is 0.401 uH/m and the IN peak 33.76 V at 290 mm, H.23(y) row (3)),''',
  tag="D04 H.23(p) helix")
R('''(PVC 300 V hook-up class, UL1007/UL1569; any insulation whose measured OD lies in that range is admissible), red.''',
  '''(PVC 300 V hook-up class, UL1007/UL1569; any insulation whose measured OD lies in that range is admissible; the class name alone does not guarantee the range, because its H.23(p) row spans OD 1.55-1.80 mm, so the T-A-02 measured OD decides), red.''',
  tag="D04 A.3 class")

# ------------------------------------------------------------------ CHG-R1-D03
R('''above the CR top at y 67.10 (H.23(s)).
''',
  '''above the CR top at y 67.10 (H.23(s)). r8 (lateral support, H.23(y) row (4)): the 2.50 mm face supports 51 % of the 4.885 mm
trunk width; the trunk centreline x 25.80 lies 0.25 mm inside the +x face edge, so the trunk overhangs 2.19 mm on +x and
0.19 mm on -x. The H.23(s) profile check holds for a cohesive round bundle whose lowest line lies on the face, because its
lower surface then stands at or above the face plane across the whole width (0.013 mm at the +x face edge). RTV therefore
binds every trunk lead into one round bundle and bonds the bundle to the ramp face from the toe to the apex, so no lead
overhangs the face edge on its own. The wedge is not widened: a wider block in the footprint interior needs a new part-box
and exclusion check (J.2 item 68).
''', tag="D03 A.3 support")
R('''Lay the trunk on the B1R ramp face from the toe to the apex, then on the B3 post.''',
  '''Lay the trunk on the B1R ramp face from the toe to the apex, then on the B3 post. Bind the trunk leads into one round bundle with RTV and bond the bundle to the ramp face from the toe to the apex (r8, A.3 lateral support).''',
  tag="D03 PM4 bind")
R('''Record the position of each anchor (B1, B3, S1-S3, A1, A2) against A.3''',
  '''Record the position of each anchor (B1R, B3 with the B3/S3 union spot, S1, S2, A1, A2) against A.3 (r8; **superseded in r8:** B1, B3, S1-S3, A1, A2)''',
  tag="D03 T-F-12 anchors")
R('''at T2 (25.80, 69.60), at B3 and at (36.00, 71.10). Measure the trunk jacket bottom above the MB''',
  '''at T2 (25.80, 69.60), at B3 and at (36.00, 71.10); at each B1R check point, also measure the jacket bottom of the lowest lead at the +x edge of the trunk (r8, H.23(y) row (4)). Measure the trunk jacket bottom above the MB''',
  tag="D03 T-F-12 +x edge")
R('''W5 on top of the trunk at every point of the overlap; the stack top recorded''',
  '''no lead below the r8 profile at any point of the trunk width (the +x edge readings included); no trunk lead above W5 at any point of the overlap, and W5 in contact with the trunk from (28.70, 64.01) to A1 (r8; **superseded in r8:** "W5 on top of the trunk at every point of the overlap"); W5 bottom 19.408 mm nominal at (28.70, 73.10) (H.23(y) row (5)), 19.285 mm at x 41.5 and 17.412 mm at x 44.0 (H.23(t)), and at least the trunk-top height at each point; the stack top recorded''',
  tag="W01/D03 T-F-12 criteria")
R('''carries the W1-W4 trunk from the W1/W2 joints, and
  an insulating post at B3 holds it 10.7 mm above the carrier top; the W5 ribbon rests on the trunk from tab Y to A1.''',
  '''carries the W1-W4, W6 and W7 trunk from the W1/W2 joints, and
  an insulating post at B3 holds it 10.7 mm above the carrier top; the W5 ribbon rests on the trunk from (28.70, 64.01) on the
  footprint interior to A1.''',
  tag="D03/W01 D.4 record")
R('''a dummy W5 ribbon on top of it, and confirm that both can be dressed this way, H.23(s), H.23(t))''',
  '''a dummy W5 ribbon on top of it, and confirm that both can be dressed this way and that the bound bundle stays on the 2.50 mm face, H.23(s), H.23(t), H.23(y) row (4))''',
  tag="D03 T-A-06 item 8")
R('''with the B1R wedge, the B3 post, S1-S3 and the off-CR support''',
  '''with the B1R wedge, the B3 post, S1, S2 and the B3/S3 union spot and the off-CR support''',
  tag="W01 T-A-06 S list")

# ------------------------------------------------------------------ CHG-R1-W01
R('''W5 rests on the trunk with RTV over the whole
    plan overlap, from the trunk start (y 57.00) to A1, at 19.850-20.750 mm above the MB at the B3 level (W5 requirement
    margin 1.866 mm, H.23(t)) (A.3)''',
  '''W5 lies above the trunk over the whole plan overlap from
    the trunk start (y 57.00) to A1; it rests on the trunk and is bonded to it with RTV from (28.70, 64.01) to A1, at
    19.850-20.750 mm above the MB at the B3 level; W5 meets its own 3-D requirement everywhere with >= 1.866 mm of margin,
    the minimum at (28.70, 64.01) (requirement 10.416 mm), and over tab Y with 4.850 mm (H.23(t), H.23(y) row (5)) (A.3)
    (r8 verification round; **superseded in r8:** "W5 rests on the trunk with RTV over the whole plan overlap, from the
    trunk start (y 57.00) to A1"; "W5 requirement margin 1.866 mm")''',
  tag="W01 J.2 62")
R('''the trunk meets the B1R / B3 profile at every T-F-12 check point, W5 lies on top of the trunk over the whole overlap, and''',
  '''the trunk meets the B1R / B3 profile at every T-F-12 check point, no trunk lead lies above W5 at any point of the overlap, W5 is in contact with the trunk and bonded to it from (28.70, 64.01) to A1 (**superseded in r8:** "W5 lies on top of the trunk over the whole overlap"), and''',
  tag="W01 PM4 pass")
R('''Under a loupe, check that W5 lies on top of the trunk over the whole overlap''',
  '''Under a loupe, check that no trunk lead lies above W5 at any point of the overlap and that W5 touches the trunk from (28.70, 64.01) to A1 (r8; **superseded in r8:** "check that W5 lies on top of the trunk over the whole overlap")''',
  tag="W01 T-F-12 loupe")
R('''Both exceptions wait for an operator ruling (J.2 item 62)). W5 also passes over the FT2 fill hole at its fold height, so a re-bed of FT2 first lifts W5 from S2 and S3.''',
  '''Both exceptions wait for an operator ruling (J.2 item 62)). r8 (H.23(y) row (5)): W5 passes over the FT2 fill hole on top of the trunk, 19.41 mm above the MB, bonded to the trunk with RTV. To re-bed FT2 after PM4 (6), cut the W5-to-trunk RTV locally over the fill hole and lift W5; re-bond W5 to the trunk after the bed cures (T-F-12, T-A-09) (**superseded in r8:** "W5 also passes over the FT2 fill hole at its fold height, so a re-bed of FT2 first lifts W5 from S2 and S3.")''',
  tag="W01 A.3 FT2")
R('''requirement (>= 15.00 mm above the MB over tab Y) with 1.866 mm of margin.''',
  '''3-D requirement everywhere with >= 1.866 mm of margin; the minimum lies at (28.70, 64.01), where W5 first rides on the
trunk (requirement 10.416 mm above the MB); over tab Y the margin is 4.850 mm (19.850 - 15.00) (H.23(y) row (5);
**superseded in r8:** "requirement (>= 15.00 mm above the MB over tab Y) with 1.866 mm of margin").''',
  tag="W01 A.3 margin")
R('''rests on the trunk there, 19.850 mm above the MB at the B3 level, and meets its own requirement with 1.866 mm of margin.''',
  '''rests on the trunk there, 19.850 mm above the MB at the B3 level, 4.850 mm above that requirement; the W5 minimum
  margin over its own requirement, 1.866 mm, lies at (28.70, 64.01) (H.23(y) row (5); **superseded in r8:** "and meets its
  own requirement with 1.866 mm of margin").''',
  tag="W01 A.3 3-D rule bullet")
R('''- W5 **spacer beads**, each an RTV bead onto an insulating spacer on the CR that holds the ribbon at its fold height: **S1** at (35.00, 47.69), **S2** at (28.70, 53.42) and **S3** at (35.00, 73.10), which merges with B3 into one spot (r8: on that spot W5 rests on the trunk, and one bead bonds both runs, H.23(t))''',
  '''- W5 **spacer beads**: **S1** at (35.00, 47.69) and **S2** at (28.70, 53.42), each an RTV bead onto an insulating spacer on the CR that holds the ribbon at its fold height, and **S3** at (35.00, 73.10), which merges with B3 into one spot where W5 rests on the trunk and one bead bonds both runs (r8, H.23(t); **superseded in r8:** "each an RTV bead onto an insulating spacer on the CR that holds the ribbon at its fold height: S1, S2 and S3")''',
  tag="W01 anchor list")
R('''In (3c), keep the weight clear of B1R''', '''In (3c), keep the weight clear of B1R''', n=0, tag="noop") if False else None
R('''A debond on polyimide found after the 22 joints are soldered: re-bed through the FT1 lane or the FT2 fill hole and repeat;''',
  '''A debond on polyimide found after the 22 joints are soldered: re-bed through the FT1 lane or the FT2 fill hole and repeat (r8: for FT2, first cut the W5-to-trunk RTV over the fill hole and lift W5, and re-bond W5 to the trunk after the bed cures, A.3);''',
  tag="W01 T-A-09 fail")
R('''**r7:** a cracked or debonded bed: re-bed and repeat T-A-09 |''',
  '''**r7:** a cracked or debonded bed: re-bed and repeat T-A-09 (r8: for FT2, first cut the W5-to-trunk RTV over the fill hole and lift W5, then re-bond W5 to the trunk after the bed cures, A.3); **r8:** a lead below the profile at the +x trunk edge: re-bind the bundle and re-bond it to the B1R face, or widen B1R (re-run H.23(s) with a part-box and exclusion check) |''',
  tag="W01/D03 T-F-12 fail")

# ------------------------------------------------------------------ CHG-R1-04
R('''the step-8b ILIM-leg heartbeat test (r4);''',
  '''the step-8b ILIM-leg heartbeat test (r4); r8: the step-8c re-arm (P5 rise with QUAL LOW clears QQ through CLR = P5N; pin 33 LOW within 5 ms) and the end-of-T1 check (CHG-R1-04);''',
  tag="04 FR-04")
R('''after the 60 s cruise, one brake of >= 0.5 s;''',
  '''after the 60 s cruise, one brake of >= 0.5 s that raises V-MOT above the cruise level by >= 0.5 V (TODO(calibrate: T-G-01)) (**superseded in r8:** "one brake of >= 0.5 s");''',
  tag="04 T-F-03 brake")
R('''pin 33 HIGH 5 ms after the P5 rise -> U111 CLR path fault (B.1): carrier fault** |''',
  '''pin 33 HIGH 5 ms after the P5 rise -> U111 CLR path fault (B.1): carrier fault; brake IBAT rise <= 0.1 A with the end-of-T1 state correct -> repeat with a brake that T-G-01 shows regenerates (V-MOT above the cruise level) before any design change; if V-MOT rises and IBAT does not, investigate the regen image (FR-25) and the REGEN / D-BC-RG conduction** |''',
  tag="04 T-F-03 fail")
R('''and steps 8b-8c (<= ~75 ms; 126.7 ms in total, H.23(x) row (3))''',
  '''and steps 8b-8c (<= ~75 ms; 128.5 ms in total with the <= 1.85 ms step-8c pre-edge read, H.23(y) row (7); **superseded in r8:** "126.7 ms in total, H.23(x) row (3)", which omitted the read)''',
  tag="04 T1 budget")
R('''(+126.7 ms, H.23(x))''', '''(+128.5 ms, H.23(y) row (7); **superseded in r8:** +126.7 ms, H.23(x))''', tag="04 r8-7")
R('''Whole step <= ~70 ms against tw_QQ,min 0.20 s.": the expiry needs >= 0.20 s, and P5 was left LOW, so the step-9 EN_CHG = 1 write could not release /CE).''',
  '''Whole step <= ~70 ms against tw_QQ,min 0.20 s."); r8: the expiry needs >= 0.20 s, and P5 was left LOW, so the step-9 EN_CHG = 1 write could not release /CE.''',
  tag="SWEEP T1 8b marker")
R('''  (H.23(q)); the FR-48 Idle probe and the FR-23 FLT-LOW diagnostic read become explicit exceptions to the FR-23 gate; T1
  step 8b, T-B-16 and T-F-16 are restated (G.2, I).''',
  '''  (H.23(q)); the FR-12(b3) Idle probe (FR-23 exception EX1) and the FR-23 FLT-LOW diagnostic read (EX2) become explicit
  exceptions to the FR-23 gate; T1 steps 8b-8c (F.5), T-B-16 and T-F-16 are restated (F.5, I) (**superseded in r8:** "the
  FR-48 Idle probe"; "T1 step 8b, T-B-16 and T-F-16 are restated (G.2, I)").''',
  tag="04/SWEEP 0.2")

# ------------------------------------------------------------------ CHG-R1-05
R('''An optional coupon before the vehicle
    build beds the RTV on the chosen sheet over an MB-mask coupon (a spare MB or any FR-4 with LPI mask), pulls it to failure
    and records which interface fails. T-A-09 decides; the fallback''',
  '''r8: the T-A-09 step 0 bond coupon
    (0.4 N for 10 s, before PM4 (1)) is mandatory and decides the fallback before the 22 joints are soldered (A.7,
    H.23(r)); a pull to failure on a second coupon is an optional information step (**superseded in r8:** "An optional
    coupon before the vehicle build beds the RTV on the chosen sheet over an MB-mask coupon (a spare MB or any FR-4 with
    LPI mask), pulls it to failure and records which interface fails. T-A-09 decides;"); the fallback''',
  tag="05 J.2 55")
R('''With a micrometer, measure the offcut stack, film and PSA together, and record it as t_rm.''',
  '''Before you bond the offcut, measure its stack, film and PSA together, with a micrometer to +-0.01 mm. Record it as t_coupon (information only; PM4 (2c) measures t_rm on the removed stack) (r8 verification round; **superseded in r8:** "With a micrometer, measure the offcut stack, film and PSA together, and record it as t_rm."). Bed a second FT1-size block directly on the coupon solder mask beside the sheet, 0.30 mm above it on shims, with the same RTV, so that the fallback bond on the mask is qualified as well.''',
  tag="05 T-A-09 t_coupon")
R('''Remove the shims. Pull the block upward with 0.4 N for 10 s.''',
  '''Remove the shims. Pull each block upward with 0.4 N for 10 s (r8; **superseded in r8:** "Pull the block upward").''',
  tag="05 T-A-09 pull both")
R('''no debond at the bed-sheet interface and no lift of the sheet from the coupon mask after the pull; t_rm recorded;''',
  '''no debond at the bed-sheet interface and no lift of the sheet from the coupon mask after the pull; no debond of the mask block; t_coupon recorded (**superseded in r8:** "t_rm recorded");''',
  tag="05 T-A-09 pass")
R('''a sheet-to-mask lift is a PSA failure, not an RTV failure: re-press the sheet and repeat before the fallback;''',
  '''a sheet-to-mask lift is a PSA failure, not an RTV failure: re-press the sheet and repeat before the fallback; r8: a debond of the step 0 mask block: no qualified fallback bond, so choose another bed RTV (T-A-05) and repeat step 0 before PM4 (1);''',
  tag="05 T-A-09 fail mask")
R('''and record it as t_rm. At those feet, use re-made foot blocks''',
  '''and record it as t_rm. Remove any PSA residue from the mask inside the cut-out with isopropyl alcohol, and let it dry (r8). At those feet, use re-made foot blocks''',
  tag="05 PM4 2c IPA")

# ------------------------------------------------------------------ CHG-R1-D02
R('''(a stuck path reads >= 13.88 V; a healthy path falls below 12 V in <= 0.183 s with the eFuse enabled, H.23(q)).''',
  '''(a stuck path reads >= 14.16 V, and >= 13.88 V with a -2 % pin-38 gain error; a healthy path falls below 12 V in 0.183 s at the typical IQ(ON) with the eFuse latched, H.23(q); IQ(ON) has no specified minimum, so T-C-04 is the gate) (r8 verification round; **superseded in r8:** "(a stuck path reads >= 13.88 V; a healthy path falls below 12 V in <= 0.183 s with the eFuse enabled, H.23(q))").''',
  tag="D02 FR-12 b1")
R('''TODO(verify: T-C-04 across initial V_chg 12.5-22.28 V and the eFuse ON, UVLO and latched states;''',
  '''TODO(verify: T-C-04 across initial V_chg 12.5-22.28 V and the eFuse ON and latched states (r8: the UVLO state cannot occur above the 9.70-10.13 V UVLO band of R102/R103/R104; **superseded in r8:** "the eFuse ON, UVLO and latched states");''',
  tag="D02 FR-12 states")
R('''if T-C-04 shows less than 0.375 mA in any state, the dwell becomes 1.5 s''',
  '''if T-C-04 shows less than 0.375 mA in the latched state, the dwell becomes 1.5 s''',
  tag="D02 FR-12 dwell")
R('''the probe could not pass the FR-23 gate.)''',
  '''the probe could not pass the FR-23 gate.)''', tag="anchor")
R('''(**superseded in r8:** "FCC = REGEN = 0 -> V_chg decays below 3 V within 2 s (shorted D-BC-FC/D-BC-RG); H1 rb 0; H2c rb 0; I2C to 0x6B NACK (charger unpowered)": the decay from 9.9 V to 3 V below UVLO takes 1.65-2.75 s (H.23(q)), so a warm reset with a fast bring-up could false-fail it and refuse regen for one boot, and the probe could not pass the FR-23 gate.)''',
  '''r8: the r7 decay test failed because the decay from 9.9 V to 3 V below UVLO takes 1.65-2.75 s (H.23(q)), so a warm reset with a fast bring-up could false-fail it and refuse regen for one boot, and the r7 probe could not pass the FR-23 gate (**superseded in r8:** "FCC = REGEN = 0 -> V_chg decays below 3 V within 2 s (shorted D-BC-FC/D-BC-RG); H1 rb 0; H2c rb 0; I2C to 0x6B NACK (charger unpowered)").''',
  tag="SWEEP FR-12 marker")
R('''IQ(ON) 1.38-1.70 mA, tps2663.pdf §6.5) | r7 test''',
  '''IQ(ON) 1.38 mA typical, 1.70 mA maximum, no minimum specified, tps2663.pdf §6.5; **superseded in r8:** "IQ(ON) 1.38-1.70 mA") | r7 test''',
  tag="D02 H.21 iq")
R('''worst 0.183 s with the eFuse enabled (LATCHED, 28.4 uF, from 22.28 V; margin 0.317 s);''',
  '''0.183 s at the typical IQ(ON) (LATCHED, 28.4 uF, from 22.28 V; margin 0.317 s); no datasheet lower bound exists, so T-C-04 is the gate (**superseded in r8:** "worst 0.183 s with the eFuse enabled");''',
  tag="D02 H.21 worst")
R('''(needs >= 0.375 mA IN-side; IQ in UVLO and latched unspecified, TODO(verify: tps2663.pdf §6.5; T-C-04)); a stuck path reads >= 13.88 V |''',
  '''(needs >= 0.375 mA IN-side; IQ in the latched state unspecified, TODO(verify: tps2663.pdf §6.5; T-C-04)); a stuck path reads >= 14.16 V (>= 13.88 V with a -2 % pin-38 gain error) (**superseded in r8:** "IQ in UVLO and latched unspecified"; "a stuck path reads >= 13.88 V") |''',
  tag="D02 H.21 end")
R('''eFuse IQ(ON) 1.38-1.70 mA, `references/Datasheets/tps2663.pdf` sec 6.5)''',
  '''eFuse IQ(ON) 1.38 mA typical, 1.70 mA maximum, no minimum specified, `references/Datasheets/tps2663.pdf` sec 6.5; **superseded in r8:** "IQ(ON) 1.38-1.70 mA")''',
  tag="D02 H.23(q) iq")
R('''worst case with the eFuse enabled 0.183 s (latched, 28.4 uF, from 22.28 V), margin 0.317 s;''',
  '''0.183 s at the typical IQ(ON) (latched, 28.4 uF, from 22.28 V), margin 0.317 s, with no datasheet lower bound, so T-C-04 is the gate (**superseded in r8:** "worst case with the eFuse enabled 0.183 s");''',
  tag="D02 H.23(q) worst")
R('''it needs an IN-side current >= 0.375 mA against IQ(ON) min 1.38 mA, and IQ in UVLO and in the latched state is unspecified;''',
  '''it needs an IN-side current >= 0.375 mA against IQ(ON) 1.38 mA typical, and IQ in the latched state is unspecified (the UVLO state cannot occur above 12 V) (**superseded in r8:** "against IQ(ON) min 1.38 mA, and IQ in UVLO and in the latched state is unspecified");''',
  tag="D02 H.23(q) need")
R('''(worst case 0.183 s with the eFuse enabled, H.23(q))''',
  '''(0.183 s at the typical IQ(ON), no datasheet lower bound, H.23(q); **superseded in r8:** "worst case 0.183 s with the eFuse enabled")''',
  tag="D02 r8-11")
R('''holds with the eFuse enabled (worst case
    0.183 s, margin 0.317 s), but it fails''',
  '''holds with the eFuse enabled at the typical IQ(ON)
    (0.183 s, margin 0.317 s; **superseded in r8:** "worst case 0.183 s"), but it fails''',
  tag="D02 J.2 65 a")
R('''IQ(ON) is >= 1.38 mA, and the IQ in UVLO and in the latched state is not specified (H.23(q)).''',
  '''IQ(ON) is 1.38 mA typical with no specified minimum, and the IQ in the latched state is not specified; the UVLO state
    cannot occur above the 9.70-10.13 V UVLO band (H.23(q)) (**superseded in r8:** "IQ(ON) is >= 1.38 mA, and the IQ in UVLO
    and in the latched state is not specified").''',
  tag="D02 J.2 65 b")
R('''A stuck path reads >= 13.88 V
    (14.16 V with a -2 % gain error), so''',
  '''A stuck path reads >= 14.16 V
    (>= 13.88 V with a -2 % pin-38 gain error) (**superseded in r8:** ">= 13.88 V (14.16 V with a -2 % gain error)"), so''',
  tag="D02 J.2 65 swap")
R('''set VCHG-IN to 12.5, 16.0, 19.38 and 22.28 V in turn, in each of three eFuse states (ON, in UVLO, latched);''',
  '''set VCHG-IN to 12.5, 16.0, 19.38 and 22.28 V in turn, in each of two eFuse states (ON and latched; the UVLO state cannot occur above the 9.70-10.13 V UVLO band, R102/R103/R104) (**superseded in r8:** "in each of three eFuse states (ON, in UVLO, latched)");''',
  tag="D02 T-C-04 proc")
R('''and the IN-side current is >= 0.375 mA in UVLO and in the latched state (H.23(q)) |''',
  '''and the IN-side current is >= 0.375 mA in the latched state (H.23(q)) (**superseded in r8:** "in UVLO and in the latched state") |''',
  tag="D02 T-C-04 pass")
R('''or an IN-side current < 0.375 mA in UVLO or latched: set the FR-12(b1) dwell''',
  '''or an IN-side current < 0.375 mA in the latched state: set the FR-12(b1) dwell''',
  tag="D02 T-C-04 fail")
R('''eFuse IN-side current in UVLO and in the latched state
  (H.23(q),''', '''eFuse IN-side current in the latched state
  (H.23(q),''', tag="D02 D.5 list")
R('''`chg_flags` bits **chg_full**, **window-refused-by-goal**,''',
  '''`chg_flags` bits **chg_full**, **window-refused-by-goal**, **`vchg_slow_decay`** (r8, CHG-R1-D02, FR-12(b2)),''',
  tag="D02 FR-20 flag")

# ------------------------------------------------------------------ CHG-R1-08 nits
R('''Then run the same two currents at 0.6 s on and 0.4 s off (period 1.0 s, 60 % duty) for 5 min.''',
  '''Then, for 5 min, alternate 0.6 s at the burst current with 0.4 s at 1.6 A (period 1.0 s, 60 % duty).''',
  tag="08 T-B-16 run B")
R('''It represents regen inside an FC window (0.2), and''', '''It represents regen inside an FC window (F.1 raised image, T3), and''', tag="08 cite")
R('''so the 2.67 W and 0.97 W figures above are its two dissipation levels;''',
  '''so the 2.67 W and 0.93-0.97 W figures above (1.6 A nominal, 1.656 A upper bound) are its two dissipation levels;''',
  tag="08 H.14")

# ------------------------------------------------------------------ CHG-R1-06
R('''new T-A-08 (pre-capture survey MS1-MS8; MS1a gates PM1, the MS6 reading at the CHG holes gates PM4, the other items gate PM0) (**superseded in r7 (D-H):** MS1a is taken before PM1 because the module must be fitted, and it gates nothing; gate D-2 and the MS2 lid clearance retire; J.2 items 46-63),''',
  '''new T-A-08 (pre-capture survey MS1-MS8; MS1a is taken before PM1 because the module must be fitted, and it gates nothing (D-H); gate D-2 and the MS2 lid clearance retire; the MS6 reading at the CHG holes gates PM4, the other items gate PM0; J.2 items 46-63) (**superseded in r8:** MS1a gates PM1),''',
  tag="06 r7-17")
R('''(D-H; **superseded:** MS1a gates PM1)''', '''(D-H; **superseded in r7 (D-H):** MS1a gates PM1)''', tag="06 T-A-08 tag")
R('''C EM5/EM23, D.1 PM0/PM4, D.4 record, E CR PCB, sheet and cost lines, 0.3 r7-9,''',
  '''C EM5/EM23, D.1 PM0/PM4, D.4 record, E CR PCB, sheet and cost lines, 0.3 r7-9 and r7-17 (verification round),''',
  tag="06 r8-13 list")
R('''the rev-2 W-lead tables are labelled history | CHG-R1-06 (A-06) |''',
  '''the rev-2 W-lead tables are labelled history; a marker converted in r8 carries the label "superseded in r8" whichever revision first withdrew the text it holds, and a marker that r8 did not touch keeps its own label | CHG-R1-06 (A-06) |''',
  tag="06 r8-13 label rule")
R('''(r7 review 7 close; relief-hole bullet below); **superseded in r8:** each cut to the part body + 0.5 mm, i.e. inside
    the bottom keep-out x 24.5-36.0, y 48.5-53.5; r7: the named keep-out retires and the five cut-outs are unchanged) so the sheet lies flat''',
  '''(r7 review 7 close; relief-hole bullet below) (**superseded in r8:** each cut to the part body + 0.5 mm, i.e. inside
    the bottom keep-out x 24.5-36.0, y 48.5-53.5; r7: the named keep-out retires and the five cut-outs are unchanged)) so the sheet lies flat''',
  tag="SWEEP A.7 delimiter")
R('''FR-22/FR-48 (the Idle probe exception to the FR-23 gate)''',
  '''FR-12(b3)/FR-22/FR-48(a) (the Idle probe, FR-23 exception EX1)''', tag="SWEEP D.5 term")

# ------------------------------------------------------------------ SWEEP: markers holding r8 rationale
R('''(**superseded in r8:** FLT LOW with fresh I2C and VBUS_PRESENT_STAT = 1 for > 250 ms -> carrier fault latched (FR-23); unreachable, because FR-23 attempts I2C only with FLT HIGH) |''',
  '''r8: the r4 rule was unreachable, because FR-23 attempts I2C only with FLT HIGH (**superseded in r8:** FLT LOW with fresh I2C and VBUS_PRESENT_STAT = 1 for > 250 ms -> carrier fault latched (FR-23)) |''',
  tag="SWEEP F.3 marker")
R('''-> carrier fault latched (a FLT reading that contradicts a powered charger); unreachable, because this gate attempts I2C only with FLT HIGH, so i2c_fresh is never TRUE while FLT reads LOW);''',
  '''-> carrier fault latched (a FLT reading that contradicts a powered charger)); r8: that rule was unreachable, because this gate attempts I2C only with FLT HIGH, so i2c_fresh is never TRUE while FLT reads LOW;''',
  tag="SWEEP FR-23 marker")
R('''set ADC_EN (one-shot), read REG3B VBAT_ADC", which named no route through the FR-23 gate)''',
  '''set ADC_EN (one-shot), read REG3B VBAT_ADC"; r8: it named no route through the FR-23 gate)''',
  tag="SWEEP FR-48 marker")
R('''clear ADC_EN with a REG2E read-back (A-07) (**superseded''',
  '''clear ADC_EN with a REG2E read-back (A-07), after the FR-23 EX1 T_ADC_ONESHOT wait with no ADC_DONE poll (**superseded''',
  tag="03 FR-48 wait")
R('''(r8; **superseded in r8:** if 8.8 x the TP27 component exceeds 0.5 V p-p (TP27 above 57 mV p-p); 8.8 holds at 90 mm only).''',
  '''(r8; **superseded in r8:** if 8.8 x the TP27 component exceeds 0.5 V p-p (TP27 above 57 mV p-p)).''',
  tag="SWEEP T-C-16 marker")

# ------------------------------------------------------------------ CHG-R1-07
R('''For any other built length, use 17.80 until H.23(v) is re-run at that length (TP27 above 28 mV p-p)''',
  '''For any other built length, use 25.6, the H.23(k) undamped Q with the E8 return at 20 mm, which bounds the H.23(y) row (6) sweep maximum of 25.5 at 81.7 mm over the 70.8-90 mm build range (the built bent route is 70.8 mm), until H.23(v) is re-run at that length (TP27 above 19.5 mV p-p) (r8 verification round; **superseded in r8:** "use 17.80 until H.23(v) is re-run at that length (TP27 above 28 mV p-p)")''',
  tag="07 T-C-16 step 2")
R('''(7.75-15.13 with R276 bridged on the two-wire return, 7.75-17.80 over the H.23(v) set;''',
  '''(7.75-15.13 with R276 bridged on the two-wire return, 7.75-17.80 over the H.23(v) set at 85 and 90 mm, up to 25.5 at 81.7 mm over the 70.8-90 mm build range, H.23(y) row (6);''',
  n=2, tag="07 T-C-16 cell")
R('''passes for a TP27 ripple up to 273 mV (H.23(v);''',
  '''passes for a TP27 ripple up to 273 mV on the f0 basis and 268 mV at 1.5 MHz (H.23(v), H.23(y) row (6);''',
  tag="07 T-C-16 268")
R('''the C205/TP27 ratio (predicted 7.75-17.80, H.23(v);''',
  '''the C205/TP27 ratio (predicted 7.75-17.80 at 85 and 90 mm, up to 25.5 at another built length, H.23(v), H.23(y) row (6);''',
  tag="07 T-C-16 pass")
R('''another built E1 length uses the
    17.80 bound until H.23(v) is re-run.''',
  '''another built E1 length uses 25.6,
    the H.23(k) undamped Q, which bounds the sweep maximum 25.5 at about 81.7 mm where f0 equals 1.5 MHz (H.23(y) row (6)),
    until H.23(v) is re-run (**superseded in r8:** "uses the 17.80 bound").''',
  tag="07 J.2 68d")
R('''C205/TP27 at 1.5 MHz with R276 bridged: 7.75 (90 mm) to 15.13 (85 mm); with R276 fitted, the T-C-16 4.8 mV limit holds for a TP27 ripple up to 273 mV | replaces the H.23(k) and A.5 hand calculations; the T-C-16 abort ratio 8.8 holds at a 90 mm E1 only (up to 15.1 at 85 mm) |''',
  '''C205/TP27 at 1.5 MHz with R276 bridged: 7.75-15.13 on the two-wire return, 7.75-17.80 over the full set (9.20 at 90 mm, 17.80 at 85 mm), and 25.5 at 81.7 mm over the 70.8-90 mm build range (H.23(y) row (6)); with R276 fitted, the T-C-16 4.8 mV limit holds for a TP27 ripple up to 273 mV on the f0 basis (268 mV at 1.5 MHz) (**superseded in r8:** "7.75 (90 mm) to 15.13 (85 mm)") | replaces the H.23(k) and A.5 hand calculations; the r7 abort ratio 8.8 is the two-wire DC value at 90 mm (8.72); T-C-16 uses the full-set values and 25.6 at another built length (**superseded in r8:** "the T-C-16 abort ratio 8.8 holds at a 90 mm E1 only (up to 15.1 at 85 mm)") |''',
  tag="07/SWEEP H.23(v) row")
R('''| the r7 ratio 8.8 holds at 90 mm only; H.23(v) gives 17.80 at 85 mm |''',
  '''| the r7 ratio 8.8 is the 90 mm two-wire DC value (8.72); the 90 mm full-set value is 9.20 and H.23(v) gives 17.80 at 85 mm; r8 verification round: the bound at another built length is 25.6 (H.23(y) row (6)) (**superseded in r8:** "the r7 ratio 8.8 holds at 90 mm only") |''',
  tag="07 L.8 row")

# ------------------------------------------------------------------ H.23(y) row, J.2 item 68 additions, 0.2/0.3 rows
R('''| FR-12(b2), F.5 T1, T-C-05c, J.2 item 68 |
''',
  '''| FR-12(b2), F.5 T1, T-C-05c, J.2 item 68 |
| H.23 | **(y) r8 verification-round figures (r8, calc revision 7)** (`round4/calc/r7_calc.py` H.23(y); VIH 0.70 x 3V3 ASSUMPTION, TODO(verify: IMXRT1060CEC)) | (1) F17-F15 bridge, FLT asserted, U108 HIGH: node 1.60-1.93 V, inside the undefined band VIL 0.94-1.04 V / VIH 2.19-2.43 V (r7 without R106s <= 0.434 V, a defined LOW); (2) T3 behind one FR-41 ramp group in FIFO order: 2.329 ms at 100 kHz (misses 1.5 ms by 0.829 ms), 0.808 ms at 400 kHz; with the FR-07 r8 queue-priority rule the in-flight term is 0.470 / 0.117 ms, inside the H.23(o) 0.50 / 0.35 ms term; (3) W1/W2 lead current when the FET opens 128.3 A at 290 mm (lead peak 130 A); helix factor at OD max 1.0371 (the H.23(p) basis), at OD min 1.0311 (L' 0.401 uH/m, IN peak 33.76 V); (4) B1R face 2.50 mm against the 4.885 mm trunk: 51 % support, overhang 2.193 mm (+x) and 0.193 mm (-x); a cohesive round bundle stays at or above the face plane (0.013 mm at the +x face edge); (5) W5 air gap above the trunk 0.198-3.115 mm from y 57.00 to the ride point (28.70, 64.01); W5 bottom 19.408 mm at (28.70, 73.10); W5 minimum margin 1.866 mm at (28.70, 64.01) (requirement 10.416 mm), 4.850 mm over tab Y; (6) C205/TP27 without R276 at 1.5 MHz over E1 70.8-90 mm: 7.19 at 70.8 mm, 22.46 at 80 mm, maximum 25.47 at 81.7 mm (DC, E8 return 20 mm), above 17.80 for 78.5-85.0 mm, bounded by the H.23(k) undamped Q 25.6; omit threshold 19.5 mV p-p at TP27; TP27 limit with R276 at 1.5 MHz 268 mV; (7) T1 increment with the step-8c pre-edge read (1.849 ms at 100 kHz with t_BUF) 128.5 ms | F17-F15 level, FR-07 queue priority, B.4 D103 criterion (4), A.3 lateral support, T-F-12 W5 values, T-C-16 bound, F.5 T1 budget |
''',
  tag="H.23(y) row")
R('''(e) The T3 budget of H.23(o) excludes the pin-34 ISR latency, TODO(calibrate: T-C-06).''',
  '''(e) The T3 budget of H.23(o) excludes the pin-34 ISR latency, TODO(calibrate: T-C-06). (f) (r8 verification round) An
    F17-F15 bridge with FLT asserted and U108 H2C HIGH leaves pins 35 and 16 at 1.60-1.93 V, in the undefined band
    (H.23(y) row (1)); T-F-12 is the detector. (g) The B1R face supports 51 % of the trunk width; the design relies on the
    RTV-bound round bundle (A.3), and the T-A-06 item (8) dry fit confirms it; a wider wedge needs a part-box and
    exclusion check in H.23(s), TODO(calc). (h) T_ADC_ONESHOT of the FR-23 EX1 wait is TODO(calc) from the default
    REG2F/REG30 channel set, TODO(verify: SLUSDV2C §6.5), measured in T-D-15. (i) The published 1.359 ms T3 bound holds
    only with the FR-07 r8 queue-priority rule (H.23(y) row (2)).''',
  tag="J.2 68 f-i")
R('''  (H.23(u)-(w)), the r8 integration figures are revision 6 (H.23(x)), and''',
  '''  (H.23(u)-(w)), the r8 integration figures are revision 6 (H.23(x)), the r8 verification-round figures are revision 7 (H.23(y)), and''',
  tag="0.2 rev7")
R('''| r8-15 | **TPS26630 datasheet local:**''',
  '''| r8-16 | **Verification round (r8):** the F17-F15 bridge level is undefined with R106s (A.8, T-C-05c step 8, H.23(y) row (1)); the FR-07 queue-priority rule for a posted raise, FR-41(iii), FR-22 (xxxiii) and T-C-06 (H.23(y) row (2)); FR-43: no State-99 exit to Idle in production, so a commit requested in State 99 is lost at the reset (T-W-01, J.2 item 33, T-C-06); B.4 D103 criterion (4), a 130 A pulse for <= 1 us (H.23(y) row (3)); the FR-23 exceptions renamed EX1/EX2 (the EVM leads keep E1/E2), at most four transactions after the EX1 poll and a fixed T_ADC_ONESHOT wait, at most five per EX2 episode; T-F-03 brake and fail branch, FR-04 step 8c, the T1 increment 128.5 ms (H.23(y) row (7)); B1R lateral support by the bound bundle (A.3, PM4 (6), T-F-12, H.23(y) row (4)); W5 rests on the trunk only from (28.70, 64.01), its margins located, the FT2 re-bed releases W5 (A.3, J.2 item 62, D.4, T-F-12, T-A-09, H.23(y) row (5)); J.2 item 55 coupon mandatory, t_coupon, a mask block on the coupon, PSA residue removed (T-A-09, PM4 (2c)); IQ(ON) 1.38 mA is typical, T-C-04 in the ON and latched states, the stuck-path figures in order, FR-20 `vchg_slow_decay`; T-B-16 and H.14 wording; 0.3 r7-17 marker direction; T-C-16 uses 25.6 at another built length (H.23(y) row (6)); markers that held r8 rationale now hold only old text; J.2 item 68 (f)-(i) | CHG-R1-01, -02, -D01, -D04, -03, -04, -D03, -W01, -05, -D02, -08, -06, -07 (verification round) |
| r8-15 | **TPS26630 datasheet local:**''',
  tag="0.3 r8-16")

R('''| r8-2 | **FR-23 exception E2, the bounded FLT-LOW diagnostic read:**''', '''| r8-2 | **FR-23 exception EX2, the bounded FLT-LOW diagnostic read:**''', tag="r8-2 rename") if t.count("| r8-2 | **FR-23 exception E2,") else None

# L.8 additions
R('''| CHG-R1-W01 | decide the order and/or a plan separation | W5 above the trunk over the whole overlap, resting on it with RTV; no plan separation |''',
  '''| CHG-R1-W01 | decide the order and/or a plan separation | W5 above the trunk over the whole overlap, resting on it with RTV from (28.70, 64.01) to A1 (r8 verification round: from y 57.00 to the ride point W5 is above the trunk with a 0.198-3.115 mm gap, H.23(y) row (5)); no plan separation |''',
  tag="L.8 W01")
R('''| CHG-R1-A02 | add the datasheet |''',
  '''| CHG-R1-D03 (verification) | widen B1R to the trunk width, or bind the trunk to the face | the trunk is bound into one round bundle with RTV and bonded to the 2.50 mm face from the toe to the apex; T-F-12 measures the +x trunk edge | a widened wedge needs a part-box and exclusion recompute in the footprint interior; a cohesive round bundle stays at or above the face plane (H.23(y) row (4)) |
| CHG-R1-03 (verification) | a fixed conversion wait or ADC_DONE polling | a fixed wait T_ADC_ONESHOT, no ADC_DONE poll; four transactions after the EX1 poll | the transaction count stays fixed and the REG2F/REG30 masks are not rewritten; the duration is TODO(calc) and T-D-15 measures it |
| CHG-R1-05 (verification) | qualify the fallback bond on the mask | a second FT1-size block bedded on the coupon mask in T-A-09 step 0 | the fallback bed bonds to the mask, so step 0 qualifies both interfaces before PM4 (1) |
| CHG-R1-A02 | add the datasheet |''',
  tag="L.8 new rows")

R('''+ step 8c <= 5 ms = 126.7 ms;''', '''+ step 8c <= 5 ms = 126.7 ms, which omits the <= 1.85 ms step-8c pre-edge read (128.5 ms with it, H.23(y) row (7));''', tag="04 H.23(x) note")

new = t
# emit line-block edits
a, b = src.split("\n"), new.split("\n")
sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
ops = [o for o in sm.get_opcodes() if o[0] != "equal"]
hunks = []
for tag_, i1, i2, j1, j2 in ops:
    lo, hi, nlo, nhi = i1, i2, j1, j2
    if lo == hi:
        lo -= 1
        nlo -= 1
    while src.count("\n".join(a[lo:hi])) != 1 or not "\n".join(a[lo:hi]).strip():
        lo -= 1
        nlo -= 1
    hunks.append([lo, hi, nlo, nhi])
merged = []
for h in hunks:
    if merged and h[0] <= merged[-1][1]:
        merged[-1][1] = max(merged[-1][1], h[1])
        merged[-1][3] = max(merged[-1][3], h[3])
    else:
        merged.append(h)
edits = []
for lo, hi, nlo, nhi in merged:
    old, nw = "\n".join(a[lo:hi]), "\n".join(b[nlo:nhi])
    edits.append(dict(note="r8 verification round (0.3 r8-16): lines %d-%d" % (lo + 1, hi), old=old, new=nw))
os.makedirs(OUTDIR, exist_ok=True)
json.dump(dict(group="r8_V", edits=edits), open(os.path.join(OUTDIR, "patch.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("replacements %d, edits %d, length %d -> %d" % (len(LOG), len(edits), len(src), len(new)))
open(os.path.join(os.path.dirname(__file__), "r8V_new.md"), "w", encoding="utf-8").write(new)

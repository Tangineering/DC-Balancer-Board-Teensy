---
name: self-review
description: Run the mandated post-implementation self-review of firmware changes — the structured correctness/safety/architecture pass required by CLAUDE.md after every feature or change. Use this automatically at the end of any implementation task on teensy_controller.ino or the test suite (do not wait to be asked), and whenever the user says "review this", "self-review", "check your work", or "before we flash".
---

# Post-implementation self-review

CLAUDE.md makes this a required final step of every implementation task, like the test
suite. It exists because a past review caught a real asymmetry (a drive-cycle profile whose
natural completion left the motor running while its stop path zeroed it) plus several minor
bugs that the happy-path tests never flagged. The review is cheap; this class of bug is not.

## Step 1 — Re-read the full diff

Read the actual diff (`git diff`, or the session's edits if uncommitted), not your memory of
it. Check every hunk against this project-specific hazard list:

**Correctness**
- Off-by-one, inverted polarity (`MPPT_DISABLE` is active-LOW; `CBAL_DISABLE` LOW = balancer
  active), wrong register or scale factor (cite the datasheet/CSV in a comment).
- Stale references after a rename — grep for the old name across `.ino`, tests, PLAN.md.
- Missing `vesc.setCurrent(0)` flushes on any path that stops or abandons motor control.
- Telemetry/command struct edits without byte-count + checksum-span + version updates
  (if found, route through the `protocol-bump` skill).

**Architecture**
- Asymmetric paths: does natural completion clean up everything the stop/abort path does?
- State not reset on exit, fault, or re-entry (integrators, phase machines, `ag105Configured`,
  wheel-speed buffers).
- Blocking calls (`delay()`, unbounded waits) that would stall `detectFaults()` — State 0/3/99
  are non-blocking phase machines for exactly this reason.

**Safety (the dangerous failure modes on this board)**
- Switch sequencing: `FC_CHARGE_ENABLE` only via `assertFcChargeEnable()`; `BT_BUS_ENABLE`
  and `REGEN_ENABLE` must be LOW first. Never leave a regen path pointed into a disabled
  boost (TPS61288 back-feed).
- Hot-plug: no path may close a `*_BUS_ENABLE` or `MOT_PWR_ENABLE` onto a mismatched node —
  the guards are `busHotPlugUnsafe()` / `motPwrHotPlugUnsafe()` / `assertMotPwrEnable()`;
  new code goes through them, never around them. Boosts have died five times to this.
- Any new path that could leave the motor running, a boost enabled into a collapsed rail,
  or an illegal switch combination latched into Idle.

**Docs**
- Comments that now contradict the code; CLAUDE.md/PLAN.md addenda that the change supersedes.

## Step 2 — Report findings

Report to the user grouped by severity — correctness/safety first, then architecture, then
doc/polish — each with a concrete recommended fix. Report even the minor ones; "no findings"
is a valid result only after genuinely completing Step 1.

## Step 3 — Fix and re-test

With the user's go-ahead: apply the fixes, and for every *behavioural* fix add or extend a
host-native test in `test/test_main.cpp` that would have caught it. Then run the `test`
skill (both `-DBENCH_TEST=0` and `=1` builds) and confirm all tests pass before closing out.

# HIL suite run 2026-08-30 18:14 — per-scenario findings

First full `run_hil_suite.py` pass on fw v23 (any-fault recovery). This file is the
orchestrator's analysis ledger, written alongside the suite's own REPORT.md; one section
per scenario, appended as each investigation agent reports. Suite verdicts quoted from
results.json; deep-dive findings from per-CSV analysis agents.

> **FINAL SUMMARY at the end of this file.** Suite completed: 39 runs, suite-reported
> 6 PASS / 33 FAIL. After per-run investigation: **23 of the 33 FAILs are false**
> (grace-union artifact), 3 of the 6 PASSes are rubber-stamps, and the board's firmware
> behaved correctly in every single run.

## Suite verdict snapshot (as of 18:20, run still in progress)

| Scenario | Suite verdict | Failed checks | Warm resets |
|---|---|---|---|
| steady | PASS | — | 0 (first run) |
| step-load | FAIL | no_unexpected_fault: PI_TIMEOUT/HIL_LINK latched | grace @0.5 s |
| sag | PASS | — | grace @0.5 s |
| comm-loss | PASS | — | grace @0.5 s + designed in-run @7.5 s |
| drive | FAIL | no_unexpected_fault: PI_TIMEOUT/HIL_LINK latched | grace @0.5 s |
| charge-cruise | FAIL | no_unexpected_fault: OC_FC + PI_TIMEOUT/HIL_LINK latched | grace @0.5 s |
| charge-regen | FAIL | no_unexpected_fault: OC_FC + PI_TIMEOUT/HIL_LINK latched | grace @0.5 s |
| charge-fault | PASS | — | grace @0.5 s |

Cross-cutting observations (orchestrator, pre-analysis):
- The fw v23 between-run recovery mechanism is doing its job: every run after the first
  starts with the expected grace-window warm reset, and comm-loss executes its designed
  mid-run recovery and passes. Sequential runs without power-cycles are confirmed working.
- Four runs latched faults mid-run. The PI_TIMEOUT/HIL_LINK union in step-load/drive means
  the injection link went stale DURING those runs; OC_FC in the two charge scenarios points
  at the hifi charger-path currents. Both are under per-scenario investigation below.

---

## Per-scenario findings

(appended as analysis completes)

### steady — clean baseline, expected behavior (HIGH confidence)

Run 1 on the freshly powered board: no warm reset, bring-up FC/BT bus → BT_SEQUENCE →
MOT_PWR pre-charge → **Idle at t=138 ms**, then 29,862 rows of unchanged state. Link
perfect: 30,000/30,000 frames, seq wrap-aware 0 irregularities, 1 blank row (pre-first-
frame tick only). Steady window: V_bus 15.8144 V flat (1.16% below nominal 16.0, inside
band), V_fc 12.9156, V_batt 7.840 drifting −2.4 mV over 28 s in lockstep with soc −0.00033
(coulomb counting live), I_fc = I_batt = 0.0829 A (perfect 50/50 open-loop droop split at
0.166 A total — under the 0.60 A closed-loop gate, as designed). Charger unpowered
(V_chg = 0, ag105_status 0x00) — correct, no charge path open. hifi engine: median 61 kHz
substeps; 1.6% of rows dip to 3.5–13 kHz on host descheduling with zero visible plant
disturbance. Zero faults, zero events. Characterization notes: `achieved_rate` check is
SKIPPED under --dash (documented F3 behavior — the suite is running with the dashboard);
mdac telemetry words carry the 0x1000 LOAD_UPDATE command nibble (5316 = 0x1000|1220 →
gain 0.298) — mask before reading. **This is the reference baseline; no action.**

### step-load — suite-artifact FALSE FAIL; run itself clean (HIGH confidence)

**There was no mid-run link stall.** The board was already latched 0x8010 at this run's
first observation frame (t=0.0013 s) — the inherited settle latch from the end of `steady`,
exactly as fw v23 designs it. Warm reset at t=0.500, Idle at t=0.616, then 29,384 rows of
state 1 / fault 0 to run end. State histogram: 1×29384, 99×499, 0×116. Sidecar:
`warm_resets_mid_run: 0`, `final_state: 1`, `final_fault_flags: 0`.

- Link quality: 30,000/30,000 tx frames, 29,999 rx, 0 send errors, max tick overrun
  2.0 ms, max CSV Δt 2.67 ms — nowhere near the 50 ms hold or 250 ms stale thresholds.
- hifi engine: mean 61.4 kHz substeps, min 8.1 kHz on isolated ticks; 0 events, no
  numeric fault. The +1.2 A aux step at t=5.000: V_bus 15.81→15.43 V (−0.38 V), clean
  50/50 split (I_fc = I_batt = 0.68 A), settled in ~5 ms. Uncorrelated with anything.
- Lost coverage: 1.66% (the pre-stimulus 0–0.5 s window only).

**Root cause of the FAIL:** `compute_metrics()` (run_hil_suite.py:466) accumulates
`fault_bits_seen` from t=0 with no grace-window exclusion; `judge_warm_resets()` (:603)
DOES apply the 2.0 s grace. The two checks disagree by construction on every run that
inherits the previous run's settle latch — i.e., every run after the first. `drive`'s FAIL
is the same artifact; charge-cruise/charge-regen carry the same 0x8010 component PLUS a
genuine OC_FC (separate investigation).

**Recommended fix (suite):** a post-grace fault union for `no_unexpected_fault`, guarded to
apply only when the grace-window bits are exactly 0x8010 AND the board demonstrably
recovered (state 99→0→1 inside the window); REPORT.md keeps printing the full union with a
note. Operational reading for THIS session: step-load and drive are PASSes by sidecar
evidence (`final_fault_flags: 0`, `warm_resets_mid_run: 0`).

### sag — UV chain validated end-to-end on hardware (HIGH confidence, PASS confirmed correct)

The scenario's −5.000 V sensor-path step lands at t=5.0003 (V_bus 15.8144 → 10.8144 V
exact). Measured firmware chain: transient UV indication bit 0x0100 at +1.9 ms (loop
latency), **latch at +19.887 ms of dwell vs UV_BUS_DWELL_LATCH_MS = 20.0 ms design —
0.6% agreement**, no leak engagement (V_bus never re-crossed 12.0 V — clean accumulation).
Teardown measured for the first time: switch masks 0x34 → 0x28 → 0x20 decode exactly to
doState99() phases 0/1/2 with ~9–10 ms inter-phase gaps (the 10 ms TODO(calibrate)
floors); the transient FC_CHARGE-on sample is the documented VBUS-cap drain, not an
anomaly. Board stayed latched 0x8100 to run end with `warm_resets_mid_run: 0` — the fw v23
in-run latch contract held (no ≥1 s link gap mid-run). hifi solver: 3 sw_ring events at
the teardown switch openings (peaks 17.8/15.4 V, over_absmax false — normal disable
ringing); substep dips to 3.6 kHz at the topology-change transients, no numeric fault;
V_bus decays to exactly 0 after isolation (correct — no source or load on the node).
Cosmetic only: the results.json check text folds the pre-frame 0x0010 wait-gate bit into
the "observed" fault union description. **H2 satisfied; no action.**

### comm-loss — fw v23 run-boundary recovery VALIDATED ON HARDWARE, to the tick (HIGH confidence)

Every stage of the mechanism measured against prediction:
- Last frame t=4.9994; latch at **5.251129 s** vs predicted 5.2494 (HIL_ZERO_MS) — Δ 1.7 ms
  (loop jitter). Fault exactly 0x8010.
- Teardown phases 0→1→2→3 in **19.08 ms**, correct switch ordering, with the REGEN
  bleed-down physically visible (V_bus 15.8→0 V over the phase-1 window).
- Observation stream UNBROKEN through the whole 2 s gap (~1730 rows of state 99) — the
  board streams independently of the dead injection link, as documented.
- Boundary (1000 ms, anchored at last frame) seen at 5.999; frames resume 7.000293;
  **recovery measured 7.500100 s vs predicted 7.500293 s — Δ = 193 µs, within one tick.**
- Warm-reset bring-up State 0 → Idle in **115.79 ms**, bit-for-bit identical (same switch
  sequence, same duration) to the cold-boot bring-up earlier in the same file —
  hilWarmReset() is a deterministic software-state-only restore, proven.
- Sidecar exact: warm_resets [0.5 grace, 7.5 mid-run]; suite's REQUIRES-exactly-1 check
  passed. 3 sw_ring events at the teardown switch openings only; no solver stress.
- Note (non-anomaly): results.json's fault union 0x8110 includes UV_BUS inherited from
  sag's carryover latch in the grace window; the scenario's own fault was strictly 0x8010.

**H3 objective fully met. No action.**

### charge-fault — PASS is a RUBBER-STAMP; scenario never reached its stimulus (HIGH confidence)

The run latched **OC_FC at t=5.758 s** — 14.25 s before the scripted t=20 s charger-fault
injection — and sat latched for the remaining 34.2 s. The `fault_allowed` check accepted
the unrelated latch signature, so the suite PASSed a run that never exercised its test
target (GENSTAT fault decode / charger-loss reaction). What it DID validate incidentally:
the first powered-Ag105 GENSTAT progression on hardware is clean and textbook —
0x00 (BatteryDisconnect) → 0x04 (BringUpCharge, t=5.024, first input power) → 0x42 →
0x5A (Charging + MPPT_EN + PWR_TRACK) — and after the OC teardown opened FC_CHARGE the
Ag105 correctly reverted to 0x00 with I_charge → 0.

**Critical evidence for the OC_FC family:** this scenario has NO drive/cruise load, yet
I_fc still crossed LIMIT_I_FC_MAX (1.4 A) during the charging ramp, at I_charge = 1.115 A
(still climbing toward the 2.5 A configured ceiling). So the OC_FC in charge-cruise /
charge-regen is NOT load-dependent — any FC-path charging ramp toward useful charge
current trips 1.4 A. Structural conflict between LIMIT_I_FC_MAX and the Ag105 charge
profile as modeled. (Energy-bookkeeping question for the sibling agents: I_charge 1.115 A
at ~7.86 V ≈ 8.8 W out vs the FC-path input draw implied at ~15.8 V — the implied charger
efficiency looks low; verify whether the SIM's charger input-draw model is physical before
treating 1.4 A as a real limit conflict.)

**Recommended fixes:** (a) resolve the LIMIT_I_FC_MAX-vs-charging conflict — an operator
decision (limit derivation vs charge-current ceiling vs sim draw model), flagged not
prescribed; (b) tighten charge-fault's pass check to require surviving in State 2/3 to
t≥20 s before accepting a latch as the intended one — as written it cannot distinguish
"GENSTAT fault handled" from "board already dead".

### charge-cruise — OC_FC is REAL (in-model), driven by two sim fidelity gaps + a genuine scenario/hardware conflict (HIGH confidence)

Timeline: grace recovery @0.5 s → Run @3.0 → cruise 1.2 m/s → charge_goal @8.022
(`assertFcChargeEnable()` measured enforcing its guard: BT_BUS low 1 ms BEFORE FC_CHARGE
high) → Ag105 GENSTAT 0x00→0x04→0x42→0x5A → I_charge τ=0.4 s ramp → **OC_FC at t=8.7221,
I_fc = 1.4065 A**, single-sample trip on a smooth 190 ms monotonic ramp. Not a solver
artifact: bus bookkeeping at the trip closes to 9 mA (aux 0.150 + motor 0.286 + charger
0.962 = 1.398 vs 1.4065 measured); substeps healthy; both events benign en_low rings.
FC-side referral: 1.77 A @ 12.18 V = 21.5 W — the H-20's entire 20 W rating. The limit
fired exactly where the modeled stack ran out.

**Two sim modeling defects found:**
1. `hil_electrical.py:1256` stamps the Ag105's OUTPUT current (into the 7.9 V pack) as the
   INPUT draw on the 12.9 V VCHG node — power not conserved, charger bus draw overstated
   ~1.47×. Fix: `i_charge·V_batt/(V_chg·η_chg)` with an ETA_CHG TODO(verify).
2. No MPPT input-power limiting: the sim ramps to 2.5 A gated only on V_chg ≥ 8 V; the
   real Ag105 is an MPPT charger that would throttle to the stack's MPP. Until modeled,
   EVERY hifi charge scenario overloads the FC path by construction. Highest-value
   follow-up — it decides whether this OC is bench reality or sim artifact.

**Even corrected, the conflict stands:** at the full 2.5 A target the physical FC draw is
~2.16 A vs LIMIT_I_FC_MAX 1.4 A (which itself carries TODO(verify: H-20 datasheet)).
Cruise is only 0.29 A of it — no cruise speed makes 2.5 A of charging fit. Options flagged
for the operator (not prescribed): lower charge profile (a firmware lazy-config change),
a charge-idle scenario (0.15+0.96 = 1.11 A fits), revisit the BT_BUS-low-during-FC-charge
exclusivity, or re-derive the limit from the real H-20 datasheet.

**Incidental finding (own follow-up):** at 8.581–8.588 the share loop armed (I_tot crossed
0.60 A) and railed the MDACs 5316/5316 → 8163/4813 in 7 ms chasing the BT channel that
`assertFcChargeEnable()` had just physically disconnected — measured share pinned at 1.0 by
construction. Deepened the bus sag 15.4 → 13.0 V. Check whether shareIso/shareSpCut cover
the FC-charge handoff.

**PI_TIMEOUT in the verdict = the same grace-union artifact** (0x8010 only before t=0.5,
never after; the run's own fault is strictly 0x8001).

**What the first powered-Ag105 run validated:** open-on-intent (no deadlock), the ordering
guard on real hardware, chargerHasPower → full Table-6 GENSTAT progression with correct
500 ms settle, lazy config-by-fiat + ag105IsReady gating the MPPT release (driven HIGH
33 ms after Charging appeared — first exercise of that gate ever), I_charge telemetry end
to end, phased teardown, and the negative path: a genuine OC_FC did NOT auto-recover.

### charge-regen — same OC_FC class, sharper mechanism; regen objectives 100% unreached (HIGH confidence)

The OC latched at t=5.585 (I_fc 1.4115 A), 6.4 s BEFORE the first braking entry — the run
never reached regen. Mechanism sharper than charge-cruise: the scenario's t=5.0 timeline
entry commands `v_setpoint 1.5` AND `charge_goal 1.0` **simultaneously**, so the drive
controller rails +12 A for the acceleration while `assertFcChargeEnable()` (by design)
removes BT from the bus — the FC channel alone carried the accel ramp (0.083→0.92 A) plus
the Ag105 bring-up (+0.49 A in 61 ms). I_batt = 0.000 the whole window. The bus was
diverging (−16.4 V/s at the latch; UV_BUS was ~80 ms behind — OC won the race). Physical
sanity confirmed: FC terminal drop implies 0.445 Ω vs the model's 0.447 Ω spec (0.5%);
stack power 21.6 W vs the H-20's 20 W rating. **Firmware behaved correctly on every count**
— mutual-exclusion audit over 45,000 samples: zero violations, REGEN and FC_CHARGE never
both high; single-sample OC latch; correct phased teardown.

Validated: fw v23 sequential recovery; assertFcChargeEnable ordering under live load with
the share loop releasing its BT claim; Ag105 lazy bring-up timing (BRINGUP +8 ms, CC at
+507 ms = AG105_SETTLE_S); MPPT release gated on readiness with correct active-LOW
polarity; the fw v22 regen-node topology (V_rgn tracks V_bus within 0.03–0.05 V closed,
holds 8.6 V open). Lost: ALL five setpoint steps, all four regen entries, the regenActive
branch (zero executions), MPPT-during-braking, the chopper clamp, the regen→charger path —
87% of the run.

**System-level finding for the operator:** FC-path charging and hard acceleration are
mutually incompatible on this hardware BY DESIGN (single-source bus during FC-charge).
Re-run guidance: stagger charge_goal to t=8 s after cruise establishes, v_setpoint
0.8–1.0 m/s — restores regen coverage without touching any limit. LIMIT_I_FC_MAX 1.4 A
remains TODO(verify: H-20 datasheet) and is now the binding constraint on three of eight
scenarios; also note the bus-side referral assumed a 16 V bus (at the sagged 13 V the same
1.4 A is a different stack current). Signals to watch on the re-run (never yet observed on
hardware): REGEN high with FC_CHARGE low, MPPT_DISABLE LOW during braking, a chopper event
near 18.1 V, I_charge nonzero via REGEN+MOT_PWR.

### soc-depletion — rubber-stamp PASS; endurance objective never reached (HIGH confidence)

Latched **OC_FC at t=5.001** (I_fc 1.4705 A, single-sample) and sat dark for the remaining
645 s of the 650 s run. Mechanism: the pi_timeline's `power_share_setpoint = 0.0` step and
the scenario's own `+3.0 A` aux step were authored independently and land on the SAME
t=5.0 tick — the new ~3.15 A draw splits evenly across both boosts for one tick before the
droop reapportions, and 1.47 A > LIMIT_I_FC_MAX. The fault is OC_FC, not the promised
UV_BATT; V_batt (7.28–7.30 V) never approached LIMIT_V_BATT_MIN 6.2 V; the Rs(SOC) knee
below 15% SOC was never exercised (soc moved 0.15000 → 0.14995). The suite PASS is the
same permissive `FAULT_ALLOWED` pattern as charge-fault — the check never compares the
observed bit against UV_BATT.

**What it DID validate (genuinely):** 650 s of continuous 1 kHz link integrity — 650,000
tx frames, zero loss, zero malformed, max overrun 9.3 ms — the longest continuous HIL
session on record. But against an idle plant after t=5, not sustained electrical load.

**Recommended fixes:** (a) stagger/ramp the t=5.0 share step vs the aux step in
hil_plant_sim.py so the depletion walk can run; (b) tighten soc-depletion's check to
require UV_BATT specifically (same fix family as charge-fault's stimulus-time gate).

### ems-drive-cycle — FALSE FAIL (inherited latch); the run itself is the best drive validation to date (HIGH confidence)

`final_fault_flags: 0`, `final_state: 1`, full 60,000 ticks at 999.98 Hz. The OC_FC in the
verdict is soc-depletion's carried-in 0x8001 (+0x0010 from the dead settle gap = 0x8011,
present only in rows t<0.5); the fw v23 any-fault recovery cleared it at 0.5 s — including
proof it recovers from a non-0x8010 union, the exact fw v23 widening, working. Run content
(52 s in State 2): median |v_act−v_sp| **0.5 mm/s**, p95 6.1 mm/s; share I_fc/I_tot median
**0.5000** (range 0.4998–0.5003); I_fc peak 0.380 A (3.7× margin); board current peak
6.12 A (never railed); V_bus 15.63–15.81. Matches the earlier simple-model bench run —
NO hifi fidelity gap on the drive path. Also isolates the soc-depletion trip precisely:
one 1.0 ms sample at I_fc 1.4705 A — **5 mA over the limit** — with the split perfectly
even (I_batt 1.4724 A); FC trips only because its limit (1.4 A) is under half the step
while BT's is 3.0 A. Suite-fix recommendations identical to step-load/drive, plus: the
check's "union over the run" wording should distinguish carried-in from in-run bits.
Operator question flagged (not prescribed): should the single-sample OC check get a dwell
treatment like UV for sub-ms charge-entry inrush, given a 5 mA/1-tick overshoot latches
the board?

### handoff-sag — OC_FC preempted the test; TP0178 question remains OPEN (HIGH confidence on trace, question unresolved)

Setup worked as intended: share rail 1.0 at t=6 opened BT_BUS (sw_ring i_cut 0.083 A);
BT then sat as a standby diode. But the t=20 perturbation (+1.5 A aux) drove the FC-only
channel 0.36 → 1.776 A in 1.3 ms — **OC_FC latched at +2.2 ms**, with V_bus still 13.05 V
(1.05 V ABOVE the UV floor). The teardown then dropped the bus; the reactive-pickup
dynamic, the UV dwell path, and the share-cut latch never got to act. BT_BUS was never
re-asserted (whether firmware even has a reactive-pickup path stays undetermined from
this run). The PASS is the same permissive FAULT_ALLOWED pattern. Solver clean (2 benign
sw_ring events, no over_absmax).

**Recommended fix:** shrink the perturbation to sag-without-OC (e.g. +0.8 A → ~1.16 A on
FC, inside the 1.4 A limit but deep into droop) so the handoff/UV/dwell dynamics can
actually develop; tighten the check to assert the UV_BUS/pickup class, not any fault.

### scp-inrush — three defects at once; the SCP objective is structurally unreachable (HIGH confidence)

(1) The 0x0010 half of the union is the inherited settle latch (predecessor `bringup`
ended clean; the link death between runs latched 0x8010, recovered at 0.501). (2) The
OC_FC half is REAL and CORRECT: at t=8.0 the scenario applies a 6 A V-MOT load — which
exceeds LIMIT_I_FC_MAX + LIMIT_I_BT_MAX = 4.4 A at ANY share split — I_fc hit 2.6 A on
the first loaded tick and the board protected itself. A pass signal misreported as
failure; scp-inrush has no FAULT_ALLOWED entry. (3) Scenario-design defect: the RT1987
foldback/SCP branch exists only in the SOFT state (hil_electrical.py:807), and MOT_PWR
reached ON at t≈0.62 during bring-up — the scenario's own comment says to close MOT_PWR
after t=8 ("bench 'M' or a Run entry"), but the unattended run has no pi_timeline/EMS, so
there is no mechanism to cycle the switch. **Zero scp_cut/fold events fired; the run was
a bus overload, not an inrush test.**

**Validated in passing:** the staged bring-up peaked at 0.634 A per channel — consistent
with the 2026-08-30b SOFT-state physics fix, now confirmed with a real board attached.

**Recommended fixes:** the shared grace-union fix; make the scenario cycle MOT_PWR with a
~2.5 A load present at close (folds+SCP-cuts at ~1.25 A/channel, under the OC limit, so
the sim mechanism gets to fire before the firmware faults) — needs a suite-driven mode_cmd
or EMS sequence; and gate its pass on the events sidecar containing `scp_cut` rather than
on fault flags.

### bringup — pure false FAIL; staged bring-up is EXEMPLARY on hardware (HIGH confidence)

Only two fault values in the whole file: 0x8011 in rows t<0.501 (inherited — from
handoff-sag's real OC latch + the settle-gap 0x0010; NOT from ems-drive-cycle: run order
is handoff-sag → bringup → scp-inrush), and 0x0000 for the remaining 29.5 s. Post-grace
union exactly 0. The staged bring-up (114 ms total): P0 pre-charge 39 ms peak I_fc
**0.223 A** (v22b fix predicted ~0.22), P1/P2 dwell 51 ms, P3 motor-node connect 24 ms
peak **0.473 A** (predicted ≤0.47), Idle at 0.615 — the SOFT-state physics fix's smoke
numbers corroborated on hardware to three decimals. Whole-run I_fc max 0.474 A = 34% of
limit. Also proven: fw v23 recovers from a 0x8011 union (the exact widening this round
shipped — fw v22 would have latched forever here).

**Artifact scope now formalized:** four PURE false FAILs (bringup, step-load, drive,
ems-drive-cycle — post-grace union 0x0000 in each); three real in-run OC_FC latches
(charge-cruise, charge-regen [+charge-fault, soc-depletion, handoff-sag under permissive
PASSes], scp-inrush). The systematic signature: every run whose predecessor ended 0x8001
opens on 0x8011; every run whose predecessor ended clean opens on 0x8010.

### drive — same suite-artifact FALSE FAIL, plus the run is structurally VACUOUS (HIGH confidence)

Identical signature to step-load, proven deterministic: both runs latch/recover at
IDENTICAL run-relative rows (1–499 latched 0x8010 inherited from the settle pause, warm
reset at t=0.5003 — exactly HIL_RECOVER_DEBOUNCE_MS, Idle at 0.616) despite being 106 s
apart in wall clock. Rules out host-periodic processes and scenario load; it is
run-entry-correlated by design. Link flawless (worst Δt 2.7 ms, 999.97 Hz, 0 send errors);
substep min 9.8 kHz, post-recovery.

**Second finding:** `SCENARIOS['drive']` is the OPERATOR-driven H4 scenario
(`pi_timeline_entries: 0` — "the operator drives the firmware by hand over USB"). Run
unattended, it never commands anything: `cmd_v_sp` blank for all 30,000 rows, board
`current` 0.000 A throughout, v_actual 0. The scripted run validates only Idle+link health
— the Youla drive loop was NOT exercised. Unattended drive-loop coverage belongs to
`ems-drive-cycle`.

**Recommended fixes:** (A) the same grace-window fault-union fix as step-load, with the
same exactly-0x8010-and-recovered guard; (B) mark `drive` operator-required in the
scripted plan so it renders SKIPPED instead of scored; (C) [future, protocol] `error_code`
on the observation frame would make the excusal a direct read instead of an inference. No
change warranted to HIL_ZERO_MS / debounce / substep / process priority — all margins met
with orders of magnitude to spare.

### Replay half (26 runs) — 19 pure false FAILs; the half is structurally unsound vs fw v22+ (HIGH confidence)

Census: all 26 recovered from the inherited settle latch at t≈0.500 and re-ran the staged
bring-up; **23/26 brought up successfully and sat in Idle the entire run** (replay mode
constructs no commander, so mode_cmd never arrives — no replay reached State 2, and
`current ≡ 0.000` everywhere, making every current-shape check vacuously true).

- **Class A — 19 runs, pure inherited false FAIL** (post-grace union 0x0000): ML0137/140/
  144/146/149/151/153/164, TP0170/171/176/178/201/210, WP0197, YP0152/166/196, YP0214
  (whose 0xA010 was ML0217's INIT_FAIL inherited through the settle gap — and its recovery
  proves fw v23 handles a 0xA010 union).
- **Class B — real in-run faults, all correct firmware behavior:**
  - ML0165/ML0169/ML0203/WP0097: OC_FC latches at the exact instants the RECORDED bench
    traces exceed 1.4 A (peaks 1.52/1.88/2.11/3.60 A). ⚠️ Four recorded bench runs
    routinely exceed LIMIT_I_FC_MAX — invisible on the bench because BENCH_TEST compiles
    OC out; a production vehicle build would latch on each.
  - ML0217: genuine INIT_FAIL — the log was RECORDED WITH A DARK BUS (V_bus ≈ 0 for all
    38 s), so bring-up P0 times out at exactly 300 ms. A log-selection issue, not firmware.
  - TP0010/TP0053 (UV deviation trio): BLG v1/v2 carry NO V_fc/V_batt/V_rgn fields —
    replay injects 0.0 by construction → P3 (MOT_CONNECT) can never see V_rgn track V_bus
    → MOT_HOTPLUG at 1.091 s → board dark and un-armable when the recorded UV collapse
    arrives. Replay-structural, NOT a UV-filter regression.
  - WP0097's UV check: the recorded dip provides 18 ms dwell vs the 20 ms latch and the
    log ends mid-dip — not a valid stimulus for the current filter (suite already words
    this honestly).

**Structural verdict:** open-loop BLG playback vs fw v22+ closed-loop staged bring-up is a
category error — the 23 "successful" bring-ups passed only because those recordings happen
to contain an already-energized bus. Ranked fixes: (1) post-grace fault union (19/26
become PASS on this alone); (2) gate replay checks on reaching State 1 and report
"bring-up failed at phase N" honestly; (3) synthetic bring-up preamble (~1.5 s healthy
rails with V_rgn following the board's own MOT_PWR) before the recorded trajectory — the
only route that makes BLG v1/v2 logs runnable; (4) reclassify ML0217 as a deviation entry
expecting INIT_FAIL; (5) retire WP0097 from the UV trio; (6) decide the half's purpose —
add a commander or relabel it fault-decision-only and delete the vacuous current checks.

---

## FINAL SUMMARY

### Corrected scoreboard (suite said 6/39 PASS)

| Class | Runs | Count |
|---|---|---|
| Genuinely clean + meaningful PASS | steady, comm-loss, sag | 3 |
| Clean run, FALSE FAIL (grace-union artifact) | step-load, drive*, bringup, ems-drive-cycle + 19 replays | 23 |
| Rubber-stamp PASS (objective never reached) | charge-fault, soc-depletion, handoff-sag | 3 |
| Real in-run fault, correct firmware response | charge-cruise, charge-regen, scp-inrush, ML0165/169/203, WP0097 | 7 |
| Structural replay failures (log/format, not firmware) | ML0217, TP0010, TP0053 | 3 |

*drive is additionally vacuous unattended (operator-in-the-loop scenario).

**The firmware was correct in all 39 runs.** Zero power cycles were needed across the
entire ~35-minute suite — the goal fw v22/v23 were built for, achieved.

### What the HIL system PROVED today (hardware firsts)

1. fw v23 any-fault run-boundary recovery: validated to the tick (comm-loss mid-run
   recovery Δ=193 µs from prediction), including recovery from 0x8011 and 0xA010 unions.
2. 39 sequential runs, ~35 min, zero manual intervention; warm-reset bring-up bit-for-bit
   identical to cold boot.
3. UV_BUS dwell filter: 19.887 ms measured vs 20.0 ms design (sag).
4. Staged bring-up currents: P0 0.223 A / P3 0.473 A — the 2026-08-30b SOFT-state sim fix
   corroborated to three decimals with a real board.
5. First powered Ag105: full Table-6 GENSTAT progression, lazy config-by-fiat,
   ag105IsReady-gated MPPT release, open-on-intent without deadlock,
   assertFcChargeEnable() ordering under live load.
6. Drive loop on hifi: median tracking error 0.5 mm/s, share 0.5000, no rails.
7. 650 s continuous 1 kHz link, 650,000 frames, zero loss (longest HIL session on record).
8. State-99 teardown phases measured on hardware (9–10 ms dwells, correct ordering,
   REGEN bleed-down physically visible).

### Fixes needed for future runs (ranked)

**Suite (tooling — highest value):**
1. Post-grace fault union for no_unexpected_fault/no_fault (guarded: excused only when the
   grace bits cleared via an observed warm reset) — converts 23 false FAILs; report
   carried-in bits separately.
2. Replace the FAULT_ALLOWED rubber-stamps with specific expected-fault + stimulus-time
   assertions (charge-fault: survive to t≥20 in Run; soc-depletion: require UV_BATT;
   handoff-sag: require the UV/pickup class; scp-inrush: require scp_cut in events).
3. Mark `drive` operator-required (SKIPPED when unattended).
4. Replay half: state-1 gating + synthetic bring-up preamble + ML0217/WP0097
   reclassification + purpose decision.

**Simulator (model fidelity):**
5. Charger input-draw: stamp physical input current (i·V_batt/(V_chg·η)) not output amps —
   currently 1.47× overstated.
6. Ag105 MPPT input-power limiting — until modeled, every hifi charge scenario overloads
   the FC path by construction. Decides whether the OC_FC family is bench-real.

**Scenario design:**
7. Stagger coincident stimuli (soc-depletion's t=5.0 double step; charge-regen's
   simultaneous accel+charge command); shrink handoff-sag's step to sag-without-OC
   (~+0.8 A); scp-inrush needs MOT_PWR cycling to reach the SOFT-state fold.

**Operator decisions (flagged, not prescribed):**
8. LIMIT_I_FC_MAX 1.4 A is now the binding constraint on every charging scenario AND is
   exceeded by four recorded bench traces (up to 3.6 A) — its derivation is
   TODO(verify: H-20 datasheet), and the 16 V-bus referral assumption matters at sagged
   bus voltages. Related: should the single-sample OC check get a dwell treatment like UV
   (a 5 mA/1-tick overshoot latched soc-depletion)?
9. System-level: FC-path charging and hard acceleration are mutually incompatible by
   design (single-source bus during FC-charge). Cruise+charge scenarios must respect it
   or the design must change.

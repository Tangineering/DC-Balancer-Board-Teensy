---
name: rosbag-agent-analysis
description: Fan out parallel read-only analysis agents over the Raspberry Pi's ROS 2 rosbags (logs/rosbags/, .mcap, 50 Hz /vehicle_state + /ems_command), one hypothesis-directed brief per run family or question, then synthesize in the main session. Use whenever new Pi bags arrive or the user asks to analyze rosbags, Pi logs, EMS runs, sweep/SDP/simple runs, or a vehicle-level symptom (regen, FC delivery, faults) seen on the Pi side ("analyze the new bags", "what do the rosbags say about regen", "fan out agents over the Pi logs"). Analysis-only — firmware fixes go to orchestrated-feature afterward. For the Teensy's own 1 kHz SD logs (.BLG) use benchlog-agent-analysis instead.
---

# Rosbag agent analysis round

The Pi-side counterpart of `benchlog-agent-analysis`. Same structure (scout, hypothesis
split, 7-part brief, fixed report skeleton, streaming synthesis), different instrument:
a bag is the **Pi's 50 Hz view** of the Teensy, plus what the EMS asked for. It sees
vehicle-level behaviour across whole drive cycles and EMS runs; it cannot see anything
faster than 20 ms, the VESC current, or the firmware version. First used 2026-11-04 on the
student's 22 bags (2026-09-07 .. 10-30) for the "regen returns no charge current" round.

## When to use which instrument

| Question | Bag (this skill) | BLG (benchlog skill) |
|---|---|---|
| Did a switch/fault/command happen during a run, and when | yes | yes |
| Durations under ~40 ms, edge ordering, controller dynamics | no (trap 1) | yes, 1 kHz |
| What the EMS commanded vs what was delivered | yes | partly (no EMS) |
| Firmware version | no (trap 3) | yes, header |
| Drive-cycle / multi-minute trends, FC degradation across dates | yes | rarely |

If a finding hinges on sub-20 ms timing, say so and name the BLG capture that would settle it.

## Stage 0 — Orchestrator scout (never skipped)

1. Read `references/bag-conventions.md` (this skill) and `logs/rosbags/README.md` (bag
   index, firmware date bounds). Check `pip show mcap-ros2-support`; install
   `mcap mcap-ros2-support` if missing.
2. **Run the scout** — one row per bag and a cached array per bag for the agents:

   ```
   python3 tools/rosbag_analysis/scout_bags.py logs/rosbags/rosbag_* --npz --cache <scratchpad>/cache
   ```

   (`--json` for the full record: topic widths, switch-bit occupancy, regen episode
   counts, I_charge / V_rgn / V_chg while REGEN is open, charger_status values, faults,
   error codes, command ranges.) Topic widths flag layout changes (e.g. `/ems_diagnostics`
   7 vs 9 elements = different EMS node versions). New bags not yet in the README index:
   add rows to `logs/rosbags/README.md` with their firmware bound.
3. **Bound the firmware per bag** from dates (git log of the `.ino`, the ledger
   `docs/firmware-versions.md`, the student/operator notes). Every brief carries the
   bound; never assume a batch is one build.
4. Quick scan in-session (throwaway numpy over the `.npz`) aimed at the operator's
   complaint, so each brief carries a specific hypothesis. Grep the firmware for the exact
   mechanism and constants under test and verify every number you put in a brief.
5. Announce the fan-out plan (agent count, split) in one short message, then dispatch.

## Stage 1 — Fan-out design

- **Split by question and run family:** faulted bags (forensics), the symptom under
  investigation (e.g. regen: every episode and every decel), sweep/share-tracking
  baselines, cross-date trends (FC health, battery). Target 3–6 agents.
- **Pair bag agents with firmware-reading agents when the symptom is a mechanism**
  (regen round: one agent traced the signal chain through the `.ino`, schematic and
  datasheets while another walked every episode in the bags). The bag agent finds WHERE the
  chain breaks; the firmware agent finds WHY and what can be changed.
- Opus for mystery/fault/mechanism briefs; Sonnet acceptable for clean-sweep baselines.
- Launch all agents of a wave in one message, background, `general-purpose`.

## Stage 2 — The brief (7 parts, ~4–6 kB, self-contained)

1. Role + one-line system description (board, bus, sources, VESC + flywheel, Pi EMS).
2. Sandbox: read-only on the repo, scratch dir named, final message = report.
3. Interpreter: `python3` with numpy / scipy / matplotlib / mcap_ros2, no pandas; the
   cache path and keys (`vs_t, vs, ec_t, ec, VS, EC`); other topics read from the `.mcap`
   via `scout_bags.load_bag()`.
4. Firmware context with exact constants and code locations (file:line), and the
   firmware bound for these bags.
5. Expectations / baselines the bags are judged against (design numbers, previous runs).
6. **YOUR BAGS** with the scout row pasted in and a per-bag hypothesis.
7. "Read `.claude/skills/rosbag-agent-analysis/references/bag-conventions.md` first", plus
   inline only the traps the round depends on.

Then numbered **TASKS** with the falsifiable discriminator first (regen round: "does REGEN
ever stay up >= 500 ms, the Ag105 settle time? answer this first"), and a **REPORT**
skeleton: metadata echo per bag (duration, messages, max gap, firmware bound) -> tables
-> discriminator answers -> findings with numbers -> verdict / ranked hypotheses -> what
the bags cannot tell and what to log next -> figure paths. "Numbers over prose", "derive
numbers from the arrays, use PNGs for shape only", "Read your own figures before citing
them".

## Stage 3 — Synthesis (main session)

Same rules as the benchlog skill: interim notes as agents land; convergence means
independent derivation; resolve contradictions into separate mechanisms rather than
averaging; spot-check one load-bearing number yourself against the `.npz`; report what
validated as well as what failed; label unconfirmed items with the one measurement that
would settle them. Specific to bags: when a bag finding and a firmware-reading finding
agree on a mechanism, say which half each supplied.

## Stage 4 — Routing

- Findings record: a dated doc under `docs/` (e.g. `docs/reviews/`) for a review round;
  new bags indexed in `logs/rosbags/README.md`.
- Firmware changes -> `orchestrated-feature`; telemetry layout changes -> `protocol-bump`
  (and WORK_QUEUE 0j: the firmware version still is not in the bags).
- Bench events surfaced by the bags -> `bench-incident`.
- New traps -> `references/bag-conventions.md` (one-file edit), so the next round's
  briefs inherit them; new scout columns -> `tools/rosbag_analysis/scout_bags.py`.

## Known failure modes

| Failure mode | Guard |
|---|---|
| Sub-20 ms events missed or mis-timed | trap 1: counts are lower bounds; BLG for timing |
| Command read as delivered | trap 2: pre-governor `power_share_cmd`, selector rails |
| Cross-firmware comparison | trap 3: firmware bound per bag in every brief |
| `charger_status` 0 read as a charger state | conventions: 0 also means "no data" |
| Braking inferred as measured | trap 7: no motor current in telemetry; say "inferred" |
| Regen looked for on `I_batt` / `I_fc` | trap 8: unipolar sensors; only `I_charge` |
| Bridge-computed share treated as firmware | index 9 is the bridge's own gated ratio |
| Pi stalls read as dwell | trap 5: check `max(diff(t))` first |

# HIL replay suite — log selection

**Maintained document.** This is the curated list of real bench logs (`logs/*.BLG`)
that are replayed at the firmware through `tools/hil_plant_sim.py --replay` as a
HIL scenario class, and the reason each one is in (or out of) the suite. It is
kept in lockstep with `REPLAY_SUITE` in `tools/hil_replay_suite.py` — **if you add
a log to one, add it to the other** (checklist at the bottom).

Companion documents: [`HIL_MODE.md`](HIL_MODE.md) (the wire protocol, the replay
flags, the fidelity caveat) and [`HIL_PLANT.md`](HIL_PLANT.md) (the simulated
plant, which replay bypasses).

---

## 1. Purpose

The synthetic scenarios (`steady`, `step-load`, `sag`, `comm-loss`, `drive`) probe
the firmware with *invented* stimuli. This suite probes it with **history**: every
rail voltage, source current and velocity sample that the board actually saw during
a recorded bench run is streamed back at it, at true wall-clock pacing.

That buys two things the synthetic scenarios cannot:

1. **Regression against real incidents.** A recorded VESC dead window, a handoff bus
   sag, an estimator basin, a 90-episode saturation run — each becomes a repeatable
   stimulus that any future firmware build must survive, on a bare Teensy, without
   the rig.
2. **A defect archive that keeps working.** Old logs recorded on defective firmware
   are the only samples of those failure stimuli that will ever exist. Replaying them
   at the modern build is how we prove the failure mode is gone.

---

## 2. Policy: conformance vs deviation

The mode of an entry is decided **by the firmware version the log was recorded on**,
relative to the currently flashed target — **fw v21 = the fw v18 control law + the
v19 share handoff slew + v20/v21 observability/HIL**. v19–v21 change no control
semantics except the v19 share handoff slew.

| Mode | When | What the firmware must do |
|---|---|---|
| **conformance** | The recording firmware's control semantics match the target, or the delta does not matter for the property under test | The live response is expected to be *well-behaved* on the recorded stimulus: no faults, bounded command, no windup, no limit cycle |
| **deviation** | The log was recorded on older firmware with a **known defect** | The modern firmware must **not reproduce** the recorded failure mode |

**The pre-v18 conformance caveat.** fw v18 changed both the wheel (120-slot →
90-slot, so every pre-v18 `v_act` was computed on physically different geometry)
and the control law (general-Hanus anti-windup + re-synthesis). For any entry with
`fw_version < 18`, *conformance means* **stable, fault-free and free of limit
cycling** — **it does not mean the live command matches the recorded `I_cmd`.**
Divergence there is expected and is not a defect. The per-version deltas are
encoded as `FW_DELTA_NOTES` in `hil_replay_suite.py` and are emitted into every
evaluation's `notes`.

---

## 3. Open-loop caveats — read before interpreting any result

Replay is **open loop** (see `HIL_MODE.md` §"Fidelity caveat"). Concretely:

- **The plant integrator is bypassed.** The firmware's commands do not influence
  the replayed trajectory. Command +12 A and `v_actual` keeps doing exactly what
  the bench did. Replay validates **responses** (state transitions, sequencing,
  fault latching, command shape at an operating point), never trajectories.
- **The encoder and its estimator are bypassed.** `v_actual` is *injected* in
  engineering units. Every estimator fix — the fw v12 edge-period estimator, the
  v13 adaptive filter, the v15 fractional-pitch ledger, the v17 TOCTOU fix — is
  therefore **not testable by replay**. A log recorded inside an estimator basin
  replays as *the corrupted velocity the firmware was fed*, which is a perfectly
  good stimulus for the controller and no test at all of the estimator.
- **The charger is not replayed.** No BLG record format v1–v7 carries a charge
  current or an Ag105 status byte, so `I_charge` injects as `0.0 A` and
  `ag105_status` as `0x00` (GENSTAT *Battery Disconnect*) for every entry.
- **`v_setpoint` is not replayable.** The injection frame carries sensors only; the
  22-byte Pi command packet is a separate path. The board sits at whatever setpoint
  it was left at (0 in Idle). Anything that depends on a commanded setpoint — the
  ML0144 `v_sp ≠ 0` relay, for instance — is out of reach; see that entry for the
  honest reduced claim.
- **Pre-v18 logs are a different wheel and a different law** (§2).

---

## 4. The suite

26 entries: 15 conformance, 11 deviation. `*` = provisional. Check names are the
declarative kinds in `hil_replay_suite.py` (`CHECK_KINDS`).

### Conformance — current wheel and control law

| Log | fw | BLG | Classification | Why | Checks |
|---|---|---|---|---|---|
| ML0203 | 18 | 6 | clean `'V'` velocity run, 90-slot wheel | The reference clean baseline on the flashed law — a failure here is in the HIL path, not the log | `no_fault`, `bounded_current`, `no_sustained_rail` |
| YP0196 | 18 | 6 | `'Y'` combined drive-cycle + power-share profile | Both loops' stimulus together on the current law | `no_fault`, `bounded_current` |
| WP0197 | 18 | 6 | `'W'` combined current + power-share profile | The current-axis twin of `'Y'` — encoder-less share stimulus | `no_fault`, `bounded_current` |
| TP0210 * | 19 | 6 | `'T'` share sweep, handoff-slew build | Most recent share stimulus; nearest to the flashed target | `no_fault`, `bounded_current` |
| ML0217 * | 19 | 6 | largest manual (`'K'`) run | Longest recent stimulus — duration/soak case for the HIL link | `no_fault`, `bounded_current` |
| YP0214 * | 19 | 6 | `'Y'` combined profile on fw v19 | Combined-profile stimulus with the handoff slew in the recording | `no_fault`, `bounded_current` |

### Conformance — older wheel/law (stability conformance only, §2)

| Log | fw | BLG | Classification | Why | Checks |
|---|---|---|---|---|---|
| ML0146 | 14 | 5 | clean `'V'` step, 120-slot wheel | First-flash fw v14 clean baseline. **Not a trace-match case** | `no_fault`, `bounded_current`, `no_rail_limit_cycle` |
| ML0149 | 14 | 5 | clean `'V'` step, higher setpoint | Second clean fw v14 point, same meaning | `no_fault`, `bounded_current`, `no_rail_limit_cycle` |
| ML0165 | 16 | 6 | rung stepladder | Multi-level stimulus with clean transitions | `no_fault`, `bounded_current` |
| ML0169 | 16 | 6 | friction-disturbance rejection, ~2.2 s continuous saturation | The saturation-endurance case: ride the recorded episodes out without faulting, and come off the rail | `no_fault`, `bounded_current`, `returns_off_rail` |
| TP0170 | 16 | 6 | share sweep, `share_sp = 0.5` | Balanced-share operating point of the first genuine closed-loop share dataset | `no_fault`, `bounded_current` |
| TP0176 | 16 | 6 | share sweep at the FC rail (FC-only 43–45 % of the run) | The share-rail extreme: one source carries the bus for a long stretch | `no_fault`, `bounded_current` |
| YP0152 | 14 | 5 | first `'Y'` profile on the Youla drive controller | Combined-profile representative from the fw v14 era | `no_fault`, `bounded_current` |
| **ML0151** | 14 | 5 | **H6 flagship** — 56 s stepladder with the ~428 ms VESC dead window, the drag step-change and ~90 saturation episodes | Richest recorded incident in the archive; many saturation entries/exits back to back is exactly the class the fw v18 general-Hanus fix targets | `no_fault`, `bounded_current`, `returns_off_rail`, `no_rail_limit_cycle` |
| TP0178 | 16 | 6 | handoff bus sag to 12.15 V — 0.15 V above `LIMIT_V_BUS_MIN`, 10 ms dwell (half the 20 ms latch) | The **negative** UV case: the recorded dip must *not* latch UV_BUS. Pairs with the UV trio, which must | `no_fault`, `fault_not_latched(UV_BUS)` |

### Deviation — the modern firmware must not reproduce the defect

| Log | fw | BLG | Recorded defect | Check + caveat |
|---|---|---|---|---|
| ML0137 | 11 | 5 | boxcar-estimator ±12 A rail-to-rail limit cycle, 2.3–2.6 Hz | `no_rail_limit_cycle`, `bounded_current`, `no_fault`. **Caveat:** replay injects the *recorded* `v_act`, so this tests the controller's reaction to that stimulus, **not** the estimator fix that actually removed the cycle |
| ML0140 | 12 | 5 | estimator blind holds, 120–560 ms, under direction dither | `no_fault`, `bounded_current`, `returns_off_rail` — a long frozen-velocity stimulus |
| ML0144 | 12 | 5 | `v_sp = 0` relay: 90 % rail bang-bang closing the loop below the estimator floor | `no_fault`, `near_zero_current`. **Honest limit:** replay cannot set `v_setpoint`, so the `v_sp ≠ 0` relay is unreachable. What *is* checkable, and what is checked: with `v_sp = 0` and this log's `v_actual` injected, the firmware commands ~0 A (the `V_SP_ZERO_THRESH` behaviour) instead of bang-banging |
| ML0153 | 14 | 5 | T/2 basin — `v_act` corrupted to ~2× true | `no_fault`, `bounded_current`. **Caveat:** the basin fix is in the estimator, which replay bypasses — not testable open-loop |
| ML0164 | 16 | 6 | x2 **rounding** basin, locked breakaway-to-stop | `no_fault`, `bounded_current`. Same caveat |
| TP0171 | 16 | 6 | reset re-seeded *into* the x2 basin (~15 ms recovery) | `no_fault`, `bounded_current`. Same caveat |
| YP0166 | 16 | 6 | mid-run `v = 0` injection at a true 1.49 m/s → ±12 A rail pair within 12 ms (the fw v17 TOCTOU race) | `no_fault`, `bounded_current`, `returns_off_rail` — a full-scale velocity step straight into the ~454 A/(m/s) LF gain must give a **bounded** transient that releases |
| TP0201 | 18 | 6 | share-rail handoff gap, bus 15.86 → 12.185 V | `no_fault`, `fault_not_latched(UV_BUS)` — 0.185 V above the limit for ~10 ms, inside the 20 ms dwell, so no latch. **Caveat:** the fw v19 handoff *slew* that mitigates the gap acts on the plant, which replay bypasses; only the fault decision is exercisable |
| TP0010 | — (pre-versioning) | 1 | bus collapse the old firmware died on **without faulting** | `fault_latched(UV_BUS)` — the fw v5 leaky-dwell filter must latch. That is the whole point of the rework |
| TP0053 | 4 | 2 | repetitive source-commutation dropout (~9 ms under / ~51 ms over per ~60 ms cycle) that **evaded** the fw v4 window filter | `fault_latched(UV_BUS)` — the exact case the dwell integrator was designed for: net +6.45 ms per cycle, so it must latch within a few cycles |
| WP0097 | 5 | 3 | fw v5-era bus collapse | `fault_latched(UV_BUS)` — third independent collapse shape |

The three UV-trio entries use `require_stimulus`: before scoring the firmware, the
injected `V_bus` series is run through the firmware's *own* leaky-dwell integrator
(`LIMIT_V_BUS_MIN` 12.0 V, `UV_BUS_DWELL_LATCH_MS` 20 ms, `UV_BUS_DWELL_LEAK` 0.05,
`UV_BUS_DWELL_DT_CAP_MS` 5 ms, armed once `V_BUS_CHARGED_THRESH` 13.5 V is reached).
If the stimulus would not qualify, the check fails **loudly as inconclusive** rather
than excusing the firmware — a suite entry whose stimulus stopped qualifying is a
suite bug that must be seen.

---

## 5. Exclusions

| Excluded | Why |
|---|---|
| ML0182, ML0183 | Encoder-diagnostic runs on a **defective** 120-slot thin-tooth wheel (~92 % blind). The stimulus characterises a sensor mount that no longer exists |
| ML0135 | Obsolete PI control law plus a reverse-direction diagnostic — neither the law nor the manoeuvre maps onto anything the current build does |
| The fw v3–v8 bulk campaigns (TP0014–TP0134, WP0039–WP0124, PS000x, TEST0001) | Superseded control law *and* superseded fault logic; replaying dozens adds runtime, not coverage. Three representatives are kept as the UV trio — TP0010, TP0053, WP0097 — chosen for three **different** collapse shapes |
| Hand-spin / manual-wheel diagnostics generally | The stimulus is an operator's hand, not a control scenario: no repeatable property to assert |

The same list is mirrored as `REPLAY_EXCLUSIONS` in `hil_replay_suite.py` so the
reasoning travels with the code.

---

## 6. Firmware constants the checks are pinned to

Every number below was read from source, not from memory. Re-verify if the firmware
moves.

| Constant | Value | Source |
|---|---|---|
| `MOTOR_I_CMD_MAX` | 12.0 A | `teensy_controller/teensy_controller.ino:2048` (line 2052 `static_assert`s it against `DRIVE_CTRL_I_MAX`) |
| `FAULT_UV_BUS` | `0x0100` | `teensy_controller.ino:1155` |
| `LIMIT_V_BUS_MIN` | 12.0 V | `teensy_controller.ino:1258` |
| `UV_BUS_DWELL_LATCH_MS` | 20.0 ms | `teensy_controller.ino:1284` |
| `UV_BUS_DWELL_LEAK` | 0.05 | `teensy_controller.ino:1285` |
| `UV_BUS_DWELL_DT_CAP_MS` | 5.0 ms | `teensy_controller.ino:1288` |
| `V_BUS_CHARGED_THRESH` | 13.5 V (`V_BUS_NOMINAL − 2.5`) | `teensy_controller.ino:1363` |
| Full fault bitmask | `0x0001`–`0x8000` | `teensy_controller.ino:1149–1166`; `FAULT_HIL_LINK` aliases `FAULT_PI_TIMEOUT` (`:1168`) |

Suite-policy thresholds (not firmware) — `SUSTAINED_RAIL_S` 1.0 s,
`LIMIT_CYCLE_ALT_PER_S` 2.0/s, `OFF_RAIL_LEVEL_A` 10.0 A / `OFF_RAIL_WITHIN_S` 1.0 s,
`NEAR_ZERO_I_A` 0.5 A, `RAIL_LEVEL_A` 11.9 A — are named constants in the module with
their rationale at the definition.

---

## 7. Running it

Running the board belongs to the wrapper; this module lists the suite and scores an
existing CSV.

```
# what is in the suite
python3 tools/hil_replay_suite.py --list

# every .BLG present, headers agree with the table
python3 tools/hil_replay_suite.py --verify-logs

# the argv to hand hil_plant_sim for one entry
python3 tools/hil_replay_suite.py --argv-for ML0151 --csv-dir runs/
python3 tools/hil_plant_sim.py --teensy-ip 192.168.1.50 \
        $(python3 tools/hil_replay_suite.py --argv-for ML0151 --csv-dir runs/)

# score the CSV that produced
python3 tools/hil_replay_suite.py --evaluate ML0151 runs/hil_replay_ML0151.csv
```

The emitted argv carries **`--force`**, because the CSV name is derived from the log
and is therefore identical on every replay of the same entry: `hil_plant_sim.py`
refuses an explicit `--csv` whose CSV or either sidecar (`.meta.json`,
`.events.jsonl`) already exists, so without it the second replay of an entry into the
same `--csv-dir` would exit 2 instead of running. **Re-running an entry into the same
directory therefore overwrites that entry's previous artifacts** — point `--csv-dir`
somewhere else to keep them.

`evaluate_replay_csv(entry, csv_path)` returns
`{"log", "mode", "passed", "checks": [{"name", "passed", "detail"}], "notes": [...]}`;
`--json` prints it verbatim. A missing or unparseable CSV, an unknown check kind, or a
check that raises are all reported as **failures**, never propagated.

Observation columns are blank on every tick before the board's first observation
frame; each check drops blanks per-series, and a CSV with *no* observation frames at
all fails every check with an explicit "the board never answered" note rather than
passing vacuously.

---

## 8. How to add a log

1. **Classify it.** What is the run (profile type, setpoints), and what is the one
   property worth asserting? If you cannot name the property, it is a diagnostic
   log, not a suite entry — leave it out and say why in §5.
2. **Pick the mode** by the recording firmware version (§2). Was there a known
   defect on that build that this log exhibits? → *deviation*. Otherwise →
   *conformance*, and if `fw_version < 18` say explicitly in `why` that conformance
   means stability, not a trace match.
3. **Read the header, don't guess.** `python3 tools/hil_replay_suite.py --verify-logs`
   after adding the entry — it reads the BLG magic, the format version (byte 4) and
   `fw_version` (u16 at offset 18, absent in BLG v1) and refuses to agree with a
   table that disagrees with the file.
4. **Define the checks** from the existing kinds where possible: `no_fault`,
   `fault_latched`, `fault_not_latched`, `bounded_current`, `no_sustained_rail`,
   `no_rail_limit_cycle`, `returns_off_rail`, `near_zero_current`. A new kind is a
   small pure `(ReplayCsv, spec) -> (bool, str)` function plus a `CHECK_KINDS` entry
   — and a named constant with its rationale for any threshold it introduces.
5. **Write the open-loop caveat.** If the defect being guarded lives in the estimator,
   the plant or a commanded setpoint, replay cannot test it. Say so in `why` (§3
   lists the classes). An entry that overclaims is worse than no entry.
6. **Add the `REPLAY_SUITE` entry** in `tools/hil_replay_suite.py`, and **update
   §4 of this document** in the same change.
7. If the recording firmware version is new to `FW_DELTA_NOTES`, add its one-line
   "what differs vs v21 that matters".

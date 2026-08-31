#!/usr/bin/env python3
"""
run_hil_suite.py — run EVERY HIL scenario and the whole replay suite against a
flashed board, then package the results into one report directory.

    python3 tools/run_hil_suite.py --teensy-ip 192.168.1.50

This is the wrapper the bench operator runs once; everything under it is already
built:

  * tools/hil_plant_sim.py   — the plant simulator (SCENARIOS registry, replay mode)
  * tools/hil_replay_suite.py — the 26-entry recorded-log suite + its declarative
                                per-entry checks (evaluate_replay_csv)

WHAT THIS SCRIPT ADDS
  1. A run plan over both halves (scenarios, then replays), with --only/--skip.
  2. Child-process execution (NOT in-process main()): every run is a separate
     `sys.executable tools/hil_plant_sim.py ...` with a hard timeout, so a wedged
     run is killable and recorded as TIMEOUT instead of hanging the bench session.
  3. Health checks for the SCENARIO half, which — unlike the replay entries — has
     no declarative checks of its own: observation-frame presence, final
     fault_flags vs an EXPECTED-fault table, achieved rate, hi-fi substep stats,
     and electrical event counts from the .events.jsonl sidecar.
  4. REPORT.md + results.json in a timestamped report directory, with every
     child's stdout/stderr captured to a per-run .log.

BOARD-STATE ASSUMPTION BETWEEN RUNS
  Each run opens its own UDP socket and the firmware learns its host from the
  FIRST accepted injection frame. Between runs this script sleeps
  --settle-s (default 5 s), which is >> the firmware's HIL_ZERO_MS 250 ms link-loss
  window: the board force-zeros the injected rails, unbinds the host, and latches
  ERR_HIL_STALE, so the next run starts from a known (State 99, latched) board
  rather than from whatever the previous scenario left behind. That latch is
  EXPECTED and is why a per-run "final fault" is judged against the run's own
  stimulus, not against a clean-boot assumption. If you want a clean State-1 board
  for a particular run, power-cycle between runs and pass --settle-s 0.

  fw v23+ ADDS AUTO-RECOVERY, and it has a MINIMUM: the board warm-resets that
  ERR_HIL_STALE latch back to State 0 only after the injection link has been
  continuously dead for >= 1 s, which is what marks a RUN BOUNDARY. A --settle-s
  below SETTLE_MIN_RECOVER_S (1.5 s) is therefore warned about at plan time,
  because the boundary MAY NOT be crossed reliably. Note that the boundary is
  anchored at the board's LAST ACCEPTED FRAME, so the dead window is this pause
  PLUS the previous child's teardown PLUS the next child's startup — the true
  gap is longer than --settle-s by an unmeasured margin, which is exactly why
  the wording is "may not" and not "will not". When it is not crossed, every run
  after the first starts from a board that never recovered and each of those
  results is an artifact of the pause length rather than of the scenario. The
  warning is NOT a floor: --settle-s 0 combined with a power-cycle between runs
  remains the deliberate way to give each run a clean-boot board.

PER-RUN ARTIFACTS
  Each child gets an explicit absolute --csv inside this run's fresh report
  directory, so hil_plant_sim.py's auto-naming and its overwrite refusal never
  apply here. Each CSV also gets a "<csv>.meta.json" sidecar written by the
  child (scenario/mode, resolved config, model-constants hash, git rev, results).

MID-RUN WARM-RESET TRIPWIRE
  From fw v23 the board recovers from its latched State 99 on its own after a run
  boundary. A host stall of >= 1 s mid-run looks exactly like one, so the board
  warm-resets. The damage is NOT "a latched fault silently vanishes" — the union
  and fault_latched checks look at the whole run and would fail loudly on that.
  It is that after the reset the board runs State 0 -> bring-up -> Idle, so the
  REST OF THE RUN IS NOT THE SCENARIO its checks assume: the stimulus timeline
  keeps playing against a board that restarted underneath it, a fault that fires
  again afterwards reads as having fired once (any dwell/timing conclusion from
  it is wrong), and a check keyed to the FINAL state or flags reads the clean
  post-recovery board. Each child counts the mainState transitions out of State
  99 it observed and reports them in its exit summary and its .meta.json
  sidecar; a run with a nonzero MID-RUN count is marked INCONCLUSIVE here, not
  PASS and not FAIL — nothing was disproved, the evidence was destroyed. A run
  that is inconclusive AND had other check failures is labelled as both. The one
  whitelisted scenario is `comm-loss`, whose 2 s gap exists to cross the
  boundary: it REQUIRES exactly one
  (SCENARIOS["comm-loss"]["warm_resets_expected"]); MORE than expected is
  inconclusive there too, FEWER is a plain failure.

EXIT CODES
  0  every run passed
  1  at least one run failed (an INCONCLUSIVE run counts here — re-run it)
  2  the board never answered on the first run (aborted early; --keep-going
     overrides and grinds through the whole plan anyway)
"""

from __future__ import annotations

import argparse
import csv
import datetime
import fnmatch
import json
import os
import platform
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
# Repo-root home for every HIL artifact (report dirs here, hil_plant_sim.py's
# relative --csv paths there too).  Operator-created; created on demand anyway.
HIL_RESULTS_DIR = os.path.join(_REPO, "HIL Results")
sys.path.insert(0, _HERE)

from hil_plant_sim import SCENARIOS, TEENSY_PORT_DEFAULT            # noqa: E402
from hil_replay_suite import (                                      # noqa: E402
    REPLAY_SUITE, FAULT_NAMES, TARGET_FW_VERSION,
    build_sim_argv, evaluate_replay_csv, replay_csv_path, verify_suite_logs,
)

SIM_SCRIPT = os.path.join(_HERE, "hil_plant_sim.py")
GRACE_S = 30.0                 # timeout = expected duration + this
DEFAULT_SETTLE_S = 5.0         # >> HIL_ZERO_MS (250 ms); see module docstring
# Shortest settle pause that still marks a RUN BOUNDARY for the fw v23+ HIL
# auto-recovery (the firmware needs the link continuously dead for >= 1 s; 1.5 s
# is that bound plus margin for host jitter).  Warned about, never enforced —
# --settle-s 0 with a power-cycle between runs stays a valid workflow.
SETTLE_MIN_RECOVER_S = 1.5

# ─────────────────────────────────────────────────────────────────────────────
# Which scenarios EXPECT the board to latch a fault.
#
# Sources, per entry (do not extend this table from intuition — cite a source):
#   sag           docs/HIL_MODE.md test H2: "mainState 99 and fault_flags with the
#                 UV bit set, latched" for the -5 V / 1 s dip past LIMIT_V_BUS_MIN.
#   comm-loss     The scenario stops transmitting for 2 s, which is past the
#                 firmware's 250 ms zero stage: CLAUDE.md fw v21 addendum and
#                 docs/HIL_MODE.md "Link-loss behaviour" — ">250 ms force zeros,
#                 unbind the host, and latch FAULT_HIL_LINK / ERR_HIL_STALE".
#                 FAULT_HIL_LINK ALIASES FAULT_PI_TIMEOUT (0x0010).
#   soc-depletion SCENARIOS description (hil_plant_sim.py): V_batt walks down the
#                 OCV curve toward LIMIT_V_BATT_MIN — "the honest UV_BATT path".
#                 Whether it ARRIVES inside the run depends on --soc0/--capacity-ah,
#                 so this one is "allowed", not "required" (see ALLOWED below).
# Everything else is expected fault-free; a fault there is a finding.
# ─────────────────────────────────────────────────────────────────────────────
#
# --pi-live NOTE (verified from source, do not "fix" this):
#   The comm-loss expectation is UNCHANGED under --pi-live.  The HIL stale clock
#   keys on ACCEPTED INJECTION FRAMES ONLY: hilLastFrameMs is stamped in
#   receiveCommands()'s commit block (.ino:4970-4976), which runs only for a
#   40-byte frame that passed hilParseInjectFrame() and the host lock; and
#   updateSensors() ages exactly that stamp (.ino:4379-4431).  A 22-byte Pi
#   command takes the other branch (processPiCommandPacket(), .ino:4835) and
#   touches only last_rx_ms / pi_ever_connected (.ino:4884-4885), which belong to
#   the SEPARATE Pi watchdog (checkPiWatchdog(), .ino:4817-4826).  So a real Pi's
#   command traffic does NOT keep the HIL link alive: when this simulator stops
#   injecting for 1 s, ERR_HIL_STALE latches exactly as it does without a Pi.
FAULT_REQUIRED = {
    "sag": ("docs/HIL_MODE.md H2 — UV_BUS latched by the -5 V / 1 s dip", 0x0100),
    "comm-loss": ("docs/HIL_MODE.md link-loss — 2 s gap > 250 ms zero stage, "
                  "ERR_HIL_STALE (FAULT_HIL_LINK aliases FAULT_PI_TIMEOUT 0x0010); "
                  "unchanged under --pi-live — the stale clock keys on injection "
                  "frames only (.ino:4970-4976), not on Pi command traffic",
                  0x0010),
}
FAULT_ALLOWED = {
    "soc-depletion": "UV_BATT if the pack reaches LIMIT_V_BATT_MIN inside the run "
                     "(depends on --soc0/--capacity-ah) — hil_plant_sim.py SCENARIOS",
    "charge-fault": "charger-input collapse at t = 20 s may or may not latch, "
                    "depending on the GENSTAT decode path — hil_plant_sim.py SCENARIOS",
    # F2: `handoff-sag` is a live simulation of the TP0178/TP0201 class, whose
    # RECORDED margin above LIMIT_V_BUS_MIN was only 0.15-0.185 V with a ~10 ms
    # dwell (half the 20 ms latch window) — see hil_replay_suite.py's TP0178/TP0201
    # entries. A legitimately deeper sag on this scenario's own +1.5 A load step
    # would correctly latch UV_BUS; without this entry that correct latch would be
    # misreported as an unexpected-fault FAIL rather than the real hardware-class
    # behaviour it is.
    "handoff-sag": "UV_BUS if the standby diode's reactive pickup gap is deep/long "
                   "enough — TP0178/TP0201 recorded only 0.15-0.185 V of margin "
                   "with a ~10 ms dwell against the 20 ms latch, so this is a "
                   "plausible, not anomalous, outcome of this scenario",
}

# Always-reported open findings (report section 'Known open findings').
K_DROOP_FINDING = (
    "K_DROOP_BUS design-vs-measured x4 discrepancy: tools/hil_plant_sim.py's "
    "constant comment records that the measured shared-source droop is "
    "0.074 V/A while the MDAC droop-chain DESIGN value is R_e = RE_MAX*g = "
    "2.014*0.298 = 0.60 ohm/channel = 0.30 V/A shared — four times higher. "
    "Nothing in the repo explains the gap. The hi-fi engine (hil_electrical.py) "
    "reproduces the DESIGN value by construction, so the same scenario run in "
    "both electrical modes shows the gap directly; treat any bus-droop number "
    "in this report as mode-dependent until the discrepancy is closed."
)


def _suite_mode(args):
    """The suite's command-source mode, recorded in meta and every run record.

    'pi-live'  — a REAL Pi owns the 22-byte command packet (--pi-live)
    'scripted' — the default: each scenario's own pi_timeline (or, for a scenario
                 that declares one, its emulated-EMS strategy inside the child)"""
    return "pi-live" if getattr(args, "pi_live", False) else "scripted"


def fault_names(bits):
    """'UV_BUS|OC_FC' style rendering of a fault_flags word."""
    if not bits:
        return "none"
    names = [n for b, n in sorted(FAULT_NAMES.items()) if bits & b]
    unknown = bits & ~sum(FAULT_NAMES)
    if unknown:
        names.append("0x%04X" % unknown)
    return "|".join(names)


# ─────────────────────────────────────────────────────────────────────────────
# Run plan
# ─────────────────────────────────────────────────────────────────────────────

def blg_duration_estimate_s(path):
    """Rough replay duration from a BLG's size: (bytes - 32 B header)/rec_size at
    1 kHz. Header layout per tools/decode_benchlog.py (HEADER_SIZE 32, record_size
    at byte 5). Used ONLY to size the child's timeout — never reported as fact."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(8)
        if len(head) < 8 or head[:4] != b"BLG1":
            return None
        rec = head[5]
        if rec <= 0:
            return None
        return max(0.0, (size - 32) / rec / 1000.0)
    except OSError:
        return None


def build_plan(args):
    """Return the full ordered run plan as a list of plain dicts.

    Pure w.r.t. the board: safe to call for --list / --dry-run with no hardware."""
    plan = []

    pi_live = getattr(args, "pi_live", False)

    if not args.replay_only:
        for name, meta in SCENARIOS.items():
            need = meta.get("electrical", "any")
            if pi_live and (meta.get("pi_timeline") or meta.get("ems")):
                # SKIPPED, not failed: under --pi-live the real Pi owns the 22-byte
                # command packet, and hil_plant_sim.py refuses a scenario carrying
                # its own timeline (two command sources would overwrite each other
                # at 50 Hz). Recorded with a reason so the report shows the gap.
                plan.append({
                    "kind": "scenario", "name": name,
                    "mode": need if need in ("simple", "hifi") else args.electrical_pref,
                    "electrical_required": need,
                    "description": meta.get("description", ""),
                    "duration_s": 0.0, "csv": None, "events": None, "log": None,
                    "argv": None, "timeout_s": 0.0,
                    "skip_reason": (
                        ("--pi-live: this scenario carries its own pi_timeline "
                         "(%d entries); the real Pi owns the command link"
                         % len(meta["pi_timeline"])) if meta.get("pi_timeline") else
                        ("--pi-live: this scenario's whole stimulus IS the emulated "
                         "EMS layer (strategy '%s'); with a real Pi commanding there "
                         "is nothing left for it to drive" % meta["ems"])),
                })
                continue
            mode = need if need in ("simple", "hifi") else args.electrical_pref
            dur = float(meta.get("duration_s", 30.0))
            csv_name = "hil_scenario_%s_%s.csv" % (name, mode)
            argv = [
                "--scenario", name,
                "--electrical", mode,
                "--duration", "%g" % dur,
                "--csv", os.path.join(args.out, csv_name),
            ]
            if meta.get("vesc_cap_f") is not None and mode == "hifi":
                argv += ["--vesc-cap-uf", "%g" % (meta["vesc_cap_f"] * 1e6)]
            if name == "soc-depletion":
                # L9(c): at the DEFAULT --soc0 0.7 / 5 Ah / this scenario's stock
                # 120 s duration, the run cannot reach LIMIT_V_BATT_MIN at all:
                # ~115 s of the +3.0 A load step is ~345 A*s against an 18000 A*s
                # (5 Ah) pack, i.e. ~1.9% SOC -- nowhere near the UV floor.  Even at
                # --soc0 0.15 alone, 120 s only reaches ~13% SOC (V_batt ~6.9 V,
                # still above the 6.2 V limit per the BatterySource OCV/Rs(SOC)
                # curve).  Reaching LIMIT_V_BATT_MIN (~6.2 V) needs SOC to fall to
                # roughly 0.05 (where the fitted model's Rs(SOC) knee below 15%
                # steepens the sag enough to cross 6.2 V), i.e. a further ~0.10 of
                # SOC = 1800 A*s at 3 A = 600 s beyond the 5 s ramp-up -- so this
                # entry is bumped to --soc0 0.15 and a 650 s duration (5 s ramp +
                # 645 s of load = ~1935 A*s = ~10.75% SOC, landing at ~4.25% SOC,
                # comfortably past the ~5% crossing point).
                dur = 650.0
                argv = [
                    "--scenario", name,
                    "--electrical", mode,
                    "--duration", "%g" % dur,
                    "--soc0", "0.15",
                    "--csv", os.path.join(args.out, csv_name),
                ]
            plan.append({
                "kind": "scenario", "name": name, "mode": mode,
                "electrical_required": need,
                "description": meta.get("description", ""),
                "duration_s": dur,
                "csv": os.path.join(args.out, csv_name),
                "events": os.path.join(args.out, csv_name) + ".events.jsonl",
                "log": os.path.join(args.out, "run_scenario_%s.log" % name),
                "argv": argv,
                "timeout_s": dur + GRACE_S,
            })

    if not args.scenarios_only:
        for entry in REPLAY_SUITE:
            if pi_live:
                # F5: skip the ENTIRE replay half under --pi-live, per-entry
                # (same skip-record mechanism as the pi_timeline/ems scenario
                # skips above) rather than silently letting a real Pi command
                # over a replayed trajectory it was never part of recording.
                plan.append({
                    "kind": "replay", "name": entry["log"], "mode": entry["mode"],
                    "description": entry.get("classification", ""),
                    "duration_s": 0.0, "csv": None, "events": None, "log": None,
                    "argv": None, "timeout_s": 0.0, "entry": entry,
                    "skip_reason": (
                        "--pi-live: replay mode plays a RECORDED trajectory "
                        "regardless of what a live Pi commands, so the Pi would "
                        "be an uncontrolled second stimulus over a run that "
                        "cannot react to it — the whole replay half is skipped "
                        "under --pi-live"),
                })
                continue
            csv_path = replay_csv_path(entry, args.out)
            argv = build_sim_argv(entry, args.out)
            est = blg_duration_estimate_s(os.path.join(_REPO, entry["path"]))
            plan.append({
                "kind": "replay", "name": entry["log"], "mode": entry["mode"],
                "description": entry.get("classification", ""),
                "duration_s": est,
                "csv": csv_path,
                "events": None,
                "log": os.path.join(args.out, "run_replay_%s.log" % entry["log"]),
                "argv": argv,
                "timeout_s": (est if est else 120.0) + GRACE_S,
                "entry": entry,
            })
        if pi_live:
            print("[suite] --pi-live: skipping the entire replay half (%d entries) — "
                  "a live Pi would be an uncontrolled second stimulus over a "
                  "replayed trajectory" % len(REPLAY_SUITE))

    return filter_plan(plan, args.only, args.skip)


def filter_plan(plan, only, skip):
    """--only/--skip are shell-glob patterns matched against the run name."""
    out = []
    for p in plan:
        if only and not any(fnmatch.fnmatch(p["name"], pat) for pat in only):
            continue
        if skip and any(fnmatch.fnmatch(p["name"], pat) for pat in skip):
            continue
        out.append(p)
    return out


def full_argv(plan_item, args):
    """The child's complete argv, transport flags appended (build_sim_argv and the
    scenario builder both deliberately omit them — the wrapper owns transport)."""
    if plan_item.get("skip_reason"):
        return []          # nothing is launched for a skipped run
    # D1/K1: --force on EVERY child, both halves.  hil_plant_sim.py refuses an
    # explicit --csv whose CSV or either sidecar already exists (exit 2), and a
    # child cannot be asked interactively.  The default report directory is
    # fresh per run so nothing is there — but an operator-supplied --out, a
    # re-run into the same directory, or a partially-completed plan resumed into
    # it all collide, and the run would die at startup with a refusal nobody is
    # present to answer.  Deduplicated because hil_replay_suite.build_sim_argv()
    # also emits it (for operators using --argv-for by hand).
    force = [] if "--force" in plan_item["argv"] else ["--force"]
    return ([sys.executable, SIM_SCRIPT] + plan_item["argv"] + force
            + ["--teensy-ip", args.teensy_ip, "--port", str(args.port)]
            + (["--dash"] if getattr(args, "dashboard", False) else [])
            # --pi-live applies to the SCENARIO half only: replay mode creates no
            # commander anyway, and hil_plant_sim.py refuses the combination.
            + (["--pi-live"] if getattr(args, "pi_live", False)
               and plan_item["kind"] == "scenario" else []))


# ─────────────────────────────────────────────────────────────────────────────
# Execution + health checks
# ─────────────────────────────────────────────────────────────────────────────

def parse_child_summary(text):
    """Pull the numbers out of hil_plant_sim's own exit summary lines."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[hil] done:"):
            # "[hil] done: N ticks in X s -> Y Hz achieved (target Z Hz), max overrun W ms"
            try:
                out["ticks"] = int(line.split("done:")[1].split("ticks")[0])
                out["achieved_hz"] = float(line.split("->")[1].split("Hz")[0])
                out["max_overrun_ms"] = float(line.split("max overrun")[1].split("ms")[0])
            except (IndexError, ValueError):
                pass
        elif line.startswith("[hil] tx="):
            try:
                out["tx_frames"] = int(line.split("tx=")[1].split()[0])
                out["rx_frames"] = int(line.split("rx=")[1].split()[0])
                out["rx_bad"] = int(line.split("frames,")[-1].split()[0])
            except (IndexError, ValueError):
                pass
            try:
                # F2: absent on an older sim build (pre-fix) -- treated as
                # "unknown", not "zero", by the judge below.
                out["send_errors"] = int(line.split("send_errors=")[1].split()[0])
            except (IndexError, ValueError):
                pass
        elif line.startswith("[hil] warm resets:"):
            # "[hil] warm resets: N observed, M mid-run (after 2.0s)[ at t=...]"
            try:
                out["warm_resets"] = int(line.split("resets:")[1].split("observed")[0])
                out["warm_resets_mid_run"] = int(
                    line.split("observed,")[1].split("mid-run")[0])
            except (IndexError, ValueError):
                pass
        elif line.startswith("[hil] electrical(hifi):"):
            try:
                out["substep_khz"] = float(line.split(":")[1].split("kHz")[0])
                out["elec_events"] = int(line.split("),")[1].split("events")[0])
            except (IndexError, ValueError):
                pass
        elif "ABOVE the 20 V abs-max" in line:
            out["over_absmax_line"] = line
    return out


def analyze_scenario_csv(csv_path):
    """Health metrics from a simulated-mode CSV.

    Observation columns are BLANK on every tick before the first observation
    frame arrives (hil_plant_sim's row writer), so 'n_obs' counts rows with a
    non-blank fault_flags — i.e. ticks the board actually answered."""
    m = {"csv": csv_path, "rows": 0, "n_obs": 0, "final_fault_flags": None,
         "fault_bits_seen": 0, "final_state": None, "duration_s": None,
         "substep_hz_min": None, "substep_hz_mean": None, "error": None}
    if not os.path.isfile(csv_path):
        m["error"] = "CSV not written"
        return m
    subs = []
    t_first = t_last = None
    try:
        with open(csv_path, newline="") as fh:
            for row in csv.DictReader(fh):
                m["rows"] += 1
                try:
                    t = float(row.get("t") or "nan")
                    if t == t:
                        t_first = t if t_first is None else t_first
                        t_last = t
                except ValueError:
                    pass
                ff = (row.get("fault_flags") or "").strip()
                if ff:
                    m["n_obs"] += 1
                    try:
                        bits = int(ff, 0)
                    except ValueError:
                        continue
                    m["final_fault_flags"] = bits
                    m["fault_bits_seen"] |= bits
                    st = (row.get("state") or "").strip()
                    if st:
                        try:
                            m["final_state"] = int(st, 0)
                        except ValueError:
                            pass
                s = (row.get("elec_substep_hz") or "").strip()
                if s:
                    try:
                        subs.append(float(s))
                    except ValueError:
                        pass
    except OSError as exc:
        m["error"] = str(exc)
        return m
    if t_first is not None and t_last is not None:
        m["duration_s"] = t_last - t_first
    if subs:
        m["substep_hz_min"] = min(subs)
        m["substep_hz_mean"] = sum(subs) / len(subs)
    return m


def read_run_meta(csv_path, launched_at=None):
    """Load the child's '<csv>.meta.json' sidecar; {} if absent/stale/unreadable.

    Preferred over the stdout summary for the warm-reset tripwire: under
    --dashboard the child's stdout goes to the terminal and is never captured,
    so the sidecar is the only surviving record of the count.

    D2 — THIS ATTEMPT'S sidecar, or nothing.  A sidecar sitting at that path may
    belong to a PREVIOUS run (the suite now passes --force, so a re-run into a
    non-fresh --out overwrites the CSV but reads the old sidecar until the child
    rewrites it), and reading a stale one would report a stale warm-reset count
    against a fresh run.  Three guards, in increasing strength:

      1. `results` must not be None.  The sidecar is written twice — "running"
         with results=None before the loop, then again at exit.  results=None
         means the child died before finalizing, which is genuinely UNMEASURED,
         not zero.
      2. `doc["csv"]` must equal the path we asked for.  Cheap, and catches a
         sidecar copied or renamed into place.
      3. `created` must be at or after the child's launch time, when the caller
         supplies one.  Timestamps are the child's local ISO-8601 with offset and
         this host's clock, so they are comparable; anything unparseable is
         treated as "cannot verify" and passes this guard rather than discarding
         a sidecar that is probably fine (guards 1-2 are the load-bearing pair).
    """
    if not csv_path:
        return {}
    try:
        with open(csv_path + ".meta.json", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    if doc.get("results") is None:
        return {}                          # guard 1: never finalized
    if os.path.normcase(os.path.abspath(str(doc.get("csv") or ""))) != \
            os.path.normcase(os.path.abspath(csv_path)):
        return {}                          # guard 2: not this run's CSV
    if launched_at is not None:
        created = doc.get("created")
        try:
            if datetime.datetime.fromisoformat(str(created)) < launched_at:
                return {}                  # guard 3: predates this attempt
        except (TypeError, ValueError):
            pass                           # unparseable -> cannot verify, allow
    return doc


def warm_reset_count(csv_path, child):
    """Mid-run warm resets for one run: (dict, source).

    The dict carries "mid_run", "observed" and "times" (any of them None when
    that field is unavailable).  A None `mid_run` means UNMEASURED — an older
    simulator build, a child that died before finalizing its sidecar, or a run
    whose sidecar and stdout are both unusable.  Unmeasured must never render as
    zero: the whole point of the tripwire is that the damage it detects does not
    show up in the run's own outcome."""
    launched_at = None
    raw_launch = (child or {}).get("launched_at")
    if raw_launch:
        try:
            launched_at = datetime.datetime.fromisoformat(str(raw_launch))
        except (TypeError, ValueError):
            launched_at = None
    meta = read_run_meta(csv_path, launched_at)
    res = meta.get("results") or {}
    if isinstance(res.get("warm_resets_mid_run"), int):
        return ({"mid_run": res["warm_resets_mid_run"],
                 "observed": res.get("warm_resets_observed"),
                 "times": res.get("warm_reset_times_s")},
                "meta.json")
    summary = (child or {}).get("summary") or {}
    if isinstance(summary.get("warm_resets_mid_run"), int):
        # D4: the stdout line carries both counts but no timestamps.
        return ({"mid_run": summary["warm_resets_mid_run"],
                 "observed": summary.get("warm_resets"), "times": None},
                "child stdout")
    return ({"mid_run": None, "observed": None, "times": None}, "unmeasured")


# D8: the damage a mid-run warm reset does, stated once and reused, because the
# loose version ("a latched fault silently disappears") is WRONG for the checks
# that actually exist -- judge_scenario()'s union check and the replay suite's
# fault_latched both look at the whole run and would FAIL loudly on a fault that
# fired and then vanished.
WARM_RESET_DAMAGE = (
    "after the reset the board runs State 0 -> bring-up -> Idle, so the REST OF "
    "THE RUN IS NOT THE SCENARIO the checks assume: the stimulus timeline kept "
    "playing against a board that restarted underneath it, a fault that fires "
    "again afterwards reads as having fired once (so any dwell or timing "
    "conclusion is wrong), and a check keyed to the FINAL state or flags reads "
    "the clean post-recovery board")


def judge_warm_resets(name, kind, counts, source):
    """The warm-reset tripwire check. Returns (check, note|None, inconclusive|None).

    HAZARD (safety finding S2): from fw v23 the board leaves its latched State 99
    on its own once the injection link has been dead for a run boundary
    (1000 ms) and fresh again for 500 ms.  A host stall of that length MID-RUN is
    indistinguishable from a run boundary, so the board warm-resets.  What that
    costs is WARM_RESET_DAMAGE above — the run is unusable rather than wrong, so
    it is marked INCONCLUSIVE and must be re-run.

    The exception is a scenario whose declared point IS the recovery:
    SCENARIOS[name]["warm_resets_expected"] (comm-loss = 1, whose 2 s gap exists
    precisely to cross the boundary).  D16: only a SCENARIO run may consult that
    registry — a replay entry's name is a log id (ML0151), and a collision with a
    scenario name would silently whitelist a replay.

    Returns a third value, `note`: a non-failing observation (D4) about
    grace-window transitions."""
    expected = ((SCENARIOS.get(name) or {}).get("warm_resets_expected")
                if kind == "scenario" else None)
    count = counts.get("mid_run")
    observed = counts.get("observed")
    times = counts.get("times")

    # D4: transitions inside the grace window are the expected start-of-run
    # recovery from the previous run's settle pause.  Never failing, never
    # inconclusive — but worth saying, because on the FIRST run of a plan
    # against a freshly powered board there is no previous run to recover from,
    # so a transition there means the board was ALREADY latched at power-on and
    # deserves a look before the rest of the plan is believed.
    note = None
    if isinstance(observed, int) and isinstance(count, int) and observed > count:
        note = ("%d warm reset(s) inside the start-of-run grace window%s: "
                "normally the expected recovery from the previous run's settle "
                "pause, and not counted against this run. On the FIRST run of a "
                "plan against a freshly powered board there is no previous run "
                "to recover from — a transition there means the board was "
                "already latched at power-on, which is worth investigating."
                % (observed - count,
                   (" at t=%s s" % ", ".join(str(x) for x in times)) if times else ""))

    if count is None:
        if expected is not None:
            # K7: on a whitelisted scenario the count is a REQUIREMENT, so
            # "unmeasured" is not a quiet pass — the requirement is UNVERIFIED.
            return ({"name": "warm_reset_expected", "passed": True,
                     "detail": "UNVERIFIED (%s) — this scenario REQUIRES exactly "
                               "%d mid-run warm reset(s) (the recovery IS the "
                               "test), but no count was available from this "
                               "child, so the requirement was not checked. Not "
                               "failed, not confirmed." % (source, expected)},
                    note, None)
        return ({"name": "warm_reset_tripwire", "passed": True,
                 "detail": "not measurable (%s) — no mid-run warm-reset count "
                           "available from this child, so a mid-run restart "
                           "would be invisible here" % source},
                note, None)

    if expected is not None:
        if count == expected:
            return ({"name": "warm_reset_expected", "passed": True,
                     "detail": "%d mid-run warm reset(s) observed via %s; this "
                               "scenario REQUIRES exactly %d (the recovery is "
                               "the point of the run, not an artifact)"
                               % (count, source, expected)},
                    note, None)
        if count > expected:
            # D15: an EXTRA reset destroys evidence exactly as it does anywhere
            # else -- the whitelist licenses the ONE the scenario provokes, not
            # a host stall on top of it.
            reason = ("%d mid-run warm reset(s) observed (%s) but this scenario "
                      "provokes only %d: the extra one(s) are unexplained, and "
                      "%s. Re-run it on an unloaded host."
                      % (count, source, expected, WARM_RESET_DAMAGE))
            return ({"name": "warm_reset_expected", "passed": False,
                     "detail": reason}, note, reason)
        # count < expected: the recovery this scenario exists to test did not
        # happen. A genuine FAIL -- nothing was destroyed, something is missing.
        return ({"name": "warm_reset_expected", "passed": False,
                 "detail": "%d mid-run warm reset(s) observed via %s; this "
                           "scenario REQUIRES exactly %d — the recovery it "
                           "exists to test did not happen"
                           % (count, source, expected)},
                note, None)

    if count == 0:
        return ({"name": "warm_reset_tripwire", "passed": True,
                 "detail": "no mid-run warm reset (%s) — the board never left "
                           "State 99 during the run" % source},
                note, None)
    reason = ("%d mid-run HIL warm reset(s) observed (%s): %s. Most likely a "
              "host stall of >= 1 s, which fw v23+ reads as a run boundary. "
              "Re-run it on an unloaded host."
              % (count, source, WARM_RESET_DAMAGE))
    return ({"name": "warm_reset_tripwire", "passed": False, "detail": reason},
            note, reason)


def result_label(r, bold_fail=False):
    """One verdict word for a result record, used by ALL render sites.

    D3: an INCONCLUSIVE run whose OTHER checks also failed must not read as a
    plain "re-run this one" — the tripwire destroyed the evidence for the rest
    of the run, but the failures already on the record are real and stay
    visible.  Centralized so the three render sites cannot drift apart."""
    if r.get("skipped"):
        return "SKIPPED"
    if r.get("inconclusive"):
        also = r.get("also_failed") or 0
        base = ("INCONCLUSIVE (also FAILED %d check(s))" % also) if also \
            else "INCONCLUSIVE"
        return ("**%s**" % base) if bold_fail else base
    if r["passed"]:
        return "PASS"
    return "**FAIL**" if bold_fail else "FAIL"


def analyze_events(path):
    """Event counts by kind from a hi-fi .events.jsonl sidecar."""
    out = {"path": path, "total": 0, "kinds": {}, "over_absmax": 0,
           "worst_ring_v": None, "read_error": None}
    if not path or not os.path.isfile(path):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                out["total"] += 1
                k = e.get("kind", "?")
                out["kinds"][k] = out["kinds"].get(k, 0) + 1
                if k == "sw_ring" and e.get("over_absmax"):
                    out["over_absmax"] += 1
                    pv = e.get("peak_v")
                    if pv is not None and (out["worst_ring_v"] is None
                                           or pv > out["worst_ring_v"]):
                        out["worst_ring_v"] = pv
    except OSError as exc:
        # L9(b): record the failure instead of silently swallowing it -- an
        # unreadable sidecar must not render in REPORT.md as "0 events, clean".
        out["read_error"] = str(exc)
    return out


FAULT_ERROR = 0x8000       # .ino:4501-4503 — triggerFault() ORs this into EVERY
                            # latched fault, so a lone PI_TIMEOUT/HIL_STALE latch
                            # is observed as 0x8010, never bare 0x0010.
HIL_DEFAULT_RATE_HZ = 1000.0   # the suite never overrides hil_plant_sim.py's
                                # --rate default (full_argv appends none)


def judge_scenario(name, metrics, events, child, pi_live=False, duration_s=None):
    """Scenario pass/fail. Returns (passed, checks[]) — pure over the inputs."""
    checks = []

    obs_ok = metrics["n_obs"] > 0
    checks.append({
        "name": "observation_frames", "passed": obs_ok,
        "detail": ("%d/%d ticks carry an observation frame" % (metrics["n_obs"], metrics["rows"]))
                  if obs_ok else
                  "NO observation frames — the board never answered. Flashed with "
                  "-DHIL_SIM=1 -DUSE_ETHERNET=1? Right IP/port? On the same L2?",
    })

    final = metrics["final_fault_flags"] or 0
    seen = metrics["fault_bits_seen"] or 0
    if name in FAULT_REQUIRED:
        why, want = FAULT_REQUIRED[name]
        got = bool(seen & want)
        checks.append({"name": "expected_fault", "passed": got,
                       "detail": "expected %s (%s); observed %s (final %s)"
                                 % (fault_names(want), why, fault_names(seen),
                                    fault_names(final))})
    elif name in FAULT_ALLOWED:
        checks.append({"name": "fault_allowed", "passed": True,
                       "detail": "observed %s; %s" % (fault_names(seen), FAULT_ALLOWED[name])})
    else:
        # F1/F2: under --pi-live the Pi watchdog is outside this harness's
        # control: an operator-driven Pi that stops commanding while the board
        # is in State 2/3 legitimately latches FAULT_PI_TIMEOUT (0x0010) after
        # PI_TIMEOUT_MS = 500 (.ino:2788, 4817-4826). That is an operator event,
        # not a firmware finding — but two things must be true before this
        # harness excuses it:
        #
        #   F1: triggerFault() ALWAYS ORs in FAULT_ERROR 0x8000 alongside any
        #       fault (.ino:4501-4503), so a bare PI_TIMEOUT latch is observed
        #       as 0x8010, never 0x0010 alone. The old `seen & ~0x0010` mask
        #       left 0x8000 in `unexpected` on every excusal, so the excusal
        #       NEVER actually passed anything — it printed "excused" and then
        #       failed the run anyway on the FAULT_ERROR bit it forgot to mask.
        #
        #   F2: 0x0010 is BOTH FAULT_PI_TIMEOUT and its alias FAULT_HIL_LINK
        #       (.ino:1193), and the 16-byte observation frame carries no
        #       error_code to tell them apart (residual noted below and in the
        #       manual). Excusing on the bit alone would also excuse a genuine
        #       injection-link failure. Narrowest defensible rule: excuse ONLY
        #       when (a) the fault union is EXACTLY 0x8010 — nothing else set,
        #       not even other latched bits alongside it — AND (b) THIS
        #       process's own injection stream was continuous for the run (its
        #       sendto() calls landed and kept pace), so a HIL-link explanation
        #       is implausible and PI_TIMEOUT is the only fault-producing
        #       explanation left standing. Continuity is judged from the
        #       child's own parsed summary: tx_frames >= 98% of the frames a
        #       full-rate run would have sent, and zero sendto() errors.
        #
        # Residual (documented, not fixed here): the observation frame has no
        # error_code, so even a "continuous stream" verdict is an inference by
        # elimination, not a direct read of which of the two aliased causes
        # fired. A frame extension to carry error_code is future protocol work
        # (see docs/HIL_MODE.md and the manual).
        exactly_pi_timeout = seen == (FAULT_ERROR | 0x0010)
        summary = child.get("summary") or {}
        tx = summary.get("tx_frames")
        send_errors = summary.get("send_errors")
        expected_tx = (HIL_DEFAULT_RATE_HZ * duration_s) if duration_s else None
        stream_continuous = (
            pi_live and exactly_pi_timeout
            and tx is not None and send_errors is not None
            and expected_tx is not None
            and tx >= 0.98 * expected_tx
            and send_errors == 0
        )
        if pi_live and exactly_pi_timeout and not stream_continuous:
            unexpected = seen   # do NOT excuse — attribution to the Pi is unsafe
            excuse_detail = ("  (0x%04X observed but the injection stream had "
                              "gaps or is unmeasured — cannot attribute to the "
                              "Pi; NOT excused)" % seen)
        elif stream_continuous:
            unexpected = 0
            excuse_detail = ("  (PI_TIMEOUT excused under --pi-live: fault union "
                              "is exactly 0x%04X (FAULT_ERROR|PI_TIMEOUT) and this "
                              "process's own injection stream was continuous "
                              "(tx=%d/%s frames, %d send errors) — the operator's "
                              "Pi owns the command cadence. Residual: the "
                              "observation frame carries no error_code, so "
                              "PI_TIMEOUT vs the aliased HIL_STALE is inferred by "
                              "elimination, not read directly.)"
                              % (seen, tx, ("%.0f" % expected_tx) if expected_tx
                                 else "?", send_errors))
        else:
            unexpected = seen
            excuse_detail = ""
        checks.append({"name": "no_unexpected_fault", "passed": unexpected == 0,
                       "detail": "fault_flags union over the run = %s%s"
                                 % (fault_names(seen), excuse_detail)})

    rate = (child.get("summary") or {}).get("achieved_hz")
    if rate is not None:
        checks.append({"name": "achieved_rate", "passed": rate >= 900.0,
                       "detail": "%.1f Hz achieved (target 1000; host-stall gate 900)" % rate})
    elif child.get("stdout_passthrough"):
        # F3: with --dashboard the child's stdout was handed to the terminal
        # (run_child()'s TRADE-OFF), so there is no captured summary to parse
        # a rate from. Make that explicit instead of letting the rate gate
        # silently vanish -- an absent check here reads as "not applicable",
        # not "skipped for an operational reason".
        checks.append({"name": "achieved_rate", "passed": True,
                       "detail": "not measurable — --dashboard passed stdout through; "
                                 "rate gate SKIPPED"})

    if events["over_absmax"]:
        checks.append({"name": "sw_ring_over_absmax", "passed": False,
                       "detail": "%d switching event(s) with an estimated ring peak above "
                                 "the 20 V abs-max — the boost-death signature; worst %s V"
                                 % (events["over_absmax"],
                                    ("%.2f" % events["worst_ring_v"])
                                    if events["worst_ring_v"] is not None else "?")})

    n_chop = events["kinds"].get("chopper_over_power", 0)
    if n_chop:
        checks.append({"name": "chopper_over_power", "passed": False,
                       "detail": "%d excursion(s) where V_rgn^2/47 Ω exceeded the dump "
                                 "resistor's 20 W rating (the question the chopper model "
                                 "exists to answer — see hil_electrical.py P_CHOPPER_MAX_W)"
                                 % n_chop})

    if child.get("status") != "ok":
        checks.append({"name": "child_process", "passed": False,
                       "detail": "child %s (rc=%s)" % (child.get("status"), child.get("returncode"))})

    return all(c["passed"] for c in checks), checks


CHILD_TERM_GRACE_S = 5.0    # M3: SIGTERM grace period before an unconditional kill()


def run_child(item, args):
    """Execute one plan item. Returns the child record (never raises).

    M3: uses Popen + terminate() (not subprocess.run(..., timeout=...), which only
    ever escalates straight to SIGKILL on a timeout) so a wedged hil_plant_sim.py
    child gets a chance to run its own KeyboardInterrupt/finally cleanup (closing
    its CSV and events sidecar cleanly) before being killed outright."""
    argv = full_argv(item, args)
    rec = {"argv": argv, "status": "ok", "returncode": None,
           "wall_s": None, "log": item["log"], "summary": {}}
    # --dashboard TRADE-OFF: the dashboard writes ANSI to stdout, which is
    # useless (and log-bloating) inside a captured pipe — and the child's own
    # tty check would simply disable it, making the flag a no-op.  So with
    # --dashboard we hand the child the real terminal for stdout and capture
    # only stderr.  COST: the per-run summary is parsed from stdout, so the
    # summary columns in REPORT.md are empty for dashboard runs.  That is why
    # the flag is OFF by default: without it, behaviour is byte-identical to
    # before, and reports stay complete.
    dashboard = getattr(args, "dashboard", False)
    if dashboard:
        rec["stdout_passthrough"] = True
    t0 = time.time()
    # D2 guard 3: local wall-clock at launch, in the same ISO-8601-with-offset
    # form the child stamps into its sidecar's "created", so read_run_meta() can
    # reject a sidecar that predates this attempt.  Rounded DOWN to the second
    # (the child's timespec="seconds" truncates), so a child launched at
    # x.900 s stamping x.000 s is not falsely judged stale.
    rec["launched_at"] = (datetime.datetime.fromtimestamp(t0)
                          .replace(microsecond=0).astimezone()
                          .isoformat(timespec="seconds"))
    proc = None
    try:
        proc = subprocess.Popen(argv, cwd=_REPO,
                                stdout=None if dashboard else subprocess.PIPE,
                                stderr=subprocess.PIPE if dashboard
                                else subprocess.STDOUT)
        try:
            out_b, err_b = proc.communicate(timeout=item["timeout_s"])
            out_b = out_b if out_b is not None else (err_b or b"")
            rec["returncode"] = proc.returncode
            if proc.returncode != 0:
                rec["status"] = "nonzero-exit"
            out = out_b.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            proc.terminate()          # SIGTERM: catchable, unlike SIGKILL
            try:
                out_b, err_b = proc.communicate(timeout=CHILD_TERM_GRACE_S)
                out_b = out_b if out_b is not None else (err_b or b"")
            except subprocess.TimeoutExpired:
                proc.kill()            # child ignored/missed SIGTERM -- last resort
                out_b, err_b = proc.communicate()
                out_b = out_b if out_b is not None else (err_b or b"")
            out = out_b.decode("utf-8", "replace")
            out += ("\n[run_hil_suite] *** TIMEOUT after %.1f s — child sent SIGTERM "
                    "(%.0fs grace, then SIGKILL if needed) ***\n"
                    % (item["timeout_s"], CHILD_TERM_GRACE_S))
            rec["status"] = "TIMEOUT"
            rec["returncode"] = proc.returncode
    except OSError as exc:
        out = "[run_hil_suite] could not launch child: %s\n" % exc
        rec["status"] = "launch-failed"
    rec["wall_s"] = time.time() - t0
    rec["summary"] = parse_child_summary(out)
    try:
        with open(item["log"], "w", encoding="utf-8") as fh:
            # L2: list2cmdline quotes the args, so the header line stays
            # copy-pasteable now that the default output path contains a space.
            fh.write(subprocess.list2cmdline(argv) + "\n\n")
            fh.write(out)
    except OSError as exc:
        # L9(b): record the failure instead of silently swallowing it -- the
        # REPORT.md link to this .log must not silently point at nothing.
        rec["log_write_error"] = str(exc)
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# Report generation — PURE: results dicts in, text out. No I/O, no board.
# ─────────────────────────────────────────────────────────────────────────────

def _row(cells):
    return "| " + " | ".join(str(c) for c in cells) + " |"


def render_report(meta, results):
    """Build REPORT.md from the collected result dicts. Pure function."""
    L = []
    A = L.append
    A("# HIL suite report")
    A("")
    A("| | |")
    A("|---|---|")
    A(_row(["Date", meta.get("date", "?")]))
    A(_row(["Board IP:port", "%s:%s" % (meta.get("teensy_ip"), meta.get("port"))]))
    A(_row(["Firmware expectation", "fw v%s, built `-DHIL_SIM=1 -DUSE_ETHERNET=1`"
            % meta.get("target_fw", TARGET_FW_VERSION)]))
    A(_row(["Host", meta.get("host", "?")]))
    A(_row(["Python", meta.get("python", "?")]))
    A(_row(["Command source", {"pi-live": "MODE B — a REAL Pi owned the command link "
                               "(--pi-live); scenarios with their own pi_timeline "
                               "were SKIPPED",
                               "scripted": "scripted (scenario pi_timeline / emulated "
                               "EMS strategy)"}.get(meta.get("mode", "scripted"),
                                                    meta.get("mode"))]))
    A(_row(["Electrical preference", meta.get("electrical_pref", "?")]))
    A(_row(["Settle pause between runs", "%s s" % meta.get("settle_s")]))
    if meta.get("dashboard"):
        # F3: --dashboard hands children the real terminal for stdout, so the
        # per-run summary columns below (and the achieved-rate check) cannot
        # be parsed from a capture -- flag it here, once, instead of leaving
        # the reader to infer it from a wall of "?" cells.
        A(_row(["Dashboard mode", "ON — children ran with --dash; stdout summary "
                                  "columns below are unavailable (see the "
                                  "achieved_rate note on each scenario)"]))
    A(_row(["Runs", "%d (%d scenario, %d replay)"
            % (len(results),
               sum(1 for r in results if r["kind"] == "scenario"),
               sum(1 for r in results if r["kind"] == "replay"))]))
    rates = [r["child"]["summary"].get("achieved_hz") for r in results
             if r.get("child", {}).get("summary", {}).get("achieved_hz") is not None]
    if rates:
        A(_row(["Achieved tick rate", "min %.1f / mean %.1f / max %.1f Hz"
                % (min(rates), sum(rates) / len(rates), max(rates))]))
    npass = sum(1 for r in results if r["passed"])
    nskip = sum(1 for r in results if r.get("skipped"))
    # D3: an inconclusive run whose OTHER checks also failed is BOTH — it is not
    # eligible for the "these are not failures; re-run them" sentence, because
    # something did fail on the record before the evidence was destroyed.
    inc = [r for r in results if r.get("inconclusive")]
    ninc_clean = sum(1 for r in inc if not (r.get("also_failed") or 0))
    ninc_failed = len(inc) - ninc_clean
    A(_row(["Result", "%d/%d passed%s"
            % (npass, len(results),
               # Skipped runs count as passing (they are not board failures), but
               # saying so here stops "13/13 passed" reading as 13 runs executed.
               "  (%d of them SKIPPED, not executed)" % nskip if nskip else "")]))
    if inc:
        parts = []
        if ninc_clean:
            parts.append("%d run(s) saw a MID-RUN HIL warm reset: the board "
                         "restarted underneath the stimulus, so the rest of "
                         "each run was not the scenario its checks assume and "
                         "the verdict proves nothing either way. These are NOT "
                         "failures; re-run them on an unloaded host." % ninc_clean)
        if ninc_failed:
            parts.append("%d further run(s) saw a mid-run warm reset AND had "
                         "check failures of their own — those failures are real "
                         "and are listed per run; re-running clears only the "
                         "inconclusive part." % ninc_failed)
        A(_row(["INCONCLUSIVE", " ".join(parts)]))
    if meta.get("aborted"):
        A(_row(["ABORTED", meta["aborted"]]))
    if meta.get("partial"):
        # M4: this report was written mid-run (or the run was interrupted before
        # the plan finished) -- results.json/REPORT.md are rewritten after every
        # run, so this file is never stale, but it may legitimately be incomplete.
        A(_row(["PARTIAL", "the plan did not run to completion -- this report "
                           "covers only the runs completed so far"]))
    A("")

    # ── Summary table ────────────────────────────────────────────────────────
    A("## Summary")
    A("")
    A(_row(["run", "kind", "mode", "duration", "result", "key metrics"]))
    A(_row(["---"] * 6))
    for r in results:
        dur = r.get("duration_s")
        # F6: a skipped run rendered as "PASS" here, indistinguishable from an
        # executed clean run, and paired with the fabricated-clean detail lines
        # below it looked like a run that had actually happened.
        result_cell = result_label(r, bold_fail=True)
        A(_row([r["name"], r["kind"], r.get("mode", ""),
                ("%.1f s" % dur) if dur else "—",
                result_cell,
                r.get("key_metrics", "")]))
    A("")

    # ── Scenarios ────────────────────────────────────────────────────────────
    scen = [r for r in results if r["kind"] == "scenario"]
    if scen:
        A("## Scenario runs")
        A("")
        A("Scenario entries carry no declarative checks (unlike the replay suite), so")
        A("the checks below are this runner's health criteria: an observation frame must")
        A("have arrived, the fault outcome must match the expectation table, and the")
        A("host must have held the tick rate.")
        A("")
        for r in scen:
            A("### `%s` — %s" % (r["name"], result_label(r)))
            A("")
            if r.get("description"):
                A("*%s*" % r["description"])
                A("")
            if r.get("inconclusive_reason"):
                A("> **INCONCLUSIVE.** %s" % r["inconclusive_reason"])
                A("")
            if r.get("skipped"):
                # F6: no child was ever launched for a skipped run — there is no
                # CSV, no frames, no fault_flags to report. The old code fell
                # through to the metric/frame/fault lines below with empty
                # metrics/events dicts, which rendered as e.g. "final fault_flags
                # 0x0000 (none)" -- a FABRICATED clean result for a run that never
                # happened. Short-circuit entirely instead.
                A("- child: **not run** — %s" % r.get("skip_reason", "skipped"))
                A("")
                for c in r["checks"]:
                    A("  - [%s] **%s** — %s" % ("x" if c["passed"] else " ", c["name"], c["detail"]))
                A("")
                continue
            if r.get("child", {}).get("stdout_passthrough"):
                # F3: explain the '?' frame/rate cells below before the reader
                # hits them, not just in the summary-table header row.
                A("*(ran with `--dashboard`: stdout was passed through to the "
                  "terminal, so the frame/rate summary below is unavailable — "
                  "see the `achieved_rate` check.)*")
                A("")
            m = r.get("metrics", {})
            A("- electrical: **%s** (scenario requires `%s`)"
              % (r.get("mode"), r.get("electrical_required")))
            A("- CSV: `%s` — %d rows, %d with an observation frame"
              % (os.path.basename(m.get("csv", "")), m.get("rows", 0), m.get("n_obs", 0)))
            s = r["child"].get("summary", {})
            A("- frames: tx %s / rx %s (%s malformed); achieved %s Hz, max overrun %s ms"
              % (s.get("tx_frames", "?"), s.get("rx_frames", "?"), s.get("rx_bad", "?"),
                 ("%.1f" % s["achieved_hz"]) if "achieved_hz" in s else "?",
                 ("%.2f" % s["max_overrun_ms"]) if "max_overrun_ms" in s else "?"))
            A("- final `fault_flags`: `0x%04X` (%s); union over the run: %s; final state: %s"
              % (m.get("final_fault_flags") or 0, fault_names(m.get("final_fault_flags") or 0),
                 fault_names(m.get("fault_bits_seen") or 0), m.get("final_state")))
            if m.get("substep_hz_mean") is not None:
                A("- hi-fi substep rate: mean %.0f Hz, min %.0f Hz"
                  % (m["substep_hz_mean"], m["substep_hz_min"]))
            ev = r.get("events", {})
            if ev.get("read_error"):
                # L9(b): a sidecar that failed to READ must not render as a silent
                # "0 events, clean" — it means events on disk were never inspected.
                A("- electrical events: **could not read sidecar** (%s)" % ev["read_error"])
            elif ev.get("total"):
                kinds = ", ".join("%s=%d" % kv for kv in sorted(ev["kinds"].items()))
                A("- electrical events: %d (%s)%s"
                  % (ev["total"], kinds,
                     "; **%d over abs-max**" % ev["over_absmax"] if ev["over_absmax"] else ""))
            log_note = (" **(log write failed: %s)**" % r["child"]["log_write_error"]
                        if r["child"].get("log_write_error") else "")
            A("- child: %s (rc %s, %.1f s wall) — log `%s`%s"
              % (r["child"]["status"], r["child"]["returncode"],
                 r["child"]["wall_s"] or 0.0,
                 os.path.basename(r["child"]["log"]), log_note))
            A("")
            for c in r["checks"]:
                A("  - [%s] **%s** — %s" % ("x" if c["passed"] else " ", c["name"], c["detail"]))
            A("")
            # D4: non-failing observations (currently the grace-window
            # warm-reset note). The scenario half had no notes renderer at all
            # before, so these would have been written to results.json and shown
            # nowhere a human reads.
            for n in r.get("notes", []):
                A("  > NOTE: %s" % n)
            if r.get("notes"):
                A("")

    # ── Replays ──────────────────────────────────────────────────────────────
    rep = [r for r in results if r["kind"] == "replay"]
    if rep:
        A("## Replay suite")
        A("")
        A("Recorded bench logs replayed as OPEN-LOOP stimulus (the firmware's commands")
        A("cannot influence the replayed trajectory). Checks are the declarative ones in")
        A("`tools/hil_replay_suite.py`; the notes carry each entry's fw-delta caveat.")
        A("")
        for group, title in (("conformance", "### Conformance"),
                             ("deviation", "### Deviation")):
            g = [r for r in rep if r.get("mode") == group]
            if not g:
                continue
            A(title)
            A("")
            for r in g:
                A("#### `%s` — %s" % (r["name"], result_label(r)))
                A("")
                if r.get("description"):
                    A("*%s*" % r["description"])
                    A("")
                if r.get("inconclusive_reason"):
                    A("> **INCONCLUSIVE.** %s" % r["inconclusive_reason"])
                    A("")
                if r.get("skipped"):
                    # F5/F6: --pi-live skips the whole replay half — no child, no
                    # CSV, nothing to report but why.
                    A("- child: **not run** — %s" % r.get("skip_reason", "skipped"))
                    A("")
                    for c in r["checks"]:
                        A("  - [%s] **%s** — %s" % ("x" if c["passed"] else " ", c["name"], c["detail"]))
                    A("")
                    continue
                log_note = (" **(log write failed: %s)**" % r["child"]["log_write_error"]
                            if r["child"].get("log_write_error") else "")
                A("- child: %s (rc %s, %.1f s wall) — log `%s`%s, CSV `%s`"
                  % (r["child"]["status"], r["child"]["returncode"],
                     r["child"]["wall_s"] or 0.0,
                     os.path.basename(r["child"]["log"]), log_note,
                     os.path.basename(r.get("csv", ""))))
                for c in r["checks"]:
                    A("  - [%s] **%s** — %s" % ("x" if c["passed"] else " ", c["name"], c["detail"]))
                for n in r.get("notes", []):
                    A("  - _note_: %s" % n)
                A("")

    # ── Known open findings ──────────────────────────────────────────────────
    A("## Known open findings")
    A("")
    A("1. **K_DROOP_BUS design-vs-measured x4 discrepancy.** %s"
      % K_DROOP_FINDING.split(": ", 1)[1])
    over = [r for r in results if r.get("events", {}).get("over_absmax")]
    if over:
        A("")
        A("2. **`sw_ring` events above the 20 V abs-max observed in this run** — the")
        A("   boost-death signature (hil_plant_sim.py's exit banner):")
        for r in over:
            ev = r["events"]
            A("   - `%s`: %d event(s), worst estimated ring peak %s V"
              % (r["name"], ev["over_absmax"],
                 ("%.2f" % ev["worst_ring_v"]) if ev["worst_ring_v"] is not None else "?"))
    else:
        A("")
        A("2. No `sw_ring` event above the 20 V abs-max was observed in this run.")
    for extra in meta.get("extra_findings", []):
        A("")
        A("- %s" % extra)
    A("")

    # ── Appendix ─────────────────────────────────────────────────────────────
    A("## Appendix — artifacts")
    A("")
    A(_row(["file", "run", "kind"]))
    A(_row(["---"] * 3))
    for r in results:
        for key, label in (("csv", "CSV"), ("events_path", "electrical events"),
                           ("log_path", "child stdout/stderr")):
            p = r.get(key)
            if p:
                A(_row(["`%s`" % os.path.basename(p), r["name"], label]))
    A(_row(["`REPORT.md`", "—", "this report"]))
    A(_row(["`results.json`", "—", "machine-readable results"]))
    A(_row(["`plan.json`", "—", "the run plan (also written by --dry-run)"]))
    A("")
    return "\n".join(L) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def warn_short_settle(args):
    """Warn when --settle-s is too short for the fw v23+ run-boundary rule.

    Deliberately a WARNING and not a floor: `--settle-s 0` plus a power-cycle
    between runs is a documented workflow (module docstring), and on pre-v23
    firmware a short settle is merely a shorter latch window.  What it must not
    be is silent — on fw v23+ every run after the first would start from a board
    that never recovered, and every failure after run 1 would be an artifact."""
    if args.settle_s >= SETTLE_MIN_RECOVER_S:
        return
    print("=" * 78)
    print("[suite] WARNING: --settle-s %.2f s may not reliably cross the fw v23+ "
          "RUN BOUNDARY" % args.settle_s)
    print("        (>= 1 s of continuously DEAD injection link) that gates the HIL "
          "warm recovery")
    print("        from State 99 -> State 0. 'May not' is exact: the boundary is "
          "anchored at the")
    print("        board's LAST ACCEPTED FRAME, so the previous child's teardown and "
          "the next")
    print("        child's startup also count toward the dead window — the true gap "
          "is this")
    print("        pause PLUS an unmeasured margin, and whether it clears 1 s is not "
          "decidable")
    print("        from here. When it does not, the board stays latched and every "
          "run after the")
    print("        first starts from a dead board and its result is an artifact.")
    print("        Use --settle-s >= %.1f for margin, or keep this value and "
          "POWER-CYCLE between runs." % SETTLE_MIN_RECOVER_S)
    print("=" * 78)


def print_plan(plan, args):
    print("HIL suite run plan — %d run(s)" % len(plan))
    print("%-14s %-9s %-12s %-9s %s" % ("run", "kind", "mode", "duration", "detail"))
    total = 0.0
    for p in plan:
        d = p.get("duration_s")
        # F14(a): a skipped run launches no child and gets no settle pause either
        # -- it was contributing a phantom settle_s to the wall-time estimate.
        if not p.get("skip_reason"):
            total += (d or 0.0) + args.settle_s
        print("%-14s %-9s %-12s %-9s %s"
              % (p["name"], p["kind"], p.get("mode", ""),
                 ("%.0f s" % d) if d else ("SKIP" if p.get("skip_reason") else "?"),
                 ("SKIPPED — " + p["skip_reason"]) if p.get("skip_reason")
                 else (p.get("description") or "")[:70]))
    print("\nestimated wall time incl. %.0f s settle pauses: %.0f s (%.1f min)"
          % (args.settle_s, total, total / 60.0))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Run every HIL scenario + the replay suite and package a report.")
    ap.add_argument("--teensy-ip", default="192.168.1.50", help="board IP (default 192.168.1.50)")
    ap.add_argument("--port", type=int, default=TEENSY_PORT_DEFAULT,
                    help="board UDP port (default %d, the .ino local_port)" % TEENSY_PORT_DEFAULT)
    ap.add_argument("--out", default=None,
                    help="report directory (default "
                         "'<repo>/HIL Results/hil_report_<YYYYmmdd_HHMMSS>'). An "
                         "explicit relative path is taken relative to the CWD.")
    ap.add_argument("--only", action="append", default=[], metavar="PATTERN",
                    help="glob on the run name; repeatable")
    ap.add_argument("--skip", action="append", default=[], metavar="PATTERN",
                    help="glob on the run name; repeatable")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--replay-only", action="store_true", help="skip the scenario half")
    g.add_argument("--scenarios-only", action="store_true", help="skip the replay half")
    ap.add_argument("--electrical-pref", default="hifi", choices=["hifi", "simple"],
                    help="engine for scenarios whose requirement is 'any' (default hifi)")
    ap.add_argument("--settle-s", type=float, default=DEFAULT_SETTLE_S,
                    help="pause between runs so the board unbinds the host (default %.0f s)"
                         % DEFAULT_SETTLE_S)
    ap.add_argument("--keep-going", action="store_true",
                    help="do not abort when the first run sees no observation frames")
    ap.add_argument("--dashboard", action="store_true",
                    help="run every child with the live dashboard (--dash). OFF by "
                         "default: it takes over the terminal, so children run with "
                         "stdout passed through instead of captured, and the "
                         "stdout-derived summary columns in REPORT.md are empty.")
    ap.add_argument("--pi-live", action="store_true",
                    help="MODE B: a REAL Pi drives the 22-byte command packet; the "
                         "children run with --pi-live and send injection frames only. "
                         "Scenarios carrying their own pi_timeline are SKIPPED (with a "
                         "reason) rather than run against a second command source.")
    ap.add_argument("--list", action="store_true", help="print the run plan and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="build every argv and write plan.json into the report dir; run nothing")
    args = ap.parse_args(argv)

    # F4: --dashboard hands the child the real stdout (see run_child()'s
    # TRADE-OFF comment) so it can draw ANSI directly -- but on a non-tty
    # stdout (piped into a file, captured by CI) that both fails to show a
    # dashboard AND throws away the captured stdout run_child() would
    # otherwise have parsed the per-run summary from. Refuse up front rather
    # than silently degrading both the dashboard and the report.
    if args.dashboard and not sys.stdout.isatty():
        ap.error("--dashboard requires a terminal (stdout is not a tty); "
                 "drop --dashboard or run this in an interactive terminal.")

    # F5: under --pi-live the operator's Pi is a second, uncontrolled stimulus
    # over whatever a replay run injects (replay mode plays recorded rails
    # regardless of what the Pi commands, and — unlike the scenario half — the
    # replay half is not skip-recorded per entry, so --pi-live would silently
    # run all 26 replays with a live Pi fighting the replayed trajectory).
    # --replay-only + --pi-live has NOTHING left to run once the whole replay
    # half is skipped for that reason, so refuse the combination up front
    # rather than producing an empty, confusing plan.
    if args.pi_live and args.replay_only:
        ap.error("--replay-only and --pi-live are mutually exclusive: under "
                 "--pi-live the entire replay half is skipped (a real Pi is an "
                 "uncontrolled second stimulus over a replayed trajectory), which "
                 "would leave --replay-only with nothing to run.")

    if args.out is None:
        # Default report directory lands in the repo-root "HIL Results" folder,
        # the shared home for every HIL artifact (hil_plant_sim.py resolves its
        # own relative --csv paths there too).
        args.out = os.path.join(
            HIL_RESULTS_DIR,
            "hil_report_%s" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(HIL_RESULTS_DIR, exist_ok=True)
    # Children run with cwd = repo root, so every artifact path must be absolute
    # or a relative --out would scatter CSVs into the repo root.  An explicit
    # --out keeps its historical semantics: relative is relative to the CWD.
    # Per-run CSV paths below are built with os.path.join(args.out, ...) and are
    # therefore ABSOLUTE, which hil_plant_sim.resolve_output_path() honors
    # verbatim — the suite's artifacts never get redirected into HIL Results.
    args.out = os.path.abspath(args.out)

    plan = build_plan(args)
    warn_short_settle(args)

    if args.list:
        print_plan(plan, args)
        return 0

    os.makedirs(args.out, exist_ok=True)
    plan_json = [{k: v for k, v in p.items() if k != "entry"} for p in plan]
    for p, pj in zip(plan, plan_json):
        pj["full_argv"] = full_argv(p, args)
    with open(os.path.join(args.out, "plan.json"), "w", encoding="utf-8") as fh:
        json.dump({"out": args.out, "teensy_ip": args.teensy_ip, "port": args.port,
                   "runs": plan_json}, fh, indent=2)

    if args.dry_run:
        print_plan(plan, args)
        print("\n[dry-run] plan written to %s" % os.path.join(args.out, "plan.json"))
        return 0

    problems = verify_suite_logs(_REPO)
    if problems and not args.scenarios_only:
        print("[suite] WARNING: replay-suite log verification found %d problem(s):"
              % len(problems))
        for p in problems:
            print("  - %s" % p)

    def make_meta(aborted_now, partial_now):
        return {
            "date": datetime.datetime.now().isoformat(timespec="seconds"),
            "teensy_ip": args.teensy_ip, "port": args.port,
            "target_fw": TARGET_FW_VERSION,
            "host": "%s %s (%s)" % (platform.system(), platform.release(), platform.machine()),
            "python": platform.python_version(),
            "electrical_pref": args.electrical_pref,
            "settle_s": args.settle_s,
            "out": args.out,
            "aborted": aborted_now,
            # M4: True whenever the plan did not run to completion for ANY reason
            # (Ctrl-C, an abort, or -- belt and suspenders -- a mismatched result
            # count), so a partial results.json/REPORT.md is never mistaken for a
            # clean, complete run.
            "partial": partial_now,
            "suite_log_problems": problems,
            "dashboard": args.dashboard,
            "mode": _suite_mode(args),
        }

    def write_outputs(meta_now, results_now):
        # M4: rewrite BOTH files after every run (not just once at the very end),
        # so a Ctrl-C or a hard kill loses at most the run in flight, never the
        # whole session's worth of already-completed results.
        with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": meta_now, "results": results_now}, fh, indent=2, default=str)
        with open(os.path.join(args.out, "REPORT.md"), "w", encoding="utf-8") as fh:
            fh.write(render_report(meta_now, results_now))

    results = []
    aborted = None
    interrupted = False
    try:
        results, aborted = _run_plan(plan, args, problems, results, write_outputs)
    except KeyboardInterrupt:
        interrupted = True
        print("\n[suite] interrupted (Ctrl-C) — writing partial results", file=sys.stderr)
    finally:
        meta = make_meta(aborted, interrupted or len(results) < len(plan))
        write_outputs(meta, results)

    npass = sum(1 for r in results if r["passed"])
    inc = [r for r in results if r.get("inconclusive")]
    ninc_failed = sum(1 for r in inc if (r.get("also_failed") or 0))
    # An inconclusive run is not a failure of the board, so say so here rather
    # than letting it read as one in the headline number — but D3: one that ALSO
    # failed other checks must not be swept into "just re-run it".
    inc_note = ""
    if inc:
        inc_note = (", %d INCONCLUSIVE (mid-run warm reset — re-run those)"
                    % len(inc))
        if ninc_failed:
            inc_note += (" of which %d ALSO failed checks of their own"
                         % ninc_failed)
    print("\n[suite] %d/%d passed%s — report: %s"
          % (npass, len(results), inc_note,
             os.path.join(args.out, "REPORT.md")))

    if interrupted:
        return 130
    if aborted:
        return 2
    # F6: every planned run being skipped (e.g. --pi-live over a plan whose
    # scenario half is ALL pi_timeline/ems entries) is not a passing suite run —
    # nothing was ever actually exercised against the board. The old
    # `npass == len(results) and results` check let an all-skips run exit 0
    # because skipped runs count as "passed".
    if results and all(r.get("skipped") for r in results):
        print("[suite] every planned run was SKIPPED — nothing was exercised "
              "against the board; treating this as a failing suite run", file=sys.stderr)
        return 1
    return 0 if npass == len(results) and results else 1


def _run_plan(plan, args, problems, results, write_outputs):
    """The per-run loop, factored out of main() so M4's try/except/finally around
    it can rewrite results.json/REPORT.md after every run without duplicating the
    run body. Mutates and returns `results`; returns (results, aborted)."""
    aborted = None
    for i, item in enumerate(plan):
        if item.get("skip_reason"):
            # Recorded as a PASSING, explicitly-skipped run: it is not a failure of
            # the board, and silently dropping it would make the report's run count
            # differ between modes with nothing to explain why.
            print("[suite] (%d/%d) %s %s ... SKIPPED (%s)"
                  % (i + 1, len(plan), item["kind"], item["name"], item["skip_reason"]),
                  flush=True)
            results.append({
                "kind": item["kind"], "name": item["name"], "mode": item.get("mode", ""),
                "electrical_required": item.get("electrical_required"),
                "description": item.get("description", ""), "duration_s": 0.0,
                "cmd_mode": _suite_mode(args),
                "passed": True, "skipped": True, "skip_reason": item["skip_reason"],
                "checks": [{"name": "skipped", "passed": True,
                            "detail": item["skip_reason"]}],
                "notes": [], "metrics": {}, "events": {},
                "child": {"status": "skipped", "summary": {}},
                "csv": None, "events_path": None, "log_path": None,
                "key_metrics": "skipped",
            })
            write_outputs(
                {"date": datetime.datetime.now().isoformat(timespec="seconds"),
                 "teensy_ip": args.teensy_ip, "port": args.port,
                 "target_fw": TARGET_FW_VERSION,
                 "host": "%s %s (%s)" % (platform.system(), platform.release(),
                                         platform.machine()),
                 "python": platform.python_version(),
                 "electrical_pref": args.electrical_pref, "settle_s": args.settle_s,
                 "out": args.out, "aborted": aborted,
                 "partial": (i + 1) < len(plan),
                 "suite_log_problems": problems,
                 "mode": _suite_mode(args)},
                results)
            continue

        print("[suite] (%d/%d) %s %s ..." % (i + 1, len(plan), item["kind"], item["name"]),
              flush=True)
        child = run_child(item, args)

        # Mid-run warm-reset tripwire — applied to BOTH halves.  The replay half
        # needs it at least as much as the scenario half: its `fault_latched`
        # checks are exactly the ones a silently-cleared latch turns into a false
        # PASS.
        wr_counts, wr_source = warm_reset_count(item["csv"], child)
        wr_check, wr_note, wr_reason = judge_warm_resets(
            item["name"], item["kind"], wr_counts, wr_source)

        if item["kind"] == "scenario":
            metrics = analyze_scenario_csv(item["csv"])
            events = analyze_events(item["events"])
            passed, checks = judge_scenario(item["name"], metrics, events, child,
                                            pi_live=getattr(args, "pi_live", False),
                                            duration_s=item.get("duration_s"))
            key = "obs %d/%d, faults %s" % (metrics["n_obs"], metrics["rows"],
                                            fault_names(metrics["fault_bits_seen"] or 0))
            res = {"kind": "scenario", "name": item["name"], "mode": item["mode"],
                   "cmd_mode": _suite_mode(args),
                   "electrical_required": item["electrical_required"],
                   "description": item["description"], "duration_s": item["duration_s"],
                   "passed": passed, "checks": checks, "notes": [],
                   "metrics": metrics, "events": events, "child": child,
                   "csv": item["csv"], "events_path": item["events"],
                   "log_path": item["log"], "key_metrics": key}
            no_obs = metrics["n_obs"] == 0
        else:
            ev = evaluate_replay_csv(item["entry"], item["csv"])
            checks = list(ev["checks"])
            if child["status"] != "ok":
                checks.append({"name": "child_process", "passed": False,
                               "detail": "child %s (rc=%s)" % (child["status"],
                                                               child["returncode"])})
            passed = ev["passed"] and child["status"] == "ok"
            npass = sum(1 for c in checks if c["passed"])
            res = {"kind": "replay", "name": item["name"], "mode": item["mode"],
                   "cmd_mode": _suite_mode(args),
                   "description": item["description"], "duration_s": item["duration_s"],
                   "passed": passed, "checks": checks, "notes": ev.get("notes", []),
                   "metrics": {}, "events": {}, "child": child,
                   "csv": item["csv"], "events_path": None, "log_path": item["log"],
                   "key_metrics": "%d/%d checks passed" % (npass, len(checks))}
            # L8: evaluate_replay_csv() now returns a structured "n_obs" (None if
            # the CSV itself could not be loaded/parsed at all) instead of forcing
            # this caller to substring-match a prose note from a different module.
            # Treat "unknown" the same as "zero" for the abort decision: a CSV that
            # never even parsed is at least as strong evidence the board never
            # answered as a CSV with zero observation rows.
            no_obs = ev.get("n_obs") in (0, None)

        # Fold the tripwire in AFTER the half-specific judging, so it applies
        # uniformly and cannot be forgotten by either branch.  An inconclusive
        # run is deliberately NOT counted as passing (it must be re-run), but it
        # is flagged separately so the report never renders it as a plain FAIL —
        # nothing was proven wrong about the board, the evidence was destroyed.
        # D3: whether any OTHER check failed is decided BEFORE the tripwire is
        # folded in, so an inconclusive verdict can never hide a real failure.
        other_failures = sum(1 for c in res["checks"] if not c["passed"])
        res["checks"] = list(res["checks"]) + [wr_check]
        res["warm_resets_mid_run"] = wr_counts.get("mid_run")
        res["warm_resets_observed"] = wr_counts.get("observed")
        res["warm_reset_times_s"] = wr_counts.get("times")
        res["warm_reset_source"] = wr_source
        if wr_note:
            res["notes"] = list(res.get("notes") or []) + [wr_note]
        if wr_reason is not None:
            res["inconclusive"] = True
            res["inconclusive_reason"] = wr_reason
            res["also_failed"] = other_failures
            res["passed"] = False
        elif not wr_check["passed"]:
            res["passed"] = False          # an EXPECTED recovery that never happened
        res["key_metrics"] += ", %s" % (
            ("INCONCLUSIVE — %s mid-run warm reset(s)%s"
             % (wr_counts.get("mid_run"),
                "; also FAILED %d check(s)" % other_failures if other_failures else ""))
            if wr_reason is not None else
            ("warm resets %s" % ("?" if wr_counts.get("mid_run") is None
                                 else wr_counts["mid_run"])))

        results.append(res)
        print("    -> %s (%s)"
              % (result_label(res), res["key_metrics"]))
        if wr_note:
            print("       NOTE: %s" % wr_note)

        # M4: rewrite the report after every completed run (not just at the very
        # end), so an interruption below or later in the plan loses at most the
        # run in flight. `partial=True` here is provisional -- main()'s finally
        # block writes the authoritative final meta once the loop actually exits.
        write_outputs(
            {"date": datetime.datetime.now().isoformat(timespec="seconds"),
             "teensy_ip": args.teensy_ip, "port": args.port,
             "target_fw": TARGET_FW_VERSION,
             "host": "%s %s (%s)" % (platform.system(), platform.release(), platform.machine()),
             "python": platform.python_version(),
             "electrical_pref": args.electrical_pref, "settle_s": args.settle_s,
             "out": args.out, "aborted": aborted,
             "partial": (i + 1) < len(plan),
             "suite_log_problems": problems,
             "mode": _suite_mode(args)},
            results)

        if i == 0 and no_obs and not args.keep_going:
            aborted = ("board unreachable: the first run (%s) saw ZERO observation "
                       "frames. Aborting rather than grinding through %d more dead run(s). "
                       "Check the flash flags (-DHIL_SIM=1 -DUSE_ETHERNET=1), the IP "
                       "(%s:%d) and that host and board share an L2 segment. "
                       "Pass --keep-going to run the whole plan anyway."
                       % (item["name"], len(plan) - 1, args.teensy_ip, args.port))
            print("[suite] " + aborted, file=sys.stderr)
            break

        if i + 1 < len(plan) and args.settle_s > 0:
            time.sleep(args.settle_s)

    return results, aborted


if __name__ == "__main__":
    sys.exit(main())

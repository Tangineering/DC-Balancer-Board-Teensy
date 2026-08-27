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

EXIT CODES
  0  every run passed
  1  at least one run failed
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
sys.path.insert(0, _HERE)

from hil_plant_sim import SCENARIOS, TEENSY_PORT_DEFAULT            # noqa: E402
from hil_replay_suite import (                                      # noqa: E402
    REPLAY_SUITE, FAULT_NAMES, TARGET_FW_VERSION,
    build_sim_argv, evaluate_replay_csv, replay_csv_path, verify_suite_logs,
)

SIM_SCRIPT = os.path.join(_HERE, "hil_plant_sim.py")
GRACE_S = 30.0                 # timeout = expected duration + this
DEFAULT_SETTLE_S = 5.0         # >> HIL_ZERO_MS (250 ms); see module docstring

# ─────────────────────────────────────────────────────────────────────────────
# Which scenarios EXPECT the board to latch a fault.
#
# Sources, per entry (do not extend this table from intuition — cite a source):
#   sag           docs/HIL_MODE.md test H2: "mainState 99 and fault_flags with the
#                 UV bit set, latched" for the -5 V / 1 s dip past LIMIT_V_BUS_MIN.
#   comm-loss     The scenario stops transmitting for 1 s, which is past the
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
FAULT_REQUIRED = {
    "sag": ("docs/HIL_MODE.md H2 — UV_BUS latched by the -5 V / 1 s dip", 0x0100),
    "comm-loss": ("docs/HIL_MODE.md link-loss — 1 s gap > 250 ms zero stage, "
                  "ERR_HIL_STALE (FAULT_HIL_LINK aliases FAULT_PI_TIMEOUT 0x0010)",
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

    if not args.replay_only:
        for name, meta in SCENARIOS.items():
            need = meta.get("electrical", "any")
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
    return ([sys.executable, SIM_SCRIPT] + plan_item["argv"]
            + ["--teensy-ip", args.teensy_ip, "--port", str(args.port)])


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


def judge_scenario(name, metrics, events, child):
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
        checks.append({"name": "no_unexpected_fault", "passed": seen == 0,
                       "detail": "fault_flags union over the run = %s" % fault_names(seen)})

    rate = (child.get("summary") or {}).get("achieved_hz")
    if rate is not None:
        checks.append({"name": "achieved_rate", "passed": rate >= 900.0,
                       "detail": "%.1f Hz achieved (target 1000; host-stall gate 900)" % rate})

    if events["over_absmax"]:
        checks.append({"name": "sw_ring_over_absmax", "passed": False,
                       "detail": "%d switching event(s) with an estimated ring peak above "
                                 "the 20 V abs-max — the boost-death signature; worst %s V"
                                 % (events["over_absmax"],
                                    ("%.2f" % events["worst_ring_v"])
                                    if events["worst_ring_v"] is not None else "?")})

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
    t0 = time.time()
    proc = None
    try:
        proc = subprocess.Popen(argv, cwd=_REPO, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        try:
            out_b, _ = proc.communicate(timeout=item["timeout_s"])
            rec["returncode"] = proc.returncode
            if proc.returncode != 0:
                rec["status"] = "nonzero-exit"
            out = out_b.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            proc.terminate()          # SIGTERM: catchable, unlike SIGKILL
            try:
                out_b, _ = proc.communicate(timeout=CHILD_TERM_GRACE_S)
            except subprocess.TimeoutExpired:
                proc.kill()            # child ignored/missed SIGTERM -- last resort
                out_b, _ = proc.communicate()
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
            fh.write(" ".join(argv) + "\n\n")
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
    A(_row(["Electrical preference", meta.get("electrical_pref", "?")]))
    A(_row(["Settle pause between runs", "%s s" % meta.get("settle_s")]))
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
    A(_row(["Result", "%d/%d passed" % (npass, len(results))]))
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
        A(_row([r["name"], r["kind"], r.get("mode", ""),
                ("%.1f s" % dur) if dur else "—",
                "PASS" if r["passed"] else "**FAIL**",
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
            A("### `%s` — %s" % (r["name"], "PASS" if r["passed"] else "FAIL"))
            A("")
            if r.get("description"):
                A("*%s*" % r["description"])
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
              % (r["child"]["status"], r["child"]["returncode"], r["child"]["wall_s"] or 0.0,
                 os.path.basename(r["child"]["log"]), log_note))
            A("")
            for c in r["checks"]:
                A("  - [%s] **%s** — %s" % ("x" if c["passed"] else " ", c["name"], c["detail"]))
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
                A("#### `%s` — %s" % (r["name"], "PASS" if r["passed"] else "FAIL"))
                A("")
                if r.get("description"):
                    A("*%s*" % r["description"])
                    A("")
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

def print_plan(plan, args):
    print("HIL suite run plan — %d run(s)" % len(plan))
    print("%-14s %-9s %-12s %-9s %s" % ("run", "kind", "mode", "duration", "detail"))
    total = 0.0
    for p in plan:
        d = p.get("duration_s")
        total += (d or 0.0) + args.settle_s
        print("%-14s %-9s %-12s %-9s %s"
              % (p["name"], p["kind"], p.get("mode", ""),
                 ("%.0f s" % d) if d else "?",
                 (p.get("description") or "")[:70]))
    print("\nestimated wall time incl. %.0f s settle pauses: %.0f s (%.1f min)"
          % (args.settle_s, total, total / 60.0))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Run every HIL scenario + the replay suite and package a report.")
    ap.add_argument("--teensy-ip", default="192.168.1.50", help="board IP (default 192.168.1.50)")
    ap.add_argument("--port", type=int, default=TEENSY_PORT_DEFAULT,
                    help="board UDP port (default %d, the .ino local_port)" % TEENSY_PORT_DEFAULT)
    ap.add_argument("--out", default=None,
                    help="report directory (default hil_report_<YYYYmmdd_HHMMSS>/)")
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
    ap.add_argument("--list", action="store_true", help="print the run plan and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="build every argv and write plan.json into the report dir; run nothing")
    args = ap.parse_args(argv)

    if args.out is None:
        args.out = "hil_report_%s" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # Children run with cwd = repo root, so every artifact path must be absolute
    # or a relative --out would scatter CSVs into the repo root.
    args.out = os.path.abspath(args.out)

    plan = build_plan(args)

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
    print("\n[suite] %d/%d passed — report: %s"
          % (npass, len(results), os.path.join(args.out, "REPORT.md")))

    if interrupted:
        return 130
    if aborted:
        return 2
    return 0 if npass == len(results) and results else 1


def _run_plan(plan, args, problems, results, write_outputs):
    """The per-run loop, factored out of main() so M4's try/except/finally around
    it can rewrite results.json/REPORT.md after every run without duplicating the
    run body. Mutates and returns `results`; returns (results, aborted)."""
    aborted = None
    for i, item in enumerate(plan):
        print("[suite] (%d/%d) %s %s ..." % (i + 1, len(plan), item["kind"], item["name"]),
              flush=True)
        child = run_child(item, args)

        if item["kind"] == "scenario":
            metrics = analyze_scenario_csv(item["csv"])
            events = analyze_events(item["events"])
            passed, checks = judge_scenario(item["name"], metrics, events, child)
            key = "obs %d/%d, faults %s" % (metrics["n_obs"], metrics["rows"],
                                            fault_names(metrics["fault_bits_seen"] or 0))
            res = {"kind": "scenario", "name": item["name"], "mode": item["mode"],
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

        results.append(res)
        print("    -> %s (%s)" % ("PASS" if passed else "FAIL", res["key_metrics"]))

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
             "suite_log_problems": problems},
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

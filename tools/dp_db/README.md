# `tools/dp_db/` — solved DP hydrogen baselines

This directory is the results database read by `tools/dp_results_db.py` and,
through it, by `tools/hil_report_analysis.py --matched-dp`.

## Purpose

A hydrogen comparison between two energy-management strategies is valid only at
matched terminal state of charge. Every HIL run that executed a drive cycle
therefore needs a dynamic-programming baseline solved to that run's own terminal
SoC. The solve is expensive — a few seconds for the 61 s `ems-soc-band` cycle,
tens of minutes for the 340 s FTP-75 — so solves are computed once, stored here,
and looked up afterwards.

## Layout

- `index.json` — a listing of every record. It is a CACHE. It is rebuilt from
  the solve files by every `store()` and by `dp_results_db.py rebuild-index`,
  and it is never the authority.
- `solves/<key>.json` — one solve. The key is a sha256 over the problem: the
  scenario, its profile fingerprint, the pack and grid parameters, the charger
  accounting, the auxiliary preload, and the eight model quantities the
  generated DP table header records. The terminal-SoC target is part of the key, quantized
  to 1e-5 SoC.

## Provenance

Each record carries the sha256 of `gen_dp_ems_table.py`'s source and
`hil_plant_sim`'s `constants_hash` at solve time. A lookup compares the
constants hash only, and a mismatch is reported as `provenance_drift` on the
returned record rather than hiding it: the hash also moves when a constant this
solve never reads moves, so drift is a warning and not proof of a stale
baseline. The generator's source sha is recorded but never compared — a comment
edit moves it without moving a number.

## Reuse rule

A record answers one problem. A retune of any imported simulator constant
changes the key, so the pre-retune records become unreachable rather than
silently wrong. Lookup accepts a stored target within 1e-5 SoC of the requested
one and reports the stored target alongside the result. The tolerance is
deliberately tight: on the 61 s EMS cycle the whole SoC swing is ~2e-3, and a
looser one returns a baseline solved for a materially different SoC outcome.

## Commands

    python tools/dp_results_db.py list [--scenario NAME]
    python tools/dp_results_db.py show <key-or-prefix>
    python tools/dp_results_db.py rebuild-index
    python tools/dp_results_db.py rekey
    python tools/dp_results_db.py prefill --key-fields @missing_key.json
    python tools/dp_results_db.py prefill --scenario ems-soc-band \
        --soc0 0.7 --accounting physical --dsoc-span=-0.0030:-0.0010:5

`prefill --key-fields` solves exactly the problem an analysis block reported as
uncached: paste that block's `key_fields` object into a file and hand it over.
It is the reliable form, because a prefill rebuilt from individual flags can
miss an input and solve a different problem. `rekey` re-files records whose key
predates a change to the target quantum; it is arithmetic on the stored target
and never a re-solve.

`prefill` needs an interpreter with numpy. The other commands are stdlib only.
It skips a target already cached within `--tol` (default 1e-5 SoC), so a span
whose step is not larger than that solves its first target and reports the rest
as cached. It is safe to interrupt: each record is written atomically before
the next solve starts.

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
  accounting, the auxiliary preload, the charger efficiency, and the eight model
  quantities the generated DP table header records. The terminal-SoC target is
  part of the key, quantized to 1e-5 SoC.

## Charger era (`eta_chg`)

`eta_chg` is an OPTIONAL key field, added 2026-09-01 with the charger-efficiency
round. It names the model a solve billed the Ag105 under:

- **absent, or null — the 1:1 current-transfer era.** A delivered amp cost a bus
  amp, i.e. `V_bus·i_chg` watts. Every record stored before 2026-09-01 is this
  era. An absent optional field is OMITTED from the canonical key form, so the
  `eta_chg` KEY FIELD itself leaves an old-era key byte-identical to the one the
  pre-change code computed.

  That was not the whole key, and the first version of this round briefly broke
  it. `eta_chg` also joined `hil_plant_sim.DP_FINGERPRINT_META_KEYS`, and the
  profile fingerprint IS a key field, so hashing `eta_chg=None` as a LINE moved
  every pre-existing fingerprint and orphaned all 16 stored records. The
  fingerprint now applies the SAME omission convention (orchestrator ruling,
  2026-09-02): a key in `DP_FINGERPRINT_OPTIONAL_KEYS` that resolves to None
  contributes no line at all. Old-era digests are therefore back where they
  were and the stored records are reachable again.
- **a float — the energy-conserving converter.** A delivered amp costs
  `V_pack·i_chg/eta` watts. A new-era record keys differently, which is the
  point: a baseline solved against a different charger is not a baseline for
  this one.

A run's own value comes off its sidecar meta (`charger_power.resolve_eta_chg`,
where a missing key is the old era). `prefill --eta-chg` sets it explicitly, and
`--eta-chg-none` forces the old era (the two are mutually exclusive and a
prefill passing both is refused); the value also travels inside a `--key-fields`
object and inside `era_overrides`, which accepts `eta_chg` like any other
fingerprint key.

A post-η run keys and FINGERPRINTS separately from a pre-η one: its sidecar
carries `eta_chg`, so the term is present in its canonical string. `prefill
--scenario --eta-chg` therefore resolves the era into the fingerprint meta as
well as into the key field — a live scenario declares no `eta_chg` of its own,
and fingerprinting the live meta while keying an explicit era would seed a
record no post-η lookup could ever hit.

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

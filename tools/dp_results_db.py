#!/usr/bin/env python3
"""dp_results_db.py — a reusable store of solved DP hydrogen baselines.

WHY THIS EXISTS
═══════════════════════════════════════════════════════════════════════════
A hydrogen comparison between two energy-management strategies is only valid
at MATCHED TERMINAL SoC, so every HIL run that executed a drive cycle needs a
DP baseline solved to that run's OWN terminal SoC (WORK_QUEUE §1, operator
ruling 2026-09-01).  Those solves are expensive: the 61 s `ems-soc-band`
cycle costs a few seconds per matched solve, and the 340 s FTP-75 costs tens
of minutes.  Re-solving one on every invocation of the analysis pipeline is
not affordable, and solving inside an analysis pass makes the pass's cost
depend on the campaign's contents.

So the solves live HERE, keyed on the problem they answer, and the analysis
pipeline's DEFAULT mode is LOOKUP ONLY.  Compute is scheduled separately, by
`prefill`, when a machine is free.

WHAT A KEY MEANS
═══════════════════════════════════════════════════════════════════════════
The key is a sha256 over a canonical JSON of every input that changes the
answer: the scenario and its `profile_fingerprint` (which already covers the
speed profile, the duration, the charge ceiling and the declared preload),
the pack and grid parameters, the charger accounting, and the eight model
quantities the generated table's header records as its drift guard.  A record
is therefore reusable ONLY by a caller whose problem is identical in every
one of them — a retune of any imported simulator constant produces a
different key, and the stale record becomes unreachable rather than wrong.

The TARGET SoC is part of the key, quantized to DP_DB_TARGET_QUANTUM.  It is
also matched with a tolerance on lookup (DP_DB_LOOKUP_TOL), because two runs
of one scenario land on terminal SoCs that differ by less than the DP's own
match residual and do not deserve two solves.  `lookup()` returns the NEAREST
stored target within the tolerance among the records that agree on every
other field, and the record carries its own unrounded target and residual so
the caller can report what it actually got.

STORE LAYOUT
═══════════════════════════════════════════════════════════════════════════
    tools/dp_db/index.json          — a listing, REBUILDABLE from the records
    tools/dp_db/solves/<key>.json   — one solve, the authority

The index is a cache and is never trusted alone: `store()` rebuilds it from
the files on disk, and `rebuild-index` restores it after a manual deletion.
Both writes are atomic (temp file + os.replace), so an interrupted prefill
leaves a consistent store.

DEPENDENCIES
═══════════════════════════════════════════════════════════════════════════
Storage, lookup and the `list` / `show` / `rebuild-index` commands are
STDLIB-ONLY, so any interpreter can read the store.  SOLVING imports
tools/gen_dp_ems_table.py, which needs numpy; that import is lazy and only
`solve_and_store` and `prefill` take it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
import warnings
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

DP_DB_DIR = os.path.join(_HERE, "dp_db")
DP_DB_INDEX = os.path.join(DP_DB_DIR, "index.json")
DP_DB_SOLVES = os.path.join(DP_DB_DIR, "solves")

# Target-SoC quantum used in the KEY.  1e-5 SoC is 0.5 % of this rig's 61 s
# cycle swing and 5x the DP's own match tolerance, so it collapses the
# accidental spread of two nominally identical runs into one key without
# merging two genuinely different SoC outcomes.  It tracks DP_DB_LOOKUP_TOL
# below and was tightened with it (2026-09-01).
DP_DB_TARGET_QUANTUM = 1.0e-5

# Tolerance a LOOKUP accepts between the caller's target and a stored one.
#
# TIGHTENED 5e-4 -> 1e-5 (orchestrator decision, 2026-09-01).  The whole SoC
# swing of the 61 s EMS cycle is ~2e-3, so a 5e-4 tolerance let a baseline
# miss the run's terminal SoC by a QUARTER of the swing, and the deviation it
# produced was not the run's: campaign-080905's `soc-band` leg read +22.29 %
# against a baseline solved at 0.697500 for a run that ended at 0.697940,
# where the true deviation is +10.79 %.  A tolerance that admits a wrong
# number is worse than one that misses, because a miss is visible and a wrong
# number is not.  1e-5 is 0.5 % of the swing, and the cost of the resulting
# miss is ONE solve of ~13 s per uncached run on this cycle.  Widen it
# deliberately (--matched-dp-tol) only for a cycle whose swing is far larger.
DP_DB_LOOKUP_TOL = 1.0e-5

# The quantum must never be coarser than the tolerance: a coarser one would
# move a caller's target further from the stored value than the tolerance
# admits, so a record could be unreachable by the very target that produced it.
assert DP_DB_TARGET_QUANTUM <= DP_DB_LOOKUP_TOL, (
    "DP_DB_TARGET_QUANTUM (%g) must be <= DP_DB_LOOKUP_TOL (%g)"
    % (DP_DB_TARGET_QUANTUM, DP_DB_LOOKUP_TOL))

# Trajectory storage stride.  A 61 s cycle at 0.1 s stages is 610 points and
# is stored whole; a 340 s cycle is 3400 and is stored every 10th stage, which
# is enough to see the policy's shape without making the record large.
DP_DB_TRAJ_FULL_MAX = 1200
DP_DB_TRAJ_STRIDE = 10

# Every field that participates in the key, in a FIXED order.  `target_soc_q`
# is listed last and is the only one lookup() is allowed to vary.
KEY_FIELDS = (
    "scenario", "profile_fingerprint", "soc0", "capacity_ah",
    "charger_accounting", "stage_dt", "n_share", "soc_step", "chg_a",
    "lambda_dev", "aux_preload_a", "eta_chg", "loss_map",
    "drag", "eta_regen",
    "gfc_dc_gain", "eta_boost", "limit_i_fc_max_a", "charge_share_value",
    "share_span", "cruise_slope_max", "cruise_min_mps", "run_entry_s",
    "run_exit_s",
    "target_soc_q",
)

# Key fields that may be ABSENT or None, and are then OMITTED from the
# canonical form rather than encoded as a null (2026-09-01, the
# charger-efficiency round).
#
# WHY OMISSION AND NOT A NULL.  `eta_chg` names the CHARGER ERA: None is the
# 1:1 current-transfer charger every record in this store was solved against.
# Encoding it as an explicit null would put a new entry in the canonical JSON
# and move EVERY existing record's key, so every archived solve would become
# unreachable by an old-era lookup that is asking for exactly the problem the
# record answers.  Omitting an absent optional field keeps the old-era
# canonical string byte-identical to the pre-2026-09-01 one, so
#   missing key  <->  None  <->  the old era
# are one thing, and a NEW-era record (eta_chg 0.88) keys differently, which
# is the whole point: a baseline solved against a different charger model is
# not a baseline for this one.
# `loss_map` JOINED 2026-09-02 (the DP-bound round), on exactly these terms
# and for the same reason: an ABSENT map names the LOSS-MAP-FREE demand model
# every record in this store was solved against, so omitting it keeps all 30
# stored records reachable by the old-era lookup that is asking for the problem
# they answer.  It is carried as the CANONICAL STRING
# (`hil_plant_sim.loss_map_canonical`), not as a dict: `_canonical()` renders a
# str verbatim and a float through repr(), and a dict is neither.
# `drag` and `eta_regen` JOINED 2026-09-02 (the ftp75c round), on exactly
# these terms again.  An ABSENT `drag` names the MEASURED RIG ROAD LOAD and
# an ABSENT `eta_regen` the PRE-REGEN demand model, which is what every
# record in this store was solved against, so omitting both keeps all of
# them reachable.  `drag` is carried as its MODE STRING (`_canonical()`
# renders a str verbatim), and the rig mode resolves to None rather than to
# the literal "rig" so that "absent" and "rig" are one statement.
OPTIONAL_KEY_FIELDS = ("eta_chg", "loss_map", "drag", "eta_regen")

_NON_TARGET_FIELDS = tuple(f for f in KEY_FIELDS if f != "target_soc_q")


# ─────────────────────────────────────────────────────────────────────────────
# Keying
# ─────────────────────────────────────────────────────────────────────────────
def _canonical(fields):
    """The canonical JSON text a key is taken over.

    Floats go through repr() as strings so a value's exact bits decide the
    key: 0.1 and 0.1000000000000001 are different problems, and JSON's own
    float rendering would not always separate them."""
    out = {}
    for name in KEY_FIELDS:
        if name not in fields:
            if name in OPTIONAL_KEY_FIELDS:
                continue          # absent optional field: omitted, see above
            raise KeyError("key field %r is missing" % name)
        val = fields[name]
        if val is None and name in OPTIONAL_KEY_FIELDS:
            continue              # None optional field: the same omission
        out[name] = val if isinstance(val, str) or val is None else repr(float(val))
    return json.dumps(out, sort_keys=True, separators=(",", ":"))


def quantize_target(target_soc):
    """The key's target field: `target_soc` on the DP_DB_TARGET_QUANTUM grid."""
    return round(round(float(target_soc) / DP_DB_TARGET_QUANTUM)
                 * DP_DB_TARGET_QUANTUM, 12)


def make_key(fields):
    """sha256 (hex) over the canonical form of a complete key-field dict."""
    return hashlib.sha256(_canonical(fields).encode("utf-8")).hexdigest()


def non_target_hash(fields):
    """sha256 (hex) over the key fields EXCEPT the target.

    The index stores this per record so `lookup()` can find every record that
    shares a problem and differs only in its SoC target without opening any of
    them."""
    sub = {name: fields[name] for name in _NON_TARGET_FIELDS
           if name in fields}
    sub["target_soc_q"] = None
    return hashlib.sha256(_canonical(sub).encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Stimulus era
# ─────────────────────────────────────────────────────────────────────────────
def apply_era_overrides(scen_meta, era_overrides):
    """A scenario meta with the RUN-ERA values put back.

    The profile fingerprint is taken over hil_plant_sim's
    DP_FINGERPRINT_META_KEYS, of which the auxiliary preload is only one:
    `chg_i_ceiling_a`, `duration_s` and the speed profile itself are in it too.
    An archived run executed under the metadata of ITS OWN era, and a baseline
    for that run must be solved against that metadata, so every fingerprint
    key the run's sidecar can supply is overridden here rather than only the
    preload (MED, 2026-09-01: a parallel round moved the FTP-75 preload and
    added a charge ceiling, and preload-only reconstruction then refused every
    archived FTP-75 run for fingerprint drift).

    Keys whose value is None are DELETED rather than set, so "the run-era meta
    declared nothing here" is expressible and hashes as the absent key does."""
    meta = dict(scen_meta or {})
    for key, val in (era_overrides or {}).items():
        if val is None:
            meta.pop(key, None)
        else:
            meta[key] = val
    return meta


def fingerprint_parts(scenario, meta):
    """Per-key contributions to hil_plant_sim.dp_profile_fingerprint().

    A sha256 cannot be inverted, so a mismatch between two fingerprints can
    only be EXPLAINED by recomputing both sides' inputs.  This reproduces the
    canonical string that function builds, key by key, and `_self_check`
    confirms the reproduction still hashes to the same digest — if
    dp_profile_fingerprint's construction ever changes, this raises instead of
    reporting a confident but wrong diff."""
    import hil_plant_sim as sim
    parts = {"scenario": "scenario=%s" % scenario}
    # Per-key RESOLVERS the fingerprint applies before hashing.  `eta_chg` is
    # the first MODEL constant in the tuple (2026-09-01): an absent key means
    # "the module's own ETA_CHG", not None, so reproducing the canonical
    # string requires the same resolution the simulator makes.  The lookup is
    # by getattr so this file still works against a checkout whose
    # hil_plant_sim predates the resolver; `_self_check` in fingerprint_diff()
    # catches any resolver this mirror ever misses.
    resolvers = {}
    _eta = getattr(sim, "dp_eta_chg", None)
    if callable(_eta):
        resolvers["eta_chg"] = _eta
    # H3 (orchestrator ruling, 2026-09-02): an OPTIONAL key whose resolver
    # returns None contributes NO LINE at all - the old era is the ABSENCE of
    # the term, which is what keeps every pre-2026-09-01 digest (and the 16
    # stored records keyed on one) exactly where it was.  Mirrored from
    # dp_profile_fingerprint(); `_self_check` in fingerprint_diff() is what
    # catches a future divergence.
    optional = frozenset(getattr(sim, "DP_FINGERPRINT_OPTIONAL_KEYS", ()))
    _resolve = getattr(sim, "_dp_fp_resolve", None)
    for key in sim.DP_FINGERPRINT_META_KEYS:
        val = meta.get(key)
        if key in optional and callable(_resolve) \
                and _resolve(key, meta) is None:
            continue
        if key in resolvers:
            val = resolvers[key](meta)
        if key == "loss_map":
            # Mirrors dp_profile_fingerprint(): the digest carries the map's
            # CANONICAL STRING, not a dict repr.  Resolved through the
            # simulator's own renderer so the two cannot drift.
            _canon = getattr(sim, "loss_map_canonical", None)
            _dpl = getattr(sim, "dp_loss_map", None)
            if callable(_canon) and callable(_dpl):
                val = _canon(_dpl(meta))
        elif key == "drag":
            # Mirrors dp_profile_fingerprint(): a MODE STRING, hashed as
            # itself, with the rig mode resolved to None by `_dp_fp_resolve`
            # above and therefore already omitted.
            _dd = getattr(sim, "dp_drag_mode", None)
            if callable(_dd):
                val = _dd(meta)
        elif key == "eta_regen":
            _de = getattr(sim, "dp_eta_regen", None)
            if callable(_de):
                val = _de(meta)
        elif key == "ems_v_profile" and val:
            val = [(float(a), float(b)) for a, b in val]
        elif val is not None:
            val = float(val)
        parts[key] = "%s=%r" % (key, val)
    for name, val in (("I_AUX_A", sim.I_AUX_A),
                      ("SOC_LOAD_RAMP_S", sim.SOC_LOAD_RAMP_S),
                      ("SOC_BAND_DRAIN_LOAD_A", sim.SOC_BAND_DRAIN_LOAD_A),
                      ("SOC_BAND_DRAIN_START_S", sim.SOC_BAND_DRAIN_START_S),
                      ("SOC_BAND_DRAIN_END_S", sim.SOC_BAND_DRAIN_END_S)):
        parts[name] = "%s=%r" % (name, float(val))
    return parts


def fingerprint_from_parts(parts):
    """The digest fingerprint_parts() describes."""
    return hashlib.sha256("\n".join(parts.values()).encode("utf-8")).hexdigest()


def fingerprint_diff(scenario, meta_a, meta_b):
    """The fingerprint keys on which two metas disagree, as {key: (a, b)}.

    Raises RuntimeError when the reconstruction no longer reproduces
    hil_plant_sim.dp_profile_fingerprint, rather than reporting a diff taken
    over a stale copy of its construction."""
    import hil_plant_sim as sim
    pa, pb = fingerprint_parts(scenario, meta_a), fingerprint_parts(scenario,
                                                                   meta_b)
    for meta, parts in ((meta_a, pa), (meta_b, pb)):
        if fingerprint_from_parts(parts) != sim.dp_profile_fingerprint(
                scenario, meta):
            raise RuntimeError(
                "fingerprint_parts() no longer reproduces "
                "hil_plant_sim.dp_profile_fingerprint() for %r - the "
                "canonical string changed and this diff would be wrong"
                % scenario)
    return {k: (pa.get(k), pb.get(k)) for k in set(pa) | set(pb)
            if pa.get(k) != pb.get(k)}


def model_fields():
    """The eight drift-guard model quantities the DP table header records.

    Eight, not ten: `run_entry_s` and `run_exit_s` complete the header's set,
    and `run_exit_s` is per-scenario, so it is supplied by the caller rather
    than read off a module here.

    Imported from the live modules, never restated, so a retune of any of them
    moves every key and makes the pre-retune records unreachable — which is
    the intended behaviour: a baseline solved against a different plant is not
    a baseline for this one."""
    import hil_plant_sim as sim
    import gen_dp_ems_table as gen
    return {
        "gfc_dc_gain": float(sim.H2_GFC_DC_GAIN_GPS_PER_W),
        "eta_boost": float(sim.ETA_BOOST),
        "limit_i_fc_max_a": float(gen.LIMIT_I_FC_MAX_A),
        "charge_share_value": float(gen.DP_CHARGE_SHARE),
        "share_span": float(sim.SOC_BAND_SHARE_SPAN),
        "cruise_slope_max": float(sim.SOC_BAND_CRUISE_SLOPE_MAX),
        "cruise_min_mps": float(sim.SOC_BAND_CRUISE_MIN_MPS),
        "run_entry_s": float(sim.EMS_RUN_ENTRY_S),
    }


def problem_fields(scenario, *, profile_fingerprint, soc0, capacity_ah,
                   charger_accounting, stage_dt, n_share, soc_step, chg_a,
                   lambda_dev, aux_preload_a, run_exit_s, target_soc,
                   era_overrides=None, eta_chg=None, loss_map=None,
                   drag=None, eta_regen=None):
    """A complete key-field dict.

    `aux_preload_a=None` means "whatever the scenario declares", which is what
    gen_dp_ems_table.scenario_drain_a() does with it, so it is RESOLVED HERE
    against the live registry rather than recorded as a number the solve will
    not use.  Recording 0.0 for None was a defect: a scenario declaring 0.85 A
    keyed as 0.0 whenever the caller left the argument out, so two genuinely
    different demands collided on one key (MED-4, 2026-09-01).

    The raw `target_soc` is emitted alongside the quantized `target_soc_q`.
    It is NOT in KEY_FIELDS and does not enter the key; `lookup()` uses it so
    the tolerance test is made against the caller's own target rather than
    against a rounded one.

    `eta_chg=None` is the CHARGER ERA of every record solved before
    2026-09-01 (a 1:1 current-transfer charger), and it is the default for the
    same stimulus-era reason `aux_preload_a` has one: an archived run must be
    keyed by the accounting it actually ran under.  It is an OPTIONAL key
    field, so None keys exactly as the pre-change code did.

    `loss_map=None` is the DEMAND-MODEL ERA of every record solved before
    2026-09-02 (motor draw plus drain, on V_BUS_DROOP_V0 -
    K_DROOP_BUS_SHARED*I), and it is optional on the same terms."""
    import hil_plant_sim as sim
    if aux_preload_a is None:
        aux_preload_a = ((sim.SCENARIOS.get(scenario) or {})
                         .get("aux_preload_a") or 0.0)
    fields = dict(model_fields())
    fields.update({
        "scenario": str(scenario),
        "profile_fingerprint": str(profile_fingerprint),
        "soc0": float(soc0),
        "capacity_ah": float(capacity_ah),
        "charger_accounting": str(charger_accounting),
        "stage_dt": float(stage_dt),
        "n_share": float(n_share),
        "soc_step": float(soc_step),
        "chg_a": float(chg_a),
        "lambda_dev": float(lambda_dev),
        "aux_preload_a": float(aux_preload_a),
        "eta_chg": (None if eta_chg is None else float(eta_chg)),
        "loss_map": (None if loss_map is None
                     else sim.loss_map_canonical(sim.check_loss_map(loss_map))),
        # THE ROAD-LOAD AND REGEN ERAS (2026-09-02).  `drag` is normalised
        # through `plant_drag_mode()` so the rig profile keys as an OMISSION
        # whether the caller passed None or the literal "rig".
        "drag": sim.plant_drag_mode(drag),
        "eta_regen": (None if eta_regen is None else float(eta_regen)),
        "run_exit_s": float(run_exit_s),
        # Not a key field: the map DICT, carried so `solve_and_store()` can
        # rebuild the problem without re-parsing the canonical string.
        "loss_map_dict": (None if loss_map is None
                          else dict(sim.check_loss_map(loss_map))),
        "target_soc_q": quantize_target(target_soc),
        # Not a key field (see KEY_FIELDS); carried for lookup()'s raw compare.
        "target_soc": float(target_soc),
        # Not a key field either: the era overrides are already ENCODED in
        # profile_fingerprint / chg_a / aux_preload_a above.  They are carried
        # so a later solve can REBUILD the run-era scenario meta and reach the
        # same fingerprint, which a `prefill --key-fields` cannot otherwise do.
        "era_overrides": dict(era_overrides or {}),
    })
    return fields


def fields_from_problem(problem, target_soc):
    """Key fields for a gen_dp_ems_table.Problem."""
    return problem_fields(
        problem.scenario, profile_fingerprint=problem.fingerprint,
        soc0=problem.soc0, capacity_ah=problem.capacity_ah,
        charger_accounting=problem.charger_accounting,
        stage_dt=problem.stage_dt, n_share=problem.n_share,
        soc_step=problem.soc_step, chg_a=problem.chg_a,
        lambda_dev=problem.lambda_dev, aux_preload_a=problem.aux_preload_a,
        eta_chg=getattr(problem, "eta_chg", None),
        loss_map=getattr(problem, "loss_map", None),
        drag=getattr(problem, "drag_mode", None),
        eta_regen=getattr(problem, "eta_regen", None),
        run_exit_s=problem.run_exit, target_soc=target_soc)


# ─────────────────────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────────────────────
def _write_json_atomic(path, payload):
    """Write LF-normalized JSON through a temp file and os.replace.

    LF is explicit (newline="\\n"): this repository runs core.autocrlf=true,
    and tools/dp_db/.gitattributes marks the store `-text` so a checked-out
    record is byte-identical to the one that was written."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # UNIQUE per writer: two prefills, or a prefill and an analysis pass in
    # --matched-dp solve, would otherwise share one "<path>.tmp" and one would
    # replace the other's half-written file.
    tmp = "%s.%d.%s.tmp" % (path, os.getpid(), uuid.uuid4().hex[:8])
    # A dump that raises part-way (a non-serializable value, a full disk)
    # cannot corrupt `path`, because os.replace is never reached. It does
    # leave the partial temp file behind, and a prefill that fails
    # repeatedly would litter the store with them. Remove it and re-raise:
    # the caller still sees the real error, and the store keeps only the
    # files it owns.
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
            fh.write("\n")
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def iter_records(db_dir=DP_DB_DIR, log=None):
    """Every readable record, from the solve files themselves.

    An unreadable or malformed file is SKIPPED and, when `log` is given,
    NAMED.  Dropping it silently would shrink the index without saying which
    record left it."""
    solves = os.path.join(db_dir, "solves")
    if not os.path.isdir(solves):
        return
    for name in sorted(os.listdir(solves)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(solves, name)
        rec = _read_json(path)
        if rec is None:
            if log:
                log("[dp_db] SKIPPING unreadable record %s" % path)
            continue
        yield rec


def rebuild_index(db_dir=DP_DB_DIR, log=None):
    """Regenerate index.json from the solve files.  Returns the index dict."""
    entries = []
    for rec in iter_records(db_dir, log=log):
        entries.append({
            "key": rec.get("key"),
            "scenario": (rec.get("key_fields") or {}).get("scenario"),
            "non_target_hash": rec.get("non_target_hash"),
            "target_soc": rec.get("target_soc"),
            "target_soc_q": (rec.get("key_fields") or {}).get("target_soc_q"),
            "h2_dp_g": rec.get("h2_g"),
            "converged": rec.get("converged"),
            "created_utc": rec.get("created_utc"),
        })
    entries.sort(key=lambda e: (e.get("scenario") or "",
                               e.get("target_soc") or 0.0))
    index = {"format_version": 1,
             "note": "CACHE, rebuilt from solves/*.json - never the authority",
             "records": entries}
    _write_json_atomic(os.path.join(db_dir, "index.json"), index)
    return index


def load_index(db_dir=DP_DB_DIR):
    """index.json, rebuilt on the spot when it is missing or unreadable."""
    index = _read_json(os.path.join(db_dir, "index.json"))
    if not index or "records" not in index:
        return rebuild_index(db_dir)
    return index


def get(key, db_dir=DP_DB_DIR):
    """One record by key, or None."""
    return _read_json(os.path.join(db_dir, "solves", "%s.json" % key))


def live_constants_hash():
    """hil_plant_sim's constants_hash for THIS checkout, or None."""
    import hil_plant_sim as sim
    collect = getattr(sim, "collect_model_constants", None)
    if not callable(collect):
        return None
    try:
        return sim.constants_hash(collect())
    except Exception:                            # pragma: no cover - defensive
        return None


def record_provenance_drift(rec, live_hash=None):
    """True when `rec` was solved under a different simulator constant set.

    Compares ONLY hil_plant_sim's constants_hash.  The generator's source
    sha256 is deliberately NOT compared: a comment or a docstring edit moves
    it without moving a single number, and a drift flag that fires on every
    edit teaches the reader to ignore it.

    The constants_hash is itself a WARNING and not proof — it moves when any
    module-level numeric constant moves, including constants this solve never
    reads.  A drifted record is therefore returned and annotated rather than
    discarded, unless the caller asks for `strict`."""
    stored = ((rec or {}).get("provenance") or {}).get(
        "hil_plant_sim_constants_hash")
    if live_hash is None:
        live_hash = live_constants_hash()
    if stored is None or live_hash is None:
        return False
    return stored != live_hash


# ── THE DRAIN-MEMBERSHIP WITNESS (review Lens-3, 2026-09-03) ────────────────
# `dp_profile_fingerprint()` hashes the SoC-band drain CONSTANTS but not WHICH
# SCENARIOS the drain branch applies to, so a stale mirror of that list produces
# a wrong record under a CORRECT key and no lookup can detect it.  That has now
# happened twice (defect B2 omitted `ems-sdp`; the 2026-09-03 pass omitted the
# three `ems-sdp-alpha-*` legs), each time worth hundreds of percent on the
# solved bound.  The list is now derived from `apply_scenario()`'s own source in
# both offline mirrors, which prevents a THIRD divergence but says nothing about
# records already on disk.
#
# So each new record carries the membership it was solved under, and a read
# compares it against the live one.  It is a WITNESS, not a key: adding it to
# the key would orphan all 71 stored records for a quantity that is identical in
# all of them.  A mismatch WARNS and annotates; it never refuses, because the
# record may still be the one the caller wants and the operator is the judge.
# A record with no `drain_membership` field predates the witness and is accepted
# SILENTLY - there is nothing to compare it against, and a warning on every old
# record teaches the reader to ignore the warning.
def drain_membership(scenario):
    """The resolved SoC-band-drain membership for `scenario`, as stored.

    Both halves matter.  `in_soc_band_drain` is the answer for THIS scenario;
    `names_sha256` witnesses the whole resolved list, so a change that moves a
    DIFFERENT scenario in or out is still visible on a re-read."""
    import hil_plant_sim as sim
    names = tuple(getattr(sim, "SOC_BAND_DRAIN_SCENARIO_NAMES", ()) or ())
    return {
        "in_soc_band_drain": scenario in names,
        "names_sha256": hashlib.sha256(
            json.dumps(sorted(names), separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def record_drain_membership_drift(rec):
    """A human-readable mismatch string for `rec`, or None.

    None means EITHER "agrees" or "the record predates the witness"; the two
    are deliberately not distinguished at this level, because neither is
    actionable."""
    stored = (rec or {}).get("drain_membership")
    if not isinstance(stored, dict):
        return None                       # pre-witness record: silent, by rule
    scenario = ((rec or {}).get("key_fields") or {}).get("scenario")
    if scenario is None:
        return None
    try:
        live = drain_membership(scenario)
    except Exception:                     # pragma: no cover - defensive
        return None
    if stored == live:
        return None
    return ("scenario %r: stored in_soc_band_drain=%r names_sha256=%s, live "
            "in_soc_band_drain=%r names_sha256=%s"
            % (scenario, stored.get("in_soc_band_drain"),
               str(stored.get("names_sha256"))[:12],
               live["in_soc_band_drain"], live["names_sha256"][:12]))


def lookup(fields, tol_soc=DP_DB_LOOKUP_TOL, db_dir=DP_DB_DIR, strict=False):
    """The nearest stored solve for `fields`, or None.

    Exactness first: a record at the caller's own key is returned without
    consulting the tolerance.  Otherwise the index is scanned for records that
    agree on every non-target field, and the one whose stored target is
    nearest — and within `tol_soc` of the caller's RAW target — is returned.
    The raw target is used rather than the quantized one so the tolerance test
    answers the question the caller actually asked (LOW-5).

    The returned dict carries a `provenance_drift` flag (see
    record_provenance_drift).  With `strict=True` a drifted record is treated
    as a MISS, which is the setting for a comparison whose number must not
    silently come from a differently-parameterised plant."""
    live = live_constants_hash()

    def _accept(rec):
        if rec is None:
            return None
        drift = record_provenance_drift(rec, live)
        if drift and strict:
            return None
        rec = dict(rec)
        rec["provenance_drift"] = bool(drift)
        # The drain-membership witness: WARN, annotate, and return the record.
        # It is not gated on `strict` — `strict` is about the constants hash,
        # and a membership mismatch is a different claim with a different fix.
        mismatch = record_drain_membership_drift(rec)
        rec["drain_membership_drift"] = mismatch
        if mismatch:
            warnings.warn(
                "dp_results_db: stored SoC-band drain membership disagrees "
                "with this checkout (%s). The record's bound was solved "
                "under a different auxiliary load, which is worth hundreds "
                "of percent on the solved hydrogen. Re-solve it before "
                "quoting the deviation." % mismatch,
                RuntimeWarning, stacklevel=2)
        return rec

    rec = _accept(get(make_key(fields), db_dir))
    if rec is not None:
        return rec
    want = float(fields.get("target_soc", fields["target_soc_q"]))
    nth = non_target_hash(fields)
    candidates = []
    for entry in load_index(db_dir).get("records", []):
        if entry.get("non_target_hash") != nth:
            continue
        target = entry.get("target_soc")
        if target is None:
            continue
        err = abs(float(target) - want)
        if err > tol_soc:
            continue
        candidates.append((err, entry.get("key")))
    # Nearest first, then the next-nearest: under `strict` the nearest record
    # can be refused for drift while a further, undrifted one is still usable.
    for _, key in sorted(candidates, key=lambda c: c[0]):
        rec = _accept(get(key, db_dir))
        if rec is not None:
            return rec
    return None


def store(record, db_dir=DP_DB_DIR):
    """Write one record and rebuild the index.  Returns the record's path.

    `provenance_drift` and `drain_membership_drift` are LOOKUP-TIME annotations
    and never stored fields; a record round-tripped through lookup() and back
    must not acquire one.  (`drain_membership` itself IS stored — it is the
    witness the annotation is computed from.)"""
    record = {k: v for k, v in record.items()
              if k not in ("provenance_drift", "drain_membership_drift")}
    key = record["key"]
    path = os.path.join(db_dir, "solves", "%s.json" % key)
    _write_json_atomic(path, record)
    rebuild_index(db_dir)
    return path


def _thin(seq):
    """Store a short trajectory whole and a long one every DP_DB_TRAJ_STRIDE."""
    seq = list(seq)
    if len(seq) <= DP_DB_TRAJ_FULL_MAX:
        return seq, 1
    return seq[::DP_DB_TRAJ_STRIDE], DP_DB_TRAJ_STRIDE


def generator_provenance():
    """Provenance of the code that produced a solve.

    sha256 of gen_dp_ems_table.py's SOURCE TEXT plus the simulator's own
    constants_hash: between them they cover the solver's logic and every
    numeric constant it imports, so a record can be told apart from one this
    checkout would produce differently."""
    import hil_plant_sim as sim
    with open(os.path.join(_HERE, "gen_dp_ems_table.py"), "rb") as fh:
        gen_sha = hashlib.sha256(fh.read()).hexdigest()
    consts = getattr(sim, "collect_model_constants", None)
    if callable(consts):
        try:
            chash = sim.constants_hash(consts())
        except Exception:                       # pragma: no cover - defensive
            chash = None
    else:
        chash = None
    return {"gen_dp_ems_table_sha256": gen_sha,
            "hil_plant_sim_constants_hash": chash}


def solve_and_store(fields, target_soc, *, match_tol=2.0e-6, db_dir=DP_DB_DIR,
                    log=print):
    """Solve the problem `fields` describes at `target_soc` and store it.

    NUMPY PATH: imports gen_dp_ems_table (and through it hil_plant_sim), so it
    must run under an interpreter that has numpy."""
    import gen_dp_ems_table as gen
    import hil_plant_sim as sim

    scenario = fields["scenario"]
    live_meta = sim.SCENARIOS.get(scenario)
    if live_meta is None:
        raise ValueError("unknown scenario %r" % scenario)
    era_overrides = fields.get("era_overrides") or {}
    meta = apply_era_overrides(live_meta, era_overrides)
    # ── THE ERA MUST REACH THE FINGERPRINT HERE TOO (2026-09-02) ────────────
    # `prepare_problem()` fingerprints the META it is given, and a LIVE
    # scenario meta declares no `eta_chg` (dp_eta_chg() resolves the absent key
    # to the module's own constant only for the RUN, not for the dict).  The
    # prefill path already resolves the era into the meta it fingerprints
    # (_cmd_prefill's M4(b)), so `prefill --scenario X --eta-chg 0.88` produced
    # a key whose fingerprint carried the era and then came in HERE, where the
    # meta did not — and every such solve died on "profile fingerprint drift"
    # before it started.  `era_overrides` is still the caller's explicit
    # channel and WINS: it is set only if the key fields named it.
    _eta = fields.get("eta_chg")
    if _eta is not None and "eta_chg" not in era_overrides:
        meta["eta_chg"] = float(_eta)
    # The same argument for the demand-model era (2026-09-02).  `store()`
    # persists only KEY_FIELDS, so a record read back off disk carries the
    # CANONICAL STRING and not the dict the caller built; parsing the string
    # back is what lets a prefill fed a stored record reconstruct the same
    # problem instead of refusing it for fingerprint drift.
    # THE ROAD-LOAD AND REGEN ERAS of the stored record, replayed into the
    # meta the re-solve fingerprints against, exactly as `eta_chg` is.
    _drag = fields.get("drag")
    if _drag is not None and "drag" not in era_overrides:
        meta["drag"] = str(_drag)
    _er = fields.get("eta_regen")
    if _er is not None and "eta_regen" not in era_overrides:
        meta["eta_regen"] = float(_er)
    _lm = fields.get("loss_map_dict")
    if _lm is None:
        _lm = sim.loss_map_from_canonical(fields.get("loss_map"))
    if _lm is not None and "loss_map" not in era_overrides:
        meta["loss_map"] = sim.check_loss_map(_lm)
    aux = fields.get("aux_preload_a")
    problem = gen.prepare_problem(
        scenario, meta, soc0=fields["soc0"],
        capacity_ah=fields["capacity_ah"], stage_dt=fields["stage_dt"],
        n_share=int(fields["n_share"]), soc_step=fields["soc_step"],
        run_exit=fields["run_exit_s"],
        charger_accounting=fields["charger_accounting"],
        lambda_dev=fields["lambda_dev"],
        aux_preload_a=(None if aux is None else float(aux)),
        eta_chg=fields.get("eta_chg"),
        loss_map=_lm,
        drag_mode=(None if _drag is None else str(_drag)),
        eta_regen=(None if _er is None else float(_er)))
    if problem.fingerprint != fields["profile_fingerprint"]:
        # The era overrides could not put the run's stimulus back.  Name what
        # they DID reconcile and what they could not, so the reader sees which
        # key is unreproducible rather than only that a digest moved.
        try:
            drift = fingerprint_diff(scenario, live_meta, meta)
        except RuntimeError as exc:
            drift = {"<reconstruction>": (str(exc), None)}
        # Split the suspects: a META key can be reconciled by adding it
        # to era_overrides, a module CONSTANT cannot -- it is a retune of
        # the plant, and no override dict can put it back.
        meta_keys = set(sim.DP_FINGERPRINT_META_KEYS)
        parts = fingerprint_parts(scenario, meta)
        unreconciled = sorted(k for k in parts
                              if k in meta_keys and k not in era_overrides)
        constants = sorted(k for k in parts
                           if k not in meta_keys and k != "scenario")
        raise ValueError(
            "profile fingerprint drift for %r: the key asks for %s, the "
            "run-era metadata reconstructs to %s.\n"
            "  era overrides applied: %s\n"
            "  keys they moved:       %s\n"
            "  meta keys NOT overridden (add one of these to "
            "`era_overrides`): %s\n"
            "  plant constants in the fingerprint (NOT overridable - a "
            "retune of one of these makes the era unreproducible): %s\n"
            "Either add the missing meta key to the key fields' "
            "`era_overrides` object, or accept that this run's stimulus "
            "no longer exists in this checkout."
            % (scenario, fields["profile_fingerprint"], problem.fingerprint,
               ", ".join(sorted(era_overrides)) or "none",
               ", ".join(sorted(drift)) or "none",
               ", ".join(unreconciled) or "none",
               ", ".join(constants) or "none"))

    solved = gen.solve_matched(problem, target_soc=float(target_soc),
                               match_tol=match_tol)
    share, stride = _thin(solved.share)
    charge, _ = _thin(solved.charge)
    record = {
        "format_version": 1,
        "key": make_key(fields),
        "non_target_hash": non_target_hash(fields),
        "key_fields": {k: fields.get(k) for k in KEY_FIELDS},
        # The drain-membership WITNESS, not a key field.  See
        # `drain_membership()`: it is compared at read time and warns.
        "drain_membership": drain_membership(scenario),
        "created_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "target_soc": float(target_soc),
        "match_tol": float(match_tol),
        "residual_soc": solved.residual_soc,
        "converged": bool(solved.converged),
        "lambda_term": solved.lambda_term,
        "n_solves": solved.n_solves,
        "j0": solved.j0,
        "h2_g": solved.h2_g,                    # `physical` accounting
        "h2_plant_g": solved.h2_plant_g,        # `simple`-mode equivalent
        "soc_final": solved.soc_final,
        "delta_soc": solved.delta_soc,
        "wall_s": solved.wall_s,
        "traj_stride": stride,
        "share": share,
        "charge": charge,
        "provenance": generator_provenance(),
    }
    path = store(record, db_dir)
    if log:
        log("[dp_db] stored %s (target %.6f, residual %+.2e, h2 %.9g g, "
            "%.1f s over %d solves)"
            % (os.path.relpath(path, REPO_ROOT), float(target_soc),
               solved.residual_soc, solved.h2_g, solved.wall_s,
               solved.n_solves))
    return record


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def _cmd_list(args):
    index = load_index(args.db_dir)
    rows = [e for e in index.get("records", [])
            if not args.scenario or e.get("scenario") == args.scenario]
    if not rows:
        print("[dp_db] no records")
        return 0
    print("%-28s %-10s %-12s %-6s %s"
          % ("scenario", "target", "h2_g", "conv", "key"))
    for e in rows:
        print("%-28s %-10.6f %-12.9g %-6s %s"
              % (e.get("scenario") or "-", float(e.get("target_soc") or 0.0),
                 float(e.get("h2_dp_g") or 0.0),
                 "yes" if e.get("converged") else "no",
                 (e.get("key") or "")[:16]))
    print("[dp_db] %d record(s) in %s" % (len(rows), args.db_dir))
    return 0


def _cmd_show(args):
    rec = get(args.key, args.db_dir)
    if rec is None:
        # A truncated key from `list` is the common case; resolve it.
        for e in load_index(args.db_dir).get("records", []):
            if (e.get("key") or "").startswith(args.key):
                rec = get(e["key"], args.db_dir)
                break
    if rec is None:
        print("[dp_db] no record for key %r" % args.key, file=sys.stderr)
        return 2
    slim = {k: v for k, v in rec.items() if k not in ("share", "charge")}
    slim["share_points"] = len(rec.get("share") or [])
    print(json.dumps(slim, indent=1, sort_keys=True))
    return 0


def rekey_store(db_dir=DP_DB_DIR, dry_run=False, log=print):
    """Re-file every record whose key no longer matches its own key fields.

    A record's key is a function of its key fields, and one of them —
    `target_soc_q` — is a QUANTIZED value.  Tightening DP_DB_TARGET_QUANTUM
    therefore leaves the existing records filed under keys the current code
    would never compute, so their exact-key hit stops firing (they remain
    reachable through the index's tolerance scan, which is why this is a
    tidying operation and not a repair).

    Re-filing is arithmetic on the STORED target, never a re-solve: the solve
    answered a target, and re-quantizing that target cannot change the answer.
    Returns the list of (old_key, new_key) pairs."""
    moved = []
    for rec in list(iter_records(db_dir, log=log)):
        fields = dict(rec.get("key_fields") or {})
        target = rec.get("target_soc")
        if not fields or target is None:
            continue
        fields["target_soc_q"] = quantize_target(target)
        fields.setdefault("target_soc", float(target))
        try:
            new_key = make_key(fields)
        except KeyError as exc:
            log("[dp_db] SKIPPING %s: %s" % (rec.get("key"), exc))
            continue
        old_key = rec.get("key")
        if new_key == old_key:
            continue
        moved.append((old_key, new_key))
        if dry_run:
            continue
        rec = dict(rec)
        rec["key"] = new_key
        rec["key_fields"] = {k: fields.get(k) for k in KEY_FIELDS}
        rec["non_target_hash"] = non_target_hash(fields)
        rec.setdefault("rekeyed_from", []).append(old_key)
        store(rec, db_dir)
        old_path = os.path.join(db_dir, "solves", "%s.json" % old_key)
        if os.path.exists(old_path):
            os.remove(old_path)
    if not dry_run:
        rebuild_index(db_dir, log=log)
    return moved


def _cmd_rekey(args):
    moved = rekey_store(args.db_dir, dry_run=args.dry_run)
    for old, new in moved:
        print("[dp_db] %s %s -> %s"
              % ("WOULD REKEY" if args.dry_run else "rekeyed",
                 (old or "")[:16], new[:16]))
    print("[dp_db] %d record(s) %s"
          % (len(moved), "would be re-keyed" if args.dry_run else "re-keyed"))
    return 0


def _cmd_rebuild(args):
    index = rebuild_index(args.db_dir, log=print)
    print("[dp_db] index rebuilt: %d record(s)" % len(index["records"]))
    return 0


def _parse_span(text):
    """START:STOP:N -> N evenly spaced values, inclusive of both ends."""
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError("--dsoc-span must be START:STOP:N, got %r" % text)
    lo, hi = float(parts[0]), float(parts[1])
    n = int(parts[2])
    if n < 1:
        raise ValueError("--dsoc-span N must be >= 1")
    if n == 1:
        return [lo]
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def load_key_fields(text):
    """A key-field dict from a JSON literal or from "@path".

    This is the exact-reproduction path: an analysis run that misses emits the
    key fields it needs, and a prefill fed those bytes solves THAT problem
    rather than one reconstructed from a handful of command-line flags that
    may not cover every input (MED-5).

    The object's `era_overrides` sub-object is part of that payload: it is not
    a key field, but it is what lets the solve rebuild the run-era scenario
    metadata and reach the recorded fingerprint. An object without one is
    accepted, and reconstructs against the live metadata."""
    if text.startswith("@"):
        with open(text[1:], "r", encoding="utf-8") as fh:
            fields = json.load(fh)
    else:
        fields = json.loads(text)
    if not isinstance(fields, dict):
        raise ValueError("--key-fields must decode to a JSON object")
    missing = [name for name in KEY_FIELDS
               if name not in fields and name not in OPTIONAL_KEY_FIELDS]
    if missing:
        raise ValueError("--key-fields is missing %s" % ", ".join(missing))
    if not isinstance(fields.get("era_overrides", {}), dict):
        raise ValueError("--key-fields `era_overrides` must be a JSON object")
    return fields


def _cmd_prefill(args):
    import hil_plant_sim as sim

    # M4(a): the two era flags contradict each other.  `--eta-chg-none` wins
    # silently in `problem_fields()` below, so a caller who passed both would
    # get an OLD-era solve while believing they had asked for an eta-era one.
    if args.eta_chg_none and args.eta_chg is not None:
        print("[dp_db] --eta-chg and --eta-chg-none are mutually exclusive: "
              "--eta-chg-none forces the 1:1 current-transfer era, so an "
              "efficiency alongside it has no meaning", file=sys.stderr)
        return 2

    # EXACT-REPRODUCTION BRANCH: solve exactly the problem the analysis tool
    # reported as uncached, with no reconstruction.
    if args.key_fields:
        try:
            fields = load_key_fields(args.key_fields)
        except (OSError, ValueError) as exc:
            print("[dp_db] %s" % exc, file=sys.stderr)
            return 2
        target = float(fields.get("target_soc", fields["target_soc_q"]))
        if lookup(fields, tol_soc=args.tol, db_dir=args.db_dir) is not None:
            print("[dp_db] target %.6f: already cached" % target)
            return 0
        if args.dry_run:
            print("[dp_db] target %.6f: WOULD SOLVE (key %s)"
                  % (target, make_key(fields)[:16]))
            return 0
        solve_and_store(fields, target, match_tol=args.match_tol,
                        db_dir=args.db_dir)
        return 0

    if not args.scenario or not args.dsoc_span:
        print("[dp_db] prefill needs either --key-fields, or --scenario "
              "together with --dsoc-span", file=sys.stderr)
        return 2
    meta = sim.SCENARIOS.get(args.scenario)
    if meta is None:
        print("[dp_db] unknown scenario %r" % args.scenario, file=sys.stderr)
        return 2
    import gen_dp_ems_table as gen

    run_exit = (args.run_exit if args.run_exit is not None
                else (float(sim.SOC_BAND_RUN_EXIT_S)
                      if meta.get("ems_run_exit_s") is None
                      else float(meta["ems_run_exit_s"])))
    aux = (meta.get("aux_preload_a") if args.aux_preload is None
           else args.aux_preload)
    chg_a = (sim.dp_chg_ceiling_a(meta) if args.chg_a is None
             else args.chg_a)
    targets = [args.soc0 + d for d in _parse_span(args.dsoc_span)]

    # M4(b): the era must reach the FINGERPRINT too, not only the key field.
    # A live scenario declares no `eta_chg`, so fingerprinting `meta` as-is
    # always yields the OLD-era digest; a post-2026-09-01 run carries
    # `eta_chg` on its own sidecar meta and therefore fingerprints
    # differently. Keying an explicit era while fingerprinting the live meta
    # produced a record no post-era lookup could ever hit. Resolving the era
    # INTO the fingerprint meta closes that: an old-era prefill is unchanged
    # (dp_profile_fingerprint omits the term when it resolves to None).
    eta_resolved = None if args.eta_chg_none else args.eta_chg
    lm_resolved = gen.resolve_loss_map_arg(getattr(args, "loss_map", "none"))
    # THE ROAD-LOAD AND REGEN ERAS (2026-09-02), on the identical M4(b)
    # argument: both have to reach the FINGERPRINT or the record is
    # unreachable.  `drag` is the one era key a SCENARIO declares, so it
    # defaults to the scenario's own value rather than to the pre-round
    # sentinel; `eta_regen` then follows the drag profile on the generator's
    # rule.  Either can be forced from the command line.
    drag_resolved = getattr(args, "drag", None)
    if drag_resolved is None:
        drag_resolved = meta.get("drag") or sim.DRAG_MODE_RIG
    er_resolved = getattr(args, "eta_regen", None)
    if er_resolved is None and drag_resolved != sim.DRAG_MODE_RIG:
        er_resolved = float(sim.ETA_REGEN)
    fp_meta = dict(meta)
    fp_meta["drag"] = drag_resolved
    if er_resolved is not None:
        fp_meta["eta_regen"] = float(er_resolved)
    if eta_resolved is not None:
        fp_meta["eta_chg"] = float(eta_resolved)
    # The same M4(b) argument for the demand-model era: the map has to reach
    # the FINGERPRINT, not only the key field, or the record is unreachable.
    if lm_resolved is not None:
        fp_meta["loss_map"] = lm_resolved
    fingerprint = sim.dp_profile_fingerprint(args.scenario, fp_meta)

    print("[dp_db] scenario %s, soc0 %.4f, accounting %s, %d target(s)"
          % (args.scenario, args.soc0, args.accounting, len(targets)))
    print("[dp_db] road load %s, regen era %s"
          % (drag_resolved,
             "none" if er_resolved is None else repr(float(er_resolved))))
    solved_n = skipped_n = 0
    for target in targets:
        fields = problem_fields(
            args.scenario,
            profile_fingerprint=fingerprint,
            soc0=args.soc0, capacity_ah=args.capacity_ah,
            charger_accounting=args.accounting, stage_dt=args.stage_dt,
            n_share=args.n_share, soc_step=args.soc_step,
            chg_a=chg_a,
            lambda_dev=gen.DP_LAMBDA_DEV_G_PER_SOC_S,
            aux_preload_a=aux, run_exit_s=run_exit, target_soc=target,
            eta_chg=(None if args.eta_chg_none else args.eta_chg),
            loss_map=lm_resolved,
            drag=drag_resolved, eta_regen=er_resolved)
        hit = lookup(fields, tol_soc=args.tol, db_dir=args.db_dir)
        if hit is not None:
            skipped_n += 1
            print("[dp_db] target %.6f: cached (stored target %.6f, h2 %.9g g)"
                  % (target, hit["target_soc"], hit["h2_g"]))
            continue
        if args.dry_run:
            print("[dp_db] target %.6f: WOULD SOLVE (key %s)"
                  % (target, make_key(fields)[:16]))
            continue
        t0 = time.time()
        solve_and_store(fields, target, match_tol=args.match_tol,
                        db_dir=args.db_dir)
        solved_n += 1
        print("[dp_db] target %.6f: solved in %.1f s" % (target,
                                                         time.time() - t0))
    print("[dp_db] %d solved, %d already cached" % (solved_n, skipped_n))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Reusable store of delta-SoC-matched DP hydrogen "
                    "baselines (WORK_QUEUE section 1).")
    ap.add_argument("--db-dir", default=DP_DB_DIR,
                    help="store directory (default tools/dp_db)")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="list stored solves")
    p.add_argument("--scenario", default=None)
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("show", help="print one record (key or prefix)")
    p.add_argument("key")
    p.set_defaults(func=_cmd_show)

    p = sub.add_parser("rebuild-index", help="regenerate index.json")
    p.set_defaults(func=_cmd_rebuild)

    p = sub.add_parser("rekey",
                       help="re-file records whose key predates a change to "
                            "DP_DB_TARGET_QUANTUM (no re-solve)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_rekey)

    p = sub.add_parser("prefill", help="solve a span of terminal-SoC targets")
    p.add_argument("--scenario", default=None)
    p.add_argument("--soc0", type=float, default=0.7)
    p.add_argument("--accounting", default="physical",
                   choices=["simple", "physical"])
    p.add_argument("--dsoc-span", default=None, metavar="START:STOP:N",
                   help="delta-SoC span, e.g. -0.0030:-0.0010:5; targets are "
                        "soc0 + each value")
    p.add_argument("--key-fields", default=None, metavar="JSON",
                   help="a complete key-field object, or @<path> to a file "
                        "holding one, as emitted by a `no_cached_solve` "
                        "analysis block. Solves exactly that problem and "
                        "ignores --scenario / --dsoc-span")
    p.add_argument("--aux-preload", type=float, default=None,
                   help="auxiliary preload in A (default: the scenario's own)")
    p.add_argument("--chg-a", type=float, default=None,
                   help="Ag105 charge ceiling in A (default: the scenario's)")
    p.add_argument("--eta-chg", type=float, default=None,
                   help="Ag105 charge efficiency, i.e. the CHARGER ERA. "
                        "Omitted = the 1:1 current-transfer era every "
                        "pre-2026-09-01 record was solved in; a value keys "
                        "and solves the energy-conserving converter instead. "
                        "A run's own value comes off its sidecar meta "
                        "(charger_power.resolve_eta_chg)")
    p.add_argument("--eta-chg-none", action="store_true",
                   help="force the 1:1 current-transfer era even when a "
                        "scenario or default would supply an efficiency")
    p.add_argument("--loss-map", choices=("none", "plant"), default="none",
                   help="DEMAND-MODEL ERA. 'none' (the default) is the "
                        "loss-map-free model every record solved before "
                        "2026-09-02 used; 'plant' carries the plant's static "
                        "losses and the realized `--droop design` bus law.")
    p.add_argument("--drag", default=None,
                   help="ROAD-LOAD PROFILE (2026-09-02). Omitted = the "
                        "SCENARIO's own `drag` key, or 'rig' - the measured "
                        "bench road load every record solved before this date "
                        "used. Unlike the other three era flags this one "
                        "defaults to the registry rather than to the "
                        "sentinel, because it is the only era key a scenario "
                        "declares.")
    p.add_argument("--eta-regen", type=float, default=None,
                   help="REGEN DEMAND ERA (2026-09-02). Omitted = derived "
                        "from --drag: the pre-regen era (no braking credit) "
                        "on the rig profile, and the plant's ETA_REGEN on a "
                        "compensated one.")
    p.add_argument("--run-exit", type=float, default=None,
                   help="strategy run-exit time in s (default: the "
                        "scenario's ems_run_exit_s, else SOC_BAND_RUN_EXIT_S)")
    p.add_argument("--capacity-ah", type=float, default=5.0)
    p.add_argument("--stage-dt", type=float, default=0.1)
    p.add_argument("--soc-step", type=float, default=5.0e-6)
    p.add_argument("--n-share", type=int, default=41)
    p.add_argument("--match-tol", type=float, default=2.0e-6)
    p.add_argument("--tol", type=float, default=DP_DB_LOOKUP_TOL,
                   help="skip a target already cached within this SoC "
                        "tolerance (default %g). A span whose step is not "
                        "larger than this solves its first target and reports "
                        "the rest as cached." % DP_DB_LOOKUP_TOL)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=_cmd_prefill)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

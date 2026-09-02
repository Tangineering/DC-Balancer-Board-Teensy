#!/usr/bin/env python3
"""pytest suite for tools/sdp_ems_solver.py -- the offline stochastic-DP EMS
policy solver.

INTERPRETER: sdp_ems_solver.py imports numpy and scipy at module scope (it is
offline tooling, not part of the 1 kHz simulator loop), so this file can only
run under an interpreter that has both -- the repo's `.venv_hil` is
deliberately stdlib-only and does NOT.  Following tools/test_gen_dp_ems_table.py's
precedent, this module SKIPS CLEANLY (does not error/collect at all) when
numpy is unavailable, via `pytest.importorskip("numpy")` at import time.

Run:
    C:/Users/ricky/miniforge3/python.exe -m pytest tools/test_sdp_ems_solver.py -v

Reduced-grid solves in this file use DELIBERATELY COARSE parameters
(--soc-n 11, --share-n 5) so a solve finishes in well under a second on this
rig's small TPM -- these are NOT the parameters the shipped artifact was
generated with (see tools/sdp_policies/sdp_policy_v1.json's own `solver` and
`soc`/`actions` blocks for that).  A single check runs the FULL default grid
against the SHIPPED artifact (item 1); everything else uses the reduced grid
to keep the suite fast, per a session-scoped fixture that solves it ONCE.
"""
import json
import os
import sys

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sdp_ems_solver as solver         # noqa: E402
import tpm_generator                    # noqa: E402

SHIPPED_POLICY_PATH = os.path.join(HERE, "sdp_policies", "sdp_policy_v1.json")

# `--eta-chg-none` (2026-09-01, WP-1B1): every NUMBER this suite pins - the
# shipped alpha 0.1629624, both admission windows, the 294-cell knife edge -
# belongs to the OLD 1:1 current-transfer charger, which is what v1/v2/v3 were
# solved against.  The solver's DEFAULT era is now the plant's converter
# (D13), so the legacy expectations are pinned to their era explicitly rather
# than being silently re-based onto a different charger.  The eta-era
# behaviour has its own tests at the end of this file.
_REDUCED_ARGV = ["--soc-n", "11", "--share-n", "5", "--eta-chg-none"]


# ─────────────────────────────────────────────────────────────────────────
# fixtures: solve the reduced grid ONCE per session; read the shipped
# artifact ONCE per session (it is checked-in, read-only).
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def shipped_policy():
    assert os.path.isfile(SHIPPED_POLICY_PATH), (
        "the shipped artifact %r is missing -- regenerate with "
        "tools/sdp_ems_solver.py before running this suite" % SHIPPED_POLICY_PATH)
    with open(SHIPPED_POLICY_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def reduced_policy(tmp_path_factory):
    out = tmp_path_factory.mktemp("sdp_reduced") / "reduced.json"
    rc = solver.main(_REDUCED_ARGV + ["--out", str(out)])
    assert rc == 0
    with open(out, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ─────────────────────────────────────────────────────────────────────────
# 1. Shipped-artifact schema pin (full default grid, against the SHIPPED file)
# ─────────────────────────────────────────────────────────────────────────

def test_shipped_artifact_schema_and_shapes(shipped_policy):
    doc = shipped_policy
    assert doc["schema"] == solver.SCHEMA == "sdp-policy-v1"
    for key in ("generated_utc", "tool", "argv", "causal", "sim_only", "tpm",
               "normalization", "demand_bins", "decision_dt_s", "gamma",
               "alpha", "soc", "actions", "battery", "h2", "solver", "policy"):
        assert key in doc, key
    assert doc["causal"] is True
    assert doc["sim_only"] is True

    soc = doc["soc"]
    share = doc["policy"]["share"]
    goal = doc["policy"]["charge_goal"]
    n_soc = soc["n"]
    n_bins = doc["demand_bins"]["n"]
    assert len(share) == n_soc
    assert len(goal) == n_soc
    for row in share:
        assert len(row) == n_bins
    for row in goal:
        assert len(row) == n_bins

    ladder = set(doc["actions"]["share_ladder"])
    for row in share:
        for v in row:
            assert v in ladder, v
    for row in goal:
        for v in row:
            assert v in (0.0, 1.0), v

    assert doc["solver"]["converged"] is True


def test_shipped_artifact_solver_converged_within_its_own_tolerance(shipped_policy):
    s = shipped_policy["solver"]
    assert s["final_delta"] < s["tolerance"]
    assert s["iterations"] > 0
    assert s["iterations"] <= s["max_iterations"]


# ─────────────────────────────────────────────────────────────────────────
# 2. Non-degeneracy of the shipped policy
# ─────────────────────────────────────────────────────────────────────────

def test_shipped_artifact_non_degenerate_across_bins_and_across_soc(shipped_policy):
    doc = shipped_policy
    share = np.array(doc["policy"]["share"])
    soc_grid = np.array(doc["soc"]["grid"]) if doc["soc"].get("grid") else \
        np.linspace(doc["soc"]["grid_min"], doc["soc"]["grid_max"], doc["soc"]["n"])
    i_tgt = int(np.abs(soc_grid - doc["soc"]["target"]).argmin())

    row_at_target = share[i_tgt]
    assert row_at_target.max() > row_at_target.min(), (
        "share does not vary across demand bins at the SoC-target row")

    col_at_bin10 = share[:, 10]
    assert col_at_bin10.max() > col_at_bin10.min(), (
        "share does not vary across SoC rows at demand bin 10")


# ─────────────────────────────────────────────────────────────────────────
# 3. charge_forbidden_bins honored (shipped artifact)
# ─────────────────────────────────────────────────────────────────────────

def test_shipped_artifact_charge_goal_zero_in_every_forbidden_bin(shipped_policy):
    doc = shipped_policy
    forbidden = doc["actions"]["charge_forbidden_bins"]
    assert forbidden, "sanity: the shipped artifact must actually forbid something"
    goal = np.array(doc["policy"]["charge_goal"])
    for j in forbidden:
        col = goal[:, j]
        assert (col == 0.0).all(), (
            "charge_goal asserted in forbidden bin %d (rows %s)"
            % (j, np.nonzero(col)[0].tolist()))


def test_shipped_artifact_charge_goal_can_be_nonzero_outside_forbidden_bins(shipped_policy):
    """Vacuity guard for the check above: confirm the artifact actually DOES
    assert charge_goal somewhere (i.e. the all-zero forbidden-bin check is
    not trivially true because charge is never asserted anywhere at all)."""
    doc = shipped_policy
    forbidden = set(doc["actions"]["charge_forbidden_bins"])
    goal = np.array(doc["policy"]["charge_goal"])
    n_bins = goal.shape[1]
    allowed_cols = [j for j in range(n_bins) if j not in forbidden]
    assert allowed_cols
    allowed_block = goal[:, allowed_cols]
    assert (allowed_block > 0.0).any(), (
        "charge_goal is never asserted anywhere outside the forbidden bins -- "
        "the forbidden-bin check above would pass even if charging were "
        "globally broken")


# ─────────────────────────────────────────────────────────────────────────
# Round 2 (review-fix round, 2026-08-31): reviewer LOW-3 provenance pins and
# the D3/D8 floor-node clamp-tie exception.
# ─────────────────────────────────────────────────────────────────────────

def test_shipped_artifact_tpm_sha256_matches_recomputed_hash_of_the_live_mat_file():
    """LOW-3(a): the artifact's recorded tpm.sha256 must equal a FRESH sha256
    of the actual TPM .mat file on disk right now -- not merely a value that
    was true at generation time. solver.sha256_file() is the SAME function
    the solver used to bake it, reused here rather than reimplemented."""
    doc_path = SHIPPED_POLICY_PATH
    with open(doc_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    tpm_rel = doc["tpm"]["path"]
    tpm_abs = os.path.join(solver.REPO_ROOT, tpm_rel.replace("/", os.sep))
    assert os.path.isfile(tpm_abs), tpm_abs
    assert solver.sha256_file(tpm_abs) == doc["tpm"]["sha256"]


def test_shipped_artifact_tpm_sidecar_sha256_matches_recomputed_hash():
    """LOW-3(a), sidecar half: checkout-stable because
    references/EMS/generated/.gitattributes now marks the sidecar `-text`
    (LF-normalized, no autocrlf rewrite between checkouts) -- so this pin
    should hold on any clean checkout, not just the machine that generated
    the artifact."""
    doc_path = SHIPPED_POLICY_PATH
    with open(doc_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    sidecar_rel = doc["tpm"]["sidecar_path"]
    sidecar_abs = os.path.join(solver.REPO_ROOT, sidecar_rel.replace("/", os.sep))
    assert os.path.isfile(sidecar_abs), sidecar_abs
    assert solver.sha256_file(sidecar_abs) == doc["tpm"]["sidecar_sha256"]


def test_shipped_artifact_policy_block_digest_pin(shipped_policy):
    """LOW-3(b): pin the POLICY-BLOCK digest, not the raw file sha256 -- the
    solver agent's own report proved the raw byte sha moves on every --force
    (it carries generated_utc), so pinning it here would fail on the very
    next regeneration even with an UNCHANGED decision law. The policy-block
    digest is exactly the quantity hil_plant_sim.load_sdp_policy() records as
    `policy_sha256` (recipe:
    sha256(json.dumps(doc["policy"], sort_keys=True).encode("utf-8")))."""
    import hashlib
    digest = hashlib.sha256(
        json.dumps(shipped_policy["policy"], sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert digest == "dbe42d1b0ec5b40f07bc1d0ad91dd86ef90f44f7c62c51382dbf54e339821048"


def test_shipped_artifact_floor_node_clamp_tie_exception(shipped_policy):
    """D3/D8 floor-node clamp-tie exception (reviewer finding, made
    executable): at the clamped TOP demand bin (column 24) the policy is
    bang-bang about the SoC target for every node EXCEPT the exact grid-floor
    node (row 0, SoC == grid_min), which the D3 clamp-then-D8-tie-break
    combination resolves to the battery-favoring 0.0 rather than continuing
    the 1.0 rail down to the floor. Row 1 (the next node up) is back on the
    ordinary 1.0 rail. A future change to the tie-break rule (D8's "ties
    resolve toward the LOWEST control index") would flip this silently
    without this pin."""
    share = shipped_policy["policy"]["share"]
    assert share[0][24] == pytest.approx(0.0)
    assert share[1][24] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────
# 3b. v2 artifact (D11 demand-map re-normalization, 2026-08-31 ledger round):
#     tools/sdp_policies/sdp_policy_v2.json is now the SHIPPED consumer
#     artifact (DEFAULT_OUT / SDP_POLICY_FILE) -- v1 stays checked in,
#     untouched, for reproduction only. Same discipline as the v1 pins
#     above: read the FILE, not a fresh solve, so a regeneration that
#     silently changed the shipped decision law is caught here.
# ─────────────────────────────────────────────────────────────────────────

SHIPPED_POLICY_V2_PATH = os.path.join(HERE, "sdp_policies", "sdp_policy_v2.json")


@pytest.fixture(scope="session")
def shipped_policy_v2():
    assert os.path.isfile(SHIPPED_POLICY_V2_PATH), (
        "the shipped v2 artifact %r is missing -- regenerate with "
        "tools/sdp_ems_solver.py --force before running this suite"
        % SHIPPED_POLICY_V2_PATH)
    with open(SHIPPED_POLICY_V2_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_default_out_points_at_v3_and_schema_is_unchanged():
    """DEFAULT_OUT moved to sdp_policy_v3.json (D12); SCHEMA is the FILE
    FORMAT and stays sdp-policy-v1 on purpose -- v2 changed the demand MAP and
    v3 the alpha CALIBRATION, neither the document shape, so the same schema
    string covers all three files."""
    assert os.path.basename(solver.DEFAULT_OUT) == "sdp_policy_v3.json"
    assert solver.SCHEMA == "sdp-policy-v1"


def test_shipped_v2_policy_block_digest_pin(shipped_policy_v2):
    """The v2 policy-block sha256 -- the decision-law identity a run's
    config.sdp_policy sidecar block is compared against. Same recipe as the
    v1 pin above: sha256(json.dumps(doc["policy"], sort_keys=True))."""
    import hashlib
    digest = hashlib.sha256(
        json.dumps(shipped_policy_v2["policy"], sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert digest == "740c802e99dde3f53fad74d1844481f1030f11345a7ba8c9269014bbe2280087"


def test_shipped_v2_charge_forbidden_bins_is_6_through_24():
    """D11: under the wider [0, 25] W map the solver's own FC-current budget
    (rule (b)) newly forbids charging above bin 5, so the forbidden set
    widens from v1's [12..24] to v2's [6..24] -- 19 bins, not 13."""
    with open(SHIPPED_POLICY_V2_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    forbidden = doc["actions"]["charge_forbidden_bins"]
    assert forbidden == list(range(6, 25))


def test_shipped_v2_share_value_set_is_000_090_095_100(shipped_policy_v2):
    """v1's table only ever emits {0.00, 1.00} (a pure two-value rail); v2's
    demand axis is live enough to put TWO interior ladder steps (0.90, 0.95)
    into the value set -- this is the artifact-level fact `cmd_share_sp_raw`
    exists to make visible on a live run (run_hil_suite.py's
    sdp_table_interior_at_high_demand / sdp_table_rail_at_low_demand)."""
    share = shipped_policy_v2["policy"]["share"]
    values = {round(v, 4) for row in share for v in row}
    assert values == {0.0, 0.90, 0.95, 1.0}


def test_shipped_v2_floor_node_is_all_zero_and_an_interior_row_is_not(shipped_policy_v2):
    """The D3/D8 floor-node clamp-tie degeneracy (row 0, SoC == grid_min)
    still resolves to the battery-favoring 0.0 -- and under v2 it does so
    across the WHOLE row, not just the clamped top bin, since 0.0 is also
    the action at every bin below the target's clamp region at this SoC.
    An interior row (5) is NOT all-zero, so the floor-node check is not
    trivially satisfied by an artifact that emits 0.0 everywhere."""
    share = shipped_policy_v2["policy"]["share"]
    assert all(v == pytest.approx(0.0) for v in share[0])
    assert any(v != pytest.approx(0.0) for v in share[5])


def test_shipped_v2_normalization_block_shape_and_demand_map_source(shipped_policy_v2):
    """The v2 `normalization` block carries FIVE keys (D11): the map
    actually used (p_dem_min_w/max_w = 0.0/25.0), `demand_map_source`
    naming its provenance, and the sidecar's own numbers preserved beside
    it for a v1-vs-v2 diff -- never silently dropped or renamed."""
    norm = shipped_policy_v2["normalization"]
    assert set(norm) == {"p_dem_min_w", "p_dem_max_w", "demand_map_source",
                         "sidecar_p_dem_min_w", "sidecar_p_dem_max_w"}
    assert norm["p_dem_min_w"] == pytest.approx(0.0)
    assert norm["p_dem_max_w"] == pytest.approx(25.0)
    assert isinstance(norm["demand_map_source"], str) and norm["demand_map_source"]
    assert norm["sidecar_p_dem_min_w"] == pytest.approx(-1.124773461276723)
    assert norm["sidecar_p_dem_max_w"] == pytest.approx(1.639842192501809)


def test_shipped_v2_alpha_unchanged_from_v1(shipped_policy_v2, shipped_policy):
    """D11: alpha has no demand-axis term (it is derived from the pack's
    coulombic energy alone), so re-mapping the demand axis must NOT move
    it -- v1 and v2 carry the identical value."""
    assert shipped_policy_v2["alpha"]["value"] == pytest.approx(0.2569444444444444)
    assert shipped_policy_v2["alpha"]["value"] == pytest.approx(
        shipped_policy["alpha"]["value"])


# ─────────────────────────────────────────────────────────────────────────
# 3d. v3 artifact (D12 two-sided alpha calibration, 2026-09-01 adjudication):
#     tools/sdp_policies/sdp_policy_v3.json is the SHIPPED benchmark
#     artifact. v1 and v2 stay checked in, BYTE-UNTOUCHED -- v2's policy
#     digest is cited in two campaign ledgers, so a regeneration that moved
#     it would invalidate published results. Same discipline as above: read
#     the FILE, never a fresh solve.
# ─────────────────────────────────────────────────────────────────────────

SHIPPED_POLICY_V3_PATH = os.path.join(HERE, "sdp_policies", "sdp_policy_v3.json")


@pytest.fixture(scope="session")
def shipped_policy_v3():
    assert os.path.isfile(SHIPPED_POLICY_V3_PATH), (
        "the shipped v3 artifact %r is missing -- regenerate with "
        "tools/sdp_ems_solver.py --force before running this suite"
        % SHIPPED_POLICY_V3_PATH)
    with open(SHIPPED_POLICY_V3_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_shipped_v3_policy_block_digest_pin(shipped_policy_v3):
    """The v3 decision-law identity, same recipe as the v1/v2 pins."""
    import hashlib
    digest = hashlib.sha256(
        json.dumps(shipped_policy_v3["policy"], sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert digest == "0443febf240a9f5c207c42595f5841d2842496ac786c4d5342f1f8dfe33c61a2"


def test_shipped_v3_alpha_is_the_two_sided_lever_value_in_both_windows(shipped_policy_v3):
    a = shipped_policy_v3["alpha"]
    assert a["value"] == pytest.approx(ALPHA_LEVER_SHIPPED, rel=1e-12)
    assert a["mode"] == "lever"
    assert a["admission"]["in_window_model"] is True
    assert a["admission"]["in_window_measured"] is True
    assert a["admission"]["allow_out_of_window"] is False
    assert a["admission"]["window_model"] == pytest.approx(WINDOW_MODEL, abs=5e-7)
    assert a["admission"]["window_measured"] == pytest.approx(WINDOW_MEASURED,
                                                             abs=5e-7)
    # The revisit condition D12 promises: the bound the charger's measured
    # lever must cross for charging to return endogenously.
    assert a["admission"]["threshold_soc_per_g"] == pytest.approx(0.30681920600332,
                                                                 rel=1e-9)
    lv = a["levers_soc_per_g"]
    assert lv["share_model"] == pytest.approx(L_SHARE_MODEL, rel=1e-12)
    assert lv["charge_model"] == pytest.approx(L_CHG_MODEL, rel=1e-12)
    assert lv["share_measured"] == solver.EMS_LEVER_SHARE_SOC_PER_G
    assert lv["charge_measured"] == solver.EMS_LEVER_CHARGE_SOC_PER_G
    assert a["candidates"]["marginal"] == pytest.approx(ALPHA_MARGINAL_V2)


def test_shipped_v3_has_zero_charge_enabled_cells_and_no_mask(shipped_policy_v3):
    """Charging is rejected ENDOGENOUSLY: the charge action is available in
    bins 0-5 and simply never chosen. `forbid_charge_all` False is what
    separates that from a mask (D12)."""
    goal = np.array(shipped_policy_v3["policy"]["charge_goal"])
    assert (goal == 0.0).all()
    assert shipped_policy_v3["actions"]["forbid_charge_all"] is False
    forbidden = set(shipped_policy_v3["actions"]["charge_forbidden_bins"])
    assert forbidden == set(range(6, 25))
    n_bins = goal.shape[1]
    assert [j for j in range(n_bins) if j not in forbidden] == [0, 1, 2, 3, 4, 5]


def test_shipped_v3_share_table_differs_from_v2_in_exactly_the_clamp_rows(
        shipped_policy_v3, shipped_policy_v2):
    """The adjudicated acceptance property: the alpha recalibration must NOT
    disturb the share map where ems-sdp actually operates. Exactly 30 cells
    move, ALL of them in SoC rows 1-2 (the D3 clamp-boundary region); the
    operating rows ~48-50 are untouched."""
    s2 = np.array(shipped_policy_v2["policy"]["share"])
    s3 = np.array(shipped_policy_v3["policy"]["share"])
    assert s2.shape == s3.shape
    rows, _cols = np.nonzero(s2 != s3)
    assert rows.size == 30
    assert set(rows.tolist()) == {1, 2}
    for r in (48, 49, 50):
        assert (s2[r] == s3[r]).all()
    # ...and the charge tables differ on every cell v2 had enabled.
    c2 = np.array(shipped_policy_v2["policy"]["charge_goal"])
    assert int((c2 > 0.0).sum()) == 294


def test_shipped_v3_non_degenerate_on_both_axes(shipped_policy_v3):
    """Both acceptance spreads are PRESERVED across the recalibration:
    0.100 across demand bins at the SoC-target row, 1.000 across SoC at the
    dominant idle bin 10."""
    share = np.array(shipped_policy_v3["policy"]["share"])
    soc_grid = np.array(shipped_policy_v3["soc"]["grid"])
    i_tgt = int(np.abs(soc_grid - shipped_policy_v3["soc"]["target"]).argmin())
    row = share[i_tgt]
    col = share[:, 10]
    assert row.max() - row.min() == pytest.approx(0.100, abs=1e-9)
    assert col.max() - col.min() == pytest.approx(1.000, abs=1e-9)


def test_shipped_v3_converged_and_shares_v2_demand_map(shipped_policy_v3):
    """v3 changes alpha ONLY -- the D11 demand map, the grid and the schema
    are v2's, so a v2-vs-v3 comparison isolates the economics."""
    assert shipped_policy_v3["solver"]["converged"] is True
    assert shipped_policy_v3["solver"]["final_delta"] < \
        shipped_policy_v3["solver"]["tolerance"]
    norm = shipped_policy_v3["normalization"]
    assert norm["p_dem_min_w"] == pytest.approx(0.0)
    assert norm["p_dem_max_w"] == pytest.approx(25.0)
    assert shipped_policy_v3["schema"] == "sdp-policy-v1"
    assert shipped_policy_v3["soc"]["n"] == 101
    assert len(shipped_policy_v3["actions"]["share_ladder"]) == 21


def test_v1_and_v2_artifacts_still_load_under_the_unchanged_schema(
        shipped_policy, shipped_policy_v2, shipped_policy_v3):
    """v3 ADDS keys under `alpha`/`actions`; the older artifacts lack them and
    must still parse. A consumer keyed on `alpha.value` + the policy tables
    reads all three."""
    for doc in (shipped_policy, shipped_policy_v2, shipped_policy_v3):
        assert doc["schema"] == solver.SCHEMA == "sdp-policy-v1"
        assert isinstance(doc["alpha"]["value"], float)
        assert len(doc["policy"]["share"]) == doc["soc"]["n"]
        assert len(doc["policy"]["charge_goal"]) == doc["soc"]["n"]
    # The additive fields exist ONLY on v3 -- pinned so a future round cannot
    # backfill them into the frozen artifacts without noticing.
    assert "mode" not in shipped_policy["alpha"]
    assert "mode" not in shipped_policy_v2["alpha"]
    assert "forbid_charge_all" not in shipped_policy_v2["actions"]


# ─────────────────────────────────────────────────────────────────────────
# 3c. --demand-map / --demand-map-sidecar CLI surface
# ─────────────────────────────────────────────────────────────────────────

def test_demand_map_and_demand_map_sidecar_are_mutually_exclusive(tmp_path, capsys):
    out = tmp_path / "bad.json"
    with pytest.raises(SystemExit):
        solver.main(_REDUCED_ARGV + ["--demand-map", "0", "10",
                                     "--demand-map-sidecar", "--out", str(out)])
    err = capsys.readouterr().err
    assert "mutually exclusive" in err
    assert not out.exists()


def test_demand_map_max_must_exceed_min(tmp_path, capsys):
    out = tmp_path / "bad.json"
    with pytest.raises(SystemExit):
        solver.main(_REDUCED_ARGV + ["--demand-map", "10", "10", "--out", str(out)])
    err = capsys.readouterr().err
    assert "MAX_W must exceed MIN_W" in err
    assert not out.exists()

    with pytest.raises(SystemExit):
        solver.main(_REDUCED_ARGV + ["--demand-map", "10", "5", "--out", str(out)])
    assert not out.exists()


def test_explicit_demand_map_is_recorded_verbatim(tmp_path):
    out = tmp_path / "explicit_map.json"
    rc = solver.main(_REDUCED_ARGV + ["--demand-map", "1.5", "40.0", "--out", str(out)])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    norm = doc["normalization"]
    assert norm["p_dem_min_w"] == pytest.approx(1.5)
    assert norm["p_dem_max_w"] == pytest.approx(40.0)
    assert "explicit --demand-map" in norm["demand_map_source"]
    # The sidecar's OWN numbers are still recorded, even though they were
    # not the map used -- D11's "carried, not consumed" contract.
    assert norm["sidecar_p_dem_min_w"] == pytest.approx(-1.124773461276723)
    assert norm["sidecar_p_dem_max_w"] == pytest.approx(1.639842192501809)


def test_demand_map_sidecar_flag_uses_the_sidecar_span(tmp_path):
    out = tmp_path / "sidecar_map.json"
    rc = solver.main(_REDUCED_ARGV + ["--demand-map-sidecar", "--out", str(out)])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    norm = doc["normalization"]
    assert norm["p_dem_min_w"] == pytest.approx(norm["sidecar_p_dem_min_w"])
    assert norm["p_dem_max_w"] == pytest.approx(norm["sidecar_p_dem_max_w"])
    assert "sidecar" in norm["demand_map_source"].lower()


def test_default_demand_map_is_0_to_25_when_neither_flag_given(tmp_path):
    out = tmp_path / "default_map.json"
    rc = solver.main(_REDUCED_ARGV + ["--out", str(out)])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    norm = doc["normalization"]
    assert norm["p_dem_min_w"] == pytest.approx(0.0)
    assert norm["p_dem_max_w"] == pytest.approx(25.0)
    assert norm["demand_map_source"] == solver.DEMAND_MAP_DEFAULT_SOURCE


# ─────────────────────────────────────────────────────────────────────────
# 4. Interp-J regression: the SoC transition genuinely sub-grid-spacing, and
#    the interpolation used against it splits weight between two nodes
#    rather than snapping to one (the D1 correctness fix, made executable).
# ─────────────────────────────────────────────────────────────────────────

def test_build_stage_soc_transition_is_sub_grid_spacing_and_not_grid_aligned():
    """Cheapest possible pin of D1's own measured fact: at this rig's power a
    single 1 s stage moves SoC by ~1e-5-1e-6 against a ~1e-3 grid spacing, so
    under NEAREST-GRID snapping (the MATLAB's own behaviour, explicitly
    rejected by D1) every transition would land back on its own starting
    node. Verified directly against build_stage()'s own soc_next output --
    no full solve required."""
    soc_grid = np.linspace(0.55, 0.65, 101)
    step = soc_grid[1] - soc_grid[0]
    shares = np.linspace(0.0, 1.0, 21)
    p_centers = np.array([0.5])          # one positive-demand bin, 0.5 W
    cap_as = 5.0 * 3600.0                # BATT_CAPACITY_AH default * 3600
    chg_allowed = np.array([True])

    stage, soc_next, feas = solver.build_stage(
        p_centers, shares, soc_grid, alpha=0.25, dt=1.0, cap_as=cap_as,
        chg_a=0.8, chg_allowed=chg_allowed, soc_target=0.6,
        soc_lo=soc_grid[0], soc_hi=soc_grid[-1])

    # share = 0.0 (pure battery discharge, control index 0) at a mid-grid SoC
    # row: the transition must have MOVED (nonzero) but stayed far inside a
    # single grid cell (sub-spacing), i.e. it neither snapped to its own
    # starting node NOR jumped to a neighboring one.
    i_soc = 50
    moved = soc_next[0, i_soc, 0]
    delta = moved - soc_grid[i_soc]
    assert delta != 0.0
    assert 0.0 < abs(delta) < 0.01 * step, (
        "expected a sub-grid-spacing SoC step (D1's whole premise); got "
        "delta=%.3e against grid step=%.3e" % (delta, step))

    # Nearest-grid semantics (the REJECTED MATLAB behaviour) would round this
    # straight back to its own starting node -- confirm that is NOT what the
    # feasibility/soc_next array records, i.e. it genuinely lies strictly
    # between two grid nodes and needs interpolation to be read at all.
    idx_below = int(np.searchsorted(soc_grid, moved)) - 1
    assert 0 <= idx_below < len(soc_grid) - 1
    assert soc_grid[idx_below] < moved < soc_grid[idx_below + 1]


def test_interpolation_splits_weight_across_two_grid_nodes_for_a_sub_spacing_step():
    """The SAME np.interp() call value_iterate()/greedy_policy() use against
    build_stage()'s soc_next, exercised directly against a KNOWN (non-flat)
    cost-to-go column: a sub-grid-spacing move must change the interpolated
    value by a PROPORIONAL sub-grid-spacing amount, never by the full
    neighbor-to-neighbor jump a nearest-grid lookup would produce."""
    soc_grid = np.linspace(0.55, 0.65, 101)
    step = soc_grid[1] - soc_grid[0]
    # A column with real slope (linear in SoC), so np.interp's LINEAR
    # blending is directly checkable against the analytic answer.
    ej_col = 3.0 * soc_grid + 1.0

    i_soc = 50
    x0 = soc_grid[i_soc]
    sub_step = step * 0.01
    x1 = x0 + sub_step

    v0 = np.interp(x0, soc_grid, ej_col)
    v1 = np.interp(x1, soc_grid, ej_col)
    assert v0 == pytest.approx(ej_col[i_soc])
    # The interpolated value at x1 must differ from v0 by the SLOPE times the
    # sub-step -- i.e. it blended the two neighboring nodes' weight
    # proportionally, not snapped wholesale onto one of them.
    assert v1 == pytest.approx(v0 + 3.0 * sub_step, rel=1e-9)
    assert v1 != pytest.approx(v0)
    # And it must NOT equal the NEXT grid node's value either -- a
    # coarser-than-nearest-grid bug (rounding up) would produce that instead.
    assert v1 != pytest.approx(ej_col[i_soc + 1])


# ─────────────────────────────────────────────────────────────────────────
# 5. alpha collapse pin: --alpha-mode level (REJECTED) degenerates the
#    policy; the default coulombic (marginal) mode does not.
# ─────────────────────────────────────────────────────────────────────────

def test_alpha_mode_level_collapses_share_spread_to_zero(tmp_path):
    """The REJECTED `level` mode collapses under the TINY sidecar demand span
    (-1.125 .. +1.640 W): alpha_level = 500 * 1.6398/60000 = 0.01366, small
    enough that the SoC penalty dominates the whole cell.  Under the SHIPPED
    v2 default map (0, 25 W) alpha_level recomputes to 500*25/60000 = 0.2083
    (solver D11 / the rejected-alternative note) -- large enough that the
    collapse this test is pinning no longer happens, so --demand-map-sidecar
    is required here to reproduce the v1-era degenerate case the module
    documents."""
    out = tmp_path / "level.json"
    # alpha_level under the sidecar map (0.01366) is far BELOW the D12
    # admission windows, so the tripwire refuses it without the explicit
    # historical-reproduction override.
    rc = solver.main(_REDUCED_ARGV + ["--alpha-mode", "level",
                                      "--demand-map-sidecar",
                                      "--allow-out-of-window", "--out", str(out)])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    share = np.array(doc["policy"]["share"])
    assert share.max() == pytest.approx(0.0)
    assert share.min() == pytest.approx(0.0)
    assert doc["alpha"]["value"] == pytest.approx(
        solver.FULL_SIZE_ALPHA * doc["normalization"]["p_dem_max_w"]
        / solver.FULL_SIZE_P_DEM_MAX_W)


def test_alpha_mode_lever_default_yields_nonzero_spread(reduced_policy):
    """The DEFAULT is now `lever` (D12), not `marginal`."""
    share = np.array(reduced_policy["policy"]["share"])
    assert share.max() > share.min()
    assert reduced_policy["alpha"]["mode"] == "lever"
    assert reduced_policy["alpha"]["value"] == pytest.approx(0.1629624189805737)


def test_alpha_mode_marginal_still_reachable_with_the_override(tmp_path):
    """The failed v1/v2 derivation stays REACHABLE (it regenerates their
    economics) but only behind --allow-out-of-window."""
    out = tmp_path / "marginal.json"
    rc = solver.main(_REDUCED_ARGV + ["--alpha-mode", "marginal",
                                      "--allow-out-of-window", "--out", str(out)])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["alpha"]["mode"] == "marginal"
    assert doc["alpha"]["value"] == pytest.approx(
        solver.FULL_SIZE_ALPHA * (solver.V_PACK_NOMINAL_V * solver.BATT_CAPACITY_AH)
        / (solver.FULL_SIZE_EM_V * solver.FULL_SIZE_Q_AH))
    assert doc["alpha"]["admission"]["in_window_model"] is False
    assert doc["alpha"]["admission"]["allow_out_of_window"] is True


def test_explicit_alpha_overrides_alpha_mode(tmp_path):
    out = tmp_path / "explicit_alpha.json"
    # 0.1 is below both windows -- an explicit alpha is not exempt from the
    # tripwire, which is the point of it.
    rc = solver.main(_REDUCED_ARGV + ["--alpha", "0.1", "--alpha-mode", "level",
                                      "--allow-out-of-window", "--out", str(out)])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["alpha"]["value"] == pytest.approx(0.1)
    assert doc["alpha"]["mode"] == "explicit"


def test_explicit_alpha_must_be_positive(tmp_path, capsys):
    """(1-gamma)/alpha is undefined at 0; argparse refuses before any solve."""
    out = tmp_path / "zero.json"
    with pytest.raises(SystemExit):
        solver.main(_REDUCED_ARGV + ["--alpha", "0", "--out", str(out)])
    assert "--alpha must be > 0" in capsys.readouterr().err
    assert not out.exists()


# ─────────────────────────────────────────────────────────────────────────
# 5b. D12 -- the lever algebra, the admission-window tripwire, the knife-edge
#     flip bracket, and --forbid-charge.
# ─────────────────────────────────────────────────────────────────────────

# The shipped numbers, pinned as literals rather than recomputed from the
# helpers: a helper that changed its own formula would otherwise agree with
# itself.  Derivations are in D12 / ALPHA_DERIVATION.
ALPHA_LEVER_SHIPPED = 0.1629624189805737
L_SHARE_MODEL = 0.4504504504504504
L_CHG_MODEL = 0.20898641588296765
WINDOW_MODEL = (0.111000, 0.239250)
WINDOW_MEASURED = (0.121359, 0.211506)
# The FAILED v1/v2 alpha and the sweep-confirmed flip point (1-gamma)/L_chg.
ALPHA_MARGINAL_V2 = 0.2569444444444444
ALPHA_JUST_BELOW_FLIP = 0.239


def test_model_levers_match_the_pinned_values_and_their_ratio_is_v_bus_over_v_pack():
    """D12's k-cancellation, made executable: the hydrogen basis drops out of
    the levers' ratio entirely, which is why no efficiency or accounting
    convention can explain v2's over-charging."""
    l_share, l_chg = solver.model_levers()
    assert l_share == pytest.approx(L_SHARE_MODEL, rel=1e-12)
    assert l_chg == pytest.approx(L_CHG_MODEL, rel=1e-12)
    assert l_chg / l_share == pytest.approx(
        solver.V_PACK_NOMINAL_V / solver.V_BUS_NOMINAL_V, rel=1e-12)
    # ...and it is INDEPENDENT of eta_fc / Q_LHV, the two constants the
    # refuted loss-chain hypothesis blamed.
    alt = solver.model_levers(eta_fc=0.4725, q_lhv=1.0e5)
    assert alt[1] / alt[0] == pytest.approx(l_chg / l_share, rel=1e-12)


def test_measured_lever_constants_are_the_campaign_values():
    assert solver.EMS_LEVER_SHARE_SOC_PER_G == 0.412
    assert solver.EMS_LEVER_CHARGE_SOC_PER_G == 0.2364
    # The finding itself: the charger is the WORSE lever on BOTH bases.
    assert solver.EMS_LEVER_CHARGE_SOC_PER_G < solver.EMS_LEVER_SHARE_SOC_PER_G
    assert L_CHG_MODEL < L_SHARE_MODEL


def test_admission_windows_and_shipped_alpha_lie_strictly_inside_both():
    one_minus_gamma = 1.0 - 0.95
    win_model = solver.admission_window(one_minus_gamma, L_SHARE_MODEL,
                                        L_CHG_MODEL)
    win_meas = solver.admission_window(one_minus_gamma,
                                       solver.EMS_LEVER_SHARE_SOC_PER_G,
                                       solver.EMS_LEVER_CHARGE_SOC_PER_G)
    assert win_model == pytest.approx(WINDOW_MODEL, abs=5e-7)
    assert win_meas == pytest.approx(WINDOW_MEASURED, abs=5e-7)

    alpha = solver.alpha_lever(one_minus_gamma, L_SHARE_MODEL, L_CHG_MODEL)
    assert alpha == pytest.approx(ALPHA_LEVER_SHIPPED, rel=1e-12)
    assert win_model[0] < alpha < win_model[1]
    assert win_meas[0] < alpha < win_meas[1]
    # And the FAILED alpha is outside the model window on the CHARGE side --
    # the single fact the tripwire exists to catch.
    assert ALPHA_MARGINAL_V2 > win_model[1]
    assert ALPHA_MARGINAL_V2 > win_meas[1]


def test_admission_window_rejects_a_degenerate_lever_pair():
    with pytest.raises(ValueError):
        solver.admission_window(0.05, 0.2, 0.4)          # hi <= lo
    with pytest.raises(ValueError):
        solver.admission_window(0.05, 0.4, 0.0)          # lo not > 0


def test_window_assert_refuses_an_out_of_window_alpha_without_the_override(tmp_path, capsys):
    """THE TRIPWIRE. --alpha-mode marginal at default gamma is exactly the
    v1/v2 configuration; it must fail LOUDLY and write nothing."""
    out = tmp_path / "refused.json"
    rc = solver.main(_REDUCED_ARGV + ["--alpha-mode", "marginal",
                                      "--out", str(out)])
    assert rc == 2
    assert not out.exists()
    err = capsys.readouterr().err
    assert "REFUSING to solve" in err
    assert "MODEL" in err and "MEASURED" in err
    assert "D12" in err


def test_window_assert_also_refuses_an_alpha_below_both_windows(tmp_path, capsys):
    out = tmp_path / "refused_low.json"
    rc = solver.main(_REDUCED_ARGV + ["--alpha", "0.05", "--out", str(out)])
    assert rc == 2
    assert not out.exists()
    assert "REFUSING to solve" in capsys.readouterr().err


def test_window_assert_passes_for_the_default_lever_mode(tmp_path):
    out = tmp_path / "ok.json"
    assert solver.main(_REDUCED_ARGV + ["--out", str(out)]) == 0
    with open(out, encoding="utf-8") as fh:
        adm = json.load(fh)["alpha"]["admission"]
    assert adm["in_window_model"] is True
    assert adm["in_window_measured"] is True
    assert adm["allow_out_of_window"] is False


def test_knife_edge_flip_bracket_at_the_full_default_grid(tmp_path):
    """THE REGRESSION THAT PINS THE DEFECT. On the FULL shipped grid:
    alpha = 0.2569444 (v1/v2) admits the Ag105 in 294 cells; alpha = 0.239,
    just below the (1-gamma)/L_chg = 0.23925 flip point, admits it in none.
    A change that silently moved the flip bracket -- a different V_bus, pack
    capacity, gamma, or charge accounting -- would break exactly here."""
    def _charge_cells(alpha):
        out = tmp_path / ("flip_%s.json" % alpha)
        rc = solver.main(["--alpha", repr(alpha), "--allow-out-of-window",
                          "--eta-chg-none", "--out", str(out)])
        assert rc == 0
        with open(out, encoding="utf-8") as fh:
            goal = json.load(fh)["policy"]["charge_goal"]
        return sum(1 for row in goal for v in row if v > 0.0)

    assert _charge_cells(ALPHA_MARGINAL_V2) == 294
    assert _charge_cells(ALPHA_JUST_BELOW_FLIP) == 0


def test_forbid_charge_yields_zero_charge_cells_at_any_alpha(tmp_path):
    """--forbid-charge is the MASK: it must hold even at the alpha that
    otherwise admits charging in 294 cells."""
    out = tmp_path / "masked.json"
    rc = solver.main(_REDUCED_ARGV + ["--forbid-charge", "--alpha",
                                      repr(ALPHA_MARGINAL_V2),
                                      "--allow-out-of-window", "--out", str(out)])
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    goal = np.array(doc["policy"]["charge_goal"])
    assert (goal == 0.0).all()
    n_bins = doc["demand_bins"]["n"]
    assert doc["actions"]["charge_forbidden_bins"] == list(range(n_bins))
    assert doc["actions"]["forbid_charge_all"] is True


def test_forbid_charge_is_a_UNION_and_keeps_every_derived_bin(tmp_path,
                                                              capsys):
    """L6 / untested-behavior #6: `--forbid-charge` UNIONS the blanket mask with
    the dwell + FC-budget set rather than replacing it, so
    `actions.charge_forbidden_bins` keeps ONE meaning in the artifact. Pinned
    against the derived set from the SAME reduced solve, and against the summary
    line, whose derived count used to be overwritten by the mask's total (so it
    printed "N by dwell, M by budget -> all_bins forbidden", a total unrelated
    to either component)."""
    plain = tmp_path / "plain.json"
    masked = tmp_path / "masked.json"
    argv = _REDUCED_ARGV + ["--alpha", repr(ALPHA_MARGINAL_V2),
                            "--allow-out-of-window"]
    assert solver.main(argv + ["--out", str(plain)]) == 0
    derived_line = capsys.readouterr().out
    assert solver.main(argv + ["--forbid-charge", "--out", str(masked)]) == 0
    masked_line = capsys.readouterr().out

    with open(plain, encoding="utf-8") as fh:
        derived = set(json.load(fh)["actions"]["charge_forbidden_bins"])
    with open(masked, encoding="utf-8") as fh:
        doc = json.load(fh)
    n_bins = doc["demand_bins"]["n"]
    got = set(doc["actions"]["charge_forbidden_bins"])
    assert derived, "sanity: the derived rules must forbid SOMETHING here"
    assert derived <= got                       # union, never a replacement
    assert got == set(range(n_bins))
    # The summary line reports the DERIVED count, and names the override.
    assert "-> %d forbidden (derived)" % len(derived) in derived_line
    assert "-> %d forbidden (derived)" % len(derived) in masked_line
    assert "OVERRIDES this to all %d bins" % n_bins in masked_line
    assert "OVERRIDES" not in derived_line


def test_default_solve_does_not_set_forbid_charge_all(reduced_policy):
    """The shipped artifact rejects charging ENDOGENOUSLY, not by mask -- the
    distinction D12 turns on. If this ever flips to True the artifact has
    stopped recording a reason."""
    assert reduced_policy["actions"]["forbid_charge_all"] is False


# ─────────────────────────────────────────────────────────────────────────
# 6. Determinism: two reduced solves, identical args -> identical policy
# ─────────────────────────────────────────────────────────────────────────

def test_two_reduced_solves_produce_identical_policy_blocks(tmp_path):
    out1 = tmp_path / "a.json"
    out2 = tmp_path / "b.json"
    rc1 = solver.main(_REDUCED_ARGV + ["--out", str(out1)])
    rc2 = solver.main(_REDUCED_ARGV + ["--out", str(out2)])
    assert rc1 == 0 and rc2 == 0
    with open(out1, encoding="utf-8") as fh:
        doc1 = json.load(fh)
    with open(out2, encoding="utf-8") as fh:
        doc2 = json.load(fh)
    assert doc1["policy"] == doc2["policy"]
    assert doc1["solver"]["iterations"] == doc2["solver"]["iterations"]
    assert doc1["solver"]["final_delta"] == doc2["solver"]["final_delta"]
    assert doc1["alpha"] == doc2["alpha"]
    assert doc1["gamma"] == doc2["gamma"]
    # generated_utc is the one field expected to differ between two calls.
    assert "generated_utc" in doc1 and "generated_utc" in doc2


# ─────────────────────────────────────────────────────────────────────────
# 7. Refusals: existing output without --force; non-convergence
# ─────────────────────────────────────────────────────────────────────────

def test_refuses_to_overwrite_existing_output_without_force(tmp_path, capsys):
    out = tmp_path / "a.json"
    rc1 = solver.main(_REDUCED_ARGV + ["--out", str(out)])
    assert rc1 == 0
    capsys.readouterr()
    rc2 = solver.main(_REDUCED_ARGV + ["--out", str(out)])
    assert rc2 == 2
    err = capsys.readouterr().err
    assert "REFUSING to overwrite" in err


def test_force_allows_overwrite(tmp_path):
    out = tmp_path / "a.json"
    assert solver.main(_REDUCED_ARGV + ["--out", str(out)]) == 0
    assert solver.main(_REDUCED_ARGV + ["--out", str(out), "--force"]) == 0


def test_non_convergence_refuses_to_write(tmp_path, capsys):
    out = tmp_path / "unconverged.json"
    rc = solver.main(_REDUCED_ARGV + ["--out", str(out), "--max-iter", "1"])
    assert rc == 2
    assert not os.path.exists(out)
    err = capsys.readouterr().err
    assert "REFUSING to write an unconverged policy" in err


def test_non_convergence_dry_run_does_not_need_to_write(tmp_path, capsys):
    """--dry-run and non-convergence are two independent refusals to write;
    a non-converged --dry-run solve must still report cleanly (rc 2, same
    refusal) rather than crash on interacting flags."""
    out = tmp_path / "never.json"
    rc = solver.main(_REDUCED_ARGV + ["--out", str(out), "--max-iter", "1",
                                      "--dry-run"])
    assert rc == 2
    assert not os.path.exists(out)


# ─────────────────────────────────────────────────────────────────────────
# 8. Gamma: rescale_gamma is actually called; effective gamma == 0.95 at dt=1
# ─────────────────────────────────────────────────────────────────────────

def test_rescale_gamma_is_called_and_matches_recorded_effective_value(tmp_path, monkeypatch):
    calls = []
    real = solver.rescale_gamma

    def _spy(gamma_base, dt, dt_base=1.0):
        calls.append((gamma_base, dt, dt_base))
        return real(gamma_base, dt, dt_base)

    monkeypatch.setattr(solver, "rescale_gamma", _spy)
    out = tmp_path / "gamma.json"
    rc = solver.main(_REDUCED_ARGV + ["--out", str(out)])
    assert rc == 0
    assert calls, "solver.rescale_gamma was never called"
    gb, dt, dtb = calls[0]
    assert gb == pytest.approx(solver.GAMMA_BASE)
    assert dt == pytest.approx(1.0)
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["gamma"]["effective"] == pytest.approx(0.95)
    assert doc["gamma"]["base"] == pytest.approx(0.95)
    assert doc["gamma"]["dt_s"] == pytest.approx(1.0)


def test_rescale_gamma_effective_tracks_dt_scaling_directly():
    """Belt-and-braces on the underlying function itself (imported from
    tpm_generator, not reimplemented here): gamma_eff = gamma_base**(dt/dt_base)."""
    assert tpm_generator.rescale_gamma(0.95, 1.0, 1.0) == pytest.approx(0.95)
    assert tpm_generator.rescale_gamma(0.95, 0.5, 1.0) == pytest.approx(0.95 ** 0.5)


# ==========================================================================
# 2026-09-01 charger-efficiency round (WP-1B1), D13.  The charge lever's
# billing voltage moves from V_bus to V_pack/eta, which halves the distance
# between the two levers and makes the alpha placement the live question.
# ==========================================================================

def test_model_levers_new_era_is_exactly_eta_times_the_share_lever():
    """D13's identity: with both levers billing at the pack voltage, the
    charge lever IS the share lever times the converter efficiency - whatever
    the pack, the bus or the capacity do."""
    for eta in (0.80, 0.88, 0.95):
        for cap in (2.5, 5.0, 9.0):
            l_share, l_chg = solver.model_levers(capacity_ah=cap, eta_chg=eta)
            assert l_chg == pytest.approx(eta * l_share, rel=1e-12)


def test_model_levers_old_era_is_unchanged_and_bills_the_bus():
    l_share, l_chg = solver.model_levers()
    assert l_share == pytest.approx(0.4504504504504504, rel=1e-12)
    assert l_chg == pytest.approx(0.20898641588296765, rel=1e-12)
    assert solver.model_levers(eta_chg=None) == (l_share, l_chg)


def test_new_era_lever_numbers_are_the_documented_ones():
    l_share, l_chg = solver.model_levers(eta_chg=0.88)
    assert l_chg == pytest.approx(0.3963963963963964, rel=1e-12)
    omg = 0.05
    assert solver.alpha_lever(omg, l_share, l_chg) == \
        pytest.approx(0.11832639757736382, rel=1e-9)
    assert solver.alpha_charge_edge(omg, l_share, l_chg) == \
        pytest.approx(0.1262625, rel=1e-9)


def test_measured_levers_projection_and_era_invariance_of_the_share_lever():
    """The share lever never touches the charger and must not move; the
    charge lever is an OLD-ERA measurement and is projected."""
    s_old, c_old = solver.measured_levers(None)
    s_new, c_new = solver.measured_levers(0.88)
    assert s_old == s_new == solver.EMS_LEVER_SHARE_SOC_PER_G
    assert c_old == solver.EMS_LEVER_CHARGE_SOC_PER_G
    ratio = solver.V_BUS_NOMINAL_V / (solver.V_PACK_NOMINAL_V / 0.88)
    assert c_new == pytest.approx(c_old * ratio, rel=1e-12)
    # And the consequence D13 records: the projected pair INVERTS.
    assert c_new > s_new


def test_admit_both_window_is_open_above_and_bounded_by_the_worse_lever():
    lo, hi = solver.admit_both_window(0.05, 0.4504504504504504,
                                      0.3963963963963964)
    assert hi == float("inf")
    assert lo == pytest.approx(0.05 / 0.3963963963963964, rel=1e-12)


def test_alpha_charge_edge_admits_both_levers_and_lever_mode_rejects_charge():
    """The two modes' whole difference, stated as the admission test itself:
    a lever L is taken iff L > (1-gamma)/alpha."""
    omg = 0.05
    l_share, l_chg = solver.model_levers(eta_chg=0.88)
    a_lever = solver.alpha_lever(omg, l_share, l_chg)
    a_edge = solver.alpha_charge_edge(omg, l_share, l_chg)
    assert l_share > omg / a_lever > l_chg          # share in, charge out
    assert l_chg > omg / a_edge                     # both in
    assert a_edge > a_lever


def test_charge_forbidden_bins_new_era_forbids_no_more_than_the_old():
    """Rule (b), the FC current budget, counts the charger's INPUT current,
    which is smaller in the eta era - so the forbidden set can only shrink."""
    _path, side = solver.load_sidecar(solver.DEFAULT_TPM)
    p_centers = np.linspace(0.0, 25.0, 25)
    old, info_old = solver.charge_forbidden_bins(side, p_centers, 0.90, 0.8)
    new, info_new = solver.charge_forbidden_bins(side, p_centers, 0.90, 0.8,
                                                 0.88)
    assert set(new) <= set(old)
    assert info_new["n_forbidden_by_fc_budget"] <= \
        info_old["n_forbidden_by_fc_budget"]


def test_solver_reproduces_the_shipped_v3_policy_in_the_old_era(tmp_path):
    """--eta-chg-none is now REQUIRED to reproduce v3, and it must reproduce
    it EXACTLY: the shipped artifact was solved against the 1:1 charger."""
    out = str(tmp_path / "v3.json")
    rc = solver.main(["--eta-chg-none", "--alpha-mode", "lever",
                      "--out", out, "--force"])
    assert rc == 0
    got = json.load(open(out, encoding="utf-8"))
    want = json.load(open(os.path.join(HERE, "sdp_policies",
                                       "sdp_policy_v3.json"),
                          encoding="utf-8"))
    assert got["policy"] == want["policy"]
    assert got["alpha"]["value"] == pytest.approx(want["alpha"]["value"],
                                                  rel=1e-15)
    assert got["charger"]["eta_chg"] is None


def test_eta_chg_none_and_eta_chg_are_mutually_exclusive():
    """The era switch must not be expressible as an efficiency: eta 1.0 bills
    the PACK voltage where the old era bills the BUS, so the two arguments are
    two answers to one question and the CLI refuses both at once."""
    with pytest.raises(SystemExit):
        solver.main(["--eta-chg-none", "--eta-chg", "1.0", "--dry-run"])
    # And they really are different models, not the same one twice.
    assert solver.model_levers(eta_chg=1.0) != solver.model_levers(eta_chg=None)


def test_charge_edge_mode_admits_charge_cells_and_lever_mode_does_not(tmp_path):
    """The two candidate artifacts of the eta era, solved end to end."""
    outs = {}
    for mode in ("lever", "charge-edge"):
        out = str(tmp_path / ("%s.json" % mode))
        assert solver.main(["--alpha-mode", mode, "--eta-chg", "0.88",
                            "--out", out, "--force"]) == 0
        outs[mode] = json.load(open(out, encoding="utf-8"))
    n = {m: sum(1 for row in d["policy"]["charge_goal"] for v in row if v > 0.0)
         for m, d in outs.items()}
    assert n["lever"] == 0
    assert n["charge-edge"] > 0
    assert outs["charge-edge"]["alpha"]["value"] > outs["lever"]["alpha"]["value"]
    for d in outs.values():
        assert d["charger"]["eta_chg"] == 0.88
        assert "V_pack" in d["charger"]["billing_rule"]
    # And the window tripwire PASSED for both, each against its own intent.
    assert outs["lever"]["alpha"]["admission"]["window_intent"] == \
        "admit share, reject charge"
    assert outs["charge-edge"]["alpha"]["admission"]["window_intent"] == \
        "admit BOTH levers"
    assert outs["charge-edge"]["alpha"]["admission"]["window_model"][1] == \
        pytest.approx(float("inf")) or \
        outs["charge-edge"]["alpha"]["admission"]["window_model"][1] is None


def test_new_era_measured_window_is_recorded_as_undecidable_not_passed(tmp_path):
    """The honest half of D13: the projected measured levers do not order, so
    the `admit share, reject charge` measured window DOES NOT EXIST and is
    written as null rather than as a pair the solver cannot compute."""
    out = str(tmp_path / "lever.json")
    assert solver.main(["--alpha-mode", "lever", "--eta-chg", "0.88",
                        "--out", out, "--force"]) == 0
    adm = json.load(open(out, encoding="utf-8"))["alpha"]["admission"]
    assert adm["window_measured"] is None
    assert adm["window_model"] is not None



def test_undecidable_window_is_recorded_as_none_not_false(tmp_path):
    """An unchecked window must not masquerade as a checked-and-failed one.
    hil_plant_sim's calibrated-benchmark certificate tests `is not True`, so
    None still refuses the frontier role - it just names the right reason."""
    out = str(tmp_path / "lever_eta.json")
    assert solver.main(["--alpha-mode", "lever", "--eta-chg", "0.88",
                        "--out", out, "--force"]) == 0
    adm = json.load(open(out, encoding="utf-8"))["alpha"]["admission"]
    assert adm["in_window_measured"] is None
    assert adm["in_window_model"] is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ─────────────────────────────────────────────────────────────────────────
# The eta-era MEASURED levers (campaign 20260902_011926, fix-queue item 9)
# ─────────────────────────────────────────────────────────────────────────

def test_eta_era_measured_levers_are_recorded_with_their_source():
    assert solver.EMS_LEVER_SHARE_ETA_SOC_PER_G == pytest.approx(0.41688)
    assert solver.EMS_LEVER_CHARGE_ETA_SOC_PER_G == pytest.approx(0.33214)
    assert "20260902_011926" in solver.EMS_LEVERS_ETA_SOURCE
    # THE FINDING: the charger is STILL the worse lever, which is what the
    # projection predicted it would stop being.
    assert (solver.EMS_LEVER_CHARGE_ETA_SOC_PER_G
            < solver.EMS_LEVER_SHARE_ETA_SOC_PER_G)


def test_measured_levers_default_is_unchanged_by_the_new_measurement():
    """Every shipped artifact and alpha was solved against the projection; a
    silent re-pricing here would move all of them."""
    l_share, l_chg = solver.measured_levers(eta_chg=0.88)
    assert l_share == pytest.approx(solver.EMS_LEVER_SHARE_SOC_PER_G)
    # ...and the projection still predicts the (refuted) inversion, which is
    # why the pair is recorded rather than adopted.
    assert l_chg > l_share


def test_measured_levers_opt_in_returns_the_measured_pair():
    l_share, l_chg = solver.measured_levers(eta_chg=0.88, use_measured_eta=True)
    assert l_share == pytest.approx(solver.EMS_LEVER_SHARE_ETA_SOC_PER_G)
    assert l_chg == pytest.approx(solver.EMS_LEVER_CHARGE_ETA_SOC_PER_G)
    # The measured pair implies an admission window the shipped alpha sits
    # just below — recorded, and deliberately NOT acted on until a second
    # campaign reading.
    lo, hi = solver.admission_window(1.0 - solver.GAMMA_BASE, l_share, l_chg)
    assert lo == pytest.approx(0.11994, rel=1e-3)
    assert hi == pytest.approx(0.15055, rel=1e-3)


def test_measured_levers_opt_in_refuses_the_old_era():
    with pytest.raises(ValueError):
        solver.measured_levers(eta_chg=None, use_measured_eta=True)

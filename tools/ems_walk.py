"""Offline walk harness for any registered EMS strategy, with the firmware
share governor in the loop.

WHAT THIS IS FOR
----------------
An offline walk predicts what a strategy will do before a campaign runs it.
Two walks in this repository were wrong because they applied the COMMANDED
share directly: the firmware's share loop holds the last converged split below
0.55 A of source total, clips the reference through a minority-current
governor, rate-limits every move, and can take a channel off the bus. The
``ems-sdp-cross`` walk of campaign 20260901_024231 mispredicted a limit-cycle
period by 5.7x for exactly that reason, and the suite check built on it failed
a correct board.

This harness drives a strategy through the SAME reduced demand, pack and
hydrogen model that ``tools/gen_dp_ems_table.py`` solves against — so a walk
result is directly comparable with a DP bound — and passes every commanded
share through ``tools/governor_model.GovernorModel`` at the firmware's 1 kHz
tick. The DELIVERED share, not the commanded one, drives the pack.

MODEL COMPOSITION
-----------------
``gen_dp_ems_table.build_demand()``      demand, bus voltage, source total
``gen_dp_ems_table.scenario_drain_a()``  the scenario's auxiliary load
``gen_dp_ems_table.charge_mask()``       where a charge window is admissible
``gen_dp_ems_table.step_discharge()``    pack and Gfc hydrogen on the split
``gen_dp_ems_table.step_charge()``       pack and Gfc hydrogen on the charger
``hil_plant_sim.EMS_STRATEGIES``         the strategy, called at PI_CMD_HZ
``governor_model.GovernorModel``         the delivery path, at 1 kHz

FIDELITY BOUNDARIES
-------------------
* Everything ``gen_dp_ems_table``'s model already declares: no regen term in
  the demand (it over-states demand on decelerating stages), a shared-droop bus
  voltage used even inside charge windows, and no Ag105 settle or ramp.
* Everything ``governor_model`` declares, in particular that the Youla share
  controller is modelled by a slew-limited walk to the governed reference.
* The strategy is called with a feedback view built from this reduced model, so
  a strategy reading a key the model does not produce sees ``None``. The keys
  supplied are those ``gen_dp_ems_table.heuristic_walk()`` supplies plus
  ``V_bus``, ``I_charge`` and the scenario's ``ems_run_exit_s``.

REGRESSION ANCHOR
-----------------
``walk("soc-band", "ems-soc-band", governor=False)`` reproduces
``gen_dp_ems_table.heuristic_walk()`` term for term.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import governor_model as gov_mod        # stdlib only

# NumPy-needing modules are imported lazily so that merely importing this file
# (a test collection, a --help) does not require the miniforge environment.
_sim = None
_gen = None


def _load():
    """Import the simulator and the DP generator once."""
    global _sim, _gen
    if _sim is None:
        import hil_plant_sim as sim         # noqa: WPS433 (deliberate lazy import)
        _sim = sim
    if _gen is None:
        import gen_dp_ems_table as gen      # noqa: WPS433 (needs numpy)
        _gen = gen
    return _sim, _gen


# The hydrogen proxy's fuel-cell efficiency. The PhD student's abbreviated
# estimate (references/EMS/SDP_EnergyManagement2.m:53) uses 0.5;
# hil_plant_sim.H2_STATIC_PROXY_GPS_PER_W (.py:1020) encodes 0.55. Neither is
# this rig's H20 stack, whose rating puts it at 0.4 — the default here, and the
# operator's choice. The Gfc figure remains the plant-side metric; this is the
# online estimate a Pi could compute.
H2_PROXY_ETA_FC = 0.4
H2_LHV_J_PER_G = 120000.0


def h2_proxy_gps(p_fc_w: float, eta_fc: float = H2_PROXY_ETA_FC,
                 q_lhv_j_per_g: float = H2_LHV_J_PER_G) -> float:
    """Abbreviated hydrogen rate: ``P_fc / (eta_fc * Q_LHV)`` in g/s.

    ``p_fc_w`` is FUEL-CELL STACK power, not bus power. A negative argument
    returns 0.0: the stack does not run backwards, and a negative bus power is
    an artefact of the reduced model, not consumption to be credited."""
    if eta_fc <= 0.0 or q_lhv_j_per_g <= 0.0:
        raise ValueError("eta_fc and q_lhv_j_per_g must be positive")
    if p_fc_w <= 0.0:
        return 0.0
    return p_fc_w / (eta_fc * q_lhv_j_per_g)


@dataclass
class WalkResult:
    h2_g: float = 0.0                 # Gfc DC-gain stage cost, physical accounting
    h2_plant_g: float = 0.0           # the same, omitting the charger's own draw
    h2_proxy_g: float = 0.0           # the abbreviated P_fc/(eta*Q_LHV) estimate
    soc_final: float = 0.0
    delta_soc: float = 0.0
    mode_fractions: dict = field(default_factory=dict)
    mode_fractions_by_segment: dict = field(default_factory=dict)
    share_cmd: list = field(default_factory=list)
    share_delivered: list = field(default_factory=list)
    r_applied: list = field(default_factory=list)
    t: list = field(default_factory=list)
    charge_windows: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "h2 (Gfc, physical) : %.9f g" % self.h2_g,
            "h2 (Gfc, plant)    : %.9f g" % self.h2_plant_g,
            "h2 (proxy, eta=%.2f): %.9f g" % (H2_PROXY_ETA_FC, self.h2_proxy_g),
            "SoC final          : %.6f  (delta %+.6f)" % (self.soc_final,
                                                          self.delta_soc),
            "charge windows     : %d" % len(self.charge_windows),
        ]
        for t0, t1 in self.charge_windows:
            lines.append("    %8.3f .. %8.3f s" % (t0, t1))
        if self.mode_fractions:
            lines.append("firmware mode fractions (governor ticks):")
            for m in gov_mod.MODES:
                lines.append("    %-18s %6.2f %%"
                             % (m, 100.0 * self.mode_fractions.get(m, 0.0)))
        for seg, frac in sorted(self.mode_fractions_by_segment.items()):
            lines.append("  segment %r:" % seg)
            for m in gov_mod.MODES:
                if frac.get(m):
                    lines.append("      %-16s %6.2f %%" % (m, 100.0 * frac[m]))
        for n in self.notes:
            lines.append("NOTE: %s" % n)
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Auxiliary-load reconciliation
#
# ``hil_plant_sim.apply_scenario()`` (:7417) gives the SoC-band drain to THREE
# scenarios — ``ems-soc-band``, ``ems-dp-replay`` and ``ems-sdp`` — deliberately,
# so the three-way EMS comparison runs on a bit-identical load.
# ``gen_dp_ems_table.scenario_drain_a()`` mirrors that branch, and a walk built
# on a generator whose whitelist is SHORTER models a run without the missing
# drain: for ``ems-sdp`` that is roughly half the demand the board sees, and the
# walk's hydrogen total is then meaningless.
#
# The generator's whitelist is read at run time from
# ``gen_dp_ems_table.SOC_BAND_DRAIN_SCENARIOS``. As of 2026-09-01 it names all
# three, so the override below is INERT and nothing is substituted or reported.
# It fires only against a generator that is missing a branch, and it fires by
# DELEGATION — the generator's own function stays the model for every scenario
# it does cover, and its signature has already grown once (the ``aux_preload_a``
# stimulus-era argument). A generator that predates the constant entirely is
# handled by the ``getattr`` fallback to the historical two-name tuple.
#
# The reconciliation is never silent: when it fires, ``walk()`` records which
# scenarios it substituted for in ``WalkResult.notes``.
# ─────────────────────────────────────────────────────────────────────────────
_SIM_SOC_BAND_DRAIN_SCENARIOS = ("ems-soc-band", "ems-dp-replay", "ems-sdp")
_GEN_DRAIN_FALLBACK = ("ems-soc-band", "ems-dp-replay")


def _gap_drain_scenarios(gen) -> tuple:
    """Scenarios the simulator drains but this generator does not."""
    covered = tuple(getattr(gen, "SOC_BAND_DRAIN_SCENARIOS",
                            _GEN_DRAIN_FALLBACK))
    return tuple(sc for sc in _SIM_SOC_BAND_DRAIN_SCENARIOS
                 if sc not in covered)


def _soc_band_drain_a(sim, t: float) -> float:
    """The SoC-band drain term, verbatim from ``hil_plant_sim.py:7431-7433``."""
    ramp_in = max(0.0, min(1.0, (t - sim.SOC_BAND_DRAIN_START_S) / sim.SOC_LOAD_RAMP_S))
    ramp_out = max(0.0, min(1.0, (t - sim.SOC_BAND_DRAIN_END_S) / sim.SOC_LOAD_RAMP_S))
    return sim.I_AUX_A + sim.SOC_BAND_DRAIN_LOAD_A * (ramp_in - ramp_out)


class _drain_override(object):
    """Supply the drain branches this generator is missing, scoped.

    ``build_demand()`` calls ``scenario_drain_a()`` internally and takes no
    injection point, so the substitution is made around the call and undone
    afterwards — on the exception path too. ``fired`` records whether the
    scenario under walk was actually one of the missing ones, which is what
    ``walk()`` reports. Walks are single-threaded by construction; nothing else
    in the process may run against the generator module concurrently."""

    def __init__(self, gen, sim, scenario):
        self.gen, self.sim, self.scenario = gen, sim, scenario
        self.gap = _gap_drain_scenarios(gen)
        self.fired = scenario in self.gap
        self.saved = None

    def __enter__(self):
        if not self.gap:
            return self          # nothing missing: do not touch the module
        saved = self.saved = self.gen.scenario_drain_a
        sim, gap = self.sim, self.gap

        def wrapper(sc, t, *args, **kwargs):
            # DELEGATE by default; intercept only the missing branches.
            if sc in gap:
                return _soc_band_drain_a(sim, t)
            return saved(sc, t, *args, **kwargs)

        self.gen.scenario_drain_a = wrapper
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            self.gen.scenario_drain_a = self.saved
            self.saved = None
        return False


def _fractions(counts: dict) -> dict:
    n = sum(counts.values())
    if not n:
        return {m: 0.0 for m in gov_mod.MODES}
    return {m: counts.get(m, 0) / float(n) for m in gov_mod.MODES}


def _instantiate(sim, strategy_name: str, scenario: str, meta,
                 policy_file: Optional[str], strategy_kwargs: Optional[dict]):
    """Build the strategy object the simulator would use.

    The registry holds SHARED instances (``hil_plant_sim.py:5050``), so a walk
    that used one directly would inherit and leave behind run state. A strategy
    class is therefore re-instantiated where the class is reachable, and the
    registry callable is used otherwise. ``bind_scenario()`` is called when the
    strategy defines it, exactly as ``main()`` does."""
    kwargs = dict(strategy_kwargs or {})
    if strategy_name not in sim.EMS_STRATEGIES:
        raise ValueError("unknown strategy %r (known: %s)"
                         % (strategy_name, ", ".join(sorted(sim.EMS_STRATEGIES))))
    registered = sim.EMS_STRATEGIES[strategy_name]

    if isinstance(registered, sim.SdpStrategy):
        pf = policy_file or registered.policy_file
        policy = sim.SdpStrategy(
            strategy_name, pf,
            policy_dir=kwargs.pop("policy_dir", registered.policy_dir),
            require_calibrated_benchmark=kwargs.pop(
                "require_calibrated_benchmark",
                registered.require_calibrated_benchmark))
    elif isinstance(registered, sim.SocBandStrategy):
        policy = sim.SocBandStrategy(**kwargs)
        kwargs = {}
    elif isinstance(registered, sim.DpReplayStrategy):
        policy = sim.DpReplayStrategy(**kwargs)
        kwargs = {}
    else:
        # A plain callable (hold-5050, the y-* replays, the harvest stimuli):
        # these are stateless functions and are used as registered.
        if policy_file:
            raise ValueError("strategy %r takes no policy file" % strategy_name)
        policy = registered
    if kwargs:
        raise TypeError("unused strategy_kwargs: %s" % sorted(kwargs))

    binder = getattr(policy, "bind_scenario", None)
    if binder is not None:
        binder(scenario, meta)
    elif hasattr(policy, "reset"):
        policy.reset()
    return policy


def walk(strategy_name: str, scenario_name: str, *, soc0: float = 0.7,
         capacity_ah: Optional[float] = None, accounting: str = "physical",
         governor: bool = True, dv0_v: float = 0.0,
         policy_file: Optional[str] = None,
         strategy_kwargs: Optional[dict] = None,
         dt_decision: Optional[float] = None,
         eta_fc_proxy: float = H2_PROXY_ETA_FC,
         charge_admission: Optional[str] = None,
         gov_dt_s: float = 1e-3,
         conv_tau_s: float = 0.0,
         trace: bool = True) -> WalkResult:
    """Walk one strategy through the reduced model.

    ``accounting``  ``"physical"`` bills the fuel cell for the charger's own
                    draw (the objective the DP minimises); ``"simple"`` omits
                    it, matching a simple-mode simulator run's ``h2_cum_g``.
    ``governor``    ``False`` applies the commanded share directly and
                    reproduces ``gen_dp_ems_table.heuristic_walk()`` exactly.
    ``dt_decision`` the model's STAGE length in seconds. Defaults to
                    ``gen_dp_ems_table.DP_STAGE_DT_S`` (0.1 s) so a walk and a
                    DP table share one discretization. The governor runs at
                    ``gov_dt_s`` inside each stage.
    ``charge_admission``
                    which test admits a charge window.

                    ``"mask"``       ``gen_dp_ems_table.charge_mask()`` (D10) —
                                     the Run window AND the cruise test AND the
                                     single-source FC budget. A window the DP
                                     forbids can then never open, which is what
                                     a PREDICTION must guarantee.
                    ``"run_window"`` the Run window alone. This is what
                                     ``gen_dp_ems_table.heuristic_walk()``
                                     applies (:753) — it does not consult the
                                     mask at all.
                    ``None``         resolves to ``"run_window"`` when
                                     ``governor`` is False and ``"mask"``
                                     otherwise.

                    ⚠️ DEVIATION, STATED. The two tests are not equivalent, and
                    the default cannot be a single value: the ungoverned walk is
                    defined as the bit-exact ``heuristic_walk()`` regression
                    anchor, and forcing the mask onto it breaks that anchor
                    (measured: h2 moves 5.8e-5 g, SoC 1.1e-5). The governed walk
                    is a prediction and must not be able to open a window the DP
                    forbids. Resolving per mode keeps both properties; either
                    can be demanded explicitly.
    """
    sim, gen = _load()

    if scenario_name not in sim.SCENARIOS:
        raise ValueError("unknown scenario %r" % scenario_name)
    if accounting not in ("physical", "simple"):
        raise ValueError("accounting must be 'physical' or 'simple'")
    if charge_admission is None:
        charge_admission = "run_window" if not governor else "mask"
    if charge_admission not in ("mask", "run_window"):
        raise ValueError("charge_admission must be 'mask' or 'run_window'")
    meta = sim.SCENARIOS[scenario_name]

    import numpy as np

    dt = float(gen.DP_STAGE_DT_S if dt_decision is None else dt_decision)
    if dt <= 0.0:
        raise ValueError("dt_decision must be positive")
    cap_ah = sim.BATT_CAPACITY_AH if capacity_ah is None else float(capacity_ah)
    cap_as = cap_ah * 3600.0
    chg_a = sim.dp_chg_ceiling_a(meta)
    run_exit_s = float(sim.SOC_BAND_RUN_EXIT_S
                       if meta.get("ems_run_exit_s") is None
                       else meta["ems_run_exit_s"])

    duration = float(meta["duration_s"])
    n_stages = int(round(duration / dt))
    times = np.arange(n_stages + 1) * dt
    _ov = _drain_override(gen, sim, scenario_name)
    with _ov:
        v, a, p_dem, v_bus, i_total, cruise = gen.build_demand(
            scenario_name, meta, times, dt)
    chg_ok = gen.charge_mask(times, p_dem, v_bus, cruise, chg_a, run_exit_s)

    prof = meta.get("ems_v_profile")
    policy = _instantiate(sim, strategy_name, scenario_name, meta,
                          policy_file, strategy_kwargs)

    cmd_period = 1.0 / sim.PiCommander.PI_CMD_HZ
    n_sub = max(1, int(round(dt / float(gov_dt_s))))
    if governor and abs(n_sub * gov_dt_s - dt) > 1e-12:
        raise ValueError("dt_decision (%g) must be an integer multiple of "
                         "gov_dt_s (%g)" % (dt, gov_dt_s))

    g = gov_mod.GovernorModel(dt_s=gov_dt_s, dv0_v=dv0_v,
                              conv_tau_s=conv_tau_s,
                              seed_r=sim.SOC_BAND_SHARE_NOMINAL)

    res = WalkResult()
    if _ov.fired:
        res.notes.append(
            "AUX LOAD RECONCILED: this checkout's "
            "gen_dp_ems_table.scenario_drain_a() omits the SoC-band drain for "
            "%s, which hil_plant_sim.py:7417 applies. This walk supplied it "
            "(see _soc_band_drain_a); without it the modelled demand for this "
            "scenario is materially low." % (", ".join(_ov.gap),))
    seg_counts = {"discharge": {}, "charge": {}}
    soc = float(soc0)
    share = sim.SOC_BAND_SHARE_NOMINAL
    delivered = share
    charging = False
    next_cmd = 0.0
    in_window = False
    window_t0 = None

    for k in range(n_stages):
        t = float(times[k])
        if t >= next_cmd:
            # Feedback view. The first five keys are exactly what
            # heuristic_walk() supplies (gen_dp_ems_table.py:740-743); the rest
            # are keys the richer strategies read and the reduced model can
            # honestly produce.
            i_fc = delivered * float(i_total[k])
            fb = {"t": t,
                  "v_profile": (None if prof is None else sim.piecewise(prof, t)),
                  "soc": soc,
                  "I_fc": i_fc,
                  "I_batt": float(i_total[k]) - i_fc,
                  "V_bus": float(v_bus[k]),
                  "I_charge": (chg_a if charging else 0.0)}
            if meta.get("ems_run_exit_s") is not None:
                fb["ems_run_exit_s"] = meta["ems_run_exit_s"]
            out = policy(t, fb)
            share = float(out["power_share_setpoint"])
            charging = float(out.get("charge_goal", 0.0)) > 0.0
            next_cmd = t + cmd_period

        # The strategy's charge intent is honoured only where this model's own
        # charge mask admits it (D10). `chg_ok` already carries the Run-window
        # term (gen_dp_ems_table.charge_mask() ANDs `in_run` in), plus the
        # cruise test and the single-source FC budget, so a window the DP forbids
        # can never open here — the policy's own admission test is causal and
        # current-based and can differ at a window edge.
        if charge_admission == "mask":
            charge_now = bool(charging and chg_ok[k])
        else:
            charge_now = bool(charging
                              and sim.EMS_RUN_ENTRY_S <= t < run_exit_s)

        if governor:
            # EXTERNAL SWITCH OWNERS, re-asserted EVERY tick exactly as the
            # firmware does. doState2() writes FC_BUS_ENABLE HIGH on every Run
            # tick, gated on !shareSpCutFC (.ino:5869), and chargingControl()
            # writes BT_BUS_ENABLE HIGH in all non-FC-charge paths, gated on
            # !shareSpCutBT (.ino:10792, :10822, :10853). Without the
            # re-assertion a share cut would stand for the rest of the walk,
            # which is not what the board does. The setpoint latch is the one
            # claim these re-asserts respect; an r-based `shareIso*` claim is
            # NOT respected by them, and the resulting orphan is exactly what
            # the model's S1 self-heal drops.
            #
            # FC-CHARGE WINDOW: chargingControl() holds BT_BUS LOW while the
            # fuel-cell path feeds the charger, so the share loop's measurement
            # is topology-pinned and its ratio winds onto DROOP_R_MIN
            # (CLAUDE.md, 2026-09-01c).
            acc = 0.0
            seg = "charge" if charge_now else "discharge"
            for j in range(n_sub):
                ts = t + j * gov_dt_s
                i_fc = delivered * float(i_total[k])
                sw_fc = True if not g.state.sp_cut_fc else g.state.sw_fc
                if charge_now:
                    sw_bt = False
                else:
                    sw_bt = True if not g.state.sp_cut_bt else g.state.sw_bt
                o = g.step(share, i_fc, float(i_total[k]) - i_fc,
                           sw_fc, sw_bt, ts,
                           charge_path_owns_bt=charge_now)
                delivered = g.delivered_share(o.r_applied, float(i_total[k]),
                                              o.fc_bus_req, o.bt_bus_req)
                acc += delivered
                seg_counts[seg][o.mode] = seg_counts[seg].get(o.mode, 0) + 1
            stage_share = acc / n_sub
            r_now = g.state.r_prev
        else:
            stage_share = share
            delivered = share
            r_now = share

        if charge_now:
            if not in_window:
                in_window, window_t0 = True, t
            soc, dh2, dh2p = gen.step_charge(soc, float(p_dem[k]),
                                             float(v_bus[k]), chg_a, dt, cap_as)
            p_fc_bus = (float(p_dem[k]) + float(v_bus[k]) * chg_a
                        if accounting == "physical" else float(p_dem[k]))
        else:
            if in_window:
                res.charge_windows.append((window_t0, t))
                in_window, window_t0 = False, None
            soc, dh2, dh2p = gen.step_discharge(soc, stage_share,
                                                float(p_dem[k]),
                                                float(v_bus[k]), dt, cap_as)
            p_fc_bus = stage_share * float(p_dem[k])

        res.h2_g += dh2
        res.h2_plant_g += dh2p
        res.h2_proxy_g += h2_proxy_gps(p_fc_bus / sim.ETA_BOOST,
                                       eta_fc_proxy) * dt
        if trace:
            res.t.append(t)
            res.share_cmd.append(share)
            res.share_delivered.append(stage_share)
            res.r_applied.append(r_now)

    if in_window:
        res.charge_windows.append((window_t0, float(times[n_stages])))

    res.soc_final = soc
    res.delta_soc = soc - float(soc0)
    if governor:
        res.mode_fractions = g.mode_fractions()
        res.mode_fractions_by_segment = {
            seg: _fractions(c) for seg, c in seg_counts.items() if c}
        hold = res.mode_fractions.get(gov_mod.MODE_OPEN_HOLD, 0.0)
        if hold > 0.0:
            res.notes.append(
                "the share loop was in OPEN-LOOP HOLD for %.1f %% of ticks; the "
                "commanded setpoint was not acted on there (the delivered split "
                "is whatever stood when the load fell below 0.55 A)" % (100.0 * hold))
        if g.state.refused_load or g.state.refused_blank:
            res.notes.append(
                "cut refusals: %d tick(s) on the load guard, %d on survivor "
                "blanking" % (g.state.refused_load, g.state.refused_blank))
    else:
        res.notes.append(
            "GOVERNOR DISABLED: the commanded share was applied directly. This "
            "reproduces gen_dp_ems_table.heuristic_walk()'s model and is a "
            "regression anchor, NOT a prediction of board behaviour.")
    res.notes.append("charge admission: %s" % charge_admission)
    return res


def main(argv=None):      # pragma: no cover - operator convenience
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--soc0", type=float, default=0.7)
    ap.add_argument("--policy-file", default=None)
    ap.add_argument("--no-governor", action="store_true")
    ap.add_argument("--dv0", type=float, default=0.0)
    ap.add_argument("--accounting", choices=("physical", "simple"),
                    default="physical")
    ap.add_argument("--dt", type=float, default=None,
                    help="stage length in s (default: the DP's 0.1 s)")
    ap.add_argument("--eta-fc", type=float, default=H2_PROXY_ETA_FC)
    ap.add_argument("--charge-admission", choices=("mask", "run_window"),
                    default=None)
    ap.add_argument("--csv", default=None, help="write the per-stage trace here")
    a = ap.parse_args(argv)

    r = walk(a.strategy, a.scenario, soc0=a.soc0, accounting=a.accounting,
             governor=not a.no_governor, dv0_v=a.dv0,
             policy_file=a.policy_file, dt_decision=a.dt,
             eta_fc_proxy=a.eta_fc, charge_admission=a.charge_admission)
    print("strategy %s on scenario %s" % (a.strategy, a.scenario))
    print(r.summary())
    if a.csv:
        import csv as _csv
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh)
            w.writerow(["t", "share_cmd", "share_delivered", "r_applied"])
            for row in zip(r.t, r.share_cmd, r.share_delivered, r.r_applied):
                w.writerow(["%.6f" % row[0]] + ["%.9f" % x for x in row[1:]])
        print("wrote %s" % a.csv)
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())

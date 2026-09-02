#!/usr/bin/env python3
"""PLANT-R1-N4 probe: is the reported I_fc / I_batt an honest INA253 proxy?

Finding under test (docs/reviews/hil-plant/ledger.md, PLANT-R1-N4):

    "FC_BUS.i as an INA proxy may under-report a bus load step by half at one
     operating point."

The hi-fi engine reports `self.switches["FC_BUS"].i` as the firmware-visible
`I_fc` sensor (hil_electrical.py ~1915 and `_rails()`).  On the board the
INA253A1 sits between the TPS61288 output and the RT1987 ideal-diode input
(schematic sheets 1-2: VOUT-FC -> INA253 IS+ / IS- -> VBUS-FC -> RT1987 VIN),
so the model's sense point and the hardware's sense point are the SAME branch.
The boost output bulk capacitance sits UPSTREAM of the shunt in both, and the
VBUS bulk capacitance sits DOWNSTREAM of it in both.

This probe measures, per electrical substep, across a bus load step:

  * the boost's own output current   (Boost.i_out, upstream of C_BOOST_OUT)
  * the true switch branch current   (the INA node current, solved voltages)
  * the reported sensor value        (`Rt1987.i`, what the firmware receives)
  * every current into the VBUS node (both source links, aux, MOT_PWR, C_VBUS)

and reports the reported/true step ratio at the first substep, at the first
1 kHz firmware sample, and settled, plus the node charge balance.

Run:
    C:/Users/ricky/miniforge3/python.exe tools/probes/probe_n4_ina_proxy.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import hil_electrical as he  # noqa: E402

SW_ALL = (he.SW_FC_BUS | he.SW_BT_BUS | he.SW_MOT_PWR | he.SW_BT_SEQ)
AUX_ALL = (he.AUX_FC_REG | he.AUX_BT_REG)
N_SUB = 20                      # pinned: 50 us substeps at a 1 ms tick
DT = 1e-3
# FC_BUS / BT_BUS carry the INA253 shunt as r_series (R_SHUNT, 2 mOhm).
R_LINK_BUS = he.RT_R_ON + he.R_SHUNT
R_LINK_MOT = he.RT_R_ON


SW_FC_ONLY = (he.SW_FC_BUS | he.SW_MOT_PWR | he.SW_BT_SEQ)


def _act(i_motor_a, code=0.5, sw=SW_ALL, aux=AUX_ALL):
    return {"sw": sw, "aux": aux, "i_motor_a": i_motor_a,
            "code_fc": code, "code_bt": code, "i_charge_a": 0.0}


class Recorder(object):
    """Wraps ElectricalSim._substep and records the per-substep node picture."""

    def __init__(self, sim):
        self.sim = sim
        self.rows = []
        self.armed = False
        self._orig = sim._substep
        sim._substep = self._wrapped

    def _wrapped(self, h, sw, aux, i_motor, code_fc, code_bt, i_charge):
        v_prev = list(self.sim.v)
        self._orig(h, sw, aux, i_motor, code_fc, code_bt, i_charge)
        if not self.armed:
            return
        e = self.sim
        v = e.v
        row = {
            "t": e.t,
            "h": h,
            "i_motor_cmd": i_motor,
            # boost's own output current (source side of C_BOOST_OUT)
            "i_out_fc": e.boost_fc.i_out,
            "i_out_bt": e.boost_bt.i_out,
            # true branch current at the INA shunt, from the SOLVED voltages
            "i_ina_fc": self._branch(v, he.N_OFC, he.N_BUS, R_LINK_BUS),
            "i_ina_bt": self._branch(v, he.N_OBT, he.N_BUS, R_LINK_BUS),
            # what the firmware is handed this substep
            "i_rep_fc": e.switches["FC_BUS"].i,
            "i_rep_bt": e.switches["BT_BUS"].i,
            # bus-node currents
            "i_mot_pwr": self._branch(v, he.N_BUS, he.N_MOT, R_LINK_MOT),
            "i_aux": e.i_aux,
            "i_c_bus": he.C_VBUS * (v[he.N_BUS] - v_prev[he.N_BUS]) / h,
            "i_c_ofc": he.C_BOOST_OUT_FC * (v[he.N_OFC] - v_prev[he.N_OFC]) / h,
            "i_c_obt": he.C_BOOST_OUT_BT * (v[he.N_OBT] - v_prev[he.N_OBT]) / h,
            "i_bleed_bus": v[he.N_BUS] * he.node_bleed_conductances()[he.N_BUS],
            "v_ofc": v[he.N_OFC],
            "v_obt": v[he.N_OBT],
            "v_bus": v[he.N_BUS],
            "v_mot": v[he.N_MOT],
        }
        self.rows.append(row)

    @staticmethod
    def _branch(v, n_in, n_out, r):
        return max(0.0, (v[n_in] - v[n_out] - he.RT_V_FWD) / r)


def run_case(i_base, i_step, ramp_ms, settle_ticks=400, window_ticks=60,
             sw=SW_ALL, aux=AUX_ALL):
    """Bring up, settle at i_base, then step to i_base+i_step; return rows."""
    e = he.ElectricalSim(trace_config="short", noise=None)
    e._n_sub = N_SUB
    rec = Recorder(e)
    # Bring-up and settle at the base operating point.
    for _ in range(settle_ticks):
        e._n_sub = N_SUB
        e.step(DT, _act(i_base, sw=sw, aux=aux))
    rec.armed = True
    # Two pre-step ticks so the baseline is inside the record.
    for _ in range(2):
        e._n_sub = N_SUB
        e.step(DT, _act(i_base, sw=sw, aux=aux))
    n_pre = len(rec.rows)
    # The step itself.
    n_ramp = max(1, int(ramp_ms))
    for k in range(window_ticks):
        if ramp_ms <= 0:
            i_now = i_base + i_step
        else:
            frac = min(1.0, (k + 1) / float(n_ramp))
            i_now = i_base + i_step * frac
        e._n_sub = N_SUB
        e.step(DT, _act(i_now, sw=sw, aux=aux))
    return e, rec.rows, n_pre


def analyse(rows, n_pre, label):
    """Ratios of the reported / true / boost-output steps."""
    base = rows[n_pre - 1]
    # baseline levels (averaged over the two pre-step ticks for stability)
    pre = rows[:n_pre]
    b_out = sum(r["i_out_fc"] for r in pre) / len(pre)
    b_ina = sum(r["i_ina_fc"] for r in pre) / len(pre)
    b_rep = sum(r["i_rep_fc"] for r in pre) / len(pre)

    first_sub = rows[n_pre]
    # `Rt1987.i` is refreshed at the TOP of the next substep, so the reported
    # sensor value is one substep (50 us) behind the solved branch current.
    # sub2 is therefore the first substep at which the report can have moved.
    second_sub = rows[n_pre + 1]
    first_tick = rows[n_pre + N_SUB - 1]          # end of the first 1 ms tick
    settled = rows[-1]

    def d(row, key, base_v):
        return row[key] - base_v

    out = {
        "label": label,
        "base_i_out": b_out, "base_i_ina": b_ina, "base_i_rep": b_rep,
        "d_out_sub1": d(first_sub, "i_out_fc", b_out),
        "d_ina_sub1": d(first_sub, "i_ina_fc", b_ina),
        "d_rep_sub1": d(first_sub, "i_rep_fc", b_rep),
        "d_out_sub2": d(second_sub, "i_out_fc", b_out),
        "d_ina_sub2": d(second_sub, "i_ina_fc", b_ina),
        "d_rep_sub2": d(second_sub, "i_rep_fc", b_rep),
        "d_out_tick1": d(first_tick, "i_out_fc", b_out),
        "d_ina_tick1": d(first_tick, "i_ina_fc", b_ina),
        "d_rep_tick1": d(first_tick, "i_rep_fc", b_rep),
        "d_out_set": d(settled, "i_out_fc", b_out),
        "d_ina_set": d(settled, "i_ina_fc", b_ina),
        "d_rep_set": d(settled, "i_rep_fc", b_rep),
    }
    for tag in ("sub1", "sub2", "tick1", "set"):
        do = out["d_out_" + tag]
        out["ratio_rep_out_" + tag] = (out["d_rep_" + tag] / do) if abs(do) > 1e-9 else float("nan")
        out["ratio_rep_ina_" + tag] = ((out["d_rep_" + tag] / out["d_ina_" + tag])
                                       if abs(out["d_ina_" + tag]) > 1e-9 else float("nan"))
    # Node charge balance on the worst substep of the transient (bus node).
    worst = max(rows[n_pre:n_pre + N_SUB],
                key=lambda r: abs(r["i_c_bus"]))
    resid = (worst["i_ina_fc"] + worst["i_ina_bt"]
             - worst["i_mot_pwr"] - worst["i_aux"]
             - worst["i_c_bus"] - worst["i_bleed_bus"])
    out["bus_resid_a"] = resid
    out["bus_i_c_peak"] = worst["i_c_bus"]
    # Boost-output node balance on the same substep index.
    idx = rows.index(worst)
    w = rows[idx]
    out["ofc_resid_a"] = (w["i_out_fc"] - w["i_ina_fc"] - w["i_c_ofc"]
                          - w["v_ofc"] * he.node_bleed_conductances()[he.N_OFC])
    # Time for the reported value to reach 90 % of its settled step.
    target = 0.9 * out["d_rep_set"]
    t0 = rows[n_pre]["t"]
    out["t90_ms"] = float("nan")
    for r in rows[n_pre:]:
        if abs(r["i_rep_fc"] - b_rep) >= abs(target):
            out["t90_ms"] = (r["t"] - t0) * 1e3
            break
    return out


def share_of_bus_step(rows, n_pre, i_step):
    """Settled FC-channel reported step, as a fraction of the WHOLE bus step."""
    pre = rows[:n_pre]
    b_fc = sum(r["i_rep_fc"] for r in pre) / len(pre)
    b_bt = sum(r["i_rep_bt"] for r in pre) / len(pre)
    last = rows[-1]
    return ((last["i_rep_fc"] - b_fc) / i_step,
            (last["i_rep_bt"] - b_bt) / i_step)


def main():
    cases = []
    shares = []
    for i_base, tag in ((0.30, "low"), (0.60, "mid"), (1.00, "high")):
        for ramp_ms, shape in ((0, "1-tick step"), (10, "10 ms ramp")):
            e, rows, n_pre = run_case(i_base, 0.5, ramp_ms)
            res = analyse(rows, n_pre, "%s / %s" % (tag, shape))
            res["i_base"] = i_base
            res["shape"] = shape
            cases.append(res)
            shares.append(("%s / %s" % (tag, shape),)
                          + share_of_bus_step(rows, n_pre, 0.5))
    # Control: one source only.  If the "half" reading were a sense-point defect
    # it would survive here; if it is the two-source share split it must vanish.
    e, rows, n_pre = run_case(0.60, 0.5, 0, sw=SW_FC_ONLY, aux=he.AUX_FC_REG)
    solo = analyse(rows, n_pre, "mid / FC only / 1-tick")
    solo["i_base"] = 0.60
    solo["shape"] = "1-tick step"
    cases.append(solo)
    shares.append(("mid / FC only / 1-tick",) + share_of_bus_step(rows, n_pre, 0.5))

    hdr = ("op point                | I_fc base | d_out_1sub d_INA_1sub d_rep_2sub "
           "| rep/out 2sub | INA/out 1sub | rep/out 1tick | rep/INA 1tick "
           "| rep/out settled | t90 ms")
    print(hdr)
    print("-" * len(hdr))
    for c in cases:
        ina_out_sub1 = (c["d_ina_sub1"] / c["d_out_sub1"]
                        if abs(c["d_out_sub1"]) > 1e-9 else float("nan"))
        print("%-23s | %9.5f | %10.6f %10.6f %10.6f | %12.4f | %12.4f | %13.4f "
              "| %13.4f | %15.4f | %6.3f"
              % (c["label"], c["base_i_rep"],
                 c["d_out_sub1"], c["d_ina_sub1"], c["d_rep_sub2"],
                 c["ratio_rep_out_sub2"], ina_out_sub1,
                 c["ratio_rep_out_tick1"], c["ratio_rep_ina_tick1"],
                 c["ratio_rep_out_set"], c["t90_ms"]))
    print()
    print("settled channel step as a fraction of the WHOLE 0.5 A bus step:")
    for label, f_fc, f_bt in shares:
        print("  %-23s FC %.4f   BT %.4f   sum %.4f" % (label, f_fc, f_bt, f_fc + f_bt))
    print()
    print("charge balance (worst transient substep):")
    for c in cases:
        print("  %-23s bus node residual %+.3e A (C_VBUS peak %+.4f A); "
              "boost-out node residual %+.3e A"
              % (c["label"], c["bus_resid_a"], c["bus_i_c_peak"], c["ofc_resid_a"]))


if __name__ == "__main__":
    main()

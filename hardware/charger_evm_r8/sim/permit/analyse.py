"""Post-processing of the permit transients: safe-state checks, glitch widths, logic levels.

Receiver thresholds follow the model library (SCES201N ROC): VIL/VIH of an LVC input as a function of the
receiving device's VCC; TLV3012B supply minimum 1.65 V; BQ25798 /CE VIL 0.4 V / VIH 1.3 V and ILIM_HIZ VIL 0.75 V /
VIH 1.0 V (SLUSDV2C, as quoted in design doc B.6 and REVIEW section 5); RT1987 EN VEN_F min 0.6 V / VEN_R max 1.4 V
(RT1987_DS-00 p.7, as quoted in REVIEW LOG-1).
"""
import numpy as np

VIL_CE, VIH_CE = 0.4, 1.3
VIL_ILIM, VIH_ILIM = 0.75, 1.0
VEN_F_MIN, VEN_R_MAX = 0.6, 1.4
VCC_MIN = 1.65
REGN_ON = 4.0


def vil(v):
    v = np.asarray(v, float)
    return np.where(v < 1.95, 0.35 * v, np.where(v < 2.3, 0.6825 + (v - 1.95) * 0.05,
                    np.where(v < 2.7, 0.7, np.where(v < 3.0, 0.7 + (v - 2.7) / 3.0, 0.8))))


def vih(v):
    v = np.asarray(v, float)
    return np.where(v < 1.95, 0.65 * v, np.where(v < 2.3, 1.2675 + (v - 1.95) * 1.2357,
                    np.where(v < 2.7, 1.7, np.where(v < 3.0, 1.7 + (v - 2.7), 2.0))))


def runs(t, mask):
    """Contiguous True runs of mask -> list of (t_start, t_end)."""
    out = []
    if mask.size == 0:
        return out
    m = mask.astype(np.int8)
    d = np.diff(np.concatenate(([0], m, [0])))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0] - 1
    for s, e in zip(starts, ends):
        t0 = t[s - 1] if s > 0 else t[s]       # extend to the previous sample (conservative width)
        t1 = t[e + 1] if e + 1 < len(t) else t[e]
        out.append((float(t0), float(t1)))
    return out


def episode_stats(t, mask, window):
    """Unsafe episodes inside window. An episode already in progress at the window start is the transition out of a
    legitimately enabled state (reported as 'trans'); every episode that starts later is a new event."""
    sel = (t >= window[0]) & (t <= window[1])
    r = runs(t[sel], mask[sel])
    trans = 0.0
    if r and r[0][0] <= t[sel][0] + 1e-12:
        trans = r[0][1] - r[0][0]
        r = r[1:]
    if not r:
        return dict(n=0, max_w=0.0, total=0.0, first=np.nan, trans=trans)
    w = [b - a for a, b in r]
    return dict(n=len(r), max_w=max(w), total=sum(w), first=r[0][0], trans=trans)


def logic(v, vcc):
    """1 if v > VIH(vcc), 0 if v < VIL(vcc), 0.5 otherwise (undefined band)."""
    v = np.asarray(v, float)
    return np.where(v > vih(vcc), 1.0, np.where(v < vil(vcc), 0.0, 0.5))


def checks(r, window, expect, allow_trans=100e-6):
    """Evaluate the enable outputs on result r inside window = (t0, t1).

    expect: dict of output -> 'safe' (must stay in the safe state in the window) or 'free' (report only).
    allow_trans: an output that was legitimately enabled at the window start must reach its safe state within
    this time (default 100 us), otherwise it is reported as '(stuck)'.
    Returns a flat dict of metrics.
    """
    t = r["time"]
    g = lambda k: r[k]
    regn = g("e_regn")
    e3 = g("e_3v3")
    c3 = g("c_3v3")
    powered = regn > REGN_ON
    out = {}
    # /CE at the BQ25798 pin (only meaningful with REGN present)
    ce = g("e_nce_drv")
    out.update(_m("CE_pin", t, powered & (ce < VIH_CE), powered & (ce < VIL_CE), window))
    # CE_DRV logic at U201 1A
    cein = g("e_n_cein")
    out.update(_m("CE_logic", t, cein > vil(e3), cein > vih(e3), window))
    # ILIM_HIZ at the BQ25798 pin
    il = g("e_ilim_hold")
    out.update(_m("ILIM_pin", t, powered & (il > VIL_ILIM), powered & (il > VIH_ILIM), window))
    # release logic at the EIB inputs: both channels must read HIGH to release (Q201 off AND Q203 on)
    ra, rb = g("e_n_rain"), g("e_n_rbin")
    rmin = np.minimum(ra, rb)
    out.update(_m("REL_logic", t, rmin > vil(e3), rmin > vih(e3), window))
    # CR-side ILIM_REL at the U110B output, judged against the CR rail
    cr = g("c_ilim_rel")
    out.update(_m("ILIM_REL_cr", t, cr > vil(c3), cr > vih(c3), window))
    # FC_CHARGE EN net (RT1987 D-BC-FC)
    en = g("m_t5")
    out.update(_m("FCEN", t, en > VEN_F_MIN, en > VEN_R_MAX, window))
    # RFC_OFF HIGH (regen clamp) while the FC path may conduct
    rf = g("e_n_rfin")
    out.update(_m("RFC_vs_FCEN", t, (rf > vil(e3)) & (en > VEN_F_MIN), (rf > vih(e3)) & (en > VEN_R_MAX), window))
    sel = (t >= window[0]) & (t <= window[1])
    out["c3v3_min"] = float(np.min(c3[sel]))
    out["e3v3_min"] = float(np.min(e3[sel]))
    out["c3v3_end"] = float(c3[-1])
    out["e3v3_end"] = float(e3[-1])
    out["t_c3v3_below_1v65"] = float(np.sum(np.diff(t[sel])[(c3[sel] < VCC_MIN)[:-1]])) if sel.sum() > 1 else 0.0
    for k in ("c_h1", "c_uvb", "c_fccn", "c_fcc_on", "c_h1u", "c_fccp", "c_qf", "c_gate", "c_ilim_rel",
              "c_ce_drv", "c_rfc_off"):
        out["end_" + k[2:]] = float(logic(g(k)[-1:], c3[-1:])[0])
    out["end_nCE_V"] = float(ce[-1])
    out["end_ILIM_V"] = float(il[-1])
    out["end_FCEN_V"] = float(en[-1])
    # driver and rail currents at the end of the run (resistor values from cr.net: R130/R131A 100, R131B/R132 4.99k,
    # R175 68 ohm)
    for nm, a, b, rv in (("I_R130_mA", "c_ce_drv", "c_ce_drv_j", 100.0), ("I_R131A_mA", "c_ilim_rel", "c_ilim_rel_a", 100.0),
                         ("I_R131B_mA", "c_ilim_rel", "c_ilim_rel_b", 4990.0), ("I_R132_mA", "c_rfc_off", "c_rfc_off_j", 4990.0),
                         ("I_R175_mA", "c_t6_3v3", "c_3v3", 68.0)):
        out[nm] = float((g(a)[-1] - g(b)[-1]) / rv * 1e3)
    out["CE_pin_min"] = float(np.min(np.where(powered[sel], ce[sel], 9.9))) if np.any(powered[sel]) else np.nan
    out["ILIM_pin_max"] = float(np.max(np.where(powered[sel], il[sel], 0.0)))
    out["FCEN_max"] = float(np.max(en[sel]))
    viol = []
    for k, mode in expect.items():
        if mode != "safe":
            continue
        if out[k + "_poss_n"] > 0:
            viol.append(k)
        elif out[k + "_trans"] > allow_trans:
            viol.append(k + "(stuck)")
    out["violations"] = ";".join(viol)
    out["verdict"] = "SAFE" if not viol else "UNSAFE:" + ",".join(viol)
    return out


def _m(name, t, poss, cert, window):
    a = episode_stats(t, poss, window)
    b = episode_stats(t, cert, window)
    return {name + "_trans": a["trans"],
            name + "_poss_n": a["n"], name + "_poss_maxw": a["max_w"], name + "_poss_first": a["first"],
            name + "_cert_n": b["n"], name + "_cert_maxw": b["max_w"], name + "_cert_first": b["first"]}

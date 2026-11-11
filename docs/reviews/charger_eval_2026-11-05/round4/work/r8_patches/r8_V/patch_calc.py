import sys
P = r"C:/Life Ops/School/Thesis/DC-Balancer-round4/docs/reviews/charger_eval_2026-11-05/round4/calc/r7_calc.py"
t = open(P, encoding="ascii").read()


def rep(old, new, n=1):
    global t
    c = t.count(old)
    if c != n:
        sys.exit("count %d != %d for %r" % (c, n, old[:80]))
    t = t.replace(old, new)


rep('''  the T1 step-8 increment, the T-C-05c pad pull-up current).
"""''', '''  the T1 step-8 increment, the T-C-05c pad pull-up current).

Revision 7 (r8 verification round): H.23(y) is added after H.23(x). Every line printed by revisions 4-6 keeps its position
  and its numbers; three lines change wording only: the H.23(p) model line states that the helix factor is evaluated at OD
  max (as the code always did), and the H.23(q) input, r7 and worst-case lines and its summary row label IQ(ON) 1.38 mA as
  the TYPICAL value (tps2663.pdf sec 6.5 gives no minimum). H.23(y): (1) the F17-F15 node level with FLT asserted and
  U108 HIGH; (2) the T3 FIFO case and the FR-07 queue-priority bound; (3) the W1/W2 lead current when the FET opens and
  the helix factor at OD min; (4) the B1R lateral support of the trunk; (5) W5 / trunk figures at the T-F-12 points;
  (6) the C205/TP27 sweep over the E1 build range 70.8-90 mm; (7) the T1 increment with the step-8c pre-edge read.
"""''')

rep('''RISER_X = (24.30, 27.30)       # mm, riser block width 3.0 mm centred on the trunk x 25.80 (toe clear of the W2 exclusion)''',
    '''RISER_X = (24.30, 27.30)       # mm, candidate block width 3.0 mm centred on the trunk x 25.80, used only when the toe
#                                lies clear of the W2 exclusion; the chosen 65 deg toe lies inside it, so the built B1R is
#                                the RISER_W_NARROW block below (revision 7 comment correction)''')

rep('''IQ_ON = (1.38e-3, 1.70e-3)   # A, tps2663.pdf sec 6.5 IQ(ON) (enabled, 4.5 V < V(IN_SYS) < 60 V)''',
    '''IQ_ON = (1.38e-3, 1.70e-3)   # A, tps2663.pdf sec 6.5 IQ(ON) TYPICAL 1.38 mA / MAXIMUM 1.70 mA (enabled,
#                              4.5 V < V(IN_SYS) < 60 V); no minimum is specified (revision 7 label correction)''')

rep('''UVLO/OVP string %.1f kOhm (parallel %.1f kOhm), eFuse IN_SYS current IQ(ON) %.2f-%.2f mA (tps2663.pdf sec 6.5, "''',
    '''UVLO/OVP string %.1f kOhm (parallel %.1f kOhm), eFuse IN_SYS current IQ(ON) %.2f mA typ / %.2f mA max, no minimum (tps2663.pdf sec 6.5, "''')
rep('''IN side only, IQ(ON) above "''', '''IN side only, IQ(ON) typ above "''')
rep('''"with IQ(ON) min down to 4.5 V then RC''', '''"with IQ(ON) typ down to 4.5 V then RC''')
rep('''"eFuse current >= %.3f mA (from %.2f V, %.1f uF) against IQ(ON) min %.2f mA''',
    '''"eFuse current >= %.3f mA (from %.2f V, %.1f uF) against IQ(ON) typ %.2f mA (no minimum specified)''')
rep('''"worst %.3f s with the eFuse enabled (margin %.3f s); needs IN-side current >= %.3f mA from %.2f V (IQ(ON) min "''',
    '''"worst %.3f s with the eFuse enabled (margin %.3f s); needs IN-side current >= %.3f mA from %.2f V (IQ(ON) typ "''')

rep('''no internal inductance, divided by the helix factor k = sqrt(1 + (pi s / p)^2) "
        "at the tightest pitch p = %.0f mm''',
    '''no internal inductance, divided by the helix factor k = sqrt(1 + (pi OD_max / p)^2) "
        "evaluated at OD max (conservative: a larger k gives a smaller L') and the tightest pitch p = %.0f mm''')

rep('''    EXTRA["st"] = dict(z_top=z_top, m=m, y0=y0, za=za)''',
    '''    EXTRA["st"] = dict(z_top=z_top, m=m, y0=y0, za=za)
    EXTRA["t"] = dict(ov_rows=ov_rows, first_ride=first_ride, rx=rx, h=h_new, tb=tb, z_top=z_top)   # revision 7''')

rep('''    sec_x()       # revision 6 (r8 integration): H.23(x)''',
    '''    sec_x()       # revision 6 (r8 integration): H.23(x)
    sec_y()       # revision 7 (r8 verification round): H.23(y)''')

SEC_Y = r'''

# ======================================================================================================================
# Revision 7 (r8 verification round): H.23(y). The sections above print the same lines (wording-only changes in H.23(p)
# and H.23(q), see the module docstring).
# ======================================================================================================================
VIH_FRAC = 0.70          # x OVDD, i.MX RT1062 GPIO VIH ASSUMPTION; TODO(verify: IMXRT1060CEC)


def in_spike_lead_off(v0, cs, lin, cin, rin=0.045, ron=0.031, cout=1.0e-6, lout=0.15e-6, dt=1e-9, tend=12e-6):
    """The in_spike model unchanged; returns the OUT-lead (W1/W2) current at the instant the FET opens."""
    vs, vin, vout = v0, v0, v0
    i_in, i_out = 0.0, 0.0
    t, t_cross, on, i_lead_off = 0.0, None, True, None
    while t < tend and i_lead_off is None:
        di_in = (vs - i_in * rin - vin) / lin
        i_in += di_in * dt
        i_fet = (vin - vout) / ron if on else 0.0
        i_out += vout / lout * dt
        vs -= i_in / cs * dt
        vin += (i_in - i_fet) / cin * dt
        vout += (i_fet - i_out) / cout * dt
        if on and t_cross is None and i_fet > 45.0:
            t_cross = t
        if on and t_cross is not None and t >= t_cross + 1e-6:
            i_lead_off = (i_out, t, vout)
        t += dt
    return i_lead_off


def sec_y():
    head("H.23(y) r8 verification-round figures (r8, calc revision 7; CHG-R1-01, -02, -D04, -D03, -W01, -07, -04)")
    # (1) F17-F15 node, FLT asserted, U108 H2C HIGH
    def node(v, r127, rpu, rflt_path):
        g1, g2, g3 = 1 / r127, 1 / rpu, 1 / rflt_path
        return v * (g1 + g2) / (g1 + g2 + g3)
    n_min = node(V_IO_RNG[0], R127_R[2], R_PU35[2], R106S[0] + R_FLT[0])
    n_max = node(V_IO_RNG[2], R127_R[0], R_PU35[0], R106S[2] + R_FLT[2])
    n_r7 = node(V_IO_RNG[2], R127_R[0], R_PU35[0], R_FLT[2])
    vil = (VIL_FRAC * V_IO_RNG[0], VIL_FRAC * V_IO_RNG[2])
    vih = (VIH_FRAC * V_IO_RNG[0], VIH_FRAC * V_IO_RNG[2])
    out("  (1) bridge F17-F15 with FLT asserted and U108 H2C HIGH (CHG-R1-01): the node is U108 -> R127 -> node -> R106s + "
        "R(FLT) -> GND with the pin-35 pull-up to 3V3 (U108 output resistance 0 ohm ASSUMPTION): %.2f V minimum (3V3 %.3f V, "
        "R127 %.0f ohm, pull-up %.0f kOhm, R106s %.0f + R(FLT) %.0f ohm) to %.2f V maximum (3V3 %.3f V, R127 %.0f ohm, "
        "pull-up %.0f kOhm, R106s %.0f + R(FLT) %.0f ohm), inside the undefined band between VIL %.2f-%.2f V and VIH "
        "%.2f-%.2f V (VIL %.2f / VIH %.2f x 3V3, ASSUMPTIONs): pins 35 and 16 can read either level. r7 (no R106s): <= "
        "%.3f V, a defined LOW. With FLT released both pins read the U108 level."
        % (n_min, V_IO_RNG[0], R127_R[2], R_PU35[2] / 1e3, R106S[0], R_FLT[0], n_max, V_IO_RNG[2], R127_R[0],
           R_PU35[0] / 1e3, R106S[2], R_FLT[2], vil[0], vil[1], vih[0], vih[1], VIL_FRAC, VIH_FRAC, n_r7))
    # (2) T3 FIFO case
    fifo = {}
    for f in (100e3, 400e3):
        tb, cap = I2C_TBUF[f], I2C_CAP[f]
        w2, w3, r2 = i2c_bits_write(2) / f, i2c_bits_write(3) / f, i2c_bits_read(2) / f
        t_fifo = cap + tb + r2 + tb + r2 + tb + w2 + tb + w3
        inflight = max(w3, 10 / f)
        fifo[f] = (t_fifo, inflight, cap)
    out("  (2) T3 raise behind one FR-41(iii) ramp group (CHG-R1-02): a ramp write in flight (the FR-07 cap term) and its "
        "two FR-46 field reads R(REG01:02), R(REG06:07) queued ahead of the raise, FIFO order: edge to write complete %.3f ms "
        "at 100 kHz (MISSES the 1.5 ms FR-07 deadline by %.3f ms), %.3f ms at 400 kHz. With the FR-07 r8 queue-priority "
        "rule (a posted raise is serviced before every queued transaction that has not started; an in-flight read aborts at "
        "the next byte boundary; an in-flight write completes), the in-flight term is max(W(REG03-05), one byte + STOP) = "
        "%.3f ms at 100 kHz / %.3f ms at 400 kHz, inside the %.2f / %.2f ms cap term of H.23(o), so the published 1.359 / "
        "0.565 ms hold only with that rule."
        % (fifo[100e3][0] * 1e3, (fifo[100e3][0] - FR07_DEADLINE) * 1e3, fifo[400e3][0] * 1e3, fifo[100e3][1] * 1e3,
           fifo[400e3][1] * 1e3, fifo[100e3][2] * 1e3, fifo[400e3][2] * 1e3))
    # (3) W1/W2 lead current at FET turn-off; helix factor at OD min
    rec = EXTRA["p"]
    a_hi = 5 * awg_d(32) / 2
    k_max = math.sqrt(1 + (math.pi * rec["rec_od"][1] / TWIST_P[0]) ** 2)
    k_min = math.sqrt(1 + (math.pi * rec["rec_od"][0] / TWIST_P[0]) ** 2)
    l_odmin = lprime(rec["rec_od"][0], a_hi) / k_min
    lo = in_spike_lead_off(22.0, 20e-6, 150e-9, 3.4e-6, lout=rec["lmin"] * W12_BUILD[0] / 1000.0)
    sp_odmin = spike_worst(l_odmin * W12_BUILD[0] / 1000.0)
    out("  (3) W1/W2 (CHG-R1-D04): at 290 mm and the L' minimum (V0 22 V, C_S 20 uF, L_IN 150 nH) the W1/W2 lead carries "
        "%.1f A when the FET opens (t = %.3f us, OUT %.2f V, unclamped model); the lead peak is the H.23(p) 130 A. Helix factor "
        "at OD max (the H.23(p) basis) %.4f, at OD min %.4f: L' minimum %.4f uH/m and IN peak %.2f V at 290 mm with k at OD "
        "min (H.23(p) %.4f uH/m, %.2f V; the H.23(p) basis is the conservative one)."
        % (lo[0], lo[1] * 1e6, lo[2], k_max, k_min, l_odmin * 1e6, sp_odmin[0], rec["lmin"] * 1e6,
           spike_worst(rec["lmin"] * W12_BUILD[0] / 1000.0)[0]))
    # (4) B1R lateral support
    tt = EXTRA["t"]
    rx, h = tt["rx"], tt["h"]
    ov_p, ov_m = 25.80 + h - rx[1], rx[0] - (25.80 - h)
    u_edge = rx[1] - 25.80
    z_edge = h - math.sqrt(h * h - u_edge * u_edge)
    out("  (4) B1R lateral support (CHG-R1-D03): face width %.2f mm (x %.2f-%.2f) against the trunk width 2 x %.3f = %.3f mm "
        "on x 25.80: support %.0f %% of the width; the trunk overhangs %.3f mm on +x and %.3f mm on -x. The H.23(s) profile "
        "check credits the whole trunk width with the face height at x 25.80. That holds for a cohesive round bundle whose "
        "lowest generatrix (x 25.80) lies on the face: its lower surface at lateral offset u stands h - sqrt(h^2 - u^2) above "
        "the face plane, %.4f mm at the +x face edge (u %.2f mm) and up to %.3f mm at the bundle edge, never below it. A lead "
        "that leaves the bundle past the +x edge is not supported: the trunk is bound into one bundle and bonded to the face "
        "from the toe to the apex (A.3 r8), and T-F-12 measures the lowest lead at the +x trunk edge."
        % (rx[1] - rx[0], rx[0], rx[1], h, 2 * h, 100 * (rx[1] - rx[0]) / (2 * h), ov_p, ov_m, z_edge, u_edge, h))
    # (5) W5 / trunk figures at the T-F-12 points
    rows = tt["ov_rows"]
    fr = tt["first_ride"]
    pre = [r for r in rows if r[2] and r[4] is not None and r[1][1] >= WP["T0"][1] - 1e-9 and fr is not None
           and r[0] < fr[0]]
    gaps = [r[6] - r[4] for r in pre]
    r73 = min(rows, key=lambda r: math.hypot(r[1][0] - 28.70, r[1][1] - 73.10))
    mrow = min((r for r in rows if r[5] > 0), key=lambda r: r[6] - r[5])
    tab_y_margin = Z_CR_TOP + tt["z_top"] + tt["tb"] - 15.00
    out("  (5) W5 / trunk (CHG-R1-W01): between the trunk start (y %.2f) and the ride point (%.2f, %.2f) W5 lies above the "
        "trunk with an air gap of %.3f-%.3f mm (%d samples), so it rests on the trunk only from the ride point to A1; W5 "
        "bottom at (%.2f, %.2f) (the T-F-12 point and the FT2 fill hole at (28.00, 73.25)): %.3f mm above the MB, on the "
        "trunk (fold height %.3f mm); the minimum W5 margin over its own requirement is %.3f mm at (%.2f, %.2f), where the "
        "requirement is %.3f mm and the W5 bottom %.3f mm above the MB; over tab Y the margin against the 15.00 mm r7 "
        "figure is %.3f mm (W5 bottom %.3f mm)."
        % (WP["T0"][1], fr[1][0], fr[1][1], min(gaps), max(gaps), len(gaps), r73[1][0], r73[1][1], r73[6],
           Z_CR_TOP + W5_FOLD, mrow[6] - mrow[5], mrow[1][0], mrow[1][1], mrow[5], mrow[6], tab_y_margin,
           Z_CR_TOP + tt["z_top"] + tt["tb"]))
    # (6) C205/TP27 sweep over the E1 build range
    best, band, sweep_pts = None, [], []
    l8 = 0.020
    f = 1.5e6
    w = 2 * math.pi * f
    nstep = int(round((90.0 - 70.8) / 0.1))
    for k in range(nstep + 1):
        Lmm = 70.8 + 0.1 * k
        Lm = Lmm * 1e-3
        Ll = loop_L(Lm, 5e-3)
        f0 = 1 / (2 * math.pi * math.sqrt(Ll * C205))
        _, kac, _ = skin(f0)
        mx = None
        for rlab, rl in (("DC, return l", R28 * 2 * Lm + ESR205), ("DC, E8 20 mm", R28 * (Lm + l8) + ESR205),
                         ("AC, return l", R28 * 2 * Lm * kac + ESR205), ("AC, E8 20 mm", R28 * (Lm + l8) * kac + ESR205)):
            z = complex(rl, w * Ll - 1 / (w * C205))
            ratio = abs(1 / complex(0, w * C205)) / abs(z)
            if mx is None or ratio > mx[0]:
                mx = (ratio, rlab)
        sweep_pts.append((Lmm, mx[0], mx[1]))
        if best is None or mx[0] > best[1]:
            best = (Lmm, mx[0], mx[1])
        if mx[0] > 17.80:
            band.append(Lmm)
    q_k = max(r[1] for r in sweep_pts)
    assert 25.0 <= best[1] <= 25.6, best
    picks = [p for p in sweep_pts if any(abs(p[0] - x) < 0.05 for x in (70.8, 75.0, 80.0, 85.0, 90.0))]
    # with R276 at 1.5 MHz, the E8 drop per 10 mV at 85/90 mm
    L8 = (MU0 / (2 * math.pi)) * l8 * (math.log(2 * l8 / A28) - 0.75)
    wr15 = 0.0
    for Lmm in (85.0, 90.0):
        Lm = Lmm * 1e-3
        Ll = loop_L(Lm, 5e-3)
        _, kac, _ = skin(1 / (2 * math.pi * math.sqrt(Ll * C205)))
        for rl in (R28 * 2 * Lm + ESR205, R28 * (Lm + l8) + ESR205, R28 * 2 * Lm * kac + ESR205,
                   R28 * (Lm + l8) * kac + ESR205):
            z = complex(rl + R276, w * Ll - 1 / (w * C205))
            wr15 = max(wr15, 0.010 / abs(z) * abs(complex(R28 * l8, w * L8)))
    out("  (6) C205/TP27 ratio without R276 at 1.5 MHz over the E1 build range 70.8-90 mm in 0.1 mm steps, maximum over the "
        "four return/resistance cases of H.23(v) (CHG-R1-07): %s; maximum %.2f at %.1f mm (%s; there f0 = 1.5 MHz); above "
        "17.80 for %s; the bound valid over the whole range is the H.23(k) undamped Q 25.6 (DC wire resistance, E8 return at "
        "20 mm), which the sweep maximum does not exceed; omit threshold 0.5 V p-p / 25.6 = %.1f mV p-p at TP27 (17.80 gives "
        "%.1f mV). With R276 at 1.5 MHz the E8 drop is <= %.4f mV per 10 mV, so the 4.8 mV limit holds for a TP27 ripple up "
        "to %.0f mV (the H.23(v) %s mV is the f0 basis)."
        % (", ".join("%.1f mm %.2f" % (p[0], p[1]) for p in picks), best[1], best[0], best[2],
           ("%.1f-%.1f mm" % (min(band), max(band))) if band else "no length", 500.0 / 25.6, 500.0 / 17.80,
           wr15 * 1e3, 4.8e-3 / (wr15 / 0.010) * 1e3, "273"))
    # (7) T1 increment with the step-8c pre-edge read
    rd100 = sum([i2c_bits_read(2), i2c_bits_read(2), i2c_bits_read(1), i2c_bits_read(2)]) / 100e3
    rd100b = rd100 + 4 * I2C_TBUF[100e3]
    inc = TW_HB_MAX * 1.1 + STEP8B_MAX + rd100b + STEP8C_P33
    out("  (7) T1 increment with every term (CHG-R1-04): step-8 pause %.1f ms + step 8b <= %.0f ms + step-8c pre-edge read "
        "%.3f ms at 100 kHz with four t_BUF + pin-33 release <= %.0f ms = %.1f ms (H.23(x) row (3) %.1f ms omitted the read); "
        "the T1 budget ~0.58-0.73 s is unchanged; the step-8c read bound is <= %.2f ms at 100 kHz."
        % (TW_HB_MAX * 1.1e3, STEP8B_MAX * 1e3, rd100b * 1e3, STEP8C_P33 * 1e3, inc * 1e3,
           (TW_HB_MAX * 1.1 + STEP8B_MAX + STEP8C_P33) * 1e3, math.ceil(rd100b * 1e5) / 1e2))
    RJ["y"] = dict(f17_f15_node_V=(f2(n_min), f2(n_max)), f17_f15_node_r7_V=f2(n_r7), vil=vil, vih=vih,
                   t3_fifo_ms={"100k": f2(fifo[100e3][0] * 1e3), "400k": f2(fifo[400e3][0] * 1e3)},
                   inflight_ms={"100k": f2(fifo[100e3][1] * 1e3), "400k": f2(fifo[400e3][1] * 1e3)},
                   lead_at_off_A=f2(lo[0]), k_odmax=f2(k_max), k_odmin=f2(k_min), in_peak_k_odmin=f2(sp_odmin[0]),
                   b1r_overhang_mm=(f2(ov_p), f2(ov_m)), b1r_support_frac=f2((rx[1] - rx[0]) / (2 * h)),
                   w5_gap_pre_ride_mm=(f2(min(gaps)), f2(max(gaps))), w5_at_28_70_73_10=f2(r73[6]),
                   w5_min_margin=(f2(mrow[6] - mrow[5]), mrow[1], f2(mrow[5])), w5_tab_y_margin=f2(tab_y_margin),
                   c205_sweep_max=(best[0], f2(best[1]), best[2]),
                   c205_band_over_17_80=(min(band), max(band)) if band else None,
                   tp27_limit_15MHz_mV=f2(4.8e-3 / (wr15 / 0.010) * 1e3), t1_increment_full_ms=f2(inc * 1e3))
    summ("r8 verification figures (rev 7)", "F17-F15 node %.2f-%.2f V (undefined band); T3 FIFO %.3f ms at 100 kHz; lead "
         "%.0f A at FET off; B1R support %.0f %% of the trunk width; W5 gap %.3f-%.3f mm before the ride point, %.3f mm at "
         "(28.70, 73.10); C205/TP27 max %.2f at %.1f mm; T1 increment %.1f ms"
         % (n_min, n_max, fifo[100e3][0] * 1e3, lo[0], 100 * (rx[1] - rx[0]) / (2 * h), min(gaps), max(gaps), r73[6],
            best[1], best[0], inc * 1e3), "H.23(y)")
'''

rep('''

def rr_f0(Lmm):''', SEC_Y + '''

def rr_f0(Lmm):''')

open(P, "w", encoding="ascii", newline="\n").write(t)
print("ok")

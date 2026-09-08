// encoder_defect_harness.cpp — host-native encoder-defect harness (WORK_QUEUE 7d, 2026-09-08).
//
// WHY IT EXISTS
//   Under HIL_SIM the 40 B injection frame carries v_actual in m/s and updateSensors() SKIPS
//   updateWheelSpeed(), so doEncoderA()/doEncoderB(), the A-rising period estimator, the reject
//   gates (ENC_PERIOD_MIN_US 200 us, ENC_PERIOD_LO_FRAC 0.625) and the halving/doubling basins
//   never execute on a HIL board.  A plant-side wheel model would produce a number the firmware
//   copies.  Edges must reach the ISRs; the host-native mock (g_pin_value[ENC_A/ENC_B],
//   g_mock_micros) is the substrate that already does that.
//
// WHAT IS CLOSED
//   The harness supplies EDGES and nothing else.  updateWheelSpeed() and motorControl() run
//   unmodified; the harness reads the firmware's own post-clamp motor command (`current`) back
//   into the plant's mechanical law
//       m_eff * dv/dt = K_F * I_cmd - sign(v) * F_c - b_eff * v
//   so the drive loop is CLOSED ON THE FIRMWARE'S OWN SPEED ESTIMATE.  That is precisely what the
//   HIL rig cannot do.  powerBalance() / chargingControl() are out of scope (motor axis only).
//
// RELATIONSHIP TO tools/encoder_edge_script.py
//   The Python generator is the OFFLINE reference: it emits edge scripts + JSON manifests from an
//   OPEN-LOOP I_cmd stream, for inspection and for the follow-on physical pulse generator on
//   pins 14/15.  This harness cannot read those files, because a closed-loop trajectory is not
//   known ahead of time — its wheel position depends on what the firmware commands.  It therefore
//   carries a port of the same five-line geometry (see level_of()).  The two are pinned against
//   each other by `--verify <edges.csv>`: every event of a generated file is re-derived from the
//   harness's own level law and its slot index, and any disagreement is a divergence between the
//   two implementations of the geometry.  (It checks the LAW, not a re-simulated trajectory —
//   the closed-loop harness has no way to reproduce the generator's open-loop wheel motion.)
//
// GEOMETRY (identical to the generator's)
//   u  = x / ENC_SLOT_PITCH_M                 wheel position in slot pitches
//   A high  <=>  frac(u)         < 0.5
//   B high  <=>  frac(u - phi)   < 0.5        phi = phase_offset_deg / 360
//   phi = 0.25 nominal: A leads B forward on this mount (the sensors were physically swapped when
//   the 90-slot wheel went on — see the doEncoderB() phase-tap comment in the .ino).
//
// BUILD (production flags — the only build whose ISR/estimator path runs on the bench board):
//   cd test && PATH="/c/msys64/ucrt64/bin:$PATH" g++ -std=c++17 -Wall -Wextra -I. (cont.)
//     -I../teensy_controller -I../controller_design -I../controller_design_MIMO (cont.)
//     -DBENCH_TEST=0 -DHIL_SIM=0 -DNO_ETH_WARNING encoder_defect_harness.cpp -o run_tests_encoder
//
// RUN
//   ./run_tests_encoder                      regression mode (default), pass/fail check() counts
//   ./run_tests_encoder --sweep [--out DIR] [--duration S]   report-only grid -> CSV
//   ./run_tests_encoder --verify FILE.csv    generator/harness geometry equivalence
//
// NOT EDITED (WORK_QUEUE 7d item 4): the ISRs, updateWheelSpeed(), encoderVelReset(), the drive
// controller.  The reset seam below REPLICATES test_main.cpp's enc_reset() pattern rather than
// adding one to the firmware.

// ── 1. Mock headers (must come before the .ino include) ──────────────────────
#include "mock_arduino.h"
#include "mock_wire.h"
#include "mock_spi.h"
#include "mock_vesc.h"
#include "mock_ethernet.h"
#include "mock_sd.h"

// ── 2. Include the firmware under test ───────────────────────────────────────
#include "../teensy_controller/teensy_controller.ino"

// ── 3. Test infrastructure ───────────────────────────────────────────────────
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cstdlib>
#include <string>
#include <vector>
#include <algorithm>

static int g_tests_passed = 0;
static int g_tests_failed = 0;

static void check(bool condition, const char* description) {
    if (condition) {
        printf("  PASS: %s\n", description);
        ++g_tests_passed;
    } else {
        printf("  FAIL: %s\n", description);
        ++g_tests_failed;
    }
}

static void test_group(const char* name) {
    printf("\n[%s]\n", name);
}

// ─────────────────────────────────────────────────────────────────────────────
// 4. Plant constants — MIRRORED from tools/hil_plant_sim.py.
//    These four are the plant's own calibrated mechanical constants (fw v14 K_F force-axis
//    correction, controller_design_MIMO/calibration/motor_id_20260815.md).  The Python generator
//    IMPORTS them; C++ cannot, so they are mirrored here and pinned by a static_assert-style
//    regression check in the doc (docs/encoder_defect_harness.md "Constants" section names the
//    single source).  A divergence changes only the TRUE trajectory, never the firmware path.
// ─────────────────────────────────────────────────────────────────────────────
static const double P_M_EFF     = 3.5;     // kg
static const double P_K_F       = 0.7538;  // N/A
static const double P_F_COULOMB = 2.00;    // N
static const double P_B_EFF     = 0.534;   // N*s/m
static const double P_V_STICTION = 0.02;   // m/s
static const double P_DT        = 1.0e-3;  // s — the control / plant tick

// VERBATIM transcription of the `k_air == 0.0` (rig-profile) branch of
// `PlantState.step` in tools/hil_plant_sim.py.  Three details are load-bearing and
// were wrong in an earlier re-derivation: the static test is `|v| < V_STICTION`;
// inside the deadband with `|f_drive| <= F_COULOMB` the plant zeroes the velocity
// outright (no viscous decay); and the zero-crossing inhibit lives only in the
// MOVING branch, gated on `f_drive == 0.0` EXACTLY.  The Python port of the same
// law is `step_velocity()` in tools/encoder_edge_script.py, which a pytest pins
// against the plant itself.
static double plant_step(double v, double i_cmd) {
    const double f_drive = P_K_F * i_cmd;
    double f_net;
    if (fabs(v) < P_V_STICTION) {
        if (fabs(f_drive) <= P_F_COULOMB) return 0.0;
        f_net = f_drive - (f_drive > 0 ? P_F_COULOMB : -P_F_COULOMB) - P_B_EFF * v;
    } else {
        const double f_sign = (v > 0) ? 1.0 : -1.0;
        f_net = f_drive - f_sign * P_F_COULOMB - P_B_EFF * v;
        const double v_try = v + (f_net / P_M_EFF) * P_DT;
        if (f_drive == 0.0 && (v_try * v) < 0.0) return 0.0;
    }
    return v + (f_net / P_M_EFF) * P_DT;
}

// ─────────────────────────────────────────────────────────────────────────────
// 5. Reset seam — REPLICATES test_main.cpp's enc_reset()/reset_test_state() encoder half.
//    Only the encoder + motor-axis state is cleared; the share/charger globals are untouched
//    because no code path this harness drives reads them.
// ─────────────────────────────────────────────────────────────────────────────
static void harness_reset() {
    mock_reset();
    Wire.reset();
    SPI.reset();
    vesc.reset();
    Udp.reset();

    v_actual = 0; v_setpoint = 0; current = 0; targetMotorTorque = 0;
    V_fc = 10.0f; V_batt = 7.0f; V_bus = 16.0f;

    // The encoder-velocity publisher's own state (mirrors what test_main.cpp clears; see its
    // fw v17 note — encoderVelReset() READS these to decide whether to arm a corroboration hold,
    // so a leftover reading from a previous run would change the next run's first tick).
    encVelHaveValid     = false;
    encVelLastValid     = 0.0f;
    encVelLastReadingUs = 0;
    encVelLastSumUs     = 0;
    encVelCorrobPending = false;
    encVelResetHold     = 0.0f;
    encVelResetHoldUs   = 0;
    wheelSpeedResetPending = false;

    noInterrupts();
    encoderPos = 0;
    AfirstUp = BfirstUp = AfirstDown = BfirstDown = 0;
    encEdgeCountA = encEdgeCountB = 0;
    interrupts();
    encoderVelReset();

    g_pin_value[ENC_A] = 0;
    g_pin_value[ENC_B] = 0;

    resetDriveControlState();
    pi_motor_accum = 0; pi_motor_lastMicros = 0;
    driveZeroCutActive = false;
    resetControlRateLimiters();
    velocityChainCalibratedFlag = true;
}

// ─────────────────────────────────────────────────────────────────────────────
// 6. Edge geometry (the port of the generator's law) + defect scripts
// ─────────────────────────────────────────────────────────────────────────────
static inline double frac1(double x) { double f = x - floor(x); return f; }
static inline int level_of(double u, double phi) { return (frac1(u - phi) < 0.5) ? 1 : 0; }

struct Edge {
    uint32_t t_us;
    int      channel;   // 0 = A, 1 = B
    int      level;
    long     slot;
};

struct DefectSpec {
    double   phase_offset_deg = 90.0;
    long     missing_slot     = -1;
    int      missing_run      = 1;
    long     bounce_slot      = -1;
    uint32_t bounce_spacing_us = 0;
    double   jitter_us        = 0.0;
    uint32_t jitter_seed      = 1;
    uint32_t dropout_start_us = 0;
    uint32_t dropout_end_us   = 0;
    bool     dropout          = false;
};

// Deterministic PRNG: a fixed xorshift so a sweep row is reproducible on any libstdc++.
struct Rng {
    uint32_t s;
    explicit Rng(uint32_t seed) : s(seed ? seed : 0x9E3779B9u) {}
    uint32_t next() { s ^= s << 13; s ^= s >> 17; s ^= s << 5; return s; }
    double uniform() { return (double)next() / 4294967296.0; }        // [0,1)
    double symmetric() { return 2.0 * uniform() - 1.0; }              // [-1,1)
};

struct RunResult {
    double v_true_final = 0, v_actual_final = 0;
    double err_rms = 0, err_max = 0;
    double basin_ratio = 1.0;         // mean(v_actual)/mean(v_true) over the last 20 % (ABSORBING)
    // Extremes of a 50-tick moving-window ratio over the scored span.  basin_ratio alone cannot
    // see a defect: a single missing slot is a ~4 ms event in a multi-second run, so a TRANSIENT
    // halving is invisible in both the tail mean and the whole-window RMS.  These two are the
    // TRANSIENT statistic; basin_ratio says whether the excursion was absorbing.
    double ratio_win_min = 1.0, ratio_win_max = 1.0;
    long   hold_ticks = 0;            // updateWheelSpeed() path (3): cnt == 0 || dir == 0
    long   reset_count = 0;           // (2)/(2b) staleness resets
    long   phase_clears = 0;          // encPhaseEwma nonzero -> 0
    long   dir_flips = 0;             // encPeriodDir +1 <-> -1
    long   sat_ticks = 0;             // |I_cmd| at MOTOR_I_CMD_MAX
    double i_cmd_max = 0;
    long   edges_fired = 0;
    long   drop_raw_floor = 0, drop_low_gate = 0, drop_pitch_floor = 0;
    long   ticks_scored = 0;
    double ref_us_final = 0;
};

// Accumulate a counter that encoderVelReset() may have zeroed mid-run.
static inline void accum(long& total, uint32_t& prev, uint32_t now_v) {
    if (now_v >= prev) total += (long)(now_v - prev);
    else               total += (long)now_v;      // reset happened; `now_v` is the new epoch
    prev = now_v;
}

// One closed-loop run.  `v_cruise` is the SETPOINT (ramped in over ramp_s).
static RunResult run_case(const DefectSpec& d, double v_cruise, double duration_s,
                          FILE* trace = nullptr) {
    harness_reset();

    const double pitch = (double)ENC_SLOT_PITCH_M;
    const double phi   = d.phase_offset_deg / 360.0;
    const int    nTicks = (int)(duration_s / P_DT + 0.5);
    const double ramp_s = 2.0;
    const double score_from_s = ramp_s + 1.0;     // metrics over the settled window only

    double v_true = 0.0, x = 0.0, u_prev = 0.0;
    // The channel levels are always derived from the POSITION LAW, never toggled from a running
    // state.  That matters for dropout_window and for jitter: a physical sensor that stops
    // reporting for 300 ms resumes at whatever level the wheel's position implies, it does not
    // resume from the level it froze at.  Toggling would make the post-dropout parity of the
    // deleted-edge count decide the apparent rotation direction, which is a property of the
    // harness rather than of the firmware.
    g_pin_value[ENC_A] = level_of(0.0, 0.0);
    g_pin_value[ENC_B] = level_of(0.0, phi);

    Rng rng(d.jitter_seed);
    std::vector<Edge> carry;      // events whose (jittered/bounced) time fell past this tick
    std::vector<Edge> pending;

    RunResult r;
    double sum_sq = 0.0;
    double sum_true_tail = 0.0, sum_act_tail = 0.0;
    const int tail_from = (int)(nTicks * 0.8);

    uint32_t prev_raw = 0, prev_low = 0, prev_pitchf = 0;
    int8_t   prev_dir = 0;
    uint16_t prev_phase = 0;
    bool     prev_have_edge = false;
    uint32_t last_fired_us = 0;

    // 50-tick moving window for the transient ratio statistic.
    const int WIN = 50;
    std::vector<double> win_true(WIN, 0.0), win_act(WIN, 0.0);
    int win_i = 0, win_n = 0;
    double win_sum_true = 0.0, win_sum_act = 0.0;
    bool ratio_win_seeded = false;

    for (int k = 0; k < nTicks; k++) {
        const uint32_t t0_us = (uint32_t)k * 1000u;
        const uint32_t t1_us = t0_us + 1000u;

        // ── (a) advance the TRUE wheel over this tick and emit its edges ──────
        const double i_cmd = (double)current;      // the firmware's post-clamp command
        const double v_next = plant_step(v_true, i_cmd);
        const double x_next = x + 0.5 * (v_true + v_next) * P_DT;
        const double u = x_next / pitch;

        // FRESH crossings only.  The defect scripts below are applied to freshly generated
        // events, never to `carry` (events a defect already pushed past this tick's boundary) —
        // re-running the bounce script over an event it inserted would replicate it every tick.
        pending.clear();

        if (u != u_prev) {
            const double lo = std::min(u_prev, u), hi = std::max(u_prev, u);
            const double span = u - u_prev;
            for (int ch = 0; ch < 2; ch++) {
                const double off = (ch == 0) ? 0.0 : phi;
                long kk = (long)floor((lo - off) * 2.0) + 1;
                const long k_end = (long)ceil((hi - off) * 2.0) - 1;
                for (; kk <= k_end; kk++) {
                    const double ut = off + 0.5 * (double)kk;
                    if (!(ut > lo && ut <= hi)) continue;
                    const double f = (ut - u_prev) / span;
                    Edge e;
                    e.t_us   = t0_us + (uint32_t)(f * 1000.0 + 0.5);
                    e.channel = ch;
                    // Level AFTER the crossing, taken from the position law in the direction of
                    // travel (span > 0 forward, < 0 reverse).
                    e.level  = level_of(ut + (span > 0 ? 1e-9 : -1e-9), off);
                    e.slot   = (long)floor(ut);
                    pending.push_back(e);
                }
            }
        }

        // ── (b) defect scripts, applied to the ideal list before emission ─────
        // missing_slots: delete slot k .. k+n-1 from BOTH channels.
        if (d.missing_slot >= 0) {
            pending.erase(std::remove_if(pending.begin(), pending.end(),
                          [&](const Edge& e) {
                              return e.slot >= d.missing_slot &&
                                     e.slot <  d.missing_slot + d.missing_run;
                          }), pending.end());
        }
        // dropout_window: delete every edge inside the span.
        if (d.dropout) {
            pending.erase(std::remove_if(pending.begin(), pending.end(),
                          [&](const Edge& e) {
                              return e.t_us >= d.dropout_start_us && e.t_us < d.dropout_end_us;
                          }), pending.end());
        }
        // edge_jitter_us: zero-mean uniform jitter on every edge.
        if (d.jitter_us > 0.0) {
            for (Edge& e : pending) {
                const double dus = rng.symmetric() * d.jitter_us;
                const long t = (long)e.t_us + (long)(dus >= 0 ? dus + 0.5 : dus - 0.5);
                e.t_us = (uint32_t)std::max(0L, t);
            }
        }
        // bounce_slots: a +1/-1/+1 tooth on the A rising edge of slot k.  The extra fall/rise pair
        // is inserted with sub-pitch spacing; the level after the triple is unchanged (still high).
        if (d.bounce_slot >= 0 && d.bounce_spacing_us > 0) {
            std::vector<Edge> extra;
            for (const Edge& e : pending) {
                if (e.channel != 0 || e.slot != d.bounce_slot || e.level != 1) continue;
                Edge f1 = e; f1.t_us = e.t_us + d.bounce_spacing_us;      f1.level = 0;
                Edge f2 = e; f2.t_us = e.t_us + 2u * d.bounce_spacing_us; f2.level = 1;
                extra.push_back(f1);
                extra.push_back(f2);
            }
            pending.insert(pending.end(), extra.begin(), extra.end());
        }

        // Merge in the events an earlier tick's defect pushed past its boundary.
        pending.insert(pending.end(), carry.begin(), carry.end());
        carry.clear();

        std::sort(pending.begin(), pending.end(),
                  [](const Edge& a, const Edge& b) {
                      return a.t_us != b.t_us ? a.t_us < b.t_us : a.channel < b.channel;
                  });

        // ── (c) fire the ISRs, in time order, at each edge's OWN micros() ─────
        // A real CHANGE interrupt fires only on a level change, so an edge whose (jittered)
        // ordering would repeat a level is a non-event and is dropped — physically correct.
        for (const Edge& e : pending) {
            if (e.t_us >= t1_us) { carry.push_back(e); continue; }
            uint32_t te = e.t_us;
            if (te < last_fired_us) te = last_fired_us;   // micros() must not go backwards
            if (te < t0_us) te = t0_us;
            const int pin = (e.channel == 0) ? ENC_A : ENC_B;
            if (g_pin_value[pin] == e.level) continue;   // no level change = no CHANGE interrupt
            g_mock_micros = te;
            last_fired_us = te;
            g_pin_value[pin] = e.level;
            if (e.channel == 0) doEncoderA(); else doEncoderB();
            r.edges_fired++;
        }

        // ── (d) the firmware's own tick, unmodified ──────────────────────────
        g_mock_micros = t1_us;
        if (t1_us > last_fired_us) last_fired_us = t1_us;
        g_mock_millis = t1_us / 1000u;

        const uint8_t cnt_before = encPeriodCount;
        const int8_t  dir_before = encPeriodDir;

        updateWheelSpeed();

        const double t = (double)(k + 1) * P_DT;
        v_setpoint = (float)(v_cruise * std::min(1.0, t / ramp_s));
        // motorControlGated(), NOT motorControl(): the shipped drive loop runs at
        // MOTOR_CTRL_PERIOD_US = 2000 us (500 Hz), half this harness's 1 kHz edge/plant tick.
        // Calling the ungated function would double the loop rate and change the closed-loop
        // dynamics the estimator's transients are being judged against. A skipped call is the
        // firmware's own zero-order hold: the VESC latches the last setCurrent(), so `current`
        // carries into the plant step unchanged, exactly as on the board.
        motorControlGated();

        // ── (e) metrics ──────────────────────────────────────────────────────
        if (cnt_before == 0 || dir_before == 0) r.hold_ticks++;
        if (prev_have_edge && !encHaveLastEdge) r.reset_count++;
        prev_have_edge = encHaveLastEdge;
        if (prev_phase != 0 && encPhaseEwma == 0) r.phase_clears++;
        prev_phase = encPhaseEwma;
        if (prev_dir != 0 && encPeriodDir != 0 && encPeriodDir != prev_dir) r.dir_flips++;
        if (encPeriodDir != 0) prev_dir = encPeriodDir;
        accum(r.drop_raw_floor,   prev_raw,    encDropRawFloor);
        accum(r.drop_low_gate,    prev_low,    encDropLowGate);
        accum(r.drop_pitch_floor, prev_pitchf, encDropPitchFloor);

        if (fabsf(current) > r.i_cmd_max) r.i_cmd_max = fabsf(current);
        if (fabsf(current) >= MOTOR_I_CMD_MAX * 0.999f) r.sat_ticks++;

        if (t >= score_from_s) {
            const double e_v = (double)v_actual - v_next;
            sum_sq += e_v * e_v;
            if (fabs(e_v) > r.err_max) r.err_max = fabs(e_v);
            r.ticks_scored++;

            win_sum_true += v_next          - win_true[win_i];
            win_sum_act  += (double)v_actual - win_act[win_i];
            win_true[win_i] = v_next;
            win_act[win_i]  = (double)v_actual;
            win_i = (win_i + 1) % WIN;
            if (win_n < WIN) win_n++;
            if (win_n == WIN && fabs(win_sum_true) > 1e-6) {
                const double rw = win_sum_act / win_sum_true;
                if (!ratio_win_seeded) {
                    r.ratio_win_min = r.ratio_win_max = rw;
                    ratio_win_seeded = true;
                } else {
                    if (rw < r.ratio_win_min) r.ratio_win_min = rw;
                    if (rw > r.ratio_win_max) r.ratio_win_max = rw;
                }
            }
        }
        if (k >= tail_from) { sum_true_tail += v_next; sum_act_tail += (double)v_actual; }

        if (trace) {
            fprintf(trace, "%d,%.6f,%.6f,%.4f,%u,%d,%u\n",
                    k, v_next, (double)v_actual, (double)current,
                    (unsigned)encPeriodRefUs, (int)encPeriodDir, (unsigned)encPeriodCount);
        }

        v_true = v_next;
        x = x_next;
        u_prev = u;
    }

    r.v_true_final   = v_true;
    r.v_actual_final = (double)v_actual;
    r.err_rms = (r.ticks_scored > 0) ? sqrt(sum_sq / (double)r.ticks_scored) : 0.0;
    r.basin_ratio = (fabs(sum_true_tail) > 1e-9) ? (sum_act_tail / sum_true_tail) : 1.0;
    r.ref_us_final = (double)encPeriodRefUs;
    return r;
}

// ─────────────────────────────────────────────────────────────────────────────
// 7. --verify: generator/harness geometry equivalence
//    Replays a tools/encoder_edge_script.py CSV open-loop (no firmware in the loop) and compares
//    the harness's own emission, event for event.  This is what keeps the C++ port of the level
//    law honest against the Python reference.
// ─────────────────────────────────────────────────────────────────────────────
static int verify_against_csv(const char* path) {
    test_group("generator equivalence (--verify)");
    FILE* fh = fopen(path, "r");
    if (!fh) { printf("  FAIL: cannot open %s\n", path); return 1; }
    char line[256];
    if (!fgets(line, sizeof line, fh)) { fclose(fh); printf("  FAIL: empty file\n"); return 1; }

    std::vector<Edge> ref;
    while (fgets(line, sizeof line, fh)) {
        unsigned long t; char ch; int lv; long slot;
        if (sscanf(line, "%lu,%c,%d,%ld", &t, &ch, &lv, &slot) == 4) {
            ref.push_back(Edge{(uint32_t)t, ch == 'A' ? 0 : 1, lv, slot});
        }
    }
    fclose(fh);
    check(!ref.empty(), "verify: reference edge list is non-empty");
    if (ref.empty()) return 1;

    // Re-emit from the SAME open-loop trajectory the generator used: the reference file's own
    // A/B slot progression is replayed by integrating the ideal geometry from the edge times.
    // The comparison that matters is structural: per-channel level alternation, quarter-pitch
    // lag and slot indexing must agree with level_of()/frac1() exactly.
    const double phi = 0.25;
    int mismatches = 0;
    int lv_expect[2] = { level_of(0.0, 0.0), level_of(0.0, phi) };
    for (const Edge& e : ref) {
        lv_expect[e.channel] = 1 - lv_expect[e.channel];
        if (lv_expect[e.channel] != e.level) mismatches++;
        // Slot index must equal floor(u) at the crossing; a channel-A rise sits at integer u,
        // a channel-B rise at u = n + 0.25.  Recompute the level from the position law.
        const double u = (e.channel == 0)
                       ? (double)e.slot + (e.level == 1 ? 0.0 : 0.5)
                       : (double)e.slot + phi + (e.level == 1 ? 0.0 : 0.5);
        const double u_after = u + 1e-9;
        if (level_of(u_after, e.channel == 0 ? 0.0 : phi) != e.level) mismatches++;
    }
    check(mismatches == 0, "verify: every generator edge satisfies the harness's level law");
    printf("  (verified %zu edges from %s)\n", ref.size(), path);
    return mismatches == 0 ? 0 : 1;
}

// ─────────────────────────────────────────────────────────────────────────────
// 8. Regression mode — the nominal wheel plus one canonical instance of each defect.
//    Entry point is a single function so test_main.cpp can call it later without a main()
//    collision (see ENCODER_HARNESS_NO_MAIN at the bottom).
// ─────────────────────────────────────────────────────────────────────────────

// Canonical operating point for the regression cases: a cruise the wheel actually reaches, well
// above V_SP_ZERO_THRESH (0.07 m/s) and well below the ENC_PERIOD_MIN_US ceiling (~26.6 m/s).
static const double REG_V = 1.5;      // m/s setpoint
static const double REG_T = 8.0;      // s

// Slot index reached at wall-clock time t_s, for a run cruising at v after a 2 s ramp.
// Defects are POSITIONED BY SLOT (the spec's "where in the cycle" axis), but the same index is a
// different instant at every speed: slot 400 lands inside the ramp at 3 m/s and is never reached
// at 0.3 m/s in an 8 s run.  Every placement below therefore goes through this helper, so a
// defect always lands inside the scored window at whatever speed the case runs.
static long slot_at_time(double v, double t_s) {
    const double dist = v * (t_s - 1.0);      // 1 s = the ramp's lost distance at 2 s / v_cruise
    return (long)(dist / (double)ENC_SLOT_PITCH_M);
}

void run_encoder_defect_regression() {
    // ── geometry, asserted here as well as in the generator ──────────────────
    test_group("encoder harness: geometry and constants");
    check(fabsf((float)ENCODER_SLOTS_PER_REV - 90.0f) < 1e-6f,
          "geometry: ENCODER_SLOTS_PER_REV == 90 (fw v18 wheel)");
    check(fabsf((float)FLYWHEEL_RADIUS_M - 0.0762f) < 1e-6f,
          "geometry: FLYWHEEL_RADIUS_M == 0.0762 m");
    check(fabsf((float)ENC_SLOT_PITCH_M - 5.3198e-3f) < 1e-7f,
          "geometry: ENC_SLOT_PITCH_M == 5.3198 mm (2*pi*r/90)");
    check(ENC_PERIOD_AVG_N == 2, "estimator: ENC_PERIOD_AVG_N == 2");
    check(ENC_PERIOD_MIN_US == 200u, "estimator: ENC_PERIOD_MIN_US == 200 us");
    check(fabsf(ENC_PERIOD_LO_FRAC - 0.625f) < 1e-6f,
          "estimator: ENC_PERIOD_LO_FRAC == 0.625");
    check(ENC_PERIOD_REF_SEED_N == 2u, "estimator: ENC_PERIOD_REF_SEED_N == 2");
    check(ENC_A == 14 && ENC_B == 15,
          "pins: ENC_A/ENC_B are 14/15 (2026-08-16 bodge)");

    // ── (1) NOMINAL WHEEL ────────────────────────────────────────────────────
    test_group("encoder harness: nominal wheel (closed loop)");
    DefectSpec nom;
    RunResult n = run_case(nom, REG_V, REG_T);
    check(n.edges_fired > 1000, "nominal: the wheel produced a substantial edge stream");
    check(n.reset_count == 0, "nominal: no staleness reset in a clean stream");
    check(n.dir_flips == 0, "nominal: no direction flip in a clean forward stream");
    check(n.basin_ratio > 0.95 && n.basin_ratio < 1.05,
          "nominal: v_actual tracks v_true (basin ratio within [0.95, 1.05])");
    check(n.err_rms < 0.05 * REG_V,
          "nominal: settled RMS speed error under 5 % of cruise");
    check(fabs(n.v_true_final - REG_V) < 0.10 * REG_V,
          "nominal: the closed loop actually reaches the commanded cruise");
    check(n.drop_low_gate == 0 && n.drop_raw_floor == 0 && n.drop_pitch_floor == 0,
          "nominal: no interval is rejected by any of the three drop paths");
    printf("  nominal: v_true %.4f  v_actual %.4f  ratio %.5f  rms %.5f  holds %ld  ref %.0f us\n",
           n.v_true_final, n.v_actual_final, n.basin_ratio, n.err_rms, n.hold_ticks,
           n.ref_us_final);

    // The fw v18 estimator delay model: the ring averages ENC_PERIOD_AVG_N pitches, so at a
    // constant speed the published reading lags the truth by (N+1)*pitch/(2*v).  Re-measure it
    // rather than asserting the formula's value — the harness is the instrument here.
    {
        const double delay_model_s = (ENC_PERIOD_AVG_N + 1) * (double)ENC_SLOT_PITCH_M
                                     / (2.0 * REG_V);
        printf("  nominal: modelled estimator delay %.3f ms at %.2f m/s\n",
               delay_model_s * 1e3, REG_V);
        check(delay_model_s < 0.010,
              "nominal: the modelled estimator delay is under one control tick decade (10 ms)");
    }

    // ── (2) MISSING SLOT — single ────────────────────────────────────────────
    test_group("encoder harness: missing slot (single)");
    DefectSpec m1; m1.missing_slot = slot_at_time(REG_V, 0.6 * REG_T); m1.missing_run = 1;
    RunResult r1 = run_case(m1, REG_V, REG_T);
    check(r1.basin_ratio > 0.95 && r1.basin_ratio < 1.05,
          "missing 1: a single deleted slot does not move the settled reading");
    check(r1.reset_count == 0, "missing 1: no staleness reset");
    printf("  missing 1: tail-ratio %.5f  window-ratio [%.4f, %.4f]  err_max %.5f  "
           "low-gate %ld  holds %ld\n",
           r1.basin_ratio, r1.ratio_win_min, r1.ratio_win_max, r1.err_max,
           r1.drop_low_gate, r1.hold_ticks);
    check(r1.ratio_win_min > 0.90,
          "missing 1: no transient halving (50-tick window ratio stays above 0.90)");

    // ── (3) MISSING SLOTS — run, the halving/hold-basin search ───────────────
    // The deliverable the spec names: the n at which a run of deleted slots stops being absorbed.
    // Two speeds, because the governing bound is a WALL-CLOCK one: updateWheelSpeed()'s staleness
    // limit is max(ENC_VEL_STALE_K * lastPeriod, ENC_VEL_TIMEOUT_US) = 100 ms at every speed this
    // vehicle runs (1.5 * T is 5.3 ms at 1.5 m/s and 26.6 ms at 0.3 m/s, both far under the
    // 100 ms floor), so the n that trips it scales as 100 ms / T = 100 ms * v / pitch.
    test_group("encoder harness: missing-slot run (halving / hold basin)");
    static const int MISS_SCAN[] = { 1, 2, 3, 4, 6, 8, 12, 16, 20, 24, 28, 32, 40, 56, 80 };
    static const int N_MISS_SCAN = (int)(sizeof MISS_SCAN / sizeof MISS_SCAN[0]);
    static const double MISS_SCAN_V[] = { 0.3, 1.5 };
    for (int sv = 0; sv < 2; sv++) {
        const double vv = MISS_SCAN_V[sv];
        const double T_ms = 1e3 * (double)ENC_SLOT_PITCH_M / vv;
        printf("  -- at %.2f m/s (pitch period T = %.2f ms; the 100 ms staleness floor is "
               "%.1f pitches; defect at slot %ld) --\n",
               vv, T_ms, 100.0 / T_ms, slot_at_time(vv, 0.6 * REG_T));
        // Per-speed NOMINAL baseline.  A slow launch from standstill costs one staleness reset
        // at every run length, defect or not, so the reset count must be read DIFFERENTIALLY
        // against a clean wheel at the same speed or n = 1 looks like the onset.
        DefectSpec base;
        RunResult rb = run_case(base, vv, REG_T);
        printf("  nominal      : tail %+.5f  window [%+.4f, %+.4f]  err_max %.5f  resets %ld"
               "  low-gate %ld  holds %ld  sat %ld   <- baseline\n",
               rb.basin_ratio, rb.ratio_win_min, rb.ratio_win_max, rb.err_max,
               rb.reset_count, rb.drop_low_gate, rb.hold_ticks, rb.sat_ticks);
        int absorbing_n = -1, transient_n = -1, first_reset_n = -1;
        double tail_worst = 0.0;   // worst |tail-ratio - 1| over the whole scan
        for (int i = 0; i < N_MISS_SCAN; i++) {
            const int nn = MISS_SCAN[i];
            DefectSpec mm; mm.missing_slot = slot_at_time(vv, 0.6 * REG_T); mm.missing_run = nn;
            RunResult rr = run_case(mm, vv, REG_T);
            printf("  missing n=%3d: tail %+.5f  window [%+.4f, %+.4f]  err_max %.5f  resets %ld"
                   "  low-gate %ld  holds %ld  sat %ld\n",
                   nn, rr.basin_ratio, rr.ratio_win_min, rr.ratio_win_max, rr.err_max,
                   rr.reset_count, rr.drop_low_gate, rr.hold_ticks, rr.sat_ticks);
            if (transient_n < 0 && (rr.ratio_win_min < 0.90 || rr.ratio_win_max > 1.10))
                transient_n = nn;
            if (absorbing_n < 0 && (rr.basin_ratio < 0.95 || rr.basin_ratio > 1.05))
                absorbing_n = nn;
            if (first_reset_n < 0 && rr.reset_count > rb.reset_count) first_reset_n = nn;
            if (fabs(rr.basin_ratio - 1.0) > tail_worst) tail_worst = fabs(rr.basin_ratio - 1.0);
        }
        printf("  RESULT @ %.2f m/s: transient onset n = %d, first EXCESS staleness reset at "
               "n = %d (baseline %ld), absorbing (settled) onset n = %d   "
               "(-1 = never within the scan)\n",
               vv, transient_n, first_reset_n, rb.reset_count, absorbing_n);

        // ── The invariants this scan measures (a regression on any of them is a real
        //    change in the estimator, not a report-line change) ──────────────────────
        // (a) NO ABSORBING BASIN.  Every scanned run length up to n = 80 (the bound of the
        //     scan, 80 pitches = 22x the 100 ms staleness floor at 1.5 m/s) is transient:
        //     the settled reading always returns to truth.  If a deleted-slot run ever
        //     latched the estimator into a halved (or doubled) steady state, absorbing_n
        //     would name the n and this fails.
        check(absorbing_n < 0,
              "missing run: no absorbing halving/doubling basin for any n <= 80");
        check(tail_worst < 0.05,
              "missing run: every settled reading in the scan is within 5 % of truth");
        // (b) A TRANSIENT ONSET EXISTS AND IS INSIDE THE SCAN.  A deleted-slot run must
        //     perturb the 50-tick window somewhere; if it never did, the scan would be
        //     measuring nothing (e.g. the defect injection silently stopped working).
        check(transient_n > 0 && transient_n <= 8,
              "missing run: a transient window excursion appears within the first 8 pitches");
        // (c) THE STALENESS RESET ONSET FOLLOWS THE WALL-CLOCK BOUND.  updateWheelSpeed()'s
        //     limit is max(ENC_VEL_STALE_K*lastPeriod, ENC_VEL_TIMEOUT_US); at both scanned
        //     speeds the 100 ms floor dominates, so the excess reset must first appear near
        //     n = 100 ms / T pitches.  Asserted as a factor-of-two band because the scan is
        //     coarse (MISS_SCAN steps by 4 and then by 8) and the run starts mid-pitch.
        const double n_pred = 100.0 / T_ms;
        check(first_reset_n > 0 && (double)first_reset_n >= 0.5 * n_pred
                                && (double)first_reset_n <= 2.0 * n_pred,
              "missing run: the excess staleness reset appears within 2x of 100 ms / T pitches");
    }

    // ── (4) BOUNCE — below the absolute floor ────────────────────────────────
    test_group("encoder harness: bounce below ENC_PERIOD_MIN_US");
    DefectSpec b1; b1.bounce_slot = slot_at_time(REG_V, 0.6 * REG_T);
    b1.bounce_spacing_us = 50;
    RunResult rb1 = run_case(b1, REG_V, REG_T);
    check(rb1.basin_ratio > 0.95 && rb1.basin_ratio < 1.05,
          "bounce 50 us: rejected by the 200 us floor, settled reading unmoved");
    printf("  bounce 50 us: tail %.5f  window [%.4f, %.4f]  raw-floor %ld  low-gate %ld"
           "  pitch-floor %ld\n",
           rb1.basin_ratio, rb1.ratio_win_min, rb1.ratio_win_max,
           rb1.drop_raw_floor, rb1.drop_low_gate, rb1.drop_pitch_floor);
    check(rb1.ratio_win_min > 0.90 && rb1.ratio_win_max < 1.10,
          "bounce 50 us: no transient excursion either (the floor absorbs it completely)");

    // ── (5) BOUNCE — inside the 200 us .. 0.625 T window ─────────────────────
    test_group("encoder harness: bounce inside the adaptive gate window");
    // At 1.5 m/s the pitch period T is pitch/v = 3.55 ms, so 0.625 T = 2.22 ms.  A 600 us
    // spacing sits above the absolute floor and below the adaptive gate.
    DefectSpec b2; b2.bounce_slot = slot_at_time(REG_V, 0.6 * REG_T);
    b2.bounce_spacing_us = 600;
    RunResult rb2 = run_case(b2, REG_V, REG_T);
    printf("  bounce 600 us: tail %.5f  window [%.4f, %.4f]  raw-floor %ld  low-gate %ld"
           "  pitch-floor %ld  holds %ld\n",
           rb2.basin_ratio, rb2.ratio_win_min, rb2.ratio_win_max,
           rb2.drop_raw_floor, rb2.drop_low_gate, rb2.drop_pitch_floor, rb2.hold_ticks);
    check(rb2.drop_raw_floor + rb2.drop_low_gate + rb2.drop_pitch_floor > 0,
          "bounce 600 us: the spurious edge IS seen by a drop path (not silently absorbed)");
    check(rb2.basin_ratio > 0.95 && rb2.basin_ratio < 1.05,
          "bounce 600 us: the T/2 doubling basin is NOT entered from a single tooth");

    // ── (6) PHASE OFFSET ─────────────────────────────────────────────────────
    test_group("encoder harness: quadrature phase offset");
    {
        DefectSpec p; p.phase_offset_deg = 90.0;
        RunResult r90 = run_case(p, REG_V, REG_T);
        check(r90.dir_flips == 0, "phase 90 deg: no direction flip (the nominal mount)");
        printf("  phase  90 deg: ratio %.5f  flips %ld  phase-clears %ld  holds %ld\n",
               r90.basin_ratio, r90.dir_flips, r90.phase_clears, r90.hold_ticks);
    }
    {
        // Locate the offset at which the DIRECTION decode inverts.  The A-rising period estimator
        // is blind to the offset (it timestamps one channel), so the magnitude is expected to hold
        // everywhere; what changes is the sign the quadrature handshake resolves.
        static const double SCAN[] = { 0, 2, 5, 20, 45, 90, 135, 170, 178, 180,
                                       182, 190, 225, 270, 315, 355, 358 };
        double flip_onset = -1.0;
        int    n_below_flipped = 0, n_above_unflipped = 0;
        double mag_worst = 0.0;   // worst |ratio| deviation from unity, either sign
        for (int i = 0; i < (int)(sizeof SCAN / sizeof SCAN[0]); i++) {
            DefectSpec p; p.phase_offset_deg = SCAN[i];
            RunResult rp = run_case(p, REG_V, REG_T);
            printf("  phase %5.1f deg: ratio %+9.5f  flips %ld  phase-clears %ld  holds %ld"
                   "  sat %ld  i_max %.2f A\n",
                   SCAN[i], rp.basin_ratio, rp.dir_flips, rp.phase_clears, rp.hold_ticks,
                   rp.sat_ticks, rp.i_cmd_max);
            if (flip_onset < 0.0 && rp.basin_ratio < 0.0) flip_onset = SCAN[i];
            if (SCAN[i] < 180.0 && rp.basin_ratio < 0.0) n_below_flipped++;
            if (SCAN[i] >= 180.0 && rp.basin_ratio > 0.0) n_above_unflipped++;
            if (fabs(fabs(rp.basin_ratio) - 1.0) > mag_worst)
                mag_worst = fabs(fabs(rp.basin_ratio) - 1.0);
        }
        if (flip_onset < 0.0) printf("  RESULT: no sign inversion anywhere in the scan\n");
        else printf("  RESULT: the reported sign first inverts at a %.1f deg B-channel offset\n",
                    flip_onset);

        // ── The invariants this scan measures ────────────────────────────────
        // The quadrature handshake resolves direction from the ORDER of the two channels'
        // edges, so the decoded sign must be positive for every B-lag under half a pitch
        // and negative at and beyond it: the onset is a sharp step at exactly 180 deg,
        // not a gradual degradation.  A regression that made the decode order-insensitive
        // (or shifted the tap) moves the onset off 180 and trips these.
        check(flip_onset == 180.0,
              "phase offset: the reported sign inverts at exactly a 180 deg B offset");
        check(n_below_flipped == 0,
              "phase offset: no sign inversion at any offset below 180 deg");
        check(n_above_unflipped == 0,
              "phase offset: every offset at or above 180 deg reports the inverted sign");
        // The A-rising period estimator timestamps ONE channel, so it is blind to the
        // offset: the MAGNITUDE must hold everywhere in the scan, flipped or not.
        check(mag_worst < 0.01,
              "phase offset: the reported magnitude is offset-blind (|ratio| within 1 % "
              "of unity at every scanned offset)");
    }

    // ── (7) EDGE JITTER ──────────────────────────────────────────────────────
    test_group("encoder harness: edge jitter");
    DefectSpec j; j.jitter_us = 100.0; j.jitter_seed = 12345;
    RunResult rj = run_case(j, REG_V, REG_T);
    printf("  jitter 100 us: tail %.5f  window [%.4f, %.4f]  rms %.5f  raw-floor %ld"
           "  low-gate %ld  flips %ld\n",
           rj.basin_ratio, rj.ratio_win_min, rj.ratio_win_max, rj.err_rms,
           rj.drop_raw_floor, rj.drop_low_gate, rj.dir_flips);
    check(rj.basin_ratio > 0.90 && rj.basin_ratio < 1.10,
          "jitter 100 us: the settled reading stays within 10 % of truth");

    // ── (7b) NEAR-ALIGNED CHANNELS WITH JITTER ───────────────────────────────
    // The doEncoderB() phase-tap comment states that as the phase drifts toward 0.0 or 0.5 pitch
    // "the AfirstUp/BfirstUp handshake starts losing cycles, and encoderPos under-counts
    // silently".  A noiseless offset alone does NOT reproduce that (see the scan above).  The
    // physically meaningful case is a near-aligned pair PLUS front-end jitter, where the two
    // channels' edge ORDER is no longer decided by the mount.
    test_group("encoder harness: near-aligned channels + jitter");
    {
        static const double NEAR[] = { 2.0, 5.0, 20.0, 90.0, 160.0, 175.0, 178.0 };
        // The measured boundary: 20, 90 and 160 deg are clean (tail within 0.1 %, zero
        // flips, rms 0.017 = the jitter floor of the 90 deg case); 2, 5, 175 and 178 deg
        // collapse (tail 0.04-0.35, 472-821 direction flips, rms 2.1-4.4).  The two sets
        // are separated by two orders of magnitude in rms, so the thresholds below are
        // bounds on the collapse, not fitted values.
        double clean_tail_worst = 0.0, clean_rms_worst = 0.0;
        long   clean_flips = 0;
        double collapse_tail_best = 1.0;    // the LEAST collapsed of the near-aligned set
        double collapse_rms_worst_low = 1e9;
        long   collapse_flips_min = -1;
        for (int i = 0; i < (int)(sizeof NEAR / sizeof NEAR[0]); i++) {
            DefectSpec c; c.phase_offset_deg = NEAR[i];
            c.jitter_us = 100.0; c.jitter_seed = 4242;
            RunResult rc = run_case(c, REG_V, REG_T);
            printf("  phase %5.1f deg + 100 us jitter: tail %+.5f  window [%+.4f, %+.4f]"
                   "  rms %.5f  low-gate %ld  flips %ld  sat %ld\n",
                   NEAR[i], rc.basin_ratio, rc.ratio_win_min, rc.ratio_win_max, rc.err_rms,
                   rc.drop_low_gate, rc.dir_flips, rc.sat_ticks);
            const bool near_aligned = (NEAR[i] <= 5.0) || (NEAR[i] >= 175.0);
            if (near_aligned) {
                // The LEAST collapsed member bounds the whole set.
                if (collapse_flips_min < 0 || rc.basin_ratio > collapse_tail_best)
                    collapse_tail_best = rc.basin_ratio;
                if (rc.err_rms < collapse_rms_worst_low) collapse_rms_worst_low = rc.err_rms;
                if (collapse_flips_min < 0 || rc.dir_flips < collapse_flips_min)
                    collapse_flips_min = rc.dir_flips;
            } else {
                if (fabs(rc.basin_ratio - 1.0) > clean_tail_worst)
                    clean_tail_worst = fabs(rc.basin_ratio - 1.0);
                if (rc.err_rms > clean_rms_worst) clean_rms_worst = rc.err_rms;
                clean_flips += rc.dir_flips;
            }
        }
        printf("  RESULT: clean set (20-160 deg): worst |tail-1| %.5f, worst rms %.5f, "
               "flips %ld; near-aligned set (<=5 / >=175 deg): best tail %.5f, "
               "lowest rms %.5f, fewest flips %ld\n",
               clean_tail_worst, clean_rms_worst, clean_flips,
               collapse_tail_best, collapse_rms_worst_low, collapse_flips_min);

        // ── The invariant this group measures: the collapse is CONFINED to the
        //    near-aligned pair.  The doEncoderB() phase-tap comment claims the handshake
        //    loses cycles as the phase drifts toward 0.0 or 0.5 pitch; the measurement
        //    bounds that claim from both sides.
        check(clean_tail_worst < 0.01 && clean_flips == 0 && clean_rms_worst < 0.05,
              "near-aligned + jitter: 20-160 deg is UNAFFECTED (tail within 1 %, zero "
              "direction flips, rms at the jitter floor)");
        check(collapse_tail_best < 0.50 && collapse_flips_min > 100
              && collapse_rms_worst_low > 1.0,
              "near-aligned + jitter: every offset within 5 deg of alignment or "
              "anti-alignment DOES collapse (tail under 0.50, > 100 flips, rms > 1.0)");
    }

    // ── (8) DROPOUT WINDOW ───────────────────────────────────────────────────
    test_group("encoder harness: dropout window");
    DefectSpec dw; dw.dropout = true;
    dw.dropout_start_us = 5000000u; dw.dropout_end_us = 5300000u;   // 300 ms of silence
    RunResult rd = run_case(dw, REG_V, REG_T);
    printf("  dropout 300 ms: tail %.5f  window [%.4f, %.4f]  resets %ld  holds %ld"
           "  sat %ld  i_max %.3f A\n",
           rd.basin_ratio, rd.ratio_win_min, rd.ratio_win_max, rd.reset_count,
           rd.hold_ticks, rd.sat_ticks, rd.i_cmd_max);
    check(rd.ratio_win_min < 0.90,
          "dropout 300 ms: the window ratio DOES collapse during the silent span");
    check(rd.reset_count >= 1,
          "dropout 300 ms: the reading-age bound fires (>= 1 staleness reset)");
    check(rd.basin_ratio > 0.95 && rd.basin_ratio < 1.05,
          "dropout 300 ms: the estimator recovers to truth after the window");
    check(rd.i_cmd_max <= MOTOR_I_CMD_MAX + 1e-6,
          "dropout 300 ms: the motor command never exceeds MOTOR_I_CMD_MAX");
}

// ─────────────────────────────────────────────────────────────────────────────
// 9. Sweep mode — report-only grid, one CSV row per run.
// ─────────────────────────────────────────────────────────────────────────────
static const double SWEEP_SPEEDS[] = { 0.3, 0.6, 1.0, 1.5, 2.2, 3.0 };
static const int    N_SPEEDS = (int)(sizeof SWEEP_SPEEDS / sizeof SWEEP_SPEEDS[0]);

static void sweep_row(FILE* csv, const char* family, double param, long slot,
                      double v, const RunResult& r) {
    fprintf(csv, "%s,%.4f,%ld,%.2f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%ld,%ld,%ld,%ld,%ld,%.4f,%ld,%ld,%ld,%ld,%.0f\n",
            family, param, slot, v,
            r.v_true_final, r.v_actual_final, r.basin_ratio,
            r.ratio_win_min, r.ratio_win_max, r.err_rms, r.err_max,
            r.hold_ticks, r.reset_count, r.phase_clears, r.dir_flips, r.sat_ticks,
            r.i_cmd_max, r.edges_fired,
            r.drop_raw_floor, r.drop_low_gate, r.drop_pitch_floor, r.ref_us_final);
}

// A run is "interesting" when either the SETTLED reading or any 50-tick window inside the
// scored span leaves the band.  The trace dump is keyed on this - the spec asks for a per-tick
// trace only where the basin ratio ENDS outside [0.95, 1.05], widened here to the transient
// statistic because the settled ratio alone never fires for a bounded single-slot defect (see
// the doc's measured findings).
static bool basin_ok(const RunResult& r) {
    return r.basin_ratio >= 0.95 && r.basin_ratio <= 1.05 &&
           r.ratio_win_min >= 0.90 && r.ratio_win_max <= 1.10;
}

static int run_sweep(const char* out_dir, double duration_s) {
    char path[1024];
    snprintf(path, sizeof path, "%s/encoder_sweep.csv", out_dir);
    FILE* csv = fopen(path, "w");
    if (!csv) { printf("ERROR: cannot write %s\n", path); return 1; }
    fprintf(csv, "family,param,slot,v_cruise,v_true_final,v_actual_final,basin_ratio,"
                 "ratio_win_min,ratio_win_max,err_rms,err_max,hold_ticks,reset_count,phase_clears,dir_flips,sat_ticks,"
                 "i_cmd_max,edges_fired,drop_raw_floor,drop_low_gate,drop_pitch_floor,"
                 "ref_us_final\n");

    long runs = 0, outside = 0, traces = 0;
    // The per-tick trace is written only for runs the band test flags, and only for the first
    // TRACE_CAP of them: a 20 s run is 20 000 lines, and the flagged set runs to four figures.
    const long TRACE_CAP = 40;
    char trace_path[1024];

    // The 30-position slot axis is derived per speed (see slot_at_time): index i lands at
    // t = 3.5 + 0.35*i seconds, i.e. inside the scored window for every speed in the grid.
    auto sweep_slot = [&](double v, int i) { return slot_at_time(v, 3.5 + 0.35 * (double)i); };

    // ── nominal reference at each speed ──────────────────────────────────────
    for (int s = 0; s < N_SPEEDS; s++) {
        DefectSpec d;
        RunResult r = run_case(d, SWEEP_SPEEDS[s], duration_s);
        sweep_row(csv, "nominal", 0.0, 0, SWEEP_SPEEDS[s], r);
        runs++;
        if (!basin_ok(r)) outside++;
    }

    // ── missing_slots: run length x slot x speed ─────────────────────────────
    static const int MISS_N[] = { 1, 2, 4, 8, 16, 32 };
    for (int p = 0; p < 6; p++)
      for (int i = 0; i < 30; i++)
        for (int s = 0; s < N_SPEEDS; s++) {
            const long kslot = sweep_slot(SWEEP_SPEEDS[s], i);
            DefectSpec d; d.missing_slot = kslot; d.missing_run = MISS_N[p];
            RunResult r = run_case(d, SWEEP_SPEEDS[s], duration_s);
            sweep_row(csv, "missing", MISS_N[p], kslot, SWEEP_SPEEDS[s], r);
            runs++;
            if (!basin_ok(r)) {
                outside++;
                snprintf(trace_path, sizeof trace_path, "%s/trace_missing_n%d_k%ld_v%.1f.csv",
                         out_dir, MISS_N[p], kslot, SWEEP_SPEEDS[s]);
                FILE* tf = (traces < TRACE_CAP) ? fopen(trace_path, "w") : nullptr;
                if (tf) {
                    traces++;
                    fprintf(tf, "tick,v_true,v_actual,i_cmd,ref_us,dir,cnt\n");
                    run_case(d, SWEEP_SPEEDS[s], duration_s, tf);
                    fclose(tf);
                }
            }
        }

    // ── bounce_slots: spacing x slot x speed ─────────────────────────────────
    static const int BOUNCE_US[] = { 50, 150, 250, 400, 600, 900 };
    for (int p = 0; p < 6; p++)
      for (int i = 0; i < 30; i++)
        for (int s = 0; s < N_SPEEDS; s++) {
            const long kslot = sweep_slot(SWEEP_SPEEDS[s], i);
            DefectSpec d; d.bounce_slot = kslot;
            d.bounce_spacing_us = (uint32_t)BOUNCE_US[p];
            RunResult r = run_case(d, SWEEP_SPEEDS[s], duration_s);
            sweep_row(csv, "bounce", BOUNCE_US[p], kslot, SWEEP_SPEEDS[s], r);
            runs++;
            if (!basin_ok(r)) {
                outside++;
                snprintf(trace_path, sizeof trace_path, "%s/trace_bounce_s%d_k%ld_v%.1f.csv",
                         out_dir, BOUNCE_US[p], kslot, SWEEP_SPEEDS[s]);
                FILE* tf = (traces < TRACE_CAP) ? fopen(trace_path, "w") : nullptr;
                if (tf) {
                    traces++;
                    fprintf(tf, "tick,v_true,v_actual,i_cmd,ref_us,dir,cnt\n");
                    run_case(d, SWEEP_SPEEDS[s], duration_s, tf);
                    fclose(tf);
                }
            }
        }

    // ── phase_offset_deg: 0 .. 180 (not slot-positioned) ─────────────────────
    // Swept past 180 deg deliberately: the A-rising period estimator is blind to the offset, and
    // the quadrature DIRECTION decode only inverts once B stops lagging and starts leading, which
    // happens across 180.  A 0-180 sweep would never see the flip it is supposed to locate.
    static const double PHASE_DEG[] = { 0, 2, 5, 10, 20, 30, 45, 60, 75, 90,
                                        105, 120, 135, 150, 160, 170, 175, 178, 179, 180,
                                        181, 182, 185, 190, 200, 225, 270, 315, 340, 355, 358 };
    const int N_PHASE = (int)(sizeof PHASE_DEG / sizeof PHASE_DEG[0]);
    for (int p = 0; p < N_PHASE; p++)
      for (int s = 0; s < N_SPEEDS; s++) {
          DefectSpec d; d.phase_offset_deg = PHASE_DEG[p];
          RunResult r = run_case(d, SWEEP_SPEEDS[s], duration_s);
          sweep_row(csv, "phase", PHASE_DEG[p], 0, SWEEP_SPEEDS[s], r);
          runs++;
          if (!basin_ok(r)) outside++;
      }

    // ── edge_jitter_us: amplitude x seed x speed ─────────────────────────────
    static const double JIT_US[] = { 10, 40, 100, 200, 400 };
    for (int p = 0; p < 5; p++)
      for (int sd = 0; sd < 6; sd++)
        for (int s = 0; s < N_SPEEDS; s++) {
            DefectSpec d; d.jitter_us = JIT_US[p]; d.jitter_seed = (uint32_t)(1000 + sd);
            RunResult r = run_case(d, SWEEP_SPEEDS[s], duration_s);
            sweep_row(csv, "jitter", JIT_US[p], sd, SWEEP_SPEEDS[s], r);
            runs++;
            if (!basin_ok(r)) outside++;
        }

    // ── dropout_window: length x start x speed ───────────────────────────────
    static const int DROP_MS[] = { 20, 60, 150, 400 };
    for (int p = 0; p < 4; p++)
      for (int st = 0; st < 6; st++)
        for (int s = 0; s < N_SPEEDS; s++) {
            DefectSpec d; d.dropout = true;
            d.dropout_start_us = (uint32_t)((4.0 + 0.4 * st) * 1e6);
            d.dropout_end_us   = d.dropout_start_us + (uint32_t)DROP_MS[p] * 1000u;
            RunResult r = run_case(d, SWEEP_SPEEDS[s], duration_s);
            sweep_row(csv, "dropout", DROP_MS[p], st, SWEEP_SPEEDS[s], r);
            runs++;
            if (!basin_ok(r)) outside++;
        }

    fclose(csv);
    printf("\nsweep complete: %ld runs, %ld flagged (settled ratio outside [0.95, 1.05] or a "
           "50-tick window ratio outside [0.90, 1.10]), %ld per-tick traces written (cap %ld)\n",
           runs, outside, traces, TRACE_CAP);
    printf("CSV: %s\n", path);
    return 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// 10. Entry point.  Guarded so test_main.cpp can link run_encoder_defect_regression()
//     into run_tests later without a main() collision (the brief's staging note).
// ─────────────────────────────────────────────────────────────────────────────
#ifndef ENCODER_HARNESS_NO_MAIN
int main(int argc, char** argv) {
    bool sweep = false;
    const char* out_dir = "../logs/encoder_harness";
    const char* verify = nullptr;
    double duration = 20.0;

    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "--sweep") sweep = true;
        else if (a == "--out" && i + 1 < argc) out_dir = argv[++i];
        else if (a == "--duration" && i + 1 < argc) duration = atof(argv[++i]);
        else if (a == "--verify" && i + 1 < argc) verify = argv[++i];
        else if (a == "--help") {
            printf("usage: run_tests_encoder [--sweep [--out DIR] [--duration S]]"
                   " [--verify FILE.csv]\n");
            return 0;
        } else {
            printf("unknown argument: %s\n", argv[i]);
            return 2;
        }
    }

    printf("=== encoder defect harness (WORK_QUEUE 7d) ===\n");
    printf("build: BENCH_TEST=%d HIL_SIM=%d\n", BENCH_TEST, HIL_SIM);

    if (verify) {
        int rc = verify_against_csv(verify);
        printf("\n%d passed, %d failed\n", g_tests_passed, g_tests_failed);
        return (rc == 0 && g_tests_failed == 0) ? 0 : 1;
    }

    if (sweep) {
        printf("mode: SWEEP (report-only), %.1f s per run, out = %s\n", duration, out_dir);
        return run_sweep(out_dir, duration);
    }

    printf("mode: REGRESSION\n");
    run_encoder_defect_regression();
    printf("\n=== %d passed, %d failed ===\n", g_tests_passed, g_tests_failed);
    return g_tests_failed == 0 ? 0 : 1;
}
#endif

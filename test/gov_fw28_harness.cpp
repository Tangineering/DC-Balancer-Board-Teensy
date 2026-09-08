// gov_fw28_harness.cpp — host-native trace generator for the fw v28 governor
// package (the SOURCE SELECTOR, the hysteresis-sliver hold, the k_d hold and
// freeze in single-source windows, the retuned conduction floor and handoff
// thresholds), on top of the fw v27 rev 2 package it generalises (battery-only
// start, relaxing feedforward clip + iso bypass, load-scheduled droop scale
// k_d, g-guard count). Renamed from gov_fw27_harness.cpp at fw v28.
//
// PURPOSE. `tools/governor_model.py` carries a Python port of the firmware's
// share-delivery path. A port is only as good as its evidence, and a
// hand-written expectation table is evidence about the author, not about the
// firmware. This harness compiles the FIRMWARE ITSELF against the same mock
// layer the main suite uses, drives the real functions through a scripted
// command stream, and prints the result as CSV.
// `tools/test_governor_fw28_equivalence.py` drives the Python port through the
// identical stream and compares the two traces.
//
// It is the SIBLING of `gov_ceiling_harness.cpp`, which covers the fw v26
// current-ceiling clamp alone. Same discipline: the stimulus is supplied on
// stdin so the test owns it and this file owns nothing but the plumbing, and a
// coverage change needs no C++ edit.
//
// ⚠️ WHAT THIS CANNOT COMPARE, STATED UP FRONT. The Youla share controller is
// on the do-not-change list and is NOT ported (governor_model fidelity boundary
// 1), so a CLOSED-LOOP tick's commanded ratio is a firmware quantity the port
// only approximates. The MDAC-code comparison is therefore exact on
//   * every OPEN-LOOP tick (the feedforward path is ported in full: clip, iso
//     bypass, proposal walk, ceilings, slew, actuation), and
//   * every DIRECT actuation (`APPLY`, `MDAC`), which is where the k_d schedule
//     and the g-guard actually reach the hardware,
// and the closed-loop stream is compared on the quantities that ARE ported —
// the governor filter, the schedule input, the live k_d, the switch topology,
// the latch/isolation flags and the refusal counters — but not on the codes.
// The test file says the same thing at each assertion; nothing here is compared
// silently.
//
// ⚠️ ONE MORE fw v28 BOUNDARY. F1's disarm-before-open and its conduction gate
// live INLINE in `chargingControl()`'s cruise branch, not in a callable of
// their own, and `chargingControl()` cannot be driven here without the Ag105
// I2C and MPPT state machines. So this harness compares the `powerBalance()`
// side of fw v28 exactly — the selection, the sliver hold, the k_d hold and
// freeze, the sub-gate slew ceiling, the raw-current escape — and the F1
// SEQUENCING property is validated by the firmware's own host-native fixtures
// (`test/test_main.cpp`, design record section 9.1 items 1, 2, 10 and 13), not
// here. The `CHGWIN` command below raises FC_CHARGE_ENABLE so the k_d hold that
// F1's window implies IS compared through the real `updateShareDroopScale()`.
//
// COMMAND STREAM (one command per line, whitespace separated):
//   TICK  sp i_fc i_batt v_bus   one powerBalance() tick; millis/micros +1 ms
//   ARM                          armShareBatteryOnlyStart()
//   RESET                        resetShareControlState()
//   CLIP  tot sp prev            shareFeedforwardClipTarget() at a set filter
//   KDT   tot                    shareDroopScaleTarget() (pure)
//   KDS   tot                    updateShareDroopScale() at a set filter
//   MDAC  g_fc g_bt              setDroopMdac() — codes + the g-guard count
//   APPLY r                      applyShareRatio() under the live k_d
//   SETKD kd                     force shareDroopKd (to stage a STALE schedule)
//   SETFILT tot                  force share_govTotAFilt
//   SETPREV r                    force droopSlew_prev
//   SETSPEFF r                   force share_spEffPrev (to stage a sliver hold)
//   CHGWIN 0|1                   drive FC_CHARGE_ENABLE (the fw v28 F4 window)
//   SETSEL 0|1                   force shareSelectorFC (0 = BT, 1 = FC)
//
// Every command prints exactly one CSV row, so the trace is index-aligned with
// the stimulus and a divergence names its own row.
//
// BUILD (MSYS2 UCRT64):
//   g++ -std=c++17 -I. -I../teensy_controller -I../controller_design \
//       -I../controller_design_MIMO -DBENCH_TEST=0 -DHIL_SIM=0 \
//       -DNO_ETH_WARNING -Wno-unused-function \
//       gov_fw28_harness.cpp -o gov_fw28_harness

#include "mock_arduino.h"
#include "mock_wire.h"
#include "mock_spi.h"
#include "mock_vesc.h"
#include "mock_ethernet.h"
#include "mock_sd.h"

#include "../teensy_controller/teensy_controller.ino"

#include <cstdio>
#include <cstring>

// %.9g reproduces a float exactly in decimal, so every comparison downstream is
// a value comparison and not a formatting comparison.
static void emit(const char* op) {
    std::printf("%s,%.9g,%.9g,%.9g,%.9g,%u,%u,%.9g,%.9g,%d,%d,%d,%d,%d,%d,%d,%d,"
                "%d,%d,%lu,%lu,%u,%d,%.9g,%.9g\n",
                op,
                (double)droopSlew_prev,
                (double)droop_gain_FC_actual,
                (double)droop_gain_BT_actual,
                (double)shareDroopKd,
                (unsigned)mdacLastCodeFC,
                (unsigned)mdacLastCodeBT,
                (double)share_govTotAFilt,
                (double)shareKdSchedTot,
                digitalRead(FC_BUS_ENABLE) == HIGH ? 1 : 0,
                digitalRead(BT_BUS_ENABLE) == HIGH ? 1 : 0,
                shareIsoFC ? 1 : 0,
                shareIsoBT ? 1 : 0,
                shareSpCutFC ? 1 : 0,
                shareSpCutBT ? 1 : 0,
                shareCutDeferredFC ? 1 : 0,
                shareCutDeferredBT ? 1 : 0,
                shareBatteryOnlyArmed ? 1 : 0,
                shareBatteryOnlyActive ? 1 : 0,
                (unsigned long)shareCutRefusedLoad,
                (unsigned long)shareCutRefusedBlank,
                (unsigned)shareGGuardCount,
                // fw v28 observables: the SELECTION (aux bit 7 on the wire),
                // the tick's slew ceiling (review S7's sub-gate rule is only
                // visible here) and the reference the sliver hold assigns.
                shareSelectorFC ? 1 : 0,
                (double)shareSlewStepThisTick,
                (double)share_spEffPrev);
}

// The scalar-returning commands print their return value in an extra column so
// a pure function can be compared without going through any loop state.
static void emit_val(const char* op, double v) {
    std::printf("%s=%.9g,", op, v);
    emit("v");
}

int main() {
    // Boot the pins the share path reads. FC_BUS/BT_BUS start HIGH (the Run
    // topology every walk models), both boosts enabled, no charge window.
    // Driven through digitalWrite rather than writeBusSwitch so no rising-edge
    // blanking stamp exists at t = 0 — an unknown edge is treated as old by
    // busSwitchBlanked(), which is the port's own convention.
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    digitalWrite(FC_REG_ENABLE, HIGH);
    digitalWrite(BT_REG_ENABLE, HIGH);
    digitalWrite(FC_CHARGE_ENABLE, LOW);
    V_bus = 16.0f;

    std::printf("op,r,g_fc,g_bt,k_d,code_fc,code_bt,filt,sched_tot,"
                "sw_fc,sw_bt,iso_fc,iso_bt,cut_fc,cut_bt,def_fc,def_bt,"
                "armed,active,ref_load,ref_blank,g_clamp,sel_fc,slew,sp_eff\n");

    char op[32];
    while (std::scanf("%31s", op) == 1) {
        if (std::strcmp(op, "TICK") == 0) {
            double sp = 0, ifc = 0, ibt = 0, vb = 16.0;
            if (std::scanf("%lf %lf %lf %lf", &sp, &ifc, &ibt, &vb) != 4) break;
            power_share_setpoint = (float)sp;
            I_fc   = (float)ifc;
            I_batt = (float)ibt;
            V_bus  = (float)vb;
            g_mock_millis += 1;
            g_mock_micros += 1000;
            powerBalance();
            emit("TICK");
        } else if (std::strcmp(op, "ARM") == 0) {
            armShareBatteryOnlyStart();
            emit("ARM");
        } else if (std::strcmp(op, "RESET") == 0) {
            resetShareControlState();
            emit("RESET");
        } else if (std::strcmp(op, "CLIP") == 0) {
            double tot = 0, sp = 0, prev = 0;
            if (std::scanf("%lf %lf %lf", &tot, &sp, &prev) != 3) break;
            share_govTotAFilt = (float)tot;
            emit_val("CLIP",
                     (double)shareFeedforwardClipTarget((float)sp, (float)prev));
        } else if (std::strcmp(op, "KDT") == 0) {
            double tot = 0;
            if (std::scanf("%lf", &tot) != 1) break;
            emit_val("KDT", (double)shareDroopScaleTarget((float)tot));
        } else if (std::strcmp(op, "KDS") == 0) {
            double tot = 0;
            if (std::scanf("%lf", &tot) != 1) break;
            share_govTotAFilt = (float)tot;
            updateShareDroopScale();
            emit("KDS");
        } else if (std::strcmp(op, "MDAC") == 0) {
            double gfc = 0, gbt = 0;
            if (std::scanf("%lf %lf", &gfc, &gbt) != 2) break;
            droop_gain_FC_actual = (float)gfc;
            droop_gain_BT_actual = (float)gbt;
            setDroopMdac((float)gfc, (float)gbt);
            emit("MDAC");
        } else if (std::strcmp(op, "APPLY") == 0) {
            double r = 0;
            if (std::scanf("%lf", &r) != 1) break;
            applyShareRatio((float)r);
            emit("APPLY");
        } else if (std::strcmp(op, "SETKD") == 0) {
            double kd = 0;
            if (std::scanf("%lf", &kd) != 1) break;
            shareDroopKd = (float)kd;
            emit("SETKD");
        } else if (std::strcmp(op, "SETFILT") == 0) {
            double tot = 0;
            if (std::scanf("%lf", &tot) != 1) break;
            share_govTotAFilt = (float)tot;
            emit("SETFILT");
        } else if (std::strcmp(op, "SETPREV") == 0) {
            double r = 0;
            if (std::scanf("%lf", &r) != 1) break;
            droopSlew_prev = (float)r;
            emit("SETPREV");
        } else if (std::strcmp(op, "SETSPEFF") == 0) {
            double r = 0;
            if (std::scanf("%lf", &r) != 1) break;
            share_spEffPrev = (float)r;
            emit("SETSPEFF");
        } else if (std::strcmp(op, "CHGWIN") == 0) {
            int on = 0;
            if (std::scanf("%d", &on) != 1) break;
            // digitalWrite, not assertFcChargeEnable(): the harness is staging
            // the PIN the fw v28 k_d hold reads, not exercising the charge
            // path's own mutual-exclusion guard (which would move BT_BUS).
            digitalWrite(FC_CHARGE_ENABLE, on ? HIGH : LOW);
            emit("CHGWIN");
        } else if (std::strcmp(op, "SETSEL") == 0) {
            int fc = 0;
            if (std::scanf("%d", &fc) != 1) break;
            shareSelectorFC = (fc != 0);
            emit("SETSEL");
        } else {
            std::fprintf(stderr, "unknown op '%s'\n", op);
            return 2;
        }
    }
    return 0;
}

// gov_fw27_harness.cpp — host-native trace generator for the fw v27 rev 2
// governor package (battery-only start, relaxing feedforward clip + iso bypass,
// load-scheduled droop scale k_d, g-guard count).
//
// PURPOSE. `tools/governor_model.py` carries a Python port of the firmware's
// share-delivery path. A port is only as good as its evidence, and a
// hand-written expectation table is evidence about the author, not about the
// firmware. This harness compiles the FIRMWARE ITSELF against the same mock
// layer the main suite uses, drives the real functions through a scripted
// command stream, and prints the result as CSV.
// `tools/test_governor_fw27_equivalence.py` drives the Python port through the
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
//
// Every command prints exactly one CSV row, so the trace is index-aligned with
// the stimulus and a divergence names its own row.
//
// BUILD (MSYS2 UCRT64):
//   g++ -std=c++17 -I. -I../teensy_controller -I../controller_design \
//       -I../controller_design_MIMO -DBENCH_TEST=0 -DHIL_SIM=0 \
//       -DNO_ETH_WARNING -Wno-unused-function \
//       gov_fw27_harness.cpp -o gov_fw27_harness

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
                "%d,%d,%lu,%lu,%u\n",
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
                (unsigned)shareGGuardCount);
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
                "armed,active,ref_load,ref_blank,g_clamp\n");

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
        } else {
            std::fprintf(stderr, "unknown op '%s'\n", op);
            return 2;
        }
    }
    return 0;
}

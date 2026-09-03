// gov_ceiling_harness.cpp — host-native trace generator for the fw v26 source
// current-ceiling clamp.
//
// PURPOSE. `tools/governor_model.py` carries a Python port of
// `applyShareCurrentCeilings()`. A port is only as good as its evidence, and a
// hand-written expectation table is evidence about the author, not about the
// firmware. This harness compiles the FIRMWARE ITSELF against the same mock
// layer the main suite uses, drives the real function through a scripted
// sequence of (filtered total, setpoint) pairs, and prints the result as CSV.
// `tools/test_governor_ceiling_equivalence.py` drives the Python port through
// the identical sequence and compares the two traces exactly.
//
// The sequence is supplied on stdin, one `tot sp` pair per line, so the test
// owns the stimulus and this file owns nothing but the plumbing. That keeps a
// stimulus change out of the C++ build.
//
// WHY THE CLAMP AND NOT THE WHOLE LOOP. `applyShareCurrentCeilings()` reads
// exactly one piece of state it does not own, `share_govTotAFilt`, and writes
// exactly two flags. Driving it directly therefore exercises the clamp's whole
// contract — the ordering, the hysteresis and the band constraint — without
// standing up the state machine, and a divergence in the trace is a divergence
// in the clamp rather than in some upstream fixture.
//
// BUILD (MSYS2 UCRT64):
//   g++ -std=c++17 -I. -I../teensy_controller -I../controller_design \
//       -I../controller_design_MIMO -DBENCH_TEST=0 -DHIL_SIM=0 \
//       -DNO_ETH_WARNING -Wno-unused-function \
//       gov_ceiling_harness.cpp -o gov_ceiling_harness

#include "mock_arduino.h"
#include "mock_wire.h"
#include "mock_spi.h"
#include "mock_vesc.h"
#include "mock_ethernet.h"
#include "mock_sd.h"

#include "../teensy_controller/teensy_controller.ino"

#include <cstdio>

int main() {
    // Start from the boot state the firmware boots into.
    clearShareCeilingState();
    std::printf("tot,sp_in,sp_out,fc,bt\n");
    double tot = 0.0, sp = 0.0;
    while (std::scanf("%lf %lf", &tot, &sp) == 2) {
        share_govTotAFilt = (float)tot;
        float out = applyShareCurrentCeilings((float)sp);
        // %.9g reproduces a float exactly in decimal, so the comparison is a
        // value comparison and not a formatting comparison.
        std::printf("%.9g,%.9g,%.9g,%d,%d\n", tot, sp, (double)out,
                    shareGovFcClamped ? 1 : 0, shareGovBtClamped ? 1 : 0);
    }
    return 0;
}

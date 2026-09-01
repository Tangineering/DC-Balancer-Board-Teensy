#!/usr/bin/env bash
# =============================================================================
# mppt_assert_probes.sh — compile-time tripwire probes for the fw v24 Ag105 MPPT
# threshold constants (teensy_controller.ino, "Ag105 MPPT input-voltage threshold
# management" block).
# =============================================================================
#
# WHY THIS EXISTS
# ---------------
# Five static_asserts guard the MPPT/backoff constant family:
#
#   1. CEILING      AG105_MPPT_VOLTS(N_CEIL) <= V_BUS_CHARGED_THRESH - AG105_CHG_PATH_DROP_V
#   2. FLOOR        AG105_MPPT_VOLTS(N_FLOOR) > LIMIT_V_BUS_MIN + 0.25
#   3. ORDERING     N_FLOOR <= N_CEIL
#   4. BACKOFF/FLOOR AG105_CHG_BACKOFF_V > AG105_MPPT_VOLTS(N_FLOOR)
#   5. HYSTERESIS   AG105_CHG_RESUME_V > AG105_CHG_BACKOFF_V + 0.5
#   6. DWELL        AG105_CHG_BACKOFF_DWELL_MS < UV_BUS_DWELL_LATCH_MS   (fw v24 review M4)
#
# A static_assert that is never seen to FAIL is not evidence of anything: it may be
# tautological, may reference the wrong constant, or may have been silently weakened.
# These probes MUTATE one constant at a time and require the compile to FAIL, plus one
# unmutated control probe required to PASS. That is the only way to demonstrate that each
# assert actually binds the value it claims to bind.
#
# HOW TO RUN (manual — deliberately NOT part of run_tests)
# --------------------------------------------------------
#   cd test && bash mppt_assert_probes.sh
#
# It is not wired into the suite because it recompiles the whole translation unit six times
# (~2-3 minutes) for a check that only needs re-running when one of these constants, or one
# of the constants they are derived from (V_BUS_CHARGED_THRESH, LIMIT_V_BUS_MIN,
# UV_BUS_DWELL_LATCH_MS, V_BUS_NOMINAL), is edited.
#
# Uses -fsyntax-only: static_asserts fire in the front end, so no codegen or link is needed.
# Requires the UCRT64 g++ on PATH for cc1plus's DLLs — the script exports it, matching the
# `test` skill.
# =============================================================================

set -u
cd "$(dirname "$0")"
export PATH="/c/msys64/ucrt64/bin:$PATH"

TESTDIR="$PWD"
REPO="$(cd .. && pwd)"
INO="$REPO/teensy_controller/teensy_controller.ino"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0

# run_probe <name> <expect: FAIL|PASS> <sed expression, or "" for unmutated>
#
# The constants are plain unguarded #defines, so the only assumption-free way to mutate one is
# to edit a COPY of the .ino. test_main.cpp reaches the firmware through the RELATIVE include
# "../teensy_controller/teensy_controller.ino", which resolves against the including file's own
# directory — so a two-directory shadow tree ($WORK/<name>/{teensy_controller,test}) makes the
# copy win without touching the real one. Every other header still comes from the real tree via
# the -I list below.
run_probe() {
    local name="$1"
    local expect="$2"
    local sed_expr="$3"

    local dir="$WORK/$name"
    mkdir -p "$dir/teensy_controller" "$dir/test"
    if [ -n "$sed_expr" ]; then
        sed "$sed_expr" "$INO" > "$dir/teensy_controller/teensy_controller.ino"
        if cmp -s "$INO" "$dir/teensy_controller/teensy_controller.ino"; then
            echo "  BAD  $name (the sed expression matched NOTHING — the constant was renamed"
            echo "         or reformatted; update this probe)"
            fail=$((fail + 1))
            return
        fi
    else
        cp "$INO" "$dir/teensy_controller/teensy_controller.ino"
    fi
    cp "$TESTDIR/test_main.cpp" "$dir/test/test_main.cpp"

    local out rc
    out=$(cd "$dir/test" && g++ -std=c++17 -fsyntax-only \
            -I"$TESTDIR" -I"$REPO/teensy_controller" -I"$REPO/controller_design" \
            -I"$REPO/controller_design_MIMO" \
            -DBENCH_TEST=0 -DHIL_SIM=0 -DNO_ETH_WARNING test_main.cpp 2>&1)
    rc=$?

    local got
    if [ $rc -eq 0 ]; then got=PASS; else got=FAIL; fi

    if [ "$got" = "$expect" ]; then
        echo "  OK   $name (compile $got, as expected)"
        pass=$((pass + 1))
    else
        echo "  BAD  $name (compile $got, expected $expect)"
        echo "$out" | grep -i "static assertion\|error:" | head -3 | sed 's/^/         /'
        fail=$((fail + 1))
    fi
}

echo "=== fw v24 Ag105 MPPT static_assert mutation probes ==="
echo "(each mutated probe MUST fail to compile; the control probe MUST compile)"
echo

# 0. CONTROL — the constants exactly as shipped must compile cleanly. If this fails, every
#    other verdict below is meaningless.
run_probe "control-unmutated" PASS ""

# 1. CEILING — 28 counts is 13.464 V, which exceeds V_BUS_CHARGED_THRESH (13.5) minus the
#    AG105_CHG_PATH_DROP_V (0.05) allowance = 13.45. This is the exact mutation the fw v24
#    review M6 finding rejected, so it is the probe that matters most.
run_probe "ceiling-28-breaks-no-hunt" FAIL \
    's/^#define AG105_MPPT_N_CEIL     27/#define AG105_MPPT_N_CEIL     28/'

# 2. FLOOR — 11 counts is 11 + 0.088*11 = 11.968 V, under LIMIT_V_BUS_MIN + 0.25 (12.25).
#    A floor there lets the charger keep pulling the bus into the UV latch.
run_probe "floor-11-touches-UV" FAIL \
    's/^#define AG105_MPPT_N_FLOOR    15/#define AG105_MPPT_N_FLOOR    11/'

# 3. BACKOFF vs FLOOR — a backoff level at or below the lowest commandable threshold means the
#    Ag105's own threshold would cut in before the firmware sheds the load.
run_probe "backoff-below-floor" FAIL \
    's/^#define AG105_CHG_BACKOFF_V       12\.8f/#define AG105_CHG_BACKOFF_V       12.2f/'

# 4. HYSTERESIS — a resume level less than 0.5 V above the backoff level lets a bus sitting at
#    the trip point chatter the RT1987.
run_probe "hysteresis-too-narrow" FAIL \
    's/^#define AG105_CHG_RESUME_V        13\.6f/#define AG105_CHG_RESUME_V        13.0f/'

# 5. DWELL ORDERING (fw v24 review M4) — the backoff dwell must stay under
#    UV_BUS_DWELL_LATCH_MS (20 ms). At 25 ms the load-shed would be slower than the fault it
#    is supposed to precede in the slow-sag case.
run_probe "dwell-exceeds-UV-latch" FAIL \
    's/^#define AG105_CHG_BACKOFF_DWELL_MS 15u/#define AG105_CHG_BACKOFF_DWELL_MS 25u/'

echo
echo "=== probes: $pass ok, $fail bad ==="
[ "$fail" -eq 0 ]

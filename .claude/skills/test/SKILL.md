---
name: test
description: Build and run the host-native firmware test suite (both BENCH_TEST builds) with the correct MSYS2 g++ invocation. Use this whenever tests need to run — after any firmware change, before flashing, when the user says "run the tests", "do the tests pass", "make", or "build" — instead of invoking make or g++ from scratch. Also use it if a test run seems to pass suspiciously fast or results look stale.
---

# Run the host-native test suite

The suite in `test/` compiles `teensy_controller/teensy_controller.ino` natively against mock
Arduino/Wire/SPI/VESC/Ethernet headers. Two builds are required — they compile the same
sources with different `BENCH_TEST` values and BOTH must pass:

- `run_tests` — `-DBENCH_TEST=0` (production fault behavior; the main suite — the count only
  grows, so trust the run output over any number written here)
- `run_tests_bench` — `-DBENCH_TEST=1` (the `doState0()` bench bypass + bring-up subset)

## The trap this skill exists to avoid

Running `mingw32-make` from PowerShell **silently reuses stale binaries**: the Makefile
recipes prefix commands with `PATH="/c/msys64/ucrt64/bin:$(PATH)"`, which does not resolve
under PowerShell, so the build can fail quietly while the old `.exe` still runs and "passes."
A green run against a stale binary is worse than a red run. Therefore: invoke g++ directly
and verify binary timestamps before trusting results.

## Procedure

Run from the repo's `test/` directory. There is no `make` on this machine outside MSYS2;
call the UCRT64 g++ directly (Bash tool, which handles the PATH for DLL resolution):

```bash
cd test
export PATH="/c/msys64/ucrt64/bin:$PATH"
g++ -std=c++17 -Wall -Wextra -I. -I../teensy_controller -I../controller_design \
    -DBENCH_TEST=0 -DNO_ETH_WARNING test_main.cpp -o run_tests
g++ -std=c++17 -Wall -Wextra -Wno-unused-function -I. -I../teensy_controller -I../controller_design \
    -DBENCH_TEST=1 -DNO_ETH_WARNING test_main.cpp -o run_tests_bench
./run_tests
./run_tests_bench
```

Flag rationale (keep these exact — they are load-bearing):
- `-DBENCH_TEST=0` for the main build: the `.ino` defaults `BENCH_TEST=1` via `#ifndef` for
  bench flashing; the suite asserts *production* fault behavior, so it must override to 0.
- `-DNO_ETH_WARNING`: suppresses the deliberate `#warning` on `BENCH_TEST=0 && USE_ETHERNET=0`
  (a real-hardware mis-flash hazard; the test build hits that combination intentionally).
- `-Wno-unused-function` on the bench build only: the full suite's test functions are
  compiled but not called in that pass.

## Verify before reporting

1. **Compile step actually ran and succeeded** — if g++ errored, stop and report; never run
   a pre-existing `.exe` after a failed compile.
2. **Timestamps** — confirm both `.exe` files are newer than `test_main.cpp`,
   `teensy_controller/teensy_controller.ino`, and any mock header touched this session.
3. **Both builds ran** — a report of "tests pass" that covers only one build is incomplete.
4. Report the pass counts from each binary's output explicitly (e.g. "316 production + 6
   bench, all pass"). If any test fails, report the failing test names and output verbatim —
   do not summarize failures away.

New warnings from `-Wall -Wextra` are worth reporting even when tests pass; the codebase is
expected to build clean.

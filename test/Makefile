# Makefile — native unit tests for teensy_controller.ino
# Usage:
#   From MSYS2 UCRT64 terminal:  cd test && make
#   From PowerShell:             make -C test  (after: $env:PATH="C:\msys64\ucrt64\bin;$env:PATH")
#   From any terminal:           make CXX=/path/to/g++
#
# -I. finds the mock/stub headers in this directory (test/)
# -I../teensy_controller finds the firmware sources (the .ino lives in that subfolder)

# On Windows+MSYS2, ensure UCRT64 bin is on PATH for DLL resolution.
# MSYS2 make translates this POSIX path to C:\msys64\ucrt64\bin for Windows child processes.
MSYS2_UCRT64 = /c/msys64/ucrt64/bin

CXX      = g++
# -DBENCH_TEST=0 compiles the PRODUCTION fault behavior (the .ino defaults BENCH_TEST=1 for
# bench flashing via #ifndef). The main suite asserts shipped behavior, so it must build with 0.
# -DHIL_SIM=0 is stated EXPLICITLY here rather than inherited from the .ino's #ifndef default
# (fw v22 HIGH-1). These two suites assert NON-HIL shipped behavior, so a future change to that
# default must not be able to silently convert them into HIL builds again. run_tests_hil below
# passes -DHIL_SIM=1 for the opposite reason.
# -DNO_ETH_WARNING: the .ino warns on BENCH_TEST=0 + USE_ETHERNET=0 (a mis-flash hazard on real
# hardware); the test suite builds that combination deliberately (mocked networking), so suppress.
CXXFLAGS = -std=c++17 -Wall -Wextra -I. -I../teensy_controller -I../controller_design -I../controller_design_MIMO -DBENCH_TEST=0 -DHIL_SIM=0 -DNO_ETH_WARNING
# Second build at -DBENCH_TEST=1 exercises the doState0() bench bypass. The full suite's test
# functions are compiled but not called in this pass, so silence the expected unused warnings.
CXXFLAGS_BENCH = -std=c++17 -Wall -Wextra -Wno-unused-function -I. -I../teensy_controller -I../controller_design -I../controller_design_MIMO -DBENCH_TEST=1 -DHIL_SIM=0 -DNO_ETH_WARNING
# Third build (fw v21): -DHIL_SIM=1 -DUSE_ETHERNET=1 exercises the HIL wiring (updateSensors()'s
# injection branch, receiveCommands()'s HIL_SIM-gated accept path, hilSendTick()) that is compiled
# out entirely in the two builds above. HIL_SIM=1 requires USE_ETHERNET=1 (the .ino #errors
# otherwise). setup()/loop() are never called by the host tests, so USE_ETHERNET=1 does not change
# any existing test's behavior — only new HIL-gated tests exercise the new code paths.
CXXFLAGS_HIL = -std=c++17 -Wall -Wextra -I. -I../teensy_controller -I../controller_design -I../controller_design_MIMO -DBENCH_TEST=0 -DHIL_SIM=1 -DUSE_ETHERNET=1 -DNO_ETH_WARNING

DEPS = mock_arduino.h mock_wire.h mock_spi.h mock_vesc.h mock_ethernet.h mock_sd.h \
       VescUart.h SPI.h Wire.h NativeEthernet.h NativeEthernetUdp.h SdFat.h \
       ../teensy_controller/teensy_controller.ino \
       ../teensy_controller/drive_controller.h ../teensy_controller/drive_controller_coeffs.h \
       ../controller_design_MIMO/drive_replay_vectors.h

.PHONY: all clean

all: run_tests run_tests_bench run_tests_hil
	PATH="$(MSYS2_UCRT64):$(PATH)" ./run_tests
	PATH="$(MSYS2_UCRT64):$(PATH)" ./run_tests_bench
	PATH="$(MSYS2_UCRT64):$(PATH)" ./run_tests_hil

run_tests: test_main.cpp $(DEPS)
	PATH="$(MSYS2_UCRT64):$(PATH)" $(CXX) $(CXXFLAGS) test_main.cpp -o run_tests

run_tests_bench: test_main.cpp $(DEPS)
	PATH="$(MSYS2_UCRT64):$(PATH)" $(CXX) $(CXXFLAGS_BENCH) test_main.cpp -o run_tests_bench

run_tests_hil: test_main.cpp $(DEPS)
	PATH="$(MSYS2_UCRT64):$(PATH)" $(CXX) $(CXXFLAGS_HIL) test_main.cpp -o run_tests_hil

clean:
	rm -f run_tests run_tests.exe run_tests_bench run_tests_bench.exe run_tests_hil run_tests_hil.exe

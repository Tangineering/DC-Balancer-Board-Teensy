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
# bench flashing via #ifndef). The suite asserts shipped behavior, so it must build with 0.
CXXFLAGS = -std=c++17 -Wall -Wextra -I. -I../teensy_controller -DBENCH_TEST=0

.PHONY: all clean

all: run_tests
	PATH="$(MSYS2_UCRT64):$(PATH)" ./run_tests

run_tests: test_main.cpp \
           mock_arduino.h mock_wire.h mock_spi.h mock_vesc.h mock_ethernet.h \
           VescUart.h SPI.h Wire.h NativeEthernet.h NativeEthernetUdp.h \
           ../teensy_controller/teensy_controller.ino
	PATH="$(MSYS2_UCRT64):$(PATH)" $(CXX) $(CXXFLAGS) test_main.cpp -o run_tests

clean:
	rm -f run_tests run_tests.exe

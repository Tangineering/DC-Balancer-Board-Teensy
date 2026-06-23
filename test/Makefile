# Makefile — native unit tests for teensy_controller.ino
# Usage:
#   From MSYS2 UCRT64 terminal:  cd test && make
#   From PowerShell:             make -C test  (after: $env:PATH="C:\msys64\ucrt64\bin;$env:PATH")
#   From any terminal:           make CXX=/path/to/g++
#
# -I. finds the mock/stub headers in this directory (test/)
# -I.. finds teensy_controller.ino for the direct #include in test_main.cpp

# On Windows+MSYS2, ensure UCRT64 bin is on PATH for DLL resolution.
# MSYS2 make translates this POSIX path to C:\msys64\ucrt64\bin for Windows child processes.
MSYS2_UCRT64 = /c/msys64/ucrt64/bin

CXX      = g++
CXXFLAGS = -std=c++17 -Wall -Wextra -I. -I..

.PHONY: all clean

all: run_tests
	PATH="$(MSYS2_UCRT64):$(PATH)" ./run_tests

run_tests: test_main.cpp \
           mock_arduino.h mock_wire.h mock_spi.h mock_vesc.h mock_ethernet.h \
           VescUart.h SPI.h Wire.h NativeEthernet.h NativeEthernetUdp.h \
           ../teensy_controller.ino
	PATH="$(MSYS2_UCRT64):$(PATH)" $(CXX) $(CXXFLAGS) test_main.cpp -o run_tests

clean:
	rm -f run_tests run_tests.exe

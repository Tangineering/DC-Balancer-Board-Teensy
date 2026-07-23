#pragma once
#include <vector>
#include <cstdint>

// ── VescUart mock ─────────────────────────────────────────────────────────────
// Stubs setSerialPort() and captures setCurrent() calls. Also mocks the read API
// (getFWversion()/getVescValues()) used by State 98's 'E'/'W' commands: seed data/
// fw_version and the *_result flags, then assert on the *_calls counters (the mock
// Serial print/println are no-ops, so tests check that reads were invoked, not text).

class VescUart {
public:
    float              last_current = 0;
    std::vector<float> current_calls;

    // Mirrors the real dataPackage members the firmware touches. `error` is a plain
    // uint8_t (the real type is mc_fault_code, an int-backed enum) — the firmware reads
    // it as (int)vesc.data.error so both compile.
    struct {
        float avgMotorCurrent = 0, avgInputCurrent = 0, dutyCycleNow = 0, rpm = 0,
              inpVoltage = 0, ampHours = 0, ampHoursCharged = 0, wattHours = 0,
              wattHoursCharged = 0, tempMosfet = 0, tempMotor = 0, pidPos = 0;
        long  tachometer = 0, tachometerAbs = 0;
        uint8_t id = 0;
        uint8_t error = 0;
    } data;

    struct { uint8_t major = 0, minor = 0; } fw_version;

    bool getValues_result = true;  int getValues_calls = 0;
    bool getFW_result     = true;  int getFW_calls     = 0;

    void setSerialPort(void*) {}

    void setCurrent(float a) {
        last_current = a;
        current_calls.push_back(a);
    }

    bool getVescValues() { getValues_calls++; return getValues_result; }
    bool getFWversion()  { getFW_calls++;     return getFW_result; }

    void reset() {
        last_current = 0;
        current_calls.clear();
        data = {};
        fw_version = {};
        getValues_result = true;  getValues_calls = 0;
        getFW_result     = true;  getFW_calls     = 0;
    }
};

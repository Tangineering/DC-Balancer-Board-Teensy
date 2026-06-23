#pragma once
#include <vector>

// ── VescUart mock ─────────────────────────────────────────────────────────────
// Stubs setSerialPort() and captures setCurrent() calls.

class VescUart {
public:
    float              last_current = 0;
    std::vector<float> current_calls;

    void setSerialPort(void*) {}

    void setCurrent(float a) {
        last_current = a;
        current_calls.push_back(a);
    }

    void reset() {
        last_current = 0;
        current_calls.clear();
    }
};

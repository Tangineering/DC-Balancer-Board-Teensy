#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#include <vector>
#include <queue>
#include <string>
#include <sstream>
#include <type_traits>
#include <algorithm>

// ── Arduino primitive types ───────────────────────────────────────────────────
typedef unsigned char  byte;

// ── Arduino constants ─────────────────────────────────────────────────────────
#define HIGH 1
#define LOW  0
#define OUTPUT 1
#define INPUT  0
#define INPUT_PULLUP 2
#define CHANGE 3
#define FALLING 2
#define RISING  3

// Print-base constants
#define HEX 16
#define DEC 10
#define OCT  8
#define BIN  2

// Arduino macro (x clamped to [lo, hi])
#define constrain(x, lo, hi) \
    ((x) < (lo) ? (lo) : ((x) > (hi) ? (hi) : (x)))

// ceil is in <math.h>

// ── Mock time ─────────────────────────────────────────────────────────────────
inline uint32_t g_mock_millis = 0;
inline uint32_t g_mock_micros = 0;

inline uint32_t millis()  { return g_mock_millis; }
inline uint32_t micros()  { return g_mock_micros; }
inline void delay(unsigned long)             {}
inline void delayMicroseconds(unsigned int)  {}

// ── Mock analog ───────────────────────────────────────────────────────────────
inline int g_analog_pin[50] = {};   // analogRead() returns g_analog_pin[pin]
inline void analogReadResolution(int) {}
inline void analogReadAveraging(int) {}
inline int  analogRead(int pin) { return (pin >= 0 && pin < 50) ? g_analog_pin[pin] : 0; }

// ── Mock GPIO ─────────────────────────────────────────────────────────────────
struct WriteEvent { int pin; int value; };

inline int  g_pin_value[50]  = {};   // current logical pin state
inline int  g_pin_mode[50]   = {};   // pin mode
inline std::vector<WriteEvent> g_write_log;   // ordered log of all digitalWrite calls

inline void pinMode(int pin, int mode) {
    if (pin >= 0 && pin < 50) g_pin_mode[pin] = mode;
}
inline void digitalWrite(int pin, int value) {
    if (pin >= 0 && pin < 50) g_pin_value[pin] = value;
    g_write_log.push_back({pin, value});
}
inline int digitalRead(int pin) {
    return (pin >= 0 && pin < 50) ? g_pin_value[pin] : LOW;
}
inline int  digitalPinToInterrupt(int pin) { return pin; }
inline void attachInterrupt(int, void(*)(), int) {}
inline void noInterrupts() {}
inline void interrupts()   {}

// ── Mock Serial ───────────────────────────────────────────────────────────────
// Template-based so it accepts every type the .ino passes without overload ambiguity.
//
// Output is CAPTURED into `tx` rather than discarded, so tests can assert on what the firmware
// actually prints. That matters for the State-98 Serial-Plotter stream ('L'), whose whole contract
// is the exact wire format — a wrong label or a varying field count silently produces an empty or
// mis-legended graph in the IDE, which no state-flag assertion would catch. The formatting mirrors
// Arduino's Print class closely enough for that purpose: floats default to 2 decimals, the second
// argument is the decimal count for floats and the base for integers.
struct MockSerialClass {
    std::queue<char> rx_queue;
    std::string      tx;   // captured output; cleared by reset_test_state()

    void begin(long) {}
    void setRX(int)  {}
    void setTX(int)  {}

    // Non-template const char* overloads take precedence over templates (exact match)
    void print  (const char* s) { tx += s; }
    void println(const char* s) { tx += s; tx += '\n'; }
    void println()              { tx += '\n'; }   // bare println()

    // Template catch-all: single argument (int, float, uint32_t, String, etc.)
    template<typename T> void print  (T v)           { tx += fmt(v); }
    template<typename T> void println(T v)           { tx += fmt(v); tx += '\n'; }
    // Template catch-all: two arguments (value + base/precision)
    template<typename T> void print  (T v, int opt)  { tx += fmt(v, opt); }
    template<typename T> void println(T v, int opt)  { tx += fmt(v, opt); tx += '\n'; }

    // Backpressure override for plotTick()'s guard: -1 (default) means "host always draining"
    // (4096 B free); a test can set this to a small value to exercise the drop/emit boundary.
    int  availableForWriteOverride = -1;
    int  available() { return (int)rx_queue.size(); }
    int  availableForWrite() { return availableForWriteOverride >= 0 ? availableForWriteOverride : 4096; }
    int  read() {
        if (rx_queue.empty()) return -1;
        char c = rx_queue.front(); rx_queue.pop();
        return (int)c;
    }

    // Test helpers
    void tx_clear()                        { tx.clear(); }
    bool tx_contains(const char* s) const  { return tx.find(s) != std::string::npos; }
    int  tx_count(const char* s) const {
        if (!*s) return 0;
        int n = 0;
        for (size_t p = tx.find(s); p != std::string::npos; p = tx.find(s, p + 1)) n++;
        return n;
    }

private:
    template<typename T> static std::string fmt(T v) {
        if constexpr (std::is_floating_point_v<T>) {
            char buf[40]; snprintf(buf, sizeof(buf), "%.2f", (double)v); return buf;   // Arduino default
        } else {
            std::ostringstream oss; oss << v; return oss.str();
        }
    }
    template<typename T> static std::string fmt(T v, int opt) {
        if constexpr (std::is_floating_point_v<T>) {
            char buf[64]; snprintf(buf, sizeof(buf), "%.*f", opt, (double)v); return buf;
        } else if constexpr (std::is_integral_v<T>) {
            std::ostringstream oss;
            if      (opt == 16) oss << std::hex << std::uppercase << (long long)v;
            else if (opt ==  8) oss << std::oct << (long long)v;
            else                oss << (long long)v;
            return oss.str();
        } else {
            std::ostringstream oss; oss << v; return oss.str();
        }
    }
};

inline MockSerialClass Serial;
inline MockSerialClass Serial1;

// String helper (Arduino String is not available; .ino uses String())
// Provide a minimal shim so String(x) compiles.
struct String {
    std::string s;
    explicit String(float v, int d = 2) {
        char buf[32]; snprintf(buf, sizeof(buf), "%.*f", d, (double)v); s = buf;
    }
    explicit String(int v) { s = std::to_string(v); }
    explicit String(const char* c) : s(c) {}
    operator const char*() const { return s.c_str(); }
    String operator+(const String& o) const { return String((s + o.s).c_str()); }
    String operator+(const char* c)   const { return String((s + c).c_str()); }
};
inline String operator+(const char* c, const String& str) {
    return String((std::string(c) + str.s).c_str());
}

// ── State reset helper ────────────────────────────────────────────────────────
// Call before each test to clear accumulated mock state.
inline void mock_reset() {
    g_mock_millis = 0;
    g_mock_micros = 0;
    memset(g_analog_pin, 0, sizeof(g_analog_pin));
    memset(g_pin_value,  0, sizeof(g_pin_value));
    memset(g_pin_mode,   0, sizeof(g_pin_mode));
    g_write_log.clear();
    while (!Serial.rx_queue.empty()) Serial.rx_queue.pop();
}

#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#include <vector>
#include <queue>
#include <string>
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
struct MockSerialClass {
    std::queue<char> rx_queue;

    void begin(long) {}
    void setRX(int)  {}
    void setTX(int)  {}

    // Non-template const char* overloads take precedence over templates (exact match)
    void print  (const char* s) { (void)s; }
    void println(const char* s) { (void)s; }
    void println()              {}   // bare println()

    // Template catch-all: single argument (int, float, uint32_t, String, etc.)
    template<typename T> void print  (T v)           { (void)v; }
    template<typename T> void println(T v)           { (void)v; }
    // Template catch-all: two arguments (value + base/precision)
    template<typename T> void print  (T v, int opt)  { (void)v; (void)opt; }
    template<typename T> void println(T v, int opt)  { (void)v; (void)opt; }

    int  available() { return (int)rx_queue.size(); }
    int  read() {
        if (rx_queue.empty()) return -1;
        char c = rx_queue.front(); rx_queue.pop();
        return (int)c;
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

#pragma once
// ── Host-native stub for the Teensyduino <EEPROM.h> library (fw v28 rev 3) ───────────────────
// The firmware uses exactly three entry points — read(), write() and update() — on the emulated
// EEPROM of the Teensy 4.1 (4284 bytes, E2END 4283). This stub models the array, the erased
// state (0xFF, as a virgin Teensy reads) and the update()-writes-only-on-change semantics that
// the wear argument in docs/fw28_source_selector.md Revision 3 depends on.
//
// Written as a self-contained header rather than a mock_*.h + shim pair because the firmware
// includes it by the Arduino name; test/EEPROM.h is on the -I. path ahead of any real library.
//
// TEST OBSERVABLES (used by the test_fw28r3_* groups in test_main.cpp):
//   g_mock_eeprom[]            — the backing store, directly readable/writable by a fixture;
//   g_mock_eeprom_writes       — count of cells actually COMMITTED (update() on an unchanged
//                                cell does not increment it — that is the wear property);
//   g_mock_eeprom_update_calls — count of update() CALLS (changed or not);
//   mock_eeprom_reset()        — erase to 0xFF and zero both counters.
#include <stdint.h>
#include <string.h>

#define MOCK_EEPROM_SIZE 4284

inline uint8_t  g_mock_eeprom[MOCK_EEPROM_SIZE];
inline uint32_t g_mock_eeprom_writes       = 0;
inline uint32_t g_mock_eeprom_update_calls = 0;

inline void mock_eeprom_reset() {
    memset(g_mock_eeprom, 0xFF, sizeof(g_mock_eeprom));   // virgin Teensy EEPROM reads 0xFF
    g_mock_eeprom_writes       = 0;
    g_mock_eeprom_update_calls = 0;
}

class MockEEPROMClass {
public:
    uint8_t read(int addr) const {
        if (addr < 0 || addr >= MOCK_EEPROM_SIZE) return 0xFF;
        return g_mock_eeprom[addr];
    }
    void write(int addr, uint8_t value) {
        if (addr < 0 || addr >= MOCK_EEPROM_SIZE) return;
        g_mock_eeprom[addr] = value;
        g_mock_eeprom_writes++;
    }
    void update(int addr, uint8_t value) {
        g_mock_eeprom_update_calls++;
        if (addr < 0 || addr >= MOCK_EEPROM_SIZE) return;
        if (g_mock_eeprom[addr] == value) return;         // no write, no wear
        g_mock_eeprom[addr] = value;
        g_mock_eeprom_writes++;
    }
    uint16_t length() const { return MOCK_EEPROM_SIZE; }
};

inline MockEEPROMClass EEPROM;

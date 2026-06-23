#pragma once
#include <stdint.h>
#include <vector>

// SPISettings stub — the real one takes (speed, bitOrder, dataMode)
struct SPISettings {
    SPISettings(long, int, int) {}
    SPISettings() {}
};

// Bit-order and data-mode constants
#define MSBFIRST 1
#define LSBFIRST 0
#define SPI_MODE0 0
#define SPI_MODE1 1
#define SPI_MODE2 2
#define SPI_MODE3 3

// ── SPI mock ──────────────────────────────────────────────────────────────────
// Captures 16-bit words written via transfer16() for assertion in tests.

struct MockSPIClass {
    std::vector<uint16_t> transfer_log;

    void setMOSI(int) {}
    void setMISO(int) {}
    void setSCK(int)  {}
    void begin()      {}
    void beginTransaction(SPISettings) {}
    void endTransaction() {}

    uint16_t transfer16(uint16_t word) {
        transfer_log.push_back(word);
        return 0;
    }

    void reset() { transfer_log.clear(); }
};

inline MockSPIClass SPI;

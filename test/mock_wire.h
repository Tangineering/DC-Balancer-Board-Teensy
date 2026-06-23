#pragma once
#include <stdint.h>
#include <vector>
#include <queue>
#include <utility>

// ── Wire I2C mock ─────────────────────────────────────────────────────────────
// Records all write sequences (for initAg105Charger() verification).
// Supports an injectable byte queue for scripted read responses (for pollAg105()).

struct I2CWriteRecord {
    uint8_t addr;
    uint8_t reg;
    uint8_t value;
};

struct MockWireClass {
    // Write capture
    std::vector<I2CWriteRecord> write_log;

    // Rx injection — push bytes here before a requestFrom/read call
    std::queue<uint8_t> rx_queue;

    // Set to non-zero to simulate I2C NAK on endTransmission (Arduino error codes 1–5)
    uint8_t next_endtransmission_result = 0;

    // Set to true to make requestFrom return 0 bytes (simulates read failure / NAK)
    bool fail_next_requestfrom = false;

    // Internal transmit buffer
    uint8_t _tx_addr = 0;
    std::vector<uint8_t> _tx_buf;

    void setSDA(int)  {}
    void setSCL(int)  {}
    void begin()      {}

    void beginTransmission(uint8_t addr) {
        _tx_addr = addr;
        _tx_buf.clear();
    }

    void write(uint8_t b) {
        _tx_buf.push_back(b);
    }

    // Returns 0 on success (Arduino convention); returns next_endtransmission_result if set
    uint8_t endTransmission(bool = true) {
        // Capture reg+value pair if this was a config write (2 data bytes)
        if (_tx_buf.size() >= 2) {
            write_log.push_back({_tx_addr, _tx_buf[0], _tx_buf[1]});
        }
        _tx_buf.clear();
        uint8_t result = next_endtransmission_result;
        next_endtransmission_result = 0;   // auto-clear: only fails once per set
        return result;
    }

    // Returns the number of bytes available to read (mimic Arduino)
    uint8_t requestFrom(uint8_t /*addr*/, uint8_t count) {
        if (fail_next_requestfrom) {
            fail_next_requestfrom = false;
            return 0;   // simulate NAK / no bytes available
        }
        return (uint8_t)std::min((size_t)count, rx_queue.size());
    }

    uint8_t read() {
        if (rx_queue.empty()) return 0xFF;
        uint8_t b = rx_queue.front();
        rx_queue.pop();
        return b;
    }

    void reset() {
        write_log.clear();
        while (!rx_queue.empty()) rx_queue.pop();
        _tx_buf.clear();
        _tx_addr = 0;
        next_endtransmission_result = 0;
        fail_next_requestfrom = false;
    }
};

inline MockWireClass Wire;

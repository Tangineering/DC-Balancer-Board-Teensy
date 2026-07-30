#pragma once
#include <stdint.h>
#include <vector>
#include <queue>
#include <utility>
#include <map>
#include <algorithm>

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

    // ── Ag105 register-file emulation ────────────────────────────────────────
    // The firmware now does read-verify-then-write-if-different on the two Ag105 config registers,
    // so a mock that only captures writes cannot exercise it. When `emulate_regs` is on, writes
    // update `reg_file` and a read of register R returns [status_byte][reg_file[R]] — i.e. the mock
    // behaves like a real charger with EPROM. It only synthesizes bytes when `rx_queue` is EMPTY,
    // so tests that script exact byte sequences (pollAg105 status/current decode) still win.
    bool emulate_regs = true;
    std::map<uint8_t, uint8_t> reg_file;   // power-on default for an unset register is 0x00,
                                           // which is also the real Ag105 default (ext-resistor mode)
    uint8_t status_byte = 0x00;            // Table 6 status byte prepended to every read
    uint8_t _last_reg   = 0;               // register pointer set by the preceding 1-byte write

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
            _last_reg = _tx_buf[0];
            // Only commit to the emulated register file if the write is going to be reported as
            // successful — a NAKed write must NOT land, or the read-verify path can't be tested.
            if (emulate_regs && next_endtransmission_result == 0) reg_file[_tx_buf[0]] = _tx_buf[1];
        } else if (_tx_buf.size() == 1) {
            _last_reg = _tx_buf[0];   // register pointer for a following requestFrom (read)
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
        // Synthesize a charger-like response only when no scripted bytes are pending.
        if (emulate_regs && rx_queue.empty()) {
            rx_queue.push(status_byte);
            rx_queue.push(reg_file.count(_last_reg) ? reg_file[_last_reg] : 0x00);
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
        // Emulated charger back to power-on defaults: both config registers 0x00 (ext-resistor
        // mode), which is what a factory Ag105 with no RVS/RCS resistors reads as 4.2V / 1000mA.
        reg_file.clear();
        status_byte  = 0x00;
        _last_reg    = 0;
        emulate_regs = true;
    }
};

inline MockWireClass Wire;

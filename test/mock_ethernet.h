#pragma once
#include <stdint.h>
#include <string.h>
#include <vector>
#include <queue>

// ── IPAddress ─────────────────────────────────────────────────────────────────
struct IPAddress {
    uint8_t bytes[4] = {};
    IPAddress() = default;
    IPAddress(uint8_t a, uint8_t b, uint8_t c, uint8_t d) {
        bytes[0]=a; bytes[1]=b; bytes[2]=c; bytes[3]=d;
    }
};

// ── EthernetClass stub ────────────────────────────────────────────────────────
struct EthernetClass {
    void begin(uint8_t*, IPAddress) {}
};
inline EthernetClass Ethernet;

// ── EthernetUDP mock ──────────────────────────────────────────────────────────
// Supports:
//   - Injecting a fake incoming packet (set fake_packet + fake_packet_size)
//   - Capturing outgoing writes for telemetry verification
struct MockEthernetUDP {
    // Incoming packet injection
    int     fake_packet_size = 0;
    uint8_t fake_packet[64]  = {};

    // Outgoing packet capture
    std::vector<uint8_t> last_written;

    void begin(int) {}

    int parsePacket() { return fake_packet_size; }

    int read(uint8_t* buf, int len) {
        int n = (len < fake_packet_size) ? len : fake_packet_size;
        memcpy(buf, fake_packet, n);
        return n;
    }

    void beginPacket(IPAddress, int) { last_written.clear(); }
    void write(const uint8_t* buf, size_t len) {
        last_written.insert(last_written.end(), buf, buf + len);
    }
    void endPacket() {}

    void reset() {
        fake_packet_size = 0;
        memset(fake_packet, 0, sizeof(fake_packet));
        last_written.clear();
    }
};

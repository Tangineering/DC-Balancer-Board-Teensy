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
    bool operator==(const IPAddress& o) const {
        return memcmp(bytes, o.bytes, 4) == 0;
    }
};

// ── EthernetClass stub ────────────────────────────────────────────────────────
struct EthernetClass {
    void begin(uint8_t*, IPAddress) {}
};
inline EthernetClass Ethernet;

// ── EthernetUDP mock ──────────────────────────────────────────────────────────
// Supports:
//   - Injecting a single fake incoming packet (set fake_packet + fake_packet_size) —
//     the original single-shot fixture used by the pre-HIL command-parsing tests.
//   - Injecting a QUEUE of arbitrary-length packets (queue_packet()), each carrying
//     its own source IP/port, so receiveCommands() can be driven through a sequence
//     of frames of differing lengths (the 22-byte command path and the 35-byte HIL
//     injection path share one socket in the firmware). Mirrors mock_wire.h's
//     injectable rx_queue style. parsePacket()/read() drain the queue first, in
//     FIFO order, before falling back to the legacy single fake_packet fields —
//     tests using only fake_packet/fake_packet_size are unaffected.
//   - Capturing outgoing writes for telemetry/HIL-output verification.
struct QueuedRxPacket {
    std::vector<uint8_t> data;
    IPAddress             ip;
    uint16_t               port = 0;
};

struct MockEthernetUDP {
    // Legacy single-packet injection (pre-HIL fixtures)
    int     fake_packet_size = 0;
    uint8_t fake_packet[64]  = {};

    // Queued multi-packet injection (fw v21 HIL dispatch tests)
    std::queue<QueuedRxPacket> rx_queue;

    // The packet currently staged by the last parsePacket() call (from either source)
    std::vector<uint8_t> current_packet;
    IPAddress            current_remote_ip{192, 168, 1, 100};
    uint16_t             current_remote_port = 5000;

    // Outgoing packet capture
    std::vector<uint8_t> last_written;

    void begin(int) {}

    // Queue an arbitrary-length packet with an explicit source address (defaults match the
    // legacy fixture's implicit Pi address so existing HIL tests don't need to specify one
    // unless they care about hilHostIp/hilHostPort learning).
    void queue_packet(const uint8_t* buf, int len, IPAddress ip = IPAddress(192, 168, 1, 100),
                       uint16_t port = 5000) {
        QueuedRxPacket p;
        p.data.assign(buf, buf + len);
        p.ip   = ip;
        p.port = port;
        rx_queue.push(p);
    }

    int parsePacket() {
        if (!rx_queue.empty()) {
            current_packet    = rx_queue.front().data;
            current_remote_ip = rx_queue.front().ip;
            current_remote_port = rx_queue.front().port;
            rx_queue.pop();
            return (int)current_packet.size();
        }
        if (fake_packet_size > 0) {
            current_packet.assign(fake_packet, fake_packet + fake_packet_size);
            // current_remote_ip/port keep whatever was set (or the default) — legacy fixtures
            // never asserted on remoteIP()/remotePort().
            return fake_packet_size;
        }
        current_packet.clear();
        return 0;
    }

    int read(uint8_t* buf, int len) {
        int n = (len < (int)current_packet.size()) ? len : (int)current_packet.size();
        if (n > 0) memcpy(buf, current_packet.data(), n);
        return n;
    }

    IPAddress remoteIP()   const { return current_remote_ip; }
    uint16_t  remotePort() const { return current_remote_port; }

    void beginPacket(IPAddress, int) { last_written.clear(); }
    void write(const uint8_t* buf, size_t len) {
        last_written.insert(last_written.end(), buf, buf + len);
    }
    void endPacket() {}

    void reset() {
        fake_packet_size = 0;
        memset(fake_packet, 0, sizeof(fake_packet));
        while (!rx_queue.empty()) rx_queue.pop();
        current_packet.clear();
        current_remote_ip   = IPAddress(192, 168, 1, 100);
        current_remote_port = 5000;
        last_written.clear();
    }
};

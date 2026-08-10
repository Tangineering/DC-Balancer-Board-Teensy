#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <string>
#include <map>
#include <vector>
#include <algorithm>

// ── SdFat mock (SdFs / FsFile / SdioConfig) ───────────────────────────────────
// Mirrors ONLY the SdFat surface the .ino's SD bench logger uses:
//   SdFs::begin(SdioConfig)   FsFile SdFs::open(name, flags)   SdFs::card()->isBusy()
//   FsFile::write/preAllocate/truncate/close/openNext/getName/isOpen/operator bool
// Shape follows mock_wire.h: one shared state singleton with capture buffers, one-shot
// self-clearing failure injectors, and a reset() the test harness calls between cases.
//
// The assertion channel is g_sd_state.files: name -> raw byte capture of everything written,
// so a test can decode the header/record/trailer bytes exactly as the host decoder would.
// It doubles as the root-directory listing for the filename-scan path (openNext()).

// SdFat's open flags. Guarded — <fcntl.h> may already define these on the host.
#ifndef O_RDONLY
#define O_RDONLY 0x00
#endif
#ifndef O_WRITE
#define O_WRITE  0x02
#endif
#ifndef O_CREAT
#define O_CREAT  0x40
#endif
#ifndef O_TRUNC
#define O_TRUNC  0x200
#endif

// SDIO config selector — value is irrelevant to the mock, only the type must exist.
#define FIFO_SDIO 1
struct SdioConfig {
    SdioConfig(int = 0) {}
};

struct MockSdState {
    // ── Card / init ──────────────────────────────────────────────────────────
    bool card_present = true;    // false → begin() fails (the "no card" warn-once path)
    bool begin_called = false;
    int  begin_calls  = 0;       // must stay at 1 across a session (sdInitTried latch)

    // ── One-shot failure injection (mock_wire style: self-clearing) ──────────
    bool fail_next_open  = false;
    bool fail_next_write = false;

    // ── Busy emulation: isBusy() returns true and decrements while > 0 ───────
    // Drives the drain-stall / ring-overflow test.
    int busy_ticks = 0;

    // ── Captured file contents (also the root-directory listing) ─────────────
    std::map<std::string, std::string> files;
    std::string last_opened;

    // ── Bookkeeping for the non-byte-stream calls ───────────────────────────
    uint64_t last_prealloc   = 0;
    int      truncate_calls  = 0;
    int      close_calls     = 0;

    void reset() {
        card_present    = true;
        begin_called    = false;
        begin_calls     = 0;
        fail_next_open  = false;
        fail_next_write = false;
        busy_ticks      = 0;
        files.clear();
        last_opened.clear();
        last_prealloc   = 0;
        truncate_calls  = 0;
        close_calls     = 0;
    }
};

inline MockSdState g_sd_state;

class FsFile {
public:
    FsFile() {}

    // ── Byte-stream writes: append to the capture for this file ─────────────
    size_t write(const void* buf, size_t n) {
        if (!_open) return 0;
        if (g_sd_state.fail_next_write) {
            g_sd_state.fail_next_write = false;   // one-shot, same idiom as mock_wire
            return 0;
        }
        const char* p = (const char*)buf;
        g_sd_state.files[_name].append(p, n);
        return n;
    }

    bool preAllocate(uint64_t sz) {
        g_sd_state.last_prealloc = sz;
        return true;
    }

    // Real truncate() cuts the pre-allocated tail back to the write position. The mock never
    // materializes the pre-allocation (files hold only what was written), so it just records
    // the call — the byte capture is already "truncated".
    bool truncate() {
        g_sd_state.truncate_calls++;
        return true;
    }

    void close() {
        if (_open) g_sd_state.close_calls++;
        _open = false;
    }

    // ── Root-directory iteration (the filename-scan path) ───────────────────
    // `this` becomes the next entry; `dir` holds the iteration cursor.
    bool openNext(FsFile* dir, int /*oflag*/ = O_RDONLY) {
        if (dir == nullptr) return false;
        if (dir->_dir_idx >= (int)g_sd_state.files.size()) return false;
        auto it = g_sd_state.files.begin();
        std::advance(it, dir->_dir_idx);
        dir->_dir_idx++;
        _name = it->first;
        _open = true;
        return true;
    }

    size_t getName(char* out, size_t len) {
        if (out == nullptr || len == 0) return 0;
        size_t n = std::min(len - 1, _name.size());
        memcpy(out, _name.data(), n);
        out[n] = '\0';
        return n;
    }

    bool isOpen() const { return _open; }
    explicit operator bool() const { return _open; }

    // Used by SdFs::open() to construct an opened handle.
    void _mock_open(const std::string& name) { _name = name; _open = true; _dir_idx = 0; }

private:
    std::string _name;
    bool        _open    = false;
    int         _dir_idx = 0;   // directory cursor when this handle is used as a dir
};

// card()->isBusy() — the non-blocking drain guard.
struct MockSdCard {
    bool isBusy() {
        if (g_sd_state.busy_ticks > 0) {
            g_sd_state.busy_ticks--;
            return true;
        }
        return false;
    }
};

class SdFs {
public:
    bool begin(SdioConfig) {
        g_sd_state.begin_calls++;
        g_sd_state.begin_called = true;
        return g_sd_state.card_present;
    }

    FsFile open(const char* name, int flags = O_RDONLY) {
        FsFile f;
        if (!g_sd_state.card_present) return f;      // closed handle
        if (g_sd_state.fail_next_open) {
            g_sd_state.fail_next_open = false;       // one-shot
            return f;
        }
        std::string n = (name == nullptr) ? "" : name;
        // Directory open ("/") yields an iterable handle without creating a file entry.
        if (n == "/" || n.empty()) {
            f._mock_open("/");
            return f;
        }
        if (flags & O_TRUNC) g_sd_state.files[n].clear();
        else if (!g_sd_state.files.count(n)) g_sd_state.files[n] = "";
        g_sd_state.last_opened = n;
        f._mock_open(n);
        return f;
    }

    // Delete a file (the header-write-failure cleanup path). Returns false if it wasn't there.
    bool remove(const char* name) {
        if (name == nullptr) return false;
        return g_sd_state.files.erase(std::string(name)) > 0;
    }

    MockSdCard* card() { return &_card; }

private:
    MockSdCard _card;
};

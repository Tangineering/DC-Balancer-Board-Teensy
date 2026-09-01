#!/usr/bin/env python3
"""
Live terminal dashboard for the HIL plant simulator (tools/hil_plant_sim.py).

PRIME DIRECTIVE — LIGHTNESS.  The 1 kHz simulation loop must not pay for this
view.  The hot-path contract is exactly ONE attribute assignment per tick:

    dash.snapshot = {...}          # a small, freshly-built, immutable-by-convention dict

That assignment is atomic under the GIL, so there are no locks, no queues and no
I/O on the simulation path.  Everything else — history rings, sparklines,
formatting, ANSI writes — happens on a DAEMON THREAD that wakes at `refresh_hz`
(default 5 Hz), grabs whatever snapshot happens to be current, and draws it.

The dashboard is therefore SAMPLED, not streamed: it is several — often many —
ticks behind, and it silently drops the ticks between renders.  That is by
design; it is a "roughly what is happening" view, not a trace.  The CSV log and
the BLG remain the record of truth.

Rendering is plain ANSI (ESC[H home, ESC[2J initial clear, ESC[K per line), NOT
curses:
  * curses is unavailable on native Windows Python, and the operator runs this
    from Windows Terminal / MSYS2;
  * a full redraw of ~25 short lines at 5 Hz is trivially cheap.
On Windows 10+ the console needs VT processing enabled; `os.system("")` is the
standard stdlib-only trick that flips it on (it spawns a shell that initialises
the console mode), and we call it once, guarded, at import-free construction
time.  No colorama, no third-party dependency.

If stdout is not a TTY (piped into a file, captured by a test runner), the
dashboard REFUSES to start and says so once — the caller keeps its normal
prints.

Stdlib only.
"""

import collections
import os
import re
import shutil
import sys
import threading
import time

# ── Fault-bit names ──────────────────────────────────────────────────────────
# SOURCE OF TRUTH: teensy_controller.ino's FAULT_* defines, mirrored in
# tools/hil_replay_suite.py (FAULT_NAMES, ~line 90).  Duplicated here rather
# than imported so the dashboard stays a leaf module with no import-time cost
# on the simulator's path; keep the two in step if a bit is ever added.
FAULT_NAMES = (
    (0x0001, "OC_FC"), (0x0002, "UV_BATT"), (0x0004, "OV_BUS"),
    (0x0008, "SWITCH_CONFLICT"), (0x0010, "PI_TIMEOUT/HIL_LINK"),
    (0x0020, "OV_BATT"), (0x0040, "UV_FC"), (0x0080, "OC_BT"),
    (0x0100, "UV_BUS"), (0x0200, "OV_RGN"), (0x0400, "OV_CHG"),
    (0x0800, "I2C_CHARGER"), (0x1000, "CHARGER_STAT"), (0x2000, "INIT_FAIL"),
    (0x4000, "MOT_HOTPLUG"), (0x8000, "ERROR(latched State 99)"),
)

STATE_NAMES = {0: "INIT", 1: "IDLE", 2: "RUN", 3: "FINISH", 98: "TEST", 99: "ERROR"}

# Ag105 reg-0x02 threshold count -> volts (fw v24; AG105_MPPT_VOLTS, .ino:1671-1677).
# Duplicated rather than imported, same rationale as FAULT_NAMES above: 11.0 V at
# count 0, 0.088 V/count. >=251 (Table 7; 0xFF/AG105_MPPT_N_RESISTOR is the boot
# value) means "never written / external-resistor mode" and renders as an
# em-dash, not a bogus volts figure.
_AG105_MPPT_V0 = 11.0
_AG105_MPPT_V_PER_CNT = 0.088

# Bit layout of the 16/17-byte observation frame's switch/aux bytes
# (hil_plant_sim.SW_* / AUX_*; .ino readSwitchState()).
SWITCH_BITS = (
    (0x01, "FC_BUS"), (0x02, "BT_BUS"), (0x04, "MOT_PWR"),
    (0x08, "REGEN"), (0x10, "FC_CHG"), (0x20, "BT_SEQ"),
)
AUX_BITS = (
    (0x01, "FC_REG"), (0x02, "BT_REG"),
    (0x04, "MPPT_DIS"), (0x08, "CBAL_DIS"),
)

SPARK_CHARS = "▁▂▃▄▅▆▇█"
HISTORY_N = 60

CSI = "\x1b["
DASH = "—"


def decode_faults(flags, max_names=None):
    """0x0000 -> 'none'; otherwise the set bit names, comma separated.

    F1: `max_names` caps how many names are spelled out before collapsing the
    rest to '+k more' — used by the dashboard to keep the faults line inside
    the terminal width. Unlimited (the pre-F1 behaviour) when omitted."""
    if not flags:
        return "none"
    names = [n for bit, n in FAULT_NAMES if flags & bit]
    if not names:
        return "0x%04X" % flags
    if max_names is not None and len(names) > max_names:
        shown = names[:max_names]
        return ", ".join(shown) + ", +%d more" % (len(names) - max_names)
    return ", ".join(names)


def sparkline(values, lo=None, hi=None, width=None):
    """Unicode block sparkline over `values` (None entries render as a space).

    F1: `width` (if given) keeps only the most recent `width` samples, so a
    narrow terminal gets a shorter spark instead of one that overflows."""
    if width is not None and width > 0:
        values = list(values)[-width:]
    pts = [v for v in values if v is not None]
    if not pts:
        return ""
    vmin = min(pts) if lo is None else lo
    vmax = max(pts) if hi is None else hi
    if vmax - vmin < 1e-9:
        vmax = vmin + 1e-9
    span = vmax - vmin
    out = []
    for v in values:
        if v is None:
            out.append(" ")
            continue
        f = (v - vmin) / span
        idx = int(f * (len(SPARK_CHARS) - 1) + 0.5)
        out.append(SPARK_CHARS[max(0, min(len(SPARK_CHARS) - 1, idx))])
    return "".join(out)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _visible_len(text):
    """Length of `text` as it will occupy terminal columns -- ANSI SGR color
    codes stripped (they are zero-width on screen). F1 needs this to decide
    whether a line needs truncating without ever cutting inside an escape."""
    return len(_ANSI_RE.sub("", text))


_NUM_WIDTH_RE = re.compile(r"%-?0?(\d+)")


def _num(v, fmt="%7.3f"):
    if v is not None:
        return fmt % v
    # F8: derive the placeholder width from fmt's own field width instead of
    # a fixed 7 -- callers pass fmt="%6.0f" etc. and a mismatched placeholder
    # width made the em-dash jitter the column vs real values.
    m = _NUM_WIDTH_RE.match(fmt)
    width = int(m.group(1)) if m else 7
    return DASH.rjust(width)


class Dashboard:
    """Sampled live view of the HIL simulation.

    Usage:
        dash = Dashboard()
        if dash.start():                 # False if stdout is not a tty
            ...
        try:
            loop:  dash.snapshot = {...}   # the ENTIRE hot-path obligation
        finally:
            dash.stop()

    `stop()` is idempotent and restores the cursor.
    """

    def __init__(self, refresh_hz=5.0, color=None):
        self.refresh_hz = max(0.5, float(refresh_hz))
        self.snapshot = None            # hot-path drop box; plain attribute
        self.color = sys.stdout.isatty() if color is None else bool(color)
        self._thread = None
        self._stop = threading.Event()
        self._stopped = False
        self._started = False
        self.error = None               # one-line reason the renderer died
        self._error_reported = False    # F6: dedupe the death message vs stop()
        # History rings — owned exclusively by the renderer thread.
        self._hist = {k: collections.deque([None] * HISTORY_N, maxlen=HISTORY_N)
                      for k in ("v_act", "share", "V_bus", "I_tot", "I_fc", "I_bt")}

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self):
        """Start the renderer.  Returns False (and prints one line) if stdout is
        not a terminal — the caller should then keep its normal status prints."""
        if self._started:
            return True
        if not sys.stdout.isatty():
            print("[hil] --dash: stdout is not a terminal; dashboard disabled "
                  "(normal status lines kept).")
            return False
        if os.name == "nt":
            # Enable VT/ANSI processing on legacy Windows consoles.  Spawning an
            # empty command through the shell is the stdlib-only way to do it.
            try:
                os.system("")
            except Exception:           # pragma: no cover - defensive
                pass
        sys.stdout.write(CSI + "2J" + CSI + "?25l")   # clear, hide cursor
        sys.stdout.flush()
        self._started = True
        self._thread = threading.Thread(target=self._run, name="hil-dash",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Idempotent teardown: stop the thread, show the cursor, leave the
        terminal usable."""
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        th, self._thread = self._thread, None
        if th is not None:
            th.join(timeout=1.0)
        if self._started:
            try:
                sys.stdout.write(CSI + "?25h\n")
                sys.stdout.flush()
            except Exception:           # pragma: no cover - defensive
                pass
        if self.error and not self._error_reported:
            # F6: the renderer thread itself prints this when it dies (see
            # _run()'s except clause); only print here if it never got the
            # chance to (e.g. the death happened after its own print already
            # ran is the common case and is already covered by the flag it
            # sets there).
            print("[hil] dashboard stopped early: %s" % self.error)
        if self._started:
            # F7 (belt-and-suspenders): re-emit the cursor-show in case a
            # timed-out join let an in-flight frame (or the error path above)
            # write after the earlier restore. Cheap and idempotent.
            try:
                sys.stdout.write(CSI + "?25h")
                sys.stdout.flush()
            except Exception:           # pragma: no cover - defensive
                pass

    # ── renderer thread ──────────────────────────────────────────────────────
    def _run(self):
        period = 1.0 / self.refresh_hz
        try:
            while not self._stop.is_set():
                snap = self.snapshot        # atomic read of the drop box
                if snap is not None:
                    self._sample(snap)
                    rendered = self._render(snap)
                    # F7: stop() may have been signalled (and may already be
                    # mid-teardown, e.g. its 1 s join about to time out) while
                    # we were sampling/rendering above -- re-check right
                    # before the write so a frame in flight cannot land after
                    # stop() has restored the cursor/terminal.
                    if self._stop.is_set():
                        break
                    sys.stdout.write(rendered)
                    sys.stdout.flush()
                self._stop.wait(period)
        except BaseException as exc:        # never propagate into the sim
            self.error = "%s: %s" % (type(exc).__name__, exc)
            try:
                sys.stdout.write(CSI + "?25h\n")
                sys.stdout.write("[hil] dashboard renderer died (%s); "
                                 "simulation continues.\n" % self.error)
                sys.stdout.flush()
                self._error_reported = True     # F6: stop() must not repeat this
            except Exception:
                pass

    def _sample(self, s):
        h = self._hist
        h["v_act"].append(s.get("v_act"))
        h["share"].append(s.get("share_act"))
        h["V_bus"].append(s.get("V_bus"))
        h["I_tot"].append(s.get("I_tot"))
        h["I_fc"].append(s.get("I_fc"))
        h["I_bt"].append(s.get("I_bt"))

    # ── formatting helpers ───────────────────────────────────────────────────
    def _dot(self, on, color=None):
        c = self.color if color is None else color
        if not c:
            return "●" if on else "○"
        return ("\x1b[32m●\x1b[0m" if on else "\x1b[2m○\x1b[0m")

    def _bits(self, value, table, color=None):
        if value is None:
            return DASH
        return "  ".join("%s %s" % (self._dot(value & bit, color=color), name)
                         for bit, name in table)

    def _line(self, text):
        return text + CSI + "K\n"

    def _fit_line(self, text, avail):
        """F1: truncate one rendered line's VISIBLE text to `avail` columns.

        Plain lines (no ANSI) are cut directly -- the visible length equals
        len(text), so a substring can never land inside an escape. A line
        carrying escapes (only the switch/aux dot lines, via `has_color`)
        would need escape-aware slicing to cut safely mid-line; instead of
        that complexity, the caller re-renders those specific lines with
        color forced off before calling here, so by the time a colored line
        reaches `_fit_line` it is always already the plain fallback."""
        if avail is None or avail <= 0 or _visible_len(text) <= avail:
            return text
        return text[:avail]

    def _render(self, s):
        # F1: adapt to the real terminal every frame -- a narrow terminal
        # combined with the ESC[H fixed-line redraw otherwise wraps long
        # lines and permanently corrupts the screen (each redraw re-wraps
        # onto lines the cursor-home math no longer accounts for).
        cols, rows = shutil.get_terminal_size((80, 24))
        avail = max(cols - 1, 20)       # leave the last column alone
        max_lines = max(rows - 1, 5)    # leave the last row alone
        spark_w = max(10, cols - 40)

        # Each entry: (priority, text). priority 0 = always keep; higher
        # numbers are dropped first (in reverse line order) if the frame
        # would otherwise overflow the terminal's row count.
        rows_out = []
        add = lambda t, pri=0: rows_out.append((pri, self._fit_line(t, avail)))

        mode = s.get("mode", "?")
        add("HIL dashboard  t=%7.2f s  %s  [%s]  %.0f Hz view"
            % (s.get("t", 0.0), s.get("source", "?"), mode, self.refresh_hz))
        add("  rate %s Hz achieved   tx=%s rx=%s bad=%s   pi=%s"
            % (_num(s.get("rate_hz"), "%6.0f"), s.get("tx", 0), s.get("rx", 0),
               s.get("bad", 0), s.get("pi", 0)))
        add("", pri=2)

        add("── setpoints ─────────────────────────────────────────────", pri=1)
        add("  v      sp %s   act %s m/s  %s"
            % (_num(s.get("v_sp")), _num(s.get("v_act")),
               sparkline(self._hist["v_act"], width=spark_w)))
        add("  share  sp %s   act %s      %s"
            % (_num(s.get("share_sp")), _num(s.get("share_act")),
               sparkline(self._hist["share"], 0.0, 1.0, width=spark_w)))
        add("", pri=2)

        add("── rails ─────────────────────────────────────────────────", pri=1)
        for key, label, unit in (("V_bus", "V_bus", "V"), ("I_tot", "I_tot", "A"),
                                 ("I_fc", "I_fc ", "A"), ("I_bt", "I_bt ", "A")):
            vals = self._hist[key]
            pts = [v for v in vals if v is not None]
            rng = ("[%.2f..%.2f]" % (min(pts), max(pts))) if pts else ""
            add("  %s %s %s  %s %s" % (label, _num(s.get(key)), unit,
                                       sparkline(vals, width=spark_w), rng))
        add("", pri=2)

        add("── switches ──────────────────────────────────────────────", pri=1)
        for value, table in ((s.get("switch"), SWITCH_BITS), (s.get("aux"), AUX_BITS)):
            colored = "  " + self._bits(value, table)
            # F1: only fall back to the uncolored render when the colored one
            # would actually need cutting -- avoids re-computing on every
            # frame in the common (wide terminal) case.
            if _visible_len(colored) > avail:
                add("  " + self._bits(value, table, color=False))
            else:
                rows_out.append((0, colored))
        add("", pri=2)

        st = s.get("state")
        add("── board ─────────────────────────────────────────────────", pri=1)
        mppt_cnt = s.get("mppt_cnt")
        if mppt_cnt is None or mppt_cnt >= 251:   # >=251 = external-resistor mode (Table 7)
            mppt_str = "—"
        else:
            mppt_str = "%d (%.2fV)" % (
                mppt_cnt, _AG105_MPPT_V0 + _AG105_MPPT_V_PER_CNT * mppt_cnt)
        add("  state %s  I_cmd %s A  I_chg %s A  ag105 %s  mpptCnt=%s"
            % (("%2d %-6s" % (st, STATE_NAMES.get(st, "?"))) if st is not None
               else (DASH + " " * 8),
               _num(s.get("I_cmd")), _num(s.get("I_chg")),
               "—" if s.get("ag105") is None else "0x%02X" % s["ag105"],
               mppt_str))
        # F1: cap the fault names spelled out so a multi-fault line can't
        # blow past the terminal width -- 4 leaves room for the "0x%04X"
        # prefix and a trailing "+k more" even on an 80-col terminal.
        add("  faults 0x%04X  %s"
            % (s.get("faults") or 0, decode_faults(s.get("faults") or 0, max_names=4)))
        if s.get("hifi_hz") is not None:
            add("  hifi   %.1f kHz substep   events %d   chopper peak %s W"
                % (s["hifi_hz"] / 1e3, s.get("hifi_events", 0),
                   _num(s.get("hifi_chopper_w"), "%6.1f")), pri=1)
        else:
            add("", pri=2)
        if s.get("rx", None) == 0 and (s.get("t") or 0.0) > 2.0:
            # F9: the most useful diagnostic when nothing has arrived yet --
            # surfaced in-frame since the 1 Hz status print is suppressed
            # while the dashboard owns the screen.
            add("  ⚠ no observation frames yet — is the board flashed with "
                "-DHIL_SIM=1?", pri=1)
        add("", pri=2)
        add("  (sampled view — several ticks behind by design; Ctrl-C to stop)", pri=1)

        # F1: clamp total lines to the terminal's row count, dropping the
        # lowest-priority lines first (stable order otherwise preserved).
        if len(rows_out) > max_lines:
            keep = sorted(range(len(rows_out)), key=lambda i: rows_out[i][0])[:max_lines]
            keep = sorted(keep)
            rows_out = [rows_out[i] for i in keep]

        L = [CSI + "H"]
        for _, text in rows_out:
            L.append(self._line(text))
        return "".join(L)

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

# Bit layout of the 16-byte observation frame's switch/aux bytes
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


def decode_faults(flags):
    """0x0000 -> 'none'; otherwise the set bit names, comma separated."""
    if not flags:
        return "none"
    names = [n for bit, n in FAULT_NAMES if flags & bit]
    return ", ".join(names) if names else "0x%04X" % flags


def sparkline(values, lo=None, hi=None):
    """Unicode block sparkline over `values` (None entries render as a space)."""
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


def _num(v, fmt="%7.3f"):
    return DASH.rjust(7) if v is None else (fmt % v)


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
        if self.error:
            print("[hil] dashboard stopped early: %s" % self.error)

    # ── renderer thread ──────────────────────────────────────────────────────
    def _run(self):
        period = 1.0 / self.refresh_hz
        try:
            while not self._stop.is_set():
                snap = self.snapshot        # atomic read of the drop box
                if snap is not None:
                    self._sample(snap)
                    sys.stdout.write(self._render(snap))
                    sys.stdout.flush()
                self._stop.wait(period)
        except BaseException as exc:        # never propagate into the sim
            self.error = "%s: %s" % (type(exc).__name__, exc)
            try:
                sys.stdout.write(CSI + "?25h\n")
                sys.stdout.write("[hil] dashboard renderer died (%s); "
                                 "simulation continues.\n" % self.error)
                sys.stdout.flush()
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
    def _dot(self, on):
        if not self.color:
            return "●" if on else "○"
        return ("\x1b[32m●\x1b[0m" if on else "\x1b[2m○\x1b[0m")

    def _bits(self, value, table):
        if value is None:
            return DASH
        return "  ".join("%s %s" % (self._dot(value & bit), name)
                         for bit, name in table)

    def _line(self, text):
        return text + CSI + "K\n"

    def _render(self, s):
        L = [CSI + "H"]
        A = L.append
        add = lambda t: A(self._line(t))

        mode = s.get("mode", "?")
        add("HIL dashboard  t=%7.2f s  %s  [%s]  %.0f Hz view"
            % (s.get("t", 0.0), s.get("source", "?"), mode, self.refresh_hz))
        add("  rate %s Hz achieved   tx=%s rx=%s bad=%s   pi=%s"
            % (_num(s.get("rate_hz"), "%6.0f"), s.get("tx", 0), s.get("rx", 0),
               s.get("bad", 0), s.get("pi", 0)))
        add("")

        add("── setpoints ─────────────────────────────────────────────")
        add("  v      sp %s   act %s m/s  %s"
            % (_num(s.get("v_sp")), _num(s.get("v_act")),
               sparkline(self._hist["v_act"])))
        add("  share  sp %s   act %s      %s"
            % (_num(s.get("share_sp")), _num(s.get("share_act")),
               sparkline(self._hist["share"], 0.0, 1.0)))
        add("")

        add("── rails ─────────────────────────────────────────────────")
        for key, label, unit in (("V_bus", "V_bus", "V"), ("I_tot", "I_tot", "A"),
                                 ("I_fc", "I_fc ", "A"), ("I_bt", "I_bt ", "A")):
            vals = self._hist[key]
            pts = [v for v in vals if v is not None]
            rng = ("[%.2f..%.2f]" % (min(pts), max(pts))) if pts else ""
            add("  %s %s %s  %s %s" % (label, _num(s.get(key)), unit,
                                       sparkline(vals), rng))
        add("")

        add("── switches ──────────────────────────────────────────────")
        add("  " + self._bits(s.get("switch"), SWITCH_BITS))
        add("  " + self._bits(s.get("aux"), AUX_BITS))
        add("")

        st = s.get("state")
        add("── board ─────────────────────────────────────────────────")
        add("  state %s  I_cmd %s A  I_chg %s A  ag105 %s"
            % (("%2d %-6s" % (st, STATE_NAMES.get(st, "?"))) if st is not None
               else (DASH + " " * 8),
               _num(s.get("I_cmd")), _num(s.get("I_chg")),
               "—" if s.get("ag105") is None else "0x%02X" % s["ag105"]))
        add("  faults 0x%04X  %s"
            % (s.get("faults") or 0, decode_faults(s.get("faults") or 0)))
        if s.get("hifi_hz") is not None:
            add("  hifi   %.1f kHz substep   events %d   chopper peak %s W"
                % (s["hifi_hz"] / 1e3, s.get("hifi_events", 0),
                   _num(s.get("hifi_chopper_w"), "%6.1f")))
        else:
            add("")
        add("")
        add("  (sampled view — several ticks behind by design; Ctrl-C to stop)")
        return "".join(L)

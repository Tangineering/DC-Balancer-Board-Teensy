#!/usr/bin/env python3
"""Self-test for the rail-spectral tools. No pytest dependency: plain checks
with a PASS/FAIL counter, like tools/test_decode_benchlog.py.

Run: python tools/rail_spectral/test_rail_spectral.py
Exit code 0 on all-pass, 1 on any failure. Needs numpy + scipy.

Covers:
  (a) blg_arrays.load_blg() agrees with decode_benchlog.decode_blg() record
      for record (t_us, every float channel, fault_flags, flags, and
      encoder_pos on v6) on synthetic v1, v3 and v6 files, including the
      trailer stop and a brownout (truncated, garbage-tailed) file.
  (b) run_windows() on a synthetic run with a 5 mV tone at 2x the motor
      order: rotation rate recovered from encoder_pos, every window steady,
      the tone's peak/sideband ratio far above 4, its amplitude ~5/sqrt(2) mV
      rms, and no comparable peak at an unrelated order.
  (c) a window that contains a fault flag is dropped.
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "benchlog_analysis"))
sys.path.insert(0, str(HERE))   # last = first: the module, not the tools/rail_spectral package

import tempfile  # noqa: E402

import decode_benchlog as D  # noqa: E402
import make_test_blg as M  # noqa: E402
import rail_spectral as RS  # noqa: E402
from blg_arrays import load_blg  # noqa: E402

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"FAIL: {msg}")


def compare_with_decoder(label, blob):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "T.BLG"
        p.write_bytes(blob)
        run = load_blg(p)
    ref = D.decode_blg(blob)
    cols = ref.csv_header.split(",")
    rows = [r.split(",") for r in ref.csv_rows]
    s = run["sig"]
    check(len(s["t_us"]) == ref.records_read,
          f"{label}: record count {len(s['t_us'])} vs decoder {ref.records_read}")
    if len(s["t_us"]) != ref.records_read or not rows:
        return
    col = {c: i for i, c in enumerate(cols)}
    check(all(int(r[col["t_us"]]) == t for r, t in zip(rows, s["t_us"])), f"{label}: t_us")
    for name in RS.VOLT_CH + ["I_fc", "I_batt", "I_cmd", "share_sp", "gFC"]:
        if name not in col:
            continue
        ref_v = np.array([float(r[col[name]]) for r in rows])
        check(np.allclose(ref_v, s[name], rtol=1e-6, atol=1e-9), f"{label}: {name}")
    check(all(int(r[col["flags"]]) == f for r, f in zip(rows, s["flags"])), f"{label}: flags")
    check(all(int(r[col["fault_flags"]]) == f for r, f in zip(rows, s["fault"])), f"{label}: fault_flags")
    if "encoder_pos" in col:
        check(s["enc"] is not None and
              all(int(r[col["encoder_pos"]]) == e for r, e in zip(rows, s["enc"])), f"{label}: encoder_pos")
    else:
        check(s["enc"] is None, f"{label}: no encoder_pos before v6")


def test_loader():
    compare_with_decoder("v1", M.build_blg(1, False, fw_version=1))
    compare_with_decoder("v3", M.build_blg(2, False, fw_version=5, v3=True))
    compare_with_decoder("v6", M.build_blg(3, False, fw_version=16, v6=True))
    compare_with_decoder("v6 wrap", M.build_blg(4, False, wrap=True, fw_version=16, v6=True))
    compare_with_decoder("v6 brownout", M.build_blg(5, True, fw_version=16, v6=True))


def synthetic_run(f_fly=4.0, tone_mv=5.0, fault_at=None, seed=0):
    """A run dict shaped like load_blg() output: steady rotation at f_fly,
    a tone at 2x motor order on V_batt, white noise elsewhere."""
    rng = np.random.default_rng(seed)
    fs, dur, fw = 885.0, 20.0, 18
    t = np.arange(int(fs * dur)) / fs
    n = len(t)
    order = 2 * RS.ORDER_MOTOR
    sig = {c: 8.0 + 1e-4 * rng.standard_normal(n) for c in RS.VOLT_CH + ["I_fc", "I_batt", "I_cmd"]}
    sig["V_batt"] = sig["V_batt"] + tone_mv * 1e-3 * np.sin(2 * np.pi * order * f_fly * t)
    sig["v_act"] = np.full(n, f_fly * 2 * np.pi * RS.R_FLY)
    enc = np.floor(t * f_fly * RS.QUAD_DECODE * RS.encoder_slots(fw)).astype(np.int64)
    fault = np.zeros(n, dtype=np.uint16)
    if fault_at is not None:
        fault[int(fault_at * fs)] = 1
    sig.update(t=t, flags=np.full(n, 0x03, np.uint8), fault=fault, enc=enc)
    return dict(version=6, fw=fw, profile_type=8, hil=False, sig=sig), order


def test_tone():
    run, order = synthetic_run()
    ws = RS.run_windows("SYN", run)
    check(len(ws) > 20, f"window count {len(ws)}")
    check(all(w["steady"] for w in ws), "constant rotation reads steady")
    check(all(abs(w["f_fly"] - 4.0) < 0.02 for w in ws), "f_fly from encoder_pos")
    ratios = [RS.tone_ratio(w, "V_batt", order, w["f_fly"]) for w in ws]
    check(np.median(ratios) > 100, f"tone ratio median {np.median(ratios):.1f}")
    amps = [RS.tone_amplitude(w, "V_batt", order) * 1e3 for w in ws]
    check(abs(np.median(amps) - 5 / np.sqrt(2)) < 0.4, f"tone amplitude {np.median(amps):.2f} mV rms")
    off = [RS.tone_ratio(w, "V_batt", 23.0, w["f_fly"]) for w in ws]
    check(np.median(off) < 4, f"no peak at an unrelated order ({np.median(off):.1f})")
    quiet = [RS.tone_ratio(w, "V_bus", order, w["f_fly"]) for w in ws]
    check(np.median(quiet) < 4, f"no tone on a noise-only channel ({np.median(quiet):.1f})")
    pord = np.nanmedian([w["V_batt_Pord"] for w in ws], 0)
    check(abs(RS.ORD[np.nanargmax(pord[RS.ORD > 5]) + np.argmax(RS.ORD > 5)] - order) < 0.1,
          "order-domain spectrum peaks at the injected order")


def test_fault_window():
    clean, _ = synthetic_run()
    faulty, _ = synthetic_run(fault_at=10.0)
    n_clean = len(RS.run_windows("A", clean))
    n_fault = len(RS.run_windows("B", faulty))
    # a single faulted sample falls in WIN_S / HOP_S = 4 overlapping windows
    check(n_clean - n_fault == int(RS.WIN_S / RS.HOP_S),
          f"faulted windows dropped ({n_clean} -> {n_fault})")


if __name__ == "__main__":
    test_loader()
    test_tone()
    test_fault_window()
    print(f"{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)

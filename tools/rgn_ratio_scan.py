#!/usr/bin/env python3
"""Scan every bench log for the V_rgn / V_bus ratio and the V_rgn regen peaks.

Companion to docs/vrgn_measurement_error_2026-11-05.md. For each logs/*.BLG that carries
V_rgn (BLG format v3+, fw v5+) it reports:

  - fw_version and start_millis (time since boot, minutes) from the BLG header,
  - the median V_rgn / V_bus over samples with V_bus in (15, 18.5) V and V_rgn < V_bus
    (motor node connected and quiet; with MOT_PWR closed V-MOT = V_bus to within the
    RT1987 forward drop, so a correct reading would be ~1.00),
  - the max V_rgn reading and that reading's node voltage (reading / 8.87 = the volts at the
    pin-39 / TL431 REF node), compared with the TL431 reference 2.495 V.

Uses logs/<name>/<name>.csv when present; otherwise decodes the BLG into --decode-dir with
tools/decode_benchlog.py. SY0001 is synthetic (docs/HIL_REPLAY_LOGS.md section 3f) and skipped.

Usage:  python3 tools/rgn_ratio_scan.py [--decode-dir DIR] [--csv OUT.csv]
"""
import argparse
import glob
import os
import re
import struct
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

DIV_GAIN = (78.7 + 10.0) / 10.0   # R1-SNT / R2-SNT (BOM), = SCALE_V_RGN / (ADC_VREF/ADC_MAX)
TL431_VREF = 2.495                # TL431BIDBZR reference, V (TODO(verify: TI TL431 datasheet))
SYNTHETIC = {"SY0001"}


def log_key(path):
    m = re.match(r"([A-Z]+)(\d+)", os.path.basename(path))
    return int(m.group(2)) if m else 0


def header(blg):
    h = open(blg, "rb").read(32)
    ver = h[4]
    fw = struct.unpack_from("<H", h, 18)[0] if ver >= 2 else None
    start_min = struct.unpack_from("<I", h, 8)[0] / 60000.0
    return ver, fw, start_min


def csv_for(name, blg, decode_dir):
    local = os.path.join("logs", name, name + ".csv")
    if os.path.exists(local):
        return local
    out = os.path.join(decode_dir, name + ".csv")
    if not os.path.exists(out):
        subprocess.run([sys.executable, "tools/decode_benchlog.py", "-o", out, blg],
                       capture_output=True, text=True)
    return out if os.path.exists(out) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--decode-dir", default=None)
    ap.add_argument("--csv", default=None, help="also write the table to this CSV")
    args = ap.parse_args()
    decode_dir = args.decode_dir or tempfile.mkdtemp(prefix="rgn_scan_")
    os.makedirs(decode_dir, exist_ok=True)

    rows = []
    for blg in sorted(glob.glob("logs/*.BLG"), key=log_key):
        name = os.path.basename(blg)[:-4]
        if name in SYNTHETIC:
            continue
        ver, fw, start_min = header(blg)
        if ver < 3:
            continue                      # BLG v1/v2 have no V_rgn column
        csv = csv_for(name, blg, decode_dir)
        if csv is None:
            continue
        d = pd.read_csv(csv, usecols=["V_bus", "V_rgn"]).dropna()
        q = d[(d.V_bus > 15.0) & (d.V_bus < 18.5) & (d.V_rgn < d.V_bus)]
        ratio = float(np.median(q.V_rgn / q.V_bus)) if len(q) >= 100 else float("nan")
        vmax = float(d.V_rgn.max())
        rows.append(dict(log=name, fw=fw, uptime_min=round(start_min, 1), n=len(q),
                         ratio=round(ratio, 4), vrgn_max=round(vmax, 3),
                         node_max_V=round(vmax / DIV_GAIN, 3),
                         true_peak_if_linear=round(vmax / ratio, 2) if ratio == ratio else float("nan")))
    t = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(t.to_string(index=False))
    ok = t.dropna(subset=["ratio"])
    print(f"\nlogs with a ratio: {len(ok)}; ratio range {ok.ratio.min():.4f} .. {ok.ratio.max():.4f}")
    print(f"max V_rgn reading: {t.vrgn_max.max():.3f} V -> node {t.vrgn_max.max() / DIV_GAIN:.3f} V "
          f"(TL431 regulates the node at {TL431_VREF} V = a {TL431_VREF * DIV_GAIN:.2f} V reading)")
    if args.csv:
        t.to_csv(args.csv, index=False)


if __name__ == "__main__":
    main()

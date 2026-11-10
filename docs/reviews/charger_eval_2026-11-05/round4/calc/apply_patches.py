#!/usr/bin/env python3
"""Round 4 (r7): apply section patch files to the design document atomically (stdlib only).

Each patch file is JSON: {"group": "<id>", "edits": [{"old": "<exact text>", "new": "<replacement>", "note": "<why>"}, ...]}.
Rules enforced:
  * every "old" string must occur exactly once in the document as it stands when that edit is applied;
  * edits are applied in file-name order, then in list order;
  * if any edit fails, nothing is written (the document is left untouched) and every failure is reported;
  * an "old" string that overlaps an earlier edit's "new" text is allowed only if it still occurs exactly once.
Usage: python -I apply_patches.py --doc DOC --patches DIR [--dry-run]   (DIR is searched recursively for *.json)
"""
import argparse
import glob
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    ap.add_argument("--patches", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    with open(a.doc, encoding="utf-8", newline="") as f:
        text = f.read()
    # The design document uses CRLF throughout; patch strings come with LF. Match and edit on LF, write back CRLF.
    crlf = text.count("\r\n") == text.count("\n") and "\r\n" in text
    if crlf:
        text = text.replace("\r\n", "\n")
    elif "\r" in text:
        print("mixed line endings: refusing to edit")
        return 3
    original_len = len(text)
    # Recursive: group sub-directories (e.g. 10_GA1/patch.json) are applied in sorted path order.
    files = sorted(glob.glob(os.path.join(a.patches, "**", "*.json"), recursive=True))
    if not files:
        print("no patch files in", a.patches)
        return 2
    failures, applied = [], 0
    for fn in files:
        with open(fn, encoding="utf-8") as f:
            try:
                p = json.load(f)
            except json.JSONDecodeError as e:
                failures.append("%s: JSON error %s" % (os.path.basename(fn), e))
                continue
        for i, e in enumerate(p.get("edits", [])):
            old = e.get("old", "").replace("\r\n", "\n")
            new = e.get("new", "").replace("\r\n", "\n")
            tag = "%s[%d] (%s)" % (os.path.basename(fn), i, (e.get("note") or "")[:60])
            if not old:
                failures.append(tag + ": empty old string")
                continue
            n = text.count(old)
            if n != 1:
                head = old[:80].replace("\n", "\\n")
                failures.append("%s: old string occurs %d times: %r" % (tag, n, head))
                continue
            text = text.replace(old, new, 1)
            applied += 1
    print("files: %d, edits applied: %d, failures: %d" % (len(files), applied, len(failures)))
    for f_ in failures:
        print("FAIL", f_)
    print("length %d -> %d characters" % (original_len, len(text)))
    if failures:
        print("document NOT written")
        return 1
    if a.dry_run:
        print("dry run: document NOT written")
        return 0
    if crlf:
        text = text.replace("\n", "\r\n")
    with open(a.doc, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print("document written")
    return 0


if __name__ == "__main__":
    sys.exit(main())

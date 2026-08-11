#!/usr/bin/env python3
"""One-click GUI (and CLI) entry point for the bench-log analysis toolkit.

Flow: pick a .BLG file (tkinter file dialog) -> ingest.ingest() decodes it
into logs/NAME/ -> make_figures.make_all() renders the analysis PNGs into
that same run dir -> a summary is shown to the user and the run dir is
opened in Explorer.

This module is also the PyInstaller entry point for the packaged
BenchLogAnalyzer.exe (see build_exe.ps1). matplotlib is forced to the
"Agg" backend before any figures module is imported so it never tries to
open its own GUI window alongside tkinter.

Usage:
    python analyze_gui.py                      # GUI: file dialog + popups
    python analyze_gui.py path\\to\\FILE.BLG      # GUI, but skip the dialog
    python analyze_gui.py path\\to\\FILE.BLG --no-popup
        # headless / automation: print the summary to stdout, no dialog,
        # no messageboxes, don't open Explorer. Exit 0 on success, exit 1
        # (with the error printed) on failure. This is what the smoke test
        # of the frozen exe uses. NOTE: the frozen (--noconsole) exe has no
        # stdout of its own -- redirect it (`... --no-popup > out.txt`) or
        # the summary is silently discarded.

Unexpected errors in the frozen exe (where no console exists) are appended
to BenchLogAnalyzer_error.log next to the exe, as well as shown in a
messagebox when tkinter is available.
"""
import argparse
import sys
import traceback
from pathlib import Path

# Must happen before any matplotlib-using module (figures/make_figures) is
# imported, anywhere, or matplotlib may pick a GUI backend and fight tkinter.
import matplotlib
matplotlib.use("Agg")

if __package__ in (None, ""):
    # Script mode (and the frozen exe, where this file is the __main__ entry
    # with no package): absolute imports. The sys.path insert is only needed
    # un-frozen -- under PyInstaller it would put the temp extraction dir's
    # PARENT (the user's %TEMP%) on sys.path, where a stray .py could shadow
    # a module; the bundle resolves benchlog_analysis.* by itself.
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from benchlog_analysis import common, ingest_log, make_figures
else:
    from . import common, ingest_log, make_figures


def _read_decode_highlights(run_dir):
    """Pull the human-relevant lines out of decode_report.txt.

    Returns (records_line, trailer_line, warnings) -- each a string or None
    for the first two, and a (possibly empty) list of strings for warnings.
    decode_report.txt is written fresh by every ingest() call, so this
    always reflects the run that was just performed.
    """
    report_path = Path(run_dir) / "decode_report.txt"
    records_line = None
    trailer_line = None
    warnings = []
    if not report_path.exists():
        return records_line, trailer_line, warnings

    with open(report_path, "r") as f:
        lines = [line.rstrip("\n") for line in f]

    for line in lines:
        if "records read:" in line:
            records_line = line
        elif "trailer:" in line or "close_reason=" in line:
            trailer_line = line
        if "WARNING" in line:
            warnings.append(line)

    return records_line, trailer_line, warnings


def run_analysis(blg_path):
    """Headless core: ingest blg_path, render figures, summarize. No GUI.

    Returns a dict:
        run_dir       -- Path to logs/NAME/
        figures       -- list[Path] of rendered figure PNGs (possibly [])
        n_figures     -- len(figures)
        records_line  -- decode_report.txt "records read" line, or None
        trailer_line  -- decode_report.txt trailer/close-reason line, or None
        warnings      -- list[str] of WARNING lines from decode_report.txt

    Raises whatever ingest_log.ingest() or make_figures.make_all() raise;
    callers (GUI or CLI) are responsible for catching and reporting.
    """
    run_dir = ingest_log.ingest(blg_path)

    cfg = common.load_or_create_config(run_dir)
    data = common.load_csv(run_dir / f"{run_dir.name}.csv")
    figures = make_figures.make_all(run_dir, data=data, cfg=cfg)

    records_line, trailer_line, warnings = _read_decode_highlights(run_dir)

    return {
        "run_dir": run_dir,
        "figures": figures,
        "n_figures": len(figures),
        "records_line": records_line,
        "trailer_line": trailer_line,
        "warnings": warnings,
    }


def _format_summary_text(summary):
    lines = []
    lines.append(f"Run directory: {summary['run_dir']}")
    if summary["records_line"]:
        lines.append(summary["records_line"])
    if summary["trailer_line"]:
        lines.append(summary["trailer_line"])
    if summary["warnings"]:
        lines.append("Warnings:")
        for w in summary["warnings"]:
            lines.append(f"  {w}")
    else:
        lines.append("Warnings: none")
    lines.append(f"Figures written: {summary['n_figures']}")
    for fig in summary["figures"]:
        lines.append(f"  {fig}")
    return "\n".join(lines)


def _default_initialdir():
    """Best-effort logs/ dir for the file-open dialog.

    Script mode: repo_root/logs if it exists, else cwd.
    Frozen mode (PyInstaller onefile exe): __file__ / sys.argv[0] point into
    a temp extraction dir, not somewhere meaningful to the user, so instead
    look next to the exe itself (exe_dir/logs), falling back to cwd. This is
    a heuristic -- the user may have the exe anywhere -- but it is a much
    more sensible default than the temp extraction directory.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidate = exe_dir / "logs"
        return str(candidate) if candidate.is_dir() else str(Path.cwd())

    candidate = common.REPO_ROOT / "logs"
    return str(candidate) if candidate.is_dir() else str(Path.cwd())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("blg", nargs="?", default=None,
                     help="path to a .BLG file; if omitted, a file-open "
                          "dialog is shown")
    ap.add_argument("--no-popup", action="store_true",
                     help="print the summary to stdout instead of "
                          "messageboxes, skip opening Explorer -- for "
                          "headless/automated smoke testing")
    args = ap.parse_args(argv)

    blg_path = args.blg

    if blg_path is None:
        import tkinter as tk
        from tkinter import filedialog, messagebox

        root = tk.Tk()
        root.withdraw()

        blg_path = filedialog.askopenfilename(
            title="Select a bench log",
            initialdir=_default_initialdir(),
            filetypes=[("Bench logs", "*.BLG *.blg"), ("All files", "*.*")],
        )
        if not blg_path:
            # User cancelled the dialog -- exit quietly, no error.
            root.destroy()
            return 0

        try:
            summary = run_analysis(blg_path)
        except Exception as e:
            detail = traceback.format_exc()
            messagebox.showerror(
                "Bench log analysis failed",
                f"{e}\n\n{detail}",
            )
            root.destroy()
            return 1

        msg = _format_summary_text(summary)
        messagebox.showinfo("Bench log analysis complete", msg)
        root.destroy()

        import os
        os.startfile(str(summary["run_dir"]))
        return 0

    # blg given on the command line: GUI-less unless popups were requested.
    try:
        summary = run_analysis(blg_path)
    except Exception as e:
        detail = traceback.format_exc()
        if args.no_popup:
            print(f"error: {e}", file=sys.stderr)
            print(detail, file=sys.stderr)
            return 1
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Bench log analysis failed", f"{e}\n\n{detail}")
        root.destroy()
        return 1

    msg = _format_summary_text(summary)

    if args.no_popup:
        print(msg)
        return 0

    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("Bench log analysis complete", msg)
    root.destroy()

    import os
    os.startfile(str(summary["run_dir"]))
    return 0


def _run_guarded():
    """Top-level catch-all so the --noconsole frozen exe never dies invisibly.

    A traceback that escapes main() (tkinter unavailable, Tk() failing,
    os.startfile raising after the root was destroyed, ...) would otherwise
    go to a console the windowed exe does not have. Log it next to the exe
    and best-effort show a messagebox.
    """
    try:
        return main()
    except SystemExit:
        raise
    except Exception:
        detail = traceback.format_exc()
        try:
            if getattr(sys, "frozen", False):
                log_dir = Path(sys.executable).resolve().parent
            else:
                log_dir = Path(__file__).resolve().parent
            with open(log_dir / "BenchLogAnalyzer_error.log", "a") as f:
                f.write(detail + "\n")
        except OSError:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Bench log analysis crashed", detail)
            root.destroy()
        except Exception:
            pass
        print(detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_run_guarded())

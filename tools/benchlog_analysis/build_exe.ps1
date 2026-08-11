# build_exe.ps1 -- package analyze_gui.py into a standalone Windows exe.
#
# Windows PowerShell 5.1 compatible: no `&&`, no ternary, no null-coalescing.
#
# Produces tools/benchlog_analysis/dist/BenchLogAnalyzer.exe (onefile,
# noconsole). All PyInstaller work directories (build cache, .spec file) are
# kept under tools/benchlog_analysis/build so nothing lands at the repo
# root or pollutes the package directory itself.
#
# Usage (from anywhere):
#   powershell -File tools\benchlog_analysis\build_exe.ps1

$ErrorActionPreference = "Stop"

# --- Resolve repo root relative to this script's location ---------------
# This script lives at <repo>\tools\benchlog_analysis\build_exe.ps1
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$PkgDir = $ScriptDir
$RepoRoot = (Resolve-Path (Join-Path $PkgDir "..\..")).Path

$VenvPython = Join-Path $RepoRoot ".venv_benchlog\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "ERROR: Could not find the bench-log venv Python at:`n  $VenvPython`nCreate it first (see tools/benchlog_analysis README) before building the exe."
    exit 1
}

$Entry = Join-Path $PkgDir "analyze_gui.py"
if (-not (Test-Path $Entry)) {
    Write-Host "ERROR: Entry point not found: $Entry"
    exit 1
}

$DistPath = Join-Path $PkgDir "dist"
$BuildPath = Join-Path $PkgDir "build"
$SpecPath = $BuildPath

Write-Host "Repo root:   $RepoRoot"
Write-Host "Venv python: $VenvPython"
Write-Host "Entry point: $Entry"
Write-Host "Dist path:   $DistPath"
Write-Host "Build path:  $BuildPath"
Write-Host ""

# --- Run PyInstaller ------------------------------------------------------
# --paths tools               : lets PyInstaller's import graph resolve
#                                 `import decode_benchlog` (common.py inserts
#                                 tools/ onto sys.path at runtime, but that
#                                 dynamic import needs a --hidden-import too,
#                                 below, since PyInstaller's static analysis
#                                 can't see it).
# --paths tools\benchlog_analysis : likewise for the sibling modules that
#                                 are imported lazily (make_figures/figures)
#                                 or via the script-mode sys.path shim in
#                                 analyze_gui.py.
# --hidden-import decode_benchlog : dynamically imported by
#                                 common.decode_benchlog_module(); PyInstaller's
#                                 static analysis never sees `import
#                                 decode_benchlog` because it happens inside a
#                                 function body behind a sys.path.insert.
# --hidden-import benchlog_analysis.* : belt-and-braces for the package
#                                 modules; analyze_gui.py imports them
#                                 statically so modulegraph usually finds
#                                 them, but the explicit list keeps the
#                                 bundle deterministic. Only the package-
#                                 qualified names are bundled -- a bare
#                                 `figures` copy would be a SECOND module
#                                 object with its own matplotlib state.
$pyinstallerArgs = @(
    "-m", "PyInstaller",
    "--onefile",
    "--noconsole",
    "--name", "BenchLogAnalyzer",
    "--distpath", $DistPath,
    "--workpath", $BuildPath,
    "--specpath", $SpecPath,
    "--noconfirm",
    "--paths", (Join-Path $RepoRoot "tools"),
    "--hidden-import", "decode_benchlog",
    "--hidden-import", "benchlog_analysis.make_figures",
    "--hidden-import", "benchlog_analysis.figures",
    "--hidden-import", "benchlog_analysis.common",
    "--hidden-import", "benchlog_analysis.ingest_log",
    $Entry
)

Write-Host "Running: $VenvPython $($pyinstallerArgs -join ' ')"
Write-Host ""

& $VenvPython @pyinstallerArgs
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "ERROR: PyInstaller failed with exit code $exitCode"
    exit $exitCode
}

$ExePath = Join-Path $DistPath "BenchLogAnalyzer.exe"
if (-not (Test-Path $ExePath)) {
    Write-Host "ERROR: Build reported success but exe not found at: $ExePath"
    exit 1
}

$sizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
Write-Host ""
Write-Host "Build succeeded:"
Write-Host "  $ExePath"
Write-Host "  size: $sizeMB MB"
exit 0

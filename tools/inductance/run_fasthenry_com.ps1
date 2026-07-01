<#
  run_fasthenry_com.ps1 -- headless bridge to the FastFieldSolvers FastHenry2
  COM automation server (ProgID FastHenry2.Document). ONE solve attempt.

  The Windows FastHenry2 distribution ships only the GUI exe, but it is also an
  ActiveX/COM server. This script runs a .inp through it without the GUI and, on
  success, writes the loop inductance to JSON:

      [ { "f": <Hz>, "L": <henries>, "R": <ohms|null> }, ... ]

  GetInductance() returns the REAL effective inductance per (freq,row,col); for a
  single .external port we take [k,0,0]. GetFrequencies() gives the sweep points.

  Reliability: this script does exactly ONE attempt and writes $Out only on a
  non-empty result. The COM server occasionally returns 0 points instantly, and
  once an instance is in that state, recreating it in the SAME PowerShell process
  does not recover -- so RETRIES ARE DRIVEN FROM PYTHON, each a fresh process /
  fresh COM apartment (see fasthenry.run_via_com). Success is signalled purely by
  $Out existing; we never rely on PowerShell function return values (bare COM
  calls like Quit() leak their return into the pipeline).

  Exit code 0 + $Out written  = success.
  Exit code 0 + no $Out        = empty result (caller should retry in a new process).
  Exit code != 0               = hard error (bad deck / timeout).

  Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File run_fasthenry_com.ps1 `
                 -Inp C:\path\loop.inp -Out C:\path\out\fasthenry_com.json
#>
param(
  [Parameter(Mandatory=$true)][string]$Inp,
  [Parameter(Mandatory=$true)][string]$Out,
  [string]$ProgId = 'FastHenry2.Document',
  [int]$TimeoutSec = 7200
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Inp)) { throw "input deck not found: $Inp" }
if (Test-Path $Out) { Remove-Item $Out -Force }

# CRITICAL: FastHenry's COM Run() silently fails (returns True but produces 0
# results) when the input path contains a SPACE -- e.g. "C:\Life Ops\...". Hand it
# the Windows 8.3 SHORT path instead, which has no spaces. (PowerShell's own
# Test-Path / Out-File handle spaces fine; only the COM Run() is space-broken.)
$runPath = (New-Object -ComObject Scripting.FileSystemObject).GetFile($Inp).ShortPath
if ($runPath -match ' ') {
  throw ("Input path has a space and no 8.3 short name is available " +
         "($runPath). Enable 8.3 names on this volume (fsutil 8dot3name) or " +
         "move the project to a space-free path.")
}

# Clear any stale/wedged instance so this process gets a clean server.
$stale = Get-Process FastHenry2 -ErrorAction SilentlyContinue
if ($stale) { $stale | Stop-Process -Force; Start-Sleep -Milliseconds 400 }

$o = New-Object -ComObject $ProgId
try {
  Start-Sleep -Milliseconds 300                     # let the server initialise
  $ok = $o.Run($runPath)
  if (-not $ok) { throw "FastHenry Run() returned false -- check the .inp syntax/path" }
  Start-Sleep -Milliseconds 800                     # let the solve actually start before polling
  $waited = 0
  while ($o.IsRunning()) {
    Start-Sleep -Milliseconds 200
    $waited += 200
    if ($waited -gt ($TimeoutSec * 1000)) { throw "FastHenry still running after $TimeoutSec s" }
  }
  $ind = $o.GetInductance()
  if ($ind.GetLength(0) -eq 0) {
    Write-Output "empty result (0 frequency points) -- caller should retry"
    return                                          # no $Out written -> caller retries
  }
  $freqs = $o.GetFrequencies()
  $res = $null
  try { $res = $o.GetResistance() } catch { $res = $null }
  $n = $ind.GetLength(0)
  $rows = New-Object System.Collections.ArrayList
  for ($k = 0; $k -lt $n; $k++) {
    $R = $null
    if ($res -ne $null) { $R = [double]$res.GetValue($k, 0, 0) }
    [void]$rows.Add([pscustomobject]@{
      f = [double]$freqs[$k]
      L = [double]$ind.GetValue($k, 0, 0)
      R = $R
    })
  }
  ConvertTo-Json -InputObject @($rows.ToArray()) -Depth 5 | Out-File -FilePath $Out -Encoding utf8
  Write-Output ("OK " + $n + " point(s) -> $Out")
}
finally {
  try { [void]$o.Quit() } catch {}
  [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($o)
}

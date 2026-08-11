# Ledger — firmware (teensy_controller/ + test/ + tools/decode_benchlog.py)

Re-raise rule: settled items reopen only with new evidence, stated explicitly.

## Active findings

| ID | Status | Finding | Rationale |
|---|---|---|---|
| FW-R1-F1 | accepted (minor) | SD close (trailer/truncate/close, synchronous in SdFat) can run between State-99 teardown phases; docs overclaim "never blocks/never delays a safety action" | Measured: motor-zero delayed 0 ms at any close cost; teardown dwells stretch max(0,D−10)+1 ms each in an already-safe state (no recorded kill mechanism maps); fix = drain gate on state99Phase<3 + 4 doc rewrites. Codex conceded critical→minor |
| FW-R1-F2 | accepted (major, wrap half) | Decoder truncates valid micros()-wrap-straddling runs: reproduced 50 % row loss + false "power loss" diagnostic; stale-sector half minor (near-unreachable, always warned) | ≈0.93 %/run at random phase; decoder-only modular-step fix proven on repro files; nonce/seq/CRC format change rejected. Thesis-data integrity class |
| FW-R1-F3 | accepted (minor) | Failed/partial directory scan silently O_TRUNCs an existing log (reproduced); named trigger mock-only, bench sibling = mid-scan openNext error | Bounded to one data file; fix = fail-closed root-open + O_EXCL create; Codex conceded major→minor |
| FW-R1-F4 | accepted (minor) | Mid-run write error writes trailer close_reason 0, undocumented | Proven never-stale; fix = LOG_CLOSE_IO_ERROR=6 chain through decoder/docs/test |
| FW-R1-F5 | settled-caveat (minor) | "True 1 kHz" wording overstates; no-backfill sampling is the shared controller rate-limiter semantics, gaps self-disclose via t_us | Working-as-designed with wording debt; fix = decoder gap statistics + PLAN rewording; firmware counters rejected as redundant |
| FW-R1-N1 | accepted (minor, open) | preAllocate(32 MB) + scan at the 'R' keypress (sole live-motor profile start) is the module's largest unbounded stall — mock-blind, est. ≤ ~1 s fragmented FAT32 | Bench-measure; if > ~100 ms, preflight at State-98 entry. From F1 verification |
| FW-R1-N2 | accepted (minor) | decode_benchlog.py has zero automated coverage | Add generator-based self-tests (wrap + brownout files). From F2 verification |

## Notes

- **Fixes applied 2026-08-10 (operator-approved), Codex-ranked order 1–5:** F1 State-99 drain gate
  (`state99Phase` hoisted, drain returns until phase 3; pinned by `test_sdlog_state99_drain_gated`,
  which fails 2 checks without the gate) + the four doc overclaim rewrites; F2 decoder wrap-safe
  modular-step check + trailer close_reason validation + corrected rationale strings; F3 fail-closed
  root-open refusal + `O_EXCL` create (O_TRUNC dropped) + mock `O_EXCL`/openNext injector +
  `test_sdlog_scan_failure_preserves_files`; F4 `LOG_CLOSE_IO_ERROR=6` chain end-to-end (firmware,
  decoder table, PLAN enumeration, trailer-byte assertion); F5 decoder `max_interval_us`/
  `missed_periods` statistics + PLAN wording; N2 `tools/test_decode_benchlog.py` (19 checks: wrap,
  brownout, io_error, gap stats). Also: dead `logRecordCount` wired into 'K' as `sampled:`;
  gap-disclosure assertion added to the rate test. Suite 1018 → **1051 production + 95 bench**, all
  green, zero warnings.
- **Open bench items (rank 6 + F2 residue), to be logged via bench-incident when run:**
  (1) TODO(measure) real-card open-path latency (`preAllocate(32 MB)` + scan) at 'R' start — if
  > ~100 ms, move the preflight to State-98 entry (FW-R1-N1 stays open until measured);
  (2) brownout dirent persistence (no `sync()` in firmware): one Y-run pull-the-plug datapoint.

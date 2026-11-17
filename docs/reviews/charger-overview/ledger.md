# Review ledger: charger-overview (prefix CHGOV)

Target: `hardware/charger_evm_r8/OVERVIEW.md` (short lab-facing overview of the CR / EIB / EVM charger design).
Primary lens: readability for an engineer without project context. Secondary lens: consistency with
`hardware/charger_evm_r8/README.md` and the design record. Re-raise rule: a settled item reopens only with new
evidence, stated explicitly.

| ID | Status | Finding | Rationale |
|---|---|---|---|
| CHGOV-R1-01..12 | accepted | Major readability/fact findings on the first draft (overclaimed hardware independence, release vs charging, mode table, diagram, purge windows, watchdog status, reset, thresholds, FCC sensing, step order, State 99, J1 shape) | Confirmed against the design record F.2, B.7, B.2 and lines 73-87; applied in run 001 |
| CHGOV-R1-13..25 | accepted | Minor/polish readability findings (terms, legend, limits, interconnects, pin 31, links) | Applied in run 001 |
| CHGOV-R1-26 | settled-caveat | Physical detail crowds operating explanation | Reduced, not moved to an appendix; Codex conceded |
| CHGOV-R2-01 | accepted | Input power equated with switch command | Applied |
| CHGOV-R2-02 | accepted | Open decisions not distinguished from untested items | Applied |
| CHGOV-R2-03 | accepted | Figure 1 MB boundary enclosed off-board sources | Applied |

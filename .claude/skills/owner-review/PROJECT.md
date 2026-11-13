# owner-review - project specifics (DC-Balancer thesis repo)

<!-- Read by the `owner-review` skill before every inventory, brief and intake. Everything specific to this repo
lives here. Adapted on 2026-11-13 from the FEA System repo's owner-review skill. -->

## 1. Operator

- **Operator:** Ricky (Ricky Tan). The repo's records call him "the operator". Replace `<owner>` in the brief with
  "Ricky".
- Engineering content (footprint geometry, pin maps, electrical limits, fab capabilities, firmware semantics, HIL
  scoring) closes only on an operator ruling, recorded with his words and the date.

## 2. Registers per work area

| Work area | Decision register | Open-items register | Unattended-run summary | Generator / verify |
|---|---|---|---|---|
| Charger EVM PCB (CR, EIB) | `hardware/charger_evm_r8/LAYOUT_DECISIONS.md` (`D-nn` entries; section 10 `P-nn` proposed design changes) | `LAYOUT_DECISIONS.md` section 11 (numbered `TODO(verify)` items, closed with "Closed <date>" / "Amended <date>"); `bom_2026-11-11/README.md` section 7 for ordering items | `hardware/charger_evm_r8/MORNING_REVIEW_<YYYY-MM-DD>.md` (section 2 decisions, section 3 operator items) | `hardware/charger_evm_r8/gen/` scripts; DRC + `gen/check_constraints.py`; `gen/export.sh` |
| Charger design document | `docs/charger_bq25798_wiring_design_2026-11-05.md` change rows (`r9-nn`) | the same document, J.2 open items | as above | adversarial-doc-review skill |
| Firmware / HIL | `docs/firmware-versions.md`, CLAUDE.md addenda (operator writes CLAUDE.md) | `WORK_QUEUE.md` | `OVERNIGHT_LOG.md` (morning digest) | the `test` skill; `self-review` skill |

Only the orchestration session writes these registers. A review session never does.

## 3. Attribution form

- **Operator ruling:** write "operator ruling <YYYY-MM-DD>" (the form used in `LAYOUT_DECISIONS.md`, for example
  D-41, D-46), with the operator's words quoted.
- **Accepted default:** write "orchestrator default <date>, accepted by the operator <date>" when Ricky accepted a
  proposal or picked one option from a list the orchestrator offered.
- **Source form:** `<review session title> (<local_… id>), chat <YYYY-MM-DD>: "<Ricky's words>"`.
- An amended entry keeps its number; the old text stays with "Superseded:" (the repo supersedes rather than deletes).

## 4. Unattended-run summary file

For the PCB work, the inventory starts from the newest `hardware/charger_evm_r8/MORNING_REVIEW_<date>.md`: section 2
gives the decisions with their reversal paths, and section 3 gives the operator items. For firmware/HIL work, start
from the newest morning digest in `OVERNIGHT_LOG.md`.

## 5. Changes the orchestration session does not apply itself

- `CLAUDE.md`: the operator edits it. Relay the exact text to him.
- `teensy_controller/teensy_controller.ino` and the tests: an execution agent applies the change through the
  `orchestrated-feature` skill, and the `test` and `self-review` skills run before the item closes.
- `references/Scale Car Teensy IO - IO*.csv` and the PSCAD files: the operator's files; edit only on his explicit
  instruction for the named file.
- Board files (`*.kicad_pcb`, footprint libraries, fab packages): never hand-edited. The change goes into the
  `gen/` scripts, the board is regenerated, DRC and the constraint check run, and the package is re-exported.
- `share_controller_coeffs.h`: generated; the `regen-coeffs` skill only.
- A verbatim change to a document (`LAYOUT_DECISIONS.md`, a README, the design document, a review file) is applied
  by the orchestration session under the item's ID.

## 6. Background block

Copy this block verbatim into the `### background` section of every brief.

```
This is the DC-Balancer thesis repo (scale-car fuel-cell/battery DC balancer: Teensy 4.1 firmware, HIL tooling, and the BQ25798 charger EVM boards - the CR carrier and the EIB). Read `CLAUDE.md` and the `owner-review` skill (`.claude/skills/owner-review/SKILL.md` and `PROJECT.md`) first. A design session (the orchestration session) ran the work; items close only on Ricky's ruling, recorded with his words. If the brief names a morning review file, read it first: it holds the run summary and the decisions with their reversal paths. This session is a READ-ONLY review conversation: edit no files, make no commits, change no branch, and do not write `LAYOUT_DECISIONS.md`, the design document, `WORK_QUEUE.md`, `CLAUDE.md` or any board or generator file (only the orchestration session writes them). Order nothing, download nothing, and start no workflow, routing run or HIL suite; if Ricky says yes to one, relay the yes. You may read manufacturer pages and datasheets in place (WebFetch or the built-in browser) to check a value, and you must cite the document, revision and table or figure; if a page is blocked by a bot check, say so and ask Ricky for the value or the PDF path. Bare `python` is the Windows Store stub: use `tools/pcb/.venv/Scripts/python.exe` for pcbnew/KiCad reads and `C:\Users\ricky\miniforge3\python.exe` for numpy work; KiCad CLI is `C:\Program Files\KiCad\9.0\bin\kicad-cli.exe`. Chat style: lead with the point, plain sentences, exact identifiers (refdes, net names, file:line).
```

## 7. Per-round facts

The orchestration session adds these to the brief's per-round line when they hold; they are never part of the fixed
block:

- The branch and commit the session must read (review sessions share the orchestration checkout).
- Another session's uncommitted files in the checkout, by path, with "leave them alone".
- The morning review file of the run, by path.
- A review that ran earlier on the same items, and what it settled.

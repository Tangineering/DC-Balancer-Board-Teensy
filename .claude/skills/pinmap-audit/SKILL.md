---
name: pinmap-audit
description: Audit the firmware against the authoritative hardware sources — pin defines vs the Teensy IO CSV, Ag105 register values vs the extracted datasheet JSON tables, polarity comments, and stale pre-reconciliation names. Use this before any flash, after any pin or register change, when the user asks "does the code still match the hardware/CSV", or when a hardware revision or bodge lands — and remember the CSV wins over the code on any disagreement.
---

# Pin map / register audit

The firmware was once an entire board revision out of date, and single-pin or single-bit
disagreements here destroy hardware (wrong enable pin = hot-plugged boost). The authority
order is fixed: the IO CSV beats the code, the BOM beats assumptions about fitted parts, the
schematic beats both for polarity/connectivity. When the audit finds a disagreement, the
code is what changes — never "fix" the CSV to match the code.

## 1. Pin defines vs the IO CSV

Read `references/Scale Car Teensy IO - IO.csv` and the `#define` pin block at the top of
`teensy_controller/teensy_controller.ino`. Compare **row-for-row, both directions**:

- Every CSV row's `Code Name` appears verbatim as a macro with the CSV's pin number.
- No macro exists that the CSV lacks (an extra define is as much a finding as a missing one).
- Direction/`pinMode` usage in `setup()` matches the CSV's Dir column, including the
  `CBAL_DISABLE` `INPUT_PULLUP`-before-`OUTPUT` idiom and the rule that pins 0/1 (RX/TX)
  must NEVER get a `pinMode()` call (it detaches LPUART6 on Teensy 4.x and silently kills
  VESC comms, including the safety flushes).

## 2. Ag105 registers vs the extracted tables

Check every Ag105 constant in the code against
`references/Datasheets/Ag105_Table3_Charge_Voltage_Select.json` … `Table7` (address 0x30;
reg 0x01 = 0x08 → 2S/8.4 V; reg 0x00 = 0x01 → 2500 mA; reg 0x06 charge current at
0.011 A/count; GENSTAT mask 0x07 with errors 0x05/0x06/0x07 and 0x04 = Bring-Up normal).
Verify the code's comments cite the table they came from; a value with no citation is a
finding even if it happens to be right.

## 3. Polarity spot-checks

These have confirmed polarities that are easy to invert silently — verify the code and its
comments still agree with the schematic-confirmed truth:
- `MPPT_DISABLE` is **active-LOW** (LOW inhibits MPPT, HIGH releases it).
- `CBAL_DISABLE`: LOW = balancer/OVP active, HIGH = disabled (fail-safe).
- `CHARGER_STAT`: steady HIGH = charging, steady LOW = input removed; pulse patterns mean a
  single `digitalRead()` is not a health check (GENSTAT over I2C is primary).
- `K_sns = 0.1` V/A (INA253**A1** fitted — the A3's 0.4 is wrong for this board).

## 4. Stale-name sweep

Grep the whole repo (`.ino`, tests, PLAN.md, docs) for names that must not exist outside
historical notes: `CHARGER_ENABLE`, `CHARGER_OK`, `CHRG_CURRENT`, `REG_ICHG`,
`CHARGER_ADDR` (as 0x6A), `maxChargeCurrentA`, `setChargerTargetCurrentA`, `BQ25690`,
`k_eq` (removed from the droop path). Matches inside changelogs/addenda that describe the
old board are fine; matches in live code or live documentation are findings.

## 5. Report

List findings grouped as: (a) code contradicts an authoritative source — with the CSV/JSON
value, the code value, and file:line; (b) missing citation comments; (c) clean sections,
stated explicitly (so "audited, no findings" is distinguishable from "not checked"). Apply
fixes only with the user's go-ahead, then run the `test` skill and, if any pin or register
changed, follow with the `self-review` skill.

# Phase C notes: sim_chopper (sim 2, review items R2-SIM-0, R2-SIM-6, R2-SIM-7)

Date: 2026-11-15. Scope: `hardware/charger_evm_r8/sim/chopper/` only. No other file was edited.

## 1. Files changed

| File | Change |
|---|---|
| `sim/chopper/run.py` | Comment marking the OVP-pin-only "lo-leak" corner as superseded (R2-SIM-0); optional `u101_body` argument of `build_deck()` that adds the U101 body diode (R2-SIM-7); `vdbody#branch` added to the vector list; body-diode metrics in `run_case()` when present. With `u101_body=None` (every 2026-11-14 deck) the decks are unchanged. Line endings kept CRLF. `run.py` was not re-run; its 2026-11-14 outputs keep their timestamps. |
| `sim/chopper/run_r2.py` | New. Sim 5 corner model (closed form, both pin leaks, 0.1 % resistors), E96/E192 lever (a) search, string-impedance study, Parts G / GS / GC (sim 5 corners, threshold sweep, candidate dividers) and the 1304-run body-diode re-run with comparison against the 2026-11-14 CSVs. |
| `sim/chopper/r2_*.csv`, `r2_summary.json`, `r2_run_log.txt` | New outputs of `run_r2.py` (1512 transient runs, 0 failed, 1068 s). |
| `sim/chopper/RESULTS.md` | New section 5.8 (dated 2026-11-15) with Tables 5.5-5.8; superseded-form edits in Table 2.2 (U101 row), assumptions 11 and 12, sections 5.1, 5.2, 5.6, 5.7, conclusions 2 and 4, section 7, section 8 item 5 and section 9; new section 10.2 with Table 10.2 and a check pass. |

## 2. Findings and status

- **R2-SIM-0: FIXED (in sim 2).** Sim 5 model reproduced to 4.8e-5 V (`a_bands_corners.csv`). Fitted divider: OVP
  rising 21.588-25.019 V, falling 19.899-22.927 V; the old 21.90 V corner replaced. Per 320 nA the OVP threshold moves
  0.291 V (OVP pin) and 0.270 V (UVLO pin). The Part GS sweep (H-hi, nominal charger) shows that the VCHG-IN rising
  threshold must be at least 23.1 V (early trip at 23.0 V and below), confirming the 23.10 V target at 0.1 V
  resolution.
- **New lever (a) numbers:**
  - Gain-scaling estimate: no-leak minimum 23.70 V, leak-corner maximum 26.77 V; the old r244 becomes about
    22.76-26.38 V and does not clear 23.10 V.
  - Recommended divider: R102 845k (kept), **R103 68.1k, R104 47.5k, 0.1 %** (E96 and E192). OVP rising
    **23.256-26.863 V** at the leak corners, 23.818-26.300 V without leakage, 24.935 V typical; falling 21.439-24.614 V;
    UVLO rising 9.092-10.571 V (fitted 9.055-10.548 V). OVP pin 3.71 V at 75 V, 3.96 V at 80 V.
  - Alternatives: 69.0k / 47.5k (E192): 23.278-26.888 V, UVLO 9.028-10.501 V; 69.8k / 46.4k (E96): 23.835-27.504 V.
  - Simulated: with 68.1k/47.5k and 69.8k/46.4k at both leak corners the first trip is 1.5-1.6 A (H-lo, H-typ) and
    1.4-1.5 A (H-hi), the charger plus chopper capacity.
  - BQ25798 (SLUSDV2C section 6.5, p.9: VBUS OVP rising 25.2/25.7/26.2 V, falling 24.0/24.4/24.8 V; 6.3 p.7: 24 V
    recommended max; 6.1 p.7: 30 V abs max): the candidate's 26.863 V maximum lies 0.66 V above 26.2 V and 1.66 V
    above 25.2 V. Structural: V_OVPR 1.298/1.18 = 1.100 forces a maximum of at least 25.41 V for a 23.10 V minimum,
    so no divider can stay below the 25.2 V VBUS_OVP minimum. A scaled string (0.5x: 432k/33.2k/24.6k) brings the
    maximum to 26.180 V, below 26.2 V; 0.25x gives 25.793 V. A scaled string changes R102 and the sim 5 decay:
    TODO(recalc: sim 5 part b), not evaluated.
  - New side result: with no converting charger and OVP at the sim 5 low corner, H-typ trips at 0.25 A or less
    (was 0.4-0.5 A at OVP lo).
- **R2-SIM-6: FIXED within sim 2.** RESULTS.md now calls 21.35-23.10 V an onset (section 5.1, conclusion 2, section
  5.8.7) and labels OVP self-release as a model input (Table 2.2, section 5.6, section 8), supported by TCKE1401NM DS
  Rev. 3.0 section 7.3 (p.6), section 7.5 (p.7) and Table 10.3 OVP_ton rows (p.16); MODE-open latch of OVP is
  TODO(verify: Toshiba). NOT FIXED here: the companion doc line 1323 and design doc line 442 (owned by other agents).
- **R2-SIM-7: FIXED.** Body diode (VOUT anode, VIN cathode, 0.40 V at 1 mA, RS 50 mOhm; ASSUMPTION, no DS data)
  added; 1304 runs (Part B 360, E 840, E-latch 48, D 56). No change in any trip, VESC-cut or RT1987-latch count;
  largest changes 11.9 mV V-MOT peak, 85 uJ charger energy, 0.79 ms U101 off time; VOUT - VIN at most 16 mV, body
  current at most 62 uA, 17.5 nC. Table 2.2 corrected.

## 3. Left open (operator or other owners)

- The U101 OVP band vs VESC regen limit decision (J.2 item 74) stays open. The sharpened evidence: lever (a) is
  achievable with R103 68.1k / R104 47.5k, but at the leak corners it gives up U101 protection of the BQ25798 VBUS
  input up to 26.86 V (BQ25798 then stops switching; consequence not simulated). This is unavoidable for any divider
  that clears 23.10 V.
- Design doc J.2 item 74 (line ~4127: ">= 23.40 V ... high corner 25.74 V, inside 25.2-26.2 V") and the r9-25
  summary (line 442) need the numbers above; companion doc line 1323 needs the onset wording. Not in this agent's
  scope.
- 0.1 % stock of 68.1k / 47.5k: TODO(verify: distributor stock).

## Addendum (phase C fix round, 2026-11-15)

sim/chopper/RESULTS.md section 2.1 tag-citation note added; section 5.8 cites R102-R104 by part reference; README.md documents row reads 'section 6 (sim 5: section 5)' (R2-SIM-4 closed). See `notes_phaseC_fix1.md`.

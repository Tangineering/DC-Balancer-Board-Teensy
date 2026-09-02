# hil-plant review ledger (prefix PLANT)

Target: docs/HIL_PLANT.md. Re-raise rule: a settled item reopens only with new evidence,
stated explicitly in the run record.

## Active findings

| ID | Status | Finding | Rationale |
|---|---|---|---|
| PLANT-R1-F2 | accepted (major) | Chopper/MOT_PWR coupling unreachable (strict-forward; V_BUS > 18.135 V needed, above the 17.5 V latch); the "6.5 % leak" is post-clamp-release bus-fed charging (0.088 J, 0.118 W), not a solver transient | Bin trace zero while clamped; link deletion → 0 J; bus sag < 1e-5 V; co-solve TODO retired |
| PLANT-R1-F4 | accepted (major) | Open loop has HOLD and slew-limited FEEDFORWARD; the doc's "never writes the MDACs" is false | 356 open-loop MDAC-write ticks measured on ems-y-b00-v3 (011926); firmware :10141-10213; rule → "hold AND feedforward slew" |
| PLANT-R1-F1 | accepted (major, validation arm) | Byte 15 is a fiat HIL mirror (manager never called under HIL_SIM; regen exclusion bypassed); two suite labels assert the manager ran | 11.8 % of ticks differ, max 12 counts; pin was unsatisfiable on all three campaigns; relabel + peak-form pin; firmware gating rejected |
| PLANT-R1-F3 | settled-caveat (minor) | −2·p_chop braking artefact in p_bal_w; line 1014 ambiguous (names the §3.4 tested invariant) | Pure observer column; wording + figure label; load-side migration deferred to the next identity change |
| PLANT-R1-F5 | accepted (minor) | §9.4 omits the measured DP fidelity gap and the regen boundary; cause is the open-loop hold, not Gfc dynamics | Dyn-vs-DC 0.01-0.03 %; gap −4.14 % / +19.6 % (011926); regen 0.000 J on every frontier leg; "unscore" rejected |
| PLANT-R1-F6 | accepted (minor) | §2 1 kHz adequacy unscoped; no substep-resolution gate | 99.98 % of ticks at h 50 µs; 2 event-free ticks over 125 µs; gate n_min ≥ 8 added; host-dependent-verdict claim refuted |
| PLANT-R1-F7 | accepted (minor) | CV taper declared absent yet implemented (synthetic FULL/CV + AG105_TAU_S) | Reword two sites; suite labels already scoped |
| PLANT-R1-F8 | accepted (minor) | 15 of 17 line citations stale, one wrong file | Symbol + pinning-test references |
| PLANT-R1-N2 | accepted (minor) | mppt peak-tripwire note predicted 21-22; measured 19 because the floor binds | V_chg +0.487 V mean; windowed-min − 3 V < 12.32 V |
| PLANT-R1-N1 | accepted (nit) | Dangling fragment at :768 | Repair |
| PLANT-R1-N4 | open (unverified) | FC_BUS.i INA proxy may under-report a bus load step by half at one point | Needs a reproducible operating-point test |

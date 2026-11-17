# charger_evm_r8/sim: circuit simulations for the CR and EIB review

This folder holds the circuit simulations that inform the findings of `../REVIEW_2026-11-14.md` (sections 2 and 4) and
the quantitative checks and tests of `docs/charger_bq25798_wiring_design_2026-11-05.md` (sections B, F, H, I and J).
Each simulation reproduces a specific design-document criterion or review finding on the circuit as captured in
`../cr/cr.net`, `../eib/eib.net` and the MB schematic `references/Scale_Car_Board_20260624.sch`. No file outside this
folder is modified by any script here.

**Overview.** The five simulations are final for the 2026-11-14 round; each `RESULTS.md` ends with a "Check and
corrections" section, and its section 6 (sim 5: section 5) states the result against the design-document criterion. In
brief:

- Sim 1, `hardshort/`: in the T-C-04 step (2) hard short, U101 OUT reaches -3.8 to -7.8 V and stays below the
  TCKE1401NM -0.3 V limit for 2.9-11.2 us with any SMA D103; a 2 ohm or 1.5 ohm short keeps OUT above 0 V (section 6).
  Revision 3 (2026-11-15) re-runs the fast-trip shorts at the datasheet tFASTTRIP of 3-8 us (2 ohm: +0.72 V minimum)
  and bounds the unmodelled current-limit dwell after each trip at up to 65.4 W for 190 ms (sections 5.6, 5.7).
- Sim 2, `chopper/`: the healthy MB chopper band (21.35-23.10 V) overlaps the U101 OVP band; the logged V_rgn readings
  are consistent with the fitted knee sink, under which the logged 18.26 V peak is a true V-MOT of 23.4-25.2 V
  (section 6, VR-1, VR-2).
- Sim 3, `comparators/`: the H1, UVB, FCC_OFF and FCC_ON bands of B.2, H.1, H.2 and H.22 are reproduced; the H1 fall
  worst case with resistor TCR is 17.843 V against 17.84 V; the VR-4 0.08 ratio is not needed for the TLV3012B
  (section 6).
- Sim 4, `permit/`: the gate implements the B.1 equations in all 64 input states; a lost T2 tap gives a release pulse
  of 3-47 us before UVB drops it; the D-66 wire-pad grids reopen the W5 bridge rail collapse (sections 5.6, 5.8 and
  6).
- Sim 5, `efuse_decay/`: with pin leakage the U101 UVLO rising band is 9.055-10.548 V and the OVP rising band
  21.588-25.019 V; the simulation recommends a slope test for FR-12(b1) and k = 0.2 with dV_bus >= 2 V for FR-12(a2) (section 5).
- Sim 6, `regen_nocut/` (2026-11-15): the measured hard brakes deliver 10.9-19.0 W peak and 2.0-5.5 J to V-MOT, below
  the nominal 21.739 W charger capacity; an early U101 OVP trip needs a 12 A brake from 3.11 m/s (lo charger) or
  3.49 m/s (nominal charger) at the nominal efficiencies, a 25 A brake from 2.51-2.70 m/s, or the 100 kHz degraded
  absorption mode at 0.4 mF (section 6). It is a mechanical model with a one-node V-MOT balance, not an ngspice deck,
  and it is the basis of the J.2 item 74 ruling (`../LAYOUT_DECISIONS.md` D-93).

The review that these simulations inform is `../REVIEW_2026-11-14.md`. The decisions taken on them are recorded in
`../LAYOUT_DECISIONS.md`: D103 (D-79, sim 1), R130 and R131A (D-80, sim 4) and C106 to C108 (D-81, sims 3 and 4). D-81
rests in part on a scratch re-run of the sim 4 decks with T2 interruptions shorter than 50 us, which is not part of
this folder.

**Phase C pointer (2026-11-15).** The second review of the round (findings R2-*) led to three re-runs that change
recorded numbers: sim 1 revision 3 (`hardshort/RESULTS.md` sections 5.6 and 5.7), sim 2 section 5.8
(`chopper/run_r2.py`: the fitted OVP bands and the lever (a) divider) and sim 4 section 5.6a (`permit/t2brief.py` and
`permit/t2brief_check.py`: the formal T2-interruption re-run, which supersedes the scratch re-run that D-81 cites).
`../LAYOUT_DECISIONS.md` D-91 lists the changed numbers and the documents that cite them, and
`../update_2026-11-14/notes_phaseC_sim_*.md` hold the per-finding status. In `permit/`, run `run.py` before
`t2brief.py` and `t2brief_check.py`, because `run.py` deletes all outputs at its start.

**Source citations (2026-11-15, second review R2-SIM-4).** The line numbers that the `RESULTS.md` files give for
`gen/netlist.py`, `cr/cr.net` and the design document refer to git tag `charger-r8-pre-review-2026-11-14`. The BOM
citations refer to `bom_2026-11-13/`; `bom_2026-11-14/` carries the same values for every simulated part. The notes at
the top of the sim 1, sim 3 and sim 5 reports state this in detail.

**Incident record (2026-11-15, sim 3, second review R2-SIM-8).** During the round, a script of another agent inserted
a duplicate, older copy of `dc_deck()` and `dc_trip()` into `comparators/run.py`. The orchestrator removed the block
and re-ran `run.py` in full (557 s). Every CSV of the re-run is byte-identical to the outputs of the run before the
removal, and `summary.json` is equal except for `runtime_s`. One definition of each function remains.
`comparators/run_log.txt` is now the console of the final run; the earlier console is kept as
`comparators/run_log_pre_dedup_2026-11-15.txt`. `comparators/RESULTS.md` section 10.1 gives the evidence. Scripts of
one simulation must not write into the folder of another simulation.

## 1. Layout

| Path | Content |
|---|---|
| `common/ngspice_run.py` | The shared runner: drives KiCad 9.0's `ngspice.dll` (ngspice-46) through `ctypes`. API in `common/README.md`. |
| `common/test_ngspice_run.py` | Ten verification tests of the runner (RC transient, DC sweep, `.meas`, B-source, XSPICE digital gates with bridges, diode, multiple plots with AC, PSpice compatibility, `bg_run` and in-process reset, deck file input). |
| `models/` | Manufacturer SPICE model text files, each with a header comment that gives the source URL and the download date, and behavioural models built from datasheet tables (each states the table used). |
| `<name>/run.py` | One entry script per simulation; it regenerates every deck, CSV and PNG of that simulation. |
| `<name>/RESULTS.md` | The simulation's report: purpose, circuit and models, assumptions, cases, results, conclusion against the design-document criterion, limitations and the confirming bench test. |

## 2. How to run

All commands use the miniforge interpreter, which provides numpy and matplotlib:

```
C:\Users\ricky\miniforge3\python.exe "C:\Life Ops\School\Thesis\DC-Balancer-Board-Teensy\hardware\charger_evm_r8\sim\common\ngspice_run.py" --selftest
C:\Users\ricky\miniforge3\python.exe "C:\Life Ops\School\Thesis\DC-Balancer-Board-Teensy\hardware\charger_evm_r8\sim\<name>\run.py"
```

The self-test must report `10/10 passed` before any simulation result is trusted on a new machine or after a KiCad
update. Each `run.py` writes its outputs inside its own folder and prints ASCII only. Scratch files go to
`C:\Users\ricky\AppData\Local\Temp\claude\sim_2026-11-14\`.

## 3. Simulations

Each simulation adds one row to this table when its folder is created.

| Folder | Informs | Entry script |
|---|---|---|
| `efuse_decay/` | Sim 5: U101 UVLO/OVP bands with pin leakage (PWR-2, DOC-0); FR-12(b1) V_chg decay (PWR-1); FR-12(a2) D-MT-EN ratio (VR-3) | `efuse_decay/run.py` |
| `chopper/` | Sim 2: MB regen chopper (TL431/BSP170P, healthy and faulty RGN-V) and the V-MOT ceiling against the U101 OVP during regen bursts, with and without the VESC over-voltage cut; retuned OVP band option; V_rgn reading reproduction (VR-1, VR-2) | `chopper/run.py` |
| `hardshort/` | Sim 1: T-C-04 steps (1)-(3) at the EVM J1 end: U101 VOUT excursion and D103 candidates, U101 VIN spike, MB-end (C-D8) and pin-38 peaks, D-BC-RG current (PWR-0, T-C-04); tFASTTRIP 3-8 us check and the current-limit dwell bound (R2-SIM-9, R2-PWR-0) | `hardshort/run.py` (`--tft-check` runs only the tFASTTRIP set) |
| `permit/` | Sim 4: CR/EIB permit logic: 64-row truth table from cr.net/eib.net (B.1, LOG-3), power-up, MCU reset and keeper (B.7, T-D-01), brown-out, J-TAP unplug and the lost-T2 race with comparator delay skew and an overdrive-dependent TLV3012B model (T-D-04), EIB/REGN loss (B.6, T-C-05), W5 bridges (INT-0, EIB-0, EIB-1, EIB-2), LOG-1, floating inputs | `permit/run.py` |
| `regen_nocut/` | Sim 6 (2026-11-15): regen power and energy of the 8 measured hard brakes (12 A, no VESC cut) from a mechanical motor model, against the sim 2 charger capacity corners; start-speed thresholds for an early U101 OVP trip; efficiency sensitivity; drive cycles; staged absorption before T3 (FR-41); the 25 A 'T' ramp (design J.2 item 74 ruling, D-93). No ngspice run | `regen_nocut/run.py` |
| `comparators/` | Sim 3: U102 H1, U103 UVB, U119 FCC_OFF, U120 FCC_ON trips and hysteresis; 4000-board Monte Carlo with TCR, rail and -20..+70 C at VBUS 15.2-19.5 V, exhaustive-vertex worst case and PSRR-reference sweep (B.2, H.1, H.2, H.22, regen threshold stack); the VR-4 0.08 H1+ ratio option; V-MOT over-range to 40 V and phase reversal (VR-4); V-MOT ripple that toggles H1 (H.1, T-E-07) | `comparators/run.py` |

## 4. Runner API in brief

```python
import sys
sys.path.insert(0, r"C:\Life Ops\School\Thesis\DC-Balancer-Board-Teensy\hardware\charger_evm_r8\sim\common")
from ngspice_run import run_deck

r = run_deck(deck_text_or_path, vectors=["time", "vout"], ngbehavior="psa")
assert r.ok, r.errors
t, v = r["time"], r["vout"]     # numpy arrays
r.meas["t_trip"]                # .meas results parsed from the log
r.plots["tran1"]                # every plot of the run, by name
r.log                           # full simulator output
```

XSPICE code models (`adc_bridge`, `dac_bridge`, `d_and`, `d_or`, `d_inverter`, and the rest of the analog, digital,
xtradev, xtraevt, table, spice2poly and tlines libraries) and B-sources are available in every deck. The default is
a fresh process per deck; `use_subprocess=False` runs in-process with a reset between decks. Section 5 of
`common/README.md` lists the limitations, among them that encrypted vendor models do not run.

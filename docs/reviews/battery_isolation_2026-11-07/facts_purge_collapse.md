# Battery-isolation study: safe collapse on an unpredicted purge inside an FC window (IC1 revision 8)

Date: 2026-11-08. Board revision 20260622, firmware baseline fw v37 rev 2, design `detailed_design_IC1.md` revision 8
(cited "IC1 section N"). Calculation: `calc/purge_collapse_sim.py`, output `calc/purge_collapse_sim_output.txt` (cited
"pc section N"). Nothing in this document has been ordered, built or flashed.

## 1. Scope, rulings and evidence classes

### 1.1 Scope

This fact sheet analyses one event: an H-20 purge that the purge predictor did not announce, which starts while an FC
window is open. In the window the bus is FC-only, because the clamp Q_X1 holds BT_BUS open while FCQ is HIGH
(IC1 section 9.7, entry step 6). The sheet states what the hardware does, what the firmware sees, which damage
mechanisms exist, and which pin states and orders a safe collapse requires.

Operator ruling 2026-11-08 (2) sets the acceptance criterion. The bus may collapse and the system may latch State 99.
No component may be damaged, on the collapse, on the recovery of the FC or on the next power-up, and the pack may not be
left in a hazardous configuration. A ride-through is not required. The purge predictor is outside the scope of this
document; the predictor interface (lead time and re-entry) is the subject of `calc/purge_demand_budget.py`.

The purge facts are those of `facts_prior.md` section 7 only: period 10.34 s, duration 100-140 ms with a 20 ms edge
uncertainty (50 Hz Pi bags), floor about 1 V. No further purge statistic is measured or assumed, except the FC fall time,
which is swept as a model parameter (section 2.3) because no primary gives it.

### 1.2 Evidence classes

The tags follow IC1 section 0.2: **BENCH** (a bench gate measures it), **TODO(verify: source)** (a primary exists and was
not read), **UNCONFIRMED** (an inference no primary states), **ASSUMED** (a working value with no primary). A number
without a tag cites a datasheet, the firmware, a bench record or a calculation section.

## 2. Model

### 2.1 Network

`calc/purge_collapse_sim.py` models five capacitive nodes joined by ideal-diode links (pc header). Table 1 gives the
nodes and their sources.

Table 1. Nodes of the collapse model.

| Node | Capacitance | Source | Link to the bus |
|---|---|---|---|
| F: FC boost output | 30 uF | OFC, `docs/HIL_PLANT.md` section 8.2 | D-FC-EN (pin 27), ideal diode F to B |
| B: VBUS | 35 uF (30-40 uF band) | HIL_PLANT.md section 8.2; `tools/hil_electrical.py:456` | - |
| C: VCHG-IN | 21 uF | C-D8 + C-D10 20 uF (calc5 section 5) + C_EI 1 uF (IC1 section 5.3) | D-BC-FC (pin 31), ideal diode B to C |
| M: module node VCHG-IN_M | C_mod 100-221 uF + C_EO 1 uF | IC1 section 5.3; C_mod is BENCH (gate S0-11) | eFuse U_EF: channel when ON; body diode M to C when OFF |
| V: V-MOT | 0.48, 1.5 or 5 mF | facts_prior section 6 (0.48 mF to about 5 mF); capture 11 effective 1.4-1.6 mF (`docs/boost-bringup-debug.md`) | D-MT-EN (pin 29), ideal diode B to V |

The link rules come from primaries:

- **RT1987.** An enabled RT1987 is an ideal diode with fast reverse blocking (DS-00 section 17.6). It is disabled when EN
  is LOW, and also when VIN falls below 2.925 V typical (DS-00 section 17.1); disabled, its back-to-back MOSFETs isolate
  VIN and VOUT completely (DS-00 section 17). After a VIN UVLO the switch re-runs t_D_ON (8 ms typical) and its soft-start
  (DS-00 section 17.1; capture 7 in boost-bringup-debug.md). After a reverse-current (TRCB) condition it restarts
  **without** soft-start when the condition clears (DS-00 section 17.4, Table 1).
- **eFuse.** The TPS26631 turns off below 11.47-12.10 V and on above 12.38-12.88 V on its input (IC1 section 5.3, calc4
  section 9). B_GATE and DRV are open, so it does not block reverse current from OUT to IN (IC1 section 5.3, SLVSE94G
  Table 5-1). The reverse path is modelled as a diode with a 0.6 V drop (ASSUMED).
- **TPS61288.** The FC boost stops switching when VIN falls below 1.8-2.0 V and restarts above 2.3 V typical (SLVSFP3C
  section 7.5, section 8.3.2). The purge floor of about 1 V is below the falling threshold, so the FC boost delivers
  nothing during the purge.

### 2.2 Loads

- **Ag105 (FC profile).** Input power 13.0-14.8 W (IC1 Table 8). Two bounding behaviours are modelled. In mode CP the
  module draws constant power until its node falls below V_LOCK 11 V (typical only, Ag105 DS p.19), then 18 mA (DS p.20
  row 4, maximum). In mode MPPT the module throttles to hold its node at the FC-profile threshold of 13.82 V (BENCH,
  gate S0-4); this is an ideal fast MPPT loop, a bound, because the datasheet does not give the loop speed
  (`facts_ag105.md` section 7).
- **Module-node elements.** R_MB 3.3 kOhm, R_MS1 + R_MS2 116.2 kOhm, and R_MD 15 Ohm when EF_EN is L (IC1 section 5.3).
- **VCHG-IN bleed.** R1-CHG 88.7 kOhm parallel R_UV 110.5 kOhm = 49.2 kOhm (calc5 section 5).
- **Bus-side auxiliary load.** 0.5 mA (bleed level, HIL_PLANT.md section 4.2), 15 mA (the HIL `I_AUX_A` 0.09 A minus its
  0.075 A VESC term, HIL_PLANT.md section 4.3) and 150 mA (the IC1 Table 8 bound, all on VBUS). The VESC sits on V-MOT,
  behind D-MT-EN, not on VBUS.
- **V-MOT.** VESC 0.075 A (HIL_PLANT.md section 4.3, TODO(calibrate)). Variant D adds 0.28 A of traction, the top of the
  0.17-0.28 A FC-window headroom (IC1 Table 8). The VESC load stops below 8 V (VESC `l_min_vin` ASSUMED 8 V,
  TODO(verify: VESC)).

### 2.3 Source and firmware

The FC current falls linearly to zero over T_fall. T_fall is 0 (step) or 20 ms (one bag sample) in the main grid, and
0-75 ms in a sensitivity sweep (pc section 3b). The fall time is not measured; no primary gives it.

The firmware runs one iteration every 1.341 ms (the p99 loop, `facts_firmware.md` section 8), with one 9.76 ms gap in a
sensitivity run (pc section 4). Two policies are modelled:

- **E1 (IC1 revision 8 as written).** A V_chg reading below 13.0 V with EF_EN H ends the window as a commanded exit (IC1
  section 9.7, exit conditions). The exit drops FC_CHARGE, waits for pin 8 LOW on two iterations, sets pin 33 LOW,
  confirms the bonded reading, and re-closes BT_BUS (IC1 section 9.7, exit steps 1-4). D-BT-EN conducts when its
  soft-start ramp, started t_D_ON after EN, passes V_bus; the ramp is 0.81 V/ms (CSS 100 nF, `calc/purge_demand_budget.py`)
  or 0.5 V/ms (capture 11). UV_BUS latches after 20 ms of accumulated dwell below 12.0 V (ino:2163, ino:2189-2193,
  ino:7369-7377). State 99 follows IC1 section 9.9.
- **E2 (proposed).** The same V_chg reading below 13.0 V inside a window latches State 99 at once; BT_BUS is not
  re-closed.

### 2.4 The recovery hazard H-R

**H-R** is defined as follows: the FC boost leaves VIN UVLO at the end of the purge while FC_BUS (pin 27) and FC_REG
(pin 3) are still HIGH, so the boost restarts into a sagged bus and, through an enabled D-MT-EN, into V-MOT. The check
instants are t_rec = 80 ms (100 ms minimum duration less the 20 ms edge uncertainty) and 100 ms (facts_prior section 7).
The severity classes of pc section 3b are BENIGN (V_bus at least 15.5 V), IN-FAMILY (12.0-15.5 V, no deeper than the
TP0178 dropout to 12.15 V, which was nondestructive) and HAZARD (below 12.0 V, the TP0010 class: 33 sags to 6.5 V with
reconnect spikes above 3 A, nondestructive but recorded as "Death-5-family stress", boost-bringup-debug.md 2026-08-11).

## 3. The collapse sequence

### 3.1 Bus collapse rates

Table 2 gives the collapse rates before any firmware action (pc section 1).

Table 2. Collapse rates.

| Load on the joined bus nodes | Rate |
|---|---|
| Ag105 13.0-14.8 W plus 0.15 A aux on B + C + M | 3.9-6.2 V/ms |
| 0.09 A aux on VBUS alone (campaign G check) | 2.57 V/ms |
| Bus aux after the eFuse turns off, on B + F (65 uF) | 0.008-0.231 V/ms |
| V-MOT, VESC 0.075 A, C_V 0.48 / 1.5 / 5 mF | 0.156 / 0.050 / 0.015 V/ms |
| V-MOT, VESC plus 0.28 A traction (variant D) | 0.740 / 0.237 / 0.071 V/ms |

The Ag105 is the dominant bus load. In mode CP the bus reaches the eFuse UVLO in about 1 ms on a step fall; the eFuse
turns off at 1.0-1.1 ms and the module locks out at 1.2-1.3 ms (pc section 2). After that the bus carries only its
auxiliary load and decays at 0.008-0.231 V/ms; with a 0.5 mA auxiliary load it hangs near 12 V for the whole purge.
In mode MPPT the module throttles at 13.82 V, the bus joins V-MOT through D-MT-EN, and the joined node decays at the
VESC rate, so V_chg reaches 13.0 V only 13.6 ms (step) to 31.3 ms (T_fall 20 ms) after the onset (pc section 2).

### 3.2 The module node and the Ag105

The module stops converting at its own lockout within about 0.2-0.5 ms of the eFuse turn-off (pc section 2). The pack
is then in the charge mode with the module dark and the sense in the return path, which is the designed state of a cold
module (IC1 section 9.5). VCHG-IN keeps 10-12.9 V after the collapse, because D-BC-FC blocks reverse current and the
eFuse body diode conducts only from the module node toward VCHG-IN; it decays with a time constant of about 1 s
(pc section 2 snapshots; calc5 section 5).

With a slow FC fall the eFuse can turn off at UVLO and turn on again while EF_EN is still H, because the removed charger
load lets the residual FC current lift VCHG-IN above 12.38-12.88 V. The grid shows 8-28 such warm restarts per 216
cases, all before the firmware reads V_chg below 13.0 V (pc section 3). A warm restart is the case IC1 section 9.7
already names: it may trip U_IM, and a hardware trip leaves the module converting from its input capacitance for up to
about 1.1 ms with the sense partly bypassed, at most about 24 mJ per trip (IC1 row F10, calc5 section 10). Whether the
Ag105 restarts after a brown-out, and how long that takes, is not given (TODO(verify: Silvertel); the prior cold start
is 65-170 ms, facts_prior section 6).

### 3.3 What the firmware sees

1. **V_chg below 13.0 V** with EF_EN H, the first symptom: 1.4 ms after a step onset in mode CP, 13.6-31.3 ms in mode
   MPPT (pc section 2). Under E1 this ends the window; under E2 it latches.
2. **EF_FLT_N L** during the eFuse UVLO. The mask of IC1 section 12.4 item 4 covers it after the V_chg excursion below
   13.0 V. If the ladder settles before the V_chg reading falls, `ERR_CHG_TRIP` latches instead; either path ends in
   State 99.
3. **Pin 8 (MOD_COLD_N)** stays HIGH while the node is above 8.69-9.15 V. The dump takes it LOW 1.3-2.9 ms after EF_EN
   falls (IC1 section 5.3). At the bond the module node reads 1.46-5.81 V in every grid case (pc section 3), below the
   pin-8 threshold and below the 11 V lockout.
4. **UV_BUS.** The transient bit sets at the first reading below 12.0 V; the latch needs 20 ms of dwell. The detector
   is armed only while a matched source pair is closed (FC_BUS and FC_REG, or BT_BUS and BT_REG), and it dumps the dwell
   when no pair is closed (ino:7338-7356).
5. **UV_FC.** V_fc below 4.5 V accumulates dwell toward the 1000 ms latch (ino:2148, ino:2243); one purge does not latch
   it. The closed excursion arms the 30 s FC-only lockout (ino:2256).
6. **OC_FC** does not fire: the FC delivers less, not more, during a purge.

### 3.4 State 99 from inside a charge-mode window

IC1 section 9.9 gives the order. Under E2 the grid gives the following times from the purge onset (pc section 3):

1. Phase 0, on the iteration after the latch: FC_CHARGE LOW and REGEN LOW (EF_EN L, dump on); FC_BUS and BT_BUS LOW;
   motor command 0. The latch comes 1.4-50.3 ms after the onset in variant P and 1.4-31.3 ms in variant D.
2. Pin 33 LOW after pin 8 reads LOW twice (2.7 ms after phase 0 in the reference trace), then pin 32 LOW.
3. MOT_PWR LOW 10 ms after phase 0: 13.6-62.6 ms after the onset (variant P), 13.6-43.5 ms (variant D).
4. Boosts LOW 20 ms after phase 0, after every bus and motor switch is LOW (ino:8329-8337).

Under E1 the latch, when it occurs, comes 20.4-76.2 ms after the onset (variant P) and 20.4-47.6 ms (variant D); in 76
of 216 variant-P cases and 55 of 216 variant-D cases no latch occurs, because the re-closed BT_BUS restores the bus
before the dwell reaches 20 ms (pc section 3).

## 4. Damage mechanisms

Table 3 gives the verdict on each mechanism of the task list. "Excluded" means that no current path or stress exists in
the model and the primaries; it is not a bench result.

Table 3. Damage mechanisms.

| No. | Mechanism | Verdict | Evidence |
|---|---|---|---|
| D1 | Death-5 hot-plug when the FC recovers onto a discharged node | **Excluded under E2. Present under E1** for slow FC falls (H-R, section 5) | E2: FC_BUS is LOW at t_rec 100 ms in all 648 sweep cases; at 80 ms it is still HIGH in 12 variant-P cases with T_fall 75 ms, all with the bus at 12.04 V or higher (IN-FAMILY), and phase 0 follows within one iteration (pc section 3b). E1: HAZARD class in 8-20 of 324 cases per variant, only at T_fall 60-75 ms with the ideal MPPT hold; bus 6.73-8.70 V with D-MT-EN joined at t_rec 80 ms |
| D2 | TPS61288 body-diode back-feed | Excluded | Boosts go LOW only after FC_BUS, BT_BUS and MOT_PWR are LOW (ino:8320-8337, IC1 section 9.9). No RT1987 conducts reverse in any state (DS-00 sections 17, 17.6). After FC_REG LOW the FC boost output holds 6.7-12.8 V in isolation (pc section 2); the H-20 recovery charges only that 30 uF through the passthrough, as at every FC connection |
| D3 | RT1987 reverse stress | Excluded | Largest pin voltage in the collapsed state 22.13 V (V-MOT at the chopper clamp) against the 40 V absolute maximum of VIN and VOUT to GND (DS-00 section 10; pc section 6). The datasheet gives no VIN-VOUT differential rating (UNCONFIRMED that none applies beyond the pin ratings) |
| D4 | RT1987 turn-on stress | E2: no turn-on occurs. E1: the BT_BUS re-close draws 0.05-1.62 A bus-side at C_V up to 1.5 mF and up to 4.46 A at 5 mF (pc section 5) | The re-close uses the same 100 nF slope as the bring-up P3 connect; capture 11 measured 0.7-1 A with no SCP cut. Above 2.5 A the start-up SCP can clamp (DS-00 section 17.5); the 5 mF corner is therefore no worse than P3 on the same vehicle, and is BENCH |
| D5 | Ag105 brown-out and restart in the charge mode | Not a damage mechanism | The dark module with the sense in the return path is the designed cold state (IC1 section 9.5). A warm eFuse restart is bounded by U_IM and, after a trip, by row F10 (at most about 24 mJ). Restart behaviour TODO(verify: Silvertel) |
| D6 | Pack left in the charge mode or with the sense bypassed | Excluded | State 99 bonds after pin 8 LOW or at the T_drain,max deadline, then sets pin 32 LOW (IC1 section 9.9). A reset, brownout or hang clears FF1 in hardware: at once, or after 43-76 ms for a hang (IC1 section 9.10). The module node is at 1.46-5.81 V at every bond (pc section 3) |
| D7 | Teensy supply | Survives | VBT is the pack; no VBUS-to-VBT path exists (facts_board section 6.3 item 2). LM1084 input at a 7.4 V pack is 7.38-7.40 V against the 6.5 V regulation limit (pc section 6; SNVS037H section 5.5). The E1 re-close draws about 2.35 A from the pack, a 0.12-0.24 V sag (pc section 6). In the charge mode the logic return passes through the Ag105 sense, which is passive with the module dark (UNCONFIRMED: IC1 risk B14 names a parallel switch, not a series one) |
| D8 | BQ29200 | Not affected | It is supplied from the cells through J-BL (facts_board section 6.3 item 5); no charge flows during the collapse; CBAL_DISABLE stays LOW in State 99 (ino:8338) |
| D9 | R_MD dump duty | Negligible | One dump per unpredicted purge, 6.1-28.1 mJ, peak 0.73-1.06 A (pc section 6), against the 51 mJ design dump (IC1 section 5.3). State 99 latches, so at most one per power cycle. Pulse rating TODO(select) as in IC1 |
| D10 | Motor regen onto a collapsed bus (variant D) | Excluded | D-MT-EN blocks V-MOT from the bus. D-BC-RG is off: pin 30 is LOW in an FC window, and the bus-present comparators U_BPk hold VOK at NOT OK below about 9.6 V-equivalent on the bus tap (IC1 Table 2, G1 (f)). V-MOT is bounded by the VESC stop at about 21.35 V and the chopper clamp of 22.13 V (facts_prior section 6) |
| D11 | Next power-up | No latent hazard found | Section 6.3 |

The only bench record of an FC-window purge collapse is 2026-10-28: UV_FC and UV_BUS latched within seconds of the first
window (`docs/firmware-versions.md` row 35). The record states the latch and no damage; no damage inspection is
recorded (UNCONFIRMED). That event ran on the pre-IC1 topology. The 2026-11-04 ML0227 supply reset is not in family: the
charger was fed from the bus with VBat- on GND.

## 5. The recovery race H-R and the exit policy

### 5.1 Why E1 leaves a window open

Under E1, the commanded exit holds FC_BUS HIGH and waits for BT_BUS to conduct. The chain from the V_chg trigger to BT
conduction is the drain, the pin-33 confirmation, t_D_ON and the ramp up to the sagged bus voltage: 21-31 ms after the
trigger in the reference traces (pc section 2). UV_BUS needs a further 20 ms of dwell below 12.0 V. Between the trigger
and the first of these events, FC_BUS is closed onto a sagged bus with no source. If the FC recovers inside that
interval, H-R occurs.

With a step or a 20 ms fall the interval ends before t_rec, and every E1 case with FC_BUS still HIGH at 80 ms has the bus
at 16.00 V (BENIGN: the ride-through has completed; pc section 3). With the ideal MPPT hold and a fall time of 60-75 ms
the trigger moves to 63.9-78.9 ms and the HAZARD class appears: bus 6.73-8.70 V with D-MT-EN joined at t_rec 80 ms
(pc section 3b). The severity of H-R then depends on whether the TPS61288 soft-starts after a VIN-UVLO recovery with EN
held HIGH. SLVSFP3C section 8.3.1 describes the soft-start only for an EN rising edge (TODO(verify: TI)). If it does not
soft-start, the boost charges bus plus V-MOT at its 15 A cycle limit (SLVSFP3C section 8.3.3), with D-MT-EN restarting
without soft-start after its TRCB condition (DS-00 section 17.4); that is the TP0010 class. The FC fall time decides
whether E1 is exposed, and it is not a measured quantity.

### 5.2 E2 removes the race

E2 latches on the same V_chg reading, and State 99 phase 0 sets FC_BUS LOW on the next iteration. FC_BUS is therefore
HIGH only while V_chg reads at or above 13.0 V, so the FC can never restart into a bus more than about 3 V below its
setpoint plus one iteration of sag. The sweep confirms it: FC_BUS is LOW at t_rec 100 ms in all 648 cases, and at
t_rec 80 ms it is still HIGH in 12 IN-FAMILY cases only (T_fall 75 ms, bus 12.04 V or higher), in which phase 0 follows
within one iteration (pc section 3b). The
9.76 ms loop gap moves no case into a worse class (pc section 4). E2 does not depend on `uvBusArmed`, so a share-loop cut
of FC_BUS cannot suppress it (section 7).

E2 gives up the ride-through. With an ideal predictor, a V_chg reading below 13.0 V inside an FC window occurs only on
an unpredicted source loss, because a predicted purge closes the window before the onset; a false latch would need a
bus sag below 13.0 V from another cause, which no record shows in an FC window (the eFuse start draws at most 0.58 A,
IC1 section 7.5). The false-latch rate is BENCH.

### 5.3 Alternative E3, if a ride-through is wanted

E3 keeps the E1 exit and adds FC_BUS LOW at the trigger iteration. H-R then cannot occur, because the recovering boost
sees only its own 30 uF. However, with FC_BUS LOW and BT_BUS not yet commanded, no matched source pair exists, so UV_BUS
disarms and dumps its dwell (ino:7349-7356); a BT re-close that fails would leave a dark bus with no latch. E3 therefore
also needs a bus-recovery deadline (V_bus at or above 13.5 V within t_D_ON plus the soft-start plus a margin, about 40 ms,
else State 99). E3 is a design option, not a requirement of ruling (2).

## 6. Recovery, end state and next power-up

### 6.1 End state after the collapse

Table 4 gives the pin end state that State 99 must reach from inside a charge-mode window.

Table 4. Safe-collapse end state (State 99 phase 3).

| Pin / signal | End state | Order and reason |
|---|---|---|
| 31 FC_CHARGE | LOW | First write (phase 0): EF_EN falls, the eFuse turns off, Q_MD dumps the module node (IC1 sections 5.3, 9.9) |
| 30 REGEN_ENABLE | LOW | Phase 0 with pin 31 (IC1 section 9.9 step 1) |
| EF_EN (hardware) | L | Follows pin 31 through FCQ; SHDN_EF on R_SDP if 3V3 fails (IC1 section 9.10) |
| 27 FC_BUS_ENABLE | LOW | Phase 0, before the earliest FC recovery (80 ms); achieved 2.7-51.6 ms after the onset under E2 in the main grid (SC-3) |
| 28 BT_BUS_ENABLE | LOW | Phase 0; under E2 never re-closed after the trigger |
| 33 (FF1 set) | LOW | After pin 8 reads LOW twice or at T_drain,max: bonded, sense out of the return path |
| 32 BT_SEQUENCE_ENABLE | LOW | After the bonded state (IC1 section 9.9 step 2) |
| 29 MOT_PWR_ENABLE | LOW | Phase 0 + 10 ms (ino:8320-8325) |
| 3, 4 FC_REG / BT_REG | LOW | Phase 0 + 20 ms, last (ino:8329-8337) |
| 5 MPPT_DISABLE | LOW | Phase 2, on a cold module (IC1 section 12.4 item 2) |
| 9 CBAL_DISABLE | LOW | Unchanged: OVP active (ino:8338) |
| 34 pump | Stopped at phase 3 | FF1 is already clear |

### 6.2 What must never close on recovery

The FC returns 100-140 ms after the onset, while State 99 is latched. FC_REG and FC_BUS are LOW, so the H-20 charges
only the FC boost output (30 uF, at 6.7-12.8 V in the model) through the passthrough; this is the same event as any
FC connection. No path may close until a power cycle: pins 27, 28, 29, 30, 31 and 33 stay LOW, and EF_EN stays L. The
production firmware has no exit from State 99; the only automatic exit is the HIL auto-recovery, compiled only under
`HIL_SIM` (ino:8350 onward).

### 6.3 Next power-up

1. No window state is stored; the Teensy reset leaves pin 33 high-Z, which clears FF1 (bonded), and SHDN_EF on R_SDP
   keeps the eFuse off (IC1 section 9.10).
2. `setup()` drives every path switch LOW before the SD probe and Ethernet (ino:6709-6715), and the 10 kOhm bodge
   pull-downs hold them LOW before that.
3. The staged bring-up precharges the bus with MOT_PWR LOW, enables the boosts, and connects V-MOT only from a regulated
   bus through the D-MT-EN soft-start (facts_firmware section 2.3). A V-MOT node that still holds charge is behind TRCB
   until the ramp passes it.
4. VCHG-IN falls below 11 V within about 0.35 s of the collapse (calc `purge_demand_budget.py` section 2), so a power
   cycle of normal length does not latch `ERR_VCHG_FED` at boot. A power cycle shorter than that is UNCONFIRMED.
5. A window needs the boot self-test and a dump-check pass in the new power cycle (IC1 sections 9.3, 9.7b).
6. The Ag105 clears its error states on an input power cycle (Ag105 DS p.18); the collapse does not meet the Major
   Battery Fault condition (battery below 2 V at 10 % current, DS p.6).

A latched State 99 keeps the Teensy on the pack through the LM1084 until the operator power-cycles. At 0.2-0.25 A
(UNCONFIRMED) that is 4.8-6.0 Ah per day against a pack of unverified 5 Ah capacity (pc section 6). This is a property of
the present State 99, not of IC1, and UV_BATT is disarmed in State 99.

## 7. Variant P and variant D

Variant P (State 1 or State 98, parked) runs the share loop not at all (`powerBalance()` is called in State 2 only,
facts_firmware section 2.1), so the matched FC pair keeps UV_BUS armed through the collapse.

Variant D (State 2, between purges) is safe-collapse-compatible under E2, with three added requirements and one
consequence:

1. **Detector independence.** In State 2 the share loop can cut FC_BUS on the I_fc collapse (`docs/fw30_fc_purge_uv.md`;
   ino:2240-2242). With BT_BUS clamped open, that cut leaves no matched pair, and UV_BUS disarms and dumps its
   dwell (ino:7349-7356). The E2 detector must therefore live in `chgModeTick()` and must not read `uvBusArmed`, and the
   share loop and the source selector must not write pin 27 while a window is open.
2. **Exit rule.** IC1 section 9.7 ends a window on any non-zero motor command; variant D needs a traction allowance
   instead. The FC-only bus carries traction plus the charger input within the 1.247 A P_MAX, so the allowance is
   0.06-0.33 A bus-side over the pack-voltage and efficiency range (`calc/purge_demand_budget_output.txt` section 1); a
   transient above it latches OC_FC at 1.4 A on one sample (ino:2090), which is a safe collapse but ends the drive.
3. **Regen.** A braking command must end the window before REGEN can rise (window types are mutually exclusive, IC1
   section 12.4 item 3); D10 shows that a regen event that arrives during the collapse has no damaging path.
4. **Consequence.** With traction, V-MOT reaches the assumed 8 V VESC cut-off 10.7 ms (0.48 mF), 33.4 ms (1.5 mF) or
   111 ms (5 mF) after the onset (pc section 1). The VESC therefore browns out in motion on most unpredicted purges and
   the vehicle coasts. No component-damage path follows from it in this analysis; the vehicle-level consequence is a
   loss of drive torque, which ruling (2) accepts as a shutdown.

On the collapse-safety evidence alone, variant D is not unsafe. Its worth depends on the traction allowance of item 2,
which leaves 0.06-0.33 A for traction; that judgement belongs to the operability analysis.

## 8. Safe-collapse requirements

The following requirements follow from sections 3-7. Each is a requirement on the IC1 design or firmware, not on the
purge predictor.

- **SC-1 (detector).** Inside every FC window, one V_chg reading below 13.0 V with EF_EN H latches State 99 (policy E2).
  The detector runs every iteration in `chgModeTick()` and does not depend on `uvBusArmed` or on the share loop.
- **SC-2 (feed first).** The first State-99 write from a window is FC_CHARGE LOW (and REGEN LOW), so EF_EN falls and the
  dump starts before any other path changes.
- **SC-3 (FC isolation deadline).** FC_BUS LOW in phase 0, at most one iteration after the detection, and in all cases
  before the earliest FC recovery of 80 ms after the onset. Achieved: 2.7-51.6 ms in the main grid (pc section 3). In the
  T_fall 75 ms sensitivity cases the trigger itself comes at 78.9 ms and phase 0 about 1.3 ms later, with the bus at
  12.04 V or higher (IN-FAMILY, pc section 3b); a fall that slow is outside every recorded purge shape (UNCONFIRMED).
- **SC-4 (no source re-close).** After an unpredicted collapse no bus switch closes until a power cycle. If a
  ride-through is wanted later, policy E3 (section 5.3) with its bus-recovery deadline replaces SC-4.
- **SC-5 (cold bond).** Pin 33 LOW only after pin 8 reads LOW on two successive iterations, or at T_drain,max; pin 32 LOW
  only after the bonded state.
- **SC-6 (back-feed order).** MOT_PWR LOW before the boosts; the boosts LOW last (existing order, ino:8320-8337).
- **SC-7 (latched end state).** Table 4 holds until a power cycle; no path of section 6.2 closes on the FC recovery.
- **SC-8 (variant D).** The share loop and the selector do not write pin 27 inside a window; the window exit rule uses
  a traction allowance; a braking command ends the window before REGEN can rise.

## 9. Open items

1. TPS61288 restart after a VIN UVLO with EN held HIGH: soft-start or not (TODO(verify: TI SLVSFP3C)). It sets the H-R
   severity under E1 only.
2. RT1987 VIN-VOUT differential rating when disabled (DS-00 gives pin-to-GND ratings only; UNCONFIRMED).
3. TPS26631 reverse current from OUT to IN with B_GATE open, and its rating (TODO(verify: SLVSE94G)).
4. Ag105 lockout tolerance (11 V typical only), MPPT loop speed and restart after a brown-out (TODO(verify: Silvertel)).
5. V-MOT capacitance (0.48-5 mF), the bus-side auxiliary load (0.5-150 mA) and the VESC cut-off voltage (BENCH;
   TODO(verify: VESC)).
6. The FC fall time at a purge onset decides whether E1 is exposed to H-R; E2 removes the dependence.
7. The E2 false-latch rate inside FC windows (BENCH, gate on the Stage-1 bench supply and on the H-20).
8. R_MD pulse rating (TODO(select), as in IC1).

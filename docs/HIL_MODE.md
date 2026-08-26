# HIL mode — real Teensy against a simulated plant (fw v21)

## Purpose

HIL mode makes the **real Teensy the device under test** and replaces the *plant*
— the boosts, the pack, the bus capacitance, the motor and the car's mechanics —
with a simulation running on a host PC. The firmware does not know the difference:
`detectFaults()`, the §2 sequencing rules and their guards, the Youla drive
controller, the power-share loop, the charger logic and the state machine all run
**completely unmodified** on the injected values.

That is what makes it useful. Several classes of behaviour are hard or destructive
to provoke on the bench:

- a bus undervoltage deep enough to latch `ERR_UV_BUS`;
- a source dropping out mid-slew (the TP0201 handoff class);
- a communications failure while the board is sequencing;
- a full drive cycle without spinning a real flywheel.

In HIL those become a command-line argument. There is deliberately **no
HIL-specific fault suppression anywhere in the firmware** — a fault-injection rig
whose faults are suppressed tests nothing.

## Architecture

```
   HOST (tools/hil_plant_sim.py)                      TEENSY 4.1 (-DHIL_SIM=1)
  ┌──────────────────────────────┐                  ┌───────────────────────────────┐
  │  Plant model @ 1 kHz         │                  │  updateSensors()              │
  │   mechanical: m_eff, K_F,    │   35 B inject    │    HIL branch: assign the 7   │
  │     F_c, b_eff               │ ───────────────► │    rails + v_actual from the  │
  │   electrical: droop bus,     │   UDP :5001      │    frame (engineering units,  │
  │     source split, charger/   │   sync 0xB5      │    no SCALE_*; updateWheel-   │
  │     regen rails              │                  │    Speed() SKIPPED)           │
  │                              │                  │            │                  │
  │                              │                  │            ▼                  │
  │                              │                  │  computeDerivedSignals()      │
  │                              │                  │  detectFaults()   ← UNMODIFIED│
  │                              │                  │  state machine / controllers  │
  │                              │                  │  sequencing guards, MDAC, VESC│
  │  Reconstruct actuator state  │   16 B observe   │            │                  │
  │  ◄─────────────────────────── │ ◄──────────────  │            ▼                  │
  │   state, switches, aux pins, │   sync 0xB6      │  hilSendTick() @ 1 kHz        │
  │   I_cmd, MDAC codes, faults  │   1 kHz          │                               │
  └──────────────────────────────┘                  └───────────────────────────────┘
            │                                                     │
            └── CSV log (per tick)                                └── USB serial: banner,
                                                                      State-98 'S' dump,
                                                                      normal SD .BLG logging
```

Both frames ride the **existing** UDP socket (`local_port` 5001) — the one the Pi
bridge uses. `receiveCommands()` dispatches on packet **length**: 22 bytes is the
Pi command packet (byte-identical to fw ≤ v20), 35 bytes is a HIL injection frame,
everything else is dropped. The sync bytes are distinct as well (`0xAA`/`0xBB` for
the Pi link, `0xB5`/`0xB6` for HIL), so the two protocols cannot be confused even
before the length check.

## Frame formats

### Injection frame — host → Teensy, 35 bytes, little-endian

| Offset | Size | Field | Units / notes |
|--------|------|-------|---------------|
| 0 | 1 | sync `0xB5` | |
| 1 | 1 | `seq` | uint8, wraps; echoed in the observation frame |
| 2 | 4 | `V_fc` | V — **post-scaling engineering units**, no ADC counts |
| 6 | 4 | `V_batt` | V |
| 10 | 4 | `V_bus` | V |
| 14 | 4 | `V_chg` | V |
| 18 | 4 | `V_rgn` | V |
| 22 | 4 | `I_fc` | A |
| 26 | 4 | `I_batt` | A |
| 30 | 4 | `v_actual` | m/s (flywheel surface speed, same terms as `v_setpoint`) |
| 34 | 1 | XOR checksum | over bytes 1–33 |

Rejected if the length, the sync byte or the checksum is wrong, or if any float
decodes as NaN/Inf (an XOR checksum passes plenty of bit patterns that do, and a
NaN reaching `v_actual` poisons the drive controller's recursion permanently).
Rejections are counted and shown in the `'S'` dump.

### Observation frame — Teensy → host, 16 bytes, little-endian

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| 0 | 1 | sync `0xB6` | |
| 1 | 1 | `seq` echo | last **accepted** injection seq — round-trip latency measure |
| 2 | 1 | `mainState` | 0/1/2/3/98/99 |
| 3 | 1 | `switch_state` | `SW_FC_BUS` 0x01, `SW_BT_BUS` 0x02, `SW_MOT_PWR` 0x04, `SW_REGEN` 0x08, `SW_FC_CHARGE` 0x10, `SW_BT_SEQ` 0x20 — same packing as telemetry offset 52 |
| 4 | 1 | aux pins | bit0 `FC_REG_ENABLE`, bit1 `BT_REG_ENABLE`, bit2 `MPPT_DISABLE`, bit3 `CBAL_DISABLE` |
| 5 | 4 | `current` | float32 A, **post-clamp** motor-current command |
| 9 | 2 | MDAC code FC | raw 16-bit AD5443 word (`0x1000` control nibble + 12-bit code) |
| 11 | 2 | MDAC code BT | ditto |
| 13 | 2 | `fault_flags` | uint16 |
| 15 | 1 | XOR checksum | over bytes 1–14 |

Sent at 1 kHz from `loop()`, but only **after the first accepted injection frame**
(before that there is no host address to send to) and only when `networkUp`.

## Link-loss behaviour: hold, then zero

Two thresholds, and the staging is deliberate:

| Age of last accepted frame | Behaviour |
|---|---|
| ≤ `HIL_STALE_MS` (50 ms) | apply the injected values normally |
| ≤ `HIL_ZERO_MS` (250 ms) | **HOLD** the last values, set `hilStale` |
| > `HIL_ZERO_MS` | force **safe zeros** on all seven rails and `v_actual` |

A dropped or late packet is a *host scheduling* artefact, not a plant event.
Zeroing immediately would inject a full-scale rail collapse into `detectFaults()`
and latch a bogus undervoltage fault on nothing but a missed 1 ms tick. But a
genuinely dead link must not read as a healthy plant frozen at its last good
values either — that would let the firmware keep sequencing switches against
fiction indefinitely — so after 250 ms the injected sensors read as a
disconnected board would, and the ordinary fault logic takes it from there.

Before the *first* frame ever arrives the real ADCs are read as usual, so a HIL
flash is still readable on a desk with the simulator not yet started.

## Building and flashing

```
# Arduino IDE / arduino-cli: add the flags to the build
-DHIL_SIM=1 -DUSE_ETHERNET=1
```

`HIL_SIM=1` with `USE_ETHERNET=0` is a **compile error** — HIL rides the UDP
socket, so a build without the Ethernet stack would silently never receive a
frame.

> ⚠️ **Never attach a live power stage to a HIL_SIM=1 flash.** Every sensor value
> the firmware sees is fiction supplied by a host, so every switch decision it
> makes is made against a simulated plant. The board prints a loud boot banner to
> this effect. Reflash a normal build before any bench run.

## Running the simulator

```
python3 tools/hil_plant_sim.py \
        --teensy-ip 192.168.1.50 \
        --port 5001 \
        --scenario steady \
        --duration 30 \
        --csv hil_run.csv
```

Stdlib only — no numpy. Scenarios:

| Scenario | What it does |
|---|---|
| `steady` | fixed aux load; the quiescent baseline |
| `step-load` | +1.2 A aux load step at t = 5 s — a bus disturbance the share loop must reject |
| `sag` | −5 V bus disturbance for 1 s at t = 5 s, crossing `LIMIT_V_BUS_MIN` (12.0 V) |
| `comm-loss` | stops transmitting for 1 s at t = 5 s, then resumes |
| `drive` | plant only; the operator drives the firmware by hand (`'V'`, `'D'`, `'Y'`) over USB |

The simulator prints a 1 Hz status line and, at exit, the achieved tick rate and
worst overrun. The CSV carries every tick: injected sensor values plus the decoded
observation frame.

Plant constants are the repo's calibrated ones (fw v14 force-axis correction —
`controller_design_MIMO/calibration/motor_id_20260815.md`): `m_eff` 3.5 kg,
`K_F` 0.7538 N/A, `F_c` 2.00 N, `b_eff` 0.534 N·s/m, `V_BUS_NOMINAL` 16.0 V,
2S pack 7.4–8.4 V, ~13 V-class fuel cell.

## HIL test plan

| ID | Precondition | Stimulus | Acceptance criterion |
|----|--------------|----------|----------------------|
| **H1 — boot to idle** | Board flashed `-DHIL_SIM=1 -DUSE_ETHERNET=1`, nothing on the power stage. Simulator not yet started. | Power the board, read the USB banner; start `--scenario steady`. | Banner names HIL_SIM and the simulated-sensor warning. Within 1 s of simulator start the `'S'` dump shows `link: UP`, rising accept count, zero rejects. Board reaches State 1 (Idle) with no fault; `fault_flags == 0`. Simulator's rx count rises at ~1 kHz. |
| **H2 — fault injection (UV)** | H1 passing, board in Idle or Run with the bus brought up. | `--scenario sag` (bus −5 V for 1 s at t = 5 s). | `V_bus` in the CSV crosses below `LIMIT_V_BUS_MIN` 12.0 V for longer than the 20 ms dwell; the observation frame shows `mainState` 99 and `fault_flags` with the UV bit set, latched. Switch bitmask goes to the State-99 safe combination. No fault is raised by the sag *before* the dwell elapses. |
| **H3 — comm-loss hold-then-zero** | H1 passing, board in Idle, simulator logging. | `--scenario comm-loss` (1 s transmit gap at t = 5 s). | During the first 50 ms of the gap the board's behaviour is unchanged. `'S'` dump reads `STALE` between 50 ms and 250 ms with no fault attributable to the gap. After 250 ms it reads `DEAD (zeroed)` and the injected rails read 0 — the ordinary UV/sequencing logic responds to that as it would to a dead board. On resume, `link: UP` returns and the accept count resumes rising. |
| **H4 — closed-loop drive cycle** | H1 passing, board in State 98, `MOT_PWR_ENABLE` closed, `--scenario drive` running. | Command `'V' 1.0` (or a `'D'` drive cycle) over USB serial. | Injected `v_actual` in the CSV converges on the setpoint with no sustained ±12 A rail chatter; observed `current` shows the Hanus-conditioned ramp and release. Steady-state error small (the model has no encoder noise, so this validates the loop's *structure*, not its tuning). Compare against `controller_design_MIMO/figures/drive_siso_step.csv`. |
| **H5 — switch-sequencing observation** | H1 passing, board in State 98. | Exercise the bring-up (`'G'`), then toggle switches individually; attempt `FC_CHARGE_ENABLE` with `BT_BUS_ENABLE`/`REGEN_ENABLE` closed. | The observation frame's switch byte shows the §2 ordering at 1 ms resolution: `BT_SEQUENCE_ENABLE` off at boot then on; `assertFcChargeEnable()` drives `BT_BUS`/`REGEN` low **before** `FC_CHARGE` goes high — never a tick with the illegal combination. The aux byte shows `MPPT_DISABLE`/`CBAL_DISABLE` at their fail-safe levels from the first frame. |

## Limitations

- **Signal-level injection, not power-HIL.** Nothing electrical is exercised: the
  ADC front ends, the dividers, the INA253s, the RT1987 turn-on behaviour and the
  boosts themselves are all bypassed. A HIL pass says the *firmware logic* is
  right, not that the board is.
- **1 kHz soft real time on a non-realtime host.** Ticks can be late; the
  simulator reports achieved rate and worst overrun, and resynchronizes rather
  than replaying a burst of catch-up ticks. Read those numbers before trusting a
  timing-sensitive result.
- **The encoder estimator is bypassed.** `updateWheelSpeed()` is not called under
  HIL, so nothing here exercises the edge-period estimator, the fractional-pitch
  ledger, the adaptive gate or the corroboration hold. Those remain bench-only
  concerns, and the 74HC14 Schmitt fix is not testable here.
- **The plant model is first-order and deliberately simple.** Two simplifications
  are named at their sites in `hil_plant_sim.py`: a single droop bus node with no
  converter dynamics, and an FC/BT current split proportional to the droop MDAC
  code ratio (sign- and monotonicity-preserving, not the true analog gain). Do
  not fit control gains against it.
- **Regen is floored at zero bus current.** The rig's VESC Battery Regen Max is a
  torque clip rather than a dump path (see the 2026-08-17b addendum), so
  decelerating energy stays kinetic in this model instead of returning to the bus.

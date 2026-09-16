# fw v30 — Fuel-cell purge-dip undervoltage rework, source-depleted ruling, FC-only lockout, battery limits

Design record for firmware version 30 (2026-09-16). This document states the design rule, the
constants and their derivations, the two rulings the operator's brief asked for, the validation,
and the bench measurement that gates every working figure. The firmware version ledger
(`docs/firmware-versions.md`, row 30) carries the change summary; the `.ino` changelog block
carries the flash-facing summary.

## 1. Purpose and scope

The Horizon H-20 fuel cell ran on the bench for the first time on 2026-09-15. Its output voltage
swings to approximately 1 V on every hydrogen purge. Under firmware version 28 revision 6 the
`FAULT_UV_FC` detector, tuned on 2026-08-12 against approximately 10 ms collapses of a bench
supply, latches `ERR_UV_FC` on one purge. The share loop reacts to the current collapse
independently of the fault.

This revision re-tunes the fuel-cell rail detector, rules on the interaction between the
detector and the share loop's own cut of the fuel cell, adds a preventive rule against a
single-source fuel-cell selection while the stack is purging, and closes two battery-limit items.
It carries the firmware version 29 share-controller change unchanged. No packet, frame or
record layout changes.

The purge has not been characterised. Every constant introduced or moved here is a working
figure from the operator's brief and is marked `TODO(calibrate)` in the firmware. Section 7
states the measurement that closes them.

## 2. The design rule

The discriminator between a purge and a failed stack is duration, not threshold. A purge reaches
approximately 1 V, so no trip limit above the purge floor separates a purge from a depleted or
disconnected stack. The trip limit therefore only sets the margin under the loaded knee, and the
dwell filter's latch time and leak carry the discrimination.

The leaky-dwell shape of the bus rail is kept: time under the limit adds to a dwell integrator,
time at or above it subtracts `UV_BUS_DWELL_LEAK` times the elapsed time, and one tick credits at
most `UV_BUS_DWELL_DT_CAP_MS`. One shape serves two rails, as it did at firmware version 6.

## 3. Constants

Table 1 lists the fuel-cell rail constants before and after this revision.

| Constant | fw v28 rev 6 | fw v30 | Derivation |
|---|---|---|---|
| `LIMIT_V_FC_MIN` | 6.0 V | 4.5 V | Margin under the loaded knee only (7.8 V at 2.6 A per the brochure, `TODO(verify: H-20 datasheet)`; fw v5 bench loaded 7.8–8.2 V; TP0178 loaded minimum 7.87 V). The brief's working band is 4–5 V. |
| `UV_FC_DWELL_LATCH_MS` | 20 ms | 1000 ms | Approximately five times a 100–200 ms purge. A sustained collapse latches at 1.0 s. |
| `UV_BUS_DWELL_LEAK` (reused) | 0.05 | 0.05 | A 200 ms purge decays fully after 200 / 0.05 = 4.0 s of armed over-time. |
| `UV_BUS_DWELL_DT_CAP_MS` (reused) | 5 ms | 5 ms | A stalled loop needs at least 200 armed under-samples to latch. |
| `V_FC_ARM_THRESH` | 7.0 V | 7.0 V | Now at least 1.0 V above the limit by `static_assert` (fw v6 review C1). |
| `UV_FC_PURGE_LOCKOUT_MS` | — | 30 s | Approximately three brochure purge intervals; see section 5. |

The break-even purge interval follows from the leak. With purge duration D and leak L, a purge
train decays between purges when the interval exceeds D / L + D. At D = 200 ms and L = 0.05 that
is 4.2 s. The brochure's 10 s interval clears it by a factor of 2.4. A measured interval under
4.2 s ratchets to a latch (the host fixture pins a 2.0 s interval latching in the ninth cycle),
and in that case a dedicated `UV_FC_DWELL_LEAK` becomes a rail-specific parameter and must be
documented as such. Until the interval is measured, one shape and two rails stands.

## 4. The source-depleted ruling

Through firmware version 29 every disarm of the fuel-cell rail detector dumped its dwell. That
is correct for an operator toggle, a dark stage or the staged bring-up, because a disarmed
interval is not evidence and two unrelated bench sequences must not add into a latch. However,
it made a depleted stack unlatchable. The share loop's own cut of `FC_BUS_ENABLE` on the
current collapse (`shareIsoFC` or `shareSpCutFC`) disarmed the block and dumped its dwell; the
re-arm required the rail back above `V_FC_ARM_THRESH`, which an unloaded depleted stack does
reach; the next load collapsed it again; and the cut and re-entry cycle was the only symptom.

Ruling: no second detector. A share-loop cut holds the dwell across the disarm. The dwell is
frozen (no credit, no leak) while the block is disarmed for that reason, the tick clock keeps
running so the re-arm sees no dt jump, and the re-armed block resumes from the held value. A
depleted stack then ratchets across cycles: each loaded stint under the limit adds, the cut
holds, and the fault latches after `UV_FC_DWELL_LATCH_MS` of total loaded under-time. This is
the detector the brief described ("N re-entries within T with V_fc under the knee"), realised
through the existing shape with the leak as T. The host fixture pins 300 ms loaded stints
latching in the fourth cycle.

Every other disarm still dumps, and the fixture pins that as a negative control. A purge that the
share loop answers with a cut credits at most one purge of dwell, which the leak clears once the
block is re-armed. An excursion that is open at a disarm is now closed, counted and timed,
rather than dropped.

## 5. The FC-only hazard and the lockout

With the firmware version 28 selector holding the fuel cell alone on the bus (commanded share at
or above 0.85), `BT_BUS_ENABLE` is open. A purge then leaves the bus without a source and it
collapses at I_load / C_VBUS, measured at 2.57 V/ms at the auxiliary load, into `ERR_UV_BUS`. The
RT1987 needs approximately 8 ms to close the battery switch, so no reactive firmware rule can
save that case.

The rule is therefore preventive. A purge-class dip is an armed under-limit excursion that closed
without latching, on either close path. It arms a lockout for `UV_FC_PURGE_LOCKOUT_MS`. While
the lockout stands a commanded share at or above 0.85 lands as a battery-only selection, both in
the selection block and in the revision 5 re-arm rule, and a standing fuel-cell selection walks
back to the battery through the ordinary make-before-break selection change. The command is
re-evaluated every tick, so it is not lost: when the lockout lapses a still-standing 0.85 selects
the fuel cell as before. A running stack re-arms the lockout on every purge, so it lapses only on
a stack that has stopped purging.

A reactive escape is added beside the revision 1 raw-current escape: with the fuel cell selected
and the rail armed, a raw `V_fc` under `LIMIT_V_FC_MIN` drops the arm with the re-arm inhibit on
that tick, so the latch's guarded battery release runs on the next tick. The armed predicate
keeps a bench with no fuel cell, where `V_fc` reads approximately 0 V, from ever tripping it. On a
deep purge this escape loses the race stated above; it covers a slow collapse and makes a fast
one fail into a named fault with the battery already commanded back.

The first dip of a session precedes any lockout. Until the purge is characterised, the Pi keeps
the share command strictly inside (0.15, 0.85) on the testbed, so the battery stays on the bus.
This is an operating rule, not a firmware guarantee, and it is recorded in `WORK_QUEUE.md` 0i.

## 6. Battery limits

`LIMIT_V_BATT_MAX` moves from 10.0 V to 8.5 V. The battery divider (16.2 kΩ / 10 kΩ) saturates
the ADC at 8.646 V, so the 10.0 V value could never trip and `FAULT_OV_BATT` was dead; under
`BENCH_TEST` the overvoltage checks are the only armed faults. Consequence: a 9 V bench supply on
the battery input reads 8.646 V and now latches `ERR_OV_BATT`. The 9 V bench-battery
convenience is retired with this value.

`LIMIT_V_BATT_MIN` moves from 6.2 V to 7.4 V, the 2026-07-10 pack-floor ruling. It is enforced
through the same armed leaky-dwell shape in a new `FAULT_UV_BATT` block that replaces the single
unfiltered State-2-gated sample: `UV_BATT_DWELL_LATCH_MS` 1000 ms, arming on the battery pair
closed and `V_batt` seen at or above `V_BATT_ARM_THRESH` 7.8 V while routed, every disarm dumps,
still compiled only when `BENCH_TEST` is 0, evaluated before the bus block so a pack collapse
names its cause. The 0.4 V arm margin is a stated deviation from review C1's 1.0 V: the pack's
usable window is 7.4–8.4 V, so a 1.0 V margin would arm only a full pack and leave the fault dead
for most of every run. A launch sag through 7.4 V for tens of milliseconds no longer latches.

Consequence for the hardware-in-the-loop plant: a drained simulated pack under 7.4 V now latches
`ERR_UV_BATT`. Campaign I's compressed-cycle legs drained the pack. The plant's battery
open-circuit-voltage floor must be re-read before the next campaign.

`LIMIT_I_FC_MAX` stays 1.4 A and remains `TODO(verify)` on the cell.

## 7. The bench measurement that gates the constants

State 98, `'K'` logging at 1 kHz on the cell, two-source. Record:

1. purge duration and purge interval;
2. the `V_fc` floor during a purge;
3. the `V_fc` knee under load, against the 7.8 V at 2.6 A brochure figure;
4. whether the TPS61288 drops out (VIN UVLO) during the purge, and its soft-start time on recovery;
5. which firmware path fires: `ERR_UV_FC`, or the share loop's dark-channel or load-guard cut of `FC_BUS_ENABLE` on the current collapse;
6. `V_bus` and `I_batt` across one purge two-source.

Re-derive `LIMIT_V_FC_MIN` as the measured knee minus margin, `UV_FC_DWELL_LATCH_MS` as several
times the measured duration, check the measured interval against the 4.2 s break-even and split
the leak if it fails, and set `UV_FC_PURGE_LOCKOUT_MS` to approximately three measured intervals.
This measurement also closes the purge-timing item in `docs/HIL_PLANT.md`.

## 8. Validation

Host-native, `test/test_main.cpp`, group prefixes `test_fw30_*`, plus the re-pointed firmware
version 6 fixtures. Production 4563 checks, bench 210, hardware-in-the-loop 4870, encoder harness
51, zero firmware warnings. The purge train, the break-even ratchet, the sustained collapse, the
dt cap, the share-cut hold with its negative control, the lockout at Run entry and on the re-arm
rule, the lockout lapse, the `V_fc` escape with its no-fuel-cell negative control, and the
battery rail's arming, sag, latch, dump and saturated-supply overvoltage are each pinned.

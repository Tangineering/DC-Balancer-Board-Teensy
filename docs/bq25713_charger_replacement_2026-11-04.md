# BQ25713EVM-017 as an Ag105 replacement - feasibility note (2026-11-04)

**Status:** feasibility review only. Nothing ordered, no hardware or firmware change. Sources read in
full text: BQ25713/BQ25713B datasheet SLUSD83C (rev. May 2023, 94 pp) and the BQ2571x EVM user's
guide SLUUBT8B (Oct 2018, 23 pp). Items marked *UNVERIFIED* are not yet confirmed on hardware.

## 1. Why replace the Ag105

The board (rev 20260622) ties the Ag105's VBat- to PCB GND by design: the 2S pack's negative
terminal is board ground. The Ag105 datasheet forbids that (p.4, pins 14/15). The leading
explanation for the 2026-11-04 `J` incident (`docs/boost-bringup-debug.md`, `logs/ML0227`) is
that the tie bypasses the module's charge-current sense, so its output is unregulated. That incident
was a 1 s ramp to ~11 A of source current that the Ag105 reported as <= 0.033 A. A charger that
senses charge current on the battery POSITIVE leg works with a common ground. The BQ25713 is one.

Goal: keep the motherboard's power electronics unchanged. Remove the Ag105 and wire an off-board
BQ25713EVM-017 to its pads.

## 2. Datasheet facts that decide the fit

| Item | Value | Source |
|---|---|---|
| VBUS/ACP/ACN recommended | 0-24 V | SLUSD83C §8.3 |
| VBUS/ACP/ACN absolute max | -0.3 to 30 V | §8.1 |
| Input OVP (ACOV) | rising 25/26/27 V, falling 23.5/24.5/25 V, 100 µs deglitch | §8.5 |
| Margin vs regen clamp (~21.4 V true, `V_rgn` reads 0.85x) | ~3.6 V to ACOV min | derived |
| Architecture | NVDC: P-channel BATFET between VSYS and battery; VSYS regulated 160 mV above VBAT when BATFET is off | §9.4.1.1 |
| Battery-only start | BATFET on if VBAT > VBAT_UVLOZ; "instant-on with no battery" supported | §9.3.1, features |
| Charge-current sense | SRP/SRN across RSR on the battery side; SRN also senses battery voltage | pin table |
| 2S select | CELL_BATPRESZ divider = 40 % of VDDA -> MaxChargeVoltage 8.400 V, SYSOVP 12 V | §9.3.3.3 |
| ChargeCurrent | REG 0x03/02, 64 mA LSB at 10 mΩ, 64 mA-8.128 A, reset 0 | §9.6.3 |
| Charge termination | **host-controlled**: inhibit bit or ChargeCurrent = 0 | §9.4.1.2 |
| Charge inhibit | CHRG_INHIBIT bit (ChargeOption0) | §9.6.1.1 |
| Watchdog | default 175 s (00 off / 5 s / 88 s / 175 s); expiry -> ChargeCurrent = 0 | §9.3.10.1 |
| Input-voltage regulation (VINDPM) | REG 0x0B/0A, 3.2 V offset, 64 mV LSB, 3.2-19.52 V; reset VBUS - 1.28 V | §9.6.6.1.3 |
| Hi-Z (converter off) | ILIM_HIZ < 0.4 V enters Hi-Z, > 0.8 V exits; also REG 0x35[7] | §8.5, §9.3 |
| I2C | address D6h (8-bit) = **0x6B (7-bit)** for BQ25713; BQ25713B differs | §9.5 |
| SDA/SCL levels | ROC up to 6.5 V, so a 3.3 V pull-up is fine | §8.3 |
| CHRG_OK | active-high open drain, needs a pull-up | §9.3.3.1 |

## 3. EVM-017 facts (SLUUBT8B)

- **Connectors:**
  - J1 VIN/GND (input)
  - J5 BAT/GND
  - J6 SYS/GND
  - J3 3V3/SDA/SCL/GND
  - J2 ILIM_control (logic HIGH pulls ILIM low = converter disable), CHRG_OK, ENZ_OTG, CELL_control
  - J4 CMPIN/CMPOUT
- **Jumpers:**
  - JP1 on + JP7 top = bypass the input FETs Q9/Q10 (factory)
  - JP2-JP4 = cell setting; **2S = JP2 on, JP3 and JP4 off** (CELL pin ~2.7 V)
  - JP5 = ILIM pre-bias (factory on)
  - JP6 = ILIM low (factory off)
  - JP8 = on-board LDO drives 3V3 (factory on)
- **Fitted parts:** RAC = RSR = 10 mΩ (R2, R8, 1206 1 W); 9.2 x 8.5 mm inductor.
- **Operating range:** VIN 3.5-24 V, VBAT 0-19.2 V.
- **EV2400:** needed only for TI's PC GUI; the I2C header can be driven by the Teensy.

## 4. Proposed wiring (Ag105 removed)

| Board point | EVM | Notes |
|---|---|---|
| Ag105 VIN+ pad (behind D-RG-EN / D-FC-CH) | J1 VIN | JP1 on, JP7 top: the RT1987 on the board does the input switching |
| Ag105 VIN- / GND | J1 GND | |
| Ag105 VBat+ pad (-> D-BT-SQ -> pack) | J5 BAT | the charger regulates 8.4 V at SRN, so the pack sees 8.4 V minus the RT1987 drop (slight undercharge) |
| - | J6 SYS | leave open (caps only) |
| Teensy 18/19 | J3 SDA/SCL | see §5 item 4 on pull-ups |
| Teensy 6 `CHARGER_STAT` | J2 CHRG_OK | add a 3.3 V pull-up if none |
| Teensy 5 `MPPT_DISABLE` | J2 ILIM_control | polarity inverted, see §5 item 1 |

Mount the EVM off-board with short, heavy leads (~2.5 A on the battery side, ~1.5 A on the input).

## 5. Issues to resolve

1. **Off-switch polarity is not fail-safe.** On the EVM, HIGH means disable, so a Teensy pin that is
   low or high-Z during reset leaves the charger enabled. Options: a pull-up on ILIM_control, or
   JP6 on (ILIM held low = Hi-Z by default) with the Teensy actively releasing it. The firmware's
   meaning for pin 5 inverts either way. *UNVERIFIED on the EVM schematic.*
2. **Host-terminated charging.** The firmware must end the charge (current taper / voltage criteria).
   Set the watchdog to 5 s so a stalled Teensy stops charging.
3. **R3 (no bus-fed charging in Run).**
   - The VINDPM threshold set above the bus (e.g. ~16.5 V vs 15.9 V) is a second layer. It is a
     regulation loop, not a hard off. Bench-check that it draws ~0 from a stiff 15.9 V bus.
   - Hi-Z and CHRG_INHIBIT are hard offs.
   - The planned 1 kHz firmware interlock on `REGEN_ENABLE` (`docs/fw37_planning_2026-11-04.md`
     §3.3) is still required.
4. **I2C pull-up rail.** EVM 3V3 comes from an on-board LDO (JP8) fed from VIN. With the charger
   input unpowered, the pull-ups sit on a dead rail and may load the Teensy's bus. Check this, or
   remove JP8 and feed J3-3V3 from the Teensy's 3.3 V.
5. **Charging through D-BT-SQ.** The charger never sees the pack directly (one-way switch).
   Expected to work (voltage-regulated output, CELL_BATPRESZ is a divider, not a detector), but
   *UNVERIFIED*. Bench-test it first.
6. **Firmware.** New I2C driver (0x6B, new register map) replacing `pollAg105()` / `initAg105Charger()`
   / the MPPT-threshold manager / the `J` session. Port the fw v37 rev 2 `J` guards (source-current
   stop, unaccounted-power stop, trip latch, hardware gate).
7. **Availability.** TI lists the EVM as "limited quantities"; DigiKey NL showed 4 in stock (~€179).

## 6. Bench plan (before wiring into the board)

1. **Standalone:** 16 V supply into J1, a diode or RT1987 standing in for D-BT-SQ, then the pack on
   J5. Jumpers set to 2S.
2. **Teensy control:** drive I2C at ~0.5 A charge. Confirm the address, CV at 8.4 V, readback and
   watchdog expiry.
3. **Threshold:** set VINDPM above 16 V and confirm ~0 A drawn from a 15.9 V supply.
4. **Hard offs:** confirm both Hi-Z (ILIM_control) and CHRG_INHIBIT stop charging.
5. **Integration:** only then wire to the board, with a scope on V_chg and a clamp on the J5 lead for
   the first powered engagement.

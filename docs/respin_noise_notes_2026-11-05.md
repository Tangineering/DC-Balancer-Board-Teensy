# Board re-spin: sensing and noise design notes (working notes, 2026-11-05)

Status: **NOTE-TAKING DOCUMENT, not a committed plan.** This file collects circuit and PCB changes
that would reduce signal noise on a re-spin of board rev 20260622. Add entries as new evidence
arrives. The evidence for the first entries is the fw v37 noise round,
[`docs/reviews/noise_fw37_2026-11-05/README.md`](reviews/noise_fw37_2026-11-05/README.md),
abbreviated "noise round" below. The power-architecture re-spin note,
[`docs/respin_power_architecture_2026-11-04.md`](respin_power_architecture_2026-11-04.md), is the
companion document. Where an entry depends on the architecture chosen there, the entry says so.

Every part value, threshold and datasheet figure here is a design estimate. Values that were not
read from a datasheet in this round are marked `TODO(verify: <source>)`. Firmware changes that
need no new hardware are in the noise round, Section 6, not here.

## 1. Summary of the evidence

The noise round found the following facts that bear on hardware:
- No ADC input has an anti-alias filter (BOM 20260622, as read in the noise round;
  `TODO(verify: schematic)` for a capacitor at each Teensy pin). The firmware reads each channel
  as one 16-sample burst of about 78 µs per 1 ms tick, so content from 24 to 500 Hz folds into
  the 1 kHz control samples. The telemetry then folds it again.
- The share ratio has a flat 6–24 Hz floor of about 0.012 rms, unchanged by fw v37. It acts as a
  fixed differential current of about 1.5 ADC counts (about 12 mA). Its origin (inter-channel
  skew, aliasing, or real 25–500 Hz dynamics) is open until the 1 kHz BLG A/B in the noise round,
  Section 7.
- The standstill sensor floor is 0.6–0.8 LSB per channel. It is 7–12 % of the share floor
  variance and 1–3 % of the moving current variance.
- The V_batt floor is 9.0 mV rms, three times V_bus, for an unidentified reason. It sets the Pi
  EKF's voltage-measurement noise.
- The INA253A1 parts (0.1 V/A) give 8.06 mA per count. At the rig's 0.1–1 A currents, share
  quantization is about 0.003 rms.
- The droop ratio and the DC share differ by about 0.04 at the 0.16 rail. The estimated cause is
  a no-load voltage mismatch ΔV0 of −45 to −65 mV (low confidence). The realized droop is about
  0.21 of the design value.
- The H-20 purges every 10.34 s and shows a second event of about −0.7 V for 0.5 s, 5.5 s after
  each purge. The firmware infers both only from V_fc.
- The FC and BT boosts may operate at or inside the TPS61288 PFM boundary at the rig's currents
  (estimate, unverified).

## 2. Candidate changes

### 2.1 Anti-alias filter on every ADC input

**Change.** Add an RC low-pass at each Teensy ADC pin. Put the filter on the ADC branch only, after
the tap that feeds the AD5443 VREF, so that the hardware droop path keeps its full bandwidth.

**Starting values (noise round, sensing agent).**
- Currents: 1 kΩ series and 100 nF to AGND at the pin, corner 1.6 kHz. The series resistor keeps
  the INA253 inside its 1 nF capacitive-load limit (INA253 DS p.5).
- Dividers: 100 nF at each tap. With the present Thevenin impedances this gives V_bus 194 Hz
  (8.2 kΩ), V_fc 217 Hz (7.3 kΩ), V_batt 257 Hz (6.2 kΩ) and V_chg / V_rgn 179 Hz (8.9 kΩ).

**Rationale.** A defined front-end bandwidth bounds what the 1 kHz loop and any decimation can
see. The INA253 wideband noise bandwidth falls from about 550 kHz to about 2.5 kHz. Boost ripple
at about 500 kHz is attenuated before the sample-and-hold.

**Constraints.**
- The share controller's measurement path is part of the synthesized plant (prefilter τf 0.8 ms;
  delay margin 11.74 ms). Any corner below about 1 kHz on the current channels adds lag that the
  synthesis must include. Regenerate the coefficients through the `regen-coeffs` skill.
- Check the Teensy ADC sample-and-hold charge against the 100 nF reservoir at the chosen source
  impedance. `TODO(verify: i.MX RT1062 RM)`.
- Decide the corner after the BLG A/B. If the share floor is real 25–500 Hz dynamics, a lower
  corner (200–500 Hz) on the currents is justified. If it is a sampling artefact, 1.6 kHz is
  enough.

### 2.2 Current-sense gain: INA253A3 as originally designed

**Change.** Fit INA253A3 (0.4 V/A), the variant the board was designed for (`CLAUDE.md` §5).
Rescale the OPA197 injection gain from 5.02 to 1.255 (for example ROP1 40.2 kΩ → 2.55 kΩ with
ROP2 10 kΩ) so that RE_MAX stays 2.014 Ω and the generated share controller is unchanged.
`TODO(verify: schematic)` for the reference designators and the gain equation. Set
`K_sns = 0.4f`.

**Rationale.** The count size falls from 8.06 mA to 2.0 mA. Share quantization falls from about
0.003 to about 0.0007 rms. The ADC-referred noise falls by 4x. The INA253 input-referred noise is
unchanged, so without the filter in 2.1 the floor improves only about 1.5x; with the filter it
improves about 5x.

**Constraint.** Full scale becomes about 7.75 A at 3.1 V output. Check this against
`LIMIT_I_BT_MAX`, the OC_FC latch at 1.4 A, and the bring-up inrush.

### 2.3 Simultaneous sampling of the two currents

**Change.** Use a dedicated simultaneous-sampling ADC for I_fc, I_batt, V_bus and V_fc. A
delta-sigma part with a sinc decimator synchronous to the 1 kHz loop, and a precision reference,
would suit. The specific part is `TODO(verify: datasheet)`.

**Rationale.** It removes the about 78 µs skew between I_fc and I_batt that the present sequential
reads have. The sinc filter places nulls at the loop rate. A precision reference removes the
ratiometric 3.3 V sensitivity of V_bus: through the ×4.8 divider, 1 mV of reference noise reads as
4.8 mV of bus noise.

**Lower-cost alternative.** Keep the Teensy ADC and read the two currents synchronously on ADC0
and ADC1 in firmware (noise round, F4). Do this first; the A/B result decides whether a dedicated
ADC is worth the cost.

### 2.4 Layout and grounding of the sense path

**Change.**
- Route the INA253 GND, REF1 and REF2 to the Teensy AGND star, away from the boost PGND and the
  RT1987 switching currents.
- Route FC-CURR and BT-CURR as two separate traces, one to the ADC pin and one to MDAC VREF, with a
  ground guard.
- Kelvin-sense V_batt at the pack connector, not at the boost input, and filter it per 2.1.

**Rationale.** A ground offset between the INA253 and the ADC, or between the INA253 and the FB
node, appears directly as current error and as a V0 shift (20.1·g per volt at the INA output).
The unipolar 0-referenced mode clips any negative offset at 0 A. The V_batt floor excess points
at the BT sense node.

### 2.5 Null the no-load voltage mismatch and close the droop authority gap

**Change.** Match or trim the two FB dividers (or add a trimmable reference on one boost) so that
ΔV0 ≈ 0. Recheck the AD5443/OPA197 injection chain against the design droop, since the realized
droop is about 0.21 of the design value. This entry applies only if the droop-shared TPS61288
architecture is kept.

**Rationale.** With ΔV0 = 0 the incremental split and the DC split coincide, so load ripple
divides at the commanded share. The noise round measured the ripple split at 0.23–0.26 against a
DC share of 0.165 (component 4, about 0.006–0.008 rms). A weak realized droop makes the share
sensitive to differential V0: 2.5–3.0 share per volt. This sensitivity forced the k_d schedule
and the minority floor, which sit at the rig's operating point.

### 2.6 Boost light-load mode

**Change.** Choose a boost with a forced-PWM option, or move the TPS61288 PFM boundary out of the
operating range (inductor value, current split).

**Rationale.** In PFM the ripple frequency varies with load and aliases unpredictably into the
ADC and into the droop-injection FB node. The estimated boundary is about 0.56 A (FC) and
0.40 A (BT), from the 2.6 A typical peak threshold and L = 2.2 µH (TPS61288 DS p.12). The rig's
moving medians are 0.15 A (FC) and about 0.5 A (BT). `TODO(verify: scope on the SW nodes)`
before acting on this entry.

### 2.7 H-20 status line into the Teensy

**Change.** Route the H-20 controller's purge-valve signal (and the fan or a status line) to a
free Teensy input. Pins 2, 7 and 8 are free per the IO CSV. Add level shifting and isolation as
the controller's signal requires. `TODO(verify: H-20 controller pinout)`.

**Rationale.** A predictive purge flag lets the firmware freeze the share loop before I_fc
collapses, instead of after the V_fc dip. This removes the droop-ratio windup and the post-purge
I_fc kick completely (noise round, component 2). It also makes purge exclusion exact in every
log, and it identifies the +5.5 s mid-cycle event.

**Note.** Option 4 of the power-architecture note uses a current-commanded FC converter with
input-voltage foldback. That converter rides through a purge in hardware. The status line is
still useful for logging and for the EMS.

### 2.8 Bidirectional pack-terminal current sense

**Change.** Add a shunt and amplifier at the pack terminal, ground-referenced with REF at
mid-supply, so that the sensor reads charge and discharge current.

**Rationale.** The Pi EKF infers pack current from the unipolar bus-side I_batt and an assumed
boost efficiency of 0.90. The R0 estimate (about 0.025 Ω) and every SoC correction scale with
that assumption. Regen and charge current are invisible to the pack model. Option 4 of the
power-architecture note needs a pack-side current measurement anyway.

### 2.9 Total-current or load-current sense

**Change.** Add a third current sensor on the VBUS-to-VESC path, or a summing amplifier on the two
INA253 outputs with its own filter.

**Rationale.** The governor floor and the k_d schedule key on the total current. A measured,
filtered total removes the error-correlated division in s = I_fc/(I_fc + I_batt), and it gives
the frequency-split FC reference (noise round, F2a) a clean input. Lower priority than 2.1–2.3.

### 2.10 Speed sensing without a once-per-rev artefact

**Change.** Replace the flywheel optical disc front end with a concentric, higher-resolution
sensor, or bring the VESC tachometer into the drive loop's measurement path.

**Rationale.** Part of the remaining 1x disturbance is a disc-geometry artefact of about 0.81 %
of v (ML0226). The drive loop chases it and turns it into bus current. A sensor without the
artefact removes that part at its source. The firmware 1x canceller (fw v38 plan) is the
as-built alternative.

## 3. Changes considered and not recommended

- **FC-side bulk hold-up capacitance for purges.** V_fc collapses to about 2 V for 80–140 ms, so
  holding up the FC boost input is not economical. Treat the purge as a scheduled outage in
  firmware (or in the converter, under option 4).
- **More bus capacitance against the 1x ripple.** At 1–6 Hz the droop resistance sets the bus
  impedance, not the capacitance. With the battery alone (2026-10-26) V_bus 1x was 33–38 mV for
  0.22 A of 1x current, against 12–18 mV with both sources on the bus.

## 4. Dependence on the power architecture

If the re-spin adopts option 4 of the power-architecture note (a current-commanded FC converter
and a bidirectional pack converter), entries 2.5 and 2.6 change:
- The droop share and ΔV0 no longer set the FC current. The FC current follows a commanded
  reference.
- A frequency-split reference becomes the natural design: the FC tracks a low-passed demand, and
  the pack converter takes the fast ripple.
- Entries 2.1–2.4 and 2.7–2.10 apply to either architecture.

## 5. Open questions to settle before the re-spin

- The origin of the 6–24 Hz share floor: the 1 kHz BLG A/B with synchronous current reads (noise
  round, Section 7). The answer sets the corner frequency in 2.1 and decides 2.3.
- Whether the TPS61288 runs in PFM at the rig's currents: a scope on both SW nodes at 0.15 A and
  0.5 A.
- The source of the V_batt floor excess: a scope on the BT_VOLTAGE pin.
- The H-20 controller's available signals: its documentation or a probe on the purge valve
  drive.

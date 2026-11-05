# Board re-spin: power architecture for regen harvest + fuel-cell charging (design note, 2026-11-04)

Status: **DESIGN DISCUSSION, not a committed plan.** Written after the 2026-11-04 `J` incident
(`docs/boost-bringup-debug.md`, 2026-11-04 entry; `logs/ML0227`), which confirmed that board rev
20260622 ties the Ag105 VBat- to PCB GND by design (the pack's negative terminal is PCB ground),
which the Ag105 datasheet forbids (p.4, pins 14/15). The bus-fed charger path is unusable on this
revision. Project goals that constrain the re-spin (operator, 2026-11-04): **regen harvesting is a
goal**, and **fuel-cell charging is a goal**, with firmware control over which is enabled.

## 1. Options considered for the charger's battery return

| # | Option | Verdict |
|---|---|---|
| 1 | Swap the Ag105 for a charger with HIGH-SIDE current sensing (common-ground compatible); keep the v38 regen interlock (REGEN closed only while V_rgn > V_bus + margin; charger input threshold above the bus) | Smallest re-spin. Still limited by a slow charger booting and reacting inside a 0.3-0.6 s braking burst (measurement M1) |
| 2 | Switch BOTH battery legs off the PCB while charging | Weakest. The bus needs another source during every charge window (the FC, which purges to ~1 V); the Teensy is powered from the battery regulator (LM1084 off VBT) and would brown out; the pack can't buffer bus transients; two switch transitions + a charger bring-up per regen event; BQ29200 / V_batt divider / BT current-sense ground references move |
| 3 | Buffer regen energy on the regen node (~3.3 mF holds ~0.7 J per decel between 16 V and ~26 V: C = 2E / (V2^2 - V1^2)); charge from the buffer afterwards | Decouples capture from the slow charger. Pairs with 1 or 2. MOT_PWR must never reconnect a drained buffer at full bus (Death-5 class) |
| 4 | Replace the BT boost + charger with ONE bidirectional converter between pack and bus | **The proper architecture for regen as a project goal.** Chosen for further design below |

## 2. Option 4 architecture

- **The battery converter forms the bus (voltage mode).** It regulates V_bus at 16 V within current
  limits [-I_chg_max, +I_dis_max]: it absorbs a bus surplus and supplies a deficit.
- **The FC boost is a current-commanded source** (section 4). The EMS sets I_fc directly. This replaces
  today's two-boost droop sharing; the "share" becomes the I_fc command (a share-loop redesign).
- **The motor node must conduct onto the bus in both directions.** Today D-MT-EN (RT1987 ideal
  diode) blocks V-MOT -> bus. It must become a back-to-back switch held fully on, or a dedicated
  regen path onto the bus; the pre-charge / hot-plug rules (Death 5) must be redesigned around it.
- **The braking chopper stays as the fast clamp** for energy the converter cannot or may not absorb.
- **The FC path stays one-way** (FC boost + FC_BUS ideal diode), so regen never reaches the stack.
- **The Ag105 is retired**, and the VBat- problem with it. Charge current is commanded by firmware.

### 2.1 Regen vs FC charging: one physical action, two controlled sources

Both are the battery converter sinking current into the pack. Firmware controls which is enabled by
what it lets onto the bus and how much the converter may absorb:

| Mode | Mechanism | Enable / disable |
|---|---|---|
| FC charging | EMS commands I_fc above the load; the surplus is absorbed by the battery converter | Enabled: allow I_fc > load. Disabled: cap I_fc at the load. Charge rate = commanded surplus |
| Regen | Motor generates; V-MOT current onto the bus; the battery converter absorbs it | Enabled: charge limit covers the regen current. Disabled: cut the charge allowance while the VESC current is negative; the chopper dumps the energy |
| Both | One shared charge budget | Regen gets priority (lost if not taken); the FC surplus fills the remaining headroom |
| Neither | Battery converter discharge-only | Charge limit = 0, I_fc <= load |

Total charge current = regen allowance + FC surplus, never above the pack's CC/CV limit. Because
firmware commands the FC surplus directly and sees the motor current, it always knows the split.

### 2.2 Battery protection (moves into firmware + converter)

- CC/CV: the charge-current limit tapers as V_batt approaches 8.4 V (2S). BQ29200 OVP stays as the
  hardware backstop.
- Charge-current limits from the pack rating (`TODO(verify: pack datasheet)`); temperature limits if
  an NTC is added.
- **Bipolar current sensing on the battery channel** (the INA253s are unipolar today, REF1/REF2 to GND).

## 3. Hardware list for the re-spin (option 4)

1. A bidirectional converter between pack and bus (the TPS61288 cannot run in reverse).
2. A reverse-conducting motor-node switch, with redesigned pre-charge / hot-plug protection.
3. The FC path one-way (FC boost + FC_BUS ideal diode).
4. Ag105 removed.
5. Teensy logic supply ORed from the bus and the battery.
6. Bipolar battery-channel current sense.
7. A current-commanded FC boost (section 4).

### 3.1 Candidate parts: bidirectional pack <-> bus converter (web search 2026-11-04; NOT datasheet-verified)

Operating point to check every candidate against: pack side 7.4-8.4 V (2S, the operating floor), bus
side 16 V, ~3-6 A per channel, charging in buck (bus -> pack) and discharge in boost (pack -> bus),
automatic or fast direction change on a regen transient, and a charge-current setpoint the Teensy can
drive (DAC / PWM / I2C).

| Part | What the search found | Fit / open questions |
|---|---|---|
| **ADI LT8708** | 80 V 4-switch bidirectional buck-boost controller; four independent resistor-set current limits (forward and reverse, input and output); aimed at battery-to-battery systems; LT8708-1 slave for multiphase. The limits shift with input/output voltage; in reverse flow the input-voltage regulator takes over | Strong fit for a bus-forming battery channel. Verify: whether the limit pins can be driven from a DAC for a firmware charge-current command; direction-change speed on a regen step; light-load (DCM) behaviour |
| **Renesas ISL81601** | 60 V bidirectional 4-switch buck-boost; 4.5-60 V in, 0.8-60 V out; four loops (input/output voltage and current); peak/valley current modulation; OCP/SCP/OVP/OTP/UVP. 2018 part; ISL81401 is the 40 V version | Good fit on paper. Verify current availability, and how a current setpoint is commanded |
| **ADI LT8228** | 100 V bidirectional synchronous buck OR boost controller (two-terminal, one side above the other) with reverse-supply / reverse-current / fault protection; bidirectional voltage or current regulation; 6 V min (aggregator listing) | Fits the topology (bus 16 V always above the pack), boost to discharge, buck to charge. 6 V min is under the 7.4 V floor but check the deep-discharge case. Built-in fault isolation is attractive |
| **TI BQ25756 / BQ25750** | Bidirectional buck-boost CHARGE controllers with I2C: forward = input -> battery charging (built-in CC/CV), reverse mode = battery -> input with I2C-programmed voltage and current. E2E threads report reverse mode needing MCU supervision, a failure to auto-enter reverse at battery-only power-up, and a disputed reverse-boost capability on the BQ25750 | Built-in CC/CV charging is a plus, but the board needs the pack to FORM the bus continuously and absorb regen instantly - not a charger with a reverse mode. Ask TI before choosing it: can reverse mode regulate a 16 V bus from 2S while seamlessly accepting forward (charge) current? |

### 3.2 Candidate parts: current-commanded FC converter (same caveat)

| Part | What the search found | Fit / open questions |
|---|---|---|
| **ADI LT8705A** | 80 V 4-switch buck-boost controller with FOUR loops: input voltage, input current, output voltage, output current; the input-voltage loop reduces current when the input drops below its set point (solar / high-impedance sources); 2.8-80 V input (EXTVCC > 6.4 V) | **Best match to section 4.1**: input-current regulation (stack current), output-voltage ceiling (CV), input-voltage foldback (purge protection) in one IC. Verify: driving the current set point from a DAC, and stability with the H-20's impedance |
| **TI TPS55288** | Integrated-FET buck-boost; output voltage AND output current limit programmable over I2C (current up to 6.35 A in 50 mA steps, external sense resistor, a slow CC loop); ILIM-pin average inductor current limit; hiccup protection; -Q1 automotive variant | Simplest build (integrated FETs, I2C). But it regulates OUTPUT current, has no input-voltage foldback (purge protection would be firmware or an added clamp), and its CC loop is described as slow. Good for a quick prototype, weaker as the final FC stage |

Every row above comes from search-result summaries, mostly vendor news and third-party listings,
not from reading the datasheets. Before any of them enters a schematic, check: the operating point
above, the current-set mechanism, loop compensation with this board's sources, availability, and
package and thermal limits.

Sources: [TI BQ25756](https://www.ti.com/product/es-mx/BQ25756), [TI BQ25750](https://www.ti.com/product/BQ25750),
[BQ25750 E2E thread](https://e2e.ti.com/support/power-management-group/power-management/f/power-management-forum/1652004/bq25750-buck-boost-problem),
[BQ25756 E2E China thread](https://e2echina.ti.com/support/power-management/f/power-management-forum/806731/bq25756-bq25756),
[LT8228 listing](https://www.radiolocman.com/datasheet/data.html?di=630821),
[LT8708 (Würth reference design)](https://www.we-online.com/en/components/icref/analog-devices/LT8708-DC2719A-Buck-Boost),
[LT8708 announcement](https://www.powersystemsdesign.com/articles/a-98-efficient-bidirectional-buck-boost-controller/6/13445),
[ISL81601 (Renesas)](https://www.renesas.com/products/power-management/pwm-switching-controller/buck-boost-controllers/device/ISL81601.html),
[ISL81601 announcement](https://www.electropages.com/2018/10/renesas-electronics-true-bidirectional-synchronous-buck-boost-controllers-battery-powered-applications),
[LT8705 (Würth reference design)](https://www.we-online.com/en/components/icref/analog-devices/LT8705-DC2285A-Buck-Boost),
[LT8705 announcement](https://www.eejournal.com/industry_news/20140805_03),
[TPS55288](https://www.ti.com/product/TPS55288), [TPS55288 datasheet](https://www.ti.com/lit/pdf/SLVSF01B).

## 4. The current-commanded FC boost

### 4.1 Requirements

1. **Track a commanded current** (the EMS's "cover the load" vs "load plus charge" lever).
2. **CV ceiling (~17 V)**: if the battery converter cannot absorb (pack full, at its charge limit,
   faulted), the FC boost stops pushing current. Implemented as CC/CV with the lower-current loop
   winning (min of two error amplifiers).
3. **Input-voltage foldback**: current pulls back automatically when V_fc falls below a floor
   (solar-charger-style input regulation). An H-20 purge dip then folds back in hardware within
   microseconds; the UV_FC 1000 ms dwell becomes a backstop. Floor value `TODO(calibrate)` against
   the H-20 purge measurement (`docs/fw30_fc_purge_uv.md`).

### 4.2 Regulate stack (input) current

The stack current is what the H-20 hydrogen map and stack health depend on, and it is what the
input-voltage foldback acts on. Output current follows through the boost efficiency. The EMS can plan
in stack current directly (fits `tools/h2_map.py`).

### 4.3 Implementation options

| Option | How | Pros | Cons |
|---|---|---|---|
| A. Boost controller with a built-in CC loop (LED-driver / charger front-end class) | Sense resistor, native current loop with an analog current-set input, OVP/CV pin, often input-voltage regulation | Fast, CC/CV/foldback in one IC; reference from a Teensy DAC or filtered PWM | New power stage + compensation; check each candidate for an input-current option and a usable 17 V CV limit |
| B. Voltage-mode boost (e.g. TPS61288) + analog outer current loop | Op-amp integrator compares sensed stack current with a DAC reference and injects current into FB (the mechanism the current board uses for droop via the MDAC) | Reuses a known power stage; small added circuit | Two cascaded loops to compensate; CV ceiling and foldback as diode-OR clamps on FB; range limited by FB injection authority |
| C. Firmware current loop at 1 kHz on the existing MDAC | Teensy adjusts the FB injection code to hit an I_fc reference | No new hardware | Too slow to protect stack or bus alone; prototyping only |

**Recommendation: A on the re-spin** (Teensy DAC reference). B if the TPS61288 power stage is kept.

### 4.4 Firmware on the new board

- EMS sets the stack-current reference, rate-limited to the H-20's tolerable slew (`TODO(calibrate)`).
- Firmware detects CV-clamp / input-foldback active and reports it (telemetry flag) so the EMS knows
  its command is not being delivered.
- UV_FC / OC_FC remain as latched backstops above the analog clamps.

## 5. Prototype on the CURRENT board (option C spec seed)

Goal: test the EMS's "I_fc command" control logic and the stack's response to a current command
(purges included) before committing a layout.

- **Topology:** BT boost is the bus-forming source; the FC channel runs to an I_fc reference via the
  existing MDAC/FB injection and the FC INA253 reading, in place of the two-channel share split.
- **Constraint:** the current board cannot sink a surplus (the battery path is not reversible), so
  test only with I_fc below the load. FC charging waits for the bidirectional converter.
- **Firmware shape (to be specced in an orchestrated round):** a State-98 mode with an I_fc reference
  (key + value), a 1 kHz PI on the MDAC FC code with anti-windup at the code limits, a hard clamp at
  the existing OC_FC limit, the existing UV_FC dwell and purge lockout left in force, 1 kHz BLG
  logging, `X` stop and `Q` exit per the State-98 conventions. Touches the share path, so it needs an
  explicit operator exception to the "What NOT to change" list.
- **Measurements:** I_fc step response and tracking error vs reference; stack V/I through a purge
  with the reference held; bus behaviour with BT as the only bus former.

## 6. EMS consequences

Charging becomes an ordinary current command: "charge from the FC" is I_fc above the load, and regen
harvest stops only at the pack's charge limit, not at a charger boot delay. Today's FC_CHARGE and
REGEN windows, the charger power-up delay and the bus-feed hazard (R3) disappear. The HIL plant,
DP/SDP and governor models will need the new topology (one bus-former + one current source + a
bidirectional battery channel).

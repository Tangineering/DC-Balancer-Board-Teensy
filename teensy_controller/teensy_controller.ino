/*
 * teensy_controller.ino — Scale Car DC Balancer Board, Rev 20260622
 *
 * CHANGELOG vs. pre-20260622 firmware:
 *  - Pin map rebuilt from Scale_Car_Teensy_IO__IO.csv (CSV is authoritative).
 *  - CHARGER_ENABLE/CHARGER_OK/CHRG_CURRENT renamed; 9 new pins added (27–32, 9, 38, 39).
 *  - BQ25690 charger code (0x6A / REG_ICHG / setChargerTargetCurrentA) removed entirely.
 *    Replaced with Silvertel Ag105 MPPT charger (GPIO MPPT_DISABLE + I2C config).
 *  - RT1987 ideal-diode switches added: 6 new GPIOs with enforced sequencing state machine.
 *  - BQ29200 cell-balancer: CBAL_DISABLE (pin 9) driven LOW by default (OVP active).
 *  - ADC resolution set explicitly to 12-bit; ADC_MAX updated to 4095.
 *  - Voltage scale factors recomputed from BOM resistor values.
 *  - I_charge ADC path removed; I_charge now sourced from Ag105 I2C reg 0x06 (0.011 A/count).
 *  - V_chg and V_rgn added as ADC inputs (pins 38, 39).
 *  - Telemetry bumped to protocol v2 (54 bytes); switch_state byte replaces charger_status.
 *  - Back-feed hazard: REGEN_ENABLE driven LOW before disabling TPS61288 boosts in all states.
 *  - State 98 (Testing): USB serial hardware exerciser with simulated drive cycle.
 *  - Pi watchdog scoped to States 2 and 3 only (was: all states after first connection).
 *  - Telemetry bumped to protocol v3 (57 bytes): fault_flags expanded to uint16_t (2 bytes),
 *    error_code (1 byte) and error_source_state (1 byte) appended before checksum.
 *  - Error code system: ErrorCode_t enum + latching error_code/error_source_state globals +
 *    central triggerFault() helper; 10 new fault conditions added (OV_BATT, UV_FC, OC_BT,
 *    UV_BUS, OV_RGN, OV_CHG, I2C_CHARGER, CHARGER_STAT, INIT_FAIL, PI_TIMEOUT).
 *  - Telemetry bumped to protocol v4 (58 bytes): charger_status reinstated at offset 51 as the
 *    raw Ag105 Table 6 status byte (ag105_status_raw; see Ag105_Table6_I2C_Status_Byte.json) —
 *    Pi decodes off/CC/CV/fault from it. switch_state and all following fields shift +1; checksum
 *    span now bytes 1–56. (The old v1 charger_status — dropped in v2 — is thus restored to its
 *    historic offset, now carrying the Ag105's richer status rather than the BQ25690's.)
 *  - VBUS bring-up (post-bench-failure): boosts now default OFF in setup(); doState0() brings the
 *    bus up only with a stiff source (bus switches FIRST, settle, THEN boosts) and gates State 0→1
 *    on V_bus reaching V_BUS_CHARGED_THRESH (timeout → FAULT_INIT_FAIL). doState3() (Finish) no
 *    longer drains the bus — it leaves boosts + bus switches ON so Idle→Run never re-hot-plugs
 *    (only State 99 tears the bus down). State 98 adds a hot-plug guard on '1'/'2' and a 'G'
 *    bring-up command. No telemetry layout change.
 *  - Corrected failure analysis (supersedes the inrush framing): the killer is NOT 470µF bus
 *    inrush. VBUS carries only ~30–40µF; the 470µF bulk cap is on V-MOT behind MOT_PWR_ENABLE.
 *    ROOT CAUSE FOUND & FIXED (2026-07-07, hardware): the BT channel's output caps sit 240 mil
 *    from the IC output pin (FC: 40 mil) → ~2.7× output-cap hot-loop inductance → SW/VOUT
 *    overshoot past the 20V abs-max when the boost drives the bus (OVP at 19V leaves ~0.5V
 *    margin; energy is the boost's own ½·L·di², so a supply current limit does NOT bound it —
 *    one boost died at 120mA input limit). Fixed by bodging 10µF + 0.1µF directly at the BT
 *    boost output; validated by four consecutive surviving 'G' bring-ups under the exact
 *    conditions that killed boost #4 (see docs/boost-bringup-debug.md, the authoritative record).
 *    The supply-collapse/motorboating framing described a real aggravator on a board-powered
 *    Teensy (boost loads VBT → brownout → reset → re-enable) but was not the root cause. Under
 *    BENCH_TEST, doState0() still boots straight to Idle with the power stage OFF (no auto
 *    boost/bus enable, no V_bus gate); the bus is brought up manually via 'G'. Production
 *    (BENCH_TEST=0) keeps the full bring-up + gate. These defensive behaviors are kept.
 *  - Audit round (2026-07-01): removed pinMode(RX/TX) after Serial1 init (was reverting the pad
 *    mux to GPIO and killing the VESC UART on Teensy 4.x); PI controllers now always return a
 *    live output (integrator still gated to sampleTime; the old 0.0f sentinel chopped the motor
 *    command / slammed the droop split on sub-sampleTime ticks); power-share PI gained anti-windup
 *    (±1.0 integral authority — EMS sets share setpoint ≈ 1.0 during FC-charge cruise, so the
 *    clamp is a defensive backstop); ag105DataValid flag distinguishes a stale status byte from
 *    GENSTAT 0x00 = Battery Disconnect; State 98: '2' refuses BT_BUS while FC_CHARGE is HIGH,
 *    'Q' closes FC_CHARGE/REGEN on exit; USE_ETHERNET now #ifndef-overridable with a #warning on
 *    the production-without-Ethernet combination. LIMIT_V_BATT_MAX flagged: 10.0f is above the
 *    8.646V divider ceiling and can never trip — change to 8.5f after 9V-battery bench testing.
 *  - Motor-node pre-charge sequencing (Death 5, 2026-07-08; docs/boost-bringup-debug.md). Closing
 *    MOT_PWR_ENABLE at full bus onto the discharged 470µF+VESC V-MOT node hot-plugged the boosts and
 *    killed the FC boost. Fix: pre-charge the motor node during the low-voltage bring-up (doState0()
 *    phase 0 + bringUpBus() now raise MOT_PWR with the bus switches, before the boosts ramp), then
 *    keep it energized through Idle/Run (torn down only in State 99) so no Idle→Run re-hot-plugs it.
 *    New motPwrHotPlugUnsafe()/assertMotPwrEnable() guard (mirrors busHotPlugUnsafe) gates the
 *    full-bus ON: doState2() faults (FAULT_MOT_HOTPLUG/ERR_MOT_HOTPLUG, new) rather than hot-plug;
 *    State 98 '3' refuses it. doState1()/doState3() no longer force MOT_PWR LOW — the motor is held
 *    stopped by commandMotorCurrent(0), a deliberate change from the old "motor isolated in Idle" intent.
 *    Bus voltage parameterized on V_BUS_NOMINAL (DONE — nominal is 16.0f per the 2026-07-11 retune
 *    bullet below) — LIMIT_V_BUS_MAX / V_BUS_CHARGED_THRESH derive from it.
 *    SUPERSEDED 2026-08-03 (docs/boost-bringup-debug.md, datapoints 5-9): the low-voltage
 *    motor-node pre-charge never functioned on the bench (VIN-UVLO abort loop). Replaced by the
 *    staged bring-up (busBringupTick(), phases P0-P3): the bus is regulated ALONE first, and only
 *    then is the motor node connected from the regulated bus via D-MT-EN's soft-start.
 *    motPwrHotPlugUnsafe() is renamed motPwrConnectBlocked() and its predicate is INVERTED — it now
 *    refuses the connect unless the bus IS in regulation. bringUpBus() is deleted; State-98 'G' runs
 *    the staged machine.
 *  - Droop MDAC mapping fixed (2026-07-10; controller_design/system_model.md §4). The old
 *    k_eq/r/K_sns/A_v gain omitted the FB injection attenuation RD1/Rinj = 237k/53.6k = 4.42
 *    and, with k_eq = 0.45, commanded g > 1 for all r < 0.896 — setDroopMdac() clamped both
 *    channels to full scale, so the achieved split was stuck near 0.5 and the share loop saw a
 *    zero-gain plant. New mapping: g = K_DROOP/(RE_MAX·r) with RE_MAX = K_sns·A_v·RD1/RINJ =
 *    2.220 Ω (schematic sheets 1–2) and K_DROOP = 0.33 Ω (TODO(calibrate)); ratio clamped to
 *    [DROOP_R_MIN, DROOP_R_MAX] = [0.15, 0.85] so g ≤ 1 with margin. k_eq removed.
 *  - 16V bus retune EXECUTED (2026-07-11, hardware bodge): RD1 changed 237k → 215k on both
 *    boost FB networks (schematic still shows 237k) → V0 = 15.91V no-load. V_BUS_NOMINAL set
 *    to 16.0f (LIMIT_V_BUS_MAX → 17.0, V_BUS_CHARGED_THRESH → 13.5 derive automatically);
 *    RD1_OVER_RINJ → 215/53.6 (RE_MAX = 2.014 Ω), K_DROOP 0.33 → 0.30 (new hard bound
 *    RE_MAX·0.15 = 0.302 Ω). Also RC-BT bodged 27.4k → 61.2k (2026-07-10) to match FC —
 *    converter-loop analysis in controller_design/system_model.md §6e.
 *  - State 98 VESC read-back (2026-07-23): 'E' one-shot (getFWversion() + getVescValues() dump,
 *    incl. live mc_fault_code via vescFaultStr()) and 'U' watch (~2 Hz poll flagging fault-code
 *    changes). First reads the firmware ever makes from the VESC — previously write-only
 *    (setCurrent()). Diagnostic aid for the 0.1 A → fault bench issue; USB-serial only, no
 *    telemetry/protocol change. Reads block ≤100 ms on Serial1 and are State-98-only. The watch
 *    poll is auto-suppressed while a drive cycle / power-share profile runs so those keep
 *    production-identical motorControl()/powerBalance() timing (resumes when the run stops).
 *  - Motor current chokepoint (2026-07-29; docs/design-review-2026-07-28.md P0-3). MOTOR_I_CMD_MAX
 *    bounded only the motor PI INTEGRATOR — motorControl() sent PI_out/motorConstant straight to
 *    vesc.setCurrent(), so the unbounded proportional term reached a 50 A bridge (5 m/s error at
 *    the uncalibrated motorConstant = 0.1 → 50 A). All 11 vesc.setCurrent() call sites now route
 *    through commandMotorCurrent(), the ONLY caller: it rejects non-finite (→ 0 A), clamps to
 *    ±MOTOR_I_CMD_MAX, and mirrors the post-clamp value into `current` so telemetry reports what
 *    was actually sent and a zero-flush clears it. receiveCommands() also sanitizes the three
 *    command floats — non-finite fields hold their previous value instead of poisoning the PI
 *    integrator, v_setpoint clamps to ±V_SETPOINT_MAX (new), power_share_setpoint to [0,1].
 *    No telemetry layout change.
 *  - Motor-output ownership (2026-07-29; docs/design-review-2026-07-28.md P0-2). State 98's four
 *    motor drivers released the motor inconsistently. Set a manual current with 'A', start 'D',
 *    then stop 'D': the stop flushed a zero but left manualMotorMode set, so the standalone branch
 *    reached later in the SAME doState98() invocation reissued the stale manual current. Natural
 *    completion never flushed a zero at all, and the caller still ran motorControl() in the
 *    completion tick — with v_setpoint just zeroed and the flywheel still spinning, the error is
 *    negative, so a "finished" drive cycle commanded regen. New haltMotorOutput() primitive
 *    (clears manualMotorMode/v_setpoint/manual setpoints/pi_motor_accum/targetMotorTorque and
 *    flushes 0 A) is now used by 'D' start+stop, 'R' stop, 'X', 'Q', and both profiles' natural
 *    completion; the drive-cycle branch re-checks driveCycleActive before running the control
 *    stack. haltMotorOutput() deliberately does NOT touch the power-path switches — the State-98
 *    teardown-vs-pre-charge policy (review P1-1) is still open and left to callers.
 *  - Velocity unit chain CORRECTED (2026-07-29; user-approved exception to "what NOT to change").
 *    v_actual = rpm * flyWheelRadius / 60 yielded rev/s x inch, dropping BOTH the 2π (rad/rev) and
 *    the inch→m 0.0254, while v_setpoint from the Pi is m/s. Now v_actual = rpm * RPM_TO_MPS with
 *    RPM_TO_MPS = (2π/60)·FLYWHEEL_RADIUS_M (radius in METRES). Dead constants CPR = 16,
 *    tireRadius and lastEncoderPos removed (CPR actively contradicted ENCODER_COUNTS_PER_REV);
 *    counts/rev is now derived as ENCODER_SLOTS_PER_REV x ENCODER_QUAD_DECODE, the decode factor
 *    being x2 (verified from the ISRs: doEncoderA only decrements, doEncoderB only increments).
 *    The encoder is 2 x OPB829DZ through-beam optical sensors on a slotted disc (BOM line 71) — a
 *    home-built encoder, so counts/rev has no datasheet and must be counted by hand.
 *    IMPORTANT: the two old errors partially CANCELLED (v_actual under-read ~6.6x); correcting the
 *    form alone makes the under-read WORSE (~32x) until the slot count is measured. Because the
 *    loop closes on v_actual, under-reading means the PI OVER-DRIVES and the current clamp bounds
 *    amps, not speed — so new VELOCITY_CHAIN_CALIBRATED (default 0) makes State 98 REFUSE the two
 *    velocity entry points ('V' manual velocity, 'D' drive cycle) until both scale constants are
 *    measured. Fixed-current tests ('A') stay available. Also: timeArr[] retyped to uint32_t and an
 *    incorrect TODO removed — the old `int` did NOT corrupt dt across a micros() wrap.
 *  - Source OC limits retargeted to the right NODE (2026-07-29). Verified from the schematic
 *    netlist that the INA253 shunts sit between each boost's VOUT and VBUS (SNS-FC IS+ on VOUT-FC,
 *    IS- on VBUS-FC), so I_fc/I_batt are BUS-side currents — but both limits had been set from
 *    SOURCE-side datasheet ratings. LIMIT_I_FC_MAX 3.5 → 1.4 A (3.5 A bus-side referred to ~7.7 A
 *    from an H-20 rated ~2.6 A, so FAULT_OC_FC could not protect the stack); LIMIT_I_BT_MAX
 *    6.0 → 3.0 A (6.0 A implied ~14 A from a 10 A pack; 3.0 A is the already-validated
 *    per-channel envelope). MOTOR_I_CMD_MAX 30 → 5.0 A for bench, from the ~67-87 W source budget
 *    (15 A documented as the post-calibration vehicle value). The bus is NOT protected by the
 *    motor ceiling at all — I_bus = D·I_mot/η — so bound it in the VESC (Battery Current Max).
 *  - P_fc_actual / P_batt_actual corrected to V_bus x I (2026-07-29). They multiplied the SOURCE
 *    terminal voltage by the BUS-side current, so they were neither input nor output power and
 *    under-reported by ~2x. Telemetry LAYOUT unchanged, but these two VALUES change meaning — the
 *    Pi bridge must be updated in lockstep.
 *  - Independent control-loop rate limiting (2026-07-29). The three Run controllers were called
 *    once per main-loop tick, uncapped. motorControl() ends in a 9-byte UART frame (781 µs of wire
 *    time at 115200) and Teensy HardwareSerial::write() BLOCKS on a full TX FIFO, so a faster loop
 *    stalled inside Serial1.write() — pinning the whole loop (including detectFaults()) and queuing
 *    superseded current commands. Each controller now has its OWN period so the rates are tunable
 *    separately: MOTOR_CTRL_PERIOD_US 2000 (500 Hz), CHARGING_CTRL_PERIOD_US 20000 (50 Hz),
 *    POWER_BAL_PERIOD_US 1000 (1 kHz, the rate the Youla controller is designed for). Gating is on
 *    the CALL; a skipped call is a zero-order hold. doState2() and the State-98 drive cycle use the
 *    gated wrappers in the same order as before. The two constant-command keep-alives share the
 *    motor gate for the same reason: doState1()'s Idle zero-flush and applyManualMotor()'s
 *    MOTOR_TEST_CURRENT re-send both ran every tick, which is pure UART backpressure (500 Hz is far
 *    inside the VESC's 1000 ms command timeout, and that timeout COASTS anyway). Safety flushes
 *    (haltMotorOutput, doState3, doState99, initEsc) are deliberately NEVER gated. All three periods
 *    are TODO(calibrate).
 *  - Ag105 config now read-verify-then-write-if-different (2026-07-29). initAg105Charger() wrote
 *    both registers blind and returned success on the ACK alone, so a write that ACKed but did not
 *    land left the charger at its 1S/4.2V default while the firmware believed it was configured —
 *    a 2S pack would then charge to a 1S target with no fault. New ag105ReadConfigReg() /
 *    ag105WriteConfigRegVerified() read the register, skip the write when it already matches (no
 *    EPROM wear on every power session), and re-read to prove the value landed.
 *  - I_charge no longer goes stale (2026-07-29; review P2-1). pollAg105() cleared ag105DataValid
 *    and ag105_status_raw on charger power loss / I2C failure but left I_charge at its last value,
 *    so the Pi saw a positive charge current beside a 0x00 "no data" status byte.
 *  - Staged motor-node bring-up (2026-08-03; docs/boost-bringup-debug.md datapoints 5-9;
 *    supersedes the Death-5 low-voltage pre-charge doctrine, which never worked on the bench).
 *    busBringupTick() now runs the bus-up sequence as a non-blocking, ADC-gated phase machine
 *    (P0 bus pre-charge alone through the source switches / P1 boosts enabled / P2 dwell / P3
 *    motor node connected from the regulated bus via D-MT-EN's soft-start), shared by doState0()
 *    and the State-98 'G' command. The connect guard is inverted from the old hot-plug check:
 *    motPwrHotPlugUnsafe() -> motPwrConnectBlocked() now refuses MOT_PWR_ENABLE unless the bus is
 *    IN REGULATION (a discharged motor node at a regulated bus is the sanctioned connect).
 *    bringUpBus() is deleted. FAULT_OV_BUS gained a 10ms/3-sample persistence filter so a decaying
 *    bring-up park doesn't nuisance-latch. No telemetry layout change.
 *  - AD5443 MDAC writes were documented NOPs — FIXED (2026-08-07; found on the bench: 'O'/'R'
 *    droop sweeps could not move the share at 3 A). Verified against ad5426_5432_5443.pdf: the
 *    16-bit word is 4 control bits + 12 data bits (Fig 49), and the bare 12-bit code this
 *    firmware sent has control nibble 0000 = "No operation" (Table 10) — both DACs never left
 *    their power-on zero scale, so NO droop was ever injected on either channel and the share
 *    was pinned at the boosts' setpoint mismatch. setDroopMdac() now ORs in MDAC_CMD_LOAD_UPDATE
 *    (0x1000) and uses SPI_MODE2 (Fig 2: SCLK idles high, data latched on falling edges — the
 *    old MODE0 transitioned MOSI at the sample instant); initMdacSpiPins() writes the standalone-
 *    mode control word (0x9000, Table 10) to both DACs at boot. Every MDAC write before this fix
 *    (all sessions, both the old k_eq mapping and the corrected K_DROOP mapping) never reached
 *    the DAC register — the droop hardware chain is bench-unvalidated below this point.
 *  - SD bench logging (2026-08-10): 1 kHz binary logging of State-98 profiles to the built-in SD
 *    (SdFat/SDIO), ring-buffered non-blocking drain in loop(), auto lifecycle with the R/T/D
 *    profiles, 'K' status command, tools/decode_benchlog.py decoder.
 *  - Combined drive-cycle + power-share profile (2026-08-10, State-98 'Y'; cutoff interaction
 *    handled 2026-08-11): a single 40 s,
 *    16-region table that sweeps v_setpoint AND power_share_setpoint together, so the velocity
 *    loop and the Youla-H share loop are exercised under the cross-coupling they actually see in
 *    the vehicle (solo steps/ramps on each axis for identification, two deliberately simultaneous
 *    regions for interaction, and brief excursions to both share bounds). Velocity waypoints are
 *    NORMALISED (scaled by an operator Vmax, default 1.0 m/s, bounded by MANUAL_MOTOR_V_MAX);
 *    share waypoints are ABSOLUTE and clipped to [b, 1-b] with an operator bound b (default 0).
 *    Same prerequisites as 'D' (calibrated velocity chain + MOT_PWR_ENABLE HIGH), mutually
 *    exclusive with D/R/T, logged to YPnnnn.BLG (LOG_TYPE_PS|LOG_TYPE_DC — both phase bytes
 *    carry the region index, which is exactly the combined-profile case the log format was
 *    designed for).
 *  - Combined CURRENT + power-share profile (2026-08-10, State-98 'W'; cutoff interaction
 *    handled 2026-08-11): the same experiment with
 *    the motor axis moved from velocity to commanded current. It REUSES COMBINED_PROFILE[]
 *    verbatim — the v column is reinterpreted as a normalised current scaled by an operator Imax
 *    (default 5.0 A, ceiling TRAP_I_ABS_MAX) — and both profiles walk it through one shared
 *    advanceComboRegion() helper so their shapes cannot diverge. Motor conventions follow 'T'
 *    (direct commandMotorCurrentLimited(), no velocity PI, NO velocityChainCalibrated() gate,
 *    MOT_PWR_ENABLE warn-only), which is the point: the share loop can now be exercised against a
 *    moving motor load on an ENCODER-LESS bench. Logged to WPnnnn.BLG (LOG_TYPE_PS|LOG_TYPE_TP;
 *    ps_phase + trap_phase carry the region index). **KEY REBINDING: the VESC watch moved from
 *    'W' to 'U' ("UART watch")** to free the letter — an operator with muscle memory now lands on
 *    a parameter prompt (cancellable), never on a started motor profile.
 *  - Combined-profile x channel-cutoff interaction (2026-08-11): both combined profiles drive the
 *    share to 1.0/0.0 in R6/R11, which under the 2026-08-10 full-span actuation OPENS a bus switch
 *    under load. Both starts now WARN when the committed band reaches the cutoff region
 *    (boundLo < DROOP_R_MIN), naming the motor ceiling the switch opens against and the safe
 *    first-run command. Both NATURAL completions call restoreShareCutoffOnCompletion(), which
 *    re-closes a still-latched channel through applyShareRatio()'s own re-entry path — without it
 *    a completed run could leave the board single-sourced forever (no profile → powerBalance never
 *    runs → no re-entry). Stop/'X'/'Q' needed nothing: safeAllSwitches() already clears the flags.
 *    Also: pollVescWatch() is now suppressed during the staged bring-up.
 *  - Trapezoid SHARE-SETPOINT SWEEP (2026-08-11, State-98 'T' with an optional list):
 *    "T <Imax> <hold> <rate> [t,r1,...,rn]" runs ONE trapezoid per closed-loop share setpoint
 *    r_i (max TSWEEP_MAX_RATIOS = 16), each to its OWN TPnnnn.BLG, separated by a t-second motor
 *    cool-off dwell. It automates the 2026-08-11 hand-run sweep (TP0007-TP0013), where the
 *    setpoint/run pairing was typed by hand and a mistyped 'P' would silently mislabel a dataset.
 *    Sequenced by the non-blocking tsweepTick() (RUNNING -> WAIT_LOG -> COOLDOWN), which gates
 *    the next run on the LOGGER being fully idle — logOpenForProfile() force-finishes a still-open
 *    file and then silently skips logging on a busy card, so starting one tick early would cost a
 *    whole run's dataset. Preconditions are re-checked at fire time (plotArmTick() discipline);
 *    the setpoint is applied BEFORE each run opens its log so the first record carries it; and the
 *    share loop is returned to 0.5 / powerBalanceLive=false on completion and on every cancel path
 *    ('T' stop, 'X', 'Q', a new 'T' line, or any other profile start). Refused under plot mode.
 *    The grammar's 4th field ends the old trailing-junk tolerance: an unparsable tail now rejects
 *    the whole line rather than quietly running a single trapezoid.
 *  - fw v4 (2026-08-12) — three changes from the fw v3 validation sweep (logs TP0014-TP0038,
 *    WP0039-WP0040; docs/share_sweep_whitepaper):
 *      (a) SHARE_MINORITY_I_MIN_A 0.20 -> 0.30 A. The sweep BRACKETED the light-load conduction
 *          floor: 0.245 A commanded minority still collapsed the bus to 8.2 V (TP0016, sp = 0.15),
 *          0.29 A is clean (TP0017, sp = 0.18). The shipped 0.20 A sat below the entire bracket
 *          and governed nothing at the setpoints that failed. The governor's collapse-to-0.5
 *          threshold follows automatically (2*I_min: 0.40 -> 0.60 A).
 *      (b) SETPOINT-LATCHED CHANNEL CUTOFF (updateShareSetpointCutoff(), "one owner per
 *          setpoint"). The governor bypassed out-of-band SETPOINTS while the cutoff in
 *          applyShareRatio() fired on the controller OUTPUT r, so two structural gaps existed:
 *          sp = 0.87 settles at r ~ 0.84, IN band -> neither mitigation engaged, 19.5 Hz limit
 *          cycle (TP0037); sp = 0.12 fired the cutoff but the standing (topology-forced) share
 *          error wound r back over the 0.01 re-entry hysteresis -> ~190 FC_BUS_ENABLE cycles per
 *          run at 20 Hz (TP0015). Now the SETPOINT decides: sp outside [DROOP_R_MIN, DROOP_R_MAX]
 *          latches the starved channel off the bus (same last-source guard as the r-based cutoff;
 *          guard-blocked -> no latch, normal governed control), FREEZES the share controller
 *          (no governor, no step, no MDAC write - the integrator never sees the standing error),
 *          and disables ratio-hysteresis re-entry for that channel. Release only on the setpoint
 *          returning in-band, gated on V_bus >= V_BUS_CHARGED_THRESH, followed by
 *          resetShareControlState(). The r-based cutoff stays as the in-band backstop.
 *      (c) FAULT_UV_BUS reworked: armed by the BUS (V_bus >= V_BUS_CHARGED_THRESH with a source
 *          switch closed; disarmed whenever both source switches are LOW) instead of gated on
 *          State 2, persistence-filtered like FAULT_OV_BUS (UV_BUS_PERSIST_*), and armed under
 *          BENCH_TEST too. WP0039 sagged the bus to 7.6 V through 89 dropout cycles with
 *          fault_flags == 0 and ended in an MCU brownout: bus UV was structurally invisible on the
 *          bench. LIMIT_V_BUS_MIN stays 12.0 V. No telemetry layout change (v4/58 bytes).
 *    Review-round hardening (2026-08-12, same fw v4): the setpoint latch is now defended against
 *    EXTERNAL re-closers — doState2()/chargingControl() no longer re-assert a latched switch, a
 *    self-heal in updateShareSetpointCutoff() degrades an orphaned latch to live control instead
 *    of a frozen loop, assertFcChargeEnable(true) restores FC to the bus before cutting BT (never
 *    cut the last source), and the bring-up/State-99 paths clear the latches they take ownership
 *    of. Every bus-switch re-close (setpoint release and ratio hysteresis) now also requires its
 *    BOOST to be enabled (§2 back-feed rule), and FAULT_UV_BUS additionally disarms while both
 *    boosts are off ('F'/'B' bench sequence) or a staged bring-up is running (sanctioned P3 sag).
 *  - fw v5 (2026-08-12) — three changes from the fw v4 validation sweep (logs TP0041–TP0068,
 *    WP0069–WP0073):
 *      (a) GOVERNOR OPEN-LOOP LOW-CURRENT FALLBACK (powerBalance()). The fw v4 governor COLLAPSED
 *          the effective setpoint to 0.5 below 2*SHARE_MINORITY_I_MIN_A — which at 0.075–0.60 A of
 *          filtered total commands 0.038–0.30 A per channel, at or below the very 0.30 A
 *          conduction floor the constant enforces, against ~20 mV of droop authority. That
 *          fallback IGNITED the source-commutation relay limit cycle it existed to prevent: six
 *          runs collapsed the bus to 7–9 V and latched ERR_UV_BUS. The loop now has two MODES,
 *          hysteretic on the filtered total (enter closed loop above 0.60 A, fall back below
 *          0.60 − SHARE_GOV_OL_HYST_A = 0.55 A). CLOSED-LOOP runs the Youla controller and the
 *          (now always-relaxing) governor clip. OPEN-LOOP does not step the controller at all: it
 *          feeds the RAW setpoint forward through the same slew limiter — the sweep showed the
 *          commanded hold ratio tracks the setpoint within ~0.01–0.02 (whitepaper §6) — until the
 *          closed loop has run once, and HOLDS the last applied ratio thereafter. The open→closed
 *          transition reseeds the controller from droopSlew_prev via the new
 *          resetShareControllerCore(), which deliberately does NOT touch share_govTotAFilt (the
 *          mode decision variable). The collapse-to-0.5 branch is deleted as unreachable.
 *      (b) FAULT_UV_BUS DWELL FILTER. The fw v4 wall-clock window (10 ms + 3 samples + 5 ms gap
 *          guard) is EVADED BY DUTY CYCLE: the relay cycle's 9 ms-under / 51 ms-over period reset
 *          the window every cycle, so runs endured 1.0–1.3 s and up to 24 excursions to 7 V before
 *          latching. Replaced by a leaky dwell integrator (UV_BUS_DWELL_*): +dt under the limit,
 *          −0.05·dt above it, latch at 20 ms of net dwell, per-tick dt capped at 5 ms (the
 *          stalled-loop floor the sample count used to provide). TP0053's cycle nets +6.45 ms per
 *          cycle → latches ≈180 ms in; WP0069's sparse ~19 ms of dips over 208 ms nets ~9.6 ms →
 *          correctly no latch. Arming/disarming is unchanged.
 *      (c) BENCH-LOG FORMAT v3 (68 B/record, hdr[4] = 3): the record gains V_fc, V_batt, V_chg,
 *          V_rgn after I_cmd. Two fw v4 runs (WP0072, WP0073) ended in an MCU BROWNOUT with the
 *          BUS in regulation — the Teensy is board-powered from V_batt through the LM1084, so the
 *          rail that actually collapsed was unlogged. tools/decode_benchlog.py must be updated in
 *          lockstep. DEFERRED: a source-rail UV FAULT is not added — its threshold is set from the
 *          next brownout's logged V_batt, not from a guess.
 *    Review-round hardening (2026-08-12, same fw v5): the HOLD branch no longer strands a
 *    controller-initiated cutoff (an outstanding shareIsoFC/BT falls through to the feedforward
 *    path so applyShareRatio()'s guarded re-entry keeps running) and no longer swallows a
 *    COMMANDED setpoint change (share_actedSp re-arms the feedforward at the new setpoint);
 *    updateShareSetpointCutoff() self-heals an ORPHANED shareIso* claim the way it already did for
 *    shareSpCut* (doState2()'s re-assert is gated on !shareSpCutFC only, and an orphaned claim
 *    makes applyShareRatio() bail before every MDAC write); setPowerShareSetpointLive() resets the
 *    share-control state, so an operator 'P' after a teardown is a fresh experiment instead of a
 *    silent no-op in HOLD; resetShareControllerCore() seeds the controller INTEGRATOR (u = R0 +
 *    R(z)e + I(z)e, so integ = seed - R0 moves the DC operating point) rather than only the held
 *    output, which the back-dated Ts gate made dead; the log record's flags gain bit2
 *    (shareClosedLoopMode) and bit3 (shareClosedLoopRun) so a decoded run says which law drove the
 *    MDACs; the 'R' and 'T'-sweep natural completions call restoreShareCutoffOnCompletion() like
 *    'Y'/'W' (a bare 'T'/'D' does NOT — it never commands the share setpoint); and FAULT_UV_BUS
 *    arming requires a MATCHED source pair (bus switch + that channel's boost) instead of two
 *    independent ORs.
 *  - fw v6 (2026-08-12) — five changes from the fw v5 validation sweep (logs TP0074–TP0094 clean,
 *    WP0095–WP0101):
 *      (a) LOAD-AWARE HANDOFF GUARD on the setpoint-latched cutoff entry
 *          (SHARE_CUT_MAX_HANDOFF_A = 0.5 A). The cut transfers the doomed channel's WHOLE
 *          current to the survivor in one tick. WP0097/WP0101 fired it at 1.3–1.5 A measured; FC
 *          was then solo above this bench's ~2.1 A source knee and the bus collapsed in ~40 ms
 *          (ERR_UV_BUS). The same cut at ~0 A is validated clean (TP0074/85/86/87 run-start
 *          latches). The entry now additionally requires the DOOMED channel's |I| ≤ 0.5 A; blocked
 *          → no latch, and the tick raises a per-tick DEFERRAL (shareCutDeferredFC/BT, review S1)
 *          which (i) clips the closed-loop REFERENCE from the out-of-band setpoint onto the doomed
 *          side's band edge, so the loop actively migrates load toward the survivor, and
 *          (ii) SUPPRESSES applyShareRatio()'s r-based cutoff on that side — that cutoff has no
 *          current guard and would otherwise execute the refused handoff a few ticks later under
 *          the wrong ownership flag (shareIso*, invisible to the !shareSpCut*-gated re-closers →
 *          re-close/re-cut cycling). The cut then fires once the migration has pulled the current
 *          under the threshold.
 *          RESIDUAL: at high total current the migration may never get there — the band edge is
 *          the maximum droop authority available — and the loop sits at the edge running the
 *          rail-saturated dropout cycle instead. Self-limiting, and strictly better than
 *          collapsing the bus. Accepted until the floor-law rework.
 *      (b) SOURCE-RAIL UV FAULT on V_fc (UV_FC_DWELL_LATCH_MS = 20 ms; reuses the bus filter's
 *          UV_BUS_DWELL_LEAK / UV_BUS_DWELL_DT_CAP_MS shape parameters). This is the source-rail
 *          fault fw v5 deferred, taken now that the data exists: three fw v5 runs ended in an MCU
 *          STOP with V_fc under 5 V while V_bus still read 15.7 V — invisible to any
 *          bus-referenced fault, and leading the bus event by ~7 ms. ARMED under BENCH_TEST and
 *          in every state (the events happened in State 98); the old State-2-gated single-sample
 *          check is REMOVED. Boot-lock is prevented by ARMING, not a state gate: the fault arms
 *          only once FC_REG_ENABLE and FC_BUS_ENABLE are both HIGH (S7 matched pair) AND V_fc has
 *          been observed at/above V_FC_ARM_THRESH (7.0 V — deliberately 1.0 V ABOVE the 6.0 V
 *          trip limit, mirroring V_BUS_CHARGED_THRESH vs LIMIT_V_BUS_MIN, so a ramp cannot arm
 *          the filter inside its own trip band) while so routed, so a bench with no fuel cell
 *          (V_fc ≈ 0) never arms. Evaluated BEFORE the bus UV block so a same-tick double-cross
 *          latches the CAUSE (ERR_UV_FC) rather than the consequence (ERR_UV_BUS). The V_batt
 *          counterpart stays deferred (threshold blocked on the LM1084-input capture).
 *      (c) GOVERNOR HANDOVER CONTINUITY (share_spEffPrev). Open loop feeds the RAW setpoint
 *          forward; the first closed-loop tick handed the controller the FLOOR-CLIPPED value —
 *          a reference step of up to 0.35 share at the 0.60 A crossing (raw 0.15 → 0.50). The
 *          clipped target is now approached through a DROOP_RATIO_SLEW_PER_TICK-limited
 *          reference, seeded at every controller reset/seed from the same value the controller
 *          core is seeded with (droopSlew_prev at the OL→CL transition, 0.5 on a full reset),
 *          band-clipped. Converged behaviour is bit-identical to fw v5 — transients only. This
 *          wraps the REFERENCE; the Youla/PI internals are untouched.
 *      (d) COMBINED-PROFILE TABLE rows 5/6/7 (W and Y). All five fw v5 W failures were R6-ENTRY
 *          events, R6 being the only region combining peak load (v = 1.0) with an extreme share
 *          (s = 1.0). The excursion is KEPT but DE-RATED: R5 ramps v down to 0.3, R6 runs s = 1.0
 *          at 0.3·Imax (≈0.6 A total on this bench, under the source knee with margin), R7 takes
 *          the s step-down at that low load and ramps v back to 1.0 so R8 keeps its 1.0 → 0.5
 *          down-step. Region count, durations and the 40 s total are unchanged; rows 0–4 and
 *          8–15 are byte-identical.
 *      (e) BLG HEADER FORMAT v4 (hdr[4] = 4). RECORD FORMAT UNCHANGED (68 B). The header gains the
 *          COMMITTED per-run profile parameters: hdr[7] = param-valid flags (bit0 amp, bit1 b),
 *          float profileAmp at 20–23 (T/W Imax, Y Vmax), float profileB at 24–27 (W/Y clip bound
 *          b); bytes 28–31 reserved zero (byte 19 is the fwVersion high byte, not reserved — the
 *          fwVersion field is 2 bytes at 18–19). Derived inside logOpenForProfile() from typeMask
 *          plus the already-committed profile globals, so no call site can omit them.
 *          tools/decode_benchlog.py must be updated in lockstep.
 *  - fw v7 (2026-08-13) — velocity chain CALIBRATED; the interlock opens.
 *      (a) ENCODER GEOMETRY MEASURED on the bench by the operator: hand-turning the flywheel
 *          exactly one revolution accumulates 120 encoderPos counts, so at the verified x2
 *          quadrature decode the disc carries 60 slots — ENCODER_SLOTS_PER_REV 512.0f → 60.0f
 *          (the 512 was UNSOURCED). [SUPERSEDED by fw v8: that "120" was 120 SLOTS, not counts,
 *          so the x2 decode was applied backwards — the correct value is 120 slots / 240 counts.
 *          The x19.70 figure below is the fw 6→7 discontinuity and stays correct for fw 7 traces.]
 *          The flywheel radius was measured directly at 0.0762 m
 *          (3.00 in) — FLYWHEEL_RADIUS_M 0.033f → 0.0762f, superseding the old nominal
 *          tire-OD/2 estimate and the reasoning that the tire radius was the right one (the
 *          encoder disc is on the FLYWHEEL). RPM_TO_MPS follows both automatically.
 *      (b) VELOCITY_CHAIN_CALIBRATED default 0 → 1. With both scale inputs measured, State 98's
 *          two velocity entry points ('V' manual velocity, 'D' drive cycle) are open, as are the
 *          'Y' combined profile's velocity axis and production State 2's velocity loop. The
 *          interlock machinery (compile-time #ifndef override + the runtime
 *          velocityChainCalibratedFlag) is retained unchanged for anyone who fits a new disc or
 *          flywheel: the over-drive hazard it guards (an under-reading v_actual makes the PI add
 *          current chasing a speed already passed, and commandMotorCurrent() bounds AMPS, not
 *          SPEED) is a property of the mechanics, not of this build.
 *      (c) 'L' SERIAL-PLOTTER STREAM: six fields → eight. 'sp'/'act' renamed to
 *          'share_sp'/'share_act' (the labels were ambiguous once velocity joined), and v_sp
 *          (v_setpoint) + v_act (v_actual) appended — now that v_actual is a calibrated number,
 *          the velocity loop is worth watching live. Field order: share_sp, share_act, gFC, gBT,
 *          ifc, ibt, v_sp, v_act. The fixed-field-count rule is unchanged (the IDE plotter
 *          re-legends the graph if the count varies mid-run); the backpressure guard rises
 *          80 → 110 bytes for the longer line.
 *      (d) MOTOR_I_CMD_MAX 5.0 → 10.0 A (operator decision). The 5 A value came from the ~67–87 W
 *          source power budget, which is a BUS-current budget — but this constant clamps what
 *          setCurrent() sends the VESC, i.e. three-PHASE motor current, related to bus current
 *          only through the duty ratio. Bus current is bounded where it belongs, in the VESC's own
 *          Battery Current Max setting (≈ 4.2 A), so the source budget never bound this constant.
 *          The old derivation is kept at the constant, marked as the previous bench value; the
 *          15.0 A vehicle TODO(calibrate) stands. This is ALSO the State-98 manual-current ceiling
 *          — setManualMotorCurrent() clamps to ±MOTOR_I_CMD_MAX, so 'A' now accepts ±10 A.
 *          Unchanged and deliberately NOT following it: TRAP_I_ABS_MAX (25 A, the ESC rating, which
 *          is what 'T'/'W' bound against), W_IMAX_DEFAULT (5 A, an independently conservative
 *          profile default), and MANUAL_MOTOR_V_MAX (5.0 m/s — a VELOCITY, unrelated). The motor
 *          PI's anti-windup integMax is derived from MOTOR_I_CMD_MAX and rescales automatically.
 *      No BLG record or header change (the log already carried v_sp/v_act, and flags bit1 already
 *      reported velocityChainCalibrated()), and no UDP telemetry change — still v4 / 58 bytes.
 *  - fw v8 (2026-08-16) — encoder observability, plus the slot-count correction it uncovered.
 *      (a) ENCODER_SLOTS_PER_REV 60.0f → 120.0f, so ENCODER_COUNTS_PER_REV 120 → 240. The disc was
 *          COUNTED DIRECTLY and physically carries 120 slots. fw v7's 60 was a transcription
 *          error, not a competing measurement: the 2026-08-13 figure of "120" was recorded as 120
 *          encoderPos COUNTS and then divided by the x2 decode, when it was 120 SLOTS and the
 *          decode should have been applied. The tell is (b) — no build through fw v7 printed
 *          encoderPos anywhere, so no count could have been read. v_actual HALVES for identical
 *          motion vs fw v7; fw 7 and fw 8 v_act traces are NOT comparable (header fwVersion
 *          disambiguates). Chain vs fw ≤ 6: (1024/240) x (0.0762/0.033) = x9.85.
 *      (b) ENCODER OBSERVABILITY. v_actual was the velocity chain's ONLY observable, and the x2
 *          decoder counts only when BOTH channels transition in the right ORDER — so a dead
 *          channel, a phototransistor swing that never crosses the Teensy's V_IL/V_IH, and two
 *          beams that are not 90° apart all produce an identical, silent encoderPos == 0, none of
 *          them distinguishable from a stationary flywheel. Added volatile encEdgeCountA/B
 *          (incremented at the top of each ISR; read by nothing but the dumps), an '--- Encoder ---'
 *          block in the State-98 'S' dump (ENC_ENABLE, live ENC_A/ENC_B levels, encoderPos, both
 *          edge counts, v_actual, and the scale constants in force), and the same line in the IDLE
 *          printSensors() dump so a hand-turn check needs no test-mode entry.
 *      No control-path change: sequencing, faults, PI gains, droop and the charger are untouched.
 *      No BLG record/header change and no UDP telemetry change — still v4 / 58 bytes.
 */

#include <VescUart.h>
#include <SPI.h>
#include <Wire.h>
#include <NativeEthernet.h>
#include <NativeEthernetUdp.h>
#include <SdFat.h>              // built-in micro-SD (SDIO) — State-98 bench logger, see logSampleTick()
#include "share_controller.h"   // Youla-H power-share controller (generated coeffs)

VescUart vesc;
EthernetUDP Udp;

// ── Pin definitions (source: Scale_Car_Teensy_IO__IO.csv) ────────────────────
#define RX                  0    // UART VESC RX
#define TX                  1    // UART VESC TX
#define ENC_A               2    // IN (INT) encoder A
#define FC_REG_ENABLE       3    // OUT fuel-cell boost regulator enable
#define BT_REG_ENABLE       4    // OUT battery boost regulator enable
#define MPPT_DISABLE        5    // OUT Ag105 MPPT disable (active-LOW: LOW=inhibit, HIGH=enabled)
#define CHARGER_STAT        6    // IN  Ag105 STAT pin
#define ENC_ENABLE          7    // OUT optical encoder enable
#define ENC_B               8    // IN (INT) encoder B
#define CBAL_DISABLE        9    // OUT BQ29200 cell-balancer disable (LOW=OVP active, HIGH=disabled)
#define MOSI               11    // SPI MDAC
#define MISO               12    // SPI MDAC
#define SCK                13    // SPI MDAC
#define SDA                18    // I2C Ag105 charger
#define SCL                19    // I2C Ag105 charger
#define FC_VOLTAGE         24    // AIN fuel-cell voltage
#define BT_VOLTAGE         25    // AIN battery voltage
#define BUS_VOLTAGE        26    // AIN VBUS voltage
#define FC_BUS_ENABLE      27    // OUT RT1987: FC regulator → VBUS
#define BT_BUS_ENABLE      28    // OUT RT1987: BT regulator → VBUS
#define MOT_PWR_ENABLE     29    // OUT RT1987: VBUS → VESC/motor
#define REGEN_ENABLE       30    // OUT RT1987: regen → charger input
#define FC_CHARGE_ENABLE   31    // OUT RT1987: VBUS(FC) → charger; BT_BUS_ENABLE and REGEN_ENABLE must be LOW first
#define BT_SEQUENCE_ENABLE 32    // OUT RT1987: battery-pack sequencing; init LOW, bring HIGH once powered
#define CS_MDAC_FC         36    // SPI CS FC droop MDAC
#define CS_MDAC_BT         37    // SPI CS BT droop MDAC
#define CHG_VOLTAGE        38    // AIN charger input voltage
#define RGN_VOLTAGE        39    // AIN regen-node voltage
#define FC_CURRENT         40    // AIN FC current (INA253)
#define BT_CURRENT         41    // AIN BT current (INA253)

// ── ADC calibration constants ─────────────────────────────────────────────────
#define ADC_VREF    3.3f
#define ADC_MAX     4095.0f     // 12-bit resolution; matches analogReadResolution(12) in setup()

// Voltage scale factors — formula: V_in = ADC_count * ADC_VREF/ADC_MAX * (R1+R2)/R2
// Source: BOM R1-FC=27.4kΩ, R2-FC=10kΩ → Vmax = 3.3*(27.4+10)/10 = 12.342V
#define SCALE_V_FC    (ADC_VREF * (27.4f + 10.0f) / 10.0f / ADC_MAX)
// Source: BOM R1-BT=16.2kΩ, R2-BT=10kΩ → Vmax = 3.3*(16.2+10)/10 = 8.646V
#define SCALE_V_BATT  (ADC_VREF * (16.2f + 10.0f) / 10.0f / ADC_MAX)
// Source: BOM R1-BUS=46.4kΩ, R2-BUS=10kΩ → Vmax = 3.3*(46.4+10)/10 = 18.612V
#define SCALE_V_BUS   (ADC_VREF * (46.4f + 10.0f) / 10.0f / ADC_MAX)
// Source: PCB schematic R1-CHG=78.7kΩ, R2-CHG=10kΩ → Vmax = 3.3*(78.7+10)/10 = 29.271V
#define SCALE_V_CHG   (ADC_VREF * (78.7f + 10.0f) / 10.0f / ADC_MAX)
// Source: PCB schematic R1-SNT=78.7kΩ, R2-SNT=10kΩ (same values as CHG; different net: regen node)
#define SCALE_V_RGN   (ADC_VREF * (78.7f + 10.0f) / 10.0f / ADC_MAX)

// Current scale: INA253A1, K_sns=0.1 V/A, unipolar 0-ref; Source: INA253A1IPWR.pdf
#define SCALE_I  (ADC_VREF / ADC_MAX / K_sns)   // 12-bit, Vref=3.3V, K_sns=0.1 → ~8.06 mA/count

// ── Fault bitmask constants (uint16_t) ────────────────────────────────────────
#define FAULT_OC_FC           0x0001  // I_fc overcurrent
#define FAULT_UV_BATT         0x0002  // V_batt undervoltage
#define FAULT_OV_BUS          0x0004  // V_bus overvoltage
#define FAULT_SWITCH_CONFLICT 0x0008  // FC_CHARGE_ENABLE asserted while BT_BUS or REGEN high
#define FAULT_PI_TIMEOUT      0x0010  // Pi watchdog expired
#define FAULT_OV_BATT         0x0020  // V_batt overvoltage (charging protection)
#define FAULT_UV_FC           0x0040  // V_fc undervoltage / fuel cell depleted
#define FAULT_OC_BT           0x0080  // I_batt overcurrent (BT boost path)
#define FAULT_UV_BUS          0x0100  // V_bus undervoltage: source-feed loss / bus collapse. ARMED by
                                      // the bus (V_bus >= V_BUS_CHARGED_THRESH with a source switch
                                      // closed), not by State 2; disarmed while the switches are open,
                                      // both boosts are off, or a staged bring-up is running; latches
                                      // only after the UV_BUS_DWELL_* leaky-integrator filter
                                      // (2026-08-12; dwell filter fw v5)
#define FAULT_OV_RGN          0x0200  // V_rgn overvoltage spike (regen node)
#define FAULT_OV_CHG          0x0400  // V_chg charger input overvoltage
#define FAULT_I2C_CHARGER     0x0800  // Ag105 I2C comms failure
#define FAULT_CHARGER_STAT    0x1000  // Ag105 GENSTAT error condition
#define FAULT_INIT_FAIL       0x2000  // Init sequence failure (State 0)
#define FAULT_MOT_HOTPLUG     0x4000  // MOT_PWR_ENABLE refused: motor node not pre-charged at full bus
#define FAULT_ERROR           0x8000  // Latched: system is in or has entered State 99

// ── Safety limits ─────────────────────────────────────────────────────────────
// ── Source overcurrent limits ────────────────────────────────────────────────
// CRITICAL NODE NOTE (corrected 2026-07-29): I_fc and I_batt are BOOST-OUTPUT (bus-side) currents,
// not source-input currents. Verified from the schematic netlist: SNS-FC's IS+1/2/3 sit on VOUT-FC
// (= REG-FC's VOUT pin) and IS-1/2/3 on VBUS-FC (= D-FC-EN's VIN), so the INA253 shunt is between
// the TPS61288 output and the RT1987 ideal-diode input. Same for SNS-BT / VOUT-BT / VBUS-BT.
// (references/Scale_Car_Board_20260624.sch.)
//
// Both limits were previously set from SOURCE-side datasheet ratings and compared against these
// BUS-side measurements, so neither fault protected its source:
//   - LIMIT_I_FC_MAX was 3.5 A bus-side. Referred to the stack that is 3.5·16/(0.93·7.8) ≈ 7.7 A
//     from an H-20 rated ~2.6 A — roughly 3× over. FAULT_OC_FC could not trip before the stack was
//     abused.
//   - LIMIT_I_BT_MAX was 6.0 A bus-side ≈ 14.1 A from a pack rated 10 A.
// Retargeted below to bus-side equivalents of the real source ratings.
//
// FC: H-20 rated 20 W, 7.8 V @ 2.6 A. Bus-side equivalent at 16 V with η≈0.93:
//     2.6 · 7.8 · 0.93 / 16 = 1.18 A. Set 1.4 A to leave headroom for η and V_fc spread.
// TODO(verify: H-20 datasheet). The H-20 datasheet is NOT in references/ — the 20 W / 7.8 V / 2.6 A
// figures are externally sourced (Horizon H-20 product page + manual), not from a repo artifact.
// Confirm against the physical datasheet and re-derive before trusting FAULT_OC_FC.
#define LIMIT_I_FC_MAX   1.4f   // A (BUS-SIDE) — H-20 2.6 A input referred through the boost
#define LIMIT_V_BATT_MIN 6.2f   // V — 2S LiPo cutoff (2 × 3.1V)
// Nominal regulated bus voltage — set by the boost FB network in HARDWARE; the firmware thresholds
// below derive from it. Death-5 headroom plan (docs/boost-bringup-debug.md) EXECUTED 2026-07-11:
// RD1 bodged 237k → 215k on BOTH channels (schematic not yet updated), so the no-load setpoint is
// V0 = 0.6·(1 + 215/10 + 215/53.6) = 15.91V ≈ 16V. This widens the SW/VOUT abs-max headroom
// (20V − 16V = 4V vs 2.5V) and keeps the bring-up soft-start overshoot clear of OV_BUS.
#define V_BUS_NOMINAL    16.0f  // matches the RD1 = 215k FB network (V0 = 15.91V no-load)
// Source: user-confirmed TPS61288 HW OVP at 19V. FW OV fault sits 1.5V above nominal (16.0 →
// 17.5), still below the 19V HW OVP so firmware catches a sustained overvoltage first, and
// matches the Death-5 ladder (nominal 16 < FW 17.5 < OVP 19 < abs-max 20). Raised from +1.0
// (operator decision, 2026-07-31): bring-up load-dump releases park the unloaded rail above the
// old limit, which tripped OV_BUS on ~80% of bring-ups. Measured (2026-08-03, capture metrology):
// parks reach ~17.0–17.2V at the ADC node and DECAY at ~44–113 V/s (≤ ~5ms above 17.0V) — the
// earlier "~50–400ms" figure here was superseded. Restore +1.0f after the staged bring-up below
// is bench-validated (operator decision 2026-08-03) — the OV persistence filter carries the
// residual transients. See docs/boost-bringup-debug.md (2026-07-31 → 08-03 entries).
#define LIMIT_V_BUS_MAX  (V_BUS_NOMINAL + 1.5f)
// FAULT_OV_BUS persistence (2026-08-03): bring-up parks are DECAYING transients (44–113 V/s), so
// a single over-limit ADC sample must not latch State 99. The fault latches only after the bus has
// been continuously over-limit for OV_BUS_PERSIST_MS AND for at least OV_BUS_PERSIST_MIN_SAMPLES
// consecutive loop ticks (the sample floor guards a stalled loop: two spikes bracketing a blocked
// ≥10ms stretch must not read as "continuously over"). While over but not yet latched, the
// FAULT_OV_BUS bit still shows in fault_flags/telemetry (truthful transient indication, no latch).
// A genuine sustained overvoltage latches ~10ms late — acceptable: the TPS61288 HW OVP (19V) is
// the fast backstop. Note firmware structurally CANNOT see cut-release parks (an SCP-cut switch
// isolates the ADC node from the parked boost output) — hardware (CSS, output caps) owns those.
#define OV_BUS_PERSIST_MS          10u  // ms — continuous over-limit time to latch. TODO(calibrate)
#define OV_BUS_PERSIST_MIN_SAMPLES 3u   // consecutive over-limit loop ticks. NOTE: with
                                        //      OV_BUS_MAX_GAP_MS=5 < PERSIST_MS=10 the gap guard
                                        //      already forces ≥3 samples per window — this floor
                                        //      is subsumed belt-and-suspenders (kept in case the
                                        //      gap/persist constants are recalibrated apart)
#define OV_BUS_MAX_GAP_MS          5u   // ms — max spacing between over-samples still counted as
                                        //      one continuous window (review F4: three sparse
                                        //      samples spanning a stalled stretch must not read
                                        //      as "continuously over"). Normal loop ticks are
                                        //      sub-ms; a gap this large restarts the window.
//#define LIMIT_V_BATT_MAX  8.6f  // V — 2S LiPo max (4.3V/cell × 2 + 0.2V margin)
// TODO: change to 8.5f. The BT divider (16.2k/10k, BOM-confirmed) saturates the ADC at
// 3.3*2.62 = 8.646V, so 10.0 can NEVER trip (OV_BATT is currently dead — and under BENCH_TEST
// the OV checks are the only armed faults). Even the old 8.6f left only ~22 ADC counts of
// headroom below the ceiling. 8.5V gives real margin while still protecting a 2S pack.
#define LIMIT_V_BATT_MAX 10.0f  // TEMP for using 9V battery for testing (unreachable — see above)
#define LIMIT_V_FC_MIN    6.0f  // V — H-20 minimum
// BT (BUS-SIDE — see the node note at LIMIT_I_FC_MAX). Set to the already-validated conservative
// per-channel envelope of 3 A (controller_design/system_model.md §9; docs/design-review-2026-07-28.md
// step 7), which is also the TPS61288 f_c ≤ f_RHPZ/5 margin point at worst-case cap derating.
// Input-side equivalent at 7.4 V, η≈0.92: 3·16/(0.92·7.4) = 7.05 A, inside the pack's 10 A rating.
// Raise toward 4.2 A (the pack-rating-limited value) only after the high-bandwidth SW/VOUT ring
// capture validates the margin. TODO(calibrate).
#define LIMIT_I_BT_MAX    3.0f  // A (BUS-SIDE) — validated per-channel envelope
// FAULT_UV_BUS threshold. Kept at 12.0 V through the fw v4 rework (2026-08-12): the fw v3 events
// it must catch sit FAR below it (TP0016 collapsed to 8.2 V, WP0039 sagged to 7.6 V), while normal
// loaded operation sits FAR above it (15.6 V measured under the sweep's trapezoid load), so 12.0 V
// separates the two populations with ~3 V of margin on both sides.
// TODO(calibrate): consider tightening to 14.0 V after the fw v4 FIX-VALIDATION re-sweep — the
// nearer the threshold sits to the regulated bus, the earlier a developing dropout latches, but it
// must stay clear of the deepest legitimate loaded sag (measure it on that sweep before moving).
#define LIMIT_V_BUS_MIN  12.0f  // V — minimum VBUS while the bus is armed (see uvBusArmed)
// FAULT_UV_BUS dwell filter (fw v5, 2026-08-12 — REPLACES the UV_BUS_PERSIST_* wall-clock window
// that shipped in fw v4). The fw v4 validation sweep (TP0041–TP0068, WP0069–WP0073) showed the
// window filter is EVADED BY DUTY CYCLE: a source-commutation relay cycle spends ~9 ms under
// 12 V and ~51 ms over it per ~60 ms period (TP0053), so every window closed before
// UV_BUS_PERSIST_MS = 10 ms elapsed and reopened from zero on the next cycle. Runs endured
// 1.0–1.3 s and up to 24 excursions to 7 V before anything latched — a filter tuned for a
// CONTINUOUS sag cannot see a REPETITIVE one.
//
// The replacement accumulates DWELL instead of measuring a window: time under the limit is added
// to uvBusDwellMs, time at/above it is subtracted at UV_BUS_DWELL_LEAK × dt. A repetitive cycle
// therefore ratchets up (net gain per cycle) while isolated dips decay away, which is exactly the
// selection the fault needs. Arithmetic against the two bounding fw v4 datasets:
//   - TP0053 relay cycle (9 ms under / 51 ms over per 60 ms): net +9 − 0.05·51 = +6.45 ms per
//     cycle → dwell crosses 20 ms early in the 4th under-phase, ≈180 ms after the cycle starts
//     (fw v4 took 1.0–1.3 s). Requirement was ≤ 5 cycles.
//   - WP0069 sparse transients (~19 ms total under-time in ≤2.3 ms excursions spread over
//     208 ms): net ≈ 19 − 0.05·189 = 9.6 ms, below the 20 ms latch → correctly no latch, the
//     transient counter and telemetry bit still report it.
//   - A CONTINUOUS collapse latches in 20 ms (was 10 ms). Accepted: the old 10 ms was evadable,
//     and 20 ms is still ~2 orders of magnitude inside the observed 1.0–1.3 s endurance.
// DEFERRED (fw v5): a SOURCE-RAIL undervoltage fault on V_batt (the rail feeding the LM1084 logic
// regulator) is NOT added here. Two fw v4 MCU brownouts (WP0072, WP0073) happened with the BUS in
// regulation, so the bus UV filter cannot see them and the source rails are unlogged — the .BLG
// v3 format below adds V_fc/V_batt/V_chg/V_rgn precisely so the next brownout sets that threshold
// from data instead of a guess.
#define UV_BUS_DWELL_LATCH_MS   20.0f  // ms of accumulated net under-dwell → latch. TODO(calibrate)
#define UV_BUS_DWELL_LEAK       0.05f  // fraction of dt subtracted while at/above the limit.
                                       //      TODO(calibrate) — sets the rejected duty cycle:
                                       //      dwell decays only if under-time < LEAK × over-time
#define UV_BUS_DWELL_DT_CAP_MS  5.0f   // ms — per-tick dt contribution cap. Replaces the old
                                       //      UV_BUS_PERSIST_MIN_SAMPLES stalled-loop floor: a loop
                                       //      that stalls (or a long-disarmed interval) can credit
                                       //      at most 5 ms of dwell in one tick, so a latch still
                                       //      needs >= 4 armed under-samples (fw v4 needed 3).
                                       //      TRADE-OFF: under a BLOCKED loop the wall-clock latch
                                       //      time is 4 ticks of whatever the loop period has
                                       //      become - e.g. ~400 ms at a 100 ms stalled tick. That
                                       //      is accepted: a loop stalled that badly is its own
                                       //      fault class, and crediting an unbounded dt per tick
                                       //      would let ONE late tick latch on a sag it never
                                       //      actually observed
// FAULT_UV_FC dwell filter (fw v6, 2026-08-12) — SOURCE-RAIL undervoltage on V_fc. This is the
// first half of the source-rail fault the fw v5 note above DEFERRED, now taken because the fw v5
// sweep produced the data it was waiting for: three runs (WP0096, WP0098 and one truncated
// sibling) ended in an MCU STOP with V_fc logged BELOW 5 V while V_bus still read 15.7 V — the
// bus was in regulation, so no bus-referenced fault could ever see it, and the old State-2-gated
// single-sample V_fc check was compiled out under BENCH_TEST and gated out of State 98 anyway.
// The V_fc collapse LEADS the bus event by ~7 ms in those logs, so an armed source-rail fault
// latches first and names the true cause (ERR_UV_FC, not ERR_UV_BUS).
// Filter SHAPE is the bus filter's, verbatim: +dt under the limit, −UV_BUS_DWELL_LEAK·dt above
// it, per-tick dt capped at UV_BUS_DWELL_DT_CAP_MS. Those two are FILTER-SHAPE parameters (which
// duty cycle is rejected; what one stalled tick may credit), not rail-specific quantities, so
// they are REUSED rather than duplicated — one shape, two rails.
// The V_batt counterpart is still deferred: its threshold is blocked on the LM1084-input capture.
#define UV_FC_DWELL_LATCH_MS   20.0f  // ms of accumulated net under-dwell on V_fc → latch.
                                       //      Same 20 ms as the bus: the WP0096/WP0098 excursions
                                       //      are ~10 ms of CONTINUOUS collapse each, so a
                                       //      repetitive pair (or one longer sag) latches, while a
                                       //      single isolated 10 ms dip leaks away.
                                       //      TODO(calibrate) against the fw v6 re-sweep.
// ARMING threshold, DISTINCT from the trip limit (fw v6 correctness review C1). Arming and
// tripping on the SAME 6.0 V leaves zero margin: a fuel-cell ramp that ticks to exactly
// LIMIT_V_FC_MIN once would arm, then dip back under during the same ramp and latch ERR_UV_FC
// mid-bring-up — the filter's dwell integrator cannot distinguish that from a real collapse.
// The bus filter this block mirrors never had that problem because it arms at
// V_BUS_CHARGED_THRESH, 3 V above LIMIT_V_BUS_MIN; this is the same pattern with the same intent.
// Value: healthy loaded V_fc measured 7.8–8.2 V across the fw v5 bench runs, so 7.0 V arms
// comfortably below normal operation (no run fails to arm) while sitting 1.0 V above the trip
// limit (no ramp arms while still inside the trip band). TODO(calibrate): re-check both edges on
// the fw v6 re-sweep, and against the vehicle fuel cell rather than the bench source.
#define V_FC_ARM_THRESH         7.0f  // V — V_fc must be seen at/above this, while routed, to arm
#define LIMIT_V_RGN_MAX  28.0f  // V — regen node spike ceiling
#define LIMIT_V_CHG_MAX  24.0f  // V — charger input max

// ── VBUS controlled bring-up (State 0) ───────────────────────────────────────
// NOTE: an earlier rationale here blamed 470µF bus inrush. That was wrong — corrected:
//   - VBUS carries only ~30–40µF (the RT1987 ceramics). The 470µF bulk cap (schematic sheet 4,
//     EEE-FN1V471UP) sits on the V-MOT / regen node BEHIND MOT_PWR_ENABLE, so it is not on VBUS
//     during Init. Bus inrush is negligible and was never the failure cause.
//   - ROOT CAUSE (validated 2026-07-07, hardware — see docs/boost-bringup-debug.md): the BT
//     channel's output caps sit 240 mil from the TPS61288 output pin (FC channel: 40 mil) →
//     ~2.7× output-cap hot-loop inductance → SW/VOUT overshoot past the 20V abs-max when the
//     boost drives the bus (OVP at 19V leaves only ~0.5V margin). The energy is the boost's own
//     ½·L·di², so a SUPPLY current limit does NOT bound it (one boost died at a 120mA limit).
//     Fixed by bodging 10µF + 0.1µF directly at the BT boost output; validated by four
//     consecutive surviving 'G' bring-ups under previously-fatal conditions. Any BT boost rework
//     MUST keep these caps (or a respun layout with Cout at the IC).
//   - Secondary hazard (real, but an aggravator — not the root cause): enabling a boost on a
//     source that can COLLAPSE. The Teensy is board-powered (LM1084 off VBT); on a weak /
//     current-limited source the boost loads VBT, the rail sags, the Teensy browns out and
//     re-enables the boost on reboot (motorboating). The bring-up sequencing below defends
//     against this.
// STAGED BRING-UP (2026-08-03, supersedes the low-voltage motor-node pre-charge doctrine):
// bench captures 5–9 (docs/boost-bringup-debug.md) showed that charging the whole
// VBUS + V-MOT + VESC chain in one RT1987 connect event rides the foldback clamp >250µs with the
// VESC attached → SCP cut + 64ms retry, with the cut-release parking the boost output at ~18V
// (TPS61288 rec-max; INVISIBLE to the firmware ADC — the cut switch isolates the node). A connect
// from an already-regulated bus completes acceptably (captures 5 deep-dip and 9 dip-2). The old
// low-voltage pre-charge also never functioned on the bench (VIN-UVLO abort loop at 5.6nF CSS).
// So the bring-up is now STAGED (shared machine busBringupTick(), used by production doState0()
// and the State-98 'G' command): P0 pre-charge the ~40µF bus alone through the source switches
// (MOT_PWR held LOW), P1 boosts regulate the bus, P2 dwell confirms regulation is stable, P3
// connects the motor node (470µF + VESC) from the regulated bus via the D-MT-EN 100nF-CSS
// soft-start. HARDWARE PREREQUISITE: 100nF CSS on D-MT-EN before P3 ever runs on the bench.
#define V_BUS_CHARGED_THRESH (V_BUS_NOMINAL - 2.5f)  // V — bus considered "up" (17.5→15.0; 16.0→13.5)
#define BUS_CHARGE_TIMEOUT_MS 800u   // ms — max for boosts to reach V_BUS_CHARGED_THRESH; else
                                     //      FAULT_INIT_FAIL (dead boost / failed switch / no source).
                                     //      TODO(calibrate)
// P0 gate: the bus must reach the winning source (through the switch + TPS61288 body-diode path)
// before the boosts are enabled. Measured switch connect at 100nF CSS: tD_ON 8ms + tON ~20ms at
// 16V ≈ 28ms (capture 8, 1.8% match) — PRECHARGE_MIN_MS also forces full RT1987 *enhancement*
// (the voltage gate alone can be met through a half-enhanced FET). V_PRECHARGE_MIN is an absolute
// floor so a dead/absent source (V_fc/V_batt reading ~0) cannot vacuously pass the relative gate.
#define PRECHARGE_DROP_MAX    1.5f   // V — max V_bus deficit vs max(V_fc,V_batt): switch + body
                                     //     diode + divider tolerance. TODO(calibrate)
#define V_PRECHARGE_MIN       5.0f   // V — absolute P0 floor (below LIMIT_V_FC_MIN and 2S cutoff).
                                     //     TODO(calibrate)
#define PRECHARGE_MIN_MS      40u    // ms — ≥ tD_ON(8) + tON(~20 @100nF) + margin. TODO(calibrate)
#define PRECHARGE_TIMEOUT_MS  300u   // ms — covers one RT1987 SCP 64ms retry cycle. TODO(calibrate)
// P2 dwell: regulation must HOLD before the motor node is offered the bus; a dip below the
// threshold restarts the dwell, and the overall timeout bounds a restart livelock.
#define BUS_REG_DWELL_MS      50u    // ms — continuous V_bus ≥ thresh before P3. TODO(calibrate)
#define BUS_DWELL_TIMEOUT_MS  500u   // ms — overall P2 bound → FAULT_INIT_FAIL. TODO(calibrate)
// P3: motor-node connect window. Covers ≥2 SCP retry cycles (64ms each) + ~30ms CSS connects —
// capture 9's retry completed at ~83ms total.
#define MOT_CONNECT_TIMEOUT_MS 500u  // ms — V_rgn must track V_bus by then → FAULT_MOT_HOTPLUG.
                                     //      TODO(calibrate)

// Motor-node (V-MOT/regen) connect gating — see motPwrConnectBlocked(). DOCTRINE (2026-08-03,
// inverts the Death-5 rule): MOT_PWR_ENABLE may be turned ON **only at a regulated bus** — the
// D-MT-EN 100nF soft-start then charges the 470µF + VESC stack from the charged bus + boosts, the
// empirically-validated connect class. Dark-bus and mid-ramp connects are refused: a node hanging
// on the chain when the boosts later ramp recreates the SCP-cut/18V-park event (capture 9 dip-1).
// MOT_HOTPLUG_MARGIN is the P3 COMPLETION margin: V_rgn within this of V_bus = node connected.
#define MOT_HOTPLUG_MARGIN    3.0f   // V — TODO(calibrate) from the observed connected V_rgn gap

// ── Staged bring-up machine state (shared by doState0() and State-98 'G') ─────
// File-scope (not function-local statics) so the host test suite can reset it between cases —
// same hoisting precedent as the PI accumulators. See busBringupStart/Tick/Abort().
typedef enum : uint8_t { BRINGUP_IDLE = 0, BRINGUP_RUNNING, BRINGUP_DONE, BRINGUP_FAILED } BringupStatus;
bool     bringupActive     = false;  // machine armed (busBringupStart() → DONE/FAILED/abort)
uint8_t  bringupPhase      = 0;      // 0=P0 entry, 1=P0 gate, 2=P1 gate, 3=P2 dwell, 4=P3 entry, 5=P3 gate
uint32_t bringupPhaseStart = 0;      // ms — current phase entry time (timeout base)
uint32_t bringupDwellStart = 0;      // ms — P2 dwell-window start (restarts on a V_bus dip)

// ── FAULT_OV_BUS persistence state ────────────────────────────────────────────
// File-scope for test resettability. See the OV_BUS_PERSIST_* rationale above / detectFaults().
bool     ovBusOverActive  = false;   // an over-limit window is open
uint32_t ovBusOverSince   = 0;       // ms — window start
uint32_t ovBusLastOverMs  = 0;       // ms — previous over-sample (gap guard, review F4)
uint8_t  ovBusOverSamples = 0;       // consecutive over-limit loop ticks (saturating)
uint16_t ovBusTransientCount = 0;    // windows that closed WITHOUT latching (review F5 — the
                                     // only trace a sub-persistence park leaves; shown by 'S';
                                     // includes windows abandoned by the gap guard)
uint32_t ovBusPrintLastMs = 0;       // ms — last "[OV] transient" print (1 Hz rate bound: an
                                     // alternating over/under sample stream must not print per
                                     // window and re-create the UART storm — review round 2)
bool     ovBusHasPrinted  = false;   // distinguishes "never printed" from a print at millis()==0
                                     // (review round 3: a 0-sentinel would defeat the rate bound
                                     // for boot-time windows)

// ── FAULT_UV_BUS arming + persistence state (2026-08-12) ─────────────────────
// File-scope for test resettability, mirroring the OV block above. ARMING replaces the old
// mainState == 2 gate: the fw v3 validation sweep ran its collapses in State 98, where the
// production State-2 gate (and the !BENCH_TEST guard) left the board with NO bus-UV indication at
// all — WP0039 sagged to 7.6 V through 89 dropout cycles with fault_flags == 0 and ended in an MCU
// brownout. The fault is now armed by the BUS ITSELF: it becomes live once the bus has actually
// been up with a MATCHED SOURCE PAIR feeding it (bus switch closed AND that channel's boost
// enabled — S7, fw v5 review), and disarms whenever no such pair exists (a dark power stage, or
// boosts off with the switches still closed, are the normal non-faulty conditions in a State-98
// dark boot, staged bring-up P0, the 'F'/'B' bench sequence, State 3 and State 99 teardown). A
// bring-up ramp therefore cannot trip it either — the bus has not yet reached
// V_BUS_CHARGED_THRESH, so nothing is armed.
bool     uvBusArmed        = false;  // bus has been observed up with a source switch closed
bool     uvBusUnderActive  = false;  // an under-limit EXCURSION is open. fw v5: this is now only
                                     // excursion-boundary bookkeeping for the transient counter and
                                     // the 1 Hz print — the LATCH decision is uvBusDwellMs alone
uint32_t uvBusUnderSince   = 0;      // ms — current excursion start (print only)
float    uvBusDwellMs      = 0.0f;   // ms — leaky accumulated under-dwell (fw v5; UV_BUS_DWELL_*)
uint32_t uvBusLastTickMs   = 0;      // ms — previous armed evaluation, for the dwell dt
uint16_t uvBusTransientCount = 0;    // excursions that closed WITHOUT latching (dropout dips)
uint32_t uvBusPrintLastMs  = 0;      // ms — last "[UV] transient" print (1 Hz rate bound)
bool     uvBusHasPrinted   = false;  // distinguishes "never printed" from a print at millis()==0

// ── FAULT_UV_FC arming + dwell state (fw v6, 2026-08-12) ─────────────────────
// Mirrors the bus block above, with ONE structural difference in the ARMING term: the bus arms on
// the bus having been observed up (V_bus ≥ V_BUS_CHARGED_THRESH) with a matched source pair,
// whereas the FC rail arms on the FC pair being CLOSED (FC_REG_ENABLE HIGH && FC_BUS_ENABLE HIGH,
// the same S7 matched-pair discipline) AND V_fc having been observed at/above V_FC_ARM_THRESH
// while so routed. The "observed healthy while routed" term is what makes this safe on the
// single-source bench that has NO fuel cell at all: V_fc reads ~0 there, the rail is never seen
// healthy, nothing ever arms, and the fault can never boot-lock State 99 — which is precisely why
// the superseded check needed its mainState == 2 gate.
// Its dwell dt uses its own timestamp (fcUvLastTickMs) rather than sharing uvBusLastTickMs: the
// two filters happen to run in the same detectFaults() pass today, but coupling their dt would
// silently break either one if a future change moved or short-circuited the other's block.
bool     fcUvArmed       = false;  // V_fc has been observed healthy with the FC pair closed
bool     fcUvUnderActive = false;  // an under-limit excursion is open (counter/print bookkeeping)
uint32_t fcUvUnderSince  = 0;      // ms — current excursion start (print only)
float    fcUvDwellMs     = 0.0f;   // ms — leaky accumulated under-dwell (UV_FC_DWELL_LATCH_MS)
uint32_t fcUvLastTickMs  = 0;      // ms — previous evaluation, for the dwell dt
uint16_t fcUvTransientCount = 0;   // excursions that closed WITHOUT latching
uint32_t fcUvLastExcursionMs = 0;  // ms — duration of the most recent CLOSED excursion. The bus
                                   // filter exposes this through its 1 Hz print; this filter has
                                   // no print (one repeating "[UV] transient" line per rail would
                                   // be indistinguishable in a scrollback), so it is reported in
                                   // the 'S' status dump instead (fw v6 review S5)

// ── Error code enum ───────────────────────────────────────────────────────────
// Latching primary cause; set once by triggerFault() on first State-99 entry.
typedef enum : uint8_t {
    ERR_NONE            = 0x00,
    ERR_OC_FC           = 0x01,  // I_fc overcurrent
    ERR_UV_BATT         = 0x02,  // V_batt undervoltage
    ERR_OV_BUS          = 0x03,  // V_bus overvoltage
    ERR_SWITCH_CONFLICT = 0x04,  // Illegal switch combination
    ERR_PI_TIMEOUT      = 0x05,  // Pi watchdog expired
    ERR_OV_BATT         = 0x06,  // V_batt overvoltage
    ERR_UV_FC           = 0x07,  // V_fc undervoltage
    ERR_OC_BT           = 0x08,  // I_batt overcurrent (BT path)
    ERR_UV_BUS          = 0x09,  // V_bus undervoltage during Run
    ERR_OV_RGN          = 0x0A,  // V_rgn overvoltage
    ERR_OV_CHG          = 0x0B,  // V_chg charger input overvoltage
    ERR_I2C_CHARGER     = 0x0C,  // Ag105 I2C comms failure
    ERR_CHARGER_STAT    = 0x0D,  // Ag105 GENSTAT error
    ERR_INIT_FAIL       = 0x0E,  // Init sequence failure
    ERR_MOT_HOTPLUG     = 0x0F,  // MOT_PWR_ENABLE refused at full bus (motor node not pre-charged)
} ErrorCode_t;

// ── Ag105 MPPT charger I2C constants ─────────────────────────────────────────
// Source: Ag105_Table7_I2C_Parameters.json (Table 7, Ag105 DS V1.1)
#define AG105_ADDR           0x30   // default I2C address (field 0xE5 default = 0x30)

// Config registers (R/W; stored in EPROM — settings persist across power cycles)
#define AG105_REG_ICHG_CFG   0x00   // Charge Current Setting; default 0x00 = ext-resistor mode
#define AG105_VAL_2500MA     0x01   // value 1 = 2.5A profile; Source: Ag105_Table4_Charge_Current_Select.json
#define AG105_REG_VBATT_CFG  0x01   // Battery Voltage Setting; default 0x00 = ext-resistor mode (→ 4.2V/1S if no RVS)
#define AG105_VAL_2S         0x08   // value 8 = 8.4V / 2S / 100% capacity; Source: Ag105_Table3_Charge_Voltage_Select.json

// Measurement registers (read-only; Ag105 always prepends status byte before data)
#define AG105_REG_ICHG_MEAS  0x06   // Measured charge current; scale: 0.011 A/count

// Table 6 GENSTAT bit patterns (bits 0–2 of the status byte)
// Source: Ag105_Table6_I2C_Status_Byte.json
#define AG105_GENSTAT_CHARGING  0x02   // 010 — actively charging
#define AG105_GENSTAT_FULL      0x03   // 011 — fully charged

// Power-up settling: the Ag105 is unpowered until a charger power path is routed to it
// (FC_CHARGE_ENABLE, or REGEN_ENABLE+MOT_PWR_ENABLE). After input power first appears the
// module needs time to boot (Bring-Up state) before its I2C is trustworthy. Until this
// window elapses, an I2C NACK is treated as "still booting", not a fault.
#define AG105_SETTLE_MS 500u   // TODO(calibrate): Ag105 bring-up time before I2C is trusted

// ── Telemetry ─────────────────────────────────────────────────────────────────
// Protocol v4 packet is 58 bytes; Pi bridge must match this version.
#define TELEMETRY_VERSION 4

// switch_state bitmask packed at offset 52 of the v4 telemetry packet
#define SW_FC_BUS    0x01
#define SW_BT_BUS    0x02
#define SW_MOT_PWR   0x04
#define SW_REGEN     0x08
#define SW_FC_CHARGE 0x10
#define SW_BT_SEQ    0x20

// ── State machine ─────────────────────────────────────────────────────────────
int mainState = 0;

// doState99()'s teardown phase. FILE SCOPE (not function-static) so logDrainTick() can see it:
// the SD drain must not run card I/O between the teardown phases (review 2026-08-10 FW-R1-F1).
// State 99 is latched until a power cycle, so there is deliberately no reset path — the phase
// only ever advances 0 -> 1 -> 2 -> 3, exactly as the old function-local static did.
uint8_t state99Phase = 0;

// ── Physical constants ────────────────────────────────────────────────────────
const int MDAC_res = 4095;          // AD5443 12-bit — VERIFIED ad5426_5432_5443.pdf Table 1 + Fig 49

// AD5443 SPI word format — VERIFIED against ad5426_5432_5443.pdf (Rev. H), 2026-08-07:
// the 16-bit word is C3..C0 control + DB11..DB0 data (Fig 49). Table 10: control 0000 is
// "No operation (power-on default)" — a bare 12-bit code in a 16-bit transfer is a documented
// NOP, which is exactly what this firmware shipped with (found on the bench: O/R sweeps could
// not move the share; both DACs sat at their power-on zero scale, p.1: "the internal shift
// register and latches are filled with 0s and the DAC outputs are at zero scale"). Every MDAC
// write must carry the load-and-update nibble.
#define MDAC_CMD_LOAD_UPDATE   0x1000u  // C3..C0 = 0001 "Load and update" (Table 10)
#define MDAC_CMD_DAISY_DISABLE 0x9000u  // C3..C0 = 1001 "Daisy-chain disable" (Table 10):
                                        // datasheet Standalone Mode (p.21) — write once after
                                        // power-on; transfers then auto-load on the 16th SCLK
                                        // falling edge. Data bits don't care.
const int32_t sampleTime = 50;      // us

// ── Flywheel / encoder geometry (the ONLY inputs to the v_actual scale) ───────
// Removed here: `CPR = 16`, `tireRadius = 1` and `lastEncoderPos` — all three were dead (defined,
// never read) and `CPR` actively contradicted ENCODER_COUNTS_PER_REV below. Two conflicting,
// unsourced encoder-resolution constants in one file is exactly how a calibration gets guessed.
//
// The encoder is NOT a commercial part: the BOM fits 2 × OPB829DZ through-beam optical sensors
// ("Optical Sensor Through-Beam 0.125in (3.18mm) Phototransistor Module", BOM line 71) plus 2 ×
// 4.7k pull-ups (line 73), i.e. a home-built two-channel beam-interrupt encoder on a slotted disc.
// So counts/rev is a property of the DISC and must be counted by hand — there is no datasheet.
//
// Decode factor is x2 per quadrature cycle, NOT x4. Verified from the ISRs: doEncoderA() only ever
// decrements and doEncoderB() only ever increments, each gated on the other channel's "first" flag,
// so one full A/B cycle yields exactly +2 (forward) or -2 (reverse). Hence:
//     counts/rev = 2 x slots/rev
#define ENCODER_QUAD_DECODE  2.0f       // counts per quadrature cycle (x2 — see above)
// COUNTED DIRECTLY on the disc (operator, 2026-08-16): the disc physically carries 120 slots.
// At the x2 decode above that is ENCODER_COUNTS_PER_REV = 240 counts per flywheel revolution.
// A physical slot count is the strongest source available for this constant — the encoder is
// home-built, so there is no datasheet to check it against, and it needs no working decoder to
// obtain (see the provenance note below for why that distinction matters).
//
// PROVENANCE (fw v8, 2026-08-16) — this SUPERSEDES the fw v7 value of 60 slots, which was a
// transcription error, not a measurement disagreement. The 2026-08-13 bench figure of "120" was
// recorded as 120 encoderPos COUNTS per revolution and then divided by the x2 decode to yield
// 60 slots. It was in fact 120 SLOTS: no build up to and including fw v7 printed encoderPos
// anywhere — not in the State-98 'S' dump the record cites, not in printSensors(), not in
// telemetry — so the counter could not have been read, and the number can only have come from
// counting the disc. The x2 decode must therefore be applied to it, not removed from it, which
// is what this line now does. Net effect vs fw v7: ENCODER_COUNTS_PER_REV 120 -> 240, so
// v_actual HALVES for identical motion (see the scale-discontinuity note in
// docs/firmware-versions.md). fw v8 adds encoderPos + per-channel edge counters to both dumps so
// the hand-turn cross-check can finally be run against the decoder's own output.
// See docs/VESC_MOTOR_INTEGRATION.md §10.
#define ENCODER_SLOTS_PER_REV 120.0f    // → ENCODER_COUNTS_PER_REV = 240 (slots counted on the disc)
constexpr float ENCODER_COUNTS_PER_REV = ENCODER_SLOTS_PER_REV * ENCODER_QUAD_DECODE;

// Effective rolling radius, in METRES — the radius that converts the ENCODED body's angular rate
// into the m/s the velocity loop closes on. MEASURED 2026-08-13 (operator, bench): 0.0762 m
// (3.00 in). This measured value is authoritative.
//
// It SUPERSEDES both the previous 0.033 m and the reasoning that produced it. That reasoning ran:
// the encoder is downstream of the 9.49:1 reduction and both differentials
// (docs/VESC_MOTOR_INTEGRATION.md §7), so the disc turns at WHEEL angular speed and the right
// radius is therefore the tire rolling radius (66 mm nominal OD / 2, §2). Both halves of that are
// retired here — the wheel-angular-speed clause included, since it is what forced the tire radius.
//
// COUPLING ASSUMPTION the measured value implies: 0.0762 m is correct when the disc's rim runs at
// road/surface speed (a roller or surface-speed coupling), NOT when it merely turns at wheel
// ANGULAR speed. Those two readings differ by 0.0762/0.033 = 2.31x, so if the disc is later found
// to be angular-coupled to the wheel, this constant is over-reading v_actual by that factor and
// must be re-derived — the interlock below exists for exactly this class of discovery.
// TODO(verify): confirm the disc's mechanical coupling against docs/VESC_MOTOR_INTEGRATION.md §10.
#define FLYWHEEL_RADIUS_M    0.0762f    // m — measured flywheel radius (3.00 in)

// Combined rev/min → m/s factor: (2π/60) · r. Precomputed so the conversion appears exactly once
// and can be asserted directly in the unit tests. (Arduino's PI macro is not available in the host
// test build, hence the literal 2π.)
constexpr float TWO_PI_F      = 6.28318530718f;
constexpr float RPM_TO_MPS    = (TWO_PI_F / 60.0f) * FLYWHEEL_RADIUS_M;

// Guard: with either scale input above at a placeholder value, closing the velocity loop
// OVER-DRIVES. v_actual under-reads true speed, so the PI keeps adding current to reach a setpoint
// the vehicle has already blown past; the commandMotorCurrent() ceiling bounds AMPS, not SPEED.
// While 0, State 98 refuses the two velocity-mode entry points ('V' manual velocity, 'D' drive
// cycle). Production State 2 is deliberately NOT gated — it needs a Pi commanding it and is out of
// scope for a bench interlock. See docs/design-review-2026-07-28.md.
// BOTH scale inputs are measured, so the shipped default is 1: ENCODER_SLOTS_PER_REV = 120 from a
// direct slot count on the disc (2026-08-16, superseding the 60 back-derived from a mis-transcribed
// hand-turn figure), FLYWHEEL_RADIUS_M = 0.0762 m from the bench (2026-08-13).
// The interlock machinery is kept for anyone who overrides back to 0 — fit a new disc or a new
// flywheel and the chain is uncalibrated again until it is re-measured.
#ifndef VELOCITY_CHAIN_CALIBRATED
#define VELOCITY_CHAIN_CALIBRATED 1
#endif
// INA253 variant mixup: the BOM calls for INA253A1IPWR (100 mV/A = 0.1 V/A), but the A3
// variant (400 mV/A) was the intended choice for easier droop scaling. The board is already
// built with A1 parts, so K_sns = 0.1 V/A is used. Update to 0.4 if the board is re-spun
// with INA253A3IPWR. Source: INA253A1IPWR.pdf Device Comparison Table.
const float K_sns = 0.1f;           // V/A — INA253A1 gain (A3 = 0.4 V/A; see note above)
const float A_v   = 5.02f;          // OPA197 gain = 1 + 40.2k/10k (schematic ROP1/ROP2)
// Droop injection chain (controller_design/system_model.md §2/§4; schematic sheets 1–2):
// the MDAC output is attenuated into the boost FB node by RD1/RINJ, so the realized droop
// resistance per channel is Re(g) = K_sns·A_v·(RD1/RINJ)·g ≤ RE_MAX. The share mapping
// R_F = K_DROOP/r, R_B = K_DROOP/(1−r) gives a unity-gain plant (α = r nominal) and requires
// g = K_DROOP/(RE_MAX·r) ≤ 1 → K_DROOP ≤ RE_MAX·DROOP_R_MIN (hard bound 0.3329 Ω at 0.15).
const float RD1_OVER_RINJ = 215.0f / 53.6f;         // FB divider top / injection resistor
                                    // RD1 bodged 237k → 215k (16V bus retune, 2026-07-11;
                                    // schematic still shows 237k)
const float RE_MAX  = K_sns * A_v * RD1_OVER_RINJ;  // 2.014 Ω — max electronic droop
const float K_DROOP = 0.30f;        // ohm — design droop scale k_d; TODO(calibrate): bench
                                    // decision, see controller_design/system_model.md §9.
                                    // Hard bound RE_MAX·DROOP_R_MIN = 0.302 Ω
const float DROOP_R_MIN = 0.15f;    // usable droop-ratio span for g ≤ 1 at K_DROOP = 0.30
const float DROOP_R_MAX = 0.85f;

// A — share-loop hold threshold. Below this total measured current the share
// ratio |I_fc|/(|I_fc|+|I_batt|) is a quotient of two near-zero ADC readings,
// i.e. pure noise: stepping the share controller on it winds the integrator to
// the DROOP_R_MIN clamp during every standstill and forces a share transient on
// every launch (observed on bench, logs TP0004/TP0005 standstill epochs,
// 2026-08-10). powerBalance() holds the controller state AND the droop MDACs
// below this threshold. Value: bench decision 2026-08-10 (~9x the post-averaging
// per-channel noise sigma at idle, far below the ~0.5 A/channel minimum real
// operating current).
const float SHARE_I_TOT_MIN_A = 0.075f;

// ── Share-loop limit-cycle mitigation (2026-08-11) ───────────────────────────
// The 2026-08-11 setpoint sweep (logs TP0007–TP0013; docs/share_sweep_whitepaper)
// found a 17–18.5 Hz minority-channel dropout limit cycle at asymmetric IN-BAND
// setpoints (0.30, 0.85) whenever total current was low (< ~1.2 A): the droop
// command starves the minority channel out of conduction, measured share slams to
// 0/1, both MDACs rail antiphase, and the bus loses its source feed each cycle
// (scope capture 12: VBUS+V-MOT sag together to 6.5 V worst-case; whether the
// final disconnect is droop-commanded RT1987 blocking or a source-switch SCP cut
// is still open — both are downstream of the railing, so the mitigation is the
// same either way). Two constants parameterize the fix in powerBalance() /
// applyShareRatio():
//
// A — minimum COMMANDED minority-channel current. The setpoint governor clips the
// effective in-band share setpoint so the starved channel is never asked to carry
// less than this (sp_eff ∈ [I_min/I_tot, 1 − I_min/I_tot]). Below 2·I_min of
// filtered total the loop leaves CLOSED-LOOP control entirely (fw v5 open-loop
// feedforward/hold — see SHARE_GOV_OL_HYST_A below; the fw v2–v4 collapse-to-0.5
// fallback is deleted, it ignited the TP0053 relay cycle).
// The linear ΔV₀ model does NOT set this floor: CAL-1 measured
// ΔV₀ = +0.05 V (system_model.md §8/§9, calibration/dv0_sweep_20260811.csv),
// whose feasibility bound is far below the observed cycle — the floor is the
// EMPIRICAL light-load boost nonlinearity (same regime as CAL-1's I_tot = 0.145 A
// outlier).
//
// Value (RAISED 0.20 → 0.30 A, 2026-08-12): the fw v3 validation sweep
// TP0014–TP0038 / WP0039–WP0040 (docs/share_sweep_whitepaper §6) BRACKETED the
// conduction floor instead of bounding it from one side. TP0016 (setpoint 0.15,
// hold I_tot = 1.63 A → commanded minority 0.245 A) still collapsed the bus to
// 8.2 V, i.e. 0.245 A commanded minority CYCLES; TP0017 (setpoint 0.18, same
// hold) commands 0.29 A and is CLEAN. The floor therefore lies in
// (0.245, 0.29] A, and the shipped 0.20 A sat below the whole bracket — it
// governed nothing at the setpoints that failed. 0.30 A sits just above the
// clean bracket edge. The collapse-to-0.5 threshold follows automatically
// (2·I_min: 0.40 → 0.60 A of total current before closed-loop control engages).
// TODO(calibrate): refine via the quasi-static dropout-boundary mapping (bench
// plan step 3) — the bracket is 45 mA wide and was measured at ONE total
// current, so the floor's I_tot dependence is still unmeasured.
const float SHARE_MINORITY_I_MIN_A = 0.30f;

// A — LOAD CEILING on the SETPOINT-LATCHED CUTOFF ENTRY (fw v6, 2026-08-12). The cutoff opens one
// bus switch in a single tick, which hands the doomed channel's ENTIRE instantaneous current to
// the surviving channel as a step. That step is only free when it is small.
// EVIDENCE (fw v5 sweep, logs WP0095–WP0101): WP0097 and WP0101 latched the BT cut with the BT
// channel carrying 1.3–1.5 A (total ~2 A, W-profile region R6 at full Imax). The survivor (FC)
// then had to source the whole load alone, went past this bench's ~2.1 A FC source knee, and the
// bus collapsed in ~40 ms → ERR_UV_BUS. The SAME cut is validated CLEAN when it fires at ~0 A —
// every run-start latch in TP0074/TP0085/TP0086/TP0087 entered at standstill with no incident.
// So the failure discriminator is the handoff current, not the cutoff itself.
// 0.5 A is set between the two populations (validated 0 A; failed 1.3 A) with margin on both
// sides, and is well under the 2.1 A knee even after the survivor absorbs it.
// TODO(calibrate): the knee is bench-source-specific (this is a lab supply, not the vehicle's
// fuel cell), and the 0–1.3 A gap is unbracketed. Refine on the fw v6 re-sweep with the two-axis
// (Imax × setpoint) mapping.
const float SHARE_CUT_MAX_HANDOFF_A = 0.5f;

// A — hysteresis on the CLOSED→OPEN loop-mode exit (fw v5, 2026-08-12). 2·SHARE_MINORITY_I_MIN_A
// (0.60 A of filtered total) is the entry into closed-loop share control; the exit back to
// open-loop is SHARE_GOV_OL_HYST_A lower (0.55 A) so a total current dithering on the threshold
// cannot chatter the two modes (each transition reseeds the controller, which is not free).
// Value: ~8% of the threshold, well above the filtered ADC noise on |I_fc|+|I_batt| at that level.
// TODO(calibrate) against the fw v5 re-sweep.
const float SHARE_GOV_OL_HYST_A = 0.05f;

// per powerBalance() tick (1 kHz) — ceiling on the commanded droop-ratio slew in
// applyShareRatio(). Bounds the MDAC antiphase rail-to-rail slams that drive the
// dropout/reconnect transients (and, if the SCP branch is real, trip the cut):
// 0.02/tick walks the full [0.15, 0.85] band in 35 ms instead of one SPI write.
// Deliberately fast enough to be invisible to normal tracking (the Youla loop's
// closed-loop rise is slower than 35 ms full-band). TODO(calibrate): tighten
// against the FIX-VALIDATION re-entry run if chatter persists.
const float DROOP_RATIO_SLEW_PER_TICK = 0.02f;

// Governor load filter: EMA weight per 1 kHz tick on |I_fc|+|I_batt| (~20 ms).
// The governor bounds depend on measured current; unfiltered, ADC noise would
// dither sp_eff and feed measurement noise straight into the setpoint.
const float SHARE_GOV_FILT_ALPHA = 0.05f;

const float motorConstant = 0.1f;   // TODO: tune this
// A — HARD ceiling on the current actually handed to the VESC. Enforced at the single chokepoint
// commandMotorCurrent(), so EVERY path (UDP velocity, State-98 manual current/velocity, drive
// cycle, power-share profile) is bounded by it — not just the motor PI integrator. Before this
// chokepoint existed, motorControl() sent PI_out/motorConstant straight through: with
// motorConstant = 0.1 an uncalibrated 5 m/s velocity error commands 50 A from the P term alone,
// on a 50 A bridge.
//
// Retargeted 30.0 → 5.0 A for bench bring-up (2026-07-29), from the source power budget in
// docs/VESC_MOTOR_INTEGRATION.md §12:
//   - The platform ceilings at ~67 W (validated envelope) to ~87 W (source datasheet) at the bus,
//     i.e. 4.2–5.4 A of bus current. Motor current maps to bus current as I_bus = D·I_mot/η_esc, so
//     a 30 A motor command at high duty demands ~28 A of bus current — several times the entire
//     source budget, and well past both boosts' validated 3 A/channel envelope.
//   - 5.0 A: at KV 1750 that is ~27 mN·m → ~7.8 N at the wheels → ~2.0 m/s² on the ~3.2 kg
//     effective mass, and ≤ 4.7 A of bus current even at D = 0.9 — inside already-validated
//     territory at any duty.
//   - Vehicle value once calibrated: 15.0 A (covers 4 m/s² at every candidate KV, under the VESC
//     Six EDU's 50 A burst / 25 A continuous rating). TODO(calibrate).
// NOTE the bus is NOT protected by this ceiling at all — I_bus depends on duty. Bound it in the
// VESC itself (Battery Current Max ≈ 4.2 A, Regen ≈ 1.5 A); see §4 of the integration doc.
//
// RAISED 5.0 → 10.0 A (2026-08-13, operator decision). The derivation above is retained as the
// PREVIOUS bench value, not as the current one. Its 4.2–5.4 A source budget is a BUS-current
// budget, but this constant clamps what setCurrent() sends the VESC — three-PHASE motor current,
// which maps to bus current only through the duty ratio (I_bus ≈ D·I_mot/η_esc). So the source
// power budget does not bind this constant, and bounding the bus is not this constant's job.
// 10.0 A is a VESC-side phase-current ceiling. The 15.0 A vehicle TODO(calibrate) stands.
// RAISED 10.0 → 12.0 A (2026-08-15, operator decision, with the Castle 1406 1900KV motor fitted
// and the Youla-H drive-controller bring-up starting). Same phase-current rationale; may rise
// again after the drive controller validates.
//
// ⚠ PRECONDITION, NOT A STATEMENT OF FACT (review 2026-08-13, S1). The argument above only holds
// if the bus is bounded SOMEWHERE ELSE, and as of this writing it is not: integration-doc §4
// records Battery Current Max and Battery Current Regen Max as "not set / not tracked". So before
// any velocity-path run at this ceiling, configure them in VESC Tool (Battery Current Max
// ≈ 4.2 A, Regen ≈ 1.5 A) and tick §4. Until that is done there is NO bus-current bound anywhere
// in the system — not here (phase current, duty-dependent), not in the VESC (unset), and not in
// this firmware on a BENCH_TEST flash, where detectFaults() is relaxed to overvoltage-only and the
// OC checks are compiled out.
const float MOTOR_I_CMD_MAX = 12.0f;
const float MANUAL_MOTOR_V_MAX = 5.0f; // m/s — State 98 manual velocity ceiling; TODO(calibrate)
// m/s — sanity bound on the Pi's v_setpoint. Not a performance limit: it exists so a corrupt or
// mis-scaled UDP field cannot drive an enormous velocity error into the motor PI. A 1/10-scale car
// tops out well under this. TODO(calibrate) once the velocity unit chain is fixed.
const float V_SETPOINT_MAX = 20.0f;

// ── Control-loop rate limiting ────────────────────────────────────────────────
// The three Run-state control functions used to be called once per main-loop tick, uncapped. Two
// reasons that is wrong:
//
//  1. motorControl() ends in a VescUart setCurrent() frame: 9 bytes at 115200 8N1 = 781 µs of wire
//     time. Teensy 4.x HardwareSerial::write() BLOCKS once the TX FIFO fills, so any main loop
//     faster than ~781 µs stalls inside Serial1.write() — silently pinning the whole loop (including
//     detectFaults()) to ~1.28 kHz and queuing up to ~7 already-superseded current commands
//     (~5.5 ms of command latency) in the FIFO.
//  2. chargingControl() and powerBalance() have no reason to run at the motor rate. The Ag105 is
//     explicitly the SLOW secondary harvester (CLAUDE.md §3) and the droop MDAC write is an SPI
//     transaction; running them flat-out just burns loop time that detectFaults() wants.
//
// Each function therefore gets its OWN independent period, so the rates can be tuned separately.
// The gate is on the CALL, not inside the functions: the PI integrators already gate their own
// state updates on sampleTime and always return a live output, so a skipped call simply holds the
// last commanded value — which is the correct zero-order-hold behaviour for all three.
//
// TODO(calibrate): these are first-cut values chosen to sit clear of the UART floor and to leave
// detectFaults() headroom, NOT measured. Profile the real loop period on hardware (no loop-period
// instrumentation exists yet) and revisit. Raising MOTOR_CTRL_PERIOD_US below ~800 µs re-introduces
// the UART backpressure described above.
#define MOTOR_CTRL_PERIOD_US    2000u   // 500 Hz — well clear of the ~781 µs UART frame floor
#define CHARGING_CTRL_PERIOD_US 20000u  //  50 Hz — matches the Ag105 I2C poll cadence
#define POWER_BAL_PERIOD_US     1000u   //  1 kHz — the rate youlaController_Power() is designed for

// Returns true (and advances `last`) when `period` has elapsed. Unsigned wrap-safe.
static inline bool rateLimitDue(uint32_t &last, uint32_t period) {
    uint32_t now = micros();
    if ((uint32_t)(now - last) < period) return false;
    last = now;
    return true;
}

// Separate timestamp per controller so the three cadences are genuinely independent.
uint32_t rl_motor_last    = 0;
uint32_t rl_charging_last = 0;
uint32_t rl_power_last    = 0;
// SD bench logger sample gate. Lives here (not with the logger module further down) because
// resetControlRateLimiters() below back-dates it, and that function is defined before the module.
// Deliberately shares POWER_BAL_PERIOD_US: the log exists to resolve the 1 kHz share loop, so a
// sample per power-balance tick is exactly the resolution the record format is for.
uint32_t rl_log_last      = 0;

// Reset all three gates so the next tick runs every controller immediately. Called on entry to a
// state or profile that starts driving, so the first control action isn't delayed by up to a full
// period left over from a previous run.
void resetControlRateLimiters() {
    uint32_t now = micros();
    rl_motor_last    = now - MOTOR_CTRL_PERIOD_US;
    rl_charging_last = now - CHARGING_CTRL_PERIOD_US;
    rl_power_last    = now - POWER_BAL_PERIOD_US;
    // Back-date the logger gate too, so a profile's FIRST control tick is also its first logged
    // sample — otherwise the run's opening transient (the most interesting part of a step test)
    // could fall in a leftover window of up to one full period.
    rl_log_last      = now - POWER_BAL_PERIOD_US;
}

// (The rate-gated wrappers motorControlGated()/chargingControlGated()/powerBalanceGated() are
// defined next to motorControl(), where the controllers themselves are in scope.)

// ── PI controller integrator state ────────────────────────────────────────────
// Hoisted to file scope (control math and sampleTime gating unchanged) so the host-native
// unit tests can deterministically reset integrator + timebase between cases. Without this
// the function-local statics leaked across tests and made results execution-order dependent.
float    pi_motor_accum      = 0;
uint32_t pi_motor_lastMicros = 0;
float    pi_power_accum      = 0;
uint32_t pi_power_lastMicros = 0;

// ── Sensor readings ───────────────────────────────────────────────────────────
float v_actual          = 0;
float current           = 0;
float targetMotorTorque = 0;
float P_fc_actual       = 0;
float P_batt_actual     = 0;

float I_fc              = 0;
float I_batt            = 0;
float I_charge          = 0;   // sourced from Ag105 I2C reg 0x06 via pollAg105() at 50 Hz
float V_fc              = 0;
float V_batt            = 0;
float V_bus             = 16.0f;   // init at nominal so a pre-ADC detectFaults() tick can't trip OV
float V_chg             = 0;   // charger input voltage (pin 38, ADC)
float V_rgn             = 0;   // regen-node voltage    (pin 39, ADC)

float power_share_actual    = 0;
float droop_gain_FC_actual  = 0;
float droop_gain_BT_actual  = 0;

uint8_t  ag105_status_raw  = 0;        // last raw Table 6 status byte; cached at 50 Hz by pollAg105()
bool     ag105DataValid    = false;    // true while ag105_status_raw/I_charge reflect a successful
                                       // read this power session. Needed because GENSTAT 0x00 is a
                                       // REAL status (Battery Disconnect, Table 6) — a raw value of
                                       // 0 cannot double as the "stale/no data" marker.
// Ag105 charger power/config tracking (see chargerHasPower() and pollAg105()).
bool     ag105Configured   = false;    // true once 0x00/0x01 written this powered session
bool     ag105HadPower     = false;    // power on/off edge detector for the settle timer
uint32_t ag105PowerOnMs    = 0;        // millis() when input power was first observed (settle base)
uint16_t fault_flags       = 0;        // bitmask of active fault conditions (see FAULT_* defines)
uint8_t  error_code        = ERR_NONE; // primary cause of State-99 entry — latches on first fault
uint8_t  error_source_state = 0;       // mainState at time of first fault (for diagnosis)

// ── Commands received from Pi ─────────────────────────────────────────────────
float   v_setpoint           = 0;
float   power_share_setpoint = 0.5f;
float   charge_goal          = 0;
uint8_t mode_cmd             = 4;   // default SAFE

// ── State transition flags ────────────────────────────────────────────────────
bool changeToRun = false;
bool changeToFin = false;

// ── Encoder ───────────────────────────────────────────────────────────────────
volatile byte AfirstUp   = 0;
volatile byte BfirstUp   = 0;
volatile byte AfirstDown = 0;
volatile byte BfirstDown = 0;
volatile int  encoderPos     = 0;
volatile byte pinA_read      = 0;
volatile byte pinB_read      = 0;
// Raw per-channel interrupt-edge counters (fw v8, diagnostic only — nothing reads these but the
// 'S' dump). They exist because `v_actual == 0.000` had exactly one observable and no way to
// localise it: the quadrature decoder below only counts when BOTH channels transition in the
// right ORDER, so a dead channel, a channel whose swing never crosses the Teensy's logic
// thresholds, and two beams that are not 90 degrees apart all produce an identical, silent
// encoderPos == 0. Counting each channel's CHANGE interrupts separately separates those cases
// before anyone touches the velocity math. NOT used by any control path.
volatile uint32_t encEdgeCountA = 0;
volatile uint32_t encEdgeCountB = 0;
// ENCODER_COUNTS_PER_REV now lives with the rest of the flywheel/encoder geometry in the physical
// constants block, derived from ENCODER_SLOTS_PER_REV x ENCODER_QUAD_DECODE.
// Set by State 3 (Finish) to clear updateWheelSpeed()'s averaging buffers between runs, so a
// new run's first velocity samples are not computed against stale timestamps from the prior run.
bool wheelSpeedResetPending = false;

// ── Bench/debug config ──────────────────────────────────────────────────────────
// BENCH_TEST relaxes the firmware so the board can reach Idle on the bench without
// the power rails connected:
//   - detectFaults() runs ONLY the overvoltage checks (OV_BUS/OV_BATT/OV_RGN/OV_CHG);
//     all overcurrent, undervoltage, switch-conflict and charger-STAT checks are skipped.
// OV checks are kept because they are the genuine destroy-the-hardware faults and a
// floating ADC reads LOW, not high, so they won't false-trip with rails unpowered.
// (Charger init no longer needs BENCH_TEST: an unpowered Ag105 is handled by the power
// gating in pollAg105(), so it never blocks boot in either build.)
// Set to 0 for normal operation.
// Overridable via -DBENCH_TEST=0 so the host test suite compiles the production fault
// behavior (the test/Makefile passes -DBENCH_TEST=0). Note: charger config/faults are no
// longer gated by BENCH_TEST — they are power-gated in pollAg105(), so they stay correct
// in either build.
// ── Firmware version ─────────────────────────────────────────────────────────
// Monotonic u16, bumped on EVERY flash-worthy behavioral change (control law,
// pin/sequencing, scaling, logging format — not comments/docs). The ledger
// mapping each number to its changes lives in docs/firmware-versions.md; add a
// row there in the same commit as the bump. Stamped into every .BLG bench-log
// header (format v2 and later, offset 18) so logged data is attributable to the
// firmware that produced it, printed at boot and in the State-98 'S' status.
// 0 is reserved for "pre-versioning" (logs PS0001–TP0005 and earlier).
#define FW_VERSION 8

#ifndef BENCH_TEST
#define BENCH_TEST 1
#endif

// ── Network config ────────────────────────────────────────────────────────────
// Set to 0 for bench testing without Ethernet/Pi (USB-serial only); 1 for normal
// operation. When 0, setup() skips Ethernet/UDP init and the UDP functions no-op.
// Calling Udp.* without Udp.begin() hard-faults the Teensy into a reboot loop, so
// the networkUp guard below must gate every UDP access.
// Overridable via -DUSE_ETHERNET=1 (same pattern as BENCH_TEST).
#ifndef USE_ETHERNET
#define USE_ETHERNET 0
#endif

// ── Power-share controller selection ─────────────────────────────────────────
// 1 (default): the Youla-H robust controller (share_controller.h; coefficients
// generated by controller_design/synthesize_controller.py — see
// controller_design/controller_synthesis.md for the design record).
// 0: the legacy PI (PI_Controller_Power) — kept as a bench fallback / A-B
// comparison path; both are compiled either way.
#ifndef USE_YOULA_SHARE_CONTROLLER
#define USE_YOULA_SHARE_CONTROLLER 1
#endif

// BENCH_TEST and USE_ETHERNET are independent flags, so it is possible to build "production
// faults, no Pi link" by mistake: with USE_ETHERNET=0 the Pi never connects, pi_ever_connected
// stays false, and the Pi watchdog is permanently inert. Warn so a vehicle flash can't ship
// that combination silently. (The host test suite passes -DNO_ETH_WARNING: it deliberately
// tests production fault behavior with mocked-out networking.)
#if !BENCH_TEST && !USE_ETHERNET && !defined(NO_ETH_WARNING)
#warning "Production build (BENCH_TEST=0) with USE_ETHERNET=0: no Pi link, Pi watchdog inert. Set USE_ETHERNET=1 for vehicle flashes."
#endif

bool networkUp = false;   // true only after Udp.begin() succeeds in setup()

IPAddress pi_ip(192, 168, 1, 100);
const int      pi_port    = 5000;
const int      local_port = 5001;
const uint8_t  SYNC_BYTE_TX = 0xAA;
const uint8_t  SYNC_BYTE_RX = 0xBB;
uint16_t       pkt_counter_T = 0;

// ── Safety watchdog ───────────────────────────────────────────────────────────
uint32_t last_rx_ms        = 0;
bool     pi_ever_connected = false;
const uint32_t PI_TIMEOUT_MS = 500;

// ── State 98 drive cycle ──────────────────────────────────────────────────────
struct DriveCyclePhase {
    uint32_t durationMs;
    float    v_start;
    float    v_end;
};

static const DriveCyclePhase DRIVE_CYCLE[] = {
    { 2000,  0.0f,  0.0f },   // 0: Standstill — verify sensors, confirm no faults
    { 4000,  0.0f,  3.0f },   // 1: Ramp-up
    { 6000,  3.0f,  3.0f },   // 2: Cruise
    { 3000,  3.0f,  0.0f },   // 3: Coast-down
    { 3000, -0.5f, -0.5f },   // 4: Regen hold
    { 2000,  0.0f,  0.0f },   // 5: Standstill — confirm I_charge > 0 if charger enabled
};
static const int DRIVE_CYCLE_PHASES = 6;

bool     driveCycleActive     = false;
uint8_t  driveCyclePhaseIdx   = 0;
uint32_t driveCyclePhaseStart = 0;
uint32_t driveCycleStatusLast = 0;

// ── State 98 bench tools: manual motor drive ──────────────────────────────────
// Hold the motor at a constant command so the power-share controller can be characterized
// independent of wheel speed. Two modes: a fixed VESC current (bypasses the velocity PI) or a
// fixed velocity setpoint driven through the existing motorControl() PI.
enum MotorTestMode { MOTOR_TEST_OFF, MOTOR_TEST_CURRENT, MOTOR_TEST_VELOCITY };
MotorTestMode manualMotorMode     = MOTOR_TEST_OFF;
float         manualMotorCurrent  = 0.0f;   // A   — used in MOTOR_TEST_CURRENT
float         manualMotorVelocity = 0.0f;   // m/s — used in MOTOR_TEST_VELOCITY (feeds v_setpoint)

// When true, doState98() runs the closed-loop powerBalance() every test tick so a manually-set
// power_share_setpoint continuously drives the droop MDAC. Cleared by an open-loop droop write.
bool powerBalanceLive = false;

// Share-controller channel-cutoff state (see applyShareRatio()): true while the
// share controller has taken that channel's bus switch off the bus because the
// commanded ratio left the physical droop band. Controller-initiated only —
// manual '1'/'2' toggles and safeAllSwitches() clear these.
bool  shareIsoFC = false;
bool  shareIsoBT = false;
const float SHARE_CUTOFF_HYST = 0.01f;  // re-entry hysteresis on the commanded ratio

// Setpoint-latched channel cutoff (2026-08-12, fw v4 "one owner per setpoint" —
// see the block comment at updateShareSetpointCutoff()). True while THAT channel
// is cut off because the COMMANDED SETPOINT is outside [DROOP_R_MIN, DROOP_R_MAX],
// as opposed to shareIsoFC/BT, which record the topology action itself (whoever
// commanded it). Invariants:
//   - shareSpCutX ⇒ shareIsoX was set by the same entry (the setpoint latch is a
//     strict subset of controller-initiated isolation), unless an operator has
//     since taken ownership — the State-98 '1'/'2' handlers clear BOTH.
//   - never both at once: one setpoint starves at most one channel.
//   - while set, powerBalance() freezes the share controller entirely and
//     applyShareRatio()'s ratio-hysteresis re-entry for that channel is disabled.
bool  shareSpCutFC = false;
bool  shareSpCutBT = false;

// Setpoint-latch DEFERRAL state (fw v6 review S1, 2026-08-12). True while this tick's setpoint
// latch entry for that channel was blocked SOLELY by the load-aware handoff guard
// (SHARE_CUT_MAX_HANDOFF_A) — i.e. the setpoint IS out of band and the cut IS wanted, but the
// doomed channel is carrying too much current to hand over in one tick.
//
// WHY IT EXISTS: without it the deferral leaks the very cut it refused. The blocked entry returns
// false, the loop runs closed-loop at an OUT-OF-BAND setpoint, the controller drives r out of
// band, and applyShareRatio()'s r-based cutoff — which has NO current guard — performs the same
// 1.3-1.5 A handoff ~10-30 ms later, claimed as shareIso* instead of shareSpCut*. That claim is
// invisible to the external re-closers (doState2()/chargingControl() gate on !shareSpCut*), so
// they re-close the switch, the self-heal drops the orphaned claim, and the r-cutoff re-fires:
// TP0053-class switch cycling, in production State 2. "One owner per setpoint" — an out-of-band
// setpoint belongs to the latch, and the r-cutoff must not preempt it with an unguarded cut.
//
// LIFECYCLE: PER-TICK DERIVED, not latched. Both are cleared at the top of
// updateShareSetpointCutoff() and re-derived from that tick's guards, so there is no staleness or
// clear-site bookkeeping to get wrong. The LAST-SOURCE guard blocking an entry does NOT set them:
// that fall-through predates fw v6 and keeps its existing semantics (an already-single-sourced
// bus has no handoff to defer). resetShareControlState() clears them as well, for the case where
// the share loop stops running entirely (powerBalanceLive false) and the only remaining caller of
// applyShareRatio() is a one-shot operator write.
//
// SCOPE — CLOSED-LOOP MODE ONLY (verified): the OPEN-LOOP feedforward path already returns quietly
// for an out-of-band setpoint (fw v5 F1, "one owner per setpoint"), and the HOLD branch writes
// nothing at all, so in open loop neither the reference clip nor the r-cutoff suppression has
// anything to act on. A deferral raised while open loop is simply inert until the load that caused
// it puts the loop back into closed-loop mode — which is the only mode that can drive r out of
// band in the first place.
bool  shareCutDeferredFC = false;
bool  shareCutDeferredBT = false;

// ── State 98 bench tools: VESC read-back ('E' one-shot / 'U' watch) ────────────────────────────
// The firmware is otherwise write-only to the VESC (setCurrent()); these are the only reads.
// getFWversion()/getVescValues() BLOCK up to the VescUart _TIMEOUT (100 ms) waiting on Serial1,
// so they stretch the main-loop tick (delaying detectFaults()). That is acceptable ONLY in State
// 98 (interactive bench) — never call these from Run/Idle. 'U' polls at ~2 Hz and flags any
// (the watch key was 'W' until 2026-08-10, when 'W' became the combined current profile)
// change in the VESC's live fault code, to catch a transient fault the moment a command trips it.
// The poll is auto-suppressed while a drive cycle / power-share profile is active so those runs
// keep production-identical control-loop timing (pollVescWatch()); it resumes when the run stops.
bool     vescWatchActive = false;
uint32_t lastVescWatchMs = 0;
uint8_t  lastVescFault   = 0;
const uint32_t VESC_WATCH_PERIOD_MS = 500;   // ~2 Hz

// ── State 98 bench tools: power-share profile emulator (mirrors DriveCyclePhase) ──────────────
// Sweeps power_share_setpoint through a phase table while the motor is held at a constant command,
// so the share-controller step response can be measured. Linear interpolation per phase, exactly
// like the drive cycle (share_start == share_end is a hold; differing is a ramp).
struct PowerShareProfilePhase {
    uint32_t durationMs;
    float    share_start;
    float    share_end;
};

static const PowerShareProfilePhase POWER_SHARE_PROFILE[] = {
    { 3000, 0.5f, 0.5f },   // 0: settle at 50/50
    { 1000, 0.5f, 0.8f },   // 1: step toward FC-heavy
    { 4000, 0.8f, 0.8f },   // 2: hold
    { 1000, 0.8f, 0.2f },   // 3: step toward BT-heavy
    { 4000, 0.2f, 0.2f },   // 4: hold
    { 2000, 0.2f, 0.5f },   // 5: return to balanced
};
static const int POWER_SHARE_PROFILE_PHASES = 6;   // TODO(calibrate): tune steps/durations on bench

bool     powerShareProfileActive     = false;
uint8_t  powerShareProfilePhaseIdx   = 0;
uint32_t powerShareProfilePhaseStart = 0;
uint32_t powerShareProfileStatusLast = 0;

// ── State 98 bench tools: trapezoidal motor-current profile ('T') ─────────────────────────────
// Operator-parameterised current ramp: 0 → I_max at a fixed A/s, hold at I_max, then I_max → 0 at
// the same rate. Drives the VESC through commandMotorCurrent() DIRECTLY — the velocity PI is never
// in the loop, exactly like the 'A' manual-current mode. That is the point of this tool: it lets
// the motor and the source power draw (the droop share loop runs alongside) be exercised with NO
// dependence on the velocity chain (ENCODER_SLOTS_PER_REV, FLYWHEEL_RADIUS_M) at all, so it
// deliberately does NOT go through velocityChainCalibrated() the way 'D'/'V' must — that stays true
// now the chain IS calibrated (fw v7), because the tool must keep working if the disc changes.
enum TrapPhase { TRAP_RAMP_UP, TRAP_HOLD, TRAP_RAMP_DOWN };

bool      trapProfileActive = false;
TrapPhase trapPhase         = TRAP_RAMP_UP;
float     trapImax          = 0.0f;   // A   — peak command (signed; negative = braking/regen test)
uint32_t  trapHoldMs        = 0;      // ms  — dwell at the peak
float     trapRateAps       = 0.0f;   // A/s — ramp rate, same up and down (symmetric by spec)
uint32_t  trapRampMs        = 0;      // ms  — derived: |I_max| / rate, floored at 1 ms (see start)
uint32_t  trapStartMs       = 0;      // millis() at t=0 of the ramp-up
uint32_t  trapStatusLast    = 0;
float     trapCmdA          = 0.0f;   // last commanded current (status print / test visibility)

// Trapezoid current ceiling. Deliberately NOT MOTOR_I_CMD_MAX: that figure (10 A since 2026-08-13,
// 5 A before) bounds the velocity-PI paths, but setCurrent() commands the VESC's three-PHASE
// motor current, which does not map 1:1 onto bus draw (I_bus ≈ D·I_mot/η) — and on the bench the VESC may be fed
// from a separate supply entirely. The only hard bound that always applies is the ESC hardware
// itself: VESC Six EDU 25 A continuous (50 A burst). Bound the profile there, not at the budget.
const float TRAP_I_ABS_MAX = 25.0f;   // A — VESC Six EDU continuous rating

// ── State 98 bench tools: trapezoid SHARE-SETPOINT SWEEP ('T … [t,r1..rn]') ───────────────────
// Why this exists: the 2026-08-11 share-setpoint sweep (TP0007–TP0013, whitepaper
// docs/share_sweep_whitepaper) was run BY HAND — seven 'T' lines, each preceded by a 'P' setpoint
// entry, with the operator eyeballing the SD status between runs and guessing a cool-off dwell.
// That is exactly the procedure a bench tool should own: the setpoint/run pairing is the
// experiment's independent variable, and a mistyped 'P' silently mislabels a whole dataset.
//
// The sweep runs ONE trapezoid per ratio, each with its OWN TPnnnn.BLG (logNextFileName() already
// auto-allocates the index), separated by an operator dwell for motor/ESC cool-off. Deliberately
// NOT one long log with the setpoint stepping inside it: the per-run file boundary is what makes
// each ratio independently decodable and comparable to the hand-run TP0007–TP0013 set.
//
// 16 ratios is the ceiling: the hand sweep used 7, the parameter line is bounded by inputBuf, and
// 16 runs x (run + dwell) is already a multi-minute unattended sequence on a bench where the
// operator is expected to be watching. Also bounds the fixed-size ratio array below.
const uint8_t TSWEEP_MAX_RATIOS = 16;
const float   TSWEEP_DWELL_MAX_S = 3600.0f;   // 1 h — a typo like "300" is plausible, "36000" is not

// Sweep state. tsweepIdx is the run CURRENTLY running (or the one just finished), 0-based, so the
// operator-facing prints are (tsweepIdx+1)/tsweepCount. The per-run trapezoid parameters are
// stashed here because startTrapProfile() takes them by value and the line that supplied them is
// long gone by the time run 2 fires.
bool     tsweepActive          = false;
uint8_t  tsweepPhase           = 0;   // 0 = RUNNING (trapezoid live), 1 = WAIT_LOG, 2 = COOLDOWN
uint8_t  tsweepCount           = 0;
uint8_t  tsweepIdx             = 0;
float    tsweepRatios[TSWEEP_MAX_RATIOS] = {0};
uint32_t tsweepDwellMs         = 0;
float    tsweepImax            = 0.0f;
uint32_t tsweepHoldMs          = 0;
float    tsweepRate            = 0.0f;
uint32_t tsweepCooldownStartMs = 0;

// ── State 98 bench tools: combined drive-cycle + power-share profile ('Y') ────────────────────
// The 'D' drive cycle sweeps velocity with the share setpoint static; the 'R' profile sweeps the
// share with the motor held constant. Neither exercises the CROSS-COUPLING: on the vehicle the
// velocity loop's changing bus draw and the share loop's changing droop split move at the same
// time, and the plant the Youla-H controller was synthesised against (controller_design/) assumes
// that interaction is benign. This profile drives BOTH setpoints from one 16-region table so the
// coupling shows up in a single 1 kHz log.
//
// Table design (FROZEN — the region boundaries are what the identification/validation reads):
//   - Each axis gets SOLO excursions (steps and ramps with the other axis held) so a per-axis
//     step response can still be fitted from the same run, and TWO deliberately SIMULTANEOUS
//     regions (R4 ramp+ramp, R8 step+step) which are the actual interaction test.
//   - Buffer/hold regions separate the excitations so each transient settles before the next.
//   - R6 and R11 are brief excursions to the share bounds (1.0 and 0.0), i.e. "all FC" / "all BT",
//     to check the CHANNEL-CUTOFF behaviour at the extremes. Since the 2026-08-10 full-span
//     actuation change these are no longer a droop CLAMP: applyShareRatio() takes the starved
//     channel OFF THE BUS there (an RT1987 opening under load — the TP0010 stressor class), and
//     while a channel is isolated the share loop is OPEN (no MDAC writes). R6/R11 datapoints are
//     therefore TOPOLOGY EVENTS, not droop-response data — do not fit a plant through them.
//   - R6 IS DE-RATED IN LOAD (fw v6, 2026-08-12) — rows 5/6/7 only; every other row is unchanged.
//     ALL FIVE failures of the fw v5 sweep (WP0095–WP0101) were R6-ENTRY events: R6 was the one
//     region combining PEAK motor load (v = 1.0) with an EXTREME share (s = 1.0), so the setpoint
//     latch cut BT under ~2 A and left FC solo above its ~2.1 A source knee — bus collapse in
//     ~40 ms, ERR_UV_BUS. The excursion is scientifically necessary and is KEPT; what is removed
//     is the coincidence of the two extremes. R5 now ramps v down to 0.3 before the excursion,
//     R6 runs the same s = 1.0 step at 0.3·Imax, and R7 takes the s step-down at that low load
//     and then ramps v back to 1.0 so R8 still enters from v = 1.0 and keeps its 1.0 → 0.5
//     down-step character. Durations and the 40 s total are untouched.
//     TWO CONTINGENCIES on what R6 actually exercises (fw v6 review S7) — both operator-set, so
//     read them off the run's committed parameters (now stamped in the BLG v4 header):
//       (a) the s = 1.00 waypoint is clipped to [b, 1−b] AFTER interpolation, so the SETPOINT
//           LATCH path is only reached when b < DROOP_R_MIN (0.15). At the b = 0.20/0.22 bounds
//           used in the fw v5 W runs the region commands 0.80/0.78 — IN band, owned by the
//           governor, and no latch ever fires. The load de-rating still applies (it halves the
//           excursion current either way), but a latch-path test needs b < 0.15.
//       (b) "the cut actually fires" holds only while 0.3·Imax leaves the doomed channel under
//           SHARE_CUT_MAX_HANDOFF_A (0.5 A). That is Imax-CONDITIONAL: it is true at the ~2 A
//           Imax of the fw v5 runs (0.3·Imax ≈ 0.6 A total, doomed channel well under 0.5 A) and
//           becomes false as Imax grows, at which point the handoff guard defers the cut and the
//           region tests the deferral path instead. Both are informative; know which one ran.
//
// Units are deliberately NOT the same on the two axes:
//   - v_start/v_end are NORMALISED [0..1] and multiplied by the operator's yProfileVmax at
//     runtime, so one table serves any bench speed (the vehicle Vmax is still uncalibrated).
//   - s_start/s_end are ABSOLUTE share values, then clipped to [b, 1-b] AFTER interpolation.
//     Post-interpolation is the point: a ramp that crosses the bound runs at its normal slope and
//     then FLATTENS at the bound. Pre-scaling the waypoints would instead shrink the slope, which
//     changes the excitation the identification sees. The kink is intended.
struct CombinedProfileRegion {
    uint32_t durationMs;
    float    v_start;   // normalised [0..1]; x yProfileVmax at runtime
    float    v_end;
    float    s_start;   // absolute FC share; clipped to [b, 1-b] at runtime
    float    s_end;
};

// Steps happen at region ENTRY (a region whose start value differs from the previous region's end
// value IS the step); ramps interpolate across the region; holds have start == end.
static const CombinedProfileRegion COMBINED_PROFILE[] = {
    { 2000, 0.0f, 0.0f, 0.50f, 0.50f },   //  0: settle
    { 4000, 0.0f, 0.6f, 0.50f, 0.50f },   //  1: v ramp up (solo)
    { 2000, 0.6f, 0.6f, 0.50f, 0.50f },   //  2: buffer
    { 3000, 0.6f, 0.6f, 0.65f, 0.65f },   //  3: s step up (solo, intermediate)
    { 4000, 0.6f, 1.0f, 0.65f, 0.35f },   //  4: BOTH ramp (v up, s down) — interaction test
    { 2000, 1.0f, 0.3f, 0.35f, 0.35f },   //  5: buffer + v ramp DOWN to the excursion load (fw v6)
    { 1500, 0.3f, 0.3f, 1.00f, 1.00f },   //  6: s step to the hi bound (brief) — at 0.3·Imax (fw v6)
    { 3500, 0.3f, 1.0f, 0.35f, 0.35f },   //  7: s step down at LOW load, then v ramps back to 1.0
    { 3000, 0.5f, 0.5f, 0.65f, 0.65f },   //  8: BOTH step (v down, s up) — interaction test
    { 2000, 0.5f, 0.5f, 0.65f, 0.65f },   //  9: buffer
    { 3000, 0.5f, 0.5f, 0.65f, 0.00f },   // 10: s ramp down to the lo bound (solo)
    { 1500, 0.5f, 0.5f, 0.00f, 0.00f },   // 11: lo-bound check (brief)
    { 1500, 0.5f, 0.5f, 0.50f, 0.50f },   // 12: s step up, recovery to mid
    { 2000, 0.2f, 0.2f, 0.50f, 0.50f },   // 13: v step down (solo)
    { 3000, 0.2f, 0.0f, 0.50f, 0.50f },   // 14: v coast-down ramp
    { 2000, 0.0f, 0.0f, 0.50f, 0.50f },   // 15: end hold -> natural completion
};
// Derived, never hand-maintained: a table edit that forgot to update a separate count constant
// would either truncate the run or walk off the end of the array.
static const int COMBINED_PROFILE_REGIONS =
    (int)(sizeof(COMBINED_PROFILE) / sizeof(COMBINED_PROFILE[0]));

// Outcome of one shared region tick (advanceComboRegion()). Both combined profiles ('Y' velocity,
// 'W' current) run the same region machine over the same table and differ only in what they do
// with the interpolated motor axis, so the walk itself lives in ONE function and this tells the
// caller which of the three cases it is.
enum ComboTickResult {
    COMBO_TICK_DONE,       // the table is exhausted — the caller runs its completion path
    COMBO_TICK_BOUNDARY,   // a region boundary was crossed this tick; no setpoints produced
    COMBO_TICK_RUN         // setpoints produced (motor axis normalised, share already clipped)
};

bool     combinedProfileActive = false;
uint8_t  combinedRegionIdx     = 0;
uint32_t combinedRegionStart   = 0;
uint32_t combinedStatusLast    = 0;
// Operator parameters, committed by startCombinedProfile() and validated in
// parseCombinedParamsLine(). Defaults are what a bare "Y<newline>" runs.
float    yProfileVmax    = 1.0f;   // m/s — scales every normalised velocity waypoint
float    yProfileBoundLo = 0.0f;   // share clip band: [b, 1-b]; 0 = no clipping
const float Y_VMAX_DEFAULT  = 1.0f;   // m/s — conservative bench speed; TODO(calibrate)
const float Y_BOUND_DEFAULT = 0.0f;   // no clip by default: run the table's full 0..1 excursions
// Above this the clip starts eating the table's INTERMEDIATE plateaus (0.35/0.65), not just the
// 0.0/1.0 bound checks — the run still works but stops being the profile described above, so it
// is accepted with a warning rather than refused.
const float Y_BOUND_WARN    = 0.35f;

// ── State 98 bench tools: combined CURRENT + power-share profile ('W') ────────────────────────
// Same experiment as 'Y', with the motor axis moved from velocity to COMMANDED CURRENT. It runs
// the SAME COMBINED_PROFILE[] table — deliberately not a copy: the two runs are only comparable
// if their shapes are identical by construction, and a duplicated table is a shape that drifts.
// For 'W' the v_start/v_end column is reinterpreted as a NORMALISED current, scaled by the
// operator's wProfileImax; the share column and its post-interpolation clip are identical to 'Y'
// (both go through the shared advanceComboRegion() helper).
//
// Why it exists alongside 'Y': the velocity axis needs a calibrated encoder chain
// (velocityChainCalibrated()), which the bench does not have. 'W' follows the 'T' trapezoid's
// motor conventions instead — direct current through commandMotorCurrentLimited(), no velocity PI,
// no calibration gate, MOT_PWR_ENABLE warn-only — so the share loop can be exercised against a
// realistic, moving motor load on an encoder-less bench.
bool     wProfileActive  = false;
uint8_t  wRegionIdx      = 0;
uint32_t wRegionStart    = 0;
uint32_t wStatusLast     = 0;
float    wProfileImax    = 5.0f;   // A — scales every normalised current waypoint
float    wProfileBoundLo = 0.0f;   // share clip band [b, 1-b]; same meaning as yProfileBoundLo
float    wCmdA           = 0.0f;   // last commanded current (status print / test visibility,
                                   // same role trapCmdA plays for the trapezoid)
// 5 A: a deliberately conservative default for a profile whose plateaus reach the full peak. It was
// originally set to match MOTOR_I_CMD_MAX's then-5 A source-power budget; that constant went to
// 10 A on 2026-08-13 and this default deliberately did NOT follow — the conservatism is the point,
// and nothing couples the two values. The ceiling is TRAP_I_ABS_MAX, not MOTOR_I_CMD_MAX, for
// exactly the reason spelled out at that constant: setCurrent() commands PHASE current, which
// does not map 1:1 onto bus draw. TODO(calibrate).
const float W_IMAX_DEFAULT = 5.0f;
// The share-bound default and warn threshold are SHARED with 'Y' (Y_BOUND_DEFAULT /
// Y_BOUND_WARN): the clip semantics are identical by spec, so a second pair of constants could
// only ever drift apart from these.

// ── State 98 bench tools: serial-plotter stream ('L') ──────────────────────────────────────────
// Emits ONE condensed, fixed-shape line per PLOT_PERIOD_MS that the Arduino IDE Serial Plotter
// parses directly: "label:value,label:value,…". Eight series whose natural ranges overlap (shares
// 0–1, MDAC gains 0–1, per-channel currents ~0–3 A, velocities ~0–3 m/s) — the plotter autoscales
// across ALL series together, so mixing in V_bus (≈17.5) would crush the low-amplitude traces into
// a flat band at the bottom. Voltages stay on the 'S' status dump. The velocity pair (v_sp/v_act)
// joined in fw v7, once the velocity chain was calibrated and v_act became a meaningful number.
//
// The plotter also requires every line to have the SAME field count and to be numeric: any stray
// human-readable line breaks the parse. So while plot mode is on, the three profiles' 500 ms status
// snapshots, their phase banners, and the 'U' VESC watch line are suppressed (plotSuppressStatus()).
// One-shot start/stop/complete notices are deliberately KEPT — a single glitched line is cheaper
// than the operator not knowing a run ended.
bool     plotModeActive = false;
uint32_t plotLastMs     = 0;
// 50 Hz. USB CDC ignores the nominal baud (Teensy enumerates as full-speed USB), so ~60 B/line at
// 50 Hz ≈ 3 kB/s is nowhere near a bottleneck; the limit is the plotter's own redraw. Fast enough
// to resolve the share-loop step response, which settles over hundreds of ms.
const uint32_t PLOT_PERIOD_MS = 20;   // TODO(calibrate): raise if the IDE plotter lags on the bench

// Arming delay. The IDE 2.x Serial Plotter has no send box (IDE 1.8's did) and opening it may close
// the Serial Monitor, so the operator cannot press 'R'/'T' once they are looking at the plot. With
// plot mode ON, those two keys therefore ARM the run instead of starting it, giving time to switch
// windows. Nothing is printed during the countdown — the plot stream is already running, so the
// operator sees a live baseline and then the trace move when the profile actually starts.
// 'D' and 'Y' are deliberately NOT armed and start immediately under plot mode. Both DO move
// plotted series ('D' the fw v7 v_sp/v_act pair, 'Y' those plus 'share_sp'), but arming either
// would mean the run fires seconds after the keypress with the velocity loop live — for 'Y', a
// parameter line typed at the prompt firing seconds later. Unlike 'R'/'T', their preconditions
// (MOT_PWR, the calibrated velocity chain) are checked at the keypress specifically because nothing
// that reaches the input buffer can invalidate them; an arming window would reopen exactly that
// hole. The interaction
// runs the other way instead: an armed 'R'/'T' is refused over a running 'Y' and cancelled by one
// that starts during the countdown (see plotArmTick() / the 'R' arm block).
enum PlotArmTarget { PLOT_ARM_NONE, PLOT_ARM_SHARE, PLOT_ARM_TRAP };
PlotArmTarget plotArmTarget    = PLOT_ARM_NONE;
uint32_t      plotArmDeadlineMs = 0;
// Trapezoid parameters are validated at type-in time but must survive the arming window.
float         plotArmTrapImax   = 0.0f;
uint32_t      plotArmTrapHoldMs = 0;
float         plotArmTrapRate   = 0.0f;
const uint32_t PLOT_ARM_DELAY_MS = 5000;   // TODO(calibrate): how long the window switch really takes

// ── State 98 bench tools: pending numeric input (typed key → serial prompt → float line) ──────
// Non-blocking: a value key sets pendingInput and prints a prompt; subsequent chars accumulate in
// inputBuf until newline, then atof() dispatches to the matching setter. Keeps detectFaults() live.
// PEND_TRAP_PARAMS takes all THREE values on one line ("<Imax> <hold_s> <rate>") — a per-value
// prompt chain broke on line-based terminals: "T\n" cancelled at the empty first prompt, and the
// digits typed afterwards ('2' for the hold time, say) fell through as switch-toggle commands.
enum PendingInput {
    PEND_NONE,
    PEND_POWER_SHARE,
    PEND_OPEN_DROOP,
    PEND_MOTOR_CURRENT,
    PEND_MOTOR_VELOCITY,
    PEND_TRAP_PARAMS,
    // Combined profile: "<Vmax> <b>" on one line, BOTH optional (a bare newline runs the
    // defaults). Same single-line discipline as PEND_TRAP_PARAMS, and for the same reason.
    PEND_Y_PARAMS,
    // Combined CURRENT profile: "<Imax> <b>", same all-optional single-line discipline.
    PEND_W_PARAMS
};
PendingInput pendingInput = PEND_NONE;
// 96 bytes (was 32, grown 2026-08-11 for the 'T' sweep list): the worst legal trapezoid line is
// the 3 values plus a 16-ratio sweep list — "-12.5 10 0.25 [3600,0.05,0.15,…]" — which runs past
// 32 chars at the fourth ratio. Overlong lines are still TRUNCATED (not overflowed) by the
// bounds-checked accumulate in handlePendingInputChar(); truncation then fails the sweep-list
// parse (a missing ']'), so a too-long line is refused outright rather than silently shortened.
char         inputBuf[96];   // 3-value trapezoid line + optional [dwell,r1..r16] sweep list
uint8_t      inputBufIdx = 0;


// ── Forward declarations ──────────────────────────────────────────────────────
// Arduino IDE generates these automatically; g++ (for host-native tests) does not.
void triggerFault(uint16_t fault_bit, ErrorCode_t err);
const char* errorCodeStr(uint8_t code);
void initEscUartPins();
void initMdacSpiPins();
void initChargerI2cPins();
void initMdacOutputs();
void initEsc();
bool initAg105Charger();
bool ag105ReadConfigReg(uint8_t reg, uint8_t &out);
bool ag105WriteConfigRegVerified(uint8_t reg, uint8_t want);
void pollAg105();
bool ag105IsReady();
bool chargerHasPower();
void updateSensors();
void updateWheelSpeed();
void computeDerivedSignals();
void detectFaults();
void checkPiWatchdog();
void receiveCommands();
void sendTelemetry();
void printToTerminal();
void scanI2C();
void printTestHelp();
void doState0();
void doState1();
void doState2();
void doState3();
void doState98();
void doState99();
void doEncoderA();
void doEncoderB();
bool busBringupStart();
BringupStatus busBringupTick(bool doInit);
void busBringupAbort();
bool busHotPlugUnsafe(int regPin);
void commandMotorCurrent(float amps);
void motorControl();
void motorControlGated();
void chargingControlGated();
void powerBalanceGated();
void resetControlRateLimiters();
void powerBalance();
void chargingControl();
float PI_Controller_Motor(float error);
float PI_Controller_Power(float error);
float youlaController_Power(float setpoint, float alphaRaw);
void setDroopMdac(float fc_gain, float bt_gain);
void applyShareRatio(float ratio);
void resetShareControlState();
void resetShareControllerCore(float seedRatio);
// Share-loop state defined with powerBalance() further down, declared here so the State-98 status
// dump (printTestStatus(), which precedes those definitions) can report the fw v5 loop mode.
extern float share_govTotAFilt;
extern bool  shareClosedLoopMode;
extern bool  shareClosedLoopRun;
extern float share_spEffPrev;    // fw v6 effective-setpoint reference (slew-limited)
void assertFcChargeEnable(bool enable);
bool motPwrConnectBlocked();
bool assertMotPwrEnable(bool enable);
void safeAllSwitches();
void printTestStatus();
void advanceDriveCycle();
void setPowerShareSetpointLive(float s);
void applyOpenLoopDroop(float ratio);
void setManualMotorCurrent(float a);
void setManualMotorVelocity(float v);
void applyManualMotor();
void haltMotorOutput();
bool velocityChainCalibrated();
void printVelocityChainRefusal(const char *what);
void advancePowerShareProfile();
void startPowerShareProfile();
void plotTick();
void plotArmTick();
void cancelPlotArm(const char *why);
bool plotSuppressStatus();
void startTrapProfile(float imax, uint32_t holdMs, float rateAps);
void advanceTrapProfile();
void parseTrapParamsLine(const char* line);
void tsweepTick();
void tsweepCancel(const char* why);
static void restoreShareCutoffOnCompletion(const char *tag);
void tsweepFinish();
void startCombinedProfile(float vmax, float boundLo);
void advanceCombinedProfile();
void parseCombinedParamsLine(const char* line);
void startCurrentComboProfile(float imax, float boundLo);
void advanceCurrentComboProfile();
void parseCurrentComboParamsLine(const char* line);
bool parseTwoOptionalFloats(const char* line, const char* usage, float &first, float &second);
bool validateShareBound(float b);
ComboTickResult advanceComboRegion(uint8_t &regionIdx, uint32_t &regionStart, const char *tag,
                                   float boundLo, float &axisNormOut, float &shareOut);
void commandMotorCurrentLimited(float amps, float absMax);
const char* trapPhaseStr(TrapPhase p);
void handlePendingInputChar(char c);
bool isNumericEntryChar(char c);
bool isSweepListChar(char c);
const char* vescFaultStr(uint8_t code);
void queryVescInfo();
void pollVescWatch();
void logOpenForProfile(uint8_t typeMask);
void logRequestClose(uint8_t reason);
void logSampleTick();
void logDrainTick();
void printSdStatus();

// ═════════════════════════════════════════════════════════════════════════════
// STATE 98 BENCH TOOL — SD-CARD DATA LOGGER (1 kHz binary, non-blocking)
// ═════════════════════════════════════════════════════════════════════════════
// Why this exists: the Youla-H share controller runs at 1 kHz, but the only other capture path
// ('L' Serial-Plotter stream) is 50 Hz — 20x too coarse to resolve the step response the H-infinity
// design round was for. This logs one fixed-size binary record per power-balance tick to the
// Teensy 4.1's BUILT-IN micro-SD over SDIO (its own bus — no contention with the MDAC SPI or the
// Ag105 I2C), for the duration of a State-98 profile run.
//
// NON-BLOCKING DISCIPLINE (five dead boosts say the main loop may never stall):
//   - The control path only ever memcpy()s 68 bytes into a static ring (logSampleTick()). No I/O,
//     no formatting, no allocation, no blocking, ever.
//   - All card I/O happens in logDrainTick(), called from loop(): it bails immediately when the
//     card is busy and writes at most ONE <=512 B chunk per loop tick. This is the SD analogue of
//     plotTick()'s Serial.availableForWrite() backpressure guard.
//   - Overflow policy is DROP-NEWEST + COUNT. The logger never waits for the card and never
//     overwrites unwritten data; a stalled card costs samples, not loop time — note this bounds
//     the *sampling* path only; the drain's own write()/truncate()/close() are synchronous inside
//     SdFat and bounded only by the card, which is why the drain is gated out of the State-99
//     teardown.
//   - The logger NEVER calls triggerFault(). An SD failure is a lost measurement, not a hazard;
//     conversely a fault must never be delayed by the card, so triggerFault() only sets the
//     deferred-close flag and the drain in loop() finishes the file once State 99 has finished
//     tearing down (state99Phase == 3) — never between its sequencing phases.
//
// Retrieval is by card pull; tools/decode_benchlog.py turns a .BLG into CSV.
#define LOG_REC_SIZE        68u                 // bytes per record (format v3) — static_assert'ed
#define LOG_RING_RECORDS    1024u               // ~1.0 s of 1 kHz coverage; covers a ~250 ms card
                                                // stall with 4x margin (68 KB of the Teensy's 1 MB)
#define LOG_RING_BYTES      (LOG_REC_SIZE * LOG_RING_RECORDS)
#define LOG_CHUNK_MAX       512u                // one SD block per loop tick: >=512 B/ms drained
                                                // against a 68 B/ms fill, so catch-up is fast.
                                                // Chunks are floored to whole records below (7 x 68 =
                                                // 476 B), so the drain accounting stays exact
#define LOG_PREALLOC_BYTES  (32u * 1024u * 1024u)  // ~8 min at 68 KB/s; truncate()d at close.
                                                // Contiguous allocation keeps per-chunk latency in
                                                // the tens of us (no FAT-chain seeks mid-run)
#define LOG_CLOSE_DEADLINE_MS 2000u             // give up draining a wedged card and close anyway

// Header profile-type field is a BITMASK, not an enum: a future combined DC+PS profile sets two
// bits with no format change (same reason the three phase bytes are independent).
#define LOG_TYPE_PS  0x01
#define LOG_TYPE_TP  0x02
#define LOG_TYPE_DC  0x04

// Trailer close-reason codes (decoder-visible: why the run ended).
#define LOG_CLOSE_COMPLETE 1   // profile ran to natural completion
#define LOG_CLOSE_STOP     2   // operator stop-toggle ('R'/'T'/'D' pressed again)
#define LOG_CLOSE_X        3   // universal stop
#define LOG_CLOSE_Q        4   // State 98 exit
#define LOG_CLOSE_FAULT    5   // triggerFault() — error_code carries the cause
#define LOG_CLOSE_IO_ERROR 6   // mid-run write failure (card full / I/O error)

// One sample. Packed + fixed size so the ring is trivially indexable and the decoder can
// struct.unpack() it directly. Little-endian native (Teensy 4.1 and the host tests are both LE).
struct __attribute__((packed)) BenchLogRecord {
    uint32_t t_us;         // micros() at sample — the timebase for step-response fits
    float    share_sp;     // power_share_setpoint (FC share commanded)
    float    share_act;    // measured share, same formula as plotTick()
    float    v_sp;         // v_setpoint  (see flags bit1 before trusting)
    float    v_act;        // v_actual    (see flags bit1 before trusting)
    float    I_fc;
    float    I_batt;
    float    gFC;          // droop_gain_FC_actual (MDAC command)
    float    gBT;          // droop_gain_BT_actual
    float    V_bus;
    float    I_cmd;        // `current` — post-clamp commanded motor current
    // Format v3 (fw v5, 2026-08-12): the four remaining measured rails. The fw v4 sweep ended two
    // runs (WP0072, WP0073) in an MCU BROWNOUT with the BUS still in regulation — the Teensy is
    // board-powered from V_batt through the LM1084, so the rail that actually collapsed was never
    // logged and no threshold for a source-rail UV fault could be set from data. All four are
    // already refreshed every tick in updateSensors(); logging them costs 16 B/record and no new
    // measurement work.
    float    V_fc;
    float    V_batt;
    float    V_chg;        // charger input (pin 38)
    float    V_rgn;        // regen node    (pin 39)
    uint16_t fault_flags;
    uint8_t  ps_phase;     // running profile's phase index, 0xFF when THAT profile is not active
    uint8_t  dc_phase;     // (three independent bytes — a combined DC+PS profile sets two at once)
    uint8_t  trap_phase;
    uint8_t  flags;        // bit0 = a profile / live share loop is driving the droop MDACs this
                           //        tick (i.e. gFC/gBT are under loop control, not a static
                           //        operator write). NOTE: bit0 alone no longer implies CLOSED
                           //        loop - see bit2/bit3 (fw v5);
                           // bit1 = velocity chain valid (velocityChainCalibrated()) - when clear,
                           //        v_sp/v_act are logged as-is but mean nothing and the decoder
                           //        marks those columns invalid. Logging NEVER requires the encoder;
                           // bit2 = shareClosedLoopMode: the Youla controller is being stepped this
                           //        tick (fw v5). Clear = OPEN-LOOP mode: either setpoint
                           //        feedforward or a hold, distinguished by bit3;
                           // bit3 = shareClosedLoopRun: the closed loop has run at least once since
                           //        the last share-control reset. bit2=0,bit3=0 -> open-loop
                           //        feedforward; bit2=0,bit3=1 -> HOLD (no MDAC write this tick);
                           //        bit2=1 -> closed loop (fw v5).
    uint8_t  pad[2];       // zero
};
static_assert(sizeof(BenchLogRecord) == LOG_REC_SIZE, "BenchLogRecord must stay 68 bytes (format v3)");

#define LOG_PHASE_NONE 0xFFu   // "this profile was not running for this sample"

// ── Logger module state ───────────────────────────────────────────────────────
// DMAMEM puts the 68 KB ring in RAM2/OCRAM instead of RAM1/DTCM, which is the tight, fast memory
// the control code and stack want. The ring is touched once per ms by a memcpy and once per loop
// tick by the drain — it does not need DTCM latency. (Host g++ has no such attribute.)
#ifndef DMAMEM
#define DMAMEM
#endif

SdFs     sd;
FsFile   logFile;
bool     sdAvailable       = false;   // card found at the one-and-only init probe
bool     sdInitTried       = false;   // probe latch — the card is probed ONCE per power cycle
                                      // (in setup(), or lazily at the first profile start if
                                      // setup() never ran, e.g. the host tests). Never retried: a
                                      // re-probe per profile start would run SdFat's multi-second
                                      // init timeout in the main loop with the power stage live.
bool     sdWarnPrinted     = false;   // one-shot "no card" warn latch, SEPARATE from sdInitTried:
                                      // the probe happens in setup() where USB Serial may not be
                                      // enumerated yet, so the warn is deferred to the first
                                      // profile start where the operator can actually see it.
bool     logActive         = false;   // file open AND sampling armed
bool     logCloseRequested = false;   // deferred close pending — drain then trailer+close
uint8_t  logCloseReason    = 0;
uint32_t logCloseRequestMs = 0;       // millis() at the request, for LOG_CLOSE_DEADLINE_MS
uint32_t logRecordCount    = 0;       // records committed to the ring this file
uint32_t logRecordsWritten = 0;       // records actually WRITTEN to the card this file. Distinct
                                      // from logRecordCount: the deadline-abandon path closes with
                                      // records still in the ring, and the trailer must report what
                                      // is really in the file, not what was sampled.
uint32_t logDroppedCount   = 0;       // samples lost to a full ring (card stall) this file
// Last completed run's numbers, so 'K'/'S' still report something after the counters are cleared
// at close (a status line reading rec=0 right after a run reads as "logging is broken").
uint32_t logLastRecordsWritten = 0;
uint32_t logLastDropped        = 0;
uint32_t logLastAbandoned      = 0;   // records still in the ring when a wedged card forced a close
char     logFileName[16]   = {0};     // active-or-last file name, for 'K'/'S' status
DMAMEM uint8_t logRing[LOG_RING_BYTES];   // static ring; byte indices, whole-record granularity
uint32_t logRingHead       = 0;       // next write offset (bytes, always a multiple of LOG_REC_SIZE)
uint32_t logRingTail       = 0;       // next drain offset  (bytes, always a multiple of LOG_REC_SIZE)
uint32_t logRingCount      = 0;       // records pending in the ring

// Clear every per-file counter/index. Called at open and at close so a stale count can never
// bleed into the next run's trailer (or the 'K' line).
static void logResetBuffers() {
    logRingHead    = 0;
    logRingTail    = 0;
    logRingCount   = 0;
    logRecordCount = 0;
    logRecordsWritten = 0;
    logDroppedCount = 0;
}

// Pick the next free name: <PREFIX><NNNN>.BLG, NNNN = 1 + the max index across ALL THREE prefixes
// so one monotonic counter orders a whole bench session regardless of profile type.
// Deliberately ONE directory pass via openNext() rather than sd.exists() probing (which is O(N)
// directory reads and would grow into a multi-hundred-ms stall as the card fills). Runs at profile
// start only — never in the control path.
// Returns false (fail-closed, no name produced) when the directory scan cannot be started or when
// the 4-digit counter is exhausted. Both causes print their own (distinguishable) console line
// here, at the site that knows which one it was; the caller just returns.
static bool logNextFileName(uint8_t typeMask, char *out, size_t outLen) {
    // The combined ('Y') profile sets PS|DC, so its test MUST come first — a plain
    // (typeMask & LOG_TYPE_PS) check would file every combined run under "PS" and make the two
    // run types indistinguishable on the card.
    const char *prefix = ((typeMask & (LOG_TYPE_PS | LOG_TYPE_DC)) == (LOG_TYPE_PS | LOG_TYPE_DC))
                                                  ? "YP"
                       : ((typeMask & (LOG_TYPE_PS | LOG_TYPE_TP)) == (LOG_TYPE_PS | LOG_TYPE_TP))
                                                  ? "WP"
                       : (typeMask & LOG_TYPE_PS) ? "PS"
                       : (typeMask & LOG_TYPE_TP) ? "TP"
                       :                            "DC";
    uint32_t maxIdx = 0;
    FsFile root = sd.open("/", O_RDONLY);
    // A failed root open is NOT an empty card: falling through with maxIdx=0 would name the file
    // <PREFIX>0001.BLG and point the create below at the OLDEST run's data — which, before the
    // O_EXCL guard at the call site, truncated it away silently.
    if (!root) {
        Serial.println("[SD] directory scan failed — this run is NOT logged");
        return false;
    }
    {
        FsFile entry;
        char   nm[32];
        while (entry.openNext(&root, O_RDONLY)) {
            nm[0] = '\0';
            entry.getName(nm, sizeof(nm));
            entry.close();
            // Expect exactly "XXNNNN.BLG": 2 prefix chars, 4 digits, ".BLG".
            if (strlen(nm) != 10) continue;
            bool knownPrefix = (nm[0] == 'P' && nm[1] == 'S') ||
                               (nm[0] == 'T' && nm[1] == 'P') ||
                               (nm[0] == 'D' && nm[1] == 'C') ||
                               (nm[0] == 'Y' && nm[1] == 'P') ||   // combined DC+PS profile
                               (nm[0] == 'W' && nm[1] == 'P');    // combined TP+PS profile
            if (!knownPrefix) continue;
            if (strcmp(nm + 6, ".BLG") != 0) continue;
            uint32_t idx = 0;
            bool digits = true;
            for (int i = 2; i < 6; i++) {
                if (nm[i] < '0' || nm[i] > '9') { digits = false; break; }
                idx = idx * 10u + (uint32_t)(nm[i] - '0');
            }
            if (digits && idx > maxIdx) maxIdx = idx;
        }
        root.close();
    }
    // At 9999 the next name would be 11 chars ("PS10000.BLG"), which the 10-char scan filter above
    // can never see — so every subsequent run would re-derive 10000 and collide on the SAME name.
    // (The O_EXCL create at the call site now refuses that collision too, but silently losing every
    // run past 9999 is worth its own explicit message.) Refuse here.
    if (maxIdx >= 9999u) {
        Serial.println("[SD] run counter exhausted — archive the card");
        return false;
    }
    snprintf(out, outLen, "%s%04lu.BLG", prefix, (unsigned long)(maxIdx + 1u));
    return true;
}

// Finish the file: trailer record, truncate the pre-allocated tail, close, clear state.
// `ok` false means a write already failed — the trailer is still attempted (a partial file with a
// trailer is far easier to interpret than one without) but its result is ignored.
static void logFinishFile(bool ok) {
    uint32_t abandoned = logRingCount;   // records sampled but never written (wedged-card close)
    if (logFile.isOpen()) {
        // Trailer = one record-sized block with the t_us sentinel, so a decoder that walks
        // fixed-size records finds it naturally — no header rewrite, hence no seek back to the
        // start of the file at close. (Close is NOT cheap in absolute terms: truncate() below
        // walks and releases the pre-allocated FAT chain, tens of ms. That is acceptable because
        // close only ever runs between runs / after a fault latch, never in the control path —
        // and truncate is a disk-space optimisation, not a correctness requirement: the decoder
        // stops at this sentinel, so the untruncated tail would be ignored anyway.)
        uint8_t tr[LOG_REC_SIZE];
        memset(tr, 0, sizeof(tr));
        uint32_t sentinel = 0xFFFFFFFFu;
        memcpy(tr + 0,  &sentinel,          4);
        memcpy(tr + 4,  &logRecordsWritten, 4);   // what is REALLY in the file, not what was sampled
        memcpy(tr + 8,  &logDroppedCount,   4);
        tr[12] = logCloseReason;
        tr[13] = error_code;   // only meaningful for LOG_CLOSE_FAULT
        memcpy(tr + 14, &abandoned,         4);   // sampled but never drained (deadline close)
        logFile.write(tr, sizeof(tr));
        logFile.truncate();    // cut the unused pre-allocation back to the write position
        logFile.close();
    }
    if (ok) {
        Serial.print("[SD] closed: ");   Serial.print(logFileName);
        Serial.print(" ");               Serial.print(logRecordsWritten);
        Serial.print(" records, ");      Serial.print(logDroppedCount);
        Serial.print(" dropped");
        if (abandoned > 0) {
            Serial.print(", ");          Serial.print(abandoned);
            Serial.print(" abandoned (card did not drain)");
        }
        Serial.println();
    } else {
        // Nothing latches here: logging simply ends for THIS run, and the next profile start
        // opens a fresh file and tries again.
        Serial.println("[SD] write error — this run's log ended");
    }
    logLastRecordsWritten = logRecordsWritten;   // preserved for the 'K'/'S' idle status lines
    logLastDropped        = logDroppedCount;
    logLastAbandoned      = abandoned;
    logActive         = false;
    logCloseRequested = false;
    logCloseReason    = 0;
    logResetBuffers();
}

// Open a file for a profile run. Called from the three profile start paths. Every failure mode
// (no card, open error, header write error) warns ONCE and returns — the profile always runs
// identically with or without a card; logging is never a precondition for a bench run.
void logOpenForProfile(uint8_t typeMask) {
    // Fallback probe. setup() normally does this with the power stage dark; this branch only fires
    // when setup() never ran (host tests) — it must stay, but on hardware it is dead code.
    if (!sdInitTried) {
        sdInitTried = true;
        sdAvailable = sd.begin(SdioConfig(FIFO_SDIO));
    }
    if (!sdAvailable) {
        // Warn HERE, not at the probe: the probe happens in setup() before USB Serial is usable.
        // One line per power cycle — a per-run repeat would be noise on a deliberately card-less run.
        if (!sdWarnPrinted) {
            sdWarnPrinted = true;
            Serial.println("[SD] no card — logging disabled");
        }
        return;
    }

    // A live log at this point means one profile took over from another without its stop path
    // running (the profile starts clear each other's flags, but a direct start-over-start does not
    // route through a stop). Never open a second file over the first — that would either leak the
    // handle or splice two runs into one file. Finish the old file, then decide whether this run
    // can still be logged. logFinishFile() (not logRequestClose()) because a stale OPEN HANDLE
    // with logActive/logCloseRequested already clear would make the request a no-op and leak it.
    if (logActive || logCloseRequested || logFile.isOpen()) {
        // Whether the NEW run can also be logged turns on the card being idle. Opening a file is
        // not free — logNextFileName() walks the directory and preAllocate() claims 32 MB — and
        // doing that on a card that is still stalled would be a second, unbounded stall at a
        // profile-start KEYPRESS with the power stage live, i.e. exactly the delay to
        // detectFaults() this module may never introduce. Idle card: finish the old file and take
        // the new one. Busy card: finish the old file and stop there.
        bool cardIdle = sd.card() && !sd.card()->isBusy();

        // Only stamp a reason if nobody has already set one. A close ALREADY REQUESTED (e.g. 'Q'
        // exit with a stalled card, then straight back into a new run) carries the real reason the
        // run ended; overwriting it with STOP would mislabel the trailer and contradicts
        // logRequestClose()'s "first requester's reason wins" discipline. Zero means we got here on
        // a stale open handle with the flags already clear, which genuinely is a STOP.
        if (logCloseReason == 0) logCloseReason = LOG_CLOSE_STOP;
        logFinishFile(true);

        if (!cardIdle) {
            Serial.println("[SD] previous log still open (card busy) — this run is NOT logged");
            return;
        }
        // FALL THROUGH to open a new file. A profile taking over from another directly (start
        // over start, without the first one's stop path running) is a real bench run, and
        // silently losing its log was the worse failure — the old file is closed and complete at
        // this point, so the open below starts from the same clean state a normal start does.
    }

    char name[16];
    if (!logNextFileName(typeMask, name, sizeof(name))) {
        // Fail-closed, two distinguishable causes — logNextFileName() prints whichever applies
        // (failed directory scan / exhausted 4-digit counter) at the site that knows.
        return;
    }
    // O_EXCL: even a wrong index from a partially-completed scan (openNext read error) cannot
    // truncate an existing log — create fails instead and lands in the refusal below, fail-closed.
    logFile = sd.open(name, O_WRITE | O_CREAT | O_EXCL);
    if (!logFile) {
        Serial.print("[SD] open failed (");
        Serial.print(name);
        Serial.println(") — this run is NOT logged");
        return;
    }
    // TODO(measure): bench-measure open-path latency (name scan + preAllocate(32 MB) + header) on
    // the card in use. preAllocate must find contiguous space — est. up to ~1 s on a fragmented
    // FAT32 card, and 'R' is the one start with a live motor command. If measured > ~100 ms, move
    // the preflight (scan + preAllocate) to State-98 entry.
    logFile.preAllocate(LOG_PREALLOC_BYTES);

    // 32-byte self-describing header: magic, format version, record size, profile bitmask, and the
    // millis/micros timebase the records' t_us is relative to.
    uint8_t hdr[32];
    memset(hdr, 0, sizeof(hdr));
    hdr[0] = 'B'; hdr[1] = 'L'; hdr[2] = 'G'; hdr[3] = '1';
    hdr[4] = 4;                       // format version (v2 added fw_version at offset 18; v3 added
                                      // V_fc/V_batt/V_chg/V_rgn to the record → 68 B; v4 adds the
                                      // committed per-run profile parameters below. RECORD FORMAT
                                      // IS UNCHANGED from v3 — 68 B, same field order — so a v3
                                      // decoder needs only the header change.)
    hdr[5] = (uint8_t)LOG_REC_SIZE;
    hdr[6] = typeMask;

    // ── v4 profile-parameter block (bytes 7, 20–27) ──────────────────────────
    // WHY: a decoded run's share/current traces are uninterpretable without the operator scale the
    // run was started with. Imax/Vmax and the share clip bound b were typed at the prompt and then
    // existed only in the scrollback; the fw v5 sweep analysis had to reconstruct them by hand.
    //
    // MECHANISM: derived HERE from typeMask plus the profile globals, rather than threaded through
    // as parameters. Every start function commits its parameters to those globals BEFORE calling
    // logOpenForProfile() (verified at all five call sites, including the 'T' sweep, whose per-run
    // startTrapProfile() re-commits trapImax each run — the sweep's per-run r_i is a SETPOINT and
    // deliberately does not appear here). typeMask already selects the run type for the filename
    // prefix, so this reuses one existing discriminator instead of introducing a second one that
    // could disagree with it; and no call site can forget to pass a value.
    // hdr[7] bit0 = profileAmp valid, bit1 = profileB valid. A run type with no such parameter
    // (R = power-share profile, D = drive cycle) leaves the flag 0 and the field 0.0 — the flag,
    // not the value, is what a decoder must test.
    uint8_t  paramFlags = 0;
    float    profileAmp = 0.0f;   // T/W: Imax [A];  Y: Vmax [m/s]
    float    profileB   = 0.0f;   // W/Y: committed share clip bound b
    if ((typeMask & (LOG_TYPE_PS | LOG_TYPE_DC)) == (LOG_TYPE_PS | LOG_TYPE_DC)) {
        profileAmp = yProfileVmax;    profileB = yProfileBoundLo;  paramFlags = 0x03;   // 'Y'
    } else if ((typeMask & (LOG_TYPE_PS | LOG_TYPE_TP)) == (LOG_TYPE_PS | LOG_TYPE_TP)) {
        profileAmp = wProfileImax;    profileB = wProfileBoundLo;  paramFlags = 0x03;   // 'W'
    } else if (typeMask & LOG_TYPE_TP) {
        profileAmp = trapImax;                                     paramFlags = 0x01;   // 'T'
    }                                                                                   // PS/DC: 0
    hdr[7] = paramFlags;
    memcpy(hdr + 20, &profileAmp, 4);
    memcpy(hdr + 24, &profileB,   4);
    // Bytes 28–31 are the only reserved region; the memset above already zeroed them. (Byte 19 is
    // NOT reserved — it is the high byte of the 2-byte fwVersion written at hdr+18 below, and it
    // merely happens to read zero while FW_VERSION < 256.)

    uint32_t startMs = millis();
    uint32_t startUs = micros();
    memcpy(hdr + 8,  &startMs, 4);
    memcpy(hdr + 12, &startUs, 4);
    uint16_t kDroopMilli = (uint16_t)(K_DROOP * 1000.0f + 0.5f);   // droop scale in use, for the decoder
    memcpy(hdr + 16, &kDroopMilli, 2);
    uint16_t fwVersion = FW_VERSION;  // which firmware produced this data (docs/firmware-versions.md)
    memcpy(hdr + 18, &fwVersion, 2);

    logResetBuffers();
    if (logFile.write(hdr, sizeof(hdr)) != sizeof(hdr)) {
        // Truncate + remove, do not just close: the preAllocate() above already claimed 32 MB, and
        // a headerless junk file of that size would both waste the card and feed the name scan
        // above (its name counts toward maxIdx forever).
        Serial.println("[SD] header write failed — this run is NOT logged");
        logFile.truncate();
        logFile.close();
        sd.remove(name);
        return;
    }
    strncpy(logFileName, name, sizeof(logFileName) - 1);
    logFileName[sizeof(logFileName) - 1] = '\0';
    logActive = true;
    Serial.print("[SD] logging -> "); Serial.println(logFileName);
}

// Ask for the file to be closed. FLAG-SET ONLY — no card I/O here, so this is safe to call from
// any exit path including triggerFault(). logDrainTick() in loop() drains the ring and writes the
// trailer. Sampling stops immediately (logActive cleared) so the tail of the file is the run.
void logRequestClose(uint8_t reason) {
    if (!logActive && !logCloseRequested) return;   // nothing open — no-op, so every exit path can
                                                    // call this unconditionally (same discipline as
                                                    // cancelPlotArm())
    if (logCloseRequested) return;                  // first requester's reason wins
    logActive         = false;
    logCloseRequested = true;
    logCloseReason    = reason;
    logCloseRequestMs = millis();
}

// One sample into the ring. Called from the State-98 tick spine. Cost is a rate-limit check plus a
// 68-byte memcpy — deliberately the only logger code that runs in the control path.
void logSampleTick() {
    if (!logActive) return;
    if (!rateLimitDue(rl_log_last, POWER_BAL_PERIOD_US)) return;

    // Ring full (card stalled): DROP THE NEW SAMPLE and count it. Never block, never overwrite —
    // overwriting would corrupt data already committed for writing, and blocking would stall
    // detectFaults() behind a card.
    if (logRingCount >= LOG_RING_RECORDS) {
        logDroppedCount++;
        return;
    }

    BenchLogRecord r;
    r.t_us     = micros();
    r.share_sp = power_share_setpoint;
    // Same measured-share formula as plotTick(): undefined with no current flowing → 0.
    float totalA = fabsf(I_fc) + fabsf(I_batt);
    r.share_act = (totalA > 1e-6f) ? (fabsf(I_fc) / totalA) : 0.0f;
    r.v_sp     = v_setpoint;
    r.v_act    = v_actual;
    r.I_fc     = I_fc;
    r.I_batt   = I_batt;
    r.gFC      = droop_gain_FC_actual;
    r.gBT      = droop_gain_BT_actual;
    r.V_bus    = V_bus;
    r.I_cmd    = current;
    // Format v3 (fw v5): the source/charger/regen rails, straight from updateSensors().
    r.V_fc     = V_fc;
    r.V_batt   = V_batt;
    r.V_chg    = V_chg;
    r.V_rgn    = V_rgn;
    r.fault_flags = fault_flags;
    // The combined ('Y') profile drives BOTH setpoints from one region index, so it writes that
    // index into BOTH phase bytes — the exact "both bytes non-0xFF at once" case the three
    // independent phase bytes and the header bitmask were designed for (no format change). The
    // header's PS|DC mask is what tells the decoder the two bytes are one axis, not two.
    r.ps_phase   = powerShareProfileActive ? powerShareProfilePhaseIdx
                 : combinedProfileActive   ? combinedRegionIdx
                 : wProfileActive          ? wRegionIdx
                 :                           LOG_PHASE_NONE;
    r.dc_phase   = driveCycleActive        ? driveCyclePhaseIdx
                 : combinedProfileActive   ? combinedRegionIdx
                 :                           LOG_PHASE_NONE;
    r.trap_phase = trapProfileActive       ? (uint8_t)trapPhase
                 : wProfileActive          ? wRegionIdx
                 :                           LOG_PHASE_NONE;
    r.flags = 0;
    if (powerShareProfileActive || driveCycleActive || trapProfileActive ||
        combinedProfileActive   || wProfileActive   || powerBalanceLive)
        r.flags |= 0x01;
    if (velocityChainCalibrated())
        r.flags |= 0x02;
    // fw v5 share-loop mode, so a decoded run says WHICH law produced gFC/gBT on each tick.
    if (shareClosedLoopMode) r.flags |= 0x04;
    if (shareClosedLoopRun)  r.flags |= 0x08;
    r.pad[0] = 0;
    r.pad[1] = 0;

    memcpy(&logRing[logRingHead], &r, LOG_REC_SIZE);
    logRingHead = (logRingHead + LOG_REC_SIZE) % LOG_RING_BYTES;
    logRingCount++;
    logRecordCount++;
}

// Drain at most one chunk per loop tick, then finish a pending close once the ring is empty.
// Called from loop() (NOT doState98()) so the drain — and therefore the deferred close — keeps
// running after a fault has latched State 99, without touching the teardown phase ordering.
void logDrainTick() {
    if (!logActive && !logCloseRequested) return;   // idle cost: one branch

    // No card → there is nothing to drain and sd.card() may be null. Dereferencing it below would
    // hard-fault, and on this board a hard fault means a reset, which means doState0() re-enabling
    // the boosts on whatever the rails are doing — the known motorboating/boost-death loop. Clear
    // the flags so this can never re-enter.
    if (!sdAvailable) {
        logActive         = false;
        logCloseRequested = false;
        return;
    }

    // No card I/O between State-99 teardown phases: write()/truncate()/close() are SYNCHRONOUS
    // inside SdFat and isBusy() cannot bound an operation it merely precedes. The teardown's
    // millis()-deadline dwells would otherwise stretch by the card's latency (measured: phase 1
    // slips from 10 ms to D+1 ms for a D-ms close). Phase 3 = fully latched — which is exactly the
    // condition logFinishFile()'s comment already assumes. Costs nothing: logActive is already
    // false from logRequestClose(), and 20 ms << LOG_CLOSE_DEADLINE_MS.
    if (mainState == 99 && state99Phase < 3) return;

    // Deadline FIRST, before the busy guard. A permanently-busy card (dead controller, bad socket)
    // would otherwise take the early return forever: the deadline check below would never be
    // reached, the file would never close, logCloseRequested would never clear, and every later
    // profile start would hit the double-open branch — silent, session-wide loss of logging.
    bool timedOut = logCloseRequested &&
                    ((uint32_t)(millis() - logCloseRequestMs) >= LOG_CLOSE_DEADLINE_MS);
    if (timedOut) {
        // Abandon whatever is still in the ring (counted into the trailer) and close NOW.
        // HONEST CAVEAT: the trailer write / truncate / close inside logFinishFile() may itself
        // busy-wait inside SdFat on a wedged card. That is tolerable ONLY because this path runs
        // after the run has already ended — State 99 with the switches parked, or Idle — never
        // while a profile drives the motor. The 2 s deadline bounds how long we politely wait
        // before accepting that risk.
        logFinishFile(true);
        return;
    }

    // Card busy → skip this tick entirely. This is the guarantee that logging cannot stretch the
    // loop period: we only ever write when the card says it is ready.
    if (sd.card()->isBusy()) return;

    if (logRingCount > 0) {
        uint32_t pending = logRingCount * LOG_REC_SIZE;
        uint32_t toEnd   = LOG_RING_BYTES - logRingTail;     // one contiguous region per tick;
        uint32_t chunk   = (pending < toEnd) ? pending : toEnd;   // the wrap is handled by simply
        if (chunk > LOG_CHUNK_MAX) chunk = LOG_CHUNK_MAX;         // stopping at the ring end
        // Keep the tail record-aligned so the ring accounting stays in whole records (the file
        // itself is a byte stream, so a short chunk is harmless).
        chunk = (chunk / LOG_REC_SIZE) * LOG_REC_SIZE;
        if (chunk == 0) chunk = LOG_REC_SIZE;

        if (logFile.write(&logRing[logRingTail], chunk) != chunk) {
            // Card full / IO error mid-run: give up on logging, attempt trailer + close ONCE, warn
            // once. Deliberately NOT a triggerFault() — a lost measurement is not a hazard, and the
            // fault path must never be entered from the logger.
            // Stamp the reason FIRST: logFinishFile() writes the trailer from logCloseReason, and
            // this path is reached with it still 0 (no logRequestClose() ran) — an undocumented
            // reason 0 in the trailer decodes as "unknown" instead of "I/O aborted".
            logCloseReason = LOG_CLOSE_IO_ERROR;
            logFinishFile(false);
            return;
        }
        logRingTail        = (logRingTail + chunk) % LOG_RING_BYTES;
        logRingCount      -= chunk / LOG_REC_SIZE;
        logRecordsWritten += chunk / LOG_REC_SIZE;   // what the trailer reports (see logFinishFile)
    }

    // Ring empty and a close pending → write the trailer and close. (The timed-out case was
    // handled above, ahead of the busy guard.)
    if (logCloseRequested && logRingCount == 0) logFinishFile(true);
}

// 'K' — SD status snapshot. Deliberately does NOT call freeClusterCount() or any other FAT-scanning
// API: those walk the allocation table and block for SECONDS on a real card, which is exactly the
// class of stall this whole module is built to avoid.
void printSdStatus() {
    Serial.println("=== SD logger ===");
    Serial.print("card:      ");
    Serial.println(!sdInitTried ? "not probed yet"
                                : (sdAvailable ? "present" : "ABSENT — logging disabled"));
    Serial.print("file:      ");
    Serial.println(logFileName[0] ? logFileName : "(none yet)");
    bool running = (logActive || logCloseRequested);
    Serial.print("active:    ");
    Serial.println(logActive ? "YES (sampling)" : (logCloseRequested ? "closing" : "no"));
    // While a run is live these are the live counters; once closed they are cleared, so fall back
    // to the LAST run's numbers — a status line reading rec=0 straight after a run looks broken.
    // Field labels stay fixed either way; the "(last run)" suffix says which is being shown.
    Serial.print("records:   ");
    Serial.print(running ? logRecordsWritten : logLastRecordsWritten);
    Serial.println(running ? "" : "  (last run)");
    Serial.print("dropped:   ");
    Serial.print(running ? logDroppedCount : logLastDropped);
    Serial.println(running ? "" : "  (last run)");
    if (!running && logLastAbandoned > 0) {
        Serial.print("abandoned: "); Serial.print(logLastAbandoned);
        Serial.println("  (last run — card did not drain)");
    }
    // Live-only: records COMMITTED TO THE RING this file (written + still pending). "records:"
    // above counts only what reached the card, so the two disagreeing is the card falling behind.
    // Cleared at close, hence no "(last run)" fallback — the trailer carries the closed run's total.
    if (running) {
        Serial.print("sampled:   "); Serial.println(logRecordCount);
    }
    Serial.print("ring pend: "); Serial.print(logRingCount);
    Serial.print(" / ");         Serial.println(LOG_RING_RECORDS);
    Serial.println("=================");
}

// ═════════════════════════════════════════════════════════════════════════════
// SETUP
// ═════════════════════════════════════════════════════════════════════════════
void setup() {
    Serial.begin(115200);
    Serial1.begin(115200);
    Serial.print("[BOOT] DC balancer firmware v"); Serial.print(FW_VERSION);
    Serial.print(" (BENCH_TEST="); Serial.print(BENCH_TEST); Serial.println(")");

    // Teensy 4.1 ADC: select 12-bit resolution before any analogRead
    analogReadResolution(12);
    // Hardware-average 16 samples per analogRead (Teensyduino default is 4).
    // This is GLOBAL: it applies to every analogRead on both ADC modules, so
    // all 7 analog channels -- the INA253 currents, V_bus, and the other
    // rail dividers -- get the same averaging. Bench validation: 4 -> 8
    // (logs PS0001 vs PS0002, matched 3 A runs) cut the INA253-channel noise
    // by exactly the predicted sqrt(2) (sigma_share 0.065 -> 0.047),
    // confirming the volt-domain ADC floor dominates at light load; 8 -> 16
    // buys another ~sqrt(2). Cost: ~4x the default conversion time, still
    // well inside the 1 kHz tick budget (at averaging=8 the logs showed
    // missed_periods=0 with >0.6 ms of margin).
    analogReadAveraging(16);

    initEscUartPins();
    initMdacSpiPins();
    initChargerI2cPins();

    // Pins 0/1 (RX/TX) are owned by Serial1 — initEscUartPins() already configured their pad
    // mux for LPUART6. Do NOT call pinMode() on them: on Teensy 4.x pinMode() reassigns the
    // pad to GPIO, which silently disconnects the UART and kills all VESC communication.
    pinMode(ENC_A,   INPUT);
    pinMode(ENC_B,   INPUT);
    pinMode(ENC_ENABLE,    OUTPUT);
    // Boost regulators default OFF. doState0() decides when to enable them: in production after the
    // bus switches (gentle bring-up), and in BENCH_TEST never at boot (the power stage stays dark so
    // a soft bench supply can't brown out and motorboat the boost). See "VBUS controlled bring-up".
    pinMode(FC_REG_ENABLE, OUTPUT); digitalWrite(FC_REG_ENABLE, LOW);
    pinMode(BT_REG_ENABLE, OUTPUT); digitalWrite(BT_REG_ENABLE, LOW);
    pinMode(CS_MDAC_FC,    OUTPUT);
    pinMode(CS_MDAC_BT,    OUTPUT);
    pinMode(CHARGER_STAT,  INPUT);

    // Path switches — all LOW at boot (fail-safe; 10kΩ EN-to-GND bodge resistors also pull LOW)
    // Firmware still drives explicit levels early so we don't rely solely on passive resistors.
    pinMode(FC_BUS_ENABLE,      OUTPUT); digitalWrite(FC_BUS_ENABLE,      LOW);
    pinMode(BT_BUS_ENABLE,      OUTPUT); digitalWrite(BT_BUS_ENABLE,      LOW);
    pinMode(MOT_PWR_ENABLE,     OUTPUT); digitalWrite(MOT_PWR_ENABLE,     LOW);
    pinMode(REGEN_ENABLE,       OUTPUT); digitalWrite(REGEN_ENABLE,       LOW);
    pinMode(FC_CHARGE_ENABLE,   OUTPUT); digitalWrite(FC_CHARGE_ENABLE,   LOW);
    pinMode(BT_SEQUENCE_ENABLE, OUTPUT); digitalWrite(BT_SEQUENCE_ENABLE, LOW);

    // MPPT_DISABLE (active-LOW): LOW = MPPT loop inhibited.
    // Fail-safe: charger cannot harvest if Teensy resets mid-run.
    // Source: user-confirmed from PCB schematic.
    pinMode(MPPT_DISABLE, OUTPUT); digitalWrite(MPPT_DISABLE, LOW);

    // CBAL_DISABLE (pin 9): LOW = balancer/OVP active, HIGH = disabled.
    // No external pull resistor on CB-DISABLE net (direct GPIO connection — source: PCB schematic).
    // Enable INPUT_PULLUP first so pin defaults HIGH (balancer disabled = safe) during any
    // MCU reset/high-Z window before setup() drives it.
    pinMode(CBAL_DISABLE, INPUT_PULLUP);
    pinMode(CBAL_DISABLE, OUTPUT); digitalWrite(CBAL_DISABLE, LOW);   // OVP active

    digitalWrite(CS_MDAC_FC,    HIGH);
    digitalWrite(CS_MDAC_BT,    HIGH);
    // FC_REG_ENABLE / BT_REG_ENABLE intentionally left LOW here — doState0() enables them after
    // the bus switches so the bus is charged via boost soft-start, not a hot-plug step.
    digitalWrite(ENC_ENABLE,    LOW);

    attachInterrupt(digitalPinToInterrupt(ENC_A), doEncoderA, CHANGE);
    attachInterrupt(digitalPinToInterrupt(ENC_B), doEncoderB, CHANGE);

    // Probe the built-in SD ONCE, here — deliberately at boot rather than at the first profile
    // start. SdFat's init can take up to ~2 s on a slow/absent card, and at a profile keypress that
    // stall would sit in the main loop with the power stage LIVE and detectFaults() blind. Placed
    // AFTER the pin-init block above (never before it): every path switch / boost enable must be
    // driven to its deterministic safe level as early as possible — a slow card must not stretch
    // the GPIO high-Z window that the 10k EN-to-GND bodge resistors only backstop. At this point
    // the switches are explicitly LOW and nothing is enabled, so the worst case is a slow boot.
    // The "no card" warn is NOT printed here — USB Serial may not be enumerated yet; it is deferred
    // to the first profile start (sdWarnPrinted). logOpenForProfile() keeps a fallback probe for
    // the host tests, which never call setup().
    sdAvailable = sd.begin(SdioConfig(FIFO_SDIO));
    sdInitTried = true;

#if USE_ETHERNET
    byte mac[] = {0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED};
    IPAddress ip(192, 168, 1, 50);
    Ethernet.begin(mac, ip);   // NOTE: blocks while probing the PHY if no link is present
    Udp.begin(local_port);
    networkUp = true;
    Serial.println("Teensy FCHEV ready | IP=192.168.1.50 | Listening on port 5001");
#else
    Serial.println("Teensy FCHEV ready | BENCH MODE (no Ethernet/Pi) | USB serial only");
#endif
}


// ═════════════════════════════════════════════════════════════════════════════
// MAIN LOOP
// ═════════════════════════════════════════════════════════════════════════════
void loop() {
    updateSensors();
    computeDerivedSignals();
    detectFaults();
    checkPiWatchdog();
    receiveCommands();

    switch (mainState) {
        case 0:  doState0();  break;
        case 1:  doState1();  break;
        case 2:  doState2();  break;
        case 3:  doState3();  break;
        case 98: doState98(); break;
        case 99:
        default: doState99(); break;
    }

    // SD bench-log drain. Deliberately here and NOT in doState98(): a fault that latches State 99
    // mid-profile must still be able to flush and close the file, and 'Q' must not lose it either.
    // No-ops in one branch when nothing is logging. Never blocks (see the logger module header).
    logDrainTick();

    // Telemetry + Ag105 poll at ~50 Hz
    static uint32_t lastSend = 0;
    if (millis() - lastSend > 20) {
        pollAg105();        // refresh I_charge and ag105_status_raw from I2C
        sendTelemetry();
        //printToTerminal();
        lastSend = millis();
    }
}

void printToTerminal() {
    Serial.println("State = " + String(mainState));
    Serial.println("V_batt = " + String(V_batt));
    Serial.println("I_batt = " + String(I_batt));
    Serial.println("I_charge = " + String(I_charge) + " (Ag105 I2C reg 0x06)");
    Serial.println("V_fc = " + String(V_fc));
    Serial.println("I_fc = " + String(I_fc));
    Serial.println("V_bus = " + String(V_bus));
    Serial.println("V_chg = " + String(V_chg));
    Serial.println("V_rgn = " + String(V_rgn));
}

// Dump every sensor value to USB Serial. Sensors are refreshed each loop tick by
// updateSensors()/computeDerivedSignals() before the state switch, so values are current.
// Called throttled from doState1() (IDLE); style mirrors the State 98 status dump.
void printSensors() {
    Serial.println("=== Sensors (IDLE) ===");
    Serial.println("--- Voltages (V) ---");
    Serial.print("V_fc=");   Serial.print(V_fc,   3); Serial.print("  ");
    Serial.print("V_batt="); Serial.print(V_batt, 3); Serial.print("  ");
    Serial.print("V_bus=");  Serial.println(V_bus, 3);
    Serial.print("V_chg=");  Serial.print(V_chg, 3);  Serial.print("  ");
    Serial.print("V_rgn=");  Serial.println(V_rgn, 3);
    Serial.println("--- Currents (A) ---");
    Serial.print("I_fc=");     Serial.print(I_fc,   3); Serial.print("  ");
    Serial.print("I_batt=");   Serial.println(I_batt, 3);
    Serial.print("I_charge="); Serial.print(I_charge, 3); Serial.println("  (Ag105 I2C reg 0x06)");
    Serial.println("--- Derived ---");
    // encoderPos/edges alongside v_actual for the same reason as the State-98 block: a hand-turn
    // check in IDLE must be able to tell "no counts" from "counts but no velocity".
    Serial.print("v_actual=");           Serial.print(v_actual, 3);    Serial.println(" m/s");
    noInterrupts();
    int32_t  encSnap   = encoderPos;
    uint32_t edgeSnapA = encEdgeCountA;
    uint32_t edgeSnapB = encEdgeCountB;
    interrupts();
    Serial.print("encoderPos=");         Serial.print(encSnap);
    Serial.print("  edges A=");          Serial.print(edgeSnapA);
    Serial.print(" B=");                 Serial.print(edgeSnapB);
    Serial.print("  ENC_ENABLE=");       Serial.println(digitalRead(ENC_ENABLE));
    Serial.print("power_share_actual="); Serial.println(power_share_actual, 3);
    Serial.print("P_fc=");               Serial.print(P_fc_actual, 2); Serial.print("W  ");
    Serial.print("P_batt=");             Serial.print(P_batt_actual, 2); Serial.println("W");
    Serial.println("--- Charger ---");
    Serial.print("ag105_status_raw=0x"); Serial.print(ag105_status_raw, HEX);
    Serial.print("  CHARGER_STAT=");     Serial.println(digitalRead(CHARGER_STAT));
    Serial.print("powered=");            Serial.print(chargerHasPower());
    Serial.print("  configured=");       Serial.println(ag105Configured);
    Serial.println("======================");
}


// ═════════════════════════════════════════════════════════════════════════════
// SENSOR READING
// ═════════════════════════════════════════════════════════════════════════════
void updateSensors() {
    updateWheelSpeed();

    // INA253A1: unipolar, REF1/REF2 tied to GND; senses only forward boost current
    I_fc   = analogRead(FC_CURRENT) * SCALE_I;
    I_batt = analogRead(BT_CURRENT) * SCALE_I;
    // I_charge is sourced from Ag105 I2C reg 0x06 by pollAg105() at 50 Hz — no ADC path exists

    V_fc   = analogRead(FC_VOLTAGE)  * SCALE_V_FC;
    V_batt = analogRead(BT_VOLTAGE)  * SCALE_V_BATT;
    V_bus  = analogRead(BUS_VOLTAGE) * SCALE_V_BUS;
    V_chg  = analogRead(CHG_VOLTAGE) * SCALE_V_CHG;
    V_rgn  = analogRead(RGN_VOLTAGE) * SCALE_V_RGN;
}

void computeDerivedSignals() {
    float totalA = fabsf(I_fc) + fabsf(I_batt);
    if (totalA > 1e-6f) {
        power_share_actual = fabsf(I_fc) / totalA;
    }
    // Per-channel power DELIVERED TO THE BUS.
    //
    // Corrected 2026-07-29. These used to read `V_fc * I_fc` and `V_batt * I_batt`, mixing the
    // SOURCE-side terminal voltage with the BUS-side current: the INA253 shunts sit between each
    // boost's VOUT and VBUS (SNS-FC IS+ on VOUT-FC / IS- on VBUS-FC — see the node note at
    // LIMIT_I_FC_MAX), so I_fc/I_batt are boost-OUTPUT currents. The old product was neither input
    // power nor output power, and under-reported by V_bus/V_source ≈ 2× on both channels.
    //
    // Both are now V_bus × I_channel = true power onto the bus, which is also the quantity the
    // power-share split is defined over, so P_fc_actual + P_batt_actual is the bus power and
    // P_fc_actual / (P_fc_actual + P_batt_actual) is the share the EMS commands.
    //
    // PI-BRIDGE NOTE: the telemetry LAYOUT is unchanged (same offsets, same v4 protocol) but these
    // two VALUES now read roughly 2× higher and mean something different. Any Pi-side logging,
    // efficiency calculation, or EMS model that consumed them must be updated in lockstep.
    // To recover source-side INPUT power the board would need input-current sense, which it does
    // not have — estimate it as P_bus/η if needed.
    P_fc_actual   = V_bus * I_fc;
    P_batt_actual = V_bus * I_batt;
}

// Sets fault bit, latches primary error_code on first call, and transitions to State 99.
// All fault entry points funnel through here so no State-99 path bypasses error capture.
void triggerFault(uint16_t fault_bit, ErrorCode_t err) {
    fault_flags |= fault_bit;
    fault_flags |= FAULT_ERROR;    // mark error immediately so detectFaults() preserves it
    if (error_code == ERR_NONE) {  // latch first cause only
        error_code = err;
        error_source_state = (uint8_t)mainState;
    }
    // Close any open bench log with the fault reason. FLAG-SET ONLY — no card I/O on the fault
    // path; logDrainTick() in loop() flushes and closes it during State 99. error_code is latched
    // above first, so the trailer carries the cause.
    logRequestClose(LOG_CLOSE_FAULT);
    mainState = 99;
}

const char* errorCodeStr(uint8_t code) {
    switch (code) {
        case ERR_OC_FC:           return "FC overcurrent";
        case ERR_UV_BATT:         return "Batt undervoltage";
        case ERR_OV_BUS:          return "Bus overvoltage";
        case ERR_SWITCH_CONFLICT: return "Switch conflict";
        case ERR_PI_TIMEOUT:      return "Pi timeout";
        case ERR_OV_BATT:         return "Batt overvoltage";
        case ERR_UV_FC:           return "FC undervoltage";
        case ERR_OC_BT:           return "BT overcurrent";
        case ERR_UV_BUS:          return "Bus undervoltage";
        case ERR_OV_RGN:          return "Regen overvoltage";
        case ERR_OV_CHG:          return "Charger input OV";
        case ERR_I2C_CHARGER:     return "Ag105 I2C fail";
        case ERR_CHARGER_STAT:    return "Ag105 STAT fault";
        case ERR_INIT_FAIL:       return "Init failure";
        case ERR_MOT_HOTPLUG:     return "Motor hot-plug refused";
        default:                  return "Unknown";
    }
}

void detectFaults() {
    // In State 99 (latched), skip threshold recalculation — just ensure FAULT_ERROR stays set.
    // fault_flags retains whatever bits were set when triggerFault() first fired.
    if (mainState == 99) {
        fault_flags |= FAULT_ERROR;
        return;
    }

    fault_flags = 0;  // clear; re-evaluate all threshold conditions this tick

    // -- Existing fault checks (preserve original priority order) ----------------
    // Under BENCH_TEST, only the overvoltage checks below run (the real destroy-the-board
    // faults); overcurrent / undervoltage / switch-conflict / charger-STAT are skipped so a
    // bench board with unpowered rails doesn't latch State 99. Source: bench-test guard.
#if !BENCH_TEST
    if (I_fc   > LIMIT_I_FC_MAX)   triggerFault(FAULT_OC_FC,   ERR_OC_FC);
    // UV checks only fire in Run (State 2): sources are not guaranteed ramped/sequenced in
    // Init/Idle, and V_batt/V_fc read ~0 before the regulators stabilise. Firing UV here would
    // latch State 99 on the very first tick of every boot (V_fc/V_batt init to 0 < limits).
    // Source: boot-lock review. (FAULT_UV_BUS no longer uses a State-2 gate — since 2026-08-12 it
    // is armed by the bus itself; see the uvBusArmed block below.)
    if (mainState == 2 && V_batt < LIMIT_V_BATT_MIN) triggerFault(FAULT_UV_BATT, ERR_UV_BATT);
#endif

    // FAULT_OV_BUS — time-persistence filtered (see OV_BUS_PERSIST_* rationale at the constants).
    // Bring-up load-dump parks are decaying ~ms transients; a single over-limit sample shows the
    // bit (truthful telemetry) but latches State 99 only after the bus has been over-limit for
    // OV_BUS_PERSIST_MS continuous AND OV_BUS_PERSIST_MIN_SAMPLES consecutive ticks (the sample
    // floor keeps a stalled loop from mistaking two spikes bracketing a blocked stretch for a
    // sustained overvoltage). All other faults keep their single-sample semantics.
    if (V_bus > LIMIT_V_BUS_MAX) {
        fault_flags |= FAULT_OV_BUS;             // transient indication — not yet a latch
        uint32_t nowMs = millis();
        // A fresh window opens on the first over-sample AND whenever the spacing from the
        // previous over-sample exceeds OV_BUS_MAX_GAP_MS (review F4): sparse samples across a
        // stalled loop must not be credited as a continuous overvoltage.
        if (!ovBusOverActive || (uint32_t)(nowMs - ovBusLastOverMs) > OV_BUS_MAX_GAP_MS) {
            // A gap-abandoned window is still a real unlatched transient — count it (review
            // round 2: the restart must not silently discard the observation).
            if (ovBusOverActive && ovBusTransientCount < 65535u) ovBusTransientCount++;
            ovBusOverActive  = true;
            ovBusOverSince   = nowMs;
            ovBusOverSamples = 0;
        }
        ovBusLastOverMs = nowMs;
        if (ovBusOverSamples < 255u) ovBusOverSamples++;
        if ((uint32_t)(nowMs - ovBusOverSince) >= OV_BUS_PERSIST_MS &&
            ovBusOverSamples >= OV_BUS_PERSIST_MIN_SAMPLES) {
            triggerFault(FAULT_OV_BUS, ERR_OV_BUS);
        }
    } else {
        if (ovBusOverActive) {
            // Window closed without latching — the only externally-visible trace of a
            // sub-persistence park (review F5: the flicker bit can miss every 50Hz telemetry
            // frame and the [FAULT] print is latch-gated). Print at most 1 Hz (review round 2:
            // an alternating over/under sample stream closes a window every other tick — the
            // counter absorbs the rate, the print must not).
            if (ovBusTransientCount < 65535u) ovBusTransientCount++;
            uint32_t nowMs = millis();
            // Suppressed under the State-98 plot stream (the one repeating print outside the
            // profile/watch paths — review 2026-08-07 F1): the counter still increments and is
            // visible via 'S', so the transient is not lost, just not printed mid-plot.
            if (!plotSuppressStatus() &&
                (!ovBusHasPrinted || (uint32_t)(nowMs - ovBusPrintLastMs) >= 1000u)) {
                ovBusHasPrinted  = true;
                ovBusPrintLastMs = nowMs;
                Serial.print("[OV] transient over-limit window(s), latest ~");
                Serial.print(nowMs - ovBusOverSince);
                Serial.print(" ms, no latch; total=");
                Serial.print(ovBusTransientCount);
                Serial.println(" (1Hz-limited report)");
            }
        }
        ovBusOverActive  = false;
        ovBusOverSamples = 0;
    }

    // FAULT_UV_FC — FC-source-rail armed + leaky-dwell filtered (fw v6, 2026-08-12; see the
    // UV_FC_DWELL_LATCH_MS and fcUvArmed rationale at the constants/state blocks). Deliberately
    // OUTSIDE the !BENCH_TEST guard and NOT state-gated, for the same reason as the bus block: the
    // events it exists to catch (WP0096/WP0098 — V_fc under 5 V with the bus still at 15.7 V,
    // ending in an MCU stop) happened in State 98 under BENCH_TEST, where the superseded
    // State-2-gated check was compiled out entirely. ARMING, not a state gate, is what keeps an
    // unrouted or absent fuel cell from tripping it.
    // ORDER MATTERS (fw v6 review S3): this block runs BEFORE the bus block below. triggerFault()
    // latches the FIRST cause only, and a source collapse propagates to the bus — in the WP0096 /
    // WP0098 logs V_fc leads V_bus by ~7 ms, but a same-tick double-cross is possible. Evaluating
    // the source rail first makes the latched error_code name the CAUSE (ERR_UV_FC) rather than
    // the CONSEQUENCE (ERR_UV_BUS). Both blocks' internals are otherwise independent.
    {
        uint32_t nowMs = millis();
        // MATCHED PAIR (S7 discipline): the FC rail is only load-bearing when its own boost is
        // enabled AND its own bus switch is closed. Either open (dark stage, operator 'F', the
        // share loop's own FC cut, State 3/99 teardown) and V_fc is simply an unrouted source —
        // not evidence of anything. The staged bring-up owns its own sags (S3), same as the bus.
        bool fcRouted = (digitalRead(FC_BUS_ENABLE) == HIGH) && (digitalRead(FC_REG_ENABLE) == HIGH);
        if (bringupActive || !fcRouted) {
            // Disarm and DUMP the dwell: a disarmed interval is not evidence of a collapse, and
            // carrying dwell across it would let two unrelated bench sequences add into a latch.
            fcUvArmed       = false;
            fcUvUnderActive = false;
            fcUvDwellMs     = 0.0f;
        } else if (V_fc >= V_FC_ARM_THRESH) {
            // The rail has demonstrably been healthy while routed — from here a collapse below
            // LIMIT_V_FC_MIN is a real source failure, not a boot ramp or a missing source.
            // ARM > TRIP by 1.0 V (C1): arming on the trip limit itself would let one sample of a
            // ramp through 6.0 V arm the filter mid-ramp, and the next dip back under would latch.
            fcUvArmed = true;
        }

        float dtMs = (float)(uint32_t)(nowMs - fcUvLastTickMs);
        if (dtMs > UV_BUS_DWELL_DT_CAP_MS) dtMs = UV_BUS_DWELL_DT_CAP_MS;
        fcUvLastTickMs = nowMs;

        if (fcUvArmed && V_fc < LIMIT_V_FC_MIN) {
            fault_flags |= FAULT_UV_FC;          // transient indication — not yet a latch
            if (!fcUvUnderActive) {
                fcUvUnderActive = true;
                fcUvUnderSince  = nowMs;
            }
            fcUvDwellMs += dtMs;
            if (fcUvDwellMs >= UV_FC_DWELL_LATCH_MS) {
                triggerFault(FAULT_UV_FC, ERR_UV_FC);
            }
        } else {
            if (fcUvUnderActive) {
                // Excursion closed without latching. Counted, and its duration kept for the 'S'
                // dump (fw v6 review S5) — no periodic print: the bus block already owns the 1 Hz
                // "[UV] transient" line, and a second repeating source of the same string would
                // make the two rails indistinguishable in a scrollback.
                if (fcUvTransientCount < 65535u) fcUvTransientCount++;
                fcUvLastExcursionMs = (uint32_t)(nowMs - fcUvUnderSince);
            }
            fcUvUnderActive = false;
            if (fcUvArmed) {
                fcUvDwellMs -= UV_BUS_DWELL_LEAK * dtMs;
                if (fcUvDwellMs < 0.0f) fcUvDwellMs = 0.0f;
            }
        }
    }

    // FAULT_UV_BUS — bus-armed + leaky-dwell filtered (fw v5, 2026-08-12; see the UV_BUS_DWELL_*
    // and uvBusArmed rationale at the constants/state blocks). Deliberately OUTSIDE the
    // !BENCH_TEST guard: the fw v3 validation sweep ran in State 98 under BENCH_TEST, where a
    // sub-9 V bus produced zero fault indication (WP0039, TP0016). Bench collapses are exactly the
    // events this fault exists to catch, so it is armed on the bench too. Arming, not a state
    // gate, is what keeps a dark or ramping power stage from tripping it.
    {
        // MATCHED SOURCE PAIR (S7, fw v5 review — supersedes the two independent ORs). A channel
        // can only hold the bus when ITS OWN switch is closed AND ITS OWN boost is enabled. The
        // fw v4 predicate ANDed two independent ORs, so the mixed topology "FC_BUS closed with the
        // FC boost off, BT boost on with BT_BUS open" read as armed while NO converter was
        // actually feeding the bus — the routine 'F' press in that topology would have latched a
        // spurious UV. Requiring the pair also keeps the original S4 intent (both boosts off ⇒
        // disarmed) as a strict subset.
        bool fcFeeding = (digitalRead(FC_BUS_ENABLE) == HIGH) && (digitalRead(FC_REG_ENABLE) == HIGH);
        bool btFeeding = (digitalRead(BT_BUS_ENABLE) == HIGH) && (digitalRead(BT_REG_ENABLE) == HIGH);
        bool sourceFeeding = fcFeeding || btFeeding;
        // S3 (2026-08-12): the staged bring-up owns its own sags. Its arming threshold margin is
        // only V_BUS_CHARGED_THRESH − LIMIT_V_BUS_MIN = 1.5 V, the documented P3 motor-node
        // connect sags below that, and P3 runs ~30–83 ms — far past UV_BUS_DWELL_LATCH_MS — so an
        // armed UV would latch on a SANCTIONED CSS-controlled connect. Bring-up connects are
        // deliberate; UV coverage targets post-bring-up steady state (the WP0039/TP0016 class of
        // collapse). busBringupTick() has its own per-phase timeouts for a bring-up that fails.
        uint32_t nowMs = millis();
        if (bringupActive || !sourceFeeding) {
            // No matched source pair (dark boot, bring-up P0 entry, State 3/99 teardown, either
            // boost off, or a bring-up in progress): disarm, drop any open excursion, and DUMP the
            // accumulated dwell — a disarmed interval is not evidence of a collapse, and carrying
            // dwell across it would let two unrelated bench sequences add up into a latch.
            uvBusArmed        = false;
            uvBusUnderActive  = false;
            uvBusDwellMs      = 0.0f;
        } else if (V_bus >= V_BUS_CHARGED_THRESH) {
            // The bus has demonstrably come up with a source on it — from here a collapse below
            // LIMIT_V_BUS_MIN is a real loss of source feed, not a bring-up ramp.
            uvBusArmed = true;
        }

        // Dwell dt. millis() resolution quantizes each tick, but the SUM over an excursion is the
        // elapsed under-time regardless, which is all the integrator needs. The cap bounds what a
        // single tick may credit (stalled loop, or a long disarmed gap before re-arming).
        float dtMs = (float)(uint32_t)(nowMs - uvBusLastTickMs);
        if (dtMs > UV_BUS_DWELL_DT_CAP_MS) dtMs = UV_BUS_DWELL_DT_CAP_MS;
        uvBusLastTickMs = nowMs;

        if (uvBusArmed && V_bus < LIMIT_V_BUS_MIN) {
            fault_flags |= FAULT_UV_BUS;         // transient indication — not yet a latch
            // Excursion boundary bookkeeping (transient counter + print only, fw v5): the latch is
            // decided by the accumulated dwell below, which deliberately SURVIVES the gaps between
            // excursions — that survival is the whole fix (TP0053's 9 ms/51 ms duty reset the fw v4
            // window every cycle and never latched).
            if (!uvBusUnderActive) {
                uvBusUnderActive = true;
                uvBusUnderSince  = nowMs;
            }
            uvBusDwellMs += dtMs;
            if (uvBusDwellMs >= UV_BUS_DWELL_LATCH_MS) {
                triggerFault(FAULT_UV_BUS, ERR_UV_BUS);
            }
        } else {
            if (uvBusUnderActive) {
                // Excursion closed without latching — one dropout dip of a limit cycle. Counted
                // (visible via 'S') and printed at most 1 Hz, suppressed under the plot stream,
                // exactly as the OV transient report. NOTE: no dwell is cleared here; a repetitive
                // cycle of such dips is exactly what must still ratchet to a latch.
                if (uvBusTransientCount < 65535u) uvBusTransientCount++;
                if (!plotSuppressStatus() &&
                    (!uvBusHasPrinted || (uint32_t)(nowMs - uvBusPrintLastMs) >= 1000u)) {
                    uvBusHasPrinted  = true;
                    uvBusPrintLastMs = nowMs;
                    Serial.print("[UV] transient under-limit excursion(s), latest ~");
                    Serial.print(nowMs - uvBusUnderSince);
                    Serial.print(" ms, no latch; total=");
                    Serial.print(uvBusTransientCount);
                    Serial.print(", dwell=");
                    Serial.print(uvBusDwellMs, 1);
                    Serial.println(" ms (1Hz-limited report)");
                }
            }
            uvBusUnderActive = false;
            // Leak while the bus is healthy (and only while ARMED — a disarmed stage already had
            // its dwell dumped above, and leaking a zero is a no-op either way).
            if (uvBusArmed) {
                uvBusDwellMs -= UV_BUS_DWELL_LEAK * dtMs;
                if (uvBusDwellMs < 0.0f) uvBusDwellMs = 0.0f;
            }
        }
    }

#if !BENCH_TEST
    // Belt-and-suspenders: assertFcChargeEnable() guard prevents this, but catch it regardless
    if (digitalRead(FC_CHARGE_ENABLE) &&
        (digitalRead(BT_BUS_ENABLE) || digitalRead(REGEN_ENABLE))) {
        triggerFault(FAULT_SWITCH_CONFLICT, ERR_SWITCH_CONFLICT);
    }
#endif

    // -- New fault checks --------------------------------------------------------
    if (V_batt > LIMIT_V_BATT_MAX)  triggerFault(FAULT_OV_BATT, ERR_OV_BATT);

#if !BENCH_TEST
    // (The State-2-gated single-sample V_fc check that lived here was REPLACED 2026-08-12, fw v6,
    // by the FC-rail-armed leaky-dwell check above, which runs in every state and under
    // BENCH_TEST. Its State-2 gate existed only to avoid boot-locking on an unramped rail; the
    // arming term — FC pair closed AND V_fc observed healthy while routed — supersedes it and
    // additionally covers the bench-with-no-fuel-cell case the state gate never did.)
    if (I_batt > LIMIT_I_BT_MAX)    triggerFault(FAULT_OC_BT,   ERR_OC_BT);
    // (The State-2-gated single-sample bus-UV check that lived here was REPLACED 2026-08-12 by the
    // bus-armed, persistence-filtered check above, which runs in every state and under BENCH_TEST.)
#endif

    if (V_rgn > LIMIT_V_RGN_MAX)    triggerFault(FAULT_OV_RGN, ERR_OV_RGN);
    if (V_chg > LIMIT_V_CHG_MAX)    triggerFault(FAULT_OV_CHG, ERR_OV_CHG);

#if !BENCH_TEST
    // Ag105 GENSTAT occupies bits [2:0] ONLY — bit 3 is the MPPT EN/DIS flag, not GENSTAT,
    // so the mask must be 0x07 (matching ag105IsReady()), not 0x0F. Error states per Table 6:
    //   0x05 = OC/Regulation Error, 0x06 = Thermal Shutdown, 0x07 = Timeout Error.
    // 0x04 (Bring-Up Charge) is a NORMAL transient for a deeply-discharged pack and must NOT
    // fault. Gated on ag105DataValid (not raw != 0): GENSTAT 0x00 is a real status (Battery
    // Disconnect), so validity is tracked out-of-band by pollAg105() at 50 Hz.
    // Source: Ag105_Table6_I2C_Status_Byte.json
    uint8_t genstat = ag105_status_raw & 0x07;
    if (ag105DataValid &&
        (genstat == 0x05 || genstat == 0x06 || genstat == 0x07))
        triggerFault(FAULT_CHARGER_STAT, ERR_CHARGER_STAT);
#endif

    // Print only on an actual LATCH (FAULT_ERROR is set exclusively by triggerFault()). A plain
    // fault_flags test would print every tick of a sub-persistence OV_BUS flicker window — at a
    // free-running loop rate that's a UART storm, which itself stalls the loop.
    if (fault_flags & FAULT_ERROR) {
        Serial.print("[FAULT] flags=0x"); Serial.print(fault_flags, HEX);
        Serial.print(" code=0x");         Serial.print(error_code, HEX);
        Serial.print(" (");               Serial.print(errorCodeStr(error_code));
        Serial.print(") from state ");    Serial.println(error_source_state);
    }
}

void checkPiWatchdog() {
    // Watchdog is only meaningful while the Pi is actively commanding the system.
    // States 0, 1, 98, and 99 must not fault due to Pi absence.
    if (mainState != 2 && mainState != 3) return;
    if (!pi_ever_connected) return;
    if (millis() - last_rx_ms > PI_TIMEOUT_MS) {
        triggerFault(FAULT_PI_TIMEOUT, ERR_PI_TIMEOUT);
        Serial.println("Pi timeout — entering error state");
    }
}


// ═════════════════════════════════════════════════════════════════════════════
// UDP COMMUNICATION
// ═════════════════════════════════════════════════════════════════════════════
void receiveCommands() {
    if (!networkUp) return;   // UDP socket not initialized — calling Udp.* would hard-fault
    int packetSize = Udp.parsePacket();
    if (packetSize != 22) return;

    uint8_t buffer[22];
    Udp.read(buffer, 22);

    if (buffer[0] != SYNC_BYTE_RX) return;

    uint8_t checksum = 0;
    for (int i = 1; i < 21; i++) checksum ^= buffer[i];
    if (checksum != buffer[21]) {
        // Suppressed under the State-98 plot stream: with a corrupt Pi link this repeats at the
        // packet rate and would shred the plotter parse (review 2026-08-07 F6). Rarely relevant
        // (plotting is a USB-bench activity, usually USE_ETHERNET=0), but cheap to close.
        if (!plotSuppressStatus())
            Serial.println("Checksum mismatch — packet dropped");
        return;
    }

    int idx = 1;

    uint32_t timestamp;
    memcpy(&timestamp, &buffer[idx], 4); idx += 4;

    uint16_t pkt_counter_Pi;
    memcpy(&pkt_counter_Pi, &buffer[idx], 2); idx += 2;

    // Sanitize the three floats before they reach a controller. The XOR checksum catches most
    // corruption but not all of it, and a bit-pattern that survives it can still decode as NaN/Inf
    // — which would propagate through the motor PI integrator (poisoning it permanently, since
    // NaN + anything = NaN) and into the droop mapping. A rejected field HOLDS its previous value
    // rather than defaulting, so one bad packet degrades to "no update" instead of a step command.
    float v_sp_rx, share_sp_rx, charge_rx;
    memcpy(&v_sp_rx,    &buffer[idx], 4); idx += 4;
    memcpy(&share_sp_rx, &buffer[idx], 4); idx += 4;
    memcpy(&charge_rx,  &buffer[idx], 4); idx += 4;

    if (isfinite(v_sp_rx))     v_setpoint           = constrain(v_sp_rx, -V_SETPOINT_MAX, V_SETPOINT_MAX);
    if (isfinite(share_sp_rx)) power_share_setpoint = constrain(share_sp_rx, 0.0f, 1.0f);
    if (isfinite(charge_rx))   charge_goal          = charge_rx;

    mode_cmd = buffer[idx++];
    uint8_t droop_enable_reserved = buffer[idx++];   // reserved — not yet wired to hardware
    (void)droop_enable_reserved;

    last_rx_ms        = millis();
    pi_ever_connected = true;

    // MODE_HYBRID=0, MODE_FC_ONLY=1, MODE_BATT=2, MODE_CHARGE=3, MODE_SAFE=4
    if (mode_cmd <= 3 && mainState == 1) {
        changeToRun = true;
    }
    if (mode_cmd == 4 && mainState == 2) {
        changeToFin = true;
    }
}

/*
 * Telemetry packet layout — protocol v4, 58 bytes
 * TELEMETRY_VERSION = 4; Pi bridge must match this layout.
 * Change from v3: charger_status (raw Ag105 Table 6 status byte) reinstated at offset 51;
 * switch_state and all following fields shift +1; checksum span extended to bytes 1–56.
 *
 * Offset | Bytes | Field
 * -------|-------|-------
 *  0     |  1    | SYNC 0xAA
 *  1     |  4    | timestamp ms
 *  5     |  2    | pkt_counter_T
 *  7     |  4    | v_actual
 * 11     |  4    | V_batt
 * 15     |  4    | I_batt
 * 19     |  4    | I_charge (from Ag105 I2C reg 0x06 × 0.011)
 * 23     |  4    | V_fc
 * 27     |  4    | I_fc
 * 31     |  4    | V_bus
 * 35     |  4    | V_rgn  (replaces P_motor_actual)
 * 39     |  4    | V_chg  (replaces power_share_echo)
 * 43     |  4    | power_share_actual
 * 47     |  2    | fc_u16 (droop gain, Q16)
 * 49     |  2    | bt_u16 (droop gain, Q16)
 * 51     |  1    | charger_status (raw Ag105 Table 6 byte = ag105_status_raw; Pi decodes
 *        |       |   off / CC(bit6) / CV(bit5) / fault(GENSTAT 0x05–0x07))  [reinstated v4]
 * 52     |  1    | switch_state (bitmask: SW_FC_BUS|SW_BT_BUS|SW_MOT_PWR|SW_REGEN|SW_FC_CHARGE|SW_BT_SEQ)
 * 53     |  2    | fault_flags (uint16_t LE)
 * 55     |  1    | error_code (ErrorCode_t; primary cause of State-99 entry)
 * 56     |  1    | error_source_state (mainState at time of first fault)
 * 57     |  1    | checksum (XOR of bytes 1–56)
 */
void sendTelemetry() {
    if (!networkUp) return;   // UDP socket not initialized — calling Udp.* would hard-fault
    uint8_t packet[58];
    int idx = 0;

    packet[idx++] = SYNC_BYTE_TX;

    uint32_t t = millis();
    memcpy(&packet[idx], &t,             4); idx += 4;
    memcpy(&packet[idx], &pkt_counter_T, 2); idx += 2;

    memcpy(&packet[idx], &v_actual,          4); idx += 4;
    memcpy(&packet[idx], &V_batt,            4); idx += 4;
    memcpy(&packet[idx], &I_batt,            4); idx += 4;
    memcpy(&packet[idx], &I_charge,          4); idx += 4;
    memcpy(&packet[idx], &V_fc,              4); idx += 4;
    memcpy(&packet[idx], &I_fc,              4); idx += 4;
    memcpy(&packet[idx], &V_bus,             4); idx += 4;
    memcpy(&packet[idx], &V_rgn,             4); idx += 4;   // was P_motor_actual
    memcpy(&packet[idx], &V_chg,             4); idx += 4;   // was power_share_echo
    memcpy(&packet[idx], &power_share_actual, 4); idx += 4;

    uint16_t fc_u16 = (uint16_t)(constrain(droop_gain_FC_actual, 0.0f, 1.0f) * 65535.0f);
    uint16_t bt_u16 = (uint16_t)(constrain(droop_gain_BT_actual, 0.0f, 1.0f) * 65535.0f);
    memcpy(&packet[idx], &fc_u16, 2); idx += 2;
    memcpy(&packet[idx], &bt_u16, 2); idx += 2;

    // charger_status (offset 51): raw Ag105 Table 6 status byte, cached at 50 Hz by pollAg105().
    // Pi decodes off/CC/CV/fault — Source: Ag105_Table6_I2C_Status_Byte.json (GENSTAT bits 0–2,
    // CV bit 5, CC bit 6). Reinstated in v4 at its historic v1 offset.
    packet[idx++] = ag105_status_raw;

    uint8_t switch_state = 0;
    if (digitalRead(FC_BUS_ENABLE))      switch_state |= SW_FC_BUS;
    if (digitalRead(BT_BUS_ENABLE))      switch_state |= SW_BT_BUS;
    if (digitalRead(MOT_PWR_ENABLE))     switch_state |= SW_MOT_PWR;
    if (digitalRead(REGEN_ENABLE))       switch_state |= SW_REGEN;
    if (digitalRead(FC_CHARGE_ENABLE))   switch_state |= SW_FC_CHARGE;
    if (digitalRead(BT_SEQUENCE_ENABLE)) switch_state |= SW_BT_SEQ;
    packet[idx++] = switch_state;

    // fault_flags as 2 bytes, little-endian
    memcpy(&packet[idx], &fault_flags, 2); idx += 2;
    packet[idx++] = error_code;
    packet[idx++] = error_source_state;

    // Checksum over bytes 1–56
    uint8_t checksum = 0;
    for (int i = 1; i < 57; i++) checksum ^= packet[i];
    packet[idx++] = checksum;

    Udp.beginPacket(pi_ip, pi_port);
    Udp.write(packet, 58);
    Udp.endPacket();

    pkt_counter_T++;
}


// ═════════════════════════════════════════════════════════════════════════════
// STATE MACHINE
// ═════════════════════════════════════════════════════════════════════════════
// Source-agnostic peripheral init, shared by the bench and production doState0() paths.
static void initControlPeripherals() {
    initMdacOutputs();

    // Charger config is NOT done here. The Ag105 is unpowered in Init (no charger power path is
    // open), so it cannot ACK I2C — configuring it here would always fail. pollAg105() lazily
    // configures it the first time it is powered + settled (see §3/§5).
    ag105Configured = false;

    initEsc();

    digitalWrite(CS_MDAC_FC, HIGH);
    digitalWrite(CS_MDAC_BT, HIGH);
    digitalWrite(ENC_ENABLE, HIGH);
}

void doState0() {
#if BENCH_TEST
    // BENCH bring-up bypass — boot to Idle with the power stage DARK (boosts, bus switches, and
    // BT_SEQUENCE all stay LOW from setup()), and do NOT gate on V_bus.
    //
    // Why: the Teensy is board-powered (LM1084 off VBT). On a current-limited / soft bench supply
    // that can't carry the logic baseline, enabling a boost at boot makes VBT sag, browns out the
    // Teensy, and re-runs this on reboot — motorboating. That was an aggravator; the ROOT CAUSE of
    // the boost deaths was the BT output-cap hot-loop layout (Cout 240 mil from the IC vs FC's
    // 40 mil → SW/VOUT overshoot past the 20V abs-max), found and fixed in hardware 2026-07-07 by
    // bodging 10µF + 0.1µF at the BT boost output (validated: four surviving 'G' bring-ups; see
    // docs/boost-bringup-debug.md). The destructive energy is the boost's own ½·L·di², so a bench
    // current limit does NOT protect it (one boost died at 120mA). Keeping the power stage off at
    // boot still avoids the brownout/motorboating loop on a soft supply. Bring the bus up manually
    // with the State-98 'G' command on a STIFF supply.
    // Production (BENCH_TEST=0) runs the full bring-up + gate below.
    initControlPeripherals();
    Serial.println("State 0 -> State 1 (IDLE) [BENCH_TEST: power stage off; bring up with 'G']");
    mainState = 1;
#else
    // PRODUCTION bring-up — the shared STAGED machine (see the "Staged bring-up" constants block
    // and busBringupTick()). Non-blocking so detectFaults() keeps sampling throughout. A stiff
    // source is assumed present (vehicle battery / fuel cell). Sequence: P0 pre-charge the ~40µF
    // bus alone through the source switches with MOT_PWR held LOW → P1 boosts regulate → P2 dwell
    // confirms stable regulation → P3 connects the motor node (470µF + VESC) from the regulated
    // bus via D-MT-EN's 100nF-CSS soft-start (2026-08-03 doctrine — supersedes the Death-5
    // low-voltage pre-charge, which never functioned on the bench). The motor node then stays
    // energized through Idle/Run (torn down only in State 99). On a gate timeout the machine
    // faults from inside busBringupTick() (FAULT_INIT_FAIL / FAULT_MOT_HOTPLUG) — load-bearing:
    // the State-99 teardown is what extinguishes an invisible parked boost after a failed
    // bring-up.
    if (!bringupActive) busBringupStart();
    BringupStatus st = busBringupTick(true);   // doInit: State 0 owns peripheral init
    if (st == BRINGUP_DONE) {
        Serial.println("State 0 -> State 1 (IDLE)");
        mainState = 1;
    }
    // BRINGUP_FAILED: busBringupTick() already latched State 99 via triggerFault().
#endif
}

void doState1() {
    // IDLE — motor commanded to zero; regen path closed.
    // NOTE (staged bring-up, 2026-08-03 — supersedes the Death-5 low-voltage pre-charge doctrine):
    // MOT_PWR_ENABLE is intentionally NOT forced LOW here. The V-MOT/VESC node is CONNECTED in
    // State-0 phase P3 — from the already-regulated bus, via D-MT-EN's soft-start — and must stay
    // energized (like the bus) so the Idle→Run transition never reconnects it. The motor is held
    // stopped by commandMotorCurrent(0) every Idle tick — NOT by cutting MOT_PWR. (Under BENCH_TEST
    // the power stage boots dark, so MOT_PWR is simply LOW here until a 'G' bring-up energizes it.)
    // A reconnect after teardown ('Q' / State 99) is cheap and guarded (motPwrConnectBlocked()
    // refuses it off a non-regulated bus), so only State 99 tears the motor node down.
    // Rate-gated at the motor period. Idle runs continuously, and an ungated zero-current frame
    // every tick is 9 bytes of UART per tick — the same backpressure that pins the main loop (and
    // detectFaults()) described in the "Control-loop rate limiting" block. 500 Hz keeps the command
    // comfortably fed against the VESC's 1000 ms timeout, and the timeout's own behaviour is to
    // COAST anyway, which for a stopped motor is what a zero command achieves.
    if (rateLimitDue(rl_motor_last, MOTOR_CTRL_PERIOD_US)) commandMotorCurrent(0);
    digitalWrite(REGEN_ENABLE,   LOW);

    // 'S'/'s' toggles a 1 Hz sensor dump on/off while idle
    static bool sensorStream = false;
    static uint32_t lastSensorPrint = 0;

    // Check USB Serial for commands
    if (Serial.available()) {
        char c = (char)Serial.read();
        if (c == 'T' || c == 't') {
            Serial.println("State 1 -> State 98 (TEST)");
            printTestHelp();
            mainState = 98;
            return;
        }
        if (c == 'S' || c == 's') {   // toggle 1 Hz sensor stream
            sensorStream = !sensorStream;
            Serial.println(sensorStream ? "Sensor stream ON (1 Hz)" : "Sensor stream OFF");
            lastSensorPrint = millis() - 1000;  // print immediately on enable
        }
    }

    if (sensorStream && (millis() - lastSensorPrint >= 1000)) {
        lastSensorPrint = millis();
        printSensors();
    }

    if (changeToRun) {
        changeToRun = false;
        Serial.println("State 1 -> State 2 (RUN)");
        // Clear the control rate-limit gates so Run's first tick executes all three controllers
        // immediately rather than waiting out a stale period from a previous run.
        resetControlRateLimiters();
        mainState = 2;
    }
}

void doState2() {
    // RUN — FC and motor paths are on for the whole state (idempotent every tick).
    // BT_BUS_ENABLE is NOT set here: chargingControl() owns it so that it and
    // FC_CHARGE_ENABLE never fight on the same tick. chargingControl() drives
    // BT_BUS_ENABLE HIGH in all non-FC-charge paths and lets assertFcChargeEnable(true)
    // pull it LOW (with the required settling delay) before opening the FC→charger path.
    // share setpoint latch owns this switch — see updateShareSetpointCutoff() (2026-08-12):
    // an unguarded re-assert here re-closed FC_BUS ≤20ms after the latch opened it, while the
    // latch kept powerBalance() frozen and ratio re-entry disabled — both channels back on the
    // bus at the band-edge ratio with every mitigation inoperative (the TP0016/TP0037 condition).
    if (!shareSpCutFC) digitalWrite(FC_BUS_ENABLE, HIGH);    // FC regulator → VBUS always on in Run

    // VBUS → VESC/motor. Normally already HIGH (connected in State-0 P3, kept on through Idle),
    // so this is an idempotent no-op. Under the 2026-08-03 doctrine the guard refuses only when
    // the bus is NOT in its regulation band — i.e. Run was entered on an unregulated bus, which
    // is a real fault (and under BENCH_TEST the only armed catch, UV_BUS being compiled out).
    // If the node is LOW at a REGULATED bus (rare: 'Q'-exit then Run), this now silently starts
    // the sanctioned CSS-controlled connect (~30ms) — benign: the VESC's UVLO + 1000ms command
    // timeout coast it through the ramp.
    if (!assertMotPwrEnable(true)) {
        Serial.println("State 2: MOT_PWR connect refused (bus not in regulation) -> FAULT");
        triggerFault(FAULT_MOT_HOTPLUG, ERR_MOT_HOTPLUG);
        return;
    }

    // Rate-gated (2026-07-29). Call ORDER is unchanged and still matters: the power-path state is
    // committed before the motor/droop outputs change. Each has its own independent period, so
    // chargingControl() no longer runs at the motor rate and motorControl() no longer blocks the
    // loop on UART backpressure. NOTE the pre-existing one-tick lag is unchanged: chargingControl()
    // decides the regen path from `current` as set by the PREVIOUS motorControl() call — with
    // separate periods that lag is now up to one chargingControl() period rather than one tick.
    chargingControlGated();   // power path state committed before motor/droop outputs change
    motorControlGated();
    powerBalanceGated();

    if (changeToFin) {
        changeToFin = false;
        Serial.println("State 2 -> State 3 (FINISH)");
        mainState = 3;
    }
}

void doState3() {
    // FINISH — stop the motor and return to the charged Idle state.
    //
    // The bus is deliberately left ENERGIZED: the boosts and FC_BUS/BT_BUS switches stay ON, so
    // the bus remains at ~16V (nominal) and the next Idle→Run transition never re-hot-plugs the bus
    // (see "VBUS controlled bring-up" note; VBUS itself carries only the ~30–40µF RT1987
    // ceramics — the 470µF bulk cap is on V-MOT). Only State 99 (Error) tears the bus down —
    // and that is latched until a power cycle, which re-runs the State-0 staged bring-up
    // (busBringupTick()).
    //
    // Because the boosts stay enabled, there is NO disabled-converter back-feed hazard here, so the
    // old two-phase cap/regen drain sequence is no longer needed. End-of-run regen harvest already
    // happens through the regen path during Run coast-down (chargingControl()); the ~72mJ of VBUS
    // cap energy is not worth a re-hot-plug every cycle.
    //
    // MOT_PWR_ENABLE (staged bring-up doctrine, 2026-08-03 — supersedes the Death-5 framing): the
    // V-MOT/VESC node is ALSO left energized, for the same reason the bus is — cutting it here
    // would force a re-connect of the 470µF+VESC stack on the next Idle→Run. A reconnect is cheap
    // and CSS-controlled (motPwrConnectBlocked() only permits it off a regulated bus), but there is
    // no reason to pay for it every cycle. The motor is held stopped by commandMotorCurrent(0), not
    // by cutting MOT_PWR. Only State 99 tears the motor node down.
    commandMotorCurrent(0);
    current = 0.0f;
    assertFcChargeEnable(false);           // ensure FC→charger path is closed
    digitalWrite(REGEN_ENABLE, LOW);       // ensure regen path is closed
    digitalWrite(MPPT_DISABLE, LOW);       // inhibit MPPT (active-LOW) until next Run
    // FC_BUS / BT_BUS / MOT_PWR and the boosts intentionally stay ON — bus + motor node remain armed.

    // Clear the wheel-speed averaging buffers so the next run starts fresh (stale timestamps from
    // this run would corrupt the first velocity samples).
    wheelSpeedResetPending = true;

    Serial.println("State 3 -> State 1 (IDLE)");
    mainState = 1;
}

void doState99() {
    // ERROR — non-blocking phased safe shutdown; latched until power cycle.
    // Phase 0 routes residual VBUS energy into the charger (only the ~30–40µF of RT1987
    // ceramics — the 470µF bulk cap is on the V-MOT/regen node, NOT on VBUS; see the
    // corrected "VBUS controlled bring-up" note). Phase 1 bleeds the V-MOT/regen node
    // (470µF cap + motor back-EMF) into the charger through REGEN_ENABLE. Phase 2 closes
    // every path and disables the boosts LAST, so no energized path ever points into a
    // disabled converter (regen-into-disabled-boost hazard, CLAUDE.md §2).
    // Note on phase 1: chargerHasPower() deliberately does not count the REGEN-HIGH /
    // MOT_PWR-LOW combination — it tracks *sustained* input power routed from VBUS, while
    // this drain relies on the V-MOT node's *stored* energy reaching the charger through
    // the regen switch. The disagreement is intentional, not a topology error.
    // Returning between phases (instead of the old delay(10)) keeps detectFaults() sampling
    // live through the drain windows. phase 3 = fully latched (nothing further until power
    // cycle).
    // `phase` lives at file scope (state99Phase) so logDrainTick() can gate its card I/O out of
    // the teardown window — see the drain gate in logDrainTick().
    static uint32_t phaseStart = 0;

    // Always-on 1 Hz error report — keeps printing the latched cause for as long as
    // the board sits in State 99, so the fault is visible even if the entry message
    // scrolled off the serial monitor.
    static uint32_t lastErrPrint = 0;
    if (millis() - lastErrPrint >= 1000) {
        lastErrPrint = millis();
        Serial.print("[STATE 99] error_code=0x"); Serial.print(error_code, HEX);
        Serial.print(" (");                       Serial.print(errorCodeStr(error_code));
        Serial.print(")  fault_flags=0x");        Serial.print(fault_flags, HEX);
        Serial.print("  from state ");            Serial.println(error_source_state);
    }

    switch (state99Phase) {
        case 0:
            commandMotorCurrent(0);
            // Phase 1: Bleed VBUS capacitor energy into charger
            digitalWrite(FC_BUS_ENABLE, LOW);    // disconnect FC regulator from VBUS
            digitalWrite(BT_BUS_ENABLE, LOW);    // disconnect BT regulator from VBUS
            // S7 (2026-08-12): both bus switches are open by state action. assertFcChargeEnable()
            // below clears only the BT pair, so clear the FC pair here too — the post-mortem
            // switch/flag state reported out of State 99 must be truthful.
            shareIsoFC   = false;
            shareSpCutFC = false;
            shareSpCutBT = false;
            assertFcChargeEnable(true);          // drain remaining VBUS cap energy into Ag105
            phaseStart = millis();
            state99Phase = 1;
            break;
        case 1:
            if (millis() - phaseStart < 10) break;   // TODO(calibrate): VBUS capacitor drain time
            // Phase 2: Bleed motor / regen energy
            assertFcChargeEnable(false);         // close FC→charger path (required before REGEN HIGH)
            digitalWrite(REGEN_ENABLE, HIGH);    // open regen → charger path
            digitalWrite(MOT_PWR_ENABLE, LOW);   // cut motor from VBUS; regen bleeds through REGEN
            phaseStart = millis();
            state99Phase = 2;
            break;
        case 2:
            if (millis() - phaseStart < 10) break;   // TODO(calibrate): regen current decay time
            digitalWrite(REGEN_ENABLE, LOW);     // close regen path
            digitalWrite(MPPT_DISABLE, LOW);     // inhibit MPPT (active-LOW)
            // All paths closed — now safe to disable boosts (body-diode back-feed hazard cleared)
            digitalWrite(FC_REG_ENABLE, LOW);
            digitalWrite(BT_REG_ENABLE, LOW);
            // BT_SEQUENCE_ENABLE stays HIGH (per design — no need to turn off again)
            // CBAL_DISABLE stays LOW (OVP protection remains active in error state)
            state99Phase = 3;
            break;
        case 3:
        default:
            break;   // fully shut down; latched until power cycle
    }
}


// ═════════════════════════════════════════════════════════════════════════════
// STATE 98 — HARDWARE EXERCISER (USB serial test mode)
// ═════════════════════════════════════════════════════════════════════════════
// Commands (single uppercase char):
//   F — toggle FC_REG_ENABLE        B — toggle BT_REG_ENABLE
//   1 — toggle FC_BUS_ENABLE        2 — toggle BT_BUS_ENABLE
//   3 — toggle MOT_PWR_ENABLE       4 — toggle REGEN_ENABLE
//   5 — toggle FC_CHARGE_ENABLE     6 — toggle BT_SEQUENCE_ENABLE
//   C — toggle CBAL_DISABLE         M — toggle MPPT_DISABLE
//   D — start/stop drive cycle      T — start/stop trapezoidal current profile
//   Y [Vmax] [b] — start/stop combined drive-cycle + power-share profile (both args optional)
//   W [Imax] [b] — start/stop combined CURRENT + power-share profile (both args optional)
//   U — toggle VESC watch (~2 Hz read-back; WAS 'W' before 2026-08-10)
//   S — print status snapshot
//   K — print SD bench-logger status (card, file, record/drop counts)
//   I — scan I2C bus (lists ACKing addresses; Ag105 expected at 0x30)
//   H/? — print this command list
//   Q — exit → State 1 (MOT_PWR_ENABLE forced LOW)
//
// Safety rules still apply:
//   - FC_CHARGE_ENABLE always goes through assertFcChargeEnable() guard
//   - detectFaults() runs every loop tick; faults latch State 99 as normal
//   - Pi watchdog does not fire in State 98 (checkPiWatchdog() guards on mainState)

// Prints the State 98 command menu. Kept in sync with the command table above and the
// switch() in doState98(). Called on entry to test mode (and reachable via 'H'/'?').
void printTestHelp() {
    Serial.println("=== State 98 TEST commands ===");
    Serial.println("  F - toggle FC_REG_ENABLE     B - toggle BT_REG_ENABLE");
    Serial.println("  1 - toggle FC_BUS_ENABLE*    2 - toggle BT_BUS_ENABLE*");
    Serial.println("  3 - toggle MOT_PWR_ENABLE    4 - toggle REGEN_ENABLE");
    Serial.println("  5 - toggle FC_CHARGE_ENABLE  6 - toggle BT_SEQUENCE_ENABLE");
    Serial.println("  C - toggle CBAL_DISABLE      M - toggle MPPT_DISABLE");
    Serial.println("  G - staged bring-up (bus->boosts->motor node; 'X' aborts)   D - start/stop drive cycle");
    Serial.println("  S - print status snapshot    I - scan I2C bus");
    Serial.println("  E - read VESC FW+telemetry   U - toggle VESC watch (~2Hz, flags faults)");
    Serial.println("      ** the VESC watch MOVED from 'W' to 'U' (\"UART watch\") — 'W' is now a");
    Serial.println("         motor profile below **");
    Serial.println("  -- bench tools (prompt for a value) --");
    Serial.println("  P - set power-share setpoint (closed-loop live)");
    Serial.println("  O - set droop ratio (open-loop direct MDAC write)");
    Serial.println("  A - set manual motor current (A)");
    Serial.println("  V - set manual motor velocity (m/s)");
    Serial.println("  R - start/stop power-share profile (needs A or V set + MOT_PWR on)");
    Serial.println("  T <Imax A> <hold s> <rate A/s> - start trapezoidal current profile");
    Serial.println("      (one line, e.g. \"T 6 5 0.5\"; 'T' alone while running stops it;");
    Serial.println("      direct VESC phase current — no velocity-chain calibration needed)");
    Serial.println("  T <Imax> <hold> <rate> [t,r1,...,rn] - SWEEP: one run per share setpoint r_i,");
    Serial.println("      each to its own TPnnnn.BLG, with t s of motor cool-off between runs");
    Serial.println("      (e.g. \"T 6 3 1 [30,0,0.15,0.3,0.5,0.7,0.85,1]\"; max 16 setpoints;");
    Serial.println("      'T'/'X'/'Q' or any other profile start cancels the rest of the sweep)");
    Serial.println("  Y [Vmax m/s] [b] - start combined drive-cycle + power-share profile");
    Serial.println("      (one line, e.g. \"Y 1 0.3\"; both args optional — bare 'Y' runs the");
    Serial.println("      defaults; 'Y' alone while running stops it; sweeps v_setpoint AND");
    Serial.println("      power_share_setpoint together; needs a calibrated velocity chain +");
    Serial.println("      MOT_PWR on, like 'D'; share clipped to [b, 1-b], 0 <= b < 0.5)");
    Serial.println("  W [Imax A] [b] - start combined CURRENT + power-share profile  (was: VESC watch)");
    Serial.println("      (same 16-region table as 'Y' with the motor axis in AMPS; one line,");
    Serial.print  ("      e.g. \"W 6 0.0\"; both args optional — defaults ");
    Serial.print(W_IMAX_DEFAULT, 1);
    Serial.print("A / b=");
    Serial.print(Y_BOUND_DEFAULT, 2);
    Serial.println("; Imax <=");
    Serial.print  ("      "); Serial.print(TRAP_I_ABS_MAX, 0);
    Serial.println("A; NO velocity-chain calibration needed — direct VESC phase current)");
    Serial.println("  X - universal stop: cancel any running profile + manual motor + share live");
    Serial.println("  L - toggle Serial-Plotter stream (share_sp,share_act,gFC,gBT,ifc,ibt,v_sp,v_act @50Hz)");
    Serial.print  ("      while ON: status/phase lines suppressed; 'R'/'T' arm with a ");
    Serial.print(PLOT_ARM_DELAY_MS);
    Serial.println("ms delay");
    Serial.println("      so you can switch to the plotter window before the run starts");
    Serial.println("      ('D', 'Y' and 'W' are NOT armed — they start immediately; an armed");
    Serial.println("      'R'/'T' is refused over, and cancelled by, a running 'D'/'Y'/'W')");
    Serial.println("  K - SD logger status (auto-logs every R/T/D/Y/W run @1kHz to PS/TP/DC/YP/WP####.BLG)");
    Serial.println("  H - show this command list");
    Serial.println("  * 1/2 refuse ON if the matching boost is ON and VBUS is low (use G);");
    Serial.println("    2 also refuses while FC_CHARGE_ENABLE is HIGH (illegal combination)");
    Serial.println("  Q - exit -> State 1 (MOT_PWR_ENABLE forced LOW)");
    Serial.println("==============================");
}

void doState98() {
    if (Serial.available()) {
        char cmd = (char)Serial.read();
        int  pin;
        bool cur;

        // While awaiting a typed numeric value, route numeric chars (and the line terminator) to
        // the accumulator (non-blocking; detectFaults() keeps running each main-loop tick). A
        // non-numeric char cancels the pending entry and is then handled as a normal command key
        // below — so e.g. pressing 'Q' at a prompt both cancels the prompt and exits.
        bool handleAsCommand = true;
        if (pendingInput != PEND_NONE) {
            // The trapezoid prompt additionally accepts the sweep-list punctuation '[' ',' ']'
            // (2026-08-11). Scoped to PEND_TRAP_PARAMS on purpose: at every other prompt those
            // keys are still meaningless, and the cancel-on-unexpected-key rule is what stops a
            // stray keystroke from being absorbed into a value the operator can't see echoed.
            if (isNumericEntryChar(cmd) || cmd == '\n' || cmd == '\r' ||
                (pendingInput == PEND_TRAP_PARAMS && isSweepListChar(cmd))) {
                handlePendingInputChar(cmd);
                handleAsCommand = false;
            } else {
                pendingInput = PEND_NONE;
                inputBufIdx  = 0;
                Serial.println("(input cancelled)");
            }
        }

        // Power-path topology commands are locked out while the staged bring-up runs
        // (adversarial review 2026-08-03, F1): a mid-phase toggle defeats the machine's
        // sequencing — '3' during P2 would bypass the dwell, 'F'/'B' would re-arm a boost the
        // machine assumes dark, '5' could latch the illegal BT_BUS+FC_CHARGE combination whose
        // fault is compiled out under BENCH_TEST. 'X' (abort), 'Q' (exit, aborts too), 'S', and
        // the read-only keys stay available.
        if (handleAsCommand && bringupActive) {
            switch (cmd) {
                case '1': case '2': case '3': case '4': case '5': case '6':
                case 'F': case 'f': case 'B': case 'b':
                // Motor/droop writers too (review round 2, F1): an 'A'/'V' set mid-bring-up
                // would drive a separately-powered VESC through the sequence; 'P'/'O' write the
                // droop MDACs mid-ramp.
                case 'A': case 'a': case 'V': case 'v':
                case 'P': case 'p': case 'O': case 'o':
                    Serial.println("REFUSED: staged bring-up in progress — abort with 'X' first");
                    handleAsCommand = false;
                    break;
                default:
                    break;
            }
        }

        if (handleAsCommand)
        switch (cmd) {
            case 'F':
            case 'f':
                pin = FC_REG_ENABLE; cur = digitalRead(pin);
                digitalWrite(pin, !cur);
                Serial.print("FC_REG_ENABLE -> "); Serial.println(!cur);
                break;
            case 'B':
            case 'b':
                pin = BT_REG_ENABLE; cur = digitalRead(pin);
                digitalWrite(pin, !cur);
                Serial.print("BT_REG_ENABLE -> "); Serial.println(!cur);
                break;
            case '1':
                // Guard: refuse to hot-plug a running FC boost onto a discharged bus (use 'G').
                cur = digitalRead(FC_BUS_ENABLE);
                if (!cur && busHotPlugUnsafe(FC_REG_ENABLE)) {
                    Serial.println("REFUSED: FC boost is ON and VBUS is low — hot-plug risk. Use 'G' to bring up the bus.");
                } else {
                    digitalWrite(FC_BUS_ENABLE, !cur);
                    shareIsoFC   = false;   // operator owns the switch now — no auto re-entry
                    shareSpCutFC = false;   // and no setpoint latch holding it (2026-08-12):
                                            // the latch would otherwise keep blocking re-entry
                                            // and freezing the share loop after the operator
                                            // has taken the switch back
                    Serial.print("FC_BUS_ENABLE -> "); Serial.println(!cur);
                }
                break;
            case '2':
                // Guards: (a) BT_BUS+FC_CHARGE is the illegal combination from the IO CSV —
                // refuse rather than auto-resolve so the operator stays aware of the path state
                // ('5' via assertFcChargeEnable() is the sanctioned way to swap the paths);
                // (b) refuse to hot-plug a running BT boost onto a discharged bus (use 'G').
                cur = digitalRead(BT_BUS_ENABLE);
                if (!cur && digitalRead(FC_CHARGE_ENABLE)) {
                    Serial.println("REFUSED: FC_CHARGE_ENABLE is HIGH — BT_BUS+FC_CHARGE is illegal. Turn FC_CHARGE off first ('5').");
                } else if (!cur && busHotPlugUnsafe(BT_REG_ENABLE)) {
                    Serial.println("REFUSED: BT boost is ON and VBUS is low — hot-plug risk. Use 'G' to bring up the bus.");
                } else {
                    digitalWrite(BT_BUS_ENABLE, !cur);
                    shareIsoBT   = false;   // operator owns the switch now — no auto re-entry
                    shareSpCutBT = false;   // and no setpoint latch holding it (2026-08-12) —
                                            // mirror of the '1' handler above
                    Serial.print("BT_BUS_ENABLE -> "); Serial.println(!cur);
                }
                break;
            case '3':
                // MOT_PWR via the connect guard: OFF always allowed; ON allowed only from a bus
                // in its regulation band (the CSS-controlled connect — 2026-08-03 doctrine, see
                // motPwrConnectBlocked()). Use 'G' for the full staged bring-up.
                cur = digitalRead(MOT_PWR_ENABLE);
                if (!cur && motPwrConnectBlocked()) {
                    Serial.println("REFUSED: bus not in regulation — motor-node connect is only sanctioned from a regulated bus. Use 'G'.");
                } else {
                    assertMotPwrEnable(!cur);
                    Serial.print("MOT_PWR_ENABLE -> "); Serial.println(!cur);
                }
                break;
            case '4':
                // REGEN_ENABLE: assertFcChargeEnable(false) required before going HIGH
                cur = digitalRead(REGEN_ENABLE);
                if (!cur) {
                    assertFcChargeEnable(false);   // FC_CHARGE must be OFF before REGEN goes HIGH
                }
                digitalWrite(REGEN_ENABLE, !cur);
                Serial.print("REGEN_ENABLE -> "); Serial.println(!cur);
                break;
            case '5':
                // FC_CHARGE_ENABLE: always via guard regardless of direction
                cur = digitalRead(FC_CHARGE_ENABLE);
                assertFcChargeEnable(!cur);
                Serial.print("FC_CHARGE_ENABLE -> "); Serial.println(digitalRead(FC_CHARGE_ENABLE));
                break;
            case '6':
                pin = BT_SEQUENCE_ENABLE; cur = digitalRead(pin);
                digitalWrite(pin, !cur);
                Serial.print("BT_SEQUENCE_ENABLE -> "); Serial.println(!cur);
                break;
            case 'C':
            case 'c':
                pin = CBAL_DISABLE; cur = digitalRead(pin);
                digitalWrite(pin, !cur);
                Serial.print("CBAL_DISABLE -> "); Serial.println(!cur);
                Serial.println((!cur) ? "  WARNING: OVP bypassed" : "  OVP active");
                break;
            case 'M':
            case 'm':
                pin = MPPT_DISABLE; cur = digitalRead(pin);
                digitalWrite(pin, !cur);
                Serial.print("MPPT_DISABLE -> "); Serial.print(!cur);
                Serial.println((!cur) ? " (MPPT enabled/harvesting)" : " (MPPT inhibited)");
                break;
            case 'D':
            case 'd':
                if (!driveCycleActive) {
                    if (bringupActive) {
                        Serial.println("ERROR: bring-up in progress — wait for it or abort with 'X'");
                    } else if (!velocityChainCalibrated()) {
                        printVelocityChainRefusal("drive cycle");
                    } else if (!digitalRead(MOT_PWR_ENABLE)) {
                        Serial.println("ERROR: MOT_PWR_ENABLE must be HIGH before starting drive cycle (key '3')");
                    } else {
                        powerShareProfileActive = false;   // mutually exclusive motor drivers
                        combinedProfileActive   = false;   // ditto — 'Y' drives v_setpoint too
                        wProfileActive          = false;   // ditto — 'W' commands motor current
                        wCmdA                   = 0.0f;
                        // Clear the trapezoid too (pre-existing gap, same class as review
                        // 2026-08-07 F7 in startPowerShareProfile()): without this a 'D' pressed
                        // during a trapezoid left trapProfileActive set but SHADOWED by branch
                        // precedence, and the orphaned trapezoid then resumed with a huge elapsed
                        // time — i.e. instantly past tEnd — the moment the drive cycle stopped.
                        trapProfileActive       = false;
                        trapCmdA                = 0.0f;
                        // ...and any queued sweep with it: the sweep owns the share setpoint and
                        // would fire a trapezoid into this run when its dwell expired.
                        tsweepCancel("superseded by 'D'");
                        // Take exclusive ownership of the motor output. Without this, a manual
                        // current set with 'A' before 'D' survives the whole run and re-asserts
                        // itself the instant the drive cycle ends.
                        haltMotorOutput();
                        resetControlRateLimiters();   // first tick drives immediately
                        resetShareControlState();     // known share-loop state per run (2026-08-11)
                        driveCycleActive     = true;
                        driveCyclePhaseIdx   = 0;
                        driveCyclePhaseStart = millis();
                        driveCycleStatusLast = millis();
                        // Open the SD log AFTER the flags are set, so the very first logged sample
                        // already carries dc_phase = 0 (not LOG_PHASE_NONE). Warns and continues
                        // if there is no card — a run is never gated on logging.
                        logOpenForProfile(LOG_TYPE_DC);
                        Serial.println("[DC] Drive cycle started — Phase 0: Standstill");
                        if (vescWatchActive)
                            Serial.println("[DC] VESC watch paused during the run (production-identical timing); resumes on stop");
                    }
                } else {
                    driveCycleActive = false;
                    // Drive cycle drives the VESC (motorControl runs while active), so the control
                    // block won't execute next tick — flush a zero command immediately or the motor
                    // keeps spinning at the last commanded current. haltMotorOutput() also clears
                    // manualMotorMode, so the standalone branch reached later in THIS SAME
                    // invocation cannot reissue a pre-drive-cycle manual command.
                    haltMotorOutput();
                    safeAllSwitches();   // park path switches so a mid-phase stop leaves nothing latched
                    logRequestClose(LOG_CLOSE_STOP);   // flag only; loop() drains + closes the file
                    Serial.println("[DC] Drive cycle stopped — motor + switches safed");
                }
                break;
            case 'G':
            case 'g':
                // Full staged bring-up (P0 pre-charge → P1 boosts → P2 dwell → P3 motor-node
                // connect), non-blocking: armed here, ticked once per doState98() invocation
                // below (outside the serial block), so it advances with no keys pressed and
                // detectFaults() stays live. Mutually exclusive with the profiles — they drive
                // motor/charge paths and would fight the machine's switch sequencing.
                if (driveCycleActive || powerShareProfileActive || trapProfileActive ||
                    combinedProfileActive || wProfileActive) {
                    Serial.println("[G] REFUSED: a profile is running — stop it first ('X')");
                } else if (!busBringupStart()) {
                    Serial.print("[G] already in progress (phase ");
                    Serial.print(bringupPhase); Serial.println(")");
                } else {
                    // Take motor ownership (adversarial review round 2, F1): a standing manual
                    // 'A'/'V' command would otherwise keep driving a separately-powered VESC
                    // through the bring-up (applyManualMotor() is also suppressed below while
                    // the machine runs, and 'A'/'V'/'P'/'O' are locked out — this clears any
                    // pre-existing mode so it can't resume after DONE either).
                    haltMotorOutput();
                    powerBalanceLive = false;
                    Serial.println("[G] Staged bring-up started (P0 bus pre-charge; 'X' aborts)");
                }
                break;
            case 'S':
            case 's':
                printTestStatus();
                break;
            case 'K':
            case 'k':
                // Read-only status print — deliberately NOT in the bring-up lockout list above
                // (it touches no pin and no card FAT structure; see printSdStatus()).
                printSdStatus();
                break;
            case 'I':
            case 'i':
                scanI2C();
                break;
            case 'E':
            case 'e':
                queryVescInfo();   // one-shot VESC FW version + telemetry + fault code
                break;
            case 'U':
            case 'u':
                // VESC watch. REBOUND from 'W' to 'U' ("UART watch") on 2026-08-10 so 'W' could
                // take the combined current profile — the two shipped profiles 'D'/'R'/'T'/'Y'
                // had already taken every other natural mnemonic. Anything documenting the old
                // binding must say so loudly: an operator with muscle memory now starts a MOTOR
                // PROFILE where they expected a read-only toggle, which is why the 'W' handler
                // prompts for parameters rather than starting anything on the keypress alone.
                vescWatchActive = !vescWatchActive;
                if (vescWatchActive) {
                    lastVescWatchMs = millis();
                    lastVescFault   = 0;
                    Serial.println("VESC watch ON (~2 Hz; flags fault-code changes)");
                } else {
                    Serial.println("VESC watch OFF");
                }
                break;
            case 'P':
            case 'p':
                pendingInput = PEND_POWER_SHARE;
                Serial.print("Enter power-share setpoint 0.01-0.99 (FC share): ");
                // Under plot mode the mid-line cursor would have the next 50 Hz plot line
                // concatenate onto the prompt (one glitched plotter line per prompt — review
                // 2026-08-07 F3). Terminate the line; the typed digits aren't echoed anyway.
                if (plotModeActive) Serial.println();
                break;
            case 'O':
            case 'o':
                pendingInput = PEND_OPEN_DROOP;
                Serial.print("Enter droop ratio 0.15-0.85 (open-loop, direct MDAC): ");
                if (plotModeActive) Serial.println();   // see 'P' — plot-line concat guard
                break;
            case 'A':
            case 'a':
                pendingInput = PEND_MOTOR_CURRENT;
                Serial.print("Enter manual motor current (A): ");
                if (plotModeActive) Serial.println();   // see 'P' — plot-line concat guard
                break;
            case 'V':
            case 'v':
                pendingInput = PEND_MOTOR_VELOCITY;
                Serial.print("Enter manual motor velocity (m/s): ");
                if (plotModeActive) Serial.println();   // see 'P' — plot-line concat guard
                break;
            case 'R':
            case 'r':
                // A pending arm is cancelled by a second 'R', mirroring the running-profile toggle
                // below — otherwise the only way out of a countdown would be the 'X' sledgehammer.
                if (plotArmTarget == PLOT_ARM_SHARE) {
                    cancelPlotArm("'R' pressed again");
                    break;
                }
                if (!powerShareProfileActive) {
                    if (bringupActive) {
                        Serial.println("ERROR: bring-up in progress — wait for it or abort with 'X'");
                    } else if (!digitalRead(MOT_PWR_ENABLE)) {
                        Serial.println("ERROR: MOT_PWR_ENABLE must be HIGH before the power-share profile (key '3')");
                    } else if (manualMotorMode == MOTOR_TEST_OFF) {
                        Serial.println("ERROR: set a constant motor command first ('A' current or 'V' velocity)");
                    } else {
                        if (V_bus < V_BUS_CHARGED_THRESH) {
                            Serial.println("WARN: VBUS is low — bring the bus up ('G') for a meaningful share measurement");
                        }
                        // Plot mode defers the start so the operator can switch to the plotter
                        // window first (see PLOT_ARM_DELAY_MS). The preconditions above are checked
                        // NOW, at the keypress, so a refusal is seen before the window switch —
                        // plotArmTick() only re-checks the mutual-exclusion guards.
                        if (plotModeActive) {
                            // Refuse to arm over a RUNNING profile (review 2026-08-07 F5): the
                            // immediate path's documented takeover ('R' clears 'D') would here
                            // become "arm now, plotArmTick cancels in 5 s" — same keypress,
                            // opposite outcome. Explicit refusal beats a delayed surprise.
                            if (driveCycleActive || trapProfileActive || combinedProfileActive ||
                                wProfileActive) {
                                Serial.println("ERROR: another profile is running — stop it first ('X') before arming under plot mode");
                                break;
                            }
                            cancelPlotArm("superseded by 'R'");   // a pending trapezoid arm must
                                                                  // not vanish without a message
                            plotArmTarget     = PLOT_ARM_SHARE;
                            plotArmDeadlineMs = millis() + PLOT_ARM_DELAY_MS;
                            Serial.print("[PLOT] Power-share profile ARMED — starts in ");
                            Serial.print(PLOT_ARM_DELAY_MS);
                            Serial.println("ms. Switch to the Serial Plotter now ('R' or 'X' cancels)");
                        } else {
                            startPowerShareProfile();
                        }
                    }
                } else {
                    powerShareProfileActive = false;
                    power_share_setpoint    = 0.5f;
                    haltMotorOutput();
                    safeAllSwitches();   // park path switches so a mid-profile stop leaves nothing latched
                    logRequestClose(LOG_CLOSE_STOP);   // flag only; loop() drains + closes the file
                    Serial.println("[PS] Power-share profile stopped — motor + switches safed");
                }
                break;
            case 'T':
            case 't':
                // 'T' is free inside State 98 (the 'T' that ENTERS test mode is consumed by
                // doState1(), so there is no conflict). Toggle semantics mirror 'D'/'R'.
                // A pending plot-mode arm cancels on a second 'T', same as 'R' above.
                if (plotArmTarget == PLOT_ARM_TRAP) {
                    cancelPlotArm("'T' pressed again");
                    break;
                }
                // Between sweep runs (log-wait or cool-down: sweep queued, trapezoid idle) 'T'
                // means "stop the sweep" — the same thing it means while a run is live. Opening
                // the parameter prompt here instead would leave the queued sweep alive behind an
                // innocent-looking prompt, and run k+1 would fire after the operator walked away
                // believing it stopped (review 2026-08-11, toggle-symmetry fix).
                if (tsweepActive && !trapProfileActive) {
                    tsweepCancel("'T' pressed between sweep runs");
                    break;
                }
                if (!trapProfileActive) {
                    if (bringupActive) {
                        Serial.println("ERROR: bring-up in progress — wait for it or abort with 'X'");
                        break;
                    }
                    // Single-line entry: everything after the 'T' on the same line ("T 6 5 0.5")
                    // accumulates into inputBuf (space is a numeric-entry char) and is parsed as
                    // <Imax A> <hold s> <rate A/s> on the newline. No MOT_PWR_ENABLE gate: the VESC
                    // may be bench-powered from a separate supply, and if MOT_PWR is genuinely the
                    // only source, an unpowered VESC simply does nothing — a WARN suffices (same
                    // policy as 'A'). Also deliberately no velocityChainCalibrated() check — this
                    // mode bypasses the velocity PI entirely, which is exactly why it is safe
                    // regardless of the velocity chain's calibration state.
                    if (!digitalRead(MOT_PWR_ENABLE)) {
                        Serial.println("WARN: MOT_PWR_ENABLE is LOW — profile will run, but the motor is unpowered unless the VESC has its own supply (key '3')");
                    }
                    pendingInput = PEND_TRAP_PARAMS;
                    Serial.print("Trapezoid <Imax A> <hold s> <rate A/s> (|Imax| <= ");
                    Serial.print(TRAP_I_ABS_MAX, 0);
                    Serial.print(", negative = braking/regen): ");
                    if (plotModeActive) Serial.println();   // see 'P' — plot-line concat guard
                } else {
                    // Stopping the RUNNING trapezoid stops the whole sweep: 'T' is the operator's
                    // "stop this" key, and a sweep that carried on to run k+1 after it would be
                    // the "operator thinks it stopped but it didn't" trap 'X' exists to prevent.
                    // (Natural completion deliberately does NOT cancel — that is how the sweep
                    // advances.)
                    tsweepCancel("'T' stop");
                    trapProfileActive = false;
                    trapCmdA          = 0.0f;
                    // Flush a zero immediately: this branch clears the active flag, so the runtime
                    // branch below won't execute next tick and the VESC would otherwise hold the
                    // last commanded current until its 1000 ms command timeout coasts it out.
                    // haltMotorOutput() also clears manualMotorMode, so the standalone branch
                    // reached later in THIS SAME invocation cannot reissue a pre-profile manual
                    // command (design-review-2026-07-28.md P0-2 ownership discipline).
                    haltMotorOutput();
                    logRequestClose(LOG_CLOSE_STOP);   // flag only; loop() drains + closes the file
                    // Deliberately NO safeAllSwitches() here (unlike 'D'/'R'). Those profiles sweep
                    // the charge/regen paths themselves, so parking the switches restores a known
                    // state; the trapezoid never touches a path switch — the operator's configured
                    // paths are an input to the test. Tearing them down on every stop would also
                    // drop the motor-node connection (staged bring-up P3), forcing a full 'G'
                    // bring-up between back-to-back runs. The motor is zeroed, which is the
                    // safety-relevant part.
                    Serial.println("[TP] Trapezoid stopped — motor zeroed (path switches left as-is)");
                }
                break;
            case 'Y':
            case 'y':
                if (!combinedProfileActive) {
                    // Same three preconditions as 'D' — this profile closes the velocity loop
                    // exactly as the drive cycle does, so it inherits the drive cycle's gates
                    // verbatim (an under-reading v_actual makes the motor PI over-drive; see
                    // printVelocityChainRefusal()).
                    if (bringupActive) {
                        Serial.println("ERROR: bring-up in progress — wait for it or abort with 'X'");
                    } else if (!velocityChainCalibrated()) {
                        printVelocityChainRefusal("combined profile");
                    } else if (!digitalRead(MOT_PWR_ENABLE)) {
                        Serial.println("ERROR: MOT_PWR_ENABLE must be HIGH before starting the combined profile (key '3')");
                    } else {
                        // Single-line entry, same mechanism as 'T': everything after the 'Y' on
                        // the same line ("Y 1 0.3") accumulates into inputBuf and is parsed on
                        // the newline. BOTH values are optional — a bare "Y" + newline runs the
                        // defaults. The preconditions above are checked HERE and deliberately not
                        // re-checked at parse time: while the prompt is pending, only
                        // digits/sign/point/space reach the buffer and every other key cancels
                        // the entry outright, so no command can toggle MOT_PWR_ENABLE ('3' is
                        // swallowed as input) or arm a bring-up ('G' cancels first) in the
                        // window between this check and the start.
                        pendingInput = PEND_Y_PARAMS;
                        Serial.print("Combined profile [Vmax m/s] [share bound b] (both optional; defaults ");
                        Serial.print(Y_VMAX_DEFAULT, 2);
                        Serial.print(" ");
                        Serial.print(Y_BOUND_DEFAULT, 2);
                        Serial.print("; Vmax <= ");
                        Serial.print(MANUAL_MOTOR_V_MAX, 1);
                        Serial.print(", 0 <= b < 0.5): ");
                        if (plotModeActive) Serial.println();   // see 'P' — plot-line concat guard
                    }
                } else {
                    combinedProfileActive = false;
                    power_share_setpoint  = 0.5f;   // same reset as the 'R' stop path
                    // Flush a zero immediately: clearing the flag means the runtime branch below
                    // won't execute next tick, and the VESC would otherwise hold the last
                    // commanded current until its 1000 ms command timeout coasts it out.
                    // haltMotorOutput() also clears manualMotorMode so the standalone branch
                    // reached later in THIS SAME invocation cannot reissue a pre-profile command.
                    haltMotorOutput();
                    // Park the path switches (same policy as the 'D'/'R' stop paths). NOT because
                    // this profile runs chargingControl() — it deliberately does not (see the
                    // spine branch) — but because it SWEEPS the share across the full band, and
                    // since 2026-08-10 that band's extremes actuate the bus switches directly
                    // (applyShareRatio() channel cutoff). The run therefore owns the source
                    // topology while it is live, so a mid-region stop must leave a known state.
                    safeAllSwitches();
                    logRequestClose(LOG_CLOSE_STOP);   // flag only; loop() drains + closes the file
                    Serial.println("[YP] Combined profile stopped — motor + switches safed");
                }
                break;
            case 'W':
            case 'w':
                // 'W' was the VESC-watch toggle until 2026-08-10; it is now the combined CURRENT
                // profile and the watch moved to 'U'. Nothing starts on this keypress alone — it
                // opens a parameter prompt — so an operator reaching for the old binding gets a
                // prompt they can cancel, not a running motor.
                if (!wProfileActive) {
                    if (bringupActive) {
                        Serial.println("ERROR: bring-up in progress — wait for it or abort with 'X'");
                    } else {
                        // 'T' conventions, NOT 'Y' conventions: no velocityChainCalibrated() gate
                        // (this profile bypasses the velocity PI entirely, which is exactly why it
                        // is safe on an encoder-less bench) and MOT_PWR_ENABLE is warn-only (the
                        // VESC may be fed from a separate bench supply; if MOT_PWR really is its
                        // only source, an unpowered VESC simply ignores the commands).
                        if (!digitalRead(MOT_PWR_ENABLE)) {
                            Serial.println("WARN: MOT_PWR_ENABLE is LOW — profile will run, but the motor is unpowered unless the VESC has its own supply (key '3')");
                        }
                        pendingInput = PEND_W_PARAMS;
                        Serial.print("Combined current profile [Imax A] [share bound b] (both optional; defaults ");
                        Serial.print(W_IMAX_DEFAULT, 2);
                        Serial.print(" ");
                        Serial.print(Y_BOUND_DEFAULT, 2);
                        Serial.print("; Imax <= ");
                        Serial.print(TRAP_I_ABS_MAX, 0);
                        Serial.print(", 0 <= b < 0.5): ");
                        if (plotModeActive) Serial.println();   // see 'P' — plot-line concat guard
                    }
                } else {
                    wProfileActive       = false;
                    wCmdA                = 0.0f;
                    power_share_setpoint = 0.5f;   // same reset as the 'R'/'Y' stop paths
                    // Flush a zero immediately: clearing the flag means the runtime branch below
                    // won't execute next tick, and the VESC would otherwise hold the last
                    // commanded current until its 1000 ms command timeout coasts it out.
                    haltMotorOutput();
                    // safeAllSwitches() follows the 'Y'/'R' SHARE-profile convention rather than
                    // the 'T' trapezoid's leave-them-alone rule, even though the motor axis is
                    // current-mode like 'T'. The deciding factor is the OTHER axis: this profile
                    // sweeps power_share_setpoint across the full band, so the bus/source
                    // configuration is something the run manipulates, not a static operator input
                    // to preserve — parking it is what leaves a known state behind.
                    safeAllSwitches();
                    logRequestClose(LOG_CLOSE_STOP);   // flag only; loop() drains + closes the file
                    Serial.println("[WP] Combined current profile stopped — motor + switches safed");
                }
                break;
            case 'X':
            case 'x': {
                // Universal motor stop: halts the manual modes AND any running profile. Without
                // the profile clears, X only zeroed the motor for one tick — an active profile
                // re-commanded current on the very next doState98() invocation, which is exactly
                // the "operator thinks the motor is stopped but it isn't" trap the key exists to
                // prevent. Each profile's own stop semantics are mirrored: the drive cycle and
                // share profile park the path switches on stop ('D'/'R'), the trapezoid leaves
                // them as-is (its documented design choice — see 'T'), so switches are parked
                // only if one of the first two was running.
                // Cancelled FIRST so its "(after run k/N)" line prints above the stop banners and
                // so the setpoint it parks (0.5) is not re-parked twice with different reasons.
                // Note the sweep between runs has NO profile flag set, so the switch-parking
                // decision below is unaffected — a sweep is a trapezoid sequence and inherits the
                // trapezoid's "switches left as-is" semantics.
                tsweepCancel("universal stop");
                bool hadDC = driveCycleActive;
                bool hadPS = powerShareProfileActive;
                bool hadTP = trapProfileActive;
                bool hadY  = combinedProfileActive;   // parks switches like 'D'/'R' (it sweeps
                                                      // the charge/regen paths the same way)
                bool hadW  = wProfileActive;          // ditto — its share axis moves the same way
                busBringupAbort();   // no-op if idle; else darkens the stage (a mid-P1 SCP-cut
                                     // park is invisible to the ADC — merely stopping won't do)
                // An ARMED (not yet started) profile must die here too: 'X' exists so the operator
                // can be certain nothing will drive the motor, and a pending countdown would
                // otherwise fire a profile seconds AFTER the stop key was pressed.
                cancelPlotArm("universal stop");
                driveCycleActive        = false;
                powerShareProfileActive = false;
                trapProfileActive       = false;
                combinedProfileActive   = false;
                wProfileActive          = false;
                trapCmdA                = 0.0f;
                wCmdA                   = 0.0f;
                if (hadPS || hadY || hadW) power_share_setpoint = 0.5f;   // same reset as the 'R'/'Y'/'W' stop paths
                haltMotorOutput();
                powerBalanceLive = false;
                logRequestClose(LOG_CLOSE_X);   // flag only; loop() drains + closes the file
                if (hadDC || hadPS || hadY || hadW) safeAllSwitches();
                if (hadDC || hadPS || hadTP || hadY || hadW)
                    Serial.println("Universal stop: profile cancelled + motor zeroed");
                Serial.println((hadDC || hadPS || hadY || hadW)
                    ? "Manual motor + power-share live stopped (switches safed)"
                    : "Manual motor + power-share live stopped (motor zeroed)");
                break;
            }
            case 'L':
            case 'l':
                plotModeActive = !plotModeActive;
                if (plotModeActive) {
                    plotLastMs = millis() - PLOT_PERIOD_MS;   // stream on the very next tick
                    Serial.println("[PLOT] Serial-Plotter stream ON @50Hz — share_sp,share_act,gFC,gBT,ifc,ibt,v_sp,v_act");
                    Serial.print  ("[PLOT] status/phase lines suppressed; 'R'/'T' now arm with a ");
                    Serial.print(PLOT_ARM_DELAY_MS);
                    Serial.println("ms delay");
                    if (vescWatchActive)
                        Serial.println("[PLOT] 'U' VESC watch output suppressed while plotting (faults latch; re-check after 'L')");
                } else {
                    cancelPlotArm("plot mode turned off");
                    Serial.println("[PLOT] Serial-Plotter stream OFF");
                }
                break;
            case 'H':
            case 'h':
            case '?':
                printTestHelp();
                break;
            case 'Q':
            case 'q':
                tsweepCancel("State 98 exit");   // no queued run may survive into Idle
                driveCycleActive        = false;
                powerShareProfileActive = false;
                trapProfileActive       = false;   // no motor driver survives the exit
                combinedProfileActive   = false;
                wProfileActive          = false;
                trapCmdA                = 0.0f;
                wCmdA                   = 0.0f;
                powerBalanceLive        = false;
                vescWatchActive         = false;   // stop the blocking poll from running outside State 98
                pendingInput            = PEND_NONE;   // also drops a half-typed trapezoid line
                inputBufIdx             = 0;
                cancelPlotArm("State 98 exit");     // no armed profile may survive into Idle
                plotModeActive          = false;    // the stream is a State-98 tool only
                logRequestClose(LOG_CLOSE_Q);       // flag only — the file is NOT lost on exit:
                                                    // logDrainTick() lives in loop(), so it keeps
                                                    // draining and closes it from Idle
                busBringupAbort();                 // a mid-bring-up exit must darken the stage —
                                                   // Idle would neither tick the gates nor see a
                                                   // cut-park (invisible to the ADC)
                haltMotorOutput();                 // stop motor before cutting its power
                digitalWrite(MOT_PWR_ENABLE, LOW);   // forced LOW on exit (per spec)
                // Close the charge/regen paths too — doState1() re-clears MOT_PWR/REGEN each
                // tick but never touches FC_CHARGE, so an operator-latched FC_CHARGE would
                // otherwise keep the charger powered through Idle indefinitely (and under
                // BENCH_TEST the switch-conflict fault that would catch a lingering illegal
                // combination is compiled out).
                assertFcChargeEnable(false);
                digitalWrite(REGEN_ENABLE, LOW);
                Serial.println("State 98 -> State 1 (IDLE)");
                mainState = 1;
                return;
            default:
                break;
        }
    }

    // Staged bring-up tick — OUTSIDE the serial block so the machine advances with no keys
    // pressed (one tick per doState98() invocation, same pattern as the profile blocks below).
    // Mutually exclusive with the profiles via the 'G'/'D'/'R'/'T' interlocks. On FAILED the
    // machine has already latched State 99 via triggerFault(); no handling needed here.
    if (bringupActive) {
        if (busBringupTick(false) == BRINGUP_DONE) {   // State 98: peripherals already live
            Serial.print("[G] Bring-up complete: V_bus=");
            Serial.print(V_bus);
            Serial.print("V, V_rgn=");
            Serial.print(V_rgn);
            Serial.println("V ('S' for full status)");
        }
    }

    // Armed-profile tick — BEFORE the profile branches so a run that fires this tick executes
    // immediately rather than idling one full invocation. ORDERING IS LOAD-BEARING (review
    // 2026-08-07): busBringupTick() above can latch State 99 in this same invocation AFTER
    // clearing bringupActive, which this tick's guard would then not see — safe only because an
    // arm and a bring-up can never coexist past one tick ('R'/'T' are refused while
    // bringupActive, and a 'G' pressed during a countdown cancels the arm in the same
    // invocation, since the serial block runs before both ticks). Do not reorder these without
    // re-deriving that argument.
    plotArmTick();

    // Trapezoid sweep sequencer — immediately after the armed-profile tick and for the same
    // reason: a run that fires this tick then executes in this same invocation instead of idling
    // one. Ordering against plotArmTick() is not load-bearing (a sweep and a plot arm are mutually
    // exclusive: the sweep list is refused under plot mode, and a plain 'T' line that would arm
    // cancels any running sweep first), but keeping the two ticks adjacent keeps that argument
    // in one place.
    tsweepTick();

    if (driveCycleActive) {
        // advanceDriveCycle() only supplies v_setpoint; the real Run-state control functions
        // execute unmodified so the exerciser drives the VESC, droop MDACs, and charger paths
        // exactly as State 2 would. Same call order as doState2(). (CLAUDE.md §8.)
        advanceDriveCycle();
        // advanceDriveCycle() clears driveCycleActive on natural completion and zeroes the motor
        // itself. Re-checking the flag keeps motorControl() from running in that same tick and
        // undoing the flush: the error would be (0 − v_actual), i.e. NEGATIVE while the flywheel
        // is still spinning down, so the "completed" drive cycle would command regen current.
        if (driveCycleActive) {
            // Same rate gating and same call order as doState2(), so the exerciser keeps
            // production-identical timing (CLAUDE.md §8).
            chargingControlGated();
            motorControlGated();
            powerBalanceGated();
        }
    } else if (combinedProfileActive) {
        // Combined drive-cycle + power-share profile: supplies BOTH v_setpoint and
        // power_share_setpoint from one region table, then runs the motor + droop halves of the
        // control stack in the same order as the drive-cycle branch above (it commands velocity,
        // so unlike 'R' it needs motorControl()). The charging manager is deliberately excluded —
        // see the comment inside the branch.
        advanceCombinedProfile();
        // Re-check the flag for exactly the drive cycle's reason: advanceCombinedProfile() clears
        // it and zeroes the motor on natural completion, and letting motorControl() run in that
        // same tick would undo the flush with a NEGATIVE error (0 − v_actual) while the flywheel
        // is still spinning down — i.e. a "completed" profile commanding regen current.
        if (combinedProfileActive) {
            // Deliberately NO chargingControl() — same omission as the power-share profile, and
            // here it is load-bearing rather than merely tidy. This profile SWEEPS
            // power_share_setpoint in order to MEASURE the share axis; with charge_goal > 0 the
            // cruise branch of chargingControl() calls assertFcChargeEnable(true), whose guard
            // drives BT_BUS_ENABLE LOW. That takes the battery off the bus mid-run: I_batt → 0,
            // the measured share pins at 1.0, and every share datapoint after that instant is
            // garbage. The regen that the coast-down regions (R14/R15) produce is absorbed by the
            // hardware TL431/BSP170P braking chopper, which is not under firmware control — the
            // same way the 'R' and 'T' profiles handle it. The charge/regen paths therefore stay
            // static under operator control for the whole run.
            motorControlGated();
            powerBalanceGated();
        }
    } else if (wProfileActive) {
        // Combined CURRENT + power-share profile: walks the same region table as 'Y', but the
        // motor axis is commanded current, so this branch mirrors the TRAPEZOID's call set —
        // advanceCurrentComboProfile() issues the current itself (through the rate-gated
        // commandMotorCurrentLimited() chokepoint) and only the droop loop runs alongside. No
        // motorControlGated(): the velocity PI is never in this loop, which is what makes the
        // profile usable on an encoder-less bench.
        advanceCurrentComboProfile();
        // Safe to call powerBalanceGated() unconditionally after a natural completion, for the
        // trapezoid's reason: powerBalance() only writes the droop MDACs, never the motor output,
        // so it cannot undo the completion's zero flush (contrast 'Y'/'D', which must re-check
        // their flag because motorControl() would re-command).
        //
        // Deliberately NO chargingControl() — the same load-bearing omission as the 'Y' and 'R'
        // branches. This profile SWEEPS power_share_setpoint in order to MEASURE the share axis;
        // with charge_goal > 0 the cruise branch of chargingControl() calls
        // assertFcChargeEnable(true), whose guard drives BT_BUS_ENABLE LOW. That takes the battery
        // off the bus mid-run: I_batt → 0, the measured share pins at 1.0, and every share
        // datapoint after that instant is garbage. Coast-down regen is absorbed by the hardware
        // TL431/BSP170P braking chopper, which is not under firmware control.
        powerBalanceGated();
    } else if (powerShareProfileActive) {
        // Power-share profile: sweep power_share_setpoint while the motor is held at a constant
        // command, then let the closed-loop powerBalance() track it. Deliberately does NOT call
        // chargingControl() (unlike the drive cycle) — the regen/FC-charge paths are left static
        // under operator control so the only varying input is the droop split, for a clean share
        // measurement.
        advancePowerShareProfile();
        applyManualMotor();
        powerBalanceGated();
    } else if (trapProfileActive) {
        // Trapezoidal current profile: advanceTrapProfile() computes the commanded current from
        // elapsed time and issues it via commandMotorCurrent() (rate-gated on rl_motor_last, the
        // same gate motorControl()/applyManualMotor() use, so two writers can never collide in one
        // tick). Mutually exclusive with the drive cycle and the share profile by construction —
        // startTrapProfile() clears both flags and takes motor ownership via haltMotorOutput().
        advanceTrapProfile();
        // Run the closed droop loop alongside: the power-draw half of this test is watching how the
        // FC/BT share tracks while the motor current ramps. Safe to call unconditionally after a
        // natural completion — powerBalance() only writes the droop MDACs, never the motor output,
        // so it cannot undo advanceTrapProfile()'s zero flush (contrast the drive cycle, which must
        // re-check its flag because motorControl() would re-command).
        // Deliberately NO chargingControl() — same rationale as the power-share profile: the
        // regen/FC-charge paths stay static under operator control so the only varying input is the
        // motor current.
        powerBalanceGated();
    } else if (!bringupActive) {
        // Standalone manual modes (no profile AND no bring-up running — review round 2, F1: a
        // standing manual command must not drive a separately-powered VESC mid-sequence; 'G'
        // also haltMotorOutput()s on arm, so this gate is belt-and-suspenders).
        // Hold the motor and/or run the closed-loop
        // share controller at the operator-set setpoint. applyManualMotor() is NOT rate-gated in
        // MOTOR_TEST_CURRENT: it re-sends a CONSTANT operator-set current, and the VESC's own
        // command timeout (1000 ms, and it COASTS rather than brakes on expiry) means the bench
        // needs a steady keep-alive. Its VELOCITY branch is different: it goes through
        // motorControlGated(), so it shares rl_motor_last with every other motor writer and the two
        // can never both write the VESC in one tick — the same shared-rate-gate discipline the
        // profile branches above rely on.
        if (manualMotorMode != MOTOR_TEST_OFF) applyManualMotor();
        if (powerBalanceLive)                  powerBalanceGated();
    }

    // SD bench log sample — AFTER the profile branches so each record reflects the state produced
    // by THIS tick's control action (same rationale as plotTick()'s placement), and before the
    // blocking-ish VESC watch so the 1 kHz cadence isn't skewed by a 100 ms UART timeout. Rate-gated
    // internally on rl_log_last / POWER_BAL_PERIOD_US; a memcpy only — no card I/O here.
    logSampleTick();

    // VESC read-back watch: runs regardless of which motor driver (if any) is active, so a fault
    // can be caught whether it trips under the drive cycle, the share profile, or a manual command.
    pollVescWatch();

    // Serial-plotter stream — last, so each line reflects the state AFTER this tick's control
    // action, and outside every branch so the baseline keeps streaming with no profile running
    // (that idle baseline is what the operator watches while the arming countdown elapses).
    plotTick();
}

void advanceDriveCycle() {
    if (driveCyclePhaseIdx >= DRIVE_CYCLE_PHASES) {
        driveCycleActive = false;
        // Natural completion must release the motor exactly as the 'D' stop path does. Previously
        // it only cleared v_setpoint + the active flag: no zero was ever flushed, and any
        // manualMotorMode set before the run resumed driving the motor on the next tick.
        // (design-review-2026-07-28.md P0-2 — symmetric with advancePowerShareProfile().)
        haltMotorOutput();
        logRequestClose(LOG_CLOSE_COMPLETE);   // symmetric with the 'D' stop path — a natural
                                               // completion must close the file too
        Serial.println("[DC] Drive cycle complete — motor zeroed");
        return;
    }

    uint32_t elapsed = millis() - driveCyclePhaseStart;
    const DriveCyclePhase &ph = DRIVE_CYCLE[driveCyclePhaseIdx];

    if (elapsed >= ph.durationMs) {
        driveCyclePhaseIdx++;
        driveCyclePhaseStart = millis();
        if (driveCyclePhaseIdx < DRIVE_CYCLE_PHASES && !plotSuppressStatus()) {
            Serial.print("[DC] Phase "); Serial.println(driveCyclePhaseIdx);
        }
        return;
    }

    // Linear interpolation of v_setpoint within phase
    float t = (float)elapsed / (float)ph.durationMs;
    v_setpoint = ph.v_start + t * (ph.v_end - ph.v_start);

    // Status snapshot every 500 ms (withheld under plot mode — see plotSuppressStatus())
    if (!plotSuppressStatus() && millis() - driveCycleStatusLast >= 500) {
        driveCycleStatusLast = millis();
        Serial.print("[DC] t="); Serial.print(millis());
        Serial.print(" v_sp="); Serial.print(v_setpoint, 2);
        Serial.print(" v_act="); Serial.print(v_actual, 2);
        Serial.print(" V_bus="); Serial.print(V_bus, 2);
        Serial.print(" I_fc="); Serial.print(I_fc, 2);
        Serial.print(" I_bt="); Serial.print(I_batt, 2);
        Serial.print(" I_chg="); Serial.print(I_charge, 3);
        Serial.print(" FLT=0x"); Serial.println(fault_flags, HEX);
    }
}

// ── State 98 bench-tool helpers ───────────────────────────────────────────────────────────────

// True when a human-readable periodic line must be withheld to keep the plotter stream parseable.
// Deliberately a function, not a raw `plotModeActive` read at each call site: the suppression rule
// is one policy in one place, so a future second consumer (a CSV logger, say) changes it once.
bool plotSuppressStatus() {
    return plotModeActive;
}

// One condensed plotter line. Eight fields, ALWAYS eight — the Arduino plotter keys its series off
// the labels and a varying field count re-legends the graph mid-run. `share_act` is the measured share
// powerBalance() computes; with no current flowing the share is undefined and reported as 0 (same
// convention as the '[PS]' status line), which reads as a flat trace until the motor draws.
void plotTick() {
    if (!plotModeActive) return;
    if ((uint32_t)(millis() - plotLastMs) < PLOT_PERIOD_MS) return;
    // Backpressure guard (review 2026-08-07 F4): Teensy USB-CDC write() BLOCKS when the host is
    // enumerated but not draining (monitor closed mid-run, host hiccup). A stalled plot print
    // would freeze the whole loop — including detectFaults() — while a profile drives the motor.
    // Drop the sample instead; the stream self-heals when the host drains. ~110 B covers one line
    // (raised from 80 with the fw v7 v_sp/v_act fields and the longer share_sp/share_act labels).
    if (Serial.availableForWrite() < 110) return;
    // Note: stamping millis() (not += PLOT_PERIOD_MS) means the real interval is period +
    // loop-jitter, i.e. the stream drifts slightly slow. Fine for a plotter (no timestamps on
    // the wire); do not use this cadence for anything that integrates over time.
    plotLastMs = millis();

    float totalA = fabsf(I_fc) + fabsf(I_batt);
    float act    = (totalA > 1e-6f) ? (fabsf(I_fc) / totalA) : 0.0f;

    Serial.print("share_sp:");    Serial.print(power_share_setpoint, 3);
    Serial.print(",share_act:");  Serial.print(act, 3);
    Serial.print(",gFC:");        Serial.print(droop_gain_FC_actual, 3);
    Serial.print(",gBT:");        Serial.print(droop_gain_BT_actual, 3);
    Serial.print(",ifc:");        Serial.print(I_fc, 3);
    Serial.print(",ibt:");        Serial.print(I_batt, 3);
    Serial.print(",v_sp:");       Serial.print(v_setpoint, 3);
    Serial.print(",v_act:");      Serial.println(v_actual, 3);
}

// Drop a pending armed start. Safe to call unconditionally (no-op when nothing is armed) so every
// stop path can invoke it without first testing — which is exactly how 'X'/'Q' avoid the bug where
// a countdown outlives the key that was supposed to stop everything.
void cancelPlotArm(const char *why) {
    if (plotArmTarget == PLOT_ARM_NONE) return;
    plotArmTarget = PLOT_ARM_NONE;
    Serial.print("[PLOT] Armed profile cancelled (");
    Serial.print(why);
    Serial.println(")");
}

// Fire an armed profile once its delay has elapsed. Re-checks the mutual-exclusion guards rather
// than trusting the state captured at arm time: between the keypress and the deadline the operator
// can have started a bring-up ('G') or another profile, and firing into either would stomp a
// running sequence (startPowerShareProfile() clears driveCycleActive outright).
void plotArmTick() {
    if (plotArmTarget == PLOT_ARM_NONE) return;

    if (bringupActive || driveCycleActive || powerShareProfileActive || trapProfileActive ||
        combinedProfileActive || wProfileActive) {
        cancelPlotArm("another run started during the arming delay");
        return;
    }
    // The share profile's preconditions are re-checked at FIRE time, not just at the keypress: the
    // arming window is seconds long and the operator can press '3' (MOT_PWR OFF) inside it, which
    // would otherwise start a run against a gate that no longer holds. Not a hardware hazard (this
    // profile touches no path switch) but a silently-bypassed precondition is exactly the class of
    // thing that makes a bench measurement wrong without looking wrong. The trapezoid has no such
    // gate by design (separate-VESC-supply case — see 'T'), so it fires unconditionally.
    if (plotArmTarget == PLOT_ARM_SHARE &&
        (!digitalRead(MOT_PWR_ENABLE) || manualMotorMode == MOTOR_TEST_OFF)) {
        cancelPlotArm("preconditions no longer met (MOT_PWR or motor command changed)");
        return;
    }
    if ((int32_t)(millis() - plotArmDeadlineMs) < 0) return;

    PlotArmTarget target = plotArmTarget;
    plotArmTarget = PLOT_ARM_NONE;   // cleared BEFORE the start call so the start path cannot re-arm
    if (target == PLOT_ARM_SHARE) startPowerShareProfile();
    else                          startTrapProfile(plotArmTrapImax, plotArmTrapHoldMs, plotArmTrapRate);
}

// Commit the power-share profile. Extracted from the 'R' handler so the immediate path and the
// plot-mode armed path start the run identically — the arming delay must not become a second,
// subtly different start sequence. Preconditions (MOT_PWR, a manual motor command) are the caller's
// responsibility: 'R' checks them at the keypress so a refusal is seen before the window switch.
void startPowerShareProfile() {
    driveCycleActive            = false;   // mutually exclusive motor drivers
    // Clear the trapezoid too (review 2026-08-07 F7, pre-existing gap in the old 'R' block):
    // without this an 'R' during a trapezoid left trapProfileActive set but shadowed by branch
    // precedence — the orphaned trapezoid then resumed with a huge elapsed time when the share
    // profile stopped. Mirrors startTrapProfile()'s symmetric clears.
    trapProfileActive           = false;
    trapCmdA                    = 0.0f;
    tsweepCancel("superseded by 'R'");     // a queued sweep would fire a trapezoid into this run
                                           // when its dwell expired, and it owns the setpoint
    combinedProfileActive       = false;   // same rationale — a shadowed 'Y' would resume with a
                                           // huge elapsed time when this profile stopped
    wProfileActive              = false;   // ditto for the current-mode twin
    wCmdA                       = 0.0f;
    resetControlRateLimiters();   // first tick drives immediately
    resetShareControlState();     // known share-loop state per run (2026-08-11)
    powerShareProfileActive     = true;
    powerShareProfilePhaseIdx   = 0;
    powerShareProfilePhaseStart = millis();
    powerShareProfileStatusLast = millis();
    // Open the SD log AFTER the flags are set so the first sample already carries ps_phase = 0.
    // Warns and continues with no card — a run is never gated on logging.
    // NOTE: 'R' is deliberately the ONLY profile start without a preceding haltMotorOutput() — a
    // standing manual motor command ('A'/'V') is this profile's documented precondition, so its
    // logOpenForProfile() below runs with a live motor. See the TODO(measure) at preAllocate().
    logOpenForProfile(LOG_TYPE_PS);
    Serial.println("[PS] Power-share profile started — Phase 0");
    if (vescWatchActive)
        Serial.println("[PS] VESC watch paused during the run (production-identical timing); resumes on stop");
}

// Human-readable name for a VESC mc_fault_code. Table transcribed verbatim from the vendored
// VescUart datatypes.h:124-153 (FW 5.x-era ordering). The blink count on the VESC's red LED
// equals this code number, but the ordering is firmware-version dependent — always cross-check
// the FW version ('E' command) before trusting a name here. Codes 0-27; anything else -> UNKNOWN.
const char* vescFaultStr(uint8_t code) {
    switch (code) {
        case 0:  return "NONE";
        case 1:  return "OVER_VOLTAGE";
        case 2:  return "UNDER_VOLTAGE";
        case 3:  return "DRV";
        case 4:  return "ABS_OVER_CURRENT";
        case 5:  return "OVER_TEMP_FET";
        case 6:  return "OVER_TEMP_MOTOR";
        case 7:  return "GATE_DRIVER_OVER_VOLTAGE";
        case 8:  return "GATE_DRIVER_UNDER_VOLTAGE";
        case 9:  return "MCU_UNDER_VOLTAGE";
        case 10: return "BOOTING_FROM_WATCHDOG_RESET";
        case 11: return "ENCODER_SPI";
        case 12: return "ENCODER_SINCOS_BELOW_MIN_AMPLITUDE";
        case 13: return "ENCODER_SINCOS_ABOVE_MAX_AMPLITUDE";
        case 14: return "FLASH_CORRUPTION";
        case 15: return "HIGH_OFFSET_CURRENT_SENSOR_1";
        case 16: return "HIGH_OFFSET_CURRENT_SENSOR_2";
        case 17: return "HIGH_OFFSET_CURRENT_SENSOR_3";
        case 18: return "UNBALANCED_CURRENTS";
        case 19: return "BRK";
        case 20: return "RESOLVER_LOT";
        case 21: return "RESOLVER_DOS";
        case 22: return "RESOLVER_LOS";
        case 23: return "FLASH_CORRUPTION_APP_CFG";
        case 24: return "FLASH_CORRUPTION_MC_CFG";
        case 25: return "ENCODER_NO_MAGNET";
        case 26: return "ENCODER_MAGNET_TOO_STRONG";
        case 27: return "PHASE_FILTER";
        default: return "UNKNOWN";
    }
}

// 'E' one-shot: read the VESC firmware version and a full telemetry snapshot over UART and dump
// them to USB Serial. This is the firmware's only positive verification that the VESC UART link
// works at all (setCurrent() is fire-and-forget — a "working" motor command proves nothing about
// the return path). Blocks up to ~200 ms total (two reads × 100 ms _TIMEOUT) if the VESC is
// silent; State-98-only, so tolerable. Prints (int)data.error so it compiles against both the
// real mc_fault_code enum and the host mock's uint8_t.
void queryVescInfo() {
    Serial.println("=== VESC info ===");
    if (vesc.getFWversion()) {
        Serial.print("VESC FW: "); Serial.print(vesc.fw_version.major);
        Serial.print("."); Serial.println(vesc.fw_version.minor);
    } else {
        Serial.println("VESC FW: no response — check VESC power, RX/TX wiring, baud 115200, App Cfg = UART");
    }
    if (vesc.getVescValues()) {
        Serial.print("inpVoltage:      "); Serial.print(vesc.data.inpVoltage, 2);      Serial.println(" V");
        Serial.print("avgMotorCurrent: "); Serial.print(vesc.data.avgMotorCurrent, 2); Serial.println(" A");
        Serial.print("avgInputCurrent: "); Serial.print(vesc.data.avgInputCurrent, 2); Serial.println(" A");
        Serial.print("dutyCycleNow:    "); Serial.println(vesc.data.dutyCycleNow, 3);
        Serial.print("rpm:             "); Serial.println(vesc.data.rpm, 0);
        Serial.print("tempMosfet:      "); Serial.print(vesc.data.tempMosfet, 1);      Serial.println(" C");
        Serial.print("tempMotor:       "); Serial.print(vesc.data.tempMotor, 1);       Serial.println(" C");
        Serial.print("tachometer:      "); Serial.println(vesc.data.tachometer);
        Serial.print("tachometerAbs:   "); Serial.println(vesc.data.tachometerAbs);
        Serial.print("vesc id:         "); Serial.println(vesc.data.id);
        uint8_t flt = (uint8_t)(int)vesc.data.error;
        Serial.print("fault:           "); Serial.print(flt);
        Serial.print(" ("); Serial.print(vescFaultStr(flt)); Serial.println(")");
    } else {
        Serial.println("values: no response — VESC unpowered or UART link down");
    }
    Serial.println("=================");
}

// 'U' watch tick: poll the VESC at VESC_WATCH_PERIOD_MS and print a compact line, loudly flagging
// any change in the live fault code (so a transient fault tripped by a motor command is caught the
// moment it happens). Called every doState98() tick; no-op unless the watch is active and the
// period has elapsed. Same blocking caveat as queryVescInfo().
void pollVescWatch() {
    if (!vescWatchActive) return;
    // Suppress the blocking poll while a timed profile is running so motorControl()/powerBalance()
    // execute with production-identical loop timing — the ~100 ms getVescValues() stall would
    // otherwise perturb the drive cycle / power-share step response. The watch resumes
    // automatically when the profile stops; the VESC latches faults, so a fault raised during the
    // run is still reported by the first poll afterward (elapsed > period → immediate) or via 'E'.
    if (driveCycleActive || powerShareProfileActive || trapProfileActive ||
        combinedProfileActive || wProfileActive) return;
    // Same suppression during the STAGED BRING-UP (2026-08-11): busBringupTick()'s phase dwells
    // and its V_bus regulation gates are timed off the main-loop cadence, and a ~100 ms blocking
    // getVescValues() injected into P0-P3 both skews those windows and delays detectFaults()
    // while the power stage is ramping — the one place in State 98 with a live, moving bus.
    if (bringupActive) return;
    // Same suppression under plot mode, for a different reason: the '[VW]' line is not numeric and
    // would break the plotter parse. The VESC latches faults, so anything raised while plotting is
    // still reported by the first poll after 'L' turns the stream off (or via 'E').
    if (plotSuppressStatus()) return;
    if (millis() - lastVescWatchMs < VESC_WATCH_PERIOD_MS) return;
    lastVescWatchMs = millis();

    if (!vesc.getVescValues()) {
        Serial.println("[VW] no response");
        return;
    }
    uint8_t flt = (uint8_t)(int)vesc.data.error;
    Serial.print("[VW] V=");    Serial.print(vesc.data.inpVoltage, 2);
    Serial.print(" Imot=");     Serial.print(vesc.data.avgMotorCurrent, 2);
    Serial.print(" Iin=");      Serial.print(vesc.data.avgInputCurrent, 2);
    Serial.print(" duty=");     Serial.print(vesc.data.dutyCycleNow, 3);
    Serial.print(" rpm=");      Serial.print(vesc.data.rpm, 0);
    Serial.print(" flt=");      Serial.print(flt);
    Serial.print("(");          Serial.print(vescFaultStr(flt)); Serial.println(")");
    if (flt != lastVescFault) {
        Serial.print("*** VESC FAULT -> "); Serial.print(flt);
        Serial.print(" ("); Serial.print(vescFaultStr(flt)); Serial.println(")");
        lastVescFault = flt;
    }
}

// Closed-loop: set the share setpoint and let powerBalance() drive the MDAC from measured current
// each test tick. Needs current actually flowing (motor running) for the MDAC to update.
void setPowerShareSetpointLive(float s) {
    // Full [0,1] span is valid (2026-08-10): an endpoint setpoint drives the
    // commanded ratio out of the droop band and applyShareRatio() cuts the
    // starved channel off the bus.
    power_share_setpoint = constrain(s, 0.0f, 1.0f);
    powerBalanceLive     = true;
    // S2 (2026-08-12 fw v5 review): a new operator setpoint is a FRESH EXPERIMENT, same rationale
    // as the profile starts. Without this, shareClosedLoopRun and share_govTotAFilt survive
    // 'X'/'Q'/safeAllSwitches()/a bring-up/State 99 from an earlier run, so a 'P' typed at low
    // current would land in the HOLD branch and be a silent no-op, and a 'G'→'P' sequence would
    // carry a stale load estimate into the mode decision. Callers are the operator 'P' key and the
    // 'T' sweep's per-run setpoint (which is immediately followed by startTrapProfile(), itself a
    // resetter) — no per-tick caller exists, so this cannot reset the controller inside a run: the
    // profiles that interpolate the setpoint write power_share_setpoint directly.
    resetShareControlState();
}

// Open-loop: map a typed droop ratio directly to the droop gains and write the MDAC immediately —
// no PI, no current needed (good for bench-calibrating the droop hardware at a known split). Same
// gain math as powerBalance(). Clears powerBalanceLive so the closed loop won't stomp the write.
// This is the §9 (system_model.md) calibration entry point: sweep r, log I_fc/I_batt, fit ΔV0.
void applyOpenLoopDroop(float ratio) {
    // Accepts the full [0,1] span (2026-08-10): applyShareRatio() carries the
    // droop-band clip, the out-of-band channel cutoff, and the hysteresis, so
    // the 'O' command exercises exactly the closed loop's actuation path.
    applyShareRatio(ratio);
    powerBalanceLive = false;
}

// Manual motor: fixed VESC current (bypasses the velocity PI). Clamped to the VESC current ceiling.
void setManualMotorCurrent(float a) {
    manualMotorCurrent = constrain(a, -MOTOR_I_CMD_MAX, MOTOR_I_CMD_MAX);
    manualMotorMode    = MOTOR_TEST_CURRENT;
}

// ── Velocity-chain calibration interlock ─────────────────────────────────────
// The velocity loop closes on v_actual, whose scale depends on two constants (ENCODER_SLOTS_PER_REV,
// FLYWHEEL_RADIUS_M). Both were bench-measured on 2026-08-13, so the shipped default is CALIBRATED
// and the two State-98 velocity entry points ('V' manual velocity, 'D' drive cycle) are open.
// The interlock remains because an under-reading v_actual makes the PI OVER-DRIVE — it keeps adding
// current chasing a setpoint the flywheel has already passed — and commandMotorCurrent() bounds
// amps, not speed. Build with -DVELOCITY_CHAIN_CALIBRATED=0 (or clear the flag at runtime) if the
// disc or flywheel is changed, and re-measure before re-enabling.
// Seeded from the compile-time macro but kept as a runtime flag so the host tests can exercise BOTH
// the refusal path and the calibrated path in one build (a compile-time-only gate would leave one of
// the two branches untested in every build).
bool velocityChainCalibratedFlag = (VELOCITY_CHAIN_CALIBRATED != 0);

bool velocityChainCalibrated() {
    return velocityChainCalibratedFlag;
}

void printVelocityChainRefusal(const char *what) {
    Serial.print("REFUSED: ");
    Serial.print(what);
    Serial.println(" needs a calibrated velocity chain.");
    Serial.println("  v_actual scale is unconfirmed for this build (ENCODER_SLOTS_PER_REV, FLYWHEEL_RADIUS_M).");
    Serial.println("  An under-reading v_actual makes the velocity PI OVER-DRIVE; the current clamp");
    Serial.println("  bounds amps, not speed. Measure both, then rebuild with");
    Serial.println("  -DVELOCITY_CHAIN_CALIBRATED=1. Use 'A' (fixed current) for motor tests instead.");
}

// Manual motor: fixed velocity setpoint driven through the existing motorControl() PI. Clamped to
// the manual velocity ceiling (the motor PI's current anti-windup bounds the command either way).
// Refuses outright while the velocity chain is uncalibrated — see velocityChainCalibrated().
void setManualMotorVelocity(float v) {
    if (!velocityChainCalibrated()) {
        printVelocityChainRefusal("manual velocity mode");
        return;
    }
    manualMotorVelocity = constrain(v, -MANUAL_MOTOR_V_MAX, MANUAL_MOTOR_V_MAX);
    manualMotorMode     = MOTOR_TEST_VELOCITY;
}

// ── Motor output ownership ───────────────────────────────────────────────────
// Single primitive for "no one is driving the motor any more". State 98 has four motor drivers
// (manual current, manual velocity, drive cycle, power-share profile) and they used to release the
// motor inconsistently: the drive cycle's stop path zeroed the VESC but left manualMotorMode set,
// so control fell through to the standalone branch IN THE SAME TICK and applyManualMotor() reissued
// the pre-drive-cycle manual current. Natural completion was worse — it never flushed a zero at all.
// (design-review-2026-07-28.md P0-2.)
//
// Clearing pi_motor_accum matters as much as the zero flush: a drive cycle ends with the integrator
// wound up from the regen-hold phase, and carrying that into the next run means the first
// motorControl() tick commands a large current from stale history rather than from live error.
// This deliberately does NOT touch the power-path switches. The policy question (whether a test
// exit retains the motor-node connection or drops it) is RESOLVED (2026-08-03): 'Q' darkens the
// stage via busBringupAbort() and forces MOT_PWR_ENABLE LOW below. A reconnect from a regulated
// bus is cheap and guarded (motPwrConnectBlocked()), so teardown-on-exit is the settled policy;
// haltMotorOutput() itself stays switch-agnostic and leaves the choice to its callers.
void haltMotorOutput() {
    manualMotorMode     = MOTOR_TEST_OFF;
    v_setpoint          = 0.0f;
    manualMotorCurrent  = 0.0f;
    manualMotorVelocity = 0.0f;
    pi_motor_accum      = 0.0f;
    targetMotorTorque   = 0.0f;
    commandMotorCurrent(0);          // also clears `current`
}

// Apply the active manual motor command for one tick (called from doState98()).
void applyManualMotor() {
    if (manualMotorMode == MOTOR_TEST_CURRENT) {
        // Rate-gated on the SAME period as motorControl(). Re-sending a constant current every tick
        // blocks the loop on UART TX backpressure for no benefit; 500 Hz is far more often than the
        // VESC's 1000 ms command timeout needs to stay fed. Uses rl_motor_last so manual current and
        // motorControl() can never both write in one tick.
        if (rateLimitDue(rl_motor_last, MOTOR_CTRL_PERIOD_US))
            commandMotorCurrent(manualMotorCurrent);   // constant current, bypass velocity PI
    } else if (manualMotorMode == MOTOR_TEST_VELOCITY) {
        v_setpoint = manualMotorVelocity;   // hold velocity setpoint; motorControl() runs the PI
        motorControlGated();
    }
}

// Power-share profile emulator: same phase-machine structure as advanceDriveCycle(), but sweeps
// power_share_setpoint instead of v_setpoint. The motor is held constant by applyManualMotor() and
// the droop is closed by powerBalance() in doState98(); this function only supplies the setpoint.
void advancePowerShareProfile() {
    if (powerShareProfilePhaseIdx >= POWER_SHARE_PROFILE_PHASES) {
        power_share_setpoint    = 0.5f;     // return to balanced on completion
        powerShareProfileActive = false;
        // Halt the motor on natural completion too (symmetric with the 'R'-stop and 'Q' paths) —
        // otherwise the still-set manualMotorMode keeps applyManualMotor() driving the motor in the
        // standalone branch after the sweep ends.
        haltMotorOutput();
        // S1 (2026-08-12 fw v5 review): same end-of-run cutoff restore as 'Y'/'W'. This profile
        // COMMANDS the share setpoint, so any controller-initiated cutoff outstanding at the end
        // is this run's own claim to release — and nothing else will: the min-load gate stops
        // powerBalance() before the re-entry ever runs once the motor is zeroed.
        restoreShareCutoffOnCompletion("PS");
        logRequestClose(LOG_CLOSE_COMPLETE);   // symmetric with the 'R' stop path
        Serial.println("[PS] Power-share profile complete — motor zeroed");
        return;
    }

    uint32_t elapsed = millis() - powerShareProfilePhaseStart;
    const PowerShareProfilePhase &ph = POWER_SHARE_PROFILE[powerShareProfilePhaseIdx];

    if (elapsed >= ph.durationMs) {
        powerShareProfilePhaseIdx++;
        powerShareProfilePhaseStart = millis();
        if (powerShareProfilePhaseIdx < POWER_SHARE_PROFILE_PHASES && !plotSuppressStatus()) {
            Serial.print("[PS] Phase "); Serial.println(powerShareProfilePhaseIdx);
        }
        return;
    }

    // Linear interpolation of power_share_setpoint within phase
    float t = (float)elapsed / (float)ph.durationMs;
    power_share_setpoint = ph.share_start + t * (ph.share_end - ph.share_start);

    // Status snapshot every 500 ms — setpoint vs measured share, the currents, and droop gains.
    // Suppressed under plot mode: the same signals stream at 50 Hz in a plotter-parseable form,
    // and these lines would break the parse.
    if (!plotSuppressStatus() && millis() - powerShareProfileStatusLast >= 500) {
        powerShareProfileStatusLast = millis();
        float totalA = fabsf(I_fc) + fabsf(I_batt);
        float share_act = (totalA > 1e-6f) ? (fabsf(I_fc) / totalA) : 0.0f;
        Serial.print("[PS] t="); Serial.print(millis());
        Serial.print(" sp="); Serial.print(power_share_setpoint, 3);
        Serial.print(" act="); Serial.print(share_act, 3);
        Serial.print(" I_fc="); Serial.print(I_fc, 2);
        Serial.print(" I_bt="); Serial.print(I_batt, 2);
        Serial.print(" gFC="); Serial.print(droop_gain_FC_actual, 3);
        Serial.print(" gBT="); Serial.print(droop_gain_BT_actual, 3);
        Serial.print(" V_bus="); Serial.print(V_bus, 2);
        Serial.print(" FLT=0x"); Serial.println(fault_flags, HEX);
    }
}

// ── Trapezoidal motor-current profile ('T') ──────────────────────────────────────────────────
// Parse the single-line parameter entry "<Imax A> <hold s> <rate A/s>" (e.g. "6 5 0.5", typically
// typed as one line "T 6 5 0.5") and start the profile if all three validate. Any failure rejects
// the WHOLE line — no partial parameter set can ever be committed. strtof() consumes leading
// whitespace itself, so the leftover " 6 5 0.5" after the 'T' key parses cleanly.
void parseTrapParamsLine(const char* line) {
    char* end = nullptr;
    float imax = strtof(line, &end);
    if (end == line) {
        Serial.println("ERROR: expected \"<Imax A> <hold s> <rate A/s>\" (e.g. T 6 5 0.5) — trapezoid cancelled");
        return;
    }
    const char* p    = end;
    float       hold = strtof(p, &end);
    if (end == p) {
        Serial.println("ERROR: missing hold time — usage \"T <Imax A> <hold s> <rate A/s>\" — trapezoid cancelled");
        return;
    }
    p          = end;
    float rate = strtof(p, &end);
    if (end == p) {
        Serial.println("ERROR: missing ramp rate — usage \"T <Imax A> <hold s> <rate A/s>\" — trapezoid cancelled");
        return;
    }

    // Negative peaks are ALLOWED by design: a negative command is a braking/regen torque test,
    // which is exactly the load case the regen/charger path needs exercised. Bounded by the ESC's
    // hardware rating (TRAP_I_ABS_MAX), NOT MOTOR_I_CMD_MAX — see the constant's rationale.
    imax = constrain(imax, -TRAP_I_ABS_MAX, TRAP_I_ABS_MAX);
    if (fabsf(imax) < 1e-3f) {
        // Zero peak would make the whole profile a no-op AND give a 0 ms ramp; refuse rather than
        // silently run a null test.
        Serial.println("ERROR: peak current must be non-zero — trapezoid cancelled");
        return;
    }
    if (hold < 0.0f) {
        Serial.println("ERROR: hold time must be >= 0 s — trapezoid cancelled");
        return;
    }
    if (rate <= 0.0f) {
        // Rate is a divisor for the ramp duration — 0/negative is not just meaningless but
        // arithmetically unsafe, so it is refused outright.
        Serial.println("ERROR: ramp rate must be > 0 A/s — trapezoid cancelled");
        return;
    }

    uint32_t holdMs = (uint32_t)(hold * 1000.0f + 0.5f);   // hold 0 is legal: triangle

    // ── Optional sweep list "[t,r1,…,rn]" (2026-08-11) ───────────────────────────────────────
    // Parsed into LOCALS and only committed after the whole line validates — same all-or-nothing
    // discipline as the three scalars above, and for the same reason: a half-accepted sweep would
    // run the first ratio and then stop somewhere the operator never asked for.
    //
    // Before this field existed, anything after the third value was ignored. That tolerance is now
    // REMOVED: with a 4th field in the grammar, silently dropping "…  [3,0.3,0.7" (a missed ']')
    // would run a plain single trapezoid while the operator believes a 3-run sweep is under way —
    // and they would only find out an hour later, from a card holding one file.
    float   sweepRatios[TSWEEP_MAX_RATIOS];
    uint8_t sweepN     = 0;
    float   sweepDwell = 0.0f;
    bool    haveSweep  = false;

    p = end;
    while (*p == ' ' || *p == '\t') p++;
    if (*p == '[') {
        p++;
        // Dwell (seconds) first, then >= 1 comma-separated ratios.
        sweepDwell = strtof(p, &end);
        if (end == p) {
            Serial.println("ERROR: sweep list must start with the dwell seconds, \"[t,r1,...]\" — trapezoid cancelled");
            return;
        }
        if (!(sweepDwell >= 0.0f) || sweepDwell > TSWEEP_DWELL_MAX_S) {
            Serial.print("ERROR: sweep dwell must be 0-");
            Serial.print(TSWEEP_DWELL_MAX_S, 0);
            Serial.println(" s — trapezoid cancelled");
            return;
        }
        p = end;
        while (*p == ' ' || *p == '\t') p++;
        while (*p == ',') {
            p++;
            float r = strtof(p, &end);
            if (end == p) {
                Serial.println("ERROR: non-numeric value in the sweep list — trapezoid cancelled");
                return;
            }
            // Full [0,1] span is legal here for the same reason 'P' accepts it (2026-08-10): an
            // endpoint setpoint is a channel-CUTOFF datapoint, which is a run worth sweeping.
            if (!(r >= 0.0f) || r > 1.0f) {
                Serial.println("ERROR: sweep share setpoints must be 0.0-1.0 — trapezoid cancelled");
                return;
            }
            if (sweepN >= TSWEEP_MAX_RATIOS) {
                Serial.print("ERROR: sweep list holds at most ");
                Serial.print(TSWEEP_MAX_RATIOS);
                Serial.println(" setpoints — trapezoid cancelled");
                return;
            }
            sweepRatios[sweepN++] = r;
            p = end;
            while (*p == ' ' || *p == '\t') p++;
        }
        if (sweepN == 0) {
            Serial.println("ERROR: sweep list needs at least one share setpoint, \"[t,r1,...]\" — trapezoid cancelled");
            return;
        }
        if (*p != ']') {
            Serial.println("ERROR: sweep list is missing its closing ']' — trapezoid cancelled");
            return;
        }
        p++;
        while (*p == ' ' || *p == '\t') p++;
        if (*p != '\0') {
            Serial.println("ERROR: unexpected text after the sweep list — trapezoid cancelled");
            return;
        }
        haveSweep = true;
    } else if (*p != '\0') {
        // A 4th token that is not a sweep list. Refused rather than ignored (see above).
        Serial.println("ERROR: unexpected 4th value — usage \"T <Imax A> <hold s> <rate A/s> [t,r1,...,rn]\" — trapezoid cancelled");
        return;
    }

    // Plot mode defers the start so the operator can reach the plotter window (PLOT_ARM_DELAY_MS).
    // Arming happens HERE rather than inside startTrapProfile() so plotArmTick() can call that
    // function directly without re-arming itself — one start path, no recursion guard needed.
    // All three values are already validated above, so the armed run cannot fail later.
    if (plotModeActive) {
        // A sweep is minutes long and fires runs from a tick, not from a keypress; the arming
        // window's "operator is away at the plotter window" assumption and the sweep's own
        // fire-time precondition re-checks would have to be reconciled for no benefit — the 50 Hz
        // plot stream is not the capture path for a sweep anyway (each run has its own 1 kHz log).
        // Refuse the combination outright rather than pick one of the two semantics silently.
        if (haveSweep) {
            Serial.println("ERROR: sweep list not supported under plot mode ('L') — trapezoid cancelled");
            return;
        }
        // Same running-profile refusal as the 'R' arm path (review 2026-08-07 F5).
        if (driveCycleActive || powerShareProfileActive || combinedProfileActive ||
            wProfileActive) {
            Serial.println("ERROR: another profile is running — stop it first ('X') before arming under plot mode");
            return;
        }
        cancelPlotArm("superseded by 'T'");   // a pending share arm must not vanish silently
        plotArmTarget     = PLOT_ARM_TRAP;
        plotArmDeadlineMs = millis() + PLOT_ARM_DELAY_MS;
        plotArmTrapImax   = imax;
        plotArmTrapHoldMs = holdMs;
        plotArmTrapRate   = rate;
        Serial.print("[PLOT] Trapezoid ARMED (Imax=");
        Serial.print(imax, 2);
        Serial.print("A) — starts in ");
        Serial.print(PLOT_ARM_DELAY_MS);
        Serial.println("ms. Switch to the Serial Plotter now ('T' or 'X' cancels)");
        return;
    }

    // A newly typed 'T' line supersedes a sweep that is between runs (its trapezoid is not
    // running, so the 'T' keypress reached the parameter prompt rather than the stop path). Done
    // HERE, not in startTrapProfile(), because the sweep itself starts every run through that
    // function — cancelling there would abort the sweep on its own second run.
    tsweepCancel("superseded by a new 'T' line");

    if (haveSweep) {
        tsweepActive          = true;
        tsweepPhase           = 0;    // the first run starts below, so we are RUNNING immediately
        tsweepCount           = sweepN;
        tsweepIdx             = 0;
        tsweepDwellMs         = (uint32_t)(sweepDwell * 1000.0f + 0.5f);
        tsweepImax            = imax;
        tsweepHoldMs          = holdMs;
        tsweepRate            = rate;
        tsweepCooldownStartMs = millis();
        for (uint8_t i = 0; i < sweepN; i++) tsweepRatios[i] = sweepRatios[i];

        Serial.print("[TSWEEP] "); Serial.print(tsweepCount);
        Serial.print(" runs, dwell "); Serial.print(sweepDwell, 1);
        Serial.print(" s: r =");
        for (uint8_t i = 0; i < tsweepCount; i++) {
            Serial.print(" "); Serial.print(tsweepRatios[i], 3);
        }
        Serial.println();

        // Setpoint BEFORE the start call: startTrapProfile() opens the SD log, and the log's very
        // first record must already carry this run's share_sp (the same "flags before
        // logOpenForProfile()" rule the profile start paths follow).
        setPowerShareSetpointLive(tsweepRatios[0]);
        startTrapProfile(tsweepImax, tsweepHoldMs, tsweepRate);
        Serial.print("[TSWEEP] run 1/"); Serial.print(tsweepCount);
        Serial.print(": share_sp="); Serial.println(tsweepRatios[0], 3);
        return;
    }

    startTrapProfile(imax, holdMs, rate);
}

// Sweep sequencer: one tick per doState98() invocation, alongside plotArmTick(). Non-blocking by
// construction — the dwell is a millis() comparison and the log wait is a POLL of the logger's own
// flags. It must never call logDrainTick() itself: that is loop()'s job and the drain is
// deliberately gated out of the State-99 teardown (FW-R1-F1), an ordering this must not subvert.
void tsweepTick() {
    if (!tsweepActive) return;

    if (tsweepPhase == 0) {                 // RUNNING
        if (trapProfileActive) return;
        // The trapezoid ended. Only a NATURAL completion can reach here: every operator/supersede
        // stop path cancels the sweep first, so a cleared flag here means the run finished.
        tsweepPhase = 1;
        return;
    }

    if (tsweepPhase == 1) {                 // WAIT_LOG
        // Gate the next run on the logger being fully idle. logOpenForProfile() force-finishes a
        // still-open file and then SILENTLY SKIPS logging when the card is busy — starting run k+1
        // one tick early would cost that run its entire dataset with no error anywhere.
        if (logActive || logCloseRequested) return;
        if ((uint8_t)(tsweepIdx + 1) >= tsweepCount) {
            uint8_t n = tsweepCount;
            tsweepFinish();
            Serial.print("[TSWEEP] complete — "); Serial.print(n); Serial.println(" runs logged");
            return;
        }
        tsweepPhase           = 2;
        tsweepCooldownStartMs = millis();
        Serial.print("[TSWEEP] cool-down "); Serial.print(tsweepDwellMs / 1000.0f, 1);
        Serial.print(" s before run "); Serial.print(tsweepIdx + 2);
        Serial.print("/"); Serial.println(tsweepCount);
        return;
    }

    // COOLDOWN
    if (millis() - tsweepCooldownStartMs < tsweepDwellMs) return;

    // Fire-time precondition re-check, same discipline (and same reason) as plotArmTick(): the
    // dwell is seconds-to-minutes long and the operator can start a bring-up or another profile
    // inside it. Firing a trapezoid into either would stomp a running sequence.
    if (bringupActive || driveCycleActive || powerShareProfileActive || combinedProfileActive ||
        wProfileActive) {
        tsweepCancel("preconditions changed during cool-down");
        return;
    }
    // MOT_PWR is warn-only, exactly as the 'T' keypress treats it: the VESC may be fed from its
    // own bench supply, and if MOT_PWR really is its only source an unpowered VESC just ignores
    // the commands. A refusal here would abandon the sweep for a condition that is often benign.
    if (!digitalRead(MOT_PWR_ENABLE)) {
        Serial.println("[TSWEEP] WARN: MOT_PWR_ENABLE is LOW — next run will command an unpowered motor (key '3')");
    }

    tsweepIdx++;
    setPowerShareSetpointLive(tsweepRatios[tsweepIdx]);   // before the start: see the start path
    startTrapProfile(tsweepImax, tsweepHoldMs, tsweepRate);
    tsweepPhase = 0;
    Serial.print("[TSWEEP] run "); Serial.print(tsweepIdx + 1);
    Serial.print("/"); Serial.print(tsweepCount);
    Serial.print(": share_sp="); Serial.println(tsweepRatios[tsweepIdx], 3);
}

// Restore the share loop to the quiescent state the sweep found it in. The sweep is what turned
// powerBalanceLive on (via setPowerShareSetpointLive()), so it owns turning it back off —
// mirroring the 'R'/'X' share-profile stop convention of parking the setpoint at 0.5.
static void tsweepRelease() {
    tsweepActive         = false;
    tsweepPhase          = 0;
    tsweepIdx            = 0;
    power_share_setpoint = 0.5f;
    powerBalanceLive     = false;
}

void tsweepFinish() {
    if (!tsweepActive) return;
    // S1 (2026-08-12 fw v5 review): the sweep is the 'T' family's share-COMMANDING path (it drives
    // setPowerShareSetpointLive() per run), so its natural completion owns any outstanding
    // controller cutoff — restore before releasing the loop, exactly as 'Y'/'W'/'R' do. Kept in
    // tsweepFinish() and NOT in the shared tsweepRelease(): the cancel paths ('X', 'Q', a stop
    // key) run their own teardown, and re-closing a bus switch mid-teardown would fight it.
    restoreShareCutoffOnCompletion("TSWEEP");
    tsweepRelease();
}

// Drop a running sweep. Safe to call unconditionally (no-op when none is active) so every stop
// path can invoke it without testing first — the same discipline that keeps cancelPlotArm() from
// leaving a countdown alive past the key that was supposed to stop everything. Deliberately does
// NOT touch the motor or the path switches: each caller already applies its own stop semantics
// (the trapezoid's are "motor zeroed, switches left as-is").
void tsweepCancel(const char* why) {
    if (!tsweepActive) return;
    uint8_t doneRuns = tsweepIdx + 1;
    uint8_t total    = tsweepCount;
    tsweepRelease();
    Serial.print("[TSWEEP] cancelled: "); Serial.print(why);
    Serial.print(" (after run "); Serial.print(doneRuns);
    Serial.print("/"); Serial.print(total); Serial.println(")");
}

const char* trapPhaseStr(TrapPhase p) {
    switch (p) {
        case TRAP_RAMP_UP:   return "RAMP_UP";
        case TRAP_HOLD:      return "HOLD";
        case TRAP_RAMP_DOWN: return "RAMP_DOWN";
        default:             return "?";
    }
}

// Commit the three validated operator values and take exclusive ownership of the motor output.
// Called only from parseTrapParamsLine() (all three values already range-checked there). No
// MOT_PWR_ENABLE gate — the VESC may be powered from a separate bench supply; if MOT_PWR really
// is its only source, an unpowered VESC just ignores the commands (the 'T' handler warns).
void startTrapProfile(float imax, uint32_t holdMs, float rateAps) {
    // Exclusive motor ownership, same discipline as the 'D' start path: clear the other two motor
    // drivers, flush a zero + clear the manual modes and the PI integrator (haltMotorOutput()), then
    // reset the rate limiters so the very first profile tick drives immediately rather than waiting
    // out a stale MOTOR_CTRL_PERIOD_US window. Without the halt, a manual current set with 'A'
    // before 'T' would survive the run and re-assert itself the instant the profile ends.
    driveCycleActive        = false;
    powerShareProfileActive = false;
    combinedProfileActive   = false;   // ditto: it drives both setpoints and must not survive
    wProfileActive          = false;
    wCmdA                   = 0.0f;
    haltMotorOutput();
    resetControlRateLimiters();
    resetShareControlState();     // known share-loop state per run (2026-08-11)

    trapImax    = imax;
    trapHoldMs  = holdMs;
    trapRateAps = rateAps;
    // Ramp duration from |I_max| / rate. Floored at 1 ms: a very steep rate can round to 0 ms, and
    // the phase interpolation below divides by trapRampMs. A 1 ms ramp is effectively a step, which
    // is a legitimate (if aggressive) operator request — the ±TRAP_I_ABS_MAX clamp still bounds it.
    uint32_t rampMs = (uint32_t)((fabsf(imax) / rateAps) * 1000.0f + 0.5f);
    trapRampMs      = (rampMs == 0) ? 1u : rampMs;

    trapPhase         = TRAP_RAMP_UP;
    trapCmdA          = 0.0f;
    trapStartMs       = millis();
    trapStatusLast    = millis();
    trapProfileActive = true;
    // Open the SD log AFTER the flags are set so the first sample already carries trap_phase.
    // Warns and continues with no card — a run is never gated on logging.
    logOpenForProfile(LOG_TYPE_TP);

    Serial.print("[TP] Trapezoid started — Imax="); Serial.print(trapImax, 2);
    Serial.print("A rate=");  Serial.print(trapRateAps, 2);
    Serial.print("A/s ramp="); Serial.print(trapRampMs);
    Serial.print("ms hold=");  Serial.print(trapHoldMs);
    Serial.print("ms total="); Serial.print(2u * trapRampMs + trapHoldMs);
    Serial.println("ms  (Phase RAMP_UP; 'T' again to stop)");
    if (vescWatchActive)
        Serial.println("[TP] VESC watch paused during the run (production-identical timing); resumes on stop");
}

// One profile tick: compute the commanded current from elapsed time and issue it. Structurally the
// same phase machine as advanceDriveCycle()/advancePowerShareProfile(), but it drives the VESC
// current directly instead of only supplying a setpoint for a downstream controller.
void advanceTrapProfile() {
    uint32_t elapsed  = millis() - trapStartMs;
    uint32_t tHoldEnd = trapRampMs + trapHoldMs;
    uint32_t tEnd     = tHoldEnd + trapRampMs;   // symmetric down-ramp at the same rate

    if (elapsed >= tEnd) {
        trapProfileActive = false;
        trapCmdA          = 0.0f;
        // Natural completion releases the motor EXACTLY as the 'T' stop path does — flush a zero
        // and clear the manual modes/integrator. Asymmetry here is precisely the P0-2 bug class
        // (design-review-2026-07-28.md): a completion path that only clears its own flag leaves a
        // pre-run manualMotorMode driving the motor from the standalone branch on the next tick.
        // Switches are left alone on completion for the same reason as the stop path (see 'T').
        haltMotorOutput();
        logRequestClose(LOG_CLOSE_COMPLETE);   // symmetric with the 'T' stop path
        // NOTE (S1, fw v5 review): deliberately NO restoreShareCutoffOnCompletion() here. A bare
        // trapezoid never commands the share setpoint, so an outstanding cutoff belongs to whoever
        // did (the sweep's tsweepFinish(), an operator 'P'), and this profile's stated contract on
        // both its stop and completion paths is that path switches are left exactly as configured.
        Serial.println("[TP] Trapezoid complete — motor zeroed (path switches left as-is)");
        return;
    }

    float     cmd;
    TrapPhase newPhase;
    if (elapsed < trapRampMs) {
        newPhase = TRAP_RAMP_UP;
        cmd      = trapImax * ((float)elapsed / (float)trapRampMs);
    } else if (elapsed < tHoldEnd) {
        newPhase = TRAP_HOLD;
        cmd      = trapImax;
    } else {
        newPhase = TRAP_RAMP_DOWN;
        cmd      = trapImax * (1.0f - (float)(elapsed - tHoldEnd) / (float)trapRampMs);
    }

    if (newPhase != trapPhase) {
        trapPhase = newPhase;
        if (!plotSuppressStatus()) {
            Serial.print("[TP] Phase "); Serial.println(trapPhaseStr(trapPhase));
        }
    }
    trapCmdA = cmd;

    // Rate-gated on rl_motor_last / MOTOR_CTRL_PERIOD_US, identical to applyManualMotor()'s current
    // branch: the shared limiter guarantees this and motorControl() can never both write the VESC in
    // one tick, and 500 Hz re-sends keep the VESC's 1000 ms command timeout fed (on expiry it
    // COASTS rather than brakes, which would silently truncate the profile).
    if (rateLimitDue(rl_motor_last, MOTOR_CTRL_PERIOD_US))
        commandMotorCurrentLimited(cmd, TRAP_I_ABS_MAX);   // ESC-rating ceiling, not MOTOR_I_CMD_MAX

    // Status snapshot every 500 ms — same cadence/style as the other two profiles (and suppressed
    // under plot mode for the same reason).
    if (!plotSuppressStatus() && millis() - trapStatusLast >= 500) {
        trapStatusLast = millis();
        Serial.print("[TP] t=");    Serial.print(elapsed);
        Serial.print(" ph=");       Serial.print(trapPhaseStr(trapPhase));
        Serial.print(" I_cmd=");    Serial.print(trapCmdA, 2);
        Serial.print(" I_fc=");     Serial.print(I_fc, 2);
        Serial.print(" I_bt=");     Serial.print(I_batt, 2);
        Serial.print(" V_bus=");    Serial.print(V_bus, 2);
        Serial.print(" FLT=0x");    Serial.println(fault_flags, HEX);
    }
}

// ── Shared combined-profile helpers: cutoff warning + end-of-run restore ─────────────────────
// S1 warning. Since the 2026-08-10 full-span actuation change, a commanded share ratio outside
// [DROOP_R_MIN, DROOP_R_MAX] no longer clips — applyShareRatio() opens the starved channel's
// RT1987 bus switch UNDER LOAD. Both combined profiles drive the share to 1.0 (R6) and 0.0 (R11)
// by design, so with a bound below DROOP_R_MIN the run WILL perform two bus-switch openings while
// the motor is drawing. That is the TP0010 stressor class and must never be a surprise: warn
// explicitly, name the motor ceiling the switch will open against, and point at the safe first run.
static void warnIfBandReachesCutoff(const char *tag, float boundLo, const char *safeCmd,
                                    float motorCapA, const char *capUnitNote) {
    if (boundLo >= DROOP_R_MIN) return;   // band stays inside the droop-clip span — no cutoff
    Serial.print("["); Serial.print(tag);
    Serial.print("] WARNING: share band reaches the full-span cutoff — R6/R11 will open a bus "
                 "switch under load (motor cmd up to ");
    Serial.print(capUnitNote);
    Serial.print(motorCapA, 1);
    Serial.print(" A phase; bus draw is duty-dependent). First run: use ");
    Serial.print(safeCmd);
    Serial.println(", scope-armed (see TP0010).");
}

// A2 restore. A combined profile can reach its natural completion with a controller-initiated
// cutoff still LATCHED (e.g. the run ends while the share is parked at an extreme, or the re-entry
// hysteresis never cleared). Nothing would then put the channel back: with no profile running,
// powerBalance() never executes, so applyShareRatio() is never called again and the board sits
// SINGLE-SOURCED indefinitely with the bus still up. Re-close through applyShareRatio() itself
// with a mid-band ratio rather than writing the pins here — that reuses the controller's OWN
// re-entry path, including its V_bus >= V_BUS_CHARGED_THRESH guard and its ownership rules, so
// this can never close a switch the controller does not own. If the bus is NOT in regulation the
// re-entry correctly declines and the flag stays latched; the next teardown clears it
// (safeAllSwitches() already owns that, which is why the stop/'X'/'Q' paths need nothing here).
static void restoreShareCutoffOnCompletion(const char *tag) {
    if (!shareIsoFC && !shareIsoBT) return;
    // Drop any SETPOINT latch first (2026-08-12): the completion path's whole
    // purpose is to put both sources back, and a run that ended at an
    // out-of-band setpoint would otherwise have its re-entry blocked by the
    // latch (applyShareRatio() gates re-entry on !shareSpCutX) with no governed
    // tick left to release it — powerBalance() stops running when the run ends.
    // If the setpoint is still out of band, the next governed tick simply
    // re-latches through the normal entry path.
    shareSpCutFC = false;
    shareSpCutBT = false;
    applyShareRatio(0.5f);   // mid-band: unambiguously past both hysteresis thresholds
    Serial.print("["); Serial.print(tag);
    if (shareIsoFC || shareIsoBT) {
        Serial.println("] NOTE: a channel is still cut off (bus not in regulation) — "
                       "'X'/'Q' or a fresh 'G' bring-up will clear it");
    } else {
        Serial.println("] channel cutoff cleared on completion — both sources back on the bus");
    }
}

// ── Combined drive-cycle + power-share profile ('Y') ─────────────────────────────────────────
// Parse the single-line parameter entry "[Vmax m/s] [share bound b]" (e.g. typed as one line
// "Y 1 0.3"). BOTH values are optional — unlike the trapezoid, an empty line is a legitimate
// "run the defaults" and is NOT a cancel (handlePendingInputChar() dispatches PEND_Y_PARAMS
// before its shared empty-line cancel for exactly this reason). Any validation failure rejects
// the WHOLE line: no partial parameter set can ever be committed.
void parseCombinedParamsLine(const char* line) {
    float vmax  = Y_VMAX_DEFAULT;
    float bound = Y_BOUND_DEFAULT;

    if (!parseTwoOptionalFloats(line, "ERROR: expected \"Y [Vmax m/s] [b]\" — at most two values (e.g. Y 1 0.3) — profile cancelled",
                                vmax, bound))
        return;

    if (vmax <= 0.0f) {
        Serial.println("ERROR: Vmax must be > 0 m/s — profile cancelled");
        return;
    }
    // Reuse the SAME ceiling the 'V' manual-velocity path enforces (setManualMotorVelocity()):
    // this profile closes the identical velocity loop, so inventing a second, different bound
    // here would let 'Y' drive a setpoint that 'V' refuses.
    if (vmax > MANUAL_MOTOR_V_MAX) {
        Serial.print("ERROR: Vmax must be <= ");
        Serial.print(MANUAL_MOTOR_V_MAX, 1);
        Serial.println(" m/s (MANUAL_MOTOR_V_MAX, the same ceiling 'V' enforces) — profile cancelled");
        return;
    }
    if (!validateShareBound(bound)) return;

    startCombinedProfile(vmax, bound);
}

// ── Shared parameter-line helpers ('Y' and 'W') ──────────────────────────────────────────────
// Extract up to two OPTIONAL floats from a typed parameter line, leaving each output at its
// caller-seeded default when the corresponding value is absent. Returns false (having printed
// `usage`) if anything but whitespace follows the values. Shared so the two combined profiles can
// never acquire subtly different entry grammars.
bool parseTwoOptionalFloats(const char* line, const char* usage, float &first, float &second) {
    char*       end = nullptr;
    const char* p   = line;
    float       a   = strtof(p, &end);
    if (end != p) {
        first = a;
        p     = end;
        float b = strtof(p, &end);
        if (end != p) second = b;   // second value absent is fine — it keeps its default
    }
    // Whatever strtof() stopped on must be whitespace only. Only digits/sign/point/space can
    // reach these buffers at all (isNumericEntryChar()), so the realistic case this catches is a
    // THIRD value ("Y 1 0.3 2") — refuse rather than silently ignore it, since a third number
    // means the operator believes the command takes a parameter it does not have.
    while (*end == ' ' || *end == '\t') end++;
    if (*end != '\0') {
        Serial.println(usage);
        return false;
    }
    return true;
}

// Validate the share clip bound. Identical rules for both combined profiles by spec, so the rules
// (and their messages) live here rather than in each parser.
bool validateShareBound(float b) {
    if (b < 0.0f) {
        Serial.println("ERROR: share bound b must be >= 0 — profile cancelled");
        return false;
    }
    if (b >= 0.5f) {
        // At b = 0.5 the band [b, 1-b] collapses to the single point 0.5 and the whole share axis
        // of the profile becomes a flat line — a null test, so refuse rather than run it.
        Serial.println("ERROR: share bound b must be < 0.5 (the band [b, 1-b] collapses at 0.5) — profile cancelled");
        return false;
    }
    if (b > Y_BOUND_WARN) {
        // Accepted, not refused: a tight band is a legitimate way to keep a fragile bench setup
        // away from the share extremes. Warn because the run no longer matches the documented
        // region table.
        Serial.print("WARN: b > ");
        Serial.print(Y_BOUND_WARN, 2);
        Serial.println(" — the clip will start compressing the intermediate 0.35/0.65 plateaus, not just the 0/1 bound checks");
    }
    return true;
}

// ── Shared region walk ('Y' and 'W') ─────────────────────────────────────────────────────────
// One tick of the COMBINED_PROFILE[] region machine: advances the index at a region boundary and,
// on a normal tick, interpolates both axes and clips the share. Both combined profiles call this
// so their SHAPES are identical by construction — the whole point of reusing one table would be
// lost if each profile walked it with its own copy of the interpolation.
// `axisNormOut` is the raw NORMALISED motor axis ([0..1] from the table); the caller scales it by
// its own peak ('Y' → m/s, 'W' → A). `shareOut` is already clipped and ready to assign.
ComboTickResult advanceComboRegion(uint8_t &regionIdx, uint32_t &regionStart, const char *tag,
                                   float boundLo, float &axisNormOut, float &shareOut) {
    if (regionIdx >= COMBINED_PROFILE_REGIONS) return COMBO_TICK_DONE;

    uint32_t elapsed = millis() - regionStart;
    const CombinedProfileRegion &rg = COMBINED_PROFILE[regionIdx];

    if (elapsed >= rg.durationMs) {
        regionIdx++;
        regionStart = millis();
        if (regionIdx < COMBINED_PROFILE_REGIONS && !plotSuppressStatus()) {
            Serial.print("["); Serial.print(tag); Serial.print("] Region ");
            Serial.println(regionIdx);
        }
        return COMBO_TICK_BOUNDARY;
    }

    // Linear interpolation of BOTH axes within the region. A step between regions is encoded as
    // a start value differing from the previous region's end value, so it lands on the first tick
    // of the new region — no special-casing here.
    float t     = (float)elapsed / (float)rg.durationMs;
    axisNormOut = rg.v_start + t * (rg.v_end - rg.v_start);
    float s_abs = rg.s_start + t * (rg.s_end - rg.s_start);

    // Clip AFTER interpolation, never before: a ramp that crosses the bound must run at its
    // normal slope and then FLATTEN there. Pre-scaling the waypoints into the band would change
    // every slope in the table and quietly alter the excitation the identification is fitted to.
    // The resulting kink is intended behaviour.
    shareOut = constrain(s_abs, boundLo, 1.0f - boundLo);
    return COMBO_TICK_RUN;
}

// Commit the two validated operator values and take exclusive ownership of the motor output.
// Called only from parseCombinedParamsLine() (both values already range-checked there).
// Preconditions (bring-up idle, calibrated velocity chain, MOT_PWR_ENABLE HIGH) are the 'Y'
// handler's responsibility — they are checked at the keypress so a refusal is seen before the
// operator types parameters, and nothing that reaches the input buffer can invalidate them.
void startCombinedProfile(float vmax, float boundLo) {
    // Exclusive motor ownership, same discipline as the 'D'/'R'/'T' start paths: clear every
    // other motor driver, flush a zero + clear the manual modes and the PI integrator
    // (haltMotorOutput()), then reset the rate limiters so the first profile tick drives
    // immediately. Without the halt, a manual current set with 'A' before 'Y' would survive the
    // run and re-assert itself the instant the profile ends.
    driveCycleActive        = false;
    powerShareProfileActive = false;
    trapProfileActive       = false;
    trapCmdA                = 0.0f;
    tsweepCancel("superseded by 'Y'");   // a queued sweep owns the share setpoint this profile
                                         // sweeps, and would fire a run into it at dwell expiry
    wProfileActive          = false;   // the current-mode twin — mutually exclusive both ways
    wCmdA                   = 0.0f;
    haltMotorOutput();
    resetControlRateLimiters();
    resetShareControlState();     // known share-loop state per run (2026-08-11)

    yProfileVmax    = vmax;
    yProfileBoundLo = boundLo;

    combinedProfileActive = true;
    combinedRegionIdx     = 0;
    combinedRegionStart   = millis();
    combinedStatusLast    = millis();
    // Open the SD log AFTER the flags/region index are set, so the very first logged sample
    // already carries region 0 in both phase bytes (not LOG_PHASE_NONE). The PS|DC mask is what
    // gives the file its "YP" prefix and tells the decoder the two phase bytes are one axis.
    logOpenForProfile(LOG_TYPE_PS | LOG_TYPE_DC);

    Serial.print("[YP] Combined profile started — Vmax=");
    Serial.print(yProfileVmax, 2);
    Serial.print("m/s share band=[");
    Serial.print(yProfileBoundLo, 2);
    Serial.print(", ");
    Serial.print(1.0f - yProfileBoundLo, 2);
    Serial.print("] regions=");
    Serial.print(COMBINED_PROFILE_REGIONS);
    Serial.println("  (Region 0: settle; 'Y' again to stop)");
    // Motor ceiling quoted for the cutoff warning is the velocity PI's own current clamp — the
    // most the bus switch can be asked to open against on this profile.
    warnIfBandReachesCutoff("YP", yProfileBoundLo, "Y 0.5 0.2", MOTOR_I_CMD_MAX, "");
    if (vescWatchActive)
        Serial.println("[YP] VESC watch paused during the run (production-identical timing); resumes on stop");
}

// One profile tick. Same phase-machine structure as advanceDriveCycle()/advancePowerShareProfile(),
// but supplies BOTH setpoints; the real control functions in doState98() do the driving.
void advanceCombinedProfile() {
    if (combinedRegionIdx >= COMBINED_PROFILE_REGIONS) {
        combinedProfileActive = false;
        power_share_setpoint  = 0.5f;   // return to balanced, as advancePowerShareProfile() does
        // Natural completion releases the motor EXACTLY as the 'Y' stop path does — a completion
        // path that only cleared its own flag would leave a pre-run manualMotorMode driving the
        // motor from the standalone branch on the next tick (design-review-2026-07-28.md P0-2).
        // Switches are deliberately left as-is here, matching the 'D'/'R' NATURAL completions
        // (only their stop-toggle/'X' paths park them).
        haltMotorOutput();
        // Put a still-latched channel cutoff back on the bus BEFORE the run is declared over —
        // otherwise nothing ever calls applyShareRatio() again (see restoreShareCutoffOnCompletion).
        restoreShareCutoffOnCompletion("YP");
        logRequestClose(LOG_CLOSE_COMPLETE);   // symmetric with the 'Y' stop path
        Serial.println("[YP] Combined profile complete — motor zeroed, share back to 0.50");
        return;
    }

    float v_norm = 0.0f, share = 0.0f;
    if (advanceComboRegion(combinedRegionIdx, combinedRegionStart, "YP", yProfileBoundLo,
                           v_norm, share) != COMBO_TICK_RUN)
        return;   // region boundary this tick (or the table just ran out — caught at the top of
                  // the NEXT tick by the completion block above, exactly as before the refactor)

    v_setpoint           = v_norm * yProfileVmax;   // normalised table value -> m/s
    power_share_setpoint = share;                   // already clipped to [b, 1-b] by the helper

    // Status snapshot every 500 ms — both axes at once (withheld under plot mode, same reason as
    // the other profiles: a non-numeric line breaks the plotter parse).
    if (!plotSuppressStatus() && millis() - combinedStatusLast >= 500) {
        combinedStatusLast = millis();
        float totalA    = fabsf(I_fc) + fabsf(I_batt);
        float share_act = (totalA > 1e-6f) ? (fabsf(I_fc) / totalA) : 0.0f;
        Serial.print("[YP] t=");      Serial.print(millis());
        Serial.print(" R");           Serial.print(combinedRegionIdx);
        Serial.print(" v_sp=");       Serial.print(v_setpoint, 2);
        Serial.print(" sp=");         Serial.print(power_share_setpoint, 3);
        Serial.print(" act=");        Serial.print(share_act, 3);
        Serial.print(" I_fc=");       Serial.print(I_fc, 2);
        Serial.print(" I_bt=");       Serial.print(I_batt, 2);
        Serial.print(" V_bus=");      Serial.print(V_bus, 2);
        Serial.print(" FLT=0x");      Serial.println(fault_flags, HEX);
    }
}

// ── Combined CURRENT + power-share profile ('W') ─────────────────────────────────────────────
// Parse the single-line parameter entry "[Imax A] [share bound b]" (e.g. typed as one line
// "W 6 0.0"). BOTH values are optional — a bare newline runs the defaults, same as 'Y' (and
// unlike the trapezoid, where an empty line is a cancel).
void parseCurrentComboParamsLine(const char* line) {
    float imax  = W_IMAX_DEFAULT;
    float bound = Y_BOUND_DEFAULT;   // shared bound default — see the 'W' state block

    if (!parseTwoOptionalFloats(line, "ERROR: expected \"W [Imax A] [b]\" — at most two values (e.g. W 6 0.0) — profile cancelled",
                                imax, bound))
        return;

    if (imax <= 0.0f) {
        // Unlike the trapezoid, a NEGATIVE peak is not meaningful here: the table's motor column
        // is a normalised magnitude with its own coast-down back to zero, so a negative peak would
        // simply mirror the whole profile into braking rather than test anything new (use 'T' for
        // a braking/regen ramp). Zero is a null test.
        Serial.println("ERROR: Imax must be > 0 A — profile cancelled");
        return;
    }
    // Reuse the TRAPEZOID's ceiling, not MOTOR_I_CMD_MAX: this profile commands VESC phase current
    // directly through the same chokepoint 'T' uses, and the rationale at TRAP_I_ABS_MAX applies
    // unchanged — the 5 A figure is a source-power budget on the velocity-PI paths, while the hard
    // bound that always applies is the ESC's own rating. Peaks above MOTOR_I_CMD_MAX are therefore
    // accepted here exactly as 'T' accepts them.
    if (imax > TRAP_I_ABS_MAX) {
        Serial.print("ERROR: Imax must be <= ");
        Serial.print(TRAP_I_ABS_MAX, 0);
        Serial.println(" A (TRAP_I_ABS_MAX, the VESC Six EDU continuous rating) — profile cancelled");
        return;
    }
    if (!validateShareBound(bound)) return;

    startCurrentComboProfile(imax, bound);
}

// Commit the two validated operator values and take exclusive ownership of the motor output.
// Called only from parseCurrentComboParamsLine() (both values already range-checked there).
// Deliberately NO velocityChainCalibrated() gate and no hard MOT_PWR_ENABLE gate — this profile
// drives current directly, bypassing the velocity PI, which is exactly what makes it safe on an
// encoder-less bench (same policy as 'T'; the 'W' handler warns about MOT_PWR).
void startCurrentComboProfile(float imax, float boundLo) {
    // Exclusive motor ownership, same discipline as every other profile start: clear the other
    // motor drivers, flush a zero + clear the manual modes and the PI integrator, then reset the
    // rate limiters so the first profile tick drives immediately.
    driveCycleActive        = false;
    powerShareProfileActive = false;
    trapProfileActive       = false;
    trapCmdA                = 0.0f;
    combinedProfileActive   = false;   // the velocity twin — mutually exclusive both ways
    tsweepCancel("superseded by 'W'");   // same reason as 'Y': it owns the share setpoint and
                                         // would fire a trapezoid into this run at dwell expiry
    haltMotorOutput();
    resetControlRateLimiters();
    resetShareControlState();     // known share-loop state per run (2026-08-11)

    wProfileImax    = imax;
    wProfileBoundLo = boundLo;

    wProfileActive = true;
    wRegionIdx     = 0;
    wRegionStart   = millis();
    wStatusLast    = millis();
    wCmdA          = 0.0f;
    // Open the SD log AFTER the flags/region index are set, so the very first logged sample
    // already carries region 0 in both phase bytes. The PS|TP mask gives the file its "WP" prefix
    // (share axis + current axis) and tells the decoder which two phase bytes carry the region.
    logOpenForProfile(LOG_TYPE_PS | LOG_TYPE_TP);

    Serial.print("[WP] Combined current profile started — Imax=");
    Serial.print(wProfileImax, 2);
    Serial.print("A share band=[");
    Serial.print(wProfileBoundLo, 2);
    Serial.print(", ");
    Serial.print(1.0f - wProfileBoundLo, 2);
    Serial.print("] regions=");
    Serial.print(COMBINED_PROFILE_REGIONS);
    Serial.println("  (Region 0: settle; 'W' again to stop)");
    // Here the ceiling is the operator's own Imax: this profile commands phase current directly,
    // so the switch opens against whatever peak was just committed.
    warnIfBandReachesCutoff("WP", wProfileBoundLo, "W 2 0.2", wProfileImax, "Imax=");
    if (vescWatchActive)
        Serial.println("[WP] VESC watch paused during the run (production-identical timing); resumes on stop");
}

// One profile tick. Walks the SAME region table as advanceCombinedProfile() through the shared
// helper, but scales the motor axis into amps and issues it directly — the velocity PI is never
// in the loop (contrast 'Y', which only supplies v_setpoint for motorControl()).
void advanceCurrentComboProfile() {
    if (wRegionIdx >= COMBINED_PROFILE_REGIONS) {
        wProfileActive       = false;
        wCmdA                = 0.0f;
        power_share_setpoint = 0.5f;   // return to balanced, as the 'Y'/'R' completions do
        // Natural completion releases the motor EXACTLY as the 'W' stop path does — a completion
        // path that only cleared its own flag would leave a pre-run manualMotorMode driving the
        // motor from the standalone branch on the next tick (design-review-2026-07-28.md P0-2).
        // Switches are left as-is here, matching the 'Y'/'D'/'R' NATURAL completions (only their
        // stop-toggle/'X' paths park them).
        haltMotorOutput();
        // Same end-of-run cutoff restore as 'Y' — see restoreShareCutoffOnCompletion().
        restoreShareCutoffOnCompletion("WP");
        logRequestClose(LOG_CLOSE_COMPLETE);   // symmetric with the 'W' stop path
        Serial.println("[WP] Combined current profile complete — motor zeroed, share back to 0.50");
        return;
    }

    float i_norm = 0.0f, share = 0.0f;
    if (advanceComboRegion(wRegionIdx, wRegionStart, "WP", wProfileBoundLo,
                           i_norm, share) != COMBO_TICK_RUN)
        return;   // region boundary this tick; the table running out is caught at the top of the
                  // next tick by the completion block above

    float cmd            = i_norm * wProfileImax;   // normalised table value -> A
    wCmdA                = cmd;
    power_share_setpoint = share;                   // already clipped to [b, 1-b] by the helper
    // v_setpoint is deliberately NOT touched — this profile has no velocity axis at all, and
    // writing it would leave a stale setpoint behind for whatever runs next (same as 'T').

    // Rate-gated on rl_motor_last / MOTOR_CTRL_PERIOD_US and sent through the same chokepoint the
    // trapezoid uses: the shared limiter guarantees this and motorControl() can never both write
    // the VESC in one tick, and the 500 Hz re-sends keep the VESC's 1000 ms command timeout fed
    // (on expiry it COASTS rather than brakes, which would silently truncate the profile).
    if (rateLimitDue(rl_motor_last, MOTOR_CTRL_PERIOD_US))
        commandMotorCurrentLimited(cmd, TRAP_I_ABS_MAX);   // ESC-rating ceiling, not MOTOR_I_CMD_MAX

    // Status snapshot every 500 ms — both axes at once (withheld under plot mode, same reason as
    // the other profiles: a non-numeric line breaks the plotter parse).
    if (!plotSuppressStatus() && millis() - wStatusLast >= 500) {
        wStatusLast = millis();
        float totalA    = fabsf(I_fc) + fabsf(I_batt);
        float share_act = (totalA > 1e-6f) ? (fabsf(I_fc) / totalA) : 0.0f;
        Serial.print("[WP] t=");      Serial.print(millis());
        Serial.print(" R");           Serial.print(wRegionIdx);
        Serial.print(" I_cmd=");      Serial.print(wCmdA, 2);
        Serial.print(" sp=");         Serial.print(power_share_setpoint, 3);
        Serial.print(" act=");        Serial.print(share_act, 3);
        Serial.print(" I_fc=");       Serial.print(I_fc, 2);
        Serial.print(" I_bt=");       Serial.print(I_batt, 2);
        Serial.print(" V_bus=");      Serial.print(V_bus, 2);
        Serial.print(" FLT=0x");      Serial.println(fault_flags, HEX);
    }
}

// True for chars that belong in a typed numeric value (digits, sign, point, and whitespace fillers).
// Anything else, seen while a prompt is pending, cancels the entry (handled in doState98()).
bool isNumericEntryChar(char c) {
    return (c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+' || c == ' ' || c == '\t';
}

// Punctuation of the trapezoid sweep list "[t,r1,…,rn]" (2026-08-11). Not folded into
// isNumericEntryChar(): these three keys must keep cancelling every OTHER pending prompt, which is
// what stops an unexpected keystroke from being silently absorbed into an un-echoed value.
bool isSweepListChar(char c) {
    return c == '[' || c == ']' || c == ',';
}

// Accumulate a typed numeric line (set up by a value command key), then dispatch on newline. Keeps
// the input non-blocking so detectFaults() runs every tick while the operator types. Only numeric
// chars and the line terminator reach here — doState98() filters out (and cancels on) other keys.
void handlePendingInputChar(char c) {
    if (c == '\n' || c == '\r') {
        inputBuf[inputBufIdx] = '\0';
        float val = atof(inputBuf);
        PendingInput which = pendingInput;
        pendingInput = PEND_NONE;
        inputBufIdx  = 0;
        // The combined profile is the ONE prompt whose parameters are all optional, so a bare
        // newline means "run the defaults" — it must be dispatched BEFORE the shared empty-line
        // cancel below (which is right for every other prompt: none of them has a default).
        if (which == PEND_Y_PARAMS) {
            parseCombinedParamsLine(inputBuf);
            return;
        }
        if (which == PEND_W_PARAMS) {   // same all-optional grammar as 'Y'
            parseCurrentComboParamsLine(inputBuf);
            return;
        }
        if (inputBuf[0] == '\0') {
            Serial.println("(no value entered — cancelled)");
            return;
        }
        switch (which) {
            case PEND_POWER_SHARE:
                setPowerShareSetpointLive(val);
                Serial.print("power_share_setpoint -> "); Serial.print(power_share_setpoint, 3);
                Serial.println(" (closed-loop live)");
                break;
            case PEND_OPEN_DROOP:
                applyOpenLoopDroop(val);
                Serial.print("open-loop share ratio -> "); Serial.print(constrain(val, 0.0f, 1.0f), 3);
                if (shareIsoFC)      Serial.print(" (FC cut off the bus; BT gain held)");
                else if (shareIsoBT) Serial.print(" (BT cut off the bus; FC gain held)");
                Serial.print(" (gFC="); Serial.print(droop_gain_FC_actual, 3);
                Serial.print(" gBT="); Serial.print(droop_gain_BT_actual, 3); Serial.println(")");
                break;
            case PEND_MOTOR_CURRENT:
                setManualMotorCurrent(val);
                if (!digitalRead(MOT_PWR_ENABLE)) {
                    Serial.println("WARN: MOT_PWR_ENABLE is LOW — command set but motor unpowered (key '3')");
                }
                Serial.print("manual motor current -> "); Serial.print(manualMotorCurrent, 2);
                Serial.println(" A");
                break;
            case PEND_MOTOR_VELOCITY:
                setManualMotorVelocity(val);
                if (!digitalRead(MOT_PWR_ENABLE)) {
                    Serial.println("WARN: MOT_PWR_ENABLE is LOW — command set but motor unpowered (key '3')");
                }
                Serial.print("manual motor velocity -> "); Serial.print(manualMotorVelocity, 2);
                Serial.println(" m/s");
                break;
            case PEND_TRAP_PARAMS:
                // All three values on one line; `val` (atof of the whole buffer) is ignored.
                parseTrapParamsLine(inputBuf);
                break;
            default:
                break;
        }
    } else if (inputBufIdx < (uint8_t)(sizeof(inputBuf) - 1)) {
        inputBuf[inputBufIdx++] = c;
    }
}

void printTestStatus() {
    Serial.println("=== State 98 Status ===");
    Serial.print("FW_VERSION:         "); Serial.println(FW_VERSION);
    Serial.print("FC_REG_ENABLE:      "); Serial.println(digitalRead(FC_REG_ENABLE));
    Serial.print("BT_REG_ENABLE:      "); Serial.println(digitalRead(BT_REG_ENABLE));
    Serial.print("FC_BUS_ENABLE:      "); Serial.println(digitalRead(FC_BUS_ENABLE));
    Serial.print("BT_BUS_ENABLE:      "); Serial.println(digitalRead(BT_BUS_ENABLE));
    Serial.print("MOT_PWR_ENABLE:     "); Serial.println(digitalRead(MOT_PWR_ENABLE));
    Serial.print("REGEN_ENABLE:       "); Serial.println(digitalRead(REGEN_ENABLE));
    Serial.print("FC_CHARGE_ENABLE:   "); Serial.println(digitalRead(FC_CHARGE_ENABLE));
    Serial.print("BT_SEQUENCE_ENABLE: "); Serial.println(digitalRead(BT_SEQUENCE_ENABLE));
    Serial.print("CBAL_DISABLE:       "); Serial.println(digitalRead(CBAL_DISABLE));
    Serial.print("MPPT_DISABLE:       "); Serial.println(digitalRead(MPPT_DISABLE));
    Serial.print("CHARGER_STAT:       "); Serial.println(digitalRead(CHARGER_STAT));
    Serial.print("charger_powered:    "); Serial.println(chargerHasPower());
    Serial.print("ag105Configured:    "); Serial.println(ag105Configured);
    Serial.println("--- ADC ---");
    Serial.print("V_fc=");   Serial.print(V_fc,   3); Serial.print("V  ");
    Serial.print("V_batt="); Serial.print(V_batt, 3); Serial.print("V  ");
    Serial.print("V_bus=");  Serial.println(V_bus, 3);
    Serial.print("V_chg=");  Serial.print(V_chg, 3); Serial.print("V  ");
    Serial.print("V_rgn=");  Serial.println(V_rgn, 3);
    Serial.print("I_fc=");   Serial.print(I_fc,   3); Serial.print("A  ");
    Serial.print("I_batt="); Serial.println(I_batt, 3);
    Serial.print("I_charge="); Serial.print(I_charge, 3); Serial.println("A (Ag105 I2C)");
    // ── Encoder (fw v8) ───────────────────────────────────────────────────────────────────────
    // Added because `v_actual` was the ONLY encoder observable and it collapses three distinct
    // failures into one 0.000. Read this block top-down:
    //   ENC_ENABLE 0            -> optical sensors unpowered; nothing downstream can work.
    //   A=/B= never change       -> the MCU sees no valid logic transitions on that channel
    //                              (dead emitter/phototransistor, broken wire, or a phototransistor
    //                              swing that never crosses V_IL/V_IH — a scope can show "a signal"
    //                              the Teensy still reads as a constant level).
    //   edges A>0, B==0 (or v/v) -> one channel is dead; the x2 decoder needs BOTH, so encoderPos
    //                              stays 0 with a live signal on the other channel.
    //   edges A>0, B>0, pos==0   -> both channels live but NOT in quadrature (beams aligned or a
    //                              whole slot-pitch apart). The decoder's "first" flags are never
    //                              satisfied, so it counts nothing.
    //   pos moving, v_act 0.000  -> only then is the fault in updateWheelSpeed()/the scale chain.
    // Counters are diagnostic only; nothing in the control path reads them.
    Serial.println("--- Encoder ---");
    Serial.print("ENC_ENABLE="); Serial.print(digitalRead(ENC_ENABLE));
    Serial.print("  A=");        Serial.print(digitalRead(ENC_A));
    Serial.print(" B=");         Serial.println(digitalRead(ENC_B));
    noInterrupts();
    int32_t  encSnap  = encoderPos;
    uint32_t edgeSnapA = encEdgeCountA;
    uint32_t edgeSnapB = encEdgeCountB;
    interrupts();
    Serial.print("encoderPos=");  Serial.print(encSnap);
    Serial.print("  edges A=");   Serial.print(edgeSnapA);
    Serial.print(" B=");          Serial.println(edgeSnapB);
    Serial.print("v_actual=");    Serial.print(v_actual, 3);
    Serial.print(" m/s  (counts/rev="); Serial.print(ENCODER_COUNTS_PER_REV, 0);
    Serial.print(", r=");               Serial.print(FLYWHEEL_RADIUS_M, 4);
    Serial.println(" m)");
    Serial.print("fault_flags=0x"); Serial.println(fault_flags, HEX);
    Serial.print("error_code=0x");  Serial.print(error_code, HEX);
    Serial.print(" (");             Serial.print(errorCodeStr(error_code));
    Serial.println(")");
    Serial.print("error_source_state="); Serial.println(error_source_state);
    Serial.println("--- bench tools ---");
    Serial.print("bringup:            ");
    if (bringupActive) { Serial.print("ACTIVE phase="); Serial.println(bringupPhase); }
    else               { Serial.println("idle"); }
    Serial.print("OV transients:      "); Serial.println(ovBusTransientCount);
    // UV counterpart (2026-08-12): the dropout-dip counter is the only externally-visible trace of
    // a bus sag that never latched, and the armed flag says whether the check is live at all.
    Serial.print("UV transients:      "); Serial.print(uvBusTransientCount);
    Serial.print(uvBusArmed ? "  (armed)" : "  (disarmed — no matched switch+boost pair, bring-up, or bus never up)");
    // fw v5: the leaky dwell is the actual latch state — a non-zero dwell with zero latch says a
    // repetitive dropout cycle is being accumulated right now (UV_BUS_DWELL_LATCH_MS to go).
    Serial.print("  dwell="); Serial.print(uvBusDwellMs, 1);
    Serial.print("/"); Serial.print(UV_BUS_DWELL_LATCH_MS, 1); Serial.print(" ms");
    Serial.println();
    // FC source-rail counterpart (fw v6): same three facts — transient count, armed/disarmed, live
    // dwell. "disarmed" here most often means no fuel cell is connected at all, which is the
    // normal single-source bench topology, so the reason text names that case first.
    // NOTE (fw v6 review S6): in State 99 these values are FROZEN at their latch-time readings —
    // detectFaults() keeps running, but a latched board is a post-mortem, so "armed" here means
    // "was armed", same as the bus filter's line above.
    Serial.print("UV_FC transients:   "); Serial.print(fcUvTransientCount);
    Serial.print(fcUvArmed ? "  (armed)" : "  (disarmed — FC pair open, bring-up, or V_fc never seen healthy)");
    Serial.print("  dwell="); Serial.print(fcUvDwellMs, 1);
    Serial.print("/"); Serial.print(UV_FC_DWELL_LATCH_MS, 1); Serial.print(" ms");
    Serial.print(", latest excursion "); Serial.print(fcUvLastExcursionMs); Serial.print(" ms");
    Serial.println();
    Serial.print("share sp-cut latch: ");
    Serial.println(shareSpCutFC ? "FC" : (shareSpCutBT ? "BT" : "none"));
    // fw v5: which share-loop MODE is running, and the filtered total current that decides it —
    // the operator needs to know whether a run's droop split came from the Youla controller or
    // from the open-loop setpoint feedforward before reading anything into its share trace.
    Serial.print("share loop mode:    ");
    Serial.print(shareClosedLoopMode ? "CLOSED"
                                     : (shareClosedLoopRun ? "OPEN (hold)" : "OPEN (feedforward)"));
    Serial.print("  I_tot_filt="); Serial.print(share_govTotAFilt, 3);
    Serial.print(" A, enter>"); Serial.print(2.0f * SHARE_MINORITY_I_MIN_A, 2);
    Serial.println(" A");
    Serial.print("manualMotorMode:    ");
    Serial.println(manualMotorMode == MOTOR_TEST_OFF      ? "OFF"
                 : manualMotorMode == MOTOR_TEST_CURRENT  ? "CURRENT"
                 :                                          "VELOCITY");
    Serial.print("manual I/V cmd:     "); Serial.print(manualMotorCurrent, 2); Serial.print("A / ");
    Serial.print(manualMotorVelocity, 2); Serial.println(" m/s");
    Serial.print("power_share_setpt:  "); Serial.println(power_share_setpoint, 3);
    Serial.print("powerBalanceLive:   "); Serial.println(powerBalanceLive);
    Serial.print("droop gFC/gBT:      "); Serial.print(droop_gain_FC_actual, 3);
    Serial.print(" / "); Serial.println(droop_gain_BT_actual, 3);
    Serial.print("powerShareProfile:  "); Serial.println(powerShareProfileActive);
    // card=? until the probe has run (setup() probes on hardware; host tests may never call it).
    Serial.print("SD: card=");    Serial.print(!sdInitTried ? "?" : (sdAvailable ? "Y" : "N"));
    Serial.print(" file=");       Serial.print(logFileName[0] ? logFileName : "-");
    Serial.print(" rec=");        Serial.print(logActive ? logRecordsWritten : logLastRecordsWritten);
    Serial.print(" drop=");       Serial.print(logActive ? logDroppedCount : logLastDropped);
    Serial.print(" active=");     Serial.println(logActive ? "Y" : "N");
    Serial.print("plot stream ('L'):  ");
    Serial.println(plotModeActive ? "ON (status lines suppressed)" : "off");
    if (plotArmTarget != PLOT_ARM_NONE) {
        Serial.print("plot ARMED:         ");
        Serial.print(plotArmTarget == PLOT_ARM_SHARE ? "power-share" : "trapezoid");
        Serial.print(" in ");
        int32_t remain = (int32_t)(plotArmDeadlineMs - millis());
        Serial.print(remain > 0 ? remain : 0);
        Serial.println("ms");
    }
    Serial.print("trapProfile:        "); Serial.print(trapProfileActive);
    if (trapProfileActive) {
        Serial.print(" ph=");     Serial.print(trapPhaseStr(trapPhase));
        Serial.print(" I_cmd=");  Serial.print(trapCmdA, 2);
        Serial.print("A Imax=");  Serial.print(trapImax, 2);
        Serial.print("A rate=");  Serial.print(trapRateAps, 2);
        Serial.print("A/s hold="); Serial.print(trapHoldMs); Serial.print("ms");
    }
    Serial.println();
    // Sweep line: between runs NOTHING else in this dump shows that more runs are queued
    // (trapProfileActive is false and the logger is idle), which is exactly when an operator asks
    // "is it done?".
    Serial.print("TSWEEP:             ");
    if (!tsweepActive) {
        Serial.println("inactive");
    } else {
        Serial.print("run ");      Serial.print(tsweepIdx + 1);
        Serial.print("/");         Serial.print(tsweepCount);
        Serial.print(" phase ");   Serial.print(tsweepPhase);
        Serial.print(tsweepPhase == 0 ? " (RUNNING)" : tsweepPhase == 1 ? " (WAIT_LOG)" : " (COOLDOWN)");
        Serial.print(" dwell ");   Serial.print(tsweepDwellMs); Serial.println("ms");
    }
    Serial.print("driveCycle:         "); Serial.print(driveCycleActive);
    if (driveCycleActive) { Serial.print(" phase="); Serial.print(driveCyclePhaseIdx); }
    Serial.println();
    // The 'Y' start banner scrolls away behind the 500 ms status lines, so 'S' is the only way to
    // confirm which parameters were actually COMMITTED (as opposed to typed). Printed whenever a
    // combined run has been started this power cycle — yProfileVmax/yProfileBoundLo hold the last
    // committed pair after the run ends, which is exactly what a post-run readback needs.
    Serial.print("combinedProfile:    "); Serial.print(combinedProfileActive);
    if (combinedProfileActive) { Serial.print(" R="); Serial.print(combinedRegionIdx); }
    Serial.print(" Vmax=");     Serial.print(yProfileVmax, 2);
    Serial.print("m/s band=["); Serial.print(yProfileBoundLo, 2);
    Serial.print(", ");         Serial.print(1.0f - yProfileBoundLo, 2);
    Serial.println("]");
    // Same readback rationale as the 'Y' line above: the start banner scrolls away, so 'S' is the
    // only way to confirm the COMMITTED parameters (they hold the last committed pair after the
    // run ends, which is exactly what a post-run readback needs).
    Serial.print("currentCombo (W):   "); Serial.print(wProfileActive);
    if (wProfileActive) {
        Serial.print(" R=");     Serial.print(wRegionIdx);
        Serial.print(" I_cmd="); Serial.print(wCmdA, 2); Serial.print("A");
    }
    Serial.print(" Imax=");     Serial.print(wProfileImax, 2);
    Serial.print("A band=[");   Serial.print(wProfileBoundLo, 2);
    Serial.print(", ");         Serial.print(1.0f - wProfileBoundLo, 2);
    Serial.println("]");
    Serial.println("=======================");
}


// ═════════════════════════════════════════════════════════════════════════════
// CONTROL FUNCTIONS
// ═════════════════════════════════════════════════════════════════════════════

// Enforces mutual-exclusion rule before asserting FC_CHARGE_ENABLE.
// BT_BUS_ENABLE and REGEN_ENABLE must be LOW before FC_CHARGE_ENABLE may go HIGH.
void assertFcChargeEnable(bool enable) {
    if (enable) {
        // S2 ORDERING (2026-08-12) — restore FC to the bus BEFORE cutting BT. If the share
        // setpoint latch has FC off the bus (sp < DROOP_R_MIN), BT is the ONLY live source;
        // dropping it below would darken the bus with MOT_PWR still closed, freeze the share
        // loop on the stale latch, and disarm FAULT_UV_BUS along with it (a dark bus disarms).
        // The charging path is a deliberate state action and outranks the share loop's claim —
        // the same ownership precedence as the BT-side clears below — and routing FC → charger
        // is meaningless with FC off the bus in the first place.
        // SCOPED to the share loop's own claim (shareSpCutFC/shareIsoFC), NOT to "FC_BUS reads
        // LOW" generally: doState99() phase 0 opens both bus switches and then calls this
        // function to drain VBUS into the charger, and an unscoped restore would re-energize the
        // bus during an error teardown. Only the share loop's latch is overridden here.
        if ((shareSpCutFC || shareIsoFC) && digitalRead(FC_BUS_ENABLE) == LOW) {
            shareIsoFC   = false;
            shareSpCutFC = false;
            digitalWrite(FC_BUS_ENABLE, HIGH);
        }
        // Cut BT contribution to VBUS first, then close regen path, then open FC→charger path
        digitalWrite(BT_BUS_ENABLE, LOW);    // disconnect BT from VBUS before routing FC → charger
        // BT_BUS is now owned by the charge path: clear any share-controller
        // isolation claim on it, or applyShareRatio()'s re-entry would close
        // BT_BUS while FC_CHARGE is HIGH — the illegal switch combination.
        // The setpoint latch is cleared with it (2026-08-12): a stale latch
        // would freeze the whole share loop for as long as the charge path
        // holds BT_BUS, and its entry guard (both switches HIGH) already
        // prevents it from re-claiming BT_BUS while FC_CHARGE is asserted.
        shareIsoBT   = false;
        shareSpCutBT = false;
        digitalWrite(REGEN_ENABLE,  LOW);    // close regen path before routing FC → charger
        delayMicroseconds(100);              // RT1987 turn-off propagation — confirmed sufficient
        digitalWrite(FC_CHARGE_ENABLE, HIGH);
    } else {
        digitalWrite(FC_CHARGE_ENABLE, LOW);
    }
}

// Parks every RT1987 path switch in its safe (LOW) state and inhibits the MPPT loop.
// Used by the State 98 'D'-stop so a cycle halted mid-phase doesn't leave REGEN/FC_CHARGE/etc
// latched. BT_SEQUENCE_ENABLE is left HIGH (per design it stays sequenced in once raised), and
// the boost regulators (FC/BT_REG) are left under explicit operator control via 'F'/'B'. With
// the boosts still enabled there is no disabled-converter back-feed path, so LOW-ing order here
// is not safety-critical; FC_CHARGE is still dropped through its guard for consistency.
// Dropping MOT_PWR_ENABLE here is also fine under the staged bring-up doctrine (2026-08-03): a
// later reconnect is refused unless the bus is in regulation (motPwrConnectBlocked()) and is
// CSS-controlled via D-MT-EN's soft-start, so there is no hot-plug hazard from cutting it mid-test.
void safeAllSwitches() {
    assertFcChargeEnable(false);          // close FC→charger path via the guard
    digitalWrite(REGEN_ENABLE,   LOW);
    digitalWrite(BT_BUS_ENABLE,  LOW);
    digitalWrite(FC_BUS_ENABLE,  LOW);
    digitalWrite(MOT_PWR_ENABLE, LOW);
    digitalWrite(MPPT_DISABLE,   LOW);    // inhibit MPPT (active-LOW)
    // The bus switches are now open by state action, not by the share
    // controller -- clear the cutoff flags so applyShareRatio() will not
    // "re-enter" a switch it no longer owns. The setpoint latches go with them
    // (2026-08-12): they are a strict subset of the same ownership claim, and a
    // latch surviving a teardown would freeze the share loop on the next run.
    shareIsoFC   = false;
    shareIsoBT   = false;
    shareSpCutFC = false;
    shareSpCutBT = false;
}

// ── Staged bring-up machine ──────────────────────────────────────────────────
// Shared by production doState0() (doInit=true) and the State-98 'G' command (doInit=false —
// peripherals are already live in State 98; re-running initControlPeripherals() there would
// re-init the ESC/MDACs mid-session). Non-blocking: callers tick it once per loop so
// detectFaults() keeps sampling. Sequence + rationale at the "STAGED BRING-UP" constants block;
// bench basis in docs/boost-bringup-debug.md (captures 5–9). Still use a STIFF supply on the
// bench: a source that collapses under the soft-start draw sags VBT and browns out the
// board-powered Teensy (motorboating), and no supply current limit bounds the boost's internal
// ½·L·di² energy.

// Arm the machine. Returns false (no-op) if already running — callers refuse/report.
bool busBringupStart() {
    if (bringupActive) return false;
    bringupActive = true;
    bringupPhase  = 0;
    return true;
}

// Internal: fail the bring-up. Machine state is cleared BEFORE faulting so the hardware phase
// state can't leak into the next arm (and tests stay isolated); triggerFault() then latches
// State 99, whose teardown extinguishes any invisible parked boost.
static BringupStatus busBringupFail(const char* msg, uint16_t fault_bit, ErrorCode_t err) {
    bringupActive = false;
    bringupPhase  = 0;
    Serial.print("[bringup] FAIL: "); Serial.println(msg);
    triggerFault(fault_bit, err);
    return BRINGUP_FAILED;
}

BringupStatus busBringupTick(bool doInit) {
    if (!bringupActive) return BRINGUP_IDLE;

    uint32_t now = millis();
    switch (bringupPhase) {
        case 0:
            // P0 entry — start from a KNOWN-DARK power stage (adversarial review 2026-08-03,
            // F1): a boost left enabled by a manual 'F'/'B' would otherwise be hot-plugged onto
            // the discharged bus by the switch closes below (the exact busHotPlugUnsafe() class
            // the '1'/'2' keys refuse), and a latched FC_CHARGE would form the illegal
            // BT_BUS+FC_CHARGE combination (whose fault is compiled out under BENCH_TEST).
            // Ordering: paths closed first (regen/charge), then boosts off (never leave a regen
            // path pointed into a disabled boost), then MOT_PWR actively LOW (a hanging node
            // would ride the P1 ramp and recreate the SCP-cut/18V-park event), then the bus
            // switches close onto disabled boosts (body-diode pre-charge path only).
            assertFcChargeEnable(false);
            digitalWrite(REGEN_ENABLE,   LOW);
            digitalWrite(FC_REG_ENABLE,  LOW);
            digitalWrite(BT_REG_ENABLE,  LOW);
            digitalWrite(MOT_PWR_ENABLE, LOW);
            digitalWrite(FC_BUS_ENABLE,  HIGH);   // switches first — RT1987s soft-start the bus
            digitalWrite(BT_BUS_ENABLE,  HIGH);   //   to ~max(V_fc, V_batt) via body-diode path
            // S6 (2026-08-12): the bring-up takes OWNERSHIP of the whole topology, so no share-
            // loop isolation claim may survive it. Both switches are now closed by state action;
            // a latch left set here would be orphaned (frozen share loop with both channels on
            // the bus) from a nominally-safe 'G'.
            shareIsoFC   = false;
            shareIsoBT   = false;
            shareSpCutFC = false;
            shareSpCutBT = false;
            bringupPhaseStart = now;
            bringupPhase = 1;
            Serial.println("[bringup] P0: stage darkened; bus switches closed (MOT_PWR held LOW)");
            break;

        case 1: {
            // P0 gate — bus must reach the winning source (relative gate), be above the absolute
            // floor (a dead source reading ~0 must not vacuously pass), and the RT1987 must have
            // had time to fully ENHANCE (~28ms measured at 100nF; voltage alone can be met
            // through a half-enhanced FET). TIMEOUT IS CHECKED FIRST in every phase (review F2):
            // with a free-running, uninstrumented loop a stalled tick can land past the deadline
            // with the gate freshly true — the deadline must still win (deterministic fault, not
            // a late accept).
            if ((now - bringupPhaseStart) > PRECHARGE_TIMEOUT_MS) {
                return busBringupFail("bus pre-charge never completed (switch/source dead?)",
                                      FAULT_INIT_FAIL, ERR_INIT_FAIL);
            }
            float vSrc = (V_fc > V_batt) ? V_fc : V_batt;
            bool gate = (now - bringupPhaseStart) >= PRECHARGE_MIN_MS &&
                        V_bus >= (vSrc - PRECHARGE_DROP_MAX) &&
                        V_bus >= V_PRECHARGE_MIN;
            if (gate) {
                digitalWrite(FC_REG_ENABLE, HIGH);   // boosts ramp the bus via their own soft-start
                digitalWrite(BT_REG_ENABLE, HIGH);
                digitalWrite(BT_SEQUENCE_ENABLE, HIGH);   // battery-pack sequencing in once powered
                if (doInit) initControlPeripherals();
                bringupPhaseStart = now;
                bringupPhase = 2;
                Serial.println("[bringup] P1: bus pre-charged; boosts enabled");
            }
            break;
        }

        case 2:
            // P1 gate — boosts must bring the bus into regulation. (Timeout first — review F2.)
            if ((now - bringupPhaseStart) > BUS_CHARGE_TIMEOUT_MS) {
                return busBringupFail("VBUS failed to reach charge threshold (dead boost/no source)",
                                      FAULT_INIT_FAIL, ERR_INIT_FAIL);
            }
            if (V_bus >= V_BUS_CHARGED_THRESH) {
                bringupDwellStart = now;
                bringupPhaseStart = now;
                bringupPhase = 3;
                Serial.println("[bringup] P2: bus in regulation band; dwell");
            }
            break;

        case 3:
            // P2 dwell — regulation must HOLD for BUS_REG_DWELL_MS continuous before the motor
            // node is offered the bus; a dip restarts the dwell, the overall timeout bounds a
            // restart livelock. (Timeout first — review F2.)
            if ((now - bringupPhaseStart) > BUS_DWELL_TIMEOUT_MS) {
                return busBringupFail("bus regulation would not hold through the dwell",
                                      FAULT_INIT_FAIL, ERR_INIT_FAIL);
            }
            if (V_bus < V_BUS_CHARGED_THRESH) bringupDwellStart = now;
            if ((now - bringupDwellStart) >= BUS_REG_DWELL_MS) {
                bringupPhase = 4;
            }
            break;

        case 4:
            // P3 entry — connect the motor node from the regulated bus through the guard. A
            // refusal means the bus collapsed between the dwell pass and this tick: fail
            // deterministically rather than looping back to P2 (livelock).
            if (!assertMotPwrEnable(true)) {
                return busBringupFail("bus fell out of regulation before motor-node connect",
                                      FAULT_INIT_FAIL, ERR_INIT_FAIL);
            }
            bringupPhaseStart = now;
            bringupPhase = 5;
            Serial.println("[bringup] P3: MOT_PWR closed — motor node charging");
            break;

        case 5:
            // P3 gate — the motor node must come up to the bus (CSS soft-start ~30ms; window
            // covers ≥2 RT1987 SCP 64ms retry cycles, cf. capture 9's ~83ms completion).
            // (Timeout first — review F2.) The bus must ALSO still be in regulation (review F3):
            // relative tracking alone would accept a connect that dragged the bus down with it
            // (e.g. 16→12.5V with V_rgn at 9.5V "tracking" within margin) — that is not a healthy
            // completion, and under BENCH_TEST the Run UV fault that would later catch it is
            // compiled out. A sagged bus simply keeps this gate false until it recovers or the
            // timeout faults.
            if ((now - bringupPhaseStart) > MOT_CONNECT_TIMEOUT_MS) {
                return busBringupFail("motor node never tracked the bus (D-MT-EN/SCP-retry stuck?)",
                                      FAULT_MOT_HOTPLUG, ERR_MOT_HOTPLUG);
            }
            if (V_bus >= V_BUS_CHARGED_THRESH && V_rgn >= (V_bus - MOT_HOTPLUG_MARGIN)) {
                bringupActive = false;
                bringupPhase  = 0;               // self-reset for the next arm
                Serial.println("[bringup] DONE: bus + motor node up");
                return BRINGUP_DONE;
            }
            break;
    }
    return BRINGUP_RUNNING;
}

// Abort a running bring-up and leave the power stage DARK. Merely stopping the machine is not
// enough: a mid-P1 SCP-cut can leave a boost parked at ~18V upstream of the (cut) switch —
// invisible to the ADC — so the boosts and switches come down too. Ordering: motor node first
// (isolate the regen path), then boosts, then bus switches (RT1987s block reverse, so a live bus
// briefly facing disabled boosts has no back-feed path). Used by State-98 'X' and 'Q'.
void busBringupAbort() {
    if (!bringupActive) return;
    bringupActive = false;
    bringupPhase  = 0;
    digitalWrite(MOT_PWR_ENABLE, LOW);
    digitalWrite(FC_REG_ENABLE,  LOW);
    digitalWrite(BT_REG_ENABLE,  LOW);
    digitalWrite(FC_BUS_ENABLE,  LOW);
    digitalWrite(BT_BUS_ENABLE,  LOW);
    // S6 (2026-08-12): both switches are open by state action — the bring-up owns the topology,
    // so clear every share-loop claim. A latch surviving the abort would freeze the share loop
    // on the next run (same argument as safeAllSwitches()).
    shareIsoFC   = false;
    shareIsoBT   = false;
    shareSpCutFC = false;
    shareSpCutBT = false;
    Serial.println("[bringup] ABORTED — power stage dark");
}

// True when turning a *_BUS_ENABLE switch ON would hot-plug a RUNNING boost onto a discharged bus.
// (Historical note: this was once believed to be what killed the BT boosts; the validated root
// cause was the BT output-cap hot loop, fixed in hardware — see docs/boost-bringup-debug.md. The
// guard is kept as cheap defense: a hot-plug step is still a needless load transient.) We can't
// sense the boost output directly, so "boost ON (regPin HIGH) AND bus below the charged threshold"
// is the available proxy. Used by the State 98 '1'/'2' handlers to refuse the unsafe toggle (use
// 'G' for a safe bring-up instead).
bool busHotPlugUnsafe(int regPin) {
    return digitalRead(regPin) == HIGH && V_bus < V_BUS_CHARGED_THRESH;
}

// True when turning MOT_PWR_ENABLE (D-MT-EN: VBUS → V-MOT/VESC) ON must be refused. DOCTRINE
// (2026-08-03 — INVERTS the Death-5 rule; renamed from motPwrHotPlugUnsafe(), whose predicate was
// the exact opposite): the motor node may be connected ONLY from a bus already in its regulation
// band. There the D-MT-EN 100nF-CSS soft-start charges the 470µF + VESC stack from the charged
// bus + boosts — the connect class validated on the bench (captures 5 deep-dip / 9 dip-2,
// docs/boost-bringup-debug.md). Refused otherwise: a dark- or partially-charged-bus connect
// leaves the node hanging on the chain, and the boosts' later ramp then drives the RT1987 into
// its foldback clamp >250µs → SCP cut + 64ms retry, with the cut-release parking the boost
// output at ~18V — ABOVE the TPS61288 recommended max and invisible to the firmware ADC (the
// cut switch isolates the node). Note the old "V_rgn lagging V_bus" term is gone from the
// refusal: a discharged node at a regulated bus is precisely the sanctioned P3 connect. V_rgn
// tracking V_bus is instead the COMPLETION criterion (busBringupTick() P3 gate).
// HARDWARE PREREQUISITE for this doctrine: 100nF CSS fitted on D-MT-EN.
bool motPwrConnectBlocked() {
    return V_bus < V_BUS_CHARGED_THRESH;
}

// Guarded control of MOT_PWR_ENABLE. Turning OFF is always allowed. Turning ON is idempotent when
// already ON, and otherwise REFUSED unless the bus is in its regulation band
// (motPwrConnectBlocked()) — the CSS-controlled connect from a regulated bus is the only
// sanctioned way to bring the node from discharged to connected (busBringupTick() P3, or a
// manual State-98 '3' at a regulated bus). Returns false iff an ON was refused.
bool assertMotPwrEnable(bool enable) {
    if (!enable) { digitalWrite(MOT_PWR_ENABLE, LOW); return true; }
    if (digitalRead(MOT_PWR_ENABLE) == HIGH) return true;   // already on — idempotent, no re-check
    if (motPwrConnectBlocked()) return false;                // refuse: bus not in regulation
    digitalWrite(MOT_PWR_ENABLE, HIGH);
    return true;
}

// ── Motor current chokepoint ─────────────────────────────────────────────────
// THE ONLY place in the firmware that calls vesc.setCurrent(). Every motor command — UDP velocity
// (motorControl), State-98 manual current, State-98 manual velocity, the drive cycle, the
// power-share profile, and all the safety zero-flushes — routes through here so the ceiling is
// unbypassable.
//
// Two guarantees:
//   1. Non-finite in → 0 A out. motorConstant is still an uncalibrated TODO (the velocity unit
//      chain was measured in fw v7); a NaN/Inf reaching COMM_SET_CURRENT serializes as a garbage
//      int32 the VESC would act on. Commanding 0 is the only safe interpretation of "I don't know
//      what to command".
//   2. |amps| ≤ MOTOR_I_CMD_MAX. The PI integrator anti-windup bound alone did NOT bound the
//      command: the proportional term is added after it, so a large velocity error passed straight
//      through to a 50 A bridge.
// `current` mirrors what was actually sent (post-clamp), so telemetry and the State-98 status dump
// report the real command rather than the pre-clamp intent, and a zero-flush clears it rather than
// leaving a stale value visible to the Pi.
void commandMotorCurrent(float amps) {
    commandMotorCurrentLimited(amps, MOTOR_I_CMD_MAX);
}

// Same chokepoint guarantees (non-finite → 0 A; `current` mirrors the post-clamp send) with a
// caller-chosen ceiling. Exists for the State-98 trapezoid, whose ceiling is the ESC hardware
// rating (TRAP_I_ABS_MAX) rather than the velocity-path source budget (MOTOR_I_CMD_MAX) — phase
// current does not map 1:1 onto bus draw, and on the bench the VESC may have its own supply.
// Every vesc.setCurrent() in the firmware still funnels through here (P0-3 discipline intact).
void commandMotorCurrentLimited(float amps, float absMax) {
    if (!isfinite(amps)) amps = 0.0f;
    current = constrain(amps, -absMax, absMax);
    vesc.setCurrent(current);
}

void motorControl() {
    targetMotorTorque = PI_Controller_Motor(v_setpoint - v_actual);
    commandMotorCurrent(targetMotorTorque / motorConstant);
}

// Rate-gated wrappers — see the "Control-loop rate limiting" block for the periods and rationale.
// A skipped call is a zero-order hold: the VESC latches the last setCurrent(), the MDACs hold their
// last written codes, and the PI integrators keep their own sampleTime gating, so nothing decays.
void motorControlGated()    { if (rateLimitDue(rl_motor_last,    MOTOR_CTRL_PERIOD_US))    motorControl(); }
void chargingControlGated() { if (rateLimitDue(rl_charging_last, CHARGING_CTRL_PERIOD_US)) chargingControl(); }
void powerBalanceGated()    { if (rateLimitDue(rl_power_last,    POWER_BAL_PERIOD_US))     powerBalance(); }

float PI_Controller_Motor(float error) {
    const float Kp = 1.0f;
    const float Ki = 1.0f;

    // The integrator updates at most once per sampleTime window, but the output is ALWAYS
    // computed live. The old form returned a 0.0f sentinel on sub-sampleTime ticks — and since
    // motorControl() runs every loop tick, that sentinel chopped the VESC current command to
    // zero between samples. (Same fix applied to PI_Controller_Power, where the sentinel
    // slammed the droop split to the 0.01 extreme on gated ticks.)
    uint32_t now = micros();
    uint32_t dtMicros = now - pi_motor_lastMicros;
    if (dtMicros >= (uint32_t)sampleTime) {
        pi_motor_lastMicros = now;
        pi_motor_accum += error * dtMicros * 1e-6f;
        // Anti-windup: clamp the integrator so a sustained error (stalled setpoint, or a VESC that
        // saturates at MOTOR_I_CMD_MAX) cannot wind pi_motor_accum up without bound. The bound is the
        // torque equivalent of the motor current ceiling (output = torque; current = torque/motorConstant),
        // divided by Ki so the integral term Ki*accum stays within ±(MOTOR_I_CMD_MAX * motorConstant).
        const float integMax = (MOTOR_I_CMD_MAX * motorConstant) / Ki;
        pi_motor_accum = constrain(pi_motor_accum, -integMax, integMax);
    }
    return Kp * error + Ki * pi_motor_accum;
}

// Limit-cycle-mitigation state (2026-08-11). File-scope for host-test
// resettability, same pattern as the PIs.
//   share_govTotAFilt — governor's filtered |I_fc|+|I_batt| (see powerBalance()).
//   droopSlew_prev    — last droop ratio actually applied to the MDACs (see
//                       applyShareRatio()); 0.5 matches the fresh-boot MDAC
//                       state commanded by initMdacOutputs().
//   shareClosedLoopMode — the share loop is currently running CLOSED loop (fw v5;
//                       hysteretic on share_govTotAFilt, see powerBalance()).
//   shareClosedLoopRun  — the closed loop has run at least once since the last
//                       resetShareControlState(); decides whether the open-loop
//                       mode feeds the setpoint forward or simply HOLDS.
//   share_actedSp     — the setpoint the loop last ACTED on (S3 review fix): a
//                       commanded setpoint change must not be swallowed by the
//                       HOLD branch, so it re-arms the feedforward path.
//   share_spEffPrev   — the EFFECTIVE setpoint the closed-loop controller was
//                       last given as its REFERENCE (fw v6). Slew-limited toward
//                       the governor-clipped target so the OL→CL handover cannot
//                       step the reference discontinuously; see powerBalance().
float share_govTotAFilt = 0.0f;
float droopSlew_prev    = 0.5f;
bool  shareClosedLoopMode = false;
bool  shareClosedLoopRun  = false;
float share_actedSp       = 0.5f;
float share_spEffPrev     = 0.5f;
// Deadband on that comparison: the setpoint is a commanded float (Pi packet, operator 'P', a
// profile's interpolation), never a measurement, so anything above float round-off is a real
// command change. Kept explicit so a profile that interpolates the setpoint every tick is not
// mistaken for noise.
const float SHARE_SP_CHANGE_EPS = 1e-4f;

// ── Setpoint-latched channel cutoff ("one owner per setpoint", 2026-08-12) ───
// EVIDENCE (fw v3 validation sweep TP0014–TP0038; docs/share_sweep_whitepaper):
// before this function existed, an out-of-band *setpoint* had no owner. The
// setpoint governor deliberately bypasses setpoints outside
// [DROOP_R_MIN, DROOP_R_MAX], and the channel cutoff in applyShareRatio() fires
// on the CONTROLLER OUTPUT r, not on the setpoint. Two gaps followed:
//   - TP0037 (setpoint 0.87): the loop settles at r ≈ 0.84, which is INSIDE the
//     droop band, so the cutoff never fired and the governor never clipped —
//     neither mitigation engaged and the run limit-cycled at 19.5 Hz.
//   - TP0015 (setpoint 0.12): the cutoff DID fire, but the standing share error
//     (topology pins the measured share at the opposite rail) wound the
//     controller output back across the SHARE_CUTOFF_HYST = 0.01 re-entry
//     threshold, so the channel re-entered, starved, and cut again — ~190
//     FC_BUS_ENABLE cycles per run at ~20 Hz.
// FIX: the SETPOINT decides the cutoff, and it LATCHES. Every setpoint now has
// exactly one owner: in-band → the governor; out-of-band → this latch. While a
// channel is setpoint-cut the share controller is frozen (not stepped at all —
// TP0015's hunting was integrator-driven re-entry, so the integrator must not
// see the standing error) and the ratio-hysteresis re-entry for that channel is
// disabled. Only a setpoint change back inside the band releases it.
//
// Returns true while a setpoint latch is active, i.e. the caller must freeze the
// whole share loop this tick.
static bool updateShareSetpointCutoff() {
    float sp = power_share_setpoint;
    bool  releasedThisTick = false;

    // Deferral flags are PER-TICK DERIVED (fw v6 review S1): cleared here, set only by the entry
    // block below when the handoff guard alone blocked the cut. Every early return from this
    // function therefore leaves them false, which is correct — a latched, released, or
    // guard-blocked-for-another-reason tick has no deferral outstanding.
    shareCutDeferredFC = false;
    shareCutDeferredBT = false;

    // ── S1 SELF-HEAL (2026-08-12). A latch is a claim of OWNERSHIP over a bus
    // switch, and that claim is only true while the switch is actually open. If
    // the switch reads HIGH again, somebody else re-closed it (a state action,
    // an operator key, a re-assert path the guards above missed) — the latch is
    // now ORPHANED, and holding it would freeze the share loop indefinitely with
    // both channels on the bus and every mitigation inoperative. Drop the flags
    // and fall through to normal governed control: a stale latch must degrade to
    // LIVE control, never to a frozen loop. Deliberately no resetShareControlState()
    // here — the controller was frozen, not diverged, and the governor should see
    // the recovered topology immediately.
    if (shareSpCutFC && digitalRead(FC_BUS_ENABLE) == HIGH) {
        shareSpCutFC = false;
        shareIsoFC   = false;
    }
    if (shareSpCutBT && digitalRead(BT_BUS_ENABLE) == HIGH) {
        shareSpCutBT = false;
        shareIsoBT   = false;
    }
    // Same self-heal for a RATIO-based cutoff claim with no setpoint latch behind it (S1,
    // 2026-08-12 fw v5 safety review). shareIsoFC/BT is equally a claim of ownership over an OPEN
    // switch: doState2() re-asserts FC_BUS/BT_BUS gated on !shareSpCutFC only, so a re-assert can
    // leave the switch HIGH with shareIso* still set — and applyShareRatio() returns early before
    // EVERY MDAC write while shareIso* is set, so an orphaned claim silently freezes the droop
    // split for the rest of the run. Drop the orphan; the cutoff re-fires through the normal
    // entry path on the next tick if the ratio still calls for it.
    if (shareIsoFC && digitalRead(FC_BUS_ENABLE) == HIGH) shareIsoFC = false;
    if (shareIsoBT && digitalRead(BT_BUS_ENABLE) == HIGH) shareIsoBT = false;

    // ── Release (evaluated FIRST, so a setpoint that flips from one side of the
    // band to the other releases this side before the other side may latch —
    // the two latches are never set simultaneously). The re-close is subject to
    // the same charged-bus guard as applyShareRatio()'s re-entry: closing a
    // running-but-unloaded boost onto a bus that is NOT in regulation is the
    // hot-plug direction. If the bus is low the latch is HELD (the loop stays
    // frozen) and the re-close is retried on the next tick.
    if (shareSpCutFC && sp >= DROOP_R_MIN) {
        // S5 (2026-08-12): the boost must also be ENABLED. Closing a bus switch onto a DISABLED
        // TPS61288 is the back-feed direction of CLAUDE.md §2 — never point a live bus at a
        // disabled converter. If the boost is off (operator 'F', a teardown), HOLD the latch and
        // retry next tick rather than re-closing.
        if (V_bus >= V_BUS_CHARGED_THRESH && digitalRead(FC_REG_ENABLE) == HIGH) {
            // Re-close FC onto a regulated bus; BT is still HIGH (the entry
            // guard proved it), so the bus is never left unsourced mid-swap.
            digitalWrite(FC_BUS_ENABLE, HIGH);
            shareIsoFC       = false;   // topology claim released with the latch
            shareSpCutFC     = false;
            releasedThisTick = true;
            // Restart the controller clean: it has been frozen against a
            // topology-pinned measurement, and droopSlew_prev (untouched
            // throughout) still holds the ratio physically on the MDACs, so the
            // first post-release write walks from the true hardware state.
            // fw v5 (S9): this also zeroes share_govTotAFilt, so under load the
            // loop runs OPEN-LOOP FEEDFORWARD at the released setpoint for the
            // ~20-40 ms the EMA needs to climb back past 2*SHARE_MINORITY_I_MIN_A
            // - slew-limited, no controller step. Intended: the alternative is
            // stepping a just-reset controller against a topology that changed
            // this very tick.
            resetShareControlState();
        }
    } else if (shareSpCutBT && sp <= DROOP_R_MAX) {
        // S5 (2026-08-12): BT boost must be enabled too — mirror of the FC branch above.
        if (V_bus >= V_BUS_CHARGED_THRESH && digitalRead(BT_REG_ENABLE) == HIGH) {
            // Re-close BT onto a regulated bus; FC is still HIGH (entry guard).
            // MUTUAL EXCLUSION NOTE (2026-08-12, safety review): BT_BUS HIGH is illegal while
            // FC_CHARGE_ENABLE is HIGH. This re-close is safe because chargingControl() runs
            // BEFORE powerBalance() in every caller (doState2()'s gated call order, the State-98
            // profiles' control-call set), so an FC-charge tick has already cleared shareSpCutBT
            // via assertFcChargeEnable(true) and this branch cannot be reached with FC_CHARGE
            // asserted. Any future caller MUST preserve that ordering.
            digitalWrite(BT_BUS_ENABLE, HIGH);
            shareIsoBT       = false;
            shareSpCutBT     = false;
            releasedThisTick = true;
            resetShareControlState();   // fw v5 (S9): ~20-40 ms of open-loop
                                        // feedforward follows - see the FC branch
        }
    }

    // A release tick returns the loop to normal control for at least one tick
    // before the opposite latch may engage, so the freshly reset controller and
    // the governor both see one live sample of the new topology.
    if (releasedThisTick) return false;

    // ── Entry. Only from the fully-released state (never both channels), and
    // only as a closed→open transition this function itself performs: the
    // LAST-SOURCE GUARD (both bus switches HIGH) is identical to the r-based
    // cutoff's — the share loop must never darken the bus, and it must never
    // claim ownership of a switch the operator or a state action opened. When
    // the guard blocks, do NOT latch: fall through to normal governed control so
    // droop authority stays live (same fallback as applyShareRatio()).
    //
    // LOAD-AWARE HANDOFF GUARD (fw v6, 2026-08-12; SHARE_CUT_MAX_HANDOFF_A). The cut is a
    // one-tick step transfer of the DOOMED channel's whole current onto the survivor. WP0097 /
    // WP0101 fired it with 1.3–1.5 A on the doomed channel; the survivor was pushed past its
    // source knee (~2.1 A on this bench) and the bus collapsed in ~40 ms (ERR_UV_BUS). The same
    // cut at ~0 A is validated clean (TP0074/85/86/87 run-start latches). So the latch is
    // additionally gated on the doomed channel's MEASURED current being small enough that the
    // survivor can absorb it in one step.
    //
    // BLOCKED → DEFERRED, not abandoned (fw v6 review S1). The tick sets shareCutDeferredFC/BT and
    // falls through to live governed control, and that flag does two things elsewhere:
    //   - powerBalance() clips the controller REFERENCE from the out-of-band setpoint onto the
    //     doomed side's band edge (DROOP_R_MIN / DROOP_R_MAX) before the governor's floor clip, so
    //     the loop actively migrates load OFF the doomed channel toward the survivor. Without that
    //     clip the reference stays out of band (the governor's floor clip is in-band-gated) and no
    //     migration happens at all;
    //   - applyShareRatio() suppresses its own r-based cutoff on that side, because that cutoff
    //     has NO current guard and would otherwise execute the refused handoff a few ticks later
    //     under the wrong ownership flag (see the shareCutDeferred* block comment).
    // The cut then fires here on a later tick, once the migration has pulled the doomed channel's
    // current under the threshold.
    //
    // RESIDUAL (accepted, fw v6): at high total current the migration may NEVER get the doomed
    // channel under the threshold — the band edge is a droop command, and at the droop rail it
    // cannot starve the channel further. The loop then sits at the band edge and runs the
    // rail-saturated dropout cycle instead of cutting. That cycle is self-limiting and does not
    // collapse the bus (it is the pre-latch fw v3 behaviour at an in-band setpoint), whereas the
    // cut at 1.3-1.5 A demonstrably does. Accepted until the floor law is reworked
    // (fraction-vs-absolute, next round).
    if (!shareSpCutFC && !shareSpCutBT) {
        if (sp < DROOP_R_MIN) {
            if (digitalRead(FC_BUS_ENABLE) == HIGH &&
                digitalRead(BT_BUS_ENABLE) == HIGH) {
                if (fabsf(I_fc) <= SHARE_CUT_MAX_HANDOFF_A) {
                    digitalWrite(FC_BUS_ENABLE, LOW);   // BT stays HIGH and keeps its
                                                        // droop gain — the bus feed is
                                                        // handed over, never dropped
                    shareIsoFC   = true;   // topology owner (telemetry/status truth)
                    shareSpCutFC = true;   // latched by the setpoint
                } else {
                    // Wanted, refused on load only — deferred (see above). Deliberately NOT set
                    // when the last-source guard is what blocked: that fall-through predates
                    // fw v6 and keeps its existing semantics.
                    shareCutDeferredFC = true;
                }
            }
        } else if (sp > DROOP_R_MAX) {
            if (digitalRead(BT_BUS_ENABLE) == HIGH &&
                digitalRead(FC_BUS_ENABLE) == HIGH) {
                if (fabsf(I_batt) <= SHARE_CUT_MAX_HANDOFF_A) {
                    digitalWrite(BT_BUS_ENABLE, LOW);   // FC stays HIGH and keeps its
                                                        // droop gain (see above)
                    shareIsoBT   = true;
                    shareSpCutBT = true;
                } else {
                    shareCutDeferredBT = true;          // mirror of the FC branch
                }
            }
        }
    }

    return shareSpCutFC || shareSpCutBT;
}

void powerBalance() {
    // Setpoint-latched cutoff owns every out-of-band setpoint (2026-08-12). It is
    // evaluated BEFORE the minimum-load gate and before the governor: the release
    // path must run even at standstill, or a run that ends at an extreme setpoint
    // would leave the board single-sourced until the next teardown. While latched
    // the ENTIRE share loop is frozen — no governor, no controller step, no MDAC
    // write — so the standing (topology-forced) share error can never wind the
    // controller back over the re-entry hysteresis (TP0015).
    if (updateShareSetpointCutoff()) return;

    float totalA = fabsf(I_fc) + fabsf(I_batt);
    // Minimum-load gate (was a bare 1e-6 divide-by-zero guard): below
    // SHARE_I_TOT_MIN_A the measured share is undefined-in-practice, so hold
    // EVERYTHING -- no Youla/PI controller step (their integrator and filter
    // states freeze, since youlaController_Power()/PI_Controller_Power() are
    // simply not called), and the droop MDACs keep the last commanded split,
    // which is the correct starting point for the next launch. On the first
    // tick back above threshold the Youla wrapper's Ts gate has long expired,
    // so the controller resumes immediately with the fresh measurement.
    if (totalA < SHARE_I_TOT_MIN_A) return;

    // Governor load estimate (filtered so ADC noise doesn't dither the bounds).
    // Updated only on ticks that reach here — below SHARE_I_TOT_MIN_A the whole
    // loop is frozen, so the filter correctly resumes from its pre-hold value.
    share_govTotAFilt += SHARE_GOV_FILT_ALPHA * (totalA - share_govTotAFilt);

    // ── Loop-mode decision: closed loop vs open-loop feedforward (fw v5) ──────
    // EVIDENCE (fw v4 validation sweep TP0041–TP0068): the governor's old
    // collapse-to-0.5 fallback IGNITED the failure it existed to prevent. Below
    // 2·SHARE_MINORITY_I_MIN_A it forced sp_eff = 0.5, which at 0.075–0.60 A of
    // filtered total commands 0.038–0.30 A PER CHANNEL — at or below the very
    // 0.30 A conduction floor the constant enforces — against only ~20 mV of
    // droop authority at those currents. Six runs source-commutation relayed,
    // collapsed the bus to 7–9 V and latched ERR_UV_BUS. A closed loop cannot
    // be asked to hold a split it has neither the authority nor the conduction
    // to realize, so below the threshold the controller is NOT RUN AT ALL.
    // Hysteresis (SHARE_GOV_OL_HYST_A) keeps a total current sitting on the
    // threshold from chattering between the two modes.
    if (!shareClosedLoopMode) {
        if (share_govTotAFilt > 2.0f * SHARE_MINORITY_I_MIN_A) {
            shareClosedLoopMode = true;
            // OPEN→CLOSED seed: restart the controller from the ratio physically
            // on the MDACs (droopSlew_prev) so its first output continues from
            // the held split instead of the 0.5 default — the same discipline as
            // the setpoint-latch release, which resets the controller and lets
            // the slew limiter walk from droopSlew_prev. Deliberately NOT
            // resetShareControlState(): that zeroes share_govTotAFilt, which
            // would drop the loop straight back into open-loop mode next tick.
            resetShareControllerCore(droopSlew_prev);
        }
    } else if (share_govTotAFilt < 2.0f * SHARE_MINORITY_I_MIN_A - SHARE_GOV_OL_HYST_A) {
        shareClosedLoopMode = false;
    }

    if (!shareClosedLoopMode) {
        // ── OPEN-LOOP mode ────────────────────────────────────────────────────
        // Case 1 — the closed loop has ALREADY run this profile: HOLD. No MDAC
        // write at all; droopSlew_prev (maintained by applyShareRatio()) keeps
        // the last physically-applied ratio, which is the settled split the
        // loop converged to before the load fell away. Re-commanding anything
        // here would slam the gains during a coast-down, the transient the slew
        // limiter and this whole mitigation family exist to remove.
        //
        // PRODUCTION SEMANTICS (State 2 cruise/regen, review-traced): a cruise or
        // regen window that drops the total below 0.55 A parks the split here.
        // chargingControl()/doState2() may re-close BT_BUS in that window; the
        // droop gains simply stay at the converged split until the load brings
        // the filtered total back over 0.60 A, at which point the controller
        // restarts seeded from that same split. Nothing re-commands the MDACs in
        // between — by design.
        //
        // TWO EXCEPTIONS to the hold (S1/S3, 2026-08-12 safety review):
        //   (a) an outstanding CONTROLLER-INITIATED cutoff (shareIsoFC/BT). The
        //       re-entry that re-closes that switch lives in applyShareRatio(),
        //       so a hold that never calls it strands the channel off the bus
        //       for the rest of the run — and doState2()'s re-assert (gated on
        //       !shareSpCutFC, not shareIsoFC) can then orphan the claim, which
        //       makes applyShareRatio() bail before every later MDAC write. Fall
        //       through to the feedforward path so the guarded re-entry keeps
        //       being evaluated.
        //   (b) a CHANGED setpoint. HOLD is about a load that fell away, not
        //       about ignoring commands: an EMS/operator setpoint change while
        //       parked must take effect at the NEW setpoint, open loop, rather
        //       than wait for the load to return.
        if (shareClosedLoopRun) {
            bool spChanged      = fabsf(power_share_setpoint - share_actedSp) > SHARE_SP_CHANGE_EPS;
            bool isoOutstanding = shareIsoFC || shareIsoBT;
            if (!spChanged && !isoOutstanding) return;   // HOLD
            // A changed setpoint re-arms the feedforward path (a still-outstanding
            // cutoff does NOT: once it clears, the hold resumes).
            if (spChanged) shareClosedLoopRun = false;
        }

        // Case 2 — no closed-loop authority yet this profile: FEEDFORWARD the
        // raw setpoint. The fw v4 sweep showed the commanded hold ratio tracks
        // the setpoint within ~0.01–0.02 across the band (whitepaper §6), so the
        // setpoint IS the correct open-loop map; what ignited the TP0053 relay
        // cycle was commanding an infeasible balanced 0.5 split at ~0.2 A total,
        // not the setpoint itself. The governor's minority-current clip does not
        // apply: with no controller running there is no loop to limit-cycle, and
        // the operator's setpoint is honoured as typed.
        // F1 (2026-08-12 fw v5 review): an OUT-OF-BAND setpoint is NEVER actuated here — the
        // setpoint latch owns it ("one owner per setpoint"), and this path must not act as a
        // second owner. The reachable case is the RELEASE tick: updateShareSetpointCutoff()
        // returns false on a release so the loop gets one live tick, and a setpoint that flipped
        // straight from one out-of-band side to the other (0.05 → 0.95) is still out of band on
        // that tick. Feeding it forward would hand applyShareRatio() an unslewed extreme ratio,
        // which fires the OPPOSITE channel's r-based cutoff immediately — defeating the one-live-
        // tick release the fw v4 latch was built for (TP0037/TP0015), and worse, claiming the cut
        // under shareIsoBT/FC instead of shareSpCutBT/FC. The external re-close guards
        // (chargingControl(), doState2()) key on shareSpCut*, so an shareIso*-claimed cut can be
        // re-closed by them and immediately re-cut here — switch cycling. Returning quietly leaves
        // exactly one idle tick, after which the latch's own entry branch claims the new side.
        if (power_share_setpoint < DROOP_R_MIN || power_share_setpoint > DROOP_R_MAX) return;

        // Same slew constraint and the same origin as the controller path below, so mode changes
        // are continuous on the MDACs.
        float target = constrain(power_share_setpoint,
                                 droopSlew_prev - DROOP_RATIO_SLEW_PER_TICK,
                                 droopSlew_prev + DROOP_RATIO_SLEW_PER_TICK);
        applyShareRatio(target);
        share_actedSp = power_share_setpoint;   // this tick acted on this setpoint (S3)
        return;
    }

    // ── CLOSED-LOOP mode ─────────────────────────────────────────────────────
    shareClosedLoopRun = true;
    share_actedSp      = power_share_setpoint;

    // ── Setpoint governor (limit-cycle mitigation, 2026-08-11) ────────────────
    // In-band setpoints ask the droop split to hold a live minority channel at
    // sp·I_tot (or (1−sp)·I_tot); below the light-load conduction floor that is
    // infeasible and the loop limit-cycles chasing it (TP0010/TP0013 — see the
    // SHARE_MINORITY_I_MIN_A block). Clip the EFFECTIVE setpoint so the commanded
    // minority current stays ≥ SHARE_MINORITY_I_MIN_A, relaxing to no clip as
    // load grows. OUT-OF-BAND setpoints (incl. 0.0 / 1.0) never reach here at
    // all: updateShareSetpointCutoff() above owns them and has already returned
    // (2026-08-12 — "one owner per setpoint"). Governing them would break the
    // full-span semantics, and the sweep showed the topology-forced share is
    // stable once the loop stops fighting it (TP0009/TP0011).
    // fw v5: the old collapse-to-0.5 else-branch is GONE — closed-loop mode is
    // only entered above 2·SHARE_MINORITY_I_MIN_A, so lo < 0.5 < hi always and
    // the collapse case is unreachable here. The open-loop mode above replaced
    // it (that fallback commanded a split below the conduction floor it was
    // enforcing, and ignited the TP0053 relay cycle).
    float spTarget = power_share_setpoint;

    // DEFERRED-CUT REFERENCE CLIP (fw v6 review S1). A deferral means the setpoint is OUT of band
    // (that is the only way to reach the latch entry) but the cut was refused on load. The
    // governor's floor clip below is in-band-gated, so without this the reference would stay
    // out of band, the controller would drive r out of band, and NO load migration would happen —
    // the deferral would merely hand the unguarded r-based cutoff the job a few ticks later.
    // Clipping onto the doomed side's band edge is the maximum droop authority that exists for
    // starving that channel, and it feeds the floor clip below a legal in-band value.
    // The deferral flags are per-tick derived by updateShareSetpointCutoff(), which ran at the top
    // of this function, so they describe THIS tick.
    if (shareCutDeferredFC || shareCutDeferredBT) {
        spTarget = constrain(spTarget, DROOP_R_MIN, DROOP_R_MAX);
    }

    if (spTarget >= DROOP_R_MIN && spTarget <= DROOP_R_MAX) {
        float lo = SHARE_MINORITY_I_MIN_A / share_govTotAFilt;
        // Ceiling at 0.5 for the HYSTERESIS SLIVER only: closed-loop mode is held down to
        // 2·I_min − SHARE_GOV_OL_HYST_A (0.55 A), where the raw bound would be lo = 0.545 > hi =
        // 0.455 — an INVERTED pair, and constrain(x, lo, hi) with lo > hi returns lo, i.e. it
        // would command the minority split on the WRONG side (0.25 A minority, below the floor).
        // Clamping lo to 0.5 makes the bound degenerate to the balanced split across that 0.05 A
        // sliver instead, which is the least-asymmetric feasible command while the loop is on its
        // way out to open-loop mode. Above 0.60 A (the entry threshold) this branch never fires.
        if (lo > 0.5f) lo = 0.5f;
        float hi = 1.0f - lo;
        spTarget = constrain(spTarget, lo, hi);
    }

    // ── Effective-setpoint slew (fw v6, 2026-08-12) ──────────────────────────
    // The OPEN→CLOSED handover used to STEP the controller's reference: open loop feeds the RAW
    // setpoint forward (the governor's clip is inert there — below 0.60 A the bound is
    // lo = I_min/tot ≥ 0.5, so clipping the feedforward would either do nothing or command the
    // very 0.5 split fw v5 deliberately deleted), while the first closed-loop tick hands the
    // controller the FLOOR-CLIPPED value. At the 0.60 A crossing that is a discontinuity of up to
    // 0.35 share (e.g. raw 0.15 → clipped 0.50) applied to the reference in one tick, right at the
    // load level where the sweep's failures live.
    // The fix wraps the REFERENCE, not the controller: share_spEffPrev walks toward the clipped
    // target at DROOP_RATIO_SLEW_PER_TICK (the same ceiling the actuation path uses, so reference
    // and actuation cannot disagree about how fast the split may move) and is what the controller
    // is given. constrain() lands EXACTLY on the target once within one step, so every converged
    // hold point is bit-identical to fw v5 — this changes handover transients only.
    // SECOND-ORDER EFFECT (fw v6 review S4): the slew applies to the governor's FLOOR CLIP too, so
    // inside closed-loop mode the clip is no longer instantaneous when the load DROPS. A load fall
    // that moves the bound by the full band (0.15 → 0.85 is the extreme) takes ~35 ticks of
    // reference walk, ~18 for a half-band move — monotonic, in the right direction, and one to two
    // orders of magnitude shorter than a dropout-cycle period (~50-60 ms), so the floor is still
    // reached long before the cycle it guards against could develop. Accepted deliberately: the
    // alternative is a step in the reference, which is the failure this whole change removes.
    share_spEffPrev = constrain(spTarget,
                                share_spEffPrev - DROOP_RATIO_SLEW_PER_TICK,
                                share_spEffPrev + DROOP_RATIO_SLEW_PER_TICK);
    float spEff = share_spEffPrev;

    float power_share_actual_local = fabsf(I_fc) / totalA;
    float shareError = spEff - power_share_actual_local;
#if USE_YOULA_SHARE_CONTROLLER
    // clamped to [0,1] + anti-windup; filters the measurement internally
    float droopRatio = youlaController_Power(spEff, power_share_actual_local);
    (void)shareError;
#else
    float droopRatio = PI_Controller_Power(shareError);
#endif

    // ── Ratio slew limit (limit-cycle mitigation, 2026-08-11) ────────────────
    // Bound the per-tick step of the CONTROLLER-commanded ratio so the MDAC
    // pair can never slam rail-to-rail in one write — the antiphase slam is
    // what drives the TP0010/TP0013 dropout/reconnect transients (see
    // DROOP_RATIO_SLEW_PER_TICK). The limiter walks from droopSlew_prev, the
    // ratio last physically applied to the MDACs by ANY path (applyShareRatio()
    // records it), so it stays continuous across profile resets and operator
    // 'O' jumps. Only ratios inside the droop band are slewed: an out-of-band
    // command passes through unlimited so the channel-cutoff decision in
    // applyShareRatio() sees the controller's true intent (the cutoff is a
    // topology action, not an MDAC write — slewing it would only delay the
    // hysteresis crossing while the gains sit pinned at the band edge anyway).
    if (droopRatio >= DROOP_R_MIN && droopRatio <= DROOP_R_MAX) {
        droopRatio = constrain(droopRatio,
                               droopSlew_prev - DROOP_RATIO_SLEW_PER_TICK,
                               droopSlew_prev + DROOP_RATIO_SLEW_PER_TICK);
    }

    // Full-span actuation (2026-08-10): commanded ratios span [0,1]; the
    // [DROOP_R_MIN, DROOP_R_MAX] physical-droop clip, the channel cutoff for
    // ratios outside it, and the re-entry hysteresis all live inside
    // applyShareRatio().
    applyShareRatio(droopRatio);
}

// ── Share-ratio actuation: droop mapping + channel cutoff ────────────────────
// Commanded share ratios r ∈ [0,1] are all valid (2026-08-10 design decision).
// The droop gain map g = K_DROOP/(RE_MAX·r) is only physical over
// [DROOP_R_MIN, DROOP_R_MAX] (g ≤ 1); OUTSIDE that band the starved channel is
// taken OFF THE BUS instead of clipping the split:
//   r < DROOP_R_MIN  →  open FC_BUS_ENABLE   (FC share commanded ~zero)
//   r > DROOP_R_MAX  →  open BT_BUS_ENABLE   (BT share commanded ~zero)
// while the still-active channel KEEPS its previous droop gain (no MDAC writes
// while a channel is isolated). Re-entry has SHARE_CUTOFF_HYST hysteresis so
// a ratio dithering at the boundary cannot chatter the bus switch.
//
// SAFETY — isolation is via the RT1987 bus switch, NEVER the boost enable: a
// disabled TPS61288 under an energized bus is the back-feed death mode (the
// doState3() keep-boosts-on doctrine). The boost keeps regulating unloaded, so
// re-entry closes a *running* regulator onto the already-charged bus — the
// safe direction of the hot-plug rule — and is additionally refused while
// V_bus < V_BUS_CHARGED_THRESH (same class of guard as busHotPlugUnsafe()).
//
// The flags record *controller-initiated* isolation only (shareIsoFC/BT,
// defined with the State-98 globals): this function never re-closes a switch
// the operator (State 98 '1'/'2') or a state transition opened. Manual
// bus-switch toggles and safeAllSwitches() clear the flags.
void applyShareRatio(float ratio) {
    float r = constrain(ratio, 0.0f, 1.0f);

    // LAST-SOURCE GUARD: a channel may be cut ONLY while the other channel's
    // bus switch is closed — the controller must never darken the bus. This
    // matters for the pathological-but-real case of a disconnected source:
    // e.g. BT off the bus pins the measured share at 1.0, a mid setpoint
    // then winds r toward 0, and an unguarded cutoff would take FC — the only
    // live source — off the bus too (min-load hold would then freeze the
    // whole loop with the bus dark). When the guard blocks a cutoff, fall
    // through to the band-edge clip instead, so droop authority stays live.

    // A cutoff fires only as a closed→open transition of a switch this
    // function itself opens: if the channel is ALREADY off the bus (operator
    // or state action), there is nothing to cut and no ownership to claim —
    // claiming it would make the later re-entry close a switch somebody else
    // opened (e.g. FC-charge cruise holds BT_BUS LOW; the controller must not
    // put the battery back on the bus from a share excursion).

    // DEFERRED-CUT SUPPRESSION (fw v6 review S1): while updateShareSetpointCutoff() has an
    // outstanding deferral on a side, this function's r-based cutoff for that side is suppressed.
    // The setpoint latch owns every out-of-band setpoint ("one owner per setpoint"), it refused
    // this exact cut on load, and the r-based cutoff has no current guard — letting it fire would
    // execute the refused 1.3-1.5 A handoff a few ticks later AND claim it as shareIso*, which the
    // external re-closers cannot see (they gate on !shareSpCut*), producing re-close/re-cut
    // cycling. The channel instead sits at its band-edge droop gain; that rail-saturated dropout
    // cycle is the documented accepted residual.
    // NOTE the flags are per-tick derived in updateShareSetpointCutoff(), so a ONE-SHOT caller of
    // this function (operator 'O', the guard fallback, the completion restore) reads at most one
    // powerBalance() tick of staleness — and reads it in the conservative direction: it may skip a
    // cut, never perform an unguarded one.

    // FC channel cutoff / re-entry
    if (!shareIsoFC && r < DROOP_R_MIN && !shareCutDeferredFC) {
        if (digitalRead(FC_BUS_ENABLE) == HIGH &&
            digitalRead(BT_BUS_ENABLE) == HIGH) {
            digitalWrite(FC_BUS_ENABLE, LOW);
            shareIsoFC = true;
        }
    } else if (shareIsoFC && !shareSpCutFC &&
               r >= DROOP_R_MIN + SHARE_CUTOFF_HYST &&
               V_bus >= V_BUS_CHARGED_THRESH &&
               digitalRead(FC_REG_ENABLE) == HIGH) {
        // FC_REG_ENABLE HIGH (S5, 2026-08-12 — pre-existing gap closed in the same pass as the
        // setpoint-latch release): re-entry must never point the energized bus at a DISABLED
        // TPS61288 (CLAUDE.md §2 back-feed rule). Boost off → stay isolated, retry next tick.
        // !shareSpCutFC (2026-08-12): while the SETPOINT holds the channel cut,
        // ratio hysteresis must not re-enter it. TP0015 hunted at ~20 Hz exactly
        // here — the standing share error wound r back over the 0.01 threshold
        // every cycle. Release is the setpoint's job (updateShareSetpointCutoff).
        digitalWrite(FC_BUS_ENABLE, HIGH);
        shareIsoFC = false;
    }

    // BT channel cutoff / re-entry
    if (!shareIsoBT && r > DROOP_R_MAX && !shareCutDeferredBT) {
        if (digitalRead(BT_BUS_ENABLE) == HIGH &&
            digitalRead(FC_BUS_ENABLE) == HIGH) {
            digitalWrite(BT_BUS_ENABLE, LOW);
            shareIsoBT = true;
        }
    } else if (shareIsoBT && !shareSpCutBT &&
               r <= DROOP_R_MAX - SHARE_CUTOFF_HYST &&
               V_bus >= V_BUS_CHARGED_THRESH &&
               digitalRead(BT_REG_ENABLE) == HIGH) {
        // !shareSpCutBT, and BT_REG_ENABLE HIGH (S5 back-feed guard) — mirror of the FC branch
        // above (2026-08-12).
        digitalWrite(BT_BUS_ENABLE, HIGH);
        shareIsoBT = false;
    }

    // While a channel is isolated the active one keeps its previous droop
    // gain -- the share is forced to 0 or 1 by topology, so there is nothing
    // for the droop split to do until both channels are back on the bus.
    if (shareIsoFC || shareIsoBT) return;

    // Both on the bus: physical-droop band clip + gain mapping. The clip is
    // the span where both MDAC gains stay ≤ 1 (g = K_DROOP/(RE_MAX·r); see
    // the K_DROOP block comment).
    float rc = constrain(r, DROOP_R_MIN, DROOP_R_MAX);

    // Record the ratio actually applied to the MDACs (limit-cycle mitigation,
    // 2026-08-11). The slew LIMITING lives in powerBalance() — the controller
    // path — not here: one-shot actuation paths (the State-98 'O' open-loop
    // command, the guard-blocked fallback above, the run-completion restore)
    // are deliberate operator/state actions that must land exactly where
    // commanded in a single call. This tracker is what the controller-path
    // limiter walks from, so a direct jump (e.g. 'O 0.2') is picked up as the
    // new starting point instead of leaving the limiter with a stale origin.
    droopSlew_prev = rc;

    droop_gain_FC_actual = K_DROOP / (RE_MAX * rc);
    droop_gain_BT_actual = K_DROOP / (RE_MAX * (1.0f - rc));
    setDroopMdac(droop_gain_FC_actual, droop_gain_BT_actual);
}

// ── Youla-H share controller wrapper ─────────────────────────────────────────
// Gates shareControllerStep() (share_controller.h) to its design cadence
// SHARE_CTRL_TS_US and holds the output between updates — powerBalance() runs
// every loop tick, but the difference equations must advance exactly once per
// Ts (the ZOH + latency is part of the design plant, system_model.md §6c).
// The measured share is prefiltered (200 Hz, part of the design plant); the
// setpoint is NOT filtered, so EMS commands are tracked unsmoothed.
// State is file-scope for host-test resettability (same pattern as the PIs).
float    shareCtrl_heldOut    = 0.5f;   // balanced split until the first update
uint32_t shareCtrl_lastMicros = 0;

// Reset the share-loop CONTROLLER state (Youla biquads + prefilter, held output,
// Ts gate, governor load filter) so a profile run starts from a known state
// instead of inheriting the previous run's — the 2026-08-11 sweep showed every
// run's entry transient was contaminated by the prior run's final state (only
// TP0007, fresh boot, started clean). Deliberately NOT reset:
//   droopSlew_prev — tracks the ratio physically on the MDACs, which the
//                    hardware holds across profiles; resetting it to mid-band
//                    would let the first post-reset write jump the gains by the
//                    full mid-band distance, exactly the slam the slew limiter
//                    exists to prevent.
//   shareIsoFC/BT  — cutoff/topology state is owned by applyShareRatio()'s
//                    hysteresis + the run-completion restore path.
//   shareSpCutFC/BT — the setpoint latch is owned by the SETPOINT
//                    (updateShareSetpointCutoff(), 2026-08-12). A profile that
//                    starts while the setpoint is out of band must keep the
//                    channel cut; releasing it here would re-close a switch the
//                    commanded setpoint still says must be open. This function
//                    is itself called from the release path, so clearing the
//                    latch here would also be self-referential.
// The Ts gate is back-dated (not zeroed) so the first governed tick steps the
// controller immediately — same idiom as resetControlRateLimiters().
// Controller-only restart (fw v5): biquads + prefilter + held output + Ts gate, with the held
// output SEEDED to a caller-chosen ratio. Factored out of resetShareControlState() so the
// open→closed loop-mode transition in powerBalance() can restart the controller from
// droopSlew_prev WITHOUT zeroing share_govTotAFilt — resetting the governor filter there would
// drop the loop straight back into open-loop mode on the next tick (the filter is the mode
// decision variable). Nothing here touches droopSlew_prev, the MDACs, or the latches.
void resetShareControllerCore(float seedRatio) {
    float seed = constrain(seedRatio, 0.0f, 1.0f);
    shareControllerReset();                 // biquads + measured-share prefilter
    // S5 (2026-08-12 fw v5 review): seed the INTEGRATOR, not just the held output. The controller
    // forms u = SHARE_CTRL_R0 + R(z)·e + I(z)·e with R0 = 0.5 fixed (share_controller.h), and the
    // Ts gate below is back-dated so the very first closed-loop tick recomputes u before
    // shareCtrl_heldOut is ever returned — a held-output seed alone is therefore DEAD, and the
    // first output would always be ≈0.5 regardless of where the MDACs actually sit. Offsetting the
    // integrator state by (seed − R0) moves the controller's DC operating point to the seed, so the
    // first output is seed + (transient terms in e) and the loop genuinely continues from the
    // held split. Anti-windup absorbs the excess if that lands outside [0,1]. Coefficients are
    // untouched — this only writes controller STATE, the same variable shareControllerReset()
    // zeroes. shareCtrl_heldOut is still seeded for the (test-visible) pre-first-tick read.
    shareCtrl_integ      = seed - SHARE_CTRL_R0;
    shareCtrl_heldOut    = seed;
    shareCtrl_lastMicros = micros() - (uint32_t)SHARE_CTRL_TS_US;
    // fw v6: the effective-setpoint reference is seeded from the SAME value, clipped into the
    // droop band. Every caller's seed is already the right continuity anchor:
    //   - the OPEN→CLOSED transition seeds droopSlew_prev, which IS what the feedforward last
    //     commanded (applyShareRatio() records the band-clipped ratio it wrote), so the reference
    //     starts where the hardware actually sits — and if the feedforward was still slewing, this
    //     is strictly MORE continuous than the raw setpoint would be;
    //   - resetShareControlState() seeds 0.5, the historic fresh-start split.
    // The band clip matters: an out-of-band seed would put the reference outside the range the
    // governor clip can ever produce, so the first ticks would slew through dead space.
    share_spEffPrev      = constrain(seed, DROOP_R_MIN, DROOP_R_MAX);
}

void resetShareControlState() {
    resetShareControllerCore(0.5f);         // 0.5 = the historic fresh-start state: seeding at
                                            // SHARE_CTRL_R0 leaves the integrator at exactly 0,
                                            // i.e. bit-identical to the pre-fw-v5 reset
    share_govTotAFilt    = 0.0f;
    share_actedSp        = power_share_setpoint;   // no phantom "setpoint changed" on the first tick
    // fw v5 loop-mode state: a fresh run starts in OPEN-LOOP feedforward at its commanded
    // setpoint and only enters closed-loop control once the filtered total current earns it.
    // shareClosedLoopRun false is what makes that first open-loop phase feed the setpoint
    // forward rather than hold — the hold semantics belong to a load that has FALLEN AWAY from
    // a converged closed loop, not to a run that has not started yet.
    shareClosedLoopMode  = false;
    shareClosedLoopRun   = false;
    // fw v6 (review S1): drop any outstanding deferral. These are normally re-derived every
    // powerBalance() tick, but a profile end / teardown can stop the share loop entirely, and a
    // stale deferral would then suppress the r-based cutoff for a one-shot operator write.
    shareCutDeferredFC   = false;
    shareCutDeferredBT   = false;
}

float youlaController_Power(float setpoint, float alphaRaw) {
    uint32_t now = micros();
    if ((uint32_t)(now - shareCtrl_lastMicros) >= (uint32_t)SHARE_CTRL_TS_US) {
        shareCtrl_lastMicros = now;
        float e = setpoint - shareControllerFilterMeas(alphaRaw);
        // Authority span [0,1] (2026-08-10): the controller may command the
        // full ratio range; ratios outside [DROOP_R_MIN, DROOP_R_MAX] are
        // realized by applyShareRatio() as a channel cutoff, not a clip. The
        // back-calculation anti-windup bounds follow the span, so the
        // integrator can settle at 0 or 1 for a fully-one-sided setpoint
        // instead of winding against the old droop clip.
        shareCtrl_heldOut = shareControllerStep(e, 0.0f, 1.0f);
    }
    return shareCtrl_heldOut;
}

float PI_Controller_Power(float error) {
    const float Kp = 1.0f;
    const float Ki = 1.0f;

    // Same structure as PI_Controller_Motor: integrate once per sampleTime window, always
    // return a live output (no 0.0f sentinel — see comment there).
    uint32_t now = micros();
    uint32_t dtMicros = now - pi_power_lastMicros;
    if (dtMicros >= (uint32_t)sampleTime) {
        pi_power_lastMicros = now;
        pi_power_accum += error * dtMicros * 1e-6f;
        // Anti-windup: the output is a droop ratio, clamped to [DROOP_R_MIN, DROOP_R_MAX] downstream in
        // powerBalance(), so integral authority beyond ±1.0 is unusable — clamp Ki*accum to
        // ±1.0. This matters when the share error can't converge (e.g. a source disconnected
        // from the bus): without the clamp the integrator winds up for the whole episode and
        // slams the split on recovery. Note: during FC-charge cruise (BT_BUS_ENABLE LOW) the
        // EMS on the Pi commands power_share_setpoint ≈ 1.0 to match the FC-only bus, so the
        // share error is ~0 there by design — this clamp is the defensive backstop for
        // off-nominal cases, not the primary mechanism.
        const float integMax = 1.0f / Ki;
        pi_power_accum = constrain(pi_power_accum, -integMax, integMax);
    }
    return Kp * error + Ki * pi_power_accum;
}

void setDroopMdac(float fc_gain, float bt_gain) {
    // Word = load-and-update control nibble + 12-bit code (ad5426_5432_5443.pdf Fig 49 +
    // Table 10 — a bare code has control 0000 = NOP and the DAC never leaves zero scale; this
    // was the 2026-08-07 droop-immovable bench bug).
    uint16_t fcCode = MDAC_CMD_LOAD_UPDATE | (uint16_t)(constrain(fc_gain, 0.0f, 1.0f) * MDAC_res);
    uint16_t btCode = MDAC_CMD_LOAD_UPDATE | (uint16_t)(constrain(bt_gain, 0.0f, 1.0f) * MDAC_res);

    // SPI_MODE2 (CPOL=1, CPHA=0) — VERIFIED ad5426_5432_5443.pdf Fig 2: SCLK idles HIGH and
    // "data is clocked into the shift register on falling clock edges" (p.20). The old
    // SPI_MODE0 transitioned MOSI on the falling edge — i.e. exactly at the AD5443's sample
    // instant. MSBFIRST (DB15 first, Fig 49); 1 MHz is far under the 50 MHz f_SCLK max.
    SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE2));
    digitalWrite(CS_MDAC_FC, LOW);    // SYNC frames each 16-bit word (t8 SYNC-high min 30 ns)
    SPI.transfer16(fcCode);
    digitalWrite(CS_MDAC_FC, HIGH);
    digitalWrite(CS_MDAC_BT, LOW);
    SPI.transfer16(btCode);
    digitalWrite(CS_MDAC_BT, HIGH);
    SPI.endTransaction();
    // Note: OPA197 output ceiling is set by the 5V rail (hardware bodge); droop mapping
    // must not assume a 3.3V output swing. No firmware change required.
}

void chargingControl() {
    // charge_goal == 0 → Pi wants no charging; inhibit everything
    if (charge_goal <= 0.05f) {
        digitalWrite(MPPT_DISABLE, LOW);   // inhibit MPPT (active-LOW: LOW = inhibit)
        assertFcChargeEnable(false);
        digitalWrite(REGEN_ENABLE, LOW);
        // share setpoint latch owns this switch — see updateShareSetpointCutoff() (2026-08-12)
        if (!shareSpCutBT) digitalWrite(BT_BUS_ENABLE, HIGH); // BT contributes to VBUS when not FC-charging
        return;
    }

    // CHARGER_STAT (pin 6) polarity — Source: Ag105_Table5_Status_Output.json:
    //   Steady HIGH  = Charging
    //   50% duty 2s  = Fully Charged
    //   Pulse trains = error states (1–5 pulses per mode)
    //   Steady LOW   = Input Voltage Removed
    // A single digitalRead() cannot distinguish Charging from an error-state pulse-high, so
    // GENSTAT from I2C (ag105_status_raw) is the authoritative charger-ready source.
    // CHARGER_STAT steady-LOW is a fast "no input power" guard but not used here.
    bool chargerReady = ag105IsReady();

    // VESC commanded current: negative = regen braking
    bool regenActive = (current < -0.1f);   // TODO(calibrate): regen detection threshold

    if (regenActive) {
        // Fast regen: inhibit MPPT so slow perturb-and-observe doesn't fight the transient.
        // TL431/BSP170P braking chopper is the primary fast clamp — do not rely on Ag105 here.
        // REGEN_ENABLE and BT_BUS_ENABLE are not mutually exclusive; BT stays on the bus.
        assertFcChargeEnable(false);         // FC_CHARGE must be OFF before REGEN can go HIGH
        digitalWrite(REGEN_ENABLE, HIGH);    // open regen → charger path
        digitalWrite(MPPT_DISABLE, LOW);     // inhibit MPPT during regen (active-LOW)
        // share setpoint latch owns this switch — see updateShareSetpointCutoff() (2026-08-12)
        if (!shareSpCutBT) digitalWrite(BT_BUS_ENABLE, HIGH);   // BT continues contributing to VBUS during regen
    } else {
        // Cruise/coast: close regen path and harvest via the FC→charger path.
        digitalWrite(REGEN_ENABLE, LOW);
        // Open FC_CHARGE on INTENT (charge_goal>0), not on readiness. The Ag105 has NO input
        // power until this path is open, so gating the path on chargerReady would deadlock:
        // it can never become ready because it is never powered. assertFcChargeEnable(true)
        // still drives BT_BUS_ENABLE/REGEN_ENABLE LOW with the 100µs settle, so the
        // mutual-exclusion hazard is preserved. This is the only place BT_BUS_ENABLE goes LOW
        // in Run.
        assertFcChargeEnable(true);
        // Release the slow perturb-and-observe MPPT loop ONLY once the charger reports ready,
        // so it doesn't run during bring-up (active-LOW: HIGH = enabled, LOW = inhibited).
        digitalWrite(MPPT_DISABLE, chargerReady ? HIGH : LOW);
    }
}


// ═════════════════════════════════════════════════════════════════════════════
// Ag105 I2C HELPERS
// ═════════════════════════════════════════════════════════════════════════════

// I2C bus scanner — probes addresses 0x01–0x7E and prints any that ACK their address.
// Bench diagnostic for the State-98 'I' command: confirms the Ag105 is alive at 0x30
// (AG105_ADDR). A NACK on every address means no pull-ups, the device is unpowered, or
// SDA/SCL are mis-wired. Uses beginTransmission()/endTransmission() only — endTransmission()
// returning 0 means the slave ACKed its address; no data is written, so this is non-intrusive.
void scanI2C() {
    Serial.println("=== I2C scan (0x01-0x7E) ===");
    uint8_t found = 0;
    for (uint8_t addr = 0x01; addr <= 0x7E; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.print("  device at 0x");
            if (addr < 0x10) Serial.print('0');
            Serial.print(addr, HEX);
            if (addr == AG105_ADDR) Serial.print("  <- Ag105 (expected)");
            Serial.println();
            found++;
        }
    }
    Serial.print(found ? "Scan complete: " : "Scan complete: no devices found");
    if (found) { Serial.print(found); Serial.println(" device(s)"); }
    else       { Serial.println(" (check pull-ups / power / SDA=18 SCL=19)"); }
    Serial.println("============================");
}

// Writes the Ag105 charge-current and battery-voltage profiles over I2C. Returns true if
// both writes ACKed, false on any NACK/bus error. Does NOT raise faults — the caller
// (pollAg105) decides whether a failure is a fault based on power/settle/state. Only called
// once the charger is confirmed powered + settled, so a NACK here is a genuine config failure.
// Settings persist in the Ag105 EPROM across power cycles, so re-writing is idempotent.
// Read one Ag105 config register back. The Ag105 ALWAYS prepends the Table 6 status byte before
// data, so a 1-byte field needs a 2-byte request: [status][data]. Returns false on any I2C failure
// or short read; on success `out` holds the data byte.
// Source: Ag105_Table7_I2C_Parameters.json (register map), Ag105_Table6_I2C_Status_Byte.json.
bool ag105ReadConfigReg(uint8_t reg, uint8_t &out) {
    Wire.beginTransmission(AG105_ADDR);
    Wire.write(reg);
    // Full STOP before the read, deliberately matching pollAg105()'s register-read sequence rather
    // than using a repeated start. pollAg105() is the pattern that has been exercised against this
    // part; a repeated start is more textbook-correct but is not what this device has been shown to
    // accept, and this is not the place to introduce an untested I2C variation.
    if (Wire.endTransmission() != 0) return false;
    if (Wire.requestFrom((uint8_t)AG105_ADDR, (uint8_t)2) != 2) return false;
    (void)Wire.read();          // status byte (Table 6) — discarded here
    out = (uint8_t)Wire.read(); // the register value
    return true;
}

// Write one config register only if it does not already hold the wanted value.
// Rationale: these registers live in EPROM. A blind write every powered session burns write cycles
// for no reason, and — more importantly — a blind write gives NO evidence it took effect. The
// previous version wrote both registers unconditionally and returned success on ACK alone, so a
// write that ACKed but did not land left the charger at its 1S/4.2V default while the firmware
// believed it was configured — a real 2S pack would then be charged to a 1S target with no fault.
// docs/VESC_MOTOR_INTEGRATION.md §11 asks for exactly this read-verify-then-write-if-different.
// Returns false if the register cannot be read, cannot be written, or still reads wrong after the
// write.
bool ag105WriteConfigRegVerified(uint8_t reg, uint8_t want) {
    uint8_t got = 0;
    if (!ag105ReadConfigReg(reg, got)) return false;
    if (got == want) return true;              // already correct — no EPROM write

    Wire.beginTransmission(AG105_ADDR);
    Wire.write(reg);
    Wire.write(want);
    if (Wire.endTransmission() != 0) return false;

    // Verify: prove the value actually landed rather than trusting the ACK.
    if (!ag105ReadConfigReg(reg, got)) return false;
    return got == want;
}

bool initAg105Charger() {
    // Power-on defaults: reg 0x00 = 0x00 (ext-resistor mode → no RCS → 1000mA),
    //                    reg 0x01 = 0x00 (ext-resistor mode → no RVS → 4.2V / 1S).
    // Write explicit 2.5A current and 2S/8.4V voltage configs before any charging is allowed.
    // Both go through read-verify-then-write-if-different (see ag105WriteConfigRegVerified).

    // Charge current 2.5A (highest profile); termination at 250mA (C/10)
    // Source: Ag105_Table7_I2C_Parameters.json field 0x00; Ag105_Table4_Charge_Current_Select.json
    if (!ag105WriteConfigRegVerified(AG105_REG_ICHG_CFG, AG105_VAL_2500MA)) return false;

    // Battery voltage 2S / 8.4V (100% capacity profile)
    // Source: Ag105_Table3_Charge_Voltage_Select.json — i2c_field_value 8 = 8.4V
    if (!ag105WriteConfigRegVerified(AG105_REG_VBATT_CFG, AG105_VAL_2S)) return false;

    return true;
}

void pollAg105() {
    // Power-aware service: tracks when the charger has input power, lazily configures it once
    // it has booted, polls measured current/status, and faults only when the charger genuinely
    // should be responding. Called at ~50 Hz from loop() in every state.
    bool powered = chargerHasPower();
    if (powered && !ag105HadPower) ag105PowerOnMs = millis();  // power edge → start settle timer
    if (!powered) {
        ag105Configured = false;    // re-arm config for next power session
        ag105DataValid  = false;    // cached status/current no longer reflect a live charger
        // Clear the measured charge current too. Without this, sendTelemetry() kept shipping the
        // last good value forever: the Pi would see charger_status = 0x00 ("no charger data")
        // alongside a positive, plausible-looking I_charge while the charger was unpowered.
        // (docs/design-review-2026-07-28.md P2-1.)
        I_charge        = 0.0f;
    }
    ag105HadPower = powered;

    // The charger only responds reliably after it has powered up and finished bring-up.
    bool settled = powered && (millis() - ag105PowerOnMs >= AG105_SETTLE_MS);
    // Fault only when the charger genuinely should respond: powered, past the settle window,
    // and in an operational state. State 98 (manual test) is intentionally excluded — the
    // operator may drive FC_CHARGE_ENABLE HIGH without expecting the charger to ACK.
    bool faultArmed = settled && (mainState == 2 || mainState == 3);

    // Read measured charge current — Source: Ag105_Table7_I2C_Parameters.json field 0x06
    // I2C read protocol: Ag105 always prepends the Table 6 status byte before any data byte.
    // For a 1-byte field, Wire.requestFrom must request 2 bytes: first is status, second is data.
    Wire.beginTransmission(AG105_ADDR);
    Wire.write(AG105_REG_ICHG_MEAS);
    Wire.endTransmission(false);             // repeated-start (keep bus active)
    if (Wire.requestFrom((uint8_t)AG105_ADDR, (uint8_t)2) == 2) {
        ag105_status_raw = Wire.read();      // Table 6 status byte (always first)
        ag105DataValid   = true;             // raw byte is live — even if it is 0x00 (Battery Disconnect)
        I_charge = Wire.read() * 0.011f;    // A; scale: 0.011 A/count (Table 7 field 0x06)

        // Lazy configuration: the charger is now powered, settled, and ACKing. Write the
        // 2.5A / 2S-8.4V profile once per power session (EPROM persists; re-write idempotent).
        if (settled && !ag105Configured) {
            if (initAg105Charger()) ag105Configured = true;
            else if (faultArmed)    triggerFault(FAULT_INIT_FAIL, ERR_INIT_FAIL);
        }
    } else {
        // NAK or bus error. Mark charger data stale via ag105DataValid (NOT by zeroing the raw
        // byte — 0x00 is a real Table 6 status) so ag105IsReady() returns false (safe) and the
        // GENSTAT fault check in detectFaults() ignores the stale byte. ag105_status_raw is
        // still zeroed for telemetry: the Pi reads offset 51 == 0x00 as "no charger data".
        // Unpowered or still-settling → not a fault (normal). Only a powered+settled charger
        // that goes silent in an operational state latches State 99.
        ag105DataValid   = false;
        ag105_status_raw = 0;
        I_charge         = 0.0f;   // never leave a stale current next to a "no data" status byte
        if (faultArmed)
            triggerFault(FAULT_I2C_CHARGER, ERR_I2C_CHARGER);
    }
}

inline bool ag105IsReady() {
    // Returns true when the Ag105 is actively charging or fully charged, based on a LIVE
    // status read (ag105DataValid) — a stale cached byte must never report ready.
    uint8_t genstat = ag105_status_raw & 0x07;   // bits 0–2; Source: Ag105_Table6_I2C_Status_Byte.json
    return ag105DataValid &&
           (genstat == AG105_GENSTAT_CHARGING || genstat == AG105_GENSTAT_FULL);
}

// True when a power path is routing input power to the Ag105. The charger is unpowered
// (and cannot ACK I2C) unless FC_CHARGE_ENABLE is HIGH, or REGEN_ENABLE and MOT_PWR_ENABLE
// are both HIGH. An unpowered charger is a NORMAL operating mode (e.g. Init/Idle), so its
// I2C silence must never be treated as a fault. Source: 20260622 board power-path design.
inline bool chargerHasPower() {
    return digitalRead(FC_CHARGE_ENABLE) ||
           (digitalRead(REGEN_ENABLE) && digitalRead(MOT_PWR_ENABLE));
}


// ═════════════════════════════════════════════════════════════════════════════
// INIT HELPERS
// ═════════════════════════════════════════════════════════════════════════════
void initMdacSpiPins() {
    SPI.setMOSI(11);
    SPI.setMISO(12);
    SPI.setSCK(13);
    SPI.begin();
    pinMode(CS_MDAC_FC, OUTPUT);
    pinMode(CS_MDAC_BT, OUTPUT);
    digitalWrite(CS_MDAC_FC, HIGH);
    digitalWrite(CS_MDAC_BT, HIGH);

    // Put both AD5443s in standalone mode (daisy-chain is the power-on default) — datasheet
    // Standalone Mode section (p.21): "After power-on, write 1001 to the control word to
    // disable daisy-chain mode." Not strictly required with our exact-16-clock frames (a
    // daisy-chain-mode DAC still latches on the SYNC rising edge), but standalone re-arms the
    // internal SCLK counter on every SYNC fall, so one glitched clock edge can't shift the
    // frame forever after. Same MODE2/MSBFIRST settings as setDroopMdac().
    SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE2));
    digitalWrite(CS_MDAC_FC, LOW);
    SPI.transfer16(MDAC_CMD_DAISY_DISABLE);
    digitalWrite(CS_MDAC_FC, HIGH);
    digitalWrite(CS_MDAC_BT, LOW);
    SPI.transfer16(MDAC_CMD_DAISY_DISABLE);
    digitalWrite(CS_MDAC_BT, HIGH);
    SPI.endTransaction();
}

void initChargerI2cPins() {
    Wire.setSDA(18);
    Wire.setSCL(19);
    Wire.begin();
}

void initEscUartPins() {
    Serial1.setRX(RX);
    Serial1.setTX(TX);
    Serial1.begin(115200);
    vesc.setSerialPort(&Serial1);
}

void initMdacOutputs() {
    // Balanced 50/50 split at boot: g = K_DROOP/(RE_MAX·0.5) on both channels
    setDroopMdac(K_DROOP / (RE_MAX * 0.5f),
                 K_DROOP / (RE_MAX * 0.5f));
}

void initEsc() {
    commandMotorCurrent(0);
}


// ═════════════════════════════════════════════════════════════════════════════
// WHEEL SPEED (encoder)
// ═════════════════════════════════════════════════════════════════════════════
void updateWheelSpeed() {
    static uint32_t lastMicros = 0;
    static int32_t  index      = 0;

    // averagingTime/sampleTime must not exceed the hard-coded buffer depth — changing either
    // constant used to silently overflow both arrays. static_assert makes that a build error.
    const int averagingTime = 10000;
    const int BUF_DEPTH = 200;
    static_assert(10000 / 50 <= 200, "posArr/timeArr too small for averagingTime/sampleTime");
    const int arraySize = (int)ceil((float)averagingTime / sampleTime);
    static int      posArr[BUF_DEPTH]  = {0};
    // uint32_t, matching micros(). The previous `int` was NOT a bug (the subtraction below promotes
    // it back to uint32_t bit-preservingly, so dt stays correct across both the 2^31 and 2^32
    // wraps) — an earlier TODO here wrongly claimed the wrap corrupted dt. Typed correctly now so
    // nobody "fixes" the non-bug.
    static uint32_t timeArr[BUF_DEPTH] = {0};

    // Requested by State 3 between runs: drop stale timestamps/positions so the next run's
    // first samples don't measure velocity against the previous run's buffer contents.
    if (wheelSpeedResetPending) {
        memset(posArr,  0, sizeof(posArr));
        memset(timeArr, 0, sizeof(timeArr));
        index      = 0;
        lastMicros = 0;
        wheelSpeedResetPending = false;
    }

    uint32_t now      = micros();
    uint32_t dtMicros = now - lastMicros;
    if (dtMicros < (uint32_t)sampleTime) return;
    lastMicros = now;

    noInterrupts();
    int32_t pos = encoderPos;
    interrupts();

    posArr[index]  = pos;
    timeArr[index] = now;
    if (index < arraySize - 1) index++;
    else index = 0;

    // The slot at (index+1) was written arraySize-2 iterations ago (posArr[index] is written, THEN
    // index is incremented, THEN this reads index+1), so the window is 198 samples, not 200 — i.e.
    // averagingTime is nominal only. Harmless because dt is measured rather than assumed.
    uint32_t dt    = now - timeArr[(index + 1) % arraySize];
    float    dtSec = dt * 1e-6f;
    int      dx    = pos - posArr[(index + 1) % arraySize];

    if (dtSec < 1e-6f) return;

    // ── Unit chain (CORRECTED 2026-07-29; user-approved exception to CLAUDE.md "what NOT to
    //    change"). The old line was:
    //        v_actual = flyWheelSpeedRpm * flyWheelRadius / 60.0f;      // flyWheelRadius = 1 "inch"
    //    That yields rev/s × inch, NOT m/s — it dropped the 2π (rad/rev) AND the inch→m 0.0254,
    //    while v_setpoint from the Pi is m/s. Correct conversion for a wheel/roller of radius r:
    //        v [m/s] = ω [rev/s] · 2π · r [m] = rpm · (2π/60) · r_m
    //
    //    HISTORY: the two old errors used to partially CANCEL (v_actual under-read ~6.6×), and
    //    correcting the form alone made the under-read WORSE (~32×) while ENCODER_SLOTS_PER_REV was
    //    still the unsourced 512. Because the loop closes on v_actual, under-reading means the PI
    //    OVER-DRIVES — hence the VELOCITY_CHAIN_CALIBRATED interlock on the State-98 velocity entry
    //    points. Both scale inputs are now measured (240 counts/rev from the disc's 120 counted
    //    slots, 2026-08-16; r = 0.0762 m, 2026-08-13) and
    //    the interlock now defaults open. Tune the motor PI gains only against this measured scale.
    float flyWheelSpeedRpm = (dx / ENCODER_COUNTS_PER_REV) * (60.0f / dtSec);
    v_actual = flyWheelSpeedRpm * RPM_TO_MPS;
}


// ═════════════════════════════════════════════════════════════════════════════
// ENCODER ISRs
// ═════════════════════════════════════════════════════════════════════════════
void doEncoderA() {
    encEdgeCountA++;          // diagnostic only — see the encoder globals block
    pinA_read = digitalRead(ENC_A);
    pinB_read = digitalRead(ENC_B);

    if ((pinA_read == 1) && (pinB_read == 1) && BfirstUp) {
        encoderPos--;
        AfirstUp = 0; BfirstUp = 0;
    } else if ((pinA_read == 1) && (pinB_read == 0)) {
        AfirstUp = 1;
    }

    if ((pinA_read == 0) && (pinB_read == 0) && BfirstDown) {
        encoderPos--;
        AfirstDown = 0; BfirstDown = 0;
    } else if ((pinA_read == 0) && (pinB_read == 1)) {
        AfirstDown = 1;
    }
}

void doEncoderB() {
    encEdgeCountB++;          // diagnostic only — see the encoder globals block
    pinA_read = digitalRead(ENC_A);
    pinB_read = digitalRead(ENC_B);

    if ((pinA_read == 1) && (pinB_read == 1) && AfirstUp) {
        encoderPos++;
        AfirstUp = 0; BfirstUp = 0;
    } else if ((pinA_read == 0) && (pinB_read == 1)) {
        BfirstUp = 1;
    }

    if ((pinA_read == 0) && (pinB_read == 0) && AfirstDown) {
        encoderPos++;
        AfirstDown = 0; BfirstDown = 0;
    } else if ((pinA_read == 1) && (pinB_read == 0)) {
        BfirstDown = 1;
    }
}

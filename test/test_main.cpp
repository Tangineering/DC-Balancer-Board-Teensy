// test_main.cpp — host-native unit tests for teensy_controller.ino
// Build:  cd test && make
// No Teensy hardware or Arduino IDE required.
//
// The .ino is included directly (not compiled separately) after all mock headers
// satisfy its dependencies.  Every function defined in the .ino becomes available
// for direct invocation here.

// ── 1. Mock headers (must come before the .ino include) ──────────────────────
#include "mock_arduino.h"   // millis, micros, GPIO, Serial, String, etc.
#include "mock_wire.h"      // Wire I2C mock
#include "mock_spi.h"       // SPI mock + SPISettings
#include "mock_vesc.h"      // VescUart class
#include "mock_ethernet.h"  // IPAddress, Ethernet, MockEthernetUDP
#include "mock_sd.h"        // SdFs/FsFile/SdioConfig mock (SD bench logger)
// NativeEthernetUdp.h (included by the .ino) defines: using EthernetUDP = MockEthernetUDP

// ── 2. Include the firmware under test ───────────────────────────────────────
#include "../teensy_controller/teensy_controller.ino"

// ── 3. Test infrastructure ───────────────────────────────────────────────────
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cstddef>

static int g_tests_passed = 0;
static int g_tests_failed = 0;

static void check(bool condition, const char* description) {
    if (condition) {
        printf("  PASS: %s\n", description);
        ++g_tests_passed;
    } else {
        printf("  FAIL: %s\n", description);
        ++g_tests_failed;
    }
}

static void test_group(const char* name) {
    printf("\n[%s]\n", name);
}

// Reset all .ino globals and mock state between tests.
static void reset_test_state() {
    mock_reset();
    Wire.reset();
    SPI.reset();
    vesc.reset();
    Udp.reset();

    // .ino sensor globals — use safe-for-detectFaults() defaults so tests that call
    // detectFaults() without setting every sensor don't accidentally trip new faults.
    v_actual = 0;     current = 0;      targetMotorTorque = 0;
    P_fc_actual = 0;  P_batt_actual = 0;
    I_fc = 0;         I_batt = 0;       I_charge = 0;
    V_fc = 10.0f;     V_batt = 7.0f;   V_bus = 16.0f;  // nominal (16V bus), above UV limits, below OV
    V_chg = 0;        V_rgn = 0;

    power_share_actual   = 0;
    droop_gain_FC_actual = 0;
    droop_gain_BT_actual = 0;
    ag105_status_raw     = 0;
    ag105DataValid       = false;
    ag105Configured      = false;
    ag105HadPower        = false;
    ag105PowerOnMs       = 0;
    fault_flags          = 0;
    error_code           = ERR_NONE;
    error_source_state   = 0;

    // PI integrator state (hoisted to file scope so it can be reset between cases)
    pi_motor_accum = 0;  pi_motor_lastMicros = 0;
    pi_power_accum = 0;  pi_power_lastMicros = 0;

    // Control-loop rate-limit gates: open them so a single-tick test call actually runs the
    // controllers rather than being suppressed by a period left over from the previous case.
    // (test_control_rate_limiting exercises the gating itself.)
    resetControlRateLimiters();

    // Velocity-chain interlock: default the runtime flag to CALIBRATED for the existing suite, so
    // the velocity-mode and drive-cycle tests keep exercising the control paths. The refusal path
    // is covered explicitly by test_velocity_chain_interlock().
    velocityChainCalibratedFlag = true;

    // Youla-H share controller state (share_controller.h + wrapper)
    shareControllerReset();
    shareCtrl_heldOut    = 0.5f;
    shareCtrl_lastMicros = 0;
    shareIsoFC = false;
    shareIsoBT = false;
    // Setpoint-latched channel cutoff (fw v4, 2026-08-12): the SETPOINT-owned latch is
    // separate from shareIsoFC/BT (the topology/controller-owned flag) and must be reset
    // independently, or a case that latched one in a prior run would start the next run
    // frozen with no way to release (the release path itself requires an in-band setpoint).
    shareSpCutFC = false;
    shareSpCutBT = false;
    // fw v6 review S1: the per-tick-derived deferral flags. Normally re-derived every
    // updateShareSetpointCutoff() call, but a test that calls applyShareRatio() or the
    // suppression logic directly (without a prior powerBalance() tick) must not inherit a
    // stale true from an earlier case.
    shareCutDeferredFC = false;
    shareCutDeferredBT = false;
    // .ino State-98 trapezoid SHARE-SETPOINT SWEEP ('T … [t,r1..rn]'). Cleared here rather than
    // relying on tsweepFinish()/tsweepCancel(): a case that leaves a sweep mid-cool-down would
    // otherwise fire a trapezoid inside the NEXT case's first doState98() tick.
    tsweepActive          = false;
    tsweepPhase           = 0;
    tsweepCount           = 0;
    tsweepIdx             = 0;
    tsweepDwellMs         = 0;
    tsweepImax            = 0.0f;
    tsweepHoldMs          = 0;
    tsweepRate            = 0.0f;
    tsweepCooldownStartMs = 0;
    // Limit-cycle mitigation state (2026-08-11): fresh-boot values — governor
    // filter empty, slew tracker at the initMdacOutputs() mid-band split.
    share_govTotAFilt = 0.0f;
    droopSlew_prev    = 0.5f;
    // fw v5 governor loop-mode state: a fresh run starts open-loop (feedforward), not held.
    shareClosedLoopMode = false;
    shareClosedLoopRun  = false;
    // fw v5 review round (S3): the setpoint the loop last ACTED on, used to detect a commanded
    // setpoint change that must re-arm the feedforward path out of HOLD. Reset alongside the
    // other loop-mode state so a case can't inherit a stale share_actedSp from a prior test's
    // setpoint and see a spurious (or missing) "changed" edge on its own first tick.
    share_actedSp = 0.5f;
    // fw v6: the effective-setpoint reference the CLOSED-LOOP controller is fed (slew-limited
    // toward the governor-clipped target). Reset alongside the other loop-mode state so a case
    // can't inherit a stale seed from a prior test's OL->CL handover.
    share_spEffPrev = 0.5f;

    // fw v10: Youla-H drive (velocity) controller state (drive_controller.h + wrapper). Zeroes
    // the 5-state Hanus vector, the held output, and back-dates the Ts gate -- the same helper
    // resetDriveControlState() the firmware itself calls at every reset site (haltMotorOutput(),
    // setManualMotorVelocity() entry edge, Idle->Run).
    resetDriveControlState();

    // .ino command globals
    v_setpoint           = 0;
    power_share_setpoint = 0.5f;
    charge_goal          = 0;
    mode_cmd             = 4;

    // .ino flags
    changeToRun = false;
    changeToFin = false;
    mainState   = 0;

    // .ino network/watchdog
    networkUp        = true;   // UDP "up" so sendTelemetry/receiveCommands run (they no-op when false)
    pkt_counter_T    = 0;
    last_rx_ms       = 0;
    pi_ever_connected = false;

    // .ino drive cycle
    driveCycleActive     = false;
    driveCyclePhaseIdx   = 0;
    driveCyclePhaseStart = 0;
    driveCycleStatusLast = 0;

    // .ino State 98 bench tools
    manualMotorMode             = MOTOR_TEST_OFF;
    manualMotorCurrent          = 0.0f;
    manualMotorVelocity         = 0.0f;
    powerBalanceLive            = false;
    powerShareProfileActive     = false;
    powerShareProfilePhaseIdx   = 0;
    powerShareProfilePhaseStart = 0;
    powerShareProfileStatusLast = 0;
    pendingInput                = PEND_NONE;
    inputBufIdx                 = 0;

    // .ino State 98 bench tools — Serial-Plotter stream ('L') + armed start
    plotModeActive    = false;
    plotLastMs        = 0;
    plotArmTarget     = PLOT_ARM_NONE;
    plotArmDeadlineMs = 0;
    plotArmTrapImax   = 0.0f;
    plotArmTrapHoldMs = 0;
    plotArmTrapRate   = 0.0f;
    Serial.tx_clear();
    Serial1.tx_clear();   // defensive: nothing writes to Serial1 today (VescUart mock is
                          // counter-based), but a future mock change must not leak text

    // .ino State 98 bench tools — trapezoidal current profile
    trapProfileActive = false;
    trapPhase         = TRAP_RAMP_UP;
    trapImax          = 0.0f;
    trapHoldMs        = 0;
    trapRateAps       = 0.0f;
    trapRampMs        = 0;
    trapStartMs       = 0;
    trapStatusLast    = 0;
    trapCmdA          = 0.0f;

    // .ino State 98 bench tools — combined drive-cycle + power-share profile ('Y')
    combinedProfileActive = false;
    combinedRegionIdx     = 0;
    combinedRegionStart   = 0;
    combinedStatusLast    = 0;
    yProfileVmax          = Y_VMAX_DEFAULT;
    yProfileBoundLo       = Y_BOUND_DEFAULT;

    // .ino State 98 bench tools — combined CURRENT + power-share profile ('W')
    wProfileActive  = false;
    wRegionIdx      = 0;
    wRegionStart    = 0;
    wStatusLast     = 0;
    wProfileImax    = W_IMAX_DEFAULT;
    wProfileBoundLo = Y_BOUND_DEFAULT;   // shared bound default with 'Y'
    wCmdA           = 0.0f;

    // .ino staged bring-up machine (busBringupStart/Tick/Abort)
    bringupActive     = false;
    bringupPhase      = 0;
    bringupPhaseStart = 0;
    bringupDwellStart = 0;

    // .ino doState99() teardown phase (file scope so logDrainTick() can gate on it). Latched
    // forever on hardware, so the reset lives here rather than in any production path.
    state99Phase = 0;

    // .ino OV_BUS persistence window (detectFaults)
    ovBusOverActive  = false;
    ovBusOverSince   = 0;
    ovBusOverSamples = 0;
    ovBusLastOverMs  = 0;
    ovBusTransientCount = 0;
    ovBusPrintLastMs = 0;
    ovBusHasPrinted  = false;

    // .ino FAULT_UV_BUS arming + persistence window (fw v4, 2026-08-12; mirrors the OV_BUS
    // block above — see the uvBus* state comment at the .ino globals for the field meanings).
    uvBusArmed        = false;
    uvBusUnderActive  = false;
    uvBusUnderSince   = 0;
    uvBusDwellMs      = 0.0f;
    uvBusLastTickMs   = 0;
    uvBusTransientCount = 0;
    uvBusPrintLastMs  = 0;
    uvBusHasPrinted   = false;

    // .ino FAULT_UV_FC arming + leaky-dwell window (fw v6, 2026-08-12; mirrors the uvBus* block
    // above, minus the print-rate state the FC rail doesn't own — see the .ino globals comment).
    fcUvArmed         = false;
    fcUvUnderActive   = false;
    fcUvUnderSince    = 0;
    fcUvDwellMs       = 0.0f;
    fcUvLastTickMs    = 0;
    fcUvTransientCount = 0;
    fcUvLastExcursionMs = 0;

    // .ino State 98 bench tools — SD data logger (logOpenForProfile/logSampleTick/logDrainTick)
    // Note sdInitTried/sdAvailable are latches on real hardware (one probe per power cycle); the
    // reset re-arms them so each case can choose its own card_present.
    g_sd_state.reset();
    sdAvailable       = false;
    sdInitTried       = false;
    sdWarnPrinted     = false;
    logActive         = false;
    logCloseRequested = false;
    logManualActive   = false;   // fw v9: 'K 1'/'K 0' manual-log ownership flag
    logCloseReason    = 0;
    logCloseRequestMs = 0;
    logRecordCount    = 0;
    logRecordsWritten = 0;
    logDroppedCount   = 0;
    logLastRecordsWritten = 0;
    logLastDropped        = 0;
    logLastAbandoned      = 0;
    logRingHead       = 0;
    logRingTail       = 0;
    logRingCount      = 0;
    logFileName[0]    = '\0';
    if (logFile.isOpen()) logFile.close();
    rl_log_last       = 0;   // resetControlRateLimiters() above already back-dated it; explicit
                             // here so the group documents every logger global it owns
    resetControlRateLimiters();
}

// ── Bring-up machine helpers ─────────────────────────────────────────────────
// One State-98 tick with an EMPTY serial queue (the machine must advance on its own).
static void state98_tick() { doState98(); }

// Put the Ag105 into the "powered + settled" condition (a charger power path open and the
// boot settle window elapsed) — the precondition for lazy config and armed I2C faults in
// pollAg105(). Sets the power state directly so callers don't need an extra priming poll.
static void make_charger_powered_settled() {
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;   // path A powers the charger
    ag105HadPower  = true;                   // already powered → no fresh edge
    ag105PowerOnMs = 1000;
    g_mock_millis  = 1000 + AG105_SETTLE_MS; // past the settle window
}

// ── 4. Tests ─────────────────────────────────────────────────────────────────

// ─── Scale factor math ───────────────────────────────────────────────────────
static void test_scale_factors() {
    test_group("Scale factor math");

    // SCALE_V_FC = 3.3 * (27.4+10)/10 / 4095
    float expected_fc   = 3.3f * (27.4f + 10.0f) / 10.0f / 4095.0f;
    float expected_batt = 3.3f * (16.2f + 10.0f) / 10.0f / 4095.0f;
    float expected_bus  = 3.3f * (46.4f + 10.0f) / 10.0f / 4095.0f;
    float expected_chg  = 3.3f * (78.7f + 10.0f) / 10.0f / 4095.0f;
    float expected_rgn  = 3.3f * (78.7f + 10.0f) / 10.0f / 4095.0f;
    float expected_i    = 3.3f / 4095.0f / 0.1f;   // INA253A1: 0.1 V/A (A3 would be 0.4 V/A)

    check(fabsf(SCALE_V_FC   - expected_fc  ) < 1e-7f, "SCALE_V_FC correct (27.4+10)/10");
    check(fabsf(SCALE_V_BATT - expected_batt) < 1e-7f, "SCALE_V_BATT correct (16.2+10)/10");
    check(fabsf(SCALE_V_BUS  - expected_bus ) < 1e-7f, "SCALE_V_BUS correct (46.4+10)/10");
    check(fabsf(SCALE_V_CHG  - expected_chg ) < 1e-7f, "SCALE_V_CHG correct (78.7+10)/10");
    check(fabsf(SCALE_V_RGN  - expected_rgn ) < 1e-7f, "SCALE_V_RGN correct (78.7+10)/10");
    check(fabsf(SCALE_I      - expected_i   ) < 1e-7f, "SCALE_I correct (3.3/4095/0.1 — INA253A1)");

    // ADC_MAX sanity
    check(ADC_MAX == 4095.0f, "ADC_MAX == 4095 (12-bit)");

    // Voltage range sanity: SCALE * 4095 should equal Vmax
    check(fabsf(SCALE_V_FC   * 4095.0f - 12.342f) < 0.01f, "SCALE_V_FC * 4095 == 12.342V");
    check(fabsf(SCALE_V_BATT * 4095.0f -  8.646f) < 0.01f, "SCALE_V_BATT * 4095 == 8.646V");
    check(fabsf(SCALE_V_BUS  * 4095.0f - 18.612f) < 0.01f, "SCALE_V_BUS * 4095 == 18.612V");
}

// ─── Ag105 constants ─────────────────────────────────────────────────────────
static void test_ag105_constants() {
    test_group("Ag105 I2C constants");

    check(AG105_ADDR          == 0x30, "AG105_ADDR == 0x30 (field 0xE5 default)");
    check(AG105_REG_ICHG_CFG  == 0x00, "AG105_REG_ICHG_CFG == 0x00");
    check(AG105_VAL_2500MA    == 0x01, "AG105_VAL_2500MA == 0x01 (2.5A profile)");
    check(AG105_REG_VBATT_CFG == 0x01, "AG105_REG_VBATT_CFG == 0x01");
    check(AG105_VAL_2S        == 0x08, "AG105_VAL_2S == 0x08 (8.4V / 2S / 100% capacity)");
    check(AG105_REG_ICHG_MEAS == 0x06, "AG105_REG_ICHG_MEAS == 0x06 (0.011 A/count)");
    check(AG105_GENSTAT_CHARGING == 0x02, "AG105_GENSTAT_CHARGING == 0x02");
    check(AG105_GENSTAT_FULL     == 0x03, "AG105_GENSTAT_FULL == 0x03");
    check(TELEMETRY_VERSION == 4, "TELEMETRY_VERSION == 4");
}

// ─── initAg105Charger() I2C write sequence ───────────────────────────────────
static void test_init_ag105_charger() {
    test_group("initAg105Charger() I2C sequence");
    reset_test_state();

    bool ok = initAg105Charger();

    check(ok, "initAg105Charger: returns true when both writes ACK");
    check(Wire.write_log.size() == 2,
          "initAg105Charger: exactly 2 I2C config writes");

    if (Wire.write_log.size() >= 1) {
        check(Wire.write_log[0].addr  == 0x30,
              "initAg105Charger: write[0] address == 0x30 (AG105)");
        check(Wire.write_log[0].reg   == 0x00,
              "initAg105Charger: write[0] reg == 0x00 (ICHG_CFG)");
        check(Wire.write_log[0].value == 0x01,
              "initAg105Charger: write[0] value == 0x01 (2.5A)");
    }
    if (Wire.write_log.size() >= 2) {
        check(Wire.write_log[1].addr  == 0x30,
              "initAg105Charger: write[1] address == 0x30 (AG105)");
        check(Wire.write_log[1].reg   == 0x01,
              "initAg105Charger: write[1] reg == 0x01 (VBATT_CFG)");
        check(Wire.write_log[1].value == 0x08,
              "initAg105Charger: write[1] value == 0x08 (2S / 8.4V)");
    }

    // Verify ordering: ICHG write comes before VBATT write
    if (Wire.write_log.size() >= 2) {
        bool ichg_first = (Wire.write_log[0].reg == 0x00) && (Wire.write_log[1].reg == 0x01);
        check(ichg_first, "initAg105Charger: ICHG write precedes VBATT write");
    }
}

// ─── pollAg105() byte decoding ───────────────────────────────────────────────
static void test_poll_ag105() {
    test_group("pollAg105() byte decoding");
    reset_test_state();

    // Inject: status byte = 0x02 (GENSTAT=charging), current byte = 100 (→ 1.1A)
    Wire.rx_queue.push(0x02);
    Wire.rx_queue.push(100);

    pollAg105();

    check(ag105_status_raw == 0x02,
          "pollAg105: status byte captured in ag105_status_raw");
    check(fabsf(I_charge - 100 * 0.011f) < 0.001f,
          "pollAg105: I_charge = count * 0.011 A/count");
    check(ag105IsReady(),
          "ag105IsReady: true when GENSTAT == CHARGING (0x02)");

    // Inject: GENSTAT = fully charged (0x03)
    ag105_status_raw = 0;
    Wire.rx_queue.push(0x03);
    Wire.rx_queue.push(5);
    pollAg105();
    check(ag105IsReady(),
          "ag105IsReady: true when GENSTAT == FULL (0x03)");

    // Poke: GENSTAT = 0x00 (Battery Disconnect) — live data (valid from the poll above), NOT ready
    ag105_status_raw = 0x00;
    check(!ag105IsReady(),
          "ag105IsReady: false when GENSTAT == 0x00 (Battery Disconnect)");

    // Poke: GENSTAT = 0x01 — not charging or full, not ready
    ag105_status_raw = 0x01;
    check(!ag105IsReady(),
          "ag105IsReady: false when GENSTAT == 0x01");

    // Failed read (NAK): validity must drop, and a stale CHARGING byte must not report ready
    Wire.fail_next_requestfrom = true;
    pollAg105();
    check(!ag105DataValid,
          "pollAg105: ag105DataValid false after failed read");
    ag105_status_raw = AG105_GENSTAT_CHARGING;   // stale byte poked back in
    check(!ag105IsReady(),
          "ag105IsReady: false on stale data even if GENSTAT byte says CHARGING");

    // Successful read restores validity — even for a live 0x00 (Battery Disconnect) status
    Wire.rx_queue.push(0x00);
    Wire.rx_queue.push(0);
    pollAg105();
    check(ag105DataValid,
          "pollAg105: ag105DataValid true after successful read of status 0x00");
}

// ─── assertFcChargeEnable(true) ordering ─────────────────────────────────────
static void test_assert_fc_charge_enable_true() {
    test_group("assertFcChargeEnable(true) — ordering");
    reset_test_state();

    // Pre-condition: both BT_BUS and REGEN are HIGH (simulating them already enabled)
    g_pin_value[BT_BUS_ENABLE]    = HIGH;
    g_pin_value[REGEN_ENABLE]     = HIGH;
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    g_write_log.clear();

    assertFcChargeEnable(true);

    // FC_CHARGE_ENABLE must end up HIGH
    check(g_pin_value[FC_CHARGE_ENABLE] == HIGH,
          "assertFcChargeEnable(true): FC_CHARGE_ENABLE final state HIGH");
    // BT_BUS_ENABLE and REGEN_ENABLE must end up LOW
    check(g_pin_value[BT_BUS_ENABLE] == LOW,
          "assertFcChargeEnable(true): BT_BUS_ENABLE final state LOW");
    check(g_pin_value[REGEN_ENABLE]  == LOW,
          "assertFcChargeEnable(true): REGEN_ENABLE final state LOW");

    // Ordering: find the write events and verify BT_BUS and REGEN go LOW BEFORE FC_CHARGE goes HIGH
    int fc_high_idx = -1;
    bool bt_low_before_fc = false;
    bool regen_low_before_fc = false;

    for (int i = 0; i < (int)g_write_log.size(); i++) {
        if (g_write_log[i].pin == FC_CHARGE_ENABLE && g_write_log[i].value == HIGH) {
            fc_high_idx = i;
            break;
        }
    }
    if (fc_high_idx >= 0) {
        for (int i = 0; i < fc_high_idx; i++) {
            if (g_write_log[i].pin == BT_BUS_ENABLE  && g_write_log[i].value == LOW) bt_low_before_fc   = true;
            if (g_write_log[i].pin == REGEN_ENABLE    && g_write_log[i].value == LOW) regen_low_before_fc = true;
        }
    }
    check(fc_high_idx >= 0,
          "assertFcChargeEnable(true): FC_CHARGE_ENABLE was driven HIGH");
    check(bt_low_before_fc,
          "assertFcChargeEnable(true): BT_BUS_ENABLE driven LOW before FC_CHARGE_ENABLE HIGH");
    check(regen_low_before_fc,
          "assertFcChargeEnable(true): REGEN_ENABLE driven LOW before FC_CHARGE_ENABLE HIGH");
}

// ─── assertFcChargeEnable(false) behavior ────────────────────────────────────
static void test_assert_fc_charge_enable_false() {
    test_group("assertFcChargeEnable(false) — only FC_CHARGE toggled");
    reset_test_state();

    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE]    = LOW;
    g_pin_value[REGEN_ENABLE]     = HIGH;  // deliberately left HIGH to verify it is NOT touched
    g_write_log.clear();

    assertFcChargeEnable(false);

    check(g_pin_value[FC_CHARGE_ENABLE] == LOW,
          "assertFcChargeEnable(false): FC_CHARGE_ENABLE driven LOW");

    bool regen_written = false;
    bool bt_written    = false;
    for (auto& e : g_write_log) {
        if (e.pin == REGEN_ENABLE)  regen_written = true;
        if (e.pin == BT_BUS_ENABLE) bt_written    = true;
    }
    check(!regen_written,
          "assertFcChargeEnable(false): REGEN_ENABLE not disturbed");
    check(!bt_written,
          "assertFcChargeEnable(false): BT_BUS_ENABLE not disturbed");
}

// ─── chargingControl() — MPPT_DISABLE polarity ───────────────────────────────
static void test_charging_control_mppt_polarity() {
    test_group("chargingControl() MPPT_DISABLE polarity");

    // Sub-test A: charge_goal == 0 → everything inhibited
    reset_test_state();
    charge_goal = 0.0f;
    chargingControl();
    check(g_pin_value[MPPT_DISABLE]    == LOW,
          "chargingControl: MPPT_DISABLE LOW when charge_goal=0 (inhibited)");
    check(g_pin_value[FC_CHARGE_ENABLE] == LOW,
          "chargingControl: FC_CHARGE_ENABLE LOW when charge_goal=0");
    check(g_pin_value[REGEN_ENABLE]     == LOW,
          "chargingControl: REGEN_ENABLE LOW when charge_goal=0");

    // Sub-test B: active regen (current < -0.1) → MPPT inhibited, REGEN_ENABLE HIGH
    reset_test_state();
    charge_goal = 1.0f;
    current     = -1.0f;   // regen braking
    ag105_status_raw = AG105_GENSTAT_CHARGING;
    ag105DataValid   = true;
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    g_pin_value[BT_BUS_ENABLE]    = LOW;
    g_pin_value[REGEN_ENABLE]     = LOW;
    chargingControl();
    check(g_pin_value[MPPT_DISABLE]    == LOW,
          "chargingControl: MPPT_DISABLE LOW (inhibited) during regen");
    check(g_pin_value[REGEN_ENABLE]    == HIGH,
          "chargingControl: REGEN_ENABLE HIGH during regen");
    check(g_pin_value[FC_CHARGE_ENABLE] == LOW,
          "chargingControl: FC_CHARGE_ENABLE LOW during regen");

    // Sub-test C: cruise, charger ready → MPPT released (HIGH = enabled), FC_CHARGE HIGH
    reset_test_state();
    charge_goal = 1.0f;
    current     = 0.5f;   // cruise
    ag105_status_raw = AG105_GENSTAT_CHARGING;
    ag105DataValid   = true;   // live read — ag105IsReady() requires validity, not just GENSTAT
    g_pin_value[REGEN_ENABLE]     = LOW;
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    g_pin_value[BT_BUS_ENABLE]    = LOW;
    chargingControl();
    check(g_pin_value[MPPT_DISABLE]    == HIGH,
          "chargingControl: MPPT_DISABLE HIGH (released) during cruise with charger ready");
    check(g_pin_value[FC_CHARGE_ENABLE] == HIGH,
          "chargingControl: FC_CHARGE_ENABLE HIGH during cruise");
    check(g_pin_value[REGEN_ENABLE]     == LOW,
          "chargingControl: REGEN_ENABLE LOW during cruise");

    // Sub-test D: cruise but charger NOT ready → FC_CHARGE opens on intent (to power the
    // charger and break the bootstrap deadlock), but MPPT stays inhibited until ready.
    reset_test_state();
    charge_goal = 1.0f;
    current     = 0.5f;
    ag105_status_raw = 0x00;   // not ready (GENSTAT=0, startup)
    g_pin_value[REGEN_ENABLE]     = LOW;
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    g_pin_value[BT_BUS_ENABLE]    = LOW;
    chargingControl();
    check(g_pin_value[MPPT_DISABLE]    == LOW,
          "chargingControl: MPPT_DISABLE LOW when charger not ready");
    check(g_pin_value[FC_CHARGE_ENABLE] == HIGH,
          "chargingControl: FC_CHARGE_ENABLE HIGH on intent even when charger not ready (bootstrap)");
}

// ─── detectFaults() ──────────────────────────────────────────────────────────
static void test_detect_faults() {
    test_group("detectFaults()");

    // OC_FC — verify fault bit, error_code latch, and state transition
    reset_test_state();
    I_fc = LIMIT_I_FC_MAX + 0.1f;
    V_batt = 7.0f; V_bus = 16.0f;
    mainState = 1;
    detectFaults();
    check(fault_flags & FAULT_OC_FC,
          "detectFaults: FAULT_OC_FC set when I_fc > LIMIT_I_FC_MAX");
    check(mainState == 99,
          "detectFaults: mainState → 99 on OC_FC");
    check(error_code == ERR_OC_FC,
          "detectFaults: error_code == ERR_OC_FC on overcurrent");
    check(error_source_state == 1,
          "detectFaults: error_source_state captures State 1");

    // UV_BATT
    reset_test_state();
    V_batt = LIMIT_V_BATT_MIN - 0.1f;
    V_bus = 16.0f; I_fc = 0;
    mainState = 2;
    detectFaults();
    check(fault_flags & FAULT_UV_BATT,
          "detectFaults: FAULT_UV_BATT set when V_batt < LIMIT_V_BATT_MIN");
    check(mainState == 99,
          "detectFaults: mainState → 99 on UV_BATT");
    check(error_code == ERR_UV_BATT,
          "detectFaults: error_code == ERR_UV_BATT");

    // OV_BUS — now time-persistence filtered: the BIT shows on the first over-limit sample,
    // but the LATCH needs OV_BUS_PERSIST_MS continuous AND OV_BUS_PERSIST_MIN_SAMPLES ticks.
    // (Dedicated coverage in test_ov_bus_persistence(); this only checks the latch still works.)
    reset_test_state();
    V_batt = 7.0f; V_bus = LIMIT_V_BUS_MAX + 0.1f; I_fc = 0;
    mainState = 1;
    g_mock_millis = 100;
    detectFaults();
    check(fault_flags & FAULT_OV_BUS,
          "detectFaults: FAULT_OV_BUS set when V_bus > LIMIT_V_BUS_MAX");
    check(mainState == 1 && error_code == ERR_NONE,
          "detectFaults: single over-limit sample does NOT latch (persistence filter)");
    // Steps must be ≤ OV_BUS_MAX_GAP_MS or the gap guard restarts the window (review F4).
    g_mock_millis = 100 + OV_BUS_MAX_GAP_MS;     detectFaults();
    g_mock_millis = 100 + OV_BUS_PERSIST_MS;     detectFaults();
    check(mainState == 99,
          "detectFaults: mainState → 99 on OV_BUS");
    check(error_code == ERR_OV_BUS,
          "detectFaults: error_code == ERR_OV_BUS");

    // Switch conflict: FC_CHARGE_ENABLE + BT_BUS_ENABLE both HIGH
    reset_test_state();
    V_batt = 7.0f; V_bus = 16.0f; I_fc = 0;
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE]    = HIGH;
    g_pin_value[REGEN_ENABLE]     = LOW;
    mainState = 1;
    detectFaults();
    check(fault_flags & FAULT_SWITCH_CONFLICT,
          "detectFaults: FAULT_SWITCH_CONFLICT set when FC_CHARGE_ENABLE+BT_BUS_ENABLE both HIGH");
    check(error_code == ERR_SWITCH_CONFLICT,
          "detectFaults: error_code == ERR_SWITCH_CONFLICT");

    // Switch conflict: FC_CHARGE_ENABLE + REGEN_ENABLE both HIGH
    reset_test_state();
    V_batt = 7.0f; V_bus = 16.0f; I_fc = 0;
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE]    = LOW;
    g_pin_value[REGEN_ENABLE]     = HIGH;
    mainState = 1;
    detectFaults();
    check(fault_flags & FAULT_SWITCH_CONFLICT,
          "detectFaults: FAULT_SWITCH_CONFLICT set when FC_CHARGE_ENABLE+REGEN_ENABLE both HIGH");

    // OV_BATT
    reset_test_state();
    V_batt = LIMIT_V_BATT_MAX + 0.1f; V_bus = 16.0f; I_fc = 0;
    mainState = 1;
    detectFaults();
    check(fault_flags & FAULT_OV_BATT,
          "detectFaults: FAULT_OV_BATT set when V_batt > LIMIT_V_BATT_MAX");
    check(error_code == ERR_OV_BATT,
          "detectFaults: error_code == ERR_OV_BATT");

    // OV_BATT threshold — just below limit → no fault
    reset_test_state();
    V_batt = LIMIT_V_BATT_MAX - 0.05f; V_bus = 16.0f; I_fc = 0;
    mainState = 1;
    detectFaults();
    check(!(fault_flags & FAULT_OV_BATT),
          "detectFaults: no FAULT_OV_BATT when V_batt == LIMIT_V_BATT_MAX - 0.05");

    // UV_BUS (fw v4, 2026-08-12) — bus-ARMED, not state-gated: the old State-2-only
    // single-sample check is gone. Arming requires a source switch closed with V_bus having
    // reached V_BUS_CHARGED_THRESH; with both source switches LOW (the default reset state)
    // a low V_bus is just a dark power stage, never a fault, in ANY state.
    // (Dedicated coverage in test_uv_bus_dwell_relay_waveform() / test_uv_bus_not_armed_dark()
    // etc.; this only checks the unarmed default still holds and the latch still works.)
    reset_test_state();
    V_bus = LIMIT_V_BUS_MIN - 1.0f; V_batt = 7.0f; I_fc = 0;
    mainState = 1;
    detectFaults();
    check(!(fault_flags & FAULT_UV_BUS),
          "detectFaults: no FAULT_UV_BUS with both source switches LOW (never armed) even when V_bus low");
    check(mainState == 1,
          "detectFaults: mainState unchanged (not armed, so nothing to latch)");

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;   // arming also requires a boost enabled (fw v4 S4)
    V_batt = 7.0f; I_fc = 0;
    V_bus = V_BUS_CHARGED_THRESH + 0.5f;
    g_mock_millis = 0;
    detectFaults();                                          // arms
    V_bus = LIMIT_V_BUS_MIN - 1.0f;
    // fw v5: dwell filter, not a wall-clock window. Four ticks 5ms apart each credit the full
    // UV_BUS_DWELL_DT_CAP_MS (5ms), accumulating to UV_BUS_DWELL_LATCH_MS (20ms) on the 4th.
    g_mock_millis = 1000; detectFaults(); // dwell=5ms
    g_mock_millis = 1005; detectFaults(); // dwell=10ms
    g_mock_millis = 1010; detectFaults(); // dwell=15ms
    g_mock_millis = 1015; detectFaults(); // dwell=20ms -> latch
    check(fault_flags & FAULT_UV_BUS,
          "detectFaults: FAULT_UV_BUS latches once armed and the dwell filter is satisfied");
    check(error_code == ERR_UV_BUS,
          "detectFaults: error_code == ERR_UV_BUS");

    // FAULT_ERROR sticky — once in State 99, detectFaults() preserves fault_flags
    reset_test_state();
    fault_flags = FAULT_OC_FC | FAULT_ERROR;
    error_code  = ERR_OC_FC;
    mainState   = 99;
    detectFaults();   // must not clear fault_flags since mainState==99
    check(fault_flags & FAULT_ERROR,
          "detectFaults: FAULT_ERROR sticky when mainState==99");
    check(fault_flags & FAULT_OC_FC,
          "detectFaults: FAULT_OC_FC preserved when mainState==99");
    check(error_code == ERR_OC_FC,
          "detectFaults: error_code not overwritten in State 99");

    // No fault in nominal conditions
    reset_test_state();
    I_fc = 1.0f; V_batt = 7.0f; V_bus = 16.0f;
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    g_pin_value[BT_BUS_ENABLE]    = LOW;
    g_pin_value[REGEN_ENABLE]     = LOW;
    mainState = 2;
    detectFaults();
    check(fault_flags == 0,
          "detectFaults: no fault in nominal conditions");
    check(mainState == 2,
          "detectFaults: mainState unchanged in nominal conditions");
    check(error_code == ERR_NONE,
          "detectFaults: error_code remains ERR_NONE in nominal conditions");
}

// ─── Telemetry v3 layout ─────────────────────────────────────────────────────
static void test_telemetry_v4_layout() {
    test_group("Telemetry v4 layout (58-byte packet)");
    reset_test_state();

    // Set known values
    v_actual = 1.0f;    V_batt = 7.5f;   I_batt = 0.5f;  I_charge = 0.11f;
    V_fc = 12.0f;       I_fc   = 0.3f;   V_bus  = 16.0f;
    V_rgn = 5.0f;       V_chg  = 20.0f;
    power_share_actual   = 0.6f;
    droop_gain_FC_actual = 0.0f;
    droop_gain_BT_actual = 0.0f;
    fault_flags = 0;
    error_code  = ERR_NONE;
    error_source_state = 0;
    pkt_counter_T = 42;
    ag105_status_raw = 0x4A;   // raw Ag105 Table 6 byte: GENSTAT 0b010 (Charging) + CC (bit6)

    // All switches LOW → switch_state should be 0
    for (int p = 27; p <= 32; p++) g_pin_value[p] = LOW;

    sendTelemetry();

    check(Udp.last_written.size() == 58,
          "telemetry: packet length == 58 bytes (v4)");
    check(Udp.last_written[0] == 0xAA,
          "telemetry: SYNC byte 0xAA at offset 0");

    // Checksum: XOR of bytes 1–56 must equal byte 57 (v4 extended span)
    uint8_t cs = 0;
    for (int i = 1; i < 57; i++) cs ^= Udp.last_written[i];
    check(cs == Udp.last_written[57],
          "telemetry: XOR checksum over bytes 1–56 matches byte 57");

    // charger_status at offset 51 — raw Ag105 status byte forwarded verbatim (v4)
    check(Udp.last_written[51] == 0x4A,
          "telemetry: charger_status (ag105_status_raw) at offset 51");

    // V_rgn at offset 35 (was P_motor_actual in v1)
    float read_v_rgn = 0;
    memcpy(&read_v_rgn, &Udp.last_written[35], 4);
    check(fabsf(read_v_rgn - V_rgn) < 1e-4f,
          "telemetry: V_rgn at offset 35");

    // V_chg at offset 39 (was power_share_echo in v1)
    float read_v_chg = 0;
    memcpy(&read_v_chg, &Udp.last_written[39], 4);
    check(fabsf(read_v_chg - V_chg) < 1e-4f,
          "telemetry: V_chg at offset 39");

    // I_charge at offset 19 (source changed to I2C, same slot)
    float read_ichg = 0;
    memcpy(&read_ichg, &Udp.last_written[19], 4);
    check(fabsf(read_ichg - I_charge) < 1e-4f,
          "telemetry: I_charge at offset 19");

    // power_share_actual at offset 43
    float read_ps = 0;
    memcpy(&read_ps, &Udp.last_written[43], 4);
    check(fabsf(read_ps - power_share_actual) < 1e-4f,
          "telemetry: power_share_actual at offset 43");

    // switch_state at offset 52 (shifted +1 in v4) — all LOW → 0
    check(Udp.last_written[52] == 0,
          "telemetry: switch_state == 0 when all path switches LOW");

    // fault_flags at offset 53 — uint16_t LE (2 bytes)
    uint16_t read_flt = 0;
    memcpy(&read_flt, &Udp.last_written[53], 2);
    check(read_flt == 0,
          "telemetry: fault_flags (uint16_t LE) == 0 at offset 53");

    // error_code at offset 55
    check(Udp.last_written[55] == ERR_NONE,
          "telemetry: error_code == ERR_NONE at offset 55");

    // error_source_state at offset 56
    check(Udp.last_written[56] == 0,
          "telemetry: error_source_state == 0 at offset 56");

    // Re-test with a non-zero fault_flags and error_code to verify they encode correctly
    reset_test_state();
    fault_flags        = FAULT_OC_FC | FAULT_ERROR;   // 0x8001
    error_code         = ERR_OC_FC;                   // 0x01
    error_source_state = 2;
    Udp.reset();
    sendTelemetry();
    uint16_t read_flt2 = 0;
    memcpy(&read_flt2, &Udp.last_written[53], 2);
    check(read_flt2 == (FAULT_OC_FC | FAULT_ERROR),
          "telemetry: fault_flags 0x8001 correctly encoded at offset 53");
    check(Udp.last_written[55] == ERR_OC_FC,
          "telemetry: error_code ERR_OC_FC at offset 55");
    check(Udp.last_written[56] == 2,
          "telemetry: error_source_state == 2 at offset 56");

    // Verify switch_state bitmask when some switches are HIGH
    reset_test_state();
    g_pin_value[FC_BUS_ENABLE]  = HIGH;   // bit SW_FC_BUS  = 0x01
    g_pin_value[MOT_PWR_ENABLE] = HIGH;   // bit SW_MOT_PWR = 0x04
    Udp.reset();
    sendTelemetry();
    uint8_t expected_sw = SW_FC_BUS | SW_MOT_PWR;
    check(Udp.last_written[52] == expected_sw,
          "telemetry: switch_state bitmask correct (FC_BUS + MOT_PWR)");
}

// ─── Command packet parsing (receiveCommands) ─────────────────────────────────
static void test_command_parsing() {
    test_group("receiveCommands() command packet parsing");
    reset_test_state();

    // Build a valid 22-byte command packet
    uint8_t pkt[22] = {};
    pkt[0] = 0xBB;   // SYNC_BYTE_RX

    uint32_t ts_val = 12345;
    memcpy(&pkt[1], &ts_val, 4);

    uint16_t cnt = 7;
    memcpy(&pkt[5], &cnt, 2);

    float v_sp = 2.5f;
    memcpy(&pkt[7], &v_sp, 4);

    float ps = 0.4f;
    memcpy(&pkt[11], &ps, 4);

    float cg = 1.0f;
    memcpy(&pkt[15], &cg, 4);

    pkt[19] = 0;   // mode_cmd = MODE_HYBRID (0)
    pkt[20] = 0;   // droop_enable_reserved

    // Compute checksum over bytes 1–20
    uint8_t cs2 = 0;
    for (int i = 1; i < 21; i++) cs2 ^= pkt[i];
    pkt[21] = cs2;

    // Inject into mock UDP
    Udp.fake_packet_size = 22;
    memcpy(Udp.fake_packet, pkt, 22);

    mainState = 1;
    pi_ever_connected = false;
    v_setpoint = 0; power_share_setpoint = 0.5f; charge_goal = 0;

    receiveCommands();

    check(fabsf(v_setpoint           - 2.5f) < 0.001f, "receiveCommands: v_setpoint parsed correctly");
    check(fabsf(power_share_setpoint - 0.4f) < 0.001f, "receiveCommands: power_share_setpoint parsed");
    check(fabsf(charge_goal          - 1.0f) < 0.001f, "receiveCommands: charge_goal parsed");
    check(mode_cmd == 0,             "receiveCommands: mode_cmd parsed (MODE_HYBRID=0)");
    check(pi_ever_connected == true, "receiveCommands: pi_ever_connected set on first packet");
    check(changeToRun == true,       "receiveCommands: changeToRun set when mode=0 and mainState=1");

    // Bad checksum — packet should be dropped
    reset_test_state();
    pkt[21] ^= 0xFF;   // corrupt checksum
    Udp.fake_packet_size = 22;
    memcpy(Udp.fake_packet, pkt, 22);
    v_setpoint = 99.0f;

    receiveCommands();

    check(fabsf(v_setpoint - 99.0f) < 0.001f,
          "receiveCommands: packet dropped on checksum mismatch (v_setpoint unchanged)");

    // Wrong size — packet should be dropped
    Udp.fake_packet_size = 10;
    receiveCommands();
    check(fabsf(v_setpoint - 99.0f) < 0.001f,
          "receiveCommands: packet dropped when size != 22");
}

// ─── PI controller basic behavior ────────────────────────────────────────────
static void test_pi_controllers() {
    test_group("PI controllers");
    reset_test_state();

    // PI_Controller_Motor on a sub-sampleTime tick: NO 0.0f sentinel (the old sentinel chopped
    // the VESC command to zero between samples). Output must be live: Kp*error + Ki*accum(=0).
    g_mock_micros = 0;
    float out_initial = PI_Controller_Motor(1.0f);
    check(fabsf(out_initial - 1.0f) < 1e-4f,
          "PI_Controller_Motor: live proportional output on sub-sampleTime tick (no 0 sentinel)");
    check(pi_motor_accum == 0.0f,
          "PI_Controller_Motor: integrator NOT updated on sub-sampleTime tick");

    // After advancing time past sampleTime (50us), the integrator engages too
    g_mock_micros = 100;   // 100 us > sampleTime=50
    float out_1 = PI_Controller_Motor(1.0f);
    check(out_1 > 0.0f,
          "PI_Controller_Motor: positive output for positive error after dt > sampleTime");
    check(pi_motor_accum > 0.0f,
          "PI_Controller_Motor: integrator updated once dt >= sampleTime");

    g_mock_micros = 200;
    PI_Controller_Motor(-1.0f);   // just verifies no crash; exact value depends on accumulated integral
    check(true, "PI_Controller_Motor: runs without crash for negative error");

    // PI_Controller_Power: same structure, same behavior
    reset_test_state();
    g_mock_micros = 0;
    float pout0 = PI_Controller_Power(1.0f);
    check(fabsf(pout0 - 1.0f) < 1e-4f,
          "PI_Controller_Power: live proportional output on sub-sampleTime tick (no 0 sentinel)");
    check(pi_power_accum == 0.0f,
          "PI_Controller_Power: integrator NOT updated on sub-sampleTime tick");

    g_mock_micros = 100;
    float pout1 = PI_Controller_Power(0.5f);
    check(pout1 > 0.0f,
          "PI_Controller_Power: positive output for positive error");

    // Zero error → Kp * 0 = 0; integral from prior call may add
    g_mock_micros = 200;
    PI_Controller_Power(0.0f);   // should not crash
    check(true, "PI_Controller_Power: zero error runs without crash");
}

// ─── powerBalance() on a gated tick: droop must NOT slam to the 0.01 extreme ──
static void test_powerbalance_gated_tick_stable() {
    test_group("powerBalance() gated-tick droop stability");
    reset_test_state();

    // Steady operating point with a real share error (setpoint 0.8, actual 0.5)
    I_fc   = 1.0f;
    I_batt = 1.0f;
    power_share_setpoint = 0.8f;
    // fw v5: preset the governor filter above the closed-loop entry threshold so the very
    // first tick engages the controller directly, isolating this probe (a controller-output
    // stability property) from the open-loop warm-up ramp the governor now runs at low
    // filtered current (share_govTotAFilt starts at 0 and would otherwise take many ticks to
    // cross 0.60A even at a steady I_tot=2.0A, during which the OPEN-LOOP feedforward path
    // -- which has no sub-sampleTime gate at all -- would legitimately step every call).
    share_govTotAFilt = 2.0f;

    g_mock_micros = 100;           // > sampleTime → PI integrates and produces the ratio
    powerBalance();
    float gFC_first = droop_gain_FC_actual;
    float gBT_first = droop_gain_BT_actual;

    // 10 µs later (sub-sampleTime): the old 0.0f sentinel made droopRatio clamp to 0.01 and
    // slammed the MDAC gains for one tick. The live-output PI must hold the same gains.
    g_mock_micros = 110;
    powerBalance();
    check(fabsf(droop_gain_FC_actual - gFC_first) < 1e-4f,
          "powerBalance: FC droop gain stable across a sub-sampleTime tick");
    check(fabsf(droop_gain_BT_actual - gBT_first) < 1e-4f,
          "powerBalance: BT droop gain stable across a sub-sampleTime tick");
}

// ─── powerBalance() minimum-load hold (SHARE_I_TOT_MIN_A) ────────────────────
// Below 75 mA total the share quotient is ADC noise; the controller and the
// droop MDACs must hold so a standstill can't wind the integrator to the
// DROOP_R_MIN clamp (bench: TP0004/TP0005 standstill epochs, 2026-08-10).
static void test_powerbalance_min_load_hold() {
    test_group("powerBalance() minimum-load hold");
    reset_test_state();

    // Establish a steady operating point well above the threshold.
    I_fc   = 1.0f;
    I_batt = 1.0f;
    power_share_setpoint = 0.5f;
    uint32_t t = 0;
    for (int i = 0; i < 50; i++) {
        t += 1000;                 // 1 ms steps — every Youla Ts elapses
        g_mock_micros = t;
        powerBalance();
    }
    float gFC_held = droop_gain_FC_actual;
    float gBT_held = droop_gain_BT_actual;
    float heldOut  = shareCtrl_heldOut;

    // Standstill: 60 mA total (< 75 mA) with a wildly wrong apparent share
    // (all of it on the FC channel → share would read 1.0 if stepped). Many
    // seconds of ticks must change NOTHING.
    I_fc   = 0.06f;
    I_batt = 0.0f;
    for (int i = 0; i < 3000; i++) {
        t += 1000;
        g_mock_micros = t;
        powerBalance();
    }
    check(fabsf(droop_gain_FC_actual - gFC_held) < 1e-6f,
          "min-load hold: FC droop gain frozen through a standstill epoch");
    check(fabsf(droop_gain_BT_actual - gBT_held) < 1e-6f,
          "min-load hold: BT droop gain frozen through a standstill epoch");
    check(fabsf(shareCtrl_heldOut - heldOut) < 1e-6f,
          "min-load hold: share controller output state frozen (no steps)");

    // Back above the threshold with a real error: the controller must resume
    // on the very first tick (the Ts gate expired long ago) and move the
    // gains toward the new operating point.
    I_fc   = 0.8f;
    I_batt = 0.2f;                 // actual share 0.8, setpoint 0.5 → error
    for (int i = 0; i < 200; i++) {
        t += 1000;
        g_mock_micros = t;
        powerBalance();
    }
    check(fabsf(droop_gain_FC_actual - gFC_held) > 1e-3f,
          "min-load hold: controller resumes and moves the gains once load returns");

    // Boundary: just above the min-load threshold must NOT hold (the gate is strictly <
    // SHARE_I_TOT_MIN_A) -- something must move. fw v5: at 76mA the filtered total can never
    // cross the 0.60A closed-loop entry threshold (share_govTotAFilt asymptotes to totalA =
    // 0.076A), so this boundary is PERMANENTLY open-loop territory. The probe therefore needs a
    // setpoint OFF the droopSlew_prev default (0.5) so the feedforward walk is non-degenerate --
    // the old probe (sp=0.5, relying on the measured-share error) tested a mechanism (reacting
    // to measured error) that open-loop mode deliberately does not have.
    reset_test_state();
    I_fc   = 0.076f;               // 76 mA total, all FC
    I_batt = 0.0f;
    power_share_setpoint = 0.30f;  // off the 0.5 seed -> the feedforward walk must move
    g_mock_micros = 2000;
    powerBalance();
    float g_before = droop_gain_FC_actual;
    g_mock_micros = 4000;
    powerBalance();
    g_mock_micros = 6000;
    powerBalance();
    check(fabsf(droop_gain_FC_actual - g_before) > 1e-6f,
          "min-load hold: 76 mA is above the SHARE_I_TOT_MIN_A gate -- the open-loop feedforward "
          "walk steps normally (not frozen by the min-load gate)");
    check(!shareClosedLoopMode,
          "min-load hold: 76mA can never cross the 0.60A closed-loop entry threshold -- this "
          "boundary is permanently open-loop territory under fw v5");
}

// ─── Limit-cycle mitigation (2026-08-11, reworked fw v5 2026-08-12): governor, slew limit,
// profile reset ────────────────────────────────────────────────────────────────────────────
// The TP0010/TP0013 sweep found a 17–18.5 Hz minority-channel dropout limit cycle at
// asymmetric IN-BAND setpoints under low total current. Mitigation: powerBalance() clips the
// CLOSED-LOOP effective setpoint so the commanded minority current stays >= SHARE_MINORITY_I_MIN_A,
// and slew-limits the controller-commanded ratio; profile starts reset the controller state.
//
// fw v5 (validation-sweep TP0041-TP0068): the governor's clip logic below is UNCHANGED for
// closed-loop mode, but closed-loop mode is now only entered once share_govTotAFilt crosses
// 2*SHARE_MINORITY_I_MIN_A (0.60A) -- below that the loop runs OPEN-LOOP (feedforward walk /
// hold, see test_governor_openloop_* below) and the Youla/PI controller is never called at
// all. Sections (A/A2/B/E1/E2) below test the closed-loop clip math in isolation by presetting
// share_govTotAFilt to the target I_tot BEFORE the loop starts: this makes the very first
// powerBalance() tick take the real entry-check code path (share_govTotAFilt > 0.60A already
// true) straight into closed-loop mode, instead of spending ~20 ticks warming up through the
// open-loop feedforward branch first (which would target the RAW setpoint, not the clipped
// one, and contaminate these probes). The warm-up ramp itself, and the open-loop mechanism it
// exercises, are covered separately by the dedicated governor open-loop tests.
static void test_share_setpoint_governor() {
    test_group("powerBalance() setpoint governor (limit-cycle mitigation)");

    // A) In-band asymmetric setpoint at low load: governed to the feasibility
    // bound. sp=0.20 is IN-BAND (>= DROOP_R_MIN=0.15), so updateShareSetpointCutoff()'s
    // out-of-band latch does NOT own this tick and the governor code below must actually
    // run (the old probe sp=0.10 was < DROOP_R_MIN, so the setpoint latch silently owned it
    // and the governor never executed — a vacuous pass; see the .ino changelog). At
    // I_tot=1.0 A the clip bound is lo = SHARE_MINORITY_I_MIN_A/I_tot = 0.30/1.0 = 0.30
    // (fw v4: floor raised 0.20→0.30, TP0016/TP0017 bracket).
    //
    // A1) Direction probe: hold the measured share at 0.25 — strictly between the raw sp
    // (0.20) and the clip bound (0.30) — so the two candidate targets disagree in SIGN:
    // against the correct clip (spEff=lo=0.30, measured=0.25) the error is +0.05 (ratio must
    // rise); against an unclipped raw sp (0.20, measured=0.25) the error would be -0.05
    // (ratio would fall). Which way the ratio actually moves proves which target the code
    // used — a stronger check than "didn't move".
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.25f; I_batt = 0.75f;          // I_tot=1.0, measured share = 0.25
    share_govTotAFilt = 1.0f;              // fw v5: preset so tick 1 enters closed-loop directly
    power_share_setpoint = 0.20f;          // in-band; below lo=0.30 -> clipped
    uint32_t t = 0;
    float slew_start = droopSlew_prev;     // 0.5, the fresh-reset default
    for (int i = 0; i < 500; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(droopSlew_prev > slew_start + 0.01f,
          "governor A1: clipped sp=0.20 at I_tot=1.0A drives the ratio UP toward lo=0.30 "
          "(an unclipped raw sp=0.20 against the same 0.25 measurement would drive it DOWN)");

    // A2) Zero-error confirmation: with the measured share held exactly at lo=0.30, the
    // clipped effective setpoint sees zero error and the ratio must hold — not wind toward
    // the raw sp=0.20, which would be a real -0.10 error if the code failed to clip.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.3f; I_batt = 0.7f;            // I_tot=1.0, measured share = 0.30 == lo
    share_govTotAFilt = 1.0f;
    power_share_setpoint = 0.20f;
    t = 0;
    for (int i = 0; i < 200; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    float slew_settled = droopSlew_prev;
    for (int i = 0; i < 300; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - slew_settled) < 5e-3f,
          "governor A2: in-band sp=0.20 clipped to lo=0.30 is zero-error at that bound — no winding");
    check(fabsf(SHARE_MINORITY_I_MIN_A - 0.30f) < 1e-6f,
          "governor: SHARE_MINORITY_I_MIN_A is the fw v4 0.30 A floor (TP0016/TP0017 bracket)");

    // B) Same setpoint/share at HIGH load: bound relaxes
    // (lo = SHARE_MINORITY_I_MIN_A/2.0 = 0.15), the raw setpoint applies, the
    // −0.10 error is real → the ratio must move.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.8f; I_batt = 1.2f;            // I_tot=2.0, measured share = 0.40
    share_govTotAFilt = 2.0f;
    power_share_setpoint = 0.30f;
    t = 0;
    for (int i = 0; i < 200; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    // Contrast with (A): the same −0.10 apparent error is now REAL (sp_eff =
    // 0.30), so by tick 200 the ratio has been driven well off mid-band
    // (possibly all the way to the band edge / cutoff — that's fine, the point
    // is that it moved, where (A) held).
    check(droopSlew_prev < 0.45f,
          "governor: at high load the bound relaxes and the same error drives the ratio");

    // E) Explicit lo-bound check at I_tot=1.5 A (fw v4), pinning the 0.30 A floor value
    // itself rather than just "some" clip. sp=0.18 is IN-BAND (>= DROOP_R_MIN=0.15 — the old
    // probe sp=0.05 was not, and was vacuous for the same reason as the old (A)). At
    // I_tot=1.5 A the fw v4 floor gives lo = SHARE_MINORITY_I_MIN_A/I_tot = 0.30/1.5 = 0.20,
    // which is ABOVE sp=0.18 (clipped); the OLD 0.20 A floor would have given
    // lo = 0.20/1.5 = 0.1333, which is BELOW sp=0.18 (no clip at all, spEff = raw sp = 0.18).
    // This is exactly the bracket that distinguishes the two floor values.
    //
    // E1) Direction probe: hold the measured share at 0.19 — strictly between the raw sp
    // (0.18) and the fw v4 lo (0.20) — so the two candidate targets disagree in sign:
    // correct (spEff=lo=0.20) -> error +0.01 (ratio rises); old-floor (spEff=raw sp=0.18,
    // unclipped) -> error -0.01 (ratio would fall).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.285f; I_batt = 1.215f;        // I_tot=1.5, measured share = 0.19
    share_govTotAFilt = 1.5f;
    power_share_setpoint = 0.18f;
    t = 0;
    slew_start = droopSlew_prev;           // 0.5, the fresh-reset default
    for (int i = 0; i < 800; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(droopSlew_prev > slew_start + 0.003f,
          "governor E1: sp=0.18 at I_tot=1.5A clips to the fw v4 lo=0.20 and drives the ratio "
          "UP (the old 0.20A floor would give lo=0.1333 < sp -> no clip -> ratio would fall)");

    // E2) Zero-error confirmation at the exact fw v4 bound: a measured share of 0.20 is
    // zero-error against the fw v4 clip and must not wind — under the old 0.1333 floor this
    // same measurement would be a real +0.047 error (spEff=0.18) and would keep moving.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.3f; I_batt = 1.2f;            // I_tot=1.5, measured share = 0.20 == new lo
    share_govTotAFilt = 1.5f;
    power_share_setpoint = 0.18f;
    t = 0;
    for (int i = 0; i < 200; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    float slew_e = droopSlew_prev;
    for (int i = 0; i < 300; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - slew_e) < 5e-3f,
          "governor E2: effective lo bound at I_tot=1.5A is 0.30/1.5=0.20 (fw v4), not the old 0.1333");

    // C) fw v5: the old "collapse sp_eff to 0.5 below 2x the minority floor" mechanism is
    // GONE — DELETED, not relocated. Below the 0.60A entry threshold, open-loop mode
    // feedforward-walks the RAW setpoint through applyShareRatio() instead (full mechanism
    // coverage in test_governor_openloop_feedforward_walk() below). This probe pins the
    // NEGATIVE directly: at I_tot below the threshold, with an asymmetric raw setpoint, the
    // ratio must converge to the RAW setpoint, not to the deleted 0.5 balanced collapse — the
    // fw v4 version of this exact test asserted the opposite (convergence to 0.5) and would now
    // fail, which is the point: it must fail if the deleted mechanism regresses back in.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.15f; I_batt = 0.15f;          // I_tot=0.3 < 2*0.30=0.6 -> fw v5 open-loop territory
    power_share_setpoint = 0.30f;          // asymmetric raw setpoint
    t = 0;
    for (int i = 0; i < 300; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - 0.30f) < 0.01f,
          "governor C (fw v5): below the entry threshold the ratio converges to the RAW "
          "setpoint 0.30 via open-loop feedforward -- NOT the deleted 0.5 collapse");
    check(!shareClosedLoopMode,
          "governor C (fw v5): stays open-loop throughout -- I_tot=0.3A never crosses the 0.60A "
          "entry threshold");

    // D) Out-of-band setpoints BYPASS the governor entirely: full-span semantics are the
    // cutoff path's (sp=1.0 must still starve BT out via its bus switch even at low load —
    // TP0009/TP0011 showed the topology-forced endpoints are stable). Unaffected by fw v5: the
    // setpoint-latch cutoff runs before either the governor or the open-loop code and returns
    // immediately, so this test needs no changes for the mode split.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.25f; I_batt = 0.25f;          // I_tot=0.5 (governed range for in-band)
    power_share_setpoint = 1.0f;           // out-of-band: bypass
    t = 0;
    for (int i = 0; i < 3000; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareIsoBT,
          "governor: sp=1.0 bypasses the governor — BT cutoff still fires at low load");
}

// ─── fw v5: governor open-loop fallback (feedforward walk / hold) ────────────────────────────
// EVIDENCE (fw v4 validation sweep TP0041-TP0068): the old collapse-to-0.5 fallback below
// 2*SHARE_MINORITY_I_MIN_A IGNITED the failure it existed to prevent (TP0053 relay cycle). fw v5
// replaces it: below the 0.60A entry threshold (hysteresis exit at 0.55A) the Youla/PI
// controller is not called AT ALL. If the closed loop has never run this profile
// (!shareClosedLoopRun), powerBalance() slew-limited feedforward-walks the RAW setpoint through
// applyShareRatio(); if it HAS run (shareClosedLoopRun true, load fell away), it HOLDS the last
// commanded ratio instead. These tests are the fw v5 replacement for the deleted "governor
// collapses to 0.5" coverage — each must fail if the mechanism it names regresses.
static void test_governor_openloop_feedforward_walk() {
    test_group("fw v5 governor: open-loop feedforward walk at low current, converges to raw sp (G1/G2)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.09f; I_batt = 0.21f;           // I_tot = 0.30A, well under the 0.60A entry threshold
    power_share_setpoint = 0.30f;           // in-band

    uint32_t t = 0;
    float start = droopSlew_prev;           // 0.5, the fresh-reset default
    for (int i = 0; i < 5; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(!shareClosedLoopMode,
          "G1: still open-loop after a few ticks at 0.30A (well under the 0.60A entry threshold, "
          "which the filter can never cross since it asymptotes to totalA=0.30A)");
    check(shareCtrl_integ == 0.0f && fabsf(shareCtrl_heldOut - 0.5f) < 1e-9f,
          "G1: the Youla controller state never advances — powerBalance() never calls "
          "youlaController_Power() in open-loop mode");
    check(droopSlew_prev < start,
          "G1: the applied ratio is already walking DOWN toward the 0.30 setpoint (feedforward "
          "through applyShareRatio(), not held)");

    // G2: given enough ticks, the walk converges exactly to the RAW setpoint — not a clipped
    // value (the governor's minority-current clip is closed-loop-only) and not the deleted 0.5
    // collapse.
    for (int i = 0; i < 200; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - 0.30f) < 1e-6f,
          "G2: the feedforward walk converges to the RAW setpoint 0.30 (not the deleted 0.5 "
          "collapse, and not a clipped value)");
    check(!shareClosedLoopMode,
          "G2: still open-loop throughout — I_tot=0.30A never crosses the 0.60A entry threshold");
}

static void test_governor_closedloop_entry_and_response() {
    test_group("fw v5 governor: closed-loop entry once filtered I_tot crosses 0.60A, then steps (G3)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.4f; I_batt = 1.6f;             // I_tot = 2.0A, measured share = 0.20
    // sp == droopSlew_prev's fresh-reset default (0.5): the open-loop feedforward walk (target
    // 0.50, start 0.50) is a degenerate no-op, isolating this probe to the closed-loop
    // controller's own response once the mode transition happens.
    power_share_setpoint = 0.50f;

    uint32_t t = 0;
    for (int i = 0; i < 6; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(!shareClosedLoopMode,
          "G3: (setup) still open-loop a few ticks in — the filter hasn't crossed 0.60A yet");
    check(fabsf(droopSlew_prev - 0.5f) < 1e-6f,
          "G3: (setup) the open-loop walk is a no-op here (target == start == 0.5)");

    for (int i = 0; i < 20; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(shareClosedLoopMode && shareClosedLoopRun,
          "G3: closed-loop mode entered once the filtered total crosses 0.60A");

    for (int i = 0; i < 400; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(droopSlew_prev > 0.55f,
          "G3: the closed-loop controller drives the ratio UP in response to the +0.30 share "
          "error (sp=0.50, measured=0.20) — the mode transition actually engages control, not "
          "just a flag flip");
}

static void test_governor_closedloop_to_open_hold() {
    test_group("fw v5 governor: closed-loop exit -> HOLD, not feedforward (G4)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;

    // Force closed-loop entry directly (the entry mechanism itself is proven by G3): seed the
    // governor filter above the entry threshold so the very first tick transitions.
    share_govTotAFilt = 2.0f;
    I_fc = 0.4f; I_batt = 1.6f;
    power_share_setpoint = 0.70f;           // in-band, off the 0.5 seed so the controller moves
    uint32_t t = 0;
    for (int i = 0; i < 300; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(shareClosedLoopMode && shareClosedLoopRun, "G4: (setup) closed-loop, converged for a while");
    float heldRatio = droopSlew_prev;
    check(fabsf(heldRatio - 0.5f) > 0.02f, "G4: (setup) the ratio actually moved off the seed");

    // Drop the load: I_tot ~0.3A, well under the exit hysteresis (0.55A).
    I_fc = 0.09f; I_batt = 0.21f;
    for (int i = 0; i < 400; i++) {          // enough ticks for the filter to fall below 0.55A
        t += 1000; g_mock_micros = t; powerBalance();
    }
    check(!shareClosedLoopMode,
          "G4: filtered total fell below the 0.55A exit hysteresis — back to open-loop");
    check(shareClosedLoopRun,
          "G4: shareClosedLoopRun stays set — this profile HAS run closed loop, so open-loop "
          "means HOLD, not feedforward");

    float postDrop = droopSlew_prev;

    // Many more ticks: the ratio must stay frozen even though the raw setpoint (0.70) differs
    // from the held ratio — a feedforward walk would visibly move it toward 0.70.
    for (int i = 0; i < 500; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - postDrop) < 1e-9f,
          "G4: HOLD — the applied ratio is frozen across many open-loop ticks, not walking "
          "toward the (differing) raw setpoint 0.70");
}

// ─── T4 (S3, fw v5 review): a commanded setpoint change re-arms feedforward OUT of HOLD ──────
// HOLD (G4 above) is about a load that fell away, not about ignoring commands. A changed
// operator/EMS setpoint while parked in HOLD must take effect immediately at the NEW setpoint,
// open-loop, rather than silently waiting for the load to return (which could be never, e.g. a
// standstill epoch). share_actedSp is the mechanism: powerBalance() re-arms feedforward when
// |power_share_setpoint - share_actedSp| > SHARE_SP_CHANGE_EPS, clearing shareClosedLoopRun.
static void test_governor_hold_exit_on_setpoint_change() {
    test_group("fw v5 governor: a changed setpoint exits HOLD and resumes feedforward at the NEW value (S3)");

    // Seed HOLD directly (mode=false, run=true, a mid-band droopSlew_prev, share_actedSp
    // matching the current setpoint) rather than reaching it by running the real closed-loop
    // controller first: with no plant feedback in this synthetic harness, ANY sustained nonzero
    // error can make the Youla controller's raw (pre-slew) output spike out-of-band on an early
    // tick -- applyShareRatio()'s cutoff sees an UNSLEWED value whenever it lands outside
    // [DROOP_R_MIN, DROOP_R_MAX] (the slew clamp only applies to already-in-band outputs, by
    // design -- see the .ino comment at the slew-limit block), which can cut a channel and freeze
    // droopSlew_prev for a reason unrelated to the HOLD mechanism this test targets. Seeding the
    // state directly isolates the probe to exactly the S3 HOLD-exit logic.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = false;
    shareClosedLoopRun  = true;
    droopSlew_prev       = 0.65f;             // the "converged, then parked" ratio
    share_govTotAFilt    = 0.30f;             // low, well under the 0.60A entry threshold
    power_share_setpoint = 0.70f;
    share_actedSp         = 0.70f;            // last acted setpoint == current: no changed-edge yet
    I_fc = 0.09f; I_batt = 0.21f;             // I_tot=0.30A -- stays open-loop throughout

    // Confirm the hold itself first: a few ticks at the SAME (unchanged) setpoint must not move
    // the ratio -- isolates the "changed setpoint" trigger from ordinary HOLD behaviour.
    uint32_t t = 0;
    for (int i = 0; i < 20; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(!shareClosedLoopMode, "T4: (setup) still open-loop -- I_tot=0.30A never crosses 0.60A");
    check(shareClosedLoopRun, "T4: (setup) shareClosedLoopRun is still true -- HOLD, not fresh feedforward");
    check(fabsf(droopSlew_prev - 0.65f) < 1e-9f,
          "T4: (setup) confirmed HOLD -- unchanged setpoint, ratio frozen at the seeded 0.65");

    // Now command a NEW in-band setpoint, well clear of SHARE_SP_CHANGE_EPS and clear of the
    // held ratio so the direction of any movement is unambiguous.
    power_share_setpoint = 0.20f;
    t += 1000; g_mock_micros = t; powerBalance();
    check(!shareClosedLoopRun,
          "T4: the very next tick clears shareClosedLoopRun -- the changed setpoint re-arms "
          "feedforward instead of staying in HOLD");
    check(droopSlew_prev < 0.65f,
          "T4: the ratio already stepped DOWN toward the new setpoint (target 0.20 < the held "
          "0.65) on that same tick -- not still frozen at the old held value");
    check(droopSlew_prev >= 0.65f - DROOP_RATIO_SLEW_PER_TICK - 1e-6f,
          "T4: that first step is slew-limited (open-loop feedforward always constrains its "
          "target to droopSlew_prev +/- DROOP_RATIO_SLEW_PER_TICK), not a slam to 0.20");

    // Run it out: must converge to the NEW setpoint via feedforward, not stay parked.
    for (int i = 0; i < 300; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - 0.20f) < 1e-6f,
          "T4: feedforward converges to the NEW setpoint 0.20 -- HOLD did not swallow the "
          "commanded change");
    check(!shareClosedLoopMode,
          "T4: still open-loop throughout -- I_tot=0.30A never re-crosses the 0.60A entry "
          "threshold from this low-current change");
}

static void test_governor_hysteresis_band() {
    test_group("fw v5 governor: hysteresis band (0.55-0.60A) holds each mode's prior state (G5)");

    // From CLOSED: seed a converged closed loop, then park the filter (and the matching load,
    // so the filter doesn't drift) at 0.57A — inside the band — and confirm it stays closed
    // (the controller keeps stepping).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 0.57f;
    I_fc = 0.171f; I_batt = 0.399f;          // I_tot=0.57A -- matches filt, so it doesn't drift
    power_share_setpoint = 0.70f;
    uint32_t t = 0;
    float integBefore = shareCtrl_integ;
    for (int i = 0; i < 30; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(shareClosedLoopMode,
          "G5/closed: filt=0.57A (inside the 0.55-0.60 band) stays CLOSED when already closed");
    check(shareCtrl_integ != integBefore || fabsf(droopSlew_prev - 0.5f) > 1e-6f,
          "G5/closed: the controller is actually stepping (integrator moved or the ratio left "
          "the seed), not frozen, while parked in the band");

    // From OPEN: fresh reset (open-loop default), park the filter (and load) at 0.57A —
    // must stay open (feedforward walk, never enters, since entry needs STRICTLY > 0.60A).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    share_govTotAFilt = 0.57f;
    I_fc = 0.171f; I_batt = 0.399f;
    power_share_setpoint = 0.70f;
    t = 0;
    for (int i = 0; i < 30; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(!shareClosedLoopMode,
          "G5/open: filt=0.57A (inside the band, but not > the 0.60A entry bound) stays OPEN "
          "when already open");
}

// ─── T7: hysteresis literal boundaries (strict inequalities, not >=/<=) ──────────────────────
// Entry is `share_govTotAFilt > 2*SHARE_MINORITY_I_MIN_A` (strictly greater); exit is
// `share_govTotAFilt < 2*SHARE_MINORITY_I_MIN_A - SHARE_GOV_OL_HYST_A` (strictly less). At the
// EXACT boundary values (0.60A entering from open, 0.55A exiting from closed) neither transition
// may fire -- an off-by-one (>= instead of >, or <= instead of <) would flip these two cases.
static void test_governor_hysteresis_exact_boundaries() {
    test_group("fw v5 governor: hysteresis literal boundaries (T7, strict inequalities)");

    // Exactly at the entry threshold (0.60A) from OPEN: must NOT enter (entry needs STRICTLY >).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    share_govTotAFilt = 2.0f * SHARE_MINORITY_I_MIN_A;   // exactly 0.60A
    // I_fc alone reproduces the SAME float bit pattern as share_govTotAFilt (both derived from
    // the identical expression), so the filter update this tick is an exact no-op -- no risk of
    // float rounding nudging filt a few ULPs past the boundary and silently flipping the result.
    I_fc = 2.0f * SHARE_MINORITY_I_MIN_A; I_batt = 0.0f;  // I_tot == filt, bit-exact
    power_share_setpoint = 0.70f;
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(!shareClosedLoopMode,
          "T7: share_govTotAFilt exactly at 2*SHARE_MINORITY_I_MIN_A (0.60A) does NOT enter -- "
          "entry is strictly '>', not '>='");

    // Exactly at the exit threshold (0.55A) from CLOSED: must NOT exit (exit needs STRICTLY <).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 2.0f * SHARE_MINORITY_I_MIN_A - SHARE_GOV_OL_HYST_A;   // exactly 0.55A
    // Same bit-exact trick as the entry case above.
    I_fc = 2.0f * SHARE_MINORITY_I_MIN_A - SHARE_GOV_OL_HYST_A; I_batt = 0.0f;
    power_share_setpoint = 0.70f;
    t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareClosedLoopMode,
          "T7: share_govTotAFilt exactly at 2*SHARE_MINORITY_I_MIN_A - SHARE_GOV_OL_HYST_A "
          "(0.55A) does NOT exit -- exit is strictly '<', not '<='");
}

static void test_governor_open_to_closed_continuity() {
    test_group("fw v5 governor: open->closed transition is continuous, filt not reset (G6)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.09f; I_batt = 0.21f;            // I_tot=0.30A -- open-loop feedforward
    power_share_setpoint = 0.20f;            // walks the ratio away from the 0.5 seed
    uint32_t t = 0;
    for (int i = 0; i < 30; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(!shareClosedLoopMode, "G6: (setup) still open-loop at I_tot=0.30A");
    float heldBeforeEntry = droopSlew_prev;
    check(fabsf(heldBeforeEntry - 0.20f) < 0.05f,
          "G6: (setup) the feedforward walk has moved the ratio well off the 0.5 seed");

    // Jump the load up — filt crosses 0.60A over the next several ticks. Track the exact tick
    // where the mode flips and capture the ratio immediately before/after it.
    I_fc = 0.4f; I_batt = 1.6f;
    bool wasClosed = false, transitioned = false;
    float beforeTransition = droopSlew_prev, afterTransition = droopSlew_prev;
    for (int i = 0; i < 40 && !transitioned; i++) {
        float pre = droopSlew_prev;
        t += 1000; g_mock_micros = t; powerBalance();
        if (!wasClosed && shareClosedLoopMode) {
            beforeTransition = pre;
            afterTransition  = droopSlew_prev;
            transitioned = true;
        }
        wasClosed = shareClosedLoopMode;
    }
    check(transitioned, "G6: (setup) the load jump crossed the entry threshold within the window");
    check(fabsf(share_govTotAFilt) > 1e-6f,
          "G6: share_govTotAFilt was NOT reset by the transition — resetShareControllerCore() "
          "deliberately does not touch it (zeroing it would drop straight back to open-loop the "
          "very next tick)");
    check(fabsf(afterTransition - beforeTransition) <= DROOP_RATIO_SLEW_PER_TICK + 1e-4f,
          "G6: the transition tick's write lands within one slew step of the pre-transition "
          "ratio — continuous hand-off, not a jump back to the 0.5 default");
}

// ─── fw v6: effective-setpoint slew (share_spEffPrev) ────────────────────────────────────────
// Before fw v6 the OPEN->CLOSED handover stepped the controller's REFERENCE in one tick: open
// loop feeds the raw setpoint forward, but the first closed-loop tick handed the controller the
// FLOOR-CLIPPED value outright (up to a 0.35 share discontinuity at the 0.60A crossing, right at
// the load level the sweep's failures live at). share_spEffPrev wraps the reference itself,
// walking toward the governor-clipped target at DROOP_RATIO_SLEW_PER_TICK -- the same ceiling
// the actuation path already used -- so reference and actuation cannot disagree about how fast
// the split may move, and every CONVERGED hold point is bit-identical to fw v5 (only the
// handover transient changes).
static void test_share_eff_setpoint_slew_from_seed_at_transition() {
    test_group("fw v6: share_spEffPrev seeds from droopSlew_prev at the OL->CL transition and slews toward the governor-clipped target");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.09f; I_batt = 0.21f;            // I_tot=0.30A -- open-loop feedforward
    power_share_setpoint = 0.15f;            // in-band (== DROOP_R_MIN)
    uint32_t t = 0;
    for (int i = 0; i < 30; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(!shareClosedLoopMode, "eff-slew: (setup) still open-loop at I_tot=0.30A");
    check(fabsf(droopSlew_prev - 0.15f) < 0.01f,
          "eff-slew: (setup) the feedforward walk converged near the 0.15 setpoint");

    // Jump the load up -- filt crosses 0.60A over the next several ticks. Capture droopSlew_prev
    // immediately BEFORE the transition tick (the seed resetShareControllerCore() will use) and
    // share_spEffPrev immediately AFTER it (the seed plus at most one slew step toward whatever
    // the governor-clipped target is at that instant).
    I_fc = 0.4f; I_batt = 1.6f;
    bool wasClosed = false, transitioned = false;
    float seedBefore = 0.0f, effAfterTransitionTick = 0.0f;
    for (int i = 0; i < 40 && !transitioned; i++) {
        float preRatio = droopSlew_prev;
        t += 1000; g_mock_micros = t; powerBalance();
        if (!wasClosed && shareClosedLoopMode) {
            seedBefore              = preRatio;
            effAfterTransitionTick  = share_spEffPrev;
            transitioned = true;
        }
        wasClosed = shareClosedLoopMode;
    }
    check(transitioned, "eff-slew: (setup) the load jump crossed the entry threshold within the window");
    check(fabsf(effAfterTransitionTick - seedBefore) <= DROOP_RATIO_SLEW_PER_TICK + 1e-4f,
          "eff-slew: on the transition tick, share_spEffPrev moved at most one DROOP_RATIO_SLEW_PER_TICK "
          "step away from the seed (droopSlew_prev just before the transition) -- never a jump "
          "straight to the governor-clipped target");
}

static void test_share_eff_setpoint_slew_converges_to_clipped_target() {
    test_group("fw v6: share_spEffPrev converges exactly to the governor-clipped target and holds (steady state == fw v5)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 4.0f;              // well above the hysteresis sliver -- the clip is a no-op here
    I_fc = 1.6f; I_batt = 2.4f;              // I_tot=4.0A, matches filt (no drift)
    power_share_setpoint = 0.30f;            // in-band, well clear of the lo/hi clip at this load
    uint32_t t = 0;
    for (int i = 0; i < 200; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(share_spEffPrev - 0.30f) < 1e-6f,
          "eff-slew: share_spEffPrev converges EXACTLY to the target (0.30 is well inside the "
          "feasible band at 4.0A, so the governor clip is a no-op) -- constrain() lands bit-exact "
          "once within one slew step, matching the .ino's own convergence claim");
    float held = share_spEffPrev;
    for (int i = 0; i < 50; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(share_spEffPrev - held) < 1e-9f,
          "eff-slew: once converged, share_spEffPrev holds steady -- no residual slew activity "
          "once at the target");
}

static void test_share_eff_setpoint_slew_reset_reseeds() {
    test_group("fw v6: resetShareControllerCore()/resetShareControlState() re-seed share_spEffPrev");

    // resetShareControllerCore(seed) seeds share_spEffPrev to constrain(seed, DROOP_R_MIN, DROOP_R_MAX).
    reset_test_state();
    share_spEffPrev = 0.10f;   // dirty it first, so the reseed is observable
    resetShareControllerCore(0.70f);
    check(fabsf(share_spEffPrev - 0.70f) < 1e-6f,
          "eff-slew reset: resetShareControllerCore(0.70) seeds share_spEffPrev to 0.70 (in-band, unclipped)");

    // Out-of-band seeds are clipped INTO the droop band -- an out-of-band reference would slew
    // the controller through dead space the governor clip can never actually produce.
    resetShareControllerCore(0.05f);
    check(fabsf(share_spEffPrev - DROOP_R_MIN) < 1e-6f,
          "eff-slew reset: an out-of-band seed (0.05) clips to DROOP_R_MIN, never left outside "
          "the band the governor clip can produce");
    resetShareControllerCore(0.95f);
    check(fabsf(share_spEffPrev - DROOP_R_MAX) < 1e-6f,
          "eff-slew reset: an out-of-band seed (0.95) clips to DROOP_R_MAX");

    // resetShareControlState() (the historic fresh-start reset) seeds at 0.5 -- same idiom, one
    // layer up.
    share_spEffPrev = 0.10f;
    resetShareControlState();
    check(fabsf(share_spEffPrev - 0.5f) < 1e-6f,
          "eff-slew reset: resetShareControlState() re-seeds share_spEffPrev to 0.5, the historic "
          "fresh-start split");
}

static void test_governor_reset_clears_closedloop_run() {
    test_group("fw v5 governor: resetShareControlState() clears shareClosedLoopRun (G7)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    share_govTotAFilt = 2.0f;                // force immediate closed-loop entry
    I_fc = 0.4f; I_batt = 1.6f;
    power_share_setpoint = 0.70f;
    uint32_t t = 0;
    for (int i = 0; i < 100; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(shareClosedLoopMode && shareClosedLoopRun, "G7: (setup) the loop is closed and has run");

    g_mock_micros = t;
    startTrapProfile(2.0f, 1000, 1.0f);      // resetShareControlState() at profile entry
    check(!shareClosedLoopMode && !shareClosedLoopRun,
          "G7: resetShareControlState() clears both fw v5 loop-mode flags at profile start");

    // Post-reset at low current must feedforward-walk again, not hold — proves
    // shareClosedLoopRun==false is what routes open-loop mode to the walk branch, not the hold
    // branch (a stale true here would silently freeze every post-reset low-current run).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.09f; I_batt = 0.21f;
    power_share_setpoint = 0.25f;
    t = 0;
    for (int i = 0; i < 30; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - 0.5f) > 0.01f,
          "G7: after a fresh reset, open-loop mode WALKS toward the setpoint (shareClosedLoopRun "
          "false selects the feedforward branch, not the hold branch)");
}

static void test_governor_lo_clamp_sliver() {
    test_group("fw v5 governor: lo-clamp sliver keeps the closed-loop bound at <=0.5 (G9)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 0.58f;             // inside the hysteresis sliver (0.55, 0.60)
    // Unclamped: lo = 0.30/0.58 = 0.517 > hi = 1-0.517 = 0.483 -- an INVERTED pair. The
    // `if (lo > 0.5f) lo = 0.5f;` clamp must degenerate this to the balanced split (0.5)
    // instead of Arduino constrain()'s lo>hi behaviour (which returns the raw lo, 0.517).
    //
    // Zero-error confirmation, not a convergence probe: this synthetic test drives I_fc/I_batt
    // directly (no plant feedback closes the loop), so a controller fed a sustained NONZERO
    // error only winds toward the output rail over many ticks -- it never settles. Pin the
    // measured share EXACTLY at the correct clamped target (0.5): a correct clamp sees zero
    // error and the ratio (already seeded at 0.5 by the fresh reset) must never move at all;
    // a buggy unclamped implementation would see a standing +0.017 error (target 0.517) and
    // wind visibly away from 0.5 over the run.
    I_fc = 0.29f; I_batt = 0.29f;            // I_tot=0.58A (matches filt, no drift), measured=0.50
    power_share_setpoint = 0.20f;            // in-band; irrelevant once clipped into the sliver
    uint32_t t = 0;
    for (int i = 0; i < 800; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - 0.5f) < 1e-4f,
          "G9: the closed-loop clip degenerates to the balanced split 0.5 across the sliver "
          "(zero error at the clamped bound, so the ratio never moves) -- an unclamped "
          "implementation would see a standing error and wind away from 0.5");
}

static void test_governor_setpoint_latch_precedence_at_low_current() {
    test_group("fw v5 governor: out-of-band setpoint latches even at low current, no feedforward (G10)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.09f; I_batt = 0.21f;            // I_tot=0.30A -- would otherwise be open-loop
    power_share_setpoint = 0.90f;            // out-of-band (> DROOP_R_MAX=0.85)

    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareIsoBT && shareSpCutBT,
          "G10: the out-of-band setpoint latches BT off the bus even at low current");
    check(fabsf(droopSlew_prev - 0.5f) < 1e-9f,
          "G10: droopSlew_prev never moved -- updateShareSetpointCutoff() owns this tick and "
          "returns before the governor/open-loop code ever runs");
    check(SPI.transfer_log.empty(),
          "G10: the latch-entry tick makes no MDAC write at all -- confirms the open-loop "
          "feedforward branch never executed");
}

static void test_governor_min_load_gate_precedes_governor() {
    test_group("fw v5 governor: SHARE_I_TOT_MIN_A gate freezes everything before the governor (G11)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.02f; I_batt = 0.03f;            // I_tot=0.05A < SHARE_I_TOT_MIN_A=0.075A
    power_share_setpoint = 0.20f;            // in-band -- would otherwise feedforward-walk

    uint32_t t = 0;
    for (int i = 0; i < 200; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(share_govTotAFilt == 0.0f,
          "G11: share_govTotAFilt never updates below SHARE_I_TOT_MIN_A -- the min-load gate "
          "returns before the filter update");
    check(fabsf(droopSlew_prev - 0.5f) < 1e-9f,
          "G11: the ratio never moves -- the open-loop feedforward walk is also gated out below "
          "SHARE_I_TOT_MIN_A");
    check(!shareClosedLoopMode,
          "G11: mode stays open -- the entry condition is never even evaluated");
}

static void test_droop_ratio_slew_limit() {
    test_group("powerBalance() droop-ratio slew limit (limit-cycle mitigation)");

    // Sustained large in-band error at high load (governor inactive): the
    // controller wants a big ratio move; the applied ratio must walk in
    // ≤ DROOP_RATIO_SLEW_PER_TICK steps, never slam.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 1.6f; I_batt = 2.4f;            // I_tot=4.0, measured share = 0.40
    power_share_setpoint = 0.60f;          // +0.20 sustained error
    uint32_t t = 0;
    float prev = droopSlew_prev;
    float maxStep = 0.0f;
    for (int i = 0; i < 100; i++) {
        t += 1000; g_mock_micros = t;
        powerBalance();
        float step = fabsf(droopSlew_prev - prev);
        if (step > maxStep) maxStep = step;
        prev = droopSlew_prev;
    }
    check(maxStep <= DROOP_RATIO_SLEW_PER_TICK + 1e-5f,
          "slew limit: no single tick moves the applied ratio by more than the per-tick ceiling");
    check(fabsf(droopSlew_prev - 0.5f) > 0.05f,
          "slew limit: the ratio still WALKS under a sustained error (limited, not frozen)");

    // One-shot actuation paths are NOT slewed: a direct applyShareRatio() jump
    // (operator 'O', guard fallback, completion restore) lands immediately and
    // re-seeds the limiter's origin.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    applyShareRatio(0.8f);
    check(fabsf(droopSlew_prev - 0.8f) < 1e-6f,
          "slew limit: direct applyShareRatio() jumps land in one call and re-seed the tracker");
    applyShareRatio(0.2f);
    check(fabsf(droop_gain_FC_actual - K_DROOP / (RE_MAX * 0.2f)) < 1e-5f,
          "slew limit: one-shot mapping is exact (no controller-path throttling)");
}

static void test_share_state_reset_on_profile_start() {
    test_group("resetShareControlState() at profile entry (limit-cycle mitigation)");

    // Converge the controller away from mid-band, then start a trapezoid
    // profile: the controller state must reset (held output back to 0.5,
    // governor filter emptied) while the slew tracker keeps the ratio the
    // MDACs physically hold — the 2026-08-11 sweep showed every run inherited
    // the previous run's controller state (only fresh-boot TP0007 was clean).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 3.0f; I_batt = 1.0f;            // measured 0.75, sp 0.5 → sustained error
    power_share_setpoint = 0.5f;
    uint32_t t = 0;
    for (int i = 0; i < 400; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(shareCtrl_heldOut - 0.5f) > 0.02f,
          "profile reset: (setup) controller state is away from mid-band before the start");
    float slew_before = droopSlew_prev;

    g_mock_micros = t;
    startTrapProfile(2.0f, 1000, 1.0f);
    check(fabsf(shareCtrl_heldOut - 0.5f) < 1e-6f,
          "profile reset: 'T' start resets the held controller output to the balanced split");
    check(share_govTotAFilt == 0.0f,
          "profile reset: the governor load filter restarts empty");
    check(fabsf(droopSlew_prev - slew_before) < 1e-6f,
          "profile reset: the slew tracker is NOT reset — it mirrors the ratio physically on the MDACs");
}

// ─── applyShareRatio(): full-span [0,1] actuation + channel cutoff ───────────
// Ratios outside [DROOP_R_MIN, DROOP_R_MAX] must take the starved channel's
// RT1987 bus switch off the bus (never the boost enable), hold the active
// channel's droop gain, and re-enter with SHARE_CUTOFF_HYST hysteresis only
// when the bus is charged. Controller-initiated isolation only: manual/state
// switch actions clear the flags and are never auto-reverted.
static void test_share_ratio_cutoff() {
    test_group("applyShareRatio() channel cutoff");

    // In-band ratio: both switches untouched, gains follow the mapping.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    applyShareRatio(0.5f);
    check(digitalRead(FC_BUS_ENABLE) == HIGH && digitalRead(BT_BUS_ENABLE) == HIGH,
          "cutoff: in-band ratio leaves both channels on the bus");
    float gFC_mid = droop_gain_FC_actual;
    float gBT_mid = droop_gain_BT_actual;

    // r = 0: FC starved → FC_BUS opens, boost enables untouched, BT gain held.
    digitalWrite(FC_REG_ENABLE, HIGH);
    digitalWrite(BT_REG_ENABLE, HIGH);
    applyShareRatio(0.0f);
    check(digitalRead(FC_BUS_ENABLE) == LOW,
          "cutoff: r=0 opens FC_BUS_ENABLE");
    check(digitalRead(FC_REG_ENABLE) == HIGH && digitalRead(BT_REG_ENABLE) == HIGH,
          "cutoff: boost enables are NEVER touched (bus-switch isolation only)");
    check(fabsf(droop_gain_BT_actual - gBT_mid) < 1e-6f &&
          fabsf(droop_gain_FC_actual - gFC_mid) < 1e-6f,
          "cutoff: droop gains held while FC is isolated");
    check(shareIsoFC && !shareIsoBT, "cutoff: FC isolation flag set");

    // Hysteresis: r just above DROOP_R_MIN but inside the hysteresis band
    // must NOT re-enter; at DROOP_R_MIN + hyst it must.
    applyShareRatio(DROOP_R_MIN + SHARE_CUTOFF_HYST / 2.0f);
    check(digitalRead(FC_BUS_ENABLE) == LOW,
          "cutoff: re-entry refused inside the hysteresis band");
    applyShareRatio(DROOP_R_MIN + SHARE_CUTOFF_HYST);
    check(digitalRead(FC_BUS_ENABLE) == HIGH && !shareIsoFC,
          "cutoff: re-entry at DROOP_R_MIN + hysteresis closes FC back onto the bus");
    check(fabsf(droop_gain_FC_actual - gFC_mid) > 1e-6f,
          "cutoff: mapping resumes after re-entry (gains move again)");

    // Re-entry must be refused while the bus is below the charged threshold.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    digitalWrite(FC_REG_ENABLE, HIGH);   // re-entry also requires the boost enabled (fw v4 S5)
    digitalWrite(BT_REG_ENABLE, HIGH);
    V_bus = 16.0f;
    applyShareRatio(0.0f);                       // isolate FC
    V_bus = V_BUS_CHARGED_THRESH - 1.0f;         // bus collapses meanwhile
    applyShareRatio(0.5f);
    check(digitalRead(FC_BUS_ENABLE) == LOW && shareIsoFC,
          "cutoff: re-entry refused while V_bus is below the charged threshold");
    V_bus = 16.0f;
    applyShareRatio(0.5f);
    check(digitalRead(FC_BUS_ENABLE) == HIGH && !shareIsoFC,
          "cutoff: re-entry proceeds once the bus is charged again");

    // r = 1: symmetric BT cutoff.
    applyShareRatio(1.0f);
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareIsoBT,
          "cutoff: r=1 opens BT_BUS_ENABLE");
    applyShareRatio(DROOP_R_MAX - SHARE_CUTOFF_HYST);
    check(digitalRead(BT_BUS_ENABLE) == HIGH && !shareIsoBT,
          "cutoff: BT re-entry at DROOP_R_MAX - hysteresis");

    // safeAllSwitches() takes ownership: flags clear, and an in-band ratio
    // afterwards must NOT re-close the state-opened switches.
    applyShareRatio(0.0f);                       // controller isolates FC
    safeAllSwitches();
    check(!shareIsoFC && !shareIsoBT,
          "cutoff: safeAllSwitches() clears the isolation flags");
    applyShareRatio(0.5f);
    check(digitalRead(FC_BUS_ENABLE) == LOW && digitalRead(BT_BUS_ENABLE) == LOW,
          "cutoff: controller never re-closes switches it no longer owns");

    // LAST-SOURCE GUARD: with the other channel off the bus, a cutoff must be
    // refused (the controller may never darken the bus) and the request must
    // fall back to the band-edge clip so droop authority stays live.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, LOW);    // battery off the bus (e.g. FC-charge cruise)
    V_bus = 16.0f;
    applyShareRatio(0.0f);               // FC starved — but FC is the only live source
    check(digitalRead(FC_BUS_ENABLE) == HIGH && !shareIsoFC,
          "cutoff: last-source guard refuses to cut the only channel on the bus");
    check(fabsf(droop_gain_FC_actual - K_DROOP / (RE_MAX * DROOP_R_MIN)) < 1e-4f,
          "cutoff: guard-blocked request falls back to the band-edge clip");

    // Ownership handoff to the charge path: if the controller had isolated BT
    // and the charge manager then asserts FC_CHARGE (which drives BT_BUS LOW
    // itself), the controller's claim must be dropped — its re-entry would
    // otherwise close BT_BUS while FC_CHARGE is HIGH (illegal combination).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    applyShareRatio(1.0f);                   // controller isolates BT
    check(shareIsoBT, "cutoff: (setup) controller holds BT isolation");
    assertFcChargeEnable(true);              // charge path takes BT_BUS
    check(!shareIsoBT, "cutoff: assertFcChargeEnable(true) takes over BT ownership");
    applyShareRatio(0.5f);                   // mid-band: must NOT re-close BT
    check(digitalRead(BT_BUS_ENABLE) == LOW && digitalRead(FC_CHARGE_ENABLE) == HIGH,
          "cutoff: no BT re-entry while the FC-charge path holds BT_BUS LOW");
    assertFcChargeEnable(false);

    // 'O' path: applyOpenLoopDroop() accepts the full span and drives the
    // same cutoff (and clears powerBalanceLive).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    powerBalanceLive = true;
    applyOpenLoopDroop(1.0f);
    check(digitalRead(BT_BUS_ENABLE) == LOW && !powerBalanceLive,
          "cutoff: 'O 1.0' cuts BT off the bus and clears powerBalanceLive");

    // Setpoint entry point: full [0,1] accepted (old clamp was [0.01,0.99]).
    setPowerShareSetpointLive(0.0f);
    check(power_share_setpoint == 0.0f, "setpoint: 0.0 accepted verbatim");
    setPowerShareSetpointLive(1.0f);
    check(power_share_setpoint == 1.0f, "setpoint: 1.0 accepted verbatim");
}

// ─── T1 (S2, fw v5 review): setPowerShareSetpointLive() resets the loop-mode state ───────────
// Without resetShareControlState() here, shareClosedLoopRun/shareClosedLoopMode/share_govTotAFilt
// survive an 'X'/'Q'/safeAllSwitches()/bring-up/State-99 from an earlier run, so a 'P' typed at
// low current would land in the HOLD branch and be a silent no-op (no MDAC write, ever, until
// load happens to return) instead of feedforward-walking to the new operator-commanded setpoint.
static void test_setpowersharesetpointlive_resets_loop_mode() {
    test_group("setPowerShareSetpointLive() resets the fw v5 loop-mode state (S2)");

    reset_test_state();
    // Simulate the exact hazard: a PRIOR run left the loop parked in HOLD (as if the load fell
    // away after converging closed-loop) with a stale nonzero governor filter.
    shareClosedLoopRun  = true;
    shareClosedLoopMode = true;
    share_govTotAFilt   = 1.23f;

    setPowerShareSetpointLive(0.6f);

    check(power_share_setpoint == 0.6f,
          "S2: the new setpoint is accepted as usual");
    check(!shareClosedLoopMode,
          "S2: shareClosedLoopMode is cleared -- a stale CLOSED flag would otherwise make the "
          "very next powerBalance() tick re-evaluate the exit hysteresis instead of starting "
          "fresh open-loop");
    check(!shareClosedLoopRun,
          "S2: shareClosedLoopRun is cleared -- this is the fix's whole point: a stale true here "
          "routes a low-current 'P' straight into the HOLD branch (no MDAC write, silent no-op) "
          "instead of feedforward-walking to the new setpoint");
    check(share_govTotAFilt == 0.0f,
          "S2: share_govTotAFilt is zeroed -- a stale nonzero filter could otherwise sit above "
          "the closed-loop entry threshold and re-enter CLOSED on the very first tick instead of "
          "giving the operator's new setpoint an open-loop tick first");
}

// ─── Setpoint-latched channel cutoff ("one owner per setpoint", fw v4 2026-08-12) ────
// updateShareSetpointCutoff() gives every SETPOINT exactly one owner: in-band → the
// governor; out-of-band ([DROOP_R_MIN, DROOP_R_MAX] = [0.15, 0.85]) → this latch, which
// freezes the WHOLE share loop (no governor, no controller step, no MDAC write) and
// disables applyShareRatio()'s ratio-hysteresis re-entry for the latched channel. This
// closes the two TP0037 (in-band settle, cutoff never fires)/TP0015 (standing error winds
// past the 0.01 re-entry hysteresis, ~190 cycles/run) gaps described in the .ino changelog.
static void test_share_setpoint_cutoff_bt_high_side() {
    test_group("updateShareSetpointCutoff(): sp>DROOP_R_MAX latches BT, freezes the loop");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;                          // charged (irrelevant to entry, only to release)
    I_fc = 1.0f; I_batt = 0.5f;
    power_share_setpoint = 0.87f;           // > DROOP_R_MAX = 0.85

    uint32_t t = 0;
    t += 1000; g_mock_micros = t;
    powerBalance();                          // FIRST tick: entry fires and the loop freezes
    check(digitalRead(BT_BUS_ENABLE) == LOW,
          "sp-cutoff: first tick opens BT_BUS_ENABLE on the out-of-band setpoint");
    check(shareIsoBT && shareSpCutBT,
          "sp-cutoff: shareIsoBT (topology) and shareSpCutBT (setpoint latch) both set");
    check(digitalRead(FC_BUS_ENABLE) == HIGH,
          "sp-cutoff: FC (the surviving source) stays on the bus");
    check(SPI.transfer_log.empty(),
          "sp-cutoff: the entry tick returns before any MDAC write (updateShareSetpointCutoff "
          "runs BEFORE the min-load gate and the controller step)");

    // Standing topology-forced share error: BT is off the bus, so its measured current is
    // truthfully ~0 and the measured share pins at 1.0 — exactly the condition that wound
    // the old ratio-based cutoff back over its re-entry hysteresis (TP0015). Drive many
    // ticks and confirm zero hunting: the switch never toggles and the controller state
    // (Youla integrator + biquads, reset at the top of the test via reset_test_state())
    // never advances, because powerBalance() returns before ever calling the controller.
    I_fc = 1.0f; I_batt = 0.0f;
    int transitions = 0;
    int prevRead = digitalRead(BT_BUS_ENABLE);
    for (int i = 0; i < 500; i++) {
        t += 1000; g_mock_micros = t;
        powerBalance();
        int r = digitalRead(BT_BUS_ENABLE);
        if (r != prevRead) transitions++;
        prevRead = r;
    }
    check(transitions == 0,
          "sp-cutoff: zero BT_BUS_ENABLE transitions over 500 ticks of standing error — no hunting");
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareIsoBT && shareSpCutBT,
          "sp-cutoff: still latched after 500 ticks");
    check(SPI.transfer_log.empty(),
          "sp-cutoff: no MDAC writes at all while latched — the controller never steps");
    check(shareCtrl_integ == 0.0f && fabsf(shareCtrl_heldOut - 0.5f) < 1e-9f,
          "sp-cutoff: the Youla controller state never advanced from its fresh-reset values "
          "(controller freeze, not just a frozen output)");
}

static void test_share_setpoint_cutoff_fc_low_side() {
    test_group("updateShareSetpointCutoff(): sp<DROOP_R_MIN latches FC (TP0015 regression)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.5f; I_batt = 1.0f;
    power_share_setpoint = 0.12f;           // < DROOP_R_MIN = 0.15

    uint32_t t = 0;
    t += 1000; g_mock_micros = t;
    powerBalance();
    check(digitalRead(FC_BUS_ENABLE) == LOW && shareIsoFC && shareSpCutFC,
          "sp-cutoff (low side): first tick opens FC_BUS_ENABLE and latches");

    // TP0015's actual failure mode: FC off the bus pins measured share at 0.0, sp=0.12 is a
    // large standing error that, pre-fw-v4, wound the controller output back across
    // SHARE_CUTOFF_HYST at ~20 Hz (~190 FC_BUS_ENABLE cycles/run). Confirm the fix: zero
    // transitions over a run-length tick count.
    I_fc = 0.0f; I_batt = 1.0f;
    int transitions = 0;
    int prevRead = digitalRead(FC_BUS_ENABLE);
    for (int i = 0; i < 2000; i++) {          // ~2s at a 1ms tick — several TP0015 cycle periods
        t += 1000; g_mock_micros = t;
        powerBalance();
        int r = digitalRead(FC_BUS_ENABLE);
        if (r != prevRead) transitions++;
        prevRead = r;
    }
    check(transitions == 0,
          "sp-cutoff (low side): zero FC_BUS_ENABLE transitions — TP0015's ~20Hz hunting is gone");
}

static void test_share_setpoint_cutoff_release() {
    test_group("updateShareSetpointCutoff(): release on in-band setpoint, gated on V_bus");

    // Release with the bus charged: the switch re-closes, both flags clear, and
    // resetShareControlState() ran — observable via share_govTotAFilt, which
    // resetShareControlState() zeroes and which powerBalance() only re-populates once
    // totalA >= SHARE_I_TOT_MIN_A. Hold the source currents at 0 on the release tick itself
    // so the min-load gate returns immediately after release and the zeroed filter is still
    // visible (not yet re-touched by a controller step).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    digitalWrite(BT_REG_ENABLE, HIGH);   // release also requires the boost enabled (fw v4 S5)
    V_bus = 16.0f;
    power_share_setpoint = 0.87f;
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();      // latch BT
    check(shareSpCutBT, "release: (setup) BT is latched");
    share_govTotAFilt = 0.42f;                          // dirty it so the reset is observable

    power_share_setpoint = 0.5f;                        // back in-band
    I_fc = 0.0f; I_batt = 0.0f;                          // keep this tick below SHARE_I_TOT_MIN_A
    t += 1000; g_mock_micros = t; powerBalance();
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "release: BT_BUS_ENABLE re-closes once the setpoint returns in-band with a charged bus");
    check(!shareIsoBT && !shareSpCutBT,
          "release: both shareIsoBT and shareSpCutBT clear on release");
    check(share_govTotAFilt == 0.0f,
          "release: resetShareControlState() ran (governor filter re-zeroed, not re-populated yet)");

    // Release with the bus LOW: the latch is held (retried, not abandoned) — releasing onto
    // an unregulated bus would close a running-but-unloaded boost onto an unregulated rail,
    // the hot-plug direction the guard exists to prevent.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    digitalWrite(BT_REG_ENABLE, HIGH);   // release also requires the boost enabled (fw v4 S5)
    V_bus = 16.0f;
    power_share_setpoint = 0.87f;
    t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutBT, "release/low-bus: (setup) BT latched");

    power_share_setpoint = 0.5f;
    V_bus = V_BUS_CHARGED_THRESH - 1.0f;                // bus not regulated
    I_fc = 1.0f; I_batt = 0.0f;
    for (int i = 0; i < 50; i++) {
        t += 1000; g_mock_micros = t;
        powerBalance();
    }
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareIsoBT && shareSpCutBT,
          "release/low-bus: stays latched/isolated while V_bus < V_BUS_CHARGED_THRESH");

    V_bus = 16.0f;                                       // bus recovers
    t += 1000; g_mock_micros = t;
    powerBalance();
    check(digitalRead(BT_BUS_ENABLE) == HIGH && !shareIsoBT && !shareSpCutBT,
          "release/low-bus: releases on the first tick after V_bus recovers");
}

static void test_share_setpoint_cutoff_single_source_guard() {
    test_group("updateShareSetpointCutoff(): last-source guard blocks a latch");

    // BT is already off the bus (operator/state action, not the setpoint latch). An
    // out-of-band low setpoint asking to cut FC — the only live source — must be refused:
    // the entry guard requires BOTH switches HIGH. Governed control must continue on FC
    // (droop authority stays live — mirrors applyShareRatio()'s own last-source guard).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, LOW);       // battery already off the bus
    V_bus = 16.0f;
    I_fc = 1.0f; I_batt = 0.0f;
    power_share_setpoint = 0.12f;           // < DROOP_R_MIN — would latch FC if guard-unblocked

    uint32_t t = 0;
    for (int i = 0; i < 50; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(digitalRead(FC_BUS_ENABLE) == HIGH,
          "single-source guard: FC — the only live source — is never cut by the setpoint latch");
    check(!shareIsoFC && !shareSpCutFC,
          "single-source guard: no latch claimed (guard-blocked entry falls through)");
    check(!SPI.transfer_log.empty(),
          "single-source guard: normal governed control continues — MDAC gains are still written");
}

// F1 FIX CONFIRMED (2026-08-12, fw v5 review round): an earlier pass of this suite found this
// test failing on its middle two checks — a release tick fell through into the open-loop
// feedforward branch the SAME tick (updateShareSetpointCutoff() returns false, not true, on a
// release) and fed the still-out-of-band opposite-side setpoint to applyShareRatio() unslewed,
// cutting BT via the informal ratio-based path (shareIsoBT, not shareSpCutBT) before the
// intended one-live-tick gap. That was reported as a firmware defect rather than patched. The
// firmware now guards this explicitly: powerBalance()'s open-loop feedforward branch (F1 comment
// there) returns quietly on `power_share_setpoint < DROOP_R_MIN || > DROOP_R_MAX` before ever
// calling applyShareRatio(), so a release-tick out-of-band setpoint is left for the latch's own
// entry branch on the NEXT tick instead. This test passes unmodified again.
static void test_share_setpoint_cutoff_side_flip() {
    test_group("updateShareSetpointCutoff(): FC latched -> BT latched never darkens the bus");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    digitalWrite(FC_REG_ENABLE, HIGH);   // FC's release later in this flip needs the boost enabled (fw v4 S5)
    V_bus = 16.0f;
    I_fc = 0.0f; I_batt = 1.0f;
    power_share_setpoint = 0.12f;           // latch FC low-side
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutFC && digitalRead(FC_BUS_ENABLE) == LOW,
          "side flip: (setup) FC latched");

    // Flip the setpoint to the opposite extreme. Release (FC) is evaluated first and — per
    // the .ino design comment — a release tick returns without also evaluating entry, so the
    // BT latch cannot engage on the SAME tick as the FC release: it takes one extra tick.
    power_share_setpoint = 0.90f;
    I_fc = 1.0f; I_batt = 0.0f;             // FC is about to be the live source again
    t += 1000; g_mock_micros = t; powerBalance();
    check(!shareSpCutFC && digitalRead(FC_BUS_ENABLE) == HIGH,
          "side flip: FC releases first (bus is charged)");
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "side flip: BT does NOT latch on the same tick as the FC release");
    check(!(digitalRead(FC_BUS_ENABLE) == LOW && digitalRead(BT_BUS_ENABLE) == LOW),
          "side flip: the bus is never darkened (both switches LOW) at any point in the flip");

    // Next tick: BT latches (setpoint is still 0.90, both switches now HIGH — entry guard
    // satisfied).
    I_fc = 1.0f; I_batt = 0.0f;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutBT && digitalRead(BT_BUS_ENABLE) == LOW,
          "side flip: BT latches on the next tick");
    check(digitalRead(FC_BUS_ENABLE) == HIGH,
          "side flip: FC (the surviving source) stays on the bus through the whole flip");
}

// ─── fw v6: LOAD-AWARE HANDOFF GUARD on the setpoint-latch ENTRY (SHARE_CUT_MAX_HANDOFF_A) ────
// A cut hands the doomed channel's entire instantaneous current to the survivor in one tick.
// WP0097/WP0101 (fw v5 sweep) latched with 1.3-1.5A on the doomed channel and collapsed the bus
// in ~40ms; the cut at ~0A is validated clean. The entry branch now additionally requires the
// doomed channel's MEASURED current to be <= SHARE_CUT_MAX_HANDOFF_A (0.5A) before it will latch
// -- blocked -> fall through to live governed control instead (same fallback shape as the
// last-source guard), never a frozen loop.
static void test_share_setpoint_cutoff_handoff_guard_fc_blocked() {
    test_group("updateShareSetpointCutoff(): fw v6 handoff guard blocks the FC latch above 0.5A (I_fc)");

    // Force closed-loop mode directly (G3/G4 idiom) so the "live governed control continues"
    // claim is provable as a real MECHANISM -- an actual MDAC write this same tick -- rather than
    // merely "nothing crashed". At the open-loop default the out-of-band setpoint would return
    // from powerBalance() without ever touching the MDACs (F1), which would make this probe
    // vacuous regardless of whether the guard is implemented.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 2.0f;
    I_fc = 1.0f; I_batt = 0.5f;              // doomed channel (FC) carries 1.0A > 0.5A guard
    power_share_setpoint = 0.12f;            // < DROOP_R_MIN -- would latch FC if guard-unblocked
    SPI.transfer_log.clear();

    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(!shareSpCutFC && !shareIsoFC,
          "handoff guard/FC: no latch fires -- I_fc=1.0A exceeds SHARE_CUT_MAX_HANDOFF_A=0.5A");
    check(digitalRead(FC_BUS_ENABLE) == HIGH,
          "handoff guard/FC: FC_BUS_ENABLE stays HIGH -- the switch this tick's guard would have opened");
    check(!SPI.transfer_log.empty(),
          "handoff guard/FC: live control genuinely continues -- the controller stepped and wrote "
          "the MDACs this same tick, not just \"nothing changed\"");
}

static void test_share_setpoint_cutoff_handoff_guard_fc_allowed() {
    test_group("updateShareSetpointCutoff(): fw v6 handoff guard allows the FC latch at 0.1A (I_fc)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.1f; I_batt = 1.0f;              // doomed channel well under the 0.5A guard
    power_share_setpoint = 0.12f;

    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutFC && shareIsoFC && digitalRead(FC_BUS_ENABLE) == LOW,
          "handoff guard/FC allowed: I_fc=0.1A <= 0.5A -- the latch fires exactly as it did before "
          "the fw v6 guard existed");
}

// ─── Deferred cut: the guard blocks on the entry tick, then the SAME setpoint latches once the
// doomed channel's current has fallen under the threshold on a later tick (the .ino's own
// documented resolution path, not a special case) ─────────────────────────────────────────────
static void test_share_setpoint_cutoff_handoff_guard_deferred() {
    test_group("updateShareSetpointCutoff(): fw v6 handoff guard defers the cut to a later tick, then fires");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 2.0f;
    I_fc = 1.0f; I_batt = 0.5f;              // blocked: doomed FC current above the guard
    power_share_setpoint = 0.12f;

    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(!shareSpCutFC, "deferred cut: (setup) the first tick is guard-blocked, no latch yet");

    // The doomed channel's current falls under the threshold on a later tick (e.g. the survivor
    // absorbed more of the load as the governed system responded) -- the SAME out-of-band
    // setpoint is still standing, so the latch fires as soon as the guard clears.
    I_fc = 0.1f; I_batt = 1.4f;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutFC && shareIsoFC && digitalRead(FC_BUS_ENABLE) == LOW,
          "deferred cut: the latch fires on the later tick once I_fc drops to 0.1A <= 0.5A");
}

// ─── BT-side mirror of the handoff guard (sp > DROOP_R_MAX, I_batt) ─────────────────────────
static void test_share_setpoint_cutoff_handoff_guard_bt_mirror() {
    test_group("updateShareSetpointCutoff(): fw v6 handoff guard mirrors on the BT side (I_batt)");

    // Blocked at I_batt=1.0A.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 2.0f;
    I_fc = 0.5f; I_batt = 1.0f;              // doomed channel (BT) above the 0.5A guard
    power_share_setpoint = 0.90f;            // > DROOP_R_MAX -- would latch BT if guard-unblocked
    SPI.transfer_log.clear();

    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(!shareSpCutBT && !shareIsoBT,
          "handoff guard/BT: no latch fires -- I_batt=1.0A exceeds SHARE_CUT_MAX_HANDOFF_A=0.5A");
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "handoff guard/BT: BT_BUS_ENABLE stays HIGH");
    check(!SPI.transfer_log.empty(),
          "handoff guard/BT: live control continues -- an MDAC write happened this same tick");

    // Allowed at I_batt=0.1A.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 1.0f; I_batt = 0.1f;
    power_share_setpoint = 0.90f;
    t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutBT && shareIsoBT && digitalRead(BT_BUS_ENABLE) == LOW,
          "handoff guard/BT allowed: I_batt=0.1A <= 0.5A -- the latch fires");
}

// ─── Boundary: the doomed channel's current EXACTLY AT SHARE_CUT_MAX_HANDOFF_A is allowed
// (fabsf(I) <= threshold, not strict <) ───────────────────────────────────────────────────────
static void test_share_setpoint_cutoff_handoff_guard_boundary() {
    test_group("updateShareSetpointCutoff(): fw v6 handoff guard boundary -- exactly 0.5A is allowed (<=)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = SHARE_CUT_MAX_HANDOFF_A; I_batt = 1.0f;   // doomed FC current EXACTLY at the guard
    power_share_setpoint = 0.12f;

    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutFC && shareIsoFC && digitalRead(FC_BUS_ENABLE) == LOW,
          "handoff guard/boundary: I_fc exactly == SHARE_CUT_MAX_HANDOFF_A latches -- the guard "
          "is fabsf(I) <= threshold, not a strict less-than");

    // One tick above the boundary must NOT latch, confirming the test actually probes the edge.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 2.0f;
    I_fc = SHARE_CUT_MAX_HANDOFF_A + 0.01f; I_batt = 1.0f;
    power_share_setpoint = 0.12f;
    t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(!shareSpCutFC,
          "handoff guard/boundary: one step above the guard (0.51A) does not latch -- confirms "
          "the boundary is real, not a tolerance artifact");
}

// ─── The RELEASE path is UNAFFECTED by the handoff guard -- SHARE_CUT_MAX_HANDOFF_A only gates
// the ENTRY branch, so a release must proceed even with a large current standing on the channel
// being restored (the guard's own comment: "blocked ... never a frozen loop", the mirror concern
// does not apply to closing a switch back onto an already-live bus) ─────────────────────────────
static void test_share_setpoint_cutoff_handoff_guard_release_unaffected() {
    test_group("updateShareSetpointCutoff(): the handoff guard does not gate the release path");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    digitalWrite(BT_REG_ENABLE, HIGH);
    V_bus = 16.0f;
    power_share_setpoint = 0.87f;             // latch BT (low current, so entry is unblocked)
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutBT, "handoff guard/release: (setup) BT is latched");

    // Release with a LARGE current standing on the surviving (FC) channel -- irrelevant to the
    // release branch, which never reads I_fc/I_batt at all.
    power_share_setpoint = 0.5f;              // back in-band
    I_fc = 5.0f; I_batt = 0.0f;               // a handoff-sized current, but on the SURVIVOR
    t += 1000; g_mock_micros = t; powerBalance();
    check(digitalRead(BT_BUS_ENABLE) == HIGH && !shareSpCutBT && !shareIsoBT,
          "handoff guard/release: the release proceeds on the very next in-band tick despite a "
          "large standing current -- the guard is entry-only");
}

// ─── fw v6 review S1: the BLOCKED→DEFERRED mechanism (shareCutDeferredFC/BT) ──────────────────
// A load-aware-guard-blocked entry is DEFERRED, not abandoned: updateShareSetpointCutoff() sets
// shareCutDeferredFC/BT (per-tick derived -- cleared at the top of every call, set only when the
// handoff guard alone blocked the cut) and falls through to live governed control. That flag then
// does two things elsewhere: (a) powerBalance()'s CLOSED-LOOP block clips the controller
// REFERENCE onto the doomed side's band edge (DROOP_R_MIN/DROOP_R_MAX) so the loop actively
// migrates load off the doomed channel; (b) applyShareRatio() suppresses its OWN r-based cutoff
// for that side, because that cutoff has no current guard and would otherwise execute the
// refused handoff a few ticks later under the wrong ownership flag (shareIso* instead of
// shareSpCut*), which the external re-closers (gated on !shareSpCut*) cannot see.
static void test_share_cut_deferred_suppresses_r_cutoff_sustained() {
    test_group("shareCutDeferred: a sustained deferral suppresses the r-based cutoff for the whole run (S1)");

    // FC side: sp < DROOP_R_MIN, doomed FC current held above the handoff guard for many ticks,
    // high total current so the governor's floor clip never interferes with the deferral clip.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 4.0f;
    I_fc = 1.0f; I_batt = 3.0f;              // doomed FC current fixed above SHARE_CUT_MAX_HANDOFF_A
    power_share_setpoint = 0.05f;            // out-of-band low -- would latch FC if unblocked

    uint32_t t = 0;
    bool fcEverCut = false, fcEverIso = false, fcSwitchEverLow = false;
    for (int i = 0; i < 500; i++) {
        t += 1000; g_mock_micros = t; powerBalance();
        if (shareSpCutFC) fcEverCut = true;
        if (shareIsoFC)   fcEverIso = true;
        if (digitalRead(FC_BUS_ENABLE) == LOW) fcSwitchEverLow = true;
    }
    check(!fcEverCut && !fcEverIso && !fcSwitchEverLow,
          "deferred/FC sustained: across 500 ticks of a standing out-of-band setpoint with the "
          "doomed current pinned above the guard, FC_BUS_ENABLE never opens and NEITHER "
          "shareSpCutFC NOR shareIsoFC ever sets -- proves the r-based cutoff was actually "
          "suppressed the whole time, not merely \"hasn't fired yet\"");
    check(shareCutDeferredFC,
          "deferred/FC sustained: the deferral flag is still standing on the final tick (the "
          "setpoint is still out of band and the doomed current is still pinned above the guard)");

    // BT-side mirror, targeted (not a full 500-tick repeat): sp > DROOP_R_MAX, doomed BT current
    // held above the guard.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 4.0f;
    I_fc = 3.0f; I_batt = 1.0f;              // doomed BT current fixed above the guard
    power_share_setpoint = 0.95f;            // out-of-band high

    t = 0;
    bool btEverCut = false, btEverIso = false, btSwitchEverLow = false;
    for (int i = 0; i < 200; i++) {
        t += 1000; g_mock_micros = t; powerBalance();
        if (shareSpCutBT) btEverCut = true;
        if (shareIsoBT)   btEverIso = true;
        if (digitalRead(BT_BUS_ENABLE) == LOW) btSwitchEverLow = true;
    }
    check(!btEverCut && !btEverIso && !btSwitchEverLow,
          "deferred/BT mirror: 200 ticks of a standing high out-of-band setpoint with the doomed "
          "BT current pinned above the guard -- BT_BUS_ENABLE never opens, neither shareSpCutBT "
          "nor shareIsoBT ever sets");
    check(shareCutDeferredBT, "deferred/BT mirror: the deferral flag is still standing at the end");
}

static void test_share_cut_deferred_clips_reference_to_band_edge() {
    test_group("shareCutDeferred: the controller reference clips to the doomed side's band edge, never crosses it (S1)");

    // FC side: reference must be clipped onto DROOP_R_MIN and converge there, never going below it.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 4.0f;              // high total -> the governor floor clip is a no-op
    I_fc = 1.0f; I_batt = 3.0f;              // doomed FC current above the guard -> deferred
    power_share_setpoint = 0.02f;            // well out of band -- without the clip, the reference
                                              // would walk toward 0.02, crossing DROOP_R_MIN

    uint32_t t = 0;
    float minEff = 2.0f;   // above any legal [0,1] value, so the first tick always lowers it
    for (int i = 0; i < 300; i++) {
        t += 1000; g_mock_micros = t; powerBalance();
        if (share_spEffPrev < minEff) minEff = share_spEffPrev;
    }
    check(minEff >= DROOP_R_MIN - 1e-6f,
          "deferred/FC clip: share_spEffPrev never crosses below DROOP_R_MIN at any sampled tick "
          "-- the deferral clip, not the raw out-of-band setpoint, is what the controller tracks");
    check(fabsf(share_spEffPrev - DROOP_R_MIN) < 1e-5f,
          "deferred/FC clip: share_spEffPrev converges exactly to DROOP_R_MIN (the doomed side's "
          "band edge), not to the raw setpoint 0.02");

    // BT side mirror: converges to DROOP_R_MAX, never above it.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 4.0f;
    I_fc = 3.0f; I_batt = 1.0f;
    power_share_setpoint = 0.98f;

    t = 0;
    float maxEff = -1.0f;
    for (int i = 0; i < 300; i++) {
        t += 1000; g_mock_micros = t; powerBalance();
        if (share_spEffPrev > maxEff) maxEff = share_spEffPrev;
    }
    check(maxEff <= DROOP_R_MAX + 1e-6f,
          "deferred/BT clip: share_spEffPrev never crosses above DROOP_R_MAX at any sampled tick");
    check(fabsf(share_spEffPrev - DROOP_R_MAX) < 1e-5f,
          "deferred/BT clip: share_spEffPrev converges exactly to DROOP_R_MAX, not to the raw "
          "setpoint 0.98");
}

static void test_share_cut_deferred_clears_and_latches_per_tick() {
    test_group("shareCutDeferred: clears the instant the doomed current drops, and the latch fires that same tick (S1)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareClosedLoopMode = true;
    shareClosedLoopRun  = true;
    share_govTotAFilt   = 4.0f;
    I_fc = 1.0f; I_batt = 3.0f;              // blocked: doomed FC current above the guard
    power_share_setpoint = 0.10f;            // out-of-band low, standing for the whole test

    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareCutDeferredFC && !shareSpCutFC,
          "deferred/clears: (setup) the first tick defers -- guard-blocked, no latch yet");

    // The doomed channel's current falls under the guard on the NEXT tick (e.g. the deferral's
    // own reference-clip migration pulled load off it) -- the SAME out-of-band setpoint is still
    // standing. Isolate the flag transition from the latch firing: BEFORE this tick,
    // shareCutDeferredFC is still true (nothing has run yet); the entry check inside THIS tick's
    // updateShareSetpointCutoff() call is what both clears it and fires the latch, in that order.
    I_fc = 0.1f; I_batt = 3.9f;              // doomed current now well under SHARE_CUT_MAX_HANDOFF_A
    t += 1000; g_mock_micros = t; powerBalance();
    check(!shareCutDeferredFC,
          "deferred/clears: shareCutDeferredFC is false on the tick the latch fires -- the guard "
          "no longer blocks, so the entry branch takes the LATCH path, not the deferral path "
          "(mutually exclusive within the same entry check)");
    check(shareSpCutFC && shareIsoFC && digitalRead(FC_BUS_ENABLE) == LOW,
          "deferred/clears: the latch fires on that SAME tick once the doomed current drops -- "
          "the out-of-band setpoint never had to change, only the current");
}

static void test_share_cut_deferred_stale_clear_by_reset() {
    test_group("shareCutDeferred: resetShareControlState() clears a stale deferral (S1) -- the clear site matters");

    // A stale deferral (e.g. left over from a prior run's frozen state -- the flag is normally
    // per-tick re-derived, but a profile end/teardown can stop the share loop entirely before the
    // next tick would have cleared it).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    shareCutDeferredFC = true;
    resetShareControlState();
    check(!shareCutDeferredFC,
          "deferred/stale-clear: resetShareControlState() clears a stale shareCutDeferredFC");

    // Prove the clear site MATTERS: with the flag genuinely cleared, a one-shot
    // applyShareRatio() call with an out-of-band ratio now executes the cutoff normally (the
    // suppression in applyShareRatio() checks the flag itself, so this is the same code path a
    // stale TRUE would have silently defeated).
    V_bus = 16.0f;
    applyShareRatio(DROOP_R_MIN - 0.05f);
    check(digitalRead(FC_BUS_ENABLE) == LOW && shareIsoFC,
          "deferred/stale-clear: after the reset, the r-based cutoff fires normally -- confirms "
          "the flag (not something else) was what would have suppressed it");
}

static void test_share_cut_deferred_suppresses_apply_share_ratio_directly() {
    test_group("shareCutDeferred: applyShareRatio() suppresses its own r-based cutoff while the flag is set (S1, unit-level)");

    // FC side, direct unit-level check: no powerBalance() ticks at all, isolating the suppression
    // logic inside applyShareRatio() itself from the mechanism that sets the flag.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareCutDeferredFC = true;
    applyShareRatio(DROOP_R_MIN - 0.05f);     // r < DROOP_R_MIN would normally cut FC
    check(digitalRead(FC_BUS_ENABLE) == HIGH && !shareIsoFC,
          "deferred/suppression-FC: with shareCutDeferredFC set, an out-of-band-low ratio does "
          "NOT cut FC -- FC_BUS_ENABLE stays HIGH and shareIsoFC stays false");

    // BT side mirror.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareCutDeferredBT = true;
    applyShareRatio(DROOP_R_MAX + 0.05f);     // r > DROOP_R_MAX would normally cut BT
    check(digitalRead(BT_BUS_ENABLE) == HIGH && !shareIsoBT,
          "deferred/suppression-BT: with shareCutDeferredBT set, an out-of-band-high ratio does "
          "NOT cut BT -- BT_BUS_ENABLE stays HIGH and shareIsoBT stays false");

    // Contrast: with the flag clear, the SAME ratio DOES cut -- confirms the suppression check
    // above wasn't vacuously passing for some unrelated reason (e.g. the last-source guard).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    applyShareRatio(DROOP_R_MIN - 0.05f);
    check(digitalRead(FC_BUS_ENABLE) == LOW && shareIsoFC,
          "deferred/suppression contrast: without the flag, the identical out-of-band ratio DOES "
          "cut FC -- the flag, not the last-source guard, was what blocked it above");
}

static void test_share_setpoint_cutoff_ownership() {
    test_group("Setpoint latch ownership: State-98 '1'/'2' and safeAllSwitches() clear it");

    // State-98 '1' (operator toggles FC_BUS_ENABLE) clears a standing FC setpoint latch —
    // otherwise the latch would keep blocking re-entry and freezing the share loop after the
    // operator has explicitly taken the switch back (see the .ino case '1' comment).
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.0f; I_batt = 1.0f;
    power_share_setpoint = 0.12f;
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutFC, "ownership: (setup) FC setpoint-latched");

    mainState = 98;
    Serial.rx_queue.push('1');
    doState98();
    check(!shareSpCutFC,
          "ownership: State-98 '1' clears shareSpCutFC when it toggles FC_BUS_ENABLE");

    // State-98 '2' mirrors it for BT.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 1.0f; I_batt = 0.0f;
    power_share_setpoint = 0.87f;
    t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutBT, "ownership: (setup) BT setpoint-latched");

    mainState = 98;
    Serial.rx_queue.push('2');
    doState98();
    check(!shareSpCutBT,
          "ownership: State-98 '2' clears shareSpCutBT when it toggles BT_BUS_ENABLE");

    // safeAllSwitches() clears both latches unconditionally.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    shareSpCutFC = true;
    shareSpCutBT = true;
    safeAllSwitches();
    check(!shareSpCutFC && !shareSpCutBT,
          "ownership: safeAllSwitches() clears both setpoint latches");
}

// ─── S1: self-heal — an orphaned latch (switch externally re-closed) degrades to live control,
// never a frozen loop (fw v4 review round, 2026-08-12) ───────────────────────────────────────
static void test_share_setpoint_self_heal() {
    test_group("updateShareSetpointCutoff(): S1 self-heal drops an orphaned latch");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 1.0f; I_batt = 0.0f;
    power_share_setpoint = 0.87f;           // out-of-band -> latches BT
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutBT && digitalRead(BT_BUS_ENABLE) == LOW,
          "(setup) BT setpoint-latched, switch open");

    // Something outside the share loop re-closes the switch without going through the gated
    // release path (e.g. chargingControl()'s charge_goal==0 re-close). Also bring the setpoint
    // back in-band and drop V_bus BELOW the charged threshold: if this went through the normal
    // release path (which requires V_bus >= V_BUS_CHARGED_THRESH), it would stay held — self-
    // heal must clear it unconditionally regardless of that gate.
    digitalWrite(BT_BUS_ENABLE, HIGH);
    power_share_setpoint = 0.5f;
    V_bus = V_BUS_CHARGED_THRESH - 1.0f;
    I_fc = 0.5f; I_batt = 0.5f;
    check(shareSpCutBT, "(setup) the latch flag is still set — now orphaned");

    t += 1000; g_mock_micros = t; powerBalance();
    check(!shareSpCutBT && !shareIsoBT,
          "self-heal: the next tick clears the orphaned latch unconditionally (no V_bus/boost "
          "gate — that gate belongs to the release path, not self-heal)");
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "self-heal: the externally re-closed switch stays closed — degrades to live, not frozen");
    check(!SPI.transfer_log.empty(),
          "self-heal: the loop is live again — the controller stepped and wrote the MDACs");
}

// ─── T3 (S1, fw v5 review): shareIso* orphan self-heal with NO setpoint latch behind it ───────
// A DISTINCT self-heal block from test_share_setpoint_self_heal() above: that test orphans a
// COMBINED shareSpCut*+shareIso* setpoint latch. This one exercises a RATIO-based cutoff claim
// (shareIsoFC/BT set by applyShareRatio()'s own r<DROOP_R_MIN / r>DROOP_R_MAX branches) with NO
// setpoint latch behind it — e.g. doState2() re-asserting FC_BUS/BT_BUS gated only on
// !shareSpCutFC leaves the switch HIGH with shareIsoFC still set. Without this self-heal,
// applyShareRatio() returns early ("while a channel is isolated... return") before EVERY later
// MDAC write, silently freezing the droop split for the rest of the run even though the switch
// is fully closed and nothing setpoint-related is holding it open.
static void test_share_iso_orphan_self_heal_no_setpoint_latch() {
    test_group("updateShareSetpointCutoff(): T3 shareIsoFC orphan (no shareSpCutFC) self-heals");

    reset_test_state();
    // The exact orphan shape: a ratio-based claim with the switch already externally re-closed
    // and no setpoint latch backing it.
    shareIsoFC   = true;
    shareSpCutFC = false;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    g_pin_value[BT_REG_ENABLE] = HIGH;
    V_bus = 16.0f;
    I_fc = 0.5f; I_batt = 0.5f;
    power_share_setpoint = 0.5f;             // in-band -- normal governed control, not a latch

    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();

    check(!shareIsoFC,
          "T3: the orphaned shareIsoFC claim is dropped -- the switch was already HIGH, so "
          "there was nothing left to own");
    check(digitalRead(FC_BUS_ENABLE) == HIGH,
          "T3: FC_BUS_ENABLE is untouched by the self-heal itself (it was already closed)");
    check(!SPI.transfer_log.empty(),
          "T3: the loop resumes live control on the same tick -- the MDACs are writable again, "
          "not frozen by the now-dropped orphan claim");
}

// ─── S1 guard: doState2()/chargingControl() no longer re-assert a switch the setpoint latch
// owns (fw v4 review round) ───────────────────────────────────────────────────────────────────
static void test_charging_control_skips_reassert_when_latched() {
    test_group("chargingControl(): charge_goal==0 skips the BT_BUS re-assert while shareSpCutBT is latched (S1 guard)");

    reset_test_state();
    shareSpCutBT = true;
    g_pin_value[BT_BUS_ENABLE] = LOW;    // the share loop's latch already holds it open
    charge_goal = 0.0f;
    chargingControl();
    check(digitalRead(BT_BUS_ENABLE) == LOW,
          "S1 guard: BT_BUS_ENABLE stays LOW — chargingControl() does not re-assert a switch the "
          "setpoint latch owns");
    check(digitalRead(MPPT_DISABLE) == LOW && digitalRead(FC_CHARGE_ENABLE) == LOW &&
          digitalRead(REGEN_ENABLE) == LOW,
          "S1 guard: the rest of the charge_goal==0 inhibit still runs normally");

    // Contrast: without the latch, the same call DOES re-assert BT_BUS_ENABLE as before.
    reset_test_state();
    shareSpCutBT = false;
    g_pin_value[BT_BUS_ENABLE] = LOW;
    charge_goal = 0.0f;
    chargingControl();
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "S1 guard (contrast): without the latch chargingControl() re-asserts BT_BUS_ENABLE as normal");
}

// ─── S2: assertFcChargeEnable(true) restores a setpoint-latched FC to the bus BEFORE cutting
// BT — never cut the last source (fw v4 review round) ────────────────────────────────────────
static void test_assert_fc_charge_enable_clears_setpoint_latches() {
    test_group("assertFcChargeEnable(true): restores an FC setpoint latch before cutting BT (S2)");

    // FC is setpoint-latched off the bus (sp < DROOP_R_MIN); BT is the only live source.
    reset_test_state();
    g_pin_value[FC_BUS_ENABLE] = LOW;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    shareSpCutFC = true;
    shareIsoFC   = true;
    g_write_log.clear();

    assertFcChargeEnable(true);

    check(digitalRead(FC_BUS_ENABLE) == HIGH,
          "S2: FC_BUS_ENABLE ends HIGH — restored to the bus before BT is cut");
    check(digitalRead(BT_BUS_ENABLE) == LOW,
          "S2: BT_BUS_ENABLE ends LOW — the charge path takes over as usual");
    check(!shareSpCutFC && !shareIsoFC,
          "S2: the FC setpoint latch and isolation flag are both cleared");
    check(digitalRead(FC_CHARGE_ENABLE) == HIGH,
          "S2: FC_CHARGE_ENABLE ends HIGH");

    // Ordering: the bus is never left dark mid-restore — FC_BUS_ENABLE must go HIGH before
    // BT_BUS_ENABLE goes LOW.
    int fc_high_idx = -1, bt_low_idx = -1;
    for (int i = 0; i < (int)g_write_log.size(); i++) {
        if (fc_high_idx < 0 && g_write_log[i].pin == FC_BUS_ENABLE && g_write_log[i].value == HIGH)
            fc_high_idx = i;
        if (bt_low_idx < 0 && g_write_log[i].pin == BT_BUS_ENABLE && g_write_log[i].value == LOW)
            bt_low_idx = i;
    }
    check(fc_high_idx >= 0 && bt_low_idx >= 0 && fc_high_idx < bt_low_idx,
          "S2: FC_BUS_ENABLE HIGH is written before BT_BUS_ENABLE LOW — the bus is never dark");
}

// ─── Correctness-review gap (i): assertFcChargeEnable(true) must clear a GENUINE BT setpoint
// latch (shareSpCutBT), not only the ratio-isolation flag (shareIsoBT) ──────────────────────
static void test_assert_fc_charge_enable_clears_bt_setpoint_latch() {
    test_group("assertFcChargeEnable(true) clears a genuine BT setpoint latch, not just shareIsoBT (gap i)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 1.0f; I_batt = 0.0f;
    power_share_setpoint = 0.87f;          // out-of-band -> latches BT via the SETPOINT path
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutBT && shareIsoBT && digitalRead(BT_BUS_ENABLE) == LOW,
          "(setup) BT is genuinely setpoint-latched, not just ratio-isolated");

    assertFcChargeEnable(true);
    check(!shareSpCutBT && !shareIsoBT,
          "gap (i): assertFcChargeEnable(true) clears shareSpCutBT too, not only shareIsoBT");
    check(digitalRead(BT_BUS_ENABLE) == LOW && digitalRead(FC_CHARGE_ENABLE) == HIGH,
          "gap (i): BT_BUS_ENABLE stays LOW, now under the charge path's own ownership");
}

// ─── S5: every bus-switch re-close (setpoint release AND ratio hysteresis) also requires the
// channel's boost to be enabled (CLAUDE.md §2 back-feed rule, fw v4 review round) ────────────
static void test_share_setpoint_release_blocked_without_boost() {
    test_group("updateShareSetpointCutoff(): release refused while the channel's boost is disabled (S5)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    power_share_setpoint = 0.87f;
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutBT, "(setup) BT latched");

    // Setpoint back in-band, bus charged, but BT_REG_ENABLE is LOW (boost disabled): release
    // must stay held/retried, never proceed — closing a live bus onto a disabled boost is the
    // back-feed direction (CLAUDE.md §2).
    power_share_setpoint = 0.5f;
    digitalWrite(BT_REG_ENABLE, LOW);
    for (int i = 0; i < 50; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareSpCutBT && shareIsoBT,
          "S5: release stays held while BT_REG_ENABLE is LOW, even in-band and bus charged");

    // Enable the boost: releases on the very next tick.
    digitalWrite(BT_REG_ENABLE, HIGH);
    t += 1000; g_mock_micros = t; powerBalance();
    check(digitalRead(BT_BUS_ENABLE) == HIGH && !shareSpCutBT && !shareIsoBT,
          "S5: releases on the first tick after BT_REG_ENABLE goes HIGH");
}

static void test_share_ratio_reentry_blocked_without_boost() {
    test_group("applyShareRatio(): ratio-hysteresis re-entry refused while the channel's boost is disabled (S5)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    applyShareRatio(0.0f);                      // isolate FC (entry doesn't need the boost)
    check(shareIsoFC && digitalRead(FC_BUS_ENABLE) == LOW, "(setup) FC isolated by the ratio cutoff");

    // FC_REG_ENABLE stays LOW: re-entry must stay refused even at a fully in-band ratio and a
    // charged bus.
    applyShareRatio(0.5f);
    check(digitalRead(FC_BUS_ENABLE) == LOW && shareIsoFC,
          "S5: re-entry refused while FC_REG_ENABLE is LOW");

    digitalWrite(FC_REG_ENABLE, HIGH);
    applyShareRatio(0.5f);
    check(digitalRead(FC_BUS_ENABLE) == HIGH && !shareIsoFC,
          "S5: re-entry proceeds once FC_REG_ENABLE goes HIGH");
}

// ─── S6/S7: the bring-up and State-99 teardown paths clear the share-loop latches they take
// ownership of (fw v4 review round) ───────────────────────────────────────────────────────────
static void test_share_latches_cleared_by_bringup_p0_and_abort() {
    test_group("Share-loop latches cleared by bring-up ownership transitions (S6)");

    // busBringupTick() P0 entry.
    reset_test_state();
    mainState = 98;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 0.0f;
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    shareSpCutFC = true; shareIsoFC = true;
    shareSpCutBT = true; shareIsoBT = true;
    busBringupStart();
    busBringupTick(false);                      // P0 entry
    check(!shareSpCutFC && !shareIsoFC && !shareSpCutBT && !shareIsoBT,
          "S6: bring-up P0 entry clears all four share-latch flags");

    // busBringupAbort().
    reset_test_state();
    mainState = 98;
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    bringupActive = true;
    shareSpCutFC = true; shareIsoFC = true;
    shareSpCutBT = true; shareIsoBT = true;
    busBringupAbort();
    check(!shareSpCutFC && !shareIsoFC && !shareSpCutBT && !shareIsoBT,
          "S6: busBringupAbort() clears all four share-latch flags");
}

static void test_share_fc_latch_cleared_by_state99() {
    test_group("doState99() phase 0 clears the FC setpoint/isolation latches (S7)");

    reset_test_state();
    mainState = 99;
    error_code = ERR_OC_FC;
    fault_flags = FAULT_OC_FC | FAULT_ERROR;
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    shareSpCutFC = true; shareIsoFC = true;
    shareSpCutBT = true; shareIsoBT = true;
    state99Phase = 0;
    doState99();
    check(!shareSpCutFC && !shareIsoFC,
          "S7: doState99() phase 0 clears shareIsoFC/shareSpCutFC directly");
    check(!shareSpCutBT && !shareIsoBT,
          "S7: shareIsoBT/shareSpCutBT also end cleared (via the assertFcChargeEnable(true) call "
          "phase 0 makes to drain VBUS — S2's unconditional BT clear)");
    check(digitalRead(FC_BUS_ENABLE) == LOW && digitalRead(BT_BUS_ENABLE) == LOW,
          "S7: (sanity) both bus switches opened by the teardown");
}

// ─── Correctness-review gap (ii): restoreShareCutoffOnCompletion() with a genuine shareSpCut
// latch (not just shareIsoBT/FC) — flags cleared, switch re-closed given boost+bus OK ────────
static void test_restore_share_cutoff_on_completion_setpoint_latch() {
    test_group("restoreShareCutoffOnCompletion() with a genuine shareSpCut latch (gap ii)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    digitalWrite(BT_REG_ENABLE, HIGH);
    V_bus = 17.5f;
    I_fc = 1.0f; I_batt = 0.0f;
    power_share_setpoint = 0.87f;           // out-of-band -> genuine setpoint latch on BT
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutBT && shareIsoBT && digitalRead(BT_BUS_ENABLE) == LOW,
          "(setup) BT is genuinely setpoint-latched");

    restoreShareCutoffOnCompletion("TEST");
    check(!shareSpCutBT && !shareIsoBT,
          "gap (ii): the SETPOINT latch (not just the ratio-isolation flag) is cleared");
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "gap (ii): the channel is put back on the bus (boost enabled, bus charged)");
}

// ─── Correctness-review gap (iii): 'O'/applyOpenLoopDroop() cannot override a setpoint latch
// with an in-band ratio — the switch must stay open ───────────────────────────────────────────
static void test_open_loop_droop_respects_setpoint_latch() {
    test_group("applyOpenLoopDroop() ('O') cannot override a setpoint latch (gap iii)");

    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.0f; I_batt = 1.0f;
    power_share_setpoint = 0.12f;           // out-of-band -> genuine setpoint latch on FC
    uint32_t t = 0;
    t += 1000; g_mock_micros = t; powerBalance();
    check(shareSpCutFC && digitalRead(FC_BUS_ENABLE) == LOW, "(setup) FC setpoint-latched");

    powerBalanceLive = true;
    applyOpenLoopDroop(0.5f);                // in-band ratio, but the latch still owns FC_BUS
    check(digitalRead(FC_BUS_ENABLE) == LOW,
          "gap (iii): 'O' with an in-band ratio does NOT re-close a setpoint-latched switch");
    check(!powerBalanceLive,
          "gap (iii): 'O' still clears powerBalanceLive as usual");
}

// ─── Correctness-review gap (iv): resetShareControlState() resets the CONTROLLER, not the
// setpoint/isolation latches — a latch must survive a direct call ────────────────────────────
static void test_reset_share_control_state_leaves_latch() {
    test_group("resetShareControlState() does not touch the setpoint/isolation latches (gap iv)");

    reset_test_state();
    shareSpCutFC = true;
    shareIsoFC   = true;
    shareCtrl_heldOut = 0.8f;
    resetShareControlState();
    check(shareSpCutFC && shareIsoFC,
          "gap (iv): resetShareControlState() leaves the setpoint/isolation latches untouched");
    check(fabsf(shareCtrl_heldOut - 0.5f) < 1e-6f,
          "gap (iv): but it does reset the controller's held output to the balanced split");
}

// ─── Power-share PI anti-windup ───────────────────────────────────────────────
static void test_power_pi_antiwindup() {
    test_group("Power-share PI integrator anti-windup");

    const float limit = 1.0f;   // Ki == 1.0 → accum bounded to ±(1.0/Ki)

    // Sustained unsatisfiable share error (e.g. one source disconnected from the bus) must
    // not wind the integrator past the droop ratio's usable authority.
    reset_test_state();
    uint32_t t = 0;
    for (int i = 0; i < 2000; i++) {
        t += 1000;                 // 1 ms steps, all > sampleTime
        g_mock_micros = t;
        PI_Controller_Power(1.0f);
    }
    check(pi_power_accum <= limit + 1e-3f,
          "Power PI: integrator clamped at +limit under sustained positive error");

    reset_test_state();
    t = 0;
    for (int i = 0; i < 2000; i++) {
        t += 1000;
        g_mock_micros = t;
        PI_Controller_Power(-1.0f);
    }
    check(pi_power_accum >= -limit - 1e-3f,
          "Power PI: integrator clamped at -limit under sustained negative error");
}

// ─── Drive cycle phase transitions ───────────────────────────────────────────
static void test_drive_cycle() {
    test_group("Drive cycle (advanceDriveCycle) phase transitions");
    reset_test_state();

    driveCycleActive     = true;
    driveCyclePhaseIdx   = 0;
    driveCyclePhaseStart = 0;
    driveCycleStatusLast = 0;
    v_setpoint = 0;
    g_mock_millis = 0;

    // Within phase 0 (standstill, 0–2000ms): v_setpoint stays 0
    g_mock_millis = 1000;
    advanceDriveCycle();
    check(driveCyclePhaseIdx == 0,
          "drive cycle: still phase 0 at 1000ms");
    check(fabsf(v_setpoint - 0.0f) < 0.01f,
          "drive cycle: v_setpoint = 0 during standstill phase");

    // At 2001ms: phase 0 elapses → transition to phase 1
    g_mock_millis = 2001;
    advanceDriveCycle();
    check(driveCyclePhaseIdx == 1,
          "drive cycle: transitions to phase 1 at 2001ms");
    // driveCyclePhaseStart is now 2001

    // Phase 1 (ramp-up, 4000ms): at 2001+2000=4001ms, t=0.5, v_setpoint ~ 1.5
    g_mock_millis = 4001;
    advanceDriveCycle();
    check(driveCyclePhaseIdx == 1,
          "drive cycle: still in phase 1 (ramp) at 4001ms");
    check(fabsf(v_setpoint - 1.5f) < 0.1f,
          "drive cycle: v_setpoint ≈ 1.5 at midpoint of ramp-up (t=0.5)");

    // End of phase 1 at 2001+4000+1=6002ms → transition to phase 2 (cruise)
    g_mock_millis = 6002;
    advanceDriveCycle();
    check(driveCyclePhaseIdx == 2,
          "drive cycle: transitions to phase 2 (cruise) after ramp-up");

    // Skip ahead to phase 4 (regen hold) by simulating phases 2 and 3 elapsing
    // Each advanceDriveCycle() call on elapsed >= duration transitions the phase and returns.
    while (driveCyclePhaseIdx < 4 && driveCycleActive) {
        g_mock_millis += DRIVE_CYCLE[driveCyclePhaseIdx].durationMs + 1;
        advanceDriveCycle();
    }

    if (driveCyclePhaseIdx == 4) {
        // Mid-point of regen hold phase (duration=3000ms, v_start=v_end=-0.5)
        g_mock_millis += 1500;
        advanceDriveCycle();
        check(fabsf(v_setpoint - (-0.5f)) < 0.05f,
              "drive cycle: v_setpoint = -0.5 during regen hold phase");
    }

    // Exhaust remaining phases (4 then 5). Each iteration: elapse the current phase,
    // then call once more after the last phase to trigger the completion handler.
    // (Completion fires when advanceDriveCycle sees phaseIdx >= DRIVE_CYCLE_PHASES.)
    while (driveCyclePhaseIdx < DRIVE_CYCLE_PHASES) {
        g_mock_millis += DRIVE_CYCLE[driveCyclePhaseIdx].durationMs + 1;
        advanceDriveCycle();
    }
    // driveCyclePhaseIdx == DRIVE_CYCLE_PHASES — one final call fires the completion handler
    advanceDriveCycle();

    check(driveCycleActive == false,
          "drive cycle: driveCycleActive becomes false after all phases complete");
    check(fabsf(v_setpoint - 0.0f) < 0.01f,
          "drive cycle: v_setpoint reset to 0 on completion");
}

// ─── checkPiWatchdog state guard ─────────────────────────────────────────────
static void test_pi_watchdog_guard() {
    test_group("checkPiWatchdog() state guard (States 2 and 3 only)");
    reset_test_state();

    pi_ever_connected = true;
    last_rx_ms = 0;
    g_mock_millis = PI_TIMEOUT_MS + 100;   // past the timeout

    // In State 1 (Idle): watchdog must NOT trigger
    mainState = 1;
    checkPiWatchdog();
    check(mainState == 1,
          "checkPiWatchdog: no fault in State 1 even when Pi absent");

    // In State 98 (Test): watchdog must NOT trigger
    mainState = 98;
    checkPiWatchdog();
    check(mainState == 98,
          "checkPiWatchdog: no fault in State 98 even when Pi absent");

    // In State 2 (Run): watchdog MUST trigger
    mainState = 2;
    checkPiWatchdog();
    check(mainState == 99,
          "checkPiWatchdog: fault triggered in State 2 after Pi timeout");
    check(fault_flags & FAULT_PI_TIMEOUT,
          "checkPiWatchdog: FAULT_PI_TIMEOUT bit set in fault_flags");
    check(error_code == ERR_PI_TIMEOUT,
          "checkPiWatchdog: error_code == ERR_PI_TIMEOUT");
    check(error_source_state == 2,
          "checkPiWatchdog: error_source_state == 2 (was in Run)");

    // In State 3 (Finish): watchdog MUST trigger
    reset_test_state();
    pi_ever_connected = true;
    last_rx_ms = 0;
    g_mock_millis = PI_TIMEOUT_MS + 100;
    mainState = 3;
    checkPiWatchdog();
    check(mainState == 99,
          "checkPiWatchdog: fault triggered in State 3 after Pi timeout");
    check(fault_flags & FAULT_PI_TIMEOUT,
          "checkPiWatchdog: FAULT_PI_TIMEOUT set from State 3");
    check(error_code == ERR_PI_TIMEOUT,
          "checkPiWatchdog: error_code == ERR_PI_TIMEOUT from State 3");
}

// ─── Error code system ───────────────────────────────────────────────────────
static void test_error_code_system() {
    test_group("Error code system (triggerFault latching)");

    // triggerFault() latches error_code on first call; second call does not overwrite it
    reset_test_state();
    mainState = 2;
    triggerFault(FAULT_OC_FC, ERR_OC_FC);
    check(error_code == ERR_OC_FC,
          "triggerFault: error_code latched to ERR_OC_FC on first call");
    check(error_source_state == 2,
          "triggerFault: error_source_state captured mainState==2");
    check(mainState == 99,
          "triggerFault: transitions mainState to 99");
    check(fault_flags & FAULT_OC_FC,
          "triggerFault: FAULT_OC_FC bit set in fault_flags");
    check(fault_flags & FAULT_ERROR,
          "triggerFault: FAULT_ERROR bit set immediately");

    // Second triggerFault must NOT overwrite the first error_code
    triggerFault(FAULT_UV_BATT, ERR_UV_BATT);
    check(error_code == ERR_OC_FC,
          "triggerFault: error_code remains ERR_OC_FC on second call (latch)");
    check(fault_flags & FAULT_UV_BATT,
          "triggerFault: FAULT_UV_BATT added to fault_flags on second call");

    // All FAULT_* constants must be distinct powers-of-two
    test_group("Fault bitmask constants");
    uint16_t all_bits[] = {
        FAULT_OC_FC, FAULT_UV_BATT, FAULT_OV_BUS, FAULT_SWITCH_CONFLICT,
        FAULT_PI_TIMEOUT, FAULT_OV_BATT, FAULT_UV_FC, FAULT_OC_BT,
        FAULT_UV_BUS, FAULT_OV_RGN, FAULT_OV_CHG, FAULT_I2C_CHARGER,
        FAULT_CHARGER_STAT, FAULT_INIT_FAIL, FAULT_ERROR
    };
    bool all_unique = true;
    for (size_t i = 0; i < sizeof(all_bits)/sizeof(all_bits[0]); i++) {
        // Each must be a non-zero power of two
        if (all_bits[i] == 0 || (all_bits[i] & (all_bits[i] - 1)) != 0) {
            all_unique = false; break;
        }
        for (size_t j = i + 1; j < sizeof(all_bits)/sizeof(all_bits[0]); j++) {
            if (all_bits[i] == all_bits[j]) { all_unique = false; break; }
        }
    }
    check(all_unique,
          "FAULT_* constants: all distinct powers-of-two (no duplicates or non-POT)");
}

// ─── I2C fault injection ──────────────────────────────────────────────────────
static void test_i2c_fault_injection() {
    test_group("I2C fault injection");

    // initAg105Charger now returns bool and raises NO fault itself (the caller decides).
    // First write NAK → returns false, no fault, state unchanged.
    reset_test_state();
    Wire.next_endtransmission_result = 1;   // first endTransmission returns error
    mainState = 0;
    bool r = initAg105Charger();
    check(!r, "initAg105Charger: returns false when first I2C write NAKs");
    check(fault_flags == 0, "initAg105Charger: raises no fault itself on NACK");
    check(mainState == 0, "initAg105Charger: does not change state on NACK");

    // Both writes succeed → returns true, 2 writes logged.
    reset_test_state();
    mainState = 0;
    r = initAg105Charger();
    check(r, "initAg105Charger: returns true when both writes succeed");
    check(Wire.write_log.size() == 2,
          "initAg105Charger: 2 writes when both succeed");

    // pollAg105: requestFrom returns 0 with charger powered+settled in Run → FAULT_I2C_CHARGER
    reset_test_state();
    make_charger_powered_settled();
    Wire.fail_next_requestfrom = true;
    mainState = 2;
    pollAg105();
    check(fault_flags & FAULT_I2C_CHARGER,
          "pollAg105: FAULT_I2C_CHARGER set when powered+settled charger NAKs in Run");
    check(error_code == ERR_I2C_CHARGER,
          "pollAg105: error_code == ERR_I2C_CHARGER");
    check(mainState == 99,
          "pollAg105: mainState → 99 on I2C read failure (powered+settled)");

    // pollAg105: normal read succeeds → no fault
    reset_test_state();
    Wire.rx_queue.push(0x02);   // GENSTAT=charging
    Wire.rx_queue.push(50);     // 50 * 0.011 = 0.55A
    mainState = 2;
    pollAg105();
    check(mainState == 2,
          "pollAg105: no fault transition on successful I2C read");
    check(fabsf(I_charge - 0.55f) < 0.001f,
          "pollAg105: I_charge decoded correctly after successful read");
}

// ─── Motor PI anti-windup ─────────────────────────────────────────────────────
static void test_motor_pi_antiwindup() {
    test_group("Motor PI integrator anti-windup");

    const float limit = MOTOR_I_CMD_MAX * motorConstant;   // Ki == 1.0

    // Sustained large positive error must not wind the integrator past +limit.
    reset_test_state();
    uint32_t t = 0;
    for (int i = 0; i < 2000; i++) {
        t += 1000;                 // 1 ms steps, all > sampleTime
        g_mock_micros = t;
        PI_Controller_Motor(100.0f);
    }
    check(pi_motor_accum <= limit + 1e-3f,
          "Motor PI: integrator clamped at +limit under sustained positive error");

    // Sustained large negative error must not wind past -limit.
    reset_test_state();
    t = 0;
    for (int i = 0; i < 2000; i++) {
        t += 1000;
        g_mock_micros = t;
        PI_Controller_Motor(-100.0f);
    }
    check(pi_motor_accum >= -limit - 1e-3f,
          "Motor PI: integrator clamped at -limit under sustained negative error");
}

// ─── updateWheelSpeed() buffer reset request (State 3) ────────────────────────
static void test_wheelspeed_reset() {
    test_group("updateWheelSpeed() reset between runs");
    reset_test_state();

    // doState3 is single-pass (it leaves the bus energized; no drain phases). It requests a
    // wheel-speed buffer reset, which updateWheelSpeed() then consumes.
    mainState = 3;
    g_mock_millis = 0;
    doState3();                      // stop motor, return to Idle, request reset
    check(wheelSpeedResetPending == true,
          "doState3: requests wheel-speed buffer reset on completion");
    check(mainState == 1,
          "doState3: returns to State 1 after shutdown");

    // updateWheelSpeed() consumes the request and clears the flag.
    g_mock_micros = 1000000;
    updateWheelSpeed();
    check(wheelSpeedResetPending == false,
          "updateWheelSpeed: consumes and clears the reset request");
}

// ─── doState0() staged bring-up walks P0→P3 and reaches Idle ─────────────────
static void test_dostate0_reaches_idle_unpowered() {
    test_group("doState0() staged bring-up (P0→P1→P2→P3) reaches Idle");

    // Production doState0() arms and ticks the shared staged machine. Phases:
    //   P0 entry  — MOT_PWR LOW, bus switches HIGH
    //   P0 gate   — PRECHARGE_MIN_MS + V_bus ≥ max(V_fc,V_batt)−PRECHARGE_DROP_MAX + ≥ V_PRECHARGE_MIN
    //   P1 gate   — V_bus ≥ V_BUS_CHARGED_THRESH
    //   P2 dwell  — regulation holds BUS_REG_DWELL_MS continuous
    //   P3        — MOT_PWR connect, then V_rgn tracks V_bus → DONE
    // The charger is unpowered in Init and doState0() never touches it, so a NACKing charger
    // must not matter.
    reset_test_state();
    Wire.next_endtransmission_result = 1;   // any stray I2C would NACK — must not matter
    mainState = 0;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f;            // FC is the WINNING source — max() must be used
    V_bus = 0.0f; V_rgn = 0.0f;

    // ---- P0 entry -----------------------------------------------------------
    doState0();
    check(mainState == 0 && bringupActive && bringupPhase == 1,
          "doState0/P0: machine armed, advanced to the P0 gate");
    check(digitalRead(FC_BUS_ENABLE) == HIGH && digitalRead(BT_BUS_ENABLE) == HIGH,
          "doState0/P0: bus switches closed FIRST");
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState0/P0: MOT_PWR actively held LOW (motor node not on the chain)");
    check(digitalRead(FC_REG_ENABLE) == LOW && digitalRead(BT_REG_ENABLE) == LOW,
          "doState0/P0: boosts NOT enabled before the bus switches (switches-before-boosts)");

    // ---- P0 gate: max(V_fc,V_batt) is the reference -------------------------
    // 8.0V clears V_batt(7.0)−1.5 and the 5.0V floor but NOT V_fc(12.0)−1.5 = 10.5.
    g_mock_millis = PRECHARGE_MIN_MS + 5;
    V_bus = 8.0f;
    doState0();
    check(bringupPhase == 1 && digitalRead(FC_REG_ENABLE) == LOW,
          "doState0/P0 gate: uses max(V_fc,V_batt) — a V_batt-only pass is rejected");

    // Voltage now good, but rewind the clock to prove PRECHARGE_MIN_MS is enforced on its own.
    bringupPhaseStart = g_mock_millis;       // restart the phase clock at "now"
    V_bus = 11.0f;                           // ≥ 12.0 − 1.5 and ≥ 5.0
    doState0();
    check(bringupPhase == 1 && digitalRead(FC_REG_ENABLE) == LOW,
          "doState0/P0 gate: voltage good early still waits out PRECHARGE_MIN_MS");

    g_mock_millis += PRECHARGE_MIN_MS + 1;
    doState0();
    check(bringupPhase == 2,
          "doState0/P0 gate: passes once both time and voltage criteria are met");
    check(digitalRead(FC_REG_ENABLE) == HIGH && digitalRead(BT_REG_ENABLE) == HIGH,
          "doState0/P1: boosts enabled after the pre-charge");
    check(digitalRead(BT_SEQUENCE_ENABLE) == HIGH,
          "doState0/P1: BT_SEQUENCE_ENABLE raised with the boosts");
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState0/P1: MOT_PWR still LOW through the boost ramp");
    check(!SPI.transfer_log.empty(),
          "doState0/P1: doInit=true ran initControlPeripherals (MDAC outputs written)");

    // ---- P1 gate ------------------------------------------------------------
    g_mock_millis += 10;
    V_bus = 16.0f;                           // ≥ V_BUS_CHARGED_THRESH
    doState0();
    check(bringupPhase == 3,
          "doState0/P1 gate: bus in regulation → dwell phase");
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState0/P2: MOT_PWR still LOW during the dwell");

    // ---- P2 dwell -----------------------------------------------------------
    g_mock_millis += BUS_REG_DWELL_MS / 2;
    doState0();
    check(bringupPhase == 3 && mainState == 0,
          "doState0/P2: dwell not yet complete");
    g_mock_millis += BUS_REG_DWELL_MS;
    doState0();
    check(bringupPhase == 4,
          "doState0/P2: dwell complete after BUS_REG_DWELL_MS continuous regulation");
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState0: MOT_PWR held LOW through the whole of P0/P1/P2");

    // ---- P3 -----------------------------------------------------------------
    g_mock_millis += 1;
    doState0();
    check(bringupPhase == 5 && digitalRead(MOT_PWR_ENABLE) == HIGH,
          "doState0/P3: motor node connected from the regulated bus");
    check(mainState == 0, "doState0/P3: not Idle until the motor node tracks the bus");

    g_mock_millis += 20;
    V_rgn = V_bus - MOT_HOTPLUG_MARGIN + 0.5f;   // node tracks the bus
    doState0();
    check(mainState == 1,
          "doState0: BRINGUP_DONE → Idle");
    check(!bringupActive && bringupPhase == 0,
          "doState0: machine self-resets on DONE");
    check(error_code == ERR_NONE && fault_flags == 0,
          "doState0: no fault latched on a healthy bring-up");
}

// ─── doState0() P0 pre-charge timeout (dead source / switch) → FAULT_INIT_FAIL ─
static void test_dostate0_precharge_timeout() {
    test_group("doState0() P0 pre-charge timeout → FAULT_INIT_FAIL (vacuous-pass guard)");

    // Dead board: every rail reads ~0. The RELATIVE gate (V_bus ≥ max(V_fc,V_batt) − drop) is
    // vacuously true at 0 ≥ −1.5, so the ABSOLUTE V_PRECHARGE_MIN floor is what must stop it.
    reset_test_state();
    mainState = 0;
    g_mock_millis = 0;
    V_fc = 0.0f; V_batt = 0.0f; V_bus = 0.0f;

    doState0();                              // P0 entry
    g_mock_millis = PRECHARGE_MIN_MS + 1;
    doState0();
    check(mainState == 0 && bringupPhase == 1,
          "doState0/P0: all-zero rails do NOT vacuously pass the relative gate");
    check(digitalRead(FC_REG_ENABLE) == LOW,
          "doState0/P0: boosts never enabled on a dead source");

    g_mock_millis = PRECHARGE_TIMEOUT_MS + 1;
    doState0();
    check(mainState == 99 && error_code == ERR_INIT_FAIL,
          "doState0/P0: pre-charge timeout latches State 99 / ERR_INIT_FAIL");
    check((fault_flags & FAULT_INIT_FAIL) != 0,
          "doState0/P0: FAULT_INIT_FAIL flag set");
    check(!bringupActive && bringupPhase == 0,
          "doState0/P0: machine self-resets before faulting");
}

// ─── doState0() faults if the bus never charges (dead boost / no source) ──────
static void test_dostate0_bus_charge_timeout() {
    test_group("doState0() P1 bus-charge timeout → FAULT_INIT_FAIL");

    reset_test_state();
    mainState = 0;
    g_mock_millis = 0;
    V_fc = 6.0f; V_batt = 6.0f;
    V_bus = 6.0f;                            // pre-charges fine, but boosts never regulate

    doState0();                              // P0 entry
    g_mock_millis = PRECHARGE_MIN_MS + 1;
    doState0();                              // P0 gate passes → boosts on, P1 clock starts
    check(bringupPhase == 2 && mainState == 0,
          "doState0/P1: pre-charged, boosts on, waiting for regulation");

    g_mock_millis += BUS_CHARGE_TIMEOUT_MS + 1;
    doState0();                              // P1 timeout
    check(mainState == 99,
          "doState0: latches State 99 when the bus never charges");
    check(error_code == ERR_INIT_FAIL,
          "doState0: ERR_INIT_FAIL latched on bus-charge timeout");
    check((fault_flags & FAULT_INIT_FAIL) != 0,
          "doState0: FAULT_INIT_FAIL flag set on bus-charge timeout");
}

// ─── P2 dwell: a dip restarts the dwell; overall timeout faults ──────────────
static void test_bringup_dwell_dip_and_timeout() {
    test_group("Bring-up P2 dwell: dip restarts, overall timeout → FAULT_INIT_FAIL");

    // Helper walk to the dwell phase.
    auto walk_to_dwell = []() {
        reset_test_state();
        mainState = 0;
        g_mock_millis = 0;
        V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f; V_rgn = 0.0f;
        doState0();                                  // P0 entry
        g_mock_millis = PRECHARGE_MIN_MS + 1;
        doState0();                                  // P0 gate → boosts
        V_bus = 16.0f;
        g_mock_millis += 1;
        doState0();                                  // P1 gate → dwell
    };

    // --- dip mid-dwell restarts the dwell clock ------------------------------
    walk_to_dwell();
    check(bringupPhase == 3, "dwell: entered P2");
    uint32_t dwellEntry = g_mock_millis;

    g_mock_millis = dwellEntry + BUS_REG_DWELL_MS - 5;
    V_bus = 10.0f;                                    // DIP just before the dwell would complete
    doState0();
    check(bringupPhase == 3, "dwell: dip keeps the machine in P2");

    V_bus = 16.0f;
    g_mock_millis += 5;                               // past the ORIGINAL dwell deadline
    doState0();
    check(bringupPhase == 3,
          "dwell: the dip restarted the dwell — no premature P3 at the original deadline");

    g_mock_millis += BUS_REG_DWELL_MS + 1;
    doState0();
    check(bringupPhase == 4, "dwell: completes once regulation holds a full window post-dip");

    // --- overall dwell timeout (regulation never holds) ----------------------
    walk_to_dwell();
    dwellEntry = g_mock_millis;
    for (uint32_t t = 5; t <= BUS_DWELL_TIMEOUT_MS; t += BUS_REG_DWELL_MS - 5) {
        g_mock_millis = dwellEntry + t;
        V_bus = 10.0f;                                // below threshold → dwell keeps restarting
        doState0();
    }
    check(bringupPhase == 3 && mainState == 0, "dwell: still pending just inside the timeout");
    g_mock_millis = dwellEntry + BUS_DWELL_TIMEOUT_MS + 1;
    doState0();
    check(mainState == 99 && error_code == ERR_INIT_FAIL,
          "dwell: overall BUS_DWELL_TIMEOUT_MS → FAULT_INIT_FAIL");
    check(!bringupActive && bringupPhase == 0, "dwell: machine self-resets on the timeout");
}

// ─── P3: motor node never tracks the bus → FAULT_MOT_HOTPLUG ────────────────
static void test_bringup_mot_connect_timeout() {
    test_group("Bring-up P3 motor-connect timeout → FAULT_MOT_HOTPLUG");

    reset_test_state();
    mainState = 0;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f; V_rgn = 0.0f;
    doState0();                                       // P0 entry
    g_mock_millis = PRECHARGE_MIN_MS + 1;
    doState0();                                       // P0 gate
    V_bus = 16.0f;
    g_mock_millis += 1;  doState0();                  // P1 gate → dwell
    g_mock_millis += BUS_REG_DWELL_MS + 1; doState0();// dwell complete → P3 entry pending
    g_mock_millis += 1;  doState0();                  // P3 entry: MOT_PWR closed
    check(bringupPhase == 5 && digitalRead(MOT_PWR_ENABLE) == HIGH,
          "P3: MOT_PWR closed from the regulated bus");

    // V_rgn stays stuck at 0 (D-MT-EN SCP retry) → timeout.
    g_mock_millis += MOT_CONNECT_TIMEOUT_MS / 2;
    doState0();
    check(mainState == 0 && bringupPhase == 5, "P3: still waiting inside the connect window");

    g_mock_millis += MOT_CONNECT_TIMEOUT_MS;
    doState0();
    check(mainState == 99 && error_code == ERR_MOT_HOTPLUG,
          "P3: motor node never tracks the bus → FAULT_MOT_HOTPLUG");
    check((fault_flags & FAULT_MOT_HOTPLUG) != 0, "P3: FAULT_MOT_HOTPLUG flag set");
    check(!bringupActive && bringupPhase == 0, "P3: machine self-resets on the timeout");
}

// ─── State-98 'G' drives the same machine (doInit=false) ─────────────────────
static void test_dostate98_g_bringup() {
    test_group("State 98 'G' staged bring-up");

    reset_test_state();
    mainState = 98;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f; V_rgn = 0.0f;

    Serial.rx_queue.push('G');
    doState98();                                    // arms AND ticks P0 entry in one invocation
    check(bringupActive && bringupPhase == 1,
          "'G': machine armed and P0 entry executed in the same invocation");
    check(digitalRead(FC_BUS_ENABLE) == HIGH && digitalRead(BT_BUS_ENABLE) == HIGH &&
          digitalRead(MOT_PWR_ENABLE) == LOW,
          "'G': bus switches closed, MOT_PWR held LOW");

    // Re-'G' while running is refused and must not disturb the machine.
    uint8_t phaseBefore = bringupPhase;
    Serial.rx_queue.push('G');
    doState98();
    check(bringupActive && bringupPhase == phaseBefore,
          "'G': re-arm while active is refused (phase unchanged)");

    // The machine advances on EMPTY-queue ticks.
    g_mock_millis = PRECHARGE_MIN_MS + 1;
    state98_tick();
    check(bringupPhase == 2,
          "'G': machine advances on a doState98() tick with an EMPTY serial queue");
    check(digitalRead(FC_REG_ENABLE) == HIGH && digitalRead(BT_REG_ENABLE) == HIGH,
          "'G': boosts enabled at the P0 gate pass");
    check(SPI.transfer_log.empty(),
          "'G': doInit=false — initControlPeripherals NOT re-run (no MDAC writes)");

    V_bus = 16.0f;
    g_mock_millis += 1;                    state98_tick();   // P1 gate → dwell
    check(bringupPhase == 3, "'G': bus in regulation → dwell");
    g_mock_millis += BUS_REG_DWELL_MS + 1; state98_tick();   // dwell done
    g_mock_millis += 1;                    state98_tick();   // P3 entry
    check(bringupPhase == 5 && digitalRead(MOT_PWR_ENABLE) == HIGH,
          "'G': motor node connected at P3");
    V_rgn = 14.0f;
    g_mock_millis += 5;                    state98_tick();   // P3 gate → DONE
    check(!bringupActive && bringupPhase == 0,
          "'G': bring-up completes and the machine self-resets");
    check(mainState == 98 && error_code == ERR_NONE,
          "'G': stays in State 98 with no fault");
}

// ─── State-98 bring-up interlocks: 'G' vs profiles, 'D'/'R'/'T' vs bring-up ──
static void test_dostate98_bringup_interlocks() {
    test_group("State 98 bring-up ↔ profile interlocks");

    // 'G' refused while a profile is running.
    reset_test_state();
    mainState = 98;
    driveCycleActive = true;
    Serial.rx_queue.push('G');
    doState98();
    check(!bringupActive, "'G' refused while the drive cycle is active");

    reset_test_state();
    mainState = 98;
    powerShareProfileActive = true;
    Serial.rx_queue.push('G');
    doState98();
    check(!bringupActive, "'G' refused while the power-share profile is active");

    reset_test_state();
    mainState = 98;
    trapProfileActive = true;
    Serial.rx_queue.push('G');
    doState98();
    check(!bringupActive, "'G' refused while the trapezoid profile is active");

    // 'D' / 'R' / 'T' refused while a bring-up is in progress.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;    // the other preconditions are satisfied
    manualMotorMode = MOTOR_TEST_CURRENT;
    bringupActive = true; bringupPhase = 2;
    Serial.rx_queue.push('D');
    doState98();
    check(!driveCycleActive, "'D' refused while a bring-up is in progress");

    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    manualMotorMode = MOTOR_TEST_CURRENT;
    bringupActive = true; bringupPhase = 2;
    Serial.rx_queue.push('R');
    doState98();
    check(!powerShareProfileActive, "'R' refused while a bring-up is in progress");

    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    bringupActive = true; bringupPhase = 2;
    Serial.rx_queue.push('T');
    doState98();
    check(!trapProfileActive && pendingInput == PEND_NONE,
          "'T' refused while a bring-up is in progress (no pending input either)");
}

// ─── 'X' / 'Q' abort a running bring-up and darken the power stage ───────────
static void test_dostate98_bringup_abort() {
    test_group("State 98 'X'/'Q' abort the bring-up (stage darkened)");

    // Walk to mid-P1 (boosts ON, bus switches ON) then abort with 'X'.
    auto walk_to_p1 = []() {
        reset_test_state();
        mainState = 98;
        g_mock_millis = 0;
        V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f; V_rgn = 0.0f;
        Serial.rx_queue.push('G');
        doState98();
        g_mock_millis = PRECHARGE_MIN_MS + 1;
        state98_tick();                  // P0 gate → boosts on, phase 2
    };

    walk_to_p1();
    check(bringupPhase == 2 && digitalRead(FC_REG_ENABLE) == HIGH, "abort: reached mid-P1");
    Serial.rx_queue.push('X');
    doState98();
    check(!bringupActive && bringupPhase == 0, "'X': bring-up aborted");
    check(digitalRead(MOT_PWR_ENABLE) == LOW && digitalRead(FC_REG_ENABLE) == LOW &&
          digitalRead(BT_REG_ENABLE) == LOW && digitalRead(FC_BUS_ENABLE) == LOW &&
          digitalRead(BT_BUS_ENABLE) == LOW,
          "'X': all five power-stage pins driven LOW (a cut-park is invisible to the ADC)");

    walk_to_p1();
    Serial.rx_queue.push('Q');
    doState98();
    check(!bringupActive && bringupPhase == 0, "'Q': bring-up aborted on exit");
    check(digitalRead(MOT_PWR_ENABLE) == LOW && digitalRead(FC_REG_ENABLE) == LOW &&
          digitalRead(BT_REG_ENABLE) == LOW && digitalRead(FC_BUS_ENABLE) == LOW &&
          digitalRead(BT_BUS_ENABLE) == LOW,
          "'Q': power stage darkened on a mid-bring-up exit");
    check(mainState == 1, "'Q': returns to Idle");
}

// ─── FAULT_OV_BUS time-persistence filter ────────────────────────────────────
static void test_ov_bus_persistence() {
    test_group("FAULT_OV_BUS persistence filter");

    const float OVER  = LIMIT_V_BUS_MAX + 0.5f;
    const float UNDER = LIMIT_V_BUS_MAX - 0.5f;

    // (1) Single over-limit sample at t=0 (the boot-tick edge): bit visible, NO latch.
    reset_test_state();
    mainState = 1; g_mock_millis = 0; V_bus = OVER;
    detectFaults();
    check((fault_flags & FAULT_OV_BUS) != 0,
          "OV_BUS: bit set on the first over-limit sample (truthful telemetry)");
    check(mainState == 1, "OV_BUS: single sample does not change mainState");
    check(error_code == ERR_NONE, "OV_BUS: single sample leaves error_code ERR_NONE (t=0 edge)");
    check(ovBusOverActive && ovBusOverSamples == 1, "OV_BUS: window opened, 1 sample counted");

    // (2) Sustained over-limit across ≥ OV_BUS_PERSIST_MIN_SAMPLES ticks spanning the time window.
    // Sample spacing must stay ≤ OV_BUS_MAX_GAP_MS or the gap guard restarts the window (F4).
    reset_test_state();
    mainState = 1; g_mock_millis = 1000; V_bus = OVER;
    detectFaults();                                   // sample 1, t=0 of window
    g_mock_millis = 1000 + OV_BUS_MAX_GAP_MS;
    detectFaults();                                   // sample 2, time not yet met
    check(mainState == 1, "OV_BUS: no latch before the persistence time elapses");
    g_mock_millis = 1000 + OV_BUS_PERSIST_MS;
    detectFaults();                                   // sample 3, time + samples met
    check(mainState == 99 && error_code == ERR_OV_BUS,
          "OV_BUS: latches once time AND sample floor are both satisfied");
    check((fault_flags & FAULT_OV_BUS) != 0, "OV_BUS: flag retained through the latch");

    // (3) A dip mid-window resets it — no latch even after > OV_BUS_PERSIST_MS total.
    reset_test_state();
    mainState = 1; g_mock_millis = 1000; V_bus = OVER;
    detectFaults();
    g_mock_millis = 1000 + OV_BUS_PERSIST_MS / 2; V_bus = UNDER;
    detectFaults();
    check(!ovBusOverActive && ovBusOverSamples == 0, "OV_BUS: below-limit sample resets the window");
    g_mock_millis = 1000 + OV_BUS_PERSIST_MS + 1; V_bus = OVER;
    detectFaults();
    check(mainState == 1 && error_code == ERR_NONE,
          "OV_BUS: a dip restarts the window — no latch at the original deadline");

    // (4) Sample floor / gap guard: only two calls, 12ms apart (a stalled loop bracketing a
    // blocked stretch). Both the sample floor AND the OV_BUS_MAX_GAP_MS guard reject it — the
    // gap guard fires first and restarts the window, so the counter goes back to 1.
    reset_test_state();
    mainState = 1; g_mock_millis = 1000; V_bus = OVER;
    detectFaults();                                   // sample 1
    g_mock_millis = 1000 + OV_BUS_PERSIST_MS + 2;
    detectFaults();                                   // sample 2 — gap 12ms > OV_BUS_MAX_GAP_MS
    check(mainState == 1 && error_code == ERR_NONE,
          "OV_BUS: sparse stalled-loop samples do not latch (aliasing guard)");
    check(ovBusOverSamples == 1 && ovBusOverSince == g_mock_millis,
          "OV_BUS: gap > OV_BUS_MAX_GAP_MS restarts the window (counter back to 1)");

    // (5) A concurrent single-sample fault still latches immediately with an OV_BUS window open.
    reset_test_state();
    mainState = 1; g_mock_millis = 1000; V_bus = OVER;
    detectFaults();
    check(mainState == 1, "OV_BUS: window pending (no latch yet)");
    V_rgn = LIMIT_V_RGN_MAX + 1.0f;
    detectFaults();
    check(mainState == 99 && error_code == ERR_OV_RGN,
          "OV_BUS: other faults keep single-sample latching while an OV_BUS window is pending");
    check((fault_flags & FAULT_OV_BUS) != 0 && (fault_flags & FAULT_OV_RGN) != 0,
          "OV_BUS: both the pending OV_BUS bit and the latched fault are reported");
}

// ─── OV_BUS gap guard: sparse samples must not be credited as continuous ─────
static void test_ov_bus_gap_guard() {
    test_group("FAULT_OV_BUS sample-gap guard (OV_BUS_MAX_GAP_MS)");

    const float OVER = LIMIT_V_BUS_MAX + 0.5f;

    // Sparse: three over-samples at t = 0, 100, 101. Naive window arithmetic (since=0,
    // samples=3, elapsed=101 ≥ 10) would latch — the gap guard must have restarted at t=100.
    reset_test_state();
    mainState = 1; V_bus = OVER;
    g_mock_millis = 0;   detectFaults();
    g_mock_millis = 100; detectFaults();
    g_mock_millis = 101; detectFaults();
    check(mainState == 1 && error_code == ERR_NONE,
          "gap guard: samples at 0/100/101 do NOT latch (window restarted at the 100ms gap)");
    check(ovBusOverSince == 100 && ovBusOverSamples == 2,
          "gap guard: window restarted at the sparse sample, then continued");
    // Review round 2: the ABANDONED window is a real unlatched transient and must be counted,
    // not silently discarded by the restart.
    check(ovBusTransientCount == 1,
          "gap guard: the gap-abandoned window increments the transient counter");

    // Continuity: 2 ms spacing all the way to 12 ms → every gap ≤ OV_BUS_MAX_GAP_MS, so the
    // window survives and the persistence time + sample floor are both met.
    reset_test_state();
    mainState = 1; V_bus = OVER;
    for (uint32_t t = 0; t <= 12; t += 2) {
        g_mock_millis = t;
        detectFaults();
    }
    check(mainState == 99 && error_code == ERR_OV_BUS,
          "gap guard: contiguous 2ms-spaced samples across the window DO latch");
}

// ─── A gap-abandoned OV window is still counted ──────────────────────────────
static void test_ov_bus_gap_abandoned_counted() {
    test_group("FAULT_OV_BUS gap-abandoned window is counted (review round 2)");

    const float OVER = LIMIT_V_BUS_MAX + 0.5f;

    reset_test_state();
    mainState = 1; V_bus = OVER;
    g_mock_millis = 0;
    detectFaults();                                   // window opens
    check(ovBusTransientCount == 0 && ovBusOverActive,
          "gap-abandoned: window open, nothing counted yet");

    g_mock_millis = 100;
    detectFaults();                                   // gap 100ms > OV_BUS_MAX_GAP_MS → restart
    check(ovBusTransientCount == 1,
          "gap-abandoned: the restart counts the abandoned window at the restart tick");
    check(ovBusOverActive && ovBusOverSince == 100 && ovBusOverSamples == 1,
          "gap-abandoned: a FRESH window is open after the restart");
    check(mainState == 1 && error_code == ERR_NONE,
          "gap-abandoned: still no latch");

    // The fresh window closing normally counts a second time.
    g_mock_millis = 102; V_bus = LIMIT_V_BUS_MAX - 0.5f;
    detectFaults();
    check(ovBusTransientCount == 2,
          "gap-abandoned: the fresh window's normal close counts separately");
}

// ─── OV_BUS transient counter ────────────────────────────────────────────────
static void test_ov_bus_transient_counter() {
    test_group("FAULT_OV_BUS transient counter");

    const float OVER  = LIMIT_V_BUS_MAX + 0.5f;
    const float UNDER = LIMIT_V_BUS_MAX - 0.5f;

    reset_test_state();
    mainState = 1;
    check(ovBusTransientCount == 0, "transient: counter starts at 0");

    // Two over-samples 4 ms apart (sub-persistence), then back under → window closes unlatched.
    g_mock_millis = 1000; V_bus = OVER;  detectFaults();
    g_mock_millis = 1004;                detectFaults();
    check(mainState == 1 && ovBusTransientCount == 0,
          "transient: counter not incremented while the window is still open");
    g_mock_millis = 1006; V_bus = UNDER; detectFaults();
    check(ovBusTransientCount == 1,
          "transient: counter increments once when a window closes WITHOUT latching");
    check(mainState == 1 && error_code == ERR_NONE,
          "transient: a closed sub-persistence window never latches");
    check(!ovBusOverActive && ovBusOverSamples == 0, "transient: window state cleared on close");

    // A second transient window increments again.
    g_mock_millis = 1010; V_bus = OVER;  detectFaults();
    g_mock_millis = 1012; V_bus = UNDER; detectFaults();
    check(ovBusTransientCount == 2, "transient: a second window increments the counter again");

    // Staying under does not keep incrementing (only a window CLOSE counts).
    g_mock_millis = 1020; detectFaults();
    g_mock_millis = 1030; detectFaults();
    check(ovBusTransientCount == 2, "transient: under-limit ticks with no open window do nothing");

    // Print limiter boot-edge (review round 3): a window closing at millis()==0 must count as
    // "printed" so subsequent same-millisecond closes are rate-bounded (the old 0-sentinel
    // re-printed on every close until millis advanced).
    reset_test_state();
    mainState = 1;
    g_mock_millis = 0; V_bus = OVER;  detectFaults();
    V_bus = UNDER;                    detectFaults();   // close at t=0 → first print
    check(ovBusHasPrinted && ovBusPrintLastMs == 0,
          "transient: t=0 close marks the limiter as printed (flag, not 0-sentinel)");
    check(ovBusTransientCount == 1, "transient: t=0 close still counted");
}

// ─── FAULT_UV_BUS: bus-armed + leaky-dwell filtered (fw v5, 2026-08-12) ──────
// Armed (not state-gated, unlike the old single-sample State-2 check it replaces) when
// V_bus has reached V_BUS_CHARGED_THRESH with a source switch closed; disarmed the instant
// both source switches read LOW. While armed, a V_bus < LIMIT_V_BUS_MIN sample sets the
// telemetry bit immediately; the LATCH decision is a leaky dwell integrator
// (UV_BUS_DWELL_*), not a wall-clock window: under-limit ticks add min(dt,
// UV_BUS_DWELL_DT_CAP_MS) to uvBusDwellMs, over-limit ticks subtract UV_BUS_DWELL_LEAK*dt
// (floored at 0), and the latch fires once uvBusDwellMs >= UV_BUS_DWELL_LATCH_MS. This
// REPLACES the fw v4 UV_BUS_PERSIST_*/UV_BUS_MAX_GAP_MS wall-clock window, which the fw v4
// validation sweep showed is EVADED BY DUTY CYCLE (TP0053: a 9ms-under/51ms-over relay cycle
// never persisted long enough to latch, even after 1.0-1.3s and 24 excursions) — see the
// .ino UV_BUS_DWELL_* comment block for the full arithmetic. This block is compiled and
// armed in BOTH builds (deliberately outside #if !BENCH_TEST — see the .ino comment at the
// FAULT_UV_BUS block): WP0039/TP0016 sagged the bus with zero fault indication under
// BENCH_TEST, which is exactly the gap this rework closes.
static void test_uv_bus_not_armed_dark() {
    test_group("FAULT_UV_BUS: unarmed while the power stage is dark");

    // Both source switches LOW, V_bus at 0 (boot/teardown darkness) — never arms regardless
    // of how many ticks or how much time passes.
    reset_test_state();
    mainState = 1; V_bus = 0.0f;
    g_pin_value[FC_BUS_ENABLE] = LOW;
    g_pin_value[BT_BUS_ENABLE] = LOW;
    for (uint32_t t = 0; t <= 200; t += 20) {
        g_mock_millis = t;
        detectFaults();
    }
    check(!uvBusArmed, "UV_BUS/dark: never arms with both source switches LOW");
    check(!(fault_flags & FAULT_UV_BUS), "UV_BUS/dark: no fault bit despite V_bus=0 < LIMIT_V_BUS_MIN");
    check(mainState == 1 && error_code == ERR_NONE, "UV_BUS/dark: no latch");
}

// ─── U1: repetitive relay-cycle waveform (TP0053 class) ratchets to a latch ─────────────────
// The fw v4 wall-clock window was EVADED by exactly this duty cycle: every 60ms period (9ms
// under / 51ms over) closed its window before UV_BUS_PERSIST_MS elapsed and reopened from
// zero on the next cycle, so a run could sag repeatedly for over a second with no latch. The
// dwell integrator nets +9 - UV_BUS_DWELL_LEAK*51 = +6.45ms of dwell PER CYCLE, so it must
// ratchet to a latch within a handful of cycles even though no single window ever persists —
// this is the mechanism the whole fw v5 rework exists to fix, so it must actually be exercised
// here, not just "no crash".
static void test_uv_bus_dwell_relay_waveform() {
    test_group("FAULT_UV_BUS: dwell ratchets across a repetitive relay cycle (fw v5, TP0053 class)");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;
    const float UNDER   = LIMIT_V_BUS_MIN - 1.0f;

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;   // arming also requires a boost enabled
    V_bus = CHARGED; g_mock_millis = 0; detectFaults();   // arm
    check(uvBusArmed, "UV_BUS/relay: (setup) armed");

    uint32_t t = 0;
    uint32_t latchTick = 0;
    for (int cycle = 0; cycle < 6 && mainState != 99; cycle++) {
        for (uint32_t i = 0; i < 9 && mainState != 99; i++) {
            t++; g_mock_millis = t; V_bus = UNDER; detectFaults();
        }
        if (mainState == 99) { latchTick = t; break; }
        for (uint32_t i = 0; i < 51 && mainState != 99; i++) {
            t++; g_mock_millis = t; V_bus = CHARGED; detectFaults();
        }
        if (mainState == 99) { latchTick = t; break; }
    }
    check(mainState == 99 && error_code == ERR_UV_BUS,
          "UV_BUS/relay: the repetitive 9ms/51ms duty cycle ratchets to a latch within 6 cycles "
          "— fw v4's wall-clock window NEVER latched this waveform (TP0053 ran 1.0-1.3s / up to "
          "24 excursions with zero fault indication)");
    check(latchTick >= 2u * 60u,
          "UV_BUS/relay: does not latch within the first 2 cycles alone — isolated dips leak "
          "away, only the repetitive ratchet gets there");
    check(latchTick <= 5u * 60u,
          "UV_BUS/relay: latches well inside the 5-cycle budget derived from the +6.45ms/cycle "
          "net gain arithmetic");
}

// ─── U2: sparse transients (WP0069 shape) leak away, never latch ────────────────────────────
static void test_uv_bus_sparse_transient_no_latch() {
    test_group("FAULT_UV_BUS: sparse transients (WP0069 shape) leak away between excursions, no latch");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;
    const float UNDER   = LIMIT_V_BUS_MIN - 1.0f;

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_bus = CHARGED; g_mock_millis = 0; detectFaults();   // arm

    // 9 excursions of 2ms under, 24ms apart (~210ms total, ~18ms total under-time) — the same
    // shape as WP0069's ~19ms total under-time in <=2.3ms excursions over 208ms. Net dwell:
    // +2 per excursion, -UV_BUS_DWELL_LEAK*24=-1.2 per gap -> net +0.8/cycle, well under the
    // 20ms latch threshold across all 9.
    uint32_t t = 0;
    for (int ex = 0; ex < 9; ex++) {
        for (int i = 0; i < 2; i++) { t++; g_mock_millis = t; V_bus = UNDER; detectFaults(); }
        for (int i = 0; i < 24; i++) { t++; g_mock_millis = t; V_bus = CHARGED; detectFaults(); }
    }
    check(mainState == 2 && error_code == ERR_NONE,
          "UV_BUS/sparse: 9 isolated ~2ms dips spread over ~210ms never latch — the dwell leaks "
          "away between them");
    check(uvBusDwellMs < UV_BUS_DWELL_LATCH_MS,
          "UV_BUS/sparse: accumulated dwell stays below the latch threshold at the end of the run");
    check(uvBusTransientCount == 9,
          "UV_BUS/sparse: every one of the 9 dips is counted as a closed transient (visible via 'S')");
}

// ─── U3: continuous collapse latches at the dwell threshold, not before ─────────────────────
static void test_uv_bus_continuous_collapse_threshold() {
    test_group("FAULT_UV_BUS: continuous collapse latches at 20ms dwell, not at 15ms");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;
    const float UNDER   = LIMIT_V_BUS_MIN - 1.0f;

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_bus = CHARGED; g_mock_millis = 0; detectFaults();   // arm

    V_bus = UNDER;
    for (uint32_t t = 1; t <= 15; t++) { g_mock_millis = t; detectFaults(); }
    check(mainState == 2 && error_code == ERR_NONE,
          "UV_BUS/continuous: not latched at 15ms of continuous under-dwell");
    check(fabsf(uvBusDwellMs - 15.0f) < 1e-6f,
          "UV_BUS/continuous: dwell tracks the elapsed continuous under-time 1:1 (each 1ms tick "
          "is well under the 5ms dt cap)");

    for (uint32_t t = 16; t <= 20; t++) { g_mock_millis = t; detectFaults(); }
    check(mainState == 99 && error_code == ERR_UV_BUS,
          "UV_BUS/continuous: latches once dwell reaches UV_BUS_DWELL_LATCH_MS (20ms)");
}

// ─── U4: per-tick dwell credit is capped, so a stalled loop can't insta-latch ────────────────
static void test_uv_bus_dwell_dt_cap() {
    test_group("FAULT_UV_BUS: per-tick dwell credit is capped at UV_BUS_DWELL_DT_CAP_MS");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;
    const float UNDER   = LIMIT_V_BUS_MIN - 1.0f;

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_bus = CHARGED; g_mock_millis = 0; detectFaults();   // arm

    V_bus = UNDER;
    g_mock_millis = 500; detectFaults();     // 500ms gap since the last armed tick
    check(fabsf(uvBusDwellMs - UV_BUS_DWELL_DT_CAP_MS) < 1e-6f,
          "UV_BUS/cap: a stalled-loop/long gap credits at most UV_BUS_DWELL_DT_CAP_MS, not the "
          "full 500ms elapsed");

    g_mock_millis = 1000; detectFaults();    // another 500ms gap
    check(fabsf(uvBusDwellMs - 2.0f * UV_BUS_DWELL_DT_CAP_MS) < 1e-6f,
          "UV_BUS/cap: a second capped tick adds another 5ms — a stalled loop cannot insta-latch "
          "off a single huge dt");
    check(mainState == 2 && error_code == ERR_NONE,
          "UV_BUS/cap: two capped ticks (10ms total) stay below the 20ms latch");
}

// ─── U5: leaking dwell floors at zero, never goes negative ──────────────────────────────────
static void test_uv_bus_dwell_leak_floor() {
    test_group("FAULT_UV_BUS: leaking dwell floors at zero, a fresh 20ms is still required after");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;
    const float UNDER   = LIMIT_V_BUS_MIN - 1.0f;

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_bus = CHARGED; g_mock_millis = 0; detectFaults();   // arm

    // Partial accumulation (5ms, via a large gap since the arm tick so the dt cap credits the
    // full UV_BUS_DWELL_DT_CAP_MS), then a long over-limit stretch that would leak well past
    // zero under naive (unfloored) arithmetic.
    V_bus = UNDER; g_mock_millis = 1000; detectFaults();
    check(fabsf(uvBusDwellMs - 5.0f) < 1e-6f, "UV_BUS/leak: (setup) 5ms accumulated");
    V_bus = CHARGED;
    for (uint32_t t = 1001; t <= 1500; t++) { g_mock_millis = t; detectFaults(); }
    check(uvBusDwellMs == 0.0f,
          "UV_BUS/leak: a long over-limit stretch floors dwell at exactly 0, never negative");

    // A fresh 20ms continuous under-dwell from that floor must still need the FULL 20ms — no
    // residual credit carried from the leak stretch.
    V_bus = UNDER;
    for (uint32_t t = 1501; t <= 1519; t++) { g_mock_millis = t; detectFaults(); }
    check(mainState == 2 && error_code == ERR_NONE,
          "UV_BUS/leak: 19ms accumulated from the zero floor still does not latch");
    g_mock_millis = 1520; detectFaults();
    check(mainState == 99 && error_code == ERR_UV_BUS,
          "UV_BUS/leak: the 20th ms from the floor latches — confirms no negative credit was "
          "banked during the leak stretch");
}

// ─── U6: disarm dumps the accumulated dwell, re-arm needs a full fresh 20ms ──────────────────
static void test_uv_bus_disarm_resets_dwell() {
    test_group("FAULT_UV_BUS: disarm (boosts off) dumps the accumulated dwell, not just the armed flag");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;
    const float UNDER   = LIMIT_V_BUS_MIN - 1.0f;

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_bus = CHARGED; g_mock_millis = 0; detectFaults();   // arm

    V_bus = UNDER;
    for (uint32_t t = 1; t <= 15; t++) { g_mock_millis = t; detectFaults(); }
    check(fabsf(uvBusDwellMs - 15.0f) < 1e-6f, "UV_BUS/disarm: (setup) 15ms accumulated");

    // Disarm: both boosts off (the routine S4 'F'/'B' bench sequence) — a disarmed interval is
    // not evidence of a collapse, so the dwell must be dumped, not just the armed flag cleared.
    g_pin_value[FC_REG_ENABLE] = LOW;
    g_mock_millis = 16; detectFaults();
    check(!uvBusArmed && uvBusDwellMs == 0.0f,
          "UV_BUS/disarm: disarming dumps the accumulated dwell to zero");

    // Re-arm and confirm a fresh dwell is required from zero — no leftover credit from before
    // the disarm (which would let two unrelated bench sequences add up into a spurious latch).
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_bus = CHARGED; g_mock_millis = 20; detectFaults();   // re-arm
    V_bus = UNDER;
    for (uint32_t t = 21; t <= 39; t++) { g_mock_millis = t; detectFaults(); }   // 19ms
    check(mainState == 2 && error_code == ERR_NONE,
          "UV_BUS/disarm: 19ms after re-arm does not latch (fresh dwell, not 15+19=34ms carried "
          "over from before the disarm)");
    g_mock_millis = 40; detectFaults();   // 20ms
    check(mainState == 99 && error_code == ERR_UV_BUS,
          "UV_BUS/disarm: a full fresh 20ms after re-arm does latch");
}

// ─── U7: the raw telemetry bit tracks V_bus directly, independent of the latch ──────────────
static void test_uv_bus_raw_flag_bit() {
    test_group("FAULT_UV_BUS: the raw telemetry bit tracks V_bus vs LIMIT_V_BUS_MIN, before any latch");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;
    const float UNDER   = LIMIT_V_BUS_MIN - 1.0f;

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_bus = CHARGED; g_mock_millis = 0; detectFaults();   // arm
    check(!(fault_flags & FAULT_UV_BUS), "UV_BUS/flag: bit clear while V_bus is above the limit");

    V_bus = UNDER; g_mock_millis = 1; detectFaults();
    check((fault_flags & FAULT_UV_BUS) != 0 && mainState == 2,
          "UV_BUS/flag: bit sets on the very first under-limit tick, well before any latch");

    V_bus = CHARGED; g_mock_millis = 2; detectFaults();
    check(!(fault_flags & FAULT_UV_BUS),
          "UV_BUS/flag: bit clears the instant V_bus recovers above the limit");
}

static void test_uv_bus_disarm_on_teardown() {
    test_group("FAULT_UV_BUS: disarms when both source switches open (teardown)");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;

    reset_test_state();
    mainState = 3;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;   // arming also requires a boost enabled (fw v4 S4)
    V_bus = CHARGED; g_mock_millis = 0; detectFaults();
    check(uvBusArmed, "UV_BUS/disarm: (setup) armed");

    // Teardown: both switches open, bus decaying below LIMIT_V_BUS_MIN. This is the expected
    // shape of a normal State-3/99 shutdown, not a fault — it must disarm on the SAME tick
    // the switches open, before the low reading is ever evaluated as a fault.
    g_pin_value[FC_BUS_ENABLE] = LOW;
    g_pin_value[BT_BUS_ENABLE] = LOW;
    V_bus = 5.0f;
    g_mock_millis = 1000;
    detectFaults();
    check(!uvBusArmed, "UV_BUS/disarm: disarmed the instant both source switches read LOW");
    check(!(fault_flags & FAULT_UV_BUS), "UV_BUS/disarm: no fault bit during the decay");
    check(mainState == 3 && error_code == ERR_NONE, "UV_BUS/disarm: no latch");
}

static void test_uv_bus_bringup_immunity() {
    test_group("FAULT_UV_BUS: immune to a bring-up ramp that never reaches V_BUS_CHARGED_THRESH");

    // Source switches closed (as in a real bring-up) but V_bus ramping slowly from 0 and
    // never reaching V_BUS_CHARGED_THRESH: must never arm, even though V_bus sits below
    // LIMIT_V_BUS_MIN for many milliseconds — a ramping/unregulated bus is not the same
    // population as a collapsing regulated one.
    reset_test_state();
    mainState = 0;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    const float ceiling = V_BUS_CHARGED_THRESH - 0.1f;   // stays just under the arm threshold
    for (uint32_t t = 0; t <= 200; t += 10) {
        V_bus = ceiling * ((float)t / 200.0f);            // 0 -> ceiling ramp
        g_mock_millis = t;
        detectFaults();
    }
    check(!uvBusArmed, "UV_BUS/bringup: never arms across a ramp that stays under V_BUS_CHARGED_THRESH");
    check(!(fault_flags & FAULT_UV_BUS),
          "UV_BUS/bringup: no fault bit despite V_bus < LIMIT_V_BUS_MIN for most of the ramp");
    check(mainState == 0 && error_code == ERR_NONE, "UV_BUS/bringup: no latch");
}

// NOTE: the fw v4 "sample-gap guard" test (window restarts on a >UV_BUS_MAX_GAP_MS gap) is
// DELETED, not adapted — its entire premise (a window must restart on a gap) is exactly what
// fw v5 fixes. The dwell integrator is deliberately gap-tolerant: it survives gaps between
// excursions (leaking only UV_BUS_DWELL_LEAK*dt while healthy) so a repetitive cycle still
// ratchets to a latch. That behaviour is covered by test_uv_bus_dwell_relay_waveform() (U1,
// gaps between under-phases do NOT reset the accumulator) and contrasted against genuinely
// isolated dips by test_uv_bus_sparse_transient_no_latch() (U2, gaps wide/rare enough to leak
// the dwell away).

// ─── FAULT_UV_BUS: bringupActive disarms it even with everything else satisfied (S3, fw v4
// review round 2026-08-12) ────────────────────────────────────────────────────────────────────
static void test_uv_bus_disarm_during_bringup() {
    test_group("FAULT_UV_BUS: bringupActive disarms even with switches+boosts+charged bus (S3)");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;

    reset_test_state();
    mainState = 0;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    g_pin_value[BT_REG_ENABLE] = HIGH;
    bringupActive = true;
    V_bus = CHARGED;
    g_mock_millis = 0;
    detectFaults();
    check(!uvBusArmed,
          "S3: uvBusArmed stays false while bringupActive is true, even with switches+boosts+"
          "charged bus all otherwise satisfied — the staged bring-up owns its own sags");

    bringupActive = false;
    g_mock_millis = 10;
    detectFaults();
    check(uvBusArmed,
          "S3: arms on the very tick bringupActive falls, with switches/boosts/bus already up");
}

// ─── FAULT_UV_BUS: both boosts off disarms it even with the bus switches still closed (S4,
// the 'F'/'B' bench sequence, fw v4 review round) ─────────────────────────────────────────────
static void test_uv_bus_disarm_both_boosts_off() {
    test_group("FAULT_UV_BUS: disarms when both boosts are off, switches still closed (S4, 'F'/'B')");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_bus = CHARGED;
    g_mock_millis = 0;
    detectFaults();
    check(uvBusArmed, "S4: (setup) armed with a boost enabled");

    // Operator 'F'/'B': both boosts LOW, bus switches stay closed. The bus falls back to the
    // (unregulated) source rail — expected, not a loss of source feed.
    g_pin_value[FC_REG_ENABLE] = LOW;
    V_bus = 8.5f;   // below LIMIT_V_BUS_MIN, the shape of the bare source rail
    g_mock_millis = 10;
    detectFaults();
    check(!uvBusArmed,
          "S4: disarmed the instant both boosts read LOW, even with the bus switches still closed");
    check(!(fault_flags & FAULT_UV_BUS),
          "S4: no fault bit on the sag — routine 'F'/'B' bench sequence, not a loss of source feed");
    check(mainState == 2 && error_code == ERR_NONE, "S4: no latch");
}

// ─── T5 (S7, fw v5 review): UV arming requires a MATCHED source pair, not two independent ORs ──
// The fw v4 predicate ANDed two independent ORs (any switch closed) AND (any boost enabled), so
// a MIXED topology -- e.g. FC_BUS closed with the FC boost OFF, while the BT boost is ON but
// BT_BUS is open -- read as armed even though NO converter was actually feeding the bus. S7
// requires each channel's OWN switch AND OWN boost together (fcFeeding || btFeeding, each a
// matched AND pair). This test drives exactly that mismatched topology -- every individual term
// of the old OR-predicate is satisfied, but no matched pair exists -- and confirms it stays
// disarmed; then closes the matched pair and confirms it arms.
static void test_uv_bus_matched_pair_arming() {
    test_group("FAULT_UV_BUS: arming requires a MATCHED source pair, not mismatched OR terms (S7)");

    const float CHARGED = V_BUS_CHARGED_THRESH + 0.5f;
    const float UNDER   = LIMIT_V_BUS_MIN - 1.0f;

    reset_test_state();
    mainState = 2;
    // Mismatched topology: FC_BUS HIGH but FC_REG LOW (FC not actually feeding), BT_REG HIGH but
    // BT_BUS LOW (BT enabled but disconnected from the bus). Every individual OR term is
    // satisfied (a switch is HIGH, a boost is HIGH), but neither channel forms a matched pair.
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = LOW;
    g_pin_value[BT_REG_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = LOW;
    V_bus = CHARGED;
    g_mock_millis = 0;
    detectFaults();
    check(!uvBusArmed,
          "T5: the fw v4 OR-predicate's individual terms are all satisfied, but no MATCHED "
          "source pair exists -- stays DISARMED (the S7 fix)");

    // Drive the bus under the limit anyway: must never latch or even set the telemetry bit,
    // since it never armed in the first place.
    V_bus = UNDER;
    for (uint32_t t = 10; t <= 100; t += 10) { g_mock_millis = t; detectFaults(); }
    check(!(fault_flags & FAULT_UV_BUS) && uvBusDwellMs == 0.0f,
          "T5: no fault bit, no dwell accumulated -- an unarmed low bus is not a fault");
    check(mainState == 2 && error_code == ERR_NONE, "T5: no latch");

    // Now close the matched pair (FC_REG HIGH, so FC_BUS+FC_REG form a real feeding channel):
    // must arm.
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_bus = CHARGED;
    g_mock_millis = 200;
    detectFaults();
    check(uvBusArmed,
          "T5: closing the matched pair (FC_BUS HIGH + FC_REG HIGH together) arms it");
}

// ─── FAULT_UV_FC: FC-source-rail armed + leaky-dwell filtered (fw v6, 2026-08-12) ────────────
// Mirrors the FAULT_UV_BUS block above with ONE structural difference in the arming term: arms
// on the FC pair being CLOSED (FC_BUS_ENABLE HIGH && FC_REG_ENABLE HIGH, the same S7 matched-pair
// discipline) AND V_fc having been OBSERVED at/above LIMIT_V_FC_MIN while so routed -- the
// "observed healthy while routed" term is what keeps a single-source bench with no fuel cell at
// all (V_fc reads ~0) from ever arming, and therefore from ever boot-locking State 99. Compiled
// and armed in BOTH builds (deliberately outside #if !BENCH_TEST), reusing UV_BUS_DWELL_LEAK and
// UV_BUS_DWELL_DT_CAP_MS as filter-SHAPE constants (not rail-specific quantities) with its own
// UV_FC_DWELL_LATCH_MS (20ms, same value as the bus).
static void test_uv_fc_not_armed_no_source() {
    test_group("FAULT_UV_FC: never arms with V_fc ~0 even with the FC pair closed (single-source bench)");

    // FC pair HIGH+HIGH (as it would read on a bench with no fuel cell wired, or a fuel cell that
    // never actually comes up), but V_fc never reaches LIMIT_V_FC_MIN -- must never arm, and
    // therefore must never fault or latch, no matter how long V_fc sits under the limit.
    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = 0.2f;   // never observed healthy
    for (uint32_t t = 0; t <= 200; t += 20) {
        g_mock_millis = t;
        detectFaults();
    }
    check(!fcUvArmed, "UV_FC/no-source: never arms -- V_fc was never observed >= LIMIT_V_FC_MIN");
    check(!(fault_flags & FAULT_UV_FC),
          "UV_FC/no-source: no fault bit despite V_fc=0.2 < LIMIT_V_FC_MIN for the whole run");
    check(mainState == 2 && error_code == ERR_NONE,
          "UV_FC/no-source: no latch -- this is precisely the bench-with-no-fuel-cell case the "
          "arming term exists to protect");
}

static void test_uv_fc_arms_only_when_pair_and_healthy() {
    test_group("FAULT_UV_FC: arms only when the FC pair is closed AND V_fc has been observed >= V_FC_ARM_THRESH (C1)");

    // Pair closed, V_fc comfortably healthy (>= V_FC_ARM_THRESH) -> arms.
    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = V_FC_ARM_THRESH + 1.0f;
    g_mock_millis = 0;
    detectFaults();
    check(fcUvArmed, "UV_FC/arm: arms once the FC pair is closed and V_fc reads >= V_FC_ARM_THRESH");

    // Contrast (a): V_fc healthy, but the pair is NOT closed (FC_REG_ENABLE LOW) -> never arms.
    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = LOW;
    V_fc = V_FC_ARM_THRESH + 1.0f;
    g_mock_millis = 0;
    detectFaults();
    check(!fcUvArmed,
          "UV_FC/arm: a healthy V_fc alone does not arm -- the FC pair must also be closed");

    // C1: ARM (7.0V) is DISTINCT from and above TRIP (LIMIT_V_FC_MIN, 6.0V) -- arming and
    // tripping on the same value would let one ramp sample through 6.0V arm the filter
    // mid-ramp, with the next dip back under latching ERR_UV_FC. Pair closed, V_fc anywhere in
    // [LIMIT_V_FC_MIN, V_FC_ARM_THRESH) (the 1.0V margin band) must NEVER arm, no matter how
    // long it sits there or how many ticks pass.
    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    for (uint32_t t = 0; t <= 100; t += 10) {
        V_fc = LIMIT_V_FC_MIN + 0.5f;   // 6.5V -- above trip, below arm
        g_mock_millis = t;
        detectFaults();
    }
    check(!fcUvArmed,
          "UV_FC/arm (C1): V_fc = 6.5V (in [6.0, 7.0)) never arms, however long it is held there");
    check(!(fault_flags & FAULT_UV_FC) && mainState == 2 && error_code == ERR_NONE,
          "UV_FC/arm (C1): unarmed, so no fault bit and no latch either, even though V_fc is "
          "already below what the OLD (pre-C1) single-threshold arm would have required");

    // Just under the arm threshold specifically (6.99V) -> still does not arm (strictly <, not <=).
    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = V_FC_ARM_THRESH - 0.01f;
    g_mock_millis = 0;
    detectFaults();
    check(!fcUvArmed, "UV_FC/arm (C1): V_fc just under V_FC_ARM_THRESH (6.99V) does not arm");

    // Exactly at V_FC_ARM_THRESH -> arms (the comparison is >=, not >).
    V_fc = V_FC_ARM_THRESH;
    g_mock_millis = 1;
    detectFaults();
    check(fcUvArmed, "UV_FC/arm (C1): V_fc exactly at V_FC_ARM_THRESH (7.0V) does arm (>=, not >)");

    // The TRIP limit is unmoved: once armed (via a value >= V_FC_ARM_THRESH), a V_fc that falls
    // to just under LIMIT_V_FC_MIN (6.0V, NOT 7.0V) is what sets the transient bit -- confirming
    // C1 only changed the ARM edge, not the TRIP edge.
    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = V_FC_ARM_THRESH;
    g_mock_millis = 0;
    detectFaults();
    check(fcUvArmed, "UV_FC/arm (C1): (setup) armed at V_FC_ARM_THRESH");
    V_fc = LIMIT_V_FC_MIN + 0.5f;   // 6.5V -- inside the [6.0, 7.0) margin band, ABOVE trip
    g_mock_millis = 1;
    detectFaults();
    check(!(fault_flags & FAULT_UV_FC),
          "UV_FC/arm (C1): once armed, 6.5V is still ABOVE the 6.0V trip limit -- no transient bit");
    V_fc = LIMIT_V_FC_MIN - 0.1f;   // 5.9V -- below trip
    g_mock_millis = 2;
    detectFaults();
    check((fault_flags & FAULT_UV_FC) != 0,
          "UV_FC/arm (C1): the trip limit is still LIMIT_V_FC_MIN (6.0V), unmoved by C1 -- 5.9V "
          "sets the transient bit once armed");
}

static void test_uv_fc_continuous_collapse_latches() {
    test_group("FAULT_UV_FC: continuous collapse latches at 20ms dwell, not before");

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = V_FC_ARM_THRESH + 1.0f;
    g_mock_millis = 0; detectFaults();   // arm
    check(fcUvArmed, "UV_FC/collapse: (setup) armed");

    V_fc = LIMIT_V_FC_MIN - 1.0f;
    for (uint32_t t = 1; t <= 15; t++) { g_mock_millis = t; detectFaults(); }
    check(mainState == 2 && error_code == ERR_NONE,
          "UV_FC/collapse: not latched at 15ms of continuous under-dwell");
    check(fabsf(fcUvDwellMs - 15.0f) < 1e-6f,
          "UV_FC/collapse: dwell tracks the elapsed continuous under-time 1:1");

    for (uint32_t t = 16; t <= 20; t++) { g_mock_millis = t; detectFaults(); }
    check(mainState == 99 && error_code == ERR_UV_FC,
          "UV_FC/collapse: latches once dwell reaches UV_FC_DWELL_LATCH_MS (20ms), naming the "
          "cause ERR_UV_FC (not ERR_UV_BUS -- WP0096/WP0098's V_fc collapse led the bus event by "
          "~7ms, so the source-rail fault must latch first and name the true cause)");
}

static void test_uv_fc_transient_flag_bit() {
    test_group("FAULT_UV_FC: the transient telemetry bit sets/clears independently of the latch");

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = V_FC_ARM_THRESH + 1.0f;
    g_mock_millis = 0; detectFaults();   // arm
    check(!(fault_flags & FAULT_UV_FC), "UV_FC/flag: bit clear while V_fc is above the limit");

    V_fc = LIMIT_V_FC_MIN - 1.0f;
    g_mock_millis = 1; detectFaults();
    check((fault_flags & FAULT_UV_FC) != 0 && mainState == 2,
          "UV_FC/flag: bit sets on the very first under-limit tick, well before any latch");

    V_fc = V_FC_ARM_THRESH + 1.0f;
    g_mock_millis = 2; detectFaults();
    check(!(fault_flags & FAULT_UV_FC),
          "UV_FC/flag: bit clears the instant V_fc recovers above the limit");
}

static void test_uv_fc_dwell_leak() {
    test_group("FAULT_UV_FC: an intermittent under/over pattern that nets below the latch never fires");

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = V_FC_ARM_THRESH + 1.0f;
    g_mock_millis = 0; detectFaults();   // arm

    // 9 excursions of 2ms under / 24ms over -- net +0.8ms dwell/cycle (same shape as the
    // UV_BUS sparse-transient case), well under the 20ms latch across all 9.
    uint32_t t = 0;
    for (int ex = 0; ex < 9; ex++) {
        for (int i = 0; i < 2; i++) {
            t++; g_mock_millis = t; V_fc = LIMIT_V_FC_MIN - 1.0f; detectFaults();
        }
        for (int i = 0; i < 24; i++) {
            t++; g_mock_millis = t; V_fc = V_FC_ARM_THRESH + 1.0f; detectFaults();
        }
    }
    check(mainState == 2 && error_code == ERR_NONE,
          "UV_FC/leak: 9 isolated ~2ms dips spread over ~234ms never latch -- the dwell leaks "
          "away between them");
    check(fcUvDwellMs < UV_FC_DWELL_LATCH_MS,
          "UV_FC/leak: accumulated dwell stays below the latch threshold at the end of the run");
    check(fcUvTransientCount == 9,
          "UV_FC/leak: every one of the 9 dips is counted as a closed transient (visible via 'S')");
}

static void test_uv_fc_dwell_dt_cap() {
    test_group("FAULT_UV_FC: a single huge tick gap contributes at most UV_BUS_DWELL_DT_CAP_MS (5ms)");

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = V_FC_ARM_THRESH + 1.0f;
    g_mock_millis = 0; detectFaults();   // arm

    V_fc = LIMIT_V_FC_MIN - 1.0f;
    g_mock_millis = 500; detectFaults();     // 500ms gap since the last armed tick
    check(fabsf(fcUvDwellMs - UV_BUS_DWELL_DT_CAP_MS) < 1e-6f,
          "UV_FC/cap: a stalled-loop/long gap credits at most 5ms, not the full 500ms elapsed");

    g_mock_millis = 1000; detectFaults();    // another 500ms gap
    check(fabsf(fcUvDwellMs - 2.0f * UV_BUS_DWELL_DT_CAP_MS) < 1e-6f,
          "UV_FC/cap: a second capped tick adds another 5ms -- a stalled loop cannot insta-latch "
          "off a single huge dt");
    check(mainState == 2 && error_code == ERR_NONE,
          "UV_FC/cap: two capped ticks (10ms total) stay below the 20ms latch");
}

static void test_uv_fc_disarm_predicates() {
    test_group("FAULT_UV_FC: disarm (+ dwell zeroed) when the FC pair opens, the stage is dark, or bring-up runs");

    const float HEALTHY = V_FC_ARM_THRESH + 1.0f;
    const float UNDER   = LIMIT_V_FC_MIN - 1.0f;

    // (a) FC_BUS_ENABLE opens (e.g. the share loop's own cut, an operator toggle).
    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = HEALTHY;
    g_mock_millis = 0; detectFaults();
    V_fc = UNDER;
    for (uint32_t t = 1; t <= 15; t++) { g_mock_millis = t; detectFaults(); }
    check(fabsf(fcUvDwellMs - 15.0f) < 1e-6f, "UV_FC/disarm(a): (setup) 15ms accumulated");
    g_pin_value[FC_BUS_ENABLE] = LOW;
    g_mock_millis = 16; detectFaults();
    check(!fcUvArmed && fcUvDwellMs == 0.0f,
          "UV_FC/disarm(a): FC_BUS_ENABLE opening disarms and dumps the accumulated dwell");

    // (b) FC_REG_ENABLE opens (boost disabled) with the bus switch still closed.
    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = HEALTHY;
    g_mock_millis = 0; detectFaults();
    V_fc = UNDER;
    for (uint32_t t = 1; t <= 15; t++) { g_mock_millis = t; detectFaults(); }
    g_pin_value[FC_REG_ENABLE] = LOW;
    g_mock_millis = 16; detectFaults();
    check(!fcUvArmed && fcUvDwellMs == 0.0f,
          "UV_FC/disarm(b): FC_REG_ENABLE opening (boost off) disarms too, even with the bus "
          "switch still closed");

    // (c) The stage goes fully dark (both pins LOW) -- must also disarm and dump.
    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = HEALTHY;
    g_mock_millis = 0; detectFaults();
    V_fc = UNDER;
    for (uint32_t t = 1; t <= 15; t++) { g_mock_millis = t; detectFaults(); }
    g_pin_value[FC_BUS_ENABLE] = LOW;
    g_pin_value[FC_REG_ENABLE] = LOW;
    g_mock_millis = 16; detectFaults();
    check(!fcUvArmed && fcUvDwellMs == 0.0f,
          "UV_FC/disarm(c): a fully dark stage disarms and dumps the dwell");

    // (d) bringupActive disarms it even with everything else satisfied (S3 discipline, shared
    // with the FAULT_UV_BUS block above) -- the staged bring-up owns its own sags.
    reset_test_state();
    mainState = 0;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    bringupActive = true;
    V_fc = HEALTHY;
    g_mock_millis = 0;
    detectFaults();
    check(!fcUvArmed,
          "UV_FC/disarm(d): bringupActive keeps it disarmed even with the FC pair closed and "
          "V_fc healthy");
    bringupActive = false;
    g_mock_millis = 1;
    detectFaults();
    check(fcUvArmed,
          "UV_FC/disarm(d): arms on the very tick bringupActive falls, with the pair already "
          "closed and V_fc already healthy");
}

// NOTE: the fw v4 "disarm mid-window restarts it clean" test is superseded by
// test_uv_bus_disarm_resets_dwell() (U6) above, which asserts the same disarm-drops-progress
// property against the dwell accumulator (uvBusDwellMs) instead of the deleted sample-window
// state (uvBusUnderSamples/uvBusLastUnderMs).

// ─── P0 entry darkens the power stage before closing the bus switches ────────
static void test_bringup_dark_start() {
    test_group("Bring-up P0 darkens the stage first (review F1)");

    // A boost left enabled by a manual 'F' and a latched FC_CHARGE must both be cleared BEFORE
    // the bus switches close (hot-plug + illegal BT_BUS+FC_CHARGE combination respectively).
    reset_test_state();
    mainState = 98;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 0.0f; V_rgn = 0.0f;
    g_pin_value[FC_REG_ENABLE]    = HIGH;
    g_pin_value[BT_REG_ENABLE]    = HIGH;
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    g_pin_value[REGEN_ENABLE]     = HIGH;
    g_pin_value[MOT_PWR_ENABLE]   = HIGH;

    Serial.rx_queue.push('G');
    doState98();                                  // arms + runs P0 entry

    check(digitalRead(FC_REG_ENABLE) == LOW && digitalRead(BT_REG_ENABLE) == LOW,
          "P0 dark-start: both boosts driven LOW before the switches close");
    check(digitalRead(FC_CHARGE_ENABLE) == LOW,
          "P0 dark-start: a latched FC_CHARGE is closed (no illegal BT_BUS+FC_CHARGE)");
    check(digitalRead(REGEN_ENABLE) == LOW,
          "P0 dark-start: REGEN path closed");
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "P0 dark-start: motor node taken off the chain");
    check(digitalRead(FC_BUS_ENABLE) == HIGH && digitalRead(BT_BUS_ENABLE) == HIGH,
          "P0 dark-start: bus switches closed onto a dark stage");

#if !BENCH_TEST
    // Same via the production doState0() path. (Skipped under BENCH_TEST: doState0() there is
    // the bypass, which never runs the bring-up machine.)
    reset_test_state();
    mainState = 0;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 0.0f;
    g_pin_value[FC_REG_ENABLE]    = HIGH;
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    doState0();
    check(digitalRead(FC_REG_ENABLE) == LOW && digitalRead(FC_CHARGE_ENABLE) == LOW &&
          digitalRead(FC_BUS_ENABLE) == HIGH,
          "P0 dark-start: doState0() path darkens the stage identically");
#endif
}

// ─── Timeout is evaluated BEFORE the gate in every phase (review F2) ─────────
static void test_bringup_late_gate_faults() {
    test_group("Bring-up: a gate satisfied past the deadline FAULTS (review F2)");

    // --- P0: gate conditions all true, but the tick lands past PRECHARGE_TIMEOUT_MS ---------
    reset_test_state();
    mainState = 0;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 0.0f;
    doState0();                                            // P0 entry, phaseStart = 0
    V_bus = 11.0f;                                         // gate voltages now satisfied
    g_mock_millis = PRECHARGE_TIMEOUT_MS + 1;              // ...but the deadline has passed
    doState0();
    check(mainState == 99 && error_code == ERR_INIT_FAIL,
          "P0: a late-but-passing gate faults instead of accepting");
    check(digitalRead(FC_REG_ENABLE) == LOW,
          "P0: boosts never enabled by the late gate");

    // --- P1: bus reaches regulation only on a tick past BUS_CHARGE_TIMEOUT_MS ---------------
    reset_test_state();
    mainState = 0;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f;
    doState0();                                            // P0 entry
    g_mock_millis = PRECHARGE_MIN_MS + 1;
    doState0();                                            // P0 gate → P1, phaseStart = 41
    check(bringupPhase == 2, "P1: reached the bus-charge gate");
    V_bus = 16.0f;                                         // regulation reached...
    g_mock_millis += BUS_CHARGE_TIMEOUT_MS + 1;            // ...but too late
    doState0();
    check(mainState == 99 && error_code == ERR_INIT_FAIL,
          "P1: a late-but-passing regulation gate faults instead of accepting");

    // --- P3: V_rgn tracks the bus, but only past MOT_CONNECT_TIMEOUT_MS ---------------------
    reset_test_state();
    mainState = 0;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f; V_rgn = 0.0f;
    doState0();                                            // P0 entry
    g_mock_millis = PRECHARGE_MIN_MS + 1;  doState0();     // → P1
    V_bus = 16.0f;
    g_mock_millis += 1;                    doState0();     // → dwell
    g_mock_millis += BUS_REG_DWELL_MS + 1; doState0();     // dwell done → phase 4
    g_mock_millis += 1;                    doState0();     // P3 entry, phaseStart set
    check(bringupPhase == 5, "P3: motor node connected");
    V_rgn = 15.0f;                                         // node now tracks the bus...
    g_mock_millis += MOT_CONNECT_TIMEOUT_MS + 1;           // ...but past the connect deadline
    doState0();
    check(mainState == 99 && error_code == ERR_MOT_HOTPLUG,
          "P3: a late-but-passing connect gate faults with FAULT_MOT_HOTPLUG");
    check(!bringupActive && bringupPhase == 0, "P3: machine self-reset on the late-gate fault");
}

// ─── P3 completion also requires the bus to still be in regulation (review F3) ─
static void test_bringup_p3_bus_sag() {
    test_group("Bring-up P3: a sagged bus must not complete the connect (review F3)");

    reset_test_state();
    mainState = 0;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f; V_rgn = 0.0f;
    doState0();                                            // P0 entry
    g_mock_millis = PRECHARGE_MIN_MS + 1;  doState0();     // → P1
    V_bus = 16.0f;
    g_mock_millis += 1;                    doState0();     // → dwell
    g_mock_millis += BUS_REG_DWELL_MS + 1; doState0();     // dwell done
    g_mock_millis += 1;                    doState0();     // P3 entry
    check(bringupPhase == 5, "P3 sag: motor node connected from the regulated bus");

    // The connect drags the bus down: V_rgn "tracks" within MOT_HOTPLUG_MARGIN, but the bus is
    // below V_BUS_CHARGED_THRESH (13.5) — not a healthy completion.
    V_bus = 12.5f;
    V_rgn = V_bus - 2.0f;                                  // 10.5 — within the 3.0V margin
    g_mock_millis += 20;
    doState0();
    check(bringupPhase == 5 && mainState == 0 && bringupActive,
          "P3 sag: relative tracking alone does NOT complete on a sagged bus");

    // Bus recovers → completes.
    V_bus = 16.0f; V_rgn = 14.0f;
    g_mock_millis += 20;
    doState0();
    check(mainState == 1 && !bringupActive,
          "P3 sag: completes once the bus is back in regulation");
    check(error_code == ERR_NONE, "P3 sag: no fault on the recovered completion");
}

// ─── 'G' takes motor ownership from a standing manual command (round 2, F1) ──
static void test_bringup_g_takes_motor_ownership() {
    test_group("'G' clears a standing manual motor command / droop-live");

    reset_test_state();
    mainState = 98;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f; V_rgn = 0.0f;

    // Operator had set a constant current and enabled the live share controller.
    manualMotorMode    = MOTOR_TEST_CURRENT;
    manualMotorCurrent = 4.0f;
    powerBalanceLive   = true;
    vesc.reset();

    Serial.rx_queue.push('G');
    doState98();

    check(bringupActive, "'G' ownership: bring-up actually armed");
    check(manualMotorMode == MOTOR_TEST_OFF,
          "'G' ownership: standing manual mode cleared (cannot resume after DONE)");
    check(manualMotorCurrent == 0.0f,
          "'G' ownership: standing manual current cleared");
    check(!powerBalanceLive,
          "'G' ownership: live droop/share writer disabled");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "'G' ownership: a zero-current flush was sent to the VESC");

    // And nothing re-commands the motor on subsequent machine ticks.
    vesc.reset();
    g_mock_millis = 10;
    state98_tick();
    check(vesc.current_calls.empty(),
          "'G' ownership: no motor command issued on a plain bring-up tick");
}

// ─── The standalone manual/live block is suppressed while the machine runs ───
static void test_bringup_suppresses_manual_block() {
    test_group("Manual/live motor block suppressed during a bring-up (round 2, F1)");

    reset_test_state();
    mainState = 98;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f; V_rgn = 0.0f;

    Serial.rx_queue.push('G');
    doState98();                                   // arms (and haltMotorOutput()s)
    check(bringupActive, "manual suppression: bring-up armed");

    // Contrive the belt-and-suspenders case: a manual mode re-appears WHILE the machine runs
    // (the 'A'/'V' lockout normally prevents this — set the globals directly).
    manualMotorMode    = MOTOR_TEST_CURRENT;
    manualMotorCurrent = 3.5f;
    powerBalanceLive   = true;
    vesc.reset();
    SPI.reset();

    g_mock_millis = 10;
    state98_tick();                                // empty queue: machine tick only
    check(vesc.current_calls.empty(),
          "manual suppression: applyManualMotor() never runs while bringupActive");
    check(SPI.transfer_log.empty(),
          "manual suppression: powerBalanceGated() never writes the droop MDACs either");
    check(bringupActive, "manual suppression: the machine is still running");

    // Once the bring-up is aborted the manual block is live again.
    Serial.rx_queue.push('X');
    doState98();
    check(!bringupActive, "manual suppression: aborted");
    manualMotorMode    = MOTOR_TEST_CURRENT;
    manualMotorCurrent = 3.5f;
    vesc.reset();
    g_mock_millis += 10;
    state98_tick();
    check(!vesc.current_calls.empty(),
          "manual suppression: the manual block resumes once the machine is idle");
}

// ─── State-98 topology lockout while a bring-up is running (review F1) ───────
static void test_dostate98_topology_lockout() {
    test_group("State 98 topology lockout during a staged bring-up");

    // Walk to mid-P1 (boosts ON via the machine, bus switches ON).
    reset_test_state();
    mainState = 98;
    g_mock_millis = 0;
    V_fc = 12.0f; V_batt = 7.0f; V_bus = 11.0f; V_rgn = 0.0f;
    Serial.rx_queue.push('G');
    doState98();
    g_mock_millis = PRECHARGE_MIN_MS + 1;
    state98_tick();                                        // P0 gate → boosts on, phase 2
    check(bringupActive && bringupPhase == 2, "lockout: reached mid-P1 with the machine running");

    V_bus = 16.0f;   // regulated, so '3' would otherwise be ALLOWED by the connect guard
    int motBefore  = digitalRead(MOT_PWR_ENABLE);
    int fcRegBefore = digitalRead(FC_REG_ENABLE);
    int fcChgBefore = digitalRead(FC_CHARGE_ENABLE);

    Serial.rx_queue.push('3');
    doState98();
    check(digitalRead(MOT_PWR_ENABLE) == motBefore,
          "lockout: '3' refused mid-bring-up (would bypass the dwell)");

    Serial.rx_queue.push('F');
    doState98();
    check(digitalRead(FC_REG_ENABLE) == fcRegBefore,
          "lockout: 'F' refused mid-bring-up (would re-arm a boost the machine owns)");

    Serial.rx_queue.push('5');
    doState98();
    check(digitalRead(FC_CHARGE_ENABLE) == fcChgBefore,
          "lockout: '5' refused mid-bring-up (illegal BT_BUS+FC_CHARGE)");

    Serial.rx_queue.push('1');
    doState98();
    check(digitalRead(FC_BUS_ENABLE) == HIGH, "lockout: '1' refused (bus switch stays as the machine set it)");

    check(bringupActive && bringupPhase >= 2,
          "lockout: the machine keeps running through the refused keys");

    // Motor/droop writers ('A','V','P','O') are locked out too (round 2, F2). Each normally
    // opens a numeric-entry prompt — a refusal must leave pendingInput untouched.
    const char writers[] = {'A', 'V', 'P', 'O'};
    for (char w : writers) {
        pendingInput = PEND_NONE;
        inputBufIdx  = 0;
        Serial.rx_queue.push(w);
        doState98();
        char msg[96];
        snprintf(msg, sizeof(msg),
                 "lockout: '%c' refused mid-bring-up (no numeric-entry prompt opened)", w);
        check(pendingInput == PEND_NONE && inputBufIdx == 0, msg);
    }
    check(manualMotorMode == MOTOR_TEST_OFF && !powerBalanceLive,
          "lockout: no motor/droop writer took effect through the refusals");

    // 'S' (read-only status) still works and does not disturb the machine.
    uint8_t phaseBefore = bringupPhase;
    Serial.rx_queue.push('S');
    doState98();
    check(bringupActive && bringupPhase == phaseBefore,
          "lockout: 'S' status dump still works and leaves the machine alone");

    // 'X' still aborts.
    Serial.rx_queue.push('X');
    doState98();
    check(!bringupActive && bringupPhase == 0, "lockout: 'X' still aborts the bring-up");
    check(digitalRead(FC_REG_ENABLE) == LOW && digitalRead(FC_BUS_ENABLE) == LOW,
          "lockout: the abort still darkens the stage");
}

// ─── State 98 hot-plug guard on '1'/'2' ──────────────────────────────────────
static void test_dostate98_hotplug_guard() {
    test_group("State 98 bus hot-plug guard ('1'/'2')");
    reset_test_state();
    mainState = 98;

    // Boost ON + bus low → '1' ON refused (FC_BUS stays LOW): the exact failure condition.
    g_pin_value[FC_REG_ENABLE] = HIGH;
    g_pin_value[FC_BUS_ENABLE] = LOW;
    V_bus = 5.0f;
    Serial.rx_queue.push('1');
    doState98();
    check(digitalRead(FC_BUS_ENABLE) == LOW,
          "doState98: '1' refused (FC boost ON + bus low) — switch stays LOW");

    // Bus already charged → '1' ON allowed (no step across the ideal diode).
    g_pin_value[FC_BUS_ENABLE] = LOW;
    V_bus = 16.0f;
    Serial.rx_queue.push('1');
    doState98();
    check(digitalRead(FC_BUS_ENABLE) == HIGH,
          "doState98: '1' allowed when the bus is already charged");

    // Boost OFF → '2' ON allowed even with a low bus (no running boost to hot-plug).
    g_pin_value[BT_REG_ENABLE] = LOW;
    g_pin_value[BT_BUS_ENABLE] = LOW;
    V_bus = 5.0f;
    Serial.rx_queue.push('2');
    doState98();
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "doState98: '2' allowed when the boost is OFF");

    // Turning a switch OFF is always allowed (guard only blocks the unsafe ON).
    g_pin_value[BT_REG_ENABLE] = HIGH;       // boost on
    g_pin_value[BT_BUS_ENABLE] = HIGH;       // currently on
    V_bus = 5.0f;                            // bus low
    Serial.rx_queue.push('2');
    doState98();
    check(digitalRead(BT_BUS_ENABLE) == LOW,
          "doState98: '2' OFF always allowed (guard only blocks ON)");
}

// ─── State 98 '2' mutual-exclusion guard (BT_BUS while FC_CHARGE is HIGH) ─────
static void test_dostate98_bt_bus_fc_charge_guard() {
    test_group("State 98 '2' refuses BT_BUS while FC_CHARGE_ENABLE is HIGH");
    reset_test_state();
    mainState = 98;

    // FC_CHARGE HIGH → '2' ON refused (the IO CSV's illegal combination).
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE]    = LOW;
    g_pin_value[BT_REG_ENABLE]    = LOW;   // boost off, so the hot-plug guard is not the blocker
    V_bus = 16.0f;
    Serial.rx_queue.push('2');
    doState98();
    check(digitalRead(BT_BUS_ENABLE) == LOW,
          "doState98: '2' refused while FC_CHARGE_ENABLE HIGH — BT_BUS stays LOW");

    // FC_CHARGE back LOW → the same toggle is allowed.
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    Serial.rx_queue.push('2');
    doState98();
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "doState98: '2' allowed once FC_CHARGE_ENABLE is LOW");
}

// ─── State 98 'Q' exit closes the charge/regen paths ─────────────────────────
static void test_dostate98_quit_closes_charge_paths() {
    test_group("State 98 'Q' exit closes FC_CHARGE/REGEN");
    reset_test_state();
    mainState = 98;

    // Operator left the charger powered and the regen path open, then quits.
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    g_pin_value[REGEN_ENABLE]     = HIGH;
    g_pin_value[MOT_PWR_ENABLE]   = HIGH;
    Serial.rx_queue.push('Q');
    doState98();

    check(mainState == 1,
          "doState98: 'Q' returns to State 1");
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState98: 'Q' forces MOT_PWR_ENABLE LOW");
    check(digitalRead(FC_CHARGE_ENABLE) == LOW,
          "doState98: 'Q' closes FC_CHARGE_ENABLE (charger not left powered into Idle)");
    check(digitalRead(REGEN_ENABLE) == LOW,
          "doState98: 'Q' closes REGEN_ENABLE");
    check(vesc.last_current == 0.0f,
          "doState98: 'Q' flushes a zero VESC current before cutting motor power");
}

// ─── State 3 (Finish) returns to Idle with the bus left energized ────────────
static void test_dostate3_leaves_bus_energized() {
    test_group("doState3() leaves the bus energized");
    reset_test_state();

    // Bus came up in Init: switches + boosts ON entering Finish.
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    g_pin_value[BT_REG_ENABLE] = HIGH;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    mainState = 3;

    doState3();
    check(mainState == 1,
          "doState3: returns to Idle");
    check(digitalRead(FC_BUS_ENABLE) == HIGH && digitalRead(BT_BUS_ENABLE) == HIGH,
          "doState3: bus switches stay ON (no re-hot-plug on next Run)");
    check(digitalRead(FC_REG_ENABLE) == HIGH && digitalRead(BT_REG_ENABLE) == HIGH,
          "doState3: boosts stay ON (bus remains armed)");
    // Death-5 change: the motor node is left ENERGIZED (like the bus) so Idle→Run never re-hot-plugs
    // the 470µF+VESC stack. The motor is held stopped by the zero VESC command, not by cutting power.
    check(digitalRead(MOT_PWR_ENABLE) == HIGH,
          "doState3: motor node stays energized (no re-hot-plug on next Run)");
    check(vesc.last_current == 0.0f,
          "doState3: motor commanded to zero (held stopped without cutting MOT_PWR)");
}

// ─── Motor-node connect guard (2026-08-03 doctrine — INVERTS the Death-5 rule) ─
static void test_mot_pwr_hotplug_guard() {
    test_group("MOT_PWR connect guard (motPwrConnectBlocked/assertMotPwrEnable/doState2)");

    // motPwrConnectBlocked(): purely a bus-regulation test. V_rgn is NOT part of the refusal —
    // a discharged node at a regulated bus is precisely the sanctioned CSS-controlled connect.
    reset_test_state();
    V_bus = 0.0f;  V_rgn = 0.0f;              // dark bus
    check(motPwrConnectBlocked() == true,
          "blocked: dark bus → connect refused");
    V_bus = 7.0f;  V_rgn = 0.0f;              // pre-charged bus, boosts not yet regulating
    check(motPwrConnectBlocked() == true,
          "blocked: pre-charged/mid-ramp bus (below V_BUS_CHARGED_THRESH) → connect refused");
    V_bus = V_BUS_CHARGED_THRESH - 0.1f;
    check(motPwrConnectBlocked() == true,
          "blocked: just below V_BUS_CHARGED_THRESH → connect refused");
    V_bus = 16.0f; V_rgn = 0.0f;              // regulated bus, discharged node
    check(motPwrConnectBlocked() == false,
          "allowed: regulated bus + DISCHARGED node → this is the sanctioned P3 connect");
    V_rgn = 16.0f;
    check(motPwrConnectBlocked() == false,
          "allowed: regulated bus + charged node (V_rgn is irrelevant to the predicate)");

    // assertMotPwrEnable(): OFF always allowed; ON idempotent; ON gated by the predicate.
    reset_test_state();
    g_pin_value[MOT_PWR_ENABLE] = HIGH; V_bus = 16.0f;
    check(assertMotPwrEnable(false) == true && digitalRead(MOT_PWR_ENABLE) == LOW,
          "assert: OFF always succeeds (regulated bus)");
    g_pin_value[MOT_PWR_ENABLE] = HIGH; V_bus = 0.0f;
    check(assertMotPwrEnable(false) == true && digitalRead(MOT_PWR_ENABLE) == LOW,
          "assert: OFF always succeeds (dark bus too)");
    // Idempotent ON must NOT consult the predicate: set a blocking bus and leave the pin HIGH.
    g_pin_value[MOT_PWR_ENABLE] = HIGH; V_bus = 0.0f; V_rgn = 0.0f;
    check(assertMotPwrEnable(true) == true && digitalRead(MOT_PWR_ENABLE) == HIGH,
          "assert: already-ON is idempotent even at a dark bus (never re-checks the guard)");
    g_pin_value[MOT_PWR_ENABLE] = LOW; V_bus = 0.0f;
    check(assertMotPwrEnable(true) == false && digitalRead(MOT_PWR_ENABLE) == LOW,
          "assert: ON refused at a dark bus (stays LOW)");
    g_pin_value[MOT_PWR_ENABLE] = LOW; V_bus = 7.0f;
    check(assertMotPwrEnable(true) == false && digitalRead(MOT_PWR_ENABLE) == LOW,
          "assert: ON refused at a pre-charged bus (stays LOW)");
    g_pin_value[MOT_PWR_ENABLE] = LOW; V_bus = 16.0f; V_rgn = 0.0f;
    check(assertMotPwrEnable(true) == true && digitalRead(MOT_PWR_ENABLE) == HIGH,
          "assert: ON ALLOWED at a regulated bus with a discharged node (meaning flip)");

    // doState2(): motor node already energized → runs, no fault.
    reset_test_state();
    mainState = 2;
    g_pin_value[MOT_PWR_ENABLE] = HIGH; V_bus = 16.0f; V_rgn = 16.0f;
    doState2();
    check(mainState == 2 && !(fault_flags & FAULT_MOT_HOTPLUG),
          "doState2: energized motor node → runs normally, no fault");
    check(digitalRead(MOT_PWR_ENABLE) == HIGH,
          "doState2: MOT_PWR stays energized");

    // doState2(): node LOW at a REGULATED bus → now silently CONNECTS (sanctioned), no fault.
    reset_test_state();
    mainState = 2;
    g_pin_value[MOT_PWR_ENABLE] = LOW; V_bus = 16.0f; V_rgn = 0.0f;
    doState2();
    check(digitalRead(MOT_PWR_ENABLE) == HIGH,
          "doState2: node LOW at a regulated bus → starts the sanctioned CSS connect");
    check(mainState == 2 && !(fault_flags & FAULT_MOT_HOTPLUG),
          "doState2: no fault for the sanctioned connect");

    // doState2(): node LOW at an UNREGULATED bus → refuse + fault.
    reset_test_state();
    mainState = 2;
    g_pin_value[MOT_PWR_ENABLE] = LOW; V_bus = 7.0f; V_rgn = 0.0f;
    doState2();
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState2: refuses the connect on an unregulated bus (MOT_PWR stays LOW)");
    check(mainState == 99 && error_code == ERR_MOT_HOTPLUG,
          "doState2: latches State 99 with ERR_MOT_HOTPLUG on an unregulated-bus Run entry");
    check((fault_flags & FAULT_MOT_HOTPLUG) != 0,
          "doState2: FAULT_MOT_HOTPLUG flag set");
}

// ─── State 98 '3' motor-node connect guard ───────────────────────────────────
static void test_dostate98_mot_pwr_guard() {
    test_group("State 98 '3' motor-node connect guard (bus-regulation gated)");
    reset_test_state();
    mainState = 98;

    // Dark bus → '3' ON refused.
    g_pin_value[MOT_PWR_ENABLE] = LOW;
    V_bus = 0.0f; V_rgn = 0.0f;
    Serial.rx_queue.push('3');
    doState98();
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState98: '3' refused at a dark bus — stays LOW");

    // Pre-charged (mid-bring-up) bus → still refused.
    g_pin_value[MOT_PWR_ENABLE] = LOW;
    V_bus = 7.0f; V_rgn = 7.0f;
    Serial.rx_queue.push('3');
    doState98();
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState98: '3' refused at a pre-charged bus (use 'G')");

    // Regulated bus + discharged node → ALLOWED (the meaning flip).
    g_pin_value[MOT_PWR_ENABLE] = LOW;
    V_bus = 16.0f; V_rgn = 0.0f;
    Serial.rx_queue.push('3');
    doState98();
    check(digitalRead(MOT_PWR_ENABLE) == HIGH,
          "doState98: '3' allowed from a regulated bus even with a discharged node");

    // Turning OFF is always allowed.
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    V_bus = 0.0f; V_rgn = 0.0f;
    Serial.rx_queue.push('3');
    doState98();
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState98: '3' OFF always allowed (guard only blocks ON)");
}

// ─── V_BUS_NOMINAL parameterization preserves current thresholds ─────────────
static void test_bus_voltage_scaling() {
    test_group("V_BUS_NOMINAL-derived thresholds (16V nominal, RD1=215k retune executed)");
    // 16V bus retune executed 2026-07-11 (RD1 bodged 237k -> 215k, V0 = 15.91V no-load).
    // Margin raised +1.0 -> +1.5 (operator decision 2026-07-31): the G bring-up's RT1987
    // re-strike load-dump overshoot parks the bus at ~17.4V and was tripping OV_BUS.
    check(fabsf(LIMIT_V_BUS_MAX - 17.5f) < 1e-4f,
          "LIMIT_V_BUS_MAX = V_BUS_NOMINAL + 1.5 = 17.5 (16V nominal)");
    check(fabsf(V_BUS_CHARGED_THRESH - 13.5f) < 1e-4f,
          "V_BUS_CHARGED_THRESH = V_BUS_NOMINAL - 2.5 = 13.5 (16V nominal)");
}

// ─── detectFaults() Ag105 GENSTAT error-state decoding ───────────────────────
static void test_genstat_fault() {
    test_group("detectFaults() GENSTAT error states");

    struct { uint8_t raw; bool valid; bool shouldFault; const char* desc; } cases[] = {
        { 0x05, true,  true,  "GENSTAT=0x05 OC/Regulation Error → fault" },
        { 0x06, true,  true,  "GENSTAT=0x06 Thermal Shutdown → fault" },
        { 0x07, true,  true,  "GENSTAT=0x07 Timeout Error → fault" },
        { 0x04, true,  false, "GENSTAT=0x04 Bring-Up Charge (normal) → NO fault" },
        { 0x02, true,  false, "GENSTAT=0x02 Charging → NO fault" },
        { 0x0A, true,  false, "0x0A = Charging + MPPT flag (bit3) → NO fault (mask isolates 0x07)" },
        { 0x0E, true,  true,  "0x0E = Thermal Shutdown + MPPT flag → fault (regression vs old 0x0F mask)" },
        { 0x00, true,  false, "0x00 = Battery Disconnect (live read) → NO fault" },
        { 0x00, false, false, "stale data (ag105DataValid=false) → NO fault" },
        { 0x05, false, false, "stale error byte with ag105DataValid=false → NO fault (validity gate)" },
    };
    for (auto& c : cases) {
        reset_test_state();
        V_batt = 7.0f; V_bus = 16.0f; I_fc = 0; V_fc = 10.0f;
        ag105_status_raw = c.raw;
        ag105DataValid   = c.valid;
        mainState = 2;
        detectFaults();
        bool faulted = (fault_flags & FAULT_CHARGER_STAT) != 0;
        check(faulted == c.shouldFault, c.desc);
    }
}

// ─── UV faults gated to Run state (boot-lock fix) ─────────────────────────────
static void test_uv_boot_gate() {
    test_group("UV_FC / UV_BATT gated to Run (boot-lock)");

    // State 0 with un-ramped rails (V_fc = V_batt = 0) must NOT latch State 99.
    reset_test_state();
    V_fc = 0; V_batt = 0; V_bus = 16.0f; I_fc = 0;
    mainState = 0;
    detectFaults();
    check(!(fault_flags & FAULT_UV_FC),   "detectFaults: no UV_FC in State 0 (boot)");
    check(!(fault_flags & FAULT_UV_BATT), "detectFaults: no UV_BATT in State 0 (boot)");
    check(mainState == 0,                 "detectFaults: no boot-lock to State 99 in State 0");

    // State 1 (Idle) likewise exempt.
    reset_test_state();
    V_fc = 0; V_batt = 0; V_bus = 16.0f; I_fc = 0;
    mainState = 1;
    detectFaults();
    check(mainState == 1, "detectFaults: no UV boot-lock in State 1 (Idle)");

    // State 2 (Run): UV checks are armed.
    // FAULT_UV_FC (fw v6, 2026-08-12) is no longer a bare State-2-gated single-sample check --
    // it is ARMED (see the FAULT_UV_FC test family above), requiring the FC pair closed
    // (FC_BUS_ENABLE + FC_REG_ENABLE HIGH) AND V_fc having been OBSERVED healthy while routed,
    // before a collapse sets the transient bit. A bare "V_fc low in State 2" with the pair open
    // (this test's original setup) now never arms at all -- reproduce the arm-then-collapse
    // sequence explicitly instead.
    reset_test_state();
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = V_FC_ARM_THRESH + 1.0f; V_batt = 7.0f; V_bus = 16.0f; I_fc = 0;
    mainState = 2;
    g_mock_millis = 0;
    detectFaults();                          // arm: pair closed, V_fc observed healthy
    check(fcUvArmed, "detectFaults: (setup) FAULT_UV_FC arms once the FC pair is closed and V_fc is healthy");
    V_fc = LIMIT_V_FC_MIN - 0.1f;
    g_mock_millis = 1;
    detectFaults();
    check(fault_flags & FAULT_UV_FC, "detectFaults: UV_FC fires in State 2 (Run)");

    reset_test_state();
    V_fc = 10.0f; V_batt = LIMIT_V_BATT_MIN - 0.1f; V_bus = 16.0f; I_fc = 0;
    mainState = 2;
    detectFaults();
    check(fault_flags & FAULT_UV_BATT, "detectFaults: UV_BATT fires in State 2 (Run)");
}

// ─── pollAg105() I2C fault is state-gated ─────────────────────────────────────
static void test_pollag105_state_gate() {
    test_group("pollAg105() I2C fault gating");

    // Idle: a NAK must not latch State 99 (e.g. bench test, charger not powered).
    reset_test_state();
    Wire.fail_next_requestfrom = true;
    mainState = 1;
    pollAg105();
    check(!(fault_flags & FAULT_I2C_CHARGER), "pollAg105: no I2C fault in State 1 (Idle)");
    check(mainState == 1,                     "pollAg105: stays in Idle on I2C failure");

    // Run with a powered+settled charger: the fault still latches.
    reset_test_state();
    make_charger_powered_settled();
    Wire.fail_next_requestfrom = true;
    mainState = 2;
    pollAg105();
    check(fault_flags & FAULT_I2C_CHARGER, "pollAg105: I2C fault latches in State 2 (Run)");
    check(mainState == 99,                 "pollAg105: → State 99 on I2C failure in Run");
}

// ─── chargerHasPower() predicate ──────────────────────────────────────────────
static void test_charger_has_power() {
    test_group("chargerHasPower() predicate");

    reset_test_state();
    check(!chargerHasPower(), "chargerHasPower: false when all paths LOW");

    reset_test_state();
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    check(chargerHasPower(), "chargerHasPower: true when FC_CHARGE_ENABLE HIGH");

    reset_test_state();
    g_pin_value[REGEN_ENABLE] = HIGH;   // REGEN alone is not enough
    check(!chargerHasPower(), "chargerHasPower: false when only REGEN_ENABLE HIGH");

    reset_test_state();
    g_pin_value[MOT_PWR_ENABLE] = HIGH; // MOT_PWR alone is not enough
    check(!chargerHasPower(), "chargerHasPower: false when only MOT_PWR_ENABLE HIGH");

    reset_test_state();
    g_pin_value[REGEN_ENABLE]   = HIGH;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    check(chargerHasPower(), "chargerHasPower: true when REGEN_ENABLE + MOT_PWR_ENABLE HIGH");
}

// ─── pollAg105(): unpowered charger never faults ─────────────────────────────
static void test_pollag105_unpowered_never_faults() {
    test_group("pollAg105() unpowered → never faults");

    reset_test_state();
    // All power paths LOW → charger unpowered. Even in Run with a NAK, no fault.
    Wire.fail_next_requestfrom = true;
    mainState = 2;
    pollAg105();
    check(!(fault_flags & FAULT_I2C_CHARGER), "pollAg105: no fault when charger unpowered in Run");
    check(ag105_status_raw == 0,              "pollAg105: status cleared to 0 (stale) when unpowered");
    check(!ag105IsReady(),                    "pollAg105: not ready when unpowered");
    check(mainState == 2,                     "pollAg105: stays in Run when unpowered NAK");
}

// ─── pollAg105(): settle window suppresses the fault ─────────────────────────
static void test_pollag105_settle_window_suppresses_fault() {
    test_group("pollAg105() settle window");

    reset_test_state();
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;   // charger powered
    mainState = 2;

    // t = T0: power-on edge recorded; not yet settled → NAK must not fault.
    g_mock_millis = 1000;
    Wire.fail_next_requestfrom = true;
    pollAg105();
    check(!(fault_flags & FAULT_I2C_CHARGER), "pollAg105: no fault at power-on (settling)");
    check(mainState == 2,                     "pollAg105: stays in Run during settle");

    // t = T0 + SETTLE - 1: still within window → still no fault.
    g_mock_millis = 1000 + AG105_SETTLE_MS - 1;
    Wire.fail_next_requestfrom = true;
    pollAg105();
    check(!(fault_flags & FAULT_I2C_CHARGER), "pollAg105: no fault just before settle elapses");

    // t = T0 + SETTLE: window elapsed → NAK now faults.
    g_mock_millis = 1000 + AG105_SETTLE_MS;
    Wire.fail_next_requestfrom = true;
    pollAg105();
    check(fault_flags & FAULT_I2C_CHARGER, "pollAg105: fault fires once settle window elapses");
    check(mainState == 99,                 "pollAg105: → State 99 after settle");
}

// ─── pollAg105(): lazy config on first powered+settled contact ───────────────
static void test_lazy_config_on_power() {
    test_group("pollAg105() lazy config on power");

    reset_test_state();
    make_charger_powered_settled();
    mainState = 1;                    // Idle — config still runs (not gated on state)
    Wire.rx_queue.push(0x02);         // status byte (charging)
    Wire.rx_queue.push(50);           // current count
    pollAg105();
    check(ag105Configured, "pollAg105: ag105Configured true after powered+settled contact");
    check(Wire.write_log.size() == 2, "pollAg105: wrote the 2 config registers (lazy config)");

    // Second poll: already configured → must NOT re-write.
    Wire.rx_queue.push(0x02);
    Wire.rx_queue.push(50);
    pollAg105();
    check(Wire.write_log.size() == 2, "pollAg105: no re-write once configured (one-shot)");
}

// ─── pollAg105(): config flag resets on power loss, reconfigures on re-power ──
static void test_config_resets_on_power_loss() {
    test_group("pollAg105() config resets on power loss");

    reset_test_state();
    make_charger_powered_settled();
    mainState = 1;
    Wire.rx_queue.push(0x02);
    Wire.rx_queue.push(50);
    pollAg105();
    check(ag105Configured, "pollAg105: configured after first power session");

    // Drop charger power → config flag must re-arm.
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    pollAg105();
    check(!ag105Configured, "pollAg105: ag105Configured cleared when power lost");

    // Re-power + settle → re-runs the config path and re-arms ag105Configured.
    //
    // BUT it must NOT write the EPROM again: the registers already hold 0x01 / 0x08 from the first
    // session (the mock emulates the Ag105's EPROM), and initAg105Charger() now does
    // read-verify-then-write-ONLY-if-different. So the write count stays at 2 while the config is
    // still confirmed. This is the point of read-verify — it re-validates every power session
    // without burning an EPROM write cycle each time.
    make_charger_powered_settled();
    Wire.rx_queue.push(0x02);
    Wire.rx_queue.push(50);
    pollAg105();
    check(ag105Configured, "pollAg105: reconfigured after re-power");
    check(Wire.write_log.size() == 2,
          "pollAg105: re-power re-verifies but does NOT re-write matching EPROM values");

    // Now corrupt one register behind the firmware's back (as a real charger losing its EPROM
    // content, or a factory-fresh part, would look) and confirm the re-write happens.
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    pollAg105();                                  // drop power → re-arm
    Wire.reg_file[AG105_REG_VBATT_CFG] = 0x00;    // back to the 1S / 4.2V default
    make_charger_powered_settled();
    Wire.rx_queue.push(0x02);
    Wire.rx_queue.push(50);
    pollAg105();
    check(ag105Configured, "pollAg105: reconfigured after a register reverted");
    check(Wire.write_log.size() == 3,
          "pollAg105: read-verify re-writes ONLY the register that drifted");
    check(Wire.reg_file[AG105_REG_VBATT_CFG] == AG105_VAL_2S,
          "pollAg105: drifted register restored to 2S / 8.4V");
}

// ─── I_charge must not go stale (design review P2-1) ─────────────────────────
static void test_icharge_cleared_on_invalid() {
    test_group("I_charge staleness on charger loss / I2C failure");

    // Establish a good reading first.
    reset_test_state();
    make_charger_powered_settled();
    mainState = 2;
    Wire.rx_queue.push(0x02);      // GENSTAT = charging
    Wire.rx_queue.push(100);       // 100 counts x 0.011 = 1.1 A
    pollAg105();
    check(I_charge > 1.0f && ag105DataValid,
          "I_charge: good read populates a live charge current");

    // Charger power removed → I_charge must clear, not linger.
    // Turn the mock's register emulation off first: an unpowered Ag105 cannot ACK at all, and the
    // emulator would otherwise keep answering and re-validate the data on the same tick.
    Wire.emulate_regs             = false;
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    g_pin_value[REGEN_ENABLE]     = LOW;
    pollAg105();
    check(!ag105DataValid, "I_charge: data marked invalid when charger power is lost");
    check(I_charge == 0.0f,
          "I_charge: cleared on power loss (Pi never sees current next to status 0x00)");

    // I2C failure while powered → also clears.
    reset_test_state();
    make_charger_powered_settled();
    mainState = 1;                          // not fault-armed, so we test the clear in isolation
    Wire.rx_queue.push(0x02);
    Wire.rx_queue.push(100);
    pollAg105();
    check(I_charge > 1.0f, "I_charge: populated again before the failure case");
    Wire.emulate_regs          = false;     // stop the mock synthesizing a reply
    Wire.fail_next_requestfrom = true;
    pollAg105();
    check(ag105_status_raw == 0 && !ag105DataValid,
          "I_charge: status invalidated on read failure");
    check(I_charge == 0.0f, "I_charge: cleared on I2C read failure");
}

// ─── Ag105 read-verify-then-write-if-different ───────────────────────────────
// Previously initAg105Charger() wrote both config registers blind and returned success on the ACK
// alone. A write that ACKed but did not land left the charger at its 1S / 4.2V power-on default
// while the firmware believed it was configured — a real 2S pack would then be charged to a 1S
// target with no fault raised. (docs/VESC_MOTOR_INTEGRATION.md §11 asked for exactly this.)
static void test_ag105_config_read_verify() {
    test_group("Ag105 config read-verify");

    // Factory-default charger: both registers read 0x00, so both must be written.
    reset_test_state();
    check(initAg105Charger() == true, "read-verify: succeeds against a default charger");
    check(Wire.write_log.size() == 2, "read-verify: writes both registers when both differ");
    check(Wire.reg_file[AG105_REG_ICHG_CFG]  == AG105_VAL_2500MA,
          "read-verify: charge current register set to the 2.5 A profile");
    check(Wire.reg_file[AG105_REG_VBATT_CFG] == AG105_VAL_2S,
          "read-verify: battery voltage register set to 2S / 8.4 V");

    // Already-correct charger (EPROM persisted): verifies, writes nothing.
    reset_test_state();
    Wire.reg_file[AG105_REG_ICHG_CFG]  = AG105_VAL_2500MA;
    Wire.reg_file[AG105_REG_VBATT_CFG] = AG105_VAL_2S;
    check(initAg105Charger() == true, "read-verify: succeeds when already configured");
    check(Wire.write_log.empty(),
          "read-verify: NO EPROM write when both registers already match");

    // Only one register wrong → only that one is written.
    reset_test_state();
    Wire.reg_file[AG105_REG_ICHG_CFG]  = AG105_VAL_2500MA;
    Wire.reg_file[AG105_REG_VBATT_CFG] = 0x00;
    check(initAg105Charger() == true, "read-verify: succeeds with one register drifted");
    check(Wire.write_log.size() == 1, "read-verify: writes only the drifted register");
    check(Wire.write_log[0].reg == AG105_REG_VBATT_CFG,
          "read-verify: the register written is the drifted one");

    // A write that ACKs but does not land must be reported as FAILURE, not success.
    // This is the exact scenario the old blind write could not detect.
    reset_test_state();
    Wire.emulate_regs = false;                  // reads no longer reflect writes
    Wire.rx_queue.push(0x00); Wire.rx_queue.push(0x00);   // initial read of 0x00 → differs
    Wire.rx_queue.push(0x00); Wire.rx_queue.push(0x00);   // verify read → STILL 0x00
    check(initAg105Charger() == false,
          "read-verify: an ACKed write that does not take effect is reported as failure");

    // A read that cannot complete is also a failure (no silent success).
    reset_test_state();
    Wire.emulate_regs = false;
    Wire.fail_next_requestfrom = true;
    check(initAg105Charger() == false,
          "read-verify: a failed read-back is reported as failure");

    // A NAKed write is still a failure.
    reset_test_state();
    Wire.next_endtransmission_result = 2;       // NAK the register-pointer write
    check(initAg105Charger() == false,
          "read-verify: an I2C NAK is reported as failure");
}

// ─── chargingControl(): FC path bootstraps the charger ───────────────────────
static void test_charging_control_fc_bootstrap() {
    test_group("chargingControl() FC bootstrap");

    // Cruise, charge intent, charger NOT ready: FC_CHARGE must open to power the charger,
    // MPPT stays inhibited until ready.
    reset_test_state();
    charge_goal = 1.0f;
    current     = 0.5f;          // cruise
    ag105_status_raw = 0x00;     // not ready
    chargingControl();
    check(g_pin_value[FC_CHARGE_ENABLE] == HIGH,
          "chargingControl: FC_CHARGE_ENABLE HIGH to power charger (bootstrap)");
    check(g_pin_value[MPPT_DISABLE] == LOW,
          "chargingControl: MPPT inhibited until charger ready");

    // Once the charger reports ready (live read), MPPT releases (FC path stays open).
    ag105_status_raw = AG105_GENSTAT_CHARGING;
    ag105DataValid   = true;   // ag105IsReady() requires a live read, not just the GENSTAT byte
    chargingControl();
    check(g_pin_value[FC_CHARGE_ENABLE] == HIGH,
          "chargingControl: FC_CHARGE_ENABLE stays HIGH when ready");
    check(g_pin_value[MPPT_DISABLE] == HIGH,
          "chargingControl: MPPT released once charger ready");
}

// ─── doState98() drive cycle drives the real control functions ────────────────
static void test_state98_drive_cycle_runs_controls() {
    test_group("doState98() drive cycle exercises control functions");
    reset_test_state();

    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    driveCycleActive     = true;
    driveCyclePhaseIdx   = 1;       // ramp-up (non-zero v_setpoint)
    driveCyclePhaseStart = 0;
    g_mock_millis = 2000;           // mid ramp
    g_mock_micros = 100000;         // > sampleTime so PI updates
    vesc.reset();

    doState98();

    check(!vesc.current_calls.empty(),
          "doState98: motorControl() runs during drive cycle (vesc.setCurrent invoked)");

    // Stopping the cycle with 'D' must flush a zero current — otherwise the motor keeps
    // spinning at the last commanded value (the control block no longer runs once stopped) —
    // and must park all path switches safe.
    driveCycleActive = true;
    g_pin_value[REGEN_ENABLE]     = HIGH;
    g_pin_value[FC_BUS_ENABLE]    = HIGH;
    g_pin_value[BT_BUS_ENABLE]    = HIGH;
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    vesc.reset();
    Serial.rx_queue.push('D');
    doState98();
    check(driveCycleActive == false,
          "doState98: 'D' stops the drive cycle");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "doState98: 'D'-stop flushes vesc.setCurrent(0)");
    check(g_pin_value[REGEN_ENABLE]     == LOW &&
          g_pin_value[FC_BUS_ENABLE]    == LOW &&
          g_pin_value[BT_BUS_ENABLE]    == LOW &&
          g_pin_value[FC_CHARGE_ENABLE] == LOW &&
          g_pin_value[MOT_PWR_ENABLE]   == LOW,
          "doState98: 'D'-stop safes all path switches LOW");

    // 'Q' exit must also zero the VESC and force MOT_PWR_ENABLE LOW.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    vesc.reset();
    Serial.rx_queue.push('Q');
    doState98();
    check(vesc.last_current == 0.0f,
          "doState98: 'Q' exit flushes vesc.setCurrent(0)");
    check(g_pin_value[MOT_PWR_ENABLE] == LOW,
          "doState98: 'Q' exit forces MOT_PWR_ENABLE LOW");
    check(mainState == 1,
          "doState98: 'Q' exit returns to State 1");
}

// ─── Quadrature ISR pin-level helpers (used by both the unit-chain test below and the full
//     decode test further down) ─────────────────────────────────────────────────────────────
static void enc_set(int a, int b) {   // set both channel levels, fire the ISRs that changed
    int prevA = g_pin_value[ENC_A];
    int prevB = g_pin_value[ENC_B];
    g_pin_value[ENC_A] = a;
    g_pin_value[ENC_B] = b;
    if (a != prevA) doEncoderA();
    if (b != prevB) doEncoderB();
}

static void enc_reset() {
    reset_test_state();
    noInterrupts();
    encoderPos = 0;
    AfirstUp = BfirstUp = AfirstDown = BfirstDown = 0;
    encEdgeCountA = encEdgeCountB = 0;
    interrupts();
    g_pin_value[ENC_A] = 0;
    g_pin_value[ENC_B] = 0;
}

// ─── Velocity unit chain (rev/min → m/s) ─────────────────────────────────────
// The regression that matters: v_actual = rpm * flyWheelRadius / 60 yielded rev/s·inch, not m/s —
// it dropped BOTH the 2π (rad/rev) and the inch→m 0.0254. Derive the expectation from first
// principles here (v = ω·2π·r) rather than reusing RPM_TO_MPS, so the test is independent of the
// constant it is checking.
static void test_wheelspeed_units() {
    test_group("updateWheelSpeed() unit chain");

    // The conversion constant itself: (2π/60)·r, radius in METRES.
    const float expect_k = (6.28318530718f / 60.0f) * FLYWHEEL_RADIUS_M;
    check(fabsf(RPM_TO_MPS - expect_k) < 1e-9f,
          "units: RPM_TO_MPS == (2*pi/60) * FLYWHEEL_RADIUS_M");
    // Guard against a regression to the old inch-based placeholder: 1 inch would give 0.0254 m.
    check(FLYWHEEL_RADIUS_M > 0.0f && FLYWHEEL_RADIUS_M < 1.0f,
          "units: FLYWHEEL_RADIUS_M is a plausible radius in metres (not inches, not a placeholder 1)");
    check(fabsf(ENCODER_COUNTS_PER_REV - ENCODER_SLOTS_PER_REV * ENCODER_QUAD_DECODE) < 1e-6f,
          "units: ENCODER_COUNTS_PER_REV == slots x quadrature decode factor");
    check(fabsf(ENCODER_QUAD_DECODE - 2.0f) < 1e-6f,
          "units: quadrature decode factor is x2 (doEncoderA decrements / doEncoderB increments only)");
    // Both scale inputs are measured. Pin the exact values so a silent revert to the
    // pre-calibration placeholders (512 slots, 0.033 m) fails a test rather than only shifting the
    // first-principles derivation below.
    //
    // fw v8 (2026-08-16): 60 -> 120 slots, counted directly on the disc. fw v7's 60 came from
    // reading the 2026-08-13 bench figure of "120" as encoderPos COUNTS and dividing by the x2
    // decode; it was 120 SLOTS, and the decode multiplies. The 120-slot / 240-count pair and the
    // 60-slot / 120-count pair differ by exactly the decode factor, so a regression to fw v7's
    // value would still satisfy the "counts == slots x decode" identity above — that is why both
    // numbers are pinned literally here rather than only related to each other.
    check(fabsf(ENCODER_SLOTS_PER_REV - 120.0f) < 1e-6f,
          "units: ENCODER_SLOTS_PER_REV == 120 (slots counted on the disc, 2026-08-16)");
    check(fabsf(ENCODER_COUNTS_PER_REV - 240.0f) < 1e-6f,
          "units: ENCODER_COUNTS_PER_REV == 240 (120 slots x quadrature decode)");
    check(fabsf(FLYWHEEL_RADIUS_M - 0.0762f) < 1e-6f,
          "units: FLYWHEEL_RADIUS_M == 0.0762 m / 3.00 in (bench-measured 2026-08-13)");
    // fw v7 (2026-08-13, operator decision): MOTOR_I_CMD_MAX is the VESC-side phase-current
    // ceiling, doubled from 5.0 to 10.0 A. Bus current is bounded separately, in the VESC's own
    // Battery Current Max setting, so this constant only ever gates phase current. Pinned here so
    // a silent revert is caught, not just absorbed by the tests that use it symbolically.
    check(fabsf(MOTOR_I_CMD_MAX - 12.0f) < 1e-6f,
          "units: MOTOR_I_CMD_MAX == 12.0 A (VESC phase-current ceiling, 2026-08-15 operator decision)");

    // Drive the REAL decoder+estimator chain (fw v12 edge-period estimator) at a known constant
    // rate through the ISRs, rather than writing encoderPos directly — the old boxcar estimator
    // read encoderPos on a fixed cadence, so poking the counter was a valid stimulus for it, but
    // the edge-period estimator only latches a period from doEncoderA()'s A-rising tap, so a test
    // that never calls the ISR exercises nothing here (encPeriodCount would stay 0 and v_actual
    // would read 0 forever). One quadrature cycle (00->10->11->01->00) is +2 counts, i.e. one
    // ENC_SLOT_PITCH_M of travel; drive cycles at a fixed simulated period and derive the expected
    // speed from first principles (distance / time), independent of RPM_TO_MPS/ENC_SLOT_PITCH_M.
    reset_test_state();
    const uint32_t cycle_period_us = 800;   // simulated time per quadrature cycle
    encoderVelReset();
    g_mock_micros = 0;
    wheelSpeedResetPending = true;
    updateWheelSpeed();                     // consume the reset
    for (int i = 1; i <= 20; i++) {         // well past ENC_PERIOD_AVG_N warm-up
        g_mock_micros = (uint32_t)i * cycle_period_us;
        enc_set(1, 0); enc_set(1, 1); enc_set(0, 1); enc_set(0, 0);
        updateWheelSpeed();
    }
    const float slots_per_sec = 1e6f / (float)cycle_period_us;   // one slot pitch per cycle
    const float rev_per_sec   = slots_per_sec / ENCODER_SLOTS_PER_REV;
    const float expect_mps    = rev_per_sec * 6.28318530718f * FLYWHEEL_RADIUS_M;
    check(fabsf(v_actual - expect_mps) < fabsf(expect_mps) * 0.01f,
          "units: v_actual matches omega*2*pi*r for a known edge-period rate (within 1%)");
    // The old broken boxcar form would have produced rev/s x 1.0 — i.e. 2*pi*r times LARGER.
    // Assert we are not that value, so a revert is caught rather than silently passing above.
    check(fabsf(v_actual - rev_per_sec) > fabsf(expect_mps),
          "units: v_actual is NOT the old rev/s-times-inches value");

    // Direction: reverse quadrature (B leads A) must give an equal-magnitude negative speed.
    reset_test_state();
    encoderVelReset();
    g_mock_micros = 0;
    wheelSpeedResetPending = true;
    updateWheelSpeed();
    for (int i = 1; i <= 20; i++) {
        g_mock_micros = (uint32_t)i * cycle_period_us;
        enc_set(0, 1); enc_set(1, 1); enc_set(1, 0); enc_set(0, 0);
        updateWheelSpeed();
    }
    check(fabsf(v_actual + expect_mps) < fabsf(expect_mps) * 0.01f,
          "units: reverse rotation gives an equal-magnitude negative v_actual");
    enc_reset();
}

// ─── Quadrature ISR decode from raw pin levels ───────────────────────────────
// Everything above drives `encoderPos` DIRECTLY, so the whole decoder — the only code between the
// two optical channels and the velocity loop — had zero coverage. That is the gap that let a
// bench report of "encoder outputs a signal but v_actual stays 0.000" (2026-08-16) have no
// firmware-side answer: the x2 decoder only counts when BOTH channels transition in the right
// ORDER, so a dead channel and two beams that are not 90 degrees apart both produce a silent
// encoderPos == 0. These tests pin the working decode AND the three silent-zero failure modes, and
// assert the fw v8 per-channel edge counters still move in every one of them — that is exactly
// what makes the 'S' dump able to tell them apart. (enc_set()/enc_reset() are defined above, next
// to test_wheelspeed_units(), which needs them too.)
static void test_encoder_isr_decode() {
    test_group("quadrature ISR decode (raw pin levels)");

    // ── Pin assignment. Pinned literally because a stale pin map is precisely what produced the
    //    2026-08-16 bench report: the encoder was bodged onto pins 14/15 and the firmware kept
    //    reading 2/8, so no interrupt ever fired and every downstream check below still "passed"
    //    against a decoder that could not see the hardware. Nothing else in the suite would notice
    //    — the tests drive the ISRs through these same macros, so a wrong number is self-consistent
    //    everywhere. Authority is `references/Scale Car Teensy IO - IO.csv`; update both together.
    check(ENC_A == 14, "pins: ENC_A == 14 (bodged from 2 on 2026-08-16; IO CSV row updated)");
    check(ENC_B == 15, "pins: ENC_B == 15 (bodged from 8 on 2026-08-16; IO CSV row updated)");
    // ENC_ENABLE is GONE — the sensors are hardwired to power, so pin 7 must not be driven. A
    // re-added #define would not fail to compile anywhere; this is the only thing standing in the
    // way of someone reinstating a write to a pin that has no net.
    #ifdef ENC_ENABLE
    check(false, "pins: ENC_ENABLE must not exist (sensors hardwired to power; pin 7 undriven)");
    #else
    check(true,  "pins: ENC_ENABLE is absent (sensors hardwired to power; pin 7 undriven)");
    #endif
    // The encoder pins must not collide with anything else the firmware drives. A collision would
    // be silent: both macros would compile and both would read a real pin.
    const int assigned[] = {
        RX, TX, FC_REG_ENABLE, BT_REG_ENABLE, MPPT_DISABLE, CHARGER_STAT, CBAL_DISABLE,
        MOSI, MISO, SCK, SDA, SCL, FC_VOLTAGE, BT_VOLTAGE, BUS_VOLTAGE,
        FC_BUS_ENABLE, BT_BUS_ENABLE, MOT_PWR_ENABLE, REGEN_ENABLE, FC_CHARGE_ENABLE,
        BT_SEQUENCE_ENABLE, CS_MDAC_FC, CS_MDAC_BT, CHG_VOLTAGE, RGN_VOLTAGE,
        FC_CURRENT, BT_CURRENT,
    };
    bool enc_collision = false;
    for (int p : assigned) if (p == ENC_A || p == ENC_B) enc_collision = true;
    check(!enc_collision, "pins: ENC_A/ENC_B collide with no other assigned pin");
    check(ENC_A != ENC_B, "pins: ENC_A and ENC_B are distinct");

    // ── Forward: A leads B, 00 -> 10 -> 11 -> 01 -> 00. Exactly +2 per cycle (the x2 decode
    //    ENCODER_QUAD_DECODE asserts symbolically is verified against the ISRs here).
    enc_reset();
    for (int i = 0; i < 5; i++) { enc_set(1,0); enc_set(1,1); enc_set(0,1); enc_set(0,0); }
    check(encoderPos == 10,
          "encoder ISR: forward quadrature gives +2 counts per cycle (x2 decode)");
    check(encEdgeCountA == 10 && encEdgeCountB == 10,
          "encoder ISR: each channel logs 2 CHANGE edges per cycle");

    // ── Reverse: B leads A, 00 -> 01 -> 11 -> 10 -> 00. Equal magnitude, opposite sign.
    enc_reset();
    for (int i = 0; i < 5; i++) { enc_set(0,1); enc_set(1,1); enc_set(1,0); enc_set(0,0); }
    check(encoderPos == -10,
          "encoder ISR: reverse quadrature gives -2 counts per cycle");

    // ── FAILURE MODE 1: channel B dead (stuck LOW), A toggling.
    //    A live-looking scope trace on A, and no counts at all. The edge counters are the only
    //    thing that separates this from failure mode 3.
    enc_reset();
    for (int i = 0; i < 20; i++) { enc_set(1,0); enc_set(0,0); }
    check(encoderPos == 0,
          "encoder ISR: channel B stuck LOW yields ZERO counts (decoder needs both channels)");
    check(encEdgeCountA == 40 && encEdgeCountB == 0,
          "encoder ISR: stuck-B is diagnosable — edges A>0, edges B==0");

    // ── FAILURE MODE 2: channel A dead (stuck HIGH), B toggling. Mirror of the above.
    enc_reset();
    g_pin_value[ENC_A] = 1;
    for (int i = 0; i < 20; i++) { enc_set(1,1); enc_set(1,0); }
    check(encoderPos == 0,
          "encoder ISR: channel A stuck HIGH yields ZERO counts");
    check(encEdgeCountA == 0 && encEdgeCountB == 40,
          "encoder ISR: stuck-A is diagnosable — edges B>0, edges A==0");

    // ── FAILURE MODE 3: both channels live but IN PHASE (beams aligned, or a whole slot pitch
    //    apart instead of a quarter). Both edge counters climb, the "first" flags are never
    //    satisfied, and encoderPos never moves. Indistinguishable from a healthy stationary
    //    flywheel without the edge counters.
    enc_reset();
    for (int i = 0; i < 20; i++) { enc_set(1,1); enc_set(0,0); }
    check(encoderPos == 0,
          "encoder ISR: in-phase (non-quadrature) channels yield ZERO counts");
    check(encEdgeCountA == 40 && encEdgeCountB == 40,
          "encoder ISR: in-phase is diagnosable — BOTH edge counts climb while encoderPos stays 0");

    // ── End to end: ISR-driven counts must reach v_actual. Ties the decoder to the velocity
    //    chain, which no existing test did (they all wrote encoderPos by hand).
    enc_reset();
    g_mock_micros = 0;
    wheelSpeedResetPending = true;
    updateWheelSpeed();                       // consume the reset
    for (int i = 1; i <= 400; i++) {          // one quadrature cycle (+2 counts) per 200 us
        g_mock_micros = (uint32_t)i * 200;
        enc_set(1,0); enc_set(1,1); enc_set(0,1); enc_set(0,0);
        updateWheelSpeed();
    }
    // 2 counts / 200 us = 10000 counts/s, same rate as the unit-chain test above.
    const float enc_expect = (10000.0f / ENCODER_COUNTS_PER_REV) * 6.28318530718f * FLYWHEEL_RADIUS_M;
    check(fabsf(v_actual - enc_expect) < fabsf(enc_expect) * 0.01f,
          "encoder ISR: ISR-driven counts produce the expected v_actual (within 1%)");
    check(v_actual > 0.0f,
          "encoder ISR: a live quadrature signal never reads v_actual == 0");

    enc_reset();
}

// ─── Edge-period velocity estimator (fw v12) ─────────────────────────────────
// updateWheelSpeed() no longer differences a position/timestamp boxcar; it now averages the
// last ENC_PERIOD_AVG_N same-edge (A-rising) periods timestamped by doEncoderA()'s tap. These
// tests drive the ISRs from raw pin levels (enc_set()/enc_reset(), defined above) rather than
// poking encoderPos, exactly like test_encoder_isr_decode(), since the estimator reads
// encPeriodBuf/encPeriodCount/encPeriodDir — state the ISR tap owns, not encoderPos directly.
//
// One quadrature cycle (00->10->11->01->00) is exactly one A-rising edge and one slot pitch of
// travel (ENC_SLOT_PITCH_M), so "drive N cycles at period P" is the natural stimulus.
static void enc_cycle_fwd(uint32_t t_us) {   // one forward quadrature cycle, ending at t_us
    g_mock_micros = t_us; enc_set(1, 0);
    g_mock_micros = t_us; enc_set(1, 1);
    g_mock_micros = t_us; enc_set(0, 1);
    g_mock_micros = t_us; enc_set(0, 0);
}
static void enc_cycle_rev(uint32_t t_us) {   // one reverse quadrature cycle, ending at t_us
    g_mock_micros = t_us; enc_set(0, 1);
    g_mock_micros = t_us; enc_set(1, 1);
    g_mock_micros = t_us; enc_set(1, 0);
    g_mock_micros = t_us; enc_set(0, 0);
}

static void test_edge_period_estimator() {
    test_group("Edge-period velocity estimator (fw v12)");

    // (a) Forward, constant period P: after >= N+1 cycles, v_actual == 2*pitch / (period[k-1]+period[k])
    //     i.e. N*pitch / sum(last N periods) at N=2 with equal periods -> pitch/period.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    const uint32_t P = 1000;   // us per cycle -> 3.990mm/1ms = 3.99 m/s, well under the glitch floor
    for (int i = 1; i <= 6; i++) {
        enc_cycle_fwd((uint32_t)i * P);
        updateWheelSpeed();
    }
    float expect_fwd = (2.0f * ENC_SLOT_PITCH_M) / (2.0f * (float)P * 1e-6f);
    check(fabsf(v_actual - expect_fwd) < fabsf(expect_fwd) * 1e-4f,
          "(a) forward constant speed: v_actual == 2*pitch/(sum of 2 periods), positive sign");
    check(v_actual > 0.0f, "(a) forward: sign is positive");

    // (b) Reverse, same period: equal magnitude, negative sign.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    for (int i = 1; i <= 6; i++) {
        enc_cycle_rev((uint32_t)i * P);
        updateWheelSpeed();
    }
    check(fabsf(v_actual + expect_fwd) < fabsf(expect_fwd) * 1e-4f,
          "(b) reverse constant speed: equal-magnitude negative v_actual");

    // (c) N=2 averaging uses the SUM of the last two periods, not the last one alone and not the
    //     mean of the two instantaneous speeds. Drive two different periods P1 != P2 back to back
    //     from a fresh ring and check against distM/(P1+P2), which differs from both 2*pitch/P2
    //     (last-only) and the harmonic-mean-style average of instantaneous speeds.
    //     NOTE: the FIRST A-rising after a reset only establishes the timing baseline — no period
    //     is measured yet (doEncoderA() needs two edges to compute one interval) — so it takes
    //     THREE cycles (baseline, then two periods) to fill an N=2 ring, not two.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    const uint32_t P1 = 1200, P2 = 600;
    uint32_t t = 0; enc_cycle_fwd(t); updateWheelSpeed();          // baseline edge — no period yet
    check(v_actual == 0.0f, "(c) baseline: the first A-rising after a reset measures no period yet");
    t += P1;        enc_cycle_fwd(t); updateWheelSpeed();          // period 1 = P1 -> cnt=1
    check(v_actual == 0.0f, "(c) warm-up: after only 1 period the ring is not yet full (N=2)");
    t += P2;        enc_cycle_fwd(t); updateWheelSpeed();          // period 2 = P2 -> cnt=2, ring full
    float distM = 2.0f * ENC_SLOT_PITCH_M;
    float expect_sum = distM / ((float)(P1 + P2) * 1e-6f);
    float last_only  = distM / ((float)P2 * 1e-6f);        // wrong: last period doubled
    check(fabsf(v_actual - expect_sum) < fabsf(expect_sum) * 1e-4f,
          "(c) N=2 averaging: v uses the SUM of the last two (different) periods");
    check(fabsf(v_actual - last_only) > fabsf(expect_sum) * 0.05f,
          "(c) N=2 averaging: v is NOT simply 2*pitch/last_period");

    // (d) Warm-up: fewer than N periods ingested -> v_actual == 0. (Covered inline in (c) above;
    //     also check immediately after reset with zero edges.)
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    check(v_actual == 0.0f, "(d) warm-up: v_actual == 0 with zero periods ingested");

    // (e) Glitch rejection: an edge < ENC_PERIOD_MIN_US after the previous one is dropped WITHOUT
    //     advancing the period base, so the next genuine edge still measures a full pitch from the
    //     last genuine edge (not from the glitch). Needs baseline + 1 genuine period first so the
    //     ring is one short of full (cnt=1) when the glitch/next-genuine pair is exercised.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    t = 0; enc_cycle_fwd(t); updateWheelSpeed();          // baseline
    t += P; enc_cycle_fwd(t); updateWheelSpeed();         // genuine period 1 (cnt=1, still warming)
    check(v_actual == 0.0f, "(e) pre-glitch: ring one short of full (cnt=1)");
    uint32_t t_glitch = t + (ENC_PERIOD_MIN_US / 2);      // well inside the glitch floor
    enc_cycle_fwd(t_glitch); updateWheelSpeed();          // glitch — must be dropped
    check(v_actual == 0.0f, "(e) glitch: still warming up (glitch did not count as a period)");
    uint32_t t_next = t + P;                              // genuine edge, a full pitch after the LAST GENUINE edge
    enc_cycle_fwd(t_next); updateWheelSpeed();            // genuine period 2 (cnt=2, ring full)
    check(fabsf(v_actual - expect_fwd) < fabsf(expect_fwd) * 1e-4f,
          "(e) glitch: the next genuine reading is correct (base did not advance to the glitch)");

    // (f) Direction flip mid-ring. The quadrature decode only completes a cycle's full +-2 delta
    //     AFTER that cycle's own A-rising tap (the far edge of the same cycle fires later), so the
    //     tap-to-tap delta that straddles a genuine direction reversal reads +-1 (ambiguous — a
    //     partial step each way), not +-2; the firmware correctly does not treat single-count
    //     ambiguity as a flip. The ring only invalidates once TWO consecutive same-new-direction
    //     taps produce a clean -2, i.e. the SECOND reverse tap after a forward run.
    //     HOLD SEMANTICS (updated): the ring re-accumulating (cnt < N or dir == 0) no longer zeros
    //     v_actual — it HOLDS the last valid reading (encVelLastValid) until either N fresh periods
    //     land or the staleness timeout fires. A zero here would be a full-scale error step into
    //     the 545 A/(m/s) drive controller for what is, physically, still-live motion.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    for (int i = 1; i <= 4; i++) { enc_cycle_fwd((uint32_t)i * P); updateWheelSpeed(); }
    check(v_actual > 0.0f, "(f) pre-flip: forward ring is live and positive");
    float preFlipReading = v_actual;
    uint32_t tf = 4 * P;
    tf += P; enc_cycle_rev(tf); updateWheelSpeed();       // rev tap #1: ambiguous dpos, no flip yet
    check(v_actual > 0.0f,
          "(f) first reverse tap after a forward run is direction-ambiguous and does not flip the ring yet");
    tf += P; enc_cycle_rev(tf); updateWheelSpeed();       // rev tap #2: clean -2, flips, ring -> cnt=1
    check(fabsf(v_actual - preFlipReading) < 1e-6f,
          "(f) direction flip: the second reverse tap invalidates the ring but HOLDS the last valid "
          "(pre-flip, positive) reading rather than zeroing");
    tf += P; enc_cycle_rev(tf); updateWheelSpeed();       // rev tap #3: clean -2, ring refills to cnt=2
    check(v_actual < 0.0f, "(f) direction flip: after N fresh reverse periods, v_actual is negative again");
    check(fabsf(v_actual + expect_fwd) < fabsf(expect_fwd) * 1e-4f,
          "(f) direction flip: the recovered reverse reading matches the steady-state formula");

    // (f2) The invalidation-hold is BOUNDED by the same staleness timeout as everything else: if a
    //      hold never gets its N fresh periods (e.g. the wheel genuinely stops mid-flip), the ring
    //      does not hold the pre-flip reading forever — advancing mock time past
    //      max(1.5*lastPeriod, ENC_VEL_TIMEOUT_US) with no further edges must zero v_actual and
    //      reset the ring, exactly like the steady-state stale case in (g) below.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    for (int i = 1; i <= 4; i++) { enc_cycle_fwd((uint32_t)i * P); updateWheelSpeed(); }
    float f2PreFlip = v_actual;
    check(f2PreFlip > 0.0f, "(f2) pre-flip: forward ring is live and positive");
    uint32_t tf2 = 4 * P;
    tf2 += P; enc_cycle_rev(tf2); updateWheelSpeed();     // ambiguous tap, no flip yet
    tf2 += P; enc_cycle_rev(tf2); updateWheelSpeed();     // flips + invalidates -> HELD at f2PreFlip
    check(fabsf(v_actual - f2PreFlip) < 1e-6f, "(f2) mid-hold: v_actual is holding the pre-flip reading");
    // No further edges: advance past the stale bound (last period was P = 1000us, so the absolute
    // ENC_VEL_TIMEOUT_US floor governs, same as (g)).
    g_mock_micros = tf2 + ENC_VEL_TIMEOUT_US + 1;
    updateWheelSpeed();
    check(v_actual == 0.0f, "(f2) hold bounded by staleness: v_actual zeros once the timeout elapses");
    check(encPeriodCount == 0, "(f2) hold bounded by staleness: the ring resets (encPeriodCount == 0)");

    // (f3) Three-and-only-three zeroing events: boot, encoderVelReset(), and the stale timeout.
    //      Ring re-accumulation (covered above in (f)/(f2)) deliberately does NOT zero — it holds.
    // -- boot: before any edge has ever been seen, v_actual reads 0.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    check(v_actual == 0.0f, "(f3) boot: v_actual == 0 before any A-rising edge has ever been seen");
    // -- encoderVelReset(): called directly against a LIVE reading, must zero it (this is the one
    //    path documented to discard a valid reading, distinct from a mere ring re-accumulation).
    for (int i = 1; i <= 4; i++) { enc_cycle_fwd((uint32_t)i * P); updateWheelSpeed(); }
    check(v_actual > 0.0f, "(f3) encoderVelReset() setup: a live reading exists");
    encoderVelReset();
    updateWheelSpeed();
    check(v_actual == 0.0f, "(f3) encoderVelReset(): zeros a live reading");
    // -- stale timeout: re-establish a live reading, then let it go stale with no further edges.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    for (int i = 1; i <= 4; i++) { enc_cycle_fwd((uint32_t)i * P); updateWheelSpeed(); }
    check(v_actual > 0.0f, "(f3) stale-timeout setup: a live reading exists");
    g_mock_micros = 4 * P + ENC_VEL_TIMEOUT_US + 1;
    updateWheelSpeed();
    check(v_actual == 0.0f, "(f3) stale timeout: zeros a live reading");

    // (g) Stale timeout: advance mock time past max(1.5*lastPeriod, ENC_VEL_TIMEOUT_US) with no
    //     further edges -> v_actual == 0 and the ring restarts (next reading needs N fresh periods).
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    for (int i = 1; i <= 4; i++) { enc_cycle_fwd((uint32_t)i * P); updateWheelSpeed(); }
    check(v_actual > 0.0f, "(g) pre-timeout: ring is live");
    uint32_t lastEdge = 4 * P;
    // last period was P (1000us); 1.5*P = 1500us < ENC_VEL_TIMEOUT_US (150000us), so the absolute
    // floor governs here. Advance just past it.
    g_mock_micros = lastEdge + ENC_VEL_TIMEOUT_US + 1;
    updateWheelSpeed();
    check(v_actual == 0.0f, "(g) stale timeout: v_actual == 0 once the timeout elapses with no edges");
    check(encPeriodCount == 0, "(g) stale timeout: the ring restarts (encPeriodCount == 0)");
    // Ring needs N fresh periods again post-timeout (baseline tap first, then N periods).
    uint32_t t2 = g_mock_micros;
    enc_cycle_fwd(t2); updateWheelSpeed();                // baseline — no period yet
    t2 += P; enc_cycle_fwd(t2); updateWheelSpeed();        // period 1 -> cnt=1
    check(v_actual == 0.0f, "(g) post-timeout: still warming up after only 1 fresh period");
    t2 += P; enc_cycle_fwd(t2); updateWheelSpeed();        // period 2 -> cnt=2, ring full
    check(fabsf(v_actual - expect_fwd) < fabsf(expect_fwd) * 1e-4f,
          "(g) post-timeout: after N fresh periods the reading is correct again");

    // (h) Zero-speed floor arithmetic: ENC_VEL_TIMEOUT_US (150 ms) is the absolute stale-timeout
    //     floor, so the slowest speed the estimator can report before declaring standstill is
    //     pitch / (150 ms) -- verify the documented ~0.0266 m/s figure directly from the constants.
    float floor_mps = ENC_SLOT_PITCH_M / (ENC_VEL_TIMEOUT_US * 1e-6f);
    check(fabsf(floor_mps - 0.0266f) < 0.001f,
          "(h) zero-speed floor: pitch / ENC_VEL_TIMEOUT_US matches the documented ~0.0266 m/s figure");

    // (i) encoderVelReset() clears everything: after a live ring, calling it directly must zero
    //     v_actual (once updateWheelSpeed() next runs) and require N fresh periods again.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    for (int i = 1; i <= 4; i++) { enc_cycle_fwd((uint32_t)i * P); updateWheelSpeed(); }
    check(v_actual > 0.0f, "(i) pre-reset: ring is live");
    encoderVelReset();
    check(encPeriodCount == 0 && encHaveLastEdge == false,
          "(i) encoderVelReset(): clears the ring and the edge-have flag directly");
    updateWheelSpeed();
    check(v_actual == 0.0f, "(i) encoderVelReset(): v_actual reads 0 immediately after");
    uint32_t t3 = g_mock_micros;
    enc_cycle_fwd(t3); updateWheelSpeed();                 // baseline — no period yet
    t3 += P; enc_cycle_fwd(t3); updateWheelSpeed();         // period 1 -> cnt=1
    check(v_actual == 0.0f, "(i) encoderVelReset(): still warming up 1 period after the reset");
    t3 += P; enc_cycle_fwd(t3); updateWheelSpeed();         // period 2 -> cnt=2, ring full
    check(fabsf(v_actual - expect_fwd) < fabsf(expect_fwd) * 1e-4f,
          "(i) encoderVelReset(): a fresh N-period ring reads correctly again");

    // (j) Quadrature decode cross-check: encoderPos still advances +-2 per cycle underneath the
    //     new estimator (the estimator's direction comes FROM this delta, per doEncoderA()).
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    int32_t posBefore = encoderPos;
    enc_cycle_fwd(P);
    check(encoderPos == posBefore + 2, "(j) quadrature decode: encoderPos still advances +2 per forward cycle");

    // (k) End-to-end: ISR-driven edges -> updateWheelSpeed() -> nonzero v_actual -> motorControl()
    //     commands a nonzero current. Extends the fw v8 end-to-end check (which stopped at
    //     v_actual) through to the motor command, using the new estimator's own timing.
    enc_reset();
    g_mock_micros = 0;
    encoderVelReset();
    updateWheelSpeed();
    for (int i = 1; i <= 6; i++) { enc_cycle_fwd((uint32_t)i * P); updateWheelSpeed(); }
    check(v_actual > 0.0f, "(k) end-to-end: v_actual is nonzero going into motorControl()");
    velocityChainCalibratedFlag = true;
    setManualMotorVelocity(0.0f);      // command standstill against a nonzero v_actual -> braking current
    vesc.reset();
    g_mock_micros += MOTOR_CTRL_PERIOD_US + 1;   // clear the rl_motor_last rate gate
    applyManualMotor();                          // sets v_setpoint and runs motorControlGated()
    check(!vesc.current_calls.empty(),
          "(k) end-to-end: motorControl() issued a VESC current command from the estimator's v_actual");

    enc_reset();
}

// ─── Velocity-chain calibration interlock ────────────────────────────────────
// Before fw v7, the two scale constants were placeholders, so v_actual under-read and the
// velocity PI OVER-DROVE; commandMotorCurrent() bounds amps, not speed, so the velocity entry
// points refused outright rather than rely on the current clamp. fw v7 (2026-08-13) bench-measured
// both scale inputs (FLYWHEEL_RADIUS_M = 0.0762 m; ENCODER_SLOTS_PER_REV corrected to 120 by a
// direct slot count in fw v8), so the shipped
// default flips to CALIBRATED — this is a deliberate retirement of the safety default now that the
// scale is known, not a regression. The interlock machinery itself (flag, refusal paths, override)
// is unchanged and stays covered below via the runtime flag.
static void test_velocity_chain_interlock() {
    test_group("Velocity-chain calibration interlock");

    // The SHIPPED default is now calibrated — both scale inputs were bench-measured (fw v7).
    check(VELOCITY_CHAIN_CALIBRATED == 1,
          "interlock: firmware ships with VELOCITY_CHAIN_CALIBRATED = 1 (bench-measured, fw v7)");

    // Uncalibrated: manual velocity mode refuses and leaves the motor untouched.
    reset_test_state();
    velocityChainCalibratedFlag = false;
    check(velocityChainCalibrated() == false, "interlock: flag reported as uncalibrated");
    vesc.reset();
    setManualMotorVelocity(3.0f);
    check(manualMotorMode == MOTOR_TEST_OFF,
          "interlock: uncalibrated setManualMotorVelocity does NOT enter velocity mode");
    check(manualMotorVelocity == 0.0f,
          "interlock: uncalibrated setManualMotorVelocity stores no setpoint");
    check(vesc.current_calls.empty(),
          "interlock: uncalibrated setManualMotorVelocity commands no current");

    // Uncalibrated: 'D' refuses to start the drive cycle.
    reset_test_state();
    velocityChainCalibratedFlag = false;
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;    // the OTHER precondition is satisfied
    g_mock_millis = 1000;
    Serial.rx_queue.push('D');
    doState98();
    check(driveCycleActive == false,
          "interlock: uncalibrated 'D' refuses to start the drive cycle");

    // Calibrated: both paths work again (proves the interlock is the only thing blocking them).
    reset_test_state();                    // resets the flag to true
    setManualMotorVelocity(3.0f);
    check(manualMotorMode == MOTOR_TEST_VELOCITY,
          "interlock: calibrated setManualMotorVelocity enters velocity mode");

    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 1000;
    Serial.rx_queue.push('D');
    doState98();
    check(driveCycleActive == true,
          "interlock: calibrated 'D' starts the drive cycle");

    // Fixed-current mode is NOT gated — it does not close the velocity loop.
    reset_test_state();
    velocityChainCalibratedFlag = false;
    setManualMotorCurrent(2.0f);
    check(manualMotorMode == MOTOR_TEST_CURRENT,
          "interlock: fixed-current mode stays available while uncalibrated");

    // fw v7 end-to-end (review C1): reset_test_state() (line ~84) unconditionally forces
    // velocityChainCalibratedFlag = true for the convenience of the rest of the suite, so on its
    // own it cannot distinguish "the shipped macro is 1" from "the fixture always wins" — a
    // regression of VELOCITY_CHAIN_CALIBRATED back to 0 would NOT be caught by a check that only
    // ever runs after reset_test_state(). This differs from the direct macro check at the top of
    // this test (which reads VELOCITY_CHAIN_CALIBRATED as a compile-time constant, so it always
    // reflects the shipped value but proves nothing about runtime behavior). To make an
    // end-to-end claim honestly, re-seed the runtime flag FROM the macro right here, overriding
    // the fixture default, so these two checks fail if the macro ever regresses to 0.
    reset_test_state();
    velocityChainCalibratedFlag = (VELOCITY_CHAIN_CALIBRATED != 0);
    setManualMotorVelocity(3.0f);
    check(manualMotorMode == MOTOR_TEST_VELOCITY,
          "interlock: fw v7 default — with the flag re-seeded FROM VELOCITY_CHAIN_CALIBRATED "
          "(not the fixture's forced-true), the velocity path is still live");

    reset_test_state();
    velocityChainCalibratedFlag = (VELOCITY_CHAIN_CALIBRATED != 0);
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 1000;
    Serial.rx_queue.push('D');
    doState98();
    check(driveCycleActive == true,
          "interlock: fw v7 default — with the flag re-seeded FROM VELOCITY_CHAIN_CALIBRATED, "
          "'D' still starts the drive cycle");
}

// ─── Independent control-loop rate limiting ──────────────────────────────────
// motorControl() ends in a 9-byte UART frame (781 us of wire time at 115200); calling it every tick
// blocks the main loop — including detectFaults() — on TX backpressure. Each controller now has its
// own period so the three cadences can be tuned separately.
static void test_control_rate_limiting() {
    test_group("Control-loop rate limiting");

    check(MOTOR_CTRL_PERIOD_US >= 800u,
          "rate limit: motor period clears the ~781 us UART frame floor");
    check(CHARGING_CTRL_PERIOD_US > MOTOR_CTRL_PERIOD_US,
          "rate limit: charging runs slower than the motor loop (Ag105 is the slow harvester)");

    // A gated call runs once, then is suppressed until its period elapses.
    reset_test_state();
    v_setpoint = 1.0f; v_actual = 0.0f;
    g_mock_micros = 1000000;
    resetControlRateLimiters();
    vesc.reset();
    motorControlGated();
    check(vesc.current_calls.size() == 1, "rate limit: first gated motor call runs");

    motorControlGated();                     // same timestamp — must be suppressed
    check(vesc.current_calls.size() == 1, "rate limit: immediate second motor call suppressed");

    g_mock_micros += MOTOR_CTRL_PERIOD_US - 1;
    motorControlGated();
    check(vesc.current_calls.size() == 1, "rate limit: motor call still suppressed just under period");

    g_mock_micros += 2;                      // now past the period
    motorControlGated();
    check(vesc.current_calls.size() == 2, "rate limit: motor call runs again after its period");

    // Independence: advancing past only the power-balance period must not release the motor gate.
    reset_test_state();
    I_fc = 1.0f; I_batt = 1.0f;              // non-zero so powerBalance() does real work
    v_setpoint = 1.0f; v_actual = 0.0f;
    g_mock_micros = 2000000;
    resetControlRateLimiters();
    vesc.reset(); SPI.reset();
    motorControlGated();                     // consume the motor gate
    powerBalanceGated();                     // consume the power gate
    const size_t motor_calls_before = vesc.current_calls.size();
    const size_t spi_before         = SPI.transfer_log.size();

    g_mock_micros += POWER_BAL_PERIOD_US;    // < MOTOR_CTRL_PERIOD_US
    powerBalanceGated();
    motorControlGated();
    check(SPI.transfer_log.size() > spi_before,
          "rate limit: powerBalance runs again on its own (shorter) period");
    check(vesc.current_calls.size() == motor_calls_before,
          "rate limit: motor gate independent — still suppressed at the power-balance period");

    // resetControlRateLimiters() opens all three gates at once.
    reset_test_state();
    v_setpoint = 1.0f; v_actual = 0.0f;
    g_mock_micros = 3000000;
    resetControlRateLimiters();
    vesc.reset();
    motorControlGated();
    check(vesc.current_calls.size() == 1, "rate limit: reset opens the motor gate immediately");

    // State-98 manual CURRENT mode shares the motor gate: re-sending a constant current every tick
    // is pure UART backpressure. It must still send often enough to beat the VESC's 1000 ms timeout.
    reset_test_state();
    setManualMotorCurrent(3.0f);
    g_mock_micros = 4000000;
    resetControlRateLimiters();
    vesc.reset();
    applyManualMotor();
    check(vesc.current_calls.size() == 1, "rate limit: manual current sends on an open gate");
    applyManualMotor();
    check(vesc.current_calls.size() == 1, "rate limit: manual current suppressed within its period");
    g_mock_micros += MOTOR_CTRL_PERIOD_US + 1;
    applyManualMotor();
    check(vesc.current_calls.size() == 2 && fabsf(vesc.last_current - 3.0f) < 1e-4f,
          "rate limit: manual current re-sent after its period, same value");
    check(MOTOR_CTRL_PERIOD_US < 1000000u,
          "rate limit: motor period is well inside the VESC 1000 ms command timeout");

    // Idle's zero-current keep-alive is gated for the same reason — doState1() runs continuously.
    reset_test_state();
    mainState = 1;
    g_mock_micros = 5000000;
    g_mock_millis = 5000;
    resetControlRateLimiters();
    vesc.reset();
    doState1();
    const size_t idle_first = vesc.current_calls.size();
    check(idle_first == 1 && vesc.last_current == 0.0f,
          "rate limit: Idle flushes zero on an open gate");
    doState1();
    check(vesc.current_calls.size() == idle_first,
          "rate limit: Idle keep-alive suppressed within its period");
    g_mock_micros += MOTOR_CTRL_PERIOD_US + 1;
    doState1();
    check(vesc.current_calls.size() == idle_first + 1 && vesc.last_current == 0.0f,
          "rate limit: Idle keep-alive re-sent after its period, still zero");
}

// ─── Drive-cycle motor-output ownership (design review P0-2) ─────────────────
// The drive cycle is one of four State-98 motor drivers. Every path INTO and OUT OF it must leave
// exactly one owner of the VESC command. The original failure: set a manual current with 'A', start
// 'D', then stop 'D' — the stop flushed a zero but left manualMotorMode set, so the standalone
// branch reached later in the SAME doState98() invocation reissued the old manual current.
static void test_drive_cycle_motor_ownership() {
    test_group("Drive-cycle motor-output ownership");

    // ── Starting a drive cycle takes exclusive ownership ──
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(8.0f);            // stale manual command set before the run
    check(manualMotorMode == MOTOR_TEST_CURRENT, "ownership: precondition — manual mode active");
    g_mock_millis = 1000;
    vesc.reset();
    Serial.rx_queue.push('D');
    doState98();
    check(driveCycleActive == true,
          "ownership: 'D' starts the drive cycle");
    check(manualMotorMode == MOTOR_TEST_OFF,
          "ownership: 'D' start clears a stale manualMotorMode");

    // ── Stopping mid-cycle must not reissue the stale manual command in the same tick ──
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    // Reconstruct the exact review scenario: manual current set, then a running drive cycle.
    manualMotorMode    = MOTOR_TEST_CURRENT;
    manualMotorCurrent = 8.0f;
    driveCycleActive     = true;
    driveCyclePhaseIdx   = 1;
    driveCyclePhaseStart = 0;
    g_mock_millis = 2000;
    g_mock_micros = 100000;
    vesc.reset();
    Serial.rx_queue.push('D');
    doState98();
    check(driveCycleActive == false, "ownership: 'D' stops the drive cycle");
    check(manualMotorMode == MOTOR_TEST_OFF,
          "ownership: 'D' stop clears manualMotorMode");
    // THE regression: the LAST value written to the VESC in this invocation must be 0, not 8.0.
    check(vesc.last_current == 0.0f,
          "ownership: 'D' stop does not reissue the stale manual current in the same tick");
    check(current == 0.0f, "ownership: 'D' stop clears `current`");
    check(pi_motor_accum == 0.0f,
          "ownership: 'D' stop clears the motor PI integrator (no carry-over to the next run)");

    // ── Natural completion must behave identically to the explicit stop ──
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    manualMotorMode    = MOTOR_TEST_CURRENT;
    manualMotorCurrent = 8.0f;
    driveCycleActive     = true;
    driveCyclePhaseIdx   = DRIVE_CYCLE_PHASES;   // past the last phase → completes on this tick
    driveCyclePhaseStart = 0;
    v_actual      = 3.0f;                        // flywheel still spinning down
    pi_motor_accum = 5.0f;                       // wound up from the regen-hold phase
    g_mock_millis = 5000;
    g_mock_micros = 100000;
    vesc.reset();
    doState98();
    check(driveCycleActive == false,
          "ownership: drive cycle self-clears on natural completion");
    check(manualMotorMode == MOTOR_TEST_OFF,
          "ownership: natural completion clears manualMotorMode");
    check(!vesc.current_calls.empty(),
          "ownership: natural completion flushes a command (previously flushed nothing at all)");
    // With v_actual = 3.0 still spinning, running motorControl() after completion would command
    // Kp*(0 − 3.0) = negative current, i.e. regen from a "finished" drive cycle.
    check(vesc.last_current == 0.0f,
          "ownership: natural completion leaves the VESC at 0 A (no regen re-command)");
    check(current == 0.0f && pi_motor_accum == 0.0f,
          "ownership: natural completion clears `current` and the PI integrator");

    // ── A subsequent tick must stay quiet (nothing re-owns the motor) ──
    vesc.reset();
    g_mock_millis = 5100;
    doState98();
    check(vesc.current_calls.empty() || vesc.last_current == 0.0f,
          "ownership: tick after completion issues no non-zero command");

    // ── haltMotorOutput() is the shared primitive: verify it in isolation ──
    reset_test_state();
    manualMotorMode     = MOTOR_TEST_VELOCITY;
    manualMotorVelocity = 4.0f;
    manualMotorCurrent  = 7.0f;
    v_setpoint          = 4.0f;
    targetMotorTorque   = 2.0f;
    pi_motor_accum      = 9.0f;
    current             = 7.0f;
    vesc.reset();
    haltMotorOutput();
    check(manualMotorMode == MOTOR_TEST_OFF && v_setpoint == 0.0f &&
          manualMotorCurrent == 0.0f && manualMotorVelocity == 0.0f &&
          targetMotorTorque == 0.0f && pi_motor_accum == 0.0f && current == 0.0f,
          "haltMotorOutput: clears every motor-output state variable");
    check(vesc.last_current == 0.0f,
          "haltMotorOutput: flushes vesc.setCurrent(0)");
    // It must NOT touch the power-path switches — that policy is the caller's decision.
    reset_test_state();
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_pin_value[FC_BUS_ENABLE]  = HIGH;
    haltMotorOutput();
    check(g_pin_value[MOT_PWR_ENABLE] == HIGH && g_pin_value[FC_BUS_ENABLE] == HIGH,
          "haltMotorOutput: leaves power-path switches untouched");
}

// ─── State 98 bench tools: VESC read-back ('E' one-shot / 'U' watch, was 'W') ─────────
static void test_state98_vesc_readback() {
    test_group("State 98 VESC read-back");

    // 'E' one-shot invokes both reads (FW version + values).
    reset_test_state();
    mainState = 98;
    vescWatchActive = false;
    vesc.reset();
    Serial.rx_queue.push('E');
    doState98();
    check(vesc.getFW_calls == 1 && vesc.getValues_calls == 1,
          "'E': queries FW version and VESC values once each");

    // 'E' with both reads failing must not crash and still attempts both.
    reset_test_state();
    mainState = 98;
    vescWatchActive = false;
    vesc.reset();
    vesc.getFW_result     = false;
    vesc.getValues_result = false;
    Serial.rx_queue.push('E');
    doState98();
    check(vesc.getFW_calls == 1 && vesc.getValues_calls == 1,
          "'E': no-response path still issues both reads without crashing");

    // 'U' enables watch (REBOUND from 'W' on 2026-08-10 — 'W' is now the current profile).
    // Enabling does NOT poll immediately (0 < period).
    reset_test_state();
    mainState = 98;
    vescWatchActive = false;
    vesc.reset();
    g_mock_millis = 1000;
    Serial.rx_queue.push('U');
    doState98();
    check(vescWatchActive && vesc.getValues_calls == 0,
          "'U': enables watch, no poll on the enabling tick");

    // After the period elapses, a bare tick polls once.
    g_mock_millis = 1000 + VESC_WATCH_PERIOD_MS;
    doState98();
    check(vesc.getValues_calls == 1,
          "watch: polls getVescValues() once period elapsed");

    // A second 'U' stops further polling.
    Serial.rx_queue.push('U');
    doState98();                      // toggles off (does not poll while turning off)
    int calls_after_off = vesc.getValues_calls;
    g_mock_millis += 2 * VESC_WATCH_PERIOD_MS;
    doState98();
    check(!vescWatchActive && vesc.getValues_calls == calls_after_off,
          "'U' again: stops the watch, no further polls");

    // Watch period is respected: a sub-period tick does not poll.
    reset_test_state();
    mainState = 98;
    vescWatchActive = false;
    vesc.reset();
    g_mock_millis = 1000;
    Serial.rx_queue.push('U');
    doState98();                      // enable at t=1000
    g_mock_millis = 1000 + VESC_WATCH_PERIOD_MS - 1;   // just under period
    doState98();
    check(vesc.getValues_calls == 0,
          "watch: does not poll before the period elapses");

    // Fault-code transition is latched into lastVescFault.
    reset_test_state();
    mainState = 98;
    vescWatchActive = false;
    vesc.reset();
    g_mock_millis = 1000;
    Serial.rx_queue.push('U');
    doState98();                      // enable, lastVescFault reset to 0
    vesc.data.error = 16;             // seed a fault before the next poll
    g_mock_millis = 1000 + VESC_WATCH_PERIOD_MS;
    doState98();
    check(lastVescFault == 16,
          "watch: new fault code latched into lastVescFault");

    // 'Q' exit clears the watch so the blocking poll can't run outside State 98.
    reset_test_state();
    mainState = 98;
    vescWatchActive = true;           // pretend a watch was left running
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    vesc.reset();
    Serial.rx_queue.push('Q');
    doState98();
    check(!vescWatchActive && mainState == 1,
          "'Q': clears vescWatchActive on exit to State 1");

    // Watch is auto-suppressed while a DRIVE CYCLE runs so motorControl()/powerBalance() keep
    // production-identical timing (no ~100 ms getVescValues() stall), then resumes when it stops.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    vescWatchActive = true;
    lastVescWatchMs = 0;
    driveCycleActive     = true;
    driveCyclePhaseIdx   = 1;         // a valid (non-terminal) phase
    driveCyclePhaseStart = 0;
    driveCycleStatusLast = 0;
    g_mock_millis = 5 * VESC_WATCH_PERIOD_MS;   // well past the watch period
    g_mock_micros = 100000;
    vesc.reset();
    doState98();
    check(vesc.getValues_calls == 0,
          "watch: suppressed while a drive cycle is active (production timing preserved)");
    // Stop the cycle; the watch resumes on the next elapsed tick (elapsed > period → immediate).
    driveCycleActive = false;
    g_mock_millis += VESC_WATCH_PERIOD_MS;
    doState98();
    check(vesc.getValues_calls == 1,
          "watch: resumes once the drive cycle stops");

    // Same suppression during a POWER-SHARE / energy-management load PROFILE.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    vescWatchActive = true;
    lastVescWatchMs = 0;
    setManualMotorCurrent(2.0f);      // profile branch calls applyManualMotor()
    powerShareProfileActive     = true;
    powerShareProfilePhaseIdx   = 0;
    powerShareProfilePhaseStart = 0;
    powerShareProfileStatusLast = 0;
    g_mock_millis = 5 * VESC_WATCH_PERIOD_MS;
    g_mock_micros = 100000;
    vesc.reset();
    doState98();
    check(vesc.getValues_calls == 0,
          "watch: suppressed while a power-share profile is active");
    powerShareProfileActive = false;
    vescWatchActive = false;

    // vescFaultStr name table (spot checks across the range + out-of-range).
    check(strcmp(vescFaultStr(0),  "NONE") == 0,                         "vescFaultStr(0) = NONE");
    check(strcmp(vescFaultStr(4),  "ABS_OVER_CURRENT") == 0,             "vescFaultStr(4) = ABS_OVER_CURRENT");
    check(strcmp(vescFaultStr(11), "ENCODER_SPI") == 0,                  "vescFaultStr(11) = ENCODER_SPI");
    check(strcmp(vescFaultStr(16), "HIGH_OFFSET_CURRENT_SENSOR_2") == 0, "vescFaultStr(16) = HIGH_OFFSET_CURRENT_SENSOR_2");
    check(strcmp(vescFaultStr(26), "ENCODER_MAGNET_TOO_STRONG") == 0,    "vescFaultStr(26) = ENCODER_MAGNET_TOO_STRONG");
    check(strcmp(vescFaultStr(99), "UNKNOWN") == 0,                      "vescFaultStr(99) = UNKNOWN");

    vescWatchActive = false;          // don't contaminate later tests
}

// ─── State 98 bench tools: manual motor (current mode) ───────────────────────
static void test_manual_motor_current() {
    test_group("State 98 manual motor — fixed current");
    reset_test_state();

    setManualMotorCurrent(5.0f);
    check(manualMotorMode == MOTOR_TEST_CURRENT,
          "manual current: mode = CURRENT");
    check(fabsf(manualMotorCurrent - 5.0f) < 1e-4f,
          "manual current: value stored");

    // Clamp to the VESC current ceiling in both directions
    setManualMotorCurrent(100.0f);
    check(fabsf(manualMotorCurrent - MOTOR_I_CMD_MAX) < 1e-4f,
          "manual current: clamped to +MOTOR_I_CMD_MAX");
    setManualMotorCurrent(-100.0f);
    check(fabsf(manualMotorCurrent + MOTOR_I_CMD_MAX) < 1e-4f,
          "manual current: clamped to -MOTOR_I_CMD_MAX");

    // applyManualMotor() drives `current` and the VESC directly (no velocity PI)
    setManualMotorCurrent(5.0f);
    vesc.reset();
    applyManualMotor();
    check(fabsf(current - 5.0f) < 1e-4f,
          "manual current: applyManualMotor sets current");
    check(!vesc.current_calls.empty() && fabsf(vesc.last_current - 5.0f) < 1e-4f,
          "manual current: applyManualMotor flushes vesc.setCurrent(5.0)");
}

// ─── State 98 bench tools: manual motor (velocity mode) ──────────────────────
static void test_manual_motor_velocity() {
    test_group("State 98 manual motor — fixed velocity");
    reset_test_state();

    setManualMotorVelocity(2.0f);
    check(manualMotorMode == MOTOR_TEST_VELOCITY,
          "manual velocity: mode = VELOCITY");
    check(fabsf(manualMotorVelocity - 2.0f) < 1e-4f,
          "manual velocity: value stored");

    // Clamp to the manual velocity ceiling in both directions
    setManualMotorVelocity(100.0f);
    check(fabsf(manualMotorVelocity - MANUAL_MOTOR_V_MAX) < 1e-4f,
          "manual velocity: clamped to +MANUAL_MOTOR_V_MAX");
    setManualMotorVelocity(-100.0f);
    check(fabsf(manualMotorVelocity + MANUAL_MOTOR_V_MAX) < 1e-4f,
          "manual velocity: clamped to -MANUAL_MOTOR_V_MAX");
    setManualMotorVelocity(2.0f);   // restore an in-range value for the apply check below

    // applyManualMotor() feeds v_setpoint and runs the existing motorControl() PI
    v_actual = 0.0f;
    pi_motor_accum = 0; pi_motor_lastMicros = 0;
    g_mock_micros = 100000;   // > sampleTime so the PI updates
    vesc.reset();
    applyManualMotor();
    check(fabsf(v_setpoint - 2.0f) < 1e-4f,
          "manual velocity: applyManualMotor feeds v_setpoint");
    check(!vesc.current_calls.empty(),
          "manual velocity: motorControl() ran (vesc.setCurrent invoked)");
    check(fabsf(current) > 0.0f,
          "manual velocity: non-zero current from velocity error");
}

// ─── Motor current chokepoint: commandMotorCurrent() ─────────────────────────
// Regression for the design-review P0: MOTOR_I_CMD_MAX previously bounded only the motor PI
// INTEGRATOR, so the proportional term rode straight through to a 50 A bridge. Every path must
// now be bounded, and non-finite must degrade to 0 A rather than serializing garbage over UART.
static void test_motor_current_clamp() {
    test_group("commandMotorCurrent() — final VESC command clamp");
    reset_test_state();

    // Positive / negative saturation
    vesc.reset();
    commandMotorCurrent(1000.0f);
    check(fabsf(vesc.last_current - MOTOR_I_CMD_MAX) < 1e-4f,
          "clamp: +1000 A → +MOTOR_I_CMD_MAX at the VESC");
    check(fabsf(current - MOTOR_I_CMD_MAX) < 1e-4f,
          "clamp: `current` mirrors the POST-clamp value, not the intent");

    commandMotorCurrent(-1000.0f);
    check(fabsf(vesc.last_current + MOTOR_I_CMD_MAX) < 1e-4f,
          "clamp: -1000 A → -MOTOR_I_CMD_MAX at the VESC");

    // In-range values pass through untouched
    commandMotorCurrent(3.25f);
    check(fabsf(vesc.last_current - 3.25f) < 1e-4f,
          "clamp: in-range command passes through unmodified");

    // Non-finite → 0 A (and `current` cleared, so telemetry never shows a NaN)
    commandMotorCurrent(NAN);
    check(vesc.last_current == 0.0f && current == 0.0f,
          "clamp: NaN → 0 A");
    commandMotorCurrent(3.0f);
    commandMotorCurrent(INFINITY);
    check(vesc.last_current == 0.0f && current == 0.0f,
          "clamp: +Inf → 0 A");
    commandMotorCurrent(3.0f);
    commandMotorCurrent(-INFINITY);
    check(vesc.last_current == 0.0f && current == 0.0f,
          "clamp: -Inf → 0 A");

    // motorControl(): the UDP velocity path. fw v10: motorControl() defaults to the Youla-H drive
    // controller (USE_YOULA_DRIVE_CONTROLLER), whose clamp lives INSIDE driveControllerStep() at
    // exactly DRIVE_CTRL_I_MAX == MOTOR_I_CMD_MAX (see test_drive_controller_coeff_pinning()), so
    // commandMotorCurrent()'s own clamp is a redundant backstop here rather than the binding
    // limit. A single tick at 5 m/s error does NOT saturate (u = DD*e ~= 9.1 A, DD ~= 1.81) --
    // unlike the old PI path's unbounded proportional term, this controller is designed to reach
    // the rail only under sustained error. Drive several ticks to reach saturation, then check it.
    reset_test_state();
    v_actual   = 0.0f;
    v_setpoint = 5.0f;
    g_mock_micros  = 100000;
    vesc.reset();
    for (int k = 0; k < 20; k++) {
        g_mock_micros += (uint32_t)DRIVE_CTRL_TS_US;
        motorControl();
    }
    check(!vesc.current_calls.empty() && fabsf(vesc.last_current) <= MOTOR_I_CMD_MAX + 1e-4f,
          "clamp: motorControl() at 5 m/s error stays within MOTOR_I_CMD_MAX");
    check(fabsf(vesc.last_current - MOTOR_I_CMD_MAX) < 1e-4f,
          "clamp: motorControl() saturates AT the ceiling under sustained 5 m/s error "
          "(Youla-H drive controller reaches the rail, same as the old PI's unbounded term did on tick 1)");

    // State-98 manual VELOCITY path shares motorControl(), so it inherits the clamp
    reset_test_state();
    setManualMotorVelocity(MANUAL_MOTOR_V_MAX);
    v_actual = -MANUAL_MOTOR_V_MAX;      // maximal error: 2 × the velocity ceiling
    pi_motor_accum = 0; pi_motor_lastMicros = 0;
    g_mock_micros  = 100000;
    vesc.reset();
    applyManualMotor();
    check(fabsf(vesc.last_current) <= MOTOR_I_CMD_MAX + 1e-4f,
          "clamp: State-98 manual velocity at maximal error stays within the ceiling");

    // Every zero-flush routes through the chokepoint too, so it clears `current`
    current = 12.0f;
    vesc.reset();
    commandMotorCurrent(0);
    check(current == 0.0f && vesc.last_current == 0.0f,
          "clamp: zero-flush clears `current` (no stale value left in telemetry)");
}

// ─── UDP setpoint sanitization ───────────────────────────────────────────────
// A bit-pattern that survives the XOR checksum can still decode as NaN/Inf. NaN entering the PI
// integrator poisons it permanently (NaN + x = NaN), so a rejected field must HOLD its prior value.
static void test_udp_setpoint_sanitize() {
    test_group("receiveCommands() setpoint sanitization");

    // Helper: build a valid packet with the three float fields set as given
    auto send = [](float v_sp, float ps, float cg, uint8_t mode) {
        uint8_t pkt[22] = {};
        pkt[0] = 0xBB;
        uint32_t ts = 1; memcpy(&pkt[1], &ts, 4);
        uint16_t cn = 1; memcpy(&pkt[5], &cn, 2);
        memcpy(&pkt[7],  &v_sp, 4);
        memcpy(&pkt[11], &ps,   4);
        memcpy(&pkt[15], &cg,   4);
        pkt[19] = mode;
        pkt[20] = 0;
        uint8_t cs = 0;
        for (int i = 1; i < 21; i++) cs ^= pkt[i];
        pkt[21] = cs;
        Udp.fake_packet_size = 22;
        memcpy(Udp.fake_packet, pkt, 22);
        receiveCommands();
    };

    // NaN velocity: held at the previous value, not zeroed and not propagated
    reset_test_state();
    mainState = 1;
    v_setpoint = 1.5f;
    send(NAN, 0.5f, 0.0f, 0);
    check(fabsf(v_setpoint - 1.5f) < 1e-4f,
          "sanitize: NaN v_setpoint rejected — previous value held");

    // Inf velocity: same treatment
    reset_test_state();
    mainState = 1;
    v_setpoint = 1.5f;
    send(INFINITY, 0.5f, 0.0f, 0);
    check(fabsf(v_setpoint - 1.5f) < 1e-4f,
          "sanitize: Inf v_setpoint rejected — previous value held");

    // Absurd but finite velocity: clamped to the sanity bound, not rejected
    reset_test_state();
    mainState = 1;
    send(1.0e6f, 0.5f, 0.0f, 0);
    check(fabsf(v_setpoint - V_SETPOINT_MAX) < 1e-3f,
          "sanitize: huge finite v_setpoint clamped to +V_SETPOINT_MAX");
    reset_test_state();
    mainState = 1;
    send(-1.0e6f, 0.5f, 0.0f, 0);
    check(fabsf(v_setpoint + V_SETPOINT_MAX) < 1e-3f,
          "sanitize: huge negative v_setpoint clamped to -V_SETPOINT_MAX");

    // power_share_setpoint is a ratio — out-of-range values clamp into [0, 1]
    reset_test_state();
    mainState = 1;
    send(1.0f, 5.0f, 0.0f, 0);
    check(fabsf(power_share_setpoint - 1.0f) < 1e-4f,
          "sanitize: power_share_setpoint > 1 clamped to 1.0");
    reset_test_state();
    mainState = 1;
    send(1.0f, -5.0f, 0.0f, 0);
    check(fabsf(power_share_setpoint) < 1e-4f,
          "sanitize: power_share_setpoint < 0 clamped to 0.0");

    // NaN share is rejected, holding the prior value
    reset_test_state();
    mainState = 1;
    power_share_setpoint = 0.4f;
    send(1.0f, NAN, 0.0f, 0);
    check(fabsf(power_share_setpoint - 0.4f) < 1e-4f,
          "sanitize: NaN power_share_setpoint rejected — previous value held");

    // A fully valid packet is still parsed unchanged (no regression on the happy path)
    reset_test_state();
    mainState = 1;
    send(2.5f, 0.4f, 1.0f, 0);
    check(fabsf(v_setpoint - 2.5f) < 1e-3f &&
          fabsf(power_share_setpoint - 0.4f) < 1e-3f &&
          fabsf(charge_goal - 1.0f) < 1e-3f,
          "sanitize: valid packet unaffected by the guards");
}

// ─── State 98 bench tools: open-loop droop write ─────────────────────────────
static void test_open_loop_droop() {
    test_group("State 98 open-loop droop (direct MDAC write)");
    reset_test_state();

    powerBalanceLive = true;     // must be cleared by an open-loop write
    SPI.reset();

    const float r = 0.30f;       // in-span ratio: both gains well inside [0, 1]
    applyOpenLoopDroop(r);

    float expFC = K_DROOP / (RE_MAX * r);
    float expBT = K_DROOP / (RE_MAX * (1.0f - r));
    check(fabsf(droop_gain_FC_actual - expFC) < 1e-3f,
          "open-loop droop: gFC matches K_DROOP/(RE_MAX*r)");
    check(fabsf(droop_gain_BT_actual - expBT) < 1e-3f,
          "open-loop droop: gBT matches K_DROOP/(RE_MAX*(1-r))");
    check(expFC <= 1.0f && expBT <= 1.0f,
          "open-loop droop: corrected mapping keeps both gains <= 1 (no MDAC clamp)");

    check(SPI.transfer_log.size() == 2,
          "open-loop droop: two MDAC words written (FC then BT)");
    if (SPI.transfer_log.size() == 2) {
        // Word = control nibble + code (ad5426_5432_5443.pdf Fig 49). The control nibble is
        // load-bearing: a bare code is control 0000 = NOP (Table 10) and the DAC stays at zero
        // scale — the 2026-08-07 droop-immovable bench bug.
        uint16_t expFCcode = MDAC_CMD_LOAD_UPDATE | (uint16_t)(constrain(expFC, 0.0f, 1.0f) * MDAC_res);
        uint16_t expBTcode = MDAC_CMD_LOAD_UPDATE | (uint16_t)(constrain(expBT, 0.0f, 1.0f) * MDAC_res);
        check(SPI.transfer_log[0] == expFCcode,
              "open-loop droop: FC MDAC word = load-and-update nibble + clamped code");
        check(SPI.transfer_log[1] == expBTcode,
              "open-loop droop: BT MDAC word = load-and-update nibble + clamped code");
        check((SPI.transfer_log[0] & 0xF000u) == 0x1000u &&
              (SPI.transfer_log[1] & 0xF000u) == 0x1000u,
              "open-loop droop: control nibble is 0001 (0000 would be a documented NOP)");
    }
    check(powerBalanceLive == false,
          "open-loop droop: clears powerBalanceLive (closed loop must not stomp it)");
}

// ─── AD5443 boot init: standalone-mode control word ──────────────────────────
static void test_mdac_init_standalone_mode() {
    test_group("initMdacSpiPins(): AD5443 daisy-chain disable at boot");
    reset_test_state();
    SPI.reset();

    initMdacSpiPins();
    check(SPI.transfer_log.size() == 2,
          "MDAC init: one control word per DAC (FC then BT)");
    if (SPI.transfer_log.size() == 2) {
        check(SPI.transfer_log[0] == MDAC_CMD_DAISY_DISABLE &&
              SPI.transfer_log[1] == MDAC_CMD_DAISY_DISABLE,
              "MDAC init: both words are 0x9000 (Table 10: 1001 = daisy-chain disable)");
    }
}

// ─── Youla-H share controller (share_controller.h) ───────────────────────────
#include "reference_vectors.h"   // generated by controller_design/synthesize_controller.py

// Replay the generated error sequence through the C++ implementation and compare
// against the Python DiscreteController reference outputs (double precision).
// Tolerance covers float32 accumulation over the 64-tick sequence.
static void test_share_controller_reference() {
    test_group("Youla-H controller vs Python reference vectors");
    reset_test_state();

    float worst = 0.0f;
    for (int k = 0; k < SHARE_REF_N; k++) {
        float u = shareControllerStep(SHARE_REF_E[k], 0.15f, 0.85f);
        float err = fabsf(u - SHARE_REF_U[k]);
        if (err > worst) worst = err;
    }
    check(worst < 5e-4f,
          "share controller matches Python reference over 64 ticks (incl. saturation)");

    // DC behavior: zero error holds the output (integrator + biquads at rest)
    reset_test_state();
    float u1 = shareControllerStep(0.0f, 0.15f, 0.85f);
    float u2 = shareControllerStep(0.0f, 0.15f, 0.85f);
    check(fabsf(u1 - 0.5f) < 1e-6f && fabsf(u2 - 0.5f) < 1e-6f,
          "share controller: zero error -> holds balanced split r0 = 0.5");

    // integral action: sustained positive error must ratchet the output upward
    reset_test_state();
    float prev = 0.0f;
    bool monotone = true;
    for (int k = 0; k < 10; k++) {
        float u = shareControllerStep(0.05f, 0.15f, 0.85f);
        if (k > 1 && u <= prev) monotone = false;
        prev = u;
    }
    check(monotone && prev > 0.5f,
          "share controller: sustained error integrates (output ratchets toward the rail)");
}

static void test_share_controller_antiwindup() {
    test_group("Youla-H controller anti-windup (back-calculation)");
    reset_test_state();

    // Drive hard into the top rail for 200 ticks
    for (int k = 0; k < 200; k++) shareControllerStep(1.0f, 0.15f, 0.85f);
    float u_railed = shareControllerStep(1.0f, 0.15f, 0.85f);
    check(fabsf(u_railed - 0.85f) < 1e-6f, "anti-windup: output clamped at rmax");

    // Reverse the error: back-calculation means the output must leave the rail
    // within a few ticks (a wound-up integrator would pin it for ~KI*200 ticks)
    int ticks_to_leave = -1;
    for (int k = 0; k < 10; k++) {
        float u = shareControllerStep(-0.1f, 0.15f, 0.85f);
        if (u < 0.85f - 1e-4f) { ticks_to_leave = k; break; }
    }
    check(ticks_to_leave >= 0 && ticks_to_leave <= 3,
          "anti-windup: output leaves the rail within 3 ticks of error reversal");
}

static void test_youla_wrapper_gating() {
    test_group("youlaController_Power() wrapper: Ts gating + measurement filter");
    reset_test_state();

    // sub-Ts tick: no update, held initial 0.5
    g_mock_micros = 100;    // < SHARE_CTRL_TS_US since lastMicros = 0 (100-0 < 1000)
    float u0 = youlaController_Power(0.8f, 0.5f);
    check(fabsf(u0 - 0.5f) < 1e-6f,
          "wrapper: sub-Ts call returns held output (no state advance)");

    // crossing Ts: exactly one difference-equation update, on the FILTERED error
    g_mock_micros = 1200;
    float u1 = youlaController_Power(0.8f, 0.5f);
    reset_test_state();
    float alphaFilt = shareControllerFilterMeas(0.5f);   // filter starts at 0.5 -> stays 0.5
    float uref = shareControllerStep(0.8f - alphaFilt, DROOP_R_MIN, DROOP_R_MAX);
    check(fabsf(u1 - uref) < 1e-6f,
          "wrapper: first Ts-crossing call equals one filtered shareControllerStep()");

    // measurement filter: a step in raw alpha reaches the error only fractionally
    // per tick (one-pole, A = exp(-Ts/tauf)); the setpoint path is NOT filtered
    reset_test_state();
    float f1 = shareControllerFilterMeas(0.7f);   // from 0.5 toward 0.7
    check(f1 > 0.5f + 1e-3f && f1 < 0.7f - 1e-3f,
          "wrapper: measured-share step is low-pass filtered (partial first tick)");
    for (int k = 0; k < 40; k++) shareControllerFilterMeas(0.7f);
    check(fabsf(shareCtrl_alphaFilt - 0.7f) < 1e-3f,
          "wrapper: filter converges to the measured share");

    // powerBalance() integration: the Youla path drives the corrected MDAC mapping
    reset_test_state();
    I_fc = 1.0f; I_batt = 1.0f; power_share_setpoint = 0.5f;
    g_mock_micros = 2000;
    powerBalance();
    check(fabsf(droop_gain_FC_actual - K_DROOP / (RE_MAX * 0.5f)) < 5e-3f,
          "wrapper: powerBalance() with zero share error writes balanced MDAC gains");
}

// ─── Youla-H DRIVE (velocity) controller (drive_controller.h) — fw v10 ───────
// Replay reference vectors: controller_design_MIMO/figures/drive_siso_replay.csv, converted to
// controller_design_MIMO/drive_replay_vectors.h (mirrors reference_vectors.h's placement for the
// share loop) by scratchpad/gen_drive_replay_header.py. Tolerance is on the OUTPUT u only, per
// the header's own guidance ("never on the individual states") -- the state recursion is double
// and the coefficients are the exact float32 roundings the CSV was generated from, so a correct
// C++ port should track to a few mA.
#include "drive_replay_vectors.h"   // generated from drive_siso_replay.csv

static void test_drive_controller_coeff_pinning() {
    test_group("drive_controller_coeffs.h: pinned constants (fw v10)");
    check(DRIVE_CTRL_TS_US == 2000, "drive ctrl: DRIVE_CTRL_TS_US == 2000 (500 Hz, VESC UART floor)");
    check(DRIVE_CTRL_NSTATES == 5, "drive ctrl: DRIVE_CTRL_NSTATES == 5 (Hanus realization)");
    check(DRIVE_CTRL_NSOS == 2, "drive ctrl: DRIVE_CTRL_NSOS == 2 (cross-check biquads)");
    check(fabsf(DRIVE_CTRL_I_MIN - (-12.0f)) < 1e-6f, "drive ctrl: DRIVE_CTRL_I_MIN == -12.0 A (regen rail)");
    check(fabsf(DRIVE_CTRL_I_MAX - 12.0f) < 1e-6f, "drive ctrl: DRIVE_CTRL_I_MAX == +12.0 A (drive rail)");
    // Tripwire: the anti-windup conditioning is only correct if the controller's own clamp
    // equals the downstream commandMotorCurrent() ceiling. A future MOTOR_I_CMD_MAX change
    // without re-synthesis would desync these silently -- this is the test that catches it.
    check(fabsf(DRIVE_CTRL_I_MAX - MOTOR_I_CMD_MAX) < 1e-6f,
          "drive ctrl: DRIVE_CTRL_I_MAX == MOTOR_I_CMD_MAX (clamp pairing the AW design depends on)");
}

// Compile-time guard: driveCtrl_x must stay DOUBLE. The regen replay's runtime gate (5e-2 A,
// see test_drive_controller_replay_regen()) is sized around the DOCUMENTED inherent clamp-
// boundary dither (the controller genuinely straddles +-12 A during the saturated transient), not
// around a double->float state regression -- drive_controller.h's own header measures that
// regression at ~1.4e-2 A on the saturated regen episode ("validate_drive_siso.py check 4"),
// which sits INSIDE the 5e-2 A runtime tolerance and would NOT reliably fail it. This
// static_assert is the tripwire that catches that regression directly, independent of any
// runtime replay tolerance.
#include <type_traits>
static_assert(std::is_same<decltype(driveCtrl_x[0]), double&>::value ||
              sizeof(driveCtrl_x[0]) == sizeof(double),
              "driveCtrl_x must be double -- drive_controller_coeffs.h documents a ~1.4e-2 A "
              "divergence on the saturated regen episode if the state recursion runs in float32, "
              "and that magnitude is inside the regen replay test's 5e-2 A runtime gate");

static void test_drive_controller_state_is_double() {
    test_group("drive_controller.h: driveCtrl_x is DOUBLE (compile-time; see static_assert above)");
    // The static_assert above already enforces this at compile time; this runtime check exists
    // only so the guarantee shows up in the test log/count like every other coverage item.
    check(sizeof(driveCtrl_x[0]) == sizeof(double),
          "drive ctrl: driveCtrl_x element size == sizeof(double) (float32 regression is invisible "
          "to the 5e-2 A regen replay gate -- see drive_controller_coeffs.h's 1.4e-2 A figure)");
}

static void test_drive_controller_ac_identity() {
    test_group("drive_controller_coeffs.h: AC == AD - BD*CD/DD (25 entries)");
    float worst = 0.0f;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) {
        for (int j = 0; j < DRIVE_CTRL_NSTATES; j++) {
            float expected = DRIVE_CTRL_AD[i][j]
                            - DRIVE_CTRL_BD[i][0] * DRIVE_CTRL_CD[0][j] / DRIVE_CTRL_DD;
            float err = fabsf(DRIVE_CTRL_AC[i][j] - expected);
            if (err > worst) worst = err;
        }
    }
    check(worst < 2e-6f, "drive ctrl: AC == AD - BD*CD/DD within 2e-6 over all 25 entries");
}

static void test_drive_controller_replay_small() {
    test_group("drive_controller.h replay: 'small' episode (200 samples, unsaturated)");
    reset_test_state();
    driveControllerReset();

    float worst = 0.0f;
    int clamped = 0;
    for (int k = 0; k < DRIVE_REPLAY_SMALL_N; k++) {
        float u = driveControllerStep(DRIVE_REPLAY_SMALL_E[k]);
        float err = fabsf(u - DRIVE_REPLAY_SMALL_U[k]);
        if (err > worst) worst = err;
        if (u <= DRIVE_CTRL_I_MIN + 1e-6f || u >= DRIVE_CTRL_I_MAX - 1e-6f) clamped++;
    }
    check(worst < 1e-4f, "drive ctrl replay 'small': matches Python reference (max |du| < 1e-4 A)");
    check(clamped == 0, "drive ctrl replay 'small': never clamps (per the reference's own claim)");
}

static void test_drive_controller_replay_regen() {
    test_group("drive_controller.h replay: 'regen' episode (2500 samples, rails + recovers)");
    reset_test_state();
    driveControllerReset();

    // Tolerance note (updated -- the CSV's own header now documents this directly, read it before
    // touching this test). The regen episode is generated CLOSED-LOOP through these same float32
    // coefficients (not open-loop-replayed from a float64 error sequence, which was the earlier
    // knife-edge mechanism this comment used to describe), and the emission is bit-exact for a
    // full-precision reader. Despite that, during the saturated transient the controller genuinely
    // DITHERS across the +-12 A clamp boundary (82 clamp-state transitions in the float64 sim), so
    // some sample always sits arbitrarily close to the decision edge and ANY perturbation -- CSV
    // text truncation, float32 vs float64 stimulus, instruction-level rounding differences between
    // this C++ path and the generator -- can flip a clamp decision for one or more samples, each
    // worth up to ~8 A of state drive through the ~0.9999 mode. The CSV header's own measurement:
    // 12.8 mA sensitivity to a %.9e stimulus truncation, 13.4 mA to a float32 one. This is NOT
    // slack for a sloppy implementation -- it is the actual, measured, physically-inherent chatter
    // of a correct implementation replaying at finite precision.
    //   Gate chosen: this double-state C++ path measures a worst-case |du| of ~2.1e-2 A against the
    // regenerated vectors -- inside the CSV's ~5e-2 A guidance band but NOT bit-exact (0.0), so the
    // tight bit-exactness gate is not achievable here and the ~5e-2 A gate is what's kept. (A
    // float32 ARITHMETIC recursion, as opposed to a float32 STIMULUS/coefficient rounding, costs
    // ~1 A on this episode per validate_drive_siso.py check 4 -- that remains a real inadequacy,
    // guarded separately by the static_assert/driveCtrl_x-is-double checks below, not by this gate.)
    float worst = 0.0f;
    int railed = 0;
    for (int k = 0; k < DRIVE_REPLAY_REGEN_N; k++) {
        float u = driveControllerStep(DRIVE_REPLAY_REGEN_E[k]);
        float err = fabsf(u - DRIVE_REPLAY_REGEN_U[k]);
        if (err > worst) worst = err;
        if (u <= DRIVE_CTRL_I_MIN + 1e-4f) railed++;
    }
    check(worst < 5e-2f,
          "drive ctrl replay 'regen': matches Python reference (max |du| < 5e-2 A; inherent clamp-"
          "boundary dither, see the tolerance note above -- NOT slack for implementation bugs)");
    check(railed > 50, "drive ctrl replay 'regen': a meaningful stretch rails at -12 A (anti-windup exercised)");

    // Recovery: the FINAL samples must be unclamped -- the episode's whole point is that the
    // controller leaves the rail cleanly rather than staying pinned.
    bool finalUnclamped = true;
    for (int k = DRIVE_REPLAY_REGEN_N - 20; k < DRIVE_REPLAY_REGEN_N; k++) {
        if (fabsf(DRIVE_REPLAY_REGEN_U[k] - DRIVE_CTRL_I_MIN) < 1e-4f) { finalUnclamped = false; break; }
    }
    check(finalUnclamped, "drive ctrl replay 'regen': final 20 samples are unclamped (recovery happened)");
}

static void test_drive_controller_wrapper_gating() {
    test_group("youlaController_Drive() wrapper: Ts gating + held output");
    reset_test_state();

    // sub-Ts tick: no state advance, held 0 A (fresh reset)
    g_mock_micros = 100;   // < DRIVE_CTRL_TS_US (2000) since lastMicros was back-dated to -2000
    float u0 = youlaController_Drive(5.0f);
    // The reset back-dates lastMicros so the FIRST tick after a reset always fires; re-derive the
    // expected value directly rather than assuming 0, then verify a genuine sub-Ts second call holds.
    double x_snapshot[DRIVE_CTRL_NSTATES];
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) x_snapshot[i] = driveCtrl_x[i];
    float held = u0;
    g_mock_micros = 150;   // 50 us later, well under the 2000 us Ts
    float u1 = youlaController_Drive(-5.0f);   // different error -- must NOT move the output
    check(fabsf(u1 - held) < 1e-9f,
          "wrapper: sub-Ts call returns the exact held output (no state advance)");
    bool stateUnchanged = true;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++)
        if (driveCtrl_x[i] != x_snapshot[i]) stateUnchanged = false;
    check(stateUnchanged, "wrapper: sub-Ts call leaves the Hanus state vector untouched");

    // crossing Ts: exactly one further difference-equation update, continuing from the state the
    // first tick (error 5.0) left behind -- NOT from a fresh reset.
    driveControllerReset();
    driveControllerStep(5.0f);            // replays the priming tick at g_mock_micros=100
    float uref = driveControllerStep(-5.0f);   // replays the Ts-crossing tick
    reset_test_state();
    g_mock_micros = 100;
    youlaController_Drive(5.0f);
    g_mock_micros = 2200;   // >= 2000 us since the tick at 100
    float u2 = youlaController_Drive(-5.0f);
    check(fabsf(u2 - uref) < 1e-4f,
          "wrapper: first Ts-crossing call equals one further driveControllerStep() from prior state");

    // Gate-tolerance boundary: the wrapper fires at (now - lastMicros) >= DRIVE_CTRL_TS_US -
    // DRIVE_CTRL_GATE_TOL_US, i.e. 2000 - 200 = 1800 us, not at the bare 2000 us period. Pin the
    // threshold exactly where the .ino documents it: 1799 us must still hold, 1800 us must update.
    reset_test_state();
    g_mock_micros = 0;
    float uBase = youlaController_Drive(3.0f);   // primes the gate (reset back-dates lastMicros)
    double xAfterBase[DRIVE_CTRL_NSTATES];
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) xAfterBase[i] = driveCtrl_x[i];

    g_mock_micros = 1799;   // one us short of the tolerance threshold -- must still hold
    float uHold = youlaController_Drive(-3.0f);
    check(fabsf(uHold - uBase) < 1e-9f,
          "wrapper: at elapsed 1799 us (< TS_US - GATE_TOL_US = 1800) the output still holds");
    bool stateStillFrozen = true;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++)
        if (driveCtrl_x[i] != xAfterBase[i]) stateStillFrozen = false;
    check(stateStillFrozen, "wrapper: at elapsed 1799 us the Hanus state vector is still untouched");

    g_mock_micros = 1800;   // exactly at the tolerance threshold -- must update
    float uUpdate = youlaController_Drive(-3.0f);
    check(fabsf(uUpdate - uBase) > 1e-6f,
          "wrapper: at elapsed 1800 us (== TS_US - GATE_TOL_US) the controller updates");
    bool stateMoved = false;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++)
        if (driveCtrl_x[i] != xAfterBase[i]) stateMoved = true;
    check(stateMoved, "wrapper: at elapsed 1800 us the Hanus state vector advances");
}

static void test_drive_controller_motor_control_youla() {
    test_group("motorControl(): USE_YOULA_DRIVE_CONTROLLER path drives commandMotorCurrent() in AMPS");
    reset_test_state();

    v_setpoint = 1.0f;
    v_actual   = 0.0f;
    g_mock_micros = 3000;   // past the Ts gate (state was reset at -2000 by reset_test_state)
    vesc.reset();

    motorControl();

    check(!vesc.current_calls.empty(), "motorControl(): Youla path issues a VESC current command");
    // Save the results BEFORE the second reset_test_state() below, which would otherwise clear
    // vesc.last_current out from under this comparison (reset_test_state() calls vesc.reset()).
    float actualCurrent = vesc.last_current;
    float actualTorque  = targetMotorTorque;

    // Independently recompute the expected output the wrapper should have produced: reset to the
    // same state, advance time the same way, and take one driveControllerStep() directly.
    reset_test_state();
    g_mock_micros = 3000;
    float expected = driveControllerStep(1.0f - 0.0f);
    check(fabsf(actualCurrent - expected) < 1e-4f,
          "motorControl(): commanded current == youlaController_Drive() output, in AMPS "
          "(NOT divided by motorConstant -- fw v10's structural difference from the PI path)");
    check(fabsf(actualCurrent) <= MOTOR_I_CMD_MAX + 1e-4f,
          "motorControl(): Youla output stays within +-MOTOR_I_CMD_MAX");

    // targetMotorTorque is still populated (kept meaningful, not dropped) as i_cmd*motorConstant.
    check(fabsf(actualTorque - expected * motorConstant) < 1e-4f,
          "motorControl(): targetMotorTorque mirrors i_cmd*motorConstant (has no firmware reader, "
          "kept for telemetry/test symmetry per the .ino's own note)");
}

static void test_drive_controller_reset_state() {
    test_group("resetDriveControlState(): zeroes states + held output; next tick is DD*e only");
    reset_test_state();

    // Drive the controller hard into saturation so state is clearly non-zero.
    for (int k = 0; k < 500; k++) driveControllerStep(20.0f);
    bool anyNonZero = false;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) if (driveCtrl_x[i] != 0.0) anyNonZero = true;
    check(anyNonZero, "reset precondition: a saturated run leaves non-zero Hanus states");

    resetDriveControlState();
    bool allZero = true;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) if (driveCtrl_x[i] != 0.0) allZero = false;
    check(allZero, "resetDriveControlState(): zeroes all 5 Hanus states");
    check(driveCtrl_heldOut == 0.0f, "resetDriveControlState(): zeroes the held output");

    // Next raw driveControllerStep() call from the zeroed state must equal DD*e exactly (all
    // states zero, so the CD*x sum vanishes and only the direct feedthrough term remains).
    float u = driveControllerStep(2.0f);
    check(fabsf(u - DRIVE_CTRL_DD * 2.0f) < 1e-4f,
          "resetDriveControlState(): first post-reset output is DD*e only (states contribute 0)");
}

static void test_drive_controller_reset_sites() {
    test_group("fw v10 drive-controller reset sites: Idle->Run, 'V' entry edge, haltMotorOutput()");
    reset_test_state();

    // (a) Idle -> Run transition resets. Wind up the controller, enter State 1, arm the
    // transition, and tick doState1() the way the existing state-machine tests do.
    for (int k = 0; k < 50; k++) driveControllerStep(5.0f);
    bool woundUp = false;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) if (driveCtrl_x[i] != 0.0) woundUp = true;
    check(woundUp, "reset-site precondition: the controller is wound up before Idle->Run");
    v_setpoint = 3.5f;   // stale nonzero setpoint left over from a prior run -- must be cleared too
    mainState   = 1;
    changeToRun = true;
    g_mock_micros = 500000;
    doState1();
    bool allZeroA = true;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) if (driveCtrl_x[i] != 0.0) allZeroA = false;
    check(allZeroA && mainState == 2,
          "reset-site (a): Idle->Run transition (doState1() with changeToRun) resets the drive controller");
    // Companion safety fix (this round): doState2's entry zeroes v_setpoint alongside
    // resetDriveControlState(), so a stale nonzero setpoint from a previous run can't feed a live
    // current command on Run's very first tick before the Pi/operator ever sends a new one. A
    // regression that dropped just that line (leaving the drive-controller reset alone) would not
    // be caught by allZeroA above, so it is checked separately here.
    check(v_setpoint == 0.0f,
          "reset-site (a): Idle->Run transition also zeroes v_setpoint (not just the controller state)");

    // (b) setManualMotorVelocity() ENTRY EDGE resets; a second call while already in
    // MOTOR_TEST_VELOCITY mode (a live setpoint step) must NOT reset.
    reset_test_state();
    for (int k = 0; k < 50; k++) driveControllerStep(5.0f);
    setManualMotorVelocity(1.0f);
    bool allZeroB = true;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) if (driveCtrl_x[i] != 0.0) allZeroB = false;
    check(allZeroB, "reset-site (b): setManualMotorVelocity() entry edge resets the drive controller");

    for (int k = 0; k < 50; k++) driveControllerStep(5.0f);   // wind up again, still in VELOCITY mode
    bool woundUp2 = false;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) if (driveCtrl_x[i] != 0.0) woundUp2 = true;
    setManualMotorVelocity(2.0f);   // setpoint step, NOT an entry edge
    bool stillWound = false;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) if (driveCtrl_x[i] != 0.0) stillWound = true;
    check(woundUp2 && stillWound,
          "reset-site (b): a setpoint step during a live 'V' run does NOT reset the drive controller");

    // (c) haltMotorOutput() resets.
    reset_test_state();
    for (int k = 0; k < 50; k++) driveControllerStep(5.0f);
    haltMotorOutput();
    bool allZeroC = true;
    for (int i = 0; i < DRIVE_CTRL_NSTATES; i++) if (driveCtrl_x[i] != 0.0) allZeroC = false;
    check(allZeroC, "reset-site (c): haltMotorOutput() resets the drive controller");
}

static void test_drive_controller_saturation_consistency() {
    test_group("drive_controller.h: saturation stays bounded, recovers when error returns to 0");
    reset_test_state();

    // Huge error: output must saturate exactly at +12.0 A and stay bounded over 1000 ticks.
    float u = 0.0f;
    for (int k = 0; k < 1000; k++) {
        u = driveControllerStep(5.0f);
        bool boundedState = true;
        for (int i = 0; i < DRIVE_CTRL_NSTATES; i++)
            if (!std::isfinite(driveCtrl_x[i]) || fabsf((float)driveCtrl_x[i]) > 1.0e6f) boundedState = false;
        check(boundedState, "saturation: Hanus states stay bounded and finite through 1000 ticks");
        if (k > 900) break;   // one representative late-run check is enough; avoid 1000 log lines
    }
    check(fabsf(u - 12.0f) < 1e-4f, "saturation: output is exactly +12.0 A under a 5 m/s error");

    // Error returns to 0: output must come back inside the rails within a bounded number of ticks.
    int ticksToUnrail = -1;
    for (int k = 0; k < 2000; k++) {
        u = driveControllerStep(0.0f);
        if (fabsf(u) < 12.0f - 1e-3f) { ticksToUnrail = k; break; }
    }
    check(ticksToUnrail >= 0 && ticksToUnrail < 2000,
          "saturation: output returns inside the rails within a bounded number of ticks after error->0");
}

// ─── PI fallback path (USE_YOULA_DRIVE_CONTROLLER=0) — compile-only check ────
// The main suite builds with the shipped default (flag=1, Youla). Building a second full TU at
// flag=0 here is impractical within this Makefile (the .ino is included directly and pulls in
// every mock/global exactly once per link unit; a third g++ invocation per test run would
// roughly double build time for one compile-time branch that is deliberately kept byte-identical
// to the pre-fw-v10 PI path). Flagged as a coverage gap in the round report rather than forced.
// motorControl()'s #else branch (targetMotorTorque = PI_Controller_Motor(...); commandMotorCurrent
// (targetMotorTorque / motorConstant)) is unchanged from the pre-fw-v10 source and PI_Controller_Motor()
// itself is exercised directly by test_pi_controllers() above, so the arithmetic is covered --
// only the #if/#else selection itself is not compiled both ways in one run.


// ─── Droop MDAC mapping bounds (the k_eq saturation bug, fixed 2026-07-10) ────
// The old k_eq/r/K_sns/A_v mapping commanded g > 1 for all r < 0.896, pinning both
// MDACs at full scale. The corrected mapping g = K_DROOP/(RE_MAX*r) must keep both
// gains <= 1 over the whole clamped authority span, and out-of-span requests must
// clamp to [DROOP_R_MIN, DROOP_R_MAX] instead of running off the MDAC range.
static void test_droop_mapping_bounds() {
    test_group("Droop MDAC mapping bounds (K_DROOP/RE_MAX)");
    reset_test_state();

    // sanity on the derived constant: RE_MAX = K_sns*A_v*RD1/RINJ with the bodged
    // RD1 = 215k (16V bus retune) = 2.014 ohm
    check(fabsf(RE_MAX - 2.0136f) < 5e-3f,
          "mapping: RE_MAX derives to ~2.014 ohm from the bodged RD1 = 215k");
    check(K_DROOP <= RE_MAX * DROOP_R_MIN + 1e-6f,
          "mapping: K_DROOP respects the hard bound RE_MAX*DROOP_R_MIN");

    // sweep the full span: both gains in (0, 1]
    for (float r = DROOP_R_MIN; r <= DROOP_R_MAX + 1e-6f; r += 0.05f) {
        applyOpenLoopDroop(r);
        if (droop_gain_FC_actual > 1.0f || droop_gain_BT_actual > 1.0f) {
            check(false, "mapping: gain exceeded 1.0 inside the authority span");
            return;
        }
    }
    check(true, "mapping: g_FC and g_BT stay <= 1 over the full [R_MIN, R_MAX] span");

    // out-of-span requests: with NEITHER bus switch closed (reset state), the
    // channel cutoff is blocked by the last-source guard, so the request falls
    // back to the band-edge clip — the pre-cutoff behavior. (The cutoff path
    // itself is covered in test_share_ratio_cutoff.)
    applyOpenLoopDroop(0.01f);
    check(fabsf(droop_gain_FC_actual - K_DROOP / (RE_MAX * DROOP_R_MIN)) < 1e-4f,
          "mapping: low request clamps to DROOP_R_MIN");
    applyOpenLoopDroop(0.99f);
    check(fabsf(droop_gain_BT_actual - K_DROOP / (RE_MAX * (1.0f - DROOP_R_MAX))) < 1e-4f,
          "mapping: high request clamps to DROOP_R_MAX");

    // symmetric split at r = 0.5: equal gains, ~0.297 each (not full-scale!)
    applyOpenLoopDroop(0.5f);
    check(fabsf(droop_gain_FC_actual - droop_gain_BT_actual) < 1e-6f,
          "mapping: r=0.5 gives symmetric gains");
    check(droop_gain_FC_actual < 0.99f,
          "mapping: r=0.5 gains are NOT pinned at full scale (the old bug)");
}

// ─── State 98 bench tools: closed-loop power-share setpoint ───────────────────
static void test_power_share_setpoint_live() {
    test_group("State 98 power-share setpoint (closed-loop live)");
    reset_test_state();

    setPowerShareSetpointLive(0.7f);
    check(fabsf(power_share_setpoint - 0.7f) < 1e-4f,
          "power-share live: in-range value stored");
    check(powerBalanceLive == true,
          "power-share live: enables powerBalanceLive");

    // Clamp to [0, 1] — the full span is valid (2026-08-10 cutoff semantics)
    setPowerShareSetpointLive(1.5f);
    check(fabsf(power_share_setpoint - 1.0f) < 1e-4f,
          "power-share live: clamped to 1.0");
    setPowerShareSetpointLive(-0.5f);
    check(fabsf(power_share_setpoint - 0.0f) < 1e-4f,
          "power-share live: clamped to 0.0");

    // With current flowing, the live closed loop writes the MDAC
    setPowerShareSetpointLive(0.7f);
    I_fc = 2.0f; I_batt = 1.0f;
    pi_power_accum = 0; pi_power_lastMicros = 0;
    g_mock_micros = 100000;   // > sampleTime
    SPI.reset();
    powerBalance();
    check(SPI.transfer_log.size() == 2,
          "power-share live: powerBalance writes the MDAC when current flows");
}

// ─── State 98 bench tools: power-share profile phase machine ─────────────────
static void test_power_share_profile() {
    test_group("Power-share profile (advancePowerShareProfile) phase transitions");
    reset_test_state();

    powerShareProfileActive     = true;
    powerShareProfilePhaseIdx   = 0;
    powerShareProfilePhaseStart = 0;
    powerShareProfileStatusLast = 0;
    g_mock_millis = 0;

    // A constant motor command is running during the sweep — completion must halt it.
    manualMotorMode    = MOTOR_TEST_CURRENT;
    manualMotorCurrent = 5.0f;
    vesc.reset();

    // Phase 0 (settle, 0–3000ms): setpoint holds at 0.5
    g_mock_millis = 1500;
    advancePowerShareProfile();
    check(powerShareProfilePhaseIdx == 0,
          "PS profile: still phase 0 at 1500ms");
    check(fabsf(power_share_setpoint - 0.5f) < 0.01f,
          "PS profile: setpoint = 0.5 during settle");

    // At 3001ms: phase 0 elapses → phase 1
    g_mock_millis = 3001;
    advancePowerShareProfile();
    check(powerShareProfilePhaseIdx == 1,
          "PS profile: transitions to phase 1 at 3001ms");

    // Phase 1 (ramp 0.5→0.8 over 1000ms), start now 3001; at 3001+500=3501, t=0.5 → 0.65
    g_mock_millis = 3501;
    advancePowerShareProfile();
    check(powerShareProfilePhaseIdx == 1,
          "PS profile: still in ramp phase 1 at 3501ms");
    check(fabsf(power_share_setpoint - 0.65f) < 0.02f,
          "PS profile: setpoint ≈ 0.65 at ramp midpoint");

    // Exhaust the remaining phases, then one more call to fire completion
    while (powerShareProfilePhaseIdx < POWER_SHARE_PROFILE_PHASES) {
        g_mock_millis += POWER_SHARE_PROFILE[powerShareProfilePhaseIdx].durationMs + 1;
        advancePowerShareProfile();
    }
    advancePowerShareProfile();

    check(powerShareProfileActive == false,
          "PS profile: deactivates after all phases complete");
    check(fabsf(power_share_setpoint - 0.5f) < 0.01f,
          "PS profile: setpoint reset to 0.5 (balanced) on completion");
    check(manualMotorMode == MOTOR_TEST_OFF,
          "PS profile: manual motor mode cleared on natural completion");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "PS profile: motor zeroed (vesc.setCurrent(0)) on natural completion");
}

// ─── State 98 bench tools: profile drives motor (constant) + powerBalance ────
static void test_power_share_profile_runs_controls() {
    test_group("doState98() power-share profile holds motor + runs powerBalance");
    reset_test_state();

    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(5.0f);          // constant motor command
    powerShareProfileActive     = true;
    powerShareProfilePhaseIdx   = 1;      // a ramp phase (setpoint varying)
    powerShareProfilePhaseStart = 0;
    g_mock_millis = 500;
    g_mock_micros = 100000;               // > sampleTime so powerBalance's PI updates
    I_fc = 2.0f; I_batt = 1.0f;           // current flowing so powerBalance writes the MDAC
    SPI.reset();
    vesc.reset();

    doState98();

    check(!vesc.current_calls.empty() && fabsf(vesc.last_current - 5.0f) < 1e-4f,
          "PS profile: motor held at the constant manual current");
    check(SPI.transfer_log.size() == 2,
          "PS profile: powerBalance writes the MDAC during the sweep");
    check(powerShareProfileActive == true,
          "PS profile: still active mid-sweep");
}

// ─── State 98 bench tools: non-numeric input cancels a pending prompt ─────────
static void test_pending_input_cancel() {
    test_group("State 98 numeric prompt — non-numeric char cancels");
    reset_test_state();

    // A numeric char must NOT cancel: feed a full value and confirm it applies.
    mainState = 98;
    pendingInput = PEND_POWER_SHARE;
    Serial.rx_queue.push('0');
    Serial.rx_queue.push('.');
    Serial.rx_queue.push('7');
    Serial.rx_queue.push('\n');
    for (int i = 0; i < 4; i++) doState98();
    check(pendingInput == PEND_NONE,
          "pending input: numeric line consumed, prompt cleared");
    check(fabsf(power_share_setpoint - 0.7f) < 1e-4f,
          "pending input: numeric line applied (0.7)");

    // A non-numeric char cancels the pending entry AND is processed as a command key.
    reset_test_state();
    mainState = 98;
    manualMotorMode    = MOTOR_TEST_CURRENT;   // 'X' should turn this OFF + zero the motor
    manualMotorCurrent = 5.0f;
    pendingInput = PEND_POWER_SHARE;            // a prompt is pending
    vesc.reset();
    Serial.rx_queue.push('X');                  // non-numeric → cancel + run as command
    doState98();
    check(pendingInput == PEND_NONE,
          "pending input: non-numeric char cancels the prompt");
    check(manualMotorMode == MOTOR_TEST_OFF && vesc.last_current == 0.0f,
          "pending input: cancelling char ('X') is then handled as a command");
}

// Feed a whole line (chars + '\n') through doState98(), ONE doState98() call per character —
// doState98() reads only one Serial byte per invocation (mirrors how the PEND_TRAP_PARAMS line is
// typed by an operator across ticks; see test_pending_input_cancel's push-then-loop pattern).
static void feed_serial_line(const char* s) {
    for (const char* p = s; *p; ++p) {
        Serial.rx_queue.push(*p);
        doState98();
    }
    Serial.rx_queue.push('\n');
    doState98();
}

// ─── State 98 bench tools: Serial-Plotter stream ('L') ───────────────────────
// The contract under test is the WIRE FORMAT, not just a flag: the Arduino IDE plotter keys its
// series off the "label:value" pairs and needs the same field count on every line, so a wrong
// label or a dropped field yields an empty/mis-legended graph that no state assertion would catch.
static void test_plot_stream_format_and_rate() {
    test_group("Plot stream ('L'): toggle, wire format, rate gate");
    reset_test_state();

    mainState = 98;
    g_mock_millis = 1000;
    Serial.rx_queue.push('L');
    doState98();
    check(plotModeActive == true, "'L': toggles the plot stream ON");

    // doState98() already ran one plotTick() (plotLastMs was back-dated so it streams immediately).
    // Note: "sp:" and "act:" are no longer unambiguous tokens under fw v7 -- "share_sp:"/"v_sp:"
    // both contain "sp:" and "share_act:"/"v_act:" both contain "act:", so a bare tx_count("sp:")
    // would silently double-count (or a bare tx_contains would pass vacuously against the wrong
    // field). Every probe below anchors on the full label, with a leading comma for the
    // non-first fields so it can't match inside a longer label.
    check(Serial.tx_contains("share_sp:") && Serial.tx_contains(",share_act:") && Serial.tx_contains(",gFC:")
       && Serial.tx_contains(",gBT:") && Serial.tx_contains(",ifc:") && Serial.tx_contains(",ibt:")
       && Serial.tx_contains(",v_sp:") && Serial.tx_contains(",v_act:"),
          "plot: line carries all eight labelled fields");

    // Review C2: tx_contains is substring-only, so the check above proves presence, not order --
    // it would pass just as well if the wire swapped two fields. Assert the actual order by
    // walking find() forward through the captured line: each label's offset must be strictly
    // greater than the previous one's, which is only possible if they appear left-to-right in the
    // sequence the changelog documents.
    {
        static const char* kPlotFieldOrder[] = {
            "share_sp:", ",share_act:", ",gFC:", ",gBT:", ",ifc:", ",ibt:", ",v_sp:", ",v_act:"
        };
        size_t searchFrom = 0;
        bool   inOrder    = true;
        for (const char* label : kPlotFieldOrder) {
            size_t pos = Serial.tx.find(label, searchFrom);
            if (pos == std::string::npos) { inOrder = false; break; }
            searchFrom = pos + 1;   // next label's offset must be strictly greater than this one
        }
        check(inOrder,
              "plot: the eight labelled fields appear in the documented order "
              "(share_sp, share_act, gFC, gBT, ifc, ibt, v_sp, v_act)");
    }

    // Rate gate: no second line until PLOT_PERIOD_MS has elapsed. "share_sp:" appears exactly once
    // per line (unlike "sp:", which would also match "v_sp:"), so it's a valid line-count proxy.
    Serial.tx_clear();
    g_mock_millis += PLOT_PERIOD_MS - 1;
    doState98();
    check(Serial.tx_count("share_sp:") == 0, "plot: no line before PLOT_PERIOD_MS elapses");
    g_mock_millis += 1;
    doState98();
    check(Serial.tx_count("share_sp:") == 1, "plot: exactly one line once the period elapses");

    // The reported share is the same quantity powerBalance() closes on.
    Serial.tx_clear();
    I_fc = 3.0f; I_batt = 1.0f;          // |I_fc| / (|I_fc| + |I_batt|) = 0.750
    g_mock_millis += PLOT_PERIOD_MS;
    doState98();
    check(Serial.tx_contains("share_act:0.750"), "plot: 'share_act' is the measured share |I_fc|/(|I_fc|+|I_batt|)");
    check(Serial.tx_contains("ifc:3.000") && Serial.tx_contains("ibt:1.000"),
          "plot: per-channel currents reported at 3 decimals");

    // Zero current → share undefined → reported as 0 (flat trace), never NaN.
    Serial.tx_clear();
    I_fc = 0.0f; I_batt = 0.0f;
    g_mock_millis += PLOT_PERIOD_MS;
    doState98();
    check(Serial.tx_contains("share_act:0.000"), "plot: zero current reports share_act=0, not NaN");

    // fw v7: v_sp/v_act carry v_setpoint/v_actual verbatim, at 3 decimals, independent of the
    // share fields above.
    Serial.tx_clear();
    v_setpoint = 2.5f; v_actual = -1.125f;
    g_mock_millis += PLOT_PERIOD_MS;
    doState98();
    check(Serial.tx_contains(",v_sp:2.500"), "plot: v_sp reports v_setpoint at 3 decimals");
    check(Serial.tx_contains(",v_act:-1.125"), "plot: v_act reports v_actual at 3 decimals");

    // 'L' again turns it off and the stream stops.
    Serial.tx_clear();
    Serial.rx_queue.push('L');
    doState98();
    check(plotModeActive == false, "'L': toggles the plot stream OFF");
    g_mock_millis += PLOT_PERIOD_MS * 4;
    doState98();
    check(Serial.tx_count("share_sp:") == 0, "plot: no lines emitted once the stream is off");
}

static void test_plot_suppresses_status_lines() {
    test_group("Plot stream: periodic status + phase lines suppressed");
    reset_test_state();

    // A running power-share profile normally prints a '[PS]' snapshot every 500 ms and a
    // '[PS] Phase N' banner at each transition. Both would break the plotter parse.
    mainState = 98;
    g_mock_millis = 0;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    plotModeActive              = true;
    powerShareProfileActive     = true;
    powerShareProfilePhaseIdx   = 0;
    powerShareProfilePhaseStart = 0;
    powerShareProfileStatusLast = 0;

    Serial.tx_clear();
    g_mock_millis = 600;                    // past the 500 ms snapshot cadence
    advancePowerShareProfile();
    check(!Serial.tx_contains("[PS] t="), "plot: '[PS]' status snapshot suppressed while plotting");

    Serial.tx_clear();
    g_mock_millis = 3001;                   // phase 0 → 1 transition
    advancePowerShareProfile();
    check(powerShareProfilePhaseIdx == 1, "plot: phase machine still advances while plotting");
    check(!Serial.tx_contains("[PS] Phase"), "plot: '[PS] Phase' banner suppressed while plotting");

    // …and the same lines DO appear with plot mode off (guards against the suppression being
    // unconditional, which would silently gut the normal bench workflow).
    plotModeActive              = false;
    powerShareProfileStatusLast = 0;
    Serial.tx_clear();
    g_mock_millis = 4000;
    advancePowerShareProfile();
    check(Serial.tx_contains("[PS] t="), "plot off: '[PS]' status snapshot restored");

    // The 'U' VESC watch line is non-numeric too, so it is suppressed as well.
    reset_test_state();
    mainState        = 98;
    vescWatchActive  = true;
    plotModeActive   = true;
    lastVescWatchMs  = 0;
    g_mock_millis    = VESC_WATCH_PERIOD_MS + 1;
    Serial.tx_clear();
    pollVescWatch();
    check(!Serial.tx_contains("[VW]"), "plot: '[VW]' VESC watch line suppressed while plotting");
    plotModeActive = false;
    pollVescWatch();
    check(Serial.tx_contains("[VW]"), "plot off: '[VW]' VESC watch line restored");
}

static void test_plot_armed_share_profile() {
    test_group("Plot stream: 'R' arms the power-share profile with a start delay");
    reset_test_state();

    mainState = 98;
    g_mock_millis = 10000;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    V_bus = V_BUS_CHARGED_THRESH + 1.0f;
    plotModeActive = true;

    Serial.rx_queue.push('R');
    doState98();
    check(plotArmTarget == PLOT_ARM_SHARE, "'R' under plot mode: arms instead of starting");
    check(powerShareProfileActive == false, "'R' under plot mode: profile does NOT start yet");

    // Still armed just before the deadline.
    g_mock_millis += PLOT_ARM_DELAY_MS - 1;
    doState98();
    check(powerShareProfileActive == false, "armed: profile still not started 1ms before the deadline");

    // Fires on the deadline, and the run is set up exactly as the immediate path would.
    g_mock_millis += 1;
    doState98();
    check(powerShareProfileActive == true,  "armed: profile starts once the delay elapses");
    check(plotArmTarget == PLOT_ARM_NONE,   "armed: target cleared after firing");
    check(powerShareProfilePhaseIdx == 0,   "armed: profile starts at phase 0");

    // Without plot mode the same key starts immediately (no behaviour change to the normal path).
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    Serial.rx_queue.push('R');
    doState98();
    check(powerShareProfileActive == true && plotArmTarget == PLOT_ARM_NONE,
          "'R' without plot mode: starts immediately, nothing armed");
}

static void test_plot_arm_cancellation_paths() {
    test_group("Plot stream: every stop path cancels a pending armed start");

    // Helper-free setup repeated per case: arm, then exercise one cancel path.
    struct { char key; const char* name; } cases[] = {
        { 'R', "'R' pressed again cancels the armed share profile" },
        { 'X', "'X' universal stop cancels the armed share profile" },
    };
    for (auto &c : cases) {
        reset_test_state();
        mainState = 98;
        g_pin_value[MOT_PWR_ENABLE] = HIGH;
        setManualMotorCurrent(3.0f);
        plotModeActive = true;
        g_mock_millis  = 5000;
        Serial.rx_queue.push('R');
        doState98();
        check(plotArmTarget == PLOT_ARM_SHARE, "arm established for the cancel case");

        Serial.rx_queue.push(c.key);
        doState98();
        check(plotArmTarget == PLOT_ARM_NONE, c.name);

        // And the profile must never fire afterwards.
        g_mock_millis += PLOT_ARM_DELAY_MS * 2;
        doState98();
        check(powerShareProfileActive == false, "cancelled arm never starts the profile");
    }

    // 'Q' cancels the arm AND drops plot mode (a State-98-only tool must not leak into Idle).
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    plotModeActive = true;
    Serial.rx_queue.push('R');
    doState98();
    Serial.rx_queue.push('Q');
    doState98();
    check(plotArmTarget == PLOT_ARM_NONE, "'Q': cancels the armed profile on exit");
    check(plotModeActive == false,        "'Q': plot mode cleared on exit to Idle");
    check(mainState == 1,                 "'Q': still exits to State 1");

    // A bring-up started during the arming window cancels the arm rather than firing into it.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    plotModeActive = true;
    g_mock_millis  = 2000;
    Serial.rx_queue.push('R');
    doState98();
    check(plotArmTarget == PLOT_ARM_SHARE, "arm established before the bring-up case");
    bringupActive = true; bringupPhase = 1;
    plotArmTick();
    check(plotArmTarget == PLOT_ARM_NONE,
          "armed profile cancelled when a bring-up starts during the delay");
    check(powerShareProfileActive == false,
          "armed profile does not fire into a running bring-up");
}

static void test_plot_armed_trap_profile() {
    test_group("Plot stream: 'T' arms the trapezoid with its parsed parameters");
    reset_test_state();

    mainState = 98;
    g_mock_millis = 0;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    plotModeActive = true;

    Serial.rx_queue.push('T');
    doState98();
    check(pendingInput == PEND_TRAP_PARAMS, "'T' under plot mode: still prompts for the parameter line");

    feed_serial_line(" 6 5 0.5");
    check(plotArmTarget == PLOT_ARM_TRAP,  "'T' under plot mode: arms after the line parses");
    check(trapProfileActive == false,      "'T' under plot mode: trapezoid does NOT start yet");
    check(fabsf(plotArmTrapImax - 6.0f) < 1e-3f, "armed trap: peak current stashed");
    check(plotArmTrapHoldMs == 5000,             "armed trap: hold time stashed (ms)");
    check(fabsf(plotArmTrapRate - 0.5f) < 1e-3f, "armed trap: ramp rate stashed");

    g_mock_millis += PLOT_ARM_DELAY_MS;
    doState98();
    check(trapProfileActive == true, "armed trap: starts once the delay elapses");
    check(fabsf(trapImax - 6.0f) < 1e-3f && trapHoldMs == 5000 && fabsf(trapRateAps - 0.5f) < 1e-3f,
          "armed trap: fires with exactly the parameters that were typed");

    // A second 'T' while armed cancels (toggle semantics, same as the running-profile stop).
    reset_test_state();
    mainState = 98;
    plotModeActive = true;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 4 1 2");
    check(plotArmTarget == PLOT_ARM_TRAP, "armed trap established for the cancel case");
    Serial.rx_queue.push('T');
    doState98();
    check(plotArmTarget == PLOT_ARM_NONE, "'T' pressed again cancels the armed trapezoid");
    g_mock_millis += PLOT_ARM_DELAY_MS * 2;
    doState98();
    check(trapProfileActive == false, "cancelled armed trapezoid never starts");
}

static void test_plot_arm_respects_preconditions() {
    test_group("Plot stream: 'R' preconditions are checked at the keypress, not after the delay");
    reset_test_state();

    // MOT_PWR LOW is a hard refusal for the share profile. Under plot mode the refusal must happen
    // NOW (so the operator sees it before switching windows), not silently at the deadline.
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = LOW;
    setManualMotorCurrent(3.0f);
    plotModeActive = true;
    Serial.rx_queue.push('R');
    doState98();
    check(plotArmTarget == PLOT_ARM_NONE, "'R' with MOT_PWR LOW: nothing armed under plot mode");
    check(powerShareProfileActive == false, "'R' with MOT_PWR LOW: profile refused as normal");

    // No manual motor command is the other refusal.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    plotModeActive = true;
    Serial.rx_queue.push('R');
    doState98();
    check(plotArmTarget == PLOT_ARM_NONE, "'R' with no motor command: nothing armed under plot mode");

    // The gates are re-checked at FIRE time too: an operator '3' (MOT_PWR OFF) during the arming
    // window must cancel, not silently start a run whose precondition no longer holds.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    plotModeActive = true;
    g_mock_millis  = 1000;
    Serial.rx_queue.push('R');
    doState98();
    check(plotArmTarget == PLOT_ARM_SHARE, "arm established for the fire-time re-check case");
    g_pin_value[MOT_PWR_ENABLE] = LOW;      // MOT_PWR dropped during the countdown
    g_mock_millis += PLOT_ARM_DELAY_MS;
    doState98();
    check(plotArmTarget == PLOT_ARM_NONE && powerShareProfileActive == false,
          "armed share profile cancels (not fires) if MOT_PWR dropped during the delay");
}

// ─── Plot stream: review-round fixes (2026-08-07 F1/F2/F5/F7) ────────────────
static void test_plot_ov_transient_print_suppressed() {
    test_group("Plot stream: [OV] transient report suppressed while plotting (F1)");
    reset_test_state();

    // Open an over-limit window (1 sample — under the 10ms/3-sample latch bar), then close it.
    mainState = 98;
    plotModeActive = true;
    g_mock_millis  = 1000;
    V_bus = LIMIT_V_BUS_MAX + 0.5f;
    detectFaults();
    check(ovBusOverActive, "F1: over-limit window opened");
    Serial.tx_clear();
    V_bus = V_BUS_NOMINAL;
    detectFaults();
    check(ovBusTransientCount == 1,          "F1: transient counter still increments while plotting");
    check(!Serial.tx_contains("[OV]"),       "F1: [OV] transient line suppressed under plot mode");
    check(mainState == 98,                   "F1: no latch from the sub-persistence window");

    // Same sequence with plot mode off must print (suppression must not be unconditional).
    plotModeActive = false;
    g_mock_millis += 2000;                   // clear of the 1 Hz print rate bound
    V_bus = LIMIT_V_BUS_MAX + 0.5f;
    detectFaults();
    Serial.tx_clear();
    V_bus = V_BUS_NOMINAL;
    detectFaults();
    check(Serial.tx_contains("[OV]"), "F1: [OV] transient line restored with plot mode off");
}

static void test_plot_arm_supersede_message() {
    test_group("Plot stream: cross-arm supersede cancels loudly (F2)");
    reset_test_state();

    // Arm the share profile, then type a full trapezoid line: the trap arm must supersede the
    // share arm WITH a cancel message, not overwrite it silently.
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    plotModeActive = true;
    g_mock_millis  = 1000;
    Serial.rx_queue.push('R');
    doState98();
    check(plotArmTarget == PLOT_ARM_SHARE, "F2: share arm established");

    Serial.tx_clear();
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 4 1 2");
    check(plotArmTarget == PLOT_ARM_TRAP,             "F2: trap arm supersedes the share arm");
    check(Serial.tx_contains("superseded by 'T'"),    "F2: supersede printed a cancel message");
}

static void test_plot_arm_refused_over_running_profile() {
    test_group("Plot stream: arming refused while another profile runs (F5)");

    // 'R' under plot mode with a drive cycle running: refuse at the keypress (the immediate
    // path's takeover would otherwise become "arm now, cancel in 5s" — a delayed surprise).
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    plotModeActive   = true;
    driveCycleActive = true;
    Serial.rx_queue.push('R');
    doState98();
    check(plotArmTarget == PLOT_ARM_NONE, "F5: 'R' arm refused while the drive cycle runs");

    // Trapezoid parse path: same refusal over a running share profile.
    reset_test_state();
    mainState = 98;
    plotModeActive          = true;
    powerShareProfileActive = true;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 4 1 2");
    check(plotArmTarget == PLOT_ARM_NONE && !trapProfileActive,
          "F5: 'T' arm refused while the share profile runs");
}

static void test_share_start_clears_trap() {
    test_group("startPowerShareProfile() clears an active trapezoid (F7, pre-existing)");
    reset_test_state();

    // Old bug: 'R' during a trapezoid left trapProfileActive set but shadowed by branch
    // precedence; the orphaned trapezoid resumed with a huge elapsed time when the share
    // profile stopped.
    trapProfileActive = true;
    trapCmdA          = 3.5f;
    startPowerShareProfile();
    check(!trapProfileActive && trapCmdA == 0.0f,
          "F7: share-profile start clears trapProfileActive + trapCmdA");
    check(powerShareProfileActive, "F7: share profile itself started");
}

// ─── State 98 bench tools: trapezoidal current profile ('T') ─────────────────
static void test_trap_runs_without_mot_pwr() {
    test_group("Trapezoid profile ('T') runs with MOT_PWR_ENABLE LOW (warn only, no gate)");
    reset_test_state();

    // The VESC may be bench-powered from a separate supply, so MOT_PWR is NOT a precondition:
    // 'T' arms the parameter line and the profile starts regardless of the switch state.
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = LOW;
    Serial.rx_queue.push('T');
    doState98();
    check(pendingInput == PEND_TRAP_PARAMS,
          "trap: 'T' with MOT_PWR LOW still arms the parameter line");

    feed_serial_line(" 5 2 10");
    doState98();
    check(trapProfileActive == true,
          "trap: profile starts with MOT_PWR LOW (no gate — separate VESC supply case)");
}

static void test_trap_happy_path() {
    test_group("Trapezoid profile — full 'T' entry + ramp/hold/ramp-down + natural completion");
    reset_test_state();

    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 0;
    g_mock_micros = 0;

    Serial.rx_queue.push('T');
    doState98();
    check(pendingInput == PEND_TRAP_PARAMS,
          "trap: 'T' arms the single-line parameter entry");

    // Arm the other two motor drivers right before the profile actually starts, so this test
    // isolates the "starting the profile clears them" behaviour (they don't get a chance to run
    // and self-clear across the earlier prompt ticks).
    driveCycleActive        = true;
    powerShareProfileActive = true;
    g_mock_millis = 1000;   // startTrapProfile() stamps trapStartMs from millis()
    // The rest of the "T 5 2 10" line: Imax=5A, hold=2s, rate=10A/s, all on one line.
    feed_serial_line(" 5 2 10");
    doState98();

    check(trapProfileActive == true,
          "trap: single line \"T 5 2 10\" parses and starts the profile");
    check(driveCycleActive == false && powerShareProfileActive == false,
          "trap: starting the profile clears the other two motor drivers");
    check(fabsf(trapImax - 5.0f) < 1e-4f && trapHoldMs == 2000 && fabsf(trapRateAps - 10.0f) < 1e-4f,
          "trap: parsed values committed (Imax=5A, hold=2000ms, rate=10A/s)");
    // rampMs = |5|/10 * 1000 = 500ms
    check(trapRampMs == 500,
          "trap: ramp duration derived as |Imax|/rate");

    // ── Ramp-up: at t=250ms (half the 500ms ramp), cmd should be ~half of Imax.
    g_mock_millis = 1000 + 250;
    g_mock_micros = 1000000;   // clear of the 2ms motor rate gate
    vesc.reset();
    advanceTrapProfile();
    check(fabsf(trapCmdA - 2.5f) < 0.05f,
          "trap: ramp-up commanded current tracks rate*t at the midpoint (~2.5A)");
    check(trapPhase == TRAP_RAMP_UP, "trap: phase is RAMP_UP mid-ramp");

    // Another ramp-up sample point closer to the end (t=450ms of 500ms ramp).
    g_mock_millis = 1000 + 450;
    g_mock_micros = 2000000;
    advanceTrapProfile();
    check(fabsf(trapCmdA - 4.5f) < 0.05f,
          "trap: ramp-up commanded current tracks rate*t near the end (~4.5A)");

    // ── Hold: elapsed in [500, 2500)ms → I_max
    g_mock_millis = 1000 + 500 + 1000;   // mid-hold
    g_mock_micros = 3000000;
    advanceTrapProfile();
    check(fabsf(trapCmdA - 5.0f) < 1e-3f,
          "trap: hold phase holds at Imax");
    check(trapPhase == TRAP_HOLD, "trap: phase is HOLD");

    // ── Ramp-down: tHoldEnd = 500+2000 = 2500ms; at 2500+250=2750ms (half the down-ramp), ~half Imax.
    g_mock_millis = 1000 + 2750;
    g_mock_micros = 4000000;
    advanceTrapProfile();
    check(fabsf(trapCmdA - 2.5f) < 0.05f,
          "trap: ramp-down commanded current decreases (~2.5A at down-ramp midpoint)");
    check(trapPhase == TRAP_RAMP_DOWN, "trap: phase is RAMP_DOWN");

    // ── Natural completion: tEnd = 2500+500 = 3000ms.
    g_mock_millis = 1000 + 3000;
    g_mock_micros = 5000000;
    vesc.reset();
    advanceTrapProfile();
    check(trapProfileActive == false,
          "trap: profile deactivates on natural completion");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "trap: natural completion flushes vesc.setCurrent(0)");
    check(manualMotorMode == MOTOR_TEST_OFF,
          "trap: natural completion clears manualMotorMode (haltMotorOutput symmetry)");
}

static void test_trap_peak_clamp_and_negative() {
    test_group("Trapezoid profile — peak bounded by TRAP_I_ABS_MAX (not MOTOR_I_CMD_MAX); negative accepted");
    reset_test_state();

    // A peak ABOVE MOTOR_I_CMD_MAX (10A since 2026-08-13) is accepted un-clamped — phase current is
    // not bus current, so the source-budget ceiling does not apply here. Only TRAP_I_ABS_MAX (ESC
    // rating, 25A) bounds it. 16A is chosen so it stays above MOTOR_I_CMD_MAX with headroom (not
    // just equal to it, which would pass this check for the wrong reason) while staying below
    // TRAP_I_ABS_MAX.
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 0;
    Serial.rx_queue.push('T');
    doState98();
    g_mock_millis = 1000;
    feed_serial_line(" 16 0 16");   // 16A > MOTOR_I_CMD_MAX(10), < TRAP_I_ABS_MAX(25); rampMs = 1000
    doState98();
    check(trapProfileActive == true && fabsf(trapImax - 16.0f) < 1e-4f,
          "trap: 16A peak accepted un-clamped (above the 10A MOTOR_I_CMD_MAX budget)");
    // ...and the VESC actually receives more than MOTOR_I_CMD_MAX: mid-ramp at t=750ms → 12A.
    g_mock_millis = 1000 + 750;
    g_mock_micros = 1000000;
    vesc.reset();
    advanceTrapProfile();
    check(!vesc.current_calls.empty() && fabsf(vesc.last_current - 12.0f) < 0.05f,
          "trap: commanded current above MOTOR_I_CMD_MAX reaches the VESC (12A sent)");

    // Positive peak beyond the ESC rating saturates to +TRAP_I_ABS_MAX.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 0;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 999 0 10");
    doState98();
    check(trapProfileActive == true && fabsf(trapImax - TRAP_I_ABS_MAX) < 1e-4f,
          "trap: peak clamped to +TRAP_I_ABS_MAX (ESC rating)");

    // Negative peak is accepted (braking/regen test) and ramps negative.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 1000;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" -3 0 6");   // rate 6A/s -> rampMs = |−3|/6*1000 = 500ms
    doState98();
    check(trapProfileActive == true && fabsf(trapImax + 3.0f) < 1e-4f,
          "trap: negative peak accepted and stored signed");

    g_mock_millis = 1000 + 250;   // half the 500ms ramp
    g_mock_micros = 1000000;
    advanceTrapProfile();
    check(trapCmdA < 0.0f && fabsf(trapCmdA + 1.5f) < 0.05f,
          "trap: negative peak ramps toward a negative commanded current (~-1.5A at midpoint)");

    // Negative peak beyond the ESC rating saturates to -TRAP_I_ABS_MAX.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 0;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" -999 0 10");
    doState98();
    check(trapProfileActive == true && fabsf(trapImax + TRAP_I_ABS_MAX) < 1e-4f,
          "trap: negative peak clamped to -TRAP_I_ABS_MAX");
}

static void test_trap_degenerate_inputs_refused() {
    test_group("Trapezoid profile — degenerate parameter lines refused outright");
    reset_test_state();

    // Zero peak (below the 1e-3 threshold) refuses the whole line.
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 0 2 10");
    doState98();
    check(pendingInput == PEND_NONE && trapProfileActive == false,
          "trap: zero peak refused — profile does not start");

    // Negative hold time refuses the line.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 5 -1 10");
    doState98();
    check(pendingInput == PEND_NONE && trapProfileActive == false,
          "trap: negative hold refused — profile does not start");

    // Zero and negative rate refuse the line (rate is a divisor).
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 5 0 0");
    doState98();
    check(pendingInput == PEND_NONE && trapProfileActive == false,
          "trap: zero rate refused — profile does not start");

    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 5 0 -1");
    doState98();
    check(pendingInput == PEND_NONE && trapProfileActive == false,
          "trap: negative rate refused — profile does not start");

    // Too few values on the line refuses (missing rate).
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 5 2");
    doState98();
    check(pendingInput == PEND_NONE && trapProfileActive == false,
          "trap: incomplete line (2 of 3 values) refused — profile does not start");

    // Bare 'T' + newline (the old line-terminal trap): empty buffer cancels, and crucially the
    // digits typed on the NEXT line are ordinary commands again — no half-armed chain remains.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('T');
    doState98();
    Serial.rx_queue.push('\n');
    doState98();
    check(pendingInput == PEND_NONE && trapProfileActive == false,
          "trap: bare \"T\\n\" cancels cleanly (empty parameter line)");
}

static void test_trap_nonnumeric_cancels_chain() {
    test_group("Trapezoid profile — non-numeric key mid-line cancels the pending entry");
    reset_test_state();

    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('T');
    doState98();
    // Partial line typed ("5 2"), then a non-numeric key before the newline.
    for (const char* p = " 5 2"; *p; ++p) { Serial.rx_queue.push(*p); doState98(); }
    check(pendingInput == PEND_TRAP_PARAMS, "trap: mid-line, parameter entry still pending");

    // 'S' (status, harmless side effect) cancels the prompt and is then handled as a command.
    Serial.rx_queue.push('S');
    doState98();
    check(pendingInput == PEND_NONE,
          "trap: non-numeric key clears the pending prompt");
    check(inputBufIdx == 0,
          "trap: non-numeric key clears the input buffer");
    check(trapProfileActive == false,
          "trap: non-numeric mid-line cancel never starts a profile");
}

static void test_trap_stop_toggle() {
    test_group("Trapezoid profile — 'T' while running stops it (switches left as-is)");
    reset_test_state();

    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE]   = HIGH;
    g_pin_value[REGEN_ENABLE]     = HIGH;   // set so we can confirm it's untouched
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    trapProfileActive = true;
    trapImax = 3.0f; trapCmdA = 2.0f;
    manualMotorMode = MOTOR_TEST_CURRENT;   // haltMotorOutput() should clear this
    vesc.reset();

    Serial.rx_queue.push('T');
    doState98();

    check(trapProfileActive == false,
          "trap: 'T' toggles a running profile off");
    check(fabsf(trapCmdA) < 1e-9f,
          "trap: 'T' stop zeroes trapCmdA");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "trap: 'T' stop flushes vesc.setCurrent(0)");
    check(manualMotorMode == MOTOR_TEST_OFF,
          "trap: 'T' stop clears manualMotorMode via haltMotorOutput()");
    // Documented design choice: unlike 'D'/'R', 'T' does NOT call safeAllSwitches() — the
    // operator's configured power paths are an input to the test, not state to be reset.
    check(g_pin_value[REGEN_ENABLE] == HIGH && g_pin_value[FC_CHARGE_ENABLE] == HIGH,
          "trap: 'T' stop leaves path switches untouched (REGEN/FC_CHARGE still HIGH)");
    check(g_pin_value[MOT_PWR_ENABLE] == HIGH,
          "trap: 'T' stop leaves MOT_PWR_ENABLE untouched");
}

// ─── 'X' universal stop: cancels ANY running profile, not just the manual modes ───────────────
static void test_universal_stop_x() {
    test_group("'X' universal stop — cancels any running profile + manual motor");

    // Trapezoid running: X stops it, motor zeroed, switches deliberately NOT parked (mirrors the
    // 'T' stop path's documented design choice).
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE]   = HIGH;
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    trapProfileActive = true;
    trapImax = 3.0f; trapCmdA = 2.0f;
    vesc.reset();
    Serial.rx_queue.push('X');
    doState98();
    check(trapProfileActive == false, "X: cancels a running trapezoid profile");
    check(fabsf(trapCmdA) < 1e-9f, "X: zeroes trapCmdA");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "X: flushes vesc.setCurrent(0) with a trapezoid running");
    check(g_pin_value[MOT_PWR_ENABLE] == HIGH && g_pin_value[FC_CHARGE_ENABLE] == HIGH,
          "X: trapezoid stop leaves path switches untouched (T semantics)");

    // Drive cycle running: X stops it AND parks the switches (mirrors the 'D' stop path).
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_pin_value[REGEN_ENABLE]   = HIGH;
    driveCycleActive = true;
    vesc.reset();
    Serial.rx_queue.push('X');
    doState98();
    check(driveCycleActive == false, "X: cancels a running drive cycle");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "X: flushes vesc.setCurrent(0) with a drive cycle running");
    check(g_pin_value[REGEN_ENABLE] == LOW,
          "X: drive-cycle stop parks the path switches (safeAllSwitches, D semantics)");

    // Power-share profile running: X stops it, parks switches, resets the setpoint like 'R' stop.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    powerShareProfileActive = true;
    power_share_setpoint    = 0.8f;
    manualMotorMode         = MOTOR_TEST_CURRENT;
    vesc.reset();
    Serial.rx_queue.push('X');
    doState98();
    check(powerShareProfileActive == false, "X: cancels a running power-share profile");
    check(fabsf(power_share_setpoint - 0.5f) < 1e-6f,
          "X: share-profile stop resets power_share_setpoint to 0.5 (R semantics)");
    check(manualMotorMode == MOTOR_TEST_OFF, "X: clears manualMotorMode");
    check(powerBalanceLive == false, "X: clears powerBalanceLive");
}

static void test_trap_q_exit_clears_state() {
    test_group("Trapezoid profile — 'Q' during a run clears trapProfileActive and staging");
    reset_test_state();

    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    trapProfileActive = true;
    trapImax = 4.0f; trapCmdA = 1.0f;
    pendingInput = PEND_TRAP_PARAMS;   // simulate a half-typed NEXT parameter line lingering
    vesc.reset();

    Serial.rx_queue.push('Q');
    doState98();

    check(trapProfileActive == false,
          "trap: 'Q' exit clears trapProfileActive");
    check(fabsf(trapCmdA) < 1e-9f,
          "trap: 'Q' exit zeroes trapCmdA");
    check(pendingInput == PEND_NONE,
          "trap: 'Q' exit drops the half-typed parameter line too");
    check(mainState == 1,
          "trap: 'Q' exit returns to State 1");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "trap: 'Q' exit flushes vesc.setCurrent(0)");
}

static void test_trap_vescwatch_suppressed() {
    test_group("Trapezoid profile — pollVescWatch() suppressed while trapProfileActive");
    reset_test_state();

    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    trapProfileActive = true;
    trapImax = 1.0f; trapRateAps = 1.0f; trapRampMs = 1000; trapHoldMs = 0;
    trapPhase = TRAP_RAMP_UP;
    trapStartMs = 0;
    vescWatchActive = true;
    lastVescWatchMs = 0;
    g_mock_millis = VESC_WATCH_PERIOD_MS + 1;   // period elapsed — would poll if not suppressed
    g_mock_micros = 1000000;
    vesc.reset();

    doState98();

    check(vesc.getValues_calls == 0,
          "trap: pollVescWatch() does not call getVescValues() while trapProfileActive");
}

// ═══════════════════════════════════════════════════════════════════════════════
// SD bench logging (logOpenForProfile / logSampleTick / logDrainTick / 'K')
// ═══════════════════════════════════════════════════════════════════════════════
// The contract under test is the ON-CARD BYTE STREAM plus the lifecycle guarantees, not just the
// flags: the host decoder (tools/decode_benchlog.py) walks fixed-size records, so a shifted field
// or a missing trailer silently mis-decodes an entire bench session. Every case therefore asserts
// against g_sd_state.files (the raw capture) rather than against logRecordCount alone — which is
// also the only honest way to check the counters, since logFinishFile() zeroes them at close.

// Byte offsets of the record fields (mirrors BenchLogRecord; kept literal so a struct reordering
// in the .ino fails these tests instead of silently following along).
#define REC_OFF_T_US        0
#define REC_OFF_SHARE_SP    4
#define REC_OFF_SHARE_ACT   8
#define REC_OFF_V_SP       12
#define REC_OFF_V_ACT      16
#define REC_OFF_I_FC       20
#define REC_OFF_I_BATT     24
#define REC_OFF_GFC        28
#define REC_OFF_GBT        32
#define REC_OFF_V_BUS      36
#define REC_OFF_I_CMD      40
// Format v3 (fw v5, 2026-08-12): the four source/charger/regen rails, added after I_cmd.
#define REC_OFF_V_FC       44
#define REC_OFF_V_BATT     48
#define REC_OFF_V_CHG      52
#define REC_OFF_V_RGN      56
#define REC_OFF_FAULTS     60
#define REC_OFF_PS_PHASE   62
#define REC_OFF_DC_PHASE   63
#define REC_OFF_TRAP_PHASE 64
#define REC_OFF_FLAGS      65
// exp[66..67] are the pad bytes
// Format v5 (fw v11, BLG record 76 B): appended after the pad, so every offset above is
// unchanged.
#define REC_OFF_U_UNSAT    68
#define REC_OFF_DRIVE_X0   72

#define LOG_HDR_SIZE 32u

// Little-endian field read out of a captured file (the host is LE, same as the Teensy).
template <typename T>
static T sd_le(const std::string& b, size_t off) {
    T v{};
    if (off + sizeof(T) <= b.size()) memcpy(&v, b.data() + off, sizeof(T));
    return v;
}

static const std::string* sd_file(const std::string& name) {
    auto it = g_sd_state.files.find(name);
    return (it == g_sd_state.files.end()) ? nullptr : &it->second;
}

// Name of the one and only .BLG the case produced; empty when there is not exactly one (so a
// double-open regression shows up as an empty name rather than as a silently-picked first file).
static std::string sd_only_log_name() {
    std::string found;
    int n = 0;
    for (const auto& kv : g_sd_state.files) {
        if (kv.first.size() == 10 && kv.first.compare(6, 4, ".BLG") == 0) { found = kv.first; n++; }
    }
    return (n == 1) ? found : std::string();
}

// Pump logDrainTick() until a pending close finishes. Deliberately does NOT advance millis():
// LOG_CLOSE_DEADLINE_MS must stay un-expired, so a close that only completed because the deadline
// fired would surface as a leftover ring rather than passing as a clean drain.
static int sd_drain_until_closed(int maxTicks = 5000) {
    int n = 0;
    while ((logActive || logCloseRequested) && n < maxTicks) { logDrainTick(); n++; }
    return n;
}

// Same, for a close pending in State 99: the real loop() runs doState99() before logDrainTick(),
// and since review 2026-08-10 FW-R1-F1 the drain is deliberately gated until the teardown has
// fully latched (state99Phase == 3). Advancing millis is therefore REQUIRED here — the teardown's
// dwells are millis()-based — but the tick budget stays far below LOG_CLOSE_DEADLINE_MS, so a
// close that only completed because the deadline fired would still surface as a leftover ring.
static int sd_drain_until_closed_state99(int maxTicks = 200) {
    int n = 0;
    while ((logActive || logCloseRequested) && n < maxTicks) {
        doState99();
        logDrainTick();
        g_mock_millis += 1;
        n++;
    }
    return n;
}

// One State-98 tick that also advances the 1 kHz sample clock and services the drain, i.e. what
// loop() + doState98() do together for one millisecond of a real bench run.
static void sd_run_ms(int ms, bool drain = true) {
    for (int i = 0; i < ms; i++) {
        g_mock_micros += POWER_BAL_PERIOD_US;
        g_mock_millis += 1;
        doState98();
        if (drain) logDrainTick();
    }
}

// 'R' power-share run start through the real keypress path (MOT_PWR + a standing motor command
// are its documented preconditions).
static void sd_start_share_run() {
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    Serial.rx_queue.push('R');
    doState98();
}

// ─── 1. Natural completion: header, records, trailer, file closed ────────────
static void test_sdlog_lifecycle_natural_completion() {
    test_group("SD log: 'T' run to natural completion writes a complete, closed file");
    reset_test_state();

    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 0;
    g_mock_micros = 0;

    Serial.rx_queue.push('T');
    doState98();
    g_mock_millis = 1000;
    feed_serial_line(" 5 0 100");   // Imax 5A, hold 0s, 100A/s → 50ms up + 50ms down = 100ms total
    check(trapProfileActive == true,
          "SD lifecycle: the 'T' trapezoid started, so a TP log should have been opened");
    check(logActive == true,
          "SD lifecycle: opening a profile log arms sampling (logActive set)");
    check(std::string(logFileName) == "TP0001.BLG",
          "SD lifecycle: the first trapezoid run of a session opens TP0001.BLG");

    // Run the profile out. Capture the high-water record count: logFinishFile() zeroes the
    // counters at close, so the trailer is the only place the total survives.
    uint32_t expectedRecords = 0;
    for (int i = 0; i < 140; i++) {
        sd_run_ms(1);
        if (logRecordCount > expectedRecords) expectedRecords = logRecordCount;
    }
    check(trapProfileActive == false,
          "SD lifecycle: the trapezoid reached natural completion inside the run window");
    sd_drain_until_closed();

    check(expectedRecords == 100,
          "SD lifecycle: a 100 ms profile at POWER_BAL_PERIOD_US yields exactly 100 records");
    check(logActive == false && logCloseRequested == false,
          "SD lifecycle: natural completion leaves the logger idle (not active, no close pending)");
    check(logFile.isOpen() == false,
          "SD lifecycle: the file handle is closed after the drain finishes the trailer");
    check(g_sd_state.truncate_calls == 1,
          "SD lifecycle: close truncates the pre-allocation exactly once");

    std::string name = sd_only_log_name();
    check(name == "TP0001.BLG",
          "SD lifecycle: exactly one .BLG file exists on the card after the run");
    const std::string* f = sd_file("TP0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * expectedRecords + LOG_REC_SIZE,
          "SD lifecycle: file size is header + LOG_REC_SIZE*N records + one LOG_REC_SIZE trailer");

    if (f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE) {
        check(f->compare(0, 4, "BLG1") == 0,
              "SD lifecycle: the header opens with the 'BLG1' magic");
        check((uint8_t)(*f)[4] == 5,
              "SD lifecycle: the header declares format version 5 (fw v11; record grew to 76B "
              "with the appended u_unsat/drive_x0 fields — the profile-parameter block is "
              "unchanged from v4)");
        check((uint8_t)(*f)[5] == (uint8_t)LOG_REC_SIZE,
              "SD lifecycle: the header declares a 76-byte record size");
        check((uint8_t)(*f)[6] == LOG_TYPE_TP,
              "SD lifecycle: the header profile bitmask is LOG_TYPE_TP for a 'T' run");
        check(sd_le<uint16_t>(*f, 18) == (uint16_t)FW_VERSION,
              "SD lifecycle: the header stamps FW_VERSION at offset 18");
        // v4 profile-parameter block: a 'T' run carries amp-only (paramFlags bit0), amp = the
        // committed trapImax, b field left at 0.
        check((uint8_t)(*f)[7] == 0x01,
              "SD lifecycle: v4 header paramFlags == 0x01 (amp valid, b not) for a 'T' run");
        check(fabsf(sd_le<float>(*f, 20) - 5.0f) < 1e-6f,
              "SD lifecycle: v4 header amp field (offset 20) carries the committed Imax (5.0 A)");
        check(sd_le<float>(*f, 24) == 0.0f,
              "SD lifecycle: v4 header b field (offset 24) stays 0.0 for a run type with no bound");
        check((uint8_t)(*f)[28] == 0 && (uint8_t)(*f)[29] == 0 &&
              (uint8_t)(*f)[30] == 0 && (uint8_t)(*f)[31] == 0,
              "SD lifecycle: v4 header's trailing reserved bytes (28-31) are zero-filled");

        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * expectedRecords;
        check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu,
              "SD lifecycle: the last record carries the 0xFFFFFFFF trailer sentinel");
        check(sd_le<uint32_t>(*f, tr + 4) == expectedRecords,
              "SD lifecycle: the trailer's total-record count matches the records written");
        check(sd_le<uint32_t>(*f, tr + 8) == 0u,
              "SD lifecycle: a drained run drops no samples");
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_COMPLETE,
              "SD lifecycle: the trailer close reason is LOG_CLOSE_COMPLETE for a natural end");
    }
    check(Serial.tx_contains("[SD] closed: TP0001.BLG"),
          "SD lifecycle: the close prints the one-shot '[SD] closed' summary line");
}

// ─── 2. Stop-toggle / 'X' / 'Q' all close and flush the file ─────────────────
static void test_sdlog_lifecycle_stop_x_q() {
    test_group("SD log: stop-toggle, 'X' and 'Q' each close the file with their own reason");

    // ── (a) 'R' pressed again → LOG_CLOSE_STOP ──────────────────────────────
    reset_test_state();
    sd_start_share_run();
    sd_run_ms(10);
    uint32_t recs = logRecordCount;
    check(recs > 0, "SD stop: the share profile logged samples before the stop key");
    Serial.rx_queue.push('R');
    doState98();
    check(powerShareProfileActive == false && logActive == false && logCloseRequested == true,
          "SD stop: the 'R' stop-toggle requests a close without doing card I/O in the handler");
    sd_drain_until_closed();
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
              "SD stop: the stopped run's file holds every buffered record plus the trailer");
        if (f) {
            size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
            check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_STOP,
                  "SD stop: the trailer records LOG_CLOSE_STOP as the close reason");
        }
    }

    // ── (b) 'X' universal stop → LOG_CLOSE_X ────────────────────────────────
    reset_test_state();
    sd_start_share_run();
    sd_run_ms(10);
    recs = logRecordCount;
    Serial.rx_queue.push('X');
    doState98();
    check(logCloseRequested == true && logActive == false,
          "SD 'X': the universal stop requests the log close alongside the motor stop");
    sd_drain_until_closed();
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
              "SD 'X': the file is complete after the universal stop drains");
        if (f) {
            size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
            check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_X,
                  "SD 'X': the trailer records LOG_CLOSE_X as the close reason");
        }
    }

    // ── (c) 'Q' exit → LOG_CLOSE_Q, and the drain COMPLETES from State 1 ────
    // This is the reason logDrainTick() lives in loop() and not in doState98(): after 'Q' the
    // state machine has already left test mode, so a doState98()-hosted drain would strand the
    // file half-written with no trailer.
    reset_test_state();
    sd_start_share_run();
    sd_run_ms(10, /*drain=*/false);   // leave every record in the ring, undrained
    recs = logRecordCount;
    check(logRingCount == recs,
          "SD 'Q': the run's records are still buffered in the ring at the moment of exit");
    Serial.rx_queue.push('Q');
    doState98();
    check(mainState == 1,
          "SD 'Q': the exit key returns the state machine to Idle");
    check(logCloseRequested == true && logFile.isOpen() == true,
          "SD 'Q': the exit only flags the close — the file is still open on leaving State 98");
    int ticks = sd_drain_until_closed();
    check(ticks > 0 && logFile.isOpen() == false,
          "SD 'Q': the loop-level drain finishes and closes the file from State 1, outside State 98");
    check(mainState == 1,
          "SD 'Q': draining the log from Idle does not disturb the state machine");
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
              "SD 'Q': every buffered record reaches the card after the exit");
        if (f) {
            size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
            check(sd_le<uint32_t>(*f, tr + 4) == recs,
                  "SD 'Q': the trailer total matches the records captured before the exit");
            check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_Q,
                  "SD 'Q': the trailer records LOG_CLOSE_Q as the close reason");
        }
    }
}

// ─── 3. Fault path: the file survives the State-99 transition ────────────────
static void test_sdlog_lifecycle_fault_path() {
    test_group("SD log: a fault mid-run closes the file from State 99 with the cause captured");
    reset_test_state();

    sd_start_share_run();
    sd_run_ms(12, /*drain=*/false);
    uint32_t recs = logRecordCount;
    check(recs > 0 && logActive == true,
          "SD fault: the share profile was logging when the fault is injected");

    triggerFault(FAULT_OC_FC, ERR_OC_FC);

    check(mainState == 99,
          "SD fault: triggerFault() still latches State 99 with the logger attached");
    check(error_code == ERR_OC_FC && (fault_flags & FAULT_OC_FC) && (fault_flags & FAULT_ERROR),
          "SD fault: the error latch and fault flags are unaffected by the log close request");
    check(logActive == false && logCloseRequested == true && logFile.isOpen() == true,
          "SD fault: the fault path only flags the close — no card I/O happens in triggerFault()");

    // The real loop() runs doState99() alongside the drain; the drain is gated until the teardown
    // has fully latched (FW-R1-F1), so this must pump both — see sd_drain_until_closed_state99().
    int ticks = sd_drain_until_closed_state99();
    check(ticks > 0 && logFile.isOpen() == false,
          "SD fault: the loop-level drain finishes the file while State 99 is latched");
    check(mainState == 99 && error_code == ERR_OC_FC,
          "SD fault: the error stays latched in State 99 after the log is closed");

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
          "SD fault: the pre-fault records plus the trailer all reach the card");
    if (f) {
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
        check(sd_le<uint32_t>(*f, tr + 4) == recs,
              "SD fault: the trailer total matches the records captured before the fault");
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_FAULT,
              "SD fault: the trailer close reason is LOG_CLOSE_FAULT");
        check((uint8_t)(*f)[tr + 13] == (uint8_t)ERR_OC_FC,
              "SD fault: the trailer carries the latched error_code so the cause is in the file");
    }
}

// ─── 4. No card: warn exactly once, never retry, profile unaffected ──────────
static void test_sdlog_no_card() {
    test_group("SD log: with no card the warn fires once and the profile runs identically");
    reset_test_state();

    g_sd_state.card_present = false;

    sd_start_share_run();
    check(powerShareProfileActive == true,
          "SD no-card: the power-share profile starts normally with no card fitted");
    check(logActive == false && sdAvailable == false && sdInitTried == true,
          "SD no-card: the failed probe latches sdInitTried and leaves logging disarmed");
    check(Serial.tx_count("[SD] no card") == 1,
          "SD no-card: exactly one '[SD] no card' warning is printed at the first profile start");
    check(g_sd_state.begin_calls == 1,
          "SD no-card: the card is probed exactly once");

    sd_run_ms(10);
    check(logRecordCount == 0 && logRingCount == 0,
          "SD no-card: no records are buffered while logging is disabled");
    check(g_sd_state.files.empty(),
          "SD no-card: nothing is written to the card");

    // Stop and start a second profile: the latch must suppress both the retry and the warn.
    Serial.rx_queue.push('R');
    doState98();
    Serial.tx_clear();
    sd_start_share_run();
    check(powerShareProfileActive == true,
          "SD no-card: a second profile starts normally after the first no-card run");
    check(Serial.tx_count("[SD] no card") == 0,
          "SD no-card: the second profile start does not repeat the warning");
    check(g_sd_state.begin_calls == 1,
          "SD no-card: the second profile start does not re-probe the card");
}

// ─── 5. Ring overflow under a stalled card: drop-newest + counted ────────────
static void test_sdlog_overflow_drop_count() {
    test_group("SD log: a stalled card drops the newest samples and counts them in the trailer");
    reset_test_state();

    sd_start_share_run();
    Serial.tx_clear();
    g_sd_state.busy_ticks = 1000000;   // card wedged: every drain tick bails on isBusy()

    // Pump more samples than the ring can hold. Nothing here may block or stall the profile —
    // that is the whole point of the drop-newest policy.
    sd_run_ms(1200);

    check(logRingCount == LOG_RING_RECORDS,
          "SD overflow: the ring fills to exactly its 1024-record capacity and never beyond");
    check(logRecordCount == LOG_RING_RECORDS,
          "SD overflow: only the records that fit the ring are counted as committed");
    check(logDroppedCount > 0,
          "SD overflow: samples that found the ring full are counted as dropped");
    check(logRecordCount + logDroppedCount == 1201u,
          "SD overflow: committed plus dropped accounts for every 1 kHz sample in the window");
    check(powerShareProfileActive == true && mainState == 98,
          "SD overflow: the profile keeps running through the card stall (the loop never blocks)");
    // The 1200 ms window sits inside the profile's 3000 ms phase 0, so the proof that the phase
    // machine kept ticking is its 500 ms status snapshot, not a phase-index change.
    check(Serial.tx_count("[PS] t=") >= 2,
          "SD overflow: the profile's periodic status snapshots keep printing through the stall");

    uint32_t total   = logRecordCount;
    uint32_t dropped = logDroppedCount;

    g_sd_state.busy_ticks = 0;   // card recovers
    Serial.rx_queue.push('X');
    doState98();
    sd_drain_until_closed();

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * total + LOG_REC_SIZE,
          "SD overflow: the whole ring is flushed once the card recovers");
    if (f) {
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * total;
        check(sd_le<uint32_t>(*f, tr + 4) == total,
              "SD overflow: the trailer total matches the committed record count");
        check(sd_le<uint32_t>(*f, tr + 8) == dropped,
              "SD overflow: the trailer reports the dropped-sample count so the gap is visible");
    }
}

// ─── 6. Golden record schema: byte-exact field layout (format v5, fw v11) ────
static void test_sdlog_record_schema() {
    test_group("SD log: one record's 76 bytes match the documented v5 field layout exactly");
    reset_test_state();

    // Open directly (not via a profile key) so the sample below is taken from values this test
    // owns, with no controller tick in between to overwrite them.
    g_mock_millis = 5000;
    g_mock_micros = 50000;
    logOpenForProfile(LOG_TYPE_PS);
    check(logActive == true, "SD schema: the log opened for a PS-type run");

    power_share_setpoint      = 0.625f;
    I_fc                      = 3.0f;      // share_act = 3/(3+1) = 0.75 exactly
    I_batt                    = 1.0f;
    v_setpoint                = 1.5f;
    v_actual                  = 1.25f;
    droop_gain_FC_actual      = 0.4f;
    droop_gain_BT_actual      = 0.6f;
    V_bus                     = 16.5f;
    current                   = 2.25f;
    // Format v3 (fw v5): distinct sentinel values for the four new rails so a swapped-offset
    // regression shows up as a specific field mismatch, not a coincidental pass.
    V_fc                       = 11.1f;
    V_batt                     = 7.7f;
    V_chg                      = 13.3f;
    V_rgn                      = 9.9f;
    fault_flags               = 0x0012;
    powerShareProfileActive   = true;
    powerShareProfilePhaseIdx = 3;
    driveCycleActive          = false;
    trapProfileActive         = false;
    velocityChainCalibratedFlag = true;

    g_mock_micros = 123456;
    logSampleTick();
    check(logRecordCount == 1 && logRingCount == 1,
          "SD schema: exactly one record is committed to the ring");
    logDrainTick();

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE,
          "SD schema: the card holds the 32-byte header followed by one 76-byte record");
    if (f == nullptr || f->size() < LOG_HDR_SIZE + LOG_REC_SIZE) return;

    // ── Header ──────────────────────────────────────────────────────────────
    check(f->compare(0, 4, "BLG1") == 0 && (uint8_t)(*f)[4] == 5 &&
          (uint8_t)(*f)[5] == (uint8_t)LOG_REC_SIZE && (uint8_t)(*f)[6] == LOG_TYPE_PS,
          "SD schema: the header carries magic, version 5, record size 76 and the PS type bit");
    check(sd_le<uint32_t>(*f, 8) == 5000u && sd_le<uint32_t>(*f, 12) == 50000u,
          "SD schema: the header timebase is the millis()/micros() pair at open");
    check(sd_le<uint16_t>(*f, 16) == (uint16_t)(K_DROOP * 1000.0f + 0.5f),
          "SD schema: the header stores K_DROOP in milliohms for the decoder");
    check(sd_le<uint16_t>(*f, 18) == (uint16_t)FW_VERSION,
          "SD schema: the header stamps FW_VERSION at offset 18");
    // A bare PS run (LOG_TYPE_PS alone) matches none of the v4 profile-parameter branches
    // (Y = PS|DC, W = PS|TP, T = lone TP), so paramFlags stays 0 and both the amp/b fields at
    // 20-27 and the genuinely reserved 28-31 all read zero -- bytes 20-31 are zero-filled as a
    // block for this run type specifically, not because 20-27 are architecturally reserved.
    check(f->compare(20, 12, std::string(12, '\0')) == 0,
          "SD schema: bytes 20-31 are zero-filled for a PS run (paramFlags=0 -> amp/b fields "
          "unused, plus the always-reserved 28-31)");
    check((uint8_t)(*f)[7] == 0x00,
          "SD schema: v4 header paramFlags is 0x00 for a PS run (no amp/b parameter)");

    // ── Record: build the expected LOG_REC_SIZE (76, v5) bytes independently, then memcmp ──
    uint8_t exp[LOG_REC_SIZE];
    memset(exp, 0, sizeof(exp));
    uint32_t t_us = 123456u;    memcpy(exp + REC_OFF_T_US,      &t_us, 4);
    float fv;
    fv = 0.625f;  memcpy(exp + REC_OFF_SHARE_SP,  &fv, 4);
    fv = 0.75f;   memcpy(exp + REC_OFF_SHARE_ACT, &fv, 4);
    fv = 1.5f;    memcpy(exp + REC_OFF_V_SP,      &fv, 4);
    fv = 1.25f;   memcpy(exp + REC_OFF_V_ACT,     &fv, 4);
    fv = 3.0f;    memcpy(exp + REC_OFF_I_FC,      &fv, 4);
    fv = 1.0f;    memcpy(exp + REC_OFF_I_BATT,    &fv, 4);
    fv = 0.4f;    memcpy(exp + REC_OFF_GFC,       &fv, 4);
    fv = 0.6f;    memcpy(exp + REC_OFF_GBT,       &fv, 4);
    fv = 16.5f;   memcpy(exp + REC_OFF_V_BUS,     &fv, 4);
    fv = 2.25f;   memcpy(exp + REC_OFF_I_CMD,     &fv, 4);
    fv = 11.1f;   memcpy(exp + REC_OFF_V_FC,      &fv, 4);
    fv = 7.7f;    memcpy(exp + REC_OFF_V_BATT,    &fv, 4);
    fv = 13.3f;   memcpy(exp + REC_OFF_V_CHG,     &fv, 4);
    fv = 9.9f;    memcpy(exp + REC_OFF_V_RGN,     &fv, 4);
    uint16_t ff = 0x0012;       memcpy(exp + REC_OFF_FAULTS, &ff, 2);
    exp[REC_OFF_PS_PHASE]   = 3;      // the PS profile is running, at phase 3
    exp[REC_OFF_DC_PHASE]   = 0xFF;   // drive cycle not running
    exp[REC_OFF_TRAP_PHASE] = 0xFF;   // trapezoid not running
    // bit0 profile driving powerBalance, bit1 velocity chain OK, bit4/bit5 the fw v11 build-
    // identity bits -- both set because the default build has USE_YOULA_DRIVE_CONTROLLER=1 and
    // USE_YOULA_SHARE_CONTROLLER=1.
    exp[REC_OFF_FLAGS]      = 0x03 | 0x10 | 0x20;
    // exp[66..67] stay zero (pad)
    // Format v5 tail: reset_test_state() called resetDriveControlState() and no controller step
    // has run since, so the Youla build's held pre-clamp capture and integrator state are both
    // still exactly zero.
    fv = 0.0f;    memcpy(exp + REC_OFF_U_UNSAT,  &fv, 4);
    fv = 0.0f;    memcpy(exp + REC_OFF_DRIVE_X0, &fv, 4);

    check(memcmp(f->data() + LOG_HDR_SIZE, exp, LOG_REC_SIZE) == 0,
          "SD schema: the written record is byte-identical to the expected 76-byte v5 layout");

    // Field-level checks so a failure above localises instead of just saying "bytes differ".
    check(sd_le<uint32_t>(*f, LOG_HDR_SIZE + REC_OFF_T_US) == 123456u,
          "SD schema: t_us at offset 0 is the micros() value at the sample");
    check(sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_SHARE_ACT) == 0.75f,
          "SD schema: share_act at offset 8 is |I_fc|/(|I_fc|+|I_batt|)");
    check(sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_V_FC) == 11.1f,
          "SD schema: V_fc (format v3) lands at offset 44, straight from updateSensors()");
    check(sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_V_BATT) == 7.7f,
          "SD schema: V_batt (format v3) lands at offset 48");
    check(sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_V_CHG) == 13.3f,
          "SD schema: V_chg (format v3) lands at offset 52");
    check(sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_V_RGN) == 9.9f,
          "SD schema: V_rgn (format v3) lands at offset 56");
    check(sd_le<uint16_t>(*f, LOG_HDR_SIZE + REC_OFF_FAULTS) == 0x0012,
          "SD schema: fault_flags at offset 60 (shifted +16 by the four new v3 fields) is the "
          "live 16-bit fault word");
    check((uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_PS_PHASE] == 3 &&
          (uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_DC_PHASE] == LOG_PHASE_NONE &&
          (uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_TRAP_PHASE] == LOG_PHASE_NONE,
          "SD schema: the three phase bytes are independent, 0xFF for the inactive profiles");
    check((uint8_t)(*f)[LOG_HDR_SIZE + 66] == 0 && (uint8_t)(*f)[LOG_HDR_SIZE + 67] == 0,
          "SD schema: the two pad bytes (now at 66-67) are zero-filled");
}

// ─── 6a-v4. BLG header v4: the profile-parameter block (fw v6, 2026-08-12) ──────────────────
// A decoded run's share/current traces are uninterpretable without the operator scale the run
// was started with (Imax/Vmax) and the committed share-clip bound b -- previously typed at the
// prompt and lost to the scrollback. logOpenForProfile() derives them HERE from typeMask plus
// the profile globals every start function commits before opening the log, so this test drives
// each run type by setting exactly those globals and opening directly (bypassing the keypress
// path, which is covered elsewhere) to pin the header <-> typeMask mapping byte-for-byte.
static void test_sdlog_header_v4_profile_params() {
    test_group("SD log header v4: paramFlags/amp/b block, one case per run type (typeMask -> header)");

    // ── 'W' (LOG_TYPE_PS|LOG_TYPE_TP): amp = committed Imax, b = committed bound, flags=0x03.
    reset_test_state();
    wProfileImax    = 7.5f;
    wProfileBoundLo = 0.22f;
    logOpenForProfile(LOG_TYPE_PS | LOG_TYPE_TP);
    {
        const std::string* f = sd_file("WP0001.BLG");
        check(f != nullptr && f->size() >= LOG_HDR_SIZE, "v4 hdr/W: the header was written");
        if (f) {
            check((uint8_t)(*f)[4] == 5, "v4 hdr/W: format version 5 (fw v11 BLG bump)");
            check((uint8_t)(*f)[7] == 0x03, "v4 hdr/W: paramFlags == 0x03 (amp AND b valid)");
            check(fabsf(sd_le<float>(*f, 20) - 7.5f) < 1e-6f,
                  "v4 hdr/W: amp field == the committed wProfileImax (7.5 A)");
            check(fabsf(sd_le<float>(*f, 24) - 0.22f) < 1e-6f,
                  "v4 hdr/W: b field == the committed wProfileBoundLo (0.22)");
        }
    }

    // ── 'Y' (LOG_TYPE_PS|LOG_TYPE_DC): amp = committed Vmax, b = committed bound, flags=0x03.
    reset_test_state();
    yProfileVmax    = 3.25f;
    yProfileBoundLo = 0.18f;
    logOpenForProfile(LOG_TYPE_PS | LOG_TYPE_DC);
    {
        const std::string* f = sd_file("YP0001.BLG");
        check(f != nullptr && f->size() >= LOG_HDR_SIZE, "v4 hdr/Y: the header was written");
        if (f) {
            check((uint8_t)(*f)[4] == 5, "v4 hdr/Y: format version 5 (fw v11 BLG bump)");
            check((uint8_t)(*f)[7] == 0x03, "v4 hdr/Y: paramFlags == 0x03 (amp AND b valid)");
            check(fabsf(sd_le<float>(*f, 20) - 3.25f) < 1e-6f,
                  "v4 hdr/Y: amp field == the committed yProfileVmax (3.25 m/s)");
            check(fabsf(sd_le<float>(*f, 24) - 0.18f) < 1e-6f,
                  "v4 hdr/Y: b field == the committed yProfileBoundLo (0.18)");
        }
    }

    // ── 'T' (lone LOG_TYPE_TP): amp = committed trapImax, b field left at 0.0, flags=0x01.
    reset_test_state();
    trapImax = 4.4f;
    logOpenForProfile(LOG_TYPE_TP);
    {
        const std::string* f = sd_file("TP0001.BLG");
        check(f != nullptr && f->size() >= LOG_HDR_SIZE, "v4 hdr/T: the header was written");
        if (f) {
            check((uint8_t)(*f)[4] == 5, "v4 hdr/T: format version 5 (fw v11 BLG bump)");
            check((uint8_t)(*f)[7] == 0x01, "v4 hdr/T: paramFlags == 0x01 (amp only)");
            check(fabsf(sd_le<float>(*f, 20) - 4.4f) < 1e-6f,
                  "v4 hdr/T: amp field == the committed trapImax (4.4 A)");
            check(sd_le<float>(*f, 24) == 0.0f, "v4 hdr/T: b field stays 0.0 (T has no bound)");
        }
    }

    // ── 'R' (lone LOG_TYPE_PS): no profile parameter, flags=0x00, both fields 0.0.
    reset_test_state();
    logOpenForProfile(LOG_TYPE_PS);
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && f->size() >= LOG_HDR_SIZE, "v4 hdr/R: the header was written");
        if (f) {
            check((uint8_t)(*f)[4] == 5, "v4 hdr/R: format version 5 (fw v11 BLG bump)");
            check((uint8_t)(*f)[7] == 0x00, "v4 hdr/R: paramFlags == 0x00 (no profile parameter)");
            check(sd_le<float>(*f, 20) == 0.0f && sd_le<float>(*f, 24) == 0.0f,
                  "v4 hdr/R: both amp and b fields stay 0.0");
        }
    }

    // ── 'D' (lone LOG_TYPE_DC): same as 'R' -- no profile parameter, flags=0x00.
    reset_test_state();
    logOpenForProfile(LOG_TYPE_DC);
    {
        const std::string* f = sd_file("DC0001.BLG");
        check(f != nullptr && f->size() >= LOG_HDR_SIZE, "v4 hdr/D: the header was written");
        if (f) {
            check((uint8_t)(*f)[4] == 5, "v4 hdr/D: format version 5 (fw v11 BLG bump)");
            check((uint8_t)(*f)[7] == 0x00, "v4 hdr/D: paramFlags == 0x00 (no profile parameter)");
            check(sd_le<float>(*f, 20) == 0.0f && sd_le<float>(*f, 24) == 0.0f,
                  "v4 hdr/D: both amp and b fields stay 0.0");
            // Byte 19 is NOT architecturally reserved -- it is the high byte of the 2-byte
            // fwVersion field written at offset 18 (uint16_t). It reads 0 here only because
            // FW_VERSION (7) fits in the low byte; the true always-reserved tail is 28-31 (see
            // the offset arithmetic note in the report). Checked separately, not folded into a
            // "byte 19 is reserved" claim.
            check((uint8_t)(*f)[19] == 0,
                  "v4 hdr/D: byte 19 (fwVersion's high byte) reads 0 for FW_VERSION < 256, not "
                  "because it is architecturally reserved");
            check((uint8_t)(*f)[28] == 0 && (uint8_t)(*f)[29] == 0 &&
                  (uint8_t)(*f)[30] == 0 && (uint8_t)(*f)[31] == 0,
                  "v4 hdr/D: the always-reserved trailing bytes (28-31) are zero");
        }
    }

    // ── Record size byte reflects the current v5 record (76B), regardless of run type. The v4
    // header PARAMETER BLOCK (byte 7, bytes 20-27) is unchanged by the fw v11 bump -- only
    // hdr[4] (version) and hdr[5] (record size) moved when the record grew.
    reset_test_state();
    logOpenForProfile(LOG_TYPE_PS);
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && (uint8_t)(*f)[5] == (uint8_t)LOG_REC_SIZE && LOG_REC_SIZE == 76u,
              "v4/v5 hdr: the record-size byte is 76 -- the v4 parameter block is unchanged, "
              "only hdr[4]/hdr[5] moved with the fw v11 record-size bump");
    }
}

// ─── 6b. sizeof/offsetof sanity for the v3 record (L1/L2 floor coverage) ─────
// A direct struct-layout check, independent of the byte-stream test above: this fails if the
// struct's field order or padding ever drifts from LOG_REC_SIZE / the documented offsets, even
// before any record is ever written to a (mock) card.
static void test_benchlogrecord_v3_layout() {
    test_group("BenchLogRecord (format v5, fw v11): sizeof and field offsets");

    check(sizeof(BenchLogRecord) == 76, "BenchLogRecord: sizeof == 76 bytes (format v5)");
    check(LOG_REC_SIZE == 76u, "LOG_REC_SIZE == 76 (format v5)");

    check(offsetof(BenchLogRecord, V_fc)        == 44, "offsetof(V_fc) == 44");
    check(offsetof(BenchLogRecord, V_batt)      == 48, "offsetof(V_batt) == 48");
    check(offsetof(BenchLogRecord, V_chg)       == 52, "offsetof(V_chg) == 52");
    check(offsetof(BenchLogRecord, V_rgn)       == 56, "offsetof(V_rgn) == 56");
    check(offsetof(BenchLogRecord, fault_flags) == 60, "offsetof(fault_flags) == 60 (shifted +16)");
    check(offsetof(BenchLogRecord, ps_phase)    == 62, "offsetof(ps_phase) == 62");
    check(offsetof(BenchLogRecord, dc_phase)    == 63, "offsetof(dc_phase) == 63");
    check(offsetof(BenchLogRecord, trap_phase)  == 64, "offsetof(trap_phase) == 64");
    check(offsetof(BenchLogRecord, flags)       == 65, "offsetof(flags) == 65");
    check(offsetof(BenchLogRecord, pad)         == 66, "offsetof(pad) == 66 (2-byte tail)");

    // Format v5 (fw v11): APPENDED after pad, so every v1-v4 offset above is unchanged and only
    // these two new tail fields are added.
    check(offsetof(BenchLogRecord, u_unsat)  == 68, "offsetof(u_unsat) == 68 (format v5, appended)");
    check(offsetof(BenchLogRecord, drive_x0) == 72, "offsetof(drive_x0) == 72 (format v5, appended)");

    // These offsets must also match the byte-stream constants used by the on-card tests above --
    // a mismatch here would mean the two test families are silently checking different layouts.
    check(offsetof(BenchLogRecord, V_fc)        == REC_OFF_V_FC,   "offsetof(V_fc) == REC_OFF_V_FC");
    check(offsetof(BenchLogRecord, V_batt)      == REC_OFF_V_BATT, "offsetof(V_batt) == REC_OFF_V_BATT");
    check(offsetof(BenchLogRecord, V_chg)       == REC_OFF_V_CHG,  "offsetof(V_chg) == REC_OFF_V_CHG");
    check(offsetof(BenchLogRecord, V_rgn)       == REC_OFF_V_RGN,  "offsetof(V_rgn) == REC_OFF_V_RGN");
    check(offsetof(BenchLogRecord, fault_flags) == REC_OFF_FAULTS, "offsetof(fault_flags) == REC_OFF_FAULTS");
    check(offsetof(BenchLogRecord, u_unsat)     == REC_OFF_U_UNSAT,  "offsetof(u_unsat) == REC_OFF_U_UNSAT");
    check(offsetof(BenchLogRecord, drive_x0)    == REC_OFF_DRIVE_X0, "offsetof(drive_x0) == REC_OFF_DRIVE_X0");
}

// ─── T2: log record flags bit2 (shareClosedLoopMode) / bit3 (shareClosedLoopRun) ─────────────
// (fw v5 review, :~1985): the BenchLogRecord.flags byte gained two bits so a decoded run says
// which law drove the droop split each tick: bit2=shareClosedLoopMode (Youla stepped this
// tick), bit3=shareClosedLoopRun (closed loop has run at least once since the last reset). The
// three reachable combinations decode to CLOSED / open-loop feedforward / HOLD (per the .ino
// flags comment block at the BenchLogRecord struct); mode=1,run=0 cannot happen in practice
// (powerBalance()'s closed-loop branch always sets both together) so is not exercised here.
static void test_sdlog_flags_share_loop_mode_bits() {
    test_group("SD log: record flags bit2/bit3 encode the fw v5 share-loop mode (T2)");

    auto sample_flags = [](bool closedMode, bool closedRun) -> uint8_t {
        reset_test_state();
        g_mock_millis = 1000;
        g_mock_micros = 1000;
        logOpenForProfile(LOG_TYPE_PS);
        shareClosedLoopMode = closedMode;
        shareClosedLoopRun  = closedRun;
        logSampleTick();
        logDrainTick();
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE,
              "T2 sample: the record made it to the (mock) card");
        if (f == nullptr || f->size() < LOG_HDR_SIZE + LOG_REC_SIZE) return 0;
        return (uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_FLAGS];
    };

    // (a) CLOSED loop: bit2 set.
    uint8_t flagsClosed = sample_flags(/*closedMode=*/true, /*closedRun=*/true);
    check((flagsClosed & 0x04) != 0, "T2a: shareClosedLoopMode=true -> flags bit2 set");

    // (b) OPEN-LOOP feedforward: mode=false, run=false -> bits 2 and 3 both clear.
    uint8_t flagsFeedforward = sample_flags(/*closedMode=*/false, /*closedRun=*/false);
    check((flagsFeedforward & 0x04) == 0 && (flagsFeedforward & 0x08) == 0,
          "T2b: open-loop feedforward (mode=false, run=false) -> flags bits 2,3 both clear");

    // (c) HOLD: mode=false, run=true -> bit3 set, bit2 clear.
    uint8_t flagsHold = sample_flags(/*closedMode=*/false, /*closedRun=*/true);
    check((flagsHold & 0x08) != 0 && (flagsHold & 0x04) == 0,
          "T2c: HOLD (mode=false, run=true) -> flags bit3 set, bit2 clear");
}

// ─── 6c. Record flags bit4/bit5: fw v11 build-identity bits ─────────────────
// (fw v11, BLG record format v5): bit4 = USE_YOULA_DRIVE_CONTROLLER, bit5 =
// USE_YOULA_SHARE_CONTROLLER. Both are compile-time constants, but the .ino stamps them into
// EVERY record so a decoded run is self-identifying without cross-referencing the firmware
// ledger. Only the default build (both macros 1) is host-testable -- the PI-fallback branches
// are compile-time #else arms with no runtime switch, per the task brief.
static void test_sdlog_flags_youla_build_bits() {
    test_group("SD log: record flags bit4/bit5 stamp the fw v11 Youla build identity");

    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000;
    logOpenForProfile(LOG_TYPE_PS);
    powerShareProfileActive = true;   // so bit0 is set, matching the sanity check below
    logSampleTick();
    logDrainTick();

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE,
          "flags bit4/5: the record made it to the (mock) card");
    if (f == nullptr || f->size() < LOG_HDR_SIZE + LOG_REC_SIZE) return;

    uint8_t flags = (uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_FLAGS];
#if USE_YOULA_DRIVE_CONTROLLER
    check((flags & 0x10) != 0,
          "flags bit4: set under the default USE_YOULA_DRIVE_CONTROLLER=1 build");
#else
    check((flags & 0x10) == 0,
          "flags bit4: clear under a USE_YOULA_DRIVE_CONTROLLER=0 (PI fallback) build");
#endif
#if USE_YOULA_SHARE_CONTROLLER
    check((flags & 0x20) != 0,
          "flags bit5: set under the default USE_YOULA_SHARE_CONTROLLER=1 build");
#else
    check((flags & 0x20) == 0,
          "flags bit5: clear under a USE_YOULA_SHARE_CONTROLLER=0 (PI fallback) build");
#endif
    // bits 0-3 are unaffected by this round -- a sanity check that the append didn't disturb
    // the pre-existing bit-packing (bit0 set: this sample was taken with a PS profile active).
    check((flags & 0x01) != 0, "flags bit4/5 case: bit0 (profile driving powerBalance) unaffected");
}

// ─── 6d. Format v5 value plumbing: u_unsat/drive_x0 (fw v11) ────────────────
// (fw v11): the Youla drive controller's PRE-clamp output and integrator state are captured by
// driveControllerStep() into the file-scope driveCtrl_uUnsat/driveCtrl_x[0], and logSampleTick()
// copies them verbatim (default USE_YOULA_DRIVE_CONTROLLER=1 build; the PI-fallback #else arm
// logs targetMotorTorque/motorConstant and pi_motor_accum instead -- a compile-time branch, not
// exercised here per the task brief).
#if USE_YOULA_DRIVE_CONTROLLER
static void test_sdlog_record_u_unsat_drive_x0_saturating() {
    test_group("SD log: u_unsat/drive_x0 (format v5) -- saturating error, u_unsat unclamped in the log");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 100000;
    logOpenForProfile(LOG_TYPE_PS);

    // A large error drives the controller output well past the +-12 A actuator clamp.
    // youlaController_Drive() is the .ino wrapper motorControl() calls; DRIVE_CTRL_TS_US has
    // already elapsed since reset_test_state()'s resetDriveControlState() (same pattern as the
    // existing wrapper tests around test_drive_controller_reset_state()).
    float uClamped = youlaController_Drive(1000.0f);
    check(fabsf(uClamped) <= DRIVE_CTRL_I_MAX + 1e-4f,
          "u_unsat precondition: the wrapper's returned (clamped) output stays within the "
          "actuator limit");
    check(fabsf(driveCtrl_uUnsat) > DRIVE_CTRL_I_MAX,
          "u_unsat precondition: the captured pre-clamp value exceeds the +-12 A actuator clamp");

    // commandMotorCurrent() is what would normally populate `current` from the clamped output --
    // mirror that assignment directly (as the existing schema test does for other fields) so the
    // record's I_cmd reflects the POST-clamp value this test is contrasting u_unsat against.
    current = uClamped;

    logSampleTick();
    logDrainTick();

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE,
          "u_unsat saturating: the record made it to the (mock) card");
    if (f == nullptr || f->size() < LOG_HDR_SIZE + LOG_REC_SIZE) return;

    float recIcmd    = sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_I_CMD);
    float recUUnsat  = sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_U_UNSAT);
    float recDriveX0 = sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_DRIVE_X0);

    check(fabsf(recIcmd) <= DRIVE_CTRL_I_MAX + 1e-4f,
          "u_unsat saturating: logged I_cmd (post-clamp) is at the +-12 A rail");
    check(fabsf(recUUnsat) > DRIVE_CTRL_I_MAX,
          "u_unsat saturating: logged u_unsat exceeds the clamp -- the record shows how far the "
          "law wanted to drive, not just what the actuator allowed");
    check(recUUnsat == driveCtrl_uUnsat,
          "u_unsat saturating: logged u_unsat is byte-identical to driveCtrl_uUnsat");
    check(recDriveX0 == (float)driveCtrl_x[0],
          "u_unsat saturating: logged drive_x0 is byte-identical to (float)driveCtrl_x[0]");
}

static void test_sdlog_record_u_unsat_drive_x0_unclamped() {
    test_group("SD log: u_unsat/drive_x0 (format v5) -- small error, u_unsat == I_cmd (never clamps)");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 100000;
    logOpenForProfile(LOG_TYPE_PS);

    // A small error stays well inside the +-12 A rail on the first tick (DD*e only, from a
    // freshly-reset controller), so the pre-clamp and post-clamp values coincide exactly.
    float u = youlaController_Drive(0.01f);
    check(fabsf(driveCtrl_uUnsat) < DRIVE_CTRL_I_MAX,
          "u_unsat unclamped precondition: the small-error output never reaches the actuator limit");
    check(u == driveCtrl_uUnsat,
          "u_unsat unclamped precondition: wrapper output equals the pre-clamp capture (no clamp "
          "was applied)");
    current = u;

    logSampleTick();
    logDrainTick();

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE,
          "u_unsat unclamped: the record made it to the (mock) card");
    if (f == nullptr || f->size() < LOG_HDR_SIZE + LOG_REC_SIZE) return;

    float recIcmd   = sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_I_CMD);
    float recUUnsat = sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_U_UNSAT);
    check(recIcmd == recUUnsat,
          "u_unsat unclamped: logged u_unsat equals logged I_cmd when the command never clamps");
}

// ─── 6e. Format v5 held-value semantics: 1 kHz log vs 500 Hz controller (fw v11) ────────────
// driveCtrl_uUnsat/driveCtrl_x[0] are HELD between driveControllerStep() calls (the wrapper only
// steps the controller once per DRIVE_CTRL_TS_US), so two 1 kHz log samples taken inside the same
// 2 ms controller tick must carry IDENTICAL u_unsat/drive_x0 -- the same zero-order-hold pairing
// already documented for gFC/gBT/I_cmd at the motor-control cadence.
static void test_sdlog_record_u_unsat_drive_x0_held_value() {
    test_group("SD log: u_unsat/drive_x0 (format v5) -- held identical across two samples in one controller tick");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 100000;
    logOpenForProfile(LOG_TYPE_PS);

    youlaController_Drive(3.0f);   // one controller step; driveCtrl_uUnsat/x[0] now non-trivial
    float uUnsatAfterStep  = driveCtrl_uUnsat;
    float driveX0AfterStep = (float)driveCtrl_x[0];
    check(uUnsatAfterStep != 0.0f, "held-value precondition: the controller step left a non-zero capture");

    // First 1 kHz sample, same controller tick.
    logSampleTick();
    // Advance only 1 ms (< DRIVE_CTRL_TS_US == 2 ms), so the wrapper's Ts gate stays shut and no
    // further driveControllerStep() runs before the second sample.
    g_mock_micros += 1000;
    youlaController_Drive(3.0f);   // gate closed: returns the held output, does not re-step
    check(driveCtrl_uUnsat == uUnsatAfterStep && (float)driveCtrl_x[0] == driveX0AfterStep,
          "held-value precondition: the sub-Ts wrapper call left the capture unchanged");
    logSampleTick();
    logDrainTick();

    check(logRecordCount == 2, "held-value: two records were sampled");

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() >= LOG_HDR_SIZE + 2u * LOG_REC_SIZE,
          "held-value: both records made it to the (mock) card");
    if (f == nullptr || f->size() < LOG_HDR_SIZE + 2u * LOG_REC_SIZE) return;

    float u0  = sd_le<float>(*f, LOG_HDR_SIZE + 0u * LOG_REC_SIZE + REC_OFF_U_UNSAT);
    float u1  = sd_le<float>(*f, LOG_HDR_SIZE + 1u * LOG_REC_SIZE + REC_OFF_U_UNSAT);
    float x00 = sd_le<float>(*f, LOG_HDR_SIZE + 0u * LOG_REC_SIZE + REC_OFF_DRIVE_X0);
    float x01 = sd_le<float>(*f, LOG_HDR_SIZE + 1u * LOG_REC_SIZE + REC_OFF_DRIVE_X0);

    check(u0 == u1, "held-value: u_unsat is identical across both samples in the same controller tick");
    check(x00 == x01, "held-value: drive_x0 is identical across both samples in the same controller tick");
    check(u0 == uUnsatAfterStep, "held-value: the held u_unsat matches the last driveControllerStep() capture");
}

// ─── 6f. Format v5 reset semantics: u_unsat/drive_x0 zero after resetDriveControlState() ───
static void test_sdlog_record_u_unsat_drive_x0_reset() {
    test_group("SD log: u_unsat/drive_x0 (format v5) -- zero after resetDriveControlState()");
    reset_test_state();

    // Wind the controller up first, so a passing "zero after reset" check is not vacuous.
    for (int k = 0; k < 50; k++) driveControllerStep(20.0f);
    check(driveCtrl_uUnsat != 0.0f, "reset precondition: a driven controller leaves a non-zero capture");

    resetDriveControlState();
    check(driveCtrl_uUnsat == 0.0f && driveCtrl_x[0] == 0.0,
          "reset precondition: resetDriveControlState() zeroes both the capture and the state");

    g_mock_millis = 1000;
    g_mock_micros = 100000;
    logOpenForProfile(LOG_TYPE_PS);
    logSampleTick();
    logDrainTick();

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE,
          "reset: the record made it to the (mock) card");
    if (f == nullptr || f->size() < LOG_HDR_SIZE + LOG_REC_SIZE) return;

    float recUUnsat  = sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_U_UNSAT);
    float recDriveX0 = sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_DRIVE_X0);
    check(recUUnsat == 0.0f, "reset: logged u_unsat is 0.0 after resetDriveControlState()");
    check(recDriveX0 == 0.0f, "reset: logged drive_x0 is 0.0 after resetDriveControlState()");
}
#endif // USE_YOULA_DRIVE_CONTROLLER

// ─── 7. Write error mid-run: logging dies, the profile does not ─────────────
static void test_sdlog_write_error_midrun() {
    test_group("SD log: a mid-run write error disables logging without faulting the run");
    reset_test_state();

    sd_start_share_run();
    sd_run_ms(5, /*drain=*/false);
    check(logActive == true && logRingCount > 0,
          "SD write error: the run is logging with records pending before the injected failure");

    Serial.tx_clear();
    g_sd_state.fail_next_write = true;
    logDrainTick();

    check(Serial.tx_count("[SD] write error") == 1,
          "SD write error: exactly one '[SD] write error' warning is printed");
    check(logActive == false && logCloseRequested == false && logFile.isOpen() == false,
          "SD write error: logging is disabled and the file handle is released");
    check(logRingCount == 0 && logRecordCount == 0,
          "SD write error: the ring and counters are cleared so nothing bleeds into the next run");
    check(mainState == 98 && fault_flags == 0 && error_code == ERR_NONE,
          "SD write error: an SD failure never calls triggerFault() — no fault, still in State 98");

    // Trailer provenance (review 2026-08-10 FW-R1-F4): this path used to leave logCloseReason at 0,
    // an undocumented value the decoder renders as "unknown(0)". fail_next_write is one-shot, so
    // the record write failed but the trailer write itself succeeded — the trailer is on the card.
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE,
              "SD write error: the aborted file still carries its header and a trailer");
        if (f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE) {
            size_t tr = f->size() - LOG_REC_SIZE;
            check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu,
                  "SD write error: the aborted file ends in the trailer sentinel");
            check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_IO_ERROR,
                  "SD write error: the trailer reason is LOG_CLOSE_IO_ERROR, not the undocumented 0");
        }
    }
    check(powerShareProfileActive == true,
          "SD write error: the power-share profile is still running");

    // The profile must keep advancing, and the warn must not repeat every tick.
    uint8_t phaseBefore = powerShareProfilePhaseIdx;
    Serial.tx_clear();
    sd_run_ms(3200);
    check(powerShareProfileActive == true && powerShareProfilePhaseIdx > phaseBefore,
          "SD write error: the profile phase machine keeps advancing after logging is disabled");
    check(Serial.tx_count("[SD] write error") == 0,
          "SD write error: the warning is one-shot and does not repeat on later drain ticks");
    check(logRecordCount == 0,
          "SD write error: no further samples are buffered once logging is disabled");
}

// ─── 8. File-name collision: max index across all three prefixes, +1 ────────
static void test_sdlog_name_collision() {
    test_group("SD log: the run counter continues past existing files across all prefixes");

    reset_test_state();
    g_sd_state.files["PS0007.BLG"] = "";
    sd_start_share_run();
    check(std::string(logFileName) == "PS0008.BLG",
          "SD naming: an existing PS0007.BLG makes the next power-share run PS0008.BLG");
    check(sd_file("PS0008.BLG") != nullptr,
          "SD naming: the new file is actually created on the card");

    // The counter is shared across prefixes so one monotonic index orders a whole bench session.
    reset_test_state();
    g_sd_state.files["PS0007.BLG"] = "";
    g_sd_state.files["TP0020.BLG"] = "";
    g_sd_state.files["NOTES.TXT"]  = "";   // non-.BLG entries must be ignored by the scan
    sd_start_share_run();
    check(std::string(logFileName) == "PS0021.BLG",
          "SD naming: the index is one past the maximum across ALL prefixes, not just PS");
    check(sd_file("PS0007.BLG") != nullptr && sd_file("TP0020.BLG") != nullptr,
          "SD naming: the pre-existing logs are left untouched");
}

// ─── 9. Sample cadence is exactly POWER_BAL_PERIOD_US ───────────────────────
static void test_sdlog_rate_1khz() {
    test_group("SD log: sampling lands exactly once per POWER_BAL_PERIOD_US");
    reset_test_state();

    mainState = 98;
    g_mock_millis = 100;
    g_mock_micros = 100000;
    logOpenForProfile(LOG_TYPE_PS);
    rl_log_last = g_mock_micros;   // start from a freshly-closed gate
    check(logActive == true, "SD rate: the log is open and armed before the cadence sweep");

    // Sub-period steps must produce nothing at all.
    for (int i = 0; i < 3; i++) {
        g_mock_micros += POWER_BAL_PERIOD_US / 4;
        doState98();
        check(logRecordCount == 0,
              "SD rate: no record is taken before a full POWER_BAL_PERIOD_US has elapsed");
    }
    g_mock_micros += POWER_BAL_PERIOD_US / 4;   // now exactly one period since rl_log_last
    doState98();
    check(logRecordCount == 1,
          "SD rate: exactly one record is taken on the tick the period completes");

    // Ten more full periods, each split into four sub-period ticks: one record per period.
    for (int p = 0; p < 10; p++) {
        for (int i = 0; i < 4; i++) {
            g_mock_micros += POWER_BAL_PERIOD_US / 4;
            doState98();
        }
    }
    check(logRecordCount == 11,
          "SD rate: ten further periods yield exactly ten further records (1 kHz, no doubling)");

    // A single large jump must not back-fill: the gate takes one sample, not one per period missed.
    g_mock_micros += POWER_BAL_PERIOD_US * 50;
    doState98();
    check(logRecordCount == 12,
          "SD rate: a long gap yields a single catch-up record, never a burst of back-fills");

    // …and the gap is DISCLOSED IN-BAND: nothing is back-filled, but the per-record micros()
    // timestamps make the missed window explicit to the decoder, so "no back-fill" can never be
    // mistaken for "no gap". (Review 2026-08-10 FW-R1-F5: the no-backfill gate is the same
    // rate-limiter semantics the power-balance controller uses — a missed log tick is a missed
    // control tick — and this delta is how a reader sees it.) Records 10 and 11 are the last
    // pre-gap and the post-gap sample; they still sit in the undrained ring.
    {
        uint32_t tPre = 0, tPost = 0;
        memcpy(&tPre,  &logRing[10 * LOG_REC_SIZE], 4);
        memcpy(&tPost, &logRing[11 * LOG_REC_SIZE], 4);
        check((uint32_t)(tPost - tPre) == POWER_BAL_PERIOD_US * 50,
              "SD rate: the recorded t_us delta across the gap equals the full missed window");
    }
}

// ─── 10. 'L' plot stream and SD logging run independently ───────────────────
static void test_sdlog_plot_simultaneous() {
    test_group("SD log: the 'L' plot stream and 1 kHz logging coexist with independent rates");
    reset_test_state();

    sd_start_share_run();          // 'R' first: under plot mode 'R' would only ARM (delayed start)
    check(logActive == true, "SD + plot: the share profile is logging before the plotter is enabled");
    Serial.rx_queue.push('L');
    doState98();
    check(plotModeActive == true && logActive == true,
          "SD + plot: enabling the plot stream leaves the log active");

    Serial.tx_clear();
    uint32_t recsBefore = logRecordCount;
    sd_run_ms(100);

    check(logRecordCount - recsBefore == 100,
          "SD + plot: logging still lands 100 records in 100 ms with the plotter streaming");
    check(Serial.tx_count("share_sp:") == 100 / (int)PLOT_PERIOD_MS,
          "SD + plot: the plot stream still emits exactly one line per PLOT_PERIOD_MS");
    check(Serial.tx_count("[SD]") == 0,
          "SD + plot: the logger prints nothing periodic, so it cannot corrupt the plotter parse");

    // Closing the log must not disturb the plot stream.
    Serial.tx_clear();
    Serial.rx_queue.push('X');
    doState98();
    sd_drain_until_closed();
    check(Serial.tx_count("[SD] closed") == 1,
          "SD + plot: the close prints its one-shot summary exactly once");
    check(plotModeActive == true,
          "SD + plot: stopping the profile leaves the plot stream running");
    Serial.tx_clear();
    sd_run_ms(100);
    check(Serial.tx_count("share_sp:") == 100 / (int)PLOT_PERIOD_MS,
          "SD + plot: the plot cadence is unchanged after the log closed");
}

// ─── 11. 'K' status command ─────────────────────────────────────────────────
// fw v9 fixture note: 'K' no longer prints the status block on the keypress itself — it opens
// PEND_K_PARAMS and prompts, so an empty line ('K' + '\n') is now required to reach
// printSdStatus() (parseKLogLine()'s "*p == '\\0'" branch). Every case below was updated to push
// the trailing newline; this is the "existing tests sending 'K'" repair the review round flagged.
static void test_sdlog_k_status() {
    test_group("SD log: 'K' + empty line prints the logger status and stays live during the "
               "bring-up lockout");
    reset_test_state();

    mainState = 98;
    Serial.tx_clear();
    Serial.rx_queue.push('K');
    doState98();
    check(pendingInput == PEND_K_PARAMS,
          "'K': the bare keypress opens the PEND_K_PARAMS prompt (fw v9), not an immediate print");
    Serial.rx_queue.push('\n');
    doState98();
    check(pendingInput == PEND_NONE,
          "'K' + empty line: the prompt is dispatched and cleared");
    check(Serial.tx_contains("=== SD logger ==="),
          "'K' + empty line: prints the SD logger status block");
    check(Serial.tx_contains("card:") && Serial.tx_contains("file:") &&
          Serial.tx_contains("records:") && Serial.tx_contains("dropped:"),
          "'K' + empty line: the status block carries the card, file, record and drop fields");
    check(Serial.tx_contains("not probed yet"),
          "'K' + empty line: before any run the card is reported as not yet probed");
    check(g_sd_state.begin_calls == 0,
          "'K' + empty line: the status print never probes the card itself (read-only, non-blocking)");
    check(logActive == false && logManualActive == false && g_sd_state.files.empty(),
          "'K' + empty line: no state changes and no file is opened by the status query");

    // With a run in progress the same line must name the file and the live counts.
    reset_test_state();
    sd_start_share_run();
    sd_run_ms(5);
    Serial.tx_clear();
    Serial.rx_queue.push('K');
    doState98();
    Serial.rx_queue.push('\n');
    doState98();
    check(Serial.tx_contains("PS0001.BLG") && Serial.tx_contains("YES (sampling)"),
          "'K' + empty line: during a run the status names the open file and reports sampling active");
    // FW-2 (S2): the 'active:' line's ownership marker — a profile-owned log (the 'R' share run
    // above) must read "(profile-owned)", never the manual marker.
    check(Serial.tx_contains("(profile-owned)") && !Serial.tx_contains("(manual"),
          "'K' + empty line: a profile-owned log's status line carries the (profile-owned) marker");

    // Bring-up lockout: 'K' is read-only, so it must NOT be refused like the topology keys.
    Serial.tx_clear();
    bringupActive = true;
    Serial.rx_queue.push('K');
    doState98();
    Serial.rx_queue.push('\n');
    doState98();
    check(Serial.tx_contains("=== SD logger ==="),
          "'K' + empty line: still prints while the staged bring-up holds the topology lockout");
    check(!Serial.tx_contains("REFUSED: staged bring-up"),
          "'K' + empty line: is not refused by the staged-bring-up lockout");
    bringupActive = false;
}

// ─── fw v9: 'K 1' / 'K 0' manual log (LOG_TYPE_MANUAL, "ML" prefix) ──────────
// Feed a "K <rest>" entry through the real keypress path: 'K' opens PEND_K_PARAMS (one
// doState98() tick), then `rest` (may be "") is typed char-by-char and terminated with '\n' by
// feed_serial_line(), exactly as an operator would type it.
static void k_send(const char* rest) {
    Serial.rx_queue.push('K');
    doState98();
    feed_serial_line(rest);
}

static void k_start_manual() {
    k_send(" 1");
}

// ─── 11b. 'K 1' opens a manual log; joins the shared session counter ────────
static void test_sdlog_k_manual_open() {
    test_group("SD log: 'K 1' opens a manual log (LOG_TYPE_MANUAL, \"ML\" prefix)");
    reset_test_state();

    mainState = 98;
    Serial.tx_clear();
    k_start_manual();
    check(logActive == true && logManualActive == true,
          "'K 1': opens a manual log and claims manual ownership");
    check(std::string(logFileName) == "ML0001.BLG",
          "'K 1': the first manual run of a session opens ML0001.BLG");
    check(Serial.tx_contains("[SD] manual log started: ML0001.BLG"),
          "'K 1': the open prints its own one-shot confirmation naming the file");
    const std::string* f = sd_file("ML0001.BLG");
    check(f != nullptr && f->size() >= LOG_HDR_SIZE,
          "'K 1': the file actually landed on the card with at least a header");
    if (f) {
        check((uint8_t)(*f)[6] == LOG_TYPE_MANUAL,
              "'K 1': header typeMask (offset 6) is LOG_TYPE_MANUAL (0x08)");
        check((uint8_t)(*f)[7] == 0x00,
              "'K 1': header paramFlags (offset 7) is 0 — a manual run carries no profile parameter");
    }

    // ML joins the shared session counter — a pre-existing TP0005.BLG makes the next manual run
    // ML0006.BLG (mirrors test_sdlog_name_collision()'s "one monotonic counter" contract).
    reset_test_state();
    g_sd_state.files["TP0005.BLG"] = "";
    mainState = 98;
    k_start_manual();
    check(std::string(logFileName) == "ML0006.BLG",
          "'K 1': the manual log joins the shared PS/TP/DC/YP/WP/ML counter, not a counter of its own");
}

// ─── 11c. Sampling runs while manual-logging; phase bytes/flags reflect "no profile" ──
static void test_sdlog_k_manual_sampling() {
    test_group("SD log: sampling runs while a manual log is active (LOG_PHASE_NONE, flags bit0 clear)");
    reset_test_state();

    mainState = 98;
    k_start_manual();
    check(logActive == true, "manual sampling: the log is active before ticking the spine");

    uint32_t recsBefore = logRecordCount;
    sd_run_ms(50);
    check(logRecordCount - recsBefore == 50,
          "manual sampling: 50 ms of State-98 ticks yields exactly 50 records (1 kHz gate)");

    const std::string* f = sd_file("ML0001.BLG");
    check(f != nullptr, "manual sampling: the file exists on the card");
    if (f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE) {
        size_t off = LOG_HDR_SIZE;   // first record
        check((uint8_t)(*f)[off + REC_OFF_PS_PHASE]   == LOG_PHASE_NONE &&
              (uint8_t)(*f)[off + REC_OFF_DC_PHASE]   == LOG_PHASE_NONE &&
              (uint8_t)(*f)[off + REC_OFF_TRAP_PHASE] == LOG_PHASE_NONE,
              "manual sampling: all three phase bytes read LOG_PHASE_NONE — no profile is active");
        uint8_t flags = (uint8_t)(*f)[off + REC_OFF_FLAGS];
        check((flags & 0x01) == 0,
              "manual sampling: flags bit0 is clear — nothing is driving the droop MDACs under "
              "profile/live-share control during a hand-driven manual run");
    }
}

// ─── 11d. 'K 0' stops a manual log with LOG_CLOSE_STOP ───────────────────────
static void test_sdlog_k_manual_stop() {
    test_group("SD log: 'K 0' stops a manual log with LOG_CLOSE_STOP");
    reset_test_state();

    mainState = 98;
    k_start_manual();
    sd_run_ms(10);
    uint32_t recs = logRecordCount;
    check(recs > 0, "'K 0' setup: the manual run logged samples before the stop");

    Serial.tx_clear();
    k_send(" 0");
    check(logActive == false && logCloseRequested == true && logCloseReason == LOG_CLOSE_STOP,
          "'K 0': requests a close with LOG_CLOSE_STOP, flag-only (no card I/O in the handler)");
    check(Serial.tx_contains("[SD] manual log closing"),
          "'K 0': prints its own one-shot confirmation");

    sd_drain_until_closed();
    check(logManualActive == false,
          "'K 0': manual ownership clears once the drain finishes (logFinishFile() bottleneck)");
    const std::string* f = sd_file("ML0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
          "'K 0': the closed file holds every buffered record plus the trailer");
    if (f) {
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_STOP,
              "'K 0': the trailer records LOG_CLOSE_STOP as the close reason");
    }
}

// ─── 11e. 'K 1' refusals: bring-up, a running profile, an already-open log ──
static void test_sdlog_k1_refusals() {
    test_group("SD log: 'K 1' refuses under bring-up, a running profile, or an already-open log");

    // (a) staged bring-up in progress
    reset_test_state();
    mainState = 98;
    bringupActive = true;
    Serial.tx_clear();
    k_send(" 1");
    check(logActive == false && logManualActive == false && g_sd_state.files.empty(),
          "'K 1' refusal (bring-up): no file is opened");
    check(Serial.tx_contains("REFUSED: staged bring-up in progress"),
          "'K 1' refusal (bring-up): names the cause");
    bringupActive = false;

    // (b) a profile owns the log — two representative flags (a plain profile flag, and the
    // plot-arm-pending case, which is refused by the same clause).
    reset_test_state();
    mainState = 98;
    driveCycleActive = true;
    Serial.tx_clear();
    k_send(" 1");
    check(logActive == false && logManualActive == false && g_sd_state.files.empty(),
          "'K 1' refusal (drive cycle active): no file is opened");
    check(Serial.tx_contains("REFUSED: a profile owns the log"),
          "'K 1' refusal (drive cycle active): names the cause");
    driveCycleActive = false;

    reset_test_state();
    mainState = 98;
    g_mock_millis = 1000;
    // The share-arm preconditions (MOT_PWR HIGH + a standing manual motor command) are RE-CHECKED
    // every doState98() tick while armed (line ~4477) — without them the arm-tick cancels itself
    // ("preconditions no longer met") before 'K' is ever read, and plotArmTarget silently goes back
    // to PLOT_ARM_NONE, which would make this refusal pass for the wrong reason (no arm left to
    // refuse against). Mirrors sd_start_share_run()'s own preconditions.
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    plotArmTarget     = PLOT_ARM_SHARE;
    // Deadline in the future — otherwise doState98()'s own arm-tick (outside the serial block)
    // fires the armed profile on this very call before 'K' is even read, which would make the
    // refusal test accidentally pass for the wrong reason (a live profile from firing, not the
    // still-pending arm this case means to exercise).
    plotArmDeadlineMs = g_mock_millis + PLOT_ARM_DELAY_MS;
    Serial.tx_clear();
    k_send(" 1");
    check(logActive == false && logManualActive == false && g_sd_state.files.empty(),
          "'K 1' refusal (plot-arm pending): no file is opened");
    check(Serial.tx_contains("REFUSED: a profile owns the log"),
          "'K 1' refusal (plot-arm pending): names the cause");
    plotArmTarget = PLOT_ARM_NONE;

    // (c) a log is already open (manual)
    reset_test_state();
    mainState = 98;
    k_start_manual();
    check(logActive == true, "'K 1' refusal (already open) setup: the first manual log is running");
    Serial.tx_clear();
    k_send(" 1");
    check(std::string(logFileName) == "ML0001.BLG" && g_sd_state.files.size() == 1,
          "'K 1' refusal (already open): no second file is opened — the first stays the only one");
    check(Serial.tx_contains("REFUSED: a log is already open/closing"),
          "'K 1' refusal (already open): names the cause");
}

// ─── 11f. 'K 0' refusals: a profile-owned log, and nothing running ──────────
static void test_sdlog_k0_refusals() {
    test_group("SD log: 'K 0' refuses to close a profile's log, and no-ops when nothing is running");

    // (a) a profile's own log is running (a 'T' run auto-logs to TPnnnn.BLG)
    reset_test_state();
    mainState = 98;
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 5 0 100");
    check(logActive == true && logManualActive == false,
          "'K 0' refusal setup: the trapezoid's own TP log is running, not manual-owned");
    Serial.tx_clear();
    k_send(" 0");
    check(logActive == true && logCloseRequested == false,
          "'K 0' refusal (profile-owned): the running log is left untouched");
    check(Serial.tx_contains("REFUSED: the running log belongs to a profile"),
          "'K 0' refusal (profile-owned): names the cause");
    // Clean up: stop the trapezoid so its own log closes.
    Serial.rx_queue.push('X');
    doState98();
    sd_drain_until_closed();

    // (b) nothing running at all
    reset_test_state();
    mainState = 98;
    Serial.tx_clear();
    k_send(" 0");
    check(logActive == false && logCloseRequested == false,
          "'K 0' no-op: state is unchanged when nothing is running");
    check(Serial.tx_contains("[SD] no log running"),
          "'K 0' no-op: names the cause");
}

// ─── 11g. Garbage 'K' lines are rejected without opening/closing anything ───
static void test_sdlog_k_garbage_lines() {
    test_group("SD log: garbage 'K' lines are rejected without opening/closing anything");

    // Every one of these is built only from digits/'.'/'-' so the numeric-entry-char filter in
    // doState98() lets the WHOLE line through to parseKLogLine(), which rejects it as "not exactly
    // one 0/1 token".
    struct Case { const char* rest; const char* label; };
    Case cases[] = {
        { " 2",   "'K 2' (out-of-range digit)" },
        { " 01",  "'K 01' (trailing digit)" },
        { " -1",  "'K -1' (negative)" },
        { " 0.5", "'K 0.5' (fractional)" },
    };
    for (const auto& c : cases) {
        reset_test_state();
        mainState = 98;
        Serial.tx_clear();
        k_send(c.rest);
        check(pendingInput == PEND_NONE,
              (std::string(c.label) + ": the pending prompt is cleared").c_str());
        check(logActive == false && logManualActive == false && g_sd_state.files.empty(),
              (std::string(c.label) + ": no file is opened").c_str());
        check(Serial.tx_contains("ERROR: K takes 0 or 1"),
              (std::string(c.label) + ": parseKLogLine() rejects the whole line").c_str());
    }

    // A non-numeric character never reaches parseKLogLine() at all: the shared "unexpected key
    // while a prompt is pending" rule in doState98() cancels the prompt immediately, the same as
    // it would at any other value prompt ('A', 'V', 'T', ...). This is real firmware behaviour,
    // not a parseKLogLine() gap — an operator who fat-fingers a letter mid-entry sees
    // "(input cancelled)", not "ERROR: K takes 0 or 1". Deliberately uses 'z' rather than 'x'/'q':
    // those double as the universal-stop/exit COMMAND keys and would fire as a side effect once the
    // cancel falls through to the normal command switch.
    reset_test_state();
    mainState = 98;
    Serial.tx_clear();
    k_send(" 1z");
    check(pendingInput == PEND_NONE,
          "'K 1z': the letter cancels the pending prompt (generic non-numeric-key rule)");
    check(logActive == false && logManualActive == false && g_sd_state.files.empty(),
          "'K 1z': no file is opened — the cancel fires before any 'K'-specific parsing runs");
    check(Serial.tx_contains("(input cancelled)"),
          "'K 1z': the generic cancel message fires, not parseKLogLine()'s ERROR text");
    check(!Serial.tx_contains("ERROR: K takes 0 or 1"),
          "'K 1z': parseKLogLine() is never reached for a non-numeric character");
}

// ─── 11h. 'X' during a manual run closes it with LOG_CLOSE_X ────────────────
static void test_sdlog_k_manual_x_close() {
    test_group("SD log: 'X' during a manual run closes it with LOG_CLOSE_X");
    reset_test_state();

    mainState = 98;
    k_start_manual();
    sd_run_ms(8);
    uint32_t recs = logRecordCount;

    Serial.rx_queue.push('X');
    doState98();
    check(logCloseRequested == true && logActive == false && logCloseReason == LOG_CLOSE_X,
          "'X' during manual log: requests a close with LOG_CLOSE_X");
    check(logManualActive == true,
          "'X' during manual log: ownership survives until logFinishFile() actually runs — "
          "parseKLogLine()'s 'K 1' refusal must keep seeing this as manual through the drain");

    sd_drain_until_closed();
    check(logManualActive == false,
          "'X' during manual log: manual ownership clears once logFinishFile() runs");
    const std::string* f = sd_file("ML0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
          "'X' during manual log: the file holds every buffered record plus the trailer");
    if (f) {
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_X,
              "'X' during manual log: the trailer records LOG_CLOSE_X");
    }
}

// ─── 11i. 'Q' during a manual run closes it with LOG_CLOSE_Q ────────────────
static void test_sdlog_k_manual_q_close() {
    test_group("SD log: 'Q' during a manual run closes it with LOG_CLOSE_Q");
    reset_test_state();

    mainState = 98;
    k_start_manual();
    sd_run_ms(8, /*drain=*/false);
    uint32_t recs = logRecordCount;

    Serial.rx_queue.push('Q');
    doState98();
    check(mainState == 1, "'Q' during manual log: the exit key returns to Idle");
    check(logCloseRequested == true && logCloseReason == LOG_CLOSE_Q && logFile.isOpen() == true,
          "'Q' during manual log: only flags the close on the way out — the file is still open "
          "in State 98");
    check(logManualActive == true,
          "'Q' during manual log: manual ownership survives the exit, pending the loop-level drain");

    int ticks = sd_drain_until_closed();
    check(ticks > 0 && logFile.isOpen() == false,
          "'Q' during manual log: the loop-level drain finishes and closes the file from Idle");
    check(logManualActive == false,
          "'Q' during manual log: manual ownership clears once the drain finishes");
    const std::string* f = sd_file("ML0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
          "'Q' during manual log: every buffered record reaches the card after the exit");
    if (f) {
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_Q,
              "'Q' during manual log: the trailer records LOG_CLOSE_Q");
    }
}

// ─── 11j. A fault mid-manual-run closes the file from State 99 ──────────────
static void test_sdlog_k_manual_fault_close() {
    test_group("SD log: a fault mid-manual-run closes the file from State 99 with LOG_CLOSE_FAULT");
    reset_test_state();

    mainState = 98;
    k_start_manual();
    sd_run_ms(9, /*drain=*/false);
    uint32_t recs = logRecordCount;
    check(recs > 0 && logActive == true,
          "fault during manual log setup: the manual run was logging when the fault is injected");

    triggerFault(FAULT_OC_FC, ERR_OC_FC);
    check(mainState == 99, "fault during manual log: triggerFault() latches State 99");
    check(logActive == false && logCloseRequested == true && logCloseReason == LOG_CLOSE_FAULT,
          "fault during manual log: the fault path only flags the close (no card I/O in triggerFault())");
    check(logManualActive == true,
          "fault during manual log: manual ownership survives up to the drain");

    int ticks = sd_drain_until_closed_state99();
    check(ticks > 0 && logFile.isOpen() == false,
          "fault during manual log: the drain finishes the file while State 99 is latched");
    check(logManualActive == false,
          "fault during manual log: manual ownership clears once the drain closes the file");

    const std::string* f = sd_file("ML0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
          "fault during manual log: the pre-fault records plus the trailer all reach the card");
    if (f) {
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_FAULT,
              "fault during manual log: the trailer close reason is LOG_CLOSE_FAULT");
        check((uint8_t)(*f)[tr + 13] == (uint8_t)ERR_OC_FC,
              "fault during manual log: the trailer carries the latched error_code");
    }
}

// ─── 11k. A profile start takes over a live manual log (double-open handoff) ─
static void test_sdlog_k_manual_takeover() {
    test_group("SD log: a profile start takes over a live manual log (double-open handoff)");
    reset_test_state();

    mainState = 98;
    k_start_manual();
    sd_run_ms(6);
    uint32_t recs = logRecordCount;
    check(logActive == true && logManualActive == true && std::string(logFileName) == "ML0001.BLG",
          "manual takeover setup: a manual log is running before the profile starts");

    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(" 5 0 100");
    check(trapProfileActive == true, "manual takeover: the trapezoid started");
    check(logManualActive == false,
          "manual takeover: manual ownership is dropped by the handoff (logFinishFile() bottleneck)");
    check(logActive == true && std::string(logFileName) == "TP0002.BLG",
          "manual takeover: a NEW file is opened for the profile, joining the shared counter "
          "(ML0001.BLG already claimed index 1)");

    const std::string* old_f = sd_file("ML0001.BLG");
    check(old_f != nullptr && old_f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
          "manual takeover: the superseded manual file is complete (records + trailer)");
    if (old_f) {
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
        check((uint8_t)(*old_f)[tr + 12] == LOG_CLOSE_STOP,
              "manual takeover: the superseded manual run's close reason is LOG_CLOSE_STOP "
              "(double-open branch's stamp, same as every other profile-vs-profile takeover)");
    }

    // The new file must actually accumulate records under the trapezoid's own logging. Stop
    // partway through the 100 ms profile (not the full 100 ticks) — a run to natural completion
    // closes the file and logFinishFile() zeroes logRecordCount, which would read back 0 here for
    // the wrong reason (closed, not "never sampled").
    for (int i = 0; i < 50; i++) {
        g_mock_millis += 1;
        g_mock_micros += POWER_BAL_PERIOD_US;
        doState98();
        logDrainTick();
    }
    check(trapProfileActive == true && logRecordCount > 0,
          "manual takeover: the new TP file is actively sampling");
}

// ─── 11l. No card: 'K 1' warns and never sets manual ownership ──────────────
static void test_sdlog_k_manual_no_card() {
    test_group("SD log: 'K 1' with no card warns and never sets manual ownership");
    reset_test_state();

    g_sd_state.card_present = false;
    mainState = 98;
    Serial.tx_clear();
    k_send(" 1");
    check(logActive == false && logManualActive == false,
          "'K 1' no-card: neither logActive nor logManualActive is set");
    check(Serial.tx_contains("[SD] no card"),
          "'K 1' no-card: the one-shot no-card warning fires");
    check(g_sd_state.files.empty(), "'K 1' no-card: no file is created");

    // Drive logDrainTick()'s !sdAvailable clear path directly: it is the ONE path that clears
    // logActive/logCloseRequested without calling logFinishFile(), and per fw v9 it must also
    // clear manual ownership if it was somehow left set (e.g. a card pulled mid-run) — or a later
    // 'K 1' on the now-cardless board would see logManualActive stuck true forever.
    reset_test_state();
    logActive       = true;
    logManualActive = true;
    sdAvailable     = false;
    logDrainTick();
    check(logActive == false && logCloseRequested == false && logManualActive == false,
          "logDrainTick() !sdAvailable path: clears logActive AND logManualActive together");
}

// ─── 11n. Correctness finding 1: 'K 1' during a manual log's own drain window ─
static void test_sdlog_k1_during_manual_drain_window() {
    test_group("SD log: 'K 1' during a manual log's own drain window is refused (already open/closing)");
    reset_test_state();

    mainState = 98;
    k_start_manual();
    sd_run_ms(5, /*drain=*/false);   // buffer records, keep the close undrained
    Serial.tx_clear();
    k_send(" 0");
    check(logActive == false && logCloseRequested == true,
          "K1-during-drain setup: 'K 0' requested the close; the drain has not run yet");

    Serial.tx_clear();
    k_send(" 1");
    check(logActive == false && logCloseRequested == true,
          "K1-during-drain: the second-open attempt is refused; the pending close is untouched");
    check(Serial.tx_contains("REFUSED: a log is already open/closing"),
          "K1-during-drain: names the cause");
    check(g_sd_state.files.size() == 1,
          "K1-during-drain: no second file is created while the first is still draining/closing");

    sd_drain_until_closed();
    check(logManualActive == false,
          "K1-during-drain cleanup: the original manual log still finishes normally");
}

// ─── 11o. Correctness finding 2: a second 'K 0' while a close is pending ─────
static void test_sdlog_k0_twice_first_reason_wins() {
    test_group("SD log: a second 'K 0' while a close is pending leaves the first reason intact");
    reset_test_state();

    mainState = 98;
    k_start_manual();
    sd_run_ms(5, /*drain=*/false);
    k_send(" 0");
    check(logCloseRequested == true && logCloseReason == LOG_CLOSE_STOP,
          "K0 x2 setup: the first 'K 0' requested the close with LOG_CLOSE_STOP");

    Serial.tx_clear();
    k_send(" 0");
    check(logCloseRequested == true && logCloseReason == LOG_CLOSE_STOP,
          "K0 x2: the second 'K 0' does not disturb the already-latched close reason "
          "(logRequestClose()'s \"first requester wins\" rule)");
    check(logFile.isOpen() == true,
          "K0 x2: no double-close side effect — the file handle is untouched by the repeat request");

    sd_drain_until_closed();
    check(logManualActive == false && logFile.isOpen() == false,
          "K0 x2: the drain still completes normally afterward");
    const std::string* f = sd_file("ML0001.BLG");
    check(f != nullptr, "K0 x2: the file exists on the card");
    if (f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE) {
        size_t nrec = (f->size() - LOG_HDR_SIZE) / LOG_REC_SIZE - 1;
        size_t tr   = LOG_HDR_SIZE + LOG_REC_SIZE * nrec;
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_STOP,
              "K0 x2: the trailer close reason is still LOG_CLOSE_STOP, not corrupted by the repeat");
    }
}

// ─── 11p. Correctness finding 3: the 'K' prompt is unaffected by plot mode ──
static void test_sdlog_k_prompt_under_plot_mode() {
    test_group("SD log: the 'K' prompt behaves identically under plot mode, plus its own "
               "line-terminating println (the 'P' plot-line concat guard)");

    // Without plot mode: the prompt print has NO trailing newline of its own (the operator's
    // typed digits continue the same line).
    reset_test_state();
    mainState = 98;
    Serial.tx_clear();
    Serial.rx_queue.push('K');
    doState98();
    check(!Serial.tx_contains("SD log [1=start 0=stop, empty=status]: \n"),
          "'K' without plot mode: the prompt print is NOT self-terminated by a println");
    Serial.rx_queue.push('\n');
    doState98();

    // Under plot mode: 'K' + empty line still reaches printSdStatus() unchanged, AND the prompt
    // print gets the extra println() (case 'K': "if (plotModeActive) Serial.println();") so a
    // suppressed/concatenated plot line can't run on into the operator's prompt.
    reset_test_state();
    mainState = 98;
    plotModeActive = true;
    Serial.tx_clear();
    Serial.rx_queue.push('K');
    doState98();
    check(Serial.tx_contains("SD log [1=start 0=stop, empty=status]: \n"),
          "'K' under plot mode: the prompt line is terminated by its own println (concat guard)");
    Serial.rx_queue.push('\n');
    doState98();
    check(Serial.tx_contains("=== SD logger ==="),
          "'K' under plot mode + empty line: status still prints, unchanged by plot mode");

    // Under plot mode: 'K 1' still opens a manual log exactly as without plot mode.
    reset_test_state();
    mainState = 98;
    plotModeActive = true;
    Serial.tx_clear();
    k_send(" 1");
    check(logActive == true && logManualActive == true &&
          std::string(logFileName) == "ML0001.BLG",
          "'K 1' under plot mode: still opens a manual log exactly as without plot mode");
    plotModeActive = false;
}

// ─── 11q. FW-2 (S2): the 'active:' ownership marker ──────────────────────────
static void test_sdlog_k_status_ownership_marker() {
    test_group("SD log: the 'active:' status line's ownership marker (FW-2, review S2)");

    // Manual log open -> "(manual — K 0 stops)", never the profile marker.
    reset_test_state();
    mainState = 98;
    k_start_manual();
    Serial.tx_clear();
    k_send("");
    check(Serial.tx_contains("(manual") && !Serial.tx_contains("(profile-owned)"),
          "status marker: a manual log's status line carries the manual marker, not (profile-owned)");

    // Profile log open -> "(profile-owned)", never the manual marker.
    reset_test_state();
    sd_start_share_run();
    mainState = 98;
    Serial.tx_clear();
    k_send("");
    check(Serial.tx_contains("(profile-owned)") && !Serial.tx_contains("(manual"),
          "status marker: a profile-owned log's status line carries (profile-owned), not the manual marker");

    // Idle (nothing open) -> neither marker.
    reset_test_state();
    mainState = 98;
    Serial.tx_clear();
    k_send("");
    check(!Serial.tx_contains("(manual") && !Serial.tx_contains("(profile-owned)"),
          "status marker: with nothing running, neither ownership marker is printed");
}

// ─── 12. Velocity-validity flag and the three phase bytes ───────────────────
static void test_sdlog_velocity_flag_and_phases() {
    test_group("SD log: flags bit1 tracks the velocity chain; phase bytes track their own profile");

    // ── (a) Uncalibrated velocity chain: records are still written, bit1 clear ──
    reset_test_state();
    velocityChainCalibratedFlag = false;
    g_mock_millis = 10;
    g_mock_micros = 10000;
    logOpenForProfile(LOG_TYPE_PS);
    g_mock_micros += POWER_BAL_PERIOD_US;
    logSampleTick();
    logDrainTick();
    check(logRecordCount == 1,
          "SD velocity: a run with an uncalibrated velocity chain still writes records");
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE,
              "SD velocity: the uncalibrated run's record reaches the card");
        if (f) {
            uint8_t flags = (uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_FLAGS];
            check((flags & 0x02) == 0,
                  "SD velocity: flags bit1 is CLEAR when velocityChainCalibrated() is false");
        }
    }

    // Same sample with the chain calibrated → bit1 set.
    reset_test_state();
    velocityChainCalibratedFlag = true;
    g_mock_millis = 10;
    g_mock_micros = 10000;
    logOpenForProfile(LOG_TYPE_PS);
    g_mock_micros += POWER_BAL_PERIOD_US;
    logSampleTick();
    logDrainTick();
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && ((uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_FLAGS] & 0x02) != 0,
              "SD velocity: flags bit1 is SET when velocityChainCalibrated() is true");
    }

    // ── (b) 'D' drive cycle: dc_phase live, ps_phase/trap_phase 0xFF ────────
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 100;
    g_mock_micros = 100000;
    Serial.rx_queue.push('D');
    doState98();                       // start + first sample (dc_phase already 0)
    check(driveCycleActive == true && logActive == true,
          "SD phases: the 'D' drive cycle started and opened a DC log");
    check(std::string(logFileName) == "DC0001.BLG",
          "SD phases: a drive-cycle run opens a DC-prefixed file");
    logDrainTick();
    {
        const std::string* f = sd_file("DC0001.BLG");
        check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE,
              "SD phases: the drive cycle's first record reached the card");
        if (f && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE) {
            check((uint8_t)(*f)[6] == LOG_TYPE_DC,
                  "SD phases: the DC run's header type bitmask is LOG_TYPE_DC");
            check((uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_DC_PHASE] != LOG_PHASE_NONE,
                  "SD phases: dc_phase carries the live drive-cycle phase index during a 'D' run");
            check((uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_PS_PHASE] == LOG_PHASE_NONE &&
                  (uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_TRAP_PHASE] == LOG_PHASE_NONE,
                  "SD phases: ps_phase and trap_phase are 0xFF while only the drive cycle runs");
        }
    }

    // ── (c) 'R' power-share run: the reverse ────────────────────────────────
    reset_test_state();
    g_mock_millis = 100;
    g_mock_micros = 100000;
    sd_start_share_run();
    check(std::string(logFileName) == "PS0001.BLG",
          "SD phases: a power-share run opens a PS-prefixed file");
    logDrainTick();
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE,
              "SD phases: the share profile's first record reached the card");
        if (f && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE) {
            check((uint8_t)(*f)[6] == LOG_TYPE_PS,
                  "SD phases: the PS run's header type bitmask is LOG_TYPE_PS");
            check((uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_PS_PHASE] != LOG_PHASE_NONE,
                  "SD phases: ps_phase carries the live share-profile phase index during an 'R' run");
            check((uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_DC_PHASE] == LOG_PHASE_NONE &&
                  (uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_TRAP_PHASE] == LOG_PHASE_NONE,
                  "SD phases: dc_phase and trap_phase are 0xFF while only the share profile runs");
        }
    }
}

// ─── 13. Wedged card: the close deadline abandons the ring and closes anyway ─
// This is the C1 defect from the first-pass review: with the busy guard ahead of the deadline, a
// permanently-busy card took the early return forever — the file never closed, logCloseRequested
// never cleared, and every later profile start fell into the double-open branch. One dead card
// socket silently cost the whole bench session's logging.
static void test_sdlog_close_deadline_abandon() {
    test_group("SD log: a wedged card hits the close deadline, abandons the ring and still closes");
    reset_test_state();

    sd_start_share_run();
    sd_run_ms(20);                       // healthy card: these records physically reach the file
    uint32_t written = logRecordsWritten;
    // 21, not 20: the 'R' keypress tick itself takes the run's first sample (the log is opened
    // before logSampleTick() runs in that same doState98() invocation).
    check(written == 21 && logRingCount == 0,
          "SD deadline: the healthy phase drained every buffered record to the card");

    g_sd_state.busy_ticks = 1000000;     // card wedges permanently
    sd_run_ms(30);
    uint32_t abandoned = logRingCount;
    check(abandoned == 30 && logRecordsWritten == written,
          "SD deadline: samples taken during the wedge pile up in the ring, unwritten");

    Serial.tx_clear();
    Serial.rx_queue.push('X');
    doState98();
    check(logCloseRequested == true && logFile.isOpen() == true,
          "SD deadline: the stop flags the close while the card is still wedged");

    logDrainTick();
    check(logCloseRequested == true && logFile.isOpen() == true,
          "SD deadline: before the deadline elapses the drain politely waits for the card");

    g_mock_millis += LOG_CLOSE_DEADLINE_MS;
    logDrainTick();

    check(logActive == false && logCloseRequested == false,
          "SD deadline: the deadline clears both logger flags so the session is not poisoned");
    check(logFile.isOpen() == false,
          "SD deadline: the file handle is released even though the card never drained");
    check(Serial.tx_contains("abandoned (card did not drain)"),
          "SD deadline: the close line reports the abandoned records instead of claiming success");
    check(logLastAbandoned == abandoned && logLastRecordsWritten == written,
          "SD deadline: the 'last run' status counters preserve what was written and abandoned");

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * written + LOG_REC_SIZE,
          "SD deadline: the file holds exactly the records that physically drained, plus a trailer");
    if (f) {
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * written;
        check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu,
              "SD deadline: the abandoned close still writes a valid trailer sentinel");
        check(sd_le<uint32_t>(*f, tr + 4) == written,
              "SD deadline: the trailer reports records WRITTEN, not records sampled");
        check(sd_le<uint32_t>(*f, tr + 14) == abandoned,
              "SD deadline: the trailer's abandoned count is the ring remainder at close");
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_X,
              "SD deadline: the original close reason survives the deadline path");
    }

    // The whole point of the fix: the next run must log normally into a NEW file.
    g_sd_state.busy_ticks = 0;
    Serial.tx_clear();
    sd_start_share_run();
    check(logActive == true && std::string(logFileName) == "PS0002.BLG",
          "SD deadline: the next profile start opens a fresh file — the session is not poisoned");
    check(!Serial.tx_contains("previous log still open"),
          "SD deadline: the next run does not hit the double-open branch");
    sd_run_ms(5);
    check(logRecordsWritten == 6,          // 5 ticks + the 'R' keypress tick's own sample
          "SD deadline: the new run logs and drains normally after the wedged one was abandoned");
}

// ─── 14. A profile start while a close is still pending ─────────────────────
static void test_sdlog_pending_close_interleave() {
    test_group("SD log: starting a run over a pending close finishes the old file, skips the new");
    reset_test_state();

    sd_start_share_run();
    g_sd_state.busy_ticks = 1000000;     // card stalls, so the ring cannot drain
    sd_run_ms(10);
    uint32_t pending = logRingCount;
    check(pending == 11 && logRecordsWritten == 0,   // 10 ticks + the 'R' keypress tick's sample
          "SD interleave: the run's records are stuck in the ring with the card stalled");

    Serial.rx_queue.push('Q');
    doState98();
    check(mainState == 1 && logCloseRequested == true && logFile.isOpen() == true,
          "SD interleave: 'Q' leaves a close pending with the file still open");

    // Straight back into test mode and start another run while that close is unfinished.
    Serial.tx_clear();
    sd_start_share_run();

    check(powerShareProfileActive == true,
          "SD interleave: the new profile itself still runs — logging is never a precondition");
    check(Serial.tx_contains("[SD] previous log still open"),
          "SD interleave: the double-open defence reports that this run is NOT logged");
    check(logActive == false,
          "SD interleave: the new run is deliberately left unlogged rather than splicing two runs");
    check(logFile.isOpen() == false && logCloseRequested == false,
          "SD interleave: the stale handle is finished on the spot, not leaked");
    check(sd_only_log_name() == "PS0001.BLG",
          "SD interleave: no second .BLG is created for the refused run");

    // The old file must be complete and honest about what actually reached the card.
    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE,
          "SD interleave: the old file is header + trailer only (nothing drained past the stall)");
    if (f) {
        size_t tr = LOG_HDR_SIZE;
        check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu,
              "SD interleave: the old file is closed with a valid trailer sentinel");
        check(sd_le<uint32_t>(*f, tr + 4) == 0u && sd_le<uint32_t>(*f, tr + 14) == pending,
              "SD interleave: the trailer reports zero written and the whole ring abandoned");
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_Q,
              "SD interleave: the trailer keeps the ORIGINAL 'Q' close reason, not the new run's");
    }

    // With the close already finished, later drain ticks must be inert (no double trailer).
    g_sd_state.busy_ticks = 0;
    size_t sizeAfterClose = f ? f->size() : 0;
    for (int i = 0; i < 20; i++) logDrainTick();
    const std::string* f2 = sd_file("PS0001.BLG");
    check(f2 != nullptr && f2->size() == sizeAfterClose,
          "SD interleave: drain ticks after the close are inert — no second trailer is appended");
    check(logFile.isOpen() == false,
          "SD interleave: no file handle is left open once the card recovers");
}

// ─── 15. Drain across the ring wrap keeps records in logical order ──────────
static void test_sdlog_ring_wrap_drain() {
    test_group("SD log: a drain spanning the ring wrap writes records in logical order, no gaps");
    reset_test_state();

    g_mock_millis = 10;
    g_mock_micros = 10000;
    logOpenForProfile(LOG_TYPE_PS);
    check(logActive == true, "SD wrap: the log is open before the wrap sweep");

    // Stamp each record with its sequence number via share_sp (exactly representable as a float
    // for every value used here), so the decoded file proves ORDER, not just count.
    uint32_t seq = 0;
    auto fill = [&](int n) {
        for (int i = 0; i < n; i++) {
            power_share_setpoint = (float)seq++;
            g_mock_micros += POWER_BAL_PERIOD_US;
            logSampleTick();
        }
    };

    fill(900);                                  // head = 900 records, tail = 0
    check(logRingCount == 900 && logDroppedCount == 0,
          "SD wrap: 900 records buffer without dropping (under the 1024 capacity)");

    // format v5 (fw v11): LOG_REC_SIZE=76 -> floor(512/76)=6 records per LOG_CHUNK_MAX chunk (was
    // 7 at the old 68-byte record size). 70 ticks * 6 = 420 drained -- same 420 target as before,
    // reached with more ticks now that each chunk carries fewer records.
    for (int i = 0; i < 70; i++) logDrainTick();   // 6 records per tick → 420 drained
    check(logRecordsWritten == 420 && logRingTail == 420u * LOG_REC_SIZE,
          "SD wrap: a partial drain advances the tail off zero, leaving 480 records pending");

    fill(500);                                  // head passes the physical end of logRing
    check(logRingHead < logRingTail,
          "SD wrap: the head has wrapped past the end of the ring, so pending data spans the wrap");
    check(logRingCount == 980 && logDroppedCount == 0,
          "SD wrap: the refill stays inside capacity, so no sample is dropped");

    int guard = 0;
    while (logRingCount > 0 && guard++ < 500) logDrainTick();
    check(logRingCount == 0 && logRecordsWritten == 1400,
          "SD wrap: draining across the wrap boundary writes every one of the 1400 records");
    check(logRecordsWritten == logRecordCount,
          "SD wrap: records written to the card equals records committed to the ring");

    logRequestClose(LOG_CLOSE_STOP);
    sd_drain_until_closed();

    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * 1400u + LOG_REC_SIZE,
          "SD wrap: the file holds all 1400 records plus the trailer");
    if (f && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE * 1400u) {
        bool ordered = true;
        uint32_t firstBad = 0;
        for (uint32_t k = 0; k < 1400u; k++) {
            float s = sd_le<float>(*f, LOG_HDR_SIZE + LOG_REC_SIZE * k + REC_OFF_SHARE_SP);
            if (s != (float)k) { ordered = false; firstBad = k; break; }
        }
        if (!ordered) printf("    (first out-of-order record index: %u)\n", firstBad);
        check(ordered,
              "SD wrap: the decoded sequence is 0..1399 strictly increasing — no gap, no duplicate");
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * 1400u;
        check(sd_le<uint32_t>(*f, tr + 4) == 1400u && sd_le<uint32_t>(*f, tr + 14) == 0u,
              "SD wrap: the trailer reports all 1400 written and nothing abandoned");
    }
}

// ─── 16. Four-digit run counter exhausted ───────────────────────────────────
// At 9999 the next name would be 11 chars ("PS10000.BLG"), invisible to the 10-char scan filter —
// so every later run would re-derive the same name and O_TRUNC away the previous run's data.
static void test_sdlog_counter_exhausted() {
    test_group("SD log: an exhausted run counter refuses to log rather than overwrite a file");
    reset_test_state();

    g_sd_state.files["PS9999.BLG"] = "seeded";
    sd_start_share_run();

    check(Serial.tx_contains("[SD] run counter exhausted"),
          "SD counter: the exhausted 4-digit counter is reported to the operator");
    check(logActive == false && logFile.isOpen() == false,
          "SD counter: no log is opened once the counter is exhausted");
    check(g_sd_state.files.size() == 1 && sd_file("PS9999.BLG") != nullptr,
          "SD counter: no new file is created and the existing PS9999.BLG is untouched");
    check(*sd_file("PS9999.BLG") == "seeded",
          "SD counter: the last run's data is NOT truncated away by a re-derived name");
    check(powerShareProfileActive == true,
          "SD counter: the profile still runs — logging is never a precondition for a bench run");

    sd_run_ms(10);
    check(logRecordCount == 0 && logRingCount == 0,
          "SD counter: nothing is sampled while logging is disabled for the run");

    // The refusal is per-open, not a latch: freeing a slot lets the next run log again.
    g_sd_state.files.erase("PS9999.BLG");
    Serial.rx_queue.push('R');
    doState98();                       // stop the first run
    Serial.tx_clear();
    sd_start_share_run();
    check(logActive == true && std::string(logFileName) == "PS0001.BLG",
          "SD counter: the refusal is not a latch — a run logs again once a slot is free");
}

// ─── 17. The drain does no card I/O between State-99 teardown phases ─────────
// Review 2026-08-10 FW-R1-F1: write()/truncate()/close() are SYNCHRONOUS inside SdFat and
// isBusy() cannot bound an operation it merely precedes, so a close landing between the
// teardown's millis()-deadline dwells stretches them by the card's latency. The gate in
// logDrainTick() holds all card I/O until state99Phase == 3 (fully latched). This test pins
// BOTH halves: no truncate before the boosts are off, AND the unchanged 10/20 ms milestones.
static void test_sdlog_state99_drain_gated() {
    test_group("SD log: the drain is gated out of the State-99 teardown until it is fully latched");
    reset_test_state();

    sd_start_share_run();
    // Model a live bus: the boosts are on, so their going LOW marks teardown phase 2 completing.
    g_pin_value[FC_REG_ENABLE] = HIGH;
    g_pin_value[BT_REG_ENABLE] = HIGH;

    sd_run_ms(5);
    for (int i = 0; i < 10; i++) logDrainTick();     // empty the ring BEFORE the fault, so the
    check(logRingCount == 0 && logActive == true,    // close has nothing left to wait for — the
          "SD 99-gate: the ring is fully drained before the fault (the close-runs-immediately case)");
    check(g_sd_state.truncate_calls == 0,
          "SD 99-gate: nothing has been truncated yet — the file is still open and logging");

    const uint32_t t0 = g_mock_millis;
    triggerFault(FAULT_OC_FC, ERR_OC_FC);
    check(mainState == 99 && logCloseRequested == true && logRingCount == 0,
          "SD 99-gate: the fault latches State 99 with a close pending and an empty ring");

    // Run loop() as the real thing does: doState99() then logDrainTick(), 1 ms per tick.
    uint32_t motPwrLowAtMs   = 0;
    uint32_t truncateAtMs    = 0;
    bool     truncateWhileHot = false;   // a truncate seen while the boosts were still enabled
    for (int i = 0; i < 40; i++) {
        bool boostsWereHot = (digitalRead(FC_REG_ENABLE) == HIGH);
        int  truncBefore   = g_sd_state.truncate_calls;
        doState99();
        logDrainTick();
        if (g_sd_state.truncate_calls > truncBefore) {
            if (truncateAtMs == 0) truncateAtMs = g_mock_millis;
            if (boostsWereHot && digitalRead(FC_REG_ENABLE) == HIGH) truncateWhileHot = true;
        }
        if (motPwrLowAtMs == 0 && digitalRead(MOT_PWR_ENABLE) == LOW) motPwrLowAtMs = g_mock_millis;
        g_mock_millis += 1;
    }

    check(truncateWhileHot == false,
          "SD 99-gate: no truncate/close happens while the boosts are still enabled (phases 0-2)");
    check(motPwrLowAtMs == t0 + 10,
          "SD 99-gate: MOT_PWR_ENABLE still goes LOW at exactly t0+10 ms — teardown timing unchanged");
    check(digitalRead(FC_REG_ENABLE) == LOW && digitalRead(BT_REG_ENABLE) == LOW,
          "SD 99-gate: the teardown completes and disables both boosts");
    check(state99Phase == 3,
          "SD 99-gate: the teardown reaches the fully-latched phase 3");
    check(g_sd_state.truncate_calls == 1 && truncateAtMs >= t0 + 20,
          "SD 99-gate: the file is truncated/closed exactly once, only after the boosts are LOW");
    check(logFile.isOpen() == false && logCloseRequested == false,
          "SD 99-gate: the deferred close still completes — gating delays it, never drops it");

    // The file itself must be complete and correctly labelled.
    const std::string* f = sd_file("PS0001.BLG");
    check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE,
          "SD 99-gate: the log file exists with a header and at least one record");
    if (f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE) {
        size_t tr = f->size() - LOG_REC_SIZE;
        check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu,
              "SD 99-gate: the closed file ends in the trailer sentinel");
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_FAULT,
              "SD 99-gate: the trailer close reason is LOG_CLOSE_FAULT");
        check((uint8_t)(*f)[tr + 13] == (uint8_t)ERR_OC_FC,
              "SD 99-gate: the trailer carries the latched error_code");
    }
}

// ─── 18. A failed or partial directory scan never destroys an existing log ───
// Review 2026-08-10 FW-R1-F3: a failed root open used to fall through with maxIdx = 0 and the
// O_TRUNC create then erased <PREFIX>0001.BLG. Fixed at two layers — fail-closed scan, and
// O_EXCL so even a wrong index cannot truncate.
static void test_sdlog_scan_failure_preserves_files() {
    test_group("SD log: a failed/partial directory scan refuses to log rather than overwrite");

    // ── (a) Root open fails → hard refusal, existing files byte-identical ────
    reset_test_state();
    g_sd_state.files["PS0001.BLG"] = "OLD-RUN-DATA-DO-NOT-TOUCH";
    g_sd_state.files["PS0002.BLG"] = "second run";
    g_sd_state.fail_next_open = true;      // the root open in logNextFileName() is the next open
    Serial.tx_clear();
    sd_start_share_run();

    check(sd_file("PS0001.BLG") != nullptr &&
          *sd_file("PS0001.BLG") == "OLD-RUN-DATA-DO-NOT-TOUCH",
          "SD scan-fail: the oldest run's bytes are UNCHANGED after the failed scan");
    check(g_sd_state.files.size() == 2,
          "SD scan-fail: no new file is created when the directory scan fails");
    check(logActive == false && logFile.isOpen() == false,
          "SD scan-fail: logging is refused (fail-closed), not started on a guessed name");
    check(Serial.tx_contains("[SD] directory scan failed"),
          "SD scan-fail: the refusal names the cause — a scan failure, not a counter exhaustion");
    check(powerShareProfileActive == true,
          "SD scan-fail: the profile still runs — logging is never a precondition");

    // ── (b) Mid-scan read error → partial maxIdx, but no file is destroyed ───
    reset_test_state();
    for (int i = 1; i <= 5; i++) {
        char nm[16];
        snprintf(nm, sizeof(nm), "PS%04d.BLG", i);
        g_sd_state.files[nm] = "run data";
    }
    g_sd_state.fail_opennext_after_n = 2;   // the scan sees PS0001/PS0002, then errors out
    sd_start_share_run();

    for (int i = 1; i <= 5; i++) {
        char nm[16];
        snprintf(nm, sizeof(nm), "PS%04d.BLG", i);
        check(sd_file(nm) != nullptr && *sd_file(nm) == "run data",
              "SD partial-scan: every pre-existing log survives the truncated directory walk");
    }
    // The partial scan derives PS0003 (max seen = 2), which exists → O_EXCL refuses the create.
    check(logActive == false && logFile.isOpen() == false,
          "SD partial-scan: O_EXCL turns the collision into a refusal instead of a truncate");
    check(Serial.tx_contains("[SD] open failed"),
          "SD partial-scan: the refused exclusive create is reported to the operator");
    check(powerShareProfileActive == true,
          "SD partial-scan: the profile runs regardless");

    // ── (c) The mock's O_EXCL contract itself (the pin under both layers) ────
    reset_test_state();
    g_sd_state.files["PS0003.BLG"] = "existing";
    {
        FsFile f = sd.open("PS0003.BLG", O_WRITE | O_CREAT | O_EXCL);
        check(!f.isOpen(),
              "SD O_EXCL: an exclusive create over an existing name fails");
        check(*sd_file("PS0003.BLG") == "existing",
              "SD O_EXCL: the failed exclusive create leaves the file's bytes intact");
        FsFile g = sd.open("PS0004.BLG", O_WRITE | O_CREAT | O_EXCL);
        check(g.isOpen() && sd_file("PS0004.BLG") != nullptr,
              "SD O_EXCL: an exclusive create of a FREE name still succeeds");
        g.close();
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 'T' trapezoid SHARE-SETPOINT SWEEP  ("T <Imax> <hold> <rate> [t,r1,…,rn]")
// ═══════════════════════════════════════════════════════════════════════════════
// The contract under test is an UNATTENDED SEQUENCE: the operator types one line and walks away,
// so every failure here is silent and is only discovered from the card afterwards. Three things
// therefore get asserted hard: (1) the grammar is all-or-nothing — a malformed list must start
// NOTHING rather than a plain single run the operator believes is a sweep; (2) each run gets its
// own file, which requires the next run to wait for the logger to go fully idle (an early start
// makes logOpenForProfile() skip logging silently); (3) every operator stop path really does end
// the sequence, since a sweep that outlives 'X' is exactly the trap 'X' exists to prevent.

// Arm and type a trapezoid line through the real keypress path.
static void tsweep_type_line(const char* line) {
    Serial.rx_queue.push('T');
    doState98();
    feed_serial_line(line);
}

// Standard preconditions for a sweep case: State 98, motor node powered, clocks at a known origin.
static void tsweep_setup() {
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 1000;   // non-zero: a dwell comparison against a zero origin would pass by luck
    g_mock_micros = 1000000;
}

// One refusal case: the line must leave the prompt cleared, no trapezoid, and no sweep.
static void tsweep_check_refused(const char* line, const char* what) {
    tsweep_setup();
    tsweep_type_line(line);
    doState98();
    check(pendingInput == PEND_NONE && trapProfileActive == false && tsweepActive == false,
          what);
}

static void test_tsweep_parsing() {
    test_group("T sweep — grammar: a valid list arms the sequence, a malformed one starts nothing");

    // ── Valid 2-ratio list ───────────────────────────────────────────────────
    tsweep_setup();
    tsweep_type_line(" 6 3 1 [2,0.3,0.7]");
    check(tsweepActive == true && tsweepCount == 2 && tsweepIdx == 0,
          "T sweep: a 2-ratio list arms a 2-run sweep starting at run 1");
    check(tsweepDwellMs == 2000, "T sweep: the dwell seconds are committed in ms");
    check(fabsf(tsweepRatios[0] - 0.3f) < 1e-6f && fabsf(tsweepRatios[1] - 0.7f) < 1e-6f,
          "T sweep: the ratio list is committed in the order typed");
    check(trapProfileActive == true && fabsf(trapImax - 6.0f) < 1e-6f && trapHoldMs == 3000,
          "T sweep: run 1 starts immediately with the trapezoid parameters from the same line");
    check(fabsf(power_share_setpoint - 0.3f) < 1e-6f && powerBalanceLive == true,
          "T sweep: the FIRST ratio is applied as a live closed-loop setpoint before run 1");

    // ── Single-ratio list is legal (degenerate sweep = one run at a set share) ─
    tsweep_setup();
    tsweep_type_line(" 6 3 1 [5,0.42]");
    check(tsweepActive == true && tsweepCount == 1 && trapProfileActive == true,
          "T sweep: a single-ratio list is legal (one run at one setpoint)");
    check(fabsf(power_share_setpoint - 0.42f) < 1e-6f,
          "T sweep: the single ratio is applied as the setpoint");

    // ── Endpoints 0.0/1.0 are legal (channel-cutoff datapoints) ──────────────
    tsweep_setup();
    tsweep_type_line(" 6 3 1 [0,0,1]");
    check(tsweepActive == true && tsweepCount == 2 &&
          fabsf(tsweepRatios[0]) < 1e-6f && fabsf(tsweepRatios[1] - 1.0f) < 1e-6f,
          "T sweep: the full [0,1] span is accepted (endpoints are cutoff datapoints)");

    // ── Backward compatibility: the plain 3-value line is unchanged ──────────
    tsweep_setup();
    tsweep_type_line(" 6 3 1");
    check(trapProfileActive == true && tsweepActive == false,
          "T sweep: a plain 3-value 'T' line still starts a single NON-sweep run");

    // ── Refusals: every one must start nothing at all ────────────────────────
    tsweep_check_refused(" 6 3 1 [2,0.3,0.7",
                         "T sweep: a missing ']' refuses the whole line");
    tsweep_check_refused(" 6 3 1 []",
                         "T sweep: an empty list '[]' refuses the whole line");
    tsweep_check_refused(" 6 3 1 [2]",
                         "T sweep: a list with a dwell but no setpoints refuses the whole line");
    tsweep_check_refused(" 6 3 1 [2,0.3,]",
                         "T sweep: a non-numeric (missing) list value refuses the whole line");
    tsweep_check_refused(" 6 3 1 [2,1.5]",
                         "T sweep: a setpoint above 1.0 refuses the whole line");
    tsweep_check_refused(" 6 3 1 [2,-0.1]",
                         "T sweep: a negative setpoint refuses the whole line");
    tsweep_check_refused(" 6 3 1 [-1,0.3]",
                         "T sweep: a negative dwell refuses the whole line");
    tsweep_check_refused(" 6 3 1 [4000,0.3]",
                         "T sweep: a dwell beyond TSWEEP_DWELL_MAX_S refuses the whole line");
    tsweep_check_refused(" 6 3 1 [2,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1]",
                         "T sweep: more than TSWEEP_MAX_RATIOS setpoints refuses the whole line");
    tsweep_check_refused(" 6 3 1 [2,0.3] 5",
                         "T sweep: trailing text after ']' refuses the whole line");
    // The 4th-token rule: before the sweep existed this was silently ignored. It must NOT be —
    // a run the operator thinks is a sweep but isn't is the failure this rule prevents.
    tsweep_check_refused(" 6 3 1 5",
                         "T sweep: a bare 4th value (no '[') refuses the whole line");

    // ── Sweep + plot mode is refused (not silently reinterpreted) ────────────
    tsweep_setup();
    plotModeActive = true;
    tsweep_type_line(" 6 3 1 [2,0.3,0.7]");
    check(tsweepActive == false && trapProfileActive == false && plotArmTarget == PLOT_ARM_NONE,
          "T sweep: a sweep list under plot mode is refused (no sweep, no armed run)");
    // ...while a plain 'T' line under plot mode keeps its documented arming behaviour.
    tsweep_setup();
    plotModeActive = true;
    tsweep_type_line(" 6 3 1");
    check(plotArmTarget == PLOT_ARM_TRAP && tsweepActive == false,
          "T sweep: a plain 'T' line under plot mode still ARMS, unchanged");
    plotModeActive = false;
}

// Run the sweep's current trapezoid out to natural completion and let the logger drain.
// 140 ms covers the 100 ms profile used throughout these cases plus the tick that notices the
// completion and the handful of drain ticks that finish the file.
static void tsweep_run_out() { sd_run_ms(140); }

static void test_tsweep_end_to_end() {
    test_group("T sweep — two runs, two files, dwell honoured between them");
    tsweep_setup();

    // 100 ms triangle (5 A at 100 A/s = 50 ms up + 50 ms down), 1 s dwell, two setpoints.
    tsweep_type_line(" 5 0 100 [1,0.3,0.7]");
    check(trapProfileActive == true && fabsf(power_share_setpoint - 0.3f) < 1e-6f,
          "T sweep e2e: run 1 is live at share_sp = 0.3");
    check(std::string(logFileName) == "TP0001.BLG",
          "T sweep e2e: run 1 opens its own log, TP0001.BLG");

    tsweep_run_out();
    check(trapProfileActive == false && tsweepActive == true,
          "T sweep e2e: run 1 completing does NOT end the sweep");
    check(tsweepPhase == 2,
          "T sweep e2e: with the log drained the sweep sits in COOLDOWN");
    check(logActive == false && logCloseRequested == false,
          "T sweep e2e: run 1's file is closed before the cool-down starts");

    // Mid-dwell: nothing may start.
    sd_run_ms(500);
    check(trapProfileActive == false && sd_file("TP0002.BLG") == nullptr,
          "T sweep e2e: no run starts while the cool-down dwell is still running");

    // Past the dwell: run 2 fires with the SECOND setpoint and a NEW file. Ticked one ms at a
    // time and stopped at the fire: run 2 is only 100 ms long, so a coarse advance would sail
    // past its completion and assert against an already-finished sweep.
    for (int i = 0; i < 2000 && !trapProfileActive; i++) sd_run_ms(1);
    check(trapProfileActive == true && tsweepIdx == 1,
          "T sweep e2e: run 2 fires once the dwell elapses");
    check(fabsf(power_share_setpoint - 0.7f) < 1e-6f,
          "T sweep e2e: run 2 runs at the second setpoint (0.7)");
    check(std::string(logFileName) == "TP0002.BLG",
          "T sweep e2e: run 2 gets its own file, TP0002.BLG");

    tsweep_run_out();
    check(tsweepActive == false,
          "T sweep e2e: the sweep completes after the last run");
    check(fabsf(power_share_setpoint - 0.5f) < 1e-6f && powerBalanceLive == false,
          "T sweep e2e: completion restores the quiescent share state (0.5, loop off)");
    sd_drain_until_closed();

    // Both files must be complete, closed, and tagged as trapezoid runs.
    for (const char* nm : {"TP0001.BLG", "TP0002.BLG"}) {
        const std::string* f = sd_file(nm);
        check(f != nullptr && f->size() > LOG_HDR_SIZE + LOG_REC_SIZE,
              "T sweep e2e: each run left a populated file on the card");
        if (f == nullptr || f->size() < LOG_HDR_SIZE + LOG_REC_SIZE) continue;
        check((uint8_t)(*f)[6] == LOG_TYPE_TP,
              "T sweep e2e: each sweep file carries the LOG_TYPE_TP header bitmask");
        size_t nrec = (f->size() - LOG_HDR_SIZE) / LOG_REC_SIZE - 1;
        size_t tr   = LOG_HDR_SIZE + LOG_REC_SIZE * nrec;
        check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu,
              "T sweep e2e: each sweep file ends with the trailer sentinel");
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_COMPLETE,
              "T sweep e2e: each sweep run closes with LOG_CLOSE_COMPLETE (natural end)");
        // The first record must already carry the run's setpoint — the whole reason the setpoint
        // is applied BEFORE startTrapProfile() opens the log.
        float sp0 = sd_le<float>(*f, LOG_HDR_SIZE + 4);
        check(fabsf(sp0 - (std::string(nm) == "TP0001.BLG" ? 0.3f : 0.7f)) < 1e-6f,
              "T sweep e2e: the file's FIRST record already carries that run's share setpoint");
    }
}

static void test_tsweep_waits_for_log_idle() {
    test_group("T sweep — the next run waits for the logger to go fully idle");
    tsweep_setup();

    // Dwell 0: the ONLY thing that can hold run 2 back is the logger state.
    tsweep_type_line(" 5 0 100 [0,0.3,0.7]");
    check(trapProfileActive == true, "T sweep log-gate: run 1 started");

    // Run 1 out with the drain BLOCKED — the close request can never complete.
    sd_run_ms(140, /*drain=*/false);
    check(trapProfileActive == false && logCloseRequested == true,
          "T sweep log-gate: run 1 finished with its file still closing (drain blocked)");
    check(tsweepActive == true && tsweepPhase == 1,
          "T sweep log-gate: the sweep parks in WAIT_LOG rather than starting run 2");

    sd_run_ms(50, /*drain=*/false);
    check(trapProfileActive == false && tsweepIdx == 0,
          "T sweep log-gate: run 2 does NOT start while the close is pending, dwell 0 or not");

    // Release the drain; the next ticks let the sweep proceed.
    sd_drain_until_closed();
    check(logActive == false && logCloseRequested == false,
          "T sweep log-gate: the drain finished run 1's file");
    sd_run_ms(3);
    check(trapProfileActive == true && tsweepIdx == 1 &&
          fabsf(power_share_setpoint - 0.7f) < 1e-6f,
          "T sweep log-gate: run 2 starts on a later tick, once the logger is idle");
    check(std::string(logFileName) == "TP0002.BLG",
          "T sweep log-gate: run 2 still gets its own file (nothing was skipped)");
}

// Drive a sweep to its cool-down phase (run 1 complete, drained, dwell 10 s so it stays there).
static void tsweep_into_cooldown() {
    tsweep_setup();
    tsweep_type_line(" 5 0 100 [10,0.3,0.7]");
    sd_run_ms(140);
}

// ─── FW-1 (S1): 'K 1' is refused during a T-sweep's between-runs window ─────
// Regression for review round 2026-08-16: between sweep runs (WAIT_LOG/COOLDOWN) no profile flag
// is set and the logger is idle, so without the tsweepActive term in parseKLogLine()'s refusal
// list, 'K 1' would open an ML file that the next sweep run's logOpenForProfile() would then
// force-finish — silently costing that run its log. Lives here (after tsweep_into_cooldown()) so
// it can reuse that helper without a forward declaration.
static void test_sdlog_k1_refused_during_tsweep() {
    test_group("SD log: 'K 1' is refused during a T-sweep's between-runs window (FW-1, review S1)");

    tsweep_into_cooldown();   // run 1 complete + drained, 10 s dwell, tsweepPhase == 2 (COOLDOWN)
    check(tsweepActive == true && trapProfileActive == false && logActive == false,
          "tsweep x K1 setup: the sweep is parked in COOLDOWN with the logger idle — the exact "
          "window with no profile flag set that made the pre-fix 'K 1' look legal");
    check(g_sd_state.files.size() == 1,   // TP0001.BLG from run 1
          "tsweep x K1 setup: exactly run 1's file exists before the refused attempt");

    Serial.tx_clear();
    k_send(" 1");
    check(logActive == false && logManualActive == false,
          "tsweep x K1: 'K 1' does not open a manual log during the sweep's dwell window");
    check(g_sd_state.files.size() == 1,
          "tsweep x K1: no second file appears on the card");
    check(Serial.tx_contains("REFUSED: a profile owns the log"),
          "tsweep x K1: refused with the same message as any other profile-owned log");

    // The sweep's own run 2 must still fire and log normally afterward — the refused 'K 1' must
    // not have left any state behind that could interfere with it.
    sd_run_ms(9000);   // most of the 10 s dwell in one coarse jump
    for (int i = 0; i < 1000 && !trapProfileActive; i++) sd_run_ms(1);
    check(trapProfileActive == true && tsweepIdx == 1,
          "tsweep x K1: the sweep's run 2 still fires normally after the refused 'K 1'");
    check(std::string(logFileName) == "TP0002.BLG",
          "tsweep x K1: run 2 opens its own TP0002.BLG, unaffected by the refused manual attempt");
}

static void test_tsweep_cancel_paths() {
    test_group("T sweep — every operator stop path ends the sequence");

    // ── 'T' pressed mid-run-1 ────────────────────────────────────────────────
    tsweep_setup();
    tsweep_type_line(" 5 0 100 [1,0.3,0.7]");
    sd_run_ms(20);   // mid-ramp
    Serial.rx_queue.push('T');
    doState98();
    check(trapProfileActive == false && tsweepActive == false,
          "T sweep cancel: 'T' mid-run stops the trapezoid AND the sweep");
    check(fabsf(power_share_setpoint - 0.5f) < 1e-6f && powerBalanceLive == false,
          "T sweep cancel: the 'T' stop restores the quiescent share state");
    sd_drain_until_closed();
    sd_run_ms(2000);   // well past the 1 s dwell that would have fired run 2
    check(trapProfileActive == false && sd_file("TP0002.BLG") == nullptr,
          "T sweep cancel: no queued run fires after the 'T' stop");

    // ── 'T' pressed mid-cool-down (between runs) ─────────────────────────────
    // Toggle symmetry (review 2026-08-11): with the trapezoid idle between sweep
    // runs, 'T' must STOP the queued sweep, not open the parameter prompt and
    // leave run k+1 armed behind it.
    tsweep_into_cooldown();
    Serial.rx_queue.push('T');
    doState98();
    check(tsweepActive == false,
          "T sweep cancel: 'T' between runs stops the queued sweep");
    check(pendingInput == PEND_NONE,
          "T sweep cancel: 'T' between runs does NOT open the parameter prompt");
    check(fabsf(power_share_setpoint - 0.5f) < 1e-6f && powerBalanceLive == false,
          "T sweep cancel: the between-runs 'T' stop restores the quiescent share state");
    sd_run_ms(20000);
    check(trapProfileActive == false,
          "T sweep cancel: no run fires after the between-runs 'T' stop");

    // ── 'X' pressed mid-cool-down ────────────────────────────────────────────
    tsweep_into_cooldown();
    check(tsweepActive == true && tsweepPhase == 2, "T sweep cancel: (setup) sweep is cooling down");
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;   // set so we can confirm 'X' leaves it alone
    Serial.rx_queue.push('X');
    doState98();
    check(tsweepActive == false,
          "T sweep cancel: 'X' during the cool-down cancels the sweep");
    check(fabsf(power_share_setpoint - 0.5f) < 1e-6f && powerBalanceLive == false,
          "T sweep cancel: the 'X' cancel restores the quiescent share state");
    // A sweep between runs has no profile flag set, so 'X' keeps the TRAPEZOID's switch semantics.
    check(g_pin_value[MOT_PWR_ENABLE] == HIGH && g_pin_value[FC_CHARGE_ENABLE] == HIGH,
          "T sweep cancel: 'X' on a sweep leaves the path switches as-is (trapezoid semantics)");
    sd_run_ms(20000);
    check(trapProfileActive == false,
          "T sweep cancel: no run fires after 'X', dwell or not");

    // ── 'Q' pressed mid-cool-down ────────────────────────────────────────────
    tsweep_into_cooldown();
    Serial.rx_queue.push('Q');
    doState98();
    check(mainState == 1, "T sweep cancel: 'Q' still exits State 98");
    check(tsweepActive == false,
          "T sweep cancel: 'Q' cancels the sweep — no queued run survives into Idle");
    check(fabsf(power_share_setpoint - 0.5f) < 1e-6f && powerBalanceLive == false,
          "T sweep cancel: the 'Q' cancel restores the quiescent share state");

    // ── Another profile started mid-cool-down supersedes ─────────────────────
    tsweep_into_cooldown();
    setManualMotorCurrent(3.0f);   // 'R' precondition
    Serial.rx_queue.push('R');
    doState98();
    check(powerShareProfileActive == true, "T sweep cancel: (setup) 'R' started");
    check(tsweepActive == false,
          "T sweep cancel: starting the 'R' share profile supersedes and cancels the sweep");
    sd_run_ms(20000);
    check(trapProfileActive == false,
          "T sweep cancel: the superseded sweep never fires its remaining run");
}

static void test_tsweep_fire_time_preconditions() {
    test_group("T sweep — preconditions are re-checked at FIRE time, not just at type-in");
    tsweep_into_cooldown();

    // A bring-up started inside the dwell: the sweep must abandon rather than fire a trapezoid
    // into a running switch sequence (same rule, and same reason, as plotArmTick()).
    // The dwell is jumped rather than ticked out so the bring-up is still ACTIVE on the fire
    // tick: ticking it would run the bring-up machine to its own timeout first, which is a test
    // of busBringupTick(), not of this guard.
    g_mock_millis += 11000;
    bringupActive = true;
    doState98();
    check(tsweepActive == false,
          "T sweep fire-time: a bring-up started during the dwell cancels the sweep");
    check(trapProfileActive == false,
          "T sweep fire-time: the cancelled sweep does not start its queued run");
    check(fabsf(power_share_setpoint - 0.5f) < 1e-6f && powerBalanceLive == false,
          "T sweep fire-time: the cancel restores the quiescent share state");
    bringupActive = false;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 'Y' combined drive-cycle + power-share profile
// ═══════════════════════════════════════════════════════════════════════════════
// The contract under test is the REGION TABLE AS A WAVEFORM: this profile exists to excite the
// share loop and the velocity loop simultaneously so a system identification can be fitted to the
// result, so a wrong interpolation, a mis-scaled velocity waypoint or a clip applied on the wrong
// side of the interpolation silently produces a run that looks fine and fits wrong. Each case
// therefore asserts the two setpoints at named points on the table, computed here from the
// documented region durations rather than read back from the firmware's own arithmetic.
//
// Region start times, cumulative from the profile start (durations from COMBINED_PROFILE[]):
//   R0  0      R1  2000   R2  6000   R3  8000    R4  11000  R5  15000  R6  17000  R7  18500
//   R8  22000  R9  25000  R10 27000  R11 30000   R12 31500  R13 33000  R14 35000  R15 38000
//   end 40000 (the completion tick lands one millisecond later — see y_run_to())

#define Y_R0  0u
#define Y_R1  2000u
#define Y_R2  6000u
#define Y_R3  8000u
#define Y_R4  11000u
#define Y_R5  15000u
#define Y_R6  17000u
#define Y_R7  18500u
#define Y_R8  22000u
#define Y_R9  25000u
#define Y_R10 27000u
#define Y_R11 30000u
#define Y_R12 31500u
#define Y_R13 33000u
#define Y_R14 35000u
#define Y_R15 38000u
#define Y_END 40000u

static uint32_t g_y_t0 = 0;   // millis() at the moment startCombinedProfile() stamped its region 0

// Start a combined run through the REAL keypress + parameter-line path (not startCombinedProfile()
// directly), so the prompt, the parser and the preconditions are all in the loop.
// `params` is everything after the 'Y' on the line — "" is a bare Enter, i.e. run the defaults.
static void y_start(const char* params) {
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    velocityChainCalibratedFlag = true;
    Serial.rx_queue.push('Y');
    doState98();
    feed_serial_line(params);
    g_y_t0 = g_mock_millis;
}

// Advance to `tRel` ms after the profile start, ONE 1 ms control tick at a time. Tick granularity
// matters: advanceCombinedProfile() re-stamps combinedRegionStart from millis() at each region
// transition, so a coarse step would smear every subsequent region boundary by the step size and
// the assertions below would drift off the table.
static void y_run_to(uint32_t tRel, bool drain = false) {
    while (g_mock_millis < g_y_t0 + tRel) {
        g_mock_millis += 1;
        g_mock_micros += POWER_BAL_PERIOD_US;
        doState98();
        if (drain) logDrainTick();
    }
}

static bool near_f(float a, float b, float tol = 1e-4f) { return fabsf(a - b) <= tol; }

// ─── COMBINED_PROFILE[] table structure (fw v6 R5-R7 rework) ────────────────
// TP0074/TP0085-87 (fw v5 sweep) showed the R6 hi-bound share excursion coinciding with R5/R7's
// full-scale (v=1.0) load: the latch cut BT under ~2A and left FC solo above its ~2.1A source
// knee, collapsing the bus in ~40ms. R5 now ramps v DOWN to 0.3 ahead of the excursion, R6 runs
// the same s=1.00 step at 0.3*Imax, and R7 takes the s step-down at that same low load before
// ramping v back to 1.0 -- so R8 still enters from v=1.0 (its own down-step character is
// unchanged) and the total duration/region count are untouched. This test pins the table
// itself, independent of any region-walk timing test, so a future edit that silently reintroduces
// the full-load coincidence (or drifts the 40s total / 16-region count) fails here first.
static void test_combined_profile_table_fwv6() {
    test_group("COMBINED_PROFILE[] table structure (fw v6 R5-R7 rework)");

    check(COMBINED_PROFILE_REGIONS == 16, "combo table: exactly 16 regions");

    uint32_t total = 0;
    for (int i = 0; i < COMBINED_PROFILE_REGIONS; i++) total += COMBINED_PROFILE[i].durationMs;
    check(total == 40000u, "combo table: total duration is 40000 ms across all 16 regions");

    // R5: v ramps DOWN 1.0 -> 0.3 ahead of the excursion; share stays flat at 0.35.
    check(COMBINED_PROFILE[5].durationMs == 2000 &&
          near_f(COMBINED_PROFILE[5].v_start, 1.0f) && near_f(COMBINED_PROFILE[5].v_end, 0.3f) &&
          near_f(COMBINED_PROFILE[5].s_start, 0.35f) && near_f(COMBINED_PROFILE[5].s_end, 0.35f),
          "combo table: R5 == {2000, 1.0, 0.3, 0.35, 0.35}");

    // R6: the hi-bound share excursion now runs at LOW load (v flat at 0.3) -- the point of the
    // rework, so the fw v6 handoff guard sees a small doomed-channel current and the cut actually
    // fires here instead of deferring.
    check(COMBINED_PROFILE[6].durationMs == 1500 &&
          near_f(COMBINED_PROFILE[6].v_start, 0.3f) && near_f(COMBINED_PROFILE[6].v_end, 0.3f) &&
          near_f(COMBINED_PROFILE[6].s_start, 1.00f) && near_f(COMBINED_PROFILE[6].s_end, 1.00f),
          "combo table: R6 == {1500, 0.3, 0.3, 1.00, 1.00}");

    // R7: the share step-down happens at the same low load, then v ramps back up to 1.0.
    check(COMBINED_PROFILE[7].durationMs == 3500 &&
          near_f(COMBINED_PROFILE[7].v_start, 0.3f) && near_f(COMBINED_PROFILE[7].v_end, 1.0f) &&
          near_f(COMBINED_PROFILE[7].s_start, 0.35f) && near_f(COMBINED_PROFILE[7].s_end, 0.35f),
          "combo table: R7 == {3500, 0.3, 1.0, 0.35, 0.35}");

    // R8's entry condition (v arrives from 1.0, share arrives from 0.35, and itself steps to
    // v=0.5/s=0.65) must be UNCHANGED by the R5-R7 rework -- R7 ramping back up to 1.0 is exactly
    // what preserves this.
    check(COMBINED_PROFILE[8].durationMs == 3000 &&
          near_f(COMBINED_PROFILE[8].v_start, 0.5f) && near_f(COMBINED_PROFILE[8].v_end, 0.5f) &&
          near_f(COMBINED_PROFILE[8].s_start, 0.65f) && near_f(COMBINED_PROFILE[8].s_end, 0.65f),
          "combo table: R8 == {3000, 0.5, 0.5, 0.65, 0.65} -- unchanged by the fw v6 rework");
}

// ─── 1. Parameter line: defaults, one value, two values, the warn band ──────
static void test_y_params_and_defaults() {
    test_group("Y combined profile — parameter line: defaults, one value, two values, warn band");

    // ── Bare Enter runs the defaults. This prompt is the ONE that treats an empty line as
    // "accept", not "cancel", so it is the case most likely to regress into a silent no-op.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('Y');
    doState98();
    check(pendingInput == PEND_Y_PARAMS,
          "Y params: 'Y' arms the single-line parameter prompt");
    feed_serial_line("");
    check(combinedProfileActive == true,
          "Y params: a bare Enter starts the profile rather than cancelling the prompt");
    check(near_f(yProfileVmax, Y_VMAX_DEFAULT) && near_f(yProfileBoundLo, Y_BOUND_DEFAULT),
          "Y params: a bare Enter commits the documented defaults (Vmax 1.0 m/s, b 0)");
    check(combinedRegionIdx == 0 && combinedProfileActive,
          "Y params: the run begins at region 0");

    // ── One value sets Vmax and leaves b at its default.
    reset_test_state();
    y_start(" 2");
    check(combinedProfileActive == true,
          "Y params: a single value \"Y 2\" starts the profile");
    check(near_f(yProfileVmax, 2.0f) && near_f(yProfileBoundLo, 0.0f),
          "Y params: one value sets Vmax and leaves the share bound at its default");

    // ── Two values set both.
    reset_test_state();
    y_start(" 1 0.3");
    check(combinedProfileActive == true,
          "Y params: two values \"Y 1 0.3\" start the profile");
    check(near_f(yProfileVmax, 1.0f) && near_f(yProfileBoundLo, 0.3f),
          "Y params: two values commit both Vmax and the share bound");

    // ── b above the warn threshold is ACCEPTED with a warning, not refused: a tight band is a
    // legitimate way to keep a fragile bench setup off the share extremes.
    reset_test_state();
    y_start(" 1 0.4");
    check(combinedProfileActive == true,
          "Y params: b above Y_BOUND_WARN is accepted and the profile still starts");
    check(near_f(yProfileBoundLo, 0.4f),
          "Y params: the above-threshold bound is committed as typed");
    check(Serial.tx_contains("WARN: b > "),
          "Y params: a bound above Y_BOUND_WARN prints the compressed-plateau warning");

    // ── At exactly the warn threshold there must be NO warning (strict >, not >=).
    reset_test_state();
    y_start(" 1 0.35");
    check(combinedProfileActive == true && !Serial.tx_contains("WARN: b > "),
          "Y params: b exactly at Y_BOUND_WARN starts without a warning (the test is strict >)");
}

// ─── 2. Every refusal path leaves State 98 idle ─────────────────────────────
static void test_y_refusals() {
    test_group("Y combined profile — every refusal leaves the bench idle and unlogged");

    // Assert the common "nothing happened" postcondition for a refused start.
    auto check_idle = [&](const char* what) {
        char buf[160];
        snprintf(buf, sizeof(buf), "Y refusal (%s): no profile starts and no log file is opened", what);
        check(combinedProfileActive == false && logActive == false && g_sd_state.files.empty(), buf);
    };

    // ── (a) Keypress-time preconditions: the prompt is never even armed. ────
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    bringupActive = true;
    Serial.rx_queue.push('Y');
    doState98();
    check(pendingInput == PEND_NONE && Serial.tx_contains("bring-up in progress"),
          "Y refusal: 'Y' during a staged bring-up is refused at the keypress");
    check_idle("bring-up active");
    bringupActive = false;

    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    velocityChainCalibratedFlag = false;
    Serial.rx_queue.push('Y');
    doState98();
    check(pendingInput == PEND_NONE && Serial.tx_contains("combined profile needs a calibrated velocity chain"),
          "Y refusal: 'Y' with an uncalibrated velocity chain is refused by name");
    check_idle("velocity chain uncalibrated");

    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = LOW;
    Serial.rx_queue.push('Y');
    doState98();
    check(pendingInput == PEND_NONE && Serial.tx_contains("MOT_PWR_ENABLE must be HIGH"),
          "Y refusal: 'Y' with MOT_PWR_ENABLE LOW is refused at the keypress");
    check_idle("MOT_PWR low");

    // ── (b) Parse-time validation: the prompt arms, the line is rejected whole. ──
    reset_test_state();
    y_start(" 0");
    check(Serial.tx_contains("Vmax must be > 0"),
          "Y refusal: Vmax of zero is rejected");
    check_idle("Vmax = 0");

    reset_test_state();
    y_start(" -1");
    check(Serial.tx_contains("Vmax must be > 0"),
          "Y refusal: a negative Vmax is rejected");
    check_idle("Vmax negative");

    reset_test_state();
    y_start(" 6");
    check(Serial.tx_contains("Vmax must be <= "),
          "Y refusal: a Vmax above MANUAL_MOTOR_V_MAX is rejected against the same ceiling 'V' uses");
    check_idle("Vmax above MANUAL_MOTOR_V_MAX");

    reset_test_state();
    y_start(" 1 0.5");
    check(Serial.tx_contains("share bound b must be < 0.5"),
          "Y refusal: b = 0.5 is rejected because the band [b, 1-b] collapses to a point");
    check_idle("b = 0.5");

    reset_test_state();
    y_start(" 1 -0.1");
    check(Serial.tx_contains("share bound b must be >= 0"),
          "Y refusal: a negative share bound is rejected");
    check_idle("b negative");

    reset_test_state();
    y_start(" 1 0.3 2");
    check(Serial.tx_contains("at most two values"),
          "Y refusal: a third value is rejected rather than silently ignored");
    check_idle("third value");

    // ── (c) A non-numeric key cancels the pending entry outright. ───────────
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('Y');
    doState98();
    check(pendingInput == PEND_Y_PARAMS, "Y refusal: the parameter prompt is armed before the cancel");
    Serial.rx_queue.push('Z');            // not a numeric-entry char
    doState98();
    check(pendingInput == PEND_NONE && Serial.tx_contains("(input cancelled)"),
          "Y refusal: a non-numeric key cancels the parameter entry");
    Serial.rx_queue.push('\n');
    doState98();
    check_idle("non-numeric cancel");
}

// ─── 3. Full 40 s region walk at the defaults ───────────────────────────────
static void test_y_region_walk() {
    test_group("Y combined profile — both setpoints track the region table across the full run");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    check(combinedProfileActive && near_f(yProfileVmax, 1.0f) && near_f(yProfileBoundLo, 0.0f),
          "Y walk: the run starts at the defaults (Vmax 1.0, no share clip)");

    // R0 settle: both axes flat.
    y_run_to(1000);
    check(combinedRegionIdx == 0 && near_f(v_setpoint, 0.0f) && near_f(power_share_setpoint, 0.5f),
          "Y walk: R0 holds v=0 and share=0.50 while the bench settles");

    // R1 solo velocity ramp 0 -> 0.6 over 4000 ms; midpoint is half way up.
    y_run_to(Y_R1 + 2000);
    check(combinedRegionIdx == 1 && near_f(v_setpoint, 0.3f, 1e-3f),
          "Y walk: R1 midpoint has v_setpoint half way up the 0 -> 0.6 ramp (0.30)");
    check(near_f(power_share_setpoint, 0.5f),
          "Y walk: R1 leaves the share axis flat — the velocity ramp is a SOLO excitation");

    // R2 buffer: velocity has arrived, share still flat.
    y_run_to(Y_R2 + 1000);
    check(combinedRegionIdx == 2 && near_f(v_setpoint, 0.6f) && near_f(power_share_setpoint, 0.5f),
          "Y walk: R2 buffers at v=0.6 with the share still at 0.50");

    // R3 entry: the share STEPS to 0.65 on the first tick of the region while v holds.
    y_run_to(Y_R3 - 1);
    check(near_f(power_share_setpoint, 0.5f),
          "Y walk: the share is still 0.50 on the last tick before R3");
    y_run_to(Y_R3 + 1);
    check(combinedRegionIdx == 3 && near_f(power_share_setpoint, 0.65f, 1e-3f),
          "Y walk: R3 steps the share to 0.65 on its first tick (a step is a start-value mismatch)");
    check(near_f(v_setpoint, 0.6f),
          "Y walk: R3's share step leaves the velocity axis untouched — a SOLO share excitation");

    // R4: BOTH axes ramp at once (v up, s down) — the interaction test.
    y_run_to(Y_R4 + 2000);
    check(combinedRegionIdx == 4 && near_f(v_setpoint, 0.8f, 1e-3f),
          "Y walk: R4 midpoint has v_setpoint mid-ramp between 0.6 and 1.0 (0.80)");
    check(near_f(power_share_setpoint, 0.5f, 1e-3f),
          "Y walk: R4 midpoint has the share mid-ramp between 0.65 and 0.35 (0.50) — both axes move");

    // R5 (fw v6): v ramps DOWN 1.0 -> 0.3 ahead of the excursion; midpoint is half way down.
    // Share stays flat at 0.35 -- a SOLO velocity excitation, mirroring R1's shape.
    y_run_to(Y_R5 + 1000);
    check(combinedRegionIdx == 5 && near_f(v_setpoint, 0.65f, 1e-3f),
          "Y walk: R5 midpoint has v_setpoint half way down the 1.0 -> 0.3 ramp (0.65)");
    check(near_f(power_share_setpoint, 0.35f, 1e-3f),
          "Y walk: R5 leaves the share axis flat at 0.35 while the velocity ramps down");

    // R6 (fw v6): brief excursion to the high share bound, now at LOW load (v flat at 0.3) --
    // the whole point of the R5-R7 rework (TP0074/85-87: the excursion used to coincide with
    // full-scale load and collapsed the bus).
    y_run_to(Y_R6 + 750);
    check(combinedRegionIdx == 6 && near_f(power_share_setpoint, 1.0f),
          "Y walk: R6 drives the share to 1.00 (all-FC) to exercise the droop clamp");
    check(near_f(v_setpoint, 0.3f),
          "Y walk: R6 holds the velocity at the LOW-load plateau (0.3) through the share "
          "excursion (fw v6 -- this used to be full scale, 1.0)");

    // R8 entry: BOTH axes step in the SAME tick (v 1.0 -> 0.5, s 0.35 -> 0.65). R7 (fw v6) now
    // RAMPS v back up to 1.0 rather than holding it flat, so "the last tick before R8" is one
    // discrete step short of the asymptote (3499/3500 of the way up the ramp), not bit-exact --
    // widen the tolerance accordingly rather than asserting an unreachable exact 1.0.
    y_run_to(Y_R8 - 1);
    check(near_f(v_setpoint, 1.0f, 5e-4f) && near_f(power_share_setpoint, 0.35f, 1e-3f),
          "Y walk: R7 ends at v~1.0 / share=0.35 on the last tick before R8 (fw v6: R7 ramps up "
          "to 1.0 rather than holding it, so this is the last-step approach, not an exact value)");
    y_run_to(Y_R8 + 1);
    check(combinedRegionIdx == 8 && near_f(v_setpoint, 0.5f, 1e-3f) &&
          near_f(power_share_setpoint, 0.65f, 1e-3f),
          "Y walk: R8 steps BOTH axes in the same tick (v down to 0.5, share up to 0.65)");

    // R10 solo share ramp 0.65 -> 0.0; midpoint is half way down.
    y_run_to(Y_R10 + 1500);
    check(combinedRegionIdx == 10 && near_f(power_share_setpoint, 0.325f, 1e-3f),
          "Y walk: R10 midpoint has the share half way down the 0.65 -> 0 ramp (0.325)");
    check(near_f(v_setpoint, 0.5f),
          "Y walk: R10's share ramp leaves the velocity axis flat at 0.5");

    // R11 brief excursion to the low share bound.
    y_run_to(Y_R11 + 750);
    check(combinedRegionIdx == 11 && near_f(power_share_setpoint, 0.0f),
          "Y walk: R11 drives the share to 0.00 (all-BT) to exercise the other clamp");

    // R13 solo velocity step down.
    y_run_to(Y_R13 + 1000);
    check(combinedRegionIdx == 13 && near_f(v_setpoint, 0.2f, 1e-3f) &&
          near_f(power_share_setpoint, 0.5f),
          "Y walk: R13 steps the velocity down to 0.2 with the share recovered to 0.50");

    // R14 coast-down ramp 0.2 -> 0; midpoint.
    y_run_to(Y_R14 + 1500);
    check(combinedRegionIdx == 14 && near_f(v_setpoint, 0.1f, 1e-3f),
          "Y walk: R14 coasts the velocity down, half way at 0.10");

    // R15 -> natural completion.
    y_run_to(Y_R15 + 1000);
    check(combinedRegionIdx == 15 && near_f(v_setpoint, 0.0f),
          "Y walk: R15 holds at standstill before completion");
    vesc.reset();
    y_run_to(Y_END + 1);
    check(combinedProfileActive == false,
          "Y walk: the profile deactivates on natural completion after the last region");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "Y walk: natural completion flushes vesc.setCurrent(0) — the motor is not left driving");
    check(near_f(power_share_setpoint, 0.5f),
          "Y walk: natural completion returns the share setpoint to balanced (0.50)");
    check(manualMotorMode == MOTOR_TEST_OFF,
          "Y walk: natural completion clears manualMotorMode (haltMotorOutput symmetry)");

    sd_drain_until_closed();
    const std::string* f = sd_file("YP0001.BLG");
    check(f != nullptr && f->size() > LOG_HDR_SIZE + LOG_REC_SIZE,
          "Y walk: the run's log file exists and holds records");
    if (f) {
        size_t tr = f->size() - LOG_REC_SIZE;
        check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu &&
              (uint8_t)(*f)[tr + 12] == LOG_CLOSE_COMPLETE,
              "Y walk: the trailer records LOG_CLOSE_COMPLETE for a naturally-finished run");
    }
}

// ─── 4. Share clipping is applied AFTER interpolation ───────────────────────
// The kink is the whole point: a ramp that crosses the bound must keep its slope and then flatten.
// Clipping the waypoints instead would shrink every slope and change the excitation the
// identification is fitted to — a wrong answer that looks like a clean run.
static void test_y_clip_bounds() {
    test_group("Y combined profile — the share band clips after interpolation, producing a kink");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start(" 1 0.3");   // band [0.30, 0.70]
    check(combinedProfileActive && near_f(yProfileBoundLo, 0.3f),
          "Y clip: the run starts with the share band [0.30, 0.70]");

    // Intermediate plateaus sit INSIDE the band and must be untouched.
    y_run_to(Y_R3 + 1500);
    check(near_f(power_share_setpoint, 0.65f, 1e-3f),
          "Y clip: R3's 0.65 plateau is inside [0.30, 0.70] and passes through unclipped");

    // The bound-check excursions are the ones that flatten.
    y_run_to(Y_R6 + 750);
    check(near_f(power_share_setpoint, 0.7f),
          "Y clip: R6's 1.00 excursion flattens at the upper bound 0.70");

    y_run_to(Y_R8 + 1500);
    check(near_f(power_share_setpoint, 0.65f, 1e-3f),
          "Y clip: R8's 0.65 plateau is still unclipped after the excursion");

    // R10 ramps 0.65 -> 0 over 3000 ms. It crosses 0.30 at
    //   t = 3000 * (0.65 - 0.30) / 0.65 = 3000 * 0.538461... = 1615.4 ms.
    // Before that the ramp runs at its full slope; after it, the value is pinned at the bound.
    y_run_to(Y_R10 + 1000);
    check(near_f(power_share_setpoint, 0.65f - 0.65f * (1000.0f / 3000.0f), 1e-3f),
          "Y clip: R10 at 1000 ms is still on the un-clipped ramp slope (0.4333)");
    y_run_to(Y_R10 + 1500);
    check(near_f(power_share_setpoint, 0.325f, 1e-3f),
          "Y clip: R10 at its midpoint is 0.325 — still above the bound, so still on-slope");
    y_run_to(Y_R10 + 1600);
    check(near_f(power_share_setpoint, 0.65f - 0.65f * (1600.0f / 3000.0f), 1e-3f) &&
          power_share_setpoint > 0.3f,
          "Y clip: R10 at 1600 ms is the last on-slope sample before the 1615 ms crossing");
    y_run_to(Y_R10 + 1630);
    check(near_f(power_share_setpoint, 0.3f),
          "Y clip: R10 at 1630 ms has crossed the bound and is pinned at 0.30 — the kink");
    y_run_to(Y_R10 + 2500);
    check(near_f(power_share_setpoint, 0.3f),
          "Y clip: R10 stays flat at 0.30 for the rest of the ramp instead of continuing down");

    y_run_to(Y_R11 + 750);
    check(near_f(power_share_setpoint, 0.3f),
          "Y clip: R11's 0.00 excursion flattens at the lower bound 0.30");

    // Velocity is NOT affected by the share band.
    check(near_f(v_setpoint, 0.5f),
          "Y clip: the share band never touches the velocity axis");

    // ── An aggressive band eats the intermediate plateaus too — this is exactly what the
    // Y_BOUND_WARN message warns about, so it must actually happen.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start(" 1 0.4");   // band [0.40, 0.60]
    y_run_to(Y_R3 + 1500);
    check(near_f(power_share_setpoint, 0.6f),
          "Y clip: with b=0.4 the 0.65 intermediate plateau is compressed to the 0.60 bound");
    y_run_to(Y_R5 + 1000);
    check(near_f(power_share_setpoint, 0.4f),
          "Y clip: with b=0.4 the 0.35 intermediate plateau is compressed to the 0.40 bound");
    y_run_to(Y_R6 + 750);
    check(near_f(power_share_setpoint, 0.6f),
          "Y clip: with b=0.4 the 1.00 excursion flattens at 0.60");
}

// ─── 5. Velocity waypoints scale with the operator Vmax ─────────────────────
static void test_y_vmax_scaling() {
    test_group("Y combined profile — normalised velocity waypoints scale with the operator Vmax");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start(" 2");
    check(near_f(yProfileVmax, 2.0f), "Y Vmax: the run committed Vmax = 2.0 m/s");

    // R1's 0.6 end value, observed on R2's flat hold (the transition tick itself sets nothing).
    y_run_to(Y_R2 + 1000);
    check(combinedRegionIdx == 2 && near_f(v_setpoint, 1.2f, 1e-3f),
          "Y Vmax: R1's normalised 0.6 endpoint scales to 1.2 m/s at Vmax = 2");
    check(near_f(power_share_setpoint, 0.5f),
          "Y Vmax: the share axis is unaffected by Vmax — it is absolute, not normalised");

    // R5 (fw v6) midpoint: normalised 0.65 (half way down the 1.0 -> 0.3 ramp) scales too.
    y_run_to(Y_R5 + 1000);
    check(combinedRegionIdx == 5 && near_f(v_setpoint, 1.3f, 1e-3f),
          "Y Vmax: R5's normalised 0.65 midpoint scales to 1.3 m/s at Vmax = 2");
    check(near_f(power_share_setpoint, 0.35f, 1e-3f),
          "Y Vmax: R5's share plateau is the same 0.35 the defaults produce");

    // R8's 0.5 step.
    y_run_to(Y_R8 + 1500);
    check(combinedRegionIdx == 8 && near_f(v_setpoint, 1.0f, 1e-3f),
          "Y Vmax: R8's normalised 0.5 step scales to 1.0 m/s at Vmax = 2");
    check(near_f(power_share_setpoint, 0.65f, 1e-3f),
          "Y Vmax: R8's share plateau is the same 0.65 the defaults produce");

    // R1 midpoint scales too (the ramp, not just the plateaus).
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start(" 2");
    y_run_to(Y_R1 + 2000);
    check(near_f(v_setpoint, 0.6f, 1e-3f),
          "Y Vmax: mid-ramp values scale too — R1's midpoint is 0.3 x 2 = 0.6 m/s");
}

// ─── 6. Stop paths and mutual exclusion with the other profiles ─────────────
static void test_y_stop_x_q_exclusion() {
    test_group("Y combined profile — stop-toggle, 'X', 'Q' and mutual exclusion with D/R/T");

    // ── (a) 'Y' again mid-run stops it: motor zeroed, switches parked, share reset. ──
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    y_run_to(Y_R4 + 1000, /*drain=*/true);
    check(combinedProfileActive && combinedRegionIdx == 4,
          "Y stop: the run is mid-R4 before the stop key");
    uint32_t recs = logRecordsWritten;
    g_pin_value[REGEN_ENABLE] = HIGH;   // a latched path switch the stop must park
    vesc.reset();
    Serial.rx_queue.push('Y');
    doState98();
    check(combinedProfileActive == false,
          "Y stop: the 'Y' stop-toggle clears combinedProfileActive");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "Y stop: the stop flushes vesc.setCurrent(0) immediately");
    check(digitalRead(REGEN_ENABLE) == LOW,
          "Y stop: the stop parks the path switches (this profile sweeps the charge paths)");
    check(near_f(power_share_setpoint, 0.5f),
          "Y stop: the stop returns the share setpoint to balanced");
    check(logCloseRequested == true,
          "Y stop: the stop requests the log close without doing card I/O in the handler");
    sd_drain_until_closed();
    {
        const std::string* f = sd_file("YP0001.BLG");
        check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
              "Y stop: the stopped run's file holds every drained record plus the trailer");
        if (f) {
            size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
            check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_STOP,
                  "Y stop: the trailer records LOG_CLOSE_STOP");
        }
    }

    // ── (b) 'X' universal stop mid-run. ────────────────────────────────────
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    y_run_to(Y_R6 + 500, /*drain=*/true);
    recs = logRecordsWritten;
    g_pin_value[REGEN_ENABLE] = HIGH;
    vesc.reset();
    Serial.rx_queue.push('X');
    doState98();
    check(combinedProfileActive == false && manualMotorMode == MOTOR_TEST_OFF,
          "Y 'X': the universal stop cancels the combined profile and the manual modes");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "Y 'X': the universal stop zeroes the motor");
    check(digitalRead(REGEN_ENABLE) == LOW,
          "Y 'X': hadY makes the universal stop park the switches, as it does for 'D'/'R'");
    check(near_f(power_share_setpoint, 0.5f),
          "Y 'X': hadY resets the share setpoint, matching the 'R' semantics");
    sd_drain_until_closed();
    {
        const std::string* f = sd_file("YP0001.BLG");
        check(f != nullptr, "Y 'X': the run's log file was written");
        if (f) {
            size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
            check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_X,
                  "Y 'X': the trailer records LOG_CLOSE_X");
        }
    }

    // ── (c) 'Q' exit mid-run. ──────────────────────────────────────────────
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    y_run_to(Y_R2 + 500, /*drain=*/true);
    recs = logRecordsWritten;
    vesc.reset();
    Serial.rx_queue.push('Q');
    doState98();
    check(combinedProfileActive == false && mainState == 1,
          "Y 'Q': the exit clears the combined profile and returns to Idle");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "Y 'Q': the exit flushes vesc.setCurrent(0) before cutting motor power");
    check(logCloseRequested == true,
          "Y 'Q': the exit flags the log close, to be finished by the drain in loop()");
    sd_drain_until_closed();
    {
        const std::string* f = sd_file("YP0001.BLG");
        check(f != nullptr, "Y 'Q': the run's log file was written");
        if (f) {
            size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
            check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_Q,
                  "Y 'Q': the trailer records LOG_CLOSE_Q");
        }
    }

    // ── (d) Mutual exclusion, Y killed by the others. ──────────────────────
    reset_test_state();
    g_mock_millis = 1000;
    y_start("");
    check(combinedProfileActive, "Y exclusion: a combined run is active before 'D' is pressed");
    Serial.rx_queue.push('D');
    doState98();
    check(driveCycleActive == true && combinedProfileActive == false,
          "Y exclusion: starting the drive cycle clears the combined profile");

    reset_test_state();
    g_mock_millis = 1000;
    y_start("");
    setManualMotorCurrent(3.0f);          // 'R' precondition
    Serial.rx_queue.push('R');
    doState98();
    check(powerShareProfileActive == true && combinedProfileActive == false,
          "Y exclusion: starting the power-share profile clears the combined profile");

    // ── (e) Mutual exclusion, the others killed by Y. ──────────────────────
    reset_test_state();
    g_mock_millis = 1000;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    Serial.rx_queue.push('R');
    doState98();
    check(powerShareProfileActive == true, "Y exclusion: a share profile is running before 'Y'");
    y_start("");
    check(combinedProfileActive == true && powerShareProfileActive == false,
          "Y exclusion: starting the combined profile clears a running power-share profile");

    reset_test_state();
    g_mock_millis = 1000;
    trapProfileActive = true;             // a shadowed trapezoid would resume with a huge elapsed
    trapCmdA          = 3.5f;
    y_start("");
    check(combinedProfileActive == true && trapProfileActive == false && trapCmdA == 0.0f,
          "Y exclusion: starting the combined profile clears an active trapezoid and its command");

    reset_test_state();
    g_mock_millis = 1000;
    driveCycleActive = true;
    y_start("");
    check(combinedProfileActive == true && driveCycleActive == false,
          "Y exclusion: starting the combined profile clears a running drive cycle");
}

// ─── 7. Logging: YP prefix, combined typemask, both phase bytes ─────────────
static void test_y_logging() {
    test_group("Y combined profile — logs under the YP prefix with both phase bytes set");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    check(logActive == true && std::string(logFileName) == "YP0001.BLG",
          "Y logging: a combined run files under the YP prefix, not PS");

    // Run into R3 so the sampled region index is unambiguous (non-zero, and the same on both axes).
    y_run_to(Y_R3 + 1500, /*drain=*/true);
    check(combinedRegionIdx == 3, "Y logging: the run is inside region 3 when the record is taken");
    uint32_t lastIdx = logRecordsWritten - 1;

    const std::string* f = sd_file("YP0001.BLG");
    check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE * (lastIdx + 1),
          "Y logging: the records reached the card");
    if (f && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE * (lastIdx + 1)) {
        check((uint8_t)(*f)[6] == (uint8_t)(LOG_TYPE_PS | LOG_TYPE_DC),
              "Y logging: the header type field is the PS|DC bitmask, telling the decoder the two "
              "phase bytes are one axis");
        size_t rec = LOG_HDR_SIZE + LOG_REC_SIZE * lastIdx;
        check((uint8_t)(*f)[rec + REC_OFF_PS_PHASE] == 3 &&
              (uint8_t)(*f)[rec + REC_OFF_DC_PHASE] == 3,
              "Y logging: the region index is written into BOTH ps_phase and dc_phase");
        check((uint8_t)(*f)[rec + REC_OFF_TRAP_PHASE] == LOG_PHASE_NONE,
              "Y logging: trap_phase stays 0xFF — the trapezoid is not part of this profile");
        check(((uint8_t)(*f)[rec + REC_OFF_FLAGS] & 0x01) != 0,
              "Y logging: flags bit0 marks the combined profile as driving powerBalance");
        // The velocity axis is genuinely commanded here, so the record's v_sp must be non-zero.
        check(sd_le<float>(*f, rec + REC_OFF_V_SP) > 0.0f,
              "Y logging: the record's v_sp carries the profile's commanded velocity");
    }

    // ── Name collision: the YP prefix participates in the shared run counter. ──
    reset_test_state();
    g_sd_state.files["YP0007.BLG"] = "";
    g_mock_millis = 1000;
    y_start("");
    check(std::string(logFileName) == "YP0008.BLG",
          "Y logging: an existing YP0007.BLG makes the next combined run YP0008.BLG");

    // ── A later PS run must not be misfiled, and must see the YP index. ────
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    check(std::string(logFileName) == "YP0001.BLG", "Y logging: the combined run opened YP0001.BLG");
    Serial.rx_queue.push('Y');
    doState98();                       // stop it
    sd_drain_until_closed();
    setManualMotorCurrent(3.0f);
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('R');
    doState98();
    check(std::string(logFileName) == "PS0002.BLG",
          "Y logging: a power-share run after a combined run files as PS and continues the shared "
          "counter (the YP file is seen by the scan)");
}

// ─── 8. Status line, plot suppression, VESC-watch and 'G' interlocks ────────
static void test_y_status_and_suppression() {
    test_group("Y combined profile — [YP] status cadence, plot suppression and interlocks");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    Serial.tx_clear();
    y_run_to(1000);
    check(Serial.tx_count("[YP] t=") == 2,
          "Y status: the [YP] snapshot prints on the 500 ms cadence (twice in the first second)");
    check(Serial.tx_contains("[YP] t=") && Serial.tx_contains(" R") &&
          Serial.tx_contains(" v_sp=") && Serial.tx_contains(" sp=") &&
          Serial.tx_contains(" act=") && Serial.tx_contains(" I_fc=") &&
          Serial.tx_contains(" I_bt=") && Serial.tx_contains(" V_bus=") &&
          Serial.tx_contains(" FLT=0x"),
          "Y status: the snapshot carries the region, both setpoints, the measured share, the "
          "currents, the bus and the fault word");

    // ── Plot mode suppresses it: a non-numeric line breaks the plotter parse. ──
    plotModeActive = true;
    plotLastMs     = g_mock_millis;
    Serial.tx_clear();
    y_run_to(2000);
    check(Serial.tx_count("[YP] t=") == 0,
          "Y status: the [YP] snapshot is suppressed while the plot stream is running");
    check(Serial.tx_count("share_sp:") > 0,
          "Y status: the plot stream itself keeps emitting while the combined profile runs");
    check(combinedProfileActive && combinedRegionIdx > 0,
          "Y status: the region machine keeps advancing while the status lines are suppressed");

    // ── ...and it comes back when the stream is turned off. ────────────────
    plotModeActive = false;
    Serial.tx_clear();
    y_run_to(3000);
    check(Serial.tx_count("[YP] t=") >= 1,
          "Y status: the [YP] snapshot resumes once the plot stream is off");

    // ── The blocking VESC read-back poll is suppressed for production-identical timing. ──
    vescWatchActive = true;
    lastVescWatchMs = 0;
    g_mock_millis  += VESC_WATCH_PERIOD_MS + 1;   // period elapsed — would poll if not suppressed
    vesc.reset();
    doState98();
    check(vesc.getValues_calls == 0,
          "Y interlock: pollVescWatch() does not run its blocking poll while the combined profile "
          "is active");
    vescWatchActive = false;

    // ── 'G' must refuse over a running profile: it would fight the switch sequencing. ──
    Serial.tx_clear();
    Serial.rx_queue.push('G');
    doState98();
    check(Serial.tx_contains("[G] REFUSED: a profile is running") && bringupActive == false,
          "Y interlock: 'G' refuses to arm the staged bring-up while the combined profile runs");

    // ── An armed plot-mode profile must not fire into a running combined run. ──
    plotModeActive    = true;
    plotArmTarget     = PLOT_ARM_SHARE;
    plotArmDeadlineMs = g_mock_millis;
    Serial.tx_clear();
    plotArmTick();
    check(plotArmTarget == PLOT_ARM_NONE && powerShareProfileActive == false &&
          combinedProfileActive == true,
          "Y interlock: an armed plot-mode start is cancelled rather than stomping the running "
          "combined profile");
}

// ─── 9. The combined profile must NOT run the charging manager ─────────────
// Load-bearing omission, not tidiness: chargingControl()'s cruise branch calls
// assertFcChargeEnable(true), whose guard drives BT_BUS_ENABLE LOW. That takes the battery off
// the bus mid-run, so I_batt → 0 and the MEASURED share pins at 1.0 — every share datapoint after
// that instant is garbage, on the one profile whose entire purpose is measuring the share axis.
static void test_y_no_charging_manager() {
    test_group("Y combined profile — the charging manager never runs (it would corrupt the share)");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    // A charge intent the manager WOULD act on, plus the switch state it would disturb.
    charge_goal = 0.5f;
    g_pin_value[BT_BUS_ENABLE]    = HIGH;
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    // Current actually flowing in both channels: powerBalance() deliberately no-ops when the total
    // is zero (the measured share is undefined), so without this the droop assertion below would
    // pass vacuously on a loop that never ran.
    I_fc   = 2.0f;
    I_batt = 2.0f;

    // NOTE (2026-08-10 full-span actuation): BT_BUS_ENABLE is now ALSO written by
    // applyShareRatio()'s channel cutoff when the commanded droop ratio leaves
    // [DROOP_R_MIN, DROOP_R_MAX]. FC_CHARGE_ENABLE is therefore the clean discriminator — only
    // chargingControl() ever writes it — and the BT_BUS assertions below are deliberately confined
    // to the mid-share regions, where the ratio stays inside the band and no cutoff can fire.
    //
    // Walk several regions, well past the 50 Hz charging cadence many times over.
    y_run_to(Y_R1 + 2000);   // share still 0.50 here — droop ratio well inside the band
    check(digitalRead(FC_CHARGE_ENABLE) == LOW,
          "Y charging: FC_CHARGE_ENABLE stays LOW through R1 — the FC-charge path is never opened");
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "Y charging: BT_BUS_ENABLE stays HIGH in the mid-share regions — the battery is not "
          "taken off the bus");

    // The same tick must show the control stack IS being driven: the omission is of the CHARGING
    // manager only, not of the motor/droop halves.
    check(fabsf(current) > 0.01f,
          "Y charging: the combined profile's branch does drive the motor (commanded current is "
          "non-zero mid-ramp)");
    check(!vesc.current_calls.empty() && fabsf(vesc.last_current) > 0.01f,
          "Y charging: the commanded current actually reaches the VESC");
    check(SPI.transfer_log.size() > 0,
          "Y charging: the droop half of the stack runs too (powerBalance writes the MDACs)");

    y_run_to(Y_R4 + 2000);
    check(digitalRead(FC_CHARGE_ENABLE) == LOW,
          "Y charging: FC_CHARGE_ENABLE is still LOW deep into R4, with charge_goal set high");

    y_run_to(Y_R8 + 1500);
    check(digitalRead(FC_CHARGE_ENABLE) == LOW,
          "Y charging: the charge path stays under operator control for the whole run");
    check(combinedProfileActive && combinedRegionIdx == 8,
          "Y charging: the profile itself ran normally the whole time");

    // ── Contrast: the drive cycle's branch DOES include the charging manager. If someone later
    // "symmetrizes" the two branches, this half of the test fails and says which way it moved.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE]   = HIGH;
    g_pin_value[BT_BUS_ENABLE]    = HIGH;
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    charge_goal = 0.5f;
    Serial.rx_queue.push('D');
    doState98();
    check(driveCycleActive == true, "Y charging (contrast): the drive cycle started");
    for (int i = 0; i < 50; i++) {          // well past CHARGING_CTRL_PERIOD_US
        g_mock_millis += 1;
        g_mock_micros += POWER_BAL_PERIOD_US;
        doState98();
    }
    check(digitalRead(FC_CHARGE_ENABLE) == HIGH && digitalRead(BT_BUS_ENABLE) == LOW,
          "Y charging (contrast): the DRIVE CYCLE does run chargingControl() — it opens FC_CHARGE "
          "and drops BT_BUS, which is exactly what 'Y' must never do");
}

// ─── 10. Start-over-start takeover: the new run is logged too ──────────────
static void test_y_takeover_logging() {
    test_group("Y combined profile — a takeover closes the old log and opens one for the new run");

    // ── (a) Y then 'D' on an IDLE card: old file finished, new run STILL LOGGED. ──
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    y_run_to(500, /*drain=*/true);
    check(logActive && std::string(logFileName) == "YP0001.BLG",
          "Y takeover: the combined run is logging to YP0001.BLG before the takeover");
    uint32_t yRecs = logRecordsWritten;
    check(yRecs > 0, "Y takeover: the combined run drained records before the takeover");

    Serial.rx_queue.push('D');
    doState98();
    check(driveCycleActive == true && combinedProfileActive == false,
          "Y takeover: 'D' takes over from the combined profile");
    check(logActive == true && std::string(logFileName) == "DC0002.BLG",
          "Y takeover: on an idle card the takeover run IS logged, into a new DC file");
    check(logFile.isOpen() == true,
          "Y takeover: the new file's handle is open — the old one was finished, not leaked");

    {
        const std::string* f = sd_file("YP0001.BLG");
        check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * yRecs + LOG_REC_SIZE,
              "Y takeover: the superseded YP file is complete (records + trailer)");
        if (f) {
            size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * yRecs;
            check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu &&
                  sd_le<uint32_t>(*f, tr + 4) == yRecs,
                  "Y takeover: the superseded file carries a valid trailer with its record count");
            check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_STOP,
                  "Y takeover: the superseded run's close reason is LOG_CLOSE_STOP");
        }
    }

    // The new file must actually accumulate.
    for (int i = 0; i < 200; i++) {
        g_mock_millis += 1;
        g_mock_micros += POWER_BAL_PERIOD_US;
        doState98();
        logDrainTick();
    }
    {
        const std::string* f = sd_file("DC0002.BLG");
        check(f != nullptr && f->size() > LOG_HDR_SIZE + LOG_REC_SIZE * 100u,
              "Y takeover: the takeover run's file accumulates records normally");
        if (f) check((uint8_t)(*f)[6] == LOG_TYPE_DC,
                     "Y takeover: the takeover file's header type is LOG_TYPE_DC");
    }
    // A3 fix, checked cheaply here: the 'D' start now clears a pending trapezoid.
    check(trapProfileActive == false && trapCmdA == 0.0f,
          "Y takeover: the 'D' start leaves no trapezoid state behind (A3)");

    // ── (b) Y then 'R' on a BUSY card: old file finished, new run refused. ──
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    y_run_to(500, /*drain=*/true);
    yRecs = logRecordsWritten;
    setManualMotorCurrent(3.0f);            // 'R' precondition
    g_sd_state.busy_ticks = 1000000;        // opening a file here would be an unbounded stall
    Serial.tx_clear();
    Serial.rx_queue.push('R');
    doState98();

    check(powerShareProfileActive == true && combinedProfileActive == false,
          "Y takeover (busy): 'R' takes over and the profile itself still runs");
    check(Serial.tx_contains("[SD] previous log still open (card busy)"),
          "Y takeover (busy): the refusal names the busy card as the reason this run is not logged");
    check(logActive == false && logFile.isOpen() == false,
          "Y takeover (busy): no new file is opened and no handle is left behind");
    check(sd_only_log_name() == "YP0001.BLG",
          "Y takeover (busy): only the superseded YP file exists — no second .BLG was created");
    {
        const std::string* f = sd_file("YP0001.BLG");
        check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * yRecs + LOG_REC_SIZE,
              "Y takeover (busy): the superseded file is still finished with its trailer");
    }

    // ── (c) The other direction: Y taking over a running 'R' is logged too. ──
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    setManualMotorCurrent(3.0f);
    Serial.rx_queue.push('R');
    doState98();
    check(std::string(logFileName) == "PS0001.BLG",
          "Y takeover (reverse): the share run is logging to PS0001.BLG first");
    for (int i = 0; i < 50; i++) {
        g_mock_millis += 1;
        g_mock_micros += POWER_BAL_PERIOD_US;
        doState98();
        logDrainTick();
    }
    uint32_t psRecs = logRecordsWritten;
    y_start("");
    check(combinedProfileActive == true && powerShareProfileActive == false,
          "Y takeover (reverse): 'Y' takes over from the running share profile");
    check(logActive == true && std::string(logFileName) == "YP0002.BLG",
          "Y takeover (reverse): the combined takeover run IS logged, into a new YP file");
    {
        const std::string* f = sd_file("PS0001.BLG");
        check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * psRecs + LOG_REC_SIZE,
              "Y takeover (reverse): the superseded PS file is complete");
        if (f) check((uint8_t)(*f)[LOG_HDR_SIZE + LOG_REC_SIZE * psRecs + 12] == LOG_CLOSE_STOP,
                     "Y takeover (reverse): the superseded PS run closes with LOG_CLOSE_STOP");
    }
}

// ─── 11. Boundary parameters + post-run status readback ─────────────────────
static void test_y_boundary_params() {
    test_group("Y combined profile — Vmax boundary is inclusive, and 'S' reads back the committed pair");

    // ── Exactly at the ceiling is ACCEPTED: the check is `>`, not `>=`, and it must stay that
    // way — 'V' accepts MANUAL_MOTOR_V_MAX too, and the two paths close the identical loop.
    reset_test_state();
    y_start(" 5");
    check(combinedProfileActive == true && near_f(yProfileVmax, MANUAL_MOTOR_V_MAX),
          "Y bounds: Vmax exactly at MANUAL_MOTOR_V_MAX (5.0) is accepted");
    check(!Serial.tx_contains("Vmax must be <= "),
          "Y bounds: the ceiling refusal does not fire at the boundary value itself");

    // ── One step above is refused.
    reset_test_state();
    y_start(" 5.01");
    check(combinedProfileActive == false,
          "Y bounds: a Vmax just above the ceiling (5.01) is refused");
    check(Serial.tx_contains("Vmax must be <= "),
          "Y bounds: the refusal cites the MANUAL_MOTOR_V_MAX ceiling");
    check(g_sd_state.files.empty() && logActive == false,
          "Y bounds: the refused start opens no log file");

    // ── The committed pair must be readable AFTER the run: the 'Y' start banner scrolls away
    // behind the 500 ms status lines, so 'S' is the only way to confirm what was actually
    // committed rather than typed (B1).
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start(" 2 0.3");
    check(combinedProfileActive && near_f(yProfileVmax, 2.0f) && near_f(yProfileBoundLo, 0.3f),
          "Y status readback: the run committed Vmax 2.0 with band [0.30, 0.70]");
    y_run_to(500);
    Serial.rx_queue.push('Y');          // stop it — the readback must survive the run ending
    doState98();
    check(combinedProfileActive == false, "Y status readback: the run has ended before the readback");

    Serial.tx_clear();
    Serial.rx_queue.push('S');
    doState98();
    check(Serial.tx_contains("combinedProfile:"),
          "Y status readback: 'S' prints a combinedProfile line");
    check(Serial.tx_contains("Vmax=2.00"),
          "Y status readback: the line reports the COMMITTED Vmax after the run ended");
    check(Serial.tx_contains("band=[0.30, 0.70]"),
          "Y status readback: the line reports the committed share band, both edges");
    check(Serial.tx_contains("driveCycle:"),
          "Y status readback: 'S' also carries the driveCycle line");
}

// ═══════════════════════════════════════════════════════════════════════════════
// 'W' combined commanded-current + power-share profile (the current-mode twin of 'Y')
// ═══════════════════════════════════════════════════════════════════════════════
// 'W' walks the SAME COMBINED_PROFILE[] table as 'Y' through the shared advanceComboRegion()
// helper, but scales the normalised motor column into AMPS and commands it directly (no velocity
// PI), so it is usable on an encoder-less bench. The Y_R* cumulative-time table above therefore
// applies verbatim, and the two profiles' shapes are supposed to be identical by construction —
// test_w_y_equivalence() is the assertion that says so.
//
// Motor-axis plateaus at the default Imax = 5.0 A (normalised 0 / 0.2 / 0.5 / 0.6 / 1.0):
//   0 A, 1.0 A, 2.5 A, 3.0 A, 5.0 A.

// 'W' start through the real keypress + parameter-line path. Deliberately shares g_y_t0 and
// y_run_to() with the 'Y' helpers: both profiles walk one table, so one timebase helper serves
// both — and the equivalence test can then drive them with literally identical stepping code.
static void w_start(const char* params) {
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('W');
    doState98();
    feed_serial_line(params);
    g_y_t0 = g_mock_millis;
}

// ─── 1. Parameter line: defaults, one value, two values, warn band, ceiling ─
static void test_w_params_and_defaults() {
    test_group("W current profile — parameter line: defaults, one/two values, warn band, ceiling");

    // Bare Enter must ACCEPT (run the defaults), not cancel — the same all-optional grammar 'Y'
    // has, and the same regression risk (a silent no-op looks like a dead key).
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('W');
    doState98();
    check(pendingInput == PEND_W_PARAMS,
          "W params: 'W' arms the single-line parameter prompt");
    feed_serial_line("");
    check(wProfileActive == true,
          "W params: a bare Enter starts the profile rather than cancelling the prompt");
    check(near_f(wProfileImax, W_IMAX_DEFAULT) && near_f(wProfileBoundLo, Y_BOUND_DEFAULT),
          "W params: a bare Enter commits the documented defaults (Imax 5.0 A, b 0)");
    check(wRegionIdx == 0, "W params: the run begins at region 0");

    reset_test_state();
    w_start(" 6");
    check(wProfileActive == true && near_f(wProfileImax, 6.0f) && near_f(wProfileBoundLo, 0.0f),
          "W params: one value \"W 6\" sets Imax and leaves the share bound at its default");

    reset_test_state();
    w_start(" 6 0.0");
    check(wProfileActive == true && near_f(wProfileImax, 6.0f) && near_f(wProfileBoundLo, 0.0f),
          "W params: an explicit zero bound \"W 6 0.0\" is accepted and means no clipping");

    reset_test_state();
    w_start(" 6 0.3");
    check(wProfileActive == true && near_f(wProfileImax, 6.0f) && near_f(wProfileBoundLo, 0.3f),
          "W params: two values commit both Imax and the share bound");

    // The share bound's warn band is shared with 'Y' (validateShareBound), so it must behave the
    // same way here: accepted, with a warning.
    reset_test_state();
    w_start(" 5 0.4");
    check(wProfileActive == true && near_f(wProfileBoundLo, 0.4f) && Serial.tx_contains("WARN: b > "),
          "W params: a bound above Y_BOUND_WARN is accepted with the compressed-plateau warning");

    reset_test_state();
    w_start(" 5 0.35");
    check(wProfileActive == true && !Serial.tx_contains("WARN: b > "),
          "W params: a bound exactly at Y_BOUND_WARN starts without a warning (strict >)");

    // The ceiling is the TRAPEZOID's (ESC rating), not the MOTOR_I_CMD_MAX (10 A) velocity-path
    // budget — this profile commands phase current through the same chokepoint 'T' uses.
    reset_test_state();
    w_start(" 25");
    check(wProfileActive == true && near_f(wProfileImax, TRAP_I_ABS_MAX),
          "W params: Imax exactly at TRAP_I_ABS_MAX (25 A) is accepted — the check is strict >");
    check(!Serial.tx_contains("Imax must be <= "),
          "W params: the ceiling refusal does not fire at the boundary value itself");

    reset_test_state();
    w_start(" 25.01");
    check(wProfileActive == false && Serial.tx_contains("Imax must be <= "),
          "W params: an Imax just above TRAP_I_ABS_MAX is refused");

    // A peak above MOTOR_I_CMD_MAX (the 10 A source budget) must still be accepted — same policy
    // as 'T', and the reason the ceiling is TRAP_I_ABS_MAX in the first place. 16 A is chosen so it
    // is clearly above MOTOR_I_CMD_MAX (10 A) rather than merely equal to it.
    reset_test_state();
    w_start(" 16");
    check(wProfileActive == true && near_f(wProfileImax, 16.0f),
          "W params: a peak above MOTOR_I_CMD_MAX is accepted un-clamped, as 'T' accepts it");
}

// ─── 2. Refusals — and the two deliberate NON-refusals ─────────────────────
static void test_w_refusals() {
    test_group("W current profile — refusals, plus the encoder-less/unpowered cases it must ALLOW");

    auto check_idle = [&](const char* what) {
        char buf[160];
        snprintf(buf, sizeof(buf), "W refusal (%s): no profile starts and no log file is opened", what);
        check(wProfileActive == false && logActive == false && g_sd_state.files.empty(), buf);
    };

    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    bringupActive = true;
    Serial.rx_queue.push('W');
    doState98();
    check(pendingInput == PEND_NONE && Serial.tx_contains("bring-up in progress"),
          "W refusal: 'W' during a staged bring-up is refused at the keypress");
    check_idle("bring-up active");
    bringupActive = false;

    reset_test_state();
    w_start(" 0");
    check(Serial.tx_contains("Imax must be > 0"), "W refusal: an Imax of zero is rejected");
    check_idle("Imax = 0");

    reset_test_state();
    w_start(" -5");
    check(Serial.tx_contains("Imax must be > 0"),
          "W refusal: a negative Imax is rejected (unlike 'T', the table has no mirrored form)");
    check_idle("Imax negative");

    reset_test_state();
    w_start(" 30");
    check(Serial.tx_contains("Imax must be <= "),
          "W refusal: an Imax above the ESC rating is rejected");
    check_idle("Imax above TRAP_I_ABS_MAX");

    reset_test_state();
    w_start(" 5 0.5");
    check(Serial.tx_contains("share bound b must be < 0.5"),
          "W refusal: b = 0.5 is rejected — the band [b, 1-b] collapses to a point");
    check_idle("b = 0.5");

    reset_test_state();
    w_start(" 5 -0.1");
    check(Serial.tx_contains("share bound b must be >= 0"),
          "W refusal: a negative share bound is rejected");
    check_idle("b negative");

    reset_test_state();
    w_start(" 5 0.3 2");
    check(Serial.tx_contains("at most two values"),
          "W refusal: a third value is rejected rather than silently ignored");
    check_idle("third value");

    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('W');
    doState98();
    check(pendingInput == PEND_W_PARAMS, "W refusal: the parameter prompt is armed before the cancel");
    Serial.rx_queue.push('Z');
    doState98();
    check(pendingInput == PEND_NONE && Serial.tx_contains("(input cancelled)"),
          "W refusal: a non-numeric key cancels the parameter entry");
    Serial.rx_queue.push('\n');
    doState98();
    check_idle("non-numeric cancel");

    // ── The two deliberate NON-refusals. These are the entire reason 'W' exists alongside 'Y':
    // it bypasses the velocity PI, so neither an uncalibrated encoder chain nor an unpowered
    // MOT_PWR rail is a reason to refuse.
    reset_test_state();
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = LOW;
    Serial.rx_queue.push('W');
    doState98();
    check(pendingInput == PEND_W_PARAMS && Serial.tx_contains("WARN: MOT_PWR_ENABLE is LOW"),
          "W allows: MOT_PWR_ENABLE LOW only WARNS — the VESC may have its own bench supply");
    feed_serial_line(" 5");
    check(wProfileActive == true,
          "W allows: the profile starts with MOT_PWR_ENABLE LOW (no gate, same policy as 'T')");

    reset_test_state();
    velocityChainCalibratedFlag = false;   // 'Y' and 'D' would both refuse here
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    Serial.rx_queue.push('W');
    doState98();
    check(pendingInput == PEND_W_PARAMS && !Serial.tx_contains("needs a calibrated velocity chain"),
          "W allows: an uncalibrated velocity chain is NOT a refusal — the velocity PI is bypassed");
    feed_serial_line(" 5");
    check(wProfileActive == true,
          "W allows: the profile runs on an encoder-less bench, which is the point of 'W'");
}

// ─── 3. Full 40 s region walk at the defaults ──────────────────────────────
static void test_w_region_walk() {
    test_group("W current profile — commanded current and share track the shared region table");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    check(wProfileActive && near_f(wProfileImax, 5.0f) && near_f(wProfileBoundLo, 0.0f),
          "W walk: the run starts at the defaults (Imax 5.0 A, no share clip)");

    y_run_to(1000);
    check(wRegionIdx == 0 && near_f(wCmdA, 0.0f) && near_f(power_share_setpoint, 0.5f),
          "W walk: R0 holds 0 A and share 0.50 while the bench settles");

    // R1: current ramps 0 -> 3.0 A (normalised 0 -> 0.6 x 5 A); midpoint is half way up.
    y_run_to(Y_R1 + 2000);
    check(wRegionIdx == 1 && near_f(wCmdA, 1.5f, 1e-3f),
          "W walk: R1 midpoint commands 1.5 A — half of the 0 -> 3.0 A ramp");
    check(near_f(power_share_setpoint, 0.5f),
          "W walk: R1 leaves the share axis flat — the current ramp is a SOLO excitation");
    check(!vesc.current_calls.empty() && near_f(vesc.last_current, 1.5f, 0.05f),
          "W walk: the commanded current actually reaches the VESC");

    y_run_to(Y_R2 + 1000);
    check(wRegionIdx == 2 && near_f(wCmdA, 3.0f, 1e-3f) && near_f(power_share_setpoint, 0.5f),
          "W walk: R2 buffers at the 3.0 A plateau with the share still at 0.50");

    // R3: share steps to 0.65 on the region's first tick while the current holds.
    y_run_to(Y_R3 + 1);
    check(wRegionIdx == 3 && near_f(power_share_setpoint, 0.65f, 1e-3f) &&
          near_f(wCmdA, 3.0f, 1e-2f),
          "W walk: R3 steps the share to 0.65 with the current axis untouched (SOLO share step)");

    // R4: BOTH axes ramp (current up, share down) — the interaction test.
    y_run_to(Y_R4 + 2000);
    check(wRegionIdx == 4 && near_f(wCmdA, 4.0f, 1e-3f),
          "W walk: R4 midpoint commands 4.0 A — mid-ramp between the 3.0 A and 5.0 A plateaus");
    check(near_f(power_share_setpoint, 0.5f, 1e-3f),
          "W walk: R4 midpoint has the share mid-ramp between 0.65 and 0.35 — both axes move");

    // R5 (fw v6): current ramps DOWN from the 5.0 A peak to 1.5 A (0.3 x Imax) ahead of the
    // excursion; midpoint is half way down. Share stays flat at 0.35.
    y_run_to(Y_R5 + 1000);
    check(near_f(wCmdA, 3.25f, 1e-3f) && near_f(power_share_setpoint, 0.35f, 1e-3f),
          "W walk: R5 midpoint commands 3.25 A — half way down the 5.0 -> 1.5 A ramp — with the "
          "share at 0.35");

    // R6 (fw v6): the hi-bound share excursion now runs at the LOW-load 1.5 A plateau (0.3 x
    // Imax), not the full 5.0 A peak — the point of the rework (TP0074/85-87: the excursion used
    // to coincide with full load and collapsed the bus).
    y_run_to(Y_R6 + 750);
    check(wRegionIdx == 6 && near_f(power_share_setpoint, 1.0f) && near_f(wCmdA, 1.5f, 1e-3f),
          "W walk: R6 drives the share to 1.00 (all-FC) while holding the LOW-load 1.5 A plateau "
          "(fw v6 -- this used to be the full 5.0 A peak)");

    // R8: BOTH axes step in the same tick (current 5.0 -> 2.5 A, share 0.35 -> 0.65).
    y_run_to(Y_R8 - 1);
    check(near_f(wCmdA, 5.0f, 1e-2f) && near_f(power_share_setpoint, 0.35f, 1e-3f),
          "W walk: R7 ends at 5.0 A / share 0.35 on the last tick before R8");
    y_run_to(Y_R8 + 1);
    check(wRegionIdx == 8 && near_f(wCmdA, 2.5f, 1e-2f) &&
          near_f(power_share_setpoint, 0.65f, 1e-3f),
          "W walk: R8 steps BOTH axes in the same tick (current down to 2.5 A, share up to 0.65)");

    y_run_to(Y_R10 + 1500);
    check(wRegionIdx == 10 && near_f(power_share_setpoint, 0.325f, 1e-3f) &&
          near_f(wCmdA, 2.5f, 1e-3f),
          "W walk: R10 midpoint has the share half way down its ramp with the current flat");

    y_run_to(Y_R11 + 750);
    check(wRegionIdx == 11 && near_f(power_share_setpoint, 0.0f),
          "W walk: R11 drives the share to 0.00 (all-BT) to exercise the other clamp");

    y_run_to(Y_R13 + 1000);
    check(wRegionIdx == 13 && near_f(wCmdA, 1.0f, 1e-3f) &&
          near_f(power_share_setpoint, 0.5f),
          "W walk: R13 steps the current down to 1.0 A with the share recovered to 0.50");

    y_run_to(Y_R14 + 1500);
    check(wRegionIdx == 14 && near_f(wCmdA, 0.5f, 1e-3f),
          "W walk: R14 coasts the current down, half way at 0.5 A");

    // Natural completion.
    y_run_to(Y_R15 + 1000);
    check(wRegionIdx == 15 && near_f(wCmdA, 0.0f),
          "W walk: R15 holds at zero current before completion");
    vesc.reset();
    y_run_to(Y_END + 1);
    check(wProfileActive == false,
          "W walk: the profile deactivates on natural completion after the last region");
    check(near_f(wCmdA, 0.0f),
          "W walk: natural completion zeroes the commanded-current mirror");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "W walk: natural completion flushes vesc.setCurrent(0) — the motor is not left driving");
    check(near_f(power_share_setpoint, 0.5f),
          "W walk: natural completion returns the share setpoint to balanced (0.50)");
    check(manualMotorMode == MOTOR_TEST_OFF,
          "W walk: natural completion clears manualMotorMode (haltMotorOutput symmetry)");

    sd_drain_until_closed();
    const std::string* f = sd_file("WP0001.BLG");
    check(f != nullptr && f->size() > LOG_HDR_SIZE + LOG_REC_SIZE,
          "W walk: the run's log file exists and holds records");
    if (f) {
        size_t tr = f->size() - LOG_REC_SIZE;
        check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu &&
              (uint8_t)(*f)[tr + 12] == LOG_CLOSE_COMPLETE,
              "W walk: the trailer records LOG_CLOSE_COMPLETE for a naturally-finished run");
    }
}

// ─── 4. Imax scaling and the shared share-clip ─────────────────────────────
static void test_w_scaling_and_clip() {
    test_group("W current profile — the current axis scales with Imax; the share clip is shared");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start(" 6");
    check(near_f(wProfileImax, 6.0f), "W scaling: the run committed Imax = 6.0 A");

    // R5's (fw v6) normalised 0.65 midpoint (half way down the 1.0 -> 0.3 ramp) scales too.
    y_run_to(Y_R5 + 1000);
    check(wRegionIdx == 5 && near_f(wCmdA, 3.9f, 1e-3f),
          "W scaling: R5's normalised 0.65 midpoint scales to 3.9 A at Imax = 6");
    check(near_f(power_share_setpoint, 0.35f, 1e-3f),
          "W scaling: the share axis is unaffected by Imax — it is absolute, not normalised");

    y_run_to(Y_R8 + 1500);
    check(wRegionIdx == 8 && near_f(wCmdA, 3.0f, 1e-3f),
          "W scaling: R8's normalised 0.5 step scales to 3.0 A at Imax = 6");
    check(near_f(power_share_setpoint, 0.65f, 1e-3f),
          "W scaling: R8's share plateau is the same 0.65 the defaults produce");

    y_run_to(Y_R13 + 1000);
    check(near_f(wCmdA, 1.2f, 1e-3f),
          "W scaling: mid-table plateaus scale too — R13's 0.2 becomes 1.2 A");

    // ── The share clip comes from the SHARED helper, so it must behave exactly as it does for
    // 'Y': post-interpolation, with the excursions flattening at the band edge.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start(" 5 0.3");   // band [0.30, 0.70]
    y_run_to(Y_R3 + 1500);
    check(near_f(power_share_setpoint, 0.65f, 1e-3f),
          "W clip: R3's 0.65 plateau is inside [0.30, 0.70] and passes through unclipped");
    y_run_to(Y_R6 + 750);
    check(near_f(power_share_setpoint, 0.7f),
          "W clip: R6's 1.00 excursion flattens at the upper bound 0.70, exactly as under 'Y'");
    y_run_to(Y_R10 + 1000);
    check(near_f(power_share_setpoint, 0.65f - 0.65f * (1000.0f / 3000.0f), 1e-3f),
          "W clip: R10's ramp keeps its full slope before the bound crossing (post-interp clip)");
    y_run_to(Y_R10 + 2500);
    check(near_f(power_share_setpoint, 0.3f),
          "W clip: R10 pins at 0.30 after the crossing — the same kink the 'Y' profile produces");
    y_run_to(Y_R11 + 750);
    check(near_f(power_share_setpoint, 0.3f),
          "W clip: R11's 0.00 excursion flattens at the lower bound 0.30");
    check(near_f(wCmdA, 2.5f, 1e-3f),
          "W clip: the share band never touches the current axis");
}

// ─── E2: R6's low-load hi-bound excursion actually LATCHES the setpoint cutoff ─────────────────
// The fw v6 table rework (COMBINED_PROFILE R5-R7) moved R6's hi-bound share excursion onto the
// 0.3xImax plateau specifically so the handoff guard's current check passes and the cut FIRES,
// rather than deferring — table comment: "the fw v6 handoff guard actually fires here instead of
// deferring". The region-walk tests above only check that advanceComboRegion() COMMANDS the
// right power_share_setpoint; they run with FC_BUS/BT_BUS left at their reset default and
// I_fc=I_batt=0, so powerBalance() never leaves its min-load gate and the cutoff logic never
// actually runs. This test wires up a live share loop (switches HIGH, real currents) so the
// claim is exercised end-to-end, not just the setpoint arithmetic.
static void test_w_r6_share_latch_at_low_load() {
    test_group("W walk: R6's hi-bound excursion at low load actually latches BT via the setpoint cutoff, releases on R7 (E2)");

    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    digitalWrite(FC_REG_ENABLE, HIGH);
    digitalWrite(BT_REG_ENABLE, HIGH);
    V_bus = 16.0f;
    // Imax=1.5A and bound b=0.1 (< 0.15): R6 commands 1.00 clipped to [0.1, 0.9] = 0.90, out of
    // band (> DROOP_R_MAX=0.85) -- BT is the doomed channel. Its measured current is mocked at
    // the R6 plateau's own scale (0.3 x 1.5 = 0.45A), comfortably under SHARE_CUT_MAX_HANDOFF_A
    // (0.5A), so the guard should NOT defer the cut.
    w_start(" 1.5 0.1");
    check(wProfileActive && near_f(wProfileImax, 1.5f) && near_f(wProfileBoundLo, 0.1f),
          "W R6 latch: (setup) the run committed Imax=1.5A, share bound b=0.1");
    I_fc = 1.0f; I_batt = 0.45f;   // set AFTER w_start(): the profile start does not touch these

    y_run_to(Y_R6 + 750);
    check(wRegionIdx == 6 && near_f(power_share_setpoint, 0.9f),
          "W R6 latch: (setup) R6 commits the share to 0.90 (1.00 clipped to [0.1,0.9]) -- out of band");
    check(shareSpCutBT && shareIsoBT && digitalRead(BT_BUS_ENABLE) == LOW,
          "W R6 latch: the setpoint cutoff actually LATCHES BT here -- the doomed channel's "
          "0.45A measured current is under the handoff guard, so this is the fired-cut case, not "
          "the deferred one (the whole point of moving the excursion onto the low-load plateau)");
    check(digitalRead(FC_BUS_ENABLE) == HIGH,
          "W R6 latch: FC (the surviving source) stays on the bus");
    check(!shareCutDeferredBT,
          "W R6 latch: no deferral is outstanding -- the guard passed on load, it did not block");

    // R7 re-entry: the share steps back to the in-band 0.35 -- the latch must release.
    y_run_to(Y_R7 + 100);
    check(wRegionIdx == 7 && near_f(power_share_setpoint, 0.35f, 1e-3f),
          "W R6 latch: (setup) R7 steps the share back in-band to 0.35");
    check(!shareSpCutBT && !shareIsoBT,
          "W R6 latch: R7's in-band re-entry releases the BT setpoint latch");
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "W R6 latch: BT_BUS_ENABLE re-closes on R7 re-entry");
}

// ─── 5. Y/W equivalence — the shared-table guarantee ───────────────────────
// This is the test that fails the moment the two advance paths diverge. Both profiles are
// supposed to be the SAME waveform with a different motor unit; anything else silently makes two
// bench runs incomparable, which is the entire reason they share one table and one helper.
static void test_w_y_equivalence() {
    test_group("W/Y equivalence — one region table, two motor units, identical shape");

    static const uint32_t PTS[] = {
        Y_R0 + 1000,  Y_R1 + 1000,  Y_R1 + 2000,  Y_R1 + 3000, Y_R2 + 1000,
        Y_R3 + 1500,  Y_R4 + 1000,  Y_R4 + 2000,  Y_R4 + 3000, Y_R5 + 1000,
        Y_R6 + 750,   Y_R7 + 1750,  Y_R8 + 1500,  Y_R9 + 1000, Y_R10 + 500,
        Y_R10 + 1500, Y_R10 + 2500, Y_R11 + 750,  Y_R12 + 750, Y_R13 + 1000,
        Y_R14 + 1500, Y_R15 + 1000,
    };
    const int NPTS = (int)(sizeof(PTS) / sizeof(PTS[0]));

    const float VMAX = 2.0f;    // deliberately NOT 1.0, so a missing scale factor cannot hide
    const float IMAX = 8.0f;
    const float BOUND = 0.3f;   // a clipped band, so the shared clip is inside the comparison
    float yShare[32], yAxis[32], wShare[32], wAxis[32];
    uint8_t yRegion[32], wRegion[32];

    // ── Y run ───────────────────────────────────────────────────────────────
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start(" 2 0.3");
    check(combinedProfileActive && near_f(yProfileVmax, VMAX) && near_f(yProfileBoundLo, BOUND),
          "W/Y equivalence: the 'Y' reference run started with Vmax 2.0 and band [0.30, 0.70]");
    for (int i = 0; i < NPTS; i++) {
        y_run_to(PTS[i]);
        yShare[i]  = power_share_setpoint;
        yAxis[i]   = v_setpoint;
        yRegion[i] = combinedRegionIdx;
    }

    // ── W run, identical stepping code ─────────────────────────────────────
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start(" 8 0.3");
    check(wProfileActive && near_f(wProfileImax, IMAX) && near_f(wProfileBoundLo, BOUND),
          "W/Y equivalence: the 'W' run started with Imax 8.0 A and the same band");
    for (int i = 0; i < NPTS; i++) {
        y_run_to(PTS[i]);
        wShare[i]  = power_share_setpoint;
        wAxis[i]   = wCmdA;
        wRegion[i] = wRegionIdx;
    }

    // ── Compare ────────────────────────────────────────────────────────────
    bool regionsMatch = true, shareMatch = true, axisMatch = true;
    int  firstBadRegion = -1, firstBadShare = -1, firstBadAxis = -1;
    const float scale = IMAX / VMAX;   // 4.0 — W amps per Y m/s
    for (int i = 0; i < NPTS; i++) {
        if (yRegion[i] != wRegion[i] && regionsMatch) { regionsMatch = false; firstBadRegion = i; }
        if (yShare[i] != wShare[i]   && shareMatch)   { shareMatch   = false; firstBadShare  = i; }
        if (!near_f(wAxis[i], yAxis[i] * scale, 1e-3f) && axisMatch) {
            axisMatch = false; firstBadAxis = i;
        }
    }
    if (firstBadRegion >= 0)
        printf("    (region mismatch at point %d: Y=%u W=%u)\n",
               firstBadRegion, yRegion[firstBadRegion], wRegion[firstBadRegion]);
    if (firstBadShare >= 0)
        printf("    (share mismatch at point %d: Y=%.6f W=%.6f)\n",
               firstBadShare, (double)yShare[firstBadShare], (double)wShare[firstBadShare]);
    if (firstBadAxis >= 0)
        printf("    (axis mismatch at point %d: Y=%.6f x%.2f = %.6f, W=%.6f)\n",
               firstBadAxis, (double)yAxis[firstBadAxis], (double)scale,
               (double)(yAxis[firstBadAxis] * scale), (double)wAxis[firstBadAxis]);

    check(regionsMatch,
          "W/Y equivalence: both profiles are in the same region at all 22 sampled points");
    check(shareMatch,
          "W/Y equivalence: the share sequence is BIT-IDENTICAL between 'Y' and 'W' (shared "
          "interpolation and shared post-interpolation clip)");
    check(axisMatch,
          "W/Y equivalence: the motor axis is the same normalised shape — W amps equal Y m/s "
          "times Imax/Vmax at every sampled point");

    // Guard against a vacuous pass: the sampled points must actually contain movement on both
    // axes, otherwise "identical" would just mean "both constant".
    bool axisVaries = false, shareVaries = false;
    for (int i = 1; i < NPTS; i++) {
        if (!near_f(yAxis[i], yAxis[0]))  axisVaries  = true;
        if (!near_f(yShare[i], yShare[0])) shareVaries = true;
    }
    check(axisVaries && shareVaries,
          "W/Y equivalence: the sampled points genuinely exercise both axes (not a flat comparison)");
    // fw v6: R6 (PTS[10]) is no longer the full-scale peak -- the R5-R7 rework deliberately moved
    // the hi-bound share excursion onto the 0.3 x Imax plateau, so this pins the NEW low-load
    // value instead. The scale factor is still load-bearing in the comparison above: 2.4 A is
    // neither 0 nor Imax, so a missing/wrong Imax/Vmax scale would not coincidentally cancel out.
    check(near_f(wAxis[10], 2.4f, 1e-3f),
          "W/Y equivalence: the R6 sample is at the 0.3 x Imax low-load plateau (2.4 A at "
          "Imax=8.0, fw v6), confirming the scale factor is exercised at a non-trivial value");
}

// ─── 6. Stop paths and mutual exclusion ────────────────────────────────────
static void test_w_stop_x_q_exclusion() {
    test_group("W current profile — stop-toggle, 'X', 'Q' and mutual exclusion with D/R/T/Y");

    // ── (a) 'W' again mid-run.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    y_run_to(Y_R4 + 1000, /*drain=*/true);
    check(wProfileActive && wRegionIdx == 4, "W stop: the run is mid-R4 before the stop key");
    uint32_t recs = logRecordsWritten;
    g_pin_value[REGEN_ENABLE] = HIGH;
    vesc.reset();
    Serial.rx_queue.push('W');
    doState98();
    check(wProfileActive == false && near_f(wCmdA, 0.0f),
          "W stop: the 'W' stop-toggle clears the profile and its commanded-current mirror");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "W stop: the stop flushes vesc.setCurrent(0) immediately");
    check(digitalRead(REGEN_ENABLE) == LOW,
          "W stop: the stop parks the path switches (the share axis manipulates the bus config)");
    check(near_f(power_share_setpoint, 0.5f),
          "W stop: the stop returns the share setpoint to balanced");
    sd_drain_until_closed();
    {
        const std::string* f = sd_file("WP0001.BLG");
        check(f != nullptr && f->size() == LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE,
              "W stop: the stopped run's file holds every drained record plus the trailer");
        if (f) check((uint8_t)(*f)[LOG_HDR_SIZE + LOG_REC_SIZE * recs + 12] == LOG_CLOSE_STOP,
                     "W stop: the trailer records LOG_CLOSE_STOP");
    }

    // ── (b) 'X' universal stop.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    y_run_to(Y_R6 + 500, /*drain=*/true);
    recs = logRecordsWritten;
    g_pin_value[REGEN_ENABLE] = HIGH;
    vesc.reset();
    Serial.rx_queue.push('X');
    doState98();
    check(wProfileActive == false && near_f(wCmdA, 0.0f) && manualMotorMode == MOTOR_TEST_OFF,
          "W 'X': the universal stop cancels the current profile and the manual modes");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "W 'X': the universal stop zeroes the motor");
    check(digitalRead(REGEN_ENABLE) == LOW,
          "W 'X': hadW makes the universal stop park the switches, as it does for 'D'/'R'/'Y'");
    check(near_f(power_share_setpoint, 0.5f),
          "W 'X': hadW resets the share setpoint, matching the 'R'/'Y' semantics");
    sd_drain_until_closed();
    {
        const std::string* f = sd_file("WP0001.BLG");
        check(f != nullptr &&
              (uint8_t)(*f)[LOG_HDR_SIZE + LOG_REC_SIZE * recs + 12] == LOG_CLOSE_X,
              "W 'X': the trailer records LOG_CLOSE_X");
    }

    // ── (c) 'Q' exit.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    y_run_to(Y_R2 + 500, /*drain=*/true);
    recs = logRecordsWritten;
    vesc.reset();
    Serial.rx_queue.push('Q');
    doState98();
    check(wProfileActive == false && near_f(wCmdA, 0.0f) && mainState == 1,
          "W 'Q': the exit clears the current profile and returns to Idle");
    check(!vesc.current_calls.empty() && vesc.last_current == 0.0f,
          "W 'Q': the exit flushes vesc.setCurrent(0) before cutting motor power");
    sd_drain_until_closed();
    {
        const std::string* f = sd_file("WP0001.BLG");
        check(f != nullptr &&
              (uint8_t)(*f)[LOG_HDR_SIZE + LOG_REC_SIZE * recs + 12] == LOG_CLOSE_Q,
              "W 'Q': the trailer records LOG_CLOSE_Q");
    }

    // ── (d) W killed by each of the others.
    reset_test_state(); g_mock_millis = 1000; w_start("");
    Serial.rx_queue.push('D'); doState98();
    check(driveCycleActive && !wProfileActive,
          "W exclusion: starting the drive cycle clears the current profile");

    reset_test_state(); g_mock_millis = 1000; w_start("");
    setManualMotorCurrent(3.0f);
    Serial.rx_queue.push('R'); doState98();
    check(powerShareProfileActive && !wProfileActive,
          "W exclusion: starting the power-share profile clears the current profile");

    reset_test_state(); g_mock_millis = 1000; w_start("");
    y_start("");
    check(combinedProfileActive && !wProfileActive && near_f(wCmdA, 0.0f),
          "W exclusion: starting 'Y' clears the current profile and its command mirror");

    reset_test_state(); g_mock_millis = 1000; w_start("");
    Serial.rx_queue.push('T'); doState98();
    feed_serial_line(" 5 0 100");
    check(trapProfileActive && !wProfileActive,
          "W exclusion: starting the trapezoid clears the current profile");

    // ── (e) The others killed by W.
    reset_test_state(); g_mock_millis = 1000;
    y_start("");
    check(combinedProfileActive, "W exclusion: a 'Y' run is active before 'W'");
    w_start("");
    check(wProfileActive && !combinedProfileActive,
          "W exclusion: starting 'W' clears a running 'Y' (both directions covered)");

    reset_test_state(); g_mock_millis = 1000;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    setManualMotorCurrent(3.0f);
    Serial.rx_queue.push('R'); doState98();
    w_start("");
    check(wProfileActive && !powerShareProfileActive,
          "W exclusion: starting 'W' clears a running power-share profile");

    reset_test_state(); g_mock_millis = 1000;
    trapProfileActive = true; trapCmdA = 3.5f;
    w_start("");
    check(wProfileActive && !trapProfileActive && trapCmdA == 0.0f,
          "W exclusion: starting 'W' clears an active trapezoid and its command");

    reset_test_state(); g_mock_millis = 1000;
    driveCycleActive = true;
    w_start("");
    check(wProfileActive && !driveCycleActive,
          "W exclusion: starting 'W' clears a running drive cycle");
}

// ─── 7. Logging: WP prefix, PS|TP typemask, ps_phase + trap_phase ──────────
static void test_w_logging() {
    test_group("W current profile — logs under the WP prefix with the share+current phase bytes");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    check(logActive && std::string(logFileName) == "WP0001.BLG",
          "W logging: a current-combo run files under the WP prefix, not PS or TP");

    y_run_to(Y_R3 + 1500, /*drain=*/true);
    check(wRegionIdx == 3, "W logging: the run is inside region 3 when the record is taken");
    uint32_t lastIdx = logRecordsWritten - 1;

    const std::string* f = sd_file("WP0001.BLG");
    check(f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE * (lastIdx + 1),
          "W logging: the records reached the card");
    if (f && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE * (lastIdx + 1)) {
        check((uint8_t)(*f)[6] == (uint8_t)(LOG_TYPE_PS | LOG_TYPE_TP),
              "W logging: the header type field is the PS|TP bitmask (share axis + current axis)");
        size_t rec = LOG_HDR_SIZE + LOG_REC_SIZE * lastIdx;
        check((uint8_t)(*f)[rec + REC_OFF_PS_PHASE] == 3 &&
              (uint8_t)(*f)[rec + REC_OFF_TRAP_PHASE] == 3,
              "W logging: the region index is written into BOTH ps_phase and trap_phase");
        check((uint8_t)(*f)[rec + REC_OFF_DC_PHASE] == LOG_PHASE_NONE,
              "W logging: dc_phase stays 0xFF — there is no drive-cycle axis in this profile");
        check(((uint8_t)(*f)[rec + REC_OFF_FLAGS] & 0x01) != 0,
              "W logging: flags bit0 marks the current profile as driving powerBalance");
        check(sd_le<float>(*f, rec + REC_OFF_I_CMD) > 0.0f,
              "W logging: the record's I_cmd carries the profile's commanded current");
    }

    // Name collision: WP participates in the shared run counter.
    reset_test_state();
    g_sd_state.files["WP0007.BLG"] = "";
    g_mock_millis = 1000;
    w_start("");
    check(std::string(logFileName) == "WP0008.BLG",
          "W logging: an existing WP0007.BLG makes the next current-combo run WP0008.BLG");

    // A 'Y' run after a 'W' run must keep its own prefix and continue the shared counter — the
    // masks overlap on LOG_TYPE_PS, so a mis-ordered prefix test would file one as the other.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    check(std::string(logFileName) == "WP0001.BLG", "W logging: the current-combo run opened WP0001.BLG");
    Serial.rx_queue.push('W'); doState98();   // stop it
    sd_drain_until_closed();
    y_start("");
    check(std::string(logFileName) == "YP0002.BLG",
          "W logging: a 'Y' run after a 'W' run files as YP and continues the shared counter");

    // ...and the reverse order.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    check(std::string(logFileName) == "YP0001.BLG", "W logging: the 'Y' run opened YP0001.BLG");
    Serial.rx_queue.push('Y'); doState98();   // stop it
    sd_drain_until_closed();
    w_start("");
    check(std::string(logFileName) == "WP0002.BLG",
          "W logging: a 'W' run after a 'Y' run files as WP — the overlapping PS bit misfiles neither");
}

// ─── 8. Status cadence, suppression, and the charging-manager omission ─────
static void test_w_status_suppression_no_charging() {
    test_group("W current profile — [WP] status, suppression, and no charging manager");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    Serial.tx_clear();
    y_run_to(1000);
    check(Serial.tx_count("[WP] t=") == 2,
          "W status: the [WP] snapshot prints on the 500 ms cadence (twice in the first second)");
    check(Serial.tx_contains("[WP] t=") && Serial.tx_contains(" R") &&
          Serial.tx_contains(" I_cmd=") && Serial.tx_contains(" sp=") &&
          Serial.tx_contains(" act=") && Serial.tx_contains(" I_fc=") &&
          Serial.tx_contains(" I_bt=") && Serial.tx_contains(" V_bus=") &&
          Serial.tx_contains(" FLT=0x"),
          "W status: the snapshot carries the region, the commanded current, both share figures, "
          "the currents, the bus and the fault word");

    plotModeActive = true;
    plotLastMs     = g_mock_millis;
    Serial.tx_clear();
    y_run_to(2000);
    check(Serial.tx_count("[WP] t=") == 0,
          "W status: the [WP] snapshot is suppressed while the plot stream is running");
    check(Serial.tx_count("share_sp:") > 0,
          "W status: the plot stream itself keeps emitting while the current profile runs");
    check(wProfileActive && wRegionIdx > 0,
          "W status: the region machine keeps advancing while the status lines are suppressed");

    plotModeActive = false;
    Serial.tx_clear();
    y_run_to(3000);
    check(Serial.tx_count("[WP] t=") >= 1,
          "W status: the [WP] snapshot resumes once the plot stream is off");

    // Blocking VESC read-back suppressed (the watch is on 'U' since the 'W' rebinding).
    vescWatchActive = true;
    lastVescWatchMs = 0;
    g_mock_millis  += VESC_WATCH_PERIOD_MS + 1;
    vesc.reset();
    doState98();
    check(vesc.getValues_calls == 0,
          "W interlock: pollVescWatch() does not run its blocking poll while 'W' is active");
    vescWatchActive = false;

    Serial.tx_clear();
    Serial.rx_queue.push('G');
    doState98();
    check(Serial.tx_contains("[G] REFUSED: a profile is running") && bringupActive == false,
          "W interlock: 'G' refuses to arm the staged bring-up while the current profile runs");

    // ── The charging manager must never run: its cruise branch calls assertFcChargeEnable(true),
    // which would take the battery off the bus mid-run and pin the MEASURED share at 1.0 — on the
    // one axis this profile exists to measure.
    //
    // NOTE (2026-08-10 full-span actuation): BT_BUS_ENABLE is now ALSO written by
    // applyShareRatio()'s channel cutoff when the commanded droop ratio leaves
    // [DROOP_R_MIN, DROOP_R_MAX]. FC_CHARGE_ENABLE is therefore the clean discriminator — only
    // chargingControl() ever writes it — and the BT_BUS assertion below is deliberately confined
    // to the mid-share regions, where the ratio stays inside the band and no cutoff can fire.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    charge_goal = 0.5f;
    g_pin_value[BT_BUS_ENABLE]    = HIGH;
    g_pin_value[FC_CHARGE_ENABLE] = LOW;
    I_fc   = 2.0f;     // real current in both channels: powerBalance() no-ops at zero total
    I_batt = 2.0f;

    y_run_to(Y_R1 + 2000);   // share still 0.50 here — droop ratio well inside the band
    check(digitalRead(FC_CHARGE_ENABLE) == LOW,
          "W charging: FC_CHARGE_ENABLE stays LOW through R1 — the charging manager never runs");
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "W charging: BT_BUS_ENABLE stays HIGH in the mid-share regions — the battery is not "
          "taken off the bus");
    check(fabsf(wCmdA) > 0.01f,
          "W charging: the current axis is genuinely driving mid-R1 (1.5 A at the defaults)");
    check(!vesc.current_calls.empty() && fabsf(vesc.last_current) > 0.01f,
          "W charging: the commanded current actually reaches the VESC");
    check(SPI.transfer_log.size() > 0,
          "W charging: the droop half of the stack runs alongside (powerBalance writes the MDACs)");

    y_run_to(Y_R2 + 1000);
    check(digitalRead(FC_CHARGE_ENABLE) == LOW,
          "W charging: FC_CHARGE_ENABLE is still LOW deep into R2 with charge_goal set high");
    y_run_to(Y_R4 + 500);
    check(digitalRead(FC_CHARGE_ENABLE) == LOW && wProfileActive,
          "W charging: the FC-charge path stays under operator control for the whole run");
}

#if BENCH_TEST
// ─── doState0() BENCH_TEST bypass: boot to Idle with the power stage off ──────
// Built only in the -DBENCH_TEST=1 pass (run_tests_bench). The -DBENCH_TEST=0 suite covers the
// production doState0 (test_dostate0_reaches_idle_unpowered / _bus_charge_timeout).
static void test_dostate0_bench_bypass() {
    test_group("doState0() BENCH_TEST bypass (power stage off)");
    reset_test_state();
    mainState = 0;
    V_bus = 5.0f;            // deliberately below V_BUS_CHARGED_THRESH — bypass must not gate on it
    g_mock_millis = 0;

    doState0();              // single call: bench path boots straight to Idle

    check(mainState == 1,
          "doState0/bench: boots straight to Idle in one pass");
    check(digitalRead(FC_REG_ENABLE) == LOW && digitalRead(BT_REG_ENABLE) == LOW,
          "doState0/bench: boosts stay OFF");
    check(digitalRead(FC_BUS_ENABLE) == LOW && digitalRead(BT_BUS_ENABLE) == LOW,
          "doState0/bench: bus switches stay OFF");
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState0/bench: motor node NOT pre-charged (power stage dark until 'G')");
    check(digitalRead(BT_SEQUENCE_ENABLE) == LOW,
          "doState0/bench: BT_SEQUENCE stays OFF");
    check(!(fault_flags & FAULT_INIT_FAIL) && error_code == ERR_NONE && mainState != 99,
          "doState0/bench: never gates or faults on low V_bus");
}

// ─── FAULT_UV_BUS is armed under BENCH_TEST even though OC/UV_BATT are not ──
// The whole point of the fw v4 UV_BUS rework: WP0039/TP0016 both ran under BENCH_TEST (State
// 98) and produced zero fault indication on a genuine bus collapse. Contrast directly against
// an overcurrent condition, which IS compiled out under BENCH_TEST (inside #if !BENCH_TEST),
// to pin that UV_BUS's arming is deliberately outside that guard.
static void test_uv_bus_armed_under_bench_test() {
    test_group("FAULT_UV_BUS armed under BENCH_TEST (unlike OC/UV_BATT)");

    reset_test_state();
    mainState = 2;
    I_fc = LIMIT_I_FC_MAX + 5.0f;    // would trip FAULT_OC_FC in the production build
    detectFaults();
    check(!(fault_flags & FAULT_OC_FC) && mainState == 2,
          "UV_BUS/bench: (contrast) FAULT_OC_FC does NOT fire under BENCH_TEST");

    reset_test_state();
    mainState = 2;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;   // arming also requires a boost enabled (fw v4 S4)
    V_bus = V_BUS_CHARGED_THRESH + 0.5f;
    g_mock_millis = 0;
    detectFaults();
    check(uvBusArmed, "UV_BUS/bench: arms under BENCH_TEST exactly as in production");

    V_bus = LIMIT_V_BUS_MIN - 1.0f;
    g_mock_millis = 1000; detectFaults(); // dwell=5ms
    g_mock_millis = 1005; detectFaults(); // dwell=10ms
    g_mock_millis = 1010; detectFaults(); // dwell=15ms
    g_mock_millis = 1015; detectFaults(); // dwell=20ms -> latch
    check(mainState == 99 && error_code == ERR_UV_BUS,
          "UV_BUS/bench: a sustained sag STILL latches under BENCH_TEST — the fw v3 gap this closes");
}

static void test_uv_fc_armed_under_bench_test() {
    test_group("FAULT_UV_FC armed under BENCH_TEST (WP0096/WP0098 happened in State 98 under BENCH_TEST)");

    reset_test_state();
    mainState = 98;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;
    V_fc = V_FC_ARM_THRESH + 1.0f;
    g_mock_millis = 0;
    detectFaults();
    check(fcUvArmed, "UV_FC/bench: arms under BENCH_TEST exactly as in production, including State 98");

    V_fc = LIMIT_V_FC_MIN - 1.0f;
    g_mock_millis = 1000; detectFaults(); // dwell=5ms
    g_mock_millis = 1005; detectFaults(); // dwell=10ms
    g_mock_millis = 1010; detectFaults(); // dwell=15ms
    g_mock_millis = 1015; detectFaults(); // dwell=20ms -> latch
    check(mainState == 99 && error_code == ERR_UV_FC,
          "UV_FC/bench: a sustained V_fc collapse STILL latches under BENCH_TEST -- this is "
          "exactly the WP0096/WP0098 gap (V_fc under 5V, bus still in regulation, MCU stop with "
          "zero fault indication) that this check exists to close");
}
#endif

// ─── main ─────────────────────────────────────────────────────────────────────
// ─── 9. A fault mid-'W' closes the WP file from State 99 with the cause ─────
// Mirrors test_sdlog_lifecycle_fault_path() for the current profile: the fault transition itself
// must do no card I/O, State 99 must latch exactly as it does without a logger attached, and the
// deferred drain must still land a trailer carrying LOG_CLOSE_FAULT + the error code.
static void test_w_fault_path() {
    test_group("W current profile — a fault mid-run closes the WP log from State 99");
    reset_test_state();

    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    check(wProfileActive && logActive,
          "W fault: the current profile was running and logging when the fault is injected");

    y_run_to(12);
    uint32_t recs = logRecordCount;
    check(recs > 0, "W fault: records were captured before the fault");

    triggerFault(FAULT_OC_FC, ERR_OC_FC);

    check(mainState == 99,
          "W fault: triggerFault() latches State 99 with the current profile attached");
    check(error_code == ERR_OC_FC && (fault_flags & FAULT_OC_FC) && (fault_flags & FAULT_ERROR),
          "W fault: the error latch and fault flags are unaffected by the log close request");
    check(logActive == false && logCloseRequested == true && logFile.isOpen() == true,
          "W fault: the fault path only flags the close — no card I/O in triggerFault()");

    int ticks = sd_drain_until_closed_state99();
    check(ticks > 0 && logFile.isOpen() == false,
          "W fault: the loop-level drain finishes the file while State 99 is latched");
    check(mainState == 99 && error_code == ERR_OC_FC,
          "W fault: the error stays latched in State 99 after the log is closed");

    const std::string* f = sd_file("WP0001.BLG");
    check(f != nullptr,
          "W fault: the run's file is the WP-prefixed one, not PS/TP");
    if (f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE * recs + LOG_REC_SIZE) {
        size_t tr = LOG_HDR_SIZE + LOG_REC_SIZE * recs;
        check(sd_le<uint32_t>(*f, tr + 0) == 0xFFFFFFFFu,
              "W fault: the file ends with a valid trailer sentinel");
        check(sd_le<uint32_t>(*f, tr + 4) == recs,
              "W fault: the trailer total matches the records captured before the fault");
        check((uint8_t)(*f)[tr + 12] == LOG_CLOSE_FAULT,
              "W fault: the trailer close reason is LOG_CLOSE_FAULT");
        check((uint8_t)(*f)[tr + 13] == (uint8_t)ERR_OC_FC,
              "W fault: the trailer carries the latched error_code so the cause is in the file");
    } else {
        check(false, "W fault: the pre-fault records plus the trailer all reach the card");
    }
}

// ─── 10. Combined profile x full-span channel cutoff ────────────────────────
// The R6/R11 bound-touches drive the commanded ratio outside [DROOP_R_MIN, DROOP_R_MAX], where
// applyShareRatio() opens a bus switch instead of clipping. This pins the interaction: the cutoff
// itself, its last-source guard, its hysteresis, and — the 2026-08-11 additions — that a LATCHED
// cutoff cannot outlive a run in either direction (natural completion re-closes it; a stop clears
// the ownership flags through safeAllSwitches()).
static void test_share_cutoff_profile_interaction() {
    test_group("Combined profiles x channel cutoff: cut, last-source guard, hysteresis, end-of-run");

    // ── An R6-like condition: both channels on the bus, ratio pushed past DROOP_R_MAX.
    reset_test_state();
    V_bus = 17.5f;                      // regulated, so re-entry is permitted
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;   // re-entry also requires the boost enabled (fw v4 S5)
    g_pin_value[BT_REG_ENABLE] = HIGH;
    shareIsoFC = shareIsoBT = false;

    applyShareRatio(DROOP_R_MAX + 0.05f);
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareIsoBT,
          "cutoff x profile: an R6-like ratio opens exactly the starved (BT) channel");
    check(digitalRead(FC_BUS_ENABLE) == HIGH && !shareIsoFC,
          "cutoff x profile: exactly ONE switch opens — the surviving source stays on the bus");

    // ── Last-source guard: with BT already cut, an R11-like ratio must NOT also cut FC.
    applyShareRatio(DROOP_R_MIN - 0.05f);
    check(digitalRead(FC_BUS_ENABLE) == HIGH && !shareIsoFC,
          "cutoff x profile: the last-source guard blocks the second cutoff — the bus never darkens");
    // That same call also carried BT back past its re-entry threshold (r = 0.10 is well below
    // DROOP_R_MAX - hysteresis), so BT is on the bus again here. Re-cut it deliberately before
    // testing the hysteresis, rather than assuming the guard step left the cutoff standing.
    check(digitalRead(BT_BUS_ENABLE) == HIGH && !shareIsoBT,
          "cutoff x profile: the R11-like ratio also re-entered BT on the same call");
    applyShareRatio(DROOP_R_MAX + 0.05f);
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareIsoBT,
          "cutoff x profile: (setup) BT is cut again for the hysteresis check");

    // ── Hysteresis: returning just inside the band does not re-arm; past the hysteresis does.
    applyShareRatio(DROOP_R_MAX - SHARE_CUTOFF_HYST / 2.0f);
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareIsoBT,
          "cutoff x profile: a ratio dithering just inside the band does not re-close (hysteresis)");
    applyShareRatio(DROOP_R_MAX - SHARE_CUTOFF_HYST);
    check(digitalRead(BT_BUS_ENABLE) == HIGH && !shareIsoBT,
          "cutoff x profile: past the hysteresis the channel re-enters and the flag clears");

    // ── A2 (natural completion): a run that ENDS with a cutoff latched must put it back. Without
    // this the board sits single-sourced forever — no profile means powerBalance() never runs, so
    // applyShareRatio() is never called again and nothing can ever re-enter.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    V_bus = 17.5f;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    g_pin_value[BT_REG_ENABLE] = HIGH;   // completion restore re-entry needs the boost enabled (fw v4 S5)
    applyShareRatio(DROOP_R_MAX + 0.05f);          // latch a BT cutoff mid-run
    check(shareIsoBT && digitalRead(BT_BUS_ENABLE) == LOW,
          "cutoff x completion: (setup) the run holds a BT cutoff when the table runs out");

    wRegionIdx = COMBINED_PROFILE_REGIONS;         // force the completion path
    Serial.tx_clear();
    advanceCurrentComboProfile();
    check(!wProfileActive,
          "cutoff x completion: the profile completed normally");
    check(!shareIsoBT && !shareIsoFC,
          "cutoff x completion: the latched cutoff flag is cleared by the completion path");
    check(digitalRead(BT_BUS_ENABLE) == HIGH,
          "cutoff x completion: the owned channel is put BACK on the bus — no single-sourced latch");
    check(Serial.tx_contains("channel cutoff cleared on completion"),
          "cutoff x completion: the restore is announced so the operator sees the topology change");

    // The same must hold for 'Y' — both completions go through the shared restore helper.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    V_bus = 17.5f;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    g_pin_value[FC_REG_ENABLE] = HIGH;   // completion restore re-entry needs the boost enabled (fw v4 S5)
    applyShareRatio(DROOP_R_MIN - 0.05f);          // latch an FC cutoff this time
    check(shareIsoFC && digitalRead(FC_BUS_ENABLE) == LOW,
          "cutoff x completion (Y): (setup) the run holds an FC cutoff");
    combinedRegionIdx = COMBINED_PROFILE_REGIONS;
    advanceCombinedProfile();
    check(!combinedProfileActive && !shareIsoFC && digitalRead(FC_BUS_ENABLE) == HIGH,
          "cutoff x completion (Y): the FC channel is re-closed and the flag cleared on completion");

    // ── Re-entry must still respect the controller's own bus-regulation guard: with the bus down,
    // the completion restore declines rather than closing a switch onto an unregulated bus.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    V_bus = 17.5f;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    applyShareRatio(DROOP_R_MAX + 0.05f);
    V_bus = 2.0f;                                   // bus collapses before the run ends
    wRegionIdx = COMBINED_PROFILE_REGIONS;
    Serial.tx_clear();
    advanceCurrentComboProfile();
    check(digitalRead(BT_BUS_ENABLE) == LOW && shareIsoBT,
          "cutoff x completion: with the bus unregulated the restore DECLINES (no hot-plug)");
    check(Serial.tx_contains("still cut off"),
          "cutoff x completion: the declined restore says so rather than failing silently");

    // ── A2 (stop path): a stop with a cutoff latched must clear the ownership flags, so a later
    // re-entry after the next bring-up cannot close a switch the controller no longer owns.
    // safeAllSwitches() already owns this; the check pins it against a future refactor.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    V_bus = 17.5f;
    g_pin_value[FC_BUS_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE] = HIGH;
    applyShareRatio(DROOP_R_MAX + 0.05f);
    check(shareIsoBT, "cutoff x stop: (setup) the run holds a BT cutoff");
    Serial.rx_queue.push('W');                      // stop-toggle
    doState98();
    check(!wProfileActive,
          "cutoff x stop: the stop-toggle ended the run");
    check(!shareIsoBT && !shareIsoFC,
          "cutoff x stop: safeAllSwitches() clears the cutoff ownership flags on the stop path");
    check(digitalRead(BT_BUS_ENABLE) == LOW && digitalRead(FC_BUS_ENABLE) == LOW,
          "cutoff x stop: the stop parks BOTH bus switches — the bus is dark, 'G' is required next");
}

// ─── 11. A region-boundary tick is a zero-order hold on both profiles ───────
// advanceComboRegion() returns COMBO_TICK_BOUNDARY on the tick that crosses into a new region and
// produces NO setpoints. Both callers must return without commanding anything, leaving the VESC
// (and v_setpoint) holding the last value — the ZOH the control design assumes. A boundary tick
// that fell through to a stale or zeroed command would put a one-tick notch into every region
// transition, which is exactly the kind of artifact a step-response fit would swallow silently.
static void test_combo_boundary_tick_zoh() {
    test_group("Combined profiles — a region-boundary tick commands nothing (zero-order hold)");

    // ── 'W': no setCurrent() on the boundary tick.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    w_start("");
    y_run_to(Y_R1 + 500);                 // mid-R1, current genuinely moving
    float heldCmd = wCmdA;
    check(fabsf(heldCmd) > 0.01f && wRegionIdx == 1,
          "boundary ZOH: (setup) the W profile is mid-R1 with a live commanded current");

    // Land exactly on the R1→R2 boundary and take ONE tick.
    g_mock_millis = g_y_t0 + Y_R2;
    g_mock_micros += POWER_BAL_PERIOD_US;
    resetControlRateLimiters();           // open the gate so a command WOULD be sent if attempted
    vesc.reset();
    uint8_t idxBefore = wRegionIdx;
    advanceCurrentComboProfile();
    check(wRegionIdx == idxBefore + 1,
          "boundary ZOH: the boundary tick advanced the region index");
    check(vesc.current_calls.empty(),
          "boundary ZOH (W): the boundary tick issues NO setCurrent — the VESC holds its last value");
    check(near_f(wCmdA, heldCmd),
          "boundary ZOH (W): the commanded-current mirror is held, not zeroed, across the boundary");

    // ── 'Y': no v_setpoint write on the boundary tick.
    reset_test_state();
    g_mock_millis = 1000;
    g_mock_micros = 1000000;
    y_start("");
    y_run_to(Y_R1 + 500);
    float heldV = v_setpoint;
    check(fabsf(heldV) > 0.01f && combinedRegionIdx == 1,
          "boundary ZOH: (setup) the Y profile is mid-R1 with a live velocity setpoint");

    g_mock_millis = g_y_t0 + Y_R2;
    g_mock_micros += POWER_BAL_PERIOD_US;
    uint8_t yIdxBefore = combinedRegionIdx;
    advanceCombinedProfile();
    check(combinedRegionIdx == yIdxBefore + 1,
          "boundary ZOH: the Y boundary tick advanced the region index");
    check(near_f(v_setpoint, heldV),
          "boundary ZOH (Y): v_setpoint is held across the boundary, not rewritten or zeroed");
}

int main() {
    printf("teensy_controller.ino — unit tests\n");
    printf("===================================\n");

#if BENCH_TEST
    test_dostate0_bench_bypass();
    // Review F6: tests whose code paths compile IDENTICALLY in both builds also run here, so a
    // bench flash gets the same coverage. Excluded: the production doState0() bring-up tests
    // (the bench bypass replaces that path entirely) and anything relying on faults compiled out
    // under BENCH_TEST (OC/UV/switch-conflict/GENSTAT). OV_BUS and OV_RGN are armed in BOTH
    // builds, so the OV tests belong here.
    test_ov_bus_persistence();
    test_ov_bus_gap_guard();
    test_ov_bus_gap_abandoned_counted();
    test_ov_bus_transient_counter();
    // FAULT_UV_BUS (fw v4) is armed in BOTH builds too — same rationale as OV_BUS above, and
    // the dedicated BENCH_TEST-vs-production contrast for it.
    test_uv_bus_not_armed_dark();
    test_uv_bus_dwell_relay_waveform();
    test_uv_bus_sparse_transient_no_latch();
    test_uv_bus_continuous_collapse_threshold();
    test_uv_bus_dwell_dt_cap();
    test_uv_bus_dwell_leak_floor();
    test_uv_bus_disarm_resets_dwell();
    test_uv_bus_raw_flag_bit();
    test_uv_bus_disarm_on_teardown();
    test_uv_bus_bringup_immunity();
    test_uv_bus_disarm_during_bringup();
    test_uv_bus_disarm_both_boosts_off();
    test_uv_bus_matched_pair_arming();
    test_uv_bus_armed_under_bench_test();
    // FAULT_UV_FC (fw v6) is armed in BOTH builds too, mirroring FAULT_UV_BUS above.
    test_uv_fc_not_armed_no_source();
    test_uv_fc_arms_only_when_pair_and_healthy();
    test_uv_fc_continuous_collapse_latches();
    test_uv_fc_transient_flag_bit();
    test_uv_fc_dwell_leak();
    test_uv_fc_dwell_dt_cap();
    test_uv_fc_disarm_predicates();
    test_uv_fc_armed_under_bench_test();
    test_dostate98_g_bringup();
    test_dostate98_bringup_interlocks();
    test_dostate98_bringup_abort();
    test_dostate98_topology_lockout();
    test_bringup_dark_start();
    test_bringup_g_takes_motor_ownership();
    test_bringup_suppresses_manual_block();
    test_dostate98_mot_pwr_guard();
#else
    test_scale_factors();
    test_ag105_constants();
    test_init_ag105_charger();
    test_poll_ag105();
    test_assert_fc_charge_enable_true();
    test_assert_fc_charge_enable_false();
    test_charging_control_mppt_polarity();
    test_detect_faults();
    test_telemetry_v4_layout();
    test_command_parsing();
    test_pi_controllers();
    test_drive_cycle();
    test_pi_watchdog_guard();
    test_error_code_system();
    test_i2c_fault_injection();
    test_dostate0_reaches_idle_unpowered();
    test_dostate0_precharge_timeout();
    test_dostate0_bus_charge_timeout();
    test_bringup_dwell_dip_and_timeout();
    test_bringup_mot_connect_timeout();
    test_dostate98_g_bringup();
    test_dostate98_bringup_interlocks();
    test_dostate98_bringup_abort();
    test_dostate98_topology_lockout();
    test_bringup_dark_start();
    test_bringup_g_takes_motor_ownership();
    test_bringup_suppresses_manual_block();
    test_bringup_late_gate_faults();
    test_bringup_p3_bus_sag();
    test_ov_bus_persistence();
    test_ov_bus_gap_guard();
    test_ov_bus_gap_abandoned_counted();
    test_ov_bus_transient_counter();
    test_uv_bus_not_armed_dark();
    test_uv_bus_dwell_relay_waveform();
    test_uv_bus_sparse_transient_no_latch();
    test_uv_bus_continuous_collapse_threshold();
    test_uv_bus_dwell_dt_cap();
    test_uv_bus_dwell_leak_floor();
    test_uv_bus_disarm_resets_dwell();
    test_uv_bus_raw_flag_bit();
    test_uv_bus_disarm_on_teardown();
    test_uv_bus_bringup_immunity();
    test_uv_bus_disarm_during_bringup();
    test_uv_bus_disarm_both_boosts_off();
    test_uv_bus_matched_pair_arming();
    // FAULT_UV_FC (fw v6) is armed in BOTH builds too, mirroring FAULT_UV_BUS above (the bench
    // build's own dedicated armed-under-BENCH_TEST contrast lives in the #if branch only).
    test_uv_fc_not_armed_no_source();
    test_uv_fc_arms_only_when_pair_and_healthy();
    test_uv_fc_continuous_collapse_latches();
    test_uv_fc_transient_flag_bit();
    test_uv_fc_dwell_leak();
    test_uv_fc_dwell_dt_cap();
    test_uv_fc_disarm_predicates();
    test_dostate98_hotplug_guard();
    test_dostate98_bt_bus_fc_charge_guard();
    test_dostate98_quit_closes_charge_paths();
    test_dostate3_leaves_bus_energized();
    test_mot_pwr_hotplug_guard();
    test_dostate98_mot_pwr_guard();
    test_bus_voltage_scaling();
    test_genstat_fault();
    test_uv_boot_gate();
    test_pollag105_state_gate();
    test_charger_has_power();
    test_pollag105_unpowered_never_faults();
    test_pollag105_settle_window_suppresses_fault();
    test_lazy_config_on_power();
    test_config_resets_on_power_loss();
    test_icharge_cleared_on_invalid();
    test_ag105_config_read_verify();
    test_charging_control_fc_bootstrap();
    test_state98_drive_cycle_runs_controls();
    test_state98_vesc_readback();
    test_manual_motor_current();
    test_manual_motor_velocity();
    test_motor_current_clamp();
    test_udp_setpoint_sanitize();
    test_drive_cycle_motor_ownership();
    test_wheelspeed_units();
    test_encoder_isr_decode();
    test_edge_period_estimator();
    test_velocity_chain_interlock();
    test_control_rate_limiting();
    test_open_loop_droop();
    test_droop_mapping_bounds();
    test_share_controller_reference();
    test_share_controller_antiwindup();
    test_youla_wrapper_gating();

    // ── fw v10: Youla-H drive (velocity) controller ──────────────────────────
    test_drive_controller_coeff_pinning();
    test_drive_controller_state_is_double();
    test_drive_controller_ac_identity();
    test_drive_controller_replay_small();
    test_drive_controller_replay_regen();
    test_drive_controller_wrapper_gating();
    test_drive_controller_motor_control_youla();
    test_drive_controller_reset_state();
    test_drive_controller_reset_sites();
    test_drive_controller_saturation_consistency();

    test_power_share_setpoint_live();
    test_power_share_profile();
    test_power_share_profile_runs_controls();
    test_pending_input_cancel();
    test_mdac_init_standalone_mode();
    test_plot_stream_format_and_rate();
    test_plot_suppresses_status_lines();
    test_plot_armed_share_profile();
    test_plot_arm_cancellation_paths();
    test_plot_armed_trap_profile();
    test_plot_arm_respects_preconditions();
    test_plot_ov_transient_print_suppressed();
    test_plot_arm_supersede_message();
    test_plot_arm_refused_over_running_profile();
    test_share_start_clears_trap();
    test_trap_runs_without_mot_pwr();
    test_trap_happy_path();
    test_trap_peak_clamp_and_negative();
    test_trap_degenerate_inputs_refused();
    test_trap_nonnumeric_cancels_chain();
    test_trap_stop_toggle();
    test_universal_stop_x();
    test_trap_q_exit_clears_state();
    test_trap_vescwatch_suppressed();
    test_motor_pi_antiwindup();
    test_power_pi_antiwindup();
    test_powerbalance_gated_tick_stable();
    test_powerbalance_min_load_hold();
    test_share_setpoint_governor();
    test_governor_openloop_feedforward_walk();
    test_governor_closedloop_entry_and_response();
    test_governor_closedloop_to_open_hold();
    test_governor_hold_exit_on_setpoint_change();
    test_governor_hysteresis_band();
    test_governor_hysteresis_exact_boundaries();
    test_governor_open_to_closed_continuity();
    test_share_eff_setpoint_slew_from_seed_at_transition();
    test_share_eff_setpoint_slew_converges_to_clipped_target();
    test_share_eff_setpoint_slew_reset_reseeds();
    test_governor_reset_clears_closedloop_run();
    test_governor_lo_clamp_sliver();
    test_governor_setpoint_latch_precedence_at_low_current();
    test_governor_min_load_gate_precedes_governor();
    test_droop_ratio_slew_limit();
    test_share_state_reset_on_profile_start();
    test_share_ratio_cutoff();
    test_setpowersharesetpointlive_resets_loop_mode();
    test_share_setpoint_cutoff_bt_high_side();
    test_share_setpoint_cutoff_fc_low_side();
    test_share_setpoint_cutoff_release();
    test_share_setpoint_cutoff_single_source_guard();
    test_share_setpoint_cutoff_side_flip();
    test_share_setpoint_cutoff_handoff_guard_fc_blocked();
    test_share_setpoint_cutoff_handoff_guard_fc_allowed();
    test_share_setpoint_cutoff_handoff_guard_deferred();
    test_share_setpoint_cutoff_handoff_guard_bt_mirror();
    test_share_setpoint_cutoff_handoff_guard_boundary();
    test_share_setpoint_cutoff_handoff_guard_release_unaffected();
    test_share_cut_deferred_suppresses_r_cutoff_sustained();
    test_share_cut_deferred_clips_reference_to_band_edge();
    test_share_cut_deferred_clears_and_latches_per_tick();
    test_share_cut_deferred_stale_clear_by_reset();
    test_share_cut_deferred_suppresses_apply_share_ratio_directly();
    test_share_setpoint_cutoff_ownership();
    test_share_setpoint_self_heal();
    test_share_iso_orphan_self_heal_no_setpoint_latch();
    test_charging_control_skips_reassert_when_latched();
    test_assert_fc_charge_enable_clears_setpoint_latches();
    test_assert_fc_charge_enable_clears_bt_setpoint_latch();
    test_share_setpoint_release_blocked_without_boost();
    test_share_ratio_reentry_blocked_without_boost();
    test_share_latches_cleared_by_bringup_p0_and_abort();
    test_share_fc_latch_cleared_by_state99();
    test_restore_share_cutoff_on_completion_setpoint_latch();
    test_open_loop_droop_respects_setpoint_latch();
    test_reset_share_control_state_leaves_latch();
    test_wheelspeed_reset();

    // ── SD bench logging ────────────────────────────────────────────────────
    test_sdlog_lifecycle_natural_completion();
    test_sdlog_lifecycle_stop_x_q();
    test_sdlog_lifecycle_fault_path();
    test_sdlog_no_card();
    test_sdlog_overflow_drop_count();
    test_sdlog_record_schema();
    test_sdlog_header_v4_profile_params();
    test_benchlogrecord_v3_layout();
    test_sdlog_flags_share_loop_mode_bits();
    test_sdlog_flags_youla_build_bits();
#if USE_YOULA_DRIVE_CONTROLLER
    test_sdlog_record_u_unsat_drive_x0_saturating();
    test_sdlog_record_u_unsat_drive_x0_unclamped();
    test_sdlog_record_u_unsat_drive_x0_held_value();
    test_sdlog_record_u_unsat_drive_x0_reset();
#endif
    test_sdlog_write_error_midrun();
    test_sdlog_name_collision();
    test_sdlog_rate_1khz();
    test_sdlog_plot_simultaneous();
    test_sdlog_k_status();
    test_sdlog_k_manual_open();
    test_sdlog_k_manual_sampling();
    test_sdlog_k_manual_stop();
    test_sdlog_k1_refusals();
    test_sdlog_k0_refusals();
    test_sdlog_k_garbage_lines();
    test_sdlog_k_manual_x_close();
    test_sdlog_k_manual_q_close();
    test_sdlog_k_manual_fault_close();
    test_sdlog_k_manual_takeover();
    test_sdlog_k_manual_no_card();
    test_sdlog_k1_refused_during_tsweep();
    test_sdlog_k1_during_manual_drain_window();
    test_sdlog_k0_twice_first_reason_wins();
    test_sdlog_k_prompt_under_plot_mode();
    test_sdlog_k_status_ownership_marker();
    test_sdlog_velocity_flag_and_phases();
    test_sdlog_close_deadline_abandon();
    test_sdlog_pending_close_interleave();
    test_sdlog_ring_wrap_drain();
    test_sdlog_counter_exhausted();
    test_sdlog_state99_drain_gated();
    test_sdlog_scan_failure_preserves_files();

    // ── 'T' trapezoid share-setpoint sweep ──────────────────────────────────
    test_tsweep_parsing();
    test_tsweep_end_to_end();
    test_tsweep_waits_for_log_idle();
    test_tsweep_cancel_paths();
    test_tsweep_fire_time_preconditions();

    // ── 'Y' combined drive-cycle + power-share profile ──────────────────────
    test_combined_profile_table_fwv6();
    test_y_params_and_defaults();
    test_y_refusals();
    test_y_region_walk();
    test_y_clip_bounds();
    test_y_vmax_scaling();
    test_y_stop_x_q_exclusion();
    test_y_logging();
    test_y_status_and_suppression();
    test_y_no_charging_manager();
    test_y_takeover_logging();
    test_y_boundary_params();

    // ── 'W' combined commanded-current + power-share profile ────────────────
    test_w_params_and_defaults();
    test_w_refusals();
    test_w_region_walk();
    test_w_scaling_and_clip();
    test_w_r6_share_latch_at_low_load();
    test_w_y_equivalence();
    test_w_stop_x_q_exclusion();
    test_w_logging();
    test_w_status_suppression_no_charging();
    test_w_fault_path();
    test_share_cutoff_profile_interaction();
    test_combo_boundary_tick_zoh();
#endif

    printf("\n===================================\n");
    printf("Results: %d passed, %d failed\n", g_tests_passed, g_tests_failed);
    return (g_tests_failed > 0) ? 1 : 0;
}

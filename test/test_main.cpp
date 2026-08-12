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

    // .ino State 98 bench tools — SD data logger (logOpenForProfile/logSampleTick/logDrainTick)
    // Note sdInitTried/sdAvailable are latches on real hardware (one probe per power cycle); the
    // reset re-arms them so each case can choose its own card_present.
    g_sd_state.reset();
    sdAvailable       = false;
    sdInitTried       = false;
    sdWarnPrinted     = false;
    logActive         = false;
    logCloseRequested = false;
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

    // UV_BUS — only trips in State 2
    reset_test_state();
    V_bus = LIMIT_V_BUS_MIN - 1.0f; V_batt = 7.0f; I_fc = 0;
    mainState = 1;
    detectFaults();
    check(!(fault_flags & FAULT_UV_BUS),
          "detectFaults: no FAULT_UV_BUS in State 1 even when V_bus low");
    check(mainState == 1,
          "detectFaults: mainState unchanged in State 1 with low bus (not run state)");

    reset_test_state();
    V_bus = LIMIT_V_BUS_MIN - 1.0f; V_batt = 7.0f; I_fc = 0;
    mainState = 2;
    detectFaults();
    check(fault_flags & FAULT_UV_BUS,
          "detectFaults: FAULT_UV_BUS set when V_bus low in State 2");
    check(error_code == ERR_UV_BUS,
          "detectFaults: error_code == ERR_UV_BUS from State 2");

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

    // Boundary: just above the threshold must NOT hold (gate is strictly <).
    reset_test_state();
    I_fc   = 0.076f;               // 76 mA total, all FC
    I_batt = 0.0f;
    power_share_setpoint = 0.5f;
    g_mock_micros = 2000;
    powerBalance();
    float g_before = droop_gain_FC_actual;
    g_mock_micros = 4000;
    powerBalance();
    g_mock_micros = 6000;
    powerBalance();
    check(fabsf(droop_gain_FC_actual - g_before) > 1e-6f,
          "min-load hold: 76 mA is above the gate — controller steps normally");
}

// ─── Limit-cycle mitigation (2026-08-11): governor, slew limit, profile reset ─
// The TP0010/TP0013 sweep found a 17–18.5 Hz minority-channel dropout limit
// cycle at asymmetric IN-BAND setpoints under low total current. Mitigation:
// powerBalance() clips the effective setpoint so the commanded minority current
// stays ≥ SHARE_MINORITY_I_MIN_A, and slew-limits the controller-commanded
// ratio; profile starts reset the controller state.
static void test_share_setpoint_governor() {
    test_group("powerBalance() setpoint governor (limit-cycle mitigation)");

    // A) In-band asymmetric setpoint at low load: governed to the feasibility
    // bound. sp=0.30 at I_tot=0.5 A → bound lo = 0.2/0.5 = 0.4; a measured
    // share sitting exactly AT the bound is therefore zero-error, and the
    // controller must hold — not wind toward the raw 0.30.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.2f; I_batt = 0.3f;            // I_tot=0.5, measured share = 0.40
    power_share_setpoint = 0.30f;
    uint32_t t = 0;
    for (int i = 0; i < 200; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    float slew_settled = droopSlew_prev;
    for (int i = 0; i < 300; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - slew_settled) < 5e-3f,
          "governor: in-band sp below the minority floor is clipped — zero-error at the bound, no winding");

    // B) Same setpoint/share at HIGH load: bound relaxes (lo = 0.2/2.0 = 0.1),
    // the raw setpoint applies, the −0.10 error is real → the ratio must move.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.8f; I_batt = 1.2f;            // I_tot=2.0, measured share = 0.40
    power_share_setpoint = 0.30f;
    t = 0;
    for (int i = 0; i < 200; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    // Contrast with (A): the same −0.10 apparent error is now REAL (sp_eff =
    // 0.30), so by tick 200 the ratio has been driven well off mid-band
    // (possibly all the way to the band edge / cutoff — that's fine, the point
    // is that it moved, where (A) held).
    check(droopSlew_prev < 0.45f,
          "governor: at high load the bound relaxes and the same error drives the ratio");

    // C) Collapse to the balanced split: I_tot ≤ 2·SHARE_MINORITY_I_MIN_A pins
    // sp_eff at 0.5, so a balanced measured share is zero-error even with an
    // asymmetric raw setpoint.
    reset_test_state();
    digitalWrite(FC_BUS_ENABLE, HIGH);
    digitalWrite(BT_BUS_ENABLE, HIGH);
    V_bus = 16.0f;
    I_fc = 0.15f; I_batt = 0.15f;          // I_tot=0.3 < 0.4, measured 0.50
    power_share_setpoint = 0.30f;
    t = 0;
    for (int i = 0; i < 200; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    float slew_bal = droopSlew_prev;
    for (int i = 0; i < 300; i++) { t += 1000; g_mock_micros = t; powerBalance(); }
    check(fabsf(droopSlew_prev - slew_bal) < 5e-3f,
          "governor: below 2x the minority floor sp_eff collapses to 0.5 (balanced = zero error)");

    // D) Out-of-band setpoints BYPASS the governor: full-span semantics are the
    // cutoff path's (sp=1.0 must still starve BT out via its bus switch even at
    // low load — TP0009/TP0011 showed the topology-forced endpoints are stable).
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
    reset_test_state();
    V_fc = LIMIT_V_FC_MIN - 0.1f; V_batt = 7.0f; V_bus = 16.0f; I_fc = 0;
    mainState = 2;
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

    // Drive the encoder at a known constant rate and let the averaging buffer fill.
    // 1 count per 100 us = 10000 counts/s.
    reset_test_state();
    const float counts_per_sec = 10000.0f;
    const uint32_t step_us     = 100;
    encoderPos     = 0;
    g_mock_micros  = 0;
    wheelSpeedResetPending = true;
    updateWheelSpeed();                 // consume the reset
    for (int i = 1; i <= 400; i++) {    // > buffer depth, so the window is fully populated
        g_mock_micros = (uint32_t)i * step_us;
        encoderPos    = i;              // +1 count per step
        updateWheelSpeed();
    }

    const float rev_per_sec = counts_per_sec / ENCODER_COUNTS_PER_REV;
    const float expect_mps  = rev_per_sec * 6.28318530718f * FLYWHEEL_RADIUS_M;
    check(fabsf(v_actual - expect_mps) < fabsf(expect_mps) * 0.01f,
          "units: v_actual matches omega*2*pi*r for a known count rate (within 1%)");
    // The old broken form would have produced rev/s x 1.0 — i.e. 2*pi*r times LARGER. Assert we are
    // not that value, so a revert is caught rather than silently passing the tolerance above.
    check(fabsf(v_actual - rev_per_sec) > fabsf(expect_mps),
          "units: v_actual is NOT the old rev/s-times-inches value");

    // Direction: a negative count slope must give an equal-magnitude negative speed.
    reset_test_state();
    encoderPos     = 0;
    g_mock_micros  = 0;
    wheelSpeedResetPending = true;
    updateWheelSpeed();
    for (int i = 1; i <= 400; i++) {
        g_mock_micros = (uint32_t)i * step_us;
        encoderPos    = -i;
        updateWheelSpeed();
    }
    check(fabsf(v_actual + expect_mps) < fabsf(expect_mps) * 0.01f,
          "units: reverse rotation gives an equal-magnitude negative v_actual");
}

// ─── Velocity-chain calibration interlock ────────────────────────────────────
// While the two scale constants are placeholders, v_actual under-reads, so the velocity PI
// OVER-DRIVES. commandMotorCurrent() bounds amps, not speed, so the velocity entry points must
// refuse outright rather than rely on the current clamp.
static void test_velocity_chain_interlock() {
    test_group("Velocity-chain calibration interlock");

    // The SHIPPED default must be uncalibrated — this is the safety default, not a convenience.
    check(VELOCITY_CHAIN_CALIBRATED == 0,
          "interlock: firmware ships with VELOCITY_CHAIN_CALIBRATED = 0");

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

    // motorControl(): the UDP velocity path. A large velocity error with the uncalibrated
    // motorConstant = 0.1 would command error/0.1 amps — 50 A at 5 m/s — before this clamp.
    reset_test_state();
    v_actual   = 0.0f;
    v_setpoint = 5.0f;
    pi_motor_accum = 0; pi_motor_lastMicros = 0;
    g_mock_micros  = 100000;
    vesc.reset();
    motorControl();
    check(!vesc.current_calls.empty() && fabsf(vesc.last_current) <= MOTOR_I_CMD_MAX + 1e-4f,
          "clamp: motorControl() at 5 m/s error stays within MOTOR_I_CMD_MAX");
    check(fabsf(vesc.last_current - MOTOR_I_CMD_MAX) < 1e-4f,
          "clamp: motorControl() saturates AT the ceiling (proportional term was unbounded)");

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
    check(Serial.tx_contains("sp:") && Serial.tx_contains(",act:") && Serial.tx_contains(",gFC:")
       && Serial.tx_contains(",gBT:") && Serial.tx_contains(",ifc:") && Serial.tx_contains(",ibt:"),
          "plot: line carries all six labelled fields in order");

    // Rate gate: no second line until PLOT_PERIOD_MS has elapsed.
    Serial.tx_clear();
    g_mock_millis += PLOT_PERIOD_MS - 1;
    doState98();
    check(Serial.tx_count("sp:") == 0, "plot: no line before PLOT_PERIOD_MS elapses");
    g_mock_millis += 1;
    doState98();
    check(Serial.tx_count("sp:") == 1, "plot: exactly one line once the period elapses");

    // The reported share is the same quantity powerBalance() closes on.
    Serial.tx_clear();
    I_fc = 3.0f; I_batt = 1.0f;          // |I_fc| / (|I_fc| + |I_batt|) = 0.750
    g_mock_millis += PLOT_PERIOD_MS;
    doState98();
    check(Serial.tx_contains("act:0.750"), "plot: 'act' is the measured share |I_fc|/(|I_fc|+|I_batt|)");
    check(Serial.tx_contains("ifc:3.000") && Serial.tx_contains("ibt:1.000"),
          "plot: per-channel currents reported at 3 decimals");

    // Zero current → share undefined → reported as 0 (flat trace), never NaN.
    Serial.tx_clear();
    I_fc = 0.0f; I_batt = 0.0f;
    g_mock_millis += PLOT_PERIOD_MS;
    doState98();
    check(Serial.tx_contains("act:0.000"), "plot: zero current reports act=0, not NaN");

    // 'L' again turns it off and the stream stops.
    Serial.tx_clear();
    Serial.rx_queue.push('L');
    doState98();
    check(plotModeActive == false, "'L': toggles the plot stream OFF");
    g_mock_millis += PLOT_PERIOD_MS * 4;
    doState98();
    check(Serial.tx_count("sp:") == 0, "plot: no lines emitted once the stream is off");
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

    // A peak ABOVE MOTOR_I_CMD_MAX (5A) is accepted un-clamped — phase current is not bus current,
    // so the 5A source-budget ceiling does not apply here. Only TRAP_I_ABS_MAX (ESC rating) bounds it.
    mainState = 98;
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    g_mock_millis = 0;
    Serial.rx_queue.push('T');
    doState98();
    g_mock_millis = 1000;
    feed_serial_line(" 10 0 10");   // 10A > MOTOR_I_CMD_MAX, < TRAP_I_ABS_MAX; rampMs = 1000
    doState98();
    check(trapProfileActive == true && fabsf(trapImax - 10.0f) < 1e-4f,
          "trap: 10A peak accepted un-clamped (above the 5A MOTOR_I_CMD_MAX budget)");
    // ...and the VESC actually receives >5A: mid-ramp at t=750ms → 7.5A.
    g_mock_millis = 1000 + 750;
    g_mock_micros = 1000000;
    vesc.reset();
    advanceTrapProfile();
    check(!vesc.current_calls.empty() && fabsf(vesc.last_current - 7.5f) < 0.05f,
          "trap: commanded current above MOTOR_I_CMD_MAX reaches the VESC (7.5A sent)");

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
#define REC_OFF_FAULTS     44
#define REC_OFF_PS_PHASE   46
#define REC_OFF_DC_PHASE   47
#define REC_OFF_TRAP_PHASE 48
#define REC_OFF_FLAGS      49

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
          "SD lifecycle: file size is header + 52*N records + one 52-byte trailer");

    if (f != nullptr && f->size() >= LOG_HDR_SIZE + LOG_REC_SIZE) {
        check(f->compare(0, 4, "BLG1") == 0,
              "SD lifecycle: the header opens with the 'BLG1' magic");
        check((uint8_t)(*f)[4] == 2,
              "SD lifecycle: the header declares format version 2");
        check((uint8_t)(*f)[5] == (uint8_t)LOG_REC_SIZE,
              "SD lifecycle: the header declares a 52-byte record size");
        check((uint8_t)(*f)[6] == LOG_TYPE_TP,
              "SD lifecycle: the header profile bitmask is LOG_TYPE_TP for a 'T' run");
        check(sd_le<uint16_t>(*f, 18) == (uint16_t)FW_VERSION,
              "SD lifecycle: the v2 header stamps FW_VERSION at offset 18");

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

// ─── 6. Golden record schema: byte-exact field layout ───────────────────────
static void test_sdlog_record_schema() {
    test_group("SD log: one record's 52 bytes match the documented field layout exactly");
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
          "SD schema: the card holds the 32-byte header followed by one 52-byte record");
    if (f == nullptr || f->size() < LOG_HDR_SIZE + LOG_REC_SIZE) return;

    // ── Header ──────────────────────────────────────────────────────────────
    check(f->compare(0, 4, "BLG1") == 0 && (uint8_t)(*f)[4] == 2 &&
          (uint8_t)(*f)[5] == (uint8_t)LOG_REC_SIZE && (uint8_t)(*f)[6] == LOG_TYPE_PS,
          "SD schema: the header carries magic, version 2, record size 52 and the PS type bit");
    check(sd_le<uint32_t>(*f, 8) == 5000u && sd_le<uint32_t>(*f, 12) == 50000u,
          "SD schema: the header timebase is the millis()/micros() pair at open");
    check(sd_le<uint16_t>(*f, 16) == (uint16_t)(K_DROOP * 1000.0f + 0.5f),
          "SD schema: the header stores K_DROOP in milliohms for the decoder");
    check(sd_le<uint16_t>(*f, 18) == (uint16_t)FW_VERSION,
          "SD schema: the v2 header stamps FW_VERSION at offset 18");
    check(f->compare(20, 12, std::string(12, '\0')) == 0,
          "SD schema: the header's reserved tail is zero-filled out to 32 bytes");

    // ── Record: build the expected 52 bytes independently, then memcmp ──────
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
    uint16_t ff = 0x0012;       memcpy(exp + REC_OFF_FAULTS, &ff, 2);
    exp[REC_OFF_PS_PHASE]   = 3;      // the PS profile is running, at phase 3
    exp[REC_OFF_DC_PHASE]   = 0xFF;   // drive cycle not running
    exp[REC_OFF_TRAP_PHASE] = 0xFF;   // trapezoid not running
    exp[REC_OFF_FLAGS]      = 0x03;   // bit0 profile driving powerBalance, bit1 velocity chain OK
    // exp[50..51] stay zero (pad)

    check(memcmp(f->data() + LOG_HDR_SIZE, exp, LOG_REC_SIZE) == 0,
          "SD schema: the written record is byte-identical to the expected 52-byte layout");

    // Field-level checks so a failure above localises instead of just saying "bytes differ".
    check(sd_le<uint32_t>(*f, LOG_HDR_SIZE + REC_OFF_T_US) == 123456u,
          "SD schema: t_us at offset 0 is the micros() value at the sample");
    check(sd_le<float>(*f, LOG_HDR_SIZE + REC_OFF_SHARE_ACT) == 0.75f,
          "SD schema: share_act at offset 8 is |I_fc|/(|I_fc|+|I_batt|)");
    check(sd_le<uint16_t>(*f, LOG_HDR_SIZE + REC_OFF_FAULTS) == 0x0012,
          "SD schema: fault_flags at offset 44 is the live 16-bit fault word");
    check((uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_PS_PHASE] == 3 &&
          (uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_DC_PHASE] == LOG_PHASE_NONE &&
          (uint8_t)(*f)[LOG_HDR_SIZE + REC_OFF_TRAP_PHASE] == LOG_PHASE_NONE,
          "SD schema: the three phase bytes are independent, 0xFF for the inactive profiles");
    check((uint8_t)(*f)[LOG_HDR_SIZE + 50] == 0 && (uint8_t)(*f)[LOG_HDR_SIZE + 51] == 0,
          "SD schema: the two pad bytes are zero-filled");
}

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
    check(Serial.tx_count("sp:") == 100 / (int)PLOT_PERIOD_MS,
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
    check(Serial.tx_count("sp:") == 100 / (int)PLOT_PERIOD_MS,
          "SD + plot: the plot cadence is unchanged after the log closed");
}

// ─── 11. 'K' status command ─────────────────────────────────────────────────
static void test_sdlog_k_status() {
    test_group("SD log: 'K' prints the logger status and stays live during the bring-up lockout");
    reset_test_state();

    mainState = 98;
    Serial.tx_clear();
    Serial.rx_queue.push('K');
    doState98();
    check(Serial.tx_contains("=== SD logger ==="),
          "'K': prints the SD logger status block");
    check(Serial.tx_contains("card:") && Serial.tx_contains("file:") &&
          Serial.tx_contains("records:") && Serial.tx_contains("dropped:"),
          "'K': the status block carries the card, file, record and drop fields");
    check(Serial.tx_contains("not probed yet"),
          "'K': before any run the card is reported as not yet probed");
    check(g_sd_state.begin_calls == 0,
          "'K': the status print never probes the card itself (read-only, non-blocking)");

    // With a run in progress the same line must name the file and the live counts.
    reset_test_state();
    sd_start_share_run();
    sd_run_ms(5);
    Serial.tx_clear();
    Serial.rx_queue.push('K');
    doState98();
    check(Serial.tx_contains("PS0001.BLG") && Serial.tx_contains("YES (sampling)"),
          "'K': during a run the status names the open file and reports sampling active");

    // Bring-up lockout: 'K' is read-only, so it must NOT be refused like the topology keys.
    Serial.tx_clear();
    bringupActive = true;
    Serial.rx_queue.push('K');
    doState98();
    check(Serial.tx_contains("=== SD logger ==="),
          "'K': still prints while the staged bring-up holds the topology lockout");
    check(!Serial.tx_contains("REFUSED: staged bring-up"),
          "'K': is not refused by the staged-bring-up lockout");
    bringupActive = false;
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

    for (int i = 0; i < 50; i++) logDrainTick();   // 9 records per tick → 450 drained
    check(logRecordsWritten == 450 && logRingTail == 450u * LOG_REC_SIZE,
          "SD wrap: a partial drain advances the tail off zero, leaving 450 records pending");

    fill(500);                                  // head passes the physical end of logRing
    check(logRingHead < logRingTail,
          "SD wrap: the head has wrapped past the end of the ring, so pending data spans the wrap");
    check(logRingCount == 950 && logDroppedCount == 0,
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

    // R6 brief excursion to the high share bound.
    y_run_to(Y_R6 + 750);
    check(combinedRegionIdx == 6 && near_f(power_share_setpoint, 1.0f),
          "Y walk: R6 drives the share to 1.00 (all-FC) to exercise the droop clamp");
    check(near_f(v_setpoint, 1.0f),
          "Y walk: R6 holds the velocity at full scale through the share excursion");

    // R8 entry: BOTH axes step in the SAME tick (v 1.0 -> 0.5, s 0.35 -> 0.65).
    y_run_to(Y_R8 - 1);
    check(near_f(v_setpoint, 1.0f) && near_f(power_share_setpoint, 0.35f, 1e-3f),
          "Y walk: R7 ends at v=1.0 / share=0.35 on the last tick before R8");
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

    // R4's 1.0 end value, observed on R5's flat hold.
    y_run_to(Y_R5 + 1000);
    check(combinedRegionIdx == 5 && near_f(v_setpoint, 2.0f, 1e-3f),
          "Y Vmax: R4's normalised 1.0 endpoint scales to the full 2.0 m/s at Vmax = 2");
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
    check(Serial.tx_count("sp:") > 0,
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

    // The ceiling is the TRAPEZOID's (ESC rating), not the 5 A velocity-path budget — this
    // profile commands phase current through the same chokepoint 'T' uses.
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

    // A peak above MOTOR_I_CMD_MAX (the 5 A source budget) must still be accepted — same policy
    // as 'T', and the reason the ceiling is TRAP_I_ABS_MAX in the first place.
    reset_test_state();
    w_start(" 10");
    check(wProfileActive == true && near_f(wProfileImax, 10.0f),
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

    y_run_to(Y_R5 + 1000);
    check(near_f(wCmdA, 5.0f, 1e-3f) && near_f(power_share_setpoint, 0.35f, 1e-3f),
          "W walk: R5 buffers at the full 5.0 A peak with the share at 0.35");

    y_run_to(Y_R6 + 750);
    check(wRegionIdx == 6 && near_f(power_share_setpoint, 1.0f) && near_f(wCmdA, 5.0f, 1e-3f),
          "W walk: R6 drives the share to 1.00 (all-FC) while holding the current peak");

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

    // R4's normalised 1.0 endpoint, observed on R5's flat hold (the transition tick sets nothing).
    y_run_to(Y_R5 + 1000);
    check(wRegionIdx == 5 && near_f(wCmdA, 6.0f, 1e-3f),
          "W scaling: R4's normalised 1.0 endpoint scales to the full 6.0 A at Imax = 6");
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
    check(near_f(wAxis[10], 8.0f, 1e-3f),
          "W/Y equivalence: the R6 sample really is at the full 8.0 A peak, so the scale factor is "
          "load-bearing in the comparison above");
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
    check(Serial.tx_count("sp:") > 0,
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
    test_velocity_chain_interlock();
    test_control_rate_limiting();
    test_open_loop_droop();
    test_droop_mapping_bounds();
    test_share_controller_reference();
    test_share_controller_antiwindup();
    test_youla_wrapper_gating();
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
    test_droop_ratio_slew_limit();
    test_share_state_reset_on_profile_start();
    test_share_ratio_cutoff();
    test_wheelspeed_reset();

    // ── SD bench logging ────────────────────────────────────────────────────
    test_sdlog_lifecycle_natural_completion();
    test_sdlog_lifecycle_stop_x_q();
    test_sdlog_lifecycle_fault_path();
    test_sdlog_no_card();
    test_sdlog_overflow_drop_count();
    test_sdlog_record_schema();
    test_sdlog_write_error_midrun();
    test_sdlog_name_collision();
    test_sdlog_rate_1khz();
    test_sdlog_plot_simultaneous();
    test_sdlog_k_status();
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

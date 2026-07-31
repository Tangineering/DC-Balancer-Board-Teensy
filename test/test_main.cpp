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
}

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

    // OV_BUS
    reset_test_state();
    V_batt = 7.0f; V_bus = LIMIT_V_BUS_MAX + 0.1f; I_fc = 0;
    mainState = 1;
    detectFaults();
    check(fault_flags & FAULT_OV_BUS,
          "detectFaults: FAULT_OV_BUS set when V_bus > LIMIT_V_BUS_MAX");
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

// ─── doState0() gentle bring-up reaches Idle once the bus is charged ──────────
static void test_dostate0_reaches_idle_unpowered() {
    test_group("doState0() bring-up reaches Idle when bus charges");

    // doState0() is a non-blocking phase machine: switches first, settle, boosts, then gate on
    // V_bus. Drive it through its phases with the bus coming up (V_bus 16V ≥ threshold).
    // The charger is unpowered in Init and doState0() no longer touches it, so a NACKing charger
    // must not matter.
    reset_test_state();
    Wire.next_endtransmission_result = 1;   // any stray I2C would NACK — must not matter
    mainState = 0;
    V_bus = 16.0f;                           // bus comes up past V_BUS_CHARGED_THRESH
    g_mock_millis = 0;

    doState0();                              // phase 0: enable bus switches
    check(mainState == 0,
          "doState0: still in Init after enabling bus switches");
    check(digitalRead(FC_BUS_ENABLE) == HIGH && digitalRead(BT_BUS_ENABLE) == HIGH,
          "doState0: bus switches enabled FIRST");
    check(digitalRead(MOT_PWR_ENABLE) == HIGH,
          "doState0: MOT_PWR pre-charged with the bus switches (before boosts) — no full-bus hot-plug");
    check(digitalRead(FC_REG_ENABLE) == LOW && digitalRead(BT_REG_ENABLE) == LOW,
          "doState0: boosts NOT enabled before the bus switches (no hot-plug)");

    g_mock_millis = BUS_SETTLE_MS + 1;
    doState0();                              // phase 1: enable boosts + init
    check(digitalRead(FC_REG_ENABLE) == HIGH && digitalRead(BT_REG_ENABLE) == HIGH,
          "doState0: boosts enabled after the settle window");

    g_mock_millis += 1;
    doState0();                              // phase 2: V_bus ≥ threshold → Idle
    check(mainState == 1,
          "doState0: advances to Idle once V_bus reaches the charge threshold");
    check(error_code == ERR_NONE && !(fault_flags & FAULT_INIT_FAIL),
          "doState0: no fault latched on a healthy bring-up");
}

// ─── doState0() faults if the bus never charges (dead boost / no source) ──────
static void test_dostate0_bus_charge_timeout() {
    test_group("doState0() bus-charge timeout → FAULT_INIT_FAIL");

    reset_test_state();
    mainState = 0;
    V_bus = 5.0f;                            // bus never reaches V_BUS_CHARGED_THRESH
    g_mock_millis = 0;

    doState0();                              // phase 0
    g_mock_millis = BUS_SETTLE_MS + 1;
    doState0();                              // phase 1 (boosts on; start timeout clock)
    check(mainState == 0,
          "doState0: still in Init while the bus is below threshold");

    g_mock_millis += BUS_CHARGE_TIMEOUT_MS + 1;
    doState0();                              // phase 2: timeout
    check(mainState == 99,
          "doState0: latches State 99 when the bus never charges");
    check(error_code == ERR_INIT_FAIL,
          "doState0: ERR_INIT_FAIL latched on bus-charge timeout");
    check((fault_flags & FAULT_INIT_FAIL) != 0,
          "doState0: FAULT_INIT_FAIL flag set on bus-charge timeout");
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

// ─── Motor-node pre-charge hot-plug guard (Death 5) ──────────────────────────
static void test_mot_pwr_hotplug_guard() {
    test_group("MOT_PWR hot-plug guard (motPwrHotPlugUnsafe/assertMotPwrEnable/doState2)");

    // motPwrHotPlugUnsafe(): true only when the bus is up AND the motor node lags it by > margin.
    reset_test_state();
    V_bus = 16.0f; V_rgn = 0.0f;             // bus up, motor node discharged
    check(motPwrHotPlugUnsafe() == true,
          "unsafe: bus energized + motor node discharged → hot-plug");
    V_rgn = 16.0f;                            // motor node tracks the bus (pre-charged)
    check(motPwrHotPlugUnsafe() == false,
          "safe: motor node pre-charged (V_rgn ≈ V_bus)");
    V_bus = 5.0f; V_rgn = 0.0f;               // low-voltage bring-up window (bus not yet up)
    check(motPwrHotPlugUnsafe() == false,
          "safe: bus below charged threshold → low-voltage pre-charge allowed");

    // assertMotPwrEnable(): OFF always allowed; ON idempotent; ON refused when unsafe; ON allowed safe.
    reset_test_state();
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    check(assertMotPwrEnable(false) == true && digitalRead(MOT_PWR_ENABLE) == LOW,
          "assert: OFF always succeeds");
    g_pin_value[MOT_PWR_ENABLE] = HIGH; V_bus = 16.0f; V_rgn = 0.0f;
    check(assertMotPwrEnable(true) == true && digitalRead(MOT_PWR_ENABLE) == HIGH,
          "assert: already-ON is idempotent (never re-checks the guard)");
    g_pin_value[MOT_PWR_ENABLE] = LOW; V_bus = 16.0f; V_rgn = 0.0f;
    check(assertMotPwrEnable(true) == false && digitalRead(MOT_PWR_ENABLE) == LOW,
          "assert: ON refused when it would hot-plug (stays LOW)");
    g_pin_value[MOT_PWR_ENABLE] = LOW; V_bus = 16.0f; V_rgn = 17.0f;
    check(assertMotPwrEnable(true) == true && digitalRead(MOT_PWR_ENABLE) == HIGH,
          "assert: ON allowed when the motor node is already charged");
    g_pin_value[MOT_PWR_ENABLE] = LOW; V_bus = 5.0f; V_rgn = 0.0f;
    check(assertMotPwrEnable(true) == true && digitalRead(MOT_PWR_ENABLE) == HIGH,
          "assert: ON allowed during low-voltage bring-up (pre-charge)");

    // doState2(): normal case — motor node already energized → runs, no fault.
    reset_test_state();
    mainState = 2;
    g_pin_value[MOT_PWR_ENABLE] = HIGH; V_bus = 16.0f; V_rgn = 16.0f;
    doState2();
    check(mainState == 2 && !(fault_flags & FAULT_MOT_HOTPLUG),
          "doState2: pre-charged motor node → runs normally, no fault");
    check(digitalRead(MOT_PWR_ENABLE) == HIGH,
          "doState2: MOT_PWR stays energized");

    // doState2(): abnormal case — motor node discharged at full bus → refuse + fault (no hot-plug).
    reset_test_state();
    mainState = 2;
    g_pin_value[MOT_PWR_ENABLE] = LOW; V_bus = 16.0f; V_rgn = 0.0f;
    doState2();
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState2: refuses the hot-plug (MOT_PWR stays LOW)");
    check(mainState == 99 && error_code == ERR_MOT_HOTPLUG,
          "doState2: latches State 99 with ERR_MOT_HOTPLUG instead of hot-plugging");
    check((fault_flags & FAULT_MOT_HOTPLUG) != 0,
          "doState2: FAULT_MOT_HOTPLUG flag set");
}

// ─── State 98 '3' motor-node hot-plug guard ──────────────────────────────────
static void test_dostate98_mot_pwr_guard() {
    test_group("State 98 '3' refuses the motor-node hot-plug");
    reset_test_state();
    mainState = 98;

    // Motor node discharged + bus up → '3' ON refused (MOT_PWR stays LOW).
    g_pin_value[MOT_PWR_ENABLE] = LOW;
    V_bus = 16.0f; V_rgn = 0.0f;
    Serial.rx_queue.push('3');
    doState98();
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState98: '3' refused (motor node discharged, bus up) — stays LOW");

    // Motor node pre-charged → '3' ON allowed.
    g_pin_value[MOT_PWR_ENABLE] = LOW;
    V_bus = 16.0f; V_rgn = 17.0f;
    Serial.rx_queue.push('3');
    doState98();
    check(digitalRead(MOT_PWR_ENABLE) == HIGH,
          "doState98: '3' allowed when the motor node is pre-charged");

    // Turning OFF is always allowed.
    g_pin_value[MOT_PWR_ENABLE] = HIGH;
    V_bus = 16.0f; V_rgn = 0.0f;
    Serial.rx_queue.push('3');
    doState98();
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState98: '3' OFF always allowed (guard only blocks ON)");
}

// ─── V_BUS_NOMINAL parameterization preserves current thresholds ─────────────
static void test_bus_voltage_scaling() {
    test_group("V_BUS_NOMINAL-derived thresholds (16V nominal, RD1=215k retune executed)");
    // 16V bus retune executed 2026-07-11 (RD1 bodged 237k -> 215k, V0 = 15.91V no-load).
    check(fabsf(LIMIT_V_BUS_MAX - 17.0f) < 1e-4f,
          "LIMIT_V_BUS_MAX = V_BUS_NOMINAL + 1.0 = 17.0 (16V nominal)");
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

// ─── State 98 bench tools: VESC read-back ('E' one-shot / 'W' watch) ─────────
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

    // 'W' enables watch; enabling does NOT poll immediately (0 < period).
    reset_test_state();
    mainState = 98;
    vescWatchActive = false;
    vesc.reset();
    g_mock_millis = 1000;
    Serial.rx_queue.push('W');
    doState98();
    check(vescWatchActive && vesc.getValues_calls == 0,
          "'W': enables watch, no poll on the enabling tick");

    // After the period elapses, a bare tick polls once.
    g_mock_millis = 1000 + VESC_WATCH_PERIOD_MS;
    doState98();
    check(vesc.getValues_calls == 1,
          "watch: polls getVescValues() once period elapsed");

    // A second 'W' stops further polling.
    Serial.rx_queue.push('W');
    doState98();                      // toggles off (does not poll while turning off)
    int calls_after_off = vesc.getValues_calls;
    g_mock_millis += 2 * VESC_WATCH_PERIOD_MS;
    doState98();
    check(!vescWatchActive && vesc.getValues_calls == calls_after_off,
          "'W' again: stops the watch, no further polls");

    // Watch period is respected: a sub-period tick does not poll.
    reset_test_state();
    mainState = 98;
    vescWatchActive = false;
    vesc.reset();
    g_mock_millis = 1000;
    Serial.rx_queue.push('W');
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
    Serial.rx_queue.push('W');
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
        uint16_t expFCcode = (uint16_t)(constrain(expFC, 0.0f, 1.0f) * MDAC_res);
        uint16_t expBTcode = (uint16_t)(constrain(expBT, 0.0f, 1.0f) * MDAC_res);
        check(SPI.transfer_log[0] == expFCcode,
              "open-loop droop: FC MDAC code matches clamped gain");
        check(SPI.transfer_log[1] == expBTcode,
              "open-loop droop: BT MDAC code matches clamped gain");
    }
    check(powerBalanceLive == false,
          "open-loop droop: clears powerBalanceLive (closed loop must not stomp it)");
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

    // out-of-span requests clamp to the span edges (not the old 0.01/0.99)
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

    // Clamp to [0.01, 0.99]
    setPowerShareSetpointLive(1.5f);
    check(fabsf(power_share_setpoint - 0.99f) < 1e-4f,
          "power-share live: clamped to 0.99");
    setPowerShareSetpointLive(0.0f);
    check(fabsf(power_share_setpoint - 0.01f) < 1e-4f,
          "power-share live: clamped to 0.01");

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
int main() {
    printf("teensy_controller.ino — unit tests\n");
    printf("===================================\n");

#if BENCH_TEST
    test_dostate0_bench_bypass();
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
    test_dostate0_bus_charge_timeout();
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
    test_wheelspeed_reset();
#endif

    printf("\n===================================\n");
    printf("Results: %d passed, %d failed\n", g_tests_passed, g_tests_failed);
    return (g_tests_failed > 0) ? 1 : 0;
}

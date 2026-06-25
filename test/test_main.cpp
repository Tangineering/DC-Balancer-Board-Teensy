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
    V_fc = 10.0f;     V_batt = 7.0f;   V_bus = 18.0f;  // above UV_FC/UV_BATT limits
    V_chg = 0;        V_rgn = 0;

    power_share_actual   = 0;
    droop_gain_FC_actual = 0;
    droop_gain_BT_actual = 0;
    ag105_status_raw     = 0;
    ag105Configured      = false;
    ag105HadPower        = false;
    ag105PowerOnMs       = 0;
    fault_flags          = 0;
    error_code           = ERR_NONE;
    error_source_state   = 0;

    // PI integrator state (hoisted to file scope so it can be reset between cases)
    pi_motor_accum = 0;  pi_motor_lastMicros = 0;
    pi_power_accum = 0;  pi_power_lastMicros = 0;

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

    // Inject: GENSTAT = 0x00 (startup) — should NOT be ready
    ag105_status_raw = 0x00;
    check(!ag105IsReady(),
          "ag105IsReady: false when GENSTAT == 0x00 (startup)");

    // Inject: GENSTAT = 0x01 — not charging or full, not ready
    ag105_status_raw = 0x01;
    check(!ag105IsReady(),
          "ag105IsReady: false when GENSTAT == 0x01");
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
    V_batt = 7.0f; V_bus = 18.0f;
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
    V_bus = 18.0f; I_fc = 0;
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
    V_batt = 7.0f; V_bus = 18.0f; I_fc = 0;
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
    V_batt = 7.0f; V_bus = 18.0f; I_fc = 0;
    g_pin_value[FC_CHARGE_ENABLE] = HIGH;
    g_pin_value[BT_BUS_ENABLE]    = LOW;
    g_pin_value[REGEN_ENABLE]     = HIGH;
    mainState = 1;
    detectFaults();
    check(fault_flags & FAULT_SWITCH_CONFLICT,
          "detectFaults: FAULT_SWITCH_CONFLICT set when FC_CHARGE_ENABLE+REGEN_ENABLE both HIGH");

    // OV_BATT
    reset_test_state();
    V_batt = LIMIT_V_BATT_MAX + 0.1f; V_bus = 17.5f; I_fc = 0;
    mainState = 1;
    detectFaults();
    check(fault_flags & FAULT_OV_BATT,
          "detectFaults: FAULT_OV_BATT set when V_batt > LIMIT_V_BATT_MAX");
    check(error_code == ERR_OV_BATT,
          "detectFaults: error_code == ERR_OV_BATT");

    // OV_BATT threshold — just below limit → no fault
    reset_test_state();
    V_batt = LIMIT_V_BATT_MAX - 0.05f; V_bus = 17.5f; I_fc = 0;
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
    I_fc = 1.0f; V_batt = 7.0f; V_bus = 17.5f;
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
    V_fc = 12.0f;       I_fc   = 0.3f;   V_bus  = 17.5f;
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

    // PI_Controller_Motor: first call returns 0 (no dt elapsed yet)
    g_mock_micros = 0;
    float out_initial = PI_Controller_Motor(1.0f);
    check(out_initial == 0.0f,
          "PI_Controller_Motor: returns 0 on first call (no dt)");

    // After advancing time past sampleTime (50us), non-zero error produces non-zero output
    g_mock_micros = 100;   // 100 us > sampleTime=50
    float out_1 = PI_Controller_Motor(1.0f);
    check(out_1 > 0.0f,
          "PI_Controller_Motor: positive output for positive error after dt > sampleTime");

    g_mock_micros = 200;
    PI_Controller_Motor(-1.0f);   // just verifies no crash; exact value depends on accumulated integral
    check(true, "PI_Controller_Motor: runs without crash for negative error");

    // PI_Controller_Power: same structure, same behavior
    reset_test_state();
    g_mock_micros = 0;
    float pout0 = PI_Controller_Power(1.0f);
    check(pout0 == 0.0f,
          "PI_Controller_Power: returns 0 on first call (no dt)");

    g_mock_micros = 100;
    float pout1 = PI_Controller_Power(0.5f);
    check(pout1 > 0.0f,
          "PI_Controller_Power: positive output for positive error");

    // Zero error → Kp * 0 = 0; integral from prior call may add
    g_mock_micros = 200;
    PI_Controller_Power(0.0f);   // should not crash
    check(true, "PI_Controller_Power: zero error runs without crash");
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
    // V_bus. Drive it through its phases with the bus coming up (V_bus default 18V ≥ threshold).
    // The charger is unpowered in Init and doState0() no longer touches it, so a NACKing charger
    // must not matter.
    reset_test_state();
    Wire.next_endtransmission_result = 1;   // any stray I2C would NACK — must not matter
    mainState = 0;
    V_bus = 18.0f;                           // bus comes up past V_BUS_CHARGED_THRESH
    g_mock_millis = 0;

    doState0();                              // phase 0: enable bus switches
    check(mainState == 0,
          "doState0: still in Init after enabling bus switches");
    check(digitalRead(FC_BUS_ENABLE) == HIGH && digitalRead(BT_BUS_ENABLE) == HIGH,
          "doState0: bus switches enabled FIRST");
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
    V_bus = 18.0f;
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
    check(digitalRead(MOT_PWR_ENABLE) == LOW,
          "doState3: motor power cut");
}

// ─── detectFaults() Ag105 GENSTAT error-state decoding ───────────────────────
static void test_genstat_fault() {
    test_group("detectFaults() GENSTAT error states");

    struct { uint8_t raw; bool shouldFault; const char* desc; } cases[] = {
        { 0x05, true,  "GENSTAT=0x05 OC/Regulation Error → fault" },
        { 0x06, true,  "GENSTAT=0x06 Thermal Shutdown → fault" },
        { 0x07, true,  "GENSTAT=0x07 Timeout Error → fault" },
        { 0x04, false, "GENSTAT=0x04 Bring-Up Charge (normal) → NO fault" },
        { 0x02, false, "GENSTAT=0x02 Charging → NO fault" },
        { 0x0A, false, "0x0A = Charging + MPPT flag (bit3) → NO fault (mask isolates 0x07)" },
        { 0x0E, true,  "0x0E = Thermal Shutdown + MPPT flag → fault (regression vs old 0x0F mask)" },
        { 0x00, false, "0x00 = no data yet → NO fault" },
    };
    for (auto& c : cases) {
        reset_test_state();
        V_batt = 7.0f; V_bus = 18.0f; I_fc = 0; V_fc = 10.0f;
        ag105_status_raw = c.raw;
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
    V_fc = 0; V_batt = 0; V_bus = 18.0f; I_fc = 0;
    mainState = 0;
    detectFaults();
    check(!(fault_flags & FAULT_UV_FC),   "detectFaults: no UV_FC in State 0 (boot)");
    check(!(fault_flags & FAULT_UV_BATT), "detectFaults: no UV_BATT in State 0 (boot)");
    check(mainState == 0,                 "detectFaults: no boot-lock to State 99 in State 0");

    // State 1 (Idle) likewise exempt.
    reset_test_state();
    V_fc = 0; V_batt = 0; V_bus = 18.0f; I_fc = 0;
    mainState = 1;
    detectFaults();
    check(mainState == 1, "detectFaults: no UV boot-lock in State 1 (Idle)");

    // State 2 (Run): UV checks are armed.
    reset_test_state();
    V_fc = LIMIT_V_FC_MIN - 0.1f; V_batt = 7.0f; V_bus = 18.0f; I_fc = 0;
    mainState = 2;
    detectFaults();
    check(fault_flags & FAULT_UV_FC, "detectFaults: UV_FC fires in State 2 (Run)");

    reset_test_state();
    V_fc = 10.0f; V_batt = LIMIT_V_BATT_MIN - 0.1f; V_bus = 18.0f; I_fc = 0;
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

    // Re-power + settle → reconfigures (2 more writes).
    make_charger_powered_settled();
    Wire.rx_queue.push(0x02);
    Wire.rx_queue.push(50);
    pollAg105();
    check(ag105Configured, "pollAg105: reconfigured after re-power");
    check(Wire.write_log.size() == 4, "pollAg105: config re-written on re-power (2 + 2)");
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

    // Once the charger reports ready, MPPT releases (FC path stays open).
    ag105_status_raw = AG105_GENSTAT_CHARGING;
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
    test_dostate3_leaves_bus_energized();
    test_genstat_fault();
    test_uv_boot_gate();
    test_pollag105_state_gate();
    test_charger_has_power();
    test_pollag105_unpowered_never_faults();
    test_pollag105_settle_window_suppresses_fault();
    test_lazy_config_on_power();
    test_config_resets_on_power_loss();
    test_charging_control_fc_bootstrap();
    test_state98_drive_cycle_runs_controls();
    test_motor_pi_antiwindup();
    test_wheelspeed_reset();
#endif

    printf("\n===================================\n");
    printf("Results: %d passed, %d failed\n", g_tests_passed, g_tests_failed);
    return (g_tests_failed > 0) ? 1 : 0;
}

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
 */

#include <VescUart.h>
#include <SPI.h>
#include <Wire.h>
#include <NativeEthernet.h>
#include <NativeEthernetUdp.h>

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
#define SCALE_I  (ADC_VREF / ADC_MAX / K_sns)   // 12-bit, Vref=3.3V → ~2.015 mA/count

// ── Fault bitmask constants (uint16_t) ────────────────────────────────────────
#define FAULT_OC_FC           0x0001  // I_fc overcurrent
#define FAULT_UV_BATT         0x0002  // V_batt undervoltage
#define FAULT_OV_BUS          0x0004  // V_bus overvoltage
#define FAULT_SWITCH_CONFLICT 0x0008  // FC_CHARGE_ENABLE asserted while BT_BUS or REGEN high
#define FAULT_PI_TIMEOUT      0x0010  // Pi watchdog expired
#define FAULT_OV_BATT         0x0020  // V_batt overvoltage (charging protection)
#define FAULT_UV_FC           0x0040  // V_fc undervoltage / fuel cell depleted
#define FAULT_OC_BT           0x0080  // I_batt overcurrent (BT boost path)
#define FAULT_UV_BUS          0x0100  // V_bus undervoltage during Run (motor stall / source loss)
#define FAULT_OV_RGN          0x0200  // V_rgn overvoltage spike (regen node)
#define FAULT_OV_CHG          0x0400  // V_chg charger input overvoltage
#define FAULT_I2C_CHARGER     0x0800  // Ag105 I2C comms failure
#define FAULT_CHARGER_STAT    0x1000  // Ag105 GENSTAT error condition
#define FAULT_INIT_FAIL       0x2000  // Init sequence failure (State 0)
// bit 14 reserved
#define FAULT_ERROR           0x8000  // Latched: system is in or has entered State 99

// ── Safety limits ─────────────────────────────────────────────────────────────
#define LIMIT_I_FC_MAX   3.5f   // A — H-20 max; Source: H-20 datasheet
#define LIMIT_V_BATT_MIN 6.2f   // V — 2S LiPo cutoff (2 × 3.1V)
// Source: user-confirmed: 17.5V nominal bus; TPS61288 HW OVP triggers at 19V
#define LIMIT_V_BUS_MAX  18.5f  // V — 1V SW margin below 19V HW OVP
#define LIMIT_V_BATT_MAX  8.6f  // V — 2S LiPo max (4.3V/cell × 2 + 0.2V margin)
#define LIMIT_V_FC_MIN    6.0f  // V — H-20 minimum
#define LIMIT_I_BT_MAX    6.0f  // A — INA253A1, BT boost path
#define LIMIT_V_BUS_MIN  12.0f  // V — minimum VBUS during State 2
#define LIMIT_V_RGN_MAX  28.0f  // V — regen node spike ceiling
#define LIMIT_V_CHG_MAX  24.0f  // V — charger input max

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

// ── Physical constants ────────────────────────────────────────────────────────
const int CPR = 16;
const int MDAC_res = 4095;          // AD5443 12-bit; TODO(verify: ad5426_5432_5443.pdf §resolution)
const int32_t sampleTime = 50;      // us

const float tireRadius     = 1;     // inch
const float flyWheelRadius = 1;     // inch
// INA253 variant mixup: the BOM calls for INA253A1IPWR (100 mV/A = 0.1 V/A), but the A3
// variant (400 mV/A) was the intended choice for easier droop scaling. The board is already
// built with A1 parts, so K_sns = 0.1 V/A is used. Update to 0.4 if the board is re-spun
// with INA253A3IPWR. Source: INA253A1IPWR.pdf Device Comparison Table.
const float K_sns = 0.1f;           // V/A — INA253A1 gain (A3 = 0.4 V/A; see note above)
const float A_v   = 5.02f;          // static gain
const float k_eq  = 0.45f;          // ohm

const float motorConstant = 0.1f;   // TODO: tune this
const float MOTOR_I_CMD_MAX = 30.0f;   // A — VESC motor current command ceiling; TODO(calibrate)
                                       // Sets the motor PI integrator anti-windup bound.

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
float V_bus             = 18.0f;
float V_chg             = 0;   // charger input voltage (pin 38, ADC)
float V_rgn             = 0;   // regen-node voltage    (pin 39, ADC)

float power_share_actual    = 0;
float droop_gain_FC_actual  = 0;
float droop_gain_BT_actual  = 0;

uint8_t  ag105_status_raw  = 0;        // last raw Table 6 status byte; cached at 50 Hz by pollAg105()
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
volatile int  lastEncoderPos = 0;
volatile byte pinA_read      = 0;
volatile byte pinB_read      = 0;
constexpr float ENCODER_COUNTS_PER_REV = 1024.0f;
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
#ifndef BENCH_TEST
#define BENCH_TEST 1
#endif

// ── Network config ────────────────────────────────────────────────────────────
// Set to 0 for bench testing without Ethernet/Pi (USB-serial only); 1 for normal
// operation. When 0, setup() skips Ethernet/UDP init and the UDP functions no-op.
// Calling Udp.* without Udp.begin() hard-faults the Teensy into a reboot loop, so
// the networkUp guard below must gate every UDP access.
#define USE_ETHERNET 0

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
void motorControl();
void powerBalance();
void chargingControl();
float PI_Controller_Motor(float error);
float PI_Controller_Power(float error);
void setDroopMdac(float fc_gain, float bt_gain);
void assertFcChargeEnable(bool enable);
void safeAllSwitches();
void printTestStatus();
void advanceDriveCycle();

// ═════════════════════════════════════════════════════════════════════════════
// SETUP
// ═════════════════════════════════════════════════════════════════════════════
void setup() {
    Serial.begin(115200);
    Serial1.begin(115200);

    // Teensy 4.1 ADC: select 12-bit resolution before any analogRead
    analogReadResolution(12);

    initEscUartPins();
    initMdacSpiPins();
    initChargerI2cPins();

    pinMode(RX,      INPUT);
    pinMode(TX,      OUTPUT);
    pinMode(ENC_A,   INPUT);
    pinMode(ENC_B,   INPUT);
    pinMode(ENC_ENABLE,    OUTPUT);
    pinMode(FC_REG_ENABLE, OUTPUT);
    pinMode(BT_REG_ENABLE, OUTPUT);
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
    digitalWrite(BT_REG_ENABLE, HIGH);
    digitalWrite(FC_REG_ENABLE, HIGH);
    digitalWrite(ENC_ENABLE,    LOW);

    attachInterrupt(digitalPinToInterrupt(ENC_A), doEncoderA, CHANGE);
    attachInterrupt(digitalPinToInterrupt(ENC_B), doEncoderB, CHANGE);

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
    Serial.print("v_actual=");           Serial.print(v_actual, 3);    Serial.println(" m/s");
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
    P_fc_actual   = V_fc   * I_fc;
    P_batt_actual = V_batt * I_batt;
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
    // Mirrors the existing FAULT_UV_BUS State-2 gate. Source: boot-lock review.
    if (mainState == 2 && V_batt < LIMIT_V_BATT_MIN) triggerFault(FAULT_UV_BATT, ERR_UV_BATT);
#endif
    if (V_bus  > LIMIT_V_BUS_MAX)  triggerFault(FAULT_OV_BUS,  ERR_OV_BUS);

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
    // UV_FC gated to Run (State 2) for the same boot-ramp reason as UV_BATT above.
    if (mainState == 2 && V_fc < LIMIT_V_FC_MIN) triggerFault(FAULT_UV_FC, ERR_UV_FC);
    if (I_batt > LIMIT_I_BT_MAX)    triggerFault(FAULT_OC_BT,   ERR_OC_BT);

    // Bus UV only meaningful during State 2 (run); low bus during idle/shutdown is normal
    if (mainState == 2 && V_bus < LIMIT_V_BUS_MIN)
        triggerFault(FAULT_UV_BUS, ERR_UV_BUS);
#endif

    if (V_rgn > LIMIT_V_RGN_MAX)    triggerFault(FAULT_OV_RGN, ERR_OV_RGN);
    if (V_chg > LIMIT_V_CHG_MAX)    triggerFault(FAULT_OV_CHG, ERR_OV_CHG);

#if !BENCH_TEST
    // Ag105 GENSTAT occupies bits [2:0] ONLY — bit 3 is the MPPT EN/DIS flag, not GENSTAT,
    // so the mask must be 0x07 (matching ag105IsReady()), not 0x0F. Error states per Table 6:
    //   0x05 = OC/Regulation Error, 0x06 = Thermal Shutdown, 0x07 = Timeout Error.
    // 0x04 (Bring-Up Charge) is a NORMAL transient for a deeply-discharged pack and must NOT
    // fault. ag105_status_raw is refreshed at 50 Hz by pollAg105(); 0x00 = no data yet (ignore).
    // Source: Ag105_Table6_I2C_Status_Byte.json
    uint8_t genstat = ag105_status_raw & 0x07;
    if (ag105_status_raw != 0 &&
        (genstat == 0x05 || genstat == 0x06 || genstat == 0x07))
        triggerFault(FAULT_CHARGER_STAT, ERR_CHARGER_STAT);
#endif

    if (fault_flags) {
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
        Serial.println("Checksum mismatch — packet dropped");
        return;
    }

    int idx = 1;

    uint32_t timestamp;
    memcpy(&timestamp, &buffer[idx], 4); idx += 4;

    uint16_t pkt_counter_Pi;
    memcpy(&pkt_counter_Pi, &buffer[idx], 2); idx += 2;

    memcpy(&v_setpoint,           &buffer[idx], 4); idx += 4;
    memcpy(&power_share_setpoint, &buffer[idx], 4); idx += 4;
    memcpy(&charge_goal,          &buffer[idx], 4); idx += 4;

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
void doState0() {
    // 1. FC/BT boost regulators are already HIGH from setup() — confirm
    digitalWrite(FC_REG_ENABLE, HIGH);
    digitalWrite(BT_REG_ENABLE, HIGH);

    // 2. Path switches are all LOW from setup() — leave them LOW during init

    // 3. Bring battery-pack sequencing switch HIGH once system is powered
    // Must be OFF at boot; turn ON here after regulators have started.
    digitalWrite(BT_SEQUENCE_ENABLE, HIGH);   // battery pack now sequenced in

    // 4. Init MDAC droop outputs
    initMdacOutputs();

    // 5. Charger config is NOT done here. The Ag105 is unpowered in Init (no charger power
    // path is open), so it cannot ACK I2C — configuring it here would always fail. Instead,
    // pollAg105() lazily configures it the first time it is powered + settled (see §3/§5).
    ag105Configured = false;

    // 6. Init VESC
    initEsc();

    digitalWrite(CS_MDAC_FC, HIGH);
    digitalWrite(CS_MDAC_BT, HIGH);
    digitalWrite(ENC_ENABLE, HIGH);

    Serial.println("State 0 -> State 1 (IDLE)");
    mainState = 1;
}

void doState1() {
    // IDLE — belt-and-suspenders: ensure motor and regen paths are OFF
    vesc.setCurrent(0);
    digitalWrite(MOT_PWR_ENABLE, LOW);
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
        mainState = 2;
    }
}

void doState2() {
    // RUN — FC and motor paths are on for the whole state (idempotent every tick).
    // BT_BUS_ENABLE is NOT set here: chargingControl() owns it so that it and
    // FC_CHARGE_ENABLE never fight on the same tick. chargingControl() drives
    // BT_BUS_ENABLE HIGH in all non-FC-charge paths and lets assertFcChargeEnable(true)
    // pull it LOW (with the required settling delay) before opening the FC→charger path.
    digitalWrite(FC_BUS_ENABLE, HIGH);    // FC regulator → VBUS always on in Run
    digitalWrite(MOT_PWR_ENABLE, HIGH);   // VBUS → VESC/motor always on in Run

    chargingControl();   // power path state committed before motor/droop outputs change
    motorControl();
    powerBalance();

    if (changeToFin) {
        changeToFin = false;
        Serial.println("State 2 -> State 3 (FINISH)");
        mainState = 3;
    }
}

void doState3() {
    // FINISH — two-phase safe shutdown; back-feed hazard ordering applies.
    // The two energy sources (VBUS caps and motor/drivetrain) cannot be bled simultaneously
    // because FC_CHARGE_ENABLE and REGEN_ENABLE are mutually exclusive — done sequentially.
    //
    // Implemented as a NON-BLOCKING phase machine: the old blocking delay(10) calls froze the
    // main loop, so updateSensors()/detectFaults() were blind during the highest-energy drain
    // windows. Returning between phases keeps fault detection live the whole way down.
    // The 10 ms inter-phase timing is preserved exactly.
    // Note: `phase` is self-resetting to 0 on normal completion below. If a fault interrupts the
    // sequence mid-way, control latches in State 99 and the board is only ever recovered by a
    // power cycle (which re-inits this static), so a stale non-zero `phase` is not reachable.
    static uint8_t  phase      = 0;
    static uint32_t phaseStart = 0;

    switch (phase) {
        case 0:
            // Phase 1: Bleed remaining VBUS capacitor energy into the charger.
            // Cut incoming regulator feeds first; MOT_PWR_ENABLE stays HIGH so the motor
            // load also helps drain the caps. BT_BUS/REGEN now LOW → guard passes cleanly.
            vesc.setCurrent(0);
            digitalWrite(FC_BUS_ENABLE, LOW);    // disconnect FC regulator from VBUS
            digitalWrite(BT_BUS_ENABLE, LOW);    // disconnect BT regulator from VBUS
            assertFcChargeEnable(true);          // drain remaining VBUS cap energy into Ag105
            phaseStart = millis();
            phase = 1;
            break;
        case 1:
            if (millis() - phaseStart < 10) break;   // TODO(calibrate): VBUS capacitor drain time
            // Phase 2: Bleed motor / drivetrain regen energy.
            // FC_CHARGE must close before REGEN can open (mutual-exclusion rule).
            assertFcChargeEnable(false);         // close FC→charger path
            digitalWrite(REGEN_ENABLE, HIGH);    // open regen → charger path
            digitalWrite(MOT_PWR_ENABLE, LOW);   // cut motor from VBUS; regen bleeds through REGEN
            phaseStart = millis();
            phase = 2;
            break;
        case 2:
            if (millis() - phaseStart < 10) break;   // TODO(calibrate): regen current decay time
            digitalWrite(REGEN_ENABLE, LOW);     // close regen path
            digitalWrite(MPPT_DISABLE, LOW);     // inhibit MPPT (active-LOW: LOW = inhibit)
            // Clear the wheel-speed averaging buffers so the next run starts fresh (drive cycles
            // are short, but stale timestamps from this run would corrupt the first velocity samples).
            wheelSpeedResetPending = true;
            Serial.println("State 3 -> State 1 (IDLE)");
            phase = 0;                           // reset for next entry into Finish
            mainState = 1;
            break;
    }
}

void doState99() {
    // ERROR — two-phase safe shutdown; latched until power cycle.
    // Same Phase 1→2 ordering as State 3 (bleed VBUS caps, then bleed regen/motor energy)
    // before disabling boost regulators. A disabled TPS61288 has a body-diode passthrough;
    // all regen paths must be closed before the boosts are disabled.
    // Non-blocking phase machine (same back-feed ordering as State 3). The old delay(10)
    // calls blinded detectFaults() during the drain windows; returning between phases keeps
    // fault sampling live. phase 3 = fully latched (nothing further until power cycle).
    static uint8_t  phase      = 0;
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

    switch (phase) {
        case 0:
            vesc.setCurrent(0);
            // Phase 1: Bleed VBUS capacitor energy into charger
            digitalWrite(FC_BUS_ENABLE, LOW);    // disconnect FC regulator from VBUS
            digitalWrite(BT_BUS_ENABLE, LOW);    // disconnect BT regulator from VBUS
            assertFcChargeEnable(true);          // drain remaining VBUS cap energy into Ag105
            phaseStart = millis();
            phase = 1;
            break;
        case 1:
            if (millis() - phaseStart < 10) break;   // TODO(calibrate): VBUS capacitor drain time
            // Phase 2: Bleed motor / regen energy
            assertFcChargeEnable(false);         // close FC→charger path (required before REGEN HIGH)
            digitalWrite(REGEN_ENABLE, HIGH);    // open regen → charger path
            digitalWrite(MOT_PWR_ENABLE, LOW);   // cut motor from VBUS; regen bleeds through REGEN
            phaseStart = millis();
            phase = 2;
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
            phase = 3;
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
//   D — start/stop drive cycle      S — print status snapshot
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
    Serial.println("  1 - toggle FC_BUS_ENABLE     2 - toggle BT_BUS_ENABLE");
    Serial.println("  3 - toggle MOT_PWR_ENABLE    4 - toggle REGEN_ENABLE");
    Serial.println("  5 - toggle FC_CHARGE_ENABLE  6 - toggle BT_SEQUENCE_ENABLE");
    Serial.println("  C - toggle CBAL_DISABLE      M - toggle MPPT_DISABLE");
    Serial.println("  D - start/stop drive cycle   S - print status snapshot");
    Serial.println("  I - scan I2C bus             H - show this command list");
    Serial.println("  Q - exit -> State 1 (MOT_PWR_ENABLE forced LOW)");
    Serial.println("==============================");
}

void doState98() {
    if (Serial.available()) {
        char cmd = (char)Serial.read();
        int  pin;
        bool cur;

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
                pin = FC_BUS_ENABLE; cur = digitalRead(pin);
                digitalWrite(pin, !cur);
                Serial.print("FC_BUS_ENABLE -> "); Serial.println(!cur);
                break;
            case '2':
                pin = BT_BUS_ENABLE; cur = digitalRead(pin);
                digitalWrite(pin, !cur);
                Serial.print("BT_BUS_ENABLE -> "); Serial.println(!cur);
                break;
            case '3':
                pin = MOT_PWR_ENABLE; cur = digitalRead(pin);
                digitalWrite(pin, !cur);
                Serial.print("MOT_PWR_ENABLE -> "); Serial.println(!cur);
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
                    if (!digitalRead(MOT_PWR_ENABLE)) {
                        Serial.println("ERROR: MOT_PWR_ENABLE must be HIGH before starting drive cycle (key '3')");
                    } else {
                        driveCycleActive     = true;
                        driveCyclePhaseIdx   = 0;
                        driveCyclePhaseStart = millis();
                        driveCycleStatusLast = millis();
                        Serial.println("[DC] Drive cycle started — Phase 0: Standstill");
                    }
                } else {
                    driveCycleActive = false;
                    v_setpoint = 0.0f;
                    // Drive cycle now drives the VESC (motorControl runs while active), so the
                    // control block won't execute next tick — flush a zero command immediately
                    // or the motor keeps spinning at the last commanded current.
                    current = 0.0f;
                    vesc.setCurrent(0);
                    safeAllSwitches();   // park path switches so a mid-phase stop leaves nothing latched
                    Serial.println("[DC] Drive cycle stopped — switches safed");
                }
                break;
            case 'S':
            case 's':
                printTestStatus();
                break;
            case 'I':
            case 'i':
                scanI2C();
                break;
            case 'H':
            case 'h':
            case '?':
                printTestHelp();
                break;
            case 'Q':
            case 'q':
                driveCycleActive = false;
                v_setpoint = 0.0f;
                current = 0.0f;
                vesc.setCurrent(0);                  // stop motor before cutting its power
                digitalWrite(MOT_PWR_ENABLE, LOW);   // forced LOW on exit (per spec)
                Serial.println("State 98 -> State 1 (IDLE)");
                mainState = 1;
                return;
            default:
                break;
        }
    }

    if (driveCycleActive) {
        // advanceDriveCycle() only supplies v_setpoint; the real Run-state control functions
        // execute unmodified so the exerciser drives the VESC, droop MDACs, and charger paths
        // exactly as State 2 would. Same call order as doState2(). (CLAUDE.md §8.)
        advanceDriveCycle();
        chargingControl();
        motorControl();
        powerBalance();
    }
}

void advanceDriveCycle() {
    if (driveCyclePhaseIdx >= DRIVE_CYCLE_PHASES) {
        v_setpoint       = 0.0f;
        driveCycleActive = false;
        Serial.println("[DC] Drive cycle complete");
        return;
    }

    uint32_t elapsed = millis() - driveCyclePhaseStart;
    const DriveCyclePhase &ph = DRIVE_CYCLE[driveCyclePhaseIdx];

    if (elapsed >= ph.durationMs) {
        driveCyclePhaseIdx++;
        driveCyclePhaseStart = millis();
        if (driveCyclePhaseIdx < DRIVE_CYCLE_PHASES) {
            Serial.print("[DC] Phase "); Serial.println(driveCyclePhaseIdx);
        }
        return;
    }

    // Linear interpolation of v_setpoint within phase
    float t = (float)elapsed / (float)ph.durationMs;
    v_setpoint = ph.v_start + t * (ph.v_end - ph.v_start);

    // Status snapshot every 500 ms
    if (millis() - driveCycleStatusLast >= 500) {
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

void printTestStatus() {
    Serial.println("=== State 98 Status ===");
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
    Serial.print("fault_flags=0x"); Serial.println(fault_flags, HEX);
    Serial.print("error_code=0x");  Serial.print(error_code, HEX);
    Serial.print(" (");             Serial.print(errorCodeStr(error_code));
    Serial.println(")");
    Serial.print("error_source_state="); Serial.println(error_source_state);
    Serial.println("=======================");
}


// ═════════════════════════════════════════════════════════════════════════════
// CONTROL FUNCTIONS
// ═════════════════════════════════════════════════════════════════════════════

// Enforces mutual-exclusion rule before asserting FC_CHARGE_ENABLE.
// BT_BUS_ENABLE and REGEN_ENABLE must be LOW before FC_CHARGE_ENABLE may go HIGH.
void assertFcChargeEnable(bool enable) {
    if (enable) {
        // Cut BT contribution to VBUS first, then close regen path, then open FC→charger path
        digitalWrite(BT_BUS_ENABLE, LOW);    // disconnect BT from VBUS before routing FC → charger
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
void safeAllSwitches() {
    assertFcChargeEnable(false);          // close FC→charger path via the guard
    digitalWrite(REGEN_ENABLE,   LOW);
    digitalWrite(BT_BUS_ENABLE,  LOW);
    digitalWrite(FC_BUS_ENABLE,  LOW);
    digitalWrite(MOT_PWR_ENABLE, LOW);
    digitalWrite(MPPT_DISABLE,   LOW);    // inhibit MPPT (active-LOW)
}

void motorControl() {
    targetMotorTorque = PI_Controller_Motor(v_setpoint - v_actual);
    current = targetMotorTorque / motorConstant;
    vesc.setCurrent(current);
}

float PI_Controller_Motor(float error) {
    const float Kp = 1.0f;
    const float Ki = 1.0f;

    uint32_t now = micros();
    uint32_t dtMicros = now - pi_motor_lastMicros;
    if (dtMicros < (uint32_t)sampleTime) return 0.0f;
    pi_motor_lastMicros = now;

    pi_motor_accum += error * dtMicros * 1e-6f;
    // Anti-windup: clamp the integrator so a sustained error (stalled setpoint, or a VESC that
    // saturates at MOTOR_I_CMD_MAX) cannot wind pi_motor_accum up without bound. The bound is the
    // torque equivalent of the motor current ceiling (output = torque; current = torque/motorConstant),
    // divided by Ki so the integral term Ki*accum stays within ±(MOTOR_I_CMD_MAX * motorConstant).
    const float integMax = (MOTOR_I_CMD_MAX * motorConstant) / Ki;
    pi_motor_accum = constrain(pi_motor_accum, -integMax, integMax);
    return Kp * error + Ki * pi_motor_accum;
}

void powerBalance() {
    float totalA = fabsf(I_fc) + fabsf(I_batt);
    if (totalA < 1e-6f) return;

    float power_share_actual_local = fabsf(I_fc) / totalA;
    float shareError = power_share_setpoint - power_share_actual_local;
    float droopRatio = PI_Controller_Power(shareError);

    droopRatio = constrain(droopRatio, 0.01f, 0.99f);

    droop_gain_FC_actual = k_eq / droopRatio           / K_sns / A_v;
    droop_gain_BT_actual = k_eq / (1.0f - droopRatio) / K_sns / A_v;
    setDroopMdac(droop_gain_FC_actual, droop_gain_BT_actual);
}

float PI_Controller_Power(float error) {
    const float Kp = 1.0f;
    const float Ki = 1.0f;

    uint32_t now = micros();
    uint32_t dtMicros = now - pi_power_lastMicros;
    if (dtMicros < (uint32_t)sampleTime) return 0.0f;
    pi_power_lastMicros = now;

    pi_power_accum += error * dtMicros * 1e-6f;
    return Kp * error + Ki * pi_power_accum;
}

void setDroopMdac(float fc_gain, float bt_gain) {
    uint16_t fcCode = (uint16_t)(constrain(fc_gain, 0.0f, 1.0f) * MDAC_res);
    uint16_t btCode = (uint16_t)(constrain(bt_gain, 0.0f, 1.0f) * MDAC_res);

    // TODO(verify: ad5426_5432_5443.pdf §SPI interface) — SPI_MODE0, MSBFIRST, 16-bit words
    SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));
    digitalWrite(CS_MDAC_FC, LOW);
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
        digitalWrite(BT_BUS_ENABLE, HIGH); // BT contributes to VBUS when not FC-charging
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
        digitalWrite(BT_BUS_ENABLE, HIGH);   // BT continues contributing to VBUS during regen
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
bool initAg105Charger() {
    // Power-on defaults: reg 0x00 = 0x00 (ext-resistor mode → no RCS → 1000mA),
    //                    reg 0x01 = 0x00 (ext-resistor mode → no RVS → 4.2V / 1S).
    // Write explicit 2.5A current and 2S/8.4V voltage configs before any charging is allowed.

    // Set charge current to 2.5A (highest profile)
    // Source: Ag105_Table7_I2C_Parameters.json field 0x00; Ag105_Table4_Charge_Current_Select.json
    Wire.beginTransmission(AG105_ADDR);
    Wire.write(AG105_REG_ICHG_CFG);
    Wire.write(AG105_VAL_2500MA);   // 0x01 = 2.5A; termination at 250mA (C/10)
    if (Wire.endTransmission() != 0) return false;

    // Set battery voltage to 2S / 8.4V (100% capacity profile)
    // Source: Ag105_Table3_Charge_Voltage_Select.json — i2c_field_value 8 = 8.4V
    Wire.beginTransmission(AG105_ADDR);
    Wire.write(AG105_REG_VBATT_CFG);
    Wire.write(AG105_VAL_2S);       // 0x08
    if (Wire.endTransmission() != 0) return false;

    return true;
}

void pollAg105() {
    // Power-aware service: tracks when the charger has input power, lazily configures it once
    // it has booted, polls measured current/status, and faults only when the charger genuinely
    // should be responding. Called at ~50 Hz from loop() in every state.
    bool powered = chargerHasPower();
    if (powered && !ag105HadPower) ag105PowerOnMs = millis();  // power edge → start settle timer
    if (!powered) ag105Configured = false;                     // re-arm config for next power session
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
        I_charge = Wire.read() * 0.011f;    // A; scale: 0.011 A/count (Table 7 field 0x06)

        // Lazy configuration: the charger is now powered, settled, and ACKing. Write the
        // 2.5A / 2S-8.4V profile once per power session (EPROM persists; re-write idempotent).
        if (settled && !ag105Configured) {
            if (initAg105Charger()) ag105Configured = true;
            else if (faultArmed)    triggerFault(FAULT_INIT_FAIL, ERR_INIT_FAIL);
        }
    } else {
        // NAK or bus error. Mark charger data stale so ag105IsReady() returns false (safe).
        // Unpowered or still-settling → not a fault (normal). Only a powered+settled charger
        // that goes silent in an operational state latches State 99.
        ag105_status_raw = 0;
        if (faultArmed)
            triggerFault(FAULT_I2C_CHARGER, ERR_I2C_CHARGER);
    }
}

inline bool ag105IsReady() {
    // Returns true when the Ag105 is actively charging or fully charged.
    uint8_t genstat = ag105_status_raw & 0x07;   // bits 0–2; Source: Ag105_Table6_I2C_Status_Byte.json
    return (genstat == AG105_GENSTAT_CHARGING || genstat == AG105_GENSTAT_FULL);
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
    setDroopMdac(k_eq / 0.5f / K_sns / A_v,
                 k_eq / 0.5f / K_sns / A_v);
}

void initEsc() {
    vesc.setCurrent(0);
}


// ═════════════════════════════════════════════════════════════════════════════
// WHEEL SPEED (encoder)
// ═════════════════════════════════════════════════════════════════════════════
void updateWheelSpeed() {
    static uint32_t lastMicros = 0;
    static int32_t  index      = 0;

    const int averagingTime = 10000;
    const int arraySize = (int)ceil((float)averagingTime / sampleTime);
    static int posArr[200]  = {0};
    static int timeArr[200] = {0};

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

    int   dt    = now - timeArr[(index + 1) % arraySize];
    float dtSec = dt * 1e-6f;
    int   dx    = pos - posArr[(index + 1) % arraySize];

    if (dtSec < 1e-6f) return;
    float flyWheelSpeedRpm = (dx / ENCODER_COUNTS_PER_REV) * (60.0f / dtSec);
    v_actual = flyWheelSpeedRpm * flyWheelRadius / 60.0f;
}


// ═════════════════════════════════════════════════════════════════════════════
// ENCODER ISRs
// ═════════════════════════════════════════════════════════════════════════════
void doEncoderA() {
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

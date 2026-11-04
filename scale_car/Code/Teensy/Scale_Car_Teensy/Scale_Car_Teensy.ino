#include <VescUart.h> //UART
#include <SPI.h> //SPI
#include <Wire.h> //I2C
#include <NativeEthernet.h>
#include <EthernetUdp.h>

VescUart vesc;
EthernetUDP Udp;

#define RX 0
#define TX 1
#define ENC_A 2
#define FC_REG_ENABLE 3
#define BT_REG_ENABLE 4
#define CHARGER_ENABLE 5
#define CHARGER_OK 6
#define ENC_ENABLE 7
#define ENC_B 8
#define MOSI 11
#define MISO 12
#define SCK 13
#define SDA 18
#define SCL 19
#define MOTOR_OUTPUT 33
#define CS_MDAC_FC 36
#define CS_MDAC_BT 37
#define CHRG_CURRENT 39
#define FC_CURRENT 40
#define BT_CURRENT 41

int mainState = 0;

const int CPR = 16;
const int MDAC_res = 4095; //MADC resolution
const int32_t sampleTime = 50;//us

const float tireRadius = 1;//inch
const float flyWheelRadius = 1;//inch
const float K_sns = 0.4; // V/A
const float A_v = 5.02; //static gain
const float k_eq = 0.45; //ohm

float v_actual = 0;//speed of the scale car wheel
float current = 0;
float targetMotorTorque = 0;
float P_fc_actual = 0;
float P_batt_actual = 0;

//parameters from Raspberry PI (ethernet changes the values)
float v_setpoint = 0; 
float power_share_setpoint = 0.5;
float charge_goal = 0;

// encoder reading flags
volatile byte AfirstUp = 0; 
volatile byte BfirstUp = 0; 
volatile byte AfirstDown = 0; 
volatile byte BfirstDown = 0; 
// CW when it increases, CCW when it decreases
volatile int encoderPos = 0; //this variable stores our current value of encoder position. 
volatile int lastEncoderPos = 0; //this variable stores our last value of encoder position. 
volatile byte pinA_read = 0; // this variable is shared among interrupts
volatile byte pinB_read = 0; // this variable is shared among interrupts
constexpr float ENCODER_COUNTS_PER_REV = 1024.0f; 

bool changeToRun = 0;
bool changeToFin = 0;

//Added 4/17
// ---- Network config (CHANGE THESE) ----
IPAddress pi_ip(192,168,1,100);
const int pi_port = 5000;
const int local_port = 5001;

// ---- Packet ----
const uint8_t SYNC_BYTE = 0xAA;
uint16_t pkt_counter_T = 0;

// ---- Signals required by packet ----
float I_fc = 0;
float I_batt = 0;
float V_fc = 0;
float V_batt = 0;
float V_bus = 12.0;   // placeholder (you must measure later)

float P_motor_actual = 0;
float power_share_actual = 0;
float power_share_echo = 0;

float droop_gain_FC_actual = 0;
float droop_gain_BT_actual = 0;

float I_charge = 0;

uint8_t charger_status = 0;
uint8_t fault_flags = 0;

// ---- Missing constants ----
const float motorConstant = 0.1;   // YOU MUST TUNE THIS
const float maxChargeCurrentA = 5.0;

void setup() {
  // put your setup code here, to run once:
  Serial.begin(115200);   // debug
  Serial1.begin(115200);  // VESC UART
  initEscUartPins();
  initMdacSpiPins();
  initBatteryChargerI2cPins();
  
  pinMode(RX, INPUT);
  pinMode(TX, OUTPUT);

  pinMode(ENC_A, INPUT);
  pinMode(ENC_B, INPUT);//_PULLUP?
  pinMode(ENC_ENABLE, OUTPUT);

  pinMode(FC_REG_ENABLE, OUTPUT);
  pinMode(BT_REG_ENABLE, OUTPUT);
  pinMode(CHARGER_ENABLE, OUTPUT);
  pinMode(CHARGER_OK, INPUT);

  pinMode(CS_MDAC_FC, OUTPUT);
  pinMode(CS_MDAC_BT, OUTPUT);

  digitalWrite(CS_MDAC_FC, HIGH);
  digitalWrite(CS_MDAC_BT, HIGH);
  digitalWrite(FC_REG_ENABLE, LOW);
  digitalWrite(BT_REG_ENABLE, LOW);
  digitalWrite(CHARGER_ENABLE, LOW);
  digitalWrite(ENC_ENABLE, LOW);

  attachInterrupt(digitalPinToInterrupt(ENC_A), doEncoderA, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_B), doEncoderB, CHANGE);

  //Added 4/17
  byte mac[] = {0xDE,0xAD,0xBE,0xEF,0xFE,0xED};
  IPAddress ip(192,168,1,50);

  Ethernet.begin(mac, ip);
  Udp.begin(local_port);
}

void initMdacSpiPins() {
  // MDAC bus on custom SPI pins.
  SPI.setMOSI(PIN_MOSI);
  SPI.setMISO(PIN_MISO);
  SPI.setSCK(PIN_SCK);
  SPI.begin();
  pinMode(CS_MDAC_FC, OUTPUT);
  pinMode(CS_MDAC_BT, OUTPUT);
  digitalWrite(CS_MDAC_FC, HIGH);
  digitalWrite(CS_MDAC_BT, HIGH);
}

void initBatteryChargerI2cPins() {
  // Battery charger control/status over I2C.
  Wire.setSDA(PIN_SDA);
  Wire.setSCL(PIN_SCL);
  Wire.begin();
}

void initEscUartPins() {
  // ESC/VESC on UART1 using RX/TX pins.
  Serial1.setRX(RX);
  Serial1.setTX(TX);
  Serial1.begin(115200);
  vesc.setSerialPort(&Serial1);
}


void loop() {
  // put your main code here, to run repeatedly:
  //Added 4/17
  updateSensors();
  computeDerivedSignals();

  receiveCommands();   // Pi → Teensy

  switch (mainState){
    //Initialize
    case 0:
      doState0();
      break;
    //IDLE
    case 1:
      doState1();
      break;
    //Run
    case 2:
      doState2();
      break;
    //Finishing
    case 3:
      doState3();
      break;
    //Error state
    case 99:
    default:
      doState99();
      break;
    //invalid state goes to error state
  }
  
  //Added 4/17
  // send at ~50 Hz
  static uint32_t lastSend = 0;
  if (millis() - lastSend > 20) {
    sendTelemetry();
    lastSend = millis();
  }
}

void updateWheelSpeed() {
  static uint32_t lastMicros = 0;
  static int32_t lastPos = 0;
  static int32_t index = 0;
  
  //const int32_t sampleTime = 50; //us
  const int averagingTime = 10000; //us
  const int arraySize = ceil(averagingTime / sampleTime);
  static int posArr[arraySize] = {0};
  static int timeArr[arraySize] = {0};

  uint32_t now = micros();
  uint32_t dtMicros = now - lastMicros;
  if (dtMicros < sampleTime) return; // update every >= sampleTime
  lastMicros = now;

  noInterrupts();
  int32_t pos = encoderPos;
  interrupts();

  posArr[index] = pos;
  timeArr[index] = now;
  if (index<arraySize-1) index++;
  else index = 0;

  int dt = now - timeArr[(index + 1) % arraySize];
  float dtSec = dt * 1e-6f;
  int dx = pos - posArr[(index + 1) % arraySize];

  float flyWheelSpeedRpm = (dx / ENCODER_COUNTS_PER_REV) * (60.0f / dtSec);
  v_actual = flyWheelSpeedRpm * flyWheelRadius / 60; //inch/s
}

//Added 4/17
void updateSensors() {
  updateWheelSpeed();

  I_fc = analogRead(FC_CURRENT);
  I_batt = analogRead(BT_CURRENT);

  // Placeholder voltages (replace with real sensors later)
  V_fc = 12.0;
  V_batt = 12.0;

  // Charger current (placeholder)
  I_charge = analogRead(CHRG_CURRENT);
}

void computeDerivedSignals() {
  float totalA = fabsf(I_fc) + fabsf(I_batt);

  if (totalA > 1e-6) {
    power_share_actual = fabsf(I_fc) / totalA;
  }
  //not used?
  P_fc_actual = V_fc * I_fc;
  P_batt_actual = V_batt * I_batt;

  P_motor_actual = V_bus * current;
  power_share_echo = power_share_setpoint;
}

void receiveCommands() {
  int packetSize = Udp.parsePacket();
  if (packetSize != 22) return;

  uint8_t buffer[22];
  Udp.read(buffer, 22);

  if (buffer[0] != SYNC_BYTE) return; //Pi header is 0XBB - Sid

  uint8_t checksum = 0;
  for (int i = 1; i < 21; i++) checksum ^= buffer[i]; // checksum loop goes i < 21 and checks against buffer[21]. But the Pi packet is 22 bytes — header is byte 0, checksum is byte 21, data is bytes 1-20. The XOR should skip byte 0 (header) and byte 21 (checksum): sid
  if (checksum != buffer[21]) return;

  int idx = 1;

  uint32_t timestamp;
  memcpy(&timestamp, &buffer[idx], 4); idx += 4;

  uint16_t pkt_counter_Pi;
  memcpy(&pkt_counter_Pi, &buffer[idx], 2); idx += 2;

  memcpy(&v_setpoint, &buffer[idx], 4); idx += 4;
  memcpy(&power_share_setpoint, &buffer[idx], 4); idx += 4;
  memcpy(&charge_goal, &buffer[idx], 4); idx += 4;

  uint8_t mode_cmd = buffer[idx++];
  uint8_t droop_enable = buffer[idx++];
}


//Initialization State
void doState0(){
  digitalWrite(FC_REG_ENABLE, HIGH);
  digitalWrite(BT_REG_ENABLE, HIGH);

  initMdacOutputs();
  initBatteryCharger();
  initEsc();

  digitalWrite(CS_MDAC_FC, HIGH);
  digitalWrite(CS_MDAC_BT, HIGH);
  digitalWrite(ENC_ENABLE, HIGH);
  mainState = 1;
}

void initMdacOutputs() {
  // Safe startup: zero droop injection until EMS sends a command.
  setDroopMdac(k_eq / 0.5 / K_sns / A_v, k_eq / 0.5 / K_sns / A_v);
}

void initBatteryCharger() {
  // Safe startup: charger disabled until an explicit charge request is received.
  digitalWrite(CHARGER_ENABLE, LOW);
}

void initEsc() {
  // Safe startup for motor controller.
  vesc.setCurrent(current);
}


//IDLE State
void doState1(){
  vesc.setCurrent(current);
  if (changeToRun) {
        mainState = 2;
      }
}

//Run State
void doState2(){
  //motor control
  motorControl();
  //power balance
  powerBalance();
  //charging control
  chargingControl();
  if (changeToFin) {
        mainState = 3;
      }
}

void motorControl(){
  //UART,encoder
  //Input: v_setpoint, v_actual
  targetMotorTorque = PI_Controller_Motor(v_setpoint - v_actual);
  current = targetMotorTorque / motorConstant;
  vesc.setCurrent(current);
}
//Output: setCurrent(targetMotorTorque/motor constant)

float PI_Controller_Motor(float error){
  float e = error;
  const float Kp = 1;
  const float Ki = 1;
  static float accumulatedError = 0;
  static uint32_t lastMicros = 0;
  //const int32_t sampleTime = 50; //us

  uint32_t now = micros();
  uint32_t dtMicros = now - lastMicros;
  if (dtMicros < sampleTime) return; // update every >=50 us
  lastMicros = now;
  accumulatedError += e * dtMicros * 1e-6;
  float torque = Kp * e + Ki * accumulatedError;

  return torque;
}

void powerBalance(){
//input: 
  float fcCurrentA = analogRead(FC_CURRENT);
  float btCurrentA = analogRead(BT_CURRENT);
  float totalA = fabsf(fcCurrentA) + fabsf(btCurrentA);
//Added 4/17
  if (totalA < 1e-6) return;
  float power_share_actual = fabsf(fcCurrentA) / totalA;     // 0..1
  float shareError = power_share_setpoint - power_share_actual;

  float droopRatio = PI_Controller_Power(shareError);

  float droop_gain_FC_actual = k_eq / droopRatio / K_sns / A_v;
  float droop_gain_BT_actual = k_eq / (1 - droopRatio) / K_sns / A_v;
  setDroopMdac(droop_gain_FC_actual, droop_gain_BT_actual);
}

float PI_Controller_Power(float error){
  float e = error;
  const float Kp = 1;
  const float Ki = 1;
  //const int32_t sampleTime = 50; //us
  static float accumulatedError = 0;
  static uint32_t lastMicros = 0;

  uint32_t now = micros();
  uint32_t dtMicros = now - lastMicros;
  if (dtMicros < sampleTime) return; // update every >=50 us
  lastMicros = now;
  accumulatedError += e * dtMicros * 1e-6;
  float torque = Kp * e + Ki * accumulatedError;

  return torque;
}

void setDroopMdac(float droop_gain_FC_actual, float droop_gain_BT_actual) {
  uint16_t fcCode = static_cast<uint16_t>(constrain(droop_gain_FC_actual, 0.0f, 1.0f) * MDAC_res);
  uint16_t btCode = static_cast<uint16_t>(constrain(droop_gain_BT_actual, 0.0f, 1.0f) * MDAC_res);

  SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));

  digitalWrite(CS_MDAC_FC, LOW);
  SPI.transfer16(fcCode);
  digitalWrite(CS_MDAC_FC, HIGH);

  digitalWrite(CS_MDAC_BT, LOW);
  SPI.transfer16(btCode);
  digitalWrite(CS_MDAC_BT, HIGH);

  SPI.endTransaction();
}

void chargingControl(){
  bool chargerReady = (digitalRead(CHARGER_OK) == HIGH);

  if (charge_goal <= 0.05f) {
    digitalWrite(CHARGER_ENABLE, LOW);
    setChargerTargetCurrentA(0.0f);
    return;
  }

  float cmdA = constrain(charge_goal, 0.0f, maxChargeCurrentA);

  if (chargerReady) {
    digitalWrite(CHARGER_ENABLE, HIGH);
    setChargerTargetCurrentA(cmdA);
  } else {
    digitalWrite(CHARGER_ENABLE, LOW);
    setChargerTargetCurrentA(0.0f);
  }
}

//Finishing State
void doState3(){
  vesc.setCurrent(current);
  digitalWrite(CHARGER_ENABLE, LOW);
  mainState = 1;
}

//Error State
void doState99(){
  vesc.setCurrent(current);
  digitalWrite(FC_REG_ENABLE, LOW);
  digitalWrite(BT_REG_ENABLE, LOW);
  digitalWrite(CHARGER_ENABLE, LOW);
}

//Added 4/17
void sendTelemetry() {
  uint8_t packet[54];
  int idx = 0;

  packet[idx++] = SYNC_BYTE;

  uint32_t t = millis();
  memcpy(&packet[idx], &t, 4); idx += 4;

  memcpy(&packet[idx], &pkt_counter_T, 2); idx += 2;

  memcpy(&packet[idx], &v_actual, 4); idx += 4;
  memcpy(&packet[idx], &V_batt, 4); idx += 4;
  memcpy(&packet[idx], &I_batt, 4); idx += 4;
  memcpy(&packet[idx], &I_charge, 4); idx += 4;

  memcpy(&packet[idx], &V_fc, 4); idx += 4;
  memcpy(&packet[idx], &I_fc, 4); idx += 4;

  memcpy(&packet[idx], &V_bus, 4); idx += 4;
  memcpy(&packet[idx], &P_motor_actual, 4); idx += 4;

  memcpy(&packet[idx], &power_share_echo, 4); idx += 4;
  memcpy(&packet[idx], &power_share_actual, 4); idx += 4;

  uint16_t fc_u16 = (uint16_t)(droop_gain_FC_actual * 65535);
  uint16_t bt_u16 = (uint16_t)(droop_gain_BT_actual * 65535);

  memcpy(&packet[idx], &fc_u16, 2); idx += 2;
  memcpy(&packet[idx], &bt_u16, 2); idx += 2;

  packet[idx++] = charger_status;
  packet[idx++] = fault_flags;

  uint8_t checksum = 0;
  for (int i = 0; i < 53; i++) checksum ^= packet[i];
  packet[idx++] = checksum;

  Udp.beginPacket(pi_ip, pi_port);
  Udp.write(packet, 54);
  Udp.endPacket();

  pkt_counter_T++;
}


// ISR for encoder reading: Channel A
void doEncoderA(){
  pinA_read = digitalRead(ENC_A);
  pinB_read = digitalRead(ENC_B);
  // for rising edge
  //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
  if((pinA_read==1) && (pinB_read==1) && BfirstUp) { 
    encoderPos --; //decrement the encoder's position count
    AfirstUp = 0; //reset flags for the next turn
    BfirstUp = 0; //reset flags for the next turn
  }
  // Direction sensing
  else if ((pinA_read==1) && (pinB_read==0)) AfirstUp = 1; 

  // for falling edge
  //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
  if((pinA_read==0) && (pinB_read==0) && BfirstDown) { 
    encoderPos --; //decrement the encoder's position count
    AfirstDown = 0; //reset flags for the next turn
    BfirstDown = 0; //reset flags for the next turn
  }
  // Direction sensing
  else if ((pinA_read==0) && (pinB_read==1)) AfirstDown = 1; 
}
// ISR for encoder reading: Channel B
void doEncoderB(){
  // reading = PIND & 0xC; //read all eight pin values then strip away all but pinA and pinB's values
  pinA_read = digitalRead(ENC_A);
  pinB_read = digitalRead(ENC_B);
  if ((pinA_read==1) && (pinB_read==1) && AfirstUp) { //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
    encoderPos ++; //increment the encoder's position count
    AfirstUp = 0; //reset flags for the next turn
    BfirstUp = 0; //reset flags for the next turn
  }
  // Direction sensing
  else if ((pinA_read==0) && (pinB_read==1)) BfirstUp = 1; 

  // for falling edge
    //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
  if((pinA_read==0) && (pinB_read==0) && AfirstDown) { 
    encoderPos ++; //decrement the encoder's position count
    AfirstDown = 0; //reset flags for the next turn
    BfirstDown = 0; //reset flags for the next turn
  }
  // Direction sensing
  else if ((pinA_read==1) && (pinB_read==0)) BfirstDown = 1; 
}

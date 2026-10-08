// Elberr servo bridge for Wemos D1 R2 (ESP8266) + PCA9685.
// Role: low-level servo driver behind a newline-JSON serial protocol.
// The Pi (brain) sends joint targets; this board owns PWM, limits,
// speed, timeout-hold and e-stop latching. It NEVER plans motion.
//
// Libraries (Arduino IDE Library Manager):
//   Adafruit PWM Servo Driver, ArduinoJson v6 (NOT v7)
// Board: LOLIN(WEMOS) D1 R2 & mini. Serial: 115200 8N1.
//
// Protocol (Pi <-> Wemos, one JSON object per line, 115200 baud):
//   Pi -> Wemos:
//     {"ping":123}                    -> {"pong":123}
//     {"enable":true}                 -> DISABLED/READY -> ACTIVE
//     {"enable":false}                -> ACTIVE -> DISABLED (PWM off)
//     {"estop":true}                  -> ANY -> EMERGENCY_STOP (latched, PWM off)
//     {"reset":true}                  -> EMERGENCY_STOP -> DISABLED
//     {"joints":{"left_elbow_pitch":1.57,"head_pan":0.2}}  (radians, ACTIVE only)
//   Wemos -> Pi (2 Hz status + replies):
//     {"state":"ACTIVE","positions":{"left_elbow_pitch":1.56,...},"t_ms":12345}
//     {"error":"unknown joint foo"}   (non-fatal, stays ACTIVE)
//
// Safety (mirrors spec section 26, scoped to this board):
//   BOOT -> DISABLED -> READY -> ACTIVE; fault -> FAULT; estop -> EMERGENCY_STOP.
//   No valid message for 500 ms in ACTIVE -> hold last PWM, state FAULT
//   (any valid message recovers to ACTIVE). Boot never drives servos.
//   On-board LED (D4, active low): slow blink DISABLED, solid ACTIVE,
//   fast blink FAULT/EMERGENCY_STOP.

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <ArduinoJson.h>

// ---- pins (Wemos D1 R2 labels) ----
#define PIN_SDA D2          // GPIO4, default ESP8266 SDA
#define PIN_SCL D1          // GPIO5, default ESP8266 SCL
#define PIN_OE  D5          // GPIO14 -> PCA9685 OE (active low). 10k pull-up
                            // to 3V3 so outputs stay OFF until we drive LOW.
#define PIN_LED D4          // built-in LED, active low (status)

#define PWM_FREQ_HZ 50
#define CMD_TIMEOUT_MS 500
#define STATUS_MS 500

struct Joint {
  const char *name;
  uint8_t channel;
  float jmin, jmax;     // joint range, radians (config/joints.yaml)
  float init;           // start pose, radians
  float minDeg, maxDeg; // servo range, degrees (config/servos.yaml)
  int pwmMinUs, pwmMaxUs;
  bool reverse;
  float maxSpeedRadS;
  float pos;            // current (estimated), radians
  float target;         // commanded, radians
};

Joint joints[] = {
  {"left_elbow_pitch",  0, 0.17, 2.97, 1.57, 10.0, 170.0,  500, 2500, false, 1.047f, 1.57, 1.57},
  {"right_elbow_pitch", 1, 0.17, 2.97, 1.57, 10.0, 170.0,  500, 2500, true,  1.047f, 1.57, 1.57},
  {"head_pan",          2, -1.40, 1.40, 0.0, 10.0, 170.0,  500, 2500, false, 1.571f, 0.0,  0.0},
};
const int NJOINTS = sizeof(joints) / sizeof(joints[0]);

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

enum State { ST_BOOT, ST_DISABLED, ST_READY, ST_ACTIVE, ST_FAULT, ST_ESTOP };
State state = ST_BOOT;
const char *stateName[] = {"BOOT", "DISABLED", "READY", "ACTIVE", "FAULT", "EMERGENCY_STOP"};

unsigned long lastMsgMs = 0;
unsigned long lastStatusMs = 0;
unsigned long lastLedMs = 0;
bool ledOn = false;
String line;

Joint *findJoint(const char *name) {
  for (int i = 0; i < NJOINTS; i++)
    if (strcmp(joints[i].name, name) == 0) return &joints[i];
  return nullptr;
}

int radToUs(Joint *j, float rad) {
  float frac = (rad - j->jmin) / (j->jmax - j->jmin);
  frac = constrain(frac, 0.0f, 1.0f);
  if (j->reverse) frac = 1.0f - frac;
  float deg = j->minDeg + frac * (j->maxDeg - j->minDeg);
  return (int)(j->pwmMinUs + (deg - j->minDeg) / (j->maxDeg - j->minDeg) * (j->pwmMaxUs - j->pwmMinUs));
}

void pwmOffAll() {
  for (int i = 0; i < NJOINTS; i++)
    pwm.setPWM(joints[i].channel, 0, 4096);  // full off
}

void driveJoint(Joint *j) {
  int us = radToUs(j, j->pos);
  // 50 Hz: 20 ms period, 12-bit over 4096 ticks
  int ticks = (int)((float)us / 20000.0f * 4096.0f);
  pwm.setPWM(j->channel, 0, ticks);
}

void sendStatus() {
  StaticJsonDocument<256> doc;
  doc["state"] = stateName[state];
  JsonObject p = doc.createNestedObject("positions");
  for (int i = 0; i < NJOINTS; i++) p[joints[i].name] = joints[i].pos;
  doc["t_ms"] = millis();
  serializeJson(doc, Serial);
  Serial.println();
}

void sendError(const String &msg) {
  StaticJsonDocument<128> doc;
  doc["error"] = msg;
  serializeJson(doc, Serial);
  Serial.println();
}

void handleLine(const String &s) {
  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, s)) {
    sendError("bad json");
    return;
  }
  lastMsgMs = millis();

  if (doc.containsKey("ping")) {
    StaticJsonDocument<64> r;
    r["pong"] = doc["ping"];
    serializeJson(r, Serial);
    Serial.println();
    return;
  }
  if (doc.containsKey("estop") && doc["estop"].as<bool>()) {
    state = ST_ESTOP;
    digitalWrite(PIN_OE, HIGH);  // outputs off
    pwmOffAll();
    sendStatus();
    return;
  }
  if (doc.containsKey("reset") && doc["reset"].as<bool>()) {
    if (state == ST_ESTOP) state = ST_DISABLED;
    sendStatus();
    return;
  }
  if (doc.containsKey("enable")) {
    bool en = doc["enable"].as<bool>();
    if (en && (state == ST_DISABLED || state == ST_READY || state == ST_FAULT)) {
      state = ST_READY;
      // snap targets to current (no jump), then go ACTIVE
      for (int i = 0; i < NJOINTS; i++) joints[i].target = joints[i].pos;
      digitalWrite(PIN_OE, LOW);  // outputs on
      state = ST_ACTIVE;
    } else if (!en && state != ST_ESTOP) {
      state = ST_DISABLED;
      digitalWrite(PIN_OE, HIGH);
      pwmOffAll();
    }
    sendStatus();
    return;
  }
  if (doc.containsKey("joints")) {
    if (state == ST_FAULT) state = ST_ACTIVE;  // fresh command recovers
    if (state != ST_ACTIVE) {
      sendError("not active");
      return;
    }
    JsonObject j = doc["joints"].as<JsonObject>();
    for (JsonPair kv : j) {
      Joint *jt = findJoint(kv.key().c_str());
      if (!jt) {
        sendError(String("unknown joint ") + kv.key().c_str());
        continue;
      }
      float v = constrain(kv.value().as<float>(), jt->jmin, jt->jmax);
      jt->target = v;
    }
    return;
  }
  sendError("unknown command");
}

void setup() {
  pinMode(PIN_OE, OUTPUT);
  digitalWrite(PIN_OE, HIGH);  // outputs OFF until explicitly enabled
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);  // LED off (active low)
  Serial.begin(115200);
  Wire.begin(PIN_SDA, PIN_SCL);
  pwm.begin();
  pwm.setPWMFreq(PWM_FREQ_HZ);
  pwmOffAll();
  for (int i = 0; i < NJOINTS; i++) {
    joints[i].pos = joints[i].init;
    joints[i].target = joints[i].init;
  }
  state = ST_DISABLED;
  lastMsgMs = millis();
  StaticJsonDocument<128> boot;
  boot["boot"] = "elberr-servo-bridge";
  boot["state"] = stateName[state];
  serializeJson(boot, Serial);
  Serial.println();
}

void loop() {
  unsigned long now = millis();

  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      line.trim();
      if (line.length()) handleLine(line);
      line = "";
    } else if (c != '\r' && line.length() < 480) {
      line += c;
    }
  }

  // command timeout -> hold, FAULT (recoverable by next valid message)
  if (state == ST_ACTIVE && (now - lastMsgMs) > CMD_TIMEOUT_MS) {
    state = ST_FAULT;
    sendStatus();
  }

  // speed-limited motion toward target (ACTIVE only)
  if (state == ST_ACTIVE) {
    const float dt = 0.02f;  // ~50 Hz loop target
    for (int i = 0; i < NJOINTS; i++) {
      Joint *j = &joints[i];
      float err = j->target - j->pos;
      float step = j->maxSpeedRadS * dt;
      if (err > step) err = step;
      else if (err < -step) err = -step;
      if (err != 0.0f) {
        j->pos += err;
        driveJoint(j);
      }
    }
  }

  if (now - lastStatusMs >= STATUS_MS) {
    lastStatusMs = now;
    sendStatus();
  }

  // status LED: solid ACTIVE, slow blink DISABLED/READY, fast FAULT/ESTOP
  unsigned long blinkMs = (state == ST_ACTIVE) ? 0
    : ((state == ST_FAULT || state == ST_ESTOP) ? 120 : 600);
  if (blinkMs == 0) {
    digitalWrite(PIN_LED, LOW);
  } else if (now - lastLedMs >= blinkMs) {
    lastLedMs = now;
    ledOn = !ledOn;
    digitalWrite(PIN_LED, ledOn ? LOW : HIGH);
  }

  delay(5);
}

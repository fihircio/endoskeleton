# Wiring plan — Pi / Wemos / PCA9685 / servos / sensors (spec §64)

Canonical reference. Measure and update `mount_xyz_rpy` in `config/*.yaml` after physical build.

## 1. Network (spec §4)

```text
Ethernet Switch
 ├── Pi #1 (control)   — static e.g. 192.168.0.11
 ├── Pi #2 (vision)    — static e.g. 192.168.0.12
 └── Hokuyo UST-10LX   — static e.g. 192.168.0.10 (see config/lidar.yaml, env LIDAR_IP)
Pi Zero — Wi-Fi initially (no critical path).
```

Use known/static addressing so `lidar.launch.py` and vision bridge never depend on DHCP order.

## 2. Power — SEPARATE DOMAINS (§59)

* **Logic 5V:** Pi #1 + Pi #2 via official/regulated 5V 3–4A supplies. Pi Zero via regulated 5V 2.5A.
* **Servo power:** dedicated regulated 5–6V supply sized for stall current (MG995 stall ≈ 1.2A each; budget ≥5A for 3 servos + headroom). **Never power servos from Pi 5V rail.**
* **Common ground:** tie servo PSU GND ↔ PCA9685 GND ↔ Pi GND at ONE star point.
* **Fusing:** inline fuse on servo PSU (+) rated just above expected draw; fuse on each Pi feed per supply spec.
* **E-stop / disconnect:** physical series disconnect (switch or e-stop button) on servo PSU (+) BEFORE the PCA9685 V+ terminal. Software e-stop (`/servo/estop`) disables PWM, but the physical disconnect is the authority. Label it.
* **Power-up order:** logic first → verify `DISABLED` state → servo power on → `/servo/enable` → slow move to initial.

## 3. I²C bus (Pi #1 → PCA9685 + IMU)

Pi #1 GPIO header:

| Pi pin | Signal | To |
|---|---|---|
| 1 (3V3) | — | IMU VCC **only if IMU is 3.3V-tolerant/logic**; else use 5V per breakout spec |
| 2/4 (5V) | 5V | PCA9685 VCC (logic). **V+ terminal ← servo PSU, separate.** |
| 6/9/14/20/25/30/34/39 | GND | Star GND |
| 3 (GPIO2/SDA1) | I2C SDA | PCA9685 SDA + IMU SDA (bus) |
| 5 (GPIO3/SCL1) | I2C SCL | PCA9685 SCL + IMU SCL (bus) |

Addresses (see `config/servos.yaml`, `config/imu.yaml`):

| Device | Address | Notes |
|---|---|---|
| PCA9685 #1 | `0x40` | V1 servos (ch 0–2). No solder jumpers. |
| PCA9685 #2 | `0x41` | Future joints. Solder A0 jumper. Verify with `i2cdetect -y 1`. |
| BNO085/086 | `0x4A` (alt `0x4B`) | Confirm ADR jumper; rigid torso mount. |

Pull-ups: rely on Pi internal + breakout pull-ups; add 4k7 only if bus is flaky. Keep I²C leads short (<30cm ideal), twisted GND pair. Enable via `raspi-config` / `dtparam=i2c_arm=on`.

PWM: 50Hz (`pwm_freq_hz: 50` in servos.yaml). Pulse mapping per-servo `pwm_min/max_us` — calibrate, don't copy blindly.

## 4. Servo channels (PCA9685 #1, addr 0x40)

| Channel | Joint (`config/joints.yaml`) | Servo | Notes |
|---|---|---|---|
| 0 | `left_elbow_pitch` | MG995 #1 | `reverse: false` (verify) |
| 1 | `right_elbow_pitch` | MG995 #2 | `reverse: true` mirrored (verify) |
| 2 | `head_pan` | DS3109MG | Verify exact model current/torque |
| 3–15 | — | — | Reserved; leave unpopulated or disconnected |

PCA9685 #2 (0x41) ch 0–15: reserved for future joints. Do not connect V1 servos there.

28BYJ-48 stepper: **not a PCA9685 servo** — needs ULN2003 driver + GPIOs; camera/neck experiments only, never leg/hip/knee.

## 5. Sensors

* **Hokuyo UST-10LX:** Ethernet to switch; 12/24V per datasheet (separate supply, fused). `frame_id: lidar_link`, child of `torso_link`. Record mount offset in `config/lidar.yaml`.
* **BNO085/086:** I²C as above; `imu_link` child of `torso_link`; mount rigidly, axes photo + note in build log.
* **OV5642 ×4:** to Pi #2 / Pi Zero via Arducam shields (app code uses abstract `Camera Driver` interface only, §18). Stereo pair baseline ~60mm; record in `config/cameras.yaml`.

## 6. Wemos D1 R2 (aux I/O only — never primary controller)

* USB 5V or regulated 5V → 3.3V onboard. GPIOs 3.3V only — level-shift any 5V inputs.
* Suggested: D5/D6 limit switches (NO → GND, INPUT_PULLUP), D7 e-stop sense (mirrors physical disconnect state), D8 status LED + buzzer via NPN.
* Talks to Pi #1 over Wi-Fi/MQTT or USB-serial ROS bridge (decide at Milestone 9; keep out of safety-critical path).

## 7. Bring-up checklist (Milestones 0–4)

```bash
# Pi #1
i2cdetect -y 1            # expect 0x40, 0x41, 0x4A
ping 192.168.0.10         # Hokuyo
ros2 launch humanoid_bringup simulation.launch.py   # no HW needed
ros2 launch humanoid_bringup hardware.launch.py     # requires servo power + e-stop closed
ros2 service call /servo/enable std_srvs/srv/Trigger
ros2 topic pub /joint_commands humanoid_msgs/msg/JointCommand "{joint_names: [head_pan], positions: [0.0]}"  # small moves first
```

If anything moves on boot before enable → cut servo power, bug is critical (§12).

Absolutely. Below is a **Codex-ready V1 engineering specification**. I’ve written it as an implementation document rather than a conceptual discussion, so Codex can use it as the starting repository specification.

You can save it as `HUMANOID_V1_SPEC.md`.

# HUMANOID V1

## Engineering, Electronics, Sensor & Software Specification

**Project:** DIY Humanoid Robot V1
**Version:** 1.0
**Purpose:** Build a modular upper-body humanoid robotics platform using currently available hardware, with architecture suitable for future expansion into a full humanoid.

---

# 1. PROJECT OBJECTIVE

Build a working humanoid upper-body prototype capable of:

1. Reading LiDAR data.
2. Reading camera data.
3. Reading IMU orientation.
4. Controlling hobby servos.
5. Maintaining a unified robot state.
6. Representing the robot using URDF.
7. Running forward and inverse kinematics.
8. Detecting and tracking objects.
9. Sending high-level movement commands to joints.
10. Providing a foundation for future:

    * hands
    * force sensors
    * BLDC actuators
    * legs
    * balance
    * walking
    * AI/VLA control.

The V1 MUST be modular.

Do not design the software around temporary hobby-servo hardware.

---

# 2. CURRENT HARDWARE INVENTORY

The following hardware is already available.

## 2.1 LiDAR

### Hokuyo UST-10LX

Primary function:

* 2D environmental perception
* obstacle detection
* mapping
* localization
* navigation experiments

Interface:

* Ethernet

The Hokuyo is an environmental sensor and MUST NOT be treated as a replacement for RGB/depth vision.

---

# 2.2 Computers

## Raspberry Pi 4 #1

Role:

### ROBOT CONTROL COMPUTER

Responsibilities:

* ROS 2
* robot state
* joint states
* TF
* LiDAR processing
* IMU processing
* motion planning
* kinematics
* hardware interface
* safety state
* command routing

This is the primary robot computer.

---

## Raspberry Pi 4 #2

Role:

### VISION COMPUTER

Responsibilities:

* camera acquisition
* OpenCV
* image processing
* stereo experiments
* object detection
* object tracking
* future AI/VLA experimentation

Pi #2 communicates with Pi #1 through Ethernet.

Do not tightly couple the vision software to the robot-control software.

---

## Raspberry Pi Zero

Role:

### AUXILIARY CAMERA/PERIPHERAL COMPUTER

Initial role:

* experimental head camera interface
* optional camera preprocessing
* optional sensor node

The Pi Zero MUST NOT be responsible for primary robot control.

---

# 2.3 Microcontroller

## Wemos D1 R2

Use as:

### LOW-LEVEL I/O NODE

Possible responsibilities:

* limit switches
* buttons
* LEDs
* simple sensors
* servo experiments
* auxiliary peripherals

Do not use the Wemos as the primary humanoid controller.

Future architecture should move high-performance joints toward dedicated CAN/CAN-FD motor controllers.

---

# 2.4 Servo Controllers

## PCA9685 #1

16-channel, 12-bit PWM controller.

## PCA9685 #2

16-channel, 12-bit PWM controller.

Use these for V1 hobby-servo experiments.

They are temporary actuator interfaces.

They do NOT provide genuine joint position feedback.

---

# 2.5 Current Actuators

Available:

* DS3109MG servo ×1
* Tower Pro MG995 servo ×2
* 28BYJ-48 5 V stepper ×1

Initial allocation:

```text
MG995 #1     Left elbow
MG995 #2     Right elbow
DS3109MG     Neck pan
28BYJ-48     Experimental camera/neck mechanism
```

Do not use the 28BYJ-48 as a humanoid leg/hip/knee actuator.

Do not assume the DS3109MG torque/current specifications without verifying the exact physical model.

---

# 2.6 Cameras

Available:

### Arducam Mini Module Camera Shield 5 MP Plus OV5642 ×4

Use initially for:

* stereo-camera experimentation
* head vision
* object tracking
* palm/hand camera experiments

The camera integration MUST be isolated behind a camera interface.

Do not allow application code to depend directly on Arducam-specific APIs.

---

# 2.7 IMU

Recommended purchase:

### BNO085 or BNO086 breakout

Primary purpose:

* orientation
* accelerometer
* gyroscope
* magnetometer
* quaternion orientation
* torso state estimation

Mount physically rigidly to the torso.

Initial software MUST support quaternion orientation.

---

# 3. V1 ROBOT ARCHITECTURE

Overall architecture:

```text
                         HUMANOID V1
                              |
                    +---------+---------+
                    |       HEAD        |
                    |                   |
                    | Camera L/R        |
                    | Pi Zero optional  |
                    +---------+---------+
                              |
                            NECK
                              |
               +--------------+--------------+
               |             TORSO           |
               |                             |
               |         BNO085/086         |
               |                             |
               |       Raspberry Pi 4 #1     |
               |                             |
               |        Power / Network      |
               +--------------+--------------+
                              |
                            PELVIS
                       +------+------+
                       |             |
                    ARM-L          ARM-R
```

LiDAR:

```text
                 HOKUYO UST-10LX
                        |
                    Ethernet
                        |
                        v
                Raspberry Pi #1
```

Vision:

```text
OV5642 cameras
      |
      v
Raspberry Pi #2
      |
   Ethernet
      |
      v
Raspberry Pi #1
```

Servo control:

```text
Raspberry Pi #1
       |
      I2C
       |
  +----+----+
  |         |
PCA9685 #1 PCA9685 #2
  |         |
servos     future
```

---

# 4. NETWORK ARCHITECTURE

Use Ethernet as the primary robot communication network.

Recommended:

```text
                   Ethernet Switch
                         |
          +--------------+--------------+
          |              |              |
       Pi #1          Pi #2          Hokuyo
       CONTROL        VISION          LiDAR
```

Pi Zero may use Wi-Fi initially.

Future architecture:

```text
Pi #1
 |
 +--- Ethernet --- Pi #2
 |
 +--- Ethernet --- Hokuyo
 |
 +--- CAN ---------- Actuators
 |
 +--- I2C ---------- IMU/PCA9685
```

---

# 5. SOFTWARE STACK

Recommended:

* Linux
* ROS 2
* Python
* C++
* OpenCV
* NumPy
* TF2
* URDF
* RViz
* ros2_control where appropriate
* MoveIt 2 later
* Gazebo/Ignition or another ROS-compatible simulator later

Do not introduce unnecessary frameworks during V1.

---

# 6. ROS 2 PACKAGE STRUCTURE

Create a ROS 2 workspace:

```text
humanoid_ws/
```

Suggested package structure:

```text
humanoid_ws/
└── src/
    ├── humanoid_description/
    ├── humanoid_bringup/
    ├── humanoid_hardware/
    ├── humanoid_msgs/
    ├── humanoid_lidar/
    ├── humanoid_imu/
    ├── humanoid_servo/
    ├── humanoid_vision/
    ├── humanoid_kinematics/
    ├── humanoid_state/
    ├── humanoid_safety/
    ├── humanoid_tools/
    └── humanoid_sim/
```

---

# 7. PACKAGE RESPONSIBILITIES

## humanoid_description

Contains:

* URDF/Xacro
* robot dimensions
* joint definitions
* link definitions
* visual meshes
* collision meshes
* inertial parameters
* sensor mounting positions

Example:

```text
humanoid_description/
├── urdf/
│   ├── humanoid.urdf.xacro
│   ├── materials.xacro
│   ├── sensors.xacro
│   ├── torso.xacro
│   ├── head.xacro
│   ├── left_arm.xacro
│   └── right_arm.xacro
├── meshes/
└── config/
```

---

# 8. V1 ROBOT DOF

Initial target:

## Head

```text
head_pan
head_tilt
```

2 DOF.

## Left arm

```text
left_shoulder_pitch
left_shoulder_roll
left_shoulder_yaw
left_elbow_pitch
left_wrist_pitch
left_wrist_yaw
```

6 DOF.

## Right arm

```text
right_shoulder_pitch
right_shoulder_roll
right_shoulder_yaw
right_elbow_pitch
right_wrist_pitch
right_wrist_yaw
```

6 DOF.

## Torso

Initially:

```text
torso_yaw
torso_pitch
```

2 DOF.

Target:

```text
TOTAL = 16 DOF
```

Not every DOF needs a physical actuator during the first hardware milestone.

---

# 9. PHYSICAL V1 ACTUATION

Initially implement only:

```text
left_elbow
right_elbow
head_pan
```

with available servos.

The remaining joints exist in URDF and simulation but can be marked:

```text
SIMULATED
```

until additional actuators are purchased.

This allows software development to continue without waiting for hardware.

---

# 10. SERVO CONTROL

Create:

```text
humanoid_servo
```

Responsibilities:

* PCA9685 initialization
* PWM generation
* servo angle mapping
* calibration
* soft limits
* command timeout
* emergency stop state
* servo state publishing

Interface:

```text
/joint_commands
/joint_states
/servo_status
```

Example command:

```text
left_elbow_pitch = 45 degrees
```

The servo node converts:

```text
joint angle
     |
     v
servo angle
     |
     v
PWM pulse
```

---

# 11. SERVO CALIBRATION

Each servo MUST have configurable calibration.

Example:

```yaml
left_elbow_pitch:
  channel: 0
  min_angle: 10
  max_angle: 170
  center_angle: 90
  reverse: false
  pwm_min: 500
  pwm_max: 2500
```

Do not hard-code servo calibration inside Python/C++ source.

Store it in YAML.

---

# 12. IMPORTANT SERVO SAFETY

The software MUST implement:

### Position limits

```text
MIN_ANGLE <= COMMAND <= MAX_ANGLE
```

### Command timeout

If commands stop arriving:

```text
STOP / HOLD / SAFE POSITION
```

### Startup behavior

Servos MUST NOT immediately jump to arbitrary positions when the system starts.

Startup sequence:

```text
POWER ON
   |
   v
READ CONFIG
   |
   v
READ JOINT STATE
   |
   v
WAIT FOR ENABLE
   |
   v
MOVE SLOWLY TO INITIAL POSITION
```

---

# 13. IMU PACKAGE

Create:

```text
humanoid_imu
```

Publish:

```text
/imu/data
/imu/orientation
```

Recommended ROS message:

```text
sensor_msgs/Imu
```

Orientation should use quaternion representation.

Do not convert everything to Euler angles internally.

Euler angles may be used for:

* debugging
* UI
* logging

but quaternion should remain the primary orientation representation.

---

# 14. IMU FRAME

Define:

```text
imu_link
```

as a child of:

```text
torso_link
```

Example:

```text
base_link
   |
   v
pelvis_link
   |
   v
torso_link
   |
   +---- imu_link
   |
   +---- head
   |
   +---- left_arm
   |
   +---- right_arm
```

---

# 15. HOKUYO PACKAGE

Create:

```text
humanoid_lidar
```

Primary topic:

```text
/scan
```

Message:

```text
sensor_msgs/LaserScan
```

Frame:

```text
lidar_link
```

TF:

```text
torso_link
     |
     v
lidar_link
```

The LiDAR driver MUST be configurable for:

* IP address
* frame ID
* scan frequency
* range limits

Do not hard-code the Hokuyo IP.

---

# 16. HOKUYO FUNCTIONS

Initially implement:

### Function 1

Live scan.

### Function 2

Obstacle detection.

### Function 3

RViz visualization.

### Function 4

Mapping.

### Function 5

Localization.

Do not implement autonomous navigation until the basic scan and TF system works correctly.

---

# 17. CAMERA ARCHITECTURE

Pi #2 should expose camera data over ROS 2.

Initial target:

```text
/camera/left/image_raw
/camera/right/image_raw
```

If two cameras are mounted as stereo cameras:

```text
left_camera
right_camera
```

Create appropriate TF frames:

```text
head_link
   |
   +--- left_camera_link
   |
   +--- right_camera_link
```

---

# 18. CAMERA SOFTWARE LAYERS

Separate:

```text
Camera Driver
     |
     v
Image Publisher
     |
     v
Image Processing
     |
     v
Object Detection
     |
     v
Object Tracking
```

Do not combine all four layers into one script.

---

# 19. STEREO VISION

If two OV5642 cameras can be synchronously operated sufficiently for the experiment, implement:

```text
left image
     +
right image
     |
     v
stereo calibration
     |
     v
rectification
     |
     v
disparity
     |
     v
depth
```

However, do not assume the Arducam modules are hardware-synchronized.

For V1, software synchronization is acceptable for experimentation.

---

# 20. OBJECT DETECTION

Initial interface:

```text
/camera/detections
```

Each detection should contain:

```text
class
confidence
bounding_box
timestamp
```

Example:

```yaml
object:
  class: bottle
  confidence: 0.91
  x: 640
  y: 320
  width: 100
  height: 250
```

The object detection model is replaceable.

Do not hard-code one AI model into the robot architecture.

---

# 21. WORLD MODEL

Create:

```text
humanoid_state
```

The system should eventually combine:

```text
LiDAR
Camera
IMU
Joint states
```

into a unified robot state.

Conceptually:

```text
                WORLD MODEL
                     |
       +-------------+-------------+
       |             |             |
     Robot         Objects       Obstacles
     State
       |
   +---+---+
   |   |   |
 IMU joints pose
```

---

# 22. TF TREE

Initial TF:

```text
base_link
 |
 +-- pelvis_link
       |
       +-- torso_link
       |     |
       |     +-- imu_link
       |     |
       |     +-- lidar_link
       |
       +-- head_link
       |     |
       |     +-- camera_left_link
       |     |
       |     +-- camera_right_link
       |
       +-- left_shoulder_link
       |     |
       |     +-- left_upper_arm_link
       |           |
       |           +-- left_forearm_link
       |
       +-- right_shoulder_link
             |
             +-- right_upper_arm_link
                   |
                   +-- right_forearm_link
```

The TF tree MUST remain consistent.

---

# 23. ROBOT STATE ESTIMATION

Create:

```text
humanoid_state
```

Inputs:

```text
/imu/data
/joint_states
/scan
```

Outputs:

```text
/robot_state
/tf
```

Initial goal:

Estimate:

* torso orientation
* joint configuration
* robot pose
* sensor transforms

Do not attempt full dynamic state estimation in the first milestone.

---

# 24. KINEMATICS

Create:

```text
humanoid_kinematics
```

Implement:

### Forward kinematics

```text
joint angles
     |
     v
end effector pose
```

### Inverse kinematics

```text
desired hand position
        |
        v
joint angles
```

Start with the arm only.

Do not begin with whole-body IK.

---

# 25. FIRST ARM TARGET

Create a simple 6-DOF arm model:

```text
shoulder
   |
upper arm
   |
elbow
   |
forearm
   |
wrist
   |
hand
```

Test:

```text
Target:
X = 0.30 m
Y = 0.10 m
Z = 0.20 m
```

IK calculates the required joint configuration.

Then publish:

```text
/joint_commands
```

---

# 26. SAFETY PACKAGE

Create:

```text
humanoid_safety
```

States:

```text
BOOT
DISABLED
READY
ACTIVE
FAULT
EMERGENCY_STOP
```

Example:

```text
BOOT
  |
  v
DISABLED
  |
  v
READY
  |
  v
ACTIVE
```

Any serious hardware fault:

```text
ACTIVE
  |
  v
FAULT
```

Emergency stop:

```text
ANY STATE
   |
   v
EMERGENCY_STOP
```

---

# 27. SOFTWARE SHOULD NEVER ASSUME MOTOR POWER IS SAFE

The ROS system must distinguish:

```text
software_enabled
```

from:

```text
motor_power_enabled
```

This allows the computer to remain active while motors are disabled.

---

# 28. SIMULATION

Create:

```text
humanoid_sim
```

The simulated robot should use the same:

* URDF
* joint names
* joint limits
* command topics
* state topics

as the real robot.

Target architecture:

```text
                SAME ROBOT API
                     |
             +-------+-------+
             |               |
           SIM             REAL
             |               |
        simulated       PCA9685 /
        actuators       actuators
```

This is essential.

Do not create a completely separate simulation API.

---

# 29. UNITY INTEGRATION

Because Unity may later be used as a digital twin, expose robot state over:

* ROS 2
* ROS-TCP-Endpoint or equivalent
* UDP only if necessary

Unity should be able to receive:

```text
joint_states
robot_pose
object_positions
LiDAR data
```

Unity should eventually display:

```text
REAL ROBOT
    ↕
DIGITAL TWIN
```

---

# 30. DEVELOPMENT MILESTONES

## MILESTONE 0 — Computer setup

Goal:

Pi #1 boots and ROS 2 works.

Tasks:

* install OS
* configure Ethernet
* configure static/known networking
* install ROS 2
* create workspace
* create packages
* Git repository

Success:

```text
ros2 topic list
```

works.

---

# 31. MILESTONE 1 — Hokuyo

Connect:

```text
Hokuyo
   |
Ethernet
   |
Pi #1
```

Success criteria:

* Hokuyo responds
* `/scan` exists
* RViz displays scan
* `lidar_link` exists
* TF is correct

---

# 32. MILESTONE 2 — IMU

Connect BNO085/086.

Success:

```text
/imu/data
```

updates continuously.

Rotate robot torso.

RViz/debug tool shows orientation changing correctly.

---

# 33. MILESTONE 3 — PCA9685

Connect:

```text
Pi #1
 |
I2C
 |
PCA9685
 |
Servo
```

Success:

Servo moves between safe calibrated positions.

No servo should move during boot until explicitly enabled.

---

# 34. MILESTONE 4 — Three physical joints

Implement:

```text
Left elbow
Right elbow
Head pan
```

Success:

All three can be commanded independently.

Example:

```text
left_elbow = 30°
right_elbow = 60°
head_pan = 90°
```

---

# 35. MILESTONE 5 — URDF

Create complete 16-DOF upper-body model.

Even if only three joints are physical.

Success:

RViz displays the correct robot.

Joint sliders change the corresponding links.

---

# 36. MILESTONE 6 — Camera

Connect one OV5642.

Success:

```text
/camera/image_raw
```

works.

Then add second camera.

---

# 37. MILESTONE 7 — Stereo

Calibrate:

```text
camera_left
camera_right
```

Generate:

* rectified images
* disparity
* depth estimate

Do not attempt object manipulation yet.

---

# 38. MILESTONE 8 — Sensor fusion

Combine:

```text
Camera
+
LiDAR
+
IMU
```

Goal:

Detect an object and estimate its approximate position relative to the robot.

Example:

```text
Detected:
RED BOX

Estimated:
X = 0.8 m
Y = 0.2 m
Z = 0.4 m
```

---

# 39. MILESTONE 9 — ARM IK

Virtual arm first.

Input:

```text
target XYZ
```

Output:

```text
joint angles
```

Then execute with simulated joints.

Only after simulation succeeds should physical servos be enabled.

---

# 40. MILESTONE 10 — PHYSICAL ARM

Build a lightweight prototype arm.

Use current servos only for low-load experiments.

Do not attach heavy payloads.

Success:

Robot moves its arm toward predefined positions.

---

# 41. MILESTONE 11 — OBJECT REACHING

Pipeline:

```text
Camera
  |
  v
Object Detection
  |
  v
Object Position
  |
  v
IK
  |
  v
Joint Commands
  |
  v
Arm
```

Target:

Robot detects an object and moves the hand toward it.

Do NOT implement grasping yet.

---

# 42. MILESTONE 12 — GRASPING

Only after stable reaching.

Add:

* gripper
* hand servo
* object contact detection if available

Target:

```text
detect
→ reach
→ close gripper
→ lift
```

---

# 43. FUTURE ACTUATOR ARCHITECTURE

When V1 hobby servos are insufficient, replace:

```text
PCA9685
```

with:

```text
CAN/CAN-FD
```

architecture.

Future:

```text
Pi #1
   |
 CAN-FD
   |
   +--- Shoulder actuator
   |
   +--- Elbow actuator
   |
   +--- Wrist actuator
   |
   +--- Hip actuator
   |
   +--- Knee actuator
   |
   +--- Ankle actuator
```

Each actuator should eventually contain:

```text
BLDC motor
Gearbox
Absolute encoder
Current sensing
Temperature sensing
Motor controller
Optional torque sensing
```

---

# 44. FUTURE LEG ARCHITECTURE

Do NOT implement legs in V1 hardware.

Future target:

```text
LEFT LEG

hip:
  pitch
  roll
  yaw

knee:
  pitch

ankle:
  pitch
  roll
```

6 DOF per leg.

Total:

```text
12 DOF
```

for both legs.

Then full robot becomes approximately:

```text
Upper body: 16
Legs:       12
Hands:       6–10
-------------------
Total:      34–38 DOF
```

---

# 45. FUTURE BALANCE

Once legs exist:

```text
IMU
 +
joint encoders
 +
foot force sensors
       |
       v
STATE ESTIMATION
       |
       v
WHOLE BODY CONTROL
       |
       v
JOINT TORQUE
```

Walking is a separate project phase.

Do not implement walking before reliable joint-state feedback exists.

---

# 46. AI ARCHITECTURE

The eventual AI architecture should be:

```text
                 USER
                  |
           "Pick up the bottle"
                  |
                  v
             AI / VLM
                  |
                  v
            TASK PLANNER
                  |
                  v
          MOTION PLANNER
                  |
                  v
            IK / CONTROL
                  |
                  v
             ACTUATORS
```

AI MUST NOT directly output arbitrary PWM values.

The safety/control layer remains between AI and motors.

---

# 47. FUTURE VLA INTERFACE

Define a high-level command interface such as:

```text
MOVE_TO_OBJECT
LOOK_AT_OBJECT
REACH_TO
GRASP
RELEASE
WALK_TO
STOP
```

Example:

```json
{
  "command": "REACH_TO",
  "target": {
    "x": 0.45,
    "y": 0.10,
    "z": 0.25
  }
}
```

The AI layer should not know whether the robot uses:

* MG995
* BLDC
* CAN actuator
* simulated joint

That abstraction belongs to the control layer.

---

# 48. CONFIGURATION

All hardware configuration must live outside source code.

Example:

```text
config/
├── robot.yaml
├── joints.yaml
├── servos.yaml
├── cameras.yaml
├── lidar.yaml
├── imu.yaml
└── safety.yaml
```

Never hard-code:

* IP addresses
* servo limits
* PWM limits
* camera IDs
* joint limits
* calibration offsets

---

# 49. LOGGING

Every major node should support logging.

Log:

```text
timestamp
joint state
IMU
LiDAR
camera timestamp
commands
faults
servo status
```

The system should make it possible to answer:

> "What happened immediately before the robot moved incorrectly?"

---

# 50. TESTING REQUIREMENTS

Each hardware interface should have a simulation/mock mode.

Example:

```bash
ros2 launch humanoid_bringup simulation.launch.py
```

and:

```bash
ros2 launch humanoid_bringup hardware.launch.py
```

The higher-level software should work with both.

---

# 51. CODING PRINCIPLES

Use:

* Python for rapid prototyping
* C++ for performance-critical ROS nodes
* YAML for configuration
* ROS messages for communication
* Git for version control

Avoid:

* monolithic scripts
* global variables
* hard-coded calibration
* direct motor commands from AI
* hardware-specific logic inside kinematics
* unnecessary dependencies

---

# 52. GIT REPOSITORY

Recommended:

```text
humanoid-v1/
├── README.md
├── LICENSE
├── docs/
│   ├── architecture.md
│   ├── hardware.md
│   ├── wiring.md
│   ├── calibration.md
│   └── development.md
│
├── ros2_ws/
│   └── src/
│
├── firmware/
│   └── wemos/
│
├── config/
│
├── scripts/
│
├── simulation/
│
└── hardware/
    ├── electronics/
    ├── mechanical/
    └── drawings/
```

---

# 53. CODEX IMPLEMENTATION ORDER

Codex should NOT attempt to implement the entire humanoid simultaneously.

Implement in this exact order:

```text
1. Repository structure
        ↓
2. ROS 2 workspace
        ↓
3. Robot description / URDF
        ↓
4. Joint configuration
        ↓
5. Simulation
        ↓
6. Hokuyo interface
        ↓
7. IMU interface
        ↓
8. PCA9685 servo interface
        ↓
9. Wemos interface
        ↓
10. Camera interface
        ↓
11. Sensor state
        ↓
12. Kinematics
        ↓
13. Safety
        ↓
14. Physical arm
        ↓
15. Object detection
        ↓
16. Object localization
        ↓
17. Reach planning
        ↓
18. Physical reaching
```

---

# 54. FIRST CODEX TASK

Codex should initially implement ONLY:

```text
humanoid-v1/
```

with:

```text
ROS 2 workspace
humanoid_description
humanoid_bringup
humanoid_msgs
humanoid_hardware
humanoid_safety
humanoid_kinematics
```

Do NOT implement AI yet.

Do NOT implement walking yet.

Do NOT implement autonomous behavior yet.

Do NOT generate random hardware drivers if hardware documentation is unavailable.

---

# 55. FIRST ACCEPTANCE TEST

The first completed version must allow:

```bash
ros2 launch humanoid_bringup simulation.launch.py
```

to start a simulated upper-body robot.

Then:

```bash
ros2 topic list
```

should expose the robot topics.

At minimum:

```text
/joint_states
/joint_commands
/robot_state
/tf
/tf_static
```

The URDF should load successfully.

RViz should display the robot.

---

# 56. SECOND ACCEPTANCE TEST

After simulation:

```bash
ros2 launch humanoid_bringup lidar.launch.py
```

should provide:

```text
/scan
```

RViz should display the Hokuyo scan.

---

# 57. THIRD ACCEPTANCE TEST

IMU:

```text
/imu/data
```

must update continuously.

Changing torso orientation must produce corresponding quaternion changes.

---

# 58. FOURTH ACCEPTANCE TEST

Servo:

```text
ros2 service call /servo/enable
```

then:

```text
ros2 topic pub /joint_commands ...
```

should move only the requested joint.

All movement must obey configured limits.

---

# 59. HARDWARE SAFETY RULES

The system MUST assume that hobby servos can:

* move unexpectedly
* draw large current
* overheat
* strip gears
* mechanically pinch objects
* cause structural damage

Therefore:

1. Test with no load.
2. Use a separate servo power supply.
3. Use current-limited power where possible.
4. Start with low-speed movement.
5. Keep mechanical limits conservative.
6. Have a physical power disconnect.
7. Never test an unknown actuator near a person's face/body.
8. Never allow AI software to bypass the safety layer.
9. Never allow startup to cause uncontrolled movement.

---

# 60. DESIGN PHILOSOPHY

This project is NOT:

```text
Build complete humanoid immediately.
```

It IS:

```text
Build reusable robotics infrastructure
        ↓
prove perception
        ↓
prove control
        ↓
prove kinematics
        ↓
prove manipulation
        ↓
upgrade actuators
        ↓
add legs
        ↓
add balance
        ↓
add walking
        ↓
add AI/VLA
```

The V1 hardware is deliberately inexpensive.

The software architecture should NOT be inexpensive or disposable.

The software should be designed so that:

```text
MG995
  ↓
future BLDC actuator
```

can happen without rewriting:

* kinematics
* object detection
* world model
* task planning
* AI interface

---

# 61. FINAL V1 ARCHITECTURE

```text
                         USER / AI
                             |
                             v
                       TASK COMMAND
                             |
                             v
                     TASK / MOTION
                         PLANNER
                             |
                             v
                           IK
                             |
                             v
                   JOINT COMMANDS
                             |
                    +--------+--------+
                    |                 |
                 SIMULATION        HARDWARE
                    |                 |
                    |             SAFETY
                    |                 |
                    |          +------+------+
                    |          |             |
                    |       PCA9685       FUTURE CAN
                    |          |             |
                    |        SERVOS       BLDC ACTUATORS
                    |
                    v
               ROBOT STATE
                    ^
                    |
          +---------+---------+
          |         |         |
         IMU      LiDAR     JOINTS
          |         |         |
          +---------+---------+
                    ^
                    |
                 VISION
                    ^
                    |
                Pi #2
                    ^
                    |
              OV5642 CAMERAS

Main computer:
Raspberry Pi 4 #1

Vision computer:
Raspberry Pi 4 #2

Auxiliary:
Raspberry Pi Zero

Low-level prototype I/O:
Wemos D1 R2

Environmental perception:
Hokuyo UST-10LX

Orientation:
BNO085/BNO086

Servo controller:
PCA9685 ×2

Initial actuators:
MG995 ×2
DS3109MG ×1
28BYJ-48 ×1
```

---

# 62. DEFINITION OF DONE — V1

V1 is considered successful when the following demonstration works:

```text
                 PERSON
                    |
                    v
              CAMERA SYSTEM
                    |
                    v
              OBJECT DETECTION
                    |
                    v
                 Pi #2
                    |
                 Ethernet
                    |
                    v
                 Pi #1
                    |
          +---------+---------+
          |                   |
        LiDAR                IMU
          |                   |
          +---------+---------+
                    |
              WORLD MODEL
                    |
                    v
                TARGET XYZ
                    |
                    v
                   IK
                    |
                    v
             JOINT COMMAND
                    |
                    v
               SAFETY LAYER
                    |
                    v
               PCA9685
                    |
                    v
                SERVOS
                    |
                    v
              HUMANOID ARM
```

The first physical demonstration should be:

**See → locate → calculate → move arm toward target.**

Grasping, walking, balance and autonomous AI come later.

---

# 63. IMMEDIATE HARDWARE PURCHASE LIST

Before buying expensive actuators, purchase only the following core items:

### Required

* 1× BNO085/BNO086 breakout
* appropriate regulated servo power supply
* appropriate regulated Raspberry Pi power supply
* physical emergency-stop/power disconnect
* Ethernet switch
* wiring/connectors
* fuses
* servo extension cables

### Later

* RGB-D camera
* better servo/actuator
* joint encoders
* force/torque sensors
* BLDC actuator modules
* CAN interface

Do not purchase full humanoid actuators until the software and mechanical joint interface have been tested with the existing servos.

---

# 64. CODEX INSTRUCTION

Use this document as the project specification.

Prioritize:

1. Clean architecture.
2. Simulation before hardware.
3. Hardware abstraction.
4. Configuration-driven calibration.
5. ROS 2 interfaces.
6. Safety.
7. Testability.
8. Documentation.
9. Replaceable hardware.
10. Incremental implementation.

Never skip directly to AI or walking.

Every milestone must have an explicit acceptance test before moving to the next milestone.

A useful next step after Codex creates the repository is to have it produce **`hardware/wiring.md` + the actual Raspberry Pi/Wemos/PCA9685 wiring plan**, because that's where we need to be very specific about power, I²C addresses, GPIOs, servo channels, emergency stop, and the physical connections.

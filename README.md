# Humanoid V1 — DIY Upper-Body Humanoid Platform

Modular ROS 2 (Humble) upper-body humanoid. See `gpt.md` (upstream `HUMANOID_V1_SPEC.md`) for the full engineering spec.

> This directory IS `humanoid-v1/` from the spec (§52). `WIP/` = repo root.

## Architecture (spec §61)

```text
USER/AI → TASK COMMAND → PLANNER → IK → JOINT COMMANDS → SIM|HARDWARE(+SAFETY) → ROBOT STATE
                                                                                ^ IMU/LiDAR/JOINTS/VISION
```

* Control computer: Raspberry Pi 4 #1 (ROS 2, robot state, TF, LiDAR, IMU, kinematics, safety)
* Vision computer: Raspberry Pi 4 #2 (OpenCV, detection/tracking) → Ethernet → Pi #1
* Aux: Pi Zero (head camera experiments), Wemos D1 R2 (low-level I/O only)
* Sensors: Hokuyo UST-10LX (Ethernet), BNO085/086 IMU (I²C), 4× OV5642 cameras
* Actuation V1: 2× PCA9685 (I²C) → MG995 ×2 (elbows) + DS3109MG ×1 (neck pan). Rest SIMULATED.

## Repo layout (spec §52)

```text
./
├── README.md  (this file)
├── gpt.md     (upstream spec, read-only input)
├── docs/architecture.md  hardware.md  calibration.md  development.md
├── hardware/wiring.md     (canonical wiring plan — power, I²C, servo channels, e-stop)
├── config/robot.yaml joints.yaml servos.yaml lidar.yaml imu.yaml cameras.yaml safety.yaml
├── ros2_ws/src/
│   ├── humanoid_description/  (URDF/Xacro, 16-DOF)
│   ├── humanoid_bringup/      (simulation.launch.py, hardware.launch.py, …)
│   ├── humanoid_msgs/
│   ├── humanoid_hardware/     (PCA9685 abstraction, mock mode)
│   ├── humanoid_safety/       (state machine)
│   └── humanoid_kinematics/   (arm FK/IK)
├── firmware/wemos/
├── scripts/  simulation/  hardware/
├── Dockerfile  (ROS 2 Humble dev image for Mac/Docker workflow)
└── docker-compose.yml
```

## Quickstart (Mac + Docker, spec Milestone 0)

```bash
# 1. Build dev image + workspace
docker compose build
docker compose run --rm humanoid-dev bash -c "cd /ws/ros2_ws && colcon build && source install/setup.bash && ros2 launch humanoid_bringup simulation.launch.py"

# 2. In a second shell — acceptance test (§55)
docker compose run --rm humanoid-dev bash -c "source /ws/ros2_ws/install/setup.bash && ros2 topic list"
# expect: /joint_states /joint_commands /robot_state /tf /tf_static /servo_status /safety_state

# 3. Check URDF loads
docker compose run --rm humanoid-dev bash -c "source /ws/ros2_ws/install/setup.bash && ros2 run xacro xacro /ws/ros2_ws/src/humanoid_description/urdf/humanoid.urdf.xacro"
```

On Pi #1 (native, Ubuntu 22.04 + Humble): same `colcon build`, then `ros2 launch humanoid_bringup hardware.launch.py` (requires I²C + servo power — see `hardware/wiring.md`).

## Safety (spec §26–27, §59)

* States: `BOOT → DISABLED → READY → ACTIVE`, any-fault → `FAULT`, any-e-stop → `EMERGENCY_STOP`.
* `software_enabled` ≠ `motor_power_enabled`. Servos never jump on boot: read config → read state → wait enable → move slowly.
* Hobby servos can strip/overheat/pinch — separate servo PSU, current limit, conservative limits, physical disconnect. Never test near face. AI never bypasses safety.

## Status

V1 scaffold: repo + URDF (16-DOF, 3 physical + 13 simulated) + sim launch + safety + FK. Next: Hokuyo (`lidar.launch.py`), IMU, PCA9685 HW validation per milestones §31–34.

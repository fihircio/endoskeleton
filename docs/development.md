# Development — spec §§50–54

* Target: ROS 2 Humble on Ubuntu 22.04 (Pi #1). Mac dev via Docker (`Dockerfile`, `docker-compose.yml`).
* Workspace: `ros2_ws/src`. Build: `colcon build --symlink-install`.
* Packages (V1 first set, §54): `humanoid_description humanoid_bringup humanoid_msgs humanoid_hardware humanoid_safety humanoid_kinematics`.
* Every HW interface has mock/sim mode: `ros2 launch humanoid_bringup simulation.launch.py` vs `hardware.launch.py` (§50).
* Principles (§51): Python for proto, C++ for hot paths, YAML for config, ROS msgs for comms. No monoliths, no hard-coded calibration, no AI→PWM bypass.
* Order (§53): repo → workspace → URDF → joints → sim → Hokuyo → IMU → PCA9685 → Wemos → camera → state → kinematics → safety → arm → detection → localization → reach → physical reach.

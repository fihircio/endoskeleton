# Hardware inventory — spec §2

| Item | Qty | Role |
|---|---|---|
| Hokuyo UST-10LX | 1 | 2D LiDAR, Ethernet → Pi #1 |
| Raspberry Pi 4 #1 | 1 | Control computer |
| Raspberry Pi 4 #2 | 1 | Vision computer, Ethernet → Pi #1 |
| Raspberry Pi Zero | 1 | Aux head-camera experiments, Wi-Fi |
| Wemos D1 R2 | 1 | Low-level I/O only (buttons/LEDs/limits) |
| PCA9685 | 2 | #1 addr 0x40 (V1 servos), #2 addr 0x41 (future) |
| MG995 | 2 | Left/right elbow |
| DS3109MG | 1 | Neck pan (verify exact variant) |
| 28BYJ-48 5V | 1 | Camera/neck experiments only — never leg actuator |
| OV5642 5MP | 4 | Stereo head + spares/experiments |
| BNO085/086 (to buy) | 1 | Torso IMU, rigid mount, quaternion |

See `../hardware/wiring.md` for connections and `../config/*.yaml` for addresses/channels.

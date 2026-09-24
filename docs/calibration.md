# Calibration — spec §11

1. Edit `config/servos.yaml` (never source).
2. Per joint: `min/max/center_angle`, `reverse`, `pwm_min/max_us`.
3. Power servos from separate PSU, no load, slow speed. Verify direction, then set `reverse`.
4. Re-verify soft limits in `config/joints.yaml` (radians) match servo limits (degrees).
5. Log results; keep mechanical limits conservative (spec §59).

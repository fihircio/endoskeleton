# High-level joint command (spec section 10, 28). Same API for SIM and REAL.
# Angles in radians. Controller enforces soft limits + timeout + safety gate.
string[] joint_names
float64[] positions
float64[] velocities  # optional feedforward; empty = ignore
float64 duration_sec  # 0 = use per-joint max_speed; >0 = time-scaled slow move

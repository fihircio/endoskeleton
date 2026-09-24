# Architecture — spec §§3–5, 61

See `../README.md` + `gpt.md` §§3–5, 21–29, 61.

Key rule: same robot API for SIM and REAL (§28). Higher-level code (kinematics, detection, planner, AI) never knows whether a joint is MG995 / BLDC / simulated (§47).

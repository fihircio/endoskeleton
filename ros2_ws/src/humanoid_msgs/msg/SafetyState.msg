# Safety state machine (spec section 26-27).
# state: one of BOOT, DISABLED, READY, ACTIVE, FAULT, EMERGENCY_STOP
string state
bool software_enabled
bool motor_power_enabled
string reason
builtin_interfaces/Time stamp

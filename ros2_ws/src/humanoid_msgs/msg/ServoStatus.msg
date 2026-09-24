# Per-servo status from humanoid_hardware (spec section 10).
string joint_name
int32 channel
float64 commanded_rad
float64 estimated_rad  # hobby servos have no feedback — estimated from last command
bool at_limit
bool fault
builtin_interfaces/Time stamp

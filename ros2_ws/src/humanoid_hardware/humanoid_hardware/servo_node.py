"""PCA9685 servo abstraction (spec sections 10-12, 28).

Same topics as sim bridge:
  sub: /joint_commands (humanoid_msgs/JointCommand)
  pub: /joint_states (sensor_msgs/JointState) — estimated (no encoder feedback)
  pub: /servo_status (humanoid_msgs/ServoStatus) — one msg per physical joint
  sub: /safety_state — only actuate when ACTIVE (software+motor power concept, section 27)

Modes: mock (default, no I2C — for Docker/Mac) vs pca9685 (Pi, needs adafruit-pca9685).
Calibration comes from YAML, never hard-coded (section 11).
Safety: soft limits, command timeout -> HOLD, no jump on boot (section 12).
"""
import math
import os
import yaml

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from humanoid_msgs.msg import JointCommand, SafetyState, ServoStatus


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


class ServoNode(Node):
    def __init__(self):
        super().__init__('servo_node')
        self.declare_parameter('mode', 'mock')  # mock | pca9685
        self.declare_parameter('joints_config', '/ws/config/joints.yaml')
        self.declare_parameter('servos_config', '/ws/config/servos.yaml')
        mode = self.get_parameter('mode').value
        joints_path = self.get_parameter('joints_config').value
        servos_path = self.get_parameter('servos_config').value

        # Allow env override for Docker/Pi paths
        joints_path = os.path.expandvars(joints_path)
        servos_path = os.path.expandvars(servos_path)
        self.joints_cfg = load_yaml(joints_path)['joints']
        self.servos_cfg = load_yaml(servos_path)
        self.servo_cfg = self.servos_cfg['servos']
        self.timeout = float(self.servos_cfg.get('safety', {}).get('command_timeout_s', 0.5))

        self.physical = [j for j, c in self.joints_cfg.items() if c.get('mode') == 'physical']
        # current estimated positions (rad), start at initial — never jump on boot
        self.pos = {j: float(self.joints_cfg[j]['initial']) for j in self.joints_cfg}
        self.target = dict(self.pos)
        self.last_cmd_time = self.get_clock().now()
        self.safety_active = False
        self.enabled_logged = False

        self.pwm = None
        if mode == 'pca9685':
            try:
                from adafruit_pca9685 import PCA9685  # type: ignore
                import board  # type: ignore
                import busio  # type: ignore
                i2c = busio.I2C(3, 2)  # SCL, SDA (Pi I2C-1)
                self.pwm = PCA9685(i2c)
                self.pwm.frequency = 50
                self.get_logger().info('PCA9685 driver attached @50Hz')
            except Exception as e:  # never crash launch if HW missing — go to FAULT-like hold
                self.get_logger().error(f'PCA9685 init failed ({e}); holding in mock-hold mode')
                self.pwm = None
        else:
            self.get_logger().info('servo_node in MOCK mode (no I2C)')

        self.create_subscription(JointCommand, '/joint_commands', self.on_cmd, 10)
        self.create_subscription(SafetyState, '/safety_state', self.on_safety, 10)
        self.js_pub = self.create_publisher(JointState, '/joint_states', 10)
        self.status_pub = self.create_publisher(ServoStatus, '/servo_status', 10)
        self.create_timer(0.02, self.update)  # 50 Hz

    def on_safety(self, msg: SafetyState):
        self.safety_active = (msg.state == 'ACTIVE') and msg.software_enabled

    def on_cmd(self, msg: JointCommand):
        self.last_cmd_time = self.get_clock().now()
        for name, p in zip(msg.joint_names, msg.positions):
            if name not in self.joints_cfg:
                self.get_logger().warn(f'unknown joint {name}; ignoring')
                continue
            lim = self.joints_cfg[name]
            clamped = max(lim['min'], min(lim['max'], float(p)))
            if clamped != float(p):
                self.get_logger().warn(f'{name}: clamped {p:.2f} -> {clamped:.2f} (soft limit)')
            # Only physical joints drive PWM; simulated joints tracked as estimate too
            self.target[name] = clamped

    def angle_to_pwm_us(self, joint: str, rad: float) -> int:
        cfg = self.servo_cfg.get(joint)
        if cfg is None:
            return 1500
        deg = math.degrees(rad)
        # map joint rad range (from joints.yaml) onto servo deg range, then to us
        jlim = self.joints_cfg[joint]
        span_rad = jlim['max'] - jlim['min']
        frac = (rad - jlim['min']) / span_rad if span_rad > 0 else 0.5
        if cfg.get('reverse', False):
            frac = 1.0 - frac
        angle = cfg['min_angle_deg'] + frac * (cfg['max_angle_deg'] - cfg['min_angle_deg'])
        us = cfg['pwm_min_us'] + (angle - cfg['min_angle_deg']) / (
            cfg['max_angle_deg'] - cfg['min_angle_deg']) * (cfg['pwm_max_us'] - cfg['pwm_min_us'])
        return int(max(cfg['pwm_min_us'], min(cfg['pwm_max_us'], us)))

    def update(self):
        now = self.get_clock().now()
        timed_out = (now - self.last_cmd_time).nanoseconds / 1e9 > self.timeout
        # speed-limit toward target (slow moves, section 12/59)
        dt = 0.02
        for j in self.pos:
            cfg = self.servo_cfg.get(j, {})
            max_deg_s = float(cfg.get('max_speed_deg_s', 60.0))
            max_step = math.radians(max_deg_s) * dt
            if self.safety_active and not timed_out:
                err = self.target[j] - self.pos[j]
                step = max(-max_step, min(max_step, err))
                self.pos[j] += step
                if self.pwm is not None and j in self.servo_cfg:
                    us = self.angle_to_pwm_us(j, self.pos[j])
                    ch = self.servo_cfg[j]['channel'] if isinstance(self.servo_cfg[j], dict) else 0
                    # duty cycle 12-bit @50Hz: us/20000*4096
                    try:
                        self.pwm.channels[ch].duty_cycle = int(us / 20000 * 4096)
                    except Exception as e:
                        self.get_logger().warn(f'PWM write failed: {e}')
            # else: HOLD (do nothing) — timeout or not ACTIVE
        if timed_out and not getattr(self, '_timeout_logged', False):
            self.get_logger().warn('command timeout — HOLDING position')
            self._timeout_logged = True
        elif not timed_out:
            self._timeout_logged = False

        # publish estimated joint states (all joints; sim bridge does this in sim mode)
        js = JointState()
        js.header.stamp = now.to_msg()
        js.name = list(self.pos.keys())
        js.position = [self.pos[k] for k in js.name]
        self.js_pub.publish(js)
        for j in self.physical:
            st = ServoStatus()
            st.joint_name = j
            st.channel = int(self.servo_cfg.get(j, {}).get('channel', -1))
            st.commanded_rad = float(self.target.get(j, 0.0))
            st.estimated_rad = float(self.pos.get(j, 0.0))
            lim = self.joints_cfg[j]
            st.at_limit = bool(abs(self.pos[j] - lim['min']) < 1e-3 or abs(self.pos[j] - lim['max']) < 1e-3)
            st.fault = False
            st.stamp = now.to_msg()
            self.status_pub.publish(st)


def main(args=None):
    rclpy.init(args=args)
    node = ServoNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

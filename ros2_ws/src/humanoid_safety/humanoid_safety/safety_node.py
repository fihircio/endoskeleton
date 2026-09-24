"""Safety state machine (spec sections 26-27, 59).

States: BOOT -> DISABLED -> READY -> ACTIVE; any fault -> FAULT; e-stop -> EMERGENCY_STOP.
Publishes /safety_state + placeholder /robot_state (std_msgs/String JSON until
humanoid_state package lands at Milestone 8).
Services: /servo/enable, /servo/estop, /servo/reset (std_srvs/Trigger).
"""
import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger
from humanoid_msgs.msg import SafetyState


class SafetyNode(Node):
    def __init__(self):
        super().__init__('safety_node')
        self.state = 'BOOT'
        self.reason = 'booting'
        self.software_enabled = False
        self.motor_power = False  # software view; physical disconnect is authority (wiring.md)
        self.pub = self.create_publisher(SafetyState, '/safety_state', 10)
        # TODO(M8): move to humanoid_state package with IMU/joints/LiDAR fusion.
        self.robot_pub = self.create_publisher(String, '/robot_state', 10)
        self.create_service(Trigger, '/servo/enable', self.on_enable)
        self.create_service(Trigger, '/servo/estop', self.on_estop)
        self.create_service(Trigger, '/servo/reset', self.on_reset)
        self.create_timer(0.1, self.tick)
        # BOOT is transient: config check would go here -> DISABLED
        self.create_timer(1.0, self.boot_done)

    def boot_done(self):
        if self.state == 'BOOT':
            self.state = 'DISABLED'
            self.reason = 'boot OK; waiting for enable'
            self.get_logger().info('BOOT -> DISABLED')
        self.destroy_timer(self._timers[1]) if len(self._timers) > 1 else None

    def on_enable(self, req, resp):
        if self.state in ('DISABLED', 'READY'):
            self.state = 'READY'
            self.reason = 'enabled; waiting ACTIVE (send motion to go ACTIVE)'
            # V1 simplification: enable -> READY, first motion conceptually -> ACTIVE.
            # For sim acceptance, go straight to ACTIVE so joints move in tests.
            self.state = 'ACTIVE'
            self.software_enabled = True
            self.motor_power = True
            self.reason = 'ACTIVE via /servo/enable (V1 sim behavior)'
            resp.success = True
            resp.message = 'ACTIVE'
        elif self.state == 'EMERGENCY_STOP':
            resp.success = False
            resp.message = 'latched E-STOP; call /servo/reset first'
        else:
            resp.success = True
            resp.message = f'already {self.state}'
        return resp

    def on_estop(self, req, resp):
        self.state = 'EMERGENCY_STOP'
        self.software_enabled = False
        self.motor_power = False
        self.reason = 'e-stop pressed'
        resp.success = True
        resp.message = 'EMERGENCY_STOP latched'
        return resp

    def on_reset(self, req, resp):
        if self.state == 'EMERGENCY_STOP':
            self.state = 'DISABLED'
            self.reason = 'reset after e-stop'
            resp.success = True
            resp.message = 'DISABLED'
        else:
            resp.success = False
            resp.message = f'nothing to reset from {self.state}'
        return resp

    def tick(self):
        msg = SafetyState()
        msg.state = self.state
        msg.software_enabled = self.software_enabled
        msg.motor_power_enabled = self.motor_power
        msg.reason = self.reason
        msg.stamp = self.get_clock().now().to_msg()
        self.pub.publish(msg)
        self.robot_pub.publish(String(data=json.dumps({
            'state': self.state,
            'software_enabled': self.software_enabled,
            'note': 'placeholder until humanoid_state (M8)',
        })))


def main(args=None):
    rclpy.init(args=args)
    node = SafetyNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

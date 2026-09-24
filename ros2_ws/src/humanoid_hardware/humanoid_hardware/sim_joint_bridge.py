"""Sim actuator bridge (spec section 28): SAME topics as real hardware.

  sub: /joint_commands -> ideal motion toward target
  pub: /joint_states for all 16 joints

Used by simulation.launch.py so higher-level code never knows sim vs real.
"""
import os
import yaml

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from humanoid_msgs.msg import JointCommand


class SimJointBridge(Node):
    def __init__(self):
        super().__init__('sim_joint_bridge')
        self.declare_parameter('joints_config', '/ws/config/joints.yaml')
        path = os.path.expandvars(self.get_parameter('joints_config').value)
        with open(path) as f:
            self.joints = yaml.safe_load(f)['joints']
        self.pos = {j: float(c['initial']) for j, c in self.joints.items()}
        self.target = dict(self.pos)
        self.create_subscription(JointCommand, '/joint_commands', self.on_cmd, 10)
        self.pub = self.create_publisher(JointState, '/joint_states', 10)
        self.create_timer(0.02, self.update)

    def on_cmd(self, msg: JointCommand):
        for name, p in zip(msg.joint_names, msg.positions):
            if name not in self.joints:
                self.get_logger().warn(f'unknown joint {name}')
                continue
            lim = self.joints[name]
            self.target[name] = max(lim['min'], min(lim['max'], float(p)))

    def update(self):
        dt = 0.02
        for j in self.pos:
            err = self.target[j] - self.pos[j]
            step = max(-2.0 * dt, min(2.0 * dt, err))  # sim moves faster than hobby servos
            self.pos[j] += step
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = list(self.pos.keys())
        js.position = [self.pos[k] for k in js.name]
        self.pub.publish(js)


def main(args=None):
    rclpy.init(args=args)
    node = SimJointBridge()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

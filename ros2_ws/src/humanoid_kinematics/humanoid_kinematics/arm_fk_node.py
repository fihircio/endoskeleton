"""Arm forward kinematics, arm only (spec sections 24-25).

Subscribes /joint_states, publishes /left_hand_pose + /right_hand_pose (torso frame).
Link lengths match URDF. IK: numeric stub (scipy) — full IK at Milestone 9.
"""
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from geometry_msgs.msg import PoseStamped


def Rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def Ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def Rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def T_of(R, p):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


# URDF-derived arm chain (relative to torso_link)
SHOULDER_Y = 0.20
SHOULDER_Z = 0.30
D_UPPER = 0.13   # shoulder yaw -> elbow
D_FORE = 0.22    # elbow -> wrist
D_HAND = 0.04    # wrist yaw -> hand fingertip approx (visual offset)


def arm_fk(joints: dict, side: str):
    """joints: dict of 6 angles. Returns (pos xyz, R)."""
    s = 1.0 if side == 'left' else -1.0
    p = f'{side}_shoulder_pitch'
    r = f'{side}_shoulder_roll'
    y = f'{side}_shoulder_yaw'
    e = f'{side}_elbow_pitch'
    wp = f'{side}_wrist_pitch'
    wy = f'{side}_wrist_yaw'
    T = T_of(np.eye(3), np.array([0.0, s * SHOULDER_Y, SHOULDER_Z]))
    T = T @ T_of(Ry(joints[p]), np.zeros(3))
    T = T @ T_of(Rx(joints[r]), np.zeros(3))
    T = T @ T_of(Rz(joints[y]), np.zeros(3))
    T = T @ T_of(Ry(joints[e]), np.array([0.0, 0.0, -D_UPPER]))
    T = T @ T_of(Ry(joints[wp]), np.array([0.0, 0.0, -D_FORE]))
    T = T @ T_of(Rz(joints[wy]), np.array([0.0, 0.0, -D_HAND]))
    return T[:3, 3], T[:3, :3]


class ArmFkNode(Node):
    def __init__(self):
        super().__init__('arm_fk_node')
        self.js = {}
        self.create_subscription(JointState, '/joint_states', self.on_js, 10)
        self.l_pub = self.create_publisher(PoseStamped, '/left_hand_pose', 10)
        self.r_pub = self.create_publisher(PoseStamped, '/right_hand_pose', 10)
        self.create_timer(0.1, self.update)

    def on_js(self, msg: JointState):
        self.js = dict(zip(msg.name, msg.position))

    def update(self):
        if len(self.js) < 16:
            return
        for side, pub in (('left', self.l_pub), ('right', self.r_pub)):
            try:
                pos, _ = arm_fk(self.js, side)
            except KeyError:
                return
            m = PoseStamped()
            m.header.stamp = self.get_clock().now().to_msg()
            m.header.frame_id = 'torso_link'
            m.pose.position.x, m.pose.position.y, m.pose.position.z = pos.tolist()
            m.pose.orientation.w = 1.0
            pub.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = ArmFkNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

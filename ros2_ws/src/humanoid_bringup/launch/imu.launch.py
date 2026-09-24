"""IMU launch stub (spec sections 13-14, Milestone 2).

TODO(M2): replace test publisher with real BNO085/086 driver node publishing
sensor_msgs/Imu on /imu/data with quaternion orientation.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('frame_id', default_value='imu_link'),
        # Placeholder: static transform publisher documents the mount until driver lands.
        Node(package='tf2_ros', executable='static_transform_publisher', output='screen',
             arguments=['0', '0', '0.10', '0', '0', '0', 'torso_link',
                        LaunchConfiguration('frame_id')]),
    ])

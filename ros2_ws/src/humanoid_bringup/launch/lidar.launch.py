"""LiDAR launch (spec sections 15-16, acceptance 56).

Requires urg_node (ROS 2 Humble) + physical Hokuyo over Ethernet.
Params from config/lidar.yaml; IP overridable via LIDAR_IP env / launch arg.
"""
import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('lidar_ip', default_value=os.environ.get('LIDAR_IP', '192.168.0.10')),
        DeclareLaunchArgument('frame_id', default_value='lidar_link'),
        Node(package='urg_node', executable='urg_node_driver', output='screen',
             parameters=[{
                 'ip_address': LaunchConfiguration('lidar_ip'),
                 'frame_id': LaunchConfiguration('frame_id'),
             }],
             remappings=[('/scan', '/scan')]),
    ])

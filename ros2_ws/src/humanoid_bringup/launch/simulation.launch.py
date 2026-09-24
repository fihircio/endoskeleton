"""Simulation launch (spec sections 50, 55): same API as real robot."""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    desc = get_package_share_directory('humanoid_description')
    urdf_path = os.path.join(desc, 'urdf', 'humanoid.urdf.xacro')
    rviz_cfg = os.path.join(get_package_share_directory('humanoid_bringup'), 'rviz', 'humanoid.rviz')
    robot_desc = ParameterValue(Command(['xacro ', urdf_path]), value_type=str)

    return LaunchDescription([
        DeclareLaunchArgument('rviz', default_value='false', description='start RViz'),
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             parameters=[{'robot_description': robot_desc}], output='screen'),
        Node(package='humanoid_hardware', executable='sim_joint_bridge', output='screen'),
        Node(package='humanoid_safety', executable='safety_node', output='screen'),
        Node(package='humanoid_kinematics', executable='arm_fk_node', output='screen'),
        Node(package='rviz2', executable='rviz2', arguments=['-d', rviz_cfg],
             condition=IfCondition(LaunchConfiguration('rviz')), output='screen'),
    ])

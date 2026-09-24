"""Hardware launch (spec section 50): real PCA9685 + safety gate."""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    desc = get_package_share_directory('humanoid_description')
    urdf_path = os.path.join(desc, 'urdf', 'humanoid.urdf.xacro')
    robot_desc = ParameterValue(Command(['xacro ', urdf_path]), value_type=str)
    return LaunchDescription([
        DeclareLaunchArgument('servo_mode', default_value='mock',
                              description='mock | pca9685 (needs I2C + servo power)'),
        DeclareLaunchArgument('joints_config', default_value='/ws/config/joints.yaml'),
        DeclareLaunchArgument('servos_config', default_value='/ws/config/servos.yaml'),
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             parameters=[{'robot_description': robot_desc}], output='screen'),
        Node(package='humanoid_hardware', executable='servo_node', output='screen',
             parameters=[{
                 'mode': LaunchConfiguration('servo_mode'),
                 'joints_config': LaunchConfiguration('joints_config'),
                 'servos_config': LaunchConfiguration('servos_config'),
             }]),
        Node(package='humanoid_safety', executable='safety_node', output='screen'),
        Node(package='humanoid_kinematics', executable='arm_fk_node', output='screen'),
    ])

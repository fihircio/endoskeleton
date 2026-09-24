from setuptools import setup

package_name = 'humanoid_bringup'

setup(
    name=package_name,
    version='0.1.0',
    packages=[],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', [
            'launch/simulation.launch.py',
            'launch/hardware.launch.py',
            'launch/lidar.launch.py',
            'launch/imu.launch.py',
        ]),
        ('share/' + package_name + '/rviz', ['rviz/humanoid.rviz']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='humanoid-v1',
    maintainer_email='todo@todo.com',
    description='Launch files for Humanoid V1',
    license='MIT',
    tests_require=['pytest'],
)

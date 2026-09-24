from setuptools import find_packages, setup

package_name = 'humanoid_hardware'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='humanoid-v1',
    maintainer_email='todo@todo.com',
    description='PCA9685 servo abstraction with mock mode',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'servo_node = humanoid_hardware.servo_node:main',
            'sim_joint_bridge = humanoid_hardware.sim_joint_bridge:main',
        ],
    },
)

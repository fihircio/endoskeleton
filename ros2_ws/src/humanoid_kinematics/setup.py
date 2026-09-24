from setuptools import find_packages, setup

package_name = 'humanoid_kinematics'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'numpy', 'scipy'],
    zip_safe=True,
    maintainer='humanoid-v1',
    maintainer_email='todo@todo.com',
    description='Arm FK/IK',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'arm_fk_node = humanoid_kinematics.arm_fk_node:main',
        ],
    },
)

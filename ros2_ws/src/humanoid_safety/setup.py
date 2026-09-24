from setuptools import find_packages, setup

package_name = 'humanoid_safety'

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
    description='Safety state machine',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'safety_node = humanoid_safety.safety_node:main',
        ],
    },
)

#!/usr/bin/env bash
# Local (no-ROS) sanity checks for Mac dev. Full build happens in Docker / on Pi.
# Usage: bash scripts/check_local.sh
set -e
cd "$(dirname "$0")/.."
echo "== python compile =="
python3 -c "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('ros2_ws/src/humanoid_*/**/*.py', recursive=True) + glob.glob('ros2_ws/src/humanoid_bringup/launch/*.py')]; print('compile OK')"
echo "== yaml =="
python3 -c "import yaml, glob; [yaml.safe_load(open(f)) for f in glob.glob('config/*.yaml')]; print('yaml OK')"
echo "== urdf joint/link cross-check =="
python3 -c "
import re, glob, yaml
x = ''.join(open(f).read() for f in glob.glob('ros2_ws/src/humanoid_description/urdf/*.xacro'))
rev = [j for j in set(re.findall(r'<joint name=\"([a-z_0-9]+)\"', x)) if j not in ('base_to_pelvis','torso_to_imu','torso_to_lidar','head_to_camera_left','head_to_camera_right')]
yj = set(yaml.safe_load(open('config/joints.yaml'))['joints'].keys())
assert set(rev) == yj, (set(rev) ^ yj)
print('16-DOF match OK')
"
echo "== xml well-formed =="
python3 -c "import xml.dom.minidom, glob; [xml.dom.minidom.parse(f) for f in glob.glob('ros2_ws/src/humanoid_description/urdf/*.xacro')]; print('xml OK')"
echo ALL LOCAL CHECKS PASSED

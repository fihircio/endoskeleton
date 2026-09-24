FROM osrf/ros:humble-desktop-full

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-colcon-common-extensions \
    python3-rosdep \
    ros-humble-xacro \
    ros-humble-robot-state-publisher \
    ros-humble-joint-state-publisher \
    ros-humble-rviz2 \
    ros-humble-ros2-control \
    ros-humble-ros2-controllers \
    ros-humble-moveit-msgs \
    python3-pip python3-numpy python3-scipy \
    i2c-tools vim-tiny \
 && rm -rf /var/lib/apt/lists/*

# pip deps kept minimal for V1 (spec §5, §51)
RUN pip3 install --no-cache-dir transforms3d pyyaml

WORKDIR /ws
COPY ros2_ws/src /ws/ros2_ws/src
COPY config /ws/config

# rosdep (best-effort; works offline if cached)
RUN bash -c "source /opt/ros/humble/setup.bash && cd /ws/ros2_ws && rosdep init 2>/dev/null || true && rosdep update && rosdep install --from-paths src --ignore-src -r -y || true"

RUN bash -c "source /opt/ros/humble/setup.bash && cd /ws/ros2_ws && colcon build --symlink-install"

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]

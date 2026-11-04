"""
fchev_launch.py — FCHEV EMS Full System Launch File
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-03-16A

Starts all nodes with one command:
    ros2 launch fchev_ems fchev_launch.py

With options:
    ros2 launch fchev_ems fchev_launch.py ems:=sdp
    ros2 launch fchev_ems fchev_launch.py ems:=simple
    ros2 launch fchev_ems fchev_launch.py csv:=/home/pi/fchev/UDDS.csv
    ros2 launch fchev_ems fchev_launch.py log:=true

Node graph launched:
    drive_cycle_node   → /drive_cycle
    teensy_bridge_node → /vehicle_state, /comms_status
    sdp_ems_node       → /ems_command, /ems_diagnostics
    (rosbag2 record    → all topics, if log:=true)

Install:
    Copy to: ~/ros2_ws/src/fchev_ems/launch/fchev_launch.py

    In package.xml add:
        <exec_depend>rclpy</exec_depend>

    In setup.py add:
        data_files=[
            ...
            ('share/' + package_name + '/launch',
             ['launch/fchev_launch.py']),
        ],
"""

import os
from datetime import datetime

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    LogInfo,
    RegisterEventHandler,
    Shutdown,
)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():

    # ── Launch arguments (override from CLI) ──────────────────────────────────
    arg_ems = DeclareLaunchArgument(
        "ems",
        default_value="sdp",
        description="EMS algorithm: sdp | simple",
    )
    arg_csv = DeclareLaunchArgument(
        "csv",
        default_value=os.path.expanduser("~/fchev/EMS/test_dc.csv"),
        description="Path to drive cycle CSV (time_s, v_mps)",
    )
    arg_cost_j = DeclareLaunchArgument(
        "cost_j",
        default_value=os.path.expanduser(
            "~/fchev/EMS/SDP/CostToGo_J_scaled_2026-03-16A.mat"
        ),
        description="Path to precomputed SDP cost-to-go .mat file",
    )
    arg_teensy_ip = DeclareLaunchArgument(
        "teensy_ip",
        default_value="192.168.1.50",
        description="Teensy IP address",
    )
    arg_mass = DeclareLaunchArgument(
        "mass",
        default_value="5.0",
        description="Scaled vehicle mass kg",
    )
    arg_alpha = DeclareLaunchArgument(
        "alpha",
        default_value="500.0",
        description="SDP SOC penalty weight (500=conservative, 5000=more FC use)",
    )
    arg_log = DeclareLaunchArgument(
        "log",
        default_value="false",
        description="Record rosbag2 (true/false)",
    )
    arg_loop_dc = DeclareLaunchArgument(
        "loop_dc",
        default_value="false",
        description="Loop drive cycle when complete (true/false)",
    )

    # ── Timestamp for rosbag name ──────────────────────────────────────────────
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # ── Node 1: Teensy Bridge ─────────────────────────────────────────────────
    teensy_bridge = Node(
        package="fchev_ems",
        executable="teensy_bridge",
        name="teensy_bridge_node",
        output="screen",
        parameters=[{
            "teensy_ip":  LaunchConfiguration("teensy_ip"),
            "publish_hz": 50.0,
            "comms_hz":   1.0,
        }],
        remappings=[],
    )

    # ── Node 2: Drive Cycle Publisher ─────────────────────────────────────────
    drive_cycle = Node(
        package="fchev_ems",
        executable="drive_cycle_node",
        name="drive_cycle_node",
        output="screen",
        parameters=[{
            "csv_path":     LaunchConfiguration("csv"),
            "vehicle_mass": LaunchConfiguration("mass"),
            "publish_hz":   20.0,
            "loop":         LaunchConfiguration("loop_dc"),
            "start_delay":  3.0,
        }],
    )

    # ── Node 3a: SDP EMS (default) ────────────────────────────────────────────
    sdp_ems = Node(
        package="fchev_ems",
        executable="sdp_ems_node",
        name="sdp_ems_node",
        output="screen",
        parameters=[{
            "cost_j_path":   LaunchConfiguration("cost_j"),
            "alpha":         LaunchConfiguration("alpha"),
            "control_hz":    20.0,
            "vehicle_mass":  LaunchConfiguration("mass"),
        }],
        condition=IfCondition(
            PythonExpression(["'", LaunchConfiguration("ems"), "' == 'sdp'"])
        ),
    )

    # ── Node 3b: Simple rule-based EMS (bring-up / fallback) ─────────────────
    # Wraps simple_ems_test.py logic as a ROS node for easy swapping
    simple_ems = Node(
        package="fchev_ems",
        executable="simple_ems_node",
        name="simple_ems_node",
        output="screen",
        parameters=[{
            "control_hz":   20.0,
        }],
        condition=IfCondition(
            PythonExpression(["'", LaunchConfiguration("ems"), "' == 'simple'"])
        ),
    )

    # ── rosbag2 recording (optional) ──────────────────────────────────────────
    bag_dir = os.path.expanduser(f"~/fchev/logs/rosbag_{ts}")

    rosbag_record = ExecuteProcess(
        cmd=[
            "ros2", "bag", "record",
            "-o", bag_dir,
            "/vehicle_state",
            "/ems_command",
            "/ems_diagnostics",
            "/drive_cycle",
            "/drive_cycle_status",
            "/comms_status",
        ],
        output="screen",
        condition=IfCondition(LaunchConfiguration("log")),
    )

    # ── Shutdown all nodes when drive cycle finishes ──────────────────────────
    # (optional — remove if you want manual Ctrl+C only)
    # shutdown_on_dc_done = RegisterEventHandler(
    #     OnProcessExit(
    #         target_action=drive_cycle,
    #         on_exit=[Shutdown()],
    #     )
    # )

    # ── Log startup info ───────────────────────────────────────────────────────
    log_start = LogInfo(
        msg=[
            "\n",
            "=" * 60, "\n",
            "  FCHEV EMS System Starting\n",
            "  EMS:      ", LaunchConfiguration("ems"), "\n",
            "  CSV:      ", LaunchConfiguration("csv"), "\n",
            "  Teensy:   ", LaunchConfiguration("teensy_ip"), "\n",
            "  Logging:  ", LaunchConfiguration("log"), "\n",
            "=" * 60,
        ]
    )

    return LaunchDescription([
        # Arguments
        arg_ems,
        arg_csv,
        arg_cost_j,
        arg_teensy_ip,
        arg_mass,
        arg_alpha,
        arg_log,
        arg_loop_dc,
        # Info
        log_start,
        # Nodes
        teensy_bridge,
        drive_cycle,
        sdp_ems,
        simple_ems,
        # Optional bag recording
        rosbag_record,
    ])

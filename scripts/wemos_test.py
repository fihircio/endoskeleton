#!/usr/bin/env python3
"""Smoke-test CLI for the Wemos servo bridge (firmware/wemos/servo_bridge).

  python3 wemos_test.py --port /dev/ttyUSB0 ping
  python3 wemos_test.py enable
  python3 wemos_test.py move left_elbow_pitch 1.2 right_elbow_pitch 1.9 head_pan 0.3
  python3 wemos_test.py watch            # print status stream 10s
  python3 wemos_test.py estop            # latch e-stop (PWM off)
  python3 wemos_test.py reset            # estop -> disabled
  python3 wemos_test.py disable

Needs: python3-serial on the Pi (sudo apt install python3-serial).
NOTE: the bridge faults to HOLD if no valid message arrives for 500 ms,
so single manual moves hold; continuous motion needs a >2 Hz stream
(the future ROS joint driver, same protocol).
"""
import argparse
import json
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("need python3-serial: sudo apt install python3-serial")


def open_port(port, baud=115200):
    s = serial.Serial(port, baud, timeout=1.0)
    time.sleep(2.0)  # ESP8266 resets on open; let it boot + print banner
    s.reset_input_buffer()
    return s


def send(s, obj, wait_reply=1.0):
    s.write((json.dumps(obj) + "\n").encode())
    t0 = time.time()
    while time.time() - t0 < wait_reply:
        line = s.readline().decode(errors="replace").strip()
        if line:
            return line
    return "(no reply)"


def cmd_ping(s, _):
    print(send(s, {"ping": 1}))


def cmd_enable(s, _):
    print(send(s, {"enable": True}, 2.0))


def cmd_disable(s, _):
    print(send(s, {"enable": False}, 2.0))


def cmd_estop(s, _):
    print(send(s, {"estop": True}, 2.0))


def cmd_reset(s, _):
    print(send(s, {"reset": True}, 2.0))


def cmd_move(s, args):
    if len(args) % 2:
        sys.exit("move needs joint value pairs")
    joints = {}
    for name, val in zip(args[0::2], args[1::2]):
        joints[name] = float(val)
    print(send(s, {"joints": joints}, 2.0))


def cmd_watch(s, _):
    t0 = time.time()
    while time.time() - t0 < 10:
        line = s.readline().decode(errors="replace").strip()
        if line:
            print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("cmd", choices=["ping", "enable", "disable", "estop",
                                    "reset", "move", "watch"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    s = open_port(a.port)
    try:
        {"ping": cmd_ping, "enable": cmd_enable, "disable": cmd_disable,
         "estop": cmd_estop, "reset": cmd_reset, "move": cmd_move,
         "watch": cmd_watch}[a.cmd](s, a.args)
    finally:
        s.close()


if __name__ == "__main__":
    sys.exit(main())

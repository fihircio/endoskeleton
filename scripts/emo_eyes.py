#!/usr/bin/env python3
"""EMO-inspired expressive eyes for the 480x320 SPI face screen.

Runs headless on the Pi straight into the framebuffer:
  SDL_FBDEV=/dev/fb0 python3 emo_eyes.py --demo
On a desktop (no fb) it opens a window instead — keys 1-5 switch moods.

Moods: normal, happy, sleepy, surprised, sleep. Idle engine does
blinking + saccades on its own; --demo cycles moods every ~6s.

TODO(brain): subscribe /safety_state and map it onto moods, e.g.
  BOOT -> sleepy blink, READY -> normal, ACTIVE -> happy flicker,
  FAULT -> sleep, EMERGENCY_STOP -> X eyes. That binding belongs in a
  future humanoid_display ROS package; this file stays transport-free.
"""
import argparse
import math
import os
import random
import sys
import time

FBDEV = os.environ.get("SDL_FBDEV", "/dev/fb0")
# SDL2 has no fbcon driver: draw into an offscreen Surface and push RGB565
# to the framebuffer ourselves. No fb -> fall back to a desktop window.
USE_FB = os.path.exists(FBDEV)
if USE_FB:
    os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

W, H = 480, 320
BG = (5, 5, 10)
EYE = (55, 245, 255)  # EMO cyan
EYE_DIM = (0, 90, 110)

EYE_W, EYE_H = 110, 150
LEFT_C = (150, 165)
RIGHT_C = (330, 165)
LOOK_MAX = (38, 26)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class Face:
    def __init__(self, screen):
        self.screen = screen
        self.mood = "normal"
        self.open = 1.0          # eyelid: 1 open .. 0 shut
        self.open_target = 1.0
        self.look = [0.0, 0.0]
        self.look_target = [0.0, 0.0]
        self.next_blink = time.time() + 2.0
        self.next_saccade = time.time() + 1.0
        self.blinking = False
        self.t0 = time.time()

    # -- behavior ------------------------------------------------------
    def update(self, dt, now):
        if self.mood == "sleep":
            self.open_target = 0.0
        elif self.mood == "sleepy":
            self.open_target = 0.35
        elif self.blinking:
            self.open_target = 0.0
            if self.open < 0.05:
                self.blinking = False
        else:
            self.open_target = 1.0
            if now > self.next_blink and self.mood in ("normal", "surprised"):
                self.blinking = True
                self.next_blink = now + random.uniform(2.2, 5.0)
        # eyelid servo: fast shut, softer open
        rate = 14.0 if self.open_target < self.open else 7.0
        self.open += clamp(self.open_target - self.open, -rate * dt, rate * dt)

        if now > self.next_saccade and self.mood in ("normal", "happy", "sleepy"):
            self.look_target = [random.uniform(-1, 1), random.uniform(-0.7, 0.7)]
            self.next_saccade = now + random.uniform(1.4, 3.8)
        k = min(1.0, dt * 6.0)
        self.look[0] += (self.look_target[0] - self.look[0]) * k
        self.look[1] += (self.look_target[1] - self.look[1]) * k

    # -- drawing --------------------------------------------------------
    def draw_eye(self, cx, cy, happy_side):
        o = self.open
        look_dx = self.look[0] * LOOK_MAX[0]
        look_dy = self.look[1] * LOOK_MAX[1] + math.sin(time.time() * 1.7) * 2.0
        cx, cy = cx + look_dx, cy + look_dy

        if self.mood == "happy":
            # ^ ^ : thick upward arcs
            w, h = EYE_W + 10, 95
            rect = pygame.Rect(cx - w / 2, cy - h / 2 + 18, w, h)
            pygame.draw.arc(self.screen, EYE, rect, math.pi * 0.15, math.pi * 0.85, 22)
            return
        if self.mood == "surprised":
            w, h = EYE_W + 26, EYE_H + 40
        elif self.mood == "sleepy":
            w, h = EYE_W + 6, EYE_H
        else:
            w, h = EYE_W, EYE_H
        h_vis = max(6, h * o)
        top = cy - h / 2 + (h - h_vis) * (0.65 if self.mood == "sleepy" else 0.5)
        color = EYE_DIM if self.mood in ("sleep", "sleepy") else EYE
        pygame.draw.rect(self.screen, color,
                         pygame.Rect(cx - w / 2, top, w, h_vis),
                         border_radius=int(min(w, h_vis) / 2 - 2))

    def draw(self):
        self.screen.fill(BG)
        if self.mood == "sleep":
            for cx, cy in (LEFT_C, RIGHT_C):
                y = cy + self.look[1] * 8
                pygame.draw.line(self.screen, EYE_DIM,
                                 (cx - 45, y), (cx + 45, y), 10)
            # Zzz
            t = time.time()
            for i, (s, a) in enumerate([(28, 200), (20, 130), (14, 70)]):
                off = (t * 30 + i * 40) % 120
                font = pygame.font.SysFont(None, s)
                z = font.render("Z", True, EYE_DIM)
                self.screen.blit(z, (W - 70 - off * 0.4, a - off * 0.5))
        else:
            self.draw_eye(*LEFT_C, -1)
            self.draw_eye(*RIGHT_C, 1)
        _present(self.screen)


_FB = None


def _present(surf):
    """Push a pygame Surface to the raw framebuffer (RGB565) or flip a window."""
    global _FB
    if not USE_FB:
        pygame.display.flip()
        return
    import numpy as np
    if _FB is None:
        _FB = open(FBDEV, "r+b", buffering=0)
    a = pygame.surfarray.pixels3d(surf).astype(np.uint16)  # (W, H, 3)
    rgb565 = (((a[:, :, 0] & 0xF8) << 8) | ((a[:, :, 1] & 0xFC) << 3)
              | (a[:, :, 2] >> 3))
    # transpose to row-major (H, W) and emit little-endian u16
    rgb565 = np.ascontiguousarray(np.transpose(rgb565, (1, 0))).astype("<u2")
    _FB.seek(0)
    _FB.write(rgb565.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mood", default="normal",
                    choices=["normal", "happy", "sleepy", "surprised", "sleep"])
    ap.add_argument("--demo", action="store_true", help="cycle moods every 6s")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--mood-file", default=None,
                    help="when present and fresh, mood is read from this file "
                         "(written by voice_loop); e.g. /tmp/face_mood")
    args = ap.parse_args()

    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("emo eyes")
    pygame.mouse.set_visible(False)
    face = Face(screen)
    face.mood = args.mood
    mood_file, mood_mtime = args.mood_file, 0
    moods = ["normal", "happy", "sleepy", "surprised", "normal", "sleep"]
    mi, next_switch = 0, time.time() + 6
    clock = pygame.time.Clock()
    last = time.time()
    try:
        while True:
            now = time.time()
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        return
                    for i, m in enumerate(["normal", "happy", "sleepy", "surprised", "sleep"]):
                        if e.key == getattr(pygame, f"K_{i + 1}"):
                            face.mood = m
            if args.demo and now > next_switch:
                mi = (mi + 1) % len(moods)
                face.mood = moods[mi]
                next_switch = now + 6
            if mood_file:
                try:
                    mt = os.path.getmtime(mood_file)
                    if mt != mood_mtime:
                        mood_mtime = mt
                        m = open(mood_file).read().strip().split()[0]
                        if m in ("normal", "happy", "sleepy", "surprised", "sleep"):
                            face.mood = m
                            next_switch = now + 6  # pause demo rotation
                except OSError:
                    pass
            face.update(min(0.05, now - last), now)
            last = now
            face.draw()
            clock.tick(args.fps)
    finally:
        pygame.quit()


if __name__ == "__main__":
    sys.exit(main())

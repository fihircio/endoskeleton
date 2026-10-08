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

# Eye color is configurable (--eye-color R,G,B); RoboEyes-style monochrome
# is just a special case of this. Moods/animation vocabulary below is
# INSPIRED BY FluxGarage RoboEyes (GPL-3.0) but implemented originally here
# (no upstream code used), extended with full color + photo + sleep states.
DEF_EYE = (55, 245, 255)  # EMO cyan

EYE_W, EYE_H = 110, 150
LEFT_C = (150, 165)
RIGHT_C = (330, 165)
LOOK_MAX = (38, 26)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class Face:
    PHOTO_FILE = "/tmp/face_photo"

    def __init__(self, screen, eye=DEF_EYE):
        self.screen = screen
        self.mood = "normal"
        self.eye = tuple(eye)
        self.dim = tuple(max(0, min(255, int(c * 0.38))) for c in eye)
        self.shake = None       # oneshot: 'laugh' | 'confused' | None
        self.shake_until = 0.0
        self.photo_surf = None
        self.photo_path = None
        self.photo_until = 0.0
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
        # oneshot animations play ~1.2s, then fall back to normal
        if self.mood in ("laugh", "confused"):
            if self.shake != self.mood:
                self.shake, self.shake_until = self.mood, now + 1.2
            elif now > self.shake_until:
                self.mood, self.shake = "normal", None
        if self.mood == "sleep":
            self.open_target = 0.0
        elif self.mood == "sleepy":
            self.open_target = 0.35
        elif self.mood == "tired":
            self.open_target = 1.0  # full eye; droop comes from lid overlay
        elif self.blinking:
            self.open_target = 0.0
            if self.open < 0.05:
                self.blinking = False
        else:
            self.open_target = 1.0
            if now > self.next_blink and self.mood in ("normal", "surprised", "listening", "curious", "tired", "angry"):
                self.blinking = True
                self.next_blink = now + random.uniform(2.2, 5.0)
        # eyelid servo: fast shut, softer open
        rate = 14.0 if self.open_target < self.open else 7.0
        self.open += clamp(self.open_target - self.open, -rate * dt, rate * dt)

        if now > self.next_saccade and self.mood in ("normal", "happy", "sleepy", "listening", "curious", "tired", "angry"):
            self.look_target = [random.uniform(-1, 1), random.uniform(-0.7, 0.7)]
            self.next_saccade = now + random.uniform(1.4, 3.8)
        k = min(1.0, dt * 6.0)
        self.look[0] += (self.look_target[0] - self.look[0]) * k
        self.look[1] += (self.look_target[1] - self.look[1]) * k

    # -- drawing --------------------------------------------------------
    def _draw_photo(self):
        """Show /tmp/face_photo (center-cropped to 3:2) for a few seconds."""
        import time as _t
        try:
            path = open(self.PHOTO_FILE).read().strip().splitlines()[0]
        except OSError:
            return False
        if path != self.photo_path:
            try:
                img = pygame.image.load(path).convert()
            except Exception:
                return False
            # center-crop to screen aspect, then scale (smooth)
            sw, sh = img.get_size()
            target = W / H
            if sw / sh > target:
                nw = int(sh * target)
                img = img.subsurface((sw - nw) // 2, 0, nw, sh)
            else:
                nh = int(sw / target)
                img = img.subsurface(0, (sh - nh) // 2, sw, nh)
            self.photo_surf = pygame.transform.smoothscale(img, (W, H))
            self.photo_path = path
            self.photo_until = _t.time() + 8.0  # writer deletes file first
        self.screen.blit(self.photo_surf, (0, 0))
        return True

    def draw_eye(self, cx, cy, side):
        """side: -1 left eye, +1 right eye (used for asymmetric moods)."""
        o = self.open
        look_dx = self.look[0] * LOOK_MAX[0]
        look_dy = self.look[1] * LOOK_MAX[1] + math.sin(time.time() * 1.7) * 2.0
        cx, cy = cx + look_dx, cy + look_dy
        # oneshot shakes (RoboEyes laugh/confused vocabulary)
        now = time.time()
        if self.shake == "laugh":
            cy += 13 * math.sin(now * 28.0)
        elif self.shake == "confused":
            cx += 17 * math.sin(now * 21.0)

        if self.mood == "happy":
            # ^ ^ : thick upward arcs
            w, h = EYE_W + 10, 95
            rect = pygame.Rect(cx - w / 2, cy - h / 2 + 18, w, h)
            pygame.draw.arc(self.screen, self.eye, rect, math.pi * 0.15, math.pi * 0.85, 22)
            return
        if self.mood == "angry":
            # full rounded eye; anger is a lid overlay (RoboEyes technique)
            w, h = EYE_W + 14, EYE_H + 10
        elif self.mood == "curious":
            # one eye taller than the other (alternates with look direction)
            tall = 1.35 if (side < 0) == (self.look[0] < 0) else 1.0
            w, h = EYE_W + 8, int((EYE_H + 6) * tall)
        elif self.mood == "tired":
            w, h = EYE_W + 10, EYE_H + 4
        elif self.mood == "listening":
            # wide alert eyes with a gentle pulse
            pulse = 1.0 + 0.05 * math.sin(time.time() * 5.0)
            w, h = (EYE_W + 20) * pulse, (EYE_H + 34) * pulse
        elif self.mood == "surprised":
            w, h = EYE_W + 26, EYE_H + 40
        elif self.mood == "sleepy":
            w, h = EYE_W + 6, EYE_H
        else:
            w, h = EYE_W, EYE_H
        h_vis = max(6, h * o)
        droop = 0.65 if self.mood == "sleepy" else 0.5
        top = cy - h / 2 + (h - h_vis) * droop
        color = self.dim if self.mood in ("sleep", "sleepy", "tired") else self.eye
        pygame.draw.rect(self.screen, color,
                         pygame.Rect(cx - w / 2, top, w, h_vis),
                         border_radius=int(min(w, h_vis) / 2 - 2))
        # lid overlays cut from the drawn eye (background color shows through)
        if self.mood == "angry":
            # inner top corner cut, mirrored per eye
            cut = h_vis * 0.55
            if side < 0:  # left eye: cut right (inner) corner
                pygame.draw.polygon(self.screen, BG,
                                    [(cx + w / 2, top),
                                     (cx + w / 2, top + cut),
                                     (cx + w / 2 - cut * 1.6, top)])
            else:  # right eye: cut left (inner) corner
                pygame.draw.polygon(self.screen, BG,
                                    [(cx - w / 2, top),
                                     (cx - w / 2, top + cut),
                                     (cx - w / 2 + cut * 1.6, top)])
        elif self.mood == "tired":
            # outer top corners droop (mirrored per eye)
            cut = h_vis * 0.5
            if side < 0:  # left eye: cut left (outer) corner
                pygame.draw.polygon(self.screen, BG,
                                    [(cx - w / 2, top),
                                     (cx - w / 2, top + cut),
                                     (cx - w / 2 + cut * 1.6, top)])
            else:  # right eye: cut right (outer) corner
                pygame.draw.polygon(self.screen, BG,
                                    [(cx + w / 2, top),
                                     (cx + w / 2, top + cut),
                                     (cx + w / 2 - cut * 1.6, top)])

    def draw(self):
        if self.mood == "photo":
            if self._draw_photo():
                _present(self.screen)
                return
            self.mood = "normal"  # photo gone -> fall through to eyes
        self.screen.fill(BG)
        if self.mood == "sleep":
            for cx, cy in (LEFT_C, RIGHT_C):
                y = cy + self.look[1] * 8
                pygame.draw.line(self.screen, self.dim,
                                 (cx - 45, y), (cx + 45, y), 10)
            # Zzz
            t = time.time()
            for i, (s, a) in enumerate([(28, 200), (20, 130), (14, 70)]):
                off = (t * 30 + i * 40) % 120
                font = pygame.font.SysFont(None, s)
                z = font.render("Z", True, self.dim)
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


MOODS = ["normal", "happy", "sleepy", "surprised", "sleep", "listening",
         "photo", "angry", "tired", "curious", "laugh", "confused"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mood", default="normal", choices=MOODS)
    ap.add_argument("--demo", action="store_true", help="cycle moods every 6s")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--eye-color", default="55,245,255",
                    help="eye color as R,G,B (e.g. 255,170,0 amber; "
                         "80,255,120 green; 190,120,255 purple)")
    ap.add_argument("--mood-file", default=None,
                    help="when present and fresh, mood is read from this file "
                         "(written by voice_loop); e.g. /tmp/face_mood")
    args = ap.parse_args()

    try:
        eye = tuple(max(0, min(255, int(c))) for c in args.eye_color.split(","))
        assert len(eye) == 3
    except Exception:
        eye = DEF_EYE

    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("emo eyes")
    pygame.mouse.set_visible(False)
    face = Face(screen, eye=eye)
    face.mood = args.mood
    mood_file, mood_mtime = args.mood_file, 0
    moods = ["normal", "listening", "happy", "curious", "sleepy", "tired",
             "angry", "surprised", "laugh", "confused", "normal", "sleep"]
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
                    for i, m in enumerate(MOODS):
                        if i < 9 and e.key == getattr(pygame, f"K_{i + 1}"):
                            face.mood = m
            ext_fresh = False
            if mood_file:
                try:
                    mt = os.path.getmtime(mood_file)
                    # fresh external control pauses demo rotation so it can't
                    # stomp photo/listening faces mid-display
                    ext_fresh = (now - mt) < 30
                    if mt != mood_mtime:
                        mood_mtime = mt
                        m = open(mood_file).read().strip().split()[0]
                        if m in MOODS:
                            face.mood = m
                except OSError:
                    pass
            if args.demo and not ext_fresh and now > next_switch:
                mi = (mi + 1) % len(moods)
                face.mood = moods[mi]
                next_switch = now + 6
            face.update(min(0.05, now - last), now)
            last = now
            face.draw()
            clock.tick(args.fps)
    finally:
        pygame.quit()


if __name__ == "__main__":
    sys.exit(main())

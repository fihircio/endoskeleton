#!/usr/bin/env python3
"""Voice loop for humanoid-pi1: mic (USB camera) -> Vosk STT -> Qwen LLM -> espeak.

Listens in 6s windows (blip announces each window), decodes with Vosk,
asks llama.cpp (Qwen2.5-0.5B), speaks the reply, and steers the face
(/tmp/face_mood read by emo_eyes.py --mood-file).

  python3 voice_loop.py
  python3 voice_loop.py --once "hello robot"   # text-only round trip (no mic)

Files (all under ~/brain): models/qwen25-05b-q4km.gguf,
  models/vosk-model-small-en-us-0.15, voice_loop.py. LLM binary from llama.app.
"""
import argparse
import datetime
import json
import os
import struct
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
BRAIN = os.path.join(HOME, "brain")
MODEL = os.path.join(BRAIN, "models", "qwen25-05b-q4km.gguf")
VOSK_DIR = os.path.join(BRAIN, "models", "vosk-model-small-en-us-0.15")
LLAMA = os.path.join(HOME, ".llama-app", "llama")
MOOD_FILE = "/tmp/face_mood"
LOG = os.path.join(BRAIN, "chats.log")

MIC = "hw:CARD=PSE0510"  # Philips camera mic, by name (card numbers move)
SPK = "plughw:CARD=DS09"  # USB speaker via plug (mono/stereo + rate convert)
RATE = 16000
LISTEN_S = 6


def set_mood(mood):
    try:
        open(MOOD_FILE, "w").write(mood + "\n")
    except OSError:
        pass


def log(who, text):
    line = f"{datetime.datetime.now():%H:%M:%S} {who}: {text}"
    print(line, flush=True)
    try:
        open(LOG, "a").write(line + "\n")
    except OSError:
        pass


def blip(freq=880, ms=120):
    tone = os.path.join("/tmp", "blip.wav")
    subprocess.run(
        ["python3", "-c",
         f"import wave,struct,math;w=wave.open('{tone}','wb');"
         "w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);"
         f"w.writeframes(b''.join(struct.pack('<h',int(9000*math.sin(2*math.pi*{freq}*i/16000))) for i in range(int(16000*{ms}/1000))))"],
        check=True)
    subprocess.run(["aplay", "-q", "-D", SPK, tone],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_ARECORD = None  # current recorder, so signals never orphan it
_STREAM = None    # persistent mic stream: this camera's endpoint wedges on
                  # close/reopen under Linux (works on Windows), so we open
                  # once and read windows from the endless stream instead.


def _open_stream():
    global _STREAM
    _close_stream()
    _STREAM = subprocess.Popen(
        ["arecord", "-q", "-D", MIC, "-f", "S16_LE", "-r", str(RATE),
         "-c", "2", "-d", "3600", "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return _STREAM


def _close_stream():
    global _STREAM
    if _STREAM is not None:
        try:
            _STREAM.kill()
            _STREAM.wait(timeout=3)
        except OSError:
            pass
        _STREAM = None


def _read_exact(proc, nbytes, timeout_s=LISTEN_S + 8):
    """Blocking read of exactly nbytes (or b'' on EOF/timeout)."""
    import select as _select
    out, deadline = bytearray(), time.time() + timeout_s
    fd = proc.stdout.fileno()
    while len(out) < nbytes:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        r, _, _ = _select.select([fd], [], [], remaining)
        if not r:
            break
        chunk = proc.stdout.read(nbytes - len(out))
        if not chunk:
            break
        out += chunk
    return bytes(out)


def _rms(samples):
    import math as _math
    return _math.sqrt(sum(s * s for s in samples) / max(len(samples), 1))


def listen():
    """VAD-gated window from the persistent mic stream.

    Records until 0.8s of trailing silence after speech (or 6s of
    silence / 8s total cap), so typical turns take ~2s, not 6s.
    """
    for _ in ("stream", "reopen"):
        proc = _STREAM or _open_stream()
        if proc.poll() is not None:  # died -> reopen once
            proc = _open_stream()
        chunk_bytes = RATE * 2 * 2 // 5  # 0.2s stereo S16
        buf, speech, quiet, elapsed = bytearray(), False, 0, 0.0
        while elapsed < 8.0:
            raw = _read_exact(proc, chunk_bytes, timeout_s=3.0)
            if len(raw) < chunk_bytes // 2:
                break  # stream dead; outer retry reopens
            buf += raw
            elapsed += 0.2
            n = len(raw) // 2
            mono = struct.unpack(f"<{n}h", raw[:n * 2])[0::2]
            level = _rms(mono)
            if not speech:
                if level > 1500:
                    speech = True
                    quiet = 0
                elif elapsed >= 6.0:
                    break  # nobody home
            else:
                quiet = quiet + 1 if level < 700 else 0
                if quiet >= 4 and elapsed >= 1.0:
                    break  # 0.8s trailing silence
        if len(buf) >= RATE * 2 * 2 // 2:  # >=0.5s audio
            break
        _close_stream()  # wedge suspected: fresh handle, one retry
    else:
        return b""
    n = len(buf) // 2
    stereo = struct.unpack(f"<{n}h", bytes(buf[:n * 2]))
    mono = [(a + b) // 2 for a, b in zip(stereo[0::2], stereo[1::2])]
    return struct.pack(f"<{len(mono)}h", *mono)


def _cleanup(signum=None, frame=None):
    if _ARECORD is not None:
        try:
            _ARECORD.kill()
        except OSError:
            pass
    _close_stream()
    raise SystemExit(0)


def stt(pcm):
    from vosk import KaldiRecognizer, Model
    if not hasattr(stt, "rec"):
        stt.rec = KaldiRecognizer(Model(VOSK_DIR), RATE)
        stt.rec.SetWords(False)
    stt.rec.AcceptWaveform(pcm)
    return json.loads(stt.rec.FinalResult()).get("text", "").strip()


def ask_llm(user_text):
    """Chat via local llama-server (needs: llama serve -m MODEL --port 8080).

    Server keeps the model resident, so turns take ~3s instead of ~20s.
    """
    import json as _json
    import urllib.request as _url
    body = _json.dumps({
        "messages": [
            {"role": "system",
             "content": "You are Elberr, a tiny cute desk robot hand-built by your "
                        "human on a Raspberry Pi. One short plain sentence, no lists."},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 25,
        "temperature": 0.7,
    }).encode()
    try:
        req = _url.Request("http://localhost:8080/v1/chat/completions",
                           data=body, headers={"Content-Type": "application/json"})
        with _url.urlopen(req, timeout=120) as r:
            choices = _json.load(r)["choices"]
    except Exception as e:  # server down? log and stay charming
        log("ELBERR", f"brain unreachable: {e}")
        return "Hmm."
    if not choices:
        return "Hmm."
    reply = choices[0]["message"]["content"]
    return " ".join(reply.split())[:280] or "Hmm."


def _speak_piper(text):
    """Neural voice via local wyoming-piper server (needs :10200 up),
    robotized with sox (pitch down, tempo kept) for the Elberr feel."""
    import asyncio as _aio
    import wave as _wave
    from wyoming.audio import AudioChunk as _AC, AudioStop as _AS
    from wyoming.client import AsyncTcpClient as _Client
    from wyoming.tts import Synthesize as _Syn

    async def _run():
        audio = bytearray()
        async with _Client("127.0.0.1", 10200) as client:
            await client.write_event(_Syn(text=text).event())
            while True:
                event = await client.read_event()
                if event is None:
                    break
                if _AC.is_type(event.type):
                    audio += _AC.from_event(event).audio
                elif _AS.is_type(event.type):
                    break
        return bytes(audio)

    audio = _aio.run(_run())
    if not audio:
        raise RuntimeError("piper empty")
    w = _wave.open("/tmp/elberr-say.wav", "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(22050)
    w.writeframes(audio)
    w.close()
    subprocess.run(["sox", "/tmp/elberr-say.wav", "/tmp/elberr-robot.wav",
                    "pitch", "-300"],
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    subprocess.run(["aplay", "-q", "-D", SPK, "/tmp/elberr-robot.wav"],
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def speak(text):
    try:
        _speak_piper(text)  # plays itself (piper + sox robotize)
        return
    except Exception as e:
        log("ELBERR", f"piper failed ({e}), espeak fallback.")
        p1 = subprocess.Popen(["espeak-ng", "--stdout", "-s", "135", "-v", "en", text],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        subprocess.run(["aplay", "-q", "-D", SPK], stdin=p1.stdout,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def round_trip(user_text):
    log("YOU", user_text)
    set_mood("sleepy")  # small thinking eyes
    reply = ask_llm(user_text)
    log("ELBERR", reply)
    set_mood("happy")   # ^ ^ while speaking
    speak(reply)
    set_mood("normal")  # big idle eyes
    return reply


# --- structured commands: deterministic intents the tiny LLM must never
# improvise (spec section 47: the control layer owns the vocabulary, the
# model only chats). Keyword fast-path; everything else falls to chat. ---

# --- place this robot lives (set on first run; ask the human) ---
# Used for local time (via system timezone) and Open-Meteo weather.
# Kuala Lumpur default; correct me and I'll move it.
PLACE_NAME = "Kuala Lumpur"
PLACE_LAT, PLACE_LON = 3.1390, 101.6869
PLACE_TZ = "Asia/Kuala_Lumpur"
PHOTOS = os.path.join(BRAIN, "photos")


def _sys_status():
    import re as _re
    up = subprocess.run(["uptime", "-p"], capture_output=True,
                        text=True).stdout.strip().replace("up ", "")
    t = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True,
                       text=True).stdout.strip().replace("temp=", "")
    mem = subprocess.run(["free", "-m"], capture_output=True,
                         text=True).stdout.splitlines()[1].split()
    pct = int(mem[2]) * 100 // int(mem[1])
    return f"I am fine. Up {up}, {t}, memory {pct} percent full."


def _take_photo():
    os.makedirs(PHOTOS, exist_ok=True)
    path = os.path.join(PHOTOS, time.strftime("IMG_%Y%m%d_%H%M%S.jpg"))
    subprocess.run(["fswebcam", "-q", "-d", "/dev/video0", "-r", "1280x720",
                    "--no-banner", "--jpeg", "85", "-F", "5", path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=60)
    return path


def _say_datetime():
    import datetime as _dt
    now = _dt.datetime.now()
    day = now.day
    suf = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return now.strftime(f"%A, %B {day}{suf}, %I:%M %p").replace(" 0", " ")


_WMO = [(0, "clear sky"), (1, "mostly clear"), (2, "partly cloudy"),
        (3, "overcast"), (45, "foggy"), (48, "foggy"), (51, "light drizzle"),
        (53, "drizzle"), (55, "heavy drizzle"), (61, "light rain"),
        (63, "rain"), (65, "heavy rain"), (71, "light snow"),
        (73, "snow"), (75, "heavy snow"), (80, "light showers"),
        (81, "showers"), (82, "heavy showers"), (95, "thunderstorms")]


def _wmo_word(code):
    best = "unsettled"
    for c, w in sorted(_WMO):
        if code >= c:
            best = w
    return best


def _say_weather():
    import json as _json
    import urllib.request as _url
    q = (f"https://api.open-meteo.com/v1/forecast?latitude={PLACE_LAT}"
         f"&longitude={PLACE_LON}&current=temperature_2m,weather_code")
    with _url.urlopen(q, timeout=20) as r:
        cur = _json.load(r)["current"]
    temp = round(cur["temperature_2m"])
    cond = _wmo_word(int(cur["weather_code"]))
    return f"In {PLACE_NAME} it is {temp} degrees and {cond}."


def _color_name(b, g, r):
    import cv2 as _cv2
    import numpy as _np
    h, s, v = _cv2.cvtColor(
        _np.uint8([[[b, g, r]]]), _cv2.COLOR_BGR2HSV)[0][0].tolist()
    if v < 50:
        return "black"
    if s < 40:
        return "white" if v > 180 else "gray"
    if h < 10 or h >= 160:
        return "red"
    if h < 25:
        return "orange"
    if h < 35:
        return "yellow"
    if h < 85:
        return "green"
    if h < 130:
        return "blue"
    return "purple"


def _describe_scene(path):
    """Classical CV only (1GB Pi can't host a VLM): faces, light, colors."""
    import cv2 as _cv2
    img = _cv2.imread(path)
    if img is None:
        raise RuntimeError("unreadable photo")
    small = _cv2.resize(img, (320, 240))
    gray = _cv2.cvtColor(small, _cv2.COLOR_BGR2GRAY)
    nfaces = 0
    try:
        det = _cv2.FaceDetectorYN.create(
            os.path.join(BRAIN, "models", "yunet_2023mar.onnx"), "",
            (320, 240), score_threshold=0.6)
        _, faces = det.detect(small)
        nfaces = 0 if faces is None else len(faces)
    except Exception:
        nfaces = 0
    mean = float(gray.mean())
    light = "dark" if mean < 60 else ("dim" if mean < 120 else "bright")
    tiny = _cv2.resize(img, (32, 32)).reshape(-1, 3).astype("float32")
    _, _, centers = _cv2.kmeans(
        tiny, 3, None,
        (_cv2.TERM_CRITERIA_EPS + _cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0),
        2, _cv2.KMEANS_PP_CENTERS)
    names = []
    for b, g, r in centers.astype(int).tolist():
        name = _color_name(b, g, r)
        if name not in names:
            names.append(name)
    while len(names) < 2:  # dark rooms have one color: pad it
        names.append(names[0])
    if nfaces == 1:
        who = "I see you! "
    elif nfaces > 1:
        who = f"I see {nfaces} faces. "
    else:
        who = "I see no faces. "
    return f"{who}The room is {light}, mostly {names[0]} and {names[1]}."


def handle_command(text):
    """Returns True if text was a command (already executed)."""
    t = text.lower()
    if any(k in t for k in ("take a photo", "take a picture", "selfie", "cheese")):
        set_mood("happy")
        try:
            path = _take_photo()
            log("ELBERR", f"photo saved {path}")
            open("/tmp/face_photo", "w").write(path + "\n")  # face shows it...
            set_mood("photo")
            speak("Cheese! Saved it.")  # ...while this plays (~4s)
            time.sleep(2.5)  # ...plus a beat, ~7s total
        except Exception as e:
            log("ELBERR", f"camera failed: {e}")
            speak("My camera did not cooperate.")
        finally:
            try:
                os.remove("/tmp/face_photo")  # ...then eyes return
            except OSError:
                pass
        set_mood("normal")
        return True
    if any(k in t for k in ("go to sleep", "sleep now", "good night")):
        speak("Sleeping now.")
        return "sleep"
    if any(k in t for k in ("wake up", "wake up elberr")):
        speak("I am awake.")
        return "wake"
    if any(k in t for k in ("status", "how are you", "system status")):
        set_mood("happy")
        status = _sys_status()
        log("ELBERR", status)
        speak(status)
        set_mood("normal")
        return True
    if any(k in t for k in ("help", "what can you do")):
        set_mood("happy")
        help_text = ("Try: take a photo. Status. What time is it. What is the "
                     "weather. Go to sleep. Wake up. Or just talk to me.")
        log("ELBERR", help_text)
        speak(help_text)
        set_mood("normal")
        return True
    if any(k in t for k in ("what time", "the time", "what date", "today's date",
                            "what day is", "day is it")):
        set_mood("happy")
        ans = "It is " + _say_datetime() + "."
        log("ELBERR", ans)
        speak(ans)
        set_mood("normal")
        return True
    if any(k in t for k in ("weather", "temperature outside", "is it raining",
                            "is it hot", "is it cold")):
        set_mood("happy")
        try:
            ans = _say_weather()
        except Exception as e:
            ans = "I could not reach the weather service."
            log("ELBERR", f"weather failed: {e}")
        log("ELBERR", ans)
        speak(ans)
        set_mood("normal")
        return True
    if any(k in t for k in ("what do you see", "describe", "look at me",
                            "do you see me", "who is there", "who is it")):
        try:
            path = _take_photo()
            desc = _describe_scene(path)
        except Exception as e:
            desc = "My eyes did not cooperate."
            log("ELBERR", f"describe failed: {e}")
        log("ELBERR", desc)
        open("/tmp/face_photo", "w").write(path + "\n")
        set_mood("photo")
        speak(desc)
        time.sleep(2.0)
        try:
            os.remove("/tmp/face_photo")
        except OSError:
            pass
        set_mood("normal")
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", default=None, help="text-only round trip, no mic")
    args = ap.parse_args()
    if args.once:
        if handle_command(args.once) is False:
            round_trip(args.once)
        return
    set_mood("normal")
    log("ELBERR", "voice loop online. Speak after the blip.")
    import math as _math
    import signal as _signal
    # clear any recorder orphaned by a previous killed loop (-x matches
    # the process name only, so it can never match our own shell)
    subprocess.run(["pkill", "-x", "arecord"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _signal.signal(_signal.SIGTERM, _cleanup)
    last_speech, sleeping = time.time(), False
    dead_streak, last_reset = 0, 0.0
    while True:
        try:
            set_mood("sleep" if sleeping else "listening")
            if dead_streak >= 3:
                # Mic wedged. This camera's endpoint only recovers via USB
                # re-enumeration; heal it ourselves (max once per 5 min),
                # else back off quietly instead of blipping constantly.
                if time.time() - last_reset > 300:
                    last_reset = time.time()
                    log("ELBERR", "mic dead, resetting USB audio.")
                    subprocess.run(
                        ["sudo", "-n", "/usr/local/bin/usb-audio-reset"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=60)
                    time.sleep(10)  # re-enumerate
                    set_mood("listening")
                else:
                    log("ELBERR", "mic dead, backing off 60s.")
                    set_mood("sleep")
                    time.sleep(60)
                dead_streak = 0
                continue
            blip()
            pcm = listen()
            n = len(pcm) // 2
            if n == 0:
                dead_streak += 1
                log("ELBERR", "mic gave no bytes.")
                continue
            samp = struct.unpack(f"<{n}h", pcm)
            rms = _math.sqrt(sum(s * s for s in samp) / n)
            peak = max(abs(s) for s in samp)
            text = stt(pcm)
            dead_streak = 0  # mic delivered audio; only speech was absent
            if not text:
                log("ELBERR", f"heard nothing (rms={rms:.0f} peak={peak}).")
                if not sleeping and time.time() - last_speech > 300:
                    sleeping = True
                    log("ELBERR", "quiet for 5 min -> sleep.")
                continue
            if sleeping:
                sleeping = False
                log("ELBERR", "woke up.")
            last_speech = time.time()
            dead_streak = 0
            log("ELBERR", f"mic level rms={rms:.0f} peak={peak}.")
            cmd = handle_command(text)
            if cmd == "sleep":
                sleeping = True
            elif cmd != "wake":
                if not cmd:
                    round_trip(text)
        except KeyboardInterrupt:
            log("ELBERR", "going to sleep.")
            set_mood("sleep")
            _cleanup()
            break


if __name__ == "__main__":
    sys.exit(main())

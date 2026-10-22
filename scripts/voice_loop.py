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
import queue
import struct
import subprocess
import sys
import threading
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


def _play_wav(path, device=SPK):
    """Play through a file lock: concurrent speakers (loop blips vs polls
    vs --once tests) queue instead of colliding on the USB device."""
    subprocess.run(["flock", "/tmp/elberr-audio.lock",
                    "aplay", "-q", "-D", device, path],
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def blip(freq=880, ms=80):
    tone = os.path.join("/tmp", "blip.wav")
    subprocess.run(
        ["python3", "-c",
         f"import wave,struct,math;w=wave.open('{tone}','wb');"
         "w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);"
         f"w.writeframes(b''.join(struct.pack('<h',int(9000*math.sin(2*math.pi*{freq}*i/16000))) for i in range(int(16000*{ms}/1000))))"],
        check=True)
    try:
        _play_wav(tone)
    except Exception:
        pass


def _rms(samples):
    import math as _math
    return _math.sqrt(sum(s * s for s in samples) / max(len(samples), 1))


_ARECORD = None  # current recorder, so signals never orphan it
_STREAM = None    # capture window on the mic (owned by _capture_loop)
_STOP = threading.Event()
# Audio queue: the capture thread drains the USB mic into this queue and the
# main thread does the STT. Without this split, Vosk's per-chunk decoding
# (which can take longer than real time) makes ALSA overrun the capture
# buffer -> "overrun!!!" -> the mic stream dies.
_AUDIO_Q = queue.Queue(maxsize=60)   # ~12 s of audio, newest wins
CHUNK_BYTES = RATE * 2 * 2 // 5      # 0.2 s stereo S16


def _set_mic_gain(pct=50):
    """Set the mic capture level. USB re-enumeration restores the 95%
    default (clipping), so this runs at startup and after every reset."""
    try:
        card = ""
        with open("/proc/asound/cards") as f:
            for line in f:
                if "PSE0510" in line:
                    card = line.split()[0].rstrip(":")
                    break
        if card:
            subprocess.run(["amixer", "-c", card, "set", "Mic", f"{pct}%"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10)
    except Exception:
        pass


def _open_stream():
    """Open a capture window on the mic.

    NOTE on this Philips PSE0510: the device dies on close/reopen, so the
    window is a long-ish single arecord (-d 60) that we read progressively,
    and the device is re-enumerated between windows (see _reset_mic).
    """
    global _STREAM
    _close_stream()
    err = open("/tmp/arecord_err.log", "ab")
    _STREAM = subprocess.Popen(
        ["arecord", "-q", "-D", MIC, "-f", "S16_LE", "-r", str(RATE),
         "-c", "2", "-d", "60", "-t", "raw"],
        stdout=subprocess.PIPE, stderr=err)
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


def _reset_mic():
    """Re-enumerate the USB mic device. This camera mic only survives one
    open per enumeration, so the device must be re-bound between windows.
    The stream must be released BEFORE the unbind, or the unbind fails."""
    _close_stream()
    time.sleep(0.5)
    try:
        p = subprocess.run(["sudo", "-n", "/usr/local/bin/usb-audio-reset", "auto"],
                           capture_output=True, text=True, timeout=60)
        log("ELBERR", f"mic reset: rc={p.returncode} "
                      f"{(p.stdout or '').strip()} {(p.stderr or '').strip()}")
    except Exception as e:
        log("ELBERR", f"mic reset failed: {e}")
    time.sleep(3)


# Wake phrases. IMPORTANT: every word must exist in the Vosk model's
# vocabulary or it is silently dropped from the grammar ("elberr" is NOT in
# it, so a wake phrase like "hey elberr" cannot work). Keep plain English.
# Override with ELBERR_WAKE="hey dude,hey man".
WAKE_PHRASES = [p.strip() for p in os.environ.get(
    "ELBERR_WAKE", "hey dude,hey man,hey buddy").split(",") if p.strip()]
# Set ELBERR_NO_WAKE=1 to disable wake gating (always listening).
NO_WAKE = os.environ.get("ELBERR_NO_WAKE", "") == "1"
# Chunks (0.2s each) the STT partial must stay identical before we treat the
# utterance as finished and start thinking. 3 = 0.6s of stillness.
STABLE_CHUNKS = 3
CHUNK_S = 0.2
SILENCE_CHUNKS_TO_ABANDON = 60  # 12 s of silence after wake -> give up
                                # (the human needs time to speak the command)


class Ears:
    """Two parallel Vosk recognizers over one audio stream.

    rec_wake is grammar-constrained to the wake phrases; rec_cmd is free-form.
    The wake recognizer is cheap to poll and tells us when to start capturing
    a command. rec_cmd's partial results let us start thinking while the
    user is still finishing their sentence.
    """

    def __init__(self):
        from vosk import KaldiRecognizer, Model
        try:
            from vosk import SetLogLevel
            SetLogLevel(-1)  # silence Vosk's INFO spam (it floods the journal)
        except Exception:
            pass
        self.model = Model(VOSK_DIR)
        self.rec_wake = KaldiRecognizer(self.model, RATE)
        self.rec_wake.SetGrammar(json.dumps(WAKE_PHRASES + ["[unk]"]))
        self.rec_cmd = KaldiRecognizer(self.model, RATE)
        self.rec_cmd.SetWords(False)
        self.last_partial = ""
        self.stable = 0
        self.since_flush = 0.0
        self.chunk_s = 0.2
        # A recognizer that never finalises grows an unbounded lattice and
        # eventually spends MINUTES in lattice determinisation (Vosk warns
        # "size exceeds maximum 50000000 bytes"). We therefore force a
        # flush if an utterance has been open for this long.
        self.max_utterance_s = 8.0

    def reset_cmd(self):
        self.rec_cmd.Reset()
        self.last_partial = ""
        self.stable = 0
        self.since_flush = 0.0

    def feed(self, pcm, level):
        """Feed one chunk. Returns (kind, text).

        kind: 'wake'   -> wake phrase spotted
              'stable' -> command text looks complete (partial unchanged)
              'final'  -> recognizer finalised a phrase
              None     -> nothing yet
        """
        self.rec_wake.AcceptWaveform(pcm)
        self.rec_cmd.AcceptWaveform(pcm)
        self.since_flush += self.chunk_s
        quiet = level < 600
        overdue = self.since_flush > self.max_utterance_s

        if not NO_WAKE:
            w = json.loads(self.rec_wake.PartialResult()).get("partial", "")
            if len(w.split()) >= 2:
                # Reset the wake recogniser, otherwise it keeps re-matching
                # the phrase in its buffer and every later chunk is
                # classified "wake" (the command would never be heard).
                self.rec_wake.Reset()
                return ("wake", w.strip())
            if quiet or overdue:
                json.loads(self.rec_wake.Result())
                if quiet:
                    self.since_flush = 0.0
        p = json.loads(self.rec_cmd.PartialResult()).get("partial", "")
        if p.strip():
            if p == self.last_partial:
                self.stable += 1
            else:
                self.stable = 0
                self.last_partial = p
            if self.stable >= STABLE_CHUNKS:
                return ("stable", p.strip())
            return (None, p.strip())
        if quiet or overdue:
            # only finalise on silence (or when the utterance is overdue) —
            # calling Result() mid-utterance would cut the state short
            final = json.loads(self.rec_cmd.Result()).get("text", "").strip()
            self.since_flush = 0.0
            if final:
                return ("final", final)
        return (None, "")


def _capture_loop():
    """Owns the microphone.

    Opens a capture window, drains it into _AUDIO_Q as fast as the device
    delivers, and re-enumerates the USB device when the window ends (this
    camera mic only survives one open per enumeration). This thread must
    never block on STT - that is the whole point of the queue.
    """
    while not _STOP.is_set():
        proc = _open_stream()
        try:
            while not _STOP.is_set() and proc.poll() is None:
                raw = _read_exact(proc, CHUNK_BYTES, timeout_s=2.0)
                if not raw:
                    continue
                try:
                    _AUDIO_Q.put_nowait(raw)
                except queue.Full:
                    # keep the freshest audio: drop the oldest
                    try:
                        _AUDIO_Q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        _AUDIO_Q.put_nowait(raw)
                    except queue.Full:
                        pass
        except Exception as e:
            log("ELBERR", f"capture error: {e}")
        finally:
            _close_stream()
        if _STOP.is_set():
            break
        log("ELBERR", "mic window ended, re-enumerating.")
        _reset_mic()


def _cleanup(signum=None, frame=None):
    _STOP.set()
    _close_stream()
    raise SystemExit(0)




def ask_llm(user_text):
    """Chat via local Ollama server (needs: ollama serve + ollama pull qwen2.5:0.5b).

    Server keeps the model resident, so turns take ~3s instead of ~20s.
    """
    import json as _json
    import urllib.request as _url
    body = _json.dumps({
        "model": "qwen2.5:0.5b",
        "messages": [
            {"role": "system",
             "content": "You are Elberr, a cute desk robot. One short sentence."},
            {"role": "user", "content": user_text},
        ],
        "stream": False,
        # keep the model resident: otherwise Ollama unloads it after 5 min
        # idle and the next turn pays a ~30s reload.
        "keep_alive": "30m",
        "options": {
            "num_predict": 16,
            "temperature": 0.7,
        },
    }).encode()
    try:
        req = _url.Request("http://localhost:11434/api/chat",
                           data=body, headers={"Content-Type": "application/json"})
        with _url.urlopen(req, timeout=120) as r:
            data = _json.load(r)
    except Exception as e:  # server down? log and stay charming
        log("ELBERR", f"brain unreachable: {e}")
        return "Hmm."
    reply = data.get("message", {}).get("content", "").strip()
    return " ".join(reply.split())[:280] or "Hmm."


def _speak_piper(text):
    """Espeak-ng voice with sox robotize (pitch down) for the Elberr feel.
    No wyoming-piper needed — espeak-ng is already on the Pi."""
    subprocess.run(["espeak-ng", "-w", "/tmp/elberr-say.wav",
                    "-s", "145", "-v", "en", text],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=True)
    subprocess.run(["sox", "/tmp/elberr-say.wav", "/tmp/elberr-robot.wav",
                    "pitch", "-300"],
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    _play_wav("/tmp/elberr-robot.wav")


def speak(text):
    _speak_piper(text)


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

# --- servo link (Wemos bridge over USB serial) ---
# Neck joint targets in radians. Centre = 1.57 (90 deg servo = centred).
SERVO = None


def _servo_connect():
    """(Re)connect to the Wemos. The ttyUSB number shifts whenever another
    USB device re-enumerates, so we look the board up by USB ID."""
    global SERVO
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from servo_link import ServoLink, find_wemos_port
        port = find_wemos_port()
        if not port:
            return None
        link = ServoLink(port=port)
        link.connect()
        log("ELBERR", f"servo link up on {port}.")
        return link
    except Exception as e:
        log("ELBERR", f"servo link unavailable: {e}")
        return None


SERVO = None
if os.environ.get("ELBERR_NO_SERVO") == "1":
    # Debug: the Wemos shares the USB hub with the mic and reboots when we
    # open its serial port, which can disturb the mic's audio endpoint.
    log("ELBERR", "servo link disabled (ELBERR_NO_SERVO=1).")
else:
    SERVO = _servo_connect()


def _servo_cmd(joints, reply):
    """Send joint targets to the Wemos bridge. Returns True if handled."""
    global SERVO
    if SERVO is None:
        SERVO = _servo_connect()  # try to (re)connect
    if SERVO is None:
        speak("My neck is offline right now.")
        return True
    try:
        SERVO.set(joints)
    except Exception as e:
        log("ELBERR", f"servo send failed: {e}")
        SERVO = None
        speak("My neck stopped listening.")
        return True
    speak(reply)
    return True



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
        want_desc = any(k in t for k in ("describe", "what do you see", "look at me",
                                         "do you see", "who is", "tell me about"))
        try:
            path = _take_photo()
            log("ELBERR", f"photo saved {path}")
            open("/tmp/face_photo", "w").write(path + "\n")  # face shows it...
            set_mood("photo")
            if want_desc:
                try:
                    desc = _describe_scene(path)
                except Exception as e:
                    desc = "My eyes did not cooperate."
                    log("ELBERR", f"describe failed: {e}")
                log("ELBERR", desc)
                speak("Cheese! " + desc)  # ...while this plays
            else:
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
        help_text = ("Try: take a photo. Look left, right, up, down, or straight "
                     "ahead. Nod. Stop. Look happy, surprised, angry, tired, "
                     "curious, or sleepy. Status. What time is it. Go to sleep. "
                     "Wake up. Or just talk.")
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
    # --- neck / servo commands (deterministic; the LLM never drives motors) ---
    # left_neck_pan is a 360 (continuous) servo: the bridge dead-reckons the
    # angle and contains it to 0-180 deg, so these are position targets.
    if any(k in t for k in ("look left", "turn left", "look to the left")):
        return _servo_cmd({"left_neck_pan": 0.60}, "Looking left.")
    if any(k in t for k in ("look right", "turn right", "look to the right")):
        return _servo_cmd({"left_neck_pan": 2.50}, "Looking right.")
    if any(k in t for k in ("look up", "look up at the sky", "tilt up")):
        return _servo_cmd({"up_neck_tilt": 2.10}, "Looking up.")
    if any(k in t for k in ("look down", "tilt down", "look at the floor")):
        return _servo_cmd({"up_neck_tilt": 0.90}, "Looking down.")
    if any(k in t for k in ("look straight", "look ahead", "face forward",
                            "center your head", "look at me")):
        return _servo_cmd({"left_neck_pan": 1.57, "up_neck_tilt": 1.57},
                          "Looking straight ahead.")
    if any(k in t for k in ("emergency stop", "stop everything", "stop moving",
                            "freeze", "halt")):
        if SERVO is not None:
            SERVO.estop()
            log("ELBERR", "e-stop sent to servo bridge.")
        speak("Stopping.")
        return True
    if any(k in t for k in ("resume", "clear the emergency stop", "reset the stop",
                            "start moving again")):
        if SERVO is not None:
            SERVO.reset()
            SERVO.enable()
            log("ELBERR", "e-stop cleared, bridge re-enabled.")
        speak("Moving again.")
        return True
    if any(k in t for k in ("nod", "shake your head", "say no")):
        if SERVO is not None:
            for i in range(3):
                SERVO.set({"up_neck_tilt": 1.35 if i % 2 == 0 else 1.75})
                time.sleep(0.18)
            SERVO.set({"up_neck_tilt": 1.57})
        speak("No no no.")
        return True

    for mood, keys, line in [        ("happy", ("look happy", "be happy", "smile", "seem happy"), "Yay!"),
        ("surprised", ("look surprised", "be surprised", "surprise me"), "Whoa!"),
        ("angry", ("look angry", "be angry", "act angry", "get angry"), "Grr."),
        ("tired", ("look tired", "be tired", "act tired"), "So sleepy."),
        ("curious", ("look curious", "be curious", "act curious"), "Hmm?"),
        ("sleepy", ("look sleepy", "be sleepy"), "Eyes heavy."),
        ("normal", ("look normal", "neutral face", "normal face", "calm down"), "Okay."),
        ("laugh", ("make me laugh", "be funny", "tell me a joke"), "Ha ha ha!"),
        ("confused", ("confused", "look confused", "are you confused"), "Huh?"),
    ]:
        if any(k in t for k in keys):
            set_mood(mood)
            log("ELBERR", f"mood -> {mood}")
            speak(line)
            set_mood("normal")
            return True
    if any(k in t for k in ("what do you see", "describe", "look at me",
                            "do you see me", "who is there", "who is it")):
        path = None
        try:
            path = _take_photo()
            desc = _describe_scene(path)
        except Exception as e:
            desc = "My eyes did not cooperate."
            log("ELBERR", f"describe failed: {e}")
        log("ELBERR", desc)
        if path is not None:
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
    log("ELBERR", f"wake phrases: {', '.join(WAKE_PHRASES) if not NO_WAKE else 'DISABLED (always listening)'}")
    import math as _math
    import signal as _signal
    # clear any recorder orphaned by a previous killed loop (-x matches
    # the process name only, so it can never match our own shell)
    subprocess.run(["pkill", "-x", "arecord"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _set_mic_gain()
    _signal.signal(_signal.SIGTERM, _cleanup)
    last_speech, sleeping = time.time(), False
    dead_streak, last_reset = 0, 0.0
    ears = Ears()
    armed = False           # wake heard -> capturing a command
    silence = 0            # chunks of silence while armed
    # capture runs in its own thread so STT can never overrun the ALSA buffer
    cap = threading.Thread(target=_capture_loop, daemon=True)
    cap.start()
    while True:
        try:
            if not armed:
                set_mood("sleep" if sleeping else "listening")
            # audio comes from the capture thread's queue: this thread may
            # take its time with STT without overrunning the ALSA buffer.
            try:
                raw = _AUDIO_Q.get(timeout=2.0)
            except queue.Empty:
                continue
            dead_streak = 0
            n = len(raw) // 2
            stereo = struct.unpack(f"<{n}h", raw[:n * 2])
            mono = struct.pack(f"<{n // 2}h",
                               *[(a + b) // 2 for a, b in
                                 zip(stereo[0::2], stereo[1::2])])
            level = _rms(struct.unpack(f"<{n // 2}h", mono))

            kind, text = ears.feed(mono, level)

            if not armed:
                if kind == "wake":
                    if sleeping:
                        sleeping = False
                        log("ELBERR", "woke up.")
                    log("ELBERR", f"wake phrase heard ({text}).")
                    ears.reset_cmd()
                    armed = True
                    silence = 0
                    blip()  # "I'm listening"
                    set_mood("listening")
                continue

            # ---- armed: capturing a command ----
            if kind in ("stable", "final") and text:
                log("ELBERR", f"mic level rms={level:.0f}.")
                cmd = handle_command(text)
                if cmd == "sleep":
                    sleeping = True
                elif cmd != "wake":
                    if not cmd:
                        round_trip(text)
                armed = False
                ears.reset_cmd()
                set_mood("normal")
                continue
            if not text:
                silence += 1
                if silence >= SILENCE_CHUNKS_TO_ABANDON:
                    log("ELBERR", "nothing after wake, back to idle.")
                    armed = False
                    ears.reset_cmd()
                    set_mood("normal")
            else:
                silence = 0
        except KeyboardInterrupt:
            log("ELBERR", "going to sleep.")
            set_mood("sleep")
            _cleanup()
            break


if __name__ == "__main__":
    sys.exit(main())

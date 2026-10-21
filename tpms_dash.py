#!/usr/bin/env python3
"""
tpms_dash.py - Live 4-corner TPMS dashboard using rtl_433 + an RTL-SDR dongle.

Runs rtl_433 in the background, keeps only your car's four sensors (from
sensors.json), shows pressure/temperature per corner with colour-coded limits,
and logs every reading to a CSV file per session.

Works on Windows and Linux.

Usage:
    python tpms_dash.py                       # live, rtl_433 on PATH or next to this script
    python tpms_dash.py --rtl433 C:\\rtl_433\\rtl_433.exe
    python tpms_dash.py --fullscreen
    python tpms_dash.py --demo                # fake data, no dongle needed
    python tpms_dash.py --replay samples/2026-10-21_morning_drive.csv             # real time
    python tpms_dash.py --replay samples/2026-10-21_morning_drive.csv --speed 10  # 10x faster

Keys: F = toggle fullscreen, Esc / Q = quit
Replay keys: Space = pause/resume, Up/Down (or +/-) = double/halve speed, Right = skip 60 s

Requires: pip install pygame
"""

import argparse
import csv
import json
import os
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

import pygame

# --------------------------------------------------------------------------
# CONFIG - edit these
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
SENSORS_FILE = os.path.join(HERE, "sensors.json")   # your car's sensor IDs (not committed)


def load_sensors(path=SENSORS_FILE):
    """sensors.json maps corner -> sensor ID, e.g. {"FL": "1a2b3c4d", ...}.
    Returns the reverse map: sensor ID -> corner."""
    if not os.path.isfile(path):
        sys.exit(f"Missing {os.path.basename(path)}. Copy sensors.example.json to sensors.json "
                 "and fill in your sensor IDs (see README: 'Finding your sensor IDs').")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return {str(sid).strip().lower(): corner for corner, sid in cfg.items()
            if corner in ("FL", "FR", "RL", "RR")}


SENSORS = load_sensors()    # sensor ID -> corner
FREQ = "315M"

# Pressure limits (psi). Amber = warning band, red = outside alarm limits.
PSI_ALARM_LOW = 26.0
PSI_WARN_LOW = 30.0
PSI_WARN_HIGH = 40.0
PSI_ALARM_HIGH = 44.0

# Sensor air temperature limits (deg C)
TEMP_WARN_C = 60.0
TEMP_ALARM_C = 75.0

STALE_AFTER_S = 300     # grey out a corner with no update for this long
                        # (your sensors send roughly every 90-100 s in normal mode)
DUP_WINDOW_S = 3.0      # each transmission repeats 3-4x in a burst; log it once
WINDOW_SIZE = (800, 480)  # official Pi 7" screen resolution
# --------------------------------------------------------------------------

CORNERS = ["FL", "FR", "RL", "RR"]

GREEN = (40, 160, 80)
AMBER = (215, 150, 20)
RED = (200, 40, 40)
GREY = (70, 70, 75)
BG = (15, 15, 18)
FG = (240, 240, 240)
DIM = (150, 150, 155)


# ---------------------------------------------------------------- parsing --
def normalize_id(raw):
    """rtl_433 reports IDs as hex strings or integers depending on decoder."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return f"{raw:08x}"
    s = str(raw).strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return s.zfill(8)


def extract_reading(msg):
    """Pull pressure (psi) and temp (C) out of an rtl_433 JSON message.
    Different TPMS decoders use different field names, so check them all."""
    psi = None
    if "pressure_PSI" in msg:
        psi = float(msg["pressure_PSI"])
    elif "pressure_kPa" in msg:
        psi = float(msg["pressure_kPa"]) * 0.1450377
    elif "pressure_bar" in msg:
        psi = float(msg["pressure_bar"]) * 14.50377
    elif "psi" in msg:                      # this dashboard's own CSV logs
        psi = float(msg["psi"])

    temp_c = None
    if "temperature_C" in msg:
        temp_c = float(msg["temperature_C"])
    elif "temperature_F" in msg:
        temp_c = (float(msg["temperature_F"]) - 32) / 1.8
    elif "temp_c" in msg:
        temp_c = float(msg["temp_c"])

    return psi, temp_c


def parse_line(line):
    """Return (corner, sensor_id, psi, temp_c, msg) for our sensors, else None."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    sid = normalize_id(msg.get("id"))
    corner = SENSORS.get(sid)
    if corner is None and msg.get("corner") in CORNERS:
        corner = msg["corner"]      # replaying one of this dashboard's own logs
    if corner is None:
        return None
    psi, temp_c = extract_reading(msg)
    return corner, sid, psi, temp_c, msg


# ---------------------------------------------------------------- sources --
def find_rtl433(user_path):
    if user_path:
        return user_path
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("rtl_433.exe", "rtl_433"):
        p = os.path.join(here, name)
        if os.path.isfile(p):
            return p
    found = shutil.which("rtl_433")
    if found:
        return found
    sys.exit("Could not find rtl_433. Pass --rtl433 <path> or put it next to this script.")


def rtl433_reader(path, out_q, status):
    cmd = [path, "-f", FREQ, "-M", "level", "-F", "json"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
    except OSError as e:
        status["text"] = f"Failed to start rtl_433: {e}"
        return
    status["text"] = "Listening on " + FREQ
    status["proc"] = proc
    for line in proc.stdout:
        parsed = parse_line(line)
        if parsed:
            out_q.put(parsed)
        elif "No supported devices" in line or "usb_claim_interface" in line:
            status["text"] = "SDR error: " + line.strip()
    status["text"] = "rtl_433 exited"


class Clock:
    """Wall clock in live mode; in replay mode a 'log clock' that can run faster,
    pause, or skip ahead, so ages and stale timers match the original drive."""

    def __init__(self, replay=False, speed=1.0):
        self.replay = replay
        self.speed = speed
        self.paused = False
        self.anchor_log = None      # log time at anchor_wall
        self.anchor_wall = None

    def start(self, t_log):
        self.anchor_log, self.anchor_wall = t_log, time.time()

    def now(self):
        if not self.replay or self.anchor_log is None:
            return time.time()
        if self.paused:
            return self.anchor_log
        return self.anchor_log + (time.time() - self.anchor_wall) * self.speed

    def _reanchor(self):
        self.anchor_log, self.anchor_wall = self.now(), time.time()

    def set_speed(self, s):
        if self.anchor_log is not None:
            self._reanchor()
        self.speed = max(0.25, min(s, 256.0))

    def toggle_pause(self):
        if self.anchor_log is None:
            return
        if self.paused:
            self.anchor_wall = time.time()
            self.paused = False
        else:
            self._reanchor()
            self.paused = True

    def skip(self, seconds):
        if self.anchor_log is not None:
            self._reanchor()
            self.anchor_log += seconds


CLOCK = Clock()


def load_log(path):
    """Read a saved log into a time-sorted list of (t, parsed reading).
    Accepts this dashboard's CSV logs, rtl_433 CSV (-F csv:x.csv) or JSON lines (-F json:x.json)."""
    with open(path, encoding="utf-8", newline="") as f:
        if path.lower().endswith(".csv"):
            lines = [json.dumps({k: v for k, v in r.items() if v not in ("", None)})
                     for r in csv.DictReader(f)]
        else:
            lines = f.readlines()
    events = []
    for line in lines:
        parsed = parse_line(line)
        if not parsed:
            continue
        try:
            t = datetime.fromisoformat(str(parsed[4].get("time"))).timestamp()
        except ValueError:
            continue
        events.append((t, parsed))
    events.sort(key=lambda e: e[0])
    return events


def replay_reader(path, out_q, status):
    events = load_log(path)
    status["replay_name"] = os.path.basename(path)
    if not events:
        status["text"] = f"No readings for your sensor IDs in {os.path.basename(path)}"
        return
    status["replay_end"] = events[-1][0]
    CLOCK.start(events[0][0] - 1.0)
    for t, parsed in events:
        while CLOCK.now() < t:
            time.sleep(0.02)
        out_q.put(parsed)
    status["finished"] = True
    if not CLOCK.paused:
        CLOCK.toggle_pause()        # freeze the ages at the end of the log


def demo_reader(out_q, status):
    status["text"] = "DEMO MODE - fake data"
    base = {"FL": 33.0, "FR": 33.5, "RL": 32.0, "RR": 32.5}
    temps = {c: 20.0 for c in CORNERS}
    ids = {v: k for k, v in SENSORS.items()}
    t0 = time.time()
    while True:
        corner = random.choice(CORNERS)
        warm = min((time.time() - t0) / 60.0, 1.0)      # "track session" heat-up over 1 min
        temps[corner] = 20 + 45 * warm + random.uniform(-2, 2)
        psi = base[corner] + 6 * warm + random.uniform(-0.3, 0.3)
        if corner == "RR":
            psi -= 8 * warm                              # simulate a slow leak on RR
        msg = {"model": "demo", "id": ids[corner], "pressure_PSI": round(psi, 1),
               "temperature_C": round(temps[corner], 1), "battery_ok": 1, "snr": 15.0}
        out_q.put((corner, ids[corner], msg["pressure_PSI"], msg["temperature_C"], msg))
        time.sleep(random.uniform(0.3, 1.0))


# ---------------------------------------------------------------- logging --
class SessionLog:
    FIELDS = ["time", "corner", "id", "psi", "temp_c", "status", "alert_mode", "snr", "rssi", "model"]

    def __init__(self, folder="logs"):
        os.makedirs(folder, exist_ok=True)
        name = datetime.now().strftime("tpms_%Y%m%d_%H%M%S.csv")
        self.path = os.path.join(folder, name)
        self.f = open(self.path, "w", newline="", encoding="utf-8")
        self.w = csv.writer(self.f)
        self.w.writerow(self.FIELDS)

    def write(self, corner, sid, psi, temp_c, msg):
        self.w.writerow([
            datetime.now().isoformat(timespec="seconds"), corner, sid,
            "" if psi is None else round(psi, 2),
            "" if temp_c is None else round(temp_c, 1),
            msg.get("status", ""), int(alert_mode(msg)),
            msg.get("snr", ""), msg.get("rssi", ""), msg.get("model", ""),
        ])
        self.f.flush()

    def close(self):
        self.f.close()


def alert_mode(msg):
    """Your sensors report status 128 normally and 132 (bit 0x04 set) after a
    pressure change, when they switch to fast transmissions (~every 18 s)."""
    try:
        return bool(int(msg.get("status", 0)) & 0x04)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- display --
def psi_colour(psi):
    if psi is None:
        return GREY
    if psi < PSI_ALARM_LOW or psi > PSI_ALARM_HIGH:
        return RED
    if psi < PSI_WARN_LOW or psi > PSI_WARN_HIGH:
        return AMBER
    return GREEN


def temp_colour(t):
    if t is None:
        return DIM
    if t >= TEMP_ALARM_C:
        return RED
    if t >= TEMP_WARN_C:
        return AMBER
    return FG


def worst(*colours):
    for c in (RED, AMBER, GREEN):
        if c in colours:
            return c
    return GREY


def draw(screen, fonts, state, status, log_path):
    w, h = screen.get_size()
    screen.fill(BG)
    big, mid, small = fonts
    now = CLOCK.now()

    # Simple car outline in the middle
    car = pygame.Rect(0, 0, int(w * 0.16), int(h * 0.62))
    car.center = (w // 2, int(h * 0.47))
    pygame.draw.rect(screen, (45, 45, 50), car, border_radius=30)
    pygame.draw.rect(screen, (90, 90, 95), car, width=2, border_radius=30)
    lbl = small.render("FRONT", True, DIM)
    screen.blit(lbl, lbl.get_rect(midtop=(car.centerx, car.top + 10)))

    pad = int(w * 0.03)
    bw = (w - car.width) // 2 - pad * 2
    bh = int(h * 0.38)
    boxes = {
        "FL": pygame.Rect(pad, pad, bw, bh),
        "FR": pygame.Rect(w - pad - bw, pad, bw, bh),
        "RL": pygame.Rect(pad, h - pad - bh - 30, bw, bh),
        "RR": pygame.Rect(w - pad - bw, h - pad - bh - 30, bw, bh),
    }

    for corner, rect in boxes.items():
        r = state.get(corner)
        stale = r is None or now - r["t"] > STALE_AFTER_S
        if stale:
            colour = GREY
        else:
            colour = worst(psi_colour(r["psi"]),
                           RED if temp_colour(r["temp"]) == RED else
                           AMBER if temp_colour(r["temp"]) == AMBER else GREEN)
        pygame.draw.rect(screen, colour, rect, border_radius=14)
        inner = rect.inflate(-8, -8)
        pygame.draw.rect(screen, BG, inner, border_radius=11)

        screen.blit(mid.render(corner, True, colour), (inner.x + 12, inner.y + 6))

        if r is None:
            t = mid.render("waiting...", True, DIM)
            screen.blit(t, t.get_rect(center=inner.center))
            continue

        psi_txt = "--" if r["psi"] is None else f"{r['psi']:.1f}"
        t = big.render(psi_txt, True, FG if not stale else DIM)
        tr = t.get_rect(center=(inner.centerx, inner.centery - 4))
        screen.blit(t, tr)
        u = small.render("psi", True, DIM)
        screen.blit(u, (tr.right + 4, tr.bottom - u.get_height() - 8))

        temp_txt = "--" if r["temp"] is None else f"{r['temp']:.0f}\u00b0C"
        t = mid.render(temp_txt, True, temp_colour(r["temp"]) if not stale else DIM)
        screen.blit(t, (inner.x + 12, inner.bottom - t.get_height() - 6))

        age = int(now - r["t"])
        a = small.render(f"{age}s ago", True, DIM)
        screen.blit(a, (inner.right - a.get_width() - 12, inner.bottom - a.get_height() - 8))

        if r.get("alert"):
            b = small.render("\u0394P", True, AMBER)   # sensor saw a pressure change
            screen.blit(b, (inner.right - b.get_width() - 12, inner.y + 10))

    if CLOCK.replay:
        state_txt = ("FINISHED" if status.get("finished") else
                     "PAUSED" if CLOCK.paused else f"{CLOCK.speed:g}x")
        clock_txt = datetime.fromtimestamp(now).strftime("%H:%M:%S") if CLOCK.anchor_log else "--:--:--"
        end = status.get("replay_end")
        left = f"  ({int(max(end - now, 0))//60}m left)" if end and not status.get("finished") else ""
        text = (status.get("text") or
                f"REPLAY {clock_txt}  {state_txt}{left}   |   Space pause   Up/Down speed   Right +60s")
    else:
        text = f"{status['text']}   |   log: {log_path}"
    bar = small.render(text, True, DIM)
    screen.blit(bar, (pad, h - bar.get_height() - 8))
    pygame.display.flip()


def make_fonts(size):
    h = size[1]
    return (pygame.font.SysFont(None, int(h * 0.22)),
            pygame.font.SysFont(None, int(h * 0.09)),
            pygame.font.SysFont(None, int(h * 0.055)))


# ------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser(description="FR-S TPMS dashboard (rtl_433)")
    ap.add_argument("--rtl433", help="path to rtl_433 executable")
    ap.add_argument("--demo", action="store_true", help="fake data, no SDR needed")
    ap.add_argument("--replay", help="replay a saved log (this dashboard's CSV, or rtl_433 .csv/.json)")
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier (1 = real time)")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--logdir", default=os.path.join(HERE, "logs"))
    ap.add_argument("--screenshot", help=argparse.SUPPRESS)  # save a PNG after N seconds and exit (testing)
    args = ap.parse_args()

    q = queue.Queue()
    status = {"text": "Starting...", "proc": None}
    if args.demo:
        target, targs = demo_reader, (q, status)
    elif args.replay:
        CLOCK.replay = True
        CLOCK.speed = args.speed
        status["text"] = ""
        target, targs = replay_reader, (args.replay, q, status)
    else:
        target, targs = rtl433_reader, (find_rtl433(args.rtl433), q, status)
    threading.Thread(target=target, args=targs, daemon=True).start()

    log = None if args.replay else SessionLog(args.logdir)   # don't re-log a replay
    pygame.init()
    pygame.display.set_caption("FR-S TPMS")
    flags = pygame.FULLSCREEN if args.fullscreen else pygame.RESIZABLE
    screen = pygame.display.set_mode((0, 0) if args.fullscreen else WINDOW_SIZE, flags)
    fonts = make_fonts(screen.get_size())
    clock = pygame.time.Clock()
    state = {}
    start = time.time()

    try:
        running = True
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False
                    elif ev.key == pygame.K_f:
                        pygame.display.toggle_fullscreen()
                        fonts = make_fonts(screen.get_size())
                    elif CLOCK.replay and not status.get("finished"):
                        if ev.key == pygame.K_SPACE:
                            CLOCK.toggle_pause()
                        elif ev.key in (pygame.K_UP, pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                            CLOCK.set_speed(CLOCK.speed * 2)
                        elif ev.key in (pygame.K_DOWN, pygame.K_MINUS, pygame.K_KP_MINUS):
                            CLOCK.set_speed(CLOCK.speed / 2)
                        elif ev.key == pygame.K_RIGHT:
                            CLOCK.skip(60)
                elif ev.type == pygame.VIDEORESIZE:
                    fonts = make_fonts(screen.get_size())

            while not q.empty():
                corner, sid, psi, temp_c, msg = q.get()
                now = CLOCK.now()
                if CLOCK.replay:                 # use the reading's own log time
                    try:
                        now = datetime.fromisoformat(str(msg.get("time"))).timestamp()
                    except ValueError:
                        pass
                prev = state.get(corner)
                is_dup = (prev is not None and now - prev["t"] < DUP_WINDOW_S
                          and prev["psi"] == psi and prev["temp"] == temp_c)
                state[corner] = {"psi": psi, "temp": temp_c, "t": now,
                                 "alert": alert_mode(msg)}
                if log and not is_dup:
                    log.write(corner, sid, psi, temp_c, msg)

            draw(screen, fonts, state, status, log.path if log else "")
            if args.screenshot and time.time() - start > 25:
                pygame.image.save(screen, args.screenshot)
                break
            clock.tick(10)
    finally:
        if log:
            log.close()
        if status.get("proc"):
            status["proc"].terminate()
        pygame.quit()


if __name__ == "__main__":
    main()

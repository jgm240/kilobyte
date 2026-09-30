#!/usr/bin/python3
"""Music Player: songs and playlists, with dancing bars.

    music.py [FILE | FOLDER | PLAYLIST.m3u ...]    (default: ~/Music)

ffmpeg decodes (so anything it knows plays), aplay plays, and the very same
samples feed the bars, which therefore move with the music.

Keys: ↑ ↓ choose, Enter play, Space pause, N next, P previous, ← → ten
seconds back and forward, + - volume, S shuffle, R repeat, L a playlist,
W save this list as a playlist, Q or Esc quit.
"""
import curses
import math
import os
import random
import subprocess
import sys
import threading
import time

sys.path.insert(0, "/usr/lib/kilobyte/py")
import kbui  # noqa: E402
from kbui import (BLACK, BLUE, CYAN, DARKGREY, LIGHTGREEN, LIGHTGREY, LIGHTRED,  # noqa: E402
                  WHITE, YELLOW)

MUSIC = os.path.expanduser("~/Music")
SONGS = (".mp3", ".ogg", ".oga", ".flac", ".wav", ".m4a", ".opus", ".aac", ".wma")
RATE = 44100
CHUNK = 4096                                 # frames read at a time (93 ms)
BANDS = 28


def songs_in(path):
    """The songs a file, folder or playlist stands for."""
    path = os.path.expanduser(path)
    if os.path.isdir(path):
        found = []
        for root, dirs, files in os.walk(path):
            dirs.sort()
            found += [os.path.join(root, f) for f in sorted(files) if f.lower().endswith(SONGS)]
        return found
    if path.lower().endswith((".m3u", ".m3u8")):
        found = []
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        found.append(line if os.path.isabs(line) else os.path.join(os.path.dirname(path), line))
        except OSError:
            pass
        return [s for s in found if os.path.exists(s)]
    return [path] if os.path.exists(path) else []


def probe(path):
    """(title, seconds) of a song."""
    title, seconds = os.path.splitext(os.path.basename(path))[0], 0.0
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=title,artist",
             "-of", "default=noprint_wrappers=1", path],
            capture_output=True, timeout=10).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return title, seconds
    tags = {}
    for line in out.split("\n"):
        key, _, value = line.partition("=")
        tags[key.lower().replace("tag:", "")] = value.strip()
    try:
        seconds = float(tags.get("duration", 0))
    except ValueError:
        pass
    if tags.get("title"):
        title = tags["title"] + (" - " + tags["artist"] if tags.get("artist") else "")
    return title, seconds


class Engine:
    """Plays one song: ffmpeg | this program | aplay."""

    def __init__(self):
        self.ffmpeg = self.aplay = self.thread = None
        self.playing = threading.Event()
        self.playing.set()
        self.stop_flag = False
        self.frames = 0                     # frames handed to aplay since the start
        self.offset = 0.0                   # where in the song this run started
        self.samples = [0] * 1024           # the newest mono samples, for the bars
        self.ended = False
        self.error = ""

    def start(self, path, position=0.0):
        self.stop()
        self.stop_flag, self.ended, self.error = False, False, ""
        self.frames, self.offset = 0, position
        self.playing.set()
        try:
            self.ffmpeg = subprocess.Popen(
                ["ffmpeg", "-loglevel", "quiet", "-ss", "%.2f" % position, "-i", path, "-vn",
                 "-f", "s16le", "-ac", "2", "-ar", str(RATE), "-"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.aplay = subprocess.Popen(
                ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-c", "2", "-r", str(RATE), "--buffer-time=250000", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.error = str(e)
            self.ended = True
            return
        self.thread = threading.Thread(target=self.pump, daemon=True)
        self.thread.start()

    def pump(self):
        ffmpeg, aplay = self.ffmpeg, self.aplay
        try:
            while not self.stop_flag:
                self.playing.wait()
                data = ffmpeg.stdout.read(CHUNK * 4)
                if not data:
                    break
                aplay.stdin.write(data)
                aplay.stdin.flush()
                self.frames += len(data) // 4
                # Mono, every other frame: enough for bars up to 10 kHz.
                n = len(data) // 8
                mono = [0] * n
                view = memoryview(data).cast("h") if len(data) % 2 == 0 else None
                if view is not None:
                    for i in range(n):
                        mono[i] = (view[i * 4] + view[i * 4 + 1]) >> 1
                    self.samples = (self.samples + mono)[-1024:]
        except (OSError, ValueError):
            if not self.stop_flag:
                self.error = "The sound could not be played (is there a sound card?)."
        if not self.stop_flag:
            try:
                aplay.stdin.close()
                aplay.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
            if aplay.returncode not in (0, None) and self.frames < RATE:
                self.error = "The sound could not be played (is there a sound card?)."
            self.ended = True

    def stop(self):
        self.stop_flag = True
        self.playing.set()
        for p in (self.ffmpeg, self.aplay):
            if p and p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
        for p in (self.ffmpeg, self.aplay):
            if p:
                try:
                    p.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    pass
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.ffmpeg = self.aplay = self.thread = None
        self.samples = [0] * 1024

    def position(self):
        return self.offset + self.frames / RATE

    def pause(self):
        if self.playing.is_set():
            self.playing.clear()
        else:
            self.playing.set()


# The bars: how loud each of BANDS pitch ranges is, by the Goertzel method
# (one tone at a time; no numeric library needed).
FREQS = [70 * (9000 / 70) ** (i / (BANDS - 1)) for i in range(BANDS)]
COEFF = [2 * math.cos(2 * math.pi * f / (RATE / 2)) for f in FREQS]


def spectrum(samples):
    samples = samples[-512:]                 # the last 23 ms
    n = len(samples)
    if not n:
        return [0.0] * BANDS
    out = []
    for c in COEFF:
        s1 = s2 = 0.0
        for x in samples:
            s0 = x + c * s1 - s2
            s2, s1 = s1, s0
        power = s1 * s1 + s2 * s2 - c * s1 * s2
        out.append(math.sqrt(max(power, 0.0)) / n)
    return out


def volume(step=0):
    """Change the loudness by step percent; returns it (or None)."""
    for control in ("Master", "PCM", "Speaker", "Headphone"):
        try:
            args = ["amixer", "-M", "sget", control] if not step else \
                ["amixer", "-M", "sset", control, "%d%%%s" % (abs(step), "+" if step > 0 else "-")]
            out = subprocess.run(args, capture_output=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode == 0:
            text = out.stdout.decode("utf-8", "replace")
            i = text.find("%]")
            if i > 0:
                j = text.rfind("[", 0, i)
                try:
                    return int(text[j + 1:i])
                except ValueError:
                    return None
    return None


def clock(seconds):
    seconds = int(max(0, seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)


def ask(s, prompt, default=""):
    """One line of text at the bottom of the screen (Esc: nothing)."""
    h, w = s.size()
    text = default
    s.scr.nodelay(False)
    curses.curs_set(1)
    try:
        while True:
            s.put(h - 1, 0, (" " + prompt + " " + text).ljust(w - 1)[:w - 1], BLACK, YELLOW)
            s.scr.move(h - 1, min(w - 2, len(prompt) + 2 + len(text)))
            s.scr.refresh()
            try:
                k = s.scr.get_wch()
            except curses.error:
                continue
            if k in ("\n", "\r", curses.KEY_ENTER):
                return text.strip()
            if k == "\x1b":
                return ""
            if k in ("\x7f", "\b", curses.KEY_BACKSPACE):
                text = text[:-1]
            elif isinstance(k, str) and k.isprintable():
                text += k
    finally:
        curses.curs_set(0)
        s.scr.nodelay(True)


def main(s, args):
    songs = []
    for a in args or [MUSIC]:
        songs += songs_in(a)
    os.makedirs(MUSIC, exist_ok=True)
    info = {}                                # path -> (title, seconds)
    engine = Engine()
    current, chosen, top = -1, 0, 0
    shuffle = repeat = False
    message = ""
    levels = [0.0] * BANDS
    peak = 1500.0
    vol = volume()
    s.scr.nodelay(True)
    s.scr.keypad(True)

    def play(i, position=0.0):
        nonlocal current, message
        if not songs:
            return
        current = i % len(songs)
        if songs[current] not in info:
            info[songs[current]] = probe(songs[current])
        engine.start(songs[current], position)
        message = ""
        kbui_title(info[songs[current]][0])

    def kbui_title(text):
        if os.environ.get("KILOBYTE_DESK"):
            sys.stdout.write("\033]2;%s\007" % ("♫ " + text)[:40])
            sys.stdout.flush()

    def following():
        if shuffle and len(songs) > 1:
            return random.choice([i for i in range(len(songs)) if i != current])
        return current + 1

    if songs and args:
        play(0)                              # opened with a song: play it at once
    try:
        while True:
            h, w = s.size()
            bars_h = max(4, min(10, h // 4))
            list_h = max(1, h - bars_h - 6)
            # --- what is on the screen
            s.put(0, 0, (" Music Player   %d song%s%s%s" % (
                len(songs), "" if len(songs) == 1 else "s",
                "   shuffle" if shuffle else "", "   repeat" if repeat else "")).ljust(w)[:w], WHITE, BLUE)
            if chosen < top:
                top = chosen
            if chosen >= top + list_h:
                top = chosen - list_h + 1
            for row in range(list_h):
                i = top + row
                if i < len(songs):
                    name = info[songs[i]][0] if songs[i] in info else os.path.splitext(os.path.basename(songs[i]))[0]
                    mark = "► " if i == current else "  "
                    line = (" " + mark + name).ljust(w - 1)[:w - 1]
                    if i == chosen:
                        s.put(1 + row, 0, line, BLACK, CYAN)
                    else:
                        s.put(1 + row, 0, line, YELLOW if i == current else LIGHTGREY, BLACK)
                else:
                    s.put(1 + row, 0, " " * (w - 1), LIGHTGREY, BLACK)
            if not songs:
                s.put(2, 2, "No music yet. Put songs into ~/Music (the YouTube Downloader saves", LIGHTGREY, BLACK)
                s.put(3, 2, "sound there), or open a song from the file manager.", LIGHTGREY, BLACK)
            y = 1 + list_h
            s.put(y, 0, "─" * (w - 1), DARKGREY, BLACK)
            # now playing, time and the progress bar
            if 0 <= current < len(songs):
                title, total = info.get(songs[current], ("", 0))
                pos = engine.position()
                state = "  " if engine.playing.is_set() else "▌▌"
                s.put(y + 1, 0, (" %s %s" % (state, title)).ljust(w - 1)[:w - 1], WHITE, BLACK)
                times = " %s / %s " % (clock(pos), clock(total))
                bar_w = max(4, w - len(times) - 12)
                filled = int(bar_w * min(1.0, pos / total)) if total else 0
                s.put(y + 2, 0, times, LIGHTGREY, BLACK)
                s.put(y + 2, len(times), "█" * filled, CYAN, BLACK)
                s.put(y + 2, len(times) + filled, "░" * (bar_w - filled), DARKGREY, BLACK)
                s.put(y + 2, len(times) + bar_w, ("  ♪ %s" % ("%d%%" % vol if vol is not None else "--")).ljust(10)[:w - len(times) - bar_w - 1],
                      LIGHTGREY, BLACK)
            else:
                s.put(y + 1, 0, " " * (w - 1), LIGHTGREY, BLACK)
                s.put(y + 2, 0, " " * (w - 1), LIGHTGREY, BLACK)
            # the bars: they fall slowly, so the eye can follow
            fresh = spectrum(engine.samples) if engine.playing.is_set() and current >= 0 else [0.0] * BANDS
            peak = max(peak * 0.995, max(fresh), 800.0)
            for i in range(BANDS):
                level = min(1.0, (fresh[i] / peak) ** 0.6)
                levels[i] = level if level > levels[i] else max(0.0, levels[i] - 0.08)
            band_w = max(1, (w - 2) // BANDS)
            by = y + 3
            for row in range(bars_h):
                line_y = by + row
                from_bottom = bars_h - row          # 1 at the bottom row
                x = 1
                for i in range(BANDS):
                    cells = levels[i] * bars_h * 2   # in half rows
                    full, half = cells >= from_bottom * 2, cells >= from_bottom * 2 - 1
                    colour = LIGHTRED if from_bottom > bars_h * 0.8 else YELLOW if from_bottom > bars_h * 0.55 else LIGHTGREEN
                    ch = "█" if full else "▄" if half else " "
                    s.put(line_y, x, (ch * (band_w - 1 if band_w > 1 else 1)).ljust(band_w)[:max(0, w - 1 - x)], colour, BLACK)
                    x += band_w
                s.put(line_y, x, " " * max(0, w - 1 - x), LIGHTGREY, BLACK)
            help_line = message or " Enter play  Space pause  N P next/previous  ← → seek  + - volume  S shuffle  R repeat  L W playlists  Q quit"
            s.put(h - 1, 0, help_line.ljust(w - 1)[:w - 1], BLACK, LIGHTGREY if not message else YELLOW)
            s.scr.refresh()
            # --- the song is over: the next one
            if engine.ended and current >= 0:
                if engine.error:
                    message = " " + engine.error
                    engine.ended = False
                    current = -1
                elif repeat and len(songs) == 1:
                    play(current)
                elif current + 1 < len(songs) or shuffle or repeat:
                    play(following())
                else:
                    engine.ended = False
                    current = -1
            # --- keys
            time.sleep(0.07)
            while True:
                try:
                    k = s.scr.get_wch()
                except curses.error:
                    break
                if k in ("q", "Q", "\x1b", "\x03"):
                    return
                message = ""
                if k == curses.KEY_UP:
                    chosen = max(0, chosen - 1)
                elif k == curses.KEY_DOWN:
                    chosen = min(max(0, len(songs) - 1), chosen + 1)
                elif k == curses.KEY_PPAGE:
                    chosen = max(0, chosen - list_h)
                elif k == curses.KEY_NPAGE:
                    chosen = min(max(0, len(songs) - 1), chosen + list_h)
                elif k == curses.KEY_HOME:
                    chosen = 0
                elif k == curses.KEY_END:
                    chosen = max(0, len(songs) - 1)
                elif k in ("\n", "\r", curses.KEY_ENTER):
                    play(chosen)
                elif k == " ":
                    if current >= 0:
                        engine.pause()
                    else:
                        play(chosen)
                elif k in ("n", "N") and songs:
                    play(following())
                elif k in ("p", "P") and songs:
                    play(current - 1 if current > 0 else len(songs) - 1)
                elif k in (curses.KEY_RIGHT, curses.KEY_LEFT) and current >= 0:
                    total = info.get(songs[current], ("", 0))[1]
                    pos = engine.position() + (10 if k == curses.KEY_RIGHT else -10)
                    play(current, max(0.0, min(pos, max(0.0, total - 1))))
                elif k in ("+", "="):
                    vol = volume(5)
                elif k == "-":
                    vol = volume(-5)
                elif k in ("s", "S"):
                    shuffle = not shuffle
                elif k in ("r", "R"):
                    repeat = not repeat
                elif k in ("w", "W") and songs:
                    name = ask(s, "Save this list as playlist (name):")
                    if name:
                        path = os.path.join(MUSIC, name + ("" if name.lower().endswith(".m3u") else ".m3u"))
                        try:
                            with open(path, "w", encoding="utf-8") as f:
                                f.write("#EXTM3U\n" + "".join(song + "\n" for song in songs))
                            message = " Saved as " + path
                        except OSError as e:
                            message = " Not saved: %s" % e
                elif k in ("l", "L"):
                    lists = sorted(f for f in os.listdir(MUSIC) if f.lower().endswith((".m3u", ".m3u8")))
                    name = ask(s, "Playlist to open (%s; empty: all of ~/Music):" % (", ".join(lists)[:60] or "none saved yet"))
                    found = songs_in(os.path.join(MUSIC, name if name.lower().endswith((".m3u", ".m3u8")) else name + ".m3u")) \
                        if name else songs_in(MUSIC)
                    if found:
                        engine.stop()
                        songs, current, chosen, top = found, -1, 0, 0
                    else:
                        message = " Nothing found."
    finally:
        engine.stop()


if __name__ == "__main__":
    kbui.run(lambda s: main(s, sys.argv[1:]), mouse=False)

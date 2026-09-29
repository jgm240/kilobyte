#!/usr/bin/env python3
"""Generate Kilobyte's sounds: small 8-bit square-wave tunes, like a PC
speaker or an early sound card. All tunes are original.

Output: rootfs/usr/share/kilobyte/sounds/*.wav (8 kHz... 22 kHz mono, 8 bit)
Run after editing:  python3 tools/make-sounds.py
"""
import math
import os
import random
import struct
import wave

RATE = 22050
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rootfs", "usr", "share", "kilobyte", "sounds")

NOTES = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}


def freq(note):
    """'A4' -> 440.0; 'R' is a rest."""
    if note == "R":
        return 0.0
    name, octave = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((NOTES[name] + 12 * (octave - 4)) / 12)


def square(f, seconds, volume=0.35, duty=0.5):
    n = int(RATE * seconds)
    out = []
    for i in range(n):
        if f <= 0:
            out.append(0.0)
            continue
        phase = (i * f / RATE) % 1.0
        v = volume if phase < duty else -volume
        # Short fade in/out so notes do not click.
        edge = min(i, n - i, 200) / 200
        out.append(v * edge)
    return out


def tune(notes, tempo=0.12, **kw):
    samples = []
    for note, beats in notes:
        samples += square(freq(note), beats * tempo, **kw)
    return samples


def mix(*tracks):
    n = max(len(t) for t in tracks)
    return [sum(t[i] for t in tracks if i < len(t)) for i in range(n)]


def save(name, samples):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)  # 8-bit unsigned
        w.setframerate(RATE)
        w.writeframes(bytes(max(0, min(255, int(128 + s * 127))) for s in samples))
    print("wrote", os.path.relpath(path), f"{os.path.getsize(path) // 1024} KB")


def dtmf(digit, seconds=0.09):
    rows = {"1": 697, "2": 697, "3": 697, "4": 770, "5": 770, "6": 770, "7": 852, "8": 852, "9": 852, "0": 941}
    cols = {"1": 1209, "2": 1336, "3": 1477, "4": 1209, "5": 1336, "6": 1477, "7": 1209, "8": 1336, "9": 1477, "0": 1336}
    n = int(RATE * seconds)
    return [0.25 * (math.sin(2 * math.pi * rows[digit] * i / RATE) + math.sin(2 * math.pi * cols[digit] * i / RATE)) for i in range(n)]


def sine(f, seconds, volume=0.3):
    return [volume * math.sin(2 * math.pi * f * i / RATE) for i in range(int(RATE * seconds))]


def main():
    # The single short beep a PC makes when its self test passed.
    save("post-beep.wav", square(988, 0.18, volume=0.3))

    # Startup: a rising arpeggio that settles on a chord.
    melody = [("C5", 1), ("E5", 1), ("G5", 1), ("C6", 2), ("R", 0.5), ("G5", 1), ("C6", 4)]
    bass = [("C3", 3), ("G3", 2.5), ("C4", 5)]
    save("startup.wav", mix(tune(melody, 0.11), tune(bass, 0.11, volume=0.2, duty=0.25)))

    # Login: a quick "ta-da".
    save("login.wav", mix(tune([("G5", 1), ("R", 0.3), ("C6", 3)], 0.09),
                          tune([("E4", 1.3), ("E5", 3)], 0.09, volume=0.2, duty=0.25)))

    # Shut down: the startup chord falling away.
    save("shutdown.wav", tune([("C6", 1), ("G5", 1), ("E5", 1), ("C5", 3)], 0.12))

    # Dial-up modem: dial tone, a phone number, ringing, then the handshake.
    random.seed(1994)
    modem = mix(sine(350, 0.8), sine(440, 0.8))
    for d in "5550142":
        modem += dtmf(d) + [0.0] * int(RATE * 0.05)
    ring = mix(sine(440, 0.6, 0.2), sine(480, 0.6, 0.2))
    modem += [0.0] * int(RATE * 0.3) + ring + [0.0] * int(RATE * 0.4)
    modem += sine(2100, 0.9, 0.3)                          # answer tone
    for f1, f2, d in [(1200, 2400, 0.35), (980, 1180, 0.3), (1650, 1850, 0.4)]:
        modem += [0.25 * (math.sin(2 * math.pi * (f1 if (i // 40) % 2 else f2) * i / RATE)) for i in range(int(RATE * d))]
    modem += [random.uniform(-0.3, 0.3) for _ in range(int(RATE * 1.2))]   # the famous hiss
    save("modem.wav", modem)


if __name__ == "__main__":
    main()

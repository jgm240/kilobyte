#!/usr/bin/python3
"""A video's words as text: its subtitles, or YouTube's automatic captions,
as paragraphs with the time they start at.

    transcript.py INFO.json LANG [WIDTH]

INFO.json is what yt-dlp -J prints for the video. LANG is the language
wanted (en, de, ...): subtitles made by people in that language come first,
then the video's own language, then captions YouTube made automatically
(translated into LANG if there is nothing else).
"""
import html
import json
import re
import sys
import textwrap
import urllib.request

PLAIN = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", "​": ""})


def pick(tracks, lang):
    """The track of tracks (yt-dlp's {lang: [formats]}) for lang, if any."""
    for code in tracks:
        if code == lang or code.split("-")[0] == lang:
            if code.endswith("-orig") or code == lang:
                return code
    for code in tracks:
        if code.split("-")[0] == lang:
            return code
    return None


def choose(info, want):
    subs = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}
    own = (info.get("language") or "").split("-")[0]
    for tracks, lang, made in ((subs, want, "subtitles"), (subs, own, "subtitles"),
                               (auto, own, "automatic captions"), (subs, None, "subtitles"),
                               (auto, want, "automatic captions, translated by YouTube")):
        if not tracks:
            continue
        code = pick(tracks, lang) if lang else next(iter(tracks))
        if code:
            return tracks[code], code, made
    # Automatic captions in the language of the video, when it is not known.
    origs = [c for c in auto if c.endswith("-orig")]
    if origs:
        return auto[origs[0]], origs[0], "automatic captions"
    return None, None, None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def from_json3(text):
    """(seconds, text) pieces from YouTube's json3 captions."""
    out = []
    for ev in json.loads(text).get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        t = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if t:
            out.append((ev.get("tStartMs", 0) / 1000, t))
    return out


def from_vtt(text):
    """(seconds, text) pieces from WebVTT; the rolling lines of automatic
    captions (each cue repeats the one before) are taken once."""
    out, last = [], ""
    for block in re.split(r"\n\s*\n", text):
        m = re.search(r"(\d+):(\d\d):(\d\d)[.,](\d+)\s+-->", block)
        if not m:
            m2 = re.search(r"(\d\d):(\d\d)[.,](\d+)\s+-->", block)
            if not m2:
                continue
            start = int(m2.group(1)) * 60 + int(m2.group(2))
        else:
            start = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        lines = block.split("-->", 1)[1].split("\n")[1:]
        for line in lines:
            line = html.unescape(re.sub(r"<[^>]+>", "", line)).strip()
            if line and line != last:
                out.append((start, line))
                last = line
    return out


def stamp(s):
    s = int(s)
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


def main():
    info = json.load(open(sys.argv[1]))
    want = sys.argv[2] if len(sys.argv) > 2 else "en"
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 72
    formats, code, made = choose(info, want)
    if not formats:
        sys.exit("This video has no subtitles or captions.")
    by_ext = {f.get("ext"): f for f in formats}
    f = by_ext.get("json3") or by_ext.get("vtt") or formats[0]
    raw = fetch(f["url"])
    pieces = from_json3(raw) if f.get("ext") == "json3" else from_vtt(raw)
    if not pieces:
        sys.exit("The captions of this video are empty.")

    title = (info.get("title") or "").translate(PLAIN)
    print(title)
    print("=" * min(len(title), width))
    who = info.get("channel") or info.get("uploader") or ""
    print("%s%s%s" % (who, "  -  " if who else "", stamp(info.get("duration") or 0)))
    print("Text: %s (%s)" % (made, code))
    print()
    # Paragraphs of about half a minute, each starting with its time.
    para, start = [], None
    for t, words in pieces + [(10 ** 9, None)]:
        if start is None:
            start = t
        if words is None or (t - start >= 30 and para and para[-1][-1:] in ".?!" ) or t - start >= 60:
            if para:
                text = " ".join(para).translate(PLAIN)
                text = re.sub(r"\s+", " ", text).replace("[Music]", "(music)")
                print(textwrap.fill(text, width, initial_indent="[%s] " % stamp(start), subsequent_indent="  "))
                print()
            para, start = [], t
        if words:
            para.append(words)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as e:
        sys.exit("The text could not be fetched: %s" % e)

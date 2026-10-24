#!/usr/bin/python3
"""Podcasts: find podcasts, read their episodes, download them.

    podcasts.py search WORDS         podcasts in the fyyd directory:
                                     FEED<TAB>TITLE<TAB>AUTHOR, one per line
    podcasts.py find ADDRESS         a podcast's feed from its address or web
                                     site: FEED<TAB>TITLE
    podcasts.py episodes FEED [new]  its episodes, newest first:
                                     AUDIO<TAB>DATE<TAB>MINUTES<TAB>TITLE
                                     (the feed is kept for 30 minutes; "new"
                                     fetches it again)
    podcasts.py notes FEED AUDIO     an episode's description, as text
    podcasts.py download URL FILE    percentages while it downloads

fyyd (fyyd.de) is a free podcast directory that needs no account; searching
sends it the words searched for, nothing else.
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feeds  # noqa: E402

AGENT = {"User-Agent": "Mozilla/5.0 (Kilobyte Podcasts)"}
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "kilobyte", "podcasts")
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
ATOM = "{http://www.w3.org/2005/Atom}"
AUDIO = ("audio/", "video/")


def fetch(url, limit=20_000_000):
    req = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(limit)


def clean(text):
    """One line of plain text from a title or description."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def search(words):
    q = urllib.parse.urlencode({"term": words, "count": 30})
    data = json.loads(fetch("https://api.fyyd.de/0.2/search/podcast?" + q, 2_000_000))
    for p in data.get("data") or []:
        url = p.get("xmlURL") or p.get("xmlurl")
        if url:
            print("\t".join((url, clean(p.get("title"))[:70] or url, clean(p.get("author"))[:40])))


def feed(url, again=False):
    """The feed's XML, from the cache when it is fresh."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".xml")
    if not again and os.path.exists(path) and time.time() - os.path.getmtime(path) < 1800:
        with open(path, "rb") as f:
            return f.read()
    data = fetch(url)
    with open(path + ".new", "wb") as f:
        f.write(data)
    os.replace(path + ".new", path)
    return data


def minutes(text):
    """itunes:duration (seconds, MM:SS or HH:MM:SS) in minutes."""
    text = (text or "").strip()
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return ""
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return str(max(1, round(secs / 60))) if secs else ""


def date(text):
    """An RSS or Atom date as YYYY-MM-DD."""
    import email.utils
    text = (text or "").strip()
    try:
        return email.utils.parsedate_to_datetime(text).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        m = re.match(r"\d{4}-\d\d-\d\d", text)
        return m.group(0) if m else "          "


def episodes(data):
    """(audio, date, minutes, title, description) of each episode."""
    root = ET.fromstring(data)
    out = []
    for item in root.iter("item"):
        enc = item.find("enclosure")
        if enc is None or not enc.get("url"):
            continue
        kind = enc.get("type") or "audio/"
        if not kind.startswith(AUDIO) and not re.search(r"\.(mp3|m4a|ogg|oga|opus|aac|mp4)(\?|$)", enc.get("url"), re.I):
            continue
        desc = item.findtext("description") or item.findtext(ITUNES + "summary") or ""
        out.append((enc.get("url"), date(item.findtext("pubDate")), minutes(item.findtext(ITUNES + "duration")),
                    clean(item.findtext("title")) or "(no title)", desc))
    for entry in root.iter(ATOM + "entry"):
        for link in entry.findall(ATOM + "link"):
            if link.get("rel") == "enclosure" and link.get("href"):
                out.append((link.get("href"), date(entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated")),
                            "", clean(entry.findtext(ATOM + "title")) or "(no title)",
                            entry.findtext(ATOM + "summary") or entry.findtext(ATOM + "content") or ""))
                break
    out.sort(key=lambda e: e[1], reverse=True)
    return out


def find(address):
    """(feed, title) of the podcast at an address: the feed itself, or the
    first feed a web page names that has episodes."""
    url = address if "://" in address else "https://" + address
    final, data = feeds.get(url)
    tries = [(final, data)]
    if feeds.feed_title(data) is None:
        p = feeds.Links()
        try:
            p.feed(data.decode("utf-8", "replace"))
        except Exception:
            pass
        tries = [urllib.parse.urljoin(final, h) for h in p.found]
        tries += [urllib.parse.urljoin(final, x) for x in ("/feed/podcast", "/podcast.xml", "/feed", "/rss", "/rss.xml")]
    for t in tries:
        try:
            u, d = t if isinstance(t, tuple) else feeds.get(t)
            if episodes(d):
                return u, " ".join((feeds.feed_title(d) or u).split())
        except Exception:
            continue
    return None


def notes(text):
    """A description as readable text: paragraphs and links kept."""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", text or "")
    text = re.sub(r"(?i)<a [^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"\2 (\1)", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or "(This episode has no description.)"


def download(url, path):
    req = urllib.request.Request(url, headers=AGENT)
    tmp = path + ".part"
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, shown = 0, -1
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            pct = done * 100 // total if total else min(99, done // 1_000_000)
            if pct != shown:
                print(min(pct, 100), flush=True)
                shown = pct
    os.replace(tmp, path)


def main(args):
    cmd = args[0] if args else ""
    try:
        if cmd == "search" and len(args) == 2:
            search(args[1])
        elif cmd == "find" and len(args) == 2:
            found = find(args[1])
            if not found:
                sys.exit("There is no podcast at that address.")
            print("\t".join(found))
        elif cmd == "episodes" and len(args) in (2, 3):
            for e in episodes(feed(args[1], args[2:] == ["new"]))[:300]:
                print("\t".join(e[:3] + (e[3][:120],)))
        elif cmd == "notes" and len(args) == 3:
            for e in episodes(feed(args[1])):
                if e[0] == args[2]:
                    print(e[3] + "\n" + "─" * min(len(e[3]), 70) + "\n")
                    print(notes(e[4]))
                    break
        elif cmd == "download" and len(args) == 3:
            download(args[1], args[2])
        else:
            sys.exit(__doc__)
    except ET.ParseError:
        sys.exit("The podcast's feed could not be read.")
    except (OSError, ValueError) as e:
        sys.exit(f"Could not reach it: {getattr(e, 'reason', e)}")


if __name__ == "__main__":
    main(sys.argv[1:])

#!/usr/bin/python3
"""Find the news feed (RSS or Atom) of a web address.

    feeds.py find URL      prints "FEED-URL<TAB>TITLE", or fails

A feed's own address is taken as it is; for a web page, the feeds it names
in <link rel="alternate"> are used, and a few usual places are tried.
"""
import html.parser
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"
TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+xml", "application/xml", "text/xml")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Kilobyte News Feeds)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.geturl(), r.read(2_000_000)


def feed_title(data):
    """The title if data is a feed, else None."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    tag = root.tag.split("}")[-1].lower()
    if tag == "rss" or tag == "rdf":
        return (root.findtext("channel/title") or root.findtext("{http://purl.org/rss/1.0/}channel/"
                                                                 "{http://purl.org/rss/1.0/}title") or "").strip()
    if tag == "feed":
        return (root.findtext(ATOM + "title") or "").strip()
    return None


class Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and "alternate" in (a.get("rel") or "").lower() and \
                (a.get("type") or "").lower() in TYPES and a.get("href"):
            self.found.append(a["href"])


def find(url):
    if "://" not in url:
        url = "https://" + url
    final, data = get(url)
    t = feed_title(data)
    if t is not None:
        return final, t
    p = Links()
    try:
        p.feed(data.decode("utf-8", "replace"))
    except Exception:
        pass
    tries = [urllib.parse.urljoin(final, h) for h in p.found]
    tries += [urllib.parse.urljoin(final, x) for x in ("/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml", "/index.xml")]
    for u in tries:
        try:
            f, d = get(u)
        except Exception:
            continue
        t = feed_title(d)
        if t is not None:
            return f, t
    return None, None


if __name__ == "__main__":
    if sys.argv[1:2] != ["find"] or len(sys.argv) != 3:
        sys.exit("usage: feeds.py find URL")
    try:
        f, t = find(sys.argv[2])
    except Exception as e:
        sys.exit("That address could not be opened (%s)." % e)
    if not f:
        sys.exit("There is no news feed at that address.")
    print("%s\t%s" % (f, " ".join(t.split()) or f))

#!/usr/bin/python3
"""Turn weather (wttr.in JSON) and news (RSS or Atom) into the short text
shown in the Program Manager's tiles.

    tiles.py weather C|F   < wttr.in ?format=j1 JSON
    tiles.py news          < RSS or Atom feed
"""
import datetime
import json
import sys
import unicodedata
import xml.etree.ElementTree as ET

# Typographic characters the console font may lack.
PLAIN = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
})


def plain(text):
    return unicodedata.normalize("NFKC", (text or "").translate(PLAIN)).strip()


def weather(unit):
    d = json.load(sys.stdin)
    cur = d["current_condition"][0]
    area = (d.get("nearest_area") or [{}])[0]
    names = [x[0]["value"] for x in (area.get("areaName"), area.get("country")) if x]
    print(", ".join(names)[:58])
    desc = plain(cur["weatherDesc"][0]["value"])
    print("%-40s %4s°%s" % (desc[:40], cur["temp_" + unit], unit))
    print("Feels %s°  Wind %s km/h %s  Humidity %s%%" % (
        cur["FeelsLike" + unit], cur["windspeedKmph"], cur["winddir16Point"], cur["humidity"]))
    print()
    for day in d["weather"][:3]:
        name = datetime.date.fromisoformat(day["date"]).strftime("%a")
        noon = day["hourly"][len(day["hourly"]) // 2]
        print("%s  %3s° %3s°  %s" % (name, day["mintemp" + unit], day["maxtemp" + unit],
                                     plain(noon["weatherDesc"][0]["value"])[:38]))


def news():
    atom = "{http://www.w3.org/2005/Atom}"
    root = ET.fromstring(sys.stdin.buffer.read())
    title = root.findtext("channel/title") or root.findtext(atom + "title") or "News"
    print(plain(title)[:58])
    items = root.findall("channel/item") or root.findall(atom + "entry")
    for it in items[:7]:
        t = plain(it.findtext("title") or it.findtext(atom + "title"))
        print("· " + (t if len(t) <= 88 else t[:85] + "..."))


if __name__ == "__main__":
    if sys.argv[1:2] == ["weather"]:
        weather(sys.argv[2] if len(sys.argv) > 2 else "C")
    elif sys.argv[1:2] == ["news"]:
        news()
    else:
        sys.exit("usage: tiles.py weather C|F | news")

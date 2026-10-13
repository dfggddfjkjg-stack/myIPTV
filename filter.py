import urllib.request
import sys

SOURCES = [
    ("https://iptv-org.github.io/iptv/languages/spa.m3u", ["CNN", "Telemundo"]),
    ("https://iptv-org.github.io/iptv/categories/news.m3u", None),
    ("https://iptv-org.github.io/iptv/countries/us.m3u", ["ESPN", "HBO"]),
]


def fetch(url):
    data = urllib.request.urlopen(url, timeout=60).read()
    return data.decode("utf-8")


def parse(text):
    entries = []
    meta = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
        if line.startswith("#"):
            meta.append(line)
            continue
        entries.append((meta, line))
        meta = []
    return entries


def name_of(meta):
    for m in meta:
        if m.startswith("#EXTINF"):
            return m.rsplit(",", 1)[-1].lower()
    return ""


def wanted(meta, keep):
    if not keep:
        return True
    name = name_of(meta)
    return any(k.lower() in name for k in keep)


out = ["#EXTM3U"]
seen = set()

for url, keep in SOURCES:
    try:
        entries = parse(fetch(url))
    except Exception as e:
        print("Skipped", url, e)
        continue
    for meta, stream in entries:
        if stream in seen:
            continue
        if not wanted(meta, keep):
            continue
        seen.add(stream)
        out.extend(meta)
        out.append(stream)

if len(out) == 1:
    sys.exit("No channels found, keeping old file")

with open("my.m3u", "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")

print(len(seen), "channels written")

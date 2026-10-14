import urllib.request
import fnmatch
import re
import sys

# Each entry: (playlist URL, keywords)
# keywords can be: None (keep all), a "file.txt" name, or a list of names
SOURCES = [
    ("https://iptv-org.github.io/iptv/languages/kat.m3u", None),
    ("https://iptv-org.github.io/iptv/languages/rus.m3u", "rus.txt"),
]


def fetch(url):
    data = urllib.request.urlopen(url, timeout=60).read()
    return data.decode("utf-8")


def clean(name):
    name = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", name)
    name = " ".join(name.split())
    return name.lower()


def load_keywords(keep):
    if keep is None:
        return None
    if isinstance(keep, list):
        return [clean(k) for k in keep]
    words = []
    try:
        with open(keep, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    words.append(clean(line))
    except FileNotFoundError:
        print("Keyword file not found:", keep)
        return []
    return words


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
            return clean(m.rsplit(",", 1)[-1])
    return ""


def wanted(meta, keywords):
    if keywords is None:
        return True
    name = name_of(meta)
    return any(fnmatch.fnmatchcase(name, k) for k in keywords)


out = ["#EXTM3U"]
seen = set()

# 1. Your own channels go first
try:
    with open("extra.m3u", encoding="utf-8") as f:
        for meta, stream in parse(f.read()):
            seen.add(stream)
            out.extend(meta)
            out.append(stream)
except FileNotFoundError:
    print("No extra.m3u found, skipping")

# 2. Then the iptv-org sources
for url, keep in SOURCES:
    keywords = load_keywords(keep)
    try:
        entries = parse(fetch(url))
    except Exception as e:
        print("Skipped", url, e)
        continue
    for meta, stream in entries:
        if stream in seen:
            continue
        if not wanted(meta, keywords):
            continue
        seen.add(stream)
        out.extend(meta)
        out.append(stream)

if len(out) == 1:
    sys.exit("No channels found, keeping old file")

with open("my.m3u", "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")

print(len(seen), "channels written")

import urllib.request
import urllib.error
import fnmatch
import json
import re
import sys
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

# Each entry: (playlist URL, keywords, group order)
# keywords: None (keep all), a "file.txt" name, or a list of names
# group order: None (keep file order) or a list like ["Movies", "News"]
SOURCES = [
    ("https://iptv-org.github.io/iptv/languages/kat.m3u", None, None),
    ("https://iptv-org.github.io/iptv/languages/rus.m3u", "rus.txt", ["Outdoor", "Documentary", "Comedy", "Movies"]),
]

# Dead stream cleaning in the cloud (you test on your PC, so it is off)
CHECK_STREAMS = False
FAILS_TO_REMOVE = 3       # failed runs in a row before a stream is removed
TIMEOUT = 8               # seconds to wait per stream
WORKERS = 40              # streams tested at the same time
MIN_ALIVE_RATIO = 0.2     # if fewer than 20% work, assume a network problem
UA = "Mozilla/5.0"


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


def load_blacklist():
    names = []
    urls = set()
    try:
        with open("blacklist.txt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower().startswith("http"):
                    urls.add(line)
                else:
                    names.append(clean(line))
    except FileNotFoundError:
        print("No blacklist.txt found, skipping")
    return names, urls


def load_hosts():
    hosts = []
    try:
        with open("blocked_hosts.txt", encoding="utf-8") as f:
            for line in f:
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    hosts.append(line)
    except FileNotFoundError:
        print("No blocked_hosts.txt found, skipping")
    return hosts


def load_state():
    try:
        with open("dead.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


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


def group_of(meta):
    for m in meta:
        if m.startswith("#EXTINF"):
            found = re.search(r'group-title="([^"]*)"', m)
            if found:
                return found.group(1)
    return ""


def rank(meta, order):
    parts = [p.strip().lower() for p in group_of(meta).split(";")]
    for i, g in enumerate(order):
        if g.lower() in parts:
            return i
    return len(order)


def wanted(meta, keywords):
    if keywords is None:
        return True
    name = name_of(meta)
    return any(fnmatch.fnmatchcase(name, k) for k in keywords)


def blocked(meta, stream, bad_names, bad_urls):
    if stream in bad_urls:
        return True
    host = (urlparse(stream).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in BAD_HOSTS):
        return True
    name = name_of(meta)
    return any(fnmatch.fnmatchcase(name, b) for b in bad_names)


def headers_of(meta):
    headers = {"User-Agent": UA}
    for m in meta:
        low = m.lower()
        if low.startswith("#extvlcopt:http-referrer="):
            headers["Referer"] = m.split("=", 1)[1]
        elif low.startswith("#extvlcopt:http-user-agent="):
            headers["User-Agent"] = m.split("=", 1)[1]
    return headers


def is_alive(item):
    meta, url = item
    if not url.lower().startswith(("http://", "https://")):
        return True
    try:
        req = urllib.request.Request(url, headers=headers_of(meta))
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            chunk = r.read(2048)
            ctype = r.headers.get("Content-Type", "").lower()
        if ".m3u8" in url.lower() or "mpegurl" in ctype:
            return b"#EXTM3U" in chunk
        return len(chunk) > 0
    except urllib.error.HTTPError as e:
        # 401/403/451 often means "blocked for this server", not "dead"
        return e.code in (401, 403, 451)
    except Exception:
        return False


BAD_HOSTS = load_hosts()
bad_names, bad_urls = load_blacklist()
state = load_state()

out = ["#EXTM3U"]
seen = set()

# 1. Your own channels go first (never tested, blocked, or removed)
try:
    with open("extra.m3u", encoding="utf-8") as f:
        for meta, stream in parse(f.read()):
            seen.add(stream)
            out.extend(meta)
            out.append(stream)
except FileNotFoundError:
    print("No extra.m3u found, skipping")

# 2. Collect the iptv-org channels
groups = []
for url, keep, order in SOURCES:
    keywords = load_keywords(keep)
    try:
        entries = parse(fetch(url))
    except Exception as e:
        print("Skipped", url, e)
        continue
    kept = []
    for meta, stream in entries:
        if stream in seen:
            continue
        if blocked(meta, stream, bad_names, bad_urls):
            continue
        if not wanted(meta, keywords):
            continue
        seen.add(stream)
        kept.append((meta, stream))
    groups.append((kept, order))

# 3. Test the streams (only if CHECK_STREAMS is True)
dead = set()
if CHECK_STREAMS:
    items = [item for kept, _ in groups for item in kept]
    if items:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(is_alive, items))
        alive = sum(results)
        print(alive, "of", len(items), "streams responded")
        if alive / len(items) < MIN_ALIVE_RATIO:
            print("Too many failures, skipping cleanup this run")
            new_state = state
        else:
            new_state = {}
            for (meta, stream), ok in zip(items, results):
                if not ok:
                    new_state[stream] = state.get(stream, 0) + 1
        dead = {s for s, n in new_state.items() if n >= FAILS_TO_REMOVE}
        with open("dead.json", "w", encoding="utf-8") as f:
            json.dump(new_state, f, indent=0)

# 4. Write the playlist
written = 0
for kept, order in groups:
    if order:
        kept.sort(key=lambda item: rank(item[0], order))
    for meta, stream in kept:
        if stream in dead:
            continue
        out.extend(meta)
        out.append(stream)
        written += 1

if len(out) == 1:
    sys.exit("No channels found, keeping old file")

with open("my.m3u", "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")

print(written, "channels written,", len(dead), "dead streams removed")

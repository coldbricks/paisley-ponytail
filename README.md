# Paisley Ponytail — the Webshots Resurrector

**Bring lost photos back to life.**

*Why "Paisley Ponytail"? It sounds like a pony you would 100% not mess with. That's the energy this tool brings to your lost photos.*

Webshots was a photo sharing service with 14 million users at its peak. In December 2012, the final owner deleted everything. Archive Team ran an emergency crawl and saved what they could — 105.9 TB of photos locked inside 2,437 megawarc blobs on the Internet Archive.

The search tools died years ago. `warctozip.archive.org` has no DNS. The freeze-frame index links go nowhere.

This tool is the key back in.

---

## What It Does

Given a Webshots username, Resurrector:

1. **Queries the Wayback Machine CDX API** to find archived snapshots of the user's profile
2. **Scrapes album and photo page links** from the archived profile across all Webshots subdomains
3. **Extracts full-size original photos** (`_fs.jpg` at 1280x960) via Wayback, falling back to 800x600 if originals aren't available
4. **Saves everything** organized by album with metadata

No megawarc downloads. No 50 GB files. Surgical byte-range requests pull individual photos from the archive.

## Usage

```bash
# Search — find what's archived for a user
python3 resurrector.py search <username>

# Pull — download all their photos
python3 resurrector.py pull <username> [-j JOBS] [-o OUTPUT_DIR]
```

### Example

```
$ python3 resurrector.py search bexbee12

 ▄▄▄▄▄  RECON  Target: bexbee12
 ▄▄▄▄▄  RECON  Querying Wayback Machine CDX API...
   ✓    RECON  12 snapshots  (2005-03-14 .. 2012-11-28)

 ▄▄▄▄▄  SCAN   Loading profile page...
   ✓    SCAN   9 albums found

 Album               Photos  Subdomain
 ───────────────────────────────────────
 Summer Vacation      24     good-times
 Family Portraits     18     home-and-garden
 ...
```

## Requirements

Python 3.10+. Install dependencies:

```bash
pip install httpx aiohttp rich beautifulsoup4
```

## How It Works

```
Username
   │
   ├─→ Wayback CDX API (community.webshots.com/user/USERNAME/*)
   │     → archived profile URLs + timestamps
   │
   ├─→ Profile page scrape (latest snapshot)
   │     → album links across subdomains
   │
   ├─→ Album page scrape (each album)
   │     → photo detail page links
   │
   ├─→ Photo page scrape (each photo)
   │     → image server URL (imageNN.webshots.com)
   │
   └─→ Image download via Wayback proxy
         → try _fs.jpg (full-size) first, fall back to _ph.jpg
```

All requests are rate-limited with exponential backoff. archive.org is treated as a guest resource.

## Why This Exists

Between 1995 and 2012, millions of people uploaded their only copies of family photos, travel pictures, and memories to Webshots. When Threefold Photos pulled the plug, most of those photos vanished.

Archive Team's crawl saved a fraction, but the tools to search and extract them have been dead since ~2016. If someone's grandmother's photos are in there, this is how you get them back.

## License

MIT

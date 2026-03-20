# CLAUDE.md — Webshots Resurrector

> The tool that let you search Webshots archives has been dead for 10+ years.
> `warctozip.archive.org` has no DNS. The freeze-frame index links to nowhere.
> 105.9 TB of photos are locked inside 2,437 megawarc blobs on archive.org.
> We're building the key.

---

## Prime Directives

1. **This is a data recovery project.** Every design decision optimizes for one thing: given a username, find and download their Webshots photos from the Internet Archive's freeze-frame collection.
2. **Bandwidth is the enemy.** Each megawarc is ~50 GB. We never download a full megawarc to find one user's photos. CDX indexes exist — use byte-range requests to surgically extract individual WARC records.
3. **The archive is fragile.** Rate-limit all requests to archive.org. Respect their infrastructure. Use exponential backoff. We are guests in their house.
4. **Two access paths exist.** The Wayback Machine (CDX API) and the freeze-frame collection (megawarc CDX indexes) are complementary. The tool should try both.
5. **Accuracy over speed.** A false negative (missing photos that exist) is worse than being slow. Exhaustively check all 2,437 freeze-frame items if needed.

---

## Project Identity

| Field | Value |
|---|---|
| **Project** | Webshots Resurrector — Search and download Webshots photos from Internet Archive |
| **Goal** | Username-based search + photo download from archive.org's Webshots freeze-frame collection |
| **Language/Stack** | Python 3.13 (httpx, aiohttp, rich, beautifulsoup4) |
| **Target Platform** | Linux x86_64 (Kali) |
| **Repo Root** | `/home/kali/webshots-resurrector` |
| **Primary Branch** | main |

---

## The Problem (Full Context)

### What Was Webshots?
Photo sharing service (1995–2012). 14M monthly users at peak. Sold repeatedly, final owner Threefold Photos shut down image hosting on **December 1, 2012** and deleted all user photos.

### The Rescue
**Archive Team** ran an emergency crawl in late 2012 using distributed Warrior volunteers. They captured user profiles and photos from `community.webshots.com` into WARC format, bundled into megawarcs, uploaded to archive.org.

### What Exists Now
- **Collection:** `archive.org/details/webshots-freeze-frame` — 2,437 items, ~105.9 TB total
- **Each item contains:**
  - `webshots-TIMESTAMP.megawarc.warc.gz` (~50.2 GB) — the photos/pages
  - `webshots-freeze-frame-TIMESTAMP.cdx.gz` (~50 MB) — URL-to-byte-offset index
  - `webshots-freeze-frame-TIMESTAMP.cdx.idx` (~44 KB) — secondary index
  - `_files.xml`, `_meta.xml` — archive.org metadata
- **Freeze-frame index:** `archive.org/details/webshots-freeze-frame-index` — HTML search by username, but download links point to dead `warctozip.archive.org` service
- **Wayback Machine:** Also has many Webshots pages independently crawled

### What's Broken
- `warctozip.archive.org` — no DNS since ~2016. This was the only way to get per-user ZIP extracts.
- The freeze-frame HTML index renders but all download links are dead.
- Some megawarc files may be access-restricted.

### Prior Art (Existing Tools)
| Tool | URL | Status | Notes |
|---|---|---|---|
| `clarkbk/archive-org-scraper` | github.com/clarkbk/archive-org-scraper | Partial (2018) | Scrapes Wayback Machine for one user's photos. Python. May still work. |
| `rjdg14/Wayback-Machine-Webshots-Gallery-Search` | github.com/rjdg14/Wayback-Machine-Webshots-Gallery-Search | Working (2025) | 1.7M profiles as text files for grep-based search. No images. |
| `joepie91/webshots` | github.com/joepie91/webshots | Dead | Python 2, targeted live site. Search API gone. |
| `ArchiveTeam/webshots-grab` | github.com/ArchiveTeam/webshots-grab | Historical | The original crawl pipeline. Not useful for searching. |

### What Still Works
1. **Wayback CDX API** — `web.archive.org/cdx/search/cdx?url=community.webshots.com/user/USERNAME&output=json` — returns timestamps of archived captures
2. **CDX index files** in freeze-frame items — can be downloaded (~50 MB each), parsed to find byte offsets, then byte-range HTTP requests extract specific WARC records from the 50 GB megawarcs
3. **archive.org metadata API** — `archive.org/metadata/ITEM_NAME` — get file listings and sizes

---

## Architecture

### The Pipeline
```
Username Input
    │
    ├──→ [1] Wayback CDX Search
    │         Query: community.webshots.com/user/USERNAME/*
    │         Returns: list of archived URLs + timestamps
    │         Download: individual pages/images from Wayback
    │
    └──→ [2] Freeze-Frame CDX Search
              For each of 2,437 items:
                Download cdx.gz (~50 MB) → parse → grep for USERNAME
                If found: extract byte offset + length from CDX entry
                Use HTTP Range request to pull just that WARC record
                Extract photo from WARC record
```

### CDX Format
Each line in a CDX file:
```
URL TIMESTAMP ORIGINAL_URL MIMETYPE STATUS DIGEST OFFSET LENGTH FILENAME
```
The OFFSET and LENGTH fields let us do:
```
curl -H "Range: bytes=OFFSET-OFFSET+LENGTH" https://archive.org/download/ITEM/megawarc.warc.gz
```
This pulls ~KB of data from a 50 GB file. That's the whole trick.

### Key Design Decisions
1. **CDX index caching** — Download CDX files once, store locally, search locally. Don't re-download.
2. **Async everywhere** — Use aiohttp/httpx for concurrent CDX downloads and WARC range requests.
3. **Progress tracking** — 2,437 CDX files to check is a long operation. Rich progress bars, resume capability.
4. **WARC record extraction** — Use Python's gzip + io to decompress individual WARC records in memory. No need for warcat dependency.
5. **Output organization** — `output/USERNAME/album_name/photo.jpg` with metadata sidecar files.

---

## Key File Map

| Purpose | Path |
|---|---|
| Entry point / CLI | `resurrector.py` |
| Wayback CDX search | `wayback.py` |
| Freeze-frame CDX search | `freezeframe.py` |
| WARC record extraction | `warc.py` |
| CDX index parser | `cdx.py` |
| HTTP client (rate-limited) | `client.py` |
| Output/download manager | `downloader.py` |
| Config / constants | `config.py` |
| Local CDX cache | `cache/` (gitignored) |
| Downloaded photos | `output/` (gitignored) |

---

## Build and Run

```bash
# Search for a username (Wayback + freeze-frame)
python3 resurrector.py search USERNAME

# Search Wayback only (fast, no CDX download needed)
python3 resurrector.py search --wayback-only USERNAME

# Download all found photos for a user
python3 resurrector.py download USERNAME

# List all available freeze-frame items
python3 resurrector.py list-items

# Download and cache CDX indexes (do this first for freeze-frame search)
python3 resurrector.py cache-cdx [--start N] [--count N]

# Search cached CDX files locally (fast, offline after initial cache)
python3 resurrector.py search --local USERNAME
```

No build step. Pure Python. Dependencies: `httpx`, `aiohttp`, `rich`, `beautifulsoup4`.

```bash
# Install deps (if not already present)
pip install httpx aiohttp rich beautifulsoup4
```

---

## Architecture Invariants

1. **Never download a full megawarc.** Always use CDX byte-range extraction. If a code path would download 50 GB, it is wrong.
2. **All HTTP requests go through `client.py`** — rate limiting, retries, and exponential backoff are centralized there.
3. **CDX files are cached locally after first download** — `cache/` directory, one gzipped file per freeze-frame item.
4. **Output directory structure is always `output/USERNAME/`** — photos inside, metadata in `.json` sidecar files.
5. **No hardcoded archive.org URLs outside `config.py`** — base URLs, API endpoints, and collection names are constants.

---

## Coding Standards

- Python 3.13. Type hints on function signatures.
- `async`/`await` for all I/O. No blocking HTTP calls in the main pipeline.
- `rich` for all terminal output — progress bars, tables, status spinners.
- Functions under 50 lines. If longer, extract.
- No wildcard imports. No star-import from modules.
- Error handling: catch specific exceptions, log the full error, continue to next item. One broken CDX file should not abort the whole search.

---

## Domain Knowledge

### Webshots URL Patterns
```
community.webshots.com/user/USERNAME                    — profile page
community.webshots.com/user/USERNAME/albumNUMBER       — album page
community.webshots.com/photo/PHOTOID                    — individual photo
image.webshots.com/...                                  — actual image files

# Image servers (DIFFERENT from thumbnail servers):
imageNN.webshots.com/N/A/BB/CC/PHOTOIDHASH_fs.jpg     — FULL-SIZE (1280x960)
imageNN.webshots.com/N/A/BB/CC/PHOTOIDHASH_ph.jpg     — photo-size (800x600)
thumbNN.webshots.net/s/thumbN/A/BB/CC/PHOTOIDHASH_th.jpg — thumbnail (100x75)

# Suffix meanings:
#   _fs.jpg = full-size original resolution (whatever the camera shot)
#   _ph.jpg = photo-size, capped at 800x600
#   _th.jpg = thumbnail, 100x75
#
# The _ph.jpg URL appears directly on photo detail pages in <img src="...">
# The _fs.jpg URL is derived by replacing _ph.jpg suffix with _fs.jpg
# ALWAYS try _fs.jpg first, fall back to _ph.jpg if 404
# The image server number (e.g. image04) differs from thumb server (e.g. thumb13)
# The path structure (A/BB/CC/PHOTOID) encodes photo ID digits
#
# CONFIRMED across 3 photos (2026-03-20, bexbee12):
#   _ph.jpg: always 800x600 (50-70KB)
#   _fs.jpg: always 1280x960 (114-170KB) — original camera resolution
#   _th.jpg: always 100x75 (~1KB)
```

### archive.org API Patterns
```
archive.org/metadata/ITEM_NAME                          — item metadata JSON
archive.org/download/ITEM/FILENAME                      — direct file download
web.archive.org/cdx/search/cdx?url=URL&output=json     — Wayback CDX search
web.archive.org/web/TIMESTAMP/URL                       — Wayback playback
```

### CDX Index Entry Format
```
CDX N b a m s k r V g u
```
Fields: `url_key timestamp original mimetype status_code digest redirect offset length filename`

### WARC Record Structure
```
WARC/1.0
WARC-Type: response
WARC-Target-URI: http://community.webshots.com/...
Content-Length: NNNN

HTTP/1.1 200 OK
Content-Type: image/jpeg
...

[binary image data]
```

### Rate Limiting Guidelines
- archive.org: max 1 request/second sustained, burst to 5/s for short periods
- Wayback CDX API: max 15 requests/minute
- Back off on 429 or 503 responses with exponential delay (2s, 4s, 8s, 16s, cap at 60s)

---

## Environment

- **OS:** Kali Linux (zsh)
- **Python:** 3.13
- **Available libs:** httpx, aiohttp, rich, beautifulsoup4, requests
- **Storage:** CDX cache will need ~120 GB for all 2,437 items. Downloaded photos vary by user.
- **Network:** No special requirements. Standard internet access to archive.org.

---

## Workflow

### Before Writing Code
1. Check if the archive.org API endpoint you're about to use actually works — `curl` it first.
2. Verify CDX format by downloading one small CDX file and inspecting it manually.
3. Test byte-range requests against archive.org to confirm they support HTTP Range headers on megawarc files.

### While Writing Code
- Test with one known username first. Validate end-to-end before scaling.
- Log every HTTP request in debug mode so we can diagnose archive.org quirks.
- Handle the case where megawarc files are access-restricted (403/451) gracefully.

### Debugging
- If a CDX search returns nothing, check URL normalization — Webshots URLs may have trailing slashes, mixed case, or different path formats.
- If byte-range extraction returns garbage, verify the CDX offset is correct — some CDX files use compressed offsets vs uncompressed offsets.
- If photos are corrupt, check Content-Encoding — the WARC record may contain gzip-compressed HTTP responses.

---

## Active Work Context

**Current task:** Build the Wayback-based scraper pipeline (primary path). Validate full-size image access.
**Blocked on:** archive.org is intermittently offline (2026-03-20). Retry when it comes back.
**Phase:** Research and prototyping.

**Validated (2026-03-20):**
- Wayback CDX API works for username lookup: `community.webshots.com/user/USERNAME`
- Profile pages render with album links across subdomains (entertainment, sports, good-times, home-and-garden, etc.)
- Album pages render with photo links and thumbnail URLs
- Photo detail pages render with photoId references
- Tested with username `yankeefan519` — 9 albums found, 2 Wayback snapshots (2005, 2012)

**Full pipeline validated (2026-03-20, bexbee12):**
1. CDX API -> profile URL -> album links -> photo page links -> _ph.jpg URL in page source
2. Replace _ph.jpg with _fs.jpg -> full-size 1280x960 image via Wayback
3. Image server: imageNN.webshots.com (NOT thumbNN.webshots.net)
4. Wayback proxy: web.archive.org/web/YYYYim_/http://imageNN.webshots.com/...

**Remaining issues:**
- Freeze-frame CDX files return "Item not available" — collection items may need archive.org login or are intermittently restricted.
- archive.org goes offline intermittently — all paths need robust retry logic.
- Need to determine if _fs.jpg exists for ALL photos or only some (may need to fall back to _ph.jpg).

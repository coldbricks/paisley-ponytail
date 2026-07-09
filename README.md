# Paisley Ponytail

![Paisley Ponytail nose art](assets/nose_art.jpg)

**The Webshots Resurrector — bring lost photos back to life.**

*(Yes, the nose art is AI. I can dig your photos out of a 105.9 TB wreck or I can learn to paint. Pick one.)*

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3c7a3c)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-3c7a3c)](LICENSE)
![Megawarcs on frequency](https://img.shields.io/badge/on%20frequency-2%2C437%20megawarcs%20%2F%20105.9%20TB-1f3d1f)

```
ATIS PPTY  ·  PYSLY-R90  ·  v2.1
You are an air traffic controller at the busiest air traffic control
radar facility on the planet. Your traffic is deleted family photos.
The only person who can save them is you. Good luck. We're all counting on you.

WINDOWS: double-click Start_Here.bat → TRAINING MODE, a simple guided wizard
  Type a Webshots screen name in the GREEN BOX → SEARCH → PULL
  PROFESSIONAL MODE (top right) turns on the entire facility:
  sector gate, live weather brief, VSCS/ZWY panels, live ADS-B on the map
python resurrector.py scope     # radar room
python resurrector.py --cli     # terminal cab
python resurrector.py pull NAME # headless recovery

AVIATE · NAVIGATE · COMMUNICATE  ·  multiple plans · always an out
Private albums never archived. Be kind to archive.org.
Built on Archive Team + the Internet Archive.
```

Webshots hosted 14 million users' photos from 1995 until December 2012, when
its final owner deleted everything. Archive Team scrambled an emergency crawl
in the last weeks and hauled 105.9 TB into the Internet Archive. Then the
extraction tooling died in 2016, and the wreckage sat locked in 2,437
fifty-gigabyte WARC blobs for a decade. Nobody knows exactly how much of
those 14 million users made it in; the crawl caught whatever was still
public in the final weeks, and even the people who saved it have never
fully cataloged what's inside.

Whether you're about to solve a 20-year-old mystery or surfing for the most
devastating blackmail material for your 30th high school reunion, chances are
the 105.9 TB of compressed image data sitting in the Webshots archive has what
you're looking for.

The photos are still in there. This is the recovery aircraft.

> Built on the work of **[Archive Team](https://wiki.archiveteam.org)** (who
> saved the data in 2012) and the **[Internet Archive](https://archive.org)**
> (who has kept it alive since). They are the only reason any of this exists.
> If this tool brings your photos home, [donate to the
> Archive](https://archive.org/donate). They earned it years ago.

---

## Preflight — no terminal required

**Windows, never used a terminal:** green **Code** button → **Download ZIP**
→ extract it → double-click **`Start_Here.bat`**. It checks for Python
(pointing you to the free installer if needed), builds itself a private
workspace, and asks one question: *what was the screen name?* Answer it.
That's the whole manual.

**Comfortable in a terminal:**

```
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
```

Python 3.10+. Windows, macOS, Linux. The venv keeps the tool's four
dependencies out of your system Python (thanks to @unquietwiki for insisting,
in [#2](../../issues/2)). If you're a [uv](https://docs.astral.sh/uv/) person,
`uv venv && uv pip install -r requirements.txt` and you already know the rest.
No APIs or logins. No encryption either, which is exactly how Webshots ran
things, and you probably now regret it.

## Cleared for departure

```
python resurrector.py find    cooldave          # half-remember the name? sweep for it
python resurrector.py search  yourscreenname    # what's on the scope?
python resurrector.py pull    yourscreenname    # bring it home
python resurrector.py friends yourscreenname    # everyone you knew in 2004
```

`search` gives you the flight-strip board: every archived album, with its
original name and photo count. `pull` recovers everything and writes a
**`gallery.html`** contact sheet. Open it in a browser and you're looking at
your albums again, original titles, original captions, twenty years later.
Yes, including the captions. You were very funny in 2004.

![a real pull, replayed from the actual logs](assets/demo.gif)

![search — the flight-strip board](assets/screenshot_search.png)


Interrupted mid-pull? Run the same command again. Finished photos hold at the
gate; photos that only landed at 800×600 get an automatic upgrade attempt to
full-size on every pass until the archive definitively says it isn't there.

### Extended operations

```
python resurrector.py search yourscreenname --deep      # dig back to 2002
python resurrector.py pull   yourscreenname --album ID  # one album only
python resurrector.py pull   yourscreenname -j 6        # more concurrency (max 8)
```

**Only half-remember the name?** `find` sweeps the archive's own index for
every screen name matching a prefix and boards them as numbered strips:
screen name, how many archived pages, first and last seen. Then just say
intentions: type `3` to search strip 3, `p3` to pull it on the spot. Spaces
are handled too: `find cool dave` sweeps `cooldave`, `cool_dave`, and
`cool-dave`, since half-remembered names tend to come back with spaces
that Webshots never allowed.

**FLIGHT PLAN REMARKS.** Screen names are callsigns; remarks are who they
were. `remarks bexbee12 Becca from HS` files a note that shows up as an
`RMK/` column on every board and at radar contact, or tag straight from
the board with `r3 Becca from HS`. Remarks live in a local `remarks.json`
next to where you run the tool. They never leave your machine.

**The social graph survived, too.** Webshots profiles had friends & fans
pages, and the crawl captured them. `friends yourscreenname` reads the
archived people pages and boards everyone you knew as numbered strips.
One test account surfaced **202 contacts** off 14 archived pages. From the
board: `3` searches strip 3, `p3` pulls their photos, `f3` walks into
*their* friends list. Recover your account, then go get everyone else's.

`--deep` runs a CDX prefix sweep over every archived variant of your profile
(pagination pages, the date-sorted view, every site redesign from 2002 to
2013) and resurrects albums you deleted years before the site died and
forgot you ever had.

## How it actually works

The Wayback Machine is the only door: the raw freeze-frame megawarcs went
access-restricted (HTTP 401) years ago and the old username index is dark. But
everything Archive Team captured was ingested into Wayback, so recovery is a
CDX-navigation problem:

```
screen name
  └─▸ CDX API: every capture of community.webshots.com/user/NAME (2002–2013)
       └─▸ profile pages → album links (+ pagination: ?start=N and /album/ID/N)
            └─▸ album grids → (thumbnail, photo-page) pairs + album titles
                 └─▸ photo detail page → the photo's REAL image URL + caption
                      └─▸ _fs.jpg original → _ph.jpg 800×600 → thumbnail
```

The design hangs on two facts. I spent a long time trying to prove both of
them wrong against the live archive, and failed:

- **You cannot guess a photo's image server.** A thumbnail on `thumb13` maps
  to full-size copies on `image04`, `image12`, `image20`. The numbers are
  unrelated. The only trustworthy source is the archived photo detail page,
  so the tool resolves every photo through its page. (Naive URL derivation,
  the thing every dead Webshots scraper attempted, silently misses almost
  everything.)
- **The 2002–2005 era is a different aircraft.** Old thumbnails ride
  `thumbN.webshots.com` with per-image load-balancer host digits (2002 was a
  lawless time), old albums paginate by path segment, and old full-size images
  live at `community.webshots.com/sym/imageN/…`, which *is* derivable, from
  the thumbnail's path digit. Paisley Ponytail speaks both eras.

Every photo descends a fallback ladder: real full-size, real 800×600, derived
guesses, and finally the archived thumbnail itself. You always land with
*something*, and the manifest records exactly which rung each photo reached.

### Field notes from the wreckage

Things the archive will not tell you until you hit them:

- The CDX API interprets `limit=-1` as *"return only the last row."* An early
  version of this tool queried with `-1` for "unlimited" and silently saw 1 of
  33 snapshots for its own test user. If you build on the CDX API, know this.
- Some full-size images were archived **as their 404 pages**. The crawler
  arrived after the image server had already given up, and Wayback faithfully
  preserved the failure. Downloads are validated by JPEG magic bytes, never by
  HTTP status alone.
- Wayback playback rewrites the same `href` absolute on one page and
  host-relative on the next, depending on which rendering path served it.
  Every extractor here accepts both, because trusting one form loses photos.
- Album grids emit each thumbnail *twice*: anchor-less in a filmstrip widget,
  anchored in the photo grid. First-match pairing silently drops a third of
  the photo-page links; the parser prefers the anchored occurrence, including
  across pagination boundaries.
- A photo that fails today is retried in full on every future run, on purpose:
  the Internet Archive occasionally backfills. Definitive absence (a real 404
  on every candidate URL) is cached in a marker file. Ambiguous failures stay
  retryable.

## Reading the instruments

![pull — full-size originals landing, with the fallback ladder visible](assets/screenshot_pull.png)

| Callout | Meaning |
|---|---|
| `LANDED  FS` | Full-size original recovered — actual camera resolution |
| `LANDED  PH` | 800×600 copy recovered (full-size not archived) |
| `UPGRADED FS` | A previous 800×600 was replaced by the located original |
| `THUMB ONLY` | Only the 100×75 thumbnail survived the crawl |
| `AT GATE` | Already on disk from an earlier run |
| `MISSED APCH` | Genuinely not in the archive — you can't land a plane that never took off |

Everything lands in `output/yourname/`, one folder per album, named by the
album's original title, with `manifest.json` (per-photo records, variants,
captions) and the `gallery.html` contact sheet alongside.

The UI palette is the **FAA standard ATC foreground set** from
**DOT/FAA/AM-20/08** (*Evaluation of a New Color Palette for ATC Displays*,
Gildea et al., 2020) — Table 1 hex codes, including the HF-STD-010A revised
Red — as evaluated on ERAM/STARS. I stared at those colors for a living once,
so when `LANDED` prints in green, that is `#23E162`, the exact scope green
from the report. A search squawks ident. No matches means no beacons
correlated to the flight plan. If you're going to do a bit, do it from the
table.

## Honest expectations

- **Account public in fall 2012** — odds are genuinely good; often most photos
  at full resolution. The Archive Team crawl was systematic.
- **Account deleted before 2012** — sometimes. Regular Wayback crawls ran from
  2002 on; `--deep` finds those albums, but early-era image coverage is patchy.
  Expect partial albums and thumbnails.
- **Albums set to private** — never archived. No tool can recover them. Your
  secrets died with the site; the one privacy feature that actually worked.

## Etiquette (read before filing complaints about speed)

archive.org is the only reason any of this still exists. All traffic funnels
through one global rate limiter (~1 request/second sustained), a 429/503 from
the tower slows *every* coroutine, retries back off exponentially, and deep
sweeps are probe-capped. Fly the published procedure.

## The NTSB docket

The full accident investigation: what Webshots was, how fourteen million
photo libraries went down with it, why the wreckage sat locked for a decade,
and the reverse engineering that got it open, era by era, with findings and
probable cause.

**[Read DOCKET.md →](DOCKET.md)**

> **Operator's statement:** *Now, I just need everyone to break it again.*

The investigation remains open: if a screen name that should work comes back
empty, [file a report](../../issues). Every report gets looked at.

## The robot in the room

You'll find Claude all over this repo's commit history because I build with
AI tools, heavily, and I'm not going to pretend otherwise. So, for the person
about to type "thanks claude": the nine years of Wayback spelunking are mine.
The URL doctrine (which numbers derive and which ones lie), the era grammar,
the test accounts, and the air traffic control in your terminal are also
mine. Claude typed most of the code at a speed I'm never going to match, and
yes, it drafted a lot of these sentences too, working from my notes and my
war stories. If a paragraph lands a little too cleanly, that's why. I
hand-rolled an earlier version of this tool years ago and it topped out
around a third of a test account. This one gets nearly all of it, mostly
because automating the grunt work let me test every assumption against the
live archive instead of trusting my old notes. The facts underneath are mine
and they're checkable, photo IDs included. If one doesn't hold, file a
report.

## Why this exists

Between 1995 and 2012, millions of people uploaded the only copies of their
family photos to Webshots. Mine were in there too. I spent nine years getting
them back, one Wayback page at a time. Nobody should have to do that twice.

---

**Tailstrike Studios × Ash Airfoil** // coldbricks · MIT license ·
Not affiliated with the Internet Archive; just a grateful guest on their frequency.

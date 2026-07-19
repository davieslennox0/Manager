"""Newly-funded pipeline: watches crypto funding-round coverage (VC/press RSS +
a crypto-native raise tracker), records each freshly-funded firm, probes its
career board, and feeds the results into the EXISTING listing feed two ways:
 - firm has open roles  -> its board becomes a scanner source; those listings
   get newly_funded=1 and surface behind the board's "Newly funded" filter
 - no roles posted yet  -> the firm sits in a speculative tier ("recently
   funded, likely hiring soon") served by /v1/funded
The scanner itself is untouched — this module only inserts source rows and
flips a flag column on listings it recognizes."""
import asyncio
import html
import re
import time
import uuid

import feedparser
import httpx

import config
from db import get_conn

# Feeds ordered by signal quality: a dedicated raise tracker first, then
# funding-tagged and general crypto press (the raise regex filters the noise).
FUNDING_FEEDS = [
    ("crypto-fundraising.info", "https://crypto-fundraising.info/blog/feed/"),
    ("Cointelegraph funding", "https://cointelegraph.com/rss/tag/funding"),
    ("TechCrunch crypto", "https://techcrunch.com/category/cryptocurrency/feed/"),
]

# "Velocity raises $38M to build…", "Crypto.com raised $400M in a funding
# round from…", "EDX lands $76M from SBI". Completed raises only — verbs like
# "seeks"/"eyes" deliberately absent. Case matters for the firm chain (press
# capitalizes names; a case-insensitive [A-Z] would spill across sentences),
# so only the verb/unit groups carry (?i:).
_WORD = r"[A-Z0-9][\w&']*(?:\.[\w&']+)*"
_RAISE_RE = re.compile(
    rf"(?P<firm>{_WORD}(?:[ \-]{_WORD}){{0,3}})\s+"
    r"(?i:raises|raised|lands|landed|secures|secured|closes|closed|bags|nets)\s+"
    r"\$(?P<amt>\d[\d,.]*)\s*(?P<unit>[MBK]\b|(?i:million|billion))")

_ROUND_RE = re.compile(
    r"\b(pre-seed|seed|series [a-e]|strategic|private|extension|bridge)\b", re.I)

# Generic leading words press headlines prepend to the actual firm name.
_FIRM_NOISE = re.compile(
    r"^(?:crypto(?:currency)?|blockchain|web3|bitcoin|defi|nft|ai|startup|exchange|"
    r"platform|protocol|firm|company|vc|wallet|institutional|stablecoin|issuer|"
    r"maker|giant|app)\s+", re.I)


def normalize_firm(name: str) -> str:
    """Lowercase matching key: also how funded firms are matched to listings."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def parse_raises(text: str) -> list[dict]:
    """Extract completed raises from a headline blob or digest body."""
    out, seen = [], set()
    for m in _RAISE_RE.finditer(text):
        firm = m.group("firm").strip()
        # strip descriptive prefixes until the name stabilizes
        while True:
            stripped = _FIRM_NOISE.sub("", firm)
            if stripped == firm:
                break
            firm = stripped
        norm = normalize_firm(firm)
        if not firm or len(norm) < 3 or norm in seen:
            continue
        seen.add(norm)
        unit = m.group("unit").upper()[0]
        amount = f"${m.group('amt').rstrip('.')}{ {'M': 'M', 'B': 'B', 'K': 'K'}[unit] }"
        # round type must come from THIS raise's sentence, not the next deal's
        window = m.group(0) + text[m.end():m.end() + 100].split(". ")[0]
        rm = _ROUND_RE.search(window)
        out.append({"firm": firm, "normalized": norm, "amount": amount,
                    "round": (rm.group(1).title() if rm else "")})
    return out


async def _fetch_feed(url: str) -> feedparser.FeedParserDict:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "ManagerX/1.0 funding watcher"}) as c:
        resp = await c.get(url)
    resp.raise_for_status()
    return feedparser.parse(resp.text)


def _entry_blob(entry) -> str:
    """Title + body text of a feed entry, tags stripped (digest feeds put the
    whole deal list in the body)."""
    parts = [entry.get("title", "")]
    content = entry.get("content") or []
    parts.append(content[0].get("value", "") if content else entry.get("summary", ""))
    text = re.sub(r"<[^>]+>", " ", " ".join(parts))
    return html.unescape(re.sub(r"\s+", " ", text))


async def poll_funding_feeds() -> list[str]:
    """Pull every funding feed, upsert firms; returns firm_ids new this pass."""
    new_ids = []
    for _feed_name, url in FUNDING_FEEDS:
        try:
            feed = await _fetch_feed(url)
        except Exception:
            continue  # a dead feed shouldn't block the others
        conn = get_conn()
        for entry in feed.entries[:60]:
            announced = (entry.get("published", "") or "")[:16]
            link = entry.get("link", "")
            for hit in parse_raises(_entry_blob(entry)):
                exists = conn.execute("SELECT firm_id FROM funded_firms WHERE normalized=?",
                                      (hit["normalized"],)).fetchone()
                if exists:
                    continue
                fid = "fnd_" + uuid.uuid4().hex[:12]
                conn.execute(
                    """INSERT INTO funded_firms (firm_id, name, normalized, round,
                       amount, announced_at, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (fid, hit["firm"], hit["normalized"], hit["round"],
                     hit["amount"], announced, link))
                new_ids.append(fid)
        conn.commit()
        conn.close()
    return new_ids


def slug_candidates(name: str) -> list[str]:
    """Career-board slug guesses for a firm name."""
    low = name.lower().strip()
    joined = re.sub(r"[^a-z0-9]+", "", low)
    dashed = re.sub(r"[^a-z0-9]+", "-", low).strip("-")
    first = low.split()[0] if low.split() else ""
    out = []
    for c in (joined, dashed, first, joined + "labs", joined + "hq"):
        if c and len(c) >= 3 and c not in out:
            out.append(c)
    return out


async def probe_careers(name: str) -> tuple[str, str, int] | None:
    """Try Greenhouse then Lever public boards; (kind, slug, open_roles) or None."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "ManagerX/1.0 funding watcher"}) as c:
        for slug in slug_candidates(name):
            try:
                r = await c.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
                if r.status_code == 200:
                    return ("greenhouse", slug, len(r.json().get("jobs", [])))
            except httpx.HTTPError:
                pass
            try:
                r = await c.get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
                if r.status_code == 200 and isinstance(r.json(), list):
                    return ("lever", slug, len(r.json()))
            except (httpx.HTTPError, ValueError):
                pass
    return None


async def check_careers(limit: int = 8):
    """Probe boards for funded firms not yet checked (a few per tick — these
    are guess-probes against third-party APIs, keep the volume polite)."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT firm_id, name FROM funded_firms WHERE active=1 AND
           careers_checked_at IS NULL ORDER BY first_seen DESC LIMIT ?""",
        (limit,)).fetchall()
    conn.close()
    for row in rows:
        found = await probe_careers(row["name"])
        conn = get_conn()
        if found:
            kind, slug, n_roles = found
            conn.execute("UPDATE funded_firms SET careers_kind=?, careers_target=?, "
                         "careers_checked_at=CURRENT_TIMESTAMP WHERE firm_id=?",
                         (kind, slug, row["firm_id"]))
            # Register the board as a scanner source — the existing scanner
            # loop polls it like any seeded firm. Dedup on (kind, target).
            dup = conn.execute("SELECT 1 FROM sources WHERE kind=? AND target=?",
                               (kind, slug)).fetchone()
            if not dup and n_roles > 0:
                conn.execute(
                    "INSERT INTO sources (source_id, kind, name, target, poll_seconds) "
                    "VALUES (?, ?, ?, ?, 21600)",
                    ("src_" + uuid.uuid4().hex[:10], kind, row["name"], slug))
        else:
            conn.execute("UPDATE funded_firms SET careers_checked_at=CURRENT_TIMESTAMP "
                         "WHERE firm_id=?", (row["firm_id"],))
        conn.commit()
        conn.close()


def apply_funded_tags():
    """Maintain listings.newly_funded from the funded-firms set: tag listings
    whose firm matches an active funded firm, untag when the window expires,
    and flip matched firms speculative -> hiring."""
    conn = get_conn()
    cutoff = time.time() - config.FUNDING_FRESH_DAYS * 86400
    conn.execute("UPDATE funded_firms SET active=0 WHERE active=1 AND "
                 "strftime('%s', first_seen) < ?", (str(int(cutoff)),))
    firms = conn.execute("SELECT firm_id, normalized, status FROM funded_firms "
                         "WHERE active=1").fetchall()
    active_norms = set()
    for firm in firms:
        active_norms.add(firm["normalized"])
        hits = [r["listing_id"] for r in conn.execute(
            "SELECT listing_id, firm FROM listings WHERE active=1").fetchall()
            if normalize_firm(r["firm"]) == firm["normalized"]]
        if hits:
            qmarks = ",".join("?" * len(hits))
            conn.execute(f"UPDATE listings SET newly_funded=1 "
                         f"WHERE listing_id IN ({qmarks})", hits)
            if firm["status"] != "hiring":
                conn.execute("UPDATE funded_firms SET status='hiring' WHERE firm_id=?",
                             (firm["firm_id"],))
    # expire the tag on listings whose firm is no longer in the fresh window
    stale = [r["listing_id"] for r in conn.execute(
        "SELECT listing_id, firm FROM listings WHERE newly_funded=1").fetchall()
        if normalize_firm(r["firm"]) not in active_norms]
    if stale:
        qmarks = ",".join("?" * len(stale))
        conn.execute(f"UPDATE listings SET newly_funded=0 WHERE listing_id IN ({qmarks})",
                     stale)
    conn.commit()
    conn.close()


async def funding_tick() -> dict:
    new_firms = await poll_funding_feeds()
    await check_careers()
    apply_funded_tags()
    return {"new_firms": len(new_firms)}


async def funding_loop():
    """Background task started by main.py, independent of the scanner loop."""
    while True:
        try:
            await funding_tick()
        except Exception:
            pass  # never kill the loop; next tick retries
        await asyncio.sleep(config.FUNDING_TICK_SECONDS)

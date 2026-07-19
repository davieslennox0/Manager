"""Job-listing scanner: polls configured sources (Greenhouse/Lever public board
APIs, RSS feeds, LLM-assisted page scrape as a last resort), normalizes every
posting into the common listing schema, dedups across sources, and feeds the
public board + email digests. Sources are rows in the `sources` table so adding
a firm is an INSERT, not a deploy."""
import asyncio
import hashlib
import html
import json
import re
import time
import uuid

import feedparser
import httpx

import config
from db import get_conn
from llm import LLMError, generate_json

# Unambiguous names match case-insensitively on word boundaries; names that are
# also English words (Base, Near, Ton, Sui, Tron...) require their branded
# casing to count, else "database"/"Boston"/"suitable" all tag falsely.
_ECO_SAFE = ["ethereum", "solana", "bitcoin", "polygon", "arbitrum", "optimism",
             "avalanche", "cosmos", "polkadot", "aptos", "starknet", "zksync",
             "x layer", "cardano"]
_ECO_BRANDED = ["Base", "NEAR", "Near Protocol", "Sui", "TON", "TRON", "BNB"]

# Ordered: first bucket whose keyword hits the ROLE TITLE wins, so specific
# buckets (Security, Design) sit above the broad ones they'd otherwise lose to
# ("Security Engineer" -> Security, "Product Designer" -> Design).
_CATEGORIES = [
    ("Security", ["security", "auditor", "audit", "pentest", "cryptograph", "incident"]),
    ("Design", ["design", "ux", "ui ", "brand", "creative", "motion", "graphic", "art director"]),
    ("Data & Research", ["data", "analytics", "analyst", "machine learning", "ml engineer",
                         "scientist", "research", "quant", "economist", "ai "]),
    ("Product", ["product manager", "product owner", "product lead", "program manager",
                 "project manager", "technical writer", "documentation"]),
    ("Engineering", ["engineer", "developer", "solidity", "rust", "backend", "frontend",
                     "full-stack", "fullstack", "full stack", "devops", "sre", "software",
                     "protocol", "smart contract", "infrastructure", "architect", "qa",
                     "mobile", "android", "ios", "sdet", "tech lead", "cto"]),
    ("Marketing & Growth", ["marketing", "growth", "content", "seo", "social media",
                            "communication", "comms", "public relations", "pr manager",
                            "copywriter", "brand", "events", "ecosystem"]),
    ("Sales & BD", ["sales", "business development", "bd manager", "partnership",
                    "account manager", "account executive", "listings manager",
                    "institutional", "otc"]),
    ("Community & Support", ["community", "ambassador", "moderator", "support",
                             "customer", "success"]),
    ("Legal & Compliance", ["legal", "counsel", "compliance", "regulatory", "policy",
                            "aml", "kyc", "risk"]),
    ("Operations & People", ["operations", "office", "people", "hr ", "human resources",
                             "recruit", "talent", "finance", "accounting", "accountant",
                             "treasury", "payroll", "executive assistant", "chief of staff"]),
]

_SKILL_HINTS = ["solidity", "rust", "go", "typescript", "python", "react", "node",
                "evm", "defi", "zk", "cryptography", "smart contract", "protocol",
                "security", "audit", "devops", "kubernetes", "data", "ml",
                "marketing", "bd", "community", "design", "product", "legal"]

SCRAPE_PROMPT = """Extract open job listings from this careers-page text. Reply with
ONLY JSON: {{"listings": [{{"role": "", "firm": "", "location": "", "remote": "yes|no|hybrid|''",
"comp_range": "", "url": "absolute link if present else ''", "posted_at": ""}}]}}.
Maximum 30 listings. If none, return {{"listings": []}}.

Page text:
{page}"""


def _tag_ecosystem(text: str) -> str:
    for e in _ECO_SAFE:
        if re.search(rf"\b{re.escape(e)}\b", text, re.I):
            return e.title()
    for e in _ECO_BRANDED:
        if re.search(rf"\b{re.escape(e)}\b", text):
            return {"NEAR": "Near", "Near Protocol": "Near", "TON": "Ton",
                    "TRON": "Tron"}.get(e, e)
    return ""


def _tag_category(role: str, blob: str = "") -> str:
    """Bucket a listing by role title first, full text as tiebreaker."""
    for text in (role.lower(), blob.lower()):
        if not text:
            continue
        for name, keywords in _CATEGORIES:
            if any(k in text for k in keywords):
                return name
    return "Other"


def _tag_skills(text: str) -> list[str]:
    low = text.lower()
    return [s for s in _SKILL_HINTS if s in low][:10]


def _content_hash(firm: str, role: str, location: str) -> str:
    key = "|".join(x.strip().lower() for x in (firm, role, location))
    return hashlib.sha256(key.encode()).hexdigest()


def _strip_html(markup: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text))


async def _fetch_json(url: str):
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "ManagerX/1.0 job scanner"}) as c:
        resp = await c.get(url)
    resp.raise_for_status()
    return resp.json()


async def _poll_greenhouse(source) -> list[dict]:
    data = await _fetch_json(
        f"https://boards-api.greenhouse.io/v1/boards/{source['target']}/jobs?content=true")
    out = []
    for jb in data.get("jobs", []):
        blob = f"{jb.get('title', '')} {_strip_html(jb.get('content', '') or '')}"
        out.append({
            "external_id": str(jb.get("id", "")),
            "role": jb.get("title", ""), "firm": source["name"],
            "location": (jb.get("location") or {}).get("name", ""),
            "remote": "yes" if "remote" in blob.lower() else "",
            "comp_range": "", "url": jb.get("absolute_url", ""),
            "posted_at": (jb.get("updated_at") or "")[:10],
            "ecosystem": _tag_ecosystem(blob), "skills": _tag_skills(blob),
        })
    return out


async def _poll_lever(source) -> list[dict]:
    data = await _fetch_json(f"https://api.lever.co/v0/postings/{source['target']}?mode=json")
    out = []
    for jb in data if isinstance(data, list) else []:
        cats = jb.get("categories") or {}
        blob = f"{jb.get('text', '')} {_strip_html(jb.get('description', '') or '')}"
        out.append({
            "external_id": jb.get("id", ""),
            "role": jb.get("text", ""), "firm": source["name"],
            "location": cats.get("location", ""),
            "remote": "yes" if "remote" in (cats.get("location") or "").lower() else "",
            "comp_range": "", "url": jb.get("hostedUrl", ""),
            "posted_at": time.strftime("%Y-%m-%d", time.gmtime((jb.get("createdAt") or 0) / 1000))
                         if jb.get("createdAt") else "",
            "ecosystem": _tag_ecosystem(blob), "skills": _tag_skills(blob),
        })
    return out


async def _poll_rss(source) -> list[dict]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "ManagerX/1.0 job scanner"}) as c:
        resp = await c.get(source["target"])
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    out = []
    for entry in feed.entries[:100]:
        blob = f"{entry.get('title', '')} {entry.get('summary', '')}"
        title = html.unescape(entry.get("title", ""))
        # aggregator feeds usually title as "Role at Firm" / "Role — Firm"
        m = re.split(r"\s+at\s+|\s+—\s+|\s+-\s+", title, maxsplit=1)
        role, firm = (m[0], m[1]) if len(m) == 2 else (title, source["name"])
        out.append({
            "external_id": entry.get("id", entry.get("link", "")),
            "role": role.strip(), "firm": firm.strip(),
            "location": "", "remote": "yes" if "remote" in blob.lower() else "",
            "comp_range": "", "url": entry.get("link", ""),
            "posted_at": (entry.get("published", "") or "")[:16],
            "ecosystem": _tag_ecosystem(blob), "skills": _tag_skills(blob),
        })
    return out


async def _poll_scrape(source) -> list[dict]:
    """Fallback for career pages with no API/feed: fetch, strip, LLM-extract."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "ManagerX/1.0 job scanner"}) as c:
        resp = await c.get(source["target"])
    resp.raise_for_status()
    text = _strip_html(resp.text)[:25000]
    data = await generate_json(SCRAPE_PROMPT.format(page=text))
    out = []
    for jb in data.get("listings", [])[:30]:
        blob = json.dumps(jb)
        out.append({
            "external_id": "", "role": jb.get("role", ""),
            "firm": jb.get("firm", "") or source["name"],
            "location": jb.get("location", ""), "remote": jb.get("remote", ""),
            "comp_range": jb.get("comp_range", ""),
            "url": jb.get("url", "") or source["target"],
            "posted_at": jb.get("posted_at", ""),
            "ecosystem": _tag_ecosystem(blob), "skills": _tag_skills(blob),
        })
    return out


_POLLERS = {"greenhouse": _poll_greenhouse, "lever": _poll_lever,
            "rss": _poll_rss, "scrape": _poll_scrape}


def _upsert_listings(source_id: str, rows: list[dict]) -> list[str]:
    """Dedup by content hash; returns listing_ids that are NEW this pass."""
    conn = get_conn()
    new_ids = []
    for r in rows:
        if not r["role"] or not r["url"]:
            continue
        ch = _content_hash(r["firm"], r["role"], r["location"])
        existing = conn.execute("SELECT listing_id FROM listings WHERE content_hash = ?",
                                (ch,)).fetchone()
        if existing:
            conn.execute("UPDATE listings SET last_seen=CURRENT_TIMESTAMP, active=1 "
                         "WHERE listing_id=?", (existing["listing_id"],))
            continue
        lid = "lst_" + uuid.uuid4().hex[:12]
        conn.execute(
            """INSERT INTO listings (listing_id, source_id, external_id, role, firm,
               ecosystem, comp_range, skills, remote, location, url, posted_at,
               category, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (lid, source_id, r["external_id"], r["role"], r["firm"], r["ecosystem"],
             r["comp_range"], json.dumps(r["skills"]), r["remote"], r["location"],
             r["url"], r["posted_at"],
             _tag_category(r["role"], " ".join(r["skills"])), ch))
        new_ids.append(lid)
    conn.commit()
    conn.close()
    return new_ids


async def poll_source(source) -> list[str]:
    poller = _POLLERS.get(source["kind"])
    if not poller:
        raise ValueError(f"unknown source kind {source['kind']!r}")
    rows = await poller(source)
    return _upsert_listings(source["source_id"], rows)


async def scan_due_sources() -> dict:
    """One scheduler tick: poll every active source whose interval has elapsed."""
    conn = get_conn()
    due = conn.execute(
        """SELECT * FROM sources WHERE active = 1 AND (last_polled IS NULL OR
           strftime('%s','now') - strftime('%s', last_polled) >= poll_seconds)""").fetchall()
    conn.close()
    all_new = []
    for source in due:
        err = None
        try:
            all_new += await poll_source(dict(source))
        except (httpx.HTTPError, LLMError, ValueError, json.JSONDecodeError) as e:
            err = str(e)[:300]
        conn = get_conn()
        conn.execute("UPDATE sources SET last_polled=CURRENT_TIMESTAMP, last_error=? "
                     "WHERE source_id=?", (err, source["source_id"]))
        conn.commit()
        conn.close()
    return {"sources_polled": len(due), "new_listings": all_new}


# Seed sources: firms with public Greenhouse/Lever boards + crypto job feeds.
# Wrong/renamed slugs simply record last_error and are skipped — fix by UPDATE.
SEED_SOURCES = [
    ("greenhouse", "ConsenSys", "consensys", 21600),
    ("greenhouse", "OKX", "okx", 21600),
    ("greenhouse", "Paradigm", "paradigm", 21600),
    ("greenhouse", "Fireblocks", "fireblocks", 21600),
    ("greenhouse", "BitGo", "bitgo", 21600),
    ("greenhouse", "Messari", "messari", 21600),
    ("lever", "Ledger", "ledger", 21600),
    ("lever", "Kraken", "kraken123", 21600),
    ("lever", "Binance", "binance", 21600),
    ("lever", "Immutable", "immutable", 21600),
    ("rss", "CryptocurrencyJobs", "https://cryptocurrencyjobs.co/index.xml", 3600),
]


def backfill_categories():
    """One-time pass for rows inserted before the category column existed."""
    conn = get_conn()
    rows = conn.execute("SELECT listing_id, role, skills FROM listings "
                        "WHERE category = ''").fetchall()
    for r in rows:
        conn.execute("UPDATE listings SET category = ? WHERE listing_id = ?",
                     (_tag_category(r["role"], r["skills"] or ""), r["listing_id"]))
    conn.commit()
    conn.close()


def seed_sources():
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"]
    if count == 0:
        for kind, name, target, interval in SEED_SOURCES:
            conn.execute(
                "INSERT INTO sources (source_id, kind, name, target, poll_seconds) "
                "VALUES (?, ?, ?, ?, ?)",
                ("src_" + uuid.uuid4().hex[:10], kind, name, target, interval))
        conn.commit()
    conn.close()


async def scanner_loop():
    """Background task started by main.py; digests ride the same tick."""
    from mailer import send_deadline_reminders, send_digests, send_job_match_alerts
    while True:
        try:
            result = await scan_due_sources()
            if result["new_listings"]:
                await asyncio.to_thread(send_digests, result["new_listings"])
                await asyncio.to_thread(send_job_match_alerts, result["new_listings"])
            await asyncio.to_thread(send_deadline_reminders)
        except Exception:
            pass  # a failing tick must never kill the loop; per-source errors are stored
        await asyncio.sleep(config.SCANNER_TICK_SECONDS)

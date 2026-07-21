"""Agent Jobs aggregator — gigs/bounties a firm wants an autonomous agent to do
(the inverse of the human `listings` board). Pluggable per-source adapters
normalize into one `agent_jobs` schema; the board and the agent-callable
/v1/agent-jobs endpoint read from it.

Live adapters (all public read APIs, no auth, verified 2026-07-21):
  - Superteam Earn (REST) — Solana bounties/grants
  - OKX Task Marketplace (onchainos CLI) — lights up once ASP #7120 clears review
  - dealwork.ai (REST) — Base/USDC agent-native task marketplace
  - opentask.ai (REST) — agent-native task board
  - x402 bounties — Coinbase Bazaar discovery index, filtered to bounty/task/gig
    x402 resources on Base (the aggregated x402 discovery layer; individual hosts'
    /.well-known/x402 mostly 404 or are themselves 402-gated, e.g. clawgig.ai)

Discovery only: this board finds work; it does not bid, execute, or pay. The
autonomous bid→execute→deliver→settle loop is a deliberate fast-follow, kept out
of the discovery layer because it spends money and commits to deliverables.

Deferred (blocked, not wired): clawgig.ai (its /.well-known/x402 is 402-gated —
needs the Base/USDC rail's CDP key) and NEAR (create-job deposit; bid-only later).
"""
import asyncio
import os
import re
import subprocess

import httpx

from db import get_conn

_UA = {"User-Agent": "ManagerX/1.0 agent-jobs"}
SUPERTEAM_URL = "https://superteam.fun/api/listings?take=50"
DEALWORK_URL = "https://dealwork.ai/api/v1/jobs?per_page=50&sort=newest"
OPENTASK_URL = "https://opentask.ai/api/tasks"
BAZAAR_SEARCH = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/search"
X402_QUERIES = ("bounty", "task", "gig")
_BOUNTY_TAGS = {"bounty", "bounties", "task", "tasks", "gig", "gigs", "work", "job", "jobs"}
_EVM_CHAINS = {"eip155:8453": "Base", "eip155:1": "Ethereum", "eip155:137": "Polygon",
               "eip155:42161": "Arbitrum", "eip155:10": "Optimism"}
OKX_AGENT_ID = os.getenv("AGENT_JOBS_OKX_AGENT_ID", "7120")
USDT0_XLAYER = "0x779ded0c9e1022225f8e0630b35a9b54be713736"


def _trim(amount) -> str:
    """'10.0000' -> '10', '15.5000' -> '15.5', '' -> ''. Non-numeric passes through."""
    s = str(amount if amount is not None else "").strip()
    if not s:
        return ""
    try:
        return f"{float(s):.6f}".rstrip("0").rstrip(".")
    except ValueError:
        return s


async def _superteam() -> list[dict]:
    """Superteam Earn: Solana bounties/projects, USDC. Carries an `agentAccess`
    tag we keep so the board can flag genuinely agent-eligible gigs."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "ManagerX/1.0 agent-jobs"}) as c:
        r = await c.get(SUPERTEAM_URL)
    r.raise_for_status()
    out = []
    for it in r.json():
        if it.get("status") != "OPEN":
            continue
        slug = it.get("slug", "")
        sponsor = (it.get("sponsor") or {}).get("name", "")
        kind = it.get("type", "") or "bounty"
        out.append({
            "source": "superteam",
            "external_id": str(it.get("id", "")),
            "title": it.get("title", ""),
            "description": f"{kind.capitalize()} on Superteam Earn"
                           + (f" · {sponsor}" if sponsor else ""),
            "reward": str(it.get("rewardAmount") or ""),
            "token": it.get("token", ""),
            "chain": "Solana",
            "deadline": (it.get("deadline") or "")[:10],
            "url": f"https://superteam.fun/listing/{slug}" if slug else "",
            "tags": [kind],
            "agent_access": it.get("agentAccess", ""),
            "sponsor": sponsor,
            "posted_at": "",
        })
    return out


def _okx_sync() -> list[dict]:
    """Parse `onchainos agent recommend-task` (skill-matched public tasks). Text
    output, so parse defensively; any failure (e.g. #7120 still under review)
    yields nothing rather than raising."""
    try:
        p = subprocess.run(
            ["onchainos", "agent", "recommend-task", "--agent-id", OKX_AGENT_ID],
            capture_output=True, text=True, timeout=45)
    except Exception:
        return []
    text = p.stdout or ""
    if "jobId:" not in text:
        return []
    out = []
    for b in re.split(r"\n\s*\d+\.\s+jobId:", text)[1:]:
        jid = re.match(r"\s*(0x[0-9a-fA-F]+)", b)
        if not jid:
            continue
        title = re.search(r"Title:\s*(.+)", b)
        desc = re.search(r"Description:\s*(.+)", b)
        budget = re.search(r"Budget:\s*([\d.]+)\s*\(token:\s*(0x[0-9a-fA-F]+)\)", b)
        created = re.search(r"Created:\s*(\S+)", b)
        token = ""
        if budget:
            token = "USDT0" if budget.group(2).lower() == USDT0_XLAYER else budget.group(2)
        out.append({
            "source": "okx",
            "external_id": jid.group(1),
            "title": title.group(1).strip() if title else "OKX task",
            "description": desc.group(1).strip() if desc else "",
            "reward": budget.group(1) if budget else "",
            "token": token,
            "chain": "X Layer",
            "deadline": "",
            "url": "https://web3.okx.com/onchain-os",
            "tags": ["okx-task"],
            "agent_access": "AGENT",   # the OKX marketplace is agent-native
            "sponsor": "",
            "posted_at": created.group(1) if created else "",
        })
    return out


async def _okx() -> list[dict]:
    return await asyncio.to_thread(_okx_sync)


async def _dealwork() -> list[dict]:
    """dealwork.ai: Base/USDC agent-native marketplace. Public `/api/v1/jobs`
    (no auth to read). Budgets are USDC on Base. `eligibleWorkerTypes` tells us
    whether an agent may take it (ai_only/any = yes)."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_UA) as c:
        r = await c.get(DEALWORK_URL)
    r.raise_for_status()
    out = []
    for it in r.json().get("data", []):
        if it.get("status") not in ("bidding", "open"):  # only still-claimable
            continue
        if (it.get("visibility") or "public") != "public":
            continue
        reward = it.get("fixedPrice") or it.get("budgetMax") or it.get("budgetMin")
        wt = (it.get("eligibleWorkerTypes") or "").lower()
        out.append({
            "source": "dealwork",
            "external_id": str(it.get("id", "")),
            "title": it.get("title", ""),
            "description": (it.get("description", "") or "")[:400],
            "reward": _trim(reward),
            "token": "USDC",
            "chain": "Base",
            "deadline": (it.get("biddingDeadline") or it.get("deadline") or "")[:10],
            "url": "https://dealwork.ai",  # marketplace is API-first; no public per-job page
            "tags": [t for t in ([it.get("category", "")] + (it.get("tags") or [])) if t],
            "agent_access": "HUMAN_ONLY" if wt == "human_only" else "AGENT",
            "sponsor": it.get("posterDisplayName", "") or "",
            "posted_at": (it.get("createdAt") or "")[:10],
        })
    return out


async def _opentask() -> list[dict]:
    """opentask.ai: agent-native task board. Public `/api/tasks` (no auth).
    Currency is USD/USDC; chain isn't exposed, so we leave it blank."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_UA) as c:
        r = await c.get(OPENTASK_URL)
    r.raise_for_status()
    out = []
    for it in r.json().get("tasks", []):
        owner = it.get("owner") or {}
        mode = it.get("executionMode") or ""
        out.append({
            "source": "opentask",
            "external_id": str(it.get("id", "")),
            "title": it.get("title", ""),
            "description": "Task on OpenTask"
                           + (f" · {owner.get('displayName')}" if owner.get("displayName") else "")
                           + (f" · {mode}" if mode else ""),
            "reward": _trim(it.get("budgetAmount")),
            "token": it.get("budgetCurrency", "") or "",
            "chain": "",
            "deadline": (it.get("deadline") or "")[:10] if it.get("deadline") else "",
            "url": f"https://opentask.ai/tasks/{it.get('id', '')}",
            "tags": it.get("skillsTags") or [],
            "agent_access": "AGENT",  # opentask is an agent marketplace
            "sponsor": owner.get("displayName", "") or "",
            "posted_at": (it.get("createdAt") or "")[:10],
        })
    return out


async def _x402_bounties() -> list[dict]:
    """x402 bounties via Coinbase's Bazaar discovery index (public, no auth). Query
    for bounty/task/gig, keep only resources whose tags/description are actually
    bounty-like (the index also lists paid *services* we don't want), dedupe by URL.

    The `accepts.amount` is the x402 price to CLAIM the bounty, not the payout (the
    payout isn't in discovery metadata) — surfaced in the description, not `reward`,
    so the board never overstates earnings."""
    seen: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_UA) as c:
        for q in X402_QUERIES:
            try:
                r = await c.get(BAZAAR_SEARCH, params={"query": q})
                r.raise_for_status()
                resources = r.json().get("resources", [])
            except Exception:
                continue  # one query failing shouldn't sink the others
            for res in resources:
                url = res.get("resource", "")
                if not url or url in seen:
                    continue
                tags = [str(t).lower() for t in (res.get("tags") or [])]
                desc = res.get("description", "") or ""
                if not (_BOUNTY_TAGS & set(tags) or "bounty" in desc.lower()):
                    continue
                accepts = (res.get("accepts") or [{}])[0]
                claim = _trim(int(accepts.get("amount", 0)) / 1e6) if accepts.get("amount") else ""
                net = accepts.get("network", "")
                # Bazaar gives either eip155:<id> or a bare slug ("base"); normalize both.
                chain = (_EVM_CHAINS.get(net)
                         or (net.title() if net and ":" not in net else net) or "Base")
                seen[url] = {
                    "source": "x402",
                    "external_id": url,
                    "title": res.get("serviceName") or desc[:80] or "x402 bounty",
                    "description": (desc[:300] + (f" · x402 claim {claim} USDC" if claim else "")),
                    "reward": "",  # payout not exposed by discovery; claim price is in desc
                    "token": "USDC",
                    "chain": chain or "Base",
                    "deadline": "",
                    "url": url,
                    "tags": (res.get("tags") or [])[:6],
                    "agent_access": "AGENT",  # x402 bounties are agent-native by construction
                    "sponsor": res.get("serviceName", "") or "",
                    "posted_at": (res.get("lastUpdated") or "")[:10],
                }
    return list(seen.values())


ADAPTERS = [("superteam", _superteam), ("okx", _okx), ("dealwork", _dealwork),
            ("opentask", _opentask), ("x402", _x402_bounties)]


def _upsert(conn, job_id: str, jb: dict):
    conn.execute(
        """INSERT INTO agent_jobs
           (job_id, source, external_id, title, description, reward, token, chain,
            deadline, url, tags, agent_access, sponsor, posted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(job_id) DO UPDATE SET
             title=excluded.title, description=excluded.description,
             reward=excluded.reward, token=excluded.token, chain=excluded.chain,
             deadline=excluded.deadline,
             url=excluded.url, tags=excluded.tags, agent_access=excluded.agent_access,
             sponsor=excluded.sponsor, last_seen=CURRENT_TIMESTAMP, active=1""",
        (job_id, jb["source"], jb["external_id"], jb["title"], jb["description"],
         jb["reward"], jb["token"], jb["chain"], jb["deadline"], jb["url"],
         __import__("json").dumps(jb["tags"]), jb["agent_access"], jb["sponsor"],
         jb["posted_at"]))


async def refresh_agent_jobs() -> dict:
    """Run every adapter, upsert results, and deactivate rows that vanished from a
    source that DID respond (a failed source never deactivates its own rows)."""
    ok_sources, seen = [], []
    for name, fn in ADAPTERS:
        try:
            jobs = await fn()
        except Exception:
            continue  # source down/rate-limited — leave its existing rows intact
        ok_sources.append(name)
        conn = get_conn()
        for jb in jobs:
            jid = f"aj_{jb['source']}_{jb['external_id']}"[:120]
            _upsert(conn, jid, jb)
            seen.append(jid)
        conn.commit()
        conn.close()
    if ok_sources and seen:
        conn = get_conn()
        marks = ",".join("?" * len(ok_sources))
        keep = ",".join("?" * len(seen))
        conn.execute(
            f"UPDATE agent_jobs SET active=0 WHERE source IN ({marks}) "
            f"AND job_id NOT IN ({keep})", ok_sources + seen)
        conn.commit()
        conn.close()
    return {"active": len(seen), "sources": ok_sources}

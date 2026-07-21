"""Agent Jobs aggregator — gigs/bounties a firm wants an autonomous agent to do
(the inverse of the human `listings` board). Pluggable per-source adapters
normalize into one `agent_jobs` schema; the board and the agent-callable
/v1/agent-jobs endpoint read from it.

Live adapters: Superteam Earn (public REST) and OKX Task Marketplace (via the
onchainos CLI — lights up once our ASP #7120 clears review). Other agent-economy
sources (AgentWork, ClawTasks, Moltverr, Virtuals, RentAHuman…) are adapters-in-
waiting: real endpoints, but currently down / key-gated / unlaunched (verified
2026-07-21), so they're intentionally not wired until they return data."""
import asyncio
import os
import re
import subprocess

import httpx

from db import get_conn

SUPERTEAM_URL = "https://superteam.fun/api/listings?take=50"
OKX_AGENT_ID = os.getenv("AGENT_JOBS_OKX_AGENT_ID", "7120")
USDT0_XLAYER = "0x779ded0c9e1022225f8e0630b35a9b54be713736"


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


ADAPTERS = [("superteam", _superteam), ("okx", _okx)]


def _upsert(conn, job_id: str, jb: dict):
    conn.execute(
        """INSERT INTO agent_jobs
           (job_id, source, external_id, title, description, reward, token, chain,
            deadline, url, tags, agent_access, sponsor, posted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(job_id) DO UPDATE SET
             title=excluded.title, description=excluded.description,
             reward=excluded.reward, token=excluded.token, deadline=excluded.deadline,
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

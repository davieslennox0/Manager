"""Agent Jobs board — public + agent-callable. Gigs a firm wants an autonomous
agent to do, aggregated across the agent economy. No auth, free to read (the
paid services are the CV/benchmark ones); an external agent can poll this to find
work, then call /v1/tailor or /v1/benchmark to compete for it."""
from fastapi import APIRouter, HTTPException, Query

from db import get_conn, j

router = APIRouter(prefix="/v1", tags=["agent-jobs"])


def _shape(r) -> dict:
    d = {**dict(r), "tags": j(r["tags"], [])}
    # agent-eligible = the source flags it for agents, or the source is agent-native
    d["agent_eligible"] = (d["source"] == "okx"
                           or (d["agent_access"] or "").upper() not in ("", "HUMAN_ONLY"))
    return d


@router.get("/agent-jobs")
async def agent_jobs(q: str = "", source: str = "", chain: str = "",
                     agent_only: str = "", limit: int = Query(100, le=500), offset: int = 0):
    """Filterable board. `agent_only=1` restricts to gigs the source marks
    agent-eligible (OKX tasks + non-HUMAN_ONLY bounties)."""
    where, args = ["active = 1"], []
    if q:
        where.append("(title LIKE ? OR description LIKE ? OR sponsor LIKE ?)")
        args += [f"%{q}%"] * 3
    if source:
        where.append("source = ?")
        args.append(source)
    if chain:
        where.append("chain LIKE ?")
        args.append(f"%{chain}%")
    if agent_only:
        where.append("(source = 'okx' OR (agent_access != '' AND agent_access != 'HUMAN_ONLY'))")
    clause = " AND ".join(where)
    conn = get_conn()
    rows = conn.execute(
        f"SELECT * FROM agent_jobs WHERE {clause} "
        f"ORDER BY first_seen DESC LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
    total = conn.execute(f"SELECT COUNT(*) c FROM agent_jobs WHERE {clause}",
                         args).fetchone()["c"]
    src_facets = conn.execute(
        "SELECT source, COUNT(*) c FROM agent_jobs WHERE active=1 "
        "GROUP BY source ORDER BY c DESC").fetchall()
    chain_facets = conn.execute(
        "SELECT chain, COUNT(*) c FROM agent_jobs WHERE active=1 AND chain != '' "
        "GROUP BY chain ORDER BY c DESC").fetchall()
    conn.close()
    return {
        "total": total,
        "facets": {
            "sources": [{"name": f["source"], "count": f["c"]} for f in src_facets],
            "chains": [{"name": f["chain"], "count": f["c"]} for f in chain_facets],
        },
        "note": "Gigs a firm wants an AI agent to do. Discovery is free; win one, "
                "then use /v1/tailor or /v1/benchmark. Sources come online as the "
                "agent-economy platforms expose live feeds.",
        "agent_jobs": [_shape(r) for r in rows],
    }


@router.get("/agent-jobs/{job_id}")
async def get_agent_job(job_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM agent_jobs WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "No such agent job")
    return _shape(row)

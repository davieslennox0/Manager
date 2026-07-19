"""Public distribution surfaces: the filterable job board + email subscriptions.
No auth — this is the site's front door; picking a listing routes into the
authenticated per-job CV flow."""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr

from auth import current_user
from db import get_conn, j

router = APIRouter(prefix="/v1", tags=["listings"])


class SubscribeBody(BaseModel):
    email: EmailStr
    ecosystem: str = ""
    role_keywords: list[str] = []
    keywords: list[str] = []
    newly_funded: bool = False


@router.get("/listings")
async def listings(q: str = "", ecosystem: str = "", firm: str = "", remote: str = "",
                   category: str = "", newly_funded: str = "",
                   limit: int = Query(100, le=500), offset: int = 0):
    where, args = ["active = 1"], []
    if q:
        where.append("(role LIKE ? OR firm LIKE ? OR skills LIKE ?)")
        args += [f"%{q}%"] * 3
    if ecosystem:
        where.append("ecosystem LIKE ?")
        args.append(f"%{ecosystem}%")
    if firm:
        where.append("firm LIKE ?")
        args.append(f"%{firm}%")
    if remote:
        where.append("remote = ?")
        args.append(remote)
    if category:
        where.append("category = ?")
        args.append(category)
    if newly_funded:
        where.append("newly_funded = 1")
    conn = get_conn()
    rows = conn.execute(
        f"SELECT * FROM listings WHERE {' AND '.join(where)} "
        f"ORDER BY first_seen DESC LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
    total = conn.execute(f"SELECT COUNT(*) c FROM listings WHERE {' AND '.join(where)}",
                         args).fetchone()["c"]
    eco_facets = conn.execute(
        "SELECT ecosystem, COUNT(*) c FROM listings WHERE active=1 AND ecosystem != '' "
        "GROUP BY ecosystem ORDER BY c DESC LIMIT 20").fetchall()
    cat_facets = conn.execute(
        "SELECT category, COUNT(*) c FROM listings WHERE active=1 AND category != '' "
        "GROUP BY category ORDER BY c DESC").fetchall()
    funded_count = conn.execute(
        "SELECT COUNT(*) c FROM listings WHERE active=1 AND newly_funded=1").fetchone()["c"]
    conn.close()
    return {"total": total,
            "facets": {
                "ecosystems": [{"name": f["ecosystem"], "count": f["c"]} for f in eco_facets],
                "categories": [{"name": f["category"], "count": f["c"]} for f in cat_facets],
                "newly_funded": funded_count,
            },
            "listings": [{**dict(r), "skills": j(r["skills"], [])} for r in rows]}


@router.get("/funded")
async def funded_firms():
    """The newly-funded tiers: firms with live listings ("hiring") and the
    speculative tier — recently funded, likely hiring soon, no posting yet."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT name, round, amount, announced_at, source_url, careers_kind,
           careers_target, status, first_seen FROM funded_firms
           WHERE active=1 ORDER BY first_seen DESC LIMIT 100""").fetchall()
    conn.close()
    firms = [dict(r) for r in rows]
    return {"hiring": [f for f in firms if f["status"] == "hiring"],
            "speculative": [f for f in firms if f["status"] == "speculative"],
            "note": "speculative = raise announced but no public posting yet — "
                    "reach out before the role hits the boards"}


@router.get("/listings/{listing_id}")
async def get_listing(listing_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM listings WHERE listing_id = ?", (listing_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "No such listing")
    return {**dict(row), "skills": j(row["skills"], [])}


@router.post("/subscriptions")
async def subscribe(body: SubscribeBody):
    filters = {k: v for k, v in [("ecosystem", body.ecosystem),
                                 ("role_keywords", body.role_keywords),
                                 ("keywords", body.keywords),
                                 ("newly_funded", body.newly_funded)] if v}
    conn = get_conn()
    try:
        sub_id = "sub_" + uuid.uuid4().hex[:12]
        conn.execute("INSERT INTO subscriptions (sub_id, email, filters) VALUES (?, ?, ?)",
                     (sub_id, body.email, json.dumps(filters, sort_keys=True)))
        conn.commit()
    except Exception:
        conn.close()
        raise HTTPException(409, "That email already subscribes with these exact filters")
    conn.close()
    return {"sub_id": sub_id, "email": body.email, "filters": filters,
            "note": "Digest emails send as new matching listings appear"}


@router.get("/unsubscribe/{sub_id}")
async def unsubscribe(sub_id: str):
    conn = get_conn()
    cur = conn.execute("UPDATE subscriptions SET active = 0 WHERE sub_id = ?", (sub_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Unknown subscription")
    return {"unsubscribed": True}


@router.get("/sources")
async def sources(user: dict = Depends(current_user)):
    """Scanner source health — any logged-in user can inspect; edits are SQL for now."""
    conn = get_conn()
    rows = conn.execute("SELECT source_id, kind, name, target, poll_seconds, last_polled, "
                        "last_error, active FROM sources").fetchall()
    conn.close()
    return {"sources": [dict(r) for r in rows]}

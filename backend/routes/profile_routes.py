import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import current_user
from db import get_conn, j
from pipeline import load_spine

router = APIRouter(prefix="/v1/profile", tags=["profile"])


class ProfileBody(BaseModel):
    full_name: str = ""
    headline: str = ""
    location: str = ""
    links: list[dict] = []
    summary: str = ""
    skills: list[str] = []
    experience: list[dict] = []
    education: list[dict] = []


class AlertsBody(BaseModel):
    enabled: bool


@router.get("")
async def get_profile(user: dict = Depends(current_user)):
    """The full data spine: base profile + verified onchain work history,
    plus the public track-record settings (handle + toggle)."""
    spine = load_spine(user["user_id"])
    conn = get_conn()
    row = conn.execute("SELECT handle, public_profile, job_alerts FROM profiles "
                       "WHERE user_id=?", (user["user_id"],)).fetchone()
    conn.close()
    if row:
        spine["handle"] = row["handle"]
        spine["public_profile"] = bool(row["public_profile"])
        spine["job_alerts"] = bool(row["job_alerts"])
    return spine


@router.put("/alerts")
async def set_job_alerts(body: AlertsBody, user: dict = Depends(current_user)):
    """Toggle the new-listing match emails (on by default)."""
    conn = get_conn()
    conn.execute("UPDATE profiles SET job_alerts=? WHERE user_id=?",
                 (1 if body.enabled else 0, user["user_id"]))
    conn.commit()
    conn.close()
    return {"job_alerts": body.enabled}


@router.put("")
async def put_profile(body: ProfileBody, user: dict = Depends(current_user)):
    conn = get_conn()
    conn.execute(
        """UPDATE profiles SET full_name=?, headline=?, location=?, links=?, summary=?,
           skills=?, experience=?, education=?, updated_at=CURRENT_TIMESTAMP
           WHERE user_id=?""",
        (body.full_name, body.headline, body.location, json.dumps(body.links),
         body.summary, json.dumps(body.skills), json.dumps(body.experience),
         json.dumps(body.education), user["user_id"]))
    conn.commit()
    conn.close()
    return load_spine(user["user_id"])


@router.get("/history")
async def work_history(user: dict = Depends(current_user)):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM work_history WHERE user_id = ? ORDER BY signed_at DESC",
                        (user["user_id"],)).fetchall()
    conn.close()
    return {"history": [{**dict(r), "scope": j(r["scope"], [])} for r in rows]}

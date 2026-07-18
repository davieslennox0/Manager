"""Per-job flow: submit posting (URL/text/listing) -> parsed signals -> tailored
CV -> review/edit -> PDF export -> mark accepted (gate to the agreement stage)."""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import pipeline
from auth import current_user
from db import get_conn, j
from llm import LLMError
from pdfgen import render_cv_pdf

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


class JobSubmit(BaseModel):
    url: str = ""
    raw_text: str = ""
    listing_id: str = ""


class CVEdit(BaseModel):
    content: dict


def _job(conn, job_id: str, user_id: str):
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ? AND user_id = ?",
                       (job_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "No such job")
    return row


@router.post("")
async def submit_job(body: JobSubmit, user: dict = Depends(current_user)):
    text, url, source, listing_id = body.raw_text.strip(), body.url.strip(), "pasted", None
    if body.listing_id:
        conn = get_conn()
        listing = conn.execute("SELECT * FROM listings WHERE listing_id = ?",
                               (body.listing_id,)).fetchone()
        conn.close()
        if not listing:
            raise HTTPException(404, "No such listing")
        source, listing_id, url = "listing", body.listing_id, listing["url"]
    if not text and url:
        try:
            text = await pipeline.fetch_posting_text(url)
        except Exception as e:
            raise HTTPException(422, f"Could not fetch the posting URL ({e}) — "
                                     "paste the posting text instead")
    if not text:
        raise HTTPException(422, "Provide url, raw_text, or listing_id")
    try:
        parsed = await pipeline.parse_posting(text)
    except LLMError as e:
        raise HTTPException(503, f"Posting analysis unavailable: {e}")
    job_id = "job_" + uuid.uuid4().hex[:12]
    conn = get_conn()
    conn.execute(
        "INSERT INTO jobs (job_id, user_id, source, listing_id, url, raw_text, parsed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (job_id, user["user_id"], source, listing_id, url, text[:60000],
         json.dumps(parsed, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return {"job_id": job_id, "parsed": parsed, "status": "parsed"}


@router.get("")
async def list_jobs(user: dict = Depends(current_user)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT job_id, source, url, parsed, status, created_at FROM jobs "
        "WHERE user_id = ? ORDER BY created_at DESC", (user["user_id"],)).fetchall()
    conn.close()
    return {"jobs": [{**dict(r), "parsed": j(r["parsed"], {})} for r in rows]}


@router.get("/{job_id}")
async def get_job(job_id: str, user: dict = Depends(current_user)):
    conn = get_conn()
    row = _job(conn, job_id, user["user_id"])
    cv = conn.execute("SELECT cv_id, content, updated_at FROM cvs WHERE job_id = ?",
                      (job_id,)).fetchone()
    conn.close()
    out = {**dict(row), "parsed": j(row["parsed"], {})}
    out["cv"] = ({"cv_id": cv["cv_id"], "content": j(cv["content"], {}),
                  "updated_at": cv["updated_at"]} if cv else None)
    return out


@router.post("/{job_id}/cv")
async def generate_cv(job_id: str, user: dict = Depends(current_user)):
    """(Re)generate the tailored CV for this job from the profile spine.
    Overwrites any previous generation — one job, one living CV."""
    conn = get_conn()
    row = _job(conn, job_id, user["user_id"])
    conn.close()
    spine = pipeline.load_spine(user["user_id"])
    if not (spine.get("skills") or spine.get("experience")):
        raise HTTPException(422, "Fill in your profile first — the CV is generated "
                                 "from it, not from thin air")
    try:
        cv = await pipeline.tailor_cv(j(row["parsed"], {}), spine)
    except LLMError as e:
        raise HTTPException(503, f"CV generation unavailable: {e}")
    conn = get_conn()
    conn.execute(
        "INSERT INTO cvs (cv_id, job_id, user_id, content) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(job_id) DO UPDATE SET content=excluded.content, "
        "updated_at=CURRENT_TIMESTAMP",
        ("cv_" + uuid.uuid4().hex[:12], job_id, user["user_id"],
         json.dumps(cv, ensure_ascii=False)))
    conn.execute("UPDATE jobs SET status='cv_ready' WHERE job_id=? AND status='parsed'",
                 (job_id,))
    conn.commit()
    conn.close()
    return {"job_id": job_id, "cv": cv}


@router.put("/{job_id}/cv")
async def edit_cv(job_id: str, body: CVEdit, user: dict = Depends(current_user)):
    conn = get_conn()
    _job(conn, job_id, user["user_id"])
    cur = conn.execute(
        "UPDATE cvs SET content=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
        (json.dumps(body.content, ensure_ascii=False), job_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Generate the CV first")
    return {"job_id": job_id, "cv": body.content}


@router.get("/{job_id}/cv.pdf")
async def export_cv_pdf(job_id: str, user: dict = Depends(current_user)):
    conn = get_conn()
    _job(conn, job_id, user["user_id"])
    cv = conn.execute("SELECT content FROM cvs WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    if not cv:
        raise HTTPException(404, "Generate the CV first")
    pdf = render_cv_pdf(j(cv["content"], {}), pipeline.load_spine(user["user_id"]))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="cv-{job_id}.pdf"'})


@router.post("/{job_id}/accept")
async def mark_accepted(job_id: str, user: dict = Depends(current_user)):
    """The offer/gig came through — unlock the work-agreement stage."""
    conn = get_conn()
    row = _job(conn, job_id, user["user_id"])
    if row["status"] == "contracted":
        conn.close()
        raise HTTPException(409, "Already contracted")
    conn.execute("UPDATE jobs SET status='accepted' WHERE job_id=?", (job_id,))
    conn.commit()
    conn.close()
    return {"job_id": job_id, "status": "accepted"}

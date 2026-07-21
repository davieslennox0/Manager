"""Public, stateless agentic services — ManagerX's human-serving Resume & Career
Workflows, callable by another agent (on behalf of a human job-seeker). Each is
x402-gated; the handler is pure (profile + posting in → artifact out), so no
account or prior state is needed. Same engine as the authenticated web flow.

- POST /v1/tailor        — tailored CV for one posting
- POST /v1/cover-letter  — application email for one posting
(POST /v1/benchmark lives in benchmark_routes.py — the first of these services.)"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import pipeline
from llm import LLMError

router = APIRouter(prefix="/v1", tags=["agentic"])


class Profile(BaseModel):
    full_name: str = ""
    headline: str = ""
    location: str = ""
    links: list[dict] = []
    summary: str = ""
    skills: list[str] = []
    experience: list[dict] = []
    education: list[dict] = []
    verified_work_history: list[dict] = []


class TailorBody(BaseModel):
    profile: Profile
    posting_text: str = ""
    posting: dict | None = None   # pre-parsed posting to skip the parse call


class CoverBody(BaseModel):
    profile: Profile
    posting_text: str = ""
    posting: dict | None = None
    cv: dict | None = None        # a tailored CV to cite; generated if absent


async def _resolve_posting(body) -> dict:
    if body.posting:
        return body.posting
    if body.posting_text.strip():
        try:
            return await pipeline.parse_posting(body.posting_text.strip())
        except LLMError as e:
            raise HTTPException(503, f"Posting analysis unavailable: {e}")
    raise HTTPException(422, "Provide posting_text or a pre-parsed posting")


def _check_profile(spine: dict):
    if not (spine.get("skills") or spine.get("experience")):
        raise HTTPException(422, "profile needs at least skills or experience — "
                                 "the CV is generated from it, never invented")


@router.post("/tailor")
async def tailor(body: TailorBody):
    """Tailor the supplied profile to one posting: mirror its vocabulary, reorder
    to the required skills, drop irrelevant experience. Returns the CV JSON."""
    spine = body.profile.model_dump()
    _check_profile(spine)
    parsed = await _resolve_posting(body)
    try:
        cv = await pipeline.tailor_cv(parsed, spine)
    except LLMError as e:
        raise HTTPException(503, f"CV generation unavailable: {e}")
    return {"parsed": parsed, "cv": cv}


@router.post("/cover-letter")
async def cover_letter(body: CoverBody):
    """Draft the application email for one posting from the profile + tailored CV
    (generated on the fly if not supplied). Returns {subject, body}."""
    spine = body.profile.model_dump()
    _check_profile(spine)
    parsed = await _resolve_posting(body)
    cv = body.cv
    try:
        if not cv:
            cv = await pipeline.tailor_cv(parsed, spine)
        letter = await pipeline.draft_cover_letter(parsed, spine, cv)
    except LLMError as e:
        raise HTTPException(503, f"Cover letter drafting unavailable: {e}")
    return {"subject": letter.get("subject", ""), "body": letter.get("body", ""),
            "cv": cv}

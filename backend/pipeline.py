"""The generation pipeline: job posting -> parsed signals -> tailored CV ->
(on acceptance) work-agreement draft. Every step is a structured-JSON LLM call
grounded in the profile spine — the CV and the contract quote the same data."""
import hashlib
import json

import httpx

from db import get_conn, j
from llm import generate_json

PARSE_PROMPT = """You analyze a job posting for an application-tailoring system.
Extract the posting's signals. Reply with ONLY a JSON object:
{{
  "role": "job title as posted",
  "firm": "hiring company/protocol/DAO name, '' if not stated",
  "ecosystem": "blockchain ecosystem if any (e.g. Ethereum, Solana, X Layer), else ''",
  "required_skills": ["skill", ...],
  "nice_to_have": ["skill", ...],
  "seniority": "junior|mid|senior|lead|unclear",
  "tone": "2-4 words describing the posting's voice (e.g. 'formal corporate', 'casual crypto-native')",
  "language": "posting language, e.g. 'en'",
  "comp_range": "compensation if disclosed, else ''",
  "duration": "contract/permanent/gig duration if stated, else ''",
  "apply_email": "email address the posting says to apply to / send CVs to, else ''",
  "summary": "2-sentence summary of what the role actually does"
}}

Job posting:
{posting}"""

CV_PROMPT = """You tailor a CV to ONE specific job posting. Rules:
- Mirror the posting's own vocabulary and tone ({tone}, language: {language}).
- Reorder and emphasize the candidate's skills/experience that match the posting's
  required skills; drop experience irrelevant to this role entirely.
- Never invent skills, employers, dates, or achievements not present in the profile.
- Verified onchain work history entries are the candidate's strongest evidence —
  when relevant, surface them prominently and mark them "(onchain-verified)".
- Keep it one page dense: terse bullets, concrete outcomes.

Reply with ONLY a JSON object:
{{
  "headline": "one line positioning the candidate for THIS role",
  "summary": "2-3 sentence pitch tuned to the posting",
  "skills": ["ordered, most relevant first — only skills from the profile"],
  "experience": [{{"title": "", "org": "", "start": "", "end": "", "bullets": ["tailored bullet", ...], "verified": false}}],
  "education": [{{"degree": "", "school": "", "year": ""}}]
}}

Job posting signals:
{parsed}

Candidate profile (the only source of truth about the candidate):
{profile}"""

AGREEMENT_PROMPT = """You draft a work agreement for an accepted role/gig. The scope
of work MUST be derived from the candidate's claimed skills and the role's duties —
each claimed capability that the role needs becomes a concrete scope-of-work clause.
Use plain contractual English, no legalese padding. Never invent terms not implied
by the posting or profile; where the posting is silent on pay, use the placeholder
"TO BE COMPLETED" so the parties fill it before signing.

Reply with ONLY a JSON object:
{{
  "title": "Work Agreement — <role> @ <firm>",
  "parties": [{{"role": "Contractor", "name": "<candidate name>"}}, {{"role": "Client", "name": "<firm>"}}],
  "scope_of_work": ["clause derived from a matched skill/duty", ...],
  "payment": {{"amount": "as stated or TO BE COMPLETED", "schedule": "e.g. monthly / on milestones", "currency": ""}},
  "duration": {{"start": "TO BE COMPLETED unless stated", "end_or_term": "as stated or TO BE COMPLETED"}},
  "termination": "one short clause",
  "ip_and_confidentiality": "one short clause"
}}

Role (parsed posting):
{parsed}

Candidate profile + verified history:
{profile}"""

COVER_PROMPT = """You write a short application email for ONE job posting, sent with
the candidate's tailored CV attached. Rules:
- 120-180 words, plain text, no placeholders — every sentence must stand as-is.
- Mirror the posting's tone ({tone}) and language ({language}).
- Lead with the strongest concrete match between the candidate and the role;
  never invent skills or experience not in the profile/CV.
- Close with one plain sentence: the CV is attached, happy to talk.
- No salutation gymnastics: "Hello," or the hiring team by firm name.

Reply with ONLY a JSON object:
{{
  "subject": "Application: <role> — <candidate name>",
  "body": "the email text, \\n\\n between paragraphs, ending with the candidate's name"
}}

Job posting signals:
{parsed}

Tailored CV being attached:
{cv}

Candidate profile:
{profile}"""


async def fetch_posting_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "ManagerX/1.0 job-application agent"}) as client:
        resp = await client.get(url)
    resp.raise_for_status()
    text = resp.text
    if "<html" in text[:2000].lower():
        # crude tag strip is enough — the LLM parse is tolerant of residue
        import re
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    return text[:30000]


def load_spine(user_id: str) -> dict:
    """Profile + verified work history: the single source every artifact cites."""
    conn = get_conn()
    p = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    history = conn.execute(
        "SELECT title, counterparty, scope, start_date, end_date, tx_hash, doc_hash, signed_at "
        "FROM work_history WHERE user_id = ? ORDER BY signed_at DESC", (user_id,)).fetchall()
    conn.close()
    if not p:
        return {}
    return {
        "full_name": p["full_name"], "headline": p["headline"], "location": p["location"],
        "links": j(p["links"], []), "summary": p["summary"], "skills": j(p["skills"], []),
        "experience": j(p["experience"], []), "education": j(p["education"], []),
        "verified_work_history": [
            {"title": h["title"], "counterparty": h["counterparty"],
             "scope": j(h["scope"], []), "start": h["start_date"], "end": h["end_date"],
             "onchain_tx": h["tx_hash"], "doc_hash": h["doc_hash"],
             "signed_at": str(h["signed_at"])} for h in history],
    }


async def parse_posting(posting_text: str) -> dict:
    return await generate_json(PARSE_PROMPT.format(posting=posting_text[:30000]))


async def tailor_cv(parsed: dict, spine: dict) -> dict:
    return await generate_json(CV_PROMPT.format(
        tone=parsed.get("tone", "neutral"), language=parsed.get("language", "en"),
        parsed=json.dumps(parsed, ensure_ascii=False),
        profile=json.dumps(spine, ensure_ascii=False)))


async def draft_agreement(parsed: dict, spine: dict) -> dict:
    return await generate_json(AGREEMENT_PROMPT.format(
        parsed=json.dumps(parsed, ensure_ascii=False),
        profile=json.dumps(spine, ensure_ascii=False)))


async def draft_cover_letter(parsed: dict, spine: dict, cv: dict) -> dict:
    return await generate_json(COVER_PROMPT.format(
        tone=parsed.get("tone", "neutral"), language=parsed.get("language", "en"),
        parsed=json.dumps(parsed, ensure_ascii=False),
        cv=json.dumps(cv, ensure_ascii=False),
        profile=json.dumps(spine, ensure_ascii=False)))


def agreement_doc_hash(content: dict) -> str:
    """Canonical keccak-free doc hash: sha256 over sorted-key JSON. The same
    bytes are rebuilt by the frontend for wallet display and by any verifier."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "0x" + hashlib.sha256(canonical.encode()).hexdigest()

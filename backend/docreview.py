"""Offer & contract review: the receiving side of the paperwork. The user
uploads a document an employer sent (offer letter, employment contract, NDA);
one structured-LLM pass classifies it, extracts the terms and every date that
matters, flags risky clauses, and — when the document answers a job the
platform applied to — diffs it against the parsed posting we already hold.
That diff is the piece a generic reviewer can't do: we know what was promised."""
import hashlib
import io
import json

from llm import generate_json

REVIEW_PROMPT = """You review an employment-related document a JOB SEEKER received
(offer letter, employment contract, freelance/gig agreement, or NDA). You work for
the seeker, not the employer: extract the terms exactly as written, then assess them
from the seeker's side. Never invent terms that are not in the document; use "" or
[] when something is absent.

Reply with ONLY a JSON object:
{{
  "kind": "offer|contract|nda|other",
  "summary": "2-3 plain-language sentences: what this document binds the seeker to",
  "terms": {{
    "position": "", "employer": "",
    "employment_type": "full-time|part-time|contract|freelance|'' ",
    "compensation": {{"base": "", "currency": "", "period": "e.g. annual/monthly/hourly", "bonus": "", "equity_or_tokens": ""}},
    "benefits": ["as listed"],
    "location_or_remote": "",
    "start_date": "as written",
    "probation": {{"length": "", "terms": ""}},
    "notice_period": "",
    "termination": "grounds + notice, condensed",
    "non_compete": {{"present": false, "scope": "", "duration": ""}},
    "non_solicit": "",
    "ip_assignment": "what the seeker signs away, condensed",
    "confidentiality": "",
    "governing_law": "",
    "other_notable": ["anything unusual worth the seeker's attention"]
  }},
  "red_flags": [{{"clause": "quoted or closely paraphrased", "severity": "high|medium|low",
                  "why": "what it costs the seeker", "negotiation_pointer": "one concrete ask"}}],
  "deadlines": [{{"label": "e.g. Offer expires / Start date / Probation ends / Contract ends / Non-compete lapses",
                  "date": "YYYY-MM-DD if stated or derivable, else ''",
                  "note": "how the date was derived, or the vague wording as written"}}],
  "posting_diff": [{{"aspect": "e.g. compensation / remote policy / role title",
                     "posting_said": "", "document_says": "",
                     "assessment": "match|discrepancy|new_info"}}]
}}

If no job posting is provided below, return "posting_diff": [].

Document:
{document}

Job posting signals this document answers (empty if none):
{posting}"""


def document_hash(data: bytes) -> str:
    """0x sha256 over the exact uploaded bytes — what gets anchored onchain and
    what any verifier recomputes from the original file."""
    return "0x" + hashlib.sha256(data).hexdigest()


def extract_text(data: bytes, filename: str) -> str:
    """Plain text from an upload: PDFs via pypdf, everything else decoded as text."""
    if filename.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    return data.decode("utf-8", errors="replace")


async def review_document(text: str, parsed_posting: dict | None) -> dict:
    review = await generate_json(REVIEW_PROMPT.format(
        document=text[:40000],
        posting=json.dumps(parsed_posting, ensure_ascii=False) if parsed_posting else ""))
    review.setdefault("red_flags", [])
    review.setdefault("deadlines", [])
    review.setdefault("posting_diff", [])
    return review

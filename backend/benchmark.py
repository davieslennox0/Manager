"""ATS-readiness + role-fit benchmark — ManagerX's second agentic service.

The score is deterministic where it can be (skill/keyword coverage, structural
ATS checks over the extracted resume text) so a caller gets a reproducible,
defensible number — not an LLM's mood. A single LLM pass, grounded in those
deterministic findings, adds the judgment layer: semantic matches the substring
matcher missed, seniority alignment, and prioritized positioning fixes.

Powers both the authenticated per-job panel and the public /v1/benchmark
endpoint that becomes the x402-payable ASP service (Resume & Career Workflows,
the 'benchmark' verb X Layer's marketplace asked for)."""
import json
import re

from llm import generate_json

# overall = weighted blend of the three deterministic sub-scores
W_ROLE_FIT, W_KEYWORDS, W_ATS = 0.50, 0.20, 0.30

_SECTION_HINTS = {
    "experience": ["experience", "employment", "work history", "professional"],
    "education": ["education", "academic"],
    "skills": ["skills", "technologies", "tech stack", "competencies"],
}
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PHONE_RE = re.compile(r"(?:\+?\d[\s\-().]?){7,}")
_LINK_RE = re.compile(r"(https?://|github\.com|linkedin\.com|/0x[a-fA-F0-9]{6,})")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_BULLET_RE = re.compile(r"(^|\n)\s*[-•*·▪◦]\s+")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _skill_present(skill: str, blob: str, words: set[str]) -> bool:
    """Substring match, but skills shorter than 3 chars ('Go', 'R', 'C') need a
    word boundary or every résumé 'matches' them."""
    s = skill.strip().lower()
    if not s:
        return False
    return s in blob if len(s) >= 3 else s in words


def keyword_coverage(resume_text: str, parsed: dict) -> dict:
    """Deterministic skill coverage of the posting by the résumé text."""
    blob = _norm(resume_text).lower()
    words = set(re.split(r"[^a-z0-9+#.]+", blob))
    required = [s for s in parsed.get("required_skills", []) if isinstance(s, str) and s.strip()]
    nice = [s for s in parsed.get("nice_to_have", []) if isinstance(s, str) and s.strip()]

    req_hit = [s for s in required if _skill_present(s, blob, words)]
    req_miss = [s for s in required if s not in req_hit]
    nice_hit = [s for s in nice if _skill_present(s, blob, words)]

    combined = required + nice
    combined_hit = req_hit + nice_hit
    kw_score = round(100 * len(combined_hit) / len(combined)) if combined else 100
    role_fit = round(100 * len(req_hit) / len(required)) if required else 100
    return {
        "role_fit_score": role_fit,
        "keyword_score": kw_score,
        "required_covered": req_hit,
        "required_missing": req_miss,
        "nice_to_have_covered": nice_hit,
    }


def ats_structural_checks(resume_text: str) -> dict:
    """What an ATS parser can and can't recover from the extracted text. These
    run on the text an ATS would see, so they catch the failures that matter:
    missing contact info in the body, absent standard sections, no dates, and
    layout noise (the tab/pipe residue that multi-column PDFs leak)."""
    text = resume_text or ""
    low = text.lower()
    words = low.split()
    n_words = len(words)

    checks = []

    def add(name, ok, note):
        checks.append({"name": name, "ok": bool(ok), "note": note})

    add("contact_email", bool(_EMAIL_RE.search(text)),
        "An email address is in the body text" if _EMAIL_RE.search(text)
        else "No email found — ATS often can't read contact info from headers/footers")
    add("contact_link", bool(_LINK_RE.search(text)),
        "A profile/portfolio link is present" if _LINK_RE.search(text)
        else "No GitHub/LinkedIn/portfolio link — add one in the body")

    present_sections = [k for k, hints in _SECTION_HINTS.items()
                        if any(h in low for h in hints)]
    add("standard_sections", len(present_sections) >= 2,
        f"Recognizable sections: {', '.join(present_sections) or 'none'}. "
        "ATS keys off standard headers (Experience / Education / Skills)")

    add("dates_present", bool(_YEAR_RE.search(text)),
        "Dated history present" if _YEAR_RE.search(text)
        else "No year-formatted dates — ATS timelines depend on them")
    add("bullets", bool(_BULLET_RE.search(text)),
        "Uses bullet points" if _BULLET_RE.search(text)
        else "No bullets detected — dense paragraphs parse worse and read worse")

    good_len = 250 <= n_words <= 1100
    add("length", good_len,
        f"{n_words} words — within a 1–2 page range" if good_len
        else (f"{n_words} words is thin — under a page of substance" if n_words < 250
              else f"{n_words} words likely overflows two pages"))

    # layout-noise heuristic: multi-column / table exports leak runs of pipes,
    # tabs, or 3+ spaces used as column gutters
    noise = len(re.findall(r"\t|\|| {3,}", text))
    clean_layout = noise <= max(3, n_words // 120)
    add("clean_layout", clean_layout,
        "No column/table layout artifacts detected" if clean_layout
        else "Tab/pipe/gutter residue suggests a multi-column or table layout — "
             "ATS parsers scramble those; use a single-column layout")

    passed = sum(1 for c in checks if c["ok"])
    score = round(100 * passed / len(checks))
    issues = [c["note"] for c in checks if not c["ok"]]
    return {"ats_score": score, "checks": checks, "issues": issues,
            "sections_found": present_sections}


BENCHMARK_PROMPT = """You are the judgment layer of a résumé benchmarking service.
Deterministic checks have already scored keyword coverage and ATS structure — do
NOT re-score those. Your job is the semantic read a substring matcher can't do.

Rules:
- semantic_matches: of the listed MISSING required skills, which does the résumé
  clearly demonstrate under different wording? Only include ones truly evidenced;
  never invent. Return the skill string exactly as given in the missing list.
- seniority_alignment: does the résumé's depth read as under / matched / over the
  posting's seniority ({seniority})?
- ats_notes: additional ATS/formatting risks you can see in the text (only real ones).
- positioning: 2-5 concrete, prioritized edits that would most raise this
  candidate's fit for THIS posting — most impactful first, specific not generic.
- verdict_reason: one sentence, plain.

Reply with ONLY a JSON object:
{{
  "semantic_matches": ["<from the missing list only>"],
  "seniority_alignment": "under|matched|over",
  "ats_notes": ["..."],
  "positioning": ["..."],
  "verdict_reason": "one sentence"
}}

Posting role: {role}
Posting seniority: {seniority}
Required skills: {required}
Missing required skills (deterministic): {missing}

Résumé text:
{resume}"""


async def _judge(resume_text: str, parsed: dict, cov: dict) -> dict:
    try:
        return await generate_json(BENCHMARK_PROMPT.format(
            role=parsed.get("role", "the role"),
            seniority=parsed.get("seniority", "unclear"),
            required=json.dumps(parsed.get("required_skills", []), ensure_ascii=False),
            missing=json.dumps(cov["required_missing"], ensure_ascii=False),
            resume=_norm(resume_text)[:12000]))
    except Exception:
        return {}  # benchmark still returns a deterministic score without the judge


def _verdict(score: int) -> str:
    if score >= 75:
        return "strong fit"
    if score >= 50:
        return "worth tailoring"
    return "weak fit"


async def benchmark_resume(resume_text: str, parsed: dict) -> dict:
    """Full benchmark: deterministic coverage + ATS structure, refined by one
    grounded LLM pass, folded into a single reproducible overall score."""
    cov = keyword_coverage(resume_text, parsed)
    ats = ats_structural_checks(resume_text)
    judge = await _judge(resume_text, parsed, cov)

    # fold in semantic matches the substring matcher missed — but only ones that
    # were genuinely in the missing list (the prompt is constrained, we re-verify)
    required = [s for s in parsed.get("required_skills", []) if isinstance(s, str)]
    miss_set = {s.lower() for s in cov["required_missing"]}
    semantic = [s for s in judge.get("semantic_matches", [])
                if isinstance(s, str) and s.lower() in miss_set]
    covered = cov["required_covered"] + semantic
    missing = [s for s in cov["required_missing"] if s not in semantic]
    role_fit = round(100 * len(covered) / len(required)) if required else 100

    overall = round(W_ROLE_FIT * role_fit + W_KEYWORDS * cov["keyword_score"]
                    + W_ATS * ats["ats_score"])
    return {
        "overall_score": overall,
        "verdict": _verdict(overall),
        "verdict_reason": judge.get("verdict_reason", ""),
        "role_fit": {
            "score": role_fit,
            "required_covered": covered,
            "required_missing": missing,
            "nice_to_have_covered": cov["nice_to_have_covered"],
            "semantic_matches": semantic,
        },
        "keyword_coverage": {"score": cov["keyword_score"]},
        "ats": {
            "score": ats["ats_score"],
            "checks": ats["checks"],
            "issues": ats["issues"] + [n for n in judge.get("ats_notes", [])
                                       if isinstance(n, str)],
        },
        "seniority_alignment": judge.get("seniority_alignment", "unclear"),
        "positioning": [p for p in judge.get("positioning", []) if isinstance(p, str)],
        "role": parsed.get("role", ""),
    }


def spine_to_text(spine: dict) -> str:
    """Flatten a profile/CV spine into the plain text an ATS would extract, so the
    same benchmark engine scores both a pasted résumé and a generated CV."""
    lines = []
    if spine.get("full_name"):
        lines.append(spine["full_name"])
    if spine.get("headline"):
        lines.append(spine["headline"])
    contact = [spine.get("location", "")]
    contact += [l.get("url", "") if isinstance(l, dict) else str(l)
                for l in spine.get("links", [])]
    contact = [c for c in contact if c]
    if contact:
        lines.append(" | ".join(contact))
    if spine.get("summary"):
        lines.append("\nSummary\n" + spine["summary"])
    skills = spine.get("skills", [])
    if skills:
        lines.append("\nSkills\n" + ", ".join(str(s) for s in skills))
    exp = spine.get("experience", [])
    if exp:
        lines.append("\nExperience")
        for e in exp:
            head = " — ".join(x for x in [e.get("title", ""), e.get("org", "")] if x)
            span = " ".join(x for x in [e.get("start", ""), e.get("end", "")] if x)
            lines.append(f"{head} {span}".strip())
            for b in e.get("bullets", []):
                lines.append(f"- {b}")
    hist = spine.get("verified_work_history", [])
    if hist:
        lines.append("\nVerified Work History (onchain)")
        for h in hist:
            span = " ".join(x for x in [h.get("start", ""), h.get("end", "")] if x)
            lines.append(f"- {h.get('title','')} @ {h.get('counterparty','')} {span}".strip())
    edu = spine.get("education", [])
    if edu:
        lines.append("\nEducation")
        for e in edu:
            lines.append(" — ".join(x for x in [e.get("degree", ""), e.get("school", ""),
                                                str(e.get("year", ""))] if x))
    return "\n".join(lines)

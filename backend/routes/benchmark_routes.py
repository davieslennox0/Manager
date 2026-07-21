"""Public, agentic ATS-readiness + role-fit benchmark — ManagerX's second
service and its first x402-payable surface. Stateless and unauthenticated so an
external agent can call it: résumé text + posting text -> reproducible score.
The x402 middleware gates this path; the handler itself just scores."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import benchmark
import pipeline
from llm import LLMError

router = APIRouter(prefix="/v1/benchmark", tags=["benchmark"])


class BenchmarkBody(BaseModel):
    resume_text: str = ""
    posting_text: str = ""
    # escape hatches so a caller that already parsed the posting can skip the LLM
    posting: dict | None = None
    role: str = ""
    required_skills: list[str] = []
    nice_to_have: list[str] = []


@router.post("")
async def run_benchmark(body: BenchmarkBody):
    resume = body.resume_text.strip()
    if len(resume) < 40:
        raise HTTPException(422, "Provide resume_text (the résumé/CV as plain text)")

    if body.posting:
        parsed = body.posting
    elif body.role or body.required_skills:
        parsed = {"role": body.role, "required_skills": body.required_skills,
                  "nice_to_have": body.nice_to_have, "seniority": "unclear"}
    elif body.posting_text.strip():
        try:
            parsed = await pipeline.parse_posting(body.posting_text.strip())
        except LLMError as e:
            raise HTTPException(503, f"Posting analysis unavailable: {e}")
    else:
        raise HTTPException(422, "Provide posting_text, a parsed posting, or role + "
                                 "required_skills to benchmark against")

    result = await benchmark.benchmark_resume(resume, parsed)
    return result

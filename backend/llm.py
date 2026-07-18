"""LLM access: Gemini first, automatic fallback to Groq on error/timeout/429 —
the same chain the sibling services run. One entry point returns parsed JSON
(every WorkOS generation step is a structured-output task)."""
import json

import httpx

import config


class LLMError(Exception):
    pass


async def _gemini(prompt: str) -> str:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}}
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(url, json=body)
    if resp.status_code >= 400:
        raise LLMError(f"gemini {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise LLMError(f"gemini returned no candidates: {resp.text[:200]}")


async def _groq(prompt: str) -> str:
    body = {"model": config.GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "response_format": {"type": "json_object"}}
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post("https://api.groq.com/openai/v1/chat/completions",
                                 json=body,
                                 headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"})
    if resp.status_code >= 400:
        raise LLMError(f"groq {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


async def generate_json(prompt: str) -> dict:
    """Run the prompt through the fallback chain; the prompt MUST ask for JSON."""
    last: Exception | None = None
    for name, fn, key in (("gemini", _gemini, config.GEMINI_API_KEY),
                          ("groq", _groq, config.GROQ_API_KEY)):
        if not key:
            continue
        try:
            return _parse_json(await fn(prompt))
        except (LLMError, httpx.TimeoutException, httpx.TransportError,
                json.JSONDecodeError) as e:
            last = e
    raise LLMError(f"all LLM providers failed, last error: {last}")

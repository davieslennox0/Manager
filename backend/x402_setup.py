"""Wires the x402 SDK's payment middleware for ManagerX's paid agentic surface.

Self-hosted seller (no external facilitator) via x402_seller.LocalFacilitatorClient —
the same pattern Pitchook/Manny/Bondsman/Engram run in production, enforced by the
SDK's PaymentMiddlewareASGI ahead of FastAPI routing. Only imported when
config.X402_ENABLED (payTo + operator key present), so the app boots without keys and
the whole product still works — payment just isn't required.

The one paid route is /v1/benchmark: the ATS-readiness + role-fit scoring service
ManagerX lists on the OKX.AI marketplace under Resume & Career Workflows."""
import base64
import json
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from x402 import x402ResourceServer
from x402.mechanisms.evm.exact.server import ExactEvmScheme
from x402.http.types import PaymentOption, RouteConfig
from x402.schemas import AssetAmount

from x402_seller import NETWORK, EvmFacilitatorSigner, LocalFacilitatorClient

XLAYER_RPC = os.getenv("XLAYER_RPC_URL", "https://rpc.xlayer.tech")
PAY_TO = os.environ["MANAGERX_X402_PAY_TO"]
ASSET = os.environ["XLAYER_X402_USDT_CONTRACT_ADDRESS"]
BENCHMARK_FEE_ATOMIC = os.getenv("X402_BENCHMARK_FEE_ATOMIC", "20000")  # 0.02 USDT0
SERVICE_FEE_ATOMIC = os.getenv("X402_SERVICE_FEE_ATOMIC", "100000")  # 0.1 USDT0 per service

_signer = EvmFacilitatorSigner(XLAYER_RPC, os.environ["OPERATOR_WALLET_PRIVATE_KEY"])

x402_server = x402ResourceServer(LocalFacilitatorClient(_signer))
x402_server.register(NETWORK, ExactEvmScheme())
x402_server.initialize()

# EIP-3009 transferWithAuthorization: no buyer Permit2 approve needed.
# name/version must match the token's EIP-712 domain (verified on-chain).
_USDT0_EXTRA = {"assetTransferMethod": "eip3009", "name": "USD₮0", "version": "1",
                "decimals": 6}


def _option(amount_atomic: str) -> PaymentOption:
    return PaymentOption(
        scheme="exact",
        pay_to=PAY_TO,
        price=AssetAmount(amount=amount_atomic, asset=ASSET),
        network=NETWORK,
        max_timeout_seconds=120,
        extra=_USDT0_EXTRA,
    )


x402_routes = {
    "/v1/benchmark": RouteConfig(
        accepts=_option(BENCHMARK_FEE_ATOMIC),
        description="ManagerX résumé benchmark: POST {\"resume_text\": \"...\", "
                    "\"posting_text\": \"...\"} (or a parsed posting, or role + "
                    "required_skills) — returns an ATS-readiness + role-fit score "
                    "with skill-coverage gaps and prioritized positioning fixes",
    ),
    "/v1/tailor": RouteConfig(
        accepts=_option(SERVICE_FEE_ATOMIC),
        description="Tailor a CV to one job posting: POST {\"profile\": {...}, "
                    "\"posting_text\": \"...\"} — mirrors the posting's vocabulary, "
                    "reorders to the required skills, drops irrelevant experience; "
                    "returns the tailored CV as structured JSON (never invents "
                    "skills/experience not in the profile)",
    ),
    "/v1/cover-letter": RouteConfig(
        accepts=_option(SERVICE_FEE_ATOMIC),
        description="Draft the application email for one posting: POST {\"profile\": "
                    "{...}, \"posting_text\": \"...\", \"cv\": {...optional}} — 120-180 "
                    "word cover letter mirroring the posting's tone; returns "
                    "{subject, body} plus the tailored CV it cites",
    ),
}

# What a 402 should tell an agent so it can retry correctly. Merged into the SDK's
# payment-required body by Enrich402Middleware below.
_USAGE = {
    "/v1/benchmark": {
        "method": "POST",
        "content_type": "application/json",
        "body": {
            "resume_text": "the résumé/CV as plain text (required)",
            "posting_text": "the job posting as plain text — parsed for you; OR",
            "posting": "a pre-parsed posting object to skip the parse; OR",
            "role": "target role string + required_skills[] to score against directly",
            "required_skills": ["skill", "..."],
            "nice_to_have": ["skill", "..."],
        },
        "returns": "overall_score (0-100), verdict, role_fit (covered/missing skills), "
                   "ats (structural checks + issues), seniority_alignment, positioning[]",
        "billing": "0.02 USDT0 per call (X Layer / USDT0, EIP-3009 exact scheme)",
    },
    "/v1/tailor": {
        "method": "POST",
        "content_type": "application/json",
        "body": {
            "profile": "candidate profile object: full_name, headline, summary, "
                       "skills[], experience[], education[] (source of truth — not invented)",
            "posting_text": "the job posting as plain text (parsed for you); OR",
            "posting": "a pre-parsed posting object to skip the parse",
        },
        "returns": "{parsed (posting signals), cv (tailored CV JSON: headline, "
                   "summary, skills[], experience[], education[])}",
        "billing": "0.1 USDT0 per call (X Layer / USDT0, EIP-3009 exact scheme)",
    },
    "/v1/cover-letter": {
        "method": "POST",
        "content_type": "application/json",
        "body": {
            "profile": "candidate profile object (as in /v1/tailor)",
            "posting_text": "the job posting as plain text; OR posting (pre-parsed)",
            "cv": "optional tailored CV to cite; generated on the fly if omitted",
        },
        "returns": "{subject, body (120-180 word application email), cv}",
        "billing": "0.1 USDT0 per call (X Layer / USDT0, EIP-3009 exact scheme)",
    },
}


class Enrich402Middleware(BaseHTTPMiddleware):
    """The SDK's 402 puts the challenge only in the base64 PAYMENT-REQUIRED header
    and sends a literal {} body; agents (and marketplace reviewers) who look at the
    body see nothing actionable. Decode the challenge into the body and attach the
    per-route usage docs so a caller can pay from the response alone."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        header = response.headers.get("payment-required")
        if response.status_code != 402 or not header:
            return response
        try:
            challenge = json.loads(base64.b64decode(header))
        except (ValueError, TypeError):
            return response
        body = dict(challenge)
        usage = _USAGE.get(request.url.path)
        if usage:
            body["usage"] = usage
        headers = {k: v for k, v in response.headers.items()
                   if k.lower() not in ("content-length", "content-type")}
        return JSONResponse(body, status_code=402, headers=headers)

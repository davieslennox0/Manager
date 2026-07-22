"""Wires the x402 SDK's payment middleware for ManagerX's paid agentic surface.

Self-hosted seller (no external facilitator) via x402_seller.LocalFacilitatorClient —
the same pattern Pitchook/Manny/Bondsman/Engram run in production, enforced by the
SDK's PaymentMiddlewareASGI ahead of FastAPI routing. Only imported when
config.X402_ENABLED (payTo + operator key present), so the app boots without keys and
the whole product still works — payment just isn't required.

Paid surfaces: /v1/{benchmark,tailor,cover-letter} (the services ManagerX lists on
the OKX.AI marketplace under Resume & Career Workflows) plus the website itself.
Each answers its 402 with one accepts entry per stablecoin in ACCEPTED, so a payer
settles in whichever of them it already holds."""
import base64
import json
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from x402 import x402ResourceServer
from x402.mechanisms.evm.exact.server import ExactEvmScheme
from x402.http.middleware.fastapi import payment_middleware
from x402.http.types import PaymentOption, RouteConfig
from x402.schemas import AssetAmount

from x402_seller import NETWORK, EvmFacilitatorSigner, LocalFacilitatorClient

XLAYER_RPC = os.getenv("XLAYER_RPC_URL", "https://rpc.xlayer.tech")
PAY_TO = os.environ["MANAGERX_X402_PAY_TO"]
ASSET = os.environ["XLAYER_X402_USDT_CONTRACT_ADDRESS"]
BENCHMARK_FEE_ATOMIC = os.getenv("X402_BENCHMARK_FEE_ATOMIC", "20000")  # 0.02
SERVICE_FEE_ATOMIC = os.getenv("X402_SERVICE_FEE_ATOMIC", "100000")  # 0.1 per service

_signer = EvmFacilitatorSigner(XLAYER_RPC, os.environ["OPERATOR_WALLET_PRIVATE_KEY"])

x402_server = x402ResourceServer(LocalFacilitatorClient(_signer))
x402_server.register(NETWORK, ExactEvmScheme())
x402_server.initialize()

# Every stablecoin we accept, all on X Layer and all EIP-3009 + 6 decimals — so one
# atomic amount prices all of them and a single-network facilitator settles all of
# them (no router, no extra gas, no second chain). Addresses come from OKX's
# official xlayer-tokenlist. DAI is deliberately absent: it has no
# transferWithAuthorization, so the exact scheme cannot use it.
#
# `name`/`version` ARE the token's EIP-712 domain, and getting one wrong does not
# fail loudly — it silently rejects every signature the payer sends. _verify_domains
# reconstructs each DOMAIN_SEPARATOR on-chain at boot so a bad entry is caught here
# rather than as a stream of mystery payment failures.
ASSETS = [
    {"symbol": "USDT0", "address": ASSET, "name": "USD₮0", "version": "1"},
    {"symbol": "USDC", "address": os.getenv("XLAYER_USDC_CONTRACT_ADDRESS",
                                            "0x74b7F16337b8972027F6196A17a631aC6dE26d22"),
     "name": "USD Coin", "version": "2"},
    {"symbol": "USDG", "address": os.getenv("XLAYER_USDG_CONTRACT_ADDRESS",
                                            "0x4ae46a509F6b1D9056937BA4500cb143933D2dc8"),
     "name": "Global Dollar", "version": "1"},
]
DECIMALS = 6

_DOMAIN_TYPEHASH_TEXT = ("EIP712Domain(string name,string version,uint256 chainId,"
                         "address verifyingContract)")


def _verify_domains(assets: list[dict]) -> list[dict]:
    """Drop any asset whose configured EIP-712 domain doesn't match the chain.

    A mismatch is dropped (it could never take a payment anyway), but an
    unreachable RPC keeps the asset — we can't prove it wrong, and losing every
    payment option because a node blipped at boot is the worse failure."""
    from eth_abi import encode
    from web3 import Web3

    try:
        w3 = Web3(Web3.HTTPProvider(XLAYER_RPC, request_kwargs={"timeout": 15}))
        chain_id = w3.eth.chain_id
        typehash = Web3.keccak(text=_DOMAIN_TYPEHASH_TEXT)
        abi = [{"name": "DOMAIN_SEPARATOR", "inputs": [],
                "outputs": [{"type": "bytes32"}], "type": "function",
                "stateMutability": "view"}]
    except Exception as e:  # RPC unreachable — trust config, don't strip rails
        print(f"[x402] domain check skipped ({type(e).__name__}); accepting all assets")
        return assets

    ok = []
    for a in assets:
        try:
            addr = Web3.to_checksum_address(a["address"])
            onchain = w3.eth.contract(address=addr, abi=abi).functions.DOMAIN_SEPARATOR().call()
            expected = Web3.keccak(encode(
                ["bytes32", "bytes32", "bytes32", "uint256", "address"],
                [typehash, Web3.keccak(text=a["name"]),
                 Web3.keccak(text=a["version"]), chain_id, addr]))
            if onchain == expected:
                ok.append(a)
            else:
                print(f"[x402] DROPPED {a['symbol']} — EIP-712 domain mismatch "
                      f"(name={a['name']!r} version={a['version']!r}); it would "
                      f"reject every payment")
        except Exception as e:
            print(f"[x402] {a['symbol']} domain unverified ({type(e).__name__}); keeping")
            ok.append(a)
    return ok


ACCEPTED = _verify_domains(ASSETS)


def _option(amount_atomic: str) -> list[PaymentOption]:
    """One PaymentOption per accepted asset — the payer picks whichever it holds."""
    return [
        PaymentOption(
            scheme="exact",
            pay_to=PAY_TO,
            price=AssetAmount(amount=amount_atomic, asset=a["address"]),
            network=NETWORK,
            max_timeout_seconds=120,
            # EIP-3009 transferWithAuthorization: no buyer Permit2 approve needed.
            extra={"assetTransferMethod": "eip3009", "name": a["name"],
                   "version": a["version"], "decimals": DECIMALS},
        )
        for a in ACCEPTED
    ]


def _rails(unit: str) -> str:
    """'0.1 USDT0 / USDC / USDG' — the billing line for the usage docs."""
    return f"{unit} " + " / ".join(a["symbol"] for a in ACCEPTED)


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
        "billing": f"{_rails('0.02')} per call (X Layer, EIP-3009 exact scheme)",
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
        "billing": f"{_rails('0.1')} per call (X Layer, EIP-3009 exact scheme)",
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
        "billing": f"{_rails('0.1')} per call (X Layer, EIP-3009 exact scheme)",
    },
    # Base/USDC rail (CDP facilitator, x402 Bazaar) — same services, USDC on Base.
    "/v1/base/benchmark": {
        "method": "POST", "content_type": "application/json",
        "body": {"resume_text": "résumé as plain text (required)",
                 "posting_text": "job posting text; OR posting/role+required_skills"},
        "returns": "overall_score, verdict, role_fit, ats, positioning[]",
        "billing": "0.1 USDC per call (Base / USDC, CDP facilitator)",
    },
    "/v1/base/tailor": {
        "method": "POST", "content_type": "application/json",
        "body": {"profile": "candidate profile object", "posting_text": "posting text"},
        "returns": "{parsed, cv}",
        "billing": "0.1 USDC per call (Base / USDC, CDP facilitator)",
    },
    "/v1/base/cover-letter": {
        "method": "POST", "content_type": "application/json",
        "body": {"profile": "candidate profile object", "posting_text": "posting text",
                 "cv": "optional tailored CV"},
        "returns": "{subject, body, cv}",
        "billing": "0.1 USDC per call (Base / USDC, CDP facilitator)",
    },
}


# ---------------------------------------------------------------------------
# Website paywall: agents pay per view, humans (and crawlers) browse free.
# ---------------------------------------------------------------------------
# 0.1 USDT0 per page view, priced per REQUEST with no session — so a return visit
# tomorrow pays again. Reuses the X Layer/USDT0 facilitator above. A single
# "GET /*" route gates every page; _is_page_request narrows what actually reaches
# the gate (never /assets, /v1, /health, static files), and _looks_like_agent
# ensures only programmatic clients pay — human browsers pass straight through, so
# the human product and SEO are untouched. Best-effort by design: an agent that
# spoofs a full browser UA slips through free (the accepted tradeoff for not
# breaking real browsers).
PAGE_FEE_ATOMIC = os.getenv("X402_PAGE_FEE_ATOMIC", "100000")  # 0.1 USDT0 per view

PAGE_ROUTES = {
    "GET /*": RouteConfig(
        accepts=_option(PAGE_FEE_ATOMIC),
        description=f"ManagerX website access — {_rails('0.1')} per page view "
                    f"(X Layer, EIP-3009). Priced per request with no session, so "
                    f"every view including a return visit pays again. Human browsers "
                    f"are served free; automated/agent clients pay per view.",
    ),
}

_PAGE_USAGE = {
    "method": "GET",
    "note": "Website page view. Priced per request — no session, so a repeat visit "
            "pays again. Human browsers and search/social crawlers are served free; "
            "this charge applies to automated/agent clients.",
    "billing": f"{_rails('0.1')} per view (X Layer, EIP-3009 exact scheme)",
}

# Search + social crawlers stay free: gating them would drop ManagerX from indexes
# and break link previews — the whole reason we chose agents-pay over a hard wall.
_CRAWLER_UA = ("googlebot", "bingbot", "slurp", "duckduckbot", "baiduspider",
               "yandexbot", "applebot", "petalbot", "facebookexternalhit",
               "twitterbot", "linkedinbot", "telegrambot", "discordbot", "slackbot")


def _is_page_request(request) -> bool:
    """True only for human-facing HTML page routes — never the API, health, static
    assets, or well-known files (those must stay free for the site to function)."""
    if request.method != "GET":
        return False
    p = request.url.path
    if p.startswith(("/v1", "/assets", "/health", "/api", "/.well-known")):
        return False
    if p in ("/favicon.ico", "/robots.txt", "/sitemap.xml"):
        return False
    last = p.rsplit("/", 1)[-1]
    if "." in last and not last.endswith(".html"):
        return False  # a static asset (.js/.css/.png/.svg …), not a page
    return True


def _looks_like_agent(request) -> bool:
    """Best-effort human-vs-agent split. Bias is toward FREE: a false 'agent' would
    break the site for a real visitor, so we only gate clients that clearly aren't
    browsers. Real browsers always send a 'Mozilla/…' UA token."""
    if request.headers.get("x-payment") or request.headers.get("payment-signature"):
        return True  # a paying x402 client — gate so its payment settles
    ua = request.headers.get("user-agent", "").lower()
    if not ua:
        return True  # no UA is a script/agent, never a normal browser
    if any(c in ua for c in _CRAWLER_UA):
        return False  # crawlers/unfurlers free (SEO + link previews)
    return "mozilla" not in ua


class WebsiteWallMiddleware(BaseHTTPMiddleware):
    """x402 paywall on the human site, engaged only for agent/programmatic clients;
    humans and crawlers pass through untouched. Delegates matched requests to the
    SDK's payment middleware (same verify/settle path as the /v1 services), so the
    402 challenge, EIP-3009 verify, and on-chain settle are all reused."""

    def __init__(self, app):
        super().__init__(app)
        self._pay = payment_middleware(PAGE_ROUTES, x402_server)

    async def dispatch(self, request, call_next):
        if _is_page_request(request) and _looks_like_agent(request):
            return await self._pay(request, call_next)
        return await call_next(request)


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
        usage = _USAGE.get(request.url.path) or (_PAGE_USAGE if _is_page_request(request) else None)
        if usage:
            body["usage"] = usage
        headers = {k: v for k, v in response.headers.items()
                   if k.lower() not in ("content-length", "content-type")}
        return JSONResponse(body, status_code=402, headers=headers)

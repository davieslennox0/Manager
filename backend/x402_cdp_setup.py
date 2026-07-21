"""Second x402 rail: Base/USDC settled through Coinbase's CDP Facilitator — the
only path to getting ManagerX indexed in the x402 Bazaar discovery layer (Bazaar
does not see our self-hosted X Layer/USDT0 rail behind OKX #7120). Inert until
config.X402_CDP_ENABLED (CDP key present), so the app boots without it.

Bazaar has no submit step: the CDP Facilitator catalogs a resource the first time
it *settles* a real payment for it. So these routes (a) settle via the CDP
Facilitator and (b) carry discovery metadata (service_name/tags/description).
One real Base/USDC payment through /v1/base/* → ManagerX appears in
discovery/search.

REQUIRES `pip install cdp-sdk` for request auth — deferred until the key lands.
The auth (_cdp_headers) is the one piece to finalize + test against a live CDP
request once the key + cdp-sdk are present; everything else is wired."""
import os

from x402 import x402ResourceServer
from x402.http.facilitator_client import HTTPFacilitatorClient
from x402.http.facilitator_client_base import CreateHeadersAuthProvider, FacilitatorConfig
from x402.http.types import PaymentOption, RouteConfig
from x402.mechanisms.evm.exact.server import ExactEvmScheme
from x402.schemas import AssetAmount

import config

BASE_NETWORK = "eip155:8453"          # Base mainnet
CDP_HOST = "api.cdp.coinbase.com"
CDP_BASE_PATH = "/platform/v2/x402"   # facilitator hits {url}/verify|/settle|/supported
BASE_FEE_ATOMIC = os.getenv("X402_BASE_FEE_ATOMIC", "100000")  # 0.1 USDC (6 dp)


def _cdp_headers() -> dict:
    """Per-endpoint CDP Bearer JWTs. Each facilitator call ({url}/verify, /settle,
    /supported) needs a JWT whose `uri` claim matches that method+path, so we mint
    one per endpoint. cdp-sdk handles the EC/Ed25519 key formats and signing."""
    from cdp.auth.utils.jwt import JwtOptions, generate_jwt  # cdp-sdk

    def _bearer(method: str, sub: str) -> dict[str, str]:
        token = generate_jwt(JwtOptions(
            api_key_id=config.CDP_API_KEY_ID,
            api_key_secret=config.CDP_API_KEY_SECRET,
            request_method=method,
            request_host=CDP_HOST,
            request_path=CDP_BASE_PATH + sub,
            expires_in=120,
        ))
        return {"Authorization": f"Bearer {token}"}

    return {
        "verify": _bearer("POST", "/verify"),
        "settle": _bearer("POST", "/settle"),
        "supported": _bearer("GET", "/supported"),
    }


_facilitator = HTTPFacilitatorClient(FacilitatorConfig(
    url=config.CDP_FACILITATOR_URL,
    auth_provider=CreateHeadersAuthProvider(_cdp_headers)))

x402_cdp_server = x402ResourceServer(_facilitator)
x402_cdp_server.register(BASE_NETWORK, ExactEvmScheme())
x402_cdp_server.initialize()

_USDC_EXTRA = {"name": "USD Coin", "version": "2", "decimals": 6}


def _option() -> PaymentOption:
    return PaymentOption(
        scheme="exact",
        pay_to=config.BASE_X402_PAY_TO,
        price=AssetAmount(amount=BASE_FEE_ATOMIC, asset=config.BASE_USDC_CONTRACT),
        network=BASE_NETWORK,
        max_timeout_seconds=300,
        extra=_USDC_EXTRA,
    )


# Base-rail aliases of the same three services (handlers reused verbatim — only the
# payment rail differs). service_name ≤32 chars, ≤5 tags: kept within Bazaar caps.
x402_cdp_routes = {
    "/v1/base/benchmark": RouteConfig(
        accepts=_option(),
        description="ATS-readiness + role-fit résumé scoring: POST résumé + posting "
                    "-> score, skill-gaps, prioritized fixes",
        service_name="ManagerX Résumé Benchmark",
        tags=["resume", "career", "ats", "hiring", "jobs"]),
    "/v1/base/tailor": RouteConfig(
        accepts=_option(),
        description="Tailor a CV to one job posting: mirror its vocabulary, reorder "
                    "to required skills, drop irrelevant experience",
        service_name="ManagerX CV Tailoring",
        tags=["resume", "cv", "career", "jobs"]),
    "/v1/base/cover-letter": RouteConfig(
        accepts=_option(),
        description="Draft the application email for one posting from the profile + "
                    "tailored CV (120-180 words)",
        service_name="ManagerX Cover Letter",
        tags=["resume", "career", "cover-letter", "jobs"]),
}

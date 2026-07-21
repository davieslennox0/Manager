"""Base-rail aliases of the agentic services, gated by the CDP/Base-USDC x402
middleware (see x402_cdp_setup). Identical logic to the X Layer endpoints — same
handlers, reused verbatim — so a caller paying USDC-on-Base through Coinbase's
facilitator gets the same result, and the resource lands in the x402 Bazaar index.

Registered always (the endpoints exist); the CDP middleware only enforces payment
when config.X402_CDP_ENABLED. Without the key they behave like the free handlers,
which is fine — nothing reaches them until the Base rail is turned on."""
from fastapi import APIRouter, HTTPException

import config
from routes import agentic_routes, benchmark_routes

router = APIRouter(prefix="/v1/base", tags=["x402-base"])


def _rail_on():
    # Belt-and-suspenders: when the Base rail is off there is no CDP middleware to
    # gate these, so refuse rather than serve the paid service for free.
    if not config.X402_CDP_ENABLED:
        raise HTTPException(503, "Base/USDC rail not enabled on this deployment")


@router.post("/benchmark")
async def base_benchmark(body: benchmark_routes.BenchmarkBody):
    _rail_on()
    return await benchmark_routes.run_benchmark(body)


@router.post("/tailor")
async def base_tailor(body: agentic_routes.TailorBody):
    _rail_on()
    return await agentic_routes.tailor(body)


@router.post("/cover-letter")
async def base_cover_letter(body: agentic_routes.CoverBody):
    _rail_on()
    return await agentic_routes.cover_letter(body)

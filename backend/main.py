"""ManagerX API — job-first application pipeline: posting -> tailored CV -> accepted
offer -> onchain-signed work agreement -> verified work history. Plus the
discovery layer: scanner-fed public job board + email digests."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import auth
import config
import funding
import scanner
from db import init_db
from routes.agentic_routes import router as agentic_router
from routes.agreement_routes import router as agreement_router
from routes.auth_routes import router as auth_router
from routes.benchmark_routes import router as benchmark_router
from routes.document_routes import router as document_router
from routes.job_routes import router as job_router
from routes.listing_routes import router as listing_router
from routes.profile_routes import router as profile_router
from routes.proof_routes import router as proof_router
from routes.public_routes import router as public_router

STATIC_DIR = Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    auth.seed_admin()
    scanner.seed_sources()
    scanner.backfill_categories()
    tasks = []
    if config.SCANNER_ENABLED:
        tasks.append(asyncio.create_task(scanner.scanner_loop()))
    if config.FUNDING_ENABLED:
        tasks.append(asyncio.create_task(funding.funding_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="ManagerX", version="1.0.0", lifespan=lifespan)

# x402 payment gate on the agentic /v1/benchmark service. Added before CORS so
# CORS stays outermost; Enrich402 sits just outside the payment middleware to
# splice the usage hint into its 402 body. No-op when keys are absent.
if config.X402_ENABLED:
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
    from x402_setup import Enrich402Middleware, x402_routes, x402_server
    app.add_middleware(PaymentMiddlewareASGI, routes=x402_routes, server=x402_server)
    app.add_middleware(Enrich402Middleware)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

for r in (auth_router, profile_router, job_router, agreement_router, document_router,
          listing_router, proof_router, public_router, benchmark_router,
          agentic_router):
    app.include_router(r)


@app.get("/health")
async def health():
    return {"ok": True, "service": "managerx",
            "chain_id": config.CHAIN_ID,
            "registry": config.REGISTRY_ADDRESS or None,
            "scanner": config.SCANNER_ENABLED,
            "smtp": config.SMTP_ENABLED,
            "funding": config.FUNDING_ENABLED,
            "github_oauth": config.GITHUB_OAUTH_ENABLED,
            "x402": config.X402_ENABLED}


if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        candidate = STATIC_DIR / path
        if path and candidate.is_file() and candidate.resolve().is_relative_to(STATIC_DIR):
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=config.PORT)

"""WorkOS API — job-first application pipeline: posting -> tailored CV -> accepted
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
import scanner
from db import init_db
from routes.agreement_routes import router as agreement_router
from routes.auth_routes import router as auth_router
from routes.job_routes import router as job_router
from routes.listing_routes import router as listing_router
from routes.profile_routes import router as profile_router

STATIC_DIR = Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    auth.seed_admin()
    scanner.seed_sources()
    task = None
    if config.SCANNER_ENABLED:
        task = asyncio.create_task(scanner.scanner_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="WorkOS", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

for r in (auth_router, profile_router, job_router, agreement_router, listing_router):
    app.include_router(r)


@app.get("/health")
async def health():
    return {"ok": True, "service": "workos",
            "chain_id": config.CHAIN_ID,
            "registry": config.REGISTRY_ADDRESS or None,
            "scanner": config.SCANNER_ENABLED,
            "smtp": config.SMTP_ENABLED}


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

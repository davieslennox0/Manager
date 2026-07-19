"""Proof-of-work source management + per-job evidence matching.
GitHub connects via OAuth when the app is configured (GITHUB_CLIENT_ID/SECRET),
else in public-data mode by username — same normalized repo cache either way.
Wallets connect by signing a nonce; the backend recovers the signer before
trusting the address. The match endpoint merges its output into the job's
existing tailored CV (regenerating the CV drops it — just re-match)."""
import json
import secrets
import time

import httpx
import jwt
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

import config
import proofwork
from auth import current_user
from db import get_conn, j
from llm import LLMError

router = APIRouter(prefix="/v1/proof", tags=["proof"])

_STATE_TTL = 600


class PublicConnectBody(BaseModel):
    username: str


class WalletBody(BaseModel):
    address: str
    signature: str
    nonce: str


# ── GitHub ───────────────────────────────────────────────────────────────

def _github_status(user_id: str) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT username, access_token, repos, fetched_at "
                       "FROM github_accounts WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return {"connected": False, "oauth_enabled": config.GITHUB_OAUTH_ENABLED}
    return {"connected": True, "oauth_enabled": config.GITHUB_OAUTH_ENABLED,
            "username": row["username"],
            "mode": "oauth" if row["access_token"] else "public",
            "repo_count": len(j(row["repos"], [])),
            "fetched_at": row["fetched_at"]}


def _store_github(user_id: str, username: str, token: str, repos: list):
    conn = get_conn()
    conn.execute(
        """INSERT INTO github_accounts (user_id, username, access_token, repos, fetched_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
             access_token=excluded.access_token, repos=excluded.repos,
             fetched_at=CURRENT_TIMESTAMP""",
        (user_id, username, token, json.dumps(repos, ensure_ascii=False)))
    conn.commit()
    conn.close()


@router.get("/github")
async def github_status(user: dict = Depends(current_user)):
    return _github_status(user["user_id"])


@router.get("/github/repos")
async def github_repos(user: dict = Depends(current_user)):
    conn = get_conn()
    row = conn.execute("SELECT repos FROM github_accounts WHERE user_id=?",
                       (user["user_id"],)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "GitHub not connected")
    repos = j(row["repos"], [])
    return {"repos": [{k: r[k] for k in ("full_name", "description", "language",
                                         "stars", "pushed_at", "url", "pinned")}
                      for r in repos]}


@router.get("/github/login")
async def github_login(user: dict = Depends(current_user)):
    """OAuth entry: the state token carries the user through the callback."""
    if not config.GITHUB_OAUTH_ENABLED:
        raise HTTPException(503, "GitHub OAuth app not configured — connect in "
                                 "public mode with your username instead")
    state = jwt.encode({"sub": user["user_id"], "exp": int(time.time()) + _STATE_TTL,
                        "purpose": "gh_oauth"}, config.SECRET_KEY, algorithm="HS256")
    url = ("https://github.com/login/oauth/authorize"
           f"?client_id={config.GITHUB_CLIENT_ID}"
           f"&redirect_uri={config.PUBLIC_BASE_URL}/v1/proof/github/callback"
           f"&scope=read:user%20public_repo&state={state}")
    return {"url": url}


@router.get("/github/callback")
async def github_callback(code: str = "", state: str = ""):
    """No bearer auth here (GitHub redirects the browser) — state is the auth."""
    try:
        payload = jwt.decode(state, config.SECRET_KEY, algorithms=["HS256"])
        assert payload.get("purpose") == "gh_oauth"
    except Exception:
        raise HTTPException(401, "Bad or expired OAuth state — retry the connect")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={"client_id": config.GITHUB_CLIENT_ID,
                  "client_secret": config.GITHUB_CLIENT_SECRET, "code": code},
            headers={"Accept": "application/json"})
        token = resp.json().get("access_token", "")
        if not token:
            raise HTTPException(502, f"GitHub token exchange failed: {resp.text[:150]}")
        me = await client.get("https://api.github.com/user",
                              headers={"Authorization": f"Bearer {token}",
                                       "Accept": "application/vnd.github+json"})
        username = me.json().get("login", "")
    if not username:
        raise HTTPException(502, "GitHub /user returned no login")
    try:
        repos = await proofwork.fetch_github_repos(username, token)
    except proofwork.GitHubError as e:
        raise HTTPException(502, str(e))
    _store_github(payload["sub"], username, token, repos)
    return RedirectResponse("/profile?github=connected")


@router.post("/github/public")
async def github_public_connect(body: PublicConnectBody,
                                user: dict = Depends(current_user)):
    """Public-data mode: no OAuth app needed, public repos only, no token stored."""
    username = body.username.strip().lstrip("@")
    if not username:
        raise HTTPException(422, "Provide a GitHub username")
    try:
        repos = await proofwork.fetch_github_repos(username)
    except proofwork.GitHubError as e:
        raise HTTPException(422, str(e))
    _store_github(user["user_id"], username, "", repos)
    return _github_status(user["user_id"])


@router.post("/github/refresh")
async def github_refresh(user: dict = Depends(current_user)):
    conn = get_conn()
    row = conn.execute("SELECT username, access_token FROM github_accounts "
                       "WHERE user_id=?", (user["user_id"],)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "GitHub not connected")
    try:
        repos = await proofwork.fetch_github_repos(row["username"], row["access_token"])
    except proofwork.GitHubError as e:
        raise HTTPException(502, str(e))
    _store_github(user["user_id"], row["username"], row["access_token"], repos)
    return _github_status(user["user_id"])


@router.delete("/github")
async def github_disconnect(user: dict = Depends(current_user)):
    conn = get_conn()
    conn.execute("DELETE FROM github_accounts WHERE user_id=?", (user["user_id"],))
    conn.commit()
    conn.close()
    return {"connected": False}


# ── Wallet ───────────────────────────────────────────────────────────────

_NONCES: dict[str, tuple[str, float]] = {}  # user_id -> (nonce, issued_at)


def wallet_message(nonce: str) -> str:
    return (f"ManagerX proof-of-work wallet link\nnonce: {nonce}\n"
            "Signing proves you control this address. No transaction, no cost.")


@router.get("/wallet")
async def wallet_status(user: dict = Depends(current_user)):
    conn = get_conn()
    row = conn.execute("SELECT address, activity, fetched_at FROM wallets "
                       "WHERE user_id=?", (user["user_id"],)).fetchone()
    conn.close()
    if not row:
        return {"connected": False}
    return {"connected": True, "address": row["address"],
            "activity": j(row["activity"], {}), "fetched_at": row["fetched_at"]}


@router.get("/wallet/nonce")
async def wallet_nonce(user: dict = Depends(current_user)):
    nonce = secrets.token_hex(16)
    _NONCES[user["user_id"]] = (nonce, time.time())
    return {"nonce": nonce, "message": wallet_message(nonce)}


@router.post("/wallet")
async def wallet_connect(body: WalletBody, user: dict = Depends(current_user)):
    issued = _NONCES.get(user["user_id"])
    if not issued or issued[0] != body.nonce or time.time() - issued[1] > _STATE_TTL:
        raise HTTPException(422, "Nonce missing or expired — request a fresh one")
    try:
        recovered = Account.recover_message(
            encode_defunct(text=wallet_message(body.nonce)), signature=body.signature)
    except Exception:
        raise HTTPException(422, "Could not recover a signer from that signature")
    if recovered.lower() != body.address.lower():
        raise HTTPException(422, "Signature was not made by that address")
    _NONCES.pop(user["user_id"], None)
    activity = await proofwork.wallet_activity(recovered)
    conn = get_conn()
    conn.execute(
        """INSERT INTO wallets (user_id, address, activity, fetched_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id) DO UPDATE SET address=excluded.address,
             activity=excluded.activity, fetched_at=CURRENT_TIMESTAMP""",
        (user["user_id"], recovered, json.dumps(activity)))
    conn.commit()
    conn.close()
    return {"connected": True, "address": recovered, "activity": activity}


@router.delete("/wallet")
async def wallet_disconnect(user: dict = Depends(current_user)):
    conn = get_conn()
    conn.execute("DELETE FROM wallets WHERE user_id=?", (user["user_id"],))
    conn.commit()
    conn.close()
    return {"connected": False}


# ── Per-job matching ─────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/match")
async def match_job(job_id: str, user: dict = Depends(current_user)):
    """Build the proof block for THIS job (LLM repo ranking + contract
    verification + platform history) and merge it into the job's CV."""
    conn = get_conn()
    job = conn.execute("SELECT * FROM jobs WHERE job_id=? AND user_id=?",
                       (job_id, user["user_id"])).fetchone()
    conn.close()
    if not job:
        raise HTTPException(404, "No such job")
    try:
        block = await proofwork.build_proof_block(user["user_id"], j(job["parsed"], {}))
    except LLMError as e:
        raise HTTPException(503, f"Proof matching unavailable: {e}")
    conn = get_conn()
    cv = conn.execute("SELECT content FROM cvs WHERE job_id=?", (job_id,)).fetchone()
    if cv:
        content = j(cv["content"], {})
        content["relevant_work"] = block["relevant_work"]
        content["onchain_footprint"] = block["onchain_footprint"]
        conn.execute("UPDATE cvs SET content=?, updated_at=CURRENT_TIMESTAMP "
                     "WHERE job_id=?",
                     (json.dumps(content, ensure_ascii=False), job_id))
        conn.commit()
    conn.close()
    return {"job_id": job_id, **block, "merged_into_cv": bool(cv)}

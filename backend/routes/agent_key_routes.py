"""Agent API keys — the credential an autonomous client holds.

A key is minted from a signed-in session and thereafter authenticates as that
same user on the agent-facing surfaces (currently Household Gigs). Minting,
listing, and revoking all require the JWT deliberately: a key can never mint
another key, so a leaked key cannot extend its own foothold.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
from auth import current_user
from db import get_conn

router = APIRouter(prefix="/v1/agent-keys", tags=["agent-keys"])


class KeyCreate(BaseModel):
    label: str = ""


@router.post("")
async def create_key(body: KeyCreate, user: dict = Depends(current_user)):
    """Mint a key. The secret is in this response and nowhere else — it is stored
    only as a digest, so it cannot be shown again."""
    secret, row = auth.mint_agent_key(user["user_id"], body.label)
    return {
        **row,
        "key": secret,
        "usage": {
            "header": "Authorization: Bearer <key>",
            "alternative": "X-API-Key: <key>",
            "scope": "Household Gigs: browse, claim, and report cycle status as "
                     f"{user['email']}.",
            "warning": "Shown once. Store it now — a lost key is revoked and "
                       "replaced, not recovered.",
        },
    }


@router.get("")
async def list_keys(user: dict = Depends(current_user)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT key_id, label, prefix, created_at, last_used_at, revoked "
        "FROM agent_keys WHERE user_id = ? ORDER BY created_at DESC",
        (user["user_id"],)).fetchall()
    conn.close()
    return {"agent_keys": [dict(r) for r in rows]}


@router.delete("/{key_id}")
async def revoke_key(key_id: str, user: dict = Depends(current_user)):
    """Revoke immediately. The row is kept rather than deleted so `last_used_at`
    survives — after a leak, when the key was last used is the thing you want."""
    conn = get_conn()
    row = conn.execute("SELECT user_id, revoked FROM agent_keys WHERE key_id = ?",
                       (key_id,)).fetchone()
    if not row or row["user_id"] != user["user_id"]:
        conn.close()
        raise HTTPException(404, "No such agent key")
    if row["revoked"]:
        conn.close()
        raise HTTPException(409, "Already revoked")
    conn.execute("UPDATE agent_keys SET revoked = 1 WHERE key_id = ?", (key_id,))
    conn.commit()
    conn.close()
    return {"key_id": key_id, "revoked": True}

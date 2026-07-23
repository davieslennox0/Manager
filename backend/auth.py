"""Auth: dashboard JWT (pbkdf2 + HS256, same as the sibling services) for humans,
plus long-lived agent API keys for autonomous clients that can't hold a session."""
import hashlib
import secrets
import time
import uuid

import jwt
from fastapi import HTTPException, Request

from config import ADMIN_EMAIL, ADMIN_PASSWORD, SECRET_KEY
from db import get_conn

JWT_TTL_SECONDS = 24 * 3600


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    return salt + ":" + hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split(":", 1)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return secrets.compare_digest(candidate, digest)


def create_user(email: str, password: str, role: str = "user") -> str:
    user_id = "usr_" + uuid.uuid4().hex[:12]
    conn = get_conn()
    conn.execute("INSERT INTO users (user_id, email, password_hash, role) VALUES (?, ?, ?, ?)",
                 (user_id, email, hash_password(password), role))
    conn.execute("INSERT INTO profiles (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    return user_id


def seed_admin():
    if not (ADMIN_EMAIL and ADMIN_PASSWORD):
        return
    conn = get_conn()
    exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (ADMIN_EMAIL,)).fetchone()
    conn.close()
    if not exists:
        create_user(ADMIN_EMAIL, ADMIN_PASSWORD, role="admin")


def issue_jwt(user_id: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + JWT_TTL_SECONDS},
                      SECRET_KEY, algorithm="HS256")


async def current_user(request: Request) -> dict:
    bearer = request.headers.get("authorization", "")
    token = bearer[7:] if bearer.lower().startswith("bearer ") else None
    if not token:
        raise HTTPException(401, "Login required (Authorization: Bearer <token>)")
    if token.startswith(KEY_PREFIX):
        # An agent key reaching a session-only endpoint: say why, rather than
        # letting it fail as a malformed JWT and read as "your login expired".
        raise HTTPException(401, "This endpoint needs a signed-in session — an agent "
                                 "key can't be used here (keys cannot mint or manage "
                                 "keys, or change the account they belong to)")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token — log in again")
    conn = get_conn()
    row = conn.execute("SELECT user_id, email, role FROM users WHERE user_id = ?",
                       (payload["sub"],)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "Unknown user")
    return dict(row)


# ── Agent API keys ───────────────────────────────────────────────────────────
# A browser holds a JWT that expires in a day and is refreshed by a human typing
# a password. An autonomous agent can do neither, so it gets a long-lived key it
# stores in its own config and presents on every call. The key authenticates as
# the user who minted it — there is no separate agent identity to reconcile.

KEY_PREFIX = "mxk_"
_KEY_BYTES = 32          # 256 bits: unguessable, so the stored digest can be plain sha256
PREFIX_SHOWN = 12        # mxk_ + 8 chars, enough to tell two keys apart in a list


def hash_agent_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def mint_agent_key(user_id: str, label: str = "") -> tuple[str, dict]:
    """Create a key and return (secret, row). The secret is returned exactly once
    and never stored — a lost key is revoked and replaced, not recovered."""
    secret = KEY_PREFIX + secrets.token_urlsafe(_KEY_BYTES)
    key_id = "ak_" + uuid.uuid4().hex[:12]
    conn = get_conn()
    conn.execute(
        "INSERT INTO agent_keys (key_id, user_id, label, prefix, key_hash) "
        "VALUES (?, ?, ?, ?, ?)",
        (key_id, user_id, label.strip()[:60], secret[:PREFIX_SHOWN], hash_agent_key(secret)))
    conn.commit()
    row = conn.execute("SELECT key_id, label, prefix, created_at, last_used_at, revoked "
                       "FROM agent_keys WHERE key_id = ?", (key_id,)).fetchone()
    conn.close()
    return secret, dict(row)


def user_for_agent_key(secret: str) -> dict | None:
    """Resolve a presented key to its owner, or None. Looks up by digest against a
    unique index, so an invalid key costs one indexed miss."""
    conn = get_conn()
    row = conn.execute(
        """SELECT k.key_id, u.user_id, u.email, u.role FROM agent_keys k
           JOIN users u ON u.user_id = k.user_id
           WHERE k.key_hash = ? AND k.revoked = 0""",
        (hash_agent_key(secret),)).fetchone()
    if row:
        conn.execute("UPDATE agent_keys SET last_used_at=CURRENT_TIMESTAMP WHERE key_id=?",
                     (row["key_id"],))
        conn.commit()
    conn.close()
    return dict(row) if row else None


async def current_actor(request: Request) -> dict:
    """Auth for surfaces an autonomous client uses: accepts either a dashboard JWT
    or an agent key, both on the standard Authorization: Bearer header (a key is
    recognized by its mxk_ prefix). X-API-Key is accepted too, since some agent
    frameworks reserve Authorization for their own use.

    Returns the same shape as current_user plus how the caller authenticated, so a
    route can tell a browser session from a machine one without a second lookup."""
    bearer = request.headers.get("authorization", "")
    presented = bearer[7:].strip() if bearer.lower().startswith("bearer ") else ""
    api_key = request.headers.get("x-api-key", "").strip() or (
        presented if presented.startswith(KEY_PREFIX) else "")
    if api_key:
        actor = user_for_agent_key(api_key)
        if not actor:
            raise HTTPException(401, "Invalid or revoked agent key")
        return {**actor, "auth": "agent_key"}
    return {**await current_user(request), "auth": "jwt"}

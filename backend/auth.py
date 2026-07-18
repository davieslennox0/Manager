"""Dashboard JWT auth (same pbkdf2 + HS256 pattern as the sibling services)."""
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

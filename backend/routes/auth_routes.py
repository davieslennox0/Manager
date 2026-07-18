from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

import auth
from db import get_conn

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str


@router.post("/signup")
async def signup(body: Credentials):
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    conn = get_conn()
    exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (body.email,)).fetchone()
    conn.close()
    if exists:
        raise HTTPException(409, "Email already registered — log in instead")
    user_id = auth.create_user(body.email, body.password)
    return {"token": auth.issue_jwt(user_id), "user_id": user_id}


@router.post("/login")
async def login(body: Credentials):
    conn = get_conn()
    row = conn.execute("SELECT user_id, password_hash FROM users WHERE email = ?",
                       (body.email,)).fetchone()
    conn.close()
    if not row or not auth.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    return {"token": auth.issue_jwt(row["user_id"]), "user_id": row["user_id"]}

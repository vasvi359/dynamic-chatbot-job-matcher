from passlib.context import CryptContext
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import get_connection

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter()


class AuthRequest(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(data: AuthRequest):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE email = %s", (data.email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")

    password_hash = pwd_context.hash(data.password)
    cur.execute(
        "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
        (data.email, password_hash),
    )
    user_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()

    return {"user_id": user_id, "email": data.email}


@router.post("/login")
def login(data: AuthRequest):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (data.email,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if not user or not pwd_context.verify(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {"user_id": user["id"], "email": data.email}
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
import sqlite3
import uuid
import os

app = FastAPI(
    title="NaijaBank Auth Service",
    description="Authentication Microservice for Nigerian Digital Banking Platform",
    version="1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== CONFIG ==============
SECRET_KEY = "naijabank-secret-key-change-in-production-2026"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 2

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ============== DATABASE ==============
DB_FILE = "auth.db"

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT DEFAULT 'customer',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ============== SCHEMAS ==============
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    full_name: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

# ============== HELPERS ==============
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# ============== ENDPOINTS ==============
@app.get("/")
def root():
    return {
        "service": "Auth Service",
        "status": "running",
        "project": "Secure Containerized Microservice Architecture - Nigerian Digital Banking"
    }

@app.get("/health")
def health():
    return {"status": "ok", "service": "auth"}

@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterIn):
    conn = get_db()
    try:
        user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash, full_name) VALUES (?, ?, ?, ?)",
            (user_id, req.email.lower(), hash_password(req.password), req.full_name)
        )
        conn.commit()
        return {
            "message": "User registered successfully",
            "id": user_id,
            "email": req.email.lower(),
            "full_name": req.full_name,
            "role": "customer"
        }
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email already registered")
    finally:
        conn.close()

@app.post("/auth/login")
def login(req: LoginIn):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (req.email.lower(),)
        ).fetchone()

        if not row or not verify_password(req.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        token = create_token(row["id"], row["email"], row["role"])

        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": row["id"],
                "email": row["email"],
                "full_name": row["full_name"],
                "role": row["role"]
            }
        }
    finally:
        conn.close()
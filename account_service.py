from fastapi import FastAPI, HTTPException, Header, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from jose import jwt, JWTError
from datetime import datetime
import sqlite3, uuid, random

app = FastAPI(title="NaijaBank Account Service", version="1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

SECRET_KEY = "naijabank-secret-key-change-in-production-2026"
ALGORITHM = "HS256"
INTERNAL_KEY = "naijabank-internal-key-2026"
DB_FILE = "account.db"

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            account_number TEXT UNIQUE NOT NULL,
            account_name TEXT NOT NULL,
            balance REAL NOT NULL DEFAULT 0.0,
            currency TEXT DEFAULT 'NGN',
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

class CreateAccountIn(BaseModel):
    account_name: str = "Primary Account"

class InternalOp(BaseModel):
    account_id: str
    amount: float

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")

def require_internal(x_internal_key: str = Header(None)):
    if x_internal_key != INTERNAL_KEY:
        raise HTTPException(401, "Invalid internal service key")

def gen_account_number():
    return "01" + str(random.randint(10000000, 99999999))

@app.get("/health")
def health():
    return {"status": "ok", "service": "account"}

@app.post("/accounts", status_code=201)
def create_account(req: CreateAccountIn, user=Depends(get_current_user)):
    conn = get_db()
    try:
        acc_id = str(uuid.uuid4())
        acc_num = gen_account_number()
        conn.execute(
            "INSERT INTO accounts (id, user_id, account_number, account_name) VALUES (?,?,?,?)",
            (acc_id, user["sub"], acc_num, req.account_name)
        )
        conn.commit()
        return {"id": acc_id, "account_number": acc_num,
                "account_name": req.account_name, "balance": 0.0,
                "currency": "NGN", "status": "active"}
    finally:
        conn.close()

@app.get("/accounts")
def list_accounts(user=Depends(get_current_user)):
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM accounts WHERE user_id=? ORDER BY created_at",
                            (user["sub"],)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

@app.get("/accounts/{account_id}")
def get_account(account_id: str, user=Depends(get_current_user)):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Account not found")
        if row["user_id"] != user["sub"] and user.get("role") != "admin":
            raise HTTPException(403, "Access denied: not your account")
        return dict(row)
    finally:
        conn.close()

@app.post("/internal/debit")
def debit(req: InternalOp, _=Depends(require_internal)):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (req.account_id,)).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            raise HTTPException(404, "Account not found")
        if row["balance"] < req.amount:
            conn.execute("ROLLBACK")
            raise HTTPException(400, "Insufficient funds")
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?",
                     (req.amount, req.account_id))
        conn.commit()
        return {"ok": True, "new_balance": row["balance"] - req.amount}
    finally:
        conn.close()

@app.post("/internal/credit")
def credit(req: InternalOp, _=Depends(require_internal)):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (req.account_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Account not found")
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?",
                     (req.amount, req.account_id))
        conn.commit()
        return {"ok": True, "new_balance": row["balance"] + req.amount}
    finally:
        conn.close()

@app.post("/internal/fund")
def fund(req: InternalOp, _=Depends(require_internal)):
    """Demo-only endpoint to seed accounts with money."""
    return credit(req)
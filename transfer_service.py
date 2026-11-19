from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from jose import jwt, JWTError
import sqlite3, uuid, httpx, os

app = FastAPI(title="NaijaBank Transfer Service", version="1.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

SECRET_KEY = "naijabank-secret-key-change-in-production-2026"
ALGORITHM = "HS256"
INTERNAL_KEY = "naijabank-internal-key-2026"
ACCOUNT_URL = "http://localhost:8002"
DB_FILE = "transfer.db"

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transfers (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            from_account_id TEXT NOT NULL,
            to_account_id TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'NGN',
            status TEXT DEFAULT 'pending',
            failure_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

class TransferIn(BaseModel):
    from_account_id: str
    to_account_id: str
    amount: float
    idempotency_key: str | None = None

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.split(" ")[1]
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]), token
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")

@app.get("/health")
def health():
    return {"status": "ok", "service": "transfer"}

@app.post("/transfers", status_code=201)
def create_transfer(req: TransferIn, auth=Depends(get_current_user)):
    user, token = auth
    conn = get_db()
    idem = req.idempotency_key or str(uuid.uuid4())

    if req.from_account_id == req.to_account_id:
        raise HTTPException(400, "Cannot transfer to the same account")
    if req.amount <= 0:
        raise HTTPException(400, "Amount must be positive")

    # Idempotency check FIRST
    try:
        transfer_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO transfers (id, idempotency_key, user_id, from_account_id,
                                       to_account_id, amount, status)
               VALUES (?,?,?,?,?,?, 'pending')""",
            (transfer_id, idem, user["sub"], req.from_account_id,
             req.to_account_id, req.amount)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT * FROM transfers WHERE idempotency_key=?",
                           (idem,)).fetchone()
        conn.close()
        return {**dict(row), "idempotent_replay": True}

    # Verify ownership of source account
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{ACCOUNT_URL}/accounts/{req.from_account_id}",
                           headers={"Authorization": f"Bearer {token}"})
            if r.status_code != 200:
                conn.execute("UPDATE transfers SET status='failed', failure_reason=? WHERE id=?",
                             ("Source account not accessible", transfer_id))
                conn.commit()
                conn.close()
                raise HTTPException(403, "Source account not accessible")

            # Debit source
            r = client.post(f"{ACCOUNT_URL}/internal/debit",
                            json={"account_id": req.from_account_id, "amount": req.amount},
                            headers={"x-internal-key": INTERNAL_KEY})
            if r.status_code != 200:
                conn.execute("UPDATE transfers SET status='failed', failure_reason=? WHERE id=?",
                             (r.json().get("detail", "Debit failed"), transfer_id))
                conn.commit()
                conn.close()
                raise HTTPException(400, r.json().get("detail", "Debit failed"))

            # Credit destination
            r = client.post(f"{ACCOUNT_URL}/internal/credit",
                            json={"account_id": req.to_account_id, "amount": req.amount},
                            headers={"x-internal-key": INTERNAL_KEY})
            if r.status_code != 200:
                # SAGA COMPENSATION
                client.post(f"{ACCOUNT_URL}/internal/credit",
                            json={"account_id": req.from_account_id, "amount": req.amount},
                            headers={"x-internal-key": INTERNAL_KEY})
                conn.execute("UPDATE transfers SET status='failed', failure_reason=? WHERE id=?",
                             ("Credit failed; transfer reversed", transfer_id))
                conn.commit()
                conn.close()
                raise HTTPException(400, "Transfer failed and was reversed")

        conn.execute("UPDATE transfers SET status='completed' WHERE id=?", (transfer_id,))
        conn.commit()
        return {"id": transfer_id, "idempotency_key": idem,
                "from_account_id": req.from_account_id,
                "to_account_id": req.to_account_id,
                "amount": req.amount, "currency": "NGN",
                "status": "completed"}
    finally:
        conn.close()

@app.get("/transfers")
def list_transfers(auth=Depends(get_current_user)):
    user, _ = auth
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM transfers WHERE user_id=? ORDER BY created_at DESC",
                            (user["sub"],)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
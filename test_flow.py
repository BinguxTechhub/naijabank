import httpx
import json
import uuid

# Base URLs for our three microservices
AUTH_URL = "http://localhost:8001"
ACCOUNT_URL = "http://localhost:8002"
TRANSFER_URL = "http://localhost:8003"

print("🚀 Starting End-to-End Microservice Test...\n")

# Generate a unique email so we don't get a "user already exists" error
test_email = f"test_{uuid.uuid4().hex[:6]}@naija.com"
test_password = "Passw0rd!"

# 1. REGISTER
print("1️⃣ Registering user...")
res = httpx.post(f"{AUTH_URL}/auth/register", json={
    "email": test_email, "password": test_password, "full_name": "Christabel Abashi"
})
print(json.dumps(res.json(), indent=2))

# 2. LOGIN
print("\n2️⃣ Logging in...")
res = httpx.post(f"{AUTH_URL}/auth/login", json={"email": test_email, "password": test_password})
token = res.json()["access_token"]
print(f"✅ Got Token: {token[:30]}...\n")

headers = {"Authorization": f"Bearer {token}"}

# 3. CREATE MAIN ACCOUNT
print("3️⃣ Creating Main Account...")
res = httpx.post(f"{ACCOUNT_URL}/accounts", headers=headers, json={"account_name": "Main Account"})
main_id = res.json()["id"]
print(json.dumps(res.json(), indent=2))

# 4. CREATE SAVINGS ACCOUNT
print("\n4️⃣ Creating Savings Account...")
res = httpx.post(f"{ACCOUNT_URL}/accounts", headers=headers, json={"account_name": "Savings Account"})
savings_id = res.json()["id"]
print(json.dumps(res.json(), indent=2))

# 5. FUND MAIN ACCOUNT (₦50,000)
print("\n5️⃣ Funding Main Account with ₦50,000...")
res = httpx.post(f"{ACCOUNT_URL}/internal/fund", headers={"x-internal-key": "naijabank-internal-key-2026"}, json={
    "account_id": main_id, "amount": 50000
})
print(json.dumps(res.json(), indent=2))

# 6. TRANSFER ₦10,000
print("\n6️⃣ Transferring ₦10,000 to Savings...")
transfer_data = {
    "from_account_id": main_id,
    "to_account_id": savings_id,
    "amount": 10000,
    "idempotency_key": "demo-transfer-001"
}
res = httpx.post(f"{TRANSFER_URL}/transfers", headers=headers, json=transfer_data)
print(json.dumps(res.json(), indent=2))

# 7. IDEMPOTENCY TEST (Replay the same transfer)
print("\n7️⃣ Replaying the exact same transfer (Idempotency Test)...")
res = httpx.post(f"{TRANSFER_URL}/transfers", headers=headers, json=transfer_data)
print(json.dumps(res.json(), indent=2))

# 8. VERIFY BALANCES
print("\n8️⃣ Verifying Final Balances...")
res = httpx.get(f"{ACCOUNT_URL}/accounts", headers=headers)
print(json.dumps(res.json(), indent=2))

print("\n🎉 Test Complete! Take a screenshot of this terminal.")
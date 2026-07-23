import requests
import uuid
import time
import sys

BASE_URL = 'http://127.0.0.1:8000'
ORIGIN = 'https://incident-iq-weld.vercel.app'
HEADERS = {
    'Origin': ORIGIN
}

def check_cors(res):
    if res.headers.get('Access-Control-Allow-Origin') not in [ORIGIN, '*']:
        print(f"CORS ERROR on {res.url}: Expected {ORIGIN} or *, got {res.headers.get('Access-Control-Allow-Origin')}")
        return False
    return True

print("Running API tests...")
passed = True

# 1. /health
res = requests.get(f"{BASE_URL}/health", headers=HEADERS)
if res.status_code != 200 or not check_cors(res):
    print("/health FAILED", res.status_code, res.text)
    passed = False
else:
    print("/health OK")

# 2. /auth/register & login
uid = str(uuid.uuid4())
res = requests.post(f"{BASE_URL}/auth/register", json={"username": uid, "password": "pw"}, headers=HEADERS)
if res.status_code != 200 or not check_cors(res):
    print("/auth/register FAILED", res.status_code, res.text)
    passed = False
else:
    print("/auth/register OK")

res = requests.post(f"{BASE_URL}/auth/login", json={"username": uid, "password": "pw"}, headers=HEADERS)
if res.status_code != 200 or not check_cors(res):
    print("/auth/login FAILED", res.status_code, res.text)
    passed = False
else:
    print("/auth/login OK")

token = res.json().get('token')
auth_headers = HEADERS.copy()
auth_headers['Authorization'] = f"Bearer {token}"

# 3. /incident/analyze (stream)
thread_id = str(uuid.uuid4())
res = requests.post(f"{BASE_URL}/incident/analyze", json={"query": "hello", "session_id": thread_id}, headers=auth_headers, stream=True)
if res.status_code != 200 or not check_cors(res):
    print("/incident/analyze FAILED", res.status_code)
    passed = False
else:
    # Read stream to completion
    for line in res.iter_lines():
        pass
    print("/incident/analyze OK")

# 4. /incident/history
res = requests.get(f"{BASE_URL}/incident/history", headers=auth_headers)
if res.status_code != 200 or not check_cors(res):
    print("/incident/history FAILED", res.status_code, res.text)
    passed = False
else:
    print("/incident/history OK")

# 5. /incident/history/{thread_id}
res = requests.get(f"{BASE_URL}/incident/history/{thread_id}", headers=auth_headers)
if res.status_code != 200 or not check_cors(res):
    print(f"/incident/history/{thread_id} FAILED", res.status_code, res.text)
    passed = False
else:
    print(f"/incident/history/{{thread_id}} OK")

# 6. /auth/history/{thread_id} (DELETE)
res = requests.delete(f"{BASE_URL}/auth/history/{thread_id}", headers=auth_headers)
if res.status_code != 200 or not check_cors(res):
    print(f"DELETE /auth/history/{thread_id} FAILED", res.status_code, res.text)
    passed = False
else:
    print(f"DELETE /auth/history/{{thread_id}} OK")

# 7. /auth/logout
res = requests.post(f"{BASE_URL}/auth/logout", headers=auth_headers)
if res.status_code != 200 or not check_cors(res):
    print("/auth/logout FAILED", res.status_code, res.text)
    passed = False
else:
    print("/auth/logout OK")

if not passed:
    sys.exit(1)
print("ALL TESTS PASSED!")

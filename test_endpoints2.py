import requests
import uuid
import time
import sys
import json

BASE_URL = 'http://127.0.0.1:8000'
ORIGIN = 'https://incident-iq-weld.vercel.app'
HEADERS = {'Origin': ORIGIN}

def check_cors(res):
    if res.headers.get('Access-Control-Allow-Origin') not in [ORIGIN, '*']:
        print(f"CORS ERROR on {res.url}: Expected {ORIGIN} or *, got {res.headers.get('Access-Control-Allow-Origin')}")
        return False
    return True

print("Running API tests...")
passed = True

uid = str(uuid.uuid4())
res = requests.post(f"{BASE_URL}/auth/register", json={"username": uid, "password": "pw"}, headers=HEADERS)
res = requests.post(f"{BASE_URL}/auth/login", json={"username": uid, "password": "pw"}, headers=HEADERS)
token = res.json().get('token')
auth_headers = HEADERS.copy()
auth_headers['Authorization'] = f"Bearer {token}"

# POST /incident/search
res = requests.post(f"{BASE_URL}/incident/search", json={"query": "test", "top_k": 2}, headers=auth_headers)
if res.status_code != 200 or not check_cors(res):
    print("/incident/search FAILED", res.status_code, res.text)
    passed = False
else:
    print("/incident/search OK")

# POST /incident/search_vectorless
res = requests.post(f"{BASE_URL}/incident/search_vectorless", json={"query": "test"}, headers=auth_headers)
if res.status_code != 200 or not check_cors(res):
    print("/incident/search_vectorless FAILED", res.status_code, res.text)
    passed = False
else:
    print("/incident/search_vectorless OK")

# POST /incident/ingest
res = requests.post(f"{BASE_URL}/incident/ingest", json={"file_path": "test.md", "source": "test_script"}, headers=auth_headers)
if res.status_code != 200 or not check_cors(res):
    print("/incident/ingest FAILED", res.status_code, res.text)
    passed = False
else:
    print("/incident/ingest OK")

if not passed:
    sys.exit(1)
print("ALL REMAINING TESTS PASSED!")

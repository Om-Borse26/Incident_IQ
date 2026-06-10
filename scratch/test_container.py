import httpx

try:
    resp = httpx.get("http://localhost:8000/health")
    print("Health Check:")
    print(resp.status_code, resp.text)
    print()
except Exception as e:
    print(f"Health check failed: {e}")

try:
    payload = {"query": "checkout-service: 500 errors right now"}
    resp = httpx.post("http://localhost:8000/incident/analyze", json=payload, timeout=30.0)
    print("Live Query:")
    print(resp.status_code, resp.json())
except Exception as e:
    print(f"Live Query failed: {e}")

import requests
import time

BASE_URL = "http://localhost:8000/incident/analyze"

queries = [
    # 1. Live diagnostics + Historical
    ("Live Check", "checkout service is throwing 500s right now", "started 20 minutes ago"),
    
    # 2. Deploy correlation
    ("Deploy Correlation", "api-gateway 502s since the last deploy", None),
    
    # 3. Security (Input Validation)
    ("Input Validation", "fetch logs for system32", None),
    
    # 4. Security (Log Poisoning)
    # The poisoned log is natively embedded in checkout-service logs.
    # The first query ("Live Check" on checkout service) will encounter it.
]

def run_tests():
    print("=========================================")
    print("RUNNING PHASE 4 MCP AGENT TESTS")
    print("=========================================\n")
    
    for name, query, context in queries:
        print(f"\n--- Test: {name} ---")
        print(f"Query: {query}")
        
        start = time.time()
        try:
            payload = {"query": query}
            if context:
                payload["context"] = context
                
            resp = requests.post(BASE_URL, json=payload)
            dur = time.time() - start
            
            if resp.status_code == 200:
                data = resp.json()
                print(f"Status: 200 OK ({dur:.2f}s)")
                print(f"Mode: {data.get('mode')}")
                print(f"Diagnostics Available: {data.get('diagnostics_available')}")
                print(f"Degraded: {data.get('degraded')}")
                print(f"Answer snippet: {data.get('answer', '')[:150]}...")
                print(f"Reasoning: {data.get('reasoning')}")
            else:
                print(f"Error {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"Connection failed: {e}")
            
if __name__ == "__main__":
    run_tests()

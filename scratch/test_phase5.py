import httpx
import asyncio
import json

async def run_tests():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("=========================================")
        print("TEST 1: BASIC & STREAMING (Live query)")
        print("=========================================")
        session_id = "test-session-1"
        payload1 = {"query": "checkout 500s right now", "session_id": session_id}
        resp1 = await client.post("http://127.0.0.1:8000/incident/analyze", json=payload1)
        data1 = resp1.json()
        print("Status:", resp1.status_code)
        print("Response Session ID:", data1.get("session_id"))
        print("Diagnostics Used:", data1.get("diagnostics_available"))
        print("Answer Snippet:", data1.get("answer", "")[:100], "...")
        
        print("\n=========================================")
        print("TEST 2: ROUTING (Historical query)")
        print("=========================================")
        payload2 = {"query": "what caused the 502s last week?", "session_id": "test-session-2"}
        resp2 = await client.post("http://127.0.0.1:8000/incident/analyze", json=payload2)
        data2 = resp2.json()
        print("Status:", resp2.status_code)
        print("Diagnostics Used (Should be False):", data2.get("diagnostics_available"))
        
        print("\n=========================================")
        print("TEST 3: FOLLOW-UP CONVERSATION (Memory)")
        print("=========================================")
        payload3 = {"query": "what was the root cause of that?", "session_id": session_id}
        resp3 = await client.post("http://127.0.0.1:8000/incident/analyze", json=payload3)
        data3 = resp3.json()
        print("Status:", resp3.status_code)
        print("Answer uses previous context:", data3.get("answer", "")[:100], "...")
        
        print("\n=========================================")
        print("TEST 4: HUMAN APPROVAL (Postmortem Interruption)")
        print("=========================================")
        # We need a query that causes needs_postmortem=True
        payload4 = {"query": "major outage on api-gateway right now. entire system is down.", "session_id": "test-session-4"}
        resp4 = await client.post("http://127.0.0.1:8000/incident/analyze", json=payload4)
        data4 = resp4.json()
        print("Status Code:", resp4.status_code)
        print("Graph Status:", data4.get("status"))
        print("Answer:", data4.get("answer"))
        
        if data4.get("status") == "pending_approval":
            print("\n--> Sending approval resume_action...")
            payload5 = {"query": "major outage on api-gateway right now. entire system is down.", "session_id": "test-session-4", "resume_action": "approve"}
            resp5 = await client.post("http://127.0.0.1:8000/incident/analyze", json=payload5)
            data5 = resp5.json()
            print("Status Code:", resp5.status_code)
            print("Graph Status:", data5.get("status"))
            print("Answer:", data5.get("answer", "")[:100], "...")

if __name__ == "__main__":
    asyncio.run(run_tests())

import sys
import httpx
import json
import asyncio

async def main():
    service = "checkout-service"
    description = "500 errors started 10 minutes ago"
    print(f"> /diagnose-incident {service} \"{description}\"\n")
    
    try:
        resp = httpx.post("http://127.0.0.1:8000/incident/analyze", 
                          json={"query": f"{service}: {description}"}, timeout=20)
        data = resp.json()
    except Exception as e:
        print(f"IncidentIQ API unreachable. Error: {e}")
        return
        
    mode = data.get("mode", "unknown")
    answer = data.get("answer", "")
    sources = data.get("sources", [])
    session_id = data.get("session_id", "SESSION-ID-1234")
    
    # Format output based on SKILL.md logic
    if mode == "known":
        print("✅ KNOWN INCIDENT — documented fix available")
    elif mode == "partial":
        print("⚠️ PARTIAL MATCH — suggestions based on similar incidents")
    else:
        print("❓ NEW INCIDENT — no historical match found")
        
    print("\n" + answer + "\n")
    
    print("--- SOURCES ---")
    for s in sources:
        if "INC-" in s or "runbook" in s.lower():
             print(f"📄 Source: {s} (documented)")
        else:
             print(f"📄 Source: {s}")
             
    if mode in ["partial", "unknown"]:
        print(f"\n💡 AI SUGGESTION (unverified): Based on the current diagnostics and partial context, investigate recent deployments or upstream dependencies.")
        print(f"\nRun /draft-postmortem {session_id} after resolution to capture learnings.")

if __name__ == "__main__":
    asyncio.run(main())

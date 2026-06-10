---
name: diagnose-incident
description: Analyze a production incident using IncidentIQ. Use when an engineer
  reports a service outage, error spike, or anomaly and needs a diagnosis.
  Triggers on: "diagnose X", "what's wrong with Y", "analyze incident Z".
context: fork
argument-hint: [service-name] [incident-description]
allowed-tools: Bash
---

## Goal
Call the IncidentIQ API to analyze an incident and format the response
for terminal readability, clearly distinguishing documented fixes from AI suggestions.

## Inputs
- $0: affected service name (required)
- $1: incident description (required, in quotes)

## Process
Step 1: Validate inputs — fail loudly if service or description is missing.
Step 2: Call the API:
  curl -s -X POST http://localhost:8000/incident/analyze \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"$0: $1\"}"
Step 3: Parse the JSON response and format output:
  - If mode=known:   "✅ KNOWN INCIDENT — documented fix available"
  - If mode=partial: "⚠️ PARTIAL MATCH — suggestions based on similar incidents"
  - If mode=unknown: "❓ NEW INCIDENT — no historical match found"
  For sources: list each source with "📄 Source: [title] (documented)"
  For suggestions: prefix each with "💡 AI SUGGESTION (unverified):"
Step 4: If mode=partial or mode=unknown, display:
  "Run /draft-postmortem [session-id] after resolution to capture learnings."

## Critical Rules
- NEVER present AI suggestions as documented facts
- NEVER call the API more than once per invocation (idempotency)
- If the API is unreachable, say so clearly — do not fabricate a diagnosis

## Edge Cases
- API returns degraded=true: display raw sources with "⚠️ AI synthesis unavailable"
- API timeout: "IncidentIQ API unreachable. Check: uvicorn app.main:app --port 8000"

## Self-Improvement
If this skill fails, fix the immediate issue AND patch this SKILL.md so the
same failure cannot recur.

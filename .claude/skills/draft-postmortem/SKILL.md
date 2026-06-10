---
name: draft-postmortem
description: Draft and save a postmortem for a resolved incident. MANUAL ONLY —
  never auto-invoke. Use when an engineer explicitly wants to document a resolved
  incident for future reference.
context: fork
argument-hint: [session-id]
disable-model-invocation: true
allowed-tools: Bash
---

## Goal
Draft a structured postmortem from an incident analysis session and save it
to the knowledge base ONLY after explicit human approval.

## Inputs
- $0: session-id from a previous /diagnose-incident run (required)

## Process
Step 1: Retrieve the incident analysis for this session:
  curl -s http://localhost:8000/incident/session/$0
Step 2: Draft the postmortem using this structure:
  # Postmortem: [Incident Title]
  **Date:** [date] | **Severity:** [mode-based] | **Duration:** TBD
  ## What Happened
  ## Root Cause
  ## Resolution Steps
  ## Action Items
  ## What We Learned
Step 3: MANDATORY DRY-RUN — display the draft and ask:
  "Review the postmortem above. Save to the knowledge base? (yes/no)"
  STOP and wait for input. Do NOT proceed without explicit 'yes'.
Step 4: On 'yes' ONLY: POST to /incident/postmortem to save.
  On 'no': discard draft, confirm: "Postmortem discarded."

## Critical Rules
- NEVER save without explicit 'yes' in this session
- NEVER auto-invoke this skill
- The dry-run step is MANDATORY — skipping it is never acceptable

# IncidentIQ - Architecture and System Overview
*This document contains all the technical details, system flows, and architectural components of the IncidentIQ project. You can feed this directly into NotebookLM to generate PPT slides, flow diagrams, and architectural charts.*

---

## 1. Project Overview
**IncidentIQ** is an autonomous AI Reliability Engineer (AI Ops Copilot). It assists Site Reliability Engineering (SRE) and DevOps teams in diagnosing and resolving production incidents. By bridging **Historical Memory (Vector/Tree RAG)** with **Current Reality (MCP Live Telemetry)**, it provides verified, real-time root cause analysis and suggested fixes.

---

## 2. Infrastructure & Databases (AWS ECS Deployment)

To optimize costs while maintaining persistence, we use embedded databases stored on an **AWS EC2 persistent disk**, mounted as a Docker Volume (`/data`) into our ECS containers.

### A. The Three Databases
1.  **ChromaDB**: Used exclusively for storing vector embeddings for our Vector RAG pipeline.
2.  **SQLite (`auth.sqlite`)**: A relational database storing user accounts, securely hashed passwords (SHA-256), active login sessions, and chat thread metadata.
3.  **SQLite (`checkpoints.sqlite`)**: A specialized database managed by **LangGraph's `AsyncSqliteSaver`** to store the complete conversational memory (chat history) of every thread.

### B. The Two ECS Services
Our AWS ECS Cluster runs two containers side-by-side using the EC2 Launch Type:
1.  **`incidentiq-service` (The Brains)**: The core Python backend running FastAPI, LangGraph, ChromaDB, and the LLM logic.
2.  **`caddy-service` (The Shield & Router)**: An ultra-fast web server acting as a Reverse Proxy. It generates free SSL certificates via Let's Encrypt (sslip.io) to satisfy Vercel's strict HTTPS requirements, and securely routes traffic to the Python backend.

---

## 3. Core Application Components

### A. The User Interface (Frontend)
*   **Responsive Chat UI**: A ChatGPT-like interface with a resizable sidebar containing chat history. Built with Vanilla HTML5, CSS3 (Glassmorphism), and JavaScript.
*   **Knowledge Ingestion Modal**: Allows users to manually upload `.md` or `.txt` postmortem files to the RAG database.
*   **Streaming Responses**: Receives chunks from the backend via Server-Sent Events (SSE) and renders Markdown with syntax highlighting in real-time.

### B. The API Gateway (FastAPI Backend)
*   **Custom Token-Based Authentication**: `/auth/login` and `/auth/register` endpoints. We generate a lightning-fast, highly secure random 64-character hex token and store it in the `sessions` table of `auth.sqlite` (Not JWT). All endpoints are protected by `Depends(verify_token)`.
*   **Incident Analyze (`/incident/analyze`)**: The core endpoint. Takes the user's query, triggers the LangGraph agent, and yields SSE chunks back to the client.
*   **Knowledge Ingestion (`/incident/upload`)**: Receives postmortem files.
*   **History (`/incident/history/{session_id}`)**: Retrieves chat history from the LangGraph `AsyncSqliteSaver` checkpointer.

### C. The MCP Diagnostics Server
*   Runs separately from the main FastAPI app using `mcp.server.fastmcp`.
*   Exposes tools that the LangGraph node can call via the `mcp.client`.
*   Simulates fetching live data (e.g., "checkout-service: 15.4% error rate, DB connection timeout logs").

---

## 4. The AI Architecture: Multi-Agent Flow

To ensure high accuracy, we use a **Multi-Agent pattern** powered by LangGraph. A single complex query calls the LLM up to 5 times in rapid succession.

### Phase 1: The AI Agent & Query Routing
1.  **Follow-up Classifier Node (Call #1)**: 
    *   Reads the chat history (injected by LangGraph from `checkpoints.sqlite`—limited to the last 6 turns to manage context windows). 
    *   Classifies the intent (`new_query`, `followup_rag`, or `followup_conv`).
    *   **Dynamic Temperature**: Extracts `user_mood`. If the user is "panicked" ("Everything is down!"), temperature is set to **0.1** for strict, technical accuracy. If "curious", temperature is set to **0.8** for creative analogies.
2.  **Intent Classifier Node (Call #2)**: 
    *   Classifies the query as `live` (ongoing incident), `historical` (past incident), or `chitchat`.
3.  **Diagnose Node (Call #3 - Only if Live)**: 
    *   Extracts the exact service name (e.g., `payment-service`) to pass to the MCP Server.

### Phase 2: Parallel Retrieval (The RAG Pipeline)
If an incident query is detected, the agent executes multiple tools in parallel:
1.  **Vector RAG (ChromaDB)**: Converts the query to embeddings (using `sentence-transformers/all-MiniLM-L6-v2`) to find semantically similar past postmortems.
2.  **Vectorless RAG (Tree Search)**: Uses an AST (Abstract Syntax Tree) parser and BM25 keyword matching to search raw Markdown files. This guarantees exact error codes (e.g., `ERR_CONN_REFUSED`) aren't lost by the embedding model, returning perfect markdown sections intact.
3.  **MCP Diagnostics (If Live)**: Triggers our custom Model Context Protocol (MCP) Server to pull real-time server telemetry.

### Phase 3: Reasoning & Generation
1.  **Extraction Node (Call #4)**: 
    *   Takes the massive dump of MCP live logs + Vector RAG context + Vectorless RAG context.
    *   Outputs strict JSON containing the Root Cause, Confidence Score, and Fixes.
    *   **Zero-Day Incidents**: If Vector RAG finds *no* past records, the LLM is instructed to rely entirely on the MCP Live Logs + its foundational training knowledge to suggest a fix.
2.  **Human-in-the-Loop (HITL)**: 
    *   If the Extraction Node detects a *brand-new major incident*, it sets `needs_postmortem = True`.
    *   LangGraph uses `interrupt()` to completely pause execution and ask the human SRE: *"Draft postmortem ready. Do you approve?"* before saving it.
3.  **Generation Node (Call #5)**: 
    *   Takes the extracted JSON and generates a beautifully formatted Markdown response based on the RAG data.
    *   **Fallback LLM Chain**: Utilizes Groq (Llama-3) for speed, falling back to Gemini if rate limits are hit.
    *   *Graceful Degradation*: If the LLM goes down entirely, it catches the error and serves raw RAG chunks and live metrics directly to the user.

### Phase 4: Background Ingestion (Scalability)
1.  User clicks "Upload Knowledge" in the UI and uploads a `.md` or `.txt` postmortem file.
2.  FastAPI receives it (`/incident/upload`), saves it, and returns "Success" instantly.
3.  The file is pushed to an **Amazon SQS** (Simple Queue Service) queue.
4.  A background worker polls SQS, uses a Groq LLM to check for duplicates, chunks the text using LangChain text splitters, creates embeddings, and saves them to ChromaDB. SQS buffering prevents server crashes even if 1,000 users upload simultaneously.

---

## 5. CI/CD Pipeline (Jenkinsfile Flow)

Our deployment is fully automated via Jenkins:
1.  **Checkout**: Jenkins pulls the latest code from GitHub via webhook.
2.  **Setup Virtual Environment**: Installs Python dependencies (`pip install -r requirements.txt`).
3.  **Testing**: Runs `pytest` to evaluate unit tests (e.g., async API endpoint testing, health checks).
4.  **Docker Build**: Builds the Docker images for the FastAPI app and the Caddy proxy.
5.  **ECR Push**: Authenticates with AWS ECR and pushes the built images.
6.  **Deploy to AWS ECS**: Uses AWS CLI to update the ECS Service with the new image tag.
7.  **Health Check Validation**: Runs a `curl` loop against the live `/health` endpoint to verify the new containers spun up successfully (Times out after 5 minutes if it fails).

---

## 6. Advanced Caching Strategies
We implemented caching at two completely different layers of the stack to optimize speed and cost:
1.  **LLM SQLite Cache (Application Layer)**: If a user asks the exact same question within an hour, our SQLite LLM Cache intercepts it and returns the answer instantly without calling Groq/Gemini, saving API costs and reducing latency to milliseconds.
2.  **Docker Layer Cache (Infrastructure Layer)**: Configured in Jenkins. By caching the `requirements.txt` layer, Jenkins skips re-downloading Python packages if no dependencies changed, dropping CI/CD deployment time from ~4 minutes to ~1 minute.

---

## 7. Open Source Integrations (The "Flex")
*This project was built with production-grade safety in mind, directly informed by our team's contributions to major open-source AI frameworks.*

**1. Data Safety (LlamaIndex PR #22195)**
*   *The Problem*: AI frameworks often silently swallow data extraction errors, returning empty data without alerting the system. (A bug we fixed in the official LlamaIndex repo).
*   *Our Solution*: In our `Extraction Node`, if the LLM hallucinates the JSON format, our system throws a hard `OutputParserException` (using LangChain's `with_structured_output`). We strictly propagate extraction errors so we never silently drop critical incident data.

**2. Multi-Agent Reliability (OpenAI Agents PR #3724)**
*   *The Problem*: When AI agents "hand off" tasks to one another, they often pass bad or unvalidated information, breaking the pipeline. (A bug we fixed in OpenAI's official Agents repo).
*   *Our Solution*: Our LangGraph architecture relies heavily on Agent handoffs (Classifier -> Diagnoser -> Extractor). To ensure reliability, we enforce **strict Pydantic validation schemas** (`QueryClassification`, `ServiceExtraction`, etc.) for every single LLM call. The handoff between our nodes is cryptographically tight, ensuring zero hallucinations between agent hops.

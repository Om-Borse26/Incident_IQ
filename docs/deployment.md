# Deployment Guide

## Current: Railway (free tier)

### Initial Setup
1. Push to GitHub: `git push origin main`
2. Sign up at [railway.app](https://railway.app) (free, GitHub login)
3. New Project → Deploy from GitHub repo → select `Incident_IQ`
4. Railway auto-detects the Dockerfile and builds

### Environment Variables
Add these in **Railway Dashboard → Settings → Variables**:

| Variable | Description | Example |
|---|---|---|
| `GROQ_API_KEY` | Groq LLM API key | `gsk_...` |
| `GEMINI_API_KEY` | Google Gemini API key | `AIza...` |
| `LANGCHAIN_API_KEY` | LangSmith tracing key | `lsv2_...` |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing | `true` |
| `LANGCHAIN_ENDPOINT` | LangSmith API endpoint | `https://api.smith.langchain.com` |
| `LANGCHAIN_PROJECT` | LangSmith project name | `incidentiq` |
| `LLM_PROVIDER` | Default LLM provider | `groq` |
| `DATA_DIR` | Persistent data mount point | `/data` |

### Persistent Volume
1. Go to **Settings → Volumes**
2. Create a volume and mount at `/data`
3. Size: 1GB (free tier)

### Networking
1. Go to **Settings → Networking**
2. Click **Generate Domain**
3. Your URL: `https://incidentiq-xxxx.railway.app`

### Testing
```bash
# Health check
curl https://YOUR-URL/health

# Live query
curl -X POST https://YOUR-URL/incident/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "checkout-service: HTTP 500 errors"}'
```

---

## Future: Google Cloud Run

When GCP billing is resolved, switching from Railway → Cloud Run requires:

1. Uncomment `google-cloud-storage` in `requirements.txt`
2. Implement `services/storage/gcs_sync.py` (stub already exists with interface)
3. Add `restore_snapshot()` call to `app/main.py` lifespan startup
4. Create a GCS bucket: `gsutil mb gs://incidentiq-storage`
5. Upload current data: `python -c "from services.storage.gcs_sync import upload_snapshot; upload_snapshot()"`
6. Set `DATA_DIR=/tmp` in Cloud Run env vars
7. Run `./deploy.sh`

**Zero app code changes required.** The `DATA_DIR` abstraction means all path
references automatically point to the right location on any platform.

---

## Environment Variables Reference

All secrets are injected at runtime. **Never bake them into the Docker image.**

- **Railway**: Set via the dashboard UI (Settings → Variables)
- **Cloud Run**: Set via Secret Manager + `--set-secrets` deploy flag
- **Local**: Set via `.env` file (gitignored)

The pattern is identical across all platforms. Only the UI/CLI for setting them differs.

## Architecture

```
LOCAL:                      RAILWAY:                    CLOUD RUN (future):
  docker-compose up           GitHub push → auto-deploy   docker push → gcloud deploy
  localhost:8000              railway.app subdomain       run.app subdomain
  .env file                   Railway env vars UI         Secret Manager
  ./chroma_db volume          /data volume (persistent)   /tmp + GCS snapshot
  ./tree_index volume         /data volume (persistent)   /tmp + GCS snapshot
  MCP subprocess              MCP subprocess              MCP subprocess
```

The app code is identical across all three. Only the deploy target changes.

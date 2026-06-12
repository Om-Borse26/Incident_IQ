# IncidentIQ

An AI-powered incident management and root-cause analysis service.

## Quick Start

```bash
# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate   # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Run the development server
uvicorn app.main:app --reload
```

## Health Check

```
GET /health
→ {"status": "ok", "service": "incidentiq"}
```

*Note: As of Phase 11, the ingestion pipeline is event-driven via Google Pub/Sub.*

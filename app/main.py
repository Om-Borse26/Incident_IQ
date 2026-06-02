from fastapi import FastAPI

app = FastAPI(title="IncidentIQ")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "incidentiq"}

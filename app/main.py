from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.llm.client import ask_llm, LLMError

app = FastAPI(title="IncidentIQ")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "incidentiq"}


@app.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest) -> AskResponse:
    """Send a question to the configured LLM and return its answer."""
    try:
        answer = ask_llm(prompt=body.question)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return AskResponse(answer=answer)

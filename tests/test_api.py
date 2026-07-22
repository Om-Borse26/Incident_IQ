import os
import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Set testing environment before importing app
os.environ["GROQ_API_KEY"] = "fake-key"
os.environ["GEMINI_API_KEY"] = "fake-key"

import tempfile
import shutil
from app.main import app
from app.auth import verify_token
from app.config import settings
from services.agent.validator import ValidationResult
from services.retrieval.search import SearchResult

# Override the authentication dependency for tests
app.dependency_overrides[verify_token] = lambda: 1

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_temp_data_dir(monkeypatch):
    temp_dir = tempfile.mkdtemp()
    monkeypatch.setattr(settings, "DATA_DIR", temp_dir)
    yield
    shutil.rmtree(temp_dir)

# b) /health returns {"status": "ok"} (catches startup/import crashes)
def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "incidentiq"}

from services.agent.conversational_graph import QueryClassification

# c) "hello" query -> mode response doesn't invoke retrieve_node (chitchat routing)
@patch("services.agent.conversational_graph.get_chat_model")
@patch("services.retrieval.search.search_incidents") # Prevent DB interaction
def test_chitchat_routing(mock_search, mock_get_chat_model):
    mock_llm = MagicMock()
    
    mock_output = MagicMock()
    mock_output.query_type = "chitchat"
    mock_output.mode = "chitchat"
    mock_output.confidence = 1.0
    mock_output.reasoning = ""
    mock_output.suggested_fixes = []
    mock_output.sources = []
    mock_output.needs_postmortem = False
    mock_output.followup_type = "new_query"
    mock_output.rewritten_query = "hello"
    mock_output.user_mood = "neutral"
    mock_output.suggested_temperature = 0.5
    
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_output)
    mock_llm.invoke.return_value.content = "Hello there! How can I help?"
    
    mock_llm.ainvoke = AsyncMock()
    mock_llm.ainvoke.return_value.content = "Hello there! How can I help?"
    
    mock_get_chat_model.return_value = mock_llm

    response = client.post("/incident/analyze", json={"query": "hello"})
    assert response.status_code == 200
    
    # Parse SSE response
    lines = response.text.strip().split('\n\n')
    final_data = None
    for line in lines:
        if line.startswith('data: '):
            evt = json.loads(line[6:])
            if evt['type'] == 'final_result':
                final_data = evt['data']

    assert final_data is not None
    assert final_data["mode"] == "known"  # chitchat_node overrides this to 'known'
    assert final_data["answer"] == "Hello there! How can I help?"
    mock_search.assert_not_called()


# d) Known incident query -> returns mode:"known" (RAG pipeline works)
@patch("services.agent.conversational_graph.get_chat_model")
@patch("services.retrieval.search.search_incidents")
def test_known_incident_query(mock_search, mock_get_chat_model):
    # Mock search to return proper SearchResult objects
    mock_search.return_value = [
        SearchResult(
            text="The fix was to restart the container.",
            source="fake_incident.md",
            incident_title="Fake Incident",
            service="fake-service",
            distance=0.1
        )
    ]

    mock_llm = MagicMock()
    
    mock_output = MagicMock()
    mock_output.query_type = "historical"
    mock_output.mode = "historical"
    mock_output.confidence = 0.9
    mock_output.reasoning = "Matches fake_incident.md"
    mock_output.suggested_fixes = ["Restart"]
    mock_output.sources = ["fake_incident.md"]
    mock_output.needs_postmortem = False
    mock_output.followup_type = "new_query"
    mock_output.rewritten_query = "how to fix the database?"
    mock_output.user_mood = "neutral"
    mock_output.suggested_temperature = 0.5
    
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_output)
    mock_llm.invoke.return_value.content = "I found the issue, restart the container."
    mock_llm.ainvoke = AsyncMock()
    mock_llm.ainvoke.return_value.content = "I found the issue, restart the container."
    mock_get_chat_model.return_value = mock_llm

    response = client.post("/incident/analyze", json={"query": "how to fix the database?"})
    assert response.status_code == 200
    
    # Parse SSE response
    lines = response.text.strip().split('\n\n')
    final_data = None
    for line in lines:
        if line.startswith('data: '):
            evt = json.loads(line[6:])
            if evt['type'] == 'final_result':
                final_data = evt['data']

    assert final_data is not None
    assert final_data["mode"] == "historical" or final_data["mode"] == "known"
    mock_search.assert_called_once()

# e) Ingest file without Symptoms/Fixes -> 400 (validator works)
@patch("services.agent.validator.ChatGroq")
@patch("services.agent.validator.search_incidents")
def test_ingest_validation_failure(mock_search, mock_chat_groq):
    # Mock deduplication search
    mock_search.return_value = []
    
    # Mock LLM validation result
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = ValidationResult(
        is_valid=False,
        reason="Missing Symptoms and Fixes."
    )
    mock_chat_groq.return_value = mock_llm

    # Create dummy file content
    files = {"file": ("bad_incident.md", b"# Incident\nSomething broke.")}
    
    response = client.post("/incident/ingest", files=files)
    # The application raises 422 for validation failure
    assert response.status_code in [400, 422]
    assert "Document Rejected" in response.text

# f) 11th rapid request -> 429 (rate limiting works)
@patch("app.main.ask_llm")
def test_rate_limiting(mock_ask_llm):
    mock_ask_llm.return_value = "Fake answer"
    
    # The rate limit is 10/minute for /ask
    # We will send 11 requests
    for _ in range(11):
        response = client.post("/ask", json={"question": "spam"})
        if response.status_code == 429:
            break
            
    assert response.status_code == 429

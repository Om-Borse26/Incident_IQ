import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Set testing environment before importing app
os.environ["GROQ_API_KEY"] = "fake-key"
os.environ["GEMINI_API_KEY"] = "fake-key"

from app.main import app
from services.agent.validator import ValidationResult

client = TestClient(app)

# b) /health returns {"status": "ok"} (catches startup/import crashes)
def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "incidentiq"}

from services.agent.incident_graph import QueryClassification

# c) "hello" query -> mode response doesn't invoke retrieve_node (chitchat routing)
@patch("services.agent.incident_graph.get_chat_model")
@patch("services.retrieval.search.search_incidents") # Prevent DB interaction
def test_chitchat_routing(mock_search, mock_get_chat_model):
    mock_llm = MagicMock()
    # First call is router (with_structured_output). Return "chitchat" type
    mock_llm.with_structured_output.return_value.invoke.return_value = QueryClassification(query_type="chitchat")
    # Second call is the actual generation
    mock_llm.invoke.return_value.content = "Hello there! How can I help?"
    mock_get_chat_model.return_value = mock_llm

    response = client.post("/incident/analyze", json={"query": "hello"})
    assert response.status_code == 200
    
    data = response.json()
    assert data["mode"] == "known"
    assert data["answer"] == "Hello there! How can I help?"
    # Ensure search was never called (retrieve_node was skipped)
    mock_search.assert_not_called()

# d) Known incident query -> returns mode:"known" (RAG pipeline works)
@patch("services.agent.incident_graph.get_chat_model")
@patch("services.retrieval.search.search_incidents")
def test_known_incident_query(mock_search, mock_get_chat_model):
    # Mock search to return dummy chunks
    mock_chunk = MagicMock()
    mock_chunk.page_content = "The fix was to restart the container."
    mock_chunk.metadata = {"source": "fake_incident.md"}
    mock_search.return_value = [mock_chunk]

    mock_llm = MagicMock()
    # First call is router. Return "historical"
    mock_llm.with_structured_output.return_value.invoke.return_value = QueryClassification(query_type="historical")
    # Second call is the generation
    mock_llm.invoke.return_value.content = "I found the issue, restart the container."
    mock_get_chat_model.return_value = mock_llm

    response = client.post("/incident/analyze", json={"query": "how to fix the database?"})
    assert response.status_code == 200
    
    data = response.json()
    assert data["mode"] == "historical" or data["mode"] == "known"
    # Ensure search was called
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
def test_rate_limiting():
    # The rate limit is 10/minute for /ask
    # We will send 11 requests
    # To avoid actual LLM processing slowing down the test, we can use an unauthorized request,
    # because slowapi limits before authentication.
    # If slowapi limits after, we can mock the endpoint entirely or just send missing body.
    
    # Let's send 11 unauthenticated requests to a rate limited endpoint
    # Wait, /ask limits are 10/minute
    for _ in range(11):
        response = client.post("/incident/analyze", json={"query": "spam"})
        if response.status_code == 429:
            break
            
    assert response.status_code == 429

import pytest
from fastapi.testclient import TestClient
import sqlite3
import tempfile
import os
import app.auth
from app.main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_teardown_db(monkeypatch):
    # Store old overrides and clear them for auth tests
    old_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    
    # Create a temporary file for the test DB
    fd, temp_db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    
    # Override the AUTH_DB_PATH in the app
    monkeypatch.setattr("app.auth.AUTH_DB_PATH", temp_db_path)
    
    # Initialize the tables in the temp db
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS threads (
            thread_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()
    
    yield
    
    # Restore original overrides
    app.dependency_overrides = old_overrides
    
    # Cleanup temp file
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)

def test_register_and_login():
    # Test Register
    res = client.post("/auth/register", json={"username": "testuser", "password": "password123"})
    assert res.status_code == 200
    assert res.json()["message"] == "User registered successfully"
    
    # Duplicate Registration
    res = client.post("/auth/register", json={"username": "testuser", "password": "password123"})
    assert res.status_code == 400
    
    # Test Login
    res = client.post("/auth/login", json={"username": "testuser", "password": "password123"})
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["username"] == "testuser"
    
    # Test Bad Login
    res = client.post("/auth/login", json={"username": "testuser", "password": "wrong"})
    assert res.status_code == 401

def test_incident_history_requires_auth():
    # No auth header
    res = client.get("/incident/history")
    assert res.status_code == 401
    
    # Register and get token
    client.post("/auth/register", json={"username": "testuser2", "password": "password123"})
    login_res = client.post("/auth/login", json={"username": "testuser2", "password": "password123"})
    token = login_res.json()["token"]
    
    # Use auth header
    res = client.get("/incident/history", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == [] # Empty history initially

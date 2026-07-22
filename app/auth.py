import sqlite3
import hashlib
import secrets
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["Auth"])

# Database initialization
data_dir = os.environ.get("DATA_DIR", ".")
AUTH_DB_PATH = os.path.join(data_dir, "auth.sqlite")

def get_db():
    conn = sqlite3.connect(AUTH_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
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
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS threads (
            thread_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.commit()
    conn.close()

# Initialize DB on load
init_db()

# Models
class AuthRequest(BaseModel):
    username: str
    password: str

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

@router.post("/register")
def register_user(req: AuthRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if user exists
    cursor.execute("SELECT id FROM users WHERE username = ?", (req.username,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Username already exists")
    
    cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                   (req.username, hash_password(req.password)))
    conn.commit()
    conn.close()
    return {"message": "User registered successfully"}

@router.post("/login")
def login_user(req: AuthRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM users WHERE username = ? AND password_hash = ?", 
                   (req.username, hash_password(req.password)))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Generate token
    token = secrets.token_hex(32)
    cursor.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user["id"]))
    conn.commit()
    conn.close()
    
    return {"token": token, "username": req.username}

@router.post("/logout")
def logout_user(authorization: str = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    return {"message": "Logged out successfully"}

def verify_token(authorization: str = Header(None)) -> int:
    """Dependency to verify token and return user_id"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    
    token = authorization.split(" ")[1]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
    session = cursor.fetchone()
    conn.close()
    
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
        
    return session["user_id"]

def save_thread(user_id: int, thread_id: str, title: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT thread_id FROM threads WHERE thread_id = ?", (thread_id,))
    if cursor.fetchone():
        cursor.execute("UPDATE threads SET updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?", (thread_id,))
    else:
        cursor.execute("INSERT INTO threads (thread_id, user_id, title) VALUES (?, ?, ?)", (thread_id, user_id, title))
    conn.commit()
    conn.close()

def get_user_threads(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT thread_id, title, updated_at FROM threads WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    threads = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return threads

@router.delete("/history/{thread_id}")
def delete_thread(thread_id: str, user_id: int = Depends(verify_token)):
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if user owns the thread
    cursor.execute("SELECT id FROM threads WHERE thread_id = ? AND user_id = ?", (thread_id, user_id))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=403, detail="Thread not found or access denied")
        
    cursor.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
    conn.commit()
    conn.close()
    
    # Cleanup checkpointer if possible
    try:
        import os
        from app.config import settings
        db_path = os.path.join(settings.DATA_DIR, "checkpoints.sqlite")
        if os.path.exists(db_path):
            chk_conn = sqlite3.connect(db_path, check_same_thread=False)
            chk_cursor = chk_conn.cursor()
            chk_cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            chk_cursor.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
            chk_conn.commit()
            chk_conn.close()
    except Exception as e:
        print(f"Error cleaning up checkpointer for {thread_id}: {e}")
        
    return {"message": "Thread deleted successfully"}

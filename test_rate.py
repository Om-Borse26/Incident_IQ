from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/test")
@limiter.limit("2/minute")
async def test_route(request: Request, response: Response):
    async def stream():
        yield b"hello"
    return StreamingResponse(stream())

client = TestClient(app)

print(client.get("/test").status_code)
print(client.get("/test").status_code)
print(client.get("/test").status_code)
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.concurrency import run_blocking_io
from app.core.observability import RequestCorrelationMiddleware

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.auth import router as auth_router
from app.api import upload, cabinet, search, analytics, export, admin, share
from app.api.graph import router as graph_router
from app.core.websocket import manager
from app.core.version import APP_VERSION, SERVICE_NAME
from app.core.config import settings
from app.core.security import decode_token, resolve_authenticated_user
from app.core.rate_limit import limiter
from app.core.readiness import collect_readiness

app = FastAPI(
    title="DocSort API",
    description="Backend for OCR processing, document intelligence, review, search, and records management.",
    # Keep public API metadata aligned with the application release version.
    # The project does not currently expose independently versioned /v1 routes.
    version=APP_VERSION,
)

# Rate limiting (slowapi): register the limiter and its 429 handler.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# A3: restrict CORS to an explicit allowlist from settings (was "*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(upload.router)
app.include_router(cabinet.router)
app.include_router(search.router)
app.include_router(analytics.router)
app.include_router(export.router)
app.include_router(admin.router)
app.include_router(share.router)
app.include_router(graph_router)


# ── Authenticated WebSocket channel (not the source of activity recency) ─────
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    # Keep bearer credentials out of the URL/query string, where proxies and
    # access logs commonly record them. Browser clients can send the JWT as the
    # second Sec-WebSocket-Protocol value: ["docsort.jwt", "<jwt>"]. Non-browser
    # clients may use a normal Authorization: Bearer header.
    auth_header = websocket.headers.get("authorization", "")
    token = None
    selected_subprotocol = None
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    else:
        protocols = [
            item.strip()
            for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
            if item.strip()
        ]
        if len(protocols) >= 2 and protocols[0] == "docsort.jwt":
            token = protocols[1]
            selected_subprotocol = "docsort.jwt"

    payload = decode_token(token)
    if not payload or str(payload.get("sub")) != str(user_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        live_user = await run_blocking_io(resolve_authenticated_user, payload)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if str(live_user.get("id")) != str(user_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    connected = await manager.connect(
        websocket, user_id, subprotocol=selected_subprotocol
    )
    if not connected:
        return

    try:
        while True:
            await websocket.receive_text()   # keep connection alive; ignore pings
    except WebSocketDisconnect:
        pass
    finally:
        # Exact-socket cleanup is required on disconnect, cancellation, and
        # unexpected receive failures so dead sockets cannot permanently
        # consume a user's bounded connection slots.
        manager.disconnect(user_id, websocket)


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/", tags=["health"])
async def health():
    """Process liveness only; does not contact external dependencies."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready", tags=["health"])
async def readiness():
    """Dependency-aware readiness for load balancers and orchestrators."""
    report = await collect_readiness()
    status_code = 200 if report["status"] == "ready" else 503
    return JSONResponse(
        status_code=status_code,
        content=report,
        headers={"Cache-Control": "no-store"},
    )


# Keep request correlation outside FastAPI's internal exception middleware so
# even framework-generated error responses receive the same X-Request-ID.
app = RequestCorrelationMiddleware(app)

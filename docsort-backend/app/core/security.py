from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.concurrency import run_blocking_io

from app.core.config import settings
from app.utils.logger import logger

# 🔐 Token extractor
oauth2_scheme = HTTPBearer()

# Keep last-activity writes bounded while still making 5-minute recency useful.
_ACTIVITY_TOUCH_INTERVAL = timedelta(minutes=2)


def decode_token(token: str) -> Optional[dict]:
    """Decode a JWT and return its payload, or None if invalid/expired.

    Used for auth on non-HTTP entry points (e.g. WebSocket handshakes) where the
    HTTPBearer dependency can't run.
    """
    if not token:
        return None
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.InvalidTokenError:
        return None


# ─────────────────────────────────────────────
# 🔑 PASSWORD HANDLING
# ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ─────────────────────────────────────────────
# 🔐 JWT TOKEN CREATION
# ─────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )

    to_encode.update({"exp": expire})

    return jwt.encode(
        to_encode,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


# ─────────────────────────────────────────────
# 🔐 CURRENT USER
# ─────────────────────────────────────────────

def resolve_authenticated_user(payload: dict) -> dict:
    """Resolve live authorization state for a valid JWT payload.

    The JWT proves the caller's identity, but mutable authorization state must
    come from the current ``users`` row. This makes bans, role changes, and
    department changes effective immediately instead of waiting for token
    expiry.
    """
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    from app.core.database import get_supabase_sync

    supabase = get_supabase_sync()
    db_user_res = (
        supabase.table("users")
        .select("id, email, name, designation, status, role, department_id, is_active, last_seen")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )

    if not db_user_res.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account no longer exists",
        )

    db_user = db_user_res.data[0]
    if db_user.get("is_active") is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active",
        )

    user_status = (db_user.get("status") or "").strip().lower()
    if user_status != "verified":
        detail = (
            "Account has been banned"
            if user_status == "banned"
            else "Account is not active"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )

    _touch_authenticated_activity(
        supabase,
        str(db_user.get("id") or user_id),
        db_user.get("last_seen"),
    )

    email = db_user.get("email") or payload.get("email") or ""
    db_name = db_user.get("name")
    display_name = db_name or (email.split("@")[0].title() if email else "User")

    return {
        "id": str(db_user.get("id") or user_id),
        "email": email,
        "role": db_user.get("role") or "user",
        "department_id": db_user.get("department_id"),
        "name": display_name,
        "designation": db_user.get("designation"),
    }


def _parse_activity_timestamp(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _touch_authenticated_activity(supabase, user_id: str, last_seen) -> None:
    """Best-effort, throttled update of the user's last authenticated activity."""
    now = datetime.now(timezone.utc)
    previous = _parse_activity_timestamp(last_seen)
    if previous is not None and now - previous < _ACTIVITY_TOUCH_INTERVAL:
        return

    try:
        (
            supabase.table("users")
            .update({"last_seen": now.isoformat()})
            .eq("id", user_id)
            .execute()
        )
    except Exception as exc:
        # Activity tracking must never turn a valid authenticated request into a failure.
        logger.debug("last_seen activity update failed error_type=%s", type(exc).__name__)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
) -> dict:
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    return await run_blocking_io(resolve_authenticated_user, payload)


# ─────────────────────────────────────────────
# 🔐 ADMIN CHECK
# ─────────────────────────────────────────────

async def get_current_admin(
    user: dict = Depends(get_current_user),
) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for this action.",
        )
    return user

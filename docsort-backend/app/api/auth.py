from fastapi import APIRouter, Depends, HTTPException, Request, status
from datetime import datetime, timezone

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)

from app.repositories.user_repository import (
    create_user,
    get_user_by_email,
)
from app.services.activity_service import activity_service
from app.core.database import get_supabase_sync
from app.core.concurrency import run_blocking_io
from app.core.rate_limit import limiter
from app.utils.logger import logger

from app.schemas.auth_schema import (
    SignupRequest,
    LoginRequest,
    TokenResponse,
    MessageResponse,
    CurrentUserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


_GENERIC_REGISTRATION_MESSAGE = (
    "Registration request received. Check with an administrator for approval status."
)


def _is_email_unique_conflict(exc: Exception) -> bool:
    """Recognize the PostgreSQL unique-email race without exposing it publicly."""
    text = str(exc).lower()
    return (
        "23505" in text
        and "email" in text
        and ("users_email_key" in text or "duplicate key" in text)
    )


def _record_login_activity(user: dict) -> None:
    """Best-effort synchronous login audit + activity timestamp update.

    The caller executes this helper in the shared worker pool so database waits do
    not occupy the FastAPI event loop. Keeping both writes in one helper preserves
    best-effort sequencing and failure isolation for login activity updates.
    """
    try:
        activity_service.log_login(
            user_id=user["id"],
            department_id=user.get("department_id"),
        )
        supabase = get_supabase_sync()
        (
            supabase.table("users")
            .update({"last_seen": datetime.now(timezone.utc).isoformat()})
            .eq("id", user["id"])
            .execute()
        )
    except Exception as exc:
        logger.debug(
            "login activity update failed error_type=%s",
            type(exc).__name__,
        )


def _resolve_signup_department_id(data: SignupRequest) -> str | None:
    """Resolve the human-facing department code to the stored department UUID.

    ``department_id`` is accepted as an optional stored UUID. Standard clients
    should send ``department_code`` and let the backend resolve the UUID.
    """
    supabase = get_supabase_sync()

    if data.department_code and data.department_code.strip():
        department_code = data.department_code.strip()
        result = (
            supabase.table("departments")
            .select("id, code")
            .execute()
        )
        matching_department = next(
            (
                row
                for row in result.data
                if str(row.get("code", "")).casefold() == department_code.casefold()
            ),
            None,
        )
        if not matching_department:
            raise HTTPException(status_code=400, detail="Invalid department code.")

        resolved_id = str(matching_department["id"])
        if data.department_id and str(data.department_id) != resolved_id:
            raise HTTPException(
                status_code=400,
                detail="Department code and department ID do not match.",
            )
        return resolved_id

    if data.department_id:
        result = (
            supabase.table("departments")
            .select("id")
            .eq("id", data.department_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=400, detail="Invalid department ID.")
        return str(result.data[0]["id"])

    return None


@router.get("/me", response_model=CurrentUserResponse)
async def current_user_profile(user: dict = Depends(get_current_user)):
    """Return the live authorization/profile state for session rehydration."""
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "role": user.get("role", "user"),
        "department_id": user.get("department_id"),
        "name": user.get("name"),
        "designation": user.get("designation"),
    }


# ─────────────────────────────────────────────
# 📝 SIGNUP
# ─────────────────────────────────────────────

@router.post(
    "/signup",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/hour")
async def signup(request: Request, data: SignupRequest):

    # Validate request-scoped department data before checking whether the email
    # already exists. That keeps invalid department handling independent of
    # account existence and avoids creating a secondary enumeration signal.
    department_id = await run_blocking_io(_resolve_signup_department_id, data)

    # The public response is intentionally identical for new and existing
    # emails. Password-cost work is also performed in both paths so the obvious
    # timing difference is reduced under this rate-limited endpoint.
    existing = await run_blocking_io(get_user_by_email, str(data.email))
    password_hash = await run_blocking_io(hash_password, data.password)

    if existing:
        return {"message": _GENERIC_REGISTRATION_MESSAGE}

    user_data = {
        "email": str(data.email),
        "password": password_hash,
        **({"name": data.name} if data.name else {}),
        **({"department_id": department_id} if department_id else {}),
        **({"designation": data.designation} if data.designation else {}),
        **({"employee_id": data.employee_id} if data.employee_id else {}),
    }

    try:
        await run_blocking_io(create_user, user_data)
    except RuntimeError as exc:
        # A concurrent signup can win after the lookup but before this insert.
        # Normalize that unique-email race to the same public response instead
        # of re-introducing enumeration through an HTTP 409/500 difference.
        if not _is_email_unique_conflict(exc):
            raise

    return {"message": _GENERIC_REGISTRATION_MESSAGE}


# ─────────────────────────────────────────────
# 🔐 LOGIN
# ─────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, data: LoginRequest):

    # 🔍 fetch user
    users = await run_blocking_io(get_user_by_email, str(data.email))

    if not users:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

    user = users[0]

    # 🔐 verify password
    if not await run_blocking_io(verify_password, data.password, user["password"]):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

    if user.get("is_active") is False:
        raise HTTPException(
            status_code=403,
            detail="Account is not active.",
        )

    # 🔍 user status handling
    user_status = (user.get("status") or "pending").strip().lower()

    if user_status == "banned":
        raise HTTPException(
            status_code=403,
            detail="Your account has been banned.",
        )

    if user_status == "pending":
        raise HTTPException(
            status_code=403,
            detail="Your account is pending administrator approval.",
        )

    if user_status != "verified":
        raise HTTPException(
            status_code=403,
            detail="Account not approved. Contact an administrator.",
        )

    # Create the access token from the current live user row.
    access_token = create_access_token({
        "sub": user["id"],
        "email": user["email"],
        "role": user.get("role", "user"),
        "department_id": user.get("department_id"),
    })

    # 📝 Best-effort login audit and last-activity update. The helper is
    # synchronous by design and runs in the shared worker pool.
    await run_blocking_io(_record_login_activity, user)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.get("role", "user"),
    }

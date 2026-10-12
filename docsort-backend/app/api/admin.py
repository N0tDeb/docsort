from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone

class BulkReviewPayload(BaseModel):
    document_ids: List[str]
    action: str  # "approve" | "reject"

from app.core.database import get_supabase
from app.core.concurrency import run_blocking_io
from app.core.security import get_current_admin
from app.core.document_access import get_writable_document, scope_document_write_query
from app.utils.logger import logger

router = APIRouter(prefix="/admin", tags=["admin"])


def _update_user_or_404(supabase, user_id: str, payload: dict):
    """Apply an account mutation only when the target user exists."""
    result = supabase.table("users").update(payload).eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(404, "User not found")
    return result.data[0]


# =========================================================
# 🟢 TAB 1: RECENT AUTHENTICATED ACTIVITY
# =========================================================
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _activity_status(last_seen, *, now: datetime) -> str:
    if not last_seen:
        return "inactive"
    try:
        seen = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
    except ValueError:
        return "inactive"
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    age = now - seen.astimezone(timezone.utc)
    if age <= timedelta(minutes=5):
        return "active"
    if age <= timedelta(minutes=30):
        return "recent"
    return "inactive"


@router.get("/presence")
async def get_presence(supabase=Depends(get_supabase), admin: dict = Depends(get_current_admin)):
    now = _utc_now()
    query = supabase.table("users").select("id, name, designation, last_seen, role")

    # This is activity recency, not socket/heartbeat presence. Account operations
    # are intentionally organization-wide for organization administrators.
    users = await run_blocking_io(query.execute)
    result = [
        {
            **user_item,
            "presence_status": _activity_status(user_item.get("last_seen"), now=now),
        }
        for user_item in (users.data or [])
    ]

    order = {"active": 0, "recent": 1, "inactive": 2}
    result.sort(key=lambda item: order[item["presence_status"]])
    return result


# =========================================================
# 📊 TAB 2: ACTIVITY FEED
# =========================================================
@router.get("/activity")
async def get_activity(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    supabase=Depends(get_supabase),
    admin: dict = Depends(get_current_admin)
):
    offset = (page - 1) * limit
    # Fetch raw activity logs (no joins - they fail silently with PostgREST)
    query = supabase.table("activity_log").select(
        "id, action, detail, created_at, user_id, document_id, department_id"
    )

    # Organization-admin account operations are intentionally organization-wide.
    activity_query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    result = await run_blocking_io(activity_query.execute)
    logs = result.data or []

    if not logs:
        return []

    # Enrich with user names via separate lookup
    user_ids = list({r["user_id"] for r in logs if r.get("user_id")})
    users_map = {}
    if user_ids:
        users_query = supabase.table("users").select("id, name, designation").in_("id", user_ids)
        users_result = await run_blocking_io(users_query.execute)
        users_map = {u["id"]: u for u in (users_result.data or [])}

    # Enrich with document filenames via separate lookup
    doc_ids = list({r["document_id"] for r in logs if r.get("document_id")})
    docs_map = {}
    if doc_ids:
        docs_query = supabase.table("documents").select("id, filename, doc_type").in_("id", doc_ids)
        docs_result = await run_blocking_io(docs_query.execute)
        docs_map = {d["id"]: d for d in (docs_result.data or [])}

    # Merge enrichment into each log row
    enriched = []
    for log in logs:
        u = users_map.get(log.get("user_id"), {})
        d = docs_map.get(log.get("document_id"), {})
        enriched.append({
            **log,
            "users": {"name": u.get("name", "Unknown"), "designation": u.get("designation", "")},
            "documents": {"filename": d.get("filename", ""), "doc_type": d.get("doc_type", "")} if d else None,
        })

    return enriched


# =========================================================
# 🚨 TAB 3: SECURITY ALERTS
# =========================================================
@router.get("/security")
async def get_security_alerts(supabase=Depends(get_supabase), admin: dict = Depends(get_current_admin)):
    # 🚨 Tampered documents
    tamper_query = supabase.table("documents").select(
        "id, filename, doc_type, tamper_flags, created_at, users(name)"
    ).eq("is_tampered", True)
    # Account administration is organization-wide, but document-content and
    # document-mutation surfaces remain department-scoped by design.
    tamper_query = scope_document_write_query(tamper_query, admin)
    tamper_query = tamper_query.order("created_at", desc=True).limit(10)
    tampered_docs = await run_blocking_io(tamper_query.execute)

    # ❌ Failed jobs — mirror the same document-processing scope.
    jobs_query = supabase.table("upload_jobs").select(
        "id, filename, error_message, created_at, users(name)"
    ).eq("status", "failed")
    if admin.get("department_id"):
        jobs_query = jobs_query.eq("department_id", admin["department_id"])
    else:
        jobs_query = jobs_query.eq("user_id", admin["id"])
    jobs_query = jobs_query.order("created_at", desc=True).limit(10)
    failed_jobs = await run_blocking_io(jobs_query.execute)

    # 🛌 Stale or suspicious accounts
    now = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(days=30)).isoformat()

    stale_query = supabase.table("users").select(
        "id, name, email, last_seen, status"
    ).lt("last_seen", stale_cutoff)
    stale_users = await run_blocking_io(stale_query.execute)

    return {
        "tampered_documents": tampered_docs.data or [],
        "failed_jobs": failed_jobs.data or [],
        "stale_accounts": stale_users.data or [],
        "summary": {
            "tamper_count": len(tampered_docs.data or []),
            "failed_count": len(failed_jobs.data or []),
            "stale_count": len(stale_users.data or []),
        },
    }


# =========================================================
# 👑 ADMIN ACTIONS
# =========================================================
@router.post("/resolve-tamper/{doc_id}")
async def resolve_tamper_flag(doc_id: str, supabase=Depends(get_supabase), admin: dict = Depends(get_current_admin)):
    document = await run_blocking_io(
        get_writable_document, supabase, doc_id, admin, "id, filename"
    )

    if not document:
        raise HTTPException(404, "Document not found")

    update_query = supabase.table("documents").update({
        "is_tampered": False,
        "tamper_flags": [],
        "review_status": "verified",
    }).eq("id", doc_id)
    updated = await run_blocking_io(
        scope_document_write_query(update_query, admin).execute
    )
    if not updated.data:
        raise HTTPException(404, "Document not found")

    return {"message": "Tamper flag cleared"}


@router.post("/bulk-review")
async def bulk_review(
    payload: BulkReviewPayload,
    supabase=Depends(get_supabase),
    admin: dict = Depends(get_current_admin)
):
    if not payload.document_ids:
        raise HTTPException(400, "No documents specified.")
    if payload.action not in {"approve", "reject"}:
        raise HTTPException(400, "Action must be 'approve' or 'reject'.")

    try:
        if payload.action == "approve":
            # Approving means completely trusting it — turning off all tamper flags natively
            # Additionally, we auto-classify the document now that it's validated
            from app.services.autosort_service import AutoSortService
            autosort_service = AutoSortService()

            docs_query = (
                supabase.table("documents")
                .select("id, user_id, department_id, doc_type, document_fields(*)")
                .in_("id", payload.document_ids)
            )
            docs_to_approve = await run_blocking_io(
                scope_document_write_query(docs_query, admin).execute
            )

            approved_count = 0
            for doc in (docs_to_approve.data or []):
                system_suggested_folder = None
                clean_fields = []
                for f in (doc.get("document_fields") or []):
                    if f.get("label") == "system_suggested_folder":
                        system_suggested_folder = f.get("value")
                    elif not f.get("label", "").startswith("system_"):
                        clean_fields.append(f)

                folder_id, _sort_confidence = await autosort_service.classify(
                    doc_type=doc.get("doc_type", ""),
                    fields=clean_fields,
                    department_id=doc.get("department_id"),
                    suggested_folder_name=system_suggested_folder,
                    supabase=supabase,
                )

                update_payload = {"is_tampered": False, "tamper_flags": [], "review_status": "verified"}
                if folder_id:
                    # Preserve the original automatic routing score; this
                    # approval is a human/admin action, not a new auto-sort.
                    update_payload["folder_id"] = folder_id

                update_query = supabase.table("documents").update(update_payload).eq("id", doc["id"])
                updated = await run_blocking_io(
                    scope_document_write_query(update_query, admin).execute
                )
                if updated.data:
                    approved_count += 1

            return {"message": f"Successfully approved and categorized {approved_count} documents."}

        elif payload.action == "reject":
            # Rejecting is still a document mutation and therefore uses the same
            # department/ownership boundary as the rest of the cabinet.
            delete_query = (
                supabase.table("documents")
                .delete()
                .in_("id", payload.document_ids)
            )
            res = await run_blocking_io(
                scope_document_write_query(delete_query, admin).execute
            )
            deleted_rows = res.data or []
            storage_paths = [row.get("storage_path") for row in deleted_rows if row.get("storage_path")]
            if storage_paths:
                try:
                    await run_blocking_io(
                        supabase.storage.from_("docsort").remove, storage_paths
                    )
                except Exception as exc:
                    # The database delete is authoritative; source-object cleanup
                    # is best effort so we never resurrect an invalid document.
                    logger.warning("Bulk review Storage cleanup failed error_type=%s", type(exc).__name__)
            count = len(deleted_rows)
            return {"message": f"Successfully rejected and removed {count} documents."}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Bulk review operation failed error_type=%s", type(exc).__name__)
        raise HTTPException(500, "Bulk operation failed.") from exc


@router.post("/ban-user/{user_id}")
async def ban_user(user_id: str, supabase=Depends(get_supabase), admin: dict = Depends(get_current_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "Cannot ban yourself")

    await run_blocking_io(
        _update_user_or_404, supabase, user_id, {"status": "banned"}
    )

    return {"message": "User banned"}


@router.post("/approve-user/{user_id}")
async def approve_user(user_id: str, supabase=Depends(get_supabase), admin: dict = Depends(get_current_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "Cannot approve yourself")

    await run_blocking_io(
        _update_user_or_404, supabase, user_id, {"status": "verified"}
    )

    return {"message": "User approved"}


@router.post("/promote-user/{user_id}")
async def promote_user(user_id: str, supabase=Depends(get_supabase), admin: dict = Depends(get_current_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "Cannot promote yourself")

    await run_blocking_io(
        _update_user_or_404, supabase, user_id, {"role": "admin"}
    )

    return {"message": "User promoted to organization admin"}


@router.get("/users")
async def list_users(
    status: Optional[str] = Query(default=None),
    supabase=Depends(get_supabase),
    admin: dict = Depends(get_current_admin),
):
    # Return only fields needed by the admin UI. Never expose stored password
    # hashes or future internal-only columns through a wildcard projection.
    query = supabase.table("users").select(
        "id, email, name, department_id, designation, employee_id, role, "
        "status, is_active, last_seen, created_at"
    )

    if status:
        query = query.eq("status", status)

    result = await run_blocking_io(query.execute)
    return result.data or []

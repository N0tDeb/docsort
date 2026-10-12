import asyncio

from fastapi import APIRouter, Depends
from datetime import datetime, timedelta, timezone

from app.core.database import get_supabase
from app.core.concurrency import run_blocking_io
from app.core.security import get_current_user, get_current_admin
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])
analytics_service = AnalyticsService()


# ✅ EMPTY fallback (safe response)
EMPTY = {
    "total_documents": 0,
    "uploaded_today": 0,
    "processed_count": 0,
    "failed_count": 0,
    "tamper_flagged_count": 0,
    "active_users_24h": 0,
    "active_users_today": 0,  # API alias; same 24h recency metric
    "doc_type_distribution": {},
    "daily_uploads": [],
    "top_uploaders": [],
    "folder_doc_counts": [],
    "avg_ocr_confidence": 0.0,
    "autosort_rate": 0.0,
}


def _empty_department_analytics() -> dict:
    """Return the empty-state contract with explicit seven-day chart slots."""
    return {
        **EMPTY,
        "daily_uploads": analytics_service.build_daily_uploads([]),
    }


# =========================================================
# 🟢 DEPARTMENT ANALYTICS
# =========================================================
@router.get("/department")
async def get_department_analytics(
    supabase=Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    dept_id = user.get("department_id")
    if not dept_id:
        # Personal user — scope everything to their own uploads
        docs_q = (
            supabase.table("documents")
            .select("id, doc_type, is_tampered, sort_confidence, ocr_confidence, created_at, folder_id, user_id")
            .eq("user_id", user["id"])
        )
        jobs_q = (
            supabase.table("upload_jobs")
            .select("status, created_at")
            .eq("user_id", user["id"])
        )
        docs, jobs = await asyncio.gather(
            run_blocking_io(docs_q.execute),
            run_blocking_io(jobs_q.execute),
        )

        if not docs.data:
            empty = _empty_department_analytics()
            empty["active_users_24h"] = 1
            empty["active_users_today"] = 1
            return {**empty, "cabinets_count": 0}

        res = analytics_service.compute_department(
            documents=docs.data,
            jobs=jobs.data or [],
            active_users=[{"id": user["id"]}],
        )
        # Count unique generated folders (+1 for 'My Uploads')
        unique_folders = len(res.get("doc_type_distribution", {}).keys())
        res["cabinets_count"] = unique_folders + 1
        return res

    # 1. Total exact count query
    total_query = supabase.table("documents").select("id", count="exact").eq("department_id", dept_id)
    if user.get("role") != "admin":
        total_query = total_query.or_(f"is_private.eq.false,user_id.eq.{user['id']}")

    # 2. Last 30 days Documents query (reduces payload vastly)
    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    docs_query = (
        supabase.table("documents")
        .select("id, doc_type, is_tampered, sort_confidence, ocr_confidence, created_at, folder_id, user_id")
        .eq("department_id", dept_id)
        .gte("created_at", thirty_days_ago)
    )
    if user.get("role") != "admin":
        docs_query = docs_query.or_(f"is_private.eq.false,user_id.eq.{user['id']}")

    # 3. Last 30 days Jobs query
    jobs_query = (
        supabase.table("upload_jobs")
        .select("status, created_at")
        .eq("department_id", dept_id)
        .gte("created_at", thirty_days_ago)
    )
    if user.get("role") != "admin":
        jobs_query = jobs_query.eq("user_id", user["id"])

    # 4. Active users query
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    active_users_query = (
        supabase.table("users")
        .select("id, name")
        .eq("department_id", dept_id)
        .gte("last_seen", cutoff_24h)
    )
    if user.get("role") != "admin":
        active_users_query = active_users_query.eq("id", user["id"])

    # 5. Cabinets count query
    folders_query = supabase.table("folders").select("id", count="exact").eq("department_id", dept_id)

    # Execute independent synchronous DB calls concurrently in Starlette's
    # worker pool so network waits do not occupy the FastAPI event-loop thread.
    total_res, docs, jobs, active_users, folders = await asyncio.gather(
        run_blocking_io(total_query.execute),
        run_blocking_io(docs_query.execute),
        run_blocking_io(jobs_query.execute),
        run_blocking_io(active_users_query.execute),
        run_blocking_io(folders_query.execute),
    )

    if not total_res.count:
        empty = _empty_department_analytics()
        active_count = len(active_users.data or [])
        empty["active_users_24h"] = active_count
        empty["active_users_today"] = active_count
        empty["cabinets_count"] = folders.count or 0
        return empty

    res = analytics_service.compute_department(
        documents=docs.data or [],
        jobs=jobs.data or [],
        active_users=active_users.data or [],
    )

    # Override computationally inferred totals with the DB exact count
    res["total_documents"] = total_res.count or 0
    res["cabinets_count"] = folders.count or 0
    return res


# =========================================================
# 🌍 GLOBAL ANALYTICS
# =========================================================
@router.get("/global")
async def get_global_analytics(
    supabase=Depends(get_supabase),
    user: dict = Depends(get_current_admin),
):
    now = datetime.now(timezone.utc)

    # 🗓️ Start of today (UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    # Build independent aggregate queries first, then execute all four blocking
    # HTTP calls in the shared worker pool instead of serially on the event loop.
    total_query = supabase.table("documents").select("id", count="exact")
    tampered_query = (
        supabase.table("documents")
        .select("id", count="exact")
        .eq("is_tampered", True)
    )
    today_uploads_query = (
        supabase.table("documents")
        .select("id", count="exact")
        .gte("created_at", today_start)
    )

    # 👥 Active users (last 24h)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    active_query = (
        supabase.table("users")
        .select("id", count="exact")
        .gte("last_seen", cutoff_24h)
    )

    total, tampered, today_uploads, active = await asyncio.gather(
        run_blocking_io(total_query.execute),
        run_blocking_io(tampered_query.execute),
        run_blocking_io(today_uploads_query.execute),
        run_blocking_io(active_query.execute),
    )
    total_count = total.count or 0
    tamper_count = tampered.count or 0
    today_count = today_uploads.count or 0
    active_count = active.count or 0

    return {
        "total_documents": total_count,
        "tamper_flagged_count": tamper_count,
        "uploaded_today": today_count,
        "active_users_24h": active_count,
        "active_users_today": active_count,  # API alias
    }

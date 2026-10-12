from app.core.config import settings
from app.core.database import get_supabase_sync
from datetime import datetime, timedelta, timezone


class AnalyticsService:

    # =========================================================
    # 📊 DIRECT DB STATS (OPTIONAL)
    # =========================================================
    def get_department_stats(self, department_id: str) -> dict:
        supabase = get_supabase_sync()

        docs = supabase.table("documents").select(
            "id, doc_type, created_at, is_tampered, ocr_confidence"
        ).eq("department_id", department_id).execute()

        all_docs = docs.data or []

        type_counts = {}
        tamper_count = 0
        confidence_total = 0.0

        for doc in all_docs:
            dtype = doc.get("doc_type") or "Unknown"
            type_counts[dtype] = type_counts.get(dtype, 0) + 1

            if doc.get("is_tampered"):
                tamper_count += 1

            confidence_total += float(doc.get("ocr_confidence") or 0)

        total = len(all_docs)
        avg_confidence = round(confidence_total / total, 2) if total else 0.0

        now = datetime.now(timezone.utc)

        # last 7 days
        week_ago = (now - timedelta(days=7)).isoformat()
        recent = (
            supabase.table("documents")
            .select("id", count="exact")
            .eq("department_id", department_id)
            .gte("created_at", week_ago)
            .execute()
        )

        # last 24h active users
        day_ago = (now - timedelta(hours=24)).isoformat()
        active = (
            supabase.table("users")
            .select("id", count="exact")
            .eq("department_id", department_id)
            .gte("last_seen", day_ago)
            .execute()
        )

        return {
            "total_documents": total,
            "tampered_count": tamper_count,
            "avg_ocr_confidence": avg_confidence,
            "uploads_last_7d": recent.count or 0,
            "active_users_24h": active.count or 0,
            "by_doc_type": type_counts,
        }

    # =========================================================
    # 📈 COMPUTE FROM PREFETCHED DATA
    # =========================================================
    def compute_department(self, documents: list, jobs: list, active_users: list) -> dict:

        from app.services.autosort_service import fallback_folder_for_doc_type

        total = len(documents)

        type_counts = {}
        tamper_count = 0
        confidence_total = 0.0
        auto_sorted = 0

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        uploaded_today = 0

        for doc in documents:
            raw_dtype = doc.get("doc_type") or "Unknown"

            # Present analytics using the same generic taxonomy as auto-sort.
            polished_category, _ = fallback_folder_for_doc_type(raw_dtype)
            type_counts[polished_category] = type_counts.get(polished_category, 0) + 1

            if doc.get("is_tampered"):
                tamper_count += 1

            confidence_total += float(doc.get("ocr_confidence") or 0)

            if float(doc.get("sort_confidence") or 0) >= settings.autosort_confidence_threshold:
                auto_sorted += 1

            if str(doc.get("created_at") or "") >= today_start:
                uploaded_today += 1

        failed_jobs = [j for j in jobs if j.get("status") == "failed"]
        processed_jobs = [j for j in jobs if j.get("status") == "done"]

        avg_confidence = round(confidence_total / total, 2) if total else 0.0
        autosort_rate = round(auto_sorted / total, 2) if total else 0.0

        # 📅 daily uploads (exactly 7 UTC calendar days, including today)
        daily_uploads = self.build_daily_uploads(documents, now=now)

        return {
            "total_documents": total,
            "uploaded_today": uploaded_today,
            "processed_count": len(processed_jobs),
            "failed_count": len(failed_jobs),
            "tamper_flagged_count": tamper_count,
            "active_users_24h": len(active_users),
            # API alias exposing the same 24-hour recency metric.
            "active_users_today": len(active_users),
            "doc_type_distribution": type_counts,
            "daily_uploads": daily_uploads,
            "top_uploaders": [],
            "folder_doc_counts": [],
            "avg_ocr_confidence": avg_confidence,
            "autosort_rate": autosort_rate,
        }

    @staticmethod
    def build_daily_uploads(documents: list, *, now: datetime | None = None) -> list[dict]:
        """Return the seven UTC calendar days ending today, including zero-count days."""
        current = now or datetime.now(timezone.utc)
        start_date = current.date() - timedelta(days=6)
        dates = [start_date + timedelta(days=offset) for offset in range(7)]
        counts = {day.isoformat(): 0 for day in dates}

        for doc in documents:
            raw_date = str(doc.get("created_at") or "")[:10]
            if raw_date in counts:
                counts[raw_date] += 1

        return [{"date": day, "count": counts[day]} for day in counts]

    # =========================================================
    # 🌍 GLOBAL STATS
    # =========================================================
    def get_global_stats(self) -> dict:
        supabase = get_supabase_sync()

        total_docs = supabase.table("documents").select("id", count="exact").execute()
        total_users = supabase.table("users").select("id", count="exact").execute()
        total_depts = supabase.table("departments").select("id", count="exact").execute()
        tampered = (
            supabase.table("documents")
            .select("id", count="exact")
            .eq("is_tampered", True)
            .execute()
        )

        return {
            "total_documents": total_docs.count or 0,
            "total_users": total_users.count or 0,
            "total_departments": total_depts.count or 0,
            "tampered_documents": tampered.count or 0,
        }


analytics_service = AnalyticsService()

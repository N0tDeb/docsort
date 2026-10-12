"""
activity_service.py — Centralized privacy-minimized activity logging for DocSort.

The audit row keeps the actor, department, action, document foreign key and
created-at timestamp needed for accountability. Human-readable details are
fixed by action so filenames, recipients, capability tokens, storage paths and
other free-form document content are not duplicated into the audit log.
"""
from datetime import datetime, timezone

from app.core.database import get_supabase_sync
from app.utils.logger import logger


_SAFE_DETAILS = {
    "upload": "Document uploaded",
    "view": "Document viewed",
    "share": "Public share link created",
    "share_revoke": "Public share link revoked",
    "login": "User logged in",
    "export": "Document exported",
    "move": "Document moved",
    "delete": "Document deleted",
}


class ActivityService:

    def log(
        self,
        user_id: str,
        department_id: str | None,
        action: str,
        document_id: str | None = None,
    ):
        """Insert one privacy-minimized audit row; failures stay best-effort."""
        detail = _SAFE_DETAILS.get(action, "Activity recorded")
        try:
            supabase = get_supabase_sync()
            supabase.table("activity_log").insert({
                "user_id":       user_id,
                "department_id": department_id,
                "action":        action,
                "detail":        detail,
                "document_id":   document_id,
                "metadata":      {},
                "created_at":    datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as exc:
            # Exception messages from DB/Storage/HTTP layers can contain URLs,
            # keys, identifiers or document metadata. Log only the exception
            # class; request_id supplies correlation for diagnostics.
            logger.warning(
                "[activity] write failed action=%s error_type=%s",
                action,
                type(exc).__name__,
            )

    def log_upload(self, user_id, department_id, doc_id):
        self.log(user_id, department_id, "upload", doc_id)

    def log_view(self, user_id, department_id, doc_id):
        self.log(user_id, department_id, "view", doc_id)

    def log_share(self, user_id, department_id, doc_id):
        self.log(user_id, department_id, "share", doc_id)

    def log_login(self, user_id, department_id):
        self.log(user_id, department_id, "login")

    def log_export(self, user_id, department_id, doc_id=None):
        self.log(user_id, department_id, "export", doc_id)


activity_service = ActivityService()


import hashlib
from app.core.database import get_supabase_sync


class TamperService:

    def compute_hash(self, file_bytes: bytes) -> str:
        """Return hex SHA-256 digest of raw file bytes."""
        return hashlib.sha256(file_bytes).hexdigest()

    def check_duplicate(
        self,
        file_hash: str,
        user_id: str,
        department_id: str | None = None,
    ) -> dict:
        """Check for an exact duplicate in the caller's own active scope.

        Duplicate reuse must never expose or reuse another user's document. The
        Flutter review flow describes an exact duplicate as the caller's
        "existing active document", so the hash lookup is intentionally scoped
        to the same owner and current department context.

        Returns dict:
          { "is_duplicate": bool, "duplicate_of": str|None, "filename": str|None }
        """
        supabase = get_supabase_sync()
        query = (
            supabase.table("documents")
            .select("id, filename, created_at, department_id")
            .eq("file_hash", file_hash)
            .eq("user_id", user_id)
        )

        if department_id:
            result = query.eq("department_id", department_id).limit(1).execute()
        else:
            # Keep the NULL department branch fully database-scoped. This also
            # makes the post-conflict lookup deterministic when a concurrent
            # unassigned upload wins the unique-index race.
            result = query.is_("department_id", "null").limit(1).execute()
        candidates = result.data or []

        if candidates:
            existing = candidates[0]
            return {
                "is_duplicate": True,
                "duplicate_of": existing["id"],
                "filename": existing["filename"],
            }
        return {"is_duplicate": False, "duplicate_of": None, "filename": None}

    def verify_integrity(self, doc_id: str, file_bytes: bytes) -> dict:
        """
        Re-hash file and compare against stored baseline.
        Returns { "is_tampered": bool, "stored_hash": str, "current_hash": str }
        """
        supabase = get_supabase_sync()
        doc = supabase.table("documents").select("file_hash").eq("id", doc_id).execute()
        if not doc.data:
            return {"is_tampered": False, "error": "Document not found"}

        stored_hash = doc.data[0]["file_hash"]
        current_hash = self.compute_hash(file_bytes)
        return {
            "is_tampered": stored_hash != current_hash,
            "stored_hash": stored_hash,
            "current_hash": current_hash,
        }

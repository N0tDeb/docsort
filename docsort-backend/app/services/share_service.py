"""Secure public document sharing.

The final-year product keeps sharing deliberately small:
- authenticated owners/administrators acting within their assigned department can create time-limited public links;
- optional link passwords are stored as PBKDF2 hashes, never plaintext;
- successful public access returns document metadata plus a short-lived Storage URL.

Reserved email-invite/access-control tables are not used by the runtime.
"""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.core.database import get_supabase_sync


_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 210_000
_PASSWORD_SALT_BYTES = 16
_SIGNED_URL_MAX_SECONDS = 15 * 60


class ShareService:
    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(_PASSWORD_SALT_BYTES)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            _PASSWORD_ITERATIONS,
        )
        return "$".join(
            [
                _PASSWORD_SCHEME,
                str(_PASSWORD_ITERATIONS),
                base64.urlsafe_b64encode(salt).decode("ascii"),
                base64.urlsafe_b64encode(digest).decode("ascii"),
            ]
        )

    @staticmethod
    def _verify_password(stored_value: str | None, supplied_password: str | None) -> bool:
        if not stored_value:
            return True
        if not supplied_password:
            return False

        try:
            scheme, iterations_raw, salt_raw, digest_raw = stored_value.split("$", 3)
            if scheme != _PASSWORD_SCHEME:
                # Fail closed for any non-PBKDF2 password representation.
                return False
            iterations = int(iterations_raw)
            salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
        except (ValueError, TypeError):
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            supplied_password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def create_public_link(
        self,
        document_id: str,
        created_by: str,
        expires_in_hours: int = 24,
        password: str | None = None,
    ) -> dict:
        supabase = get_supabase_sync()
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)

        row = supabase.table("shared_links").insert({
            "token": token,
            "document_id": document_id,
            "created_by": created_by,
            "expires_at": expires_at.isoformat(),
            # Keep the existing DB column for compatibility, but store only a
            # password hash in it. New links never persist plaintext passwords.
            "password": self._hash_password(password) if password else None,
            "is_active": True,
        }).execute()

        return {
            "share_id": row.data[0]["id"] if row.data else None,
            "token": token,
            "expires_at": expires_at.isoformat(),
        }

    def list_public_links(self, document_id: str) -> list[dict]:
        """Return management-safe link metadata for one document.

        Capability tokens and password hashes are intentionally excluded from
        the returned shape so authenticated management UIs cannot accidentally
        disclose reusable public credentials.
        """
        supabase = get_supabase_sync()
        result = (
            supabase.table("shared_links")
            .select("id, expires_at, password, is_active, created_at")
            .eq("document_id", document_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [
            {
                "share_id": row.get("id"),
                "expires_at": row.get("expires_at"),
                "is_active": bool(row.get("is_active")),
                "created_at": row.get("created_at"),
                "password_protected": bool(row.get("password")),
            }
            for row in result.data
            if row.get("id") and row.get("expires_at")
        ]

    def get_public_link_metadata(self, share_id: str) -> dict | None:
        """Fetch the minimum metadata needed to authorize management."""
        supabase = get_supabase_sync()
        result = (
            supabase.table("shared_links")
            .select("id, document_id, is_active")
            .eq("id", share_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        document_id = row.get("document_id")
        if not document_id:
            return None
        return {
            "share_id": row.get("id"),
            "document_id": document_id,
            "is_active": bool(row.get("is_active")),
        }

    def revoke_public_link(self, share_id: str) -> dict | None:
        """Idempotently deactivate a public capability link.

        PostgREST returns the updated representation.  An empty representation
        is treated as not found so callers never report a false-success revoke.
        """
        supabase = get_supabase_sync()
        result = (
            supabase.table("shared_links")
            .update({"is_active": False})
            .eq("id", share_id)
            .execute()
        )
        if not result.data:
            return None
        return {"share_id": share_id, "is_active": False}

    def get_public_link(self, token: str) -> dict | None:
        supabase = get_supabase_sync()
        result = (
            supabase.table("shared_links")
            .select("id, token, expires_at, password, is_active, documents(id, filename, doc_type, storage_path, file_hash)")
            .eq("token", token)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None

        link = result.data[0]
        try:
            expires_at = self._parse_timestamp(link["expires_at"])
        except (KeyError, TypeError, ValueError):
            return None
        if expires_at <= datetime.now(timezone.utc):
            return None
        return link

    def access_public_link(self, token: str, password: str | None = None) -> dict | None:
        link = self.get_public_link(token)
        if not link:
            return None
        if not self._verify_password(link.get("password"), password):
            return {"password_required": True}

        document = link.get("documents") or {}
        storage_path = document.get("storage_path")
        if not storage_path:
            return None

        expires_at = self._parse_timestamp(link["expires_at"])
        remaining_seconds = max(
            1,
            int((expires_at - datetime.now(timezone.utc)).total_seconds()),
        )
        signed_seconds = min(_SIGNED_URL_MAX_SECONDS, remaining_seconds)

        expected_hash = str(document.get("file_hash") or "").strip().lower()
        if len(expected_hash) != 64:
            return None
        try:
            int(expected_hash, 16)
        except ValueError:
            return None

        supabase = get_supabase_sync()
        bucket = supabase.storage.from_("docsort")
        try:
            current_hash = bucket.compute_sha256(storage_path).lower()
        except Exception:
            return None
        if not hmac.compare_digest(expected_hash, current_hash):
            return None

        signed = bucket.create_signed_url(
            storage_path,
            signed_seconds,
        )
        signed_url = signed.get("signedURL") or signed.get("signedUrl")
        if not signed_url:
            return None

        # Never expose the internal Storage path through the public API.
        public_document = {
            "id": document.get("id"),
            "filename": document.get("filename"),
            "doc_type": document.get("doc_type"),
        }
        return {
            "password_required": False,
            "document": public_document,
            "expires_at": link["expires_at"],
            "download_url": signed_url,
        }


share_service = ShareService()

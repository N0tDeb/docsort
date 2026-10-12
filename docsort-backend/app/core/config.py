import os
from typing import List, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_here     = os.path.dirname(os.path.abspath(__file__))
_app_dir  = os.path.dirname(_here)
_root     = os.path.dirname(_app_dir)
_env_file = os.path.join(_root, ".env")

# Placeholder value that must never be accepted as a real secret.
_INSECURE_JWT_DEFAULT = "change-me-in-production"


class Settings(BaseSettings):
    # ── Runtime environment ──────────────────────────────────────────────────
    # Local development may use a Supabase emulator over HTTP. Production must
    # explicitly opt in and is then required to use HTTPS for Supabase traffic.
    app_environment: Literal["development", "test", "production"] = "development"

    # ── Supabase ───────────────────────────────────────────────────────────────
    # Required runtime dependency: fail at startup instead of waiting for the
    # first database/storage request to discover that configuration is missing.
    supabase_url:         str
    supabase_service_key: str

    # ── JWT ───────────────────────────────────────────────────────────────────
    # A1: required — no working default. The server refuses to start if JWT_SECRET
    # is missing or uses the documented insecure placeholder value.
    jwt_secret:                  str
    jwt_algorithm:               str = "HS256"
    access_token_expire_minutes: int = 1440       # 24 hours

    # ── Google Gemini ────────────────────────────────────────────────────────
    # The API key is optional for startup; without it, OCR remains available and
    # AI enrichment degrades conservatively to Needs Review.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    # ── CORS ──────────────────────────────────────────────────────────────────
    # A3: comma-separated allowlist of browser origins (used by the Flutter web
    # build). Native mobile clients are unaffected by CORS. Override in .env.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ── DocSort ─────────────────────────────────────────────────────────────
    max_upload_bytes: int   = 20 * 1024 * 1024    # 20 MB
    max_pdf_pages: int      = 25
    max_image_pixels: int   = 40_000_000
    max_ai_pages: int       = 8
    max_ai_ocr_chars: int   = 20_000
    # Bound concurrent in-process upload processors/OCR jobs. Excess admitted
    # jobs remain queued until a slot is available.
    max_concurrent_upload_processing_jobs: int = 2
    # Bound simultaneously accepted WebSockets for one authenticated user on
    # this API process. This is a per-process resource limit, not a distributed
    # global cap across multiple replicas.
    max_websocket_connections_per_user: int = 3
    max_folder_page_size: int = 100
    max_personal_folder_scan: int = 500
    max_folder_export_documents: int = 250
    # Bound the total source payload copied into one folder ZIP.  A document
    # count ceiling alone is insufficient because 250 files near the upload
    # limit could otherwise consume several GiB of network/disk resources.
    max_folder_export_bytes: int = 100 * 1024 * 1024
    export_spool_memory_bytes: int = 8 * 1024 * 1024
    autosort_confidence_threshold: float = 0.75
    ocr_languages:    str   = "mar+hin+eng"

    # Default to "tesseract" (Linux PATH binary).
    # Override in .env on Windows: TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
    tesseract_cmd: str = "tesseract"

    model_config = SettingsConfigDict(env_file=_env_file, extra="ignore")


    @field_validator("app_environment", mode="before")
    @classmethod
    def _normalize_app_environment(cls, v: str) -> str:
        return str(v or "").strip().lower()

    @field_validator("supabase_url")
    @classmethod
    def _validate_supabase_url(cls, v: str) -> str:
        value = v.strip().rstrip("/")
        if not value or not value.startswith(("https://", "http://")):
            raise ValueError("SUPABASE_URL must be a valid http(s) project URL")
        return value

    @model_validator(mode="after")
    def _require_https_supabase_in_production(self):
        if self.app_environment == "production" and not self.supabase_url.startswith("https://"):
            raise ValueError(
                "SUPABASE_URL must use HTTPS when APP_ENVIRONMENT=production"
            )
        return self

    @field_validator("supabase_service_key")
    @classmethod
    def _validate_supabase_service_key(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("SUPABASE_SERVICE_KEY must be set")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _reject_insecure_jwt_secret(cls, v: str) -> str:
        value = (v or "").strip()
        if not value or value == _INSECURE_JWT_DEFAULT:
            raise ValueError(
                "JWT_SECRET must be set in .env to a strong, unique value "
                "and must not use the insecure placeholder."
            )
        if len(value.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET must be at least 32 bytes for HS256")
        return value

    @field_validator(
        "access_token_expire_minutes",
        "max_upload_bytes",
        "max_pdf_pages",
        "max_image_pixels",
        "max_ai_pages",
        "max_concurrent_upload_processing_jobs",
        "max_websocket_connections_per_user",
        "max_folder_page_size",
        "max_personal_folder_scan",
        "max_folder_export_documents",
        "max_folder_export_bytes",
        "export_spool_memory_bytes",
    )
    @classmethod
    def _require_positive_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Resource and pagination limits must be positive")
        return value

    @property
    def cors_origin_list(self) -> List[str]:
        """CORS origins as a clean list, split from the comma-separated env value."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
# A2: the service key must never be logged.

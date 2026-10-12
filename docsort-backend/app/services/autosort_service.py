
from app.core.database import get_supabase_sync
from app.core.config import settings
from app.core.concurrency import run_blocking_io
from app.utils.logger import logger

# Keywords that map document types to folder names (order matters: more specific first)
DOC_TYPE_TO_FOLDER = {
    # Finance
    "tax invoice":           "Finance",
    "gst invoice":           "Finance",
    "purchase order":        "Finance",
    "invoice":               "Finance",
    "receipt":               "Finance",
    "expense statement":     "Finance",
    "bill":                  "Finance",

    # Human Resources
    "employment contract":   "Human Resources",
    "offer letter":          "Human Resources",
    "experience letter":     "Human Resources",
    "resume":                "Human Resources",
    "curriculum vitae":      "Human Resources",
    "cv":                    "Human Resources",

    # Legal
    "non-disclosure agreement": "Legal",
    "nda":                   "Legal",
    "legal notice":          "Legal",
    "memorandum":            "Legal",
    "agreement":             "Legal",
    "contract":              "Legal",

    # Certificates / academic and professional records
    "degree certificate":    "Certificates",
    "marksheet":             "Certificates",
    "mark sheet":            "Certificates",
    "certificate":           "Certificates",

    # Applications
    "application form":      "Applications",
    "application":           "Applications",

    # Identity Documents
    "identity document":     "Identity Documents",
    "identity card":         "Identity Documents",
    "id card":               "Identity Documents",
    "passport":              "Identity Documents",
    "driving licence":       "Identity Documents",
    "driving license":       "Identity Documents",

    # Reports
    "audit report":          "Reports",
    "project report":        "Reports",
    "annual report":         "Reports",
    "report":                "Reports",
}


def fallback_folder_for_doc_type(doc_type: str) -> tuple[str, float]:
    """Return the generic fallback folder and confidence for a detected type."""
    doc_type_lower = (doc_type or "").lower().strip()
    for keyword, folder_name in DOC_TYPE_TO_FOLDER.items():
        if keyword in doc_type_lower:
            return folder_name, 0.90
    return "Needs Review", 0.50



class AutoSortService:

    async def classify(
        self,
        doc_type: str,
        fields: list,
        department_id: str,
        suggested_folder_name: str = None,
        suggestion_confidence: float | None = None,
        supabase=None,
    ) -> tuple[str | None, float]:
        """Return ``(folder_id, confidence_score)`` for document filing.

        An AI-suggested folder is only treated as high-confidence when the model
        supplied a valid confidence value. Missing/invalid confidence falls back
        to the deterministic generic document-type mapping rather than inventing
        a 0.95 score.
        """
        if not department_id:
            return None, 0.0

        if supabase is None:
            supabase = get_supabase_sync()

        # STEP 1: Respect an explicit AI review decision, and use an AI folder
        # suggestion only with evidence-backed confidence. Never manufacture a
        # high score merely because a folder string exists.
        if suggested_folder_name:
            suggested = suggested_folder_name.strip()
            try:
                confidence = float(suggestion_confidence)
            except (TypeError, ValueError):
                confidence = None
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))

            if suggested.lower() == "needs review":
                folder_id = await self._get_or_create_folder(
                    department_id, "Needs Review", supabase
                )
                return folder_id, confidence if confidence is not None else 0.0

            if confidence is not None:
                target_folder = (
                    suggested.title()
                    if confidence >= settings.autosort_confidence_threshold
                    else "Needs Review"
                )
                folder_id = await self._get_or_create_folder(
                    department_id, target_folder, supabase
                )
                return folder_id, confidence

        # STEP 2: Generic keyword fallback is for callers that do not have an AI
        # folder decision (for example, re-filing a manually corrected type).
        matched_folder_name, confidence = fallback_folder_for_doc_type(doc_type)

        folder_id = await self._get_or_create_folder(
            department_id, matched_folder_name, supabase
        )
        return folder_id, confidence

    async def _get_or_create_folder(
        self, department_id: str, folder_name: str, supabase
    ) -> str | None:
        try:
            existing_query = (
                supabase.table("folders")
                .select("id")
                .eq("department_id", department_id)
                .eq("name", folder_name)
            )
            existing = await run_blocking_io(existing_query.execute)
            if existing.data:
                return existing.data[0]["id"]

            try:
                created_query = supabase.table("folders").insert({
                    "department_id": department_id,
                    "name":          folder_name,
                    "is_system":     True,
                })
                created = await run_blocking_io(created_query.execute)
                return created.data[0]["id"] if created.data else None
            except RuntimeError as exc:
                # PostgreSQL is the final arbiter under concurrency. If another
                # worker created the same system folder after our lookup, read
                # that winning row instead of treating a normal race as a
                # classification failure. Unrelated DB errors continue through
                # the service's existing soft-failure path below.
                if "uq_system_folders_department_name" not in str(exc):
                    raise
                winner_query = (
                    supabase.table("folders")
                    .select("id")
                    .eq("department_id", department_id)
                    .eq("name", folder_name)
                    .eq("is_system", True)
                    .limit(1)
                )
                winner = await run_blocking_io(winner_query.execute)
                return winner.data[0]["id"] if winner.data else None
        except Exception as e:
            logger.error("[autosort] Folder lookup failed error_type=%s", type(e).__name__)
            return None

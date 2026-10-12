from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from typing import Optional, Annotated, List

from anyio import CapacityLimiter

from app.core.database import get_supabase, get_supabase_sync
from app.core.config import settings
from app.core.concurrency import run_blocking_io
from app.core.document_access import get_readable_document
from app.core.security import get_current_user
from app.core.rate_limit import limiter
from app.utils.logger import logger
from app.utils.file_safety import media_type_for_filename, validate_document_structure, validate_upload
from app.schemas.upload_schema import UploadJobResponse

from app.services.ocr_service import OCRService
from app.services.tamper_service import TamperService
from app.services.autosort_service import AutoSortService
from app.services.activity_service import activity_service
from app.services.relationship_service import process_relationships

router = APIRouter(prefix="/upload", tags=["upload"])

ocr_service      = OCRService()
tamper_service   = TamperService()
autosort_service = AutoSortService()

_DUPLICATE_DOCUMENT_CONSTRAINTS = (
    "uq_documents_owner_department_hash",
    "uq_documents_owner_unassigned_hash",
)


def _is_duplicate_document_conflict(exc: Exception) -> bool:
    """Return True only for the DB invariants that arbitrate exact duplicates."""
    message = str(exc)
    return any(name in message for name in _DUPLICATE_DOCUMENT_CONSTRAINTS)


def _validate_upload_payload(filename: str | None, file_bytes: bytes) -> tuple[str, str]:
    """Run parser-backed upload validation as one synchronous worker operation."""
    safe_filename, media_type = validate_upload(filename, file_bytes)
    validate_document_structure(
        safe_filename,
        file_bytes,
        max_pdf_pages=settings.max_pdf_pages,
        max_image_pixels=settings.max_image_pixels,
    )
    return safe_filename, media_type


# ── Step progress helper ───────────────────────────────────────────────────────
_TOTAL_STEPS = 5

def _update_step(supabase, job_id: str, step: int):
    """Store real processing step in the DB so the status endpoint reflects it."""
    supabase.table("upload_jobs").update({
        "step":         step,
        "progress_pct": round(step / _TOTAL_STEPS, 2),
    }).eq("id", job_id).execute()


# ── Background processing ──────────────────────────────────────────────────────
import asyncio
import time

_upload_processing_limiter = CapacityLimiter(
    settings.max_concurrent_upload_processing_jobs
)


def _process_document_worker(
    job_id:        str,
    user_id:       str,
    department_id: str | None,
    file_bytes:    bytes,
    filename:      str,
    language_hint: str,
    doc_type_hint: str,
):
    """Run one admitted processor inside a dedicated worker-pool slot."""
    asyncio.run(_process_document_async(
        job_id, user_id, department_id, file_bytes, filename, language_hint, doc_type_hint
    ))


async def _process_document(
    job_id:        str,
    user_id:       str,
    department_id: str | None,
    file_bytes:    bytes,
    filename:      str,
    language_hint: str,
    doc_type_hint: str,
):
    """Apply process-level backpressure before consuming a worker thread.

    Upload admission persists the job as ``queued``. Excess background tasks
    await this limiter on the application event loop without occupying a worker
    thread. Only a bounded number are dispatched into the synchronous
    processing worker, where the nested async OCR/AutoSort pipeline and
    synchronous Supabase/Storage calls retain their established sequencing.
    """
    async with _upload_processing_limiter:
        await run_blocking_io(
            _process_document_worker,
            job_id,
            user_id,
            department_id,
            file_bytes,
            filename,
            language_hint,
            doc_type_hint,
        )


def _cleanup_failed_processing(supabase, job_id: str, storage_path: str) -> bool:
    """Best-effort rollback for a source file that never became a durable document.

    Delete any partially-created document row before removing Storage. If the
    database cleanup fails, keep the source object so an existing document row
    can never be left pointing at a file we deliberately removed.
    """
    try:
        (
            supabase.table("documents")
            .delete()
            .eq("job_id", job_id)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to roll back partial document error_type=%s", type(exc).__name__)
        return False

    try:
        supabase.storage.from_("docsort").remove([storage_path])
        return True
    except Exception as exc:
        logger.warning("Failed to remove orphan source file error_type=%s", type(exc).__name__)
        return False


async def _process_document_async(
    job_id:        str,
    user_id:       str,
    department_id: str | None,
    file_bytes:    bytes,
    filename:      str,
    language_hint: str,
    doc_type_hint: str,
):
    supabase = get_supabase_sync()
    started_at = time.perf_counter()
    storage_path = None
    storage_uploaded = False
    document_persisted = False
    progress_details = {}

    try:
        supabase.table("upload_jobs").update({
            "status": "processing", "step": 0, "progress_pct": 0.0
        }).eq("id", job_id).execute()

        # Step 1 — Hash + duplicate check
        _update_step(supabase, job_id, 1)
        file_hash = tamper_service.compute_hash(file_bytes)
        dup_check = tamper_service.check_duplicate(file_hash, user_id, department_id)

        # Exact duplicates reuse the existing durable document. Short-circuit
        # before Storage/OCR so a duplicate does not create an orphan object or
        # incur unnecessary OCR/AI work.
        if dup_check["is_duplicate"]:
            existing_doc_id = dup_check["duplicate_of"]
            supabase.table("upload_jobs").update({
                "status":        "done",
                "document_id":   existing_doc_id,
                "step":          5,
                "progress_pct":  1.0,
                "error_message": f"Duplicate of existing document ID: {existing_doc_id}",
                "progress": {
                    "duplicate_reused": True,
                    "processing_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                },
            }).eq("id", job_id).execute()
            logger.info("Duplicate detected; reused existing document")
            return

        # Step 2 — Storage upload. The source file is the durable record behind
        # every persisted document, so processing must stop if it cannot be
        # stored. A document must never be marked done with a dead storage_path.
        _update_step(supabase, job_id, 2)
        storage_scope = str(department_id) if department_id else f"users/{user_id}"
        storage_path = f"documents/{storage_scope}/{job_id}/{filename}"
        try:
            supabase.storage.from_("docsort").upload(
                storage_path,
                file_bytes,
                options={"content-type": media_type_for_filename(filename)},
            )
            storage_uploaded = True
        except Exception as exc:
            logger.error("Source file storage upload failed error_type=%s", type(exc).__name__)
            raise RuntimeError("Source file storage upload failed; processing aborted") from exc

        # Step 3 — OCR / AI extraction
        _update_step(supabase, job_id, 3)
        extracted = await ocr_service.process_document(
            file_bytes=file_bytes,
            filename=filename,
            language_hint=language_hint,
            doc_type_hint=doc_type_hint,
        )

        # Step 4 — Tamper detection
        _update_step(supabase, job_id, 4)
        tamper_flags = extracted.get("tamper_flags", [])

        is_tampered = len(tamper_flags) > 0

        # Step 5 — Auto-sort into the correct cabinet folder.
        # High-confidence documents are filed automatically; anything below the
        # configured threshold is routed to a "Needs Review" folder instead.
        _update_step(supabase, job_id, 5)
        suggested_folder = extracted.get("suggested_folder", "Needs Review")
        folder_id, sort_confidence = await autosort_service.classify(
            doc_type=extracted.get("doc_type", ""),
            fields=extracted.get("fields", []),
            department_id=department_id,
            suggested_folder_name=suggested_folder,
            suggestion_confidence=extracted.get("classification_confidence"),
            supabase=supabase,
        )

        # Safety net: if the classifier isn't confident enough, hold the document
        # in a review folder rather than auto-filing it somewhere wrong.
        if sort_confidence < settings.autosort_confidence_threshold:
            review_folder_id = await autosort_service._get_or_create_folder(
                department_id, "Needs Review", supabase
            )
            if review_folder_id:
                folder_id = review_folder_id

        # Persist document
        doc_data = {
            "job_id":          job_id,
            "user_id":         user_id,
            "folder_id":       folder_id,
            "filename":        filename,
            "storage_path":    storage_path,
            "doc_type":        extracted.get("doc_type"),
            "language":        extracted.get("language"),
            "raw_text":        extracted.get("raw_text"),
            "ocr_confidence":  extracted.get("ocr_confidence"),
            "sort_confidence": sort_confidence,
            "review_status":   "needs_review",
            "file_hash":       file_hash,
            "tamper_flags":    tamper_flags,
            "is_tampered":     is_tampered,
        }
        if department_id:
            doc_data["department_id"] = department_id

        try:
            doc_resp = supabase.table("documents").insert(doc_data).execute()
            doc_id = doc_resp.data[0]["id"]
        except RuntimeError as exc:
            if not _is_duplicate_document_conflict(exc):
                raise

            # The custom HTTP adapter can retry after a read timeout. Before
            # treating a unique conflict as a competing job, check whether this
            # same job's first insert actually committed and only its response
            # was lost. In that case continue normally with the committed row.
            committed = (
                supabase.table("documents")
                .select("id")
                .eq("job_id", job_id)
                .limit(1)
                .execute()
            )
            if committed.data:
                doc_id = committed.data[0]["id"]
            else:
                # Another concurrent job with the same owner/scope/hash committed
                # first. Re-read the database winner and converge this job on that
                # durable document instead of persisting a second copy.
                winner = tamper_service.check_duplicate(file_hash, user_id, department_id)
                if not winner["is_duplicate"]:
                    # A named uniqueness conflict without a visible winner indicates
                    # an unexpected database state; fail closed rather than guessing.
                    raise

                existing_doc_id = winner["duplicate_of"]
                if storage_uploaded and storage_path:
                    _cleanup_failed_processing(supabase, job_id, storage_path)

                supabase.table("upload_jobs").update({
                    "status":        "done",
                    "document_id":   existing_doc_id,
                    "step":          5,
                    "progress_pct":  1.0,
                    "error_message": f"Duplicate of existing document ID: {existing_doc_id}",
                    "progress": {
                        "duplicate_reused": True,
                        "processing_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                    },
                }).eq("id", job_id).execute()
                logger.info("Concurrent duplicate detected; reused existing document")
                return

        # Bulk-insert extracted fields
        fields_to_insert = [
            {
                "document_id": doc_id,
                "label":       field.get("label"),
                "value":       field.get("value"),
                "confidence":  field.get("confidence"),
            }
            for field in extracted.get("fields", [])
        ]
        if fields_to_insert:
            supabase.table("document_fields").insert(fields_to_insert).execute()

        # From this point on the source file has a durable document record and
        # its extracted fields (if any). Later non-essential failures must not
        # delete that successfully persisted record/source.
        document_persisted = True

        # STEP 8.5 — Experimental People Map: link supported person-centric documents
        try:
            rel_result = await process_relationships(
                db=supabase,
                document_id=str(doc_id),
                dept_id=str(department_id) if department_id else None,
                doc_type=extracted.get("doc_type", ""),
                extracted_fields=extracted.get("fields", [])
            )
            logger.info(f"People map: linked={rel_result['people_linked']} edges={rel_result['edges_created']} potential_match={rel_result['duplicate_found']}")

            # Keep optional People Map details for the final upload-job progress
            # snapshot. The same JSON object also records real processing latency
            # for the academic evaluation framework.
            progress_details.update({
                "people_linked": rel_result["people_linked"],
                "citizens_created": rel_result["citizens_created"],  # API progress field
                "edges_created": rel_result["edges_created"],
                "duplicate_found": rel_result["duplicate_found"],
            })
        except Exception as e:
            logger.warning("Relationship processing failed (non-fatal) error_type=%s", type(e).__name__)

        activity_service.log_upload(user_id, department_id, doc_id)

        # Mark done
        progress_details["processing_ms"] = round(
            (time.perf_counter() - started_at) * 1000.0, 2
        )
        supabase.table("upload_jobs").update({
            "status":       "done",
            "document_id":  doc_id,
            "step":         5,
            "progress_pct": 1.0,
            "progress":     progress_details,
        }).eq("id", job_id).execute()

    except Exception as exc:
        # Storage may already contain the source even though processing failed
        # before a complete document was persisted. Roll back that partial
        # state. Database cleanup is deliberately attempted before Storage
        # removal so we never create a document row with a dead storage_path.
        if storage_uploaded and storage_path and not document_persisted:
            _cleanup_failed_processing(supabase, job_id, storage_path)

        progress_details["processing_ms"] = round(
            (time.perf_counter() - started_at) * 1000.0, 2
        )
        supabase.table("upload_jobs").update({
            "status":        "failed",
            "error_message": "Document processing failed. Please retry.",
            "progress":      progress_details,
        }).eq("id", job_id).execute()
        logger.error("Document processing job failed error_type=%s", type(exc).__name__)


# ── Upload endpoint ────────────────────────────────────────────────────────────
@router.post("", response_model=UploadJobResponse, status_code=202)
@limiter.limit("20/hour")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file:             Annotated[UploadFile, File(...)],
    language_hint:    Optional[str] = Form(default=None),
    doc_type_hint:    Optional[str] = Form(default=""),
    supabase=Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Empty file")
    if len(file_bytes) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(413, f"File exceeds the {limit_mb} MB upload limit.")

    try:
        safe_filename, _media_type = await run_blocking_io(
            _validate_upload_payload, file.filename, file_bytes
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    department_id = user.get("department_id")

    upload_job_data = {
        "user_id":       user["id"],
        "status":        "queued",
        "filename":      safe_filename,
        "step":          0,
        "progress_pct":  0.0,
    }
    if department_id:
        upload_job_data["department_id"] = department_id

    job_query = supabase.table("upload_jobs").insert(upload_job_data)
    result = await run_blocking_io(job_query.execute)

    job_id = result.data[0]["id"]

    background_tasks.add_task(
        _process_document,
        job_id,
        user["id"],
        department_id,
        file_bytes,
        safe_filename,
        language_hint or settings.ocr_languages,
        doc_type_hint,
    )

    return result.data[0]


# ── Active Jobs endpoint ───────────────────────────────────────────────────────
@router.get("/jobs/active", response_model=List[UploadJobResponse])
async def get_active_jobs(
    supabase=Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    query = (
        supabase.table("upload_jobs")
        .select("id,status,filename,step,progress_pct,progress,error_message,document_id,created_at")
        .eq("user_id", user["id"])
        .in_("status", ["queued", "processing"])
        .order("created_at", desc=True)
    )
    result = await run_blocking_io(query.execute)
    return result.data or []


# ── Status endpoint ────────────────────────────────────────────────────────────
@router.get("/status/{job_id}")
async def get_status(
    job_id: str,
    supabase=Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    query = (
        supabase.table("upload_jobs")
        .select("id,status,step,progress_pct,progress,document_id,error_message")
        .eq("id", job_id)
        .eq("user_id", user["id"])
    )
    result = await run_blocking_io(query.execute)
    if not result.data:
        raise HTTPException(404, "Job not found")

    job = result.data[0]

    # Embed full document+fields when done so Flutter needs only one call
    extracted_data = None
    if job["status"] == "done" and job.get("document_id"):
        extracted_data = await run_blocking_io(
            get_readable_document,
            supabase,
            job["document_id"],
            user,
            "*, document_fields(*)",
        )

    return {**job, "extracted_data": extracted_data}

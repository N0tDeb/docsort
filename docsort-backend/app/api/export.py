
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from app.core.database import get_supabase, SupabaseClient
from app.core.concurrency import run_blocking_io
from app.core.security import get_current_user
from app.core.config import settings
from app.core.document_access import get_readable_document, scope_document_read_query
from app.utils.logger import logger
from app.utils.file_safety import content_disposition, csv_safe, sanitize_filename

import hashlib
import hmac
import io
import zipfile
import csv
import tempfile
from pathlib import PurePosixPath

router = APIRouter(prefix="/export", tags=["export"])


def _hash_matches(expected_hash: str | None, current_hash: str) -> bool:
    """Fail closed unless a valid stored SHA-256 exactly matches."""
    expected = str(expected_hash or "").strip().lower()
    current = str(current_hash or "").strip().lower()
    if len(expected) != 64 or len(current) != 64:
        return False
    try:
        int(expected, 16)
        int(current, 16)
    except ValueError:
        return False
    return hmac.compare_digest(expected, current)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(fileobj, *, chunk_size: int = 64 * 1024) -> str:
    """Hash a staged binary file and rewind it for subsequent streaming."""
    digest = hashlib.sha256()
    fileobj.seek(0)
    while True:
        chunk = fileobj.read(chunk_size)
        if not chunk:
            break
        digest.update(chunk)
    fileobj.seek(0)
    return digest.hexdigest()


def _unique_zip_name(filename: str, used_names: set[str]) -> str:
    safe = sanitize_filename(filename, fallback="document")
    candidate = safe
    suffix = PurePosixPath(safe).suffix
    stem = safe[:-len(suffix)] if suffix else safe
    counter = 2
    while candidate.casefold() in used_names:
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    used_names.add(candidate.casefold())
    return candidate


@router.get("/folder/{folder_id}")
async def export_folder(
    folder_id: str,
    format:    str    = Query(default="zip", enum=["zip", "csv"]),
    supabase: SupabaseClient = Depends(get_supabase),
    user:      dict   = Depends(get_current_user),
):
    """
    Exports all documents in a folder.
    ZIP mode: bundles original files + a metadata CSV inside the archive.
    CSV mode: just the metadata sheet — useful for HOD reporting.
    """
    # Verify folder belongs to user's department
    folder_query = (
        supabase.table("folders")
        .select("id, name")
        .eq("id", folder_id)
        .eq("department_id", user["department_id"])
    )
    folder = await run_blocking_io(folder_query.execute)
    if not folder.data:
        raise HTTPException(status_code=404, detail="Folder not found.")

    folder_name = folder.data[0]["name"]

    # Fetch all documents in this folder with their extracted fields
    docs_query = (
        supabase.table("documents")
        .select("*, document_fields(*), users(name, designation)")
        .eq("folder_id", folder_id)
    )
    docs_query = (
        scope_document_read_query(docs_query, user)
        .order("created_at")
        .limit(settings.max_folder_export_documents + 1)
    )
    docs = await run_blocking_io(docs_query.execute)
    if not docs.data:
        raise HTTPException(status_code=404, detail="No documents in this folder.")
    if len(docs.data) > settings.max_folder_export_documents:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Folder export is limited to {settings.max_folder_export_documents} documents. "
                "Export a smaller folder or split the records first."
            ),
        )

    # ── CSV metadata export ────────────────────────────────────────────────────
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)

        # Build header: fixed columns + all unique field labels across all docs
        all_labels = []
        seen = set()
        for doc in docs.data:
            for f in doc.get("document_fields", []):
                lbl = f.get("label", "")
                if lbl and lbl not in seen:
                    all_labels.append(lbl)
                    seen.add(lbl)

        header = ["Sr No", "Doc Type", "Filename", "Uploaded By", "Upload Date",
                  "Tamper Flag", "OCR Confidence"] + [csv_safe(label) for label in all_labels]
        writer.writerow(header)

        for sr, doc in enumerate(docs.data, 1):
            fields_by_label = {
                f.get("label"): f.get("value", "")
                for f in doc.get("document_fields", [])
            }
            row = [
                sr,
                csv_safe(doc.get("doc_type", "")),
                csv_safe(doc.get("filename", "")),
                csv_safe((doc.get("users") or {}).get("name", "")),
                str(doc.get("created_at", ""))[:10],
                "YES" if doc.get("is_tampered") else "NO",
                f"{(doc.get('ocr_confidence') or 0) * 100:.1f}%",
            ] + [csv_safe(fields_by_label.get(lbl, "")) for lbl in all_labels]
            writer.writerow(row)

        buf.seek(0)
        safe_name = sanitize_filename(f"{folder_name}.csv", fallback="documents.csv")
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": content_disposition(safe_name)},
        )

    # ── ZIP export ─────────────────────────────────────────────────────────────
    zip_buf = tempfile.SpooledTemporaryFile(
        max_size=settings.export_spool_memory_bytes,
        mode="w+b",
    )
    unavailable_files: list[str] = []
    total_source_bytes = 0

    zf = None
    try:
        zf = zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED)
        used_names = {"metadata.csv"}

        # Write metadata CSV inside the ZIP. Compression and archive writes are
        # blocking CPU/file operations, so keep them off the FastAPI event loop.
        meta_buf = io.StringIO()
        writer   = csv.writer(meta_buf)
        writer.writerow(["Filename", "Doc Type", "Tamper Flag", "OCR Confidence",
                         "Upload Date", "Uploaded By"])
        for doc in docs.data:
            writer.writerow([
                csv_safe(doc.get("filename", "")),
                csv_safe(doc.get("doc_type", "")),
                "YES" if doc.get("is_tampered") else "NO",
                f"{(doc.get('ocr_confidence') or 0) * 100:.1f}%",
                str(doc.get("created_at", ""))[:10],
                csv_safe((doc.get("users") or {}).get("name", "")),
            ])
        await run_blocking_io(zf.writestr, "metadata.csv", meta_buf.getvalue())

        # Fetch and bundle the actual files from Supabase Storage.  The archive
        # is built completely before any response bytes are sent, so a missing
        # object never produces a deceptively "successful" partial backup.
        bucket = supabase.storage.from_("docsort")
        for doc in docs.data:
            storage_path = doc.get("storage_path")
            filename = str(doc.get("filename") or "document")
            if not storage_path:
                unavailable_files.append(filename)
                logger.warning("[export] Document source path is missing")
                continue

            try:
                file_bytes = await run_blocking_io(bucket.download, storage_path)
            except Exception as e:
                unavailable_files.append(filename)
                logger.warning("[export] Source retrieval failed error_type=%s", type(e).__name__)
                continue

            current_hash = await run_blocking_io(_sha256_bytes, file_bytes)
            if not _hash_matches(doc.get("file_hash"), current_hash):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Source integrity verification failed for one or more documents. "
                        "No archive was returned."
                    ),
                )

            next_total = total_source_bytes + len(file_bytes)
            if next_total > settings.max_folder_export_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "Folder ZIP export exceeds the configured source-byte limit "
                        f"of {settings.max_folder_export_bytes} bytes. "
                        "Export a smaller folder or split the records first."
                    ),
                )
            total_source_bytes = next_total

            archive_name = _unique_zip_name(filename, used_names)
            await run_blocking_io(zf.writestr, archive_name, file_bytes)

        # Closing writes the ZIP central directory and can flush buffered file
        # data, so finalize the archive through the same blocking-I/O boundary.
        await run_blocking_io(zf.close)
        zf = None

        if unavailable_files:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Folder export could not be completed because "
                    f"{len(unavailable_files)} source file(s) were unavailable. "
                    "No partial archive was returned."
                ),
            )
    except Exception:
        if zf is not None:
            try:
                await run_blocking_io(zf.close)
            except Exception as close_exc:
                logger.warning("[export] Failed ZIP finalization error_type=%s", type(close_exc).__name__)
        zip_buf.close()
        raise

    zip_buf.seek(0)
    safe_name = sanitize_filename(f"{folder_name}.zip", fallback="documents.zip")

    def iter_zip():
        try:
            while True:
                chunk = zip_buf.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            zip_buf.close()

    return StreamingResponse(
        iter_zip(),
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(safe_name)},
    )


@router.get("/document/{doc_id}")
async def export_single_document(
    doc_id:   str,
    supabase: SupabaseClient = Depends(get_supabase),
    user:     dict   = Depends(get_current_user),
):
    """
    Returns the original file bytes for a single document.
    Used by the Result screen's share / download button.
    Streams the original image or PDF from a bounded spool — no conversion.
    """
    document = await run_blocking_io(
        get_readable_document,
        supabase,
        doc_id,
        user,
        "filename, storage_path, file_hash",
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    storage_path = document["storage_path"]
    filename = document["filename"]

    # Stage the Storage object into a bounded-memory spool before returning any
    # response bytes. Small files stay in memory; larger files spill to disk.
    # This avoids whole-object RAM buffering while preserving fail-closed export
    # semantics when Storage cannot provide the complete source object.
    file_spool = tempfile.SpooledTemporaryFile(
        max_size=settings.export_spool_memory_bytes,
        mode="w+b",
    )
    try:
        bucket = supabase.storage.from_("docsort")
        await run_blocking_io(
            bucket.download_to_file,
            storage_path,
            file_spool,
        )
        current_hash = await run_blocking_io(_sha256_file, file_spool)
        if not _hash_matches(document.get("file_hash"), current_hash):
            file_spool.close()
            raise HTTPException(
                status_code=409,
                detail="Source integrity verification failed. File was not exported.",
            )
    except HTTPException:
        file_spool.close()
        raise
    except Exception as exc:
        file_spool.close()
        logger.error("[export] Document retrieval failed error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not retrieve file.") from exc

    # Determine content type from file extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    mime_map = {
        "pdf":  "application/pdf",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "png":  "image/png",
    }
    mime = mime_map.get(ext, "application/octet-stream")

    def iter_file():
        try:
            while True:
                chunk = file_spool.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            file_spool.close()

    return StreamingResponse(
        iter_file(),
        media_type=mime,
        headers={"Content-Disposition": content_disposition(filename)},
    )

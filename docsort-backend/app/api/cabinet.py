from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Annotated, List, Optional
from pydantic import BaseModel

from app.core.database import get_supabase, SupabaseClient
from app.core.config import settings
from app.core.concurrency import run_blocking_io
from app.core.security import get_current_user, get_current_admin
from app.core.document_access import (
    get_readable_document,
    get_writable_document,
    scope_document_read_query,
    scope_document_write_query,
)
from app.utils.logger import logger
from app.schemas.cabinet_schema import (
    FolderCreate, FolderUpdate, FolderResponse,
    DocumentResponse,
)
from app.services.autosort_service import AutoSortService
from app.services.activity_service import activity_service

router = APIRouter(prefix="/cabinet", tags=["cabinet"])
autosort_service = AutoSortService()


# ── Folders — CRUD ─────────────────────────────────────────────────────────────

@router.get("/folders", response_model=List[FolderResponse])
async def list_folders(
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    if not user.get("department_id"):
        # Return categorized synthetic folders for personal documents
        try:
            doc_query = supabase.table("documents").select("id, doc_type")
            doc_query = scope_document_read_query(doc_query, user).limit(
                settings.max_personal_folder_scan
            )
            doc_res = await run_blocking_io(doc_query.execute)
            docs = doc_res.data or []
        except Exception:
            docs = []

        from app.services.autosort_service import DOC_TYPE_TO_FOLDER

        category_counts = {}
        for doc in docs:
            dt = (doc.get("doc_type") or "").lower().strip()
            folder_name = "Other"
            for k, f_name in DOC_TYPE_TO_FOLDER.items():
                if k in dt:
                    folder_name = f_name
                    break
            category_counts[folder_name] = category_counts.get(folder_name, 0) + 1

        folders = []
        for cat, count in category_counts.items():
            folders.append({
                "id": f"personal_{cat}",
                "department_id": "",
                "created_at": "2024-01-01T00:00:00Z",
                "name": cat,
                "doc_type_affinity": "all",
                "color": "#1a73e8" if cat != "Other" else "#9e9e9e",
                "icon": "folder" if cat != "Other" else "folder_open",
                "is_system": True,
                "is_default_review": False,
                "document_count": count
            })

        if not folders:
            # Fallback for entirely new users so their screen isn't completely empty
            folders.append({
                "id": "unassigned",
                "department_id": "",
                "created_at": "2024-01-01T00:00:00Z",
                "name": "My Uploads",
                "doc_type_affinity": "all",
                "color": "#1a73e8",
                "icon": "folder_shared",
                "is_system": True,
                "is_default_review": False,
                "document_count": 0
            })

        return folders
    # Folder metadata is shared within the department, but document counts must
    # obey the same privacy rules as the document listing itself. Otherwise a
    # member could infer how many private peer documents exist in each folder.
    folders_query = (
        supabase.table("folders")
        .select("*")
        .eq("department_id", user["department_id"])
        .order("created_at", desc=False)
    )
    folders_result = await run_blocking_io(folders_query.execute)
    visible_docs_query = (
        supabase.table("documents")
        .select("folder_id")
        .eq("department_id", user["department_id"])
    )
    visible_docs_query = scope_document_read_query(visible_docs_query, user)
    visible_docs = await run_blocking_io(visible_docs_query.execute)
    counts: dict[str, int] = {}
    for doc in visible_docs.data or []:
        folder_id = doc.get("folder_id")
        if folder_id:
            counts[str(folder_id)] = counts.get(str(folder_id), 0) + 1

    for folder in folders_result.data or []:
        folder["document_count"] = counts.get(str(folder.get("id")), 0)
    return folders_result.data


@router.post("/folders", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    payload: FolderCreate,
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_admin),
):
    if not user.get("department_id"):
        raise HTTPException(status_code=400, detail="Administrator has no assigned department.")
    insert_query = supabase.table("folders").insert({
        "department_id":     user["department_id"],
        "name":              payload.name,
        "doc_type_affinity": payload.doc_type_affinity,
        "color":             payload.color,
        "icon":              payload.icon,
    })
    result = await run_blocking_io(insert_query.execute)
    return result.data[0]


@router.put("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_admin),
):
    if not user.get("department_id"):
        raise HTTPException(status_code=400, detail="Administrator has no assigned department.")
    existing_query = (
        supabase.table("folders")
        .select("id")
        .eq("id", folder_id)
        .eq("department_id", user["department_id"])
    )
    existing = await run_blocking_io(existing_query.execute)
    if not existing.data:
        raise HTTPException(status_code=404, detail="Folder not found.")

    update_data = payload.model_dump(exclude_none=True)
    update_query = (
        supabase.table("folders")
        .update(update_data)
        .eq("id", folder_id)
    )
    result = await run_blocking_io(update_query.execute)
    return result.data[0]


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_admin),
):
    if not user.get("department_id"):
        raise HTTPException(status_code=400, detail="Administrator has no assigned department.")
    existing_query = (
        supabase.table("folders")
        .select("id, is_system")
        .eq("id", folder_id)
        .eq("department_id", user["department_id"])
    )
    existing = await run_blocking_io(existing_query.execute)
    if not existing.data:
        raise HTTPException(status_code=404, detail="Folder not found.")

    # Protect auto-created system folders such as "Needs Review" from deletion.
    if existing.data[0].get("is_system"):
        raise HTTPException(status_code=403, detail="System folders cannot be deleted.")

    # Move orphaned docs to "Needs Review" before deleting
    needs_review_query = (
        supabase.table("folders")
        .select("id")
        .eq("department_id", user["department_id"])
        .eq("is_default_review", True)
    )
    needs_review = await run_blocking_io(needs_review_query.execute)
    if needs_review.data:
        move_query = (
            supabase.table("documents")
            .update({"folder_id": needs_review.data[0]["id"]})
            .eq("folder_id", folder_id)
            .eq("department_id", user["department_id"])
        )
        await run_blocking_io(move_query.execute)

    delete_query = (
        supabase.table("folders")
        .delete()
        .eq("id", folder_id)
        .eq("department_id", user["department_id"])
    )
    await run_blocking_io(delete_query.execute)


# ── Documents across all folders (Recent) ──────────────────────────────────────

@router.get("/documents", response_model=List[DocumentResponse])
async def list_recent_documents(
    limit: Annotated[int, Query(ge=1, le=100)] = 5,
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    query = supabase.table("documents").select(
        "*, document_fields(*), users(name, designation)"
    )
    query = scope_document_read_query(query, user)

    query = query.order("created_at", desc=True).limit(limit)
    result = await run_blocking_io(query.execute)
    docs = result.data or []
    for doc in docs:
        if not doc.get("users"):
            doc["users"] = {"name": user["name"], "designation": ""}
        elif not doc["users"].get("name"):
            doc["users"]["name"] = user["name"]

    return docs


# ── Documents inside a folder ──────────────────────────────────────────────────

@router.get("/{folder_id}/documents", response_model=List[DocumentResponse])
async def list_folder_documents(
    folder_id: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    if folder_id == "unassigned" or folder_id.startswith("personal_"):
        # Synthetic folders only exist for unassigned users. Once a
        # user belongs to a department, accepting a client-supplied synthetic
        # ID would create an alternate path around the current department read
        # scope for documents they owned before reassignment.
        if user.get("department_id"):
            raise HTTPException(status_code=404, detail="Folder not found.")

        query = supabase.table("documents").select(
            "*, document_fields(*), users(name, designation)"
        )
        query = scope_document_read_query(query, user)
        query = query.order("created_at", desc=True).limit(
            settings.max_personal_folder_scan
        )
        result = await run_blocking_io(query.execute)
        docs = result.data or []

        if folder_id.startswith("personal_"):
            cat_name = folder_id.split("personal_", 1)[1]
            from app.services.autosort_service import DOC_TYPE_TO_FOLDER
            filtered_docs = []
            for doc in docs:
                dt = (doc.get("doc_type") or "").lower().strip()
                match = "Other"
                for k, f_name in DOC_TYPE_TO_FOLDER.items():
                    if k in dt:
                        match = f_name
                        break
                if match == cat_name:
                    filtered_docs.append(doc)
            docs = filtered_docs

        docs = docs[offset: offset + limit]
        for doc in docs:
            if not doc.get("users"):
                doc["users"] = {"name": user["name"], "designation": ""}
            elif not doc["users"].get("name"):
                doc["users"]["name"] = user["name"]
        return docs

    folder_query = (
        supabase.table("folders")
        .select("id")
        .eq("id", folder_id)
        .eq("department_id", user["department_id"])
    )
    folder = await run_blocking_io(folder_query.execute)
    if not folder.data:
        raise HTTPException(status_code=404, detail="Folder not found.")

    query = (
        supabase.table("documents")
        .select("*, document_fields(*), users(name, designation)")
        .eq("folder_id", folder_id)
    )
    # A folder belongs to the caller's department, but document.department_id is
    # not database-constrained to match folder.department_id. Re-apply the
    # centralized read policy so malformed/cross-department rows cannot leak.
    query = scope_document_read_query(query, user)

    query = query.order("created_at", desc=True).range(
        offset, offset + min(limit, settings.max_folder_page_size) - 1
    )
    result = await run_blocking_io(query.execute)
    docs = result.data or []
    for doc in docs:
        if not doc.get("users"):
            doc["users"] = {"name": user["name"], "designation": ""}
        elif not doc["users"].get("name"):
            doc["users"]["name"] = user["name"]

    return docs


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: str,
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    document = await run_blocking_io(
        get_readable_document,
        supabase,
        doc_id,
        user,
        "*, document_fields(*), users(name, designation)",
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: str,
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    logger.info("Document deletion requested")

    if not doc_id or doc_id == "None":
        raise HTTPException(status_code=400, detail="Invalid document ID")

    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Authorize and delete in the same scoped database operation.  The schema's
    # document_fields.document_id foreign key is ON DELETE CASCADE, so deleting
    # child rows manually before this authorization check would allow an
    # unauthorized caller to destroy another user's extracted fields.
    query = supabase.table("documents").delete().eq("id", doc_id)
    query = scope_document_write_query(query, user)

    res = await run_blocking_io(query.execute)

    if not res.data:
        # Avoid leaking whether the document exists outside the caller's scope.
        raise HTTPException(status_code=404, detail="Document not found.")

    # Database deletion is authoritative. Remove the private source object after
    # the row is gone so a Storage failure can never leave a live document with
    # a dead storage_path. A failed object cleanup is logged as an orphan rather
    # than rolling back an already-authorized document deletion.
    storage_path = res.data[0].get("storage_path")
    if storage_path:
        try:
            await run_blocking_io(
                supabase.storage.from_("docsort").remove, [storage_path]
            )
        except Exception as exc:
            logger.warning("Document row deleted but source cleanup failed error_type=%s", type(exc).__name__)

    return None


@router.put("/documents/{doc_id}/move")
async def move_document(
    doc_id: str,
    target_folder: str,
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    document = await run_blocking_io(
        get_writable_document,
        supabase,
        doc_id,
        user,
        "id, user_id, department_id",
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    folder_query = (
        supabase.table("folders")
        .select("id")
        .eq("id", target_folder)
        .eq("department_id", user["department_id"])
    )
    folder = await run_blocking_io(folder_query.execute)
    if not folder.data:
        raise HTTPException(status_code=404, detail="Target folder not found.")

    update_query = (
        supabase.table("documents")
        .update({"folder_id": target_folder})
        .eq("id", doc_id)
    )
    result = await run_blocking_io(
        scope_document_write_query(update_query, user).execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found.")
    await run_blocking_io(
        activity_service.log,
        user["id"],
        user["department_id"],
        "move",
        doc_id,
    )
    return result.data[0]


# ── Manual review ─────────────────────────────────────────────────────────────

class DocumentReviewUpdate(BaseModel):
    doc_type:   Optional[str]  = None
    is_private: Optional[bool] = None

class FieldUpdateItem(BaseModel):
    id:    Optional[str] = None
    label: str
    value: str

@router.put("/documents/{doc_id}")
async def update_document(
    doc_id: str,
    payload: DocumentReviewUpdate,
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    document = await run_blocking_io(
        get_writable_document, supabase, doc_id, user, "user_id, department_id"
    )
    if not document:
        raise HTTPException(404, "Document not found.")

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        return {"status": "no changes"}

    update_query = supabase.table("documents").update(update_data).eq("id", doc_id)
    res = await run_blocking_io(
        scope_document_write_query(update_query, user).execute
    )
    if not res.data:
        raise HTTPException(404, "Document not found.")
    return res.data[0]


@router.put("/documents/{doc_id}/fields")
async def update_document_fields(
    doc_id: str,
    fields: List[FieldUpdateItem],
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    document = await run_blocking_io(
        get_writable_document,
        supabase,
        doc_id,
        user,
        "user_id, department_id, doc_type",
    )
    if not document:
        raise HTTPException(404, "Document not found.")

    # Fetch current fields to preserve system suggestions and trigger classification
    old_fields_query = (
        supabase.table("document_fields").select("*").eq("document_id", doc_id)
    )
    old_fields_res = await run_blocking_io(old_fields_query.execute)
    old_fields = old_fields_res.data or []

    system_suggested_folder = None
    for f in old_fields:
        if f.get("label") == "system_suggested_folder":
            system_suggested_folder = f.get("value")

    inserts = [
        {"label": f.label, "value": f.value, "confidence": 1.0}
        for f in fields
        if not f.label.startswith("system_") # prevent user overriding system fields
    ]

    if system_suggested_folder:
        inserts.append({
            "label": "system_suggested_folder",
            "value": system_suggested_folder,
            "confidence": 1.0
        })

    # Replace the full field set atomically in PostgreSQL.  A failed replacement
    # rolls back both the delete and insert inside replace_document_fields(), so
    # manual review cannot leave a document with a partially replaced field set.
    replace_fields_rpc = supabase.rpc(
        "replace_document_fields",
        {"p_document_id": doc_id, "p_fields": inserts},
    )
    await run_blocking_io(replace_fields_rpc.execute)

    # ---- Trigger Deferred Auto-Classification ----
    from app.services.autosort_service import AutoSortService
    autosort_service = AutoSortService()

    # We need the doc_type of the document
    doc_type = document.get("doc_type", "")
    folder_id, _sort_confidence = await autosort_service.classify(
        doc_type=doc_type,
        fields=[i for i in inserts if not i["label"].startswith("system_")],
        department_id=user["department_id"],
        suggested_folder_name=system_suggested_folder,
        supabase=supabase,
    )

    update_payload = {"review_status": "verified"}
    if folder_id:
        # Human review may change the final folder, but it must not overwrite
        # the original automatic routing score used by analytics/evaluation.
        update_payload["folder_id"] = folder_id

    update_query = supabase.table("documents").update(update_payload).eq("id", doc_id)
    updated = await run_blocking_io(
        scope_document_write_query(update_query, user).execute
    )
    if not updated.data:
        raise HTTPException(404, "Document not found.")

    return {"status": "verified", "message": "Document fields reviewed and verified successfully"}


# ── Auto-Sort ─────────────────────────────────────────────────────────────────

@router.post("/autosort")
async def run_autosort(
    supabase: SupabaseClient = Depends(get_supabase),
    user: dict = Depends(get_current_user),
):
    review_folder_query = (
        supabase.table("folders")
        .select("id")
        .eq("department_id", user["department_id"])
        .eq("is_default_review", True)
    )
    review_folder = await run_blocking_io(review_folder_query.execute)
    if not review_folder.data:
        return {"sorted": 0, "still_pending": 0, "message": "No review folder found."}

    review_folder_id = review_folder.data[0]["id"]

    unsorted_query = (
        supabase.table("documents")
        .select("*, document_fields(*)")
        .eq("folder_id", review_folder_id)
    )
    # Auto-sort is a document mutation. A regular member must never be able to
    # refile a peer's document simply because both documents share the review
    # folder. Department admins retain the broader same-department write scope.
    unsorted = await run_blocking_io(
        scope_document_write_query(unsorted_query, user).execute
    )
    if not unsorted.data:
        return {"sorted": 0, "still_pending": 0}

    sorted_count  = 0
    pending_count = 0

    for doc in unsorted.data:
        folder_id, confidence = await autosort_service.classify(
            doc_type=doc.get("doc_type", ""),
            fields=doc.get("document_fields", []),
            department_id=user["department_id"],
            supabase=supabase,
        )
        if folder_id and folder_id != review_folder_id:
            update_query = supabase.table("documents").update({
                "folder_id":       folder_id,
                "sort_confidence": confidence,
            }).eq("id", doc["id"])
            updated = await run_blocking_io(
                scope_document_write_query(update_query, user).execute
            )
            if updated.data:
                sorted_count += 1
            else:
                pending_count += 1
        else:
            pending_count += 1

    return {"sorted": sorted_count, "still_pending": pending_count}

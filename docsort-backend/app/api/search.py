from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from app.core.database import get_supabase, SupabaseClient
from app.core.concurrency import run_blocking_io
from app.core.security import get_current_user
from app.core.document_access import can_read_document, scope_document_read_query
from app.schemas.search_schema import SearchResultResponse

import re

router = APIRouter(prefix="/search", tags=["search"])

# Safety cap on how many candidate rows we pull per sub-query. Keyword search runs
# at the database level (below), so this only bounds pathological queries.
# For very large cabinets, upgrade to a Postgres tsvector / pg_trgm index.
_CANDIDATE_CAP = 500


def _highlight(text: str, query: str) -> str:
    """
    Wraps all case-insensitive occurrences of 'query' in 'text' with ^^ markers.
    Flutter's RichText widget can split on ^^ to render highlighted spans.
    """
    if not text or not query:
        return text or ""
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return pattern.sub(lambda m: f"^^{m.group()}^^", text)


def _build_highlights(doc: dict, query: str) -> list:
    """Produces a list of highlight objects across all searchable fields."""
    highlights = []

    if doc.get("doc_type") and query.lower() in doc["doc_type"].lower():
        highlights.append({
            "field":   "Document Type",
            "value":   doc["doc_type"],
            "snippet": _highlight(doc["doc_type"], query),
        })

    if doc.get("filename") and query.lower() in doc["filename"].lower():
        highlights.append({
            "field":   "Filename",
            "value":   doc["filename"],
            "snippet": _highlight(doc["filename"], query),
        })

    for field in doc.get("document_fields", []):
        val = field.get("value") or ""
        if query.lower() in val.lower():
            highlights.append({
                "field":   field.get("label", "Field"),
                "value":   val,
                "snippet": _highlight(val, query),
            })

    return highlights


def _merge_candidates(docs_by_id: dict, rows: list[dict]) -> None:
    """Merge rows without replacing a richer row already fetched earlier."""
    for doc in rows:
        doc_id = doc.get("id")
        if doc_id:
            docs_by_id.setdefault(doc_id, doc)


@router.get("", response_model=List[SearchResultResponse])
async def search_documents(
    q:         str            = Query(..., min_length=1, description="Search query"),
    doc_type:  Optional[str]  = Query(default=None, description="Filter by document type"),
    folder_id: Optional[str]  = Query(default=None, description="Limit search to one folder"),
    limit:     int            = Query(default=20, ge=1, le=100),
    offset:    int            = Query(default=0, ge=0),
    supabase: SupabaseClient = Depends(get_supabase),
    user:      dict           = Depends(get_current_user),
):
    """
    Full-text keyword search across ALL documents in the user's department.

    Filtering happens at the database level via case-insensitive `ilike`:
      1. a query over documents matching on doc_type OR filename, and
      2. a query over document_fields matching on the extracted value,
    whose parent documents are then fetched.
    The two candidate sets are merged, de-duplicated, precision-checked in
    Python (which also builds highlights), sorted, and paginated.

    Candidate discovery is performed across the authorized document scope
    before ranking and pagination so matching documents are not hidden by recency.
    """
    query = q.strip()
    if not query:
        return []

    pattern = f"*{query}*"
    docs_by_id: dict = {}

    # ── Candidate set 1: match on doc_type / filename ─────────────────────────
    # Use separate queries instead of a PostgREST OR so the standard document
    # read scope (including private-document visibility) is applied *before*
    # the candidate limit.  Otherwise inaccessible peer-private documents can
    # consume the first 500 rows and hide legitimate results.
    for column in ("doc_type", "filename"):
        parent_q = scope_document_read_query(
            supabase.table("documents").select(
                "*, document_fields(*), users(name), folders(name)"
            ),
            user,
        ).ilike(column, pattern)
        if doc_type:
            parent_q = parent_q.eq("doc_type", doc_type)
        if folder_id:
            parent_q = parent_q.eq("folder_id", folder_id)
        parent_q = parent_q.limit(_CANDIDATE_CAP)
        parent_res = await run_blocking_io(parent_q.execute)
        _merge_candidates(docs_by_id, parent_res.data or [])

    # ── Candidate set 2: match inside extracted field values ──────────────────
    # Query the parent documents through an inner embedded relation so the
    # authorization scope is enforced on `documents` before the candidate cap.
    # Authorization is applied before the candidate cap so unrelated field rows
    # cannot consume the bounded search candidate window.
    field_q = scope_document_read_query(
        supabase.table("documents").select(
            "*, document_fields!inner(*), users(name), folders(name)"
        ),
        user,
    ).ilike("document_fields.value", pattern)
    if doc_type:
        field_q = field_q.eq("doc_type", doc_type)
    if folder_id:
        field_q = field_q.eq("folder_id", folder_id)
    field_q = field_q.limit(_CANDIDATE_CAP)
    field_res = await run_blocking_io(field_q.execute)
    _merge_candidates(docs_by_id, field_res.data or [])

    # ── Optional filters ──────────────────────────────────────────────────────
    candidates = list(docs_by_id.values())
    if doc_type:
        candidates = [d for d in candidates if d.get("doc_type") == doc_type]
    if folder_id:
        candidates = [d for d in candidates if str(d.get("folder_id")) == str(folder_id)]

    # ── Precision re-check + highlights ───────────────────────────────────────
    results = []
    for doc in candidates:
        # Defense in depth: every database candidate is already scoped before
        # the candidate limit, but keep the policy check before producing output.
        if not can_read_document(doc, user):
            continue
        highlights = _build_highlights(doc, query)
        if not highlights:
            continue
        results.append({
            **doc,
            "match_highlights": highlights,
            "folder_name":      (doc.get("folders") or {}).get("name", ""),
            "uploaded_by":      (doc.get("users")   or {}).get("name", ""),
        })

    # Newest first, then paginate the full matched set.
    results.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return results[offset: offset + limit]

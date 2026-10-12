# app/api/graph.py
# Experimental People Map API — internal citizen table/route identifiers back the public feature
#
# Routes:
#   GET  /graph/department          → full people/document map for department
#   GET  /graph/citizen/{id}        → single person detail + linked docs
#   POST /graph/citizen             → manually create person node
#   POST /graph/edge                → manually create edge
#   DELETE /graph/edge/{id}         → delete edge
#   GET  /graph/duplicates          → list potential duplicate identity pairs
#   POST /graph/reprocess/{doc_id}  → re-run relationship detection on doc

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.core.security import get_current_admin
from app.core.database import get_supabase as get_db
from app.schemas.graph_schema import (
    CitizenCreate, CitizenResponse,
    EdgeCreate, EdgeResponse,
    GraphResponse, GraphNodeResponse,
    CitizenDocumentCreate
)
from app.services.relationship_service import process_relationships
from app.core.database import get_supabase_sync
from app.core.concurrency import run_blocking_io
from app.core.document_access import (
    can_read_document,
    get_readable_document,
    get_writable_document,
)
from typing import List

def _get_user_dept_id(user) -> str:
    """Helper to extract or fetch department_id if missing from JWT scope."""
    dept_id = user.get("department_id")
    if not dept_id:
        sb = get_supabase_sync()
        u_res = sb.table("users").select("department_id").eq("id", user["id"]).execute()
        if u_res.data:
            dept_id = u_res.data[0].get("department_id")
    return str(dept_id) if dept_id else ""


def _require_user_dept_id(user) -> str:
    """Return the caller's department or reject graph access without one."""
    dept_id = _get_user_dept_id(user)
    if not dept_id:
        raise HTTPException(status_code=400, detail="User has no assigned department")
    return dept_id


def _access_user(user: dict, dept_id: str) -> dict:
    """Return an access-policy user with the resolved department populated."""
    if user.get("department_id"):
        return user
    return {**user, "department_id": dept_id}


def _department_citizen_ids(db, dept_id: str, citizen_ids=None) -> set[str]:
    """Return citizen IDs that belong to ``dept_id``, optionally from a candidate set."""
    query = db.table("citizens").select("id").eq("dept_id", dept_id)
    if citizen_ids:
        query = query.in_("id", [str(citizen_id) for citizen_id in citizen_ids])
    result = query.execute()
    return {str(row["id"]) for row in (result.data or [])}

router = APIRouter(prefix="/graph", tags=["experimental-people-map"])


# ── GET full graph for department ─────────────────────────────
@router.get("/department", response_model=GraphResponse)
async def get_department_graph(
    user=Depends(get_current_admin),
    db=Depends(get_db)
):
    """
    Returns person nodes + experimental identity-link edges for the current user's department.
    Internal citizen table/field identifiers are mapped to the People Map product contract.
    """
    dept_id = await run_blocking_io(_require_user_dept_id, user)
    access_user = _access_user(user, dept_id)

    # Fetch only people from the caller's department (internal citizens table). The backend uses the
    # service-role database key, so route-level tenant scoping is mandatory.
    citizens_query = db.table("citizens")\
        .select("*")\
        .eq("dept_id", dept_id)
    citizens_res = await run_blocking_io(citizens_query.execute)

    citizens = citizens_res.data or []
    citizen_ids = {str(c["id"]) for c in citizens}

    # Load person-to-document links in one batched query. The
    # relationship join may still contain malformed/cross-tenant links, so
    # document visibility is checked in Python before any field data is fetched.
    links_by_citizen: dict[str, list[dict]] = {citizen_id: [] for citizen_id in citizen_ids}
    readable_document_ids: set[str] = set()
    if citizen_ids:
        docs_query = (
            db.table("citizen_documents")
            .select(
                "document_id, citizen_id, "
                "documents(id, doc_type, ocr_confidence, is_tampered, filename, "
                "user_id, department_id, is_private)"
            )
            .in_("citizen_id", sorted(citizen_ids))
        )
        docs_res = await run_blocking_io(docs_query.execute)
        for link in (docs_res.data or []):
            citizen_id = str(link.get("citizen_id") or "")
            document = link.get("documents") or {}
            if citizen_id not in citizen_ids or not document:
                continue
            if not can_read_document(document, access_user):
                continue
            links_by_citizen[citizen_id].append(link)
            readable_document_ids.add(str(link["document_id"]))

    # Fetch fields once for all readable documents. This intentionally happens
    # after document authorization so fields from private/cross-tenant links are
    # never materialized merely because a malformed graph link references them.
    fields_by_document: dict[str, list[dict]] = {}
    if readable_document_ids:
        fields_query = (
            db.table("document_fields")
            .select("document_id, label, value")
            .in_("document_id", sorted(readable_document_ids))
        )
        fields_res = await run_blocking_io(fields_query.execute)
        for field in (fields_res.data or []):
            document_id = str(field.get("document_id") or "")
            if document_id not in readable_document_ids:
                continue
            fields_by_document.setdefault(document_id, []).append({
                "label": field.get("label"),
                "value": field.get("value"),
            })

    nodes = []
    for c in citizens:
        docs = []
        for link in links_by_citizen.get(str(c["id"]), []):
            d = link.get("documents") or {}
            document_id = str(link["document_id"])
            fields_dict = {"fields": fields_by_document.get(document_id, [])}
            display_value = _pick_display_value(d.get("doc_type", ""), fields_dict)
            docs.append({
                "document_id": link["document_id"],
                "type": d.get("doc_type", "Unknown"),
                "value": display_value,
                "confidence": d.get("ocr_confidence", 0),
                "is_tampered": d.get("is_tampered", False),
                "filename": d.get("filename", ""),
            })

        nodes.append(GraphNodeResponse(
            id=c["id"],
            full_name=c["full_name"],
            dob=c.get("dob"),
            uid_number=c.get("uid_number"),
            is_flagged=c.get("is_flagged", False),
            doc_count=len(docs),
            docs=docs,
        ))

    # Keep an edge only when both endpoints belong to this department. This
    # prevents malformed/cross-tenant graph data from leaking another person ID.
    edge_rows = []
    if citizen_ids:
        edges_query = db.table("citizen_edges")\
            .select("*")\
            .in_("from_citizen", sorted(citizen_ids))
        edges_res = await run_blocking_io(edges_query.execute)
        edge_rows = edges_res.data or []

    edges = [
        EdgeResponse(**e) for e in edge_rows
        if str(e["from_citizen"]) in citizen_ids
        and str(e["to_citizen"]) in citizen_ids
    ]

    # Empty graphs remain empty; the UI shows an explicit experimental-feature
    # empty state instead of presenting fabricated identities as real records.

    return GraphResponse(nodes=nodes, edges=edges)


# ── GET single person detail ───────────────────────────────────
@router.get("/citizen/{citizen_id}")
async def get_citizen(
    citizen_id: str,
    user=Depends(get_current_admin),
    db=Depends(get_db)
):
    dept_id = await run_blocking_io(_require_user_dept_id, user)
    access_user = _access_user(user, dept_id)

    citizen_query = db.table("citizens")\
        .select("*")\
        .eq("id", citizen_id)\
        .eq("dept_id", dept_id)\
        .limit(1)
    row = await run_blocking_io(citizen_query.execute)
    if not row.data:
        raise HTTPException(404, "Person not found")

    docs_query = db.table("citizen_documents")\
        .select("document_id, documents(*)")\
        .eq("citizen_id", citizen_id)
    docs_res = await run_blocking_io(docs_query.execute)
    documents = [
        link.get("documents") for link in (docs_res.data or [])
        if link.get("documents") and can_read_document(link["documents"], access_user)
    ]

    dept_citizen_ids = await run_blocking_io(_department_citizen_ids, db, dept_id)
    edges_query = db.table("citizen_edges")\
        .select("*")\
        .or_(f"from_citizen.eq.{citizen_id},to_citizen.eq.{citizen_id}")
    edges_res = await run_blocking_io(edges_query.execute)
    edges = [
        edge for edge in (edges_res.data or [])
        if str(edge.get("from_citizen")) in dept_citizen_ids
        and str(edge.get("to_citizen")) in dept_citizen_ids
    ]

    return {
        "citizen": row.data[0],
        "documents": documents,
        "edges": edges,
    }


# ── POST create person manually ────────────────────────────────
@router.post("/citizen", response_model=CitizenResponse)
async def create_citizen(
    body: CitizenCreate,
    user=Depends(get_current_admin),
    db=Depends(get_db)
):
    payload = body.model_dump()
    payload["dept_id"] = await run_blocking_io(_require_user_dept_id, user)
    insert_query = db.table("citizens").insert(payload)
    res = await run_blocking_io(insert_query.execute)
    if not res.data:
        raise HTTPException(500, "Failed to create person")
    return CitizenResponse(**res.data[0])


# ── POST create edge manually ─────────────────────────────────
@router.post("/edge", response_model=EdgeResponse)
async def create_edge(
    body: EdgeCreate,
    user=Depends(get_current_admin),
    db=Depends(get_db)
):
    dept_id = await run_blocking_io(_require_user_dept_id, user)
    access_user = _access_user(user, dept_id)
    payload = body.model_dump()
    payload["from_citizen"] = str(payload["from_citizen"])
    payload["to_citizen"] = str(payload["to_citizen"])

    endpoints = await run_blocking_io(
        _department_citizen_ids,
        db,
        dept_id,
        [payload["from_citizen"], payload["to_citizen"]],
    )
    if endpoints != {payload["from_citizen"], payload["to_citizen"]}:
        raise HTTPException(404, "Person not found")

    if payload.get("evidence_doc_id"):
        payload["evidence_doc_id"] = str(payload["evidence_doc_id"])
        document = await run_blocking_io(
            get_readable_document, db, payload["evidence_doc_id"], access_user, "id"
        )
        if not document:
            raise HTTPException(404, "Evidence document not found")

    insert_query = db.table("citizen_edges").insert(payload)
    res = await run_blocking_io(insert_query.execute)
    if not res.data:
        raise HTTPException(500, "Failed to create edge")
    return EdgeResponse(**res.data[0])


# ── DELETE edge ───────────────────────────────────────────────
@router.delete("/edge/{edge_id}")
async def delete_edge(
    edge_id: str,
    user=Depends(get_current_admin),
    db=Depends(get_db)
):
    dept_id = await run_blocking_io(_require_user_dept_id, user)
    edge_query = db.table("citizen_edges").select("*").eq("id", edge_id).limit(1)
    edge_res = await run_blocking_io(edge_query.execute)
    if not edge_res.data:
        raise HTTPException(404, "Edge not found")

    edge = edge_res.data[0]
    endpoints = await run_blocking_io(
        _department_citizen_ids,
        db,
        dept_id,
        [edge.get("from_citizen"), edge.get("to_citizen")],
    )
    if endpoints != {str(edge.get("from_citizen")), str(edge.get("to_citizen"))}:
        raise HTTPException(404, "Edge not found")

    delete_query = db.table("citizen_edges").delete().eq("id", edge_id)
    deleted = await run_blocking_io(delete_query.execute)
    if not deleted.data:
        raise HTTPException(404, "Edge not found")
    return {"deleted": True}


# ── GET duplicates list ───────────────────────────────────────
@router.get("/duplicates")
async def get_duplicates(
    user=Depends(get_current_admin),
    db=Depends(get_db)
):
    """Return potential duplicate identity edges with linked person details."""
    dept_id = await run_blocking_io(_get_user_dept_id, user)
    if not dept_id:
        return []

    citizen_ids = await run_blocking_io(_department_citizen_ids, db, dept_id)
    if not citizen_ids:
        return []

    edges_query = db.table("citizen_edges")\
        .select("*, from_c:from_citizen(full_name,uid_number), to_c:to_citizen(full_name,uid_number)")\
        .eq("edge_type", "duplicate_of")\
        .in_("from_citizen", list(citizen_ids))
    edges = await run_blocking_io(edges_query.execute)
    return [
        edge for edge in (edges.data or [])
        if str(edge.get("from_citizen")) in citizen_ids
        and str(edge.get("to_citizen")) in citizen_ids
    ]


# ── POST re-run relationship detection on existing doc ────────
@router.post("/reprocess/{document_id}")
async def reprocess_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_admin),
    db=Depends(get_db)
):
    """Re-run optional people/document linking on an already-processed document."""
    dept_id = await run_blocking_io(_require_user_dept_id, user)
    access_user = _access_user(user, dept_id)
    document = await run_blocking_io(
        get_writable_document, db, document_id, access_user
    )
    if not document:
        raise HTTPException(404, "Document not found")

    d = document

    fields_query = (
        db.table("document_fields")
        .select("label, value")
        .eq("document_id", document_id)
    )
    fields_res = await run_blocking_io(fields_query.execute)

    background_tasks.add_task(
        process_relationships,
        db=db,
        document_id=document_id,
        dept_id=dept_id,
        doc_type=d.get("doc_type", ""),
        extracted_fields=fields_res.data or []
    )
    return {"status": "reprocessing_started", "document_id": document_id}


# ── HELPER: pick best display value for a doc type ───────────
def _pick_display_value(doc_type: str, fields: dict) -> str:
    dt = doc_type.lower()
    field_list = fields.get("fields", []) if isinstance(fields, dict) else []

    priority = {
        "invoice": ["invoice number", "total amount", "vendor name"],
        "receipt": ["receipt number", "total amount", "merchant"],
        "resume": ["email", "skills", "experience"],
        "contract": ["effective date", "parties", "agreement type"],
        "certificate": ["certificate number", "issuer", "issue date"],
        "application": ["application number", "applicant name", "status"],
        "identity": ["document number", "id number", "holder name"],
        "passport": ["passport number", "holder name", "expiry date"],
        "report": ["title", "report date", "author"],
    }

    for key, labels in priority.items():
        if key in dt:
            for f in field_list:
                for label in labels:
                    if label in f.get("label", "").lower():
                        return f.get("value", "")

    # fallback: return first field value
    if field_list:
        return field_list[0].get("value", "")
    return ""

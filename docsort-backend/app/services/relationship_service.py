# app/services/relationship_service.py
#
# Experimental people/document linking used by the optional People Map feature.
# The database uses internal ``citizens`` table identifiers; this service treats
# those rows as generic people rather than domain-specific citizen records.
#
# The service intentionally stays conservative:
#   1. It links supported person-centric documents to a person node.
#   2. It uses fuzzy name/DOB comparison to flag potential duplicate identities.
#   3. It does not invent family/property relationships from unrelated documents.

from datetime import date, datetime
from typing import Optional

from app.utils.logger import logger


PERSON_DOC_HINTS = (
    "identity",
    "passport",
    "id card",
    "resume",
    "curriculum vitae",
    "cv",
    "certificate",
    "application",
)


def _name_similarity(a: str, b: str) -> float:
    """Simple token overlap similarity, 0.0–1.0."""
    a_tokens = set(a.lower().split())
    b_tokens = set(b.lower().split())
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    return overlap / max(len(a_tokens), len(b_tokens))


def _find_field(fields: list, *labels) -> Optional[str]:
    """Find an extracted field value by label (case-insensitive)."""
    for field in fields:
        field_label = str(field.get("label", "")).lower()
        for label in labels:
            if label.lower() in field_label:
                value = str(field.get("value", "")).strip()
                return value or None
    return None


def _is_person_centric_document(doc_type: str) -> bool:
    normalized = (doc_type or "").strip().lower()
    return any(hint in normalized for hint in PERSON_DOC_HINTS)


def _normalize_identifier(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip().casefold()
    return normalized or None


def _parse_dob(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    try:
        from dateutil import parser as date_parser

        return date_parser.parse(text, dayfirst=True).date()
    except Exception:
        return None


def _extract_person_identity(doc_type: str, extracted_fields: list) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return ``(name, dob, identifier)`` for supported person-centric documents."""
    normalized = (doc_type or "").strip().lower()

    if "resume" in normalized or "curriculum vitae" in normalized or normalized == "cv":
        name = _find_field(extracted_fields, "candidate name", "applicant name", "full name", "name")
    elif "certificate" in normalized:
        name = _find_field(extracted_fields, "holder name", "candidate name", "student name", "full name", "name")
    elif "application" in normalized:
        name = _find_field(extracted_fields, "applicant name", "candidate name", "full name", "name")
    else:
        name = _find_field(extracted_fields, "holder name", "full name", "name")

    dob = _find_field(extracted_fields, "date of birth", "dob", "birth date")

    identifier = None
    if any(hint in normalized for hint in ("identity", "passport", "id card")):
        identifier = _find_field(
            extracted_fields,
            "document number",
            "id number",
            "identity number",
            "passport number",
            "identifier",
        )

    return name, dob, identifier


async def process_relationships(
    db,
    document_id: str,
    dept_id: Optional[str],
    doc_type: str,
    extracted_fields: list,
) -> dict:
    """Link supported documents to people and detect potential duplicate identities.

    This feature is deliberately optional/experimental. Unsupported document types
    simply produce no graph data and never affect the main upload workflow.

    ``citizens_created`` is an API result key that mirrors ``people_linked`` for the
    upload progress contract.
    """
    result = {
        "people_linked": 0,
        "citizens_created": 0,
        "edges_created": 0,
        "duplicate_found": False,
    }

    if not dept_id or not _is_person_centric_document(doc_type):
        return result

    try:
        name, dob_str, identifier = _extract_person_identity(doc_type, extracted_fields)
        if not name:
            return result

        person_id = await _find_or_create_citizen(
            db,
            dept_id,
            name,
            dob_str,
            document_id,
            uid_number=identifier,
        )
        if not person_id:
            return result

        result["people_linked"] = 1
        result["citizens_created"] = 1

        duplicate_id = await _check_duplicate(
            db,
            dept_id,
            name,
            dob_str,
            person_id,
            uid_number=identifier,
        )
        if duplicate_id:
            await _create_edge(
                db,
                person_id,
                duplicate_id,
                "duplicate_of",
                document_id,
                confidence=0.85,
            )
            db.table("citizens").update({"is_flagged": True}).eq("id", str(person_id)).execute()
            result["edges_created"] = 1
            result["duplicate_found"] = True

    except Exception as exc:
        # Relationship enrichment is optional and must never invalidate a fully
        # processed document. The upload pipeline records/logs this separately.
        logger.error("relationship processing failed error_type=%s", type(exc).__name__)

    return result


async def _find_or_create_citizen(
    db,
    dept_id: str,
    name: Optional[str],
    dob_str: Optional[str],
    document_id: str,
    uid_number: Optional[str] = None,
) -> Optional[str]:
    """Find/create a generic person row using the internal ``citizens`` table."""
    if not name or len(name.strip()) < 2:
        return None

    name = name.strip()

    incoming_dob = _parse_dob(dob_str)
    incoming_identifier = _normalize_identifier(uid_number)

    existing = (
        db.table("citizens")
        .select("id,full_name,dob,uid_number")
        .eq("dept_id", dept_id)
        .execute()
    )
    for row in (existing.data or []):
        existing_identifier = _normalize_identifier(row.get("uid_number"))

        # A matching strong identifier is sufficient for automatic reuse. If both
        # sides have identifiers and they conflict, do not let name similarity
        # override that stronger evidence.
        if incoming_identifier and existing_identifier:
            if incoming_identifier == existing_identifier:
                await _link_document_to_citizen(db, row["id"], document_id)
                return row["id"]
            continue

        existing_dob = _parse_dob(row.get("dob"))
        if (
            incoming_dob
            and existing_dob
            and incoming_dob == existing_dob
            and _name_similarity(row["full_name"], name) >= 0.85
        ):
            await _link_document_to_citizen(db, row["id"], document_id)
            return row["id"]

    payload = {"dept_id": dept_id, "full_name": name}
    if incoming_dob:
        payload["dob"] = incoming_dob.isoformat()
    elif dob_str:
        logger.debug("Could not parse extracted DOB; leaving it unset.")
    if uid_number and str(uid_number).strip():
        payload["uid_number"] = str(uid_number).strip()

    new_row = db.table("citizens").insert(payload).execute()
    if new_row.data:
        new_id = new_row.data[0]["id"]
        await _link_document_to_citizen(db, new_id, document_id)
        return new_id

    return None


async def _create_edge(
    db,
    from_id: str,
    to_id: str,
    edge_type: str,
    document_id: str,
    confidence: float = 1.0,
):
    """Create a graph edge if the same directional edge does not already exist."""
    check = (
        db.table("citizen_edges")
        .select("id")
        .eq("from_citizen", from_id)
        .eq("to_citizen", to_id)
        .eq("edge_type", edge_type)
        .execute()
    )

    if not check.data:
        db.table("citizen_edges").insert(
            {
                "from_citizen": from_id,
                "to_citizen": to_id,
                "edge_type": edge_type,
                "evidence_doc_id": document_id,
                "confidence": confidence,
            }
        ).execute()


async def _link_document_to_citizen(db, citizen_id: str, document_id: str):
    """Link a document to a person using the internal table/column identifiers."""
    try:
        db.table("citizen_documents").upsert(
            {
                "citizen_id": citizen_id,
                "document_id": document_id,
                "role": "subject",
            },
            on_conflict="citizen_id,document_id",
        ).execute()
    except Exception as exc:
        logger.warning("Person-document link failed error_type=%s", type(exc).__name__)


async def _check_duplicate(
    db,
    dept_id: str,
    name: str,
    dob_str: Optional[str],
    exclude_id: str,
    uid_number: Optional[str] = None,
) -> Optional[str]:
    """Return another person ID when non-conflicting evidence suggests a potential match."""
    existing = (
        db.table("citizens")
        .select("id,full_name,dob,uid_number")
        .eq("dept_id", dept_id)
        .neq("id", exclude_id)
        .execute()
    )

    incoming_identifier = _normalize_identifier(uid_number)
    incoming_dob = _parse_dob(dob_str)

    for row in (existing.data or []):
        similarity = _name_similarity(row["full_name"], name)
        if similarity < 0.80:
            continue

        existing_identifier = _normalize_identifier(row.get("uid_number"))
        if (
            incoming_identifier
            and existing_identifier
            and incoming_identifier != existing_identifier
        ):
            continue

        existing_dob = _parse_dob(row.get("dob"))
        if incoming_dob and existing_dob:
            if incoming_dob == existing_dob:
                return row["id"]
            continue

        if similarity >= 0.92:
            return row["id"]

    return None

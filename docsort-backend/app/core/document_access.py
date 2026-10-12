"""Shared document access policy.

The API uses the Supabase service-role key, so application code is the effective
policy boundary for document access. Keep read and mutation rules in one place
so routes cannot drift from the cabinet policy.
"""
from typing import Any


def scope_document_read_query(query_builder: Any, user: dict):
    """Apply the standard document read scope to a PostgREST query builder.

    Policy:
    - users without a department can only read their own documents;
    - administrators acting within their assigned department can read all documents in their department;
    - other department users can read non-private documents in their department
      plus their own private documents.

    Callers may add additional filters after this scope is applied. Keep
    :func:`can_read_document` as a defense-in-depth check when materializing
    already-fetched rows or when a route has especially complex joins.
    """
    department_id = user.get("department_id")
    user_id = user.get("id")

    if department_id:
        query_builder = query_builder.eq("department_id", department_id)
        if user.get("role") != "admin":
            query_builder = query_builder.or_(
                f"is_private.eq.false,user_id.eq.{user_id}"
            )
        return query_builder

    return query_builder.eq("user_id", user_id)


def get_readable_document(
    supabase: Any, document_id: str, user: dict, columns: str = "*"
) -> dict | None:
    """Fetch one document only if the caller currently has read access.

    This is the preferred gateway for point-document reads. It binds the
    document identifier and the shared authorization scope before executing the
    query, reducing the chance that a route fetches by ID and forgets to apply
    current document policy.
    """
    query = supabase.table("documents").select(columns).eq("id", document_id)
    result = scope_document_read_query(query, user).execute()
    return result.data[0] if result.data else None


def get_writable_document(
    supabase: Any, document_id: str, user: dict, columns: str = "*"
) -> dict | None:
    """Fetch one document only if the caller currently has mutation access.

    Mutating statements must still apply :func:`scope_document_write_query` to
    the update/delete operation itself. This gateway protects the common
    authorization preflight used before mutation-specific work.
    """
    query = supabase.table("documents").select(columns).eq("id", document_id)
    result = scope_document_write_query(query, user).execute()
    return result.data[0] if result.data else None


def can_read_document(document: dict, user: dict) -> bool:
    """Return whether ``user`` may read an already-fetched document."""
    user_id = user.get("id")
    department_id = user.get("department_id")

    if department_id:
        if str(document.get("department_id")) != str(department_id):
            return False
        if user.get("role") == "admin":
            return True
        return (not bool(document.get("is_private"))) or (
            str(document.get("user_id")) == str(user_id)
        )

    return str(document.get("user_id")) == str(user_id)


def scope_document_write_query(query_builder: Any, user: dict):
    """Apply the standard document mutation scope to a query builder.

    Mutation policy is intentionally stricter than read policy:
    - regular users may modify only documents they own in their department;
    - administrators acting within their assigned department may modify any document in their department;
    - users without a department may modify only documents they own.

    There is no separate global-admin role in the current project, so an admin
    without a department is not treated as globally privileged.
    """
    department_id = user.get("department_id")
    user_id = user.get("id")

    if department_id:
        query_builder = query_builder.eq("department_id", department_id)
        if user.get("role") != "admin":
            query_builder = query_builder.eq("user_id", user_id)
        return query_builder

    return query_builder.eq("user_id", user_id)

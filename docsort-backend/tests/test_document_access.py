"""Unit tests for the shared document access policy and point-access gateway."""
from app.core.document_access import (
    can_read_document,
    get_readable_document,
    get_writable_document,
    scope_document_read_query,
    scope_document_write_query,
)


class RecordingQuery:
    def __init__(self):
        self.ops = []

    def eq(self, column, value):
        self.ops.append(("eq", column, value))
        return self

    def or_(self, expression):
        self.ops.append(("or", expression))
        return self


def test_regular_department_user_query_includes_privacy_rule():
    query = scope_document_read_query(
        RecordingQuery(),
        {"id": "u1", "role": "user", "department_id": "dept-a"},
    )

    assert query.ops == [
        ("eq", "department_id", "dept-a"),
        ("or", "is_private.eq.false,user_id.eq.u1"),
    ]


def test_department_admin_query_is_limited_to_department_only():
    query = scope_document_read_query(
        RecordingQuery(),
        {"id": "admin-a", "role": "admin", "department_id": "dept-a"},
    )

    assert query.ops == [("eq", "department_id", "dept-a")]


def test_unassigned_user_query_is_limited_to_owned_documents():
    query = scope_document_read_query(
        RecordingQuery(),
        {"id": "u1", "role": "user", "department_id": None},
    )

    assert query.ops == [("eq", "user_id", "u1")]


def test_regular_user_visibility_allows_public_and_own_private_only():
    user = {"id": "u1", "role": "user", "department_id": "dept-a"}

    assert can_read_document(
        {"user_id": "u2", "department_id": "dept-a", "is_private": False}, user
    )
    assert can_read_document(
        {"user_id": "u1", "department_id": "dept-a", "is_private": True}, user
    )
    assert not can_read_document(
        {"user_id": "u2", "department_id": "dept-a", "is_private": True}, user
    )
    assert not can_read_document(
        {"user_id": "u1", "department_id": "dept-b", "is_private": False}, user
    )


def test_admin_visibility_allows_private_same_department_but_not_cross_department():
    admin = {"id": "admin-a", "role": "admin", "department_id": "dept-a"}

    assert can_read_document(
        {"user_id": "u2", "department_id": "dept-a", "is_private": True}, admin
    )
    assert not can_read_document(
        {"user_id": "u3", "department_id": "dept-b", "is_private": False}, admin
    )


def test_regular_department_user_write_query_requires_department_and_owner():
    query = scope_document_write_query(
        RecordingQuery(),
        {"id": "u1", "role": "user", "department_id": "dept-a"},
    )

    assert query.ops == [
        ("eq", "department_id", "dept-a"),
        ("eq", "user_id", "u1"),
    ]


def test_department_admin_write_query_is_limited_to_department():
    query = scope_document_write_query(
        RecordingQuery(),
        {"id": "admin-a", "role": "admin", "department_id": "dept-a"},
    )

    assert query.ops == [("eq", "department_id", "dept-a")]


def test_unassigned_admin_is_not_treated_as_global_writer():
    query = scope_document_write_query(
        RecordingQuery(),
        {"id": "admin-x", "role": "admin", "department_id": None},
    )

    assert query.ops == [("eq", "user_id", "admin-x")]


class GatewayResult:
    def __init__(self, data):
        self.data = data


class GatewayQuery(RecordingQuery):
    def __init__(self, data):
        super().__init__()
        self.data = data

    def select(self, columns):
        self.ops.append(("select", columns))
        return self

    def execute(self):
        self.ops.append(("execute",))
        return GatewayResult(self.data)


class GatewaySupabase:
    def __init__(self, data):
        self.query = GatewayQuery(data)

    def table(self, name):
        assert name == "documents"
        self.query.ops.append(("table", name))
        return self.query


def test_read_gateway_binds_document_id_and_current_read_scope():
    supabase = GatewaySupabase([{"id": "doc-1", "filename": "one.pdf"}])

    document = get_readable_document(
        supabase,
        "doc-1",
        {"id": "u1", "role": "user", "department_id": "dept-a"},
        "id, filename",
    )

    assert document == {"id": "doc-1", "filename": "one.pdf"}
    assert supabase.query.ops == [
        ("table", "documents"),
        ("select", "id, filename"),
        ("eq", "id", "doc-1"),
        ("eq", "department_id", "dept-a"),
        ("or", "is_private.eq.false,user_id.eq.u1"),
        ("execute",),
    ]


def test_write_gateway_binds_document_id_and_current_write_scope():
    supabase = GatewaySupabase([{"id": "doc-1"}])

    document = get_writable_document(
        supabase,
        "doc-1",
        {"id": "u1", "role": "user", "department_id": "dept-a"},
        "id",
    )

    assert document == {"id": "doc-1"}
    assert supabase.query.ops == [
        ("table", "documents"),
        ("select", "id"),
        ("eq", "id", "doc-1"),
        ("eq", "department_id", "dept-a"),
        ("eq", "user_id", "u1"),
        ("execute",),
    ]


def test_document_gateway_returns_none_when_authorized_query_has_no_row():
    supabase = GatewaySupabase([])

    document = get_readable_document(
        supabase,
        "missing",
        {"id": "u1", "role": "user", "department_id": None},
    )

    assert document is None
    assert ("eq", "user_id", "u1") in supabase.query.ops

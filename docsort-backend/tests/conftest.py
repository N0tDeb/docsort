"""Shared pytest fixtures. Sets a test JWT secret before the app is imported."""
import os
os.environ.setdefault("JWT_SECRET", "test-secret-for-pytest-32-bytes-minimum-12345")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-role-key")

import pytest


class FakeResult:
    def __init__(self, data): self.data = data


class FakeBuilder:
    """Minimal stand-in for the Supabase query builder, backed by in-memory rows."""
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self.ops = []
        self.limit_n = None
    def select(self, *a, **k): return self
    def eq(self, c, v): self.ops.append(("eq", c, v)); return self
    def or_(self, s): self.ops.append(("or", s)); return self
    def ilike(self, c, p): self.ops.append(("ilike", c, p)); return self
    def in_(self, c, vals): self.ops.append(("in", c, list(vals))); return self
    def limit(self, n): self.limit_n = n; return self

    def execute(self):
        if self.table == "document_fields":
            pat = [o[2] for o in self.ops if o[0] == "ilike"][0].strip("*").lower()
            rows = [
                {"document_id": d["id"]}
                for d in self.store["documents"]
                for f in d.get("document_fields", [])
                if pat in (f.get("value") or "").lower()
            ]
            if self.limit_n is not None:
                rows = rows[:self.limit_n]
            return FakeResult(rows)
        rows = list(self.store["documents"])
        for op in self.ops:
            if op[0] == "eq":
                rows = [d for d in rows if str(d.get(op[1])) == str(op[2])]
            elif op[0] == "in":
                rows = [d for d in rows if d["id"] in op[2]]
            elif op[0] == "or":
                expression = op[1]
                if "is_private.eq.false" in expression:
                    user_id = expression.split("user_id.eq.", 1)[1]
                    rows = [d for d in rows
                            if not d.get("is_private", False)
                            or str(d.get("user_id")) == str(user_id)]
                else:
                    term = expression.split("ilike.*")[1].split("*")[0].lower()
                    rows = [d for d in rows
                            if term in (d.get("doc_type") or "").lower()
                            or term in (d.get("filename") or "").lower()]
            elif op[0] == "ilike":
                column, pattern = op[1], op[2]
                term = pattern.strip("*").lower()
                if column == "document_fields.value":
                    rows = [d for d in rows if any(
                        term in (f.get("value") or "").lower()
                        for f in d.get("document_fields", [])
                    )]
                else:
                    rows = [d for d in rows
                            if term in str(d.get(column) or "").lower()]
        if self.limit_n is not None:
            rows = rows[:self.limit_n]
        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, documents): self.store = {"documents": documents}
    def table(self, name): return FakeBuilder(name, self.store)


@pytest.fixture
def sample_docs():
    return [
        {"id": "d1", "doc_type": "Invoice", "filename": "invoice1.pdf",
         "department_id": "dept1", "folder_id": "f1", "created_at": "2024-01-01",
         "document_fields": [{"label": "Vendor Name", "value": "Ramesh Kumar"}],
         "users": {"name": "member"}, "folders": {"name": "Finance"}},
        {"id": "d2", "doc_type": "Resume", "filename": "resume.pdf",
         "department_id": "dept1", "folder_id": "f2", "created_at": "2024-02-01",
         "document_fields": [{"label": "Candidate Name", "value": "Suresh Rao"}],
         "users": {"name": "member"}, "folders": {"name": "Human Resources"}},
        {"id": "d3", "doc_type": "Certificate", "filename": "certificate.pdf",
         "department_id": "dept1", "folder_id": "f3", "created_at": "2024-03-01",
         "document_fields": [{"label": "Holder Name", "value": "Ramesh Iyer"}],
         "users": {"name": "member"}, "folders": {"name": "Certificates"}},
        {"id": "d4", "doc_type": "Invoice", "filename": "other-invoice.pdf",
         "department_id": "dept2", "folder_id": "f4", "created_at": "2024-04-01",
         "document_fields": [{"label": "Vendor Name", "value": "Ramesh Verma"}],
         "users": {"name": "other"}, "folders": {"name": "Finance"}},
    ]



@pytest.fixture
def user_dept1():
    return {"id": "u1", "department_id": "dept1"}

@pytest.fixture(autouse=True)
def reset_rate_limiter_state():
    """Keep SlowAPI's in-memory counters isolated between tests."""
    from app.core.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()

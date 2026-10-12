"""Regression tests for department isolation in graph routes."""
import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api import graph
from app.schemas.graph_schema import EdgeCreate


DEPT_A = "11111111-1111-1111-1111-111111111111"
DEPT_B = "22222222-2222-2222-2222-222222222222"
CIT_A1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
CIT_A2 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"
CIT_B1 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1"
EDGE_A = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee1"
EDGE_CROSS = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee2"
DOC_OWN = "dddddddd-dddd-dddd-dddd-ddddddddddd1"
DOC_PEER_PRIVATE = "dddddddd-dddd-dddd-dddd-ddddddddddd2"
DOC_OTHER = "dddddddd-dddd-dddd-dddd-ddddddddddd3"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

USER_A = {"id": "u1", "role": "user", "department_id": DEPT_A, "name": "User A"}
ADMIN_A = {"id": "admin-a", "role": "admin", "department_id": DEPT_A, "name": "Admin A"}


class FakeResult:
    def __init__(self, data):
        self.data = data


class GraphBuilder:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.action = "select"
        self.columns = "*"
        self.filters = []
        self.in_filters = []
        self.or_filter = None
        self.body = None
        self.limit_value = None

    def select(self, columns="*", *args, **kwargs):
        self.action = "select"
        self.columns = columns
        return self

    def insert(self, body):
        self.action = "insert"
        self.body = dict(body)
        return self

    def delete(self):
        self.action = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def in_(self, column, values):
        self.in_filters.append((column, {str(v) for v in values}))
        return self

    def or_(self, expression):
        self.or_filter = expression
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def _matches(self, row):
        for column, value in self.filters:
            if str(row.get(column)) != str(value):
                return False
        for column, values in self.in_filters:
            if str(row.get(column)) not in values:
                return False

        if self.or_filter:
            if self.table == "documents" and self.or_filter.startswith("is_private.eq.false,user_id.eq."):
                owner = self.or_filter.split("user_id.eq.", 1)[1]
                if bool(row.get("is_private")) and str(row.get("user_id")) != owner:
                    return False
            elif self.table == "citizen_edges" and "from_citizen.eq." in self.or_filter:
                first, second = self.or_filter.split(",", 1)
                from_id = first.split("from_citizen.eq.", 1)[1]
                to_id = second.split("to_citizen.eq.", 1)[1]
                if str(row.get("from_citizen")) != from_id and str(row.get("to_citizen")) != to_id:
                    return False
        return True

    def execute(self):
        self.db.execute_calls.append(self.table)
        self.db.query_log.append({
            "table": self.table,
            "columns": self.columns,
            "filters": list(self.filters),
            "in_filters": [(column, set(values)) for column, values in self.in_filters],
        })
        rows = self.db.tables[self.table]

        if self.action == "insert":
            row = dict(self.body)
            if self.table == "citizen_edges":
                row.setdefault("id", "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee9")
                row.setdefault("created_at", NOW)
            rows.append(row)
            self.db.inserted.append((self.table, dict(row)))
            return FakeResult([dict(row)])

        matched = [row for row in rows if self._matches(row)]
        if self.limit_value is not None:
            matched = matched[: self.limit_value]

        if self.action == "delete":
            matched_ids = {id(row) for row in matched}
            self.db.tables[self.table] = [row for row in rows if id(row) not in matched_ids]
            self.db.deleted.append((self.table, [dict(row) for row in matched]))
            return FakeResult([dict(row) for row in matched])

        if self.table == "citizen_documents" and "documents(" in self.columns:
            enriched = []
            for link in matched:
                doc = next(
                    (d for d in self.db.tables["documents"] if str(d["id"]) == str(link["document_id"])),
                    None,
                )
                enriched.append({**link, "documents": dict(doc) if doc else None})
            matched = enriched
        elif self.table == "citizen_documents" and "documents(*)" in self.columns:
            enriched = []
            for link in matched:
                doc = next(
                    (d for d in self.db.tables["documents"] if str(d["id"]) == str(link["document_id"])),
                    None,
                )
                enriched.append({**link, "documents": dict(doc) if doc else None})
            matched = enriched

        if self.columns == "id":
            matched = [{"id": row["id"]} for row in matched]

        return FakeResult([dict(row) for row in matched])


class FakeGraphDB:
    def __init__(self):
        self.tables = {
            "citizens": [
                {"id": CIT_A1, "dept_id": DEPT_A, "full_name": "Alice A", "dob": None, "uid_number": None, "is_flagged": False},
                {"id": CIT_A2, "dept_id": DEPT_A, "full_name": "Alex A", "dob": None, "uid_number": None, "is_flagged": False},
                {"id": CIT_B1, "dept_id": DEPT_B, "full_name": "Bob B", "dob": None, "uid_number": None, "is_flagged": False},
            ],
            "documents": [
                {"id": DOC_OWN, "user_id": "u1", "department_id": DEPT_A, "is_private": True,
                 "doc_type": "Invoice", "filename": "own.pdf", "ocr_confidence": 0.9, "is_tampered": False},
                {"id": DOC_PEER_PRIVATE, "user_id": "u2", "department_id": DEPT_A, "is_private": True,
                 "doc_type": "Contract", "filename": "peer-private.pdf", "ocr_confidence": 0.8, "is_tampered": False},
                {"id": DOC_OTHER, "user_id": "u3", "department_id": DEPT_B, "is_private": False,
                 "doc_type": "Report", "filename": "other.pdf", "ocr_confidence": 0.7, "is_tampered": False},
            ],
            "citizen_documents": [
                {"citizen_id": CIT_A1, "document_id": DOC_OWN},
                {"citizen_id": CIT_A1, "document_id": DOC_PEER_PRIVATE},
                {"citizen_id": CIT_B1, "document_id": DOC_OTHER},
            ],
            "document_fields": [
                {"document_id": DOC_OWN, "label": "Amount", "value": "100"},
                {"document_id": DOC_PEER_PRIVATE, "label": "Party", "value": "Secret"},
                {"document_id": DOC_OTHER, "label": "Other", "value": "Outside"},
            ],
            "citizen_edges": [
                {"id": EDGE_A, "from_citizen": CIT_A1, "to_citizen": CIT_A2,
                 "edge_type": "duplicate_of", "evidence_doc_id": DOC_OWN,
                 "confidence": 0.9, "created_at": NOW},
                {"id": EDGE_CROSS, "from_citizen": CIT_A1, "to_citizen": CIT_B1,
                 "edge_type": "duplicate_of", "evidence_doc_id": DOC_OTHER,
                 "confidence": 0.8, "created_at": NOW},
            ],
        }
        self.inserted = []
        self.deleted = []
        self.execute_calls = []
        self.query_log = []

    def table(self, name):
        return GraphBuilder(self, name)


def test_department_graph_is_department_scoped_and_hides_peer_private_docs():
    db = FakeGraphDB()

    result = asyncio.run(graph.get_department_graph(user=USER_A, db=db))

    assert {str(node.id) for node in result.nodes} == {CIT_A1, CIT_A2}
    alice = next(node for node in result.nodes if str(node.id) == CIT_A1)
    assert [doc["document_id"] for doc in alice.docs] == [DOC_OWN]
    assert {str(edge.id) for edge in result.edges} == {EDGE_A}


def test_department_graph_batches_graph_data_queries():
    db = FakeGraphDB()

    result = asyncio.run(graph.get_department_graph(user=USER_A, db=db))

    assert {str(node.id) for node in result.nodes} == {CIT_A1, CIT_A2}
    assert db.execute_calls == [
        "citizens",
        "citizen_documents",
        "document_fields",
        "citizen_edges",
    ]


def test_department_graph_fetches_fields_only_for_readable_documents():
    db = FakeGraphDB()

    asyncio.run(graph.get_department_graph(user=USER_A, db=db))

    field_query = next(entry for entry in db.query_log if entry["table"] == "document_fields")
    assert field_query["in_filters"] == [("document_id", {DOC_OWN})]


def test_department_graph_query_count_does_not_grow_with_people_and_links():
    db = FakeGraphDB()
    for index in range(3, 9):
        citizen_id = f"aaaaaaaa-aaaa-aaaa-aaaa-{index:012d}"
        db.tables["citizens"].append({
            "id": citizen_id,
            "dept_id": DEPT_A,
            "full_name": f"Person {index}",
            "dob": None,
            "uid_number": None,
            "is_flagged": False,
        })
        db.tables["citizen_documents"].append({
            "citizen_id": citizen_id,
            "document_id": DOC_OWN,
        })

    result = asyncio.run(graph.get_department_graph(user=USER_A, db=db))

    assert len(result.nodes) == 8
    assert db.execute_calls == [
        "citizens",
        "citizen_documents",
        "document_fields",
        "citizen_edges",
    ]

def test_citizen_detail_rejects_other_department():
    db = FakeGraphDB()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(graph.get_citizen(CIT_B1, user=USER_A, db=db))

    assert exc.value.status_code == 404


def test_citizen_detail_filters_unreadable_linked_documents():
    db = FakeGraphDB()

    result = asyncio.run(graph.get_citizen(CIT_A1, user=USER_A, db=db))

    assert [doc["id"] for doc in result["documents"]] == [DOC_OWN]
    assert [edge["id"] for edge in result["edges"]] == [EDGE_A]


def test_create_edge_rejects_cross_department_endpoint():
    db = FakeGraphDB()
    body = EdgeCreate(
        from_citizen=UUID(CIT_A1),
        to_citizen=UUID(CIT_B1),
        edge_type="duplicate_of",
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(graph.create_edge(body, user=USER_A, db=db))

    assert exc.value.status_code == 404
    assert db.inserted == []


def test_create_edge_rejects_unreadable_evidence_document():
    db = FakeGraphDB()
    body = EdgeCreate(
        from_citizen=UUID(CIT_A1),
        to_citizen=UUID(CIT_A2),
        edge_type="duplicate_of",
        evidence_doc_id=UUID(DOC_PEER_PRIVATE),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(graph.create_edge(body, user=USER_A, db=db))

    assert exc.value.status_code == 404
    assert db.inserted == []


def test_delete_edge_rejects_cross_department_edge():
    db = FakeGraphDB()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(graph.delete_edge(EDGE_CROSS, user=USER_A, db=db))

    assert exc.value.status_code == 404
    assert db.deleted == []


def test_duplicates_return_only_edges_fully_inside_department():
    db = FakeGraphDB()

    result = asyncio.run(graph.get_duplicates(user=USER_A, db=db))

    assert [edge["id"] for edge in result] == [EDGE_A]


def test_regular_user_cannot_reprocess_peer_document():
    db = FakeGraphDB()
    tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(graph.reprocess_document(DOC_PEER_PRIVATE, tasks, user=USER_A, db=db))

    assert exc.value.status_code == 404
    assert tasks.tasks == []


def test_owner_can_reprocess_own_document_with_resolved_department():
    db = FakeGraphDB()
    tasks = BackgroundTasks()

    result = asyncio.run(graph.reprocess_document(DOC_OWN, tasks, user=USER_A, db=db))

    assert result == {"status": "reprocessing_started", "document_id": DOC_OWN}
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].kwargs["dept_id"] == DEPT_A
    assert tasks.tasks[0].kwargs["document_id"] == DOC_OWN


def test_create_edge_allows_same_department_citizens():
    db = FakeGraphDB()
    body = EdgeCreate(
        from_citizen=UUID(CIT_A1),
        to_citizen=UUID(CIT_A2),
        edge_type="sibling_of",
    )

    result = asyncio.run(graph.create_edge(body, user=USER_A, db=db))

    assert str(result.from_citizen) == CIT_A1
    assert str(result.to_citizen) == CIT_A2
    assert db.inserted[-1][0] == "citizen_edges"


def test_delete_edge_allows_edge_fully_inside_department():
    db = FakeGraphDB()

    result = asyncio.run(graph.delete_edge(EDGE_A, user=USER_A, db=db))

    assert result == {"deleted": True}
    assert db.deleted[-1][0] == "citizen_edges"
    assert EDGE_A not in {row["id"] for row in db.tables["citizen_edges"]}


def test_empty_department_graph_returns_no_fabricated_demo_identities():
    db = FakeGraphDB()
    db.tables["citizens"] = []
    db.tables["citizen_documents"] = []
    db.tables["citizen_edges"] = []

    result = asyncio.run(graph.get_department_graph(user=USER_A, db=db))

    assert result.nodes == []
    assert result.edges == []

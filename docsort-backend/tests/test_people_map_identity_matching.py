"""Regression tests for conservative People Map identity reuse."""

import asyncio

from app.services import relationship_service as relationships


class Result:
    def __init__(self, data):
        self.data = data


class CitizensQuery:
    def __init__(self, db):
        self.db = db
        self.mode = "select"
        self.payload = None
        self.filters = []

    def select(self, _columns):
        self.mode = "select"
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def neq(self, field, value):
        self.filters.append(("neq", field, value))
        return self

    def insert(self, payload):
        self.mode = "insert"
        self.payload = dict(payload)
        return self

    def execute(self):
        if self.mode == "select":
            rows = self.db.rows
            for operator, field, value in self.filters:
                if operator == "eq":
                    rows = [row for row in rows if row.get(field) == value]
                else:
                    rows = [row for row in rows if row.get(field) != value]
            return Result([dict(row) for row in rows])

        new_row = {"id": f"person-{len(self.db.rows) + 1}", **self.payload}
        self.db.rows.append(new_row)
        self.db.inserted.append(dict(new_row))
        return Result([dict(new_row)])


class CitizensDB:
    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]
        self.inserted = []

    def table(self, name):
        assert name == "citizens"
        return CitizensQuery(self)


async def _no_link(*_args, **_kwargs):
    return None


def _find(db, *, name="Asha Rao", dob=None, uid=None):
    return asyncio.run(
        relationships._find_or_create_citizen(
            db,
            "dept-1",
            name,
            dob,
            "doc-new",
            uid_number=uid,
        )
    )


def test_conflicting_dob_prevents_name_only_auto_merge(monkeypatch):
    monkeypatch.setattr(relationships, "_link_document_to_citizen", _no_link)
    db = CitizensDB(
        [
            {
                "id": "person-existing",
                "dept_id": "dept-1",
                "full_name": "Asha Rao",
                "dob": "1990-01-02",
                "uid_number": None,
            }
        ]
    )

    person_id = _find(db, dob="1995-06-07")

    assert person_id != "person-existing"
    assert db.inserted[0]["dob"] == "1995-06-07"


def test_conflicting_strong_identifiers_prevent_name_auto_merge(monkeypatch):
    monkeypatch.setattr(relationships, "_link_document_to_citizen", _no_link)
    db = CitizensDB(
        [
            {
                "id": "person-existing",
                "dept_id": "dept-1",
                "full_name": "Asha Rao",
                "dob": None,
                "uid_number": "ID-111",
            }
        ]
    )

    person_id = _find(db, uid="ID-222")

    assert person_id != "person-existing"
    assert db.inserted[0]["uid_number"] == "ID-222"


def test_exact_strong_identifier_can_reuse_despite_name_variation(monkeypatch):
    monkeypatch.setattr(relationships, "_link_document_to_citizen", _no_link)
    db = CitizensDB(
        [
            {
                "id": "person-existing",
                "dept_id": "dept-1",
                "full_name": "Asha Meera Rao",
                "dob": None,
                "uid_number": "PASS-2048",
            }
        ]
    )

    person_id = _find(db, name="Asha Rao", uid=" pass-2048 ")

    assert person_id == "person-existing"
    assert db.inserted == []


def test_similar_name_with_compatible_dob_reuses_existing_person(monkeypatch):
    monkeypatch.setattr(relationships, "_link_document_to_citizen", _no_link)
    db = CitizensDB(
        [
            {
                "id": "person-existing",
                "dept_id": "dept-1",
                "full_name": "Rao Asha",
                "dob": "2001-03-04",
                "uid_number": None,
            }
        ]
    )

    person_id = _find(db, name="Asha Rao", dob="04/03/2001")

    assert person_id == "person-existing"
    assert db.inserted == []


def test_name_only_similarity_does_not_auto_merge(monkeypatch):
    monkeypatch.setattr(relationships, "_link_document_to_citizen", _no_link)
    db = CitizensDB(
        [
            {
                "id": "person-existing",
                "dept_id": "dept-1",
                "full_name": "Asha Rao",
                "dob": None,
                "uid_number": None,
            }
        ]
    )

    person_id = _find(db)

    assert person_id != "person-existing"
    assert db.inserted[0]["full_name"] == "Asha Rao"


def test_conflicting_identifiers_are_not_flagged_as_name_only_duplicate():
    db = CitizensDB(
        [
            {
                "id": "person-existing",
                "dept_id": "dept-1",
                "full_name": "Asha Rao",
                "dob": None,
                "uid_number": "ID-111",
            }
        ]
    )

    duplicate_id = asyncio.run(
        relationships._check_duplicate(
            db,
            "dept-1",
            "Asha Rao",
            None,
            "person-new",
            uid_number="ID-222",
        )
    )

    assert duplicate_id is None


def test_name_only_similarity_remains_a_potential_match_signal():
    db = CitizensDB(
        [
            {
                "id": "person-existing",
                "dept_id": "dept-1",
                "full_name": "Asha Rao",
                "dob": None,
                "uid_number": None,
            }
        ]
    )

    duplicate_id = asyncio.run(
        relationships._check_duplicate(
            db,
            "dept-1",
            "Asha Rao",
            None,
            "person-new",
        )
    )

    assert duplicate_id == "person-existing"

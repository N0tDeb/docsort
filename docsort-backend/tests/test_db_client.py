"""Unit tests for the custom Supabase query builder (rec #5).

These pin the PostgREST query construction so future edits to the hand-rolled
client can't silently change what gets sent to the database. No network used —
we assert on _build_params()/_url only.
"""
from app.core.database import _QueryBuilder


def qb(table="documents"):
    return _QueryBuilder("http://sb.local", table, {}, object())


def test_url_targets_rest_table():
    assert qb("users")._url == "http://sb.local/rest/v1/users"


def test_eq_filter():
    p = qb().select("*").eq("email", "a@b.com")._build_params()
    assert p["email"] == "eq.a@b.com" and p["select"] == "*"


def test_ilike_filter():
    p = qb().select("*").ilike("value", "*ram*")._build_params()
    assert p["value"] == "ilike.*ram*"


def test_is_null_filter():
    p = qb().select("*").is_("department_id", "null")._build_params()
    assert p["department_id"] == "is.null"


def test_in_filter():
    p = qb().select("*").in_("id", ["a", "b", "c"])._build_params()
    assert p["id"] == "in.(a,b,c)"


def test_or_filter():
    p = qb().select("*").or_("doc_type.ilike.*x*,filename.ilike.*x*")._build_params()
    assert p["or"] == "(doc_type.ilike.*x*,filename.ilike.*x*)"


def test_order_desc():
    p = qb().select("*").order("created_at", desc=True)._build_params()
    assert p["order"] == "created_at.desc"


def test_range_becomes_offset_limit():
    p = qb().select("*").range(0, 9)._build_params()
    assert p["offset"] == "0" and p["limit"] == "10"


def test_chaining_is_fluent():
    b = qb().select("*").eq("department_id", "d1").ilike("filename", "*pdf*").limit(5)
    p = b._build_params()
    assert p["department_id"] == "eq.d1" and p["filename"] == "ilike.*pdf*" and p["limit"] == "5"



def test_repeated_filters_on_same_column_are_preserved():
    p = qb().select("*").gte("created_at", "2026-01-01").lte("created_at", "2026-12-31")._build_params()
    assert p["created_at"] == ["gte.2026-01-01", "lte.2026-12-31"]


def test_ilike_and_exact_filter_on_same_column_are_both_preserved():
    p = qb().select("*").ilike("doc_type", "*invoice*").eq("doc_type", "Invoice")._build_params()
    assert p["doc_type"] == ["ilike.*invoice*", "eq.Invoice"]

def test_upsert_on_conflict_is_forwarded_to_postgrest():
    b = qb("citizen_documents").upsert(
        {"citizen_id": "c1", "document_id": "d1", "role": "subject"},
        on_conflict="citizen_id,document_id",
    )
    p = b._build_params()
    assert b._action == "upsert"
    assert p["on_conflict"] == "citizen_id,document_id"
    assert "resolution=merge-duplicates" in b._headers["Prefer"]


def test_upsert_without_conflict_target_remains_backward_compatible():
    b = qb().upsert({"id": "d1"})
    assert "on_conflict" not in b._build_params()


def test_rpc_builder_targets_postgrest_function_and_preserves_body():
    from app.core.database import SupabaseClient

    client = SupabaseClient("http://sb.local", "service-key")
    rpc = client.rpc(
        "replace_document_fields",
        {"p_document_id": "d1", "p_fields": [{"label": "amount", "value": "10"}]},
    )

    assert rpc._url == "http://sb.local/rest/v1/rpc/replace_document_fields"
    assert rpc._body["p_document_id"] == "d1"
    assert rpc._body["p_fields"][0]["label"] == "amount"
    assert rpc._headers["Prefer"] == "return=representation"


def test_rpc_execute_posts_to_postgrest(monkeypatch):
    import app.core.database as database

    captured = {}

    class Response:
        status_code = 200
        content = b'[{"id":"f1"}]'
        text = content.decode()
        headers = {}

        def json(self):
            return [{"id": "f1"}]

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, headers=None):
            captured.update(url=url, json=json, headers=headers)
            return Response()

    monkeypatch.setattr(database.httpx, "Client", Client)
    client = database.SupabaseClient("http://sb.local", "service-key")
    result = client.rpc("replace_document_fields", {"p_document_id": "d1", "p_fields": []}).execute()

    assert captured["url"] == "http://sb.local/rest/v1/rpc/replace_document_fields"
    assert captured["json"] == {"p_document_id": "d1", "p_fields": []}
    assert captured["headers"]["Authorization"] == "Bearer service-key"
    assert result.data == [{"id": "f1"}]


def test_supabase_client_reuses_one_http_transport_for_rest_rpc_and_storage(monkeypatch):
    import app.core.database as database

    constructions = []
    requests = []

    class Response:
        status_code = 200
        content = b'[]'
        text = '[]'
        headers = {}

        def json(self):
            return []

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *args, **kwargs):
            constructions.append((args, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, url, **kwargs):
            requests.append((method, url, kwargs))
            return Response()

        def get(self, url, **kwargs):
            requests.append(("GET", url, kwargs))
            return Response()

        def post(self, url, **kwargs):
            requests.append(("POST", url, kwargs))
            return Response()

        def patch(self, url, **kwargs):
            requests.append(("PATCH", url, kwargs))
            return Response()

        def delete(self, url, **kwargs):
            requests.append(("DELETE", url, kwargs))
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(database.httpx, "Client", Client)

    client = database.SupabaseClient("http://sb.local", "service-key")
    client.table("documents").select("id").execute()
    client.rpc("replace_document_fields", {"p_document_id": "d1", "p_fields": []}).execute()
    client.storage.from_("documents").download("u1/file.pdf")

    assert len(constructions) == 1
    assert [method for method, _, _ in requests] == ["GET", "POST", "GET"]


def test_supabase_client_close_closes_reusable_transport(monkeypatch):
    import app.core.database as database

    closed = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            closed.append(True)

    monkeypatch.setattr(database.httpx, "Client", Client)

    client = database.SupabaseClient("http://sb.local", "service-key")
    client.close()

    assert closed == [True]


def test_query_retry_reuses_the_same_transport_after_read_timeout(monkeypatch):
    import app.core.database as database

    constructions = []
    attempts = []

    class Response:
        status_code = 200
        content = b'[]'
        text = '[]'
        headers = {}

        def json(self):
            return []

    class Client:
        def __init__(self, *args, **kwargs):
            constructions.append(self)

        def get(self, url, **kwargs):
            attempts.append(url)
            if len(attempts) == 1:
                raise database.httpx.ReadTimeout("temporary timeout")
            return Response()

        def close(self):
            pass

    import time

    monkeypatch.setattr(database.httpx, "Client", Client)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    client = database.SupabaseClient("http://sb.local", "service-key")
    result = client.table("documents").select("id").execute()

    assert result.data == []
    assert len(attempts) == 2
    assert len(constructions) == 1


def test_storage_download_to_file_streams_chunks_without_response_buffering(monkeypatch):
    import io
    import app.core.database as database

    captured = {}

    class Response:
        def raise_for_status(self):
            captured["raise_for_status"] = True

        def iter_bytes(self, chunk_size):
            captured["chunk_size"] = chunk_size
            yield b"abc"
            yield b""
            yield b"defg"

    class StreamContext:
        def __enter__(self):
            captured["entered"] = True
            return Response()

        def __exit__(self, exc_type, exc, tb):
            captured["exited"] = True
            return False

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def stream(self, method, url, **kwargs):
            captured.update(method=method, url=url, kwargs=kwargs)
            return StreamContext()

        def close(self):
            pass

    monkeypatch.setattr(database.httpx, "Client", Client)

    client = database.SupabaseClient("http://sb.local", "service-key")
    sink = io.BytesIO()
    written = client.storage.from_("documents").download_to_file(
        "u1/file.pdf",
        sink,
        chunk_size=3,
    )

    assert written == 7
    assert sink.getvalue() == b"abcdefg"
    assert captured["method"] == "GET"
    assert captured["url"] == "http://sb.local/storage/v1/object/documents/u1/file.pdf"
    assert captured["kwargs"]["timeout"] == 30
    assert captured["chunk_size"] == 3
    assert captured["raise_for_status"] is True
    assert captured["entered"] is True and captured["exited"] is True


def test_storage_compute_sha256_streams_without_materializing_content(monkeypatch):
    import hashlib
    import app.core.database as database

    captured = {"content_accessed": False}
    chunks = [b"abc", b"defg"]

    class Response:
        status_code = 200

        @property
        def content(self):
            captured["content_accessed"] = True
            raise AssertionError("compute_sha256 must not materialize response.content")

        def raise_for_status(self):
            captured["raise_for_status"] = True

        def iter_bytes(self, chunk_size):
            captured["chunk_size"] = chunk_size
            yield from chunks

    class StreamContext:
        def __enter__(self):
            captured["entered"] = True
            return Response()

        def __exit__(self, exc_type, exc, tb):
            captured["exited"] = True
            return False

    class Client:
        def __init__(self, *args, **kwargs): pass
        def stream(self, method, url, **kwargs):
            captured.update(method=method, url=url, kwargs=kwargs)
            return StreamContext()
        def close(self): pass

    monkeypatch.setattr(database.httpx, "Client", Client)

    client = database.SupabaseClient("http://sb.local", "service-key")
    digest = client.storage.from_("documents").compute_sha256("u1/file.pdf", chunk_size=3)

    assert digest == hashlib.sha256(b"abcdefg").hexdigest()
    assert captured["content_accessed"] is False
    assert captured["method"] == "GET"
    assert captured["url"] == "http://sb.local/storage/v1/object/documents/u1/file.pdf"
    assert captured["kwargs"]["timeout"] == 30
    assert captured["chunk_size"] == 3
    assert captured["raise_for_status"] is True
    assert captured["entered"] is True and captured["exited"] is True


def test_storage_signed_url_targets_object_sign_endpoint(monkeypatch):
    import app.core.database as database

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "signedURL": "/storage/v1/object/sign/docsort/documents/u1/My%20file.pdf?token=test"
            }

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, url, **kwargs):
            captured.update(method=method, url=url, kwargs=kwargs)
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(database.httpx, "Client", Client)

    client = database.SupabaseClient("http://sb.local", "service-key")
    result = client.storage.from_("docsort").create_signed_url(
        "documents/u1/My file.pdf",
        expires_in=900,
    )

    assert captured["method"] == "POST"
    assert captured["url"] == (
        "http://sb.local/storage/v1/object/sign/"
        "docsort/documents/u1/My%20file.pdf"
    )
    assert captured["kwargs"]["json"] == {"expiresIn": 900}
    assert result["signedURL"].startswith("/storage/v1/object/sign/")

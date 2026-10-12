import hashlib
import httpx
from urllib.parse import quote
from typing import Any, Optional
from app.core.config import settings



class _Result:
    def __init__(self, data, count=None):
        self.data  = data if data is not None else []
        self.count = count


class _QueryBuilder:
    def __init__(self, base_url: str, table: str, headers: dict, client: httpx.Client):
        self._url     = f"{base_url}/rest/v1/{table}"
        self._headers = headers
        self._client  = client
        self._filters: list[str] = []
        self._selects: str = "*"
        self._order:   Optional[str] = None
        self._range_start: Optional[int] = None
        self._range_end:   Optional[int] = None
        self._limit:  Optional[int] = None
        self._action  = "select"
        self._body:    Any = None
        self._count_mode: Optional[str] = None
        self._on_conflict: Optional[str] = None

    def select(self, columns: str = "*", count: Optional[str] = None):
        self._selects = columns
        self._action  = "select"
        if count:
            self._count_mode = count
            self._headers = {**self._headers, "Prefer": f"count={count}"}
        return self

    def insert(self, data: dict):
        self._action = "insert"
        self._body   = data
        self._headers = {**self._headers, "Prefer": "return=representation"}
        return self

    def update(self, data: dict):
        self._action = "update"
        self._body   = data
        self._headers = {**self._headers, "Prefer": "return=representation"}
        return self

    def delete(self):
        self._action = "delete"
        self._headers = {**self._headers, "Prefer": "return=representation"}
        return self

    def upsert(self, data: dict, on_conflict: Optional[str] = None):
        self._action = "upsert"
        self._body   = data
        self._on_conflict = on_conflict
        self._headers = {**self._headers, "Prefer": "resolution=merge-duplicates,return=representation"}
        return self

    def eq(self, col: str, val: Any):
        self._filters.append(f"{col}=eq.{val}")
        return self

    def neq(self, col: str, val: Any):
        self._filters.append(f"{col}=neq.{val}")
        return self

    def is_(self, col: str, val: Any):
        """Add a PostgREST ``is`` filter (primarily for SQL NULL checks)."""
        self._filters.append(f"{col}=is.{val}")
        return self

    def gt(self, col: str, val: Any):
        self._filters.append(f"{col}=gt.{val}")
        return self

    def gte(self, col: str, val: Any):
        self._filters.append(f"{col}=gte.{val}")
        return self

    def lt(self, col: str, val: Any):
        self._filters.append(f"{col}=lt.{val}")
        return self

    def lte(self, col: str, val: Any):
        self._filters.append(f"{col}=lte.{val}")
        return self

    def ilike(self, col: str, pattern: str):
        self._filters.append(f"{col}=ilike.{pattern}")
        return self

    def in_(self, col: str, values: list):
        vals = ",".join(str(v) for v in values)
        self._filters.append(f"{col}=in.({vals})")
        return self

    def order(self, col: str, desc: bool = False):
        direction = "desc" if desc else "asc"
        self._order = f"{col}.{direction}"
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def range(self, start: int, end: int):
        self._range_start = start
        self._range_end   = end
        return self

    def or_(self, filter_str: str):
        self._filters.append(f"or=({filter_str})")
        return self

    def _build_params(self) -> dict:
        params: dict = {}
        if self._action == "select":
            params["select"] = self._selects
        for f in self._filters:
            col, expr = f.split("=", 1)
            # PostgREST allows repeated query parameters on the same column
            # (for example created_at=gte...&created_at=lte...).  Preserve all
            # of them instead of silently overwriting the earlier predicate.
            if col in params:
                existing = params[col]
                if isinstance(existing, list):
                    existing.append(expr)
                else:
                    params[col] = [existing, expr]
            else:
                params[col] = expr
        if self._on_conflict:
            params["on_conflict"] = self._on_conflict
        if self._order:
            params["order"] = self._order
        if self._limit is not None:
            params["limit"] = str(self._limit)
        if self._range_start is not None:
            params["offset"] = str(self._range_start)
            params["limit"]  = str(self._range_end - self._range_start + 1)
        return params

    def execute(self) -> _Result:
        import time
        params  = self._build_params()
        headers = {**self._headers}
        if self._count_mode:
            headers["Prefer"] = f"count={self._count_mode}"

        last_exc = None
        for attempt in range(3):
            try:
                if self._action == "select":
                    r = self._client.get(self._url, params=params, headers=headers)
                elif self._action == "insert":
                    r = self._client.post(self._url, json=self._body, params=params, headers=headers)
                elif self._action == "update":
                    r = self._client.patch(self._url, json=self._body, params=params, headers=headers)
                elif self._action == "delete":
                    r = self._client.delete(self._url, params=params, headers=headers)
                elif self._action == "upsert":
                    r = self._client.post(self._url, json=self._body, params=params, headers=headers)
                else:
                    raise ValueError(f"Unknown action: {self._action}")
                break  # success â€” exit retry loop
            except httpx.ReadTimeout as e:
                last_exc = e
                if attempt < 2:
                    time.sleep(1)
                continue
        else:
            raise RuntimeError(f"DB timeout after 3 attempts on {self._action} {self._url}") from last_exc
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} on {self._action} {self._url}: {r.text}")
        data = r.json() if r.content else []
        if isinstance(data, dict) and "message" in data:
            raise RuntimeError(data["message"])

        count = None
        if self._count_mode and "content-range" in r.headers:
            content_range = r.headers["content-range"]
            total_part = content_range.split("/")[-1]
            count = int(total_part) if total_part != "*" else None

        return _Result(data if isinstance(data, list) else [data], count=count)


class _RpcBuilder:
    def __init__(
        self,
        base_url: str,
        function: str,
        headers: dict,
        client: httpx.Client,
        params: Optional[dict] = None,
    ):
        self._url = f"{base_url}/rest/v1/rpc/{function}"
        self._headers = {**headers, "Prefer": "return=representation"}
        self._body = params or {}
        self._client = client

    def execute(self) -> _Result:
        import time

        last_exc = None
        for attempt in range(3):
            try:
                r = self._client.post(self._url, json=self._body, headers=self._headers)
                break
            except httpx.ReadTimeout as e:
                last_exc = e
                if attempt < 2:
                    time.sleep(1)
                continue
        else:
            raise RuntimeError(f"DB timeout after 3 attempts on rpc {self._url}") from last_exc

        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} on rpc {self._url}: {r.text}")
        data = r.json() if r.content else []
        if isinstance(data, dict) and "message" in data:
            raise RuntimeError(data["message"])
        return _Result(data if isinstance(data, list) else [data])


class _StorageBucket:
    def __init__(self, base_url: str, bucket: str, headers: dict, client: httpx.Client | None = None):
        self._url     = f"{base_url}/storage/v1/object"
        self._bucket  = bucket
        self._headers = headers
        self._client  = client

    def _object_url(self, path: str, *, signing: bool = False) -> str:
        # Object keys may contain spaces/Unicode but must never contain path
        # traversal segments. Encoding each segment also prevents user-controlled
        # filename characters from changing the HTTP request target.
        if not isinstance(path, str) or "\\" in path or any(ord(ch) < 32 for ch in path):
            raise ValueError("Invalid storage object path")
        segments = path.split("/")
        if not segments or any(segment in {"", ".", ".."} for segment in segments):
            raise ValueError("Invalid storage object path")
        encoded_path = "/".join(quote(segment, safe="") for segment in segments)
        base = f"{self._url}/sign" if signing else self._url
        return f"{base}/{quote(self._bucket, safe='')}/{encoded_path}"

    def _request(self, method: str, url: str, *, timeout: float, **kwargs):
        if self._client is None:
            raise RuntimeError("Storage transport is not configured")
        return self._client.request(method, url, timeout=timeout, **kwargs)

    def upload(self, path: str, data: bytes, options: dict = None):
        url  = self._object_url(path)
        hdrs = {**self._headers, "Content-Type": (options or {}).get("content-type", "application/octet-stream")}
        r = self._request("POST", url, timeout=30, content=data, headers=hdrs)
        r.raise_for_status()
        return r.json()

    def create_signed_url(self, path: str, expires_in: int = 3600) -> dict:
        url = self._object_url(path, signing=True)
        r = self._request("POST", url, timeout=10, json={"expiresIn": expires_in}, headers=self._headers)
        r.raise_for_status()
        return r.json()

    def remove(self, paths: list):
        url = f"{self._url}/{self._bucket}"
        r = self._request("DELETE", url, timeout=10, json={"prefixes": paths}, headers=self._headers)
        r.raise_for_status()
        return r.json()

    def download(self, path: str) -> bytes:
        url = self._object_url(path)
        r = self._request("GET", url, timeout=30, headers=self._headers)
        r.raise_for_status()
        return r.content

    def download_to_file(
        self,
        path: str,
        fileobj,
        *,
        chunk_size: int = 64 * 1024,
    ) -> int:
        """Stream one private object into a writable binary file-like object.

        Unlike :meth:`download`, this path never materializes ``response.content``.
        It is used when callers need bounded-memory staging while still requiring
        the complete source object before exposing a successful response.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if self._client is None:
            raise RuntimeError("Storage transport is not configured")

        url = self._object_url(path)
        total = 0
        with self._client.stream(
            "GET",
            url,
            timeout=30,
            headers=self._headers,
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(chunk_size=chunk_size):
                if not chunk:
                    continue
                fileobj.write(chunk)
                total += len(chunk)
        return total

    def compute_sha256(
        self,
        path: str,
        *,
        chunk_size: int = 64 * 1024,
    ) -> str:
        """Stream one private object through SHA-256 without buffering it.

        Delivery-time integrity checks use this path before issuing a signed
        public URL, where the source bytes must be verified without loading the
        complete object into RAM.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if self._client is None:
            raise RuntimeError("Storage transport is not configured")

        url = self._object_url(path)
        digest = hashlib.sha256()
        with self._client.stream(
            "GET",
            url,
            timeout=30,
            headers=self._headers,
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(chunk_size=chunk_size):
                if chunk:
                    digest.update(chunk)
        return digest.hexdigest()


class _Storage:
    def __init__(self, base_url: str, headers: dict, client: httpx.Client):
        self._base_url = base_url
        self._headers  = headers
        self._client   = client

    def from_(self, bucket: str) -> _StorageBucket:
        return _StorageBucket(self._base_url, bucket, self._headers, self._client)



class SupabaseClient:
    """Lightweight httpx-based Supabase REST client â€” no C++ required."""

    def __init__(self, url: str, key: str):
        self._url     = url.rstrip("/")
        self._key     = key
        self._headers = {
            "apikey":        key,
            "Authorization": f"Bearer {key}",
            "Content-Type":  "application/json",
        }
        self._http = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))
        self.storage = _Storage(self._url, self._headers, self._http)

    def table(self, name: str) -> _QueryBuilder:
        return _QueryBuilder(self._url, name, dict(self._headers), self._http)

    def rpc(self, function: str, params: Optional[dict] = None) -> _RpcBuilder:
        return _RpcBuilder(self._url, function, dict(self._headers), self._http, params)

    def check_database_ready(self, *, timeout: float = 2.0) -> None:
        """Probe PostgREST with a minimal, non-retrying database read.

        Readiness must fail quickly instead of inheriting the normal query
        adapter's 30-second timeout and retry policy.  The response body is not
        exposed to callers; only success/failure matters.
        """
        response = self._http.get(
            f"{self._url}/rest/v1/departments",
            params={"select": "id", "limit": "1"},
            headers=self._headers,
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError("database readiness check failed")

    def check_storage_ready(self, *, bucket: str = "docsort", timeout: float = 2.0) -> None:
        """Probe the required private Storage bucket without reading an object."""
        encoded_bucket = quote(bucket, safe="")
        response = self._http.get(
            f"{self._url}/storage/v1/bucket/{encoded_bucket}",
            headers=self._headers,
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError("storage readiness check failed")

    def close(self) -> None:
        """Close the shared HTTP transport and its connection pool."""
        self._http.close()


_client: SupabaseClient | None = None


def get_supabase_sync() -> SupabaseClient:
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_service_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        _client = SupabaseClient(settings.supabase_url, settings.supabase_service_key)
    return _client


async def get_supabase() -> SupabaseClient:
    """FastAPI dependency â€” yields the Supabase client."""
    return get_supabase_sync()


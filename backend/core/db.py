"""Database access.

`get_client()` returns a supabase-py client when SUPABASE_URL is set, otherwise an in-memory
fake that supports the small query surface core/ uses:

    client.table(name).insert(row | [rows]).execute().data
    client.table(name).select("*").eq(col, v).is_(col, "null").in_(col, [..]).order(col, desc=True).limit(n).execute().data
    client.table(name).update({...}).eq(col, v).is_(col, "null").execute().data   # returns updated rows

Tests call `use_fake()` / `reset_fake()`.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from config import settings


class _Result:
    def __init__(self, data: list[dict]):
        self.data = data


class _FakeQuery:
    def __init__(self, store: dict[str, list[dict]], table: str):
        self._store = store
        self._table = table
        self._filters: list[tuple[str, str, Any]] = []
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._op: str = "select"
        self._payload: Any = None

    # --- builders -------------------------------------------------------
    def select(self, _cols: str = "*"):
        self._op = "select"
        return self

    def insert(self, rows: dict | list[dict]):
        self._op = "insert"
        self._payload = rows
        return self

    def update(self, values: dict):
        self._op = "update"
        self._payload = values
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col: str, val: Any):
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col: str, val: Any):
        self._filters.append(("neq", col, val))
        return self

    def is_(self, col: str, val: Any):
        self._filters.append(("is", col, val))
        return self

    def in_(self, col: str, vals: list):
        self._filters.append(("in", col, list(vals)))
        return self

    def lte(self, col: str, val: Any):
        self._filters.append(("lte", col, val))
        return self

    def gte(self, col: str, val: Any):
        self._filters.append(("gte", col, val))
        return self

    def order(self, col: str, desc: bool = False):
        self._order = (col, desc)
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    # --- execution ------------------------------------------------------
    def _match(self, row: dict) -> bool:
        for op, col, val in self._filters:
            cur = row.get(col)
            if op == "eq" and not (cur == val or str(cur) == str(val)):
                return False
            if op == "neq" and (cur == val or str(cur) == str(val)):
                return False
            if op == "is":
                if val in (None, "null") and cur is not None:
                    return False
                if val not in (None, "null") and cur != val:
                    return False
            if op == "in" and cur not in val and str(cur) not in [str(v) for v in val]:
                return False
            if op == "lte" and not (cur is not None and str(cur) <= str(val)):
                return False
            if op == "gte" and not (cur is not None and str(cur) >= str(val)):
                return False
        return True

    def execute(self) -> _Result:
        rows = self._store.setdefault(self._table, [])
        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            out = []
            for r in payload:
                row = dict(r)
                row.setdefault("id", str(uuid.uuid4()))
                row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                rows.append(row)
                out.append(copy.deepcopy(row))
            return _Result(out)

        matched = [r for r in rows if self._match(r)]
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
            return _Result(copy.deepcopy(matched))
        if self._op == "delete":
            self._store[self._table] = [r for r in rows if r not in matched]
            return _Result(copy.deepcopy(matched))

        if self._order:
            col, desc = self._order
            matched.sort(key=lambda r: (r.get(col) is None, str(r.get(col))), reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        return _Result(copy.deepcopy(matched))


class FakeClient:
    """In-memory stand-in for supabase.Client."""

    def __init__(self):
        self.store: dict[str, list[dict]] = {}

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self.store, name)


_client: Any = None


def use_fake() -> FakeClient:
    """Force the in-memory client (tests)."""
    global _client
    _client = FakeClient()
    return _client


def reset_fake() -> FakeClient:
    return use_fake()


def get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    if settings.gary_fake_db or not settings.supabase_url:
        _client = FakeClient()
        return _client
    from supabase import create_client  # imported lazily so tests never need network

    _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

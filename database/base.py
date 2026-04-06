from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from database.errors import StorageUnavailableError

_pool_registry_lock = threading.Lock()
_pool_registry: dict[str, object] = {}


def get_shared_pool(dsn: str):
    """Return (or create) a shared ConnectionPool for *dsn*.

    All PooledDatabase subclasses using the same DSN share one pool,
    keeping the total connection count bounded (min=2, max=10) instead
    of multiplied per-class.
    """
    with _pool_registry_lock:
        pool = _pool_registry.get(dsn)
        if pool is None:
            from psycopg_pool import ConnectionPool  # type: ignore

            pool = ConnectionPool(dsn, min_size=2, max_size=10, open=True)
            _pool_registry[dsn] = pool
        return pool


def close_shared_pool(dsn: str) -> None:
    """Close and discard the shared pool for *dsn* (used on DSN change)."""
    with _pool_registry_lock:
        pool = _pool_registry.pop(dsn, None)
    if pool is not None:
        try:
            pool.close()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


class PooledDatabase(ABC):
    """Base class with lazy PostgreSQL connection pool and schema bootstrap."""

    def __init__(self, dsn: str) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise ValueError("postgres_dsn обязателен")
        self._init_lock = threading.Lock()
        self._initialized = False

    def _get_pool(self):
        return get_shared_pool(self._dsn)

    def _connect(self):
        return self._get_pool().connection()

    @abstractmethod
    def _schema_sql(self) -> str:
        """Return the SQL to bootstrap the schema."""

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            query = self._schema_sql()
            try:
                with self._connect() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(query)
                    conn.commit()
            except Exception as exc:  # noqa: BLE001
                raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc
            self._initialized = True


__all__ = ["PooledDatabase", "get_shared_pool", "close_shared_pool"]

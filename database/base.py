from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from database.errors import StorageUnavailableError


class PooledDatabase(ABC):
    """Base class with lazy PostgreSQL connection pool and schema bootstrap."""

    def __init__(self, dsn: str) -> None:
        self._dsn = str(dsn or "").strip()
        if not self._dsn:
            raise ValueError("postgres_dsn обязателен")
        self._init_lock = threading.Lock()
        self._initialized = False
        self._pool = None

    def _get_pool(self):
        if self._pool is None:
            from psycopg_pool import ConnectionPool  # type: ignore

            self._pool = ConnectionPool(self._dsn, min_size=2, max_size=10, open=True)
        return self._pool

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


__all__ = ["PooledDatabase"]

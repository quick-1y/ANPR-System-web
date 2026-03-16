from __future__ import annotations


class StorageUnavailableError(RuntimeError):
    """БД PostgreSQL временно недоступна."""


__all__ = ["StorageUnavailableError"]

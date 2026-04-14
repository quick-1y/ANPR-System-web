from __future__ import annotations

from typing import Any, Dict, List, Optional

from database.base import PooledDatabase
from database.errors import StorageUnavailableError
from database.lists_repository import normalize_plate


class ClientDatabase(PooledDatabase):
    """CRUD, search, and list-attachment operations for client records."""

    def _schema_sql(self) -> str:
        # Schema (tables, indexes) is owned by ListDatabase.
        # This no-op satisfies the abstract requirement and marks the instance initialised.
        return "SELECT 1"

    # ── Read ─────────────────────────────────────────────────────────────

    def list_all_clients(self) -> List[Dict[str, Any]]:
        """Return all non-deleted clients regardless of list membership."""
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, list_id, plate, last_name, first_name,
                           middle_name, phone, car, comment
                    FROM clients
                    WHERE is_deleted = FALSE
                    ORDER BY plate
                    """
                )
                return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_client(self, client_id: int) -> Optional[Dict[str, Any]]:
        """Return a single non-deleted client by primary key with list metadata, or None."""
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.id, c.list_id, c.plate, c.last_name, c.first_name,
                           c.middle_name, c.phone, c.car, c.comment,
                           l.name AS list_name, l.type AS list_type
                    FROM clients c
                    LEFT JOIN lists l ON l.id = c.list_id
                    WHERE c.id = %s AND c.is_deleted = FALSE
                    """,
                    (int(client_id),),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "list_id": row[1],
            "plate": row[2],
            "last_name": row[3],
            "first_name": row[4],
            "middle_name": row[5],
            "phone": row[6],
            "car": row[7],
            "comment": row[8],
            "list_name": row[9],
            "list_type": row[10],
        }

    def search_clients(self, query: str) -> List[Dict[str, Any]]:
        """Return clients whose name fields or plate contain *query* (case-insensitive)."""
        self._ensure_schema()
        pattern = f"%{query.strip()}%"
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, list_id, plate, last_name, first_name,
                           middle_name, phone, car, comment
                    FROM clients
                    WHERE is_deleted = FALSE
                      AND (
                        last_name   ILIKE %s OR
                        first_name  ILIKE %s OR
                        middle_name ILIKE %s OR
                        plate       ILIKE %s
                      )
                    ORDER BY plate
                    """,
                    (pattern, pattern, pattern, pattern),
                )
                return [self._row_to_dict(row) for row in cursor.fetchall()]

    # ── Write ────────────────────────────────────────────────────────────

    def create_client(
        self,
        plate: str,
        last_name: str = "",
        first_name: str = "",
        middle_name: str = "",
        phone: str = "",
        car: str = "",
        comment: str = "",
        list_id: Optional[int] = None,
    ) -> Optional[int]:
        """Insert a new client record. *list_id* is optional (client may be unattached)."""
        self._ensure_schema()
        normalized = normalize_plate(plate)
        if not normalized:
            return None
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO clients
                        (list_id, plate, plate_normalized, last_name, first_name,
                         middle_name, phone, car, comment)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        list_id,
                        plate.strip(),
                        normalized,
                        (last_name or "").strip(),
                        (first_name or "").strip(),
                        (middle_name or "").strip(),
                        (phone or "").strip(),
                        (car or "").strip(),
                        (comment or "").strip(),
                    ),
                )
                row = cursor.fetchone()
            conn.commit()
        return int(row[0]) if row else None

    def update_client(
        self,
        client_id: int,
        plate: str,
        last_name: str = "",
        first_name: str = "",
        middle_name: str = "",
        phone: str = "",
        car: str = "",
        comment: str = "",
    ) -> bool:
        """Update client fields (plate and metadata). Returns True if a row was changed."""
        self._ensure_schema()
        normalized = normalize_plate(plate)
        if not normalized:
            return False
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE clients
                        SET plate = %s, plate_normalized = %s,
                            last_name = %s, first_name = %s, middle_name = %s,
                            phone = %s, car = %s, comment = %s
                        WHERE id = %s AND is_deleted = FALSE
                        """,
                        (
                            plate.strip(),
                            normalized,
                            (last_name or "").strip(),
                            (first_name or "").strip(),
                            (middle_name or "").strip(),
                            (phone or "").strip(),
                            (car or "").strip(),
                            (comment or "").strip(),
                            int(client_id),
                        ),
                    )
                    updated = cursor.rowcount > 0
                conn.commit()
            return updated
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError(f"PostgreSQL недоступен: {exc}") from exc

    def delete_client(self, client_id: int) -> bool:
        """Soft-delete a client. Returns True if a row was changed."""
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE clients SET is_deleted = TRUE WHERE id = %s AND is_deleted = FALSE",
                    (int(client_id),),
                )
                deleted = cursor.rowcount > 0
            conn.commit()
        return deleted

    # ── List attachment ───────────────────────────────────────────────────

    def attach_to_list(self, client_id: int, list_id: int) -> bool:
        """Attach a client to a list (replaces any previous attachment)."""
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE clients SET list_id = %s WHERE id = %s AND is_deleted = FALSE",
                    (int(list_id), int(client_id)),
                )
                updated = cursor.rowcount > 0
            conn.commit()
        return updated

    def detach_from_list(self, client_id: int) -> bool:
        """Detach a client from its current list (sets list_id to NULL)."""
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE clients SET list_id = NULL WHERE id = %s AND is_deleted = FALSE",
                    (int(client_id),),
                )
                updated = cursor.rowcount > 0
            conn.commit()
        return updated

    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: tuple) -> Dict[str, Any]:
        return {
            "id": row[0],
            "list_id": row[1],
            "plate": row[2],
            "last_name": row[3],
            "first_name": row[4],
            "middle_name": row[5],
            "phone": row[6],
            "car": row[7],
            "comment": row[8],
        }


__all__ = ["ClientDatabase"]

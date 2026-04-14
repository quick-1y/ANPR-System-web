from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Iterable, Optional

from database.base import PooledDatabase

LIST_TYPES = OrderedDict([
    ("white", "Белый список"),
    ("info", "Информационный список"),
    ("black", "Черный список"),
])

# Visually-equivalent Cyrillic plate characters → Latin counterparts.
# Only the 13 characters that appear on Russian plates and have an
# identical-looking Latin glyph are translated.  All other characters
# (including non-plate Cyrillic such as Б, Г, Д …) are left as-is so
# the function is predictable and safe for arbitrary input.
#
# Source order: А  В  Е  К  М  Н  О  Р  С  Т  У  Х  Ё
# Target order: A  B  E  K  M  H  O  P  C  T  Y  X  E  (all Latin)
_CYRILLIC_TO_LATIN = str.maketrans("АВЕКМНОРСТУХЁ", "ABEKMHOPCTYXE")


def normalize_plate(value: str) -> str:
    """Return the canonical Latin form of a plate string.

    Steps:
      1. Remove all whitespace and uppercase.
      2. Translate visually-equivalent Cyrillic plate letters to Latin.

    The result is stored in ``clients.plate_normalized`` and used for
    all matching / uniqueness checks.  The original user-entered value
    is stored in ``clients.plate`` and shown in the UI unchanged.
    """
    upper = "".join(str(value or "").upper().split())
    return upper.translate(_CYRILLIC_TO_LATIN)


class ListDatabase(PooledDatabase):
    """PostgreSQL-only хранилище списков номеров."""

    def _schema_sql(self) -> str:
        return """
        CREATE TABLE IF NOT EXISTS lists (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clients (
            id BIGSERIAL PRIMARY KEY,
            list_id BIGINT REFERENCES lists(id) ON DELETE SET NULL,
            plate TEXT NOT NULL,
            plate_normalized TEXT NOT NULL,
            last_name TEXT NOT NULL DEFAULT '',
            first_name TEXT NOT NULL DEFAULT '',
            middle_name TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            car TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT ''
        );
        ALTER TABLE lists ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE clients ADD COLUMN IF NOT EXISTS last_name TEXT NOT NULL DEFAULT '';
        ALTER TABLE clients ADD COLUMN IF NOT EXISTS first_name TEXT NOT NULL DEFAULT '';
        ALTER TABLE clients ADD COLUMN IF NOT EXISTS middle_name TEXT NOT NULL DEFAULT '';
        ALTER TABLE clients ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT '';
        ALTER TABLE clients ADD COLUMN IF NOT EXISTS car TEXT NOT NULL DEFAULT '';
        ALTER TABLE clients ADD COLUMN IF NOT EXISTS comment TEXT NOT NULL DEFAULT '';
        CREATE INDEX IF NOT EXISTS idx_lists_type ON lists(type);
        CREATE INDEX IF NOT EXISTS idx_clients_plate ON clients(plate_normalized);
        CREATE INDEX IF NOT EXISTS idx_clients_list ON clients(list_id);
        DROP INDEX IF EXISTS uq_clients_list_plate;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_list_plate ON clients(list_id, plate_normalized) WHERE is_deleted = FALSE;
        """

    def list_lists(self) -> list[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT l.id, l.name, l.type, COUNT(e.id) AS clients_count
                    FROM lists l
                    LEFT JOIN clients e ON e.list_id = l.id AND e.is_deleted = FALSE
                    WHERE l.is_deleted = FALSE
                    GROUP BY l.id
                    ORDER BY l.name
                    """
                )
                return [
                    {"id": row[0], "name": row[1], "type": row[2], "clients_count": row[3]}
                    for row in cursor.fetchall()
                ]

    def create_list(self, name: str, list_type: str) -> int:
        self._ensure_schema()
        list_type = list_type if list_type in LIST_TYPES else "white"
        name = (name or "").strip() or "Новый список"
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO lists (name, type) VALUES (%s, %s) RETURNING id", (name, list_type))
                row = cursor.fetchone()
            conn.commit()
        return int(row[0]) if row else 0

    def list_clients_in_list(self, list_id: int) -> list[Dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, plate, last_name, first_name, middle_name, phone, car, comment
                    FROM clients
                    WHERE list_id = %s AND is_deleted = FALSE
                    ORDER BY plate
                    """,
                    (int(list_id),),
                )
                return [
                    {
                        "id": row[0],
                        "plate": row[1],
                        "last_name": row[2],
                        "first_name": row[3],
                        "middle_name": row[4],
                        "phone": row[5],
                        "car": row[6],
                        "comment": row[7],
                    }
                    for row in cursor.fetchall()
                ]

    def delete_list(self, list_id: int) -> bool:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                # Detach clients from the list before deleting it so they survive as standalone clients.
                cursor.execute(
                    "UPDATE clients SET list_id = NULL WHERE list_id = %s AND is_deleted = FALSE",
                    (int(list_id),),
                )
                cursor.execute(
                    "UPDATE lists SET is_deleted = TRUE WHERE id = %s AND is_deleted = FALSE",
                    (int(list_id),),
                )
                deleted = cursor.rowcount > 0
            conn.commit()
        return deleted

    def update_list(self, list_id: int, name: str, list_type: str) -> bool:
        self._ensure_schema()
        list_type = list_type if list_type in LIST_TYPES else "white"
        name = (name or "").strip() or "Список"
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE lists SET name = %s, type = %s WHERE id = %s AND is_deleted = FALSE",
                    (name, list_type, int(list_id)),
                )
                updated = cursor.rowcount > 0
            conn.commit()
        return updated

    def all_plates_with_type(self) -> list[Dict[str, str]]:
        self._ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT e.plate_normalized, l.type
                    FROM clients e
                    JOIN lists l ON l.id = e.list_id
                    WHERE e.is_deleted = FALSE AND l.is_deleted = FALSE
                    """
                )
                return [{"plate": row[0], "list_type": row[1]} for row in cursor.fetchall()]

    def plate_in_list_type(self, plate: str, list_type: str) -> bool:
        self._ensure_schema()
        normalized = normalize_plate(plate)
        if not normalized:
            return False
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM clients e
                    JOIN lists l ON l.id = e.list_id
                    WHERE e.plate_normalized = %s AND l.type = %s
                      AND e.is_deleted = FALSE AND l.is_deleted = FALSE
                    LIMIT 1
                    """,
                    (normalized, list_type),
                )
                return cursor.fetchone() is not None

    def find_client_by_plate(self, plate: str) -> Optional[Dict[str, Any]]:
        """Return the first client record matching the given plate that belongs to a list, or None."""
        self._ensure_schema()
        normalized = normalize_plate(plate)
        if not normalized:
            return None
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT e.id, e.plate, e.last_name, e.first_name, e.middle_name,
                           e.phone, e.car, e.comment, l.type, l.name
                    FROM clients e
                    JOIN lists l ON l.id = e.list_id
                    WHERE e.plate_normalized = %s
                      AND e.is_deleted = FALSE AND l.is_deleted = FALSE
                    LIMIT 1
                    """,
                    (normalized,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "plate": row[1],
            "last_name": row[2],
            "first_name": row[3],
            "middle_name": row[4],
            "phone": row[5],
            "car": row[6],
            "comment": row[7],
            "list_type": row[8],
            "list_name": row[9],
        }

    def plate_in_lists(self, plate: str, list_ids: Iterable[int]) -> bool:
        self._ensure_schema()
        normalized = normalize_plate(plate)
        ids = [int(list_id) for list_id in list_ids if int(list_id) > 0]
        if not normalized or not ids:
            return False
        placeholders = ",".join(["%s"] * len(ids))
        query = (
            f"SELECT 1 FROM clients e "
            f"JOIN lists l ON l.id = e.list_id "
            f"WHERE e.plate_normalized = %s AND e.list_id IN ({placeholders}) "
            f"AND e.is_deleted = FALSE AND l.is_deleted = FALSE "
            f"LIMIT 1"
        )
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, [normalized, *ids])
                return cursor.fetchone() is not None


__all__ = ["ListDatabase", "LIST_TYPES", "normalize_plate"]

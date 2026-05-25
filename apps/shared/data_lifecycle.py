from __future__ import annotations

import csv
import io
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zipfile import ZIP_DEFLATED, ZipFile

from database.postgres_event_repository import PostgresEventDatabase


@dataclass
class RetentionPolicy:
    auto_cleanup_enabled: bool = True
    cleanup_interval_minutes: int = 30
    events_retention_days: int = 30
    media_retention_days: int = 14
    max_screenshots_mb: int = 4096

    @classmethod
    def from_storage(cls, storage: Dict[str, Any]) -> "RetentionPolicy":
        return cls(
            auto_cleanup_enabled=bool(storage.get("auto_cleanup_enabled", True)),
            cleanup_interval_minutes=max(1, int(storage.get("cleanup_interval_minutes", 30))),
            events_retention_days=max(1, int(storage.get("events_retention_days", 30))),
            media_retention_days=max(1, int(storage.get("media_retention_days", 14))),
            max_screenshots_mb=max(256, int(storage.get("max_screenshots_mb", 4096))),
        )

    def to_storage(self) -> Dict[str, Any]:
        return {
            "auto_cleanup_enabled": bool(self.auto_cleanup_enabled),
            "cleanup_interval_minutes": int(self.cleanup_interval_minutes),
            "events_retention_days": int(self.events_retention_days),
            "media_retention_days": int(self.media_retention_days),
            "max_screenshots_mb": int(self.max_screenshots_mb),
        }


class DataLifecycleService:
    def __init__(self, screenshots_dir: str, policy: RetentionPolicy, postgres_dsn: str) -> None:
        self.screenshots_dir = Path(screenshots_dir)
        self.policy = policy
        self.pg_events = PostgresEventDatabase(postgres_dsn)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    def update_policy(self, policy: RetentionPolicy) -> None:
        self.policy = policy

    @staticmethod
    def _safe_unlink(path: Optional[str]) -> bool:
        if not path:
            return False
        try:
            os.remove(path)
            return True
        except (FileNotFoundError, OSError):
            return False

    def cleanup_old_events(self) -> Dict[str, int]:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=self.policy.events_retention_days)).isoformat()
        rows = self.pg_events.delete_before(cutoff_iso)
        deleted_files = 0
        for row in rows:
            for key in ("frame_path_entry", "plate_path_entry", "frame_path_exit", "plate_path_exit"):
                deleted_files += int(self._safe_unlink(row.get(key)))
        return {"deleted_events": len(rows), "deleted_media_files": deleted_files}

    def cleanup_old_media(self) -> Dict[str, int]:
        cutoff = time.time() - self.policy.media_retention_days * 86400
        deleted = 0
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            for file_path in self.screenshots_dir.rglob(ext):
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                        deleted += 1
                except OSError:
                    continue
        return {"deleted_orphan_media": deleted}

    def enforce_storage_limit(self) -> Dict[str, int]:
        max_bytes = self.policy.max_screenshots_mb * 1024 * 1024
        files: list[tuple[float, Path, int]] = []
        total = 0
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            for file_path in self.screenshots_dir.rglob(ext):
                try:
                    stat = file_path.stat()
                except OSError:
                    continue
                total += stat.st_size
                files.append((stat.st_mtime, file_path, stat.st_size))
        if total <= max_bytes:
            return {"deleted_for_limit": 0}
        files.sort(key=lambda item: item[0])
        deleted = 0
        for _, path, size in files:
            if total <= max_bytes:
                break
            try:
                path.unlink()
                total -= size
                deleted += 1
            except OSError:
                continue
        return {"deleted_for_limit": deleted}

    def run_retention_cycle(self) -> Dict[str, int]:
        result: Dict[str, int] = {}
        result.update(self.cleanup_old_events())
        result.update(self.cleanup_old_media())
        result.update(self.enforce_storage_limit())
        return result

    def export_events_csv(self, *, start: Optional[str] = None, end: Optional[str] = None, plate: Optional[str] = None, channel_id: Optional[int] = None) -> tuple[str, bytes]:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"events_{ts}.csv"
        rows = self.pg_events.fetch_for_export(start=start, end=end, plate=plate, channel_id=channel_id)
        fieldnames = ["id", "time", "channel_id_entry", "channel_id_exit", "plate", "plate_display", "country", "confidence", "source", "frame_path_entry", "plate_path_entry", "frame_path_exit", "plate_path_exit", "direction", "zone_id", "time_entry", "time_exit"]
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return filename, csv_buffer.getvalue().encode("utf-8")

    def export_events_bundle(self, *, start: Optional[str] = None, end: Optional[str] = None, channel_id: Optional[int] = None, include_media: bool = True) -> tuple[str, bytes]:
        rows = self.pg_events.fetch_for_export(start=start, end=end, channel_id=channel_id)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        csv_name = f"events_{ts}.csv"
        fieldnames = ["id", "time", "channel_id_entry", "channel_id_exit", "plate", "plate_display", "country", "confidence", "source", "frame_path_entry", "plate_path_entry", "frame_path_exit", "plate_path_exit", "direction", "zone_id", "time_entry", "time_exit"]
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        csv_bytes = csv_buffer.getvalue().encode("utf-8")

        media_paths: set[Path] = set()
        if include_media:
            for row in rows:
                for key in ("frame_path_entry", "plate_path_entry", "frame_path_exit", "plate_path_exit"):
                    raw = row.get(key)
                    if raw:
                        media_paths.add(Path(str(raw)))

        zip_filename = f"events_{ts}.zip"
        zip_buffer = io.BytesIO()
        with ZipFile(zip_buffer, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(csv_name, csv_bytes)
            if include_media:
                for media_path in sorted(media_paths):
                    if media_path.exists() and media_path.is_file():
                        try:
                            archive.writestr(f"media/{media_path.name}", media_path.read_bytes())
                        except OSError:
                            continue
        return zip_filename, zip_buffer.getvalue()


__all__ = ["RetentionPolicy", "DataLifecycleService"]

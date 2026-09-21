"""Display timezone: interface.display_timezone replaces time.timezone
(roadmap task 4.5, model 4.9, decision O-4)."""
from __future__ import annotations

import ast
import csv
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.api import schemas
from app.api.routers import settings as settings_router
from app.api.routers.system import system_time
from app.shared.data_lifecycle import DataLifecycleService
from common.timeutil import format_in_zone, zone_slug
from config.registry import SettingValidationError, get_spec
from tests.test_reconnect_settings import USER, _container, _payload

ROOT = Path(__file__).resolve().parent.parent


def _put(container, zone):
    payload = _payload()
    payload.interface = type(payload.interface)(display_timezone=zone)
    return settings_router.put_global_settings(payload, container=container, current_user=USER)


class TestTzdata:
    def test_iana_database_is_available(self):
        """Fails on a machine without tzdata (Windows) — see pyproject.toml."""
        assert ZoneInfo("Europe/Kyiv").key == "Europe/Kyiv"

    def test_tzdata_is_a_declared_dependency(self):
        assert 'tzdata = "*"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "tzdata" in dockerfile and "TZ=UTC" in dockerfile


class TestValidation:
    def test_static_default_is_utc(self):
        assert get_spec("interface.display_timezone").default == "UTC"

    @pytest.mark.parametrize("zone", ["Europe/Minsk", "Europe/Kyiv", "Asia/Almaty", "UTC"])
    def test_valid_zones_are_accepted(self, zone):
        assert get_spec("interface.display_timezone").validate(zone) == zone

    @pytest.mark.parametrize("zone", ["UTC+03:00", "Mars/Olympus", "", "Europe"])
    def test_invalid_zones_are_rejected(self, zone):
        with pytest.raises(SettingValidationError):
            get_spec("interface.display_timezone").validate(zone)

    def test_put_with_an_invalid_zone_is_422_and_writes_nothing(self):
        container, repo = _container()
        with pytest.raises(HTTPException) as exc:
            _put(container, "UTC+03:00")
        assert exc.value.status_code == 422
        assert repo.writes == []


class TestTimezoneConfigured:
    def test_false_without_a_row(self):
        container, _ = _container()
        body = system_time(container=container, _user=USER)
        assert body["display_timezone"] is None, "no zone chosen: the client shows its own time"
        assert body["timezone_configured"] is False

    def test_true_after_an_explicit_write_even_of_utc(self):
        container, repo = _container()
        _put(container, "UTC")
        assert repo.stored["interface.display_timezone"] == "UTC"
        assert system_time(container=container, _user=USER)["timezone_configured"] is True

    def test_saving_without_touching_the_zone_does_not_configure_it(self):
        container, repo = _container()
        _put(container, None)
        assert "interface.display_timezone" not in repo.stored
        assert system_time(container=container, _user=USER)["timezone_configured"] is False

    def test_explicit_zone_is_returned(self):
        container, _ = _container()
        _put(container, "Europe/Minsk")
        body = system_time(container=container, _user=USER)
        assert (body["display_timezone"], body["timezone_configured"]) == ("Europe/Minsk", True)
        assert datetime.fromisoformat(body["server_utc"]).utcoffset().total_seconds() == 0

    def test_settings_response_reports_zone_and_flag(self):
        container, _ = _container()
        _put(container, "Asia/Almaty")
        body = settings_router.get_global_settings(container=container, current_user=USER)
        assert body["interface"]["display_timezone"] == "Asia/Almaty"
        assert body["interface"]["timezone_configured"] is True
        assert "time" not in body



class _Events:
    def __init__(self, rows):
        self.rows = rows

    def fetch_for_export(self, **_kwargs):
        return self.rows


def _lifecycle(rows):
    service = object.__new__(DataLifecycleService)
    service.pg_events = _Events(rows)
    return service


def _row(when, **extra):
    return {"id": 1, "time": when, "plate": "A123BC", "time_entry": None, "time_exit": None, **extra}


class TestExport:
    def test_csv_times_follow_the_zone_across_a_dst_change(self):
        # Kyiv switched to summer time on 2026-03-29 03:00 -> 04:00 local (01:00 UTC).
        winter = datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc)
        summer = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
        _, body = _lifecycle([_row(winter, id=1), _row(summer, id=2)]).export_events_csv(display_timezone="Europe/Kyiv")
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        assert rows[0]["time (Europe/Kyiv)"] == "2026-03-28T14:00:00+02:00"
        assert rows[1]["time (Europe/Kyiv)"] == "2026-03-30T15:00:00+03:00"

    def test_header_and_filename_name_the_zone(self):
        name, body = _lifecycle([_row(datetime(2026, 1, 1, tzinfo=timezone.utc))]).export_events_csv(display_timezone="Europe/Minsk")
        assert name.startswith("events_") and name.endswith("_Europe-Minsk.csv")
        header = body.decode("utf-8").splitlines()[0].split(",")
        assert {"time (Europe/Minsk)", "time_entry (Europe/Minsk)", "time_exit (Europe/Minsk)"} <= set(header)

    def test_default_zone_is_utc_and_string_input_is_accepted(self):
        name, body = _lifecycle([_row("2026-06-01T10:00:00+00:00")]).export_events_csv()
        assert name.endswith("_UTC.csv")
        assert "2026-06-01T10:00:00+00:00" in body.decode("utf-8")

    def test_bundle_uses_the_same_zone(self):
        name, payload = _lifecycle([_row(datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc))]).export_events_bundle(
            include_media=False, display_timezone="Asia/Almaty")
        assert name.endswith("_Asia-Almaty.zip")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            (csv_name,) = archive.namelist()
            text = archive.read(csv_name).decode("utf-8")
        assert csv_name.endswith("_Asia-Almaty.csv")
        assert "time (Asia/Almaty)" in text and "2026-07-01T14:00:00+05:00" in text

    def test_export_endpoints_pass_the_instance_zone(self):
        from unittest.mock import MagicMock

        from app.api.routers.data import export_events_csv

        container, _ = _container()
        _put(container, "Europe/Minsk")
        container.lifecycle = MagicMock()
        container.lifecycle.export_events_csv.return_value = ("e.csv", b"")
        export_events_csv(container=container, _user={})
        assert container.lifecycle.export_events_csv.call_args.kwargs["display_timezone"] == "Europe/Minsk"


class TestTimeHelpers:
    def test_empty_values_render_empty(self):
        assert format_in_zone(None, "UTC") == "" and format_in_zone("", "UTC") == ""

    def test_naive_values_are_treated_as_utc(self):
        assert format_in_zone(datetime(2026, 1, 1, 0, 0), "Europe/Minsk") == "2026-01-01T03:00:00+03:00"

    def test_zone_slug(self):
        assert zone_slug("America/Argentina/Buenos_Aires") == "America-Argentina-Buenos_Aires"


class TestNaiveTimeInvariant:
    """No `datetime.now()` without a zone and no `.astimezone()` without an
    explicit zone anywhere in the application code (model 4.9)."""

    DIRS = ("anpr", "app", "common", "config", "controllers", "database", "runtime")

    def _offenders(self):
        found = []
        for directory in self.DIRS:
            for path in (ROOT / directory).rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                        continue
                    where = f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
                    attr = node.func.attr
                    if attr == "now" and not node.args and not node.keywords:
                        found.append(f"{where} now() without tz")
                    if attr == "astimezone" and not node.args and not node.keywords:
                        found.append(f"{where} astimezone() without zone")
                    if attr in ("utcnow", "today", "fromtimestamp") and getattr(node.func.value, "id", "") == "datetime":
                        if attr != "fromtimestamp" or len(node.args) < 2 and not node.keywords:
                            found.append(f"{where} naive datetime.{attr}()")
        return found

    def test_no_naive_clock_reads(self):
        assert not self._offenders(), self._offenders()

    def test_log_files_rotate_in_utc(self, tmp_path):
        from common.logging import HourlyFileHandler

        handler = HourlyFileHandler(str(tmp_path), "svc")
        try:
            assert handler._current_period_start.tzinfo == timezone.utc
        finally:
            handler.close()

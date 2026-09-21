"""Deployment configuration lives in the environment (roadmap phase 5):
model paths and device (5.1), data directories (5.2), the connection string
(5.3), pool and executor limits (5.4)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.api.container import AppContainer
from app.api.routers import settings as settings_router
from config.env_settings import EnvConfigError, load_env_config
from config.registry import get_spec
from tests.test_reconnect_settings import USER, _container, _payload
from tests.test_settings_service import _Repo

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "web"


@pytest.fixture
def heavy_modules(monkeypatch):
    """`runtime.channel_runtime` and `anpr.model_config` need cv2/torch; stub them
    only when the real ones are absent, and forget the stubbed imports after."""
    stubbed = []
    for name in ("cv2", "torch"):
        try:
            __import__(name)
        except ImportError:
            monkeypatch.setitem(sys.modules, name, MagicMock())
            stubbed.append(name)
    yield
    if stubbed:
        for module in ("runtime.channel_runtime", "anpr.model_config", "anpr.pipeline.factory"):
            sys.modules.pop(module, None)


class TestEnvConfigDeploymentValues:
    def test_defaults_are_unchanged_from_the_previous_hardcoded_values(self):
        cfg = load_env_config({})
        assert cfg.media_dir == "data/screenshots"
        assert cfg.yolo_model_path == "anpr/models/yolo/best.pt"
        assert cfg.ocr_model_path == "anpr/models/ocr_crnn/crnn_ocr_model_int8_fx.pth"
        assert cfg.device == "cpu"
        assert (cfg.postgres_pool_min, cfg.postgres_pool_max, cfg.io_pool_workers) == (2, 10, 2)
        assert cfg.postgres_dsn == "postgresql://anpr:anpr@postgres:5432/anpr"

    def test_values_are_read(self):
        cfg = load_env_config(
            {"ANPR_MEDIA_DIR": "/mnt/media", "ANPR_DEVICE": " CUDA ", "POSTGRES_POOL_MIN": "1",
             "POSTGRES_POOL_MAX": "4", "ANPR_IO_POOL_WORKERS": "6"}
        )
        assert (cfg.media_dir, cfg.device) == ("/mnt/media", "cuda")
        assert (cfg.postgres_pool_min, cfg.postgres_pool_max, cfg.io_pool_workers) == (1, 4, 6)

    @pytest.mark.parametrize(
        "env",
        [{"POSTGRES_POOL_MIN": "0"}, {"ANPR_IO_POOL_WORKERS": "x"}, {"POSTGRES_POOL_MIN": "5", "POSTGRES_POOL_MAX": "3"}],
    )
    def test_invalid_limits_fail_fast(self, env):
        with pytest.raises(EnvConfigError):
            load_env_config(env)

    def test_registry_defaults_agree_with_the_env_layer(self):
        cfg = load_env_config({})
        for key, value in (
            ("ANPR_MEDIA_DIR", cfg.media_dir), ("ANPR_LOGS_DIR", cfg.logs_dir),
            ("ANPR_YOLO_MODEL_PATH", cfg.yolo_model_path), ("ANPR_OCR_MODEL_PATH", cfg.ocr_model_path),
            ("ANPR_DEVICE", cfg.device), ("POSTGRES_POOL_MIN", cfg.postgres_pool_min),
            ("POSTGRES_POOL_MAX", cfg.postgres_pool_max), ("ANPR_IO_POOL_WORKERS", cfg.io_pool_workers),
        ):
            assert get_spec(key).default == value, key


class TestPoolLimits:  # task 5.4
    @pytest.fixture(autouse=True)
    def _fresh_registry(self, monkeypatch):
        import database.base as base

        monkeypatch.setattr(base, "_pool_registry", {})
        self.calls = []
        fake = MagicMock(side_effect=lambda dsn, **kw: self.calls.append((dsn, kw)) or object())
        monkeypatch.setitem(sys.modules, "psycopg_pool", MagicMock(ConnectionPool=fake))

    def test_defaults_are_two_and_ten(self, monkeypatch):
        from database.base import get_shared_pool

        for name in ("POSTGRES_POOL_MIN", "POSTGRES_POOL_MAX"):
            monkeypatch.delenv(name, raising=False)
        get_shared_pool("postgresql://a/a")
        assert self.calls[0][1] == {"min_size": 2, "max_size": 10, "open": True}

    def test_environment_sets_the_bounds(self, monkeypatch):
        from database.base import get_shared_pool

        monkeypatch.setenv("POSTGRES_POOL_MIN", "1")
        monkeypatch.setenv("POSTGRES_POOL_MAX", "3")
        get_shared_pool("postgresql://b/b")
        assert self.calls[0][1] == {"min_size": 1, "max_size": 3, "open": True}

    def test_io_pool_size_comes_from_the_parameter(self, tmp_path, heavy_modules):
        from runtime.channel_runtime import ChannelProcessor

        processor = ChannelProcessor(event_callback=None, events_db=object(), media_dir=str(tmp_path), io_pool_workers=5)
        try:
            assert processor._io_pool._max_workers == 5
        finally:
            processor.shutdown_io_pool()


class TestMediaDirectory:  # task 5.2
    def test_processor_and_lifecycle_write_to_the_same_env_directory(self, tmp_path, monkeypatch, heavy_modules):
        import runtime.channel_runtime as runtime_module
        from app.shared.data_lifecycle import RetentionPolicy

        monkeypatch.setenv("ANPR_MEDIA_DIR", str(tmp_path / "media"))
        captured = {}

        class _Processor:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(runtime_module, "ChannelProcessor", _Processor)
        container, _ = _container()
        container._resolve_dsn = lambda: "postgresql://x/x"
        container.get_reconnect_settings = lambda: {}
        container.get_plate_settings = lambda: {}
        container.settings_service.get = lambda key: 0.5 if key.startswith("detection") else None
        container._create_processor()
        with_patch = MagicMock()
        monkeypatch.setattr("app.api.container.DataLifecycleService", with_patch)
        monkeypatch.setattr(RetentionPolicy, "from_settings", classmethod(lambda cls, s: None))
        container._build_lifecycle()

        assert captured["media_dir"] == str(tmp_path / "media")
        assert with_patch.call_args.kwargs["screenshots_dir"] == str(tmp_path / "media")

    def test_processor_creates_and_uses_the_directory(self, tmp_path, heavy_modules):
        from runtime.channel_runtime import ChannelProcessor

        target = tmp_path / "vol" / "shots"
        processor = ChannelProcessor(event_callback=None, events_db=object(), media_dir=str(target))
        try:
            assert processor._screenshots_dir == target.resolve() and target.is_dir()
        finally:
            processor.shutdown_io_pool()


    def test_settings_payload_cannot_carry_directories(self):
        from app.api.schemas import StoragePayload

        assert set(StoragePayload.model_fields) == {
            "auto_cleanup_enabled", "cleanup_interval_minutes", "events_retention_days",
            "media_retention_days", "max_screenshots_mb",
        }


class TestConnectionStringStaysInTheEnvironment:  # task 5.3
    DSN = "postgresql://secretuser:secretpass@db.internal:5432/anpr"

    def test_get_settings_does_not_contain_the_dsn(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_DSN", self.DSN)
        container, _ = _container()
        body = settings_router.get_global_settings(container=container, current_user=USER)
        text = json.dumps(body)
        assert "secretpass" not in text and "postgres_dsn" not in text and "postgresql://" not in text

    def test_put_response_does_not_contain_it_either_and_old_clients_are_tolerated(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_DSN", self.DSN)
        container, repo = _container()
        payload = _payload()
        old_client_storage = {**payload.storage.model_dump(), "postgres_dsn": "postgresql://evil/x"}
        payload = type(payload).model_validate({**payload.model_dump(), "storage": old_client_storage})
        body = settings_router.put_global_settings(payload, container=container, current_user=USER)
        assert "postgres_dsn" not in json.dumps(body)
        assert not any("dsn" in key for values, _ in repo.writes for key in values)

    def test_container_resolves_the_dsn_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_DSN", self.DSN)
        container, _ = _container()
        assert container._resolve_dsn() == self.DSN

    def test_no_dsn_field_or_control_left_in_the_ui(self):
        assert "g_postgres_dsn" not in (WEB / "index.html").read_text(encoding="utf-8")
        for js in (WEB / "js").glob("*.js"):
            assert "postgres_dsn" not in js.read_text(encoding="utf-8"), js.name

    def test_application_code_never_reads_the_dsn_from_settings(self):
        offenders = []
        for directory in ("app", "config", "database", "runtime"):
            for path in (ROOT / directory).rglob("*.py"):
                if re.search(r"""get\(["']postgres_dsn["']""", path.read_text(encoding="utf-8")):
                    offenders.append(path.relative_to(ROOT).as_posix())
        assert not offenders, offenders


class TestDetectionThreshold:  # task 5.1
    def test_key_is_operational_and_requires_a_restart(self):
        spec = get_spec("detection.confidence_threshold")
        assert spec.requires_restart is True and spec.cls.value == "A"

    def test_saving_a_new_threshold_stores_it_and_restarts_once(self):
        container, repo = _container()
        container.restart_processor_for_settings = MagicMock()
        payload = _payload()
        payload = type(payload).model_validate({**payload.model_dump(), "detection": {"confidence_threshold": 0.7}})
        body = settings_router.put_global_settings(payload, container=container, current_user=USER)
        assert repo.stored["detection.confidence_threshold"] == 0.7
        assert body["requires_restart"] == ["detection.confidence_threshold"]
        assert body["detection"] == {"confidence_threshold": 0.7}
        container.restart_processor_for_settings.assert_called_once()

    def test_omitting_it_leaves_the_stored_value_alone(self):
        container, repo = _container(_Repo({"detection.confidence_threshold": 0.3}))
        settings_router.put_global_settings(_payload(), container=container, current_user=USER)
        assert repo.stored["detection.confidence_threshold"] == 0.3

    def test_out_of_range_is_rejected(self):
        payload = _payload()
        with pytest.raises(ValueError):
            type(payload).model_validate({**payload.model_dump(), "detection": {"confidence_threshold": 1.5}})

    def test_processor_is_built_with_the_stored_threshold(self, heavy_modules, monkeypatch, tmp_path):
        import runtime.channel_runtime as runtime_module

        captured = {}
        monkeypatch.setattr(runtime_module, "ChannelProcessor", lambda **kw: captured.update(kw))
        container, _ = _container(_Repo({"detection.confidence_threshold": 0.8}))
        container.get_plate_settings = lambda: {}
        container._create_processor()
        assert captured["model_config"].detection_confidence_threshold == 0.8



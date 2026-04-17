from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException

from database.base import close_shared_pool
from database.channel_repository import ChannelDatabase
from database.clients_repository import ClientDatabase
from database.controller_repository import ControllerDatabase
from database.lists_repository import ListDatabase
from database.user_repository import UserDatabase
from config.settings_manager import SettingsManager
from database.postgres_event_repository import PostgresEventDatabase
from database.zones_repository import ZoneDatabase
from database.errors import StorageUnavailableError
from app.shared.data_lifecycle import DataLifecycleService, RetentionPolicy
from common.logging import configure_logging, get_live_log_bus, get_logger
from controllers import ControllerAutomationService, ControllerService
from runtime.debug import DebugRegistry
from runtime.event_bus import EventBus

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "app" / "web"


@dataclass
class AppContainer:
    settings: SettingsManager
    events_db: PostgresEventDatabase
    lists_db: ListDatabase
    clients_db: ClientDatabase
    user_db: UserDatabase
    channel_db: ChannelDatabase
    controller_db: ControllerDatabase
    zone_db: ZoneDatabase
    controller_service: ControllerService
    controller_automation: ControllerAutomationService
    event_bus: EventBus
    debug_registry: DebugRegistry
    debug_log_bus: Any
    processor: Any
    lifecycle: DataLifecycleService
    main_loop: asyncio.AbstractEventLoop | None
    stream_shutdown: asyncio.Event

    def _resolve_dsn(self) -> str:
        return str(self.settings.get_storage_settings().get("postgres_dsn", "")).strip()

    @classmethod
    def build(cls) -> "AppContainer":
        settings = SettingsManager()
        configure_logging(settings.get_logging_config(), service_name="api")

        dsn = str(settings.get_storage_settings().get("postgres_dsn", "")).strip()
        events_db = PostgresEventDatabase(dsn)
        lists_db = ListDatabase(dsn)
        clients_db = ClientDatabase(dsn)
        user_db = UserDatabase(dsn)
        channel_db = ChannelDatabase(dsn)
        controller_db = ControllerDatabase(dsn)
        zone_db = ZoneDatabase(dsn)
        controller_service = ControllerService()
        event_bus = EventBus()
        debug_registry = DebugRegistry(settings.get_debug_settings())
        debug_log_bus = get_live_log_bus()

        container = cls(
            settings=settings,
            events_db=events_db,
            lists_db=lists_db,
            clients_db=clients_db,
            user_db=user_db,
            channel_db=channel_db,
            controller_db=controller_db,
            zone_db=zone_db,
            controller_service=controller_service,
            controller_automation=None,  # type: ignore[arg-type]
            event_bus=event_bus,
            debug_registry=debug_registry,
            debug_log_bus=debug_log_bus,
            processor=None,  # type: ignore[arg-type]
            lifecycle=None,  # type: ignore[arg-type]
            main_loop=None,
            stream_shutdown=asyncio.Event(),
        )
        container.controller_automation = ControllerAutomationService(
            controller_service,
            get_channels=channel_db.list_channels,
            get_controllers=controller_db.list_controllers,
            plate_in_list_type=lists_db.plate_in_list_type,
            plate_in_lists=lists_db.plate_in_lists,
        )
        container.processor = container._create_processor()
        container.lifecycle = container._build_lifecycle()
        return container

    def _create_processor(self) -> Any:
        from runtime.channel_runtime import ChannelProcessor
        from anpr.model_config import AnprModelConfig

        model_config = AnprModelConfig.from_settings(
            self.settings.get_model_settings(),
            self.settings.get_ocr_settings(),
            self.settings.get_detector_settings(),
        )
        return ChannelProcessor(
            event_callback=self.publish_event_sync,
            plate_settings=self.settings.get_plate_settings(),
            storage_settings=self.settings.get_storage_settings(),
            reconnect_settings=self.settings.get_reconnect(),
            debug_registry=self.debug_registry,
            model_config=model_config,
            events_db=self.events_db,
            lists_db=self.lists_db,
            zones_db=self.zone_db,
        )

    def _build_lifecycle(self) -> DataLifecycleService:
        policy = RetentionPolicy.from_storage(self.settings.get_storage_settings())
        return DataLifecycleService(
            screenshots_dir=self.settings.get_screenshot_dir(),
            policy=policy,
            postgres_dsn=self._resolve_dsn(),
        )

    async def startup(self) -> None:
        self.main_loop = asyncio.get_running_loop()
        self.stream_shutdown.clear()
        for channel in self.channel_db.list_channels():
            self.processor.ensure_channel(channel)
            if channel.get("enabled", True):
                self.processor.start(int(channel["id"]))

    def shutdown(self) -> None:
        self.stream_shutdown.set()
        for channel_id in list(self.processor.list_states().keys()):
            self.processor.stop(channel_id)
        self.processor.shutdown_io_pool()

    def storage_503(self, exc: Exception) -> HTTPException:
        return HTTPException(status_code=503, detail=f"PostgreSQL недоступен: {exc}")

    def db_status(self) -> Dict[str, Any]:
        try:
            self.events_db.fetch_recent(limit=1)
            return {"status": "ok", "backend": "postgresql"}
        except StorageUnavailableError as exc:
            return {"status": "degraded", "backend": "postgresql", "detail": str(exc)}

    def publish_event_sync(self, event: Dict[str, Any]) -> None:
        if self.main_loop and self.main_loop.is_running():
            self.main_loop.call_soon_threadsafe(asyncio.create_task, self.event_bus.publish(event))
        self.controller_automation.dispatch_event(event)

    def restart_processor_for_settings(self) -> None:
        channels = self.channel_db.list_channels()
        enabled_ids = [int(item["id"]) for item in channels if item.get("enabled", True)]
        old_processor = self.processor
        for channel in channels:
            try:
                old_processor.stop(int(channel["id"]))
            except Exception:
                pass
        self.processor = self._create_processor()
        old_processor.shutdown_io_pool()
        for channel in channels:
            self.processor.ensure_channel(channel)
        for channel_id in enabled_ids:
            self.processor.start(channel_id)

    def sync_channel_runtime(self, channel_id: int, enabled: bool) -> None:
        metric = self.processor.list_states().get(channel_id)
        is_running = bool(metric and metric.state == "running")
        if not enabled:
            self.processor.stop(channel_id)
            return
        if is_running:
            self.processor.restart(channel_id)
        else:
            self.processor.start(channel_id)

    def controller_exists(self, controller_id: int) -> bool:
        return self.controller_db.get_controller(controller_id) is not None

    def validate_channel_controller_binding(self, payload: Dict[str, Any]) -> None:
        controller_id = payload.get("controller_id")
        if controller_id is None:
            payload["controller_relay"] = 0
            return
        if not self.controller_exists(int(controller_id)):
            raise HTTPException(status_code=400, detail=f"Контроллер #{controller_id} не найден")

    def validate_channel_zone_binding(self, payload: Dict[str, Any]) -> None:
        zone_id = payload.get("zone_id")
        if zone_id is None:
            payload["zone_channel_type"] = None
            return
        if not self.zone_db.get_zone(int(zone_id)):
            raise HTTPException(status_code=400, detail=f"Зона #{zone_id} не найдена")

    @staticmethod
    def validate_global_hotkeys(controllers: List[Dict[str, Any]]) -> None:
        bindings: Dict[str, List[str]] = {}
        for controller in controllers:
            controller_name = str(controller.get("name") or controller.get("id") or "unknown")
            for relay_index, relay in enumerate(controller.get("relays") or []):
                hotkey = str(relay.get("hotkey") or "").strip().upper()
                if not hotkey:
                    continue
                bindings.setdefault(hotkey, []).append(f"{controller_name}:relay{relay_index + 1}")
        duplicates = {hotkey: places for hotkey, places in bindings.items() if len(places) > 1}
        if duplicates:
            details = "; ".join(f"{hotkey} -> {', '.join(places)}" for hotkey, places in sorted(duplicates.items()))
            raise HTTPException(
                status_code=422,
                detail=f"Хоткеи должны быть уникальны глобально между всеми контроллерами: {details}",
            )

    def refresh_storage_clients(self) -> None:
        old_dsn = self.events_db._dsn
        dsn = self._resolve_dsn()
        if dsn != old_dsn:
            close_shared_pool(old_dsn)
        self.events_db = PostgresEventDatabase(dsn)
        self.lifecycle = self._build_lifecycle()
        self.lists_db = ListDatabase(dsn)
        self.processor._lists_db = self.lists_db
        self.clients_db = ClientDatabase(dsn)
        self.user_db = UserDatabase(dsn)
        self.channel_db = ChannelDatabase(dsn)
        self.controller_db = ControllerDatabase(dsn)
        self.zone_db = ZoneDatabase(dsn)
        self.controller_automation = ControllerAutomationService(
            self.controller_service,
            get_channels=self.channel_db.list_channels,
            get_controllers=self.controller_db.list_controllers,
            plate_in_list_type=self.lists_db.plate_in_list_type,
            plate_in_lists=self.lists_db.plate_in_lists,
        )

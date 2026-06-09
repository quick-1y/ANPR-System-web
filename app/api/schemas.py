from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from config.settings_schema import SUPPORTED_CONTROLLER_TYPES, normalize_hotkey


# ── Auth schemas ──────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    login: str
    password: str


class UserOut(BaseModel):
    id: int
    login: str
    role: str
    permissions: List[str] = []
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    warn_default_password: bool = False


class UserCreate(BaseModel):
    login: str
    password: str
    role: str = "operator"
    permissions: List[str] = []

    @field_validator("login")
    @classmethod
    def validate_login(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Логин не может быть пустым")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 4:
            raise ValueError("Пароль должен содержать не менее 4 символов")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("admin", "operator"):
            raise ValueError("Роль должна быть 'admin' или 'operator'")
        return v


class UserUpdate(BaseModel):
    role: Optional[str] = None
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("superadmin", "admin", "operator"):
            raise ValueError("Роль должна быть 'superadmin', 'admin' или 'operator'")
        return v


class UserPasswordChange(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 4:
            raise ValueError("Пароль должен содержать не менее 4 символов")
        return v


class ChannelPayload(BaseModel):
    name: str
    source: str
    enabled: bool = True
    roi_enabled: bool = True
    region: Dict[str, Any] | None = None


class ROIRegionPayload(BaseModel):
    unit: str = Field(default="percent", pattern="^(px|percent)$")
    points: List[Dict[str, float]] = Field(default_factory=list)


class PlateSizePayload(BaseModel):
    width: int = Field(ge=1, le=4000)
    height: int = Field(ge=1, le=4000)


class ChannelConfigPayload(BaseModel):
    name: str
    source: str
    enabled: Optional[bool] = None
    controller_id: Optional[int] = None
    controller_relay: int = Field(default=0, ge=0, le=1)
    controller_direction_filter: str = Field(default="both", pattern="^(approaching|receding|both)$")
    list_filter_mode: str = Field(default="all", pattern="^(all|whitelist|custom)$")
    list_filter_list_ids: List[int] = Field(default_factory=list)
    detection_mode: str = Field(default="motion", pattern="^(always|motion)$")
    motion_threshold: float = Field(default=0.01, ge=0.0, le=1.0)
    motion_frame_stride: int = Field(default=1, ge=1, le=30)
    motion_activation_frames: int = Field(default=3, ge=1, le=120)
    motion_release_frames: int = Field(default=6, ge=1, le=120)
    detector_frame_stride: int = Field(default=2, ge=1, le=30)
    adaptive_stride_enabled: bool = True
    size_filter_enabled: bool = True
    min_plate_size: PlateSizePayload = Field(default_factory=lambda: PlateSizePayload(width=80, height=20))
    max_plate_size: PlateSizePayload = Field(default_factory=lambda: PlateSizePayload(width=600, height=240))
    best_shots: int = Field(default=3, ge=1, le=20)
    cooldown_seconds: int = Field(default=5, ge=0, le=300)
    ocr_min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    max_ocr_attempts: int = Field(default=15, ge=1, le=200)
    max_consecutive_empty_ocr: int = Field(default=5, ge=0, le=200)
    preview_fps_limit: int = Field(default=5, ge=1, le=30)
    roi_enabled: bool = True
    region: ROIRegionPayload = Field(default_factory=ROIRegionPayload)
    zone_before_id: Optional[int] = None
    zone_after_id: Optional[int] = None
    zone_channel_type: Optional[str] = Field(default=None, pattern="^(entry|exit)$")

    @field_validator("controller_id")
    @classmethod
    def normalize_controller_id(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if int(value) <= 0:
            return None
        return int(value)

    @field_validator("zone_before_id", "zone_after_id")
    @classmethod
    def validate_zone_endpoint(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        v = int(value)
        return v if v >= 0 else None

    @model_validator(mode="after")
    def clear_zone_type_when_no_zone(self) -> "ChannelConfigPayload":
        if self.zone_before_id is None or self.zone_after_id is None:
            self.zone_channel_type = None
        return self


class ChannelOCRPayload(BaseModel):
    best_shots: int = Field(ge=1, le=20)
    cooldown_seconds: int = Field(ge=0, le=300)
    ocr_min_confidence: float = Field(ge=0.0, le=1.0)
    max_ocr_attempts: int = Field(default=15, ge=1, le=200)
    max_consecutive_empty_ocr: int = Field(default=5, ge=0, le=200)


class ChannelFilterPayload(BaseModel):
    list_filter_mode: str = Field(pattern="^(all|whitelist|custom)$")
    list_filter_list_ids: List[int] = []
    size_filter_enabled: bool = True
    min_plate_size: Dict[str, int] = {"width": 80, "height": 20}
    max_plate_size: Dict[str, int] = {"width": 600, "height": 240}


def _normalize_hotkey(value: str) -> str:
    return normalize_hotkey(value, strict=True)


class RelayPayload(BaseModel):
    mode: str = Field(default="pulse", pattern="^(pulse|pulse_timer)$")
    timer_seconds: int = Field(default=1, ge=1, le=3600)
    hotkey: str = ""

    @field_validator("hotkey")
    @classmethod
    def normalize_hotkey(cls, value: str) -> str:
        return _normalize_hotkey(value)

    @model_validator(mode="after")
    def normalize_timer(self) -> "RelayPayload":
        if self.mode == "pulse":
            self.timer_seconds = 1
        return self


class ControllerPayload(BaseModel):
    name: str
    type: str = Field(default="DTWONDER2CH", min_length=1, max_length=64)
    address: str
    password: str = "0"
    relays: List[RelayPayload]

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        controller_type = str(value or "").strip()
        if not controller_type:
            return "DTWONDER2CH"
        if controller_type not in SUPPORTED_CONTROLLER_TYPES:
            supported = ", ".join(SUPPORTED_CONTROLLER_TYPES)
            raise ValueError(f"Неподдерживаемый тип контроллера: {controller_type}. Поддерживаются: {supported}")
        return controller_type

    @model_validator(mode="after")
    def validate_relays(self) -> "ControllerPayload":
        if len(self.relays) != 2:
            raise ValueError("Контроллер должен содержать ровно 2 реле")
        hotkeys = [relay.hotkey for relay in self.relays if relay.hotkey]
        if len(hotkeys) != len(set(hotkeys)):
            raise ValueError("Хоткеи реле должны быть уникальными")
        return self


class ControllerTestPayload(BaseModel):
    relay_index: int = Field(ge=0, le=1)
    is_on: bool = True


class ListPayload(BaseModel):
    name: str
    type: str = "white"


class ClientPayload(BaseModel):
    plate: str
    last_name: str = ""
    first_name: str = ""
    middle_name: str = ""
    phone: str = ""
    car: str = ""
    comment: str = ""


class AttachClientPayload(BaseModel):
    list_id: int


class UpdateListPayload(BaseModel):
    name: str
    type: str = "white"


class BulkImportPayload(BaseModel):
    clients: List[ClientPayload]


class RetentionPolicyPayload(BaseModel):
    auto_cleanup_enabled: bool = True
    cleanup_interval_minutes: int = 30
    events_retention_days: int = 30
    media_retention_days: int = 14
    max_screenshots_mb: int = 4096


class ExportBundlePayload(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    channel_id: Optional[int] = None
    include_media: bool = True


class ReconnectSignalLossPayload(BaseModel):
    enabled: bool = True
    frame_timeout_seconds: int = Field(default=5, ge=1, le=300)
    retry_interval_seconds: int = Field(default=5, ge=1, le=300)


class ReconnectPeriodicPayload(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=1, le=1440)


class ReconnectPayload(BaseModel):
    signal_loss: ReconnectSignalLossPayload
    periodic: ReconnectPeriodicPayload


class StoragePayload(BaseModel):
    postgres_dsn: Optional[str] = None
    auto_cleanup_enabled: bool
    cleanup_interval_minutes: int = Field(ge=1, le=1440)
    events_retention_days: int = Field(ge=1, le=3650)
    media_retention_days: int = Field(ge=1, le=3650)
    max_screenshots_mb: int = Field(ge=128, le=1024 * 1024)


class InterfacePayload(BaseModel):
    style: str = Field(default="graphite-minimal", pattern="^(graphite-minimal|aurora)$")
    theme: str = Field(default="light", pattern="^(light|dark)$")
    sidebar_locked: bool = False


class LoggingPayload(BaseModel):
    level: str = Field(pattern="^(ALL|DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    retention_days: int = Field(ge=1, le=3650)


class TimePayload(BaseModel):
    timezone: str


class PlatesPayload(BaseModel):
    enabled_countries: List[str] = Field(default_factory=list)


class DebugPayload(BaseModel):
    show_channel_metrics: bool = True
    log_panel_enabled: bool = False
    disable_video_output: bool = False


class GlobalSettingsPayload(BaseModel):
    reconnect: ReconnectPayload
    storage: StoragePayload
    logging: LoggingPayload
    interface: InterfacePayload
    time: TimePayload
    plates: PlatesPayload
    debug: DebugPayload


class ZonePayload(BaseModel):
    name: str
    capacity: int = Field(default=0, ge=0)


class ZoneUpdatePayload(BaseModel):
    name: str
    capacity: int = Field(ge=0)

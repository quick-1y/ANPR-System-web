from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from config.registry import (
    CHANNEL_PLATE_SIZES,
    CHANNEL_SPECS,
    ENUMS,
    REGISTRY as CONFIG_REGISTRY,
    choices_pattern,
)
from config.settings_schema import (
    SUPPORTED_CONTROLLER_TYPES,
    normalize_hotkey,
)



def _channel_field(name: str, **overrides: Any) -> Any:
    """Field for a channel setting: default, bounds and choices from the registry."""
    spec = CHANNEL_SPECS[name]
    kwargs: Dict[str, Any] = {"default": spec.default}
    if spec.minimum is not None:
        kwargs["ge"] = spec.minimum
    if spec.maximum is not None:
        kwargs["le"] = spec.maximum
    if spec.choices is not None:
        kwargs["pattern"] = choices_pattern(spec.choices)
    kwargs.update(overrides)
    return Field(**kwargs)


def _plate_size(name: str) -> "PlateSizePayload":
    return PlateSizePayload(**CHANNEL_PLATE_SIZES[name])


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
        # 'superadmin' is deliberately not assignable here, same as in
        # UserCreate: it is a technical account defined only through
        # SUPERADMIN_PASSWORD (config/env_settings.py) and never a DB row
        # (roadmap, docs/roadmap/configuration-architecture.md section 14).
        if v is not None and v not in ("admin", "operator"):
            raise ValueError("Роль должна быть 'admin' или 'operator'")
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
    unit: str = Field(default="percent", pattern=choices_pattern(ENUMS["roi_unit"]))
    points: List[Dict[str, float]] = Field(default_factory=list)


class PlateSizePayload(BaseModel):
    width: int = Field(ge=1, le=4000)
    height: int = Field(ge=1, le=4000)


class ChannelConfigPayload(BaseModel):
    name: str
    source: str
    enabled: Optional[bool] = None
    controller_id: Optional[int] = None
    controller_relay: int = _channel_field("controller_relay")
    controller_direction_filter: str = _channel_field("controller_direction_filter")
    list_filter_mode: str = _channel_field("list_filter_mode")
    list_filter_list_ids: List[int] = Field(default_factory=list)
    detection_mode: str = _channel_field("detection_mode")
    motion_threshold: float = _channel_field("motion_threshold")
    motion_frame_stride: int = _channel_field("motion_frame_stride")
    motion_activation_frames: int = _channel_field("motion_activation_frames")
    motion_release_frames: int = _channel_field("motion_release_frames")
    detector_frame_stride: int = _channel_field("detector_frame_stride")
    adaptive_stride_enabled: bool = _channel_field("adaptive_stride_enabled")
    size_filter_enabled: bool = _channel_field("size_filter_enabled")
    min_plate_size: PlateSizePayload = Field(default_factory=lambda: _plate_size("min_plate_size"))
    max_plate_size: PlateSizePayload = Field(default_factory=lambda: _plate_size("max_plate_size"))
    best_shots: int = _channel_field("best_shots")
    cooldown_seconds: int = _channel_field("cooldown_seconds")
    ocr_min_confidence: float = _channel_field("ocr_min_confidence")
    max_ocr_attempts: int = _channel_field("max_ocr_attempts")
    max_consecutive_empty_ocr: int = _channel_field("max_consecutive_empty_ocr")
    preview_fps_limit: int = _channel_field("preview_fps_limit")
    roi_enabled: bool = True
    region: ROIRegionPayload = Field(default_factory=ROIRegionPayload)
    zone_before_id: Optional[int] = None
    zone_after_id: Optional[int] = None
    zone_channel_type: Optional[str] = Field(default=None, pattern=choices_pattern(ENUMS["zone_channel_type"]))

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
    best_shots: int = _channel_field("best_shots")
    cooldown_seconds: int = _channel_field("cooldown_seconds")
    ocr_min_confidence: float = _channel_field("ocr_min_confidence")
    max_ocr_attempts: int = _channel_field("max_ocr_attempts")
    max_consecutive_empty_ocr: int = _channel_field("max_consecutive_empty_ocr")


class ChannelFilterPayload(BaseModel):
    list_filter_mode: str = _channel_field("list_filter_mode")
    list_filter_list_ids: List[int] = []
    size_filter_enabled: bool = True
    min_plate_size: Dict[str, int] = Field(default_factory=lambda: dict(CHANNEL_PLATE_SIZES["min_plate_size"]))
    max_plate_size: Dict[str, int] = Field(default_factory=lambda: dict(CHANNEL_PLATE_SIZES["max_plate_size"]))


def _normalize_hotkey(value: str) -> str:
    return normalize_hotkey(value, strict=True)


class RelayPayload(BaseModel):
    mode: str = Field(default="pulse", pattern=choices_pattern(ENUMS["relay_mode"]))
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
    auto_cleanup_enabled: bool
    cleanup_interval_minutes: int = Field(ge=1, le=1440)
    events_retention_days: int = Field(ge=1, le=3650)
    media_retention_days: int = Field(ge=1, le=3650)
    max_screenshots_mb: int = Field(ge=128, le=1024 * 1024)


class InterfacePayload(BaseModel):
    """Instance display zone (app_settings). `None` = leave unchanged.

    Theme and style are not settings at all: they live in the browser's
    localStorage (class L, no server owner) — see `app/web/js/appearance.js`.
    """

    #: IANA zone of the instance. `None` keeps an untouched setting distinguishable
    #: from an explicit choice of UTC.
    display_timezone: Optional[str] = None


class LoggingPayload(BaseModel):
    level: str = Field(pattern=choices_pattern(ENUMS["log_level"]))
    retention_days: int = Field(ge=1, le=3650)


class PlatesPayload(BaseModel):
    enabled_countries: List[str] = Field(default_factory=list)


class DebugPayload(BaseModel):
    """Server-side debug flag (app_settings `debug.video_output_enabled`)."""

    video_output_enabled: bool = True


class AuthPayload(BaseModel):
    """Authentication policy (app_settings `auth.*`); bounds come from the registry.
    `None` = leave unchanged."""

    token_ttl_minutes: Optional[int] = Field(default=None, ge=CONFIG_REGISTRY["auth.token_ttl_minutes"].minimum, le=CONFIG_REGISTRY["auth.token_ttl_minutes"].maximum)
    login_rate_limit_attempts: Optional[int] = Field(default=None, ge=CONFIG_REGISTRY["auth.login_rate_limit_attempts"].minimum, le=CONFIG_REGISTRY["auth.login_rate_limit_attempts"].maximum)
    login_rate_limit_window_seconds: Optional[int] = Field(default=None, ge=CONFIG_REGISTRY["auth.login_rate_limit_window_seconds"].minimum, le=CONFIG_REGISTRY["auth.login_rate_limit_window_seconds"].maximum)


class DetectionPayload(BaseModel):
    confidence_threshold: float = Field(ge=0.0, le=1.0)


class GlobalSettingsPayload(BaseModel):
    reconnect: ReconnectPayload
    storage: StoragePayload
    logging: LoggingPayload
    interface: InterfacePayload = InterfacePayload()
    plates: PlatesPayload
    #: Optional: `None` leaves the stored threshold unchanged (needs a processor restart).
    detection: Optional[DetectionPayload] = None
    auth: AuthPayload = AuthPayload()
    debug: Optional[DebugPayload] = None


class ZonePayload(BaseModel):
    name: str
    capacity: int = Field(default=0, ge=0)


class ZoneUpdatePayload(BaseModel):
    name: str
    capacity: int = Field(ge=0)

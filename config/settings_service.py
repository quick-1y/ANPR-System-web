"""Сервис настроек класса A поверх БД и реестра (roadmap, задача 2.1).

Единая точка чтения и записи операционных настроек, корректная в нескольких
процессах (api и retention_worker):

* чтение — значение из `app_settings`, а при его отсутствии дефолт реестра
  (правило 2: `app_settings` → константа);
* кэш в памяти, который раз в `cache_ttl_seconds` сверяет счётчик `revision`
  и перечитывает таблицу, только если тот изменился;
* запись — с валидацией по реестру и списком ключей, требующих перезапуска;
* недоступная БД не ломает чтение: возвращается последний кэш, а если его
  ещё не было — дефолты реестра.
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from common.logging import get_logger
from config.registry import ConfigClass, SettingValidationError, get_spec, specs
from database.settings_repository import AppSettingsRepository

logger = get_logger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 5.0


class SettingsService:
    def __init__(
        self,
        repository: AppSettingsRepository,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repository = repository
        self._ttl = float(cache_ttl_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        # Один поток за раз ходит в БД; остальные не ждут её, а читают кэш.
        self._refresh_lock = threading.Lock()
        self._effective: Dict[str, Any] = self._defaults()
        self._configured: frozenset = frozenset()
        self._revision: Optional[int] = None
        self._loaded = False
        self._checked_at: Optional[float] = None
        self._degraded = False

    # ── Read ──────────────────────────────────────────────────────────

    def get(self, key: str) -> Any:
        """Действующее значение ключа класса A: переопределение из БД либо дефолт."""
        self._require_class_a(key)
        self._refresh_if_stale()
        with self._lock:
            return copy.deepcopy(self._effective[key])

    def is_configured(self, key: str) -> bool:
        """`True`, если у ключа есть допустимая строка в `app_settings`.

        Отличает «администратор явно выбрал значение» (в том числе равное
        дефолту) от «действует дефолт реестра» — нужно зоне отображения,
        чей ненастроенный вид подсвечивается в интерфейсе (4.9).
        """
        self._require_class_a(key)
        self._refresh_if_stale()
        with self._lock:
            return key in self._configured

    def get_section(self, prefix: str) -> Dict[str, Any]:
        """Все ключи под *prefix*; имена возвращаются относительно префикса.

        `get_section("retention")` даёт `{"events_retention_days": 30, ...}`,
        `get_section("reconnect")` — `{"signal_loss.enabled": True, ...}`.
        """
        head = prefix.rstrip(".") + "."
        self._refresh_if_stale()
        with self._lock:
            section = {key[len(head):]: copy.deepcopy(value) for key, value in self._effective.items() if key.startswith(head)}
        if not section:
            raise KeyError(f"В реестре нет настроек класса A с префиксом {prefix!r}")
        return section

    @property
    def loaded(self) -> bool:
        """`True`, если значения хотя бы раз были успешно прочитаны из БД.

        Пока это `False`, `get` отдаёт дефолты реестра — не настройки
        оператора; потребители, для которых различие критично (retention,
        удаляющий данные), могут дождаться первой загрузки.
        """
        return self._loaded

    @property
    def degraded(self) -> bool:
        """`True`, если последняя попытка обратиться к БД не удалась."""
        return self._degraded

    # ── Write ─────────────────────────────────────────────────────────

    def update(self, mapping: Dict[str, Any], updated_by: Optional[int] = None) -> List[str]:
        """Проверить и записать настройки одной транзакцией.

        Записывается всё или ничего: при первой же ошибке валидации в БД не
        уходит ни одно значение. Возвращает отсортированный список ключей,
        значение которых изменилось и для применения требует перезапуска.
        Ошибка БД не скрывается — запись, в отличие от чтения, не может
        молча превратиться в no-op.
        """
        validated: Dict[str, Any] = {}
        for key, value in mapping.items():
            spec = self._require_class_a(key)
            if spec.reserved:
                raise SettingValidationError(f"{key}: ключ зарезервирован и пока не имеет потребителя")
            validated[key] = spec.validate(value)
        if not validated:
            return []

        current = {key: self.get(key) for key in validated}
        self._repository.set_many(validated, updated_by)
        # Следующее чтение сверит ревизию сразу, не дожидаясь окна кэша.
        with self._lock:
            self._checked_at = None
        return sorted(key for key, value in validated.items() if get_spec(key).requires_restart and value != current[key])

    def stored_values(self) -> Dict[str, Any]:
        """Explicit overrides only (rows in app_settings), not the registry defaults.

        This is what a settings backup carries: defaults are code, and freezing
        them into a dump would stop a future default change from reaching a
        restored instance.
        """
        self._refresh_if_stale()
        with self._lock:
            return {key: copy.deepcopy(self._effective[key]) for key in sorted(self._configured)}

    def replace(self, mapping: Dict[str, Any], updated_by: Optional[int] = None) -> List[str]:
        """Make the stored overrides equal to *mapping* (validated as a whole first).

        Keys absent from *mapping* lose their override and fall back to the
        registry default. Returns the restart-requiring keys whose effective
        value changed.
        """
        validated: Dict[str, Any] = {}
        for key, value in mapping.items():
            spec = self._require_class_a(key)
            if spec.reserved:
                raise SettingValidationError(f"{key}: ключ зарезервирован и пока не имеет потребителя")
            validated[key] = spec.validate(value)
        before = {key: self.get(key) for key in self._defaults()}
        self._repository.replace_all(validated, updated_by)
        with self._lock:
            self._checked_at = None
        after = {**self._defaults(), **validated}
        return sorted(key for key, value in after.items() if get_spec(key).requires_restart and value != before[key])

    # ── Cache ─────────────────────────────────────────────────────────

    def _refresh_if_stale(self) -> None:
        if not self._is_stale():
            return
        # Пока кэша нет вовсе, ждём загрузку; когда он есть — не блокируем
        # читателей ожиданием БД (у пула соединений долгий таймаут).
        if not self._refresh_lock.acquire(blocking=not self._loaded):
            return
        try:
            if not self._is_stale():
                return
            self._reload()
        finally:
            self._refresh_lock.release()

    def _is_stale(self) -> bool:
        with self._lock:
            return self._checked_at is None or self._clock() - self._checked_at >= self._ttl

    def _reload(self) -> None:
        try:
            revision = self._repository.revision()
            if self._loaded and revision == self._revision:
                self._mark_checked(ok=True)
                return
            # Ревизия читается до значений: запись между двумя запросами лишь
            # вызовет лишнюю перезагрузку, но не оставит в кэше устаревшее.
            stored = self._repository.get_all()
        except Exception as exc:  # noqa: BLE001
            self._mark_checked(ok=False, error=exc)
            return
        effective = self._overlay(stored)
        configured = frozenset(key for key in stored if key in effective and effective[key] is not None and self._is_valid(key, stored[key]))
        with self._lock:
            self._effective = effective
            self._configured = configured
            self._revision = revision
            self._loaded = True
        self._mark_checked(ok=True)

    def _mark_checked(self, *, ok: bool, error: Optional[Exception] = None) -> None:
        with self._lock:
            self._checked_at = self._clock()
            was_degraded = self._degraded
            self._degraded = not ok
        if not ok and not was_degraded:
            logger.warning("Настройки недоступны в БД, используется последний кэш или дефолты реестра: %s", error)
        elif ok and was_degraded:
            logger.info("Доступ к настройкам в БД восстановлен")

    @staticmethod
    def _defaults() -> Dict[str, Any]:
        return {spec.key: copy.deepcopy(spec.default) for spec in specs(ConfigClass.A)}

    @classmethod
    def _overlay(cls, stored: Dict[str, Any]) -> Dict[str, Any]:
        """Наложить строки БД на дефолты; недопустимые и чужие строки игнорируются."""
        effective = cls._defaults()
        for key, value in stored.items():
            if key not in effective:
                logger.warning("В app_settings найден ключ %r, которого нет среди настроек класса A — игнорируется", key)
                continue
            try:
                effective[key] = get_spec(key).validate(value)
            except SettingValidationError as exc:
                logger.warning("Значение %r в app_settings недопустимо (%s) — действует дефолт реестра", key, exc)
        return effective

    @staticmethod
    def _is_valid(key: str, value: Any) -> bool:
        try:
            get_spec(key).validate(value)
        except SettingValidationError:
            return False
        return True

    @staticmethod
    def _require_class_a(key: str):
        spec = get_spec(key)
        if spec.cls is not ConfigClass.A:
            raise KeyError(f"{key!r} — настройка класса {spec.cls.value}, а не app_settings")
        return spec


__all__ = ["DEFAULT_CACHE_TTL_SECONDS", "SettingsService"]

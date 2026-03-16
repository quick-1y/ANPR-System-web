"""Механизм совместимости/upgrade системных настроек до актуальной схемы."""

from .runner import run_settings_migrations

__all__ = ["run_settings_migrations"]

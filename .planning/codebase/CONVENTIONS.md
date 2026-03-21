# Coding Conventions

**Analysis Date:** 2026-03-21

## Naming Patterns

**Files:**
- `snake_case.py` for all Python modules: `motion_detector.py`, `anpr_pipeline.py`, `settings_schema.py`
- `__init__.py` for package markers
- Test files: `test_<component>.py`: `test_motion_detector.py`, `test_plate_validator.py`

**Functions:**
- `snake_case()` for all functions and methods
- Private methods prefixed with single underscore: `_should_analyze()`, `_normalize_service_name()`
- Class methods use `@classmethod` decorator and `cls` parameter: `from_config()`, `normalize_hotkey()`
- Static methods use `@staticmethod` decorator

**Variables:**
- `snake_case` for local and instance variables
- ALL_CAPS for module-level constants: `LOG_FILENAME_TIME_FORMAT`, `DEFAULT_LEVEL`, `DEFAULT_LOG_DIR`
- Private module-level variables prefixed with underscore: `_STATE_LOCK`, `_LOG_QUEUE`, `_CURRENT_SERVICE_NAME`
- Constants for sentinel values: `APPROACHING`, `RECEDING`, `UNKNOWN` (class attributes in uppercase)

**Types:**
- PascalCase for classes: `MotionDetector`, `TrackAggregator`, `TrackDirectionEstimator`
- PascalCase for dataclasses: `MotionDetectorConfig`, `PlateFormat`, `CountryConfig`
- PascalCase for Pydantic models: `BaseModel` subclasses like `ChannelPayload`, `ControllerPayload`

## Code Style

**Formatting:**
- No explicit formatter configured (Ruff or Black not detected)
- 4-space indentation (inferred from codebase)
- Line length appears flexible, no hard limit enforced

**Linting:**
- No `.eslintrc` or similar config files detected
- Uses type hints throughout: `from __future__ import annotations` at top of all Python files
- Type hints are used for function parameters and returns: `def update(self, frame: cv2.Mat) -> bool:`

**Import statements:**
- `from __future__ import annotations` always first (enables PEP 563 string evaluation)
- Standard library imports first
- Third-party imports grouped together
- Local imports last
- Use `TYPE_CHECKING` imports for circular dependency avoidance: see `anpr/pipeline/anpr_pipeline.py` line 14

**Path Aliases:**
- No path aliases detected; imports use relative dot notation: `from app.api.container import AppContainer`
- Root-level imports from `anpr`, `app`, `common`, `config`, `controllers`, `database`, `runtime`

## Error Handling

**Patterns:**
- Custom exception classes in `database/errors.py`: `StorageUnavailableError(RuntimeError)`
- FastAPI uses `HTTPException` for API responses with status codes: `raise HTTPException(status_code=404, detail="message")`
- Pydantic validators use `raise ValueError()` for field validation failures
- Try-except blocks for file operations, logging cleanup, and handler management
- Bare `except Exception:` used in logging handlers to prevent handler errors from crashing: `except Exception: self.handleError(record)`
- Graceful degradation: handlers log `handleError()` instead of raising

**Example from `common/logging.py`:**
```python
try:
    message = self.format(record)
    with self._lock:
        self._open_stream(datetime.now().astimezone())
        if self._stream is not None:
            self._stream.write(f"{message}\n")
            self._stream.flush()
except Exception:
    self.handleError(record)
```

## Logging

**Framework:** Python's built-in `logging` module

**Configuration:** Centralized in `common/logging.py`
- Custom `HourlyFileHandler` for hourly log rotation by service name
- Custom `ServiceNameFilter` to inject service name into all log records
- Custom `LiveDebugHandler` publishes logs to `DebugLogBus` for real-time API consumption
- `QueueListener` + `QueueHandler` for thread-safe async logging
- Configurable via config dict with keys: `level`, `logs_dir`, `retention_days`

**Patterns:**
- Get logger via `logging.getLogger(__name__)` or helper: `get_logger(name: str) -> logging.Logger`
- Performance metrics logged with custom function: `log_perf_stage(logger, channel, stage, duration_ms, **extra)`
- Example from `common/logging.py` line 277-288:
```python
def log_perf_stage(logger, channel, stage, duration_ms, level=logging.DEBUG, **extra):
    payload = {"channel": channel, "stage": stage, "duration_ms": round(float(duration_ms), 2)}
    payload.update(extra)
    parts = [f"{key}={value}" for key, value in payload.items()]
    logger.log(level, "perf %s", " ".join(parts))
```

## Comments

**When to Comment:**
- Class docstrings explain responsibility: `"""Простой детектор движения с учётом частоты обработки и устойчивостью к шуму."""`
- Method docstrings when behavior is non-obvious or has side effects
- Comments use Russian language (mixed with English for technical terms where appropriate)
- Minimal inline comments; code should be self-explanatory via clear naming

**JSDoc/TSDoc:**
- Not used; this is a Python codebase
- Docstrings follow Python convention with triple quotes

## Function Design

**Size:**
- Functions tend toward medium (10-30 lines)
- Longer functions use helper methods with descriptive names: `_should_analyze()`, `_normalize_service_name()`, `_evict_stale()`

**Parameters:**
- Prefer explicit parameters over *args/**kwargs
- Use type hints on all parameters
- Optional parameters explicitly typed: `Optional[cv2.Mat]`, `Optional[Dict[str, Any]]`
- Default parameter values used: `config: dict[str, Any] | None = None`

**Return Values:**
- Explicit return type hints on all functions
- Boolean returns for state checks: `def update(self, frame: cv2.Mat) -> bool:`
- Dictionary returns for structured data: `Dict[str, Any]`, `Dict[str, str]`
- Empty string `""` used as falsy sentinel in some contexts (aggregator returns empty string on no result)

## Module Design

**Exports:**
- Explicit `__all__` in `database/errors.py`: `__all__ = ["StorageUnavailableError"]`
- No explicit barrel files detected; imports are direct: `from anpr.detection.motion_detector import MotionDetector`

**Barrel Files:**
- Package `__init__.py` files are minimal, often empty or import nothing
- Some packages like `app/api/routers/__init__.py` are empty

**Dataclass Usage:**
- Prefer dataclasses for config objects with `@dataclass`: `MotionDetectorConfig`
- Use Pydantic `BaseModel` for API schemas with validation: schemas in `app/api/schemas.py`
- Pydantic provides field validation via `@field_validator` and `@model_validator`

---

*Convention analysis: 2026-03-21*

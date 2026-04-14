# Coding Conventions

**Analysis Date:** 2026-04-14

## Naming Patterns

**Files:**
- `snake_case.py` for all Python modules: `anpr_pipeline.py`, `motion_detector.py`, `crnn_recognizer.py`
- `__init__.py` in every package directory (mostly empty)
- Test files prefixed with `test_`: `test_track_aggregator.py`, `test_auth_router.py`

**Functions:**
- `snake_case` for all functions and methods: `add_result()`, `should_process()`, `process_frame()`
- Private methods prefixed with underscore: `_evict_stale()`, `_best_candidate()`, `_normalize()`
- Factory/builder functions use descriptive names: `build_default_settings()`, `relay_defaults()`

**Variables:**
- `snake_case` for local variables and instance attributes: `track_id`, `best_shots`, `min_confidence`
- Private attributes prefixed with underscore: `self._track_ts`, `self._channel_label`, `self._dsn`
- Module-level private state uses `_UPPER_SNAKE`: `_STATE_LOCK`, `_LOG_QUEUE`, `_FILE_HANDLER`

**Constants:**
- `UPPER_SNAKE_CASE` for module-level constants: `SETTINGS_VERSION`, `DEFAULT_LEVEL`, `CLEANUP_INTERVAL_SECONDS`
- Auth constants: `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRATION_MINUTES` in `app/api/auth_utils.py`

**Types/Classes:**
- `PascalCase` for all classes: `TrackAggregator`, `MotionDetector`, `PlatePostProcessor`, `UserDatabase`
- Dataclasses follow the same convention: `MotionDetectorConfig`, `PlateFormat`, `ChannelMetrics`
- Private dataclasses prefixed with underscore: `_TrackOCRState`
- API request schemas suffixed with `Payload` or `Request`: `ChannelPayload`, `LoginRequest`
- API response schemas suffixed with `Out`: `UserOut`, `LoginResponse`

## Code Style

**Formatting:**
- No automated formatter configured (no ruff.toml, .flake8, pyproject tool sections for formatting)
- Consistent 4-space indentation throughout
- Line length generally kept under ~120 characters
- Trailing commas used in multi-line function signatures and data structures

**Linting:**
- No formal linter configuration file
- `# noqa: BLE001` comments used on intentional broad `except Exception` blocks

**`from __future__ import annotations`:**
- Present in every Python source file. Always use it in new files.

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first)
2. Standard library imports (`os`, `re`, `time`, `threading`, `collections`, `dataclasses`, `typing`)
3. Third-party imports (`numpy`, `cv2`, `torch`, `fastapi`, `pydantic`, `yaml`, `jwt`, `bcrypt`)
4. Local/project imports (`from common.logging import get_logger`, `from database.base import PooledDatabase`)

**Conditional imports for type checking:**
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from anpr.recognition.crnn_recognizer import CRNNRecognizer
```
Use `TYPE_CHECKING` blocks to avoid circular dependencies.

**Path style:**
- Absolute imports from project root: `from common.logging import get_logger`
- Relative imports within the same package: `from .country_config import CountryConfig`
- No path aliases or import rewriting configured

## Error Handling

**Custom exceptions:**
- `StorageUnavailableError(RuntimeError)` in `database/errors.py` — PostgreSQL temporarily unavailable

**HTTPException pattern in API routers:**
```python
# 404 for missing resources
raise HTTPException(status_code=404, detail="Канал не найден")

# 503 for database unavailability — via helper
except StorageUnavailableError as exc:
    raise container.storage_503(exc) from exc

# 400 for invalid input
raise HTTPException(status_code=400, detail="before_ts и before_id должны передаваться вместе")

# 429 for rate limiting
raise HTTPException(status_code=429, detail="Слишком много попыток входа. Повторите через минуту.")
```
- Error detail messages are in Russian
- Always re-raise with `from exc` to preserve exception chain

**Broad `except Exception` usage:**
- Used intentionally in infrastructure code (logging handlers, database operations, controller communication)
- Always annotated with `# noqa: BLE001` when intentional
- In database layer: `except Exception as exc: # noqa: BLE001` wraps into `StorageUnavailableError`

**Pydantic validation errors:**
```python
raise ValueError("Хоткей должен содержать только одну основную клавишу")
raise ValueError("Контроллер должен содержать ровно 2 реле")
```

## Logging

**Framework:** Python standard `logging` with custom infrastructure in `common/logging.py`

**Logger acquisition:**
```python
from common.logging import get_logger
logger = get_logger(__name__)
```
Always call `get_logger(__name__)` at module level. Never use `logging.getLogger()` directly.

**Log levels:**
- `ALL` maps to `logging.NOTSET` (shows everything)
- `DEBUG` — per-OCR-attempt details
- `INFO` — consensus reached, startup messages
- `WARNING` — device fallback warnings

**Log format:**
```
%(asctime)s [%(levelname)s] [%(service)s] %(name)s: %(message)s
```

**Russian log messages in pipeline code:**
```python
logger.info(
    "%s, трек %d: номер \"%s\" подтверждён по консенсусу после %d OCR попыток.",
    self._channel_label, track_id, consensus, state.ocr_attempts,
)
```
- Pipeline messages always start with `self._channel_label` for channel context
- Channel label format: `"Канал {name} (id={id})"`
- Use `%s`/`%d`/`%.2f` formatting (lazy evaluation), **never f-strings in log calls**

## Comments

**Docstrings:**
- Russian docstrings for classes and key methods:
```python
class TrackAggregator:
    """Агрегирует результаты распознавания в рамках одного трека."""

class HourlyFileHandler(logging.Handler):
    """Файловый обработчик с ротацией по часу и service-prefix в имени файла."""
```

**Inline comments:**
- Section separators in test files using dashes:
```python
# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------
```
- Russian comments for business logic: `# Если список был пустым, загружаем всё`
- `# noqa:` comments with rule codes when suppressing linters

## Function Design

**Parameters:**
- Keyword-only arguments for optional/config params: `def __init__(self, ..., *, ocr_height: int = 32)`
- Type hints on all function signatures
- `Optional[X]` or `X | None` for nullable parameters
- Clamping in `__init__`: `self.best_shots = max(1, best_shots)`

**Return values:**
- Return empty string `""` for "no result" rather than `None` (in aggregator/pipeline)
- Return `bool` for state queries: `should_process()`, `_on_cooldown()`
- Return dataclasses for structured results: `PlatePostprocessResult`
- Return `Dict[str, Any]` for JSON-serializable API responses

## Module Design

**Dataclass vs Pydantic:**
- **Dataclasses** for internal domain models and configuration: `MotionDetectorConfig`, `PlateFormat`, `ChannelMetrics`
- **Pydantic `BaseModel`** exclusively for API request/response schemas: all `*Payload`, `*Request`, `*Out` classes in `app/api/schemas.py`
- Use `Field(ge=, le=, pattern=)` for Pydantic validation constraints

**Settings schema:**
- `config/settings_schema.py` uses plain functions returning `Dict[str, Any]` for defaults
- Each group has a `*_defaults()` function: `storage_defaults()`, `logging_defaults()`
- `build_default_settings()` assembles the full configuration dict

**Protocol classes for interfaces:**
```python
class BatchRecognizer(Protocol):
    """Минимальный контракт OCR-распознавателя для упрощения тестирования."""
    def recognize_batch(self, plate_images: List[np.ndarray]) -> List[tuple[str, float]]:
        ...
```

**Database repositories:**
- All extend `PooledDatabase` from `database/base.py`
- Override `_schema_sql()` to return schema DDL
- Call `self._ensure_schema()` before first query (double-checked locking)
- Use `with self._connect() as conn:` for connection management

## Thread Safety Patterns

**Double-checked locking (shared pool, OCR singleton):**
```python
if pool is None:
    with _pool_registry_lock:
        pool = _pool_registry.get(dsn)
        if pool is None:
            pool = ConnectionPool(dsn, ...)
            _pool_registry[dsn] = pool
```

**Per-IP rate limiter with rolling window:**
```python
_failed_attempts: dict[str, list[float]] = defaultdict(list)
_attempts_lock = Lock()

def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    with _attempts_lock:
        attempts = [t for t in _failed_attempts[ip] if now - t < _RATE_WINDOW_SECONDS]
        _failed_attempts[ip] = attempts
        if len(attempts) >= _MAX_FAILED_ATTEMPTS:
            raise HTTPException(status_code=429, ...)
```

---

*Convention analysis: 2026-04-14*

# Coding Conventions

**Analysis Date:** 2026-03-25

## Naming Patterns

**Files:**
- `snake_case.py` for all Python modules: `anpr_pipeline.py`, `motion_detector.py`, `crnn_recognizer.py`
- `__init__.py` in every package directory (mostly empty)
- Test files prefixed with `test_`: `test_track_aggregator.py`, `test_plate_validator.py`

**Functions:**
- `snake_case` for all functions and methods: `add_result()`, `should_process()`, `process_frame()`
- Private methods prefixed with underscore: `_evict_stale()`, `_best_candidate()`, `_normalize()`
- Factory/builder functions use descriptive names: `build_default_settings()`, `relay_defaults()`

**Variables:**
- `snake_case` for local variables and instance attributes: `track_id`, `best_shots`, `min_confidence`
- Private attributes prefixed with underscore: `self._track_ts`, `self._channel_label`, `self._stream`
- Module-level private state uses `_UPPER_SNAKE`: `_STATE_LOCK`, `_LOG_QUEUE`, `_FILE_HANDLER`

**Constants:**
- `UPPER_SNAKE_CASE` for module-level constants: `SETTINGS_VERSION`, `DEFAULT_LEVEL`, `CLEANUP_INTERVAL_SECONDS`
- Class-level constants also `UPPER_SNAKE_CASE`: `TrackDirectionEstimator.APPROACHING`, `TrackAggregator._EVICT_INTERVAL`

**Types/Classes:**
- `PascalCase` for all classes: `TrackAggregator`, `MotionDetector`, `PlatePostProcessor`
- Dataclasses follow the same convention: `MotionDetectorConfig`, `PlateFormat`, `CorrectionRules`
- Private dataclasses prefixed with underscore: `_TrackOCRState`
- Pydantic models suffixed with `Payload`: `ChannelPayload`, `ControllerPayload`, `StoragePayload`

## Code Style

**Formatting:**
- No automated formatter (no pyproject.toml, .flake8, ruff.toml, or similar config files detected)
- Consistent 4-space indentation throughout
- Line length generally kept under ~120 characters; occasional long lines in comprehensions
- Trailing commas used in multi-line function signatures and data structures

**Linting:**
- No formal linter configuration file
- `# noqa: BLE001` comments used on intentional broad `except Exception` blocks, indicating awareness of linting rules (likely ruff/flake8 used informally)

**`from __future__ import annotations`:**
- Present in every Python source file (40/40 files). Always use it in new files.

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first)
2. Standard library imports (`os`, `re`, `time`, `threading`, `collections`, `dataclasses`, `typing`)
3. Third-party imports (`numpy`, `cv2`, `torch`, `fastapi`, `pydantic`, `yaml`)
4. Local/project imports (`from common.logging import get_logger`, `from anpr.pipeline.anpr_pipeline import ...`)

**Conditional imports for type checking:**
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from anpr.recognition.crnn_recognizer import CRNNRecognizer
```
Use `TYPE_CHECKING` blocks for imports needed only for type annotations to avoid circular dependencies.

**Path style:**
- Absolute imports from project root: `from common.logging import get_logger`
- Relative imports within the same package: `from .country_config import CountryConfig` (in `anpr/postprocessing/`)
- No path aliases or import rewriting configured

## Error Handling

**Custom exceptions:**
- `StorageUnavailableError(RuntimeError)` in `database/errors.py` — used when PostgreSQL is temporarily unavailable
- Module uses `__all__` to export: `__all__ = ["StorageUnavailableError"]`

**HTTPException pattern in API routers:**
```python
# 404 for missing resources
raise HTTPException(status_code=404, detail="Канал не найден")

# 503 for database unavailability — via helper
except StorageUnavailableError as exc:
    raise container.storage_503(exc) from exc

# 400 for invalid input
raise HTTPException(status_code=400, detail="before_ts и before_id должны передаваться вместе")
```
- Error detail messages are in Russian
- Always re-raise with `from exc` to preserve exception chain

**Broad `except Exception` usage:**
- Used intentionally in infrastructure code (logging handlers, database operations, controller communication)
- Always annotated with `# noqa: BLE001` when intentional
- In logging handlers: bare `except Exception:` followed by `self.handleError(record)` or silent `pass`
- In database layer: `except Exception as exc: # noqa: BLE001` followed by wrapping in `StorageUnavailableError`

**Pydantic validation errors:**
- Raised via `@field_validator` and `@model_validator` with Russian messages:
```python
raise ValueError("Хоткей должен содержать только одну основную клавишу")
raise ValueError("Контроллер должен содержать ровно 2 реле")
```

## Logging

**Framework:** Python standard `logging` module with custom infrastructure in `common/logging.py`

**Logger acquisition:**
```python
from common.logging import get_logger
logger = get_logger(__name__)
```
Always call `get_logger(__name__)` at module level. Never use `logging.getLogger()` directly in application code.

**Log levels:**
- `ALL` maps to `logging.NOTSET` (shows everything) — the default level in settings
- `DEBUG` — per-OCR-attempt details, validation pass/fail details
- `INFO` — consensus reached, budget exhausted outcomes, startup messages
- `WARNING` — device fallback warnings (e.g., GPU to CPU)
- Standard Python levels: `ALL`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

**Log format:**
```
%(asctime)s [%(levelname)s] [%(service)s] %(name)s: %(message)s
```
Timestamp format: `%Y-%m-%dT%H:%M:%S`

**Russian log messages in pipeline code:**
```python
logger.info(
    "%s, трек %d: номер \"%s\" подтверждён по консенсусу после %d OCR попыток.",
    self._channel_label, track_id, consensus, state.ocr_attempts,
)
logger.debug(
    "%s, трек %d: OCR попытка %d/%d, кандидат \"%s\", confidence=%.2f.",
    self._channel_label, track_id, attempts, self.aggregator.max_ocr_attempts, current_text or "(пусто)", confidence,
)
```
- Pipeline log messages always start with `self._channel_label` for channel context
- Channel label format: `"Канал {name} (id={id})"`
- Use `%s`/`%d`/`%.2f` formatting (lazy evaluation), never f-strings in log calls

**Channel context in logs:**
- `LiveDebugHandler` in `common/logging.py` extracts `channel_id` from log records via `getattr(record, "channel_id", None)`
- `ServiceNameFilter` injects `service` attribute into every log record

**Infrastructure logging messages are also in Russian:**
```python
logger.info("Удалено устаревших логов: %s", removed)
```

## Comments

**Docstrings:**
- Russian docstrings for classes and key methods:
```python
class TrackAggregator:
    """Агрегирует результаты распознавания в рамках одного трека."""

class HourlyFileHandler(logging.Handler):
    """Файловый обработчик с ротацией по часу и service-prefix в имени файла."""
```
- Some docstrings mix Russian description with English technical details (see `TrackAggregator` full docstring)
- Module-level docstrings in Russian: `"""Пайплайн объединяющий детекцию и OCR."""`

**Inline comments:**
- Section separators in test files using dashes:
```python
# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
```
- Russian comments for explaining business logic: `# Если список был пустым или конфиги не найдены, загружаем всё`
- `# noqa:` comments with rule codes when suppressing linters

**When to comment:**
- Comment non-obvious algorithmic decisions
- Comment `noqa` suppressions with reason in Russian when complex: `# noqa: BLE001 - хотим логировать любые сбои инференса`

## Function Design

**Size:**
- Functions are generally compact (10-40 lines)
- `process_frame()` in `anpr/pipeline/anpr_pipeline.py` is the largest (~100 lines) — main orchestration method

**Parameters:**
- Use keyword-only arguments for optional/config params: `def __init__(self, ..., *, ocr_height: int = 32)`
- Type hints on all function signatures
- `Optional[X]` or `X | None` for nullable parameters
- Default values for configuration parameters with `max()`/`min()` clamping in `__init__`:
```python
self.best_shots = max(1, best_shots)
self.ttl_seconds = max(5.0, float(ttl_seconds))
```

**Return values:**
- Return empty string `""` for "no result" rather than `None` (in aggregator/pipeline)
- Return `bool` for state queries: `should_process()`, `_on_cooldown()`
- Return dataclasses for structured results: `PlatePostprocessResult`
- Return `Dict[str, Any]` for JSON-serializable API responses

## Module Design

**Exports:**
- `__all__` used sparingly — only in `database/errors.py`
- No barrel files (re-export patterns) — import directly from the defining module

**Dataclass vs Pydantic:**
- **Dataclasses** for internal domain models and configuration: `MotionDetectorConfig`, `PlateFormat`, `CorrectionRules`, `_TrackOCRState`, `PlatePostprocessResult`
- **Pydantic `BaseModel`** exclusively for API request validation: all `*Payload` classes in `app/api/schemas.py`
- Use `Field(ge=, le=, pattern=)` for Pydantic validation constraints
- Use `@field_validator` and `@model_validator` for complex validation logic

**Settings schema:**
- `config/settings_schema.py` uses plain functions returning `Dict[str, Any]` for defaults — no dataclass or Pydantic model
- Each settings group has a `*_defaults()` function: `storage_defaults()`, `logging_defaults()`, `direction_defaults()`
- `build_default_settings()` assembles the full default configuration dict

**Protocol classes for interfaces:**
```python
class BatchRecognizer(Protocol):
    """Минимальный контракт OCR-распознавателя для упрощения тестирования."""
    def recognize_batch(self, plate_images: List[np.ndarray]) -> List[tuple[str, float]]:
        ...
```
Use `Protocol` from `typing` for duck-typing interfaces.

---

*Convention analysis: 2026-03-25*

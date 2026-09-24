---
last_mapped_commit: 9cfd79b3a864f23127a46c35300f838c212d0007
last_mapped_at: 2026-09-24
---
# Coding Conventions

**Analysis Date:** 2026-09-24

## Naming Patterns

**Files:**

- `snake_case.py` - All Python files use lowercase with underscores (e.g., `channel_runtime.py`, `anpr_pipeline.py`, `plate_validator.py`)

**Functions:**

- `snake_case()` - Public functions use lowercase with underscores (e.g., `process_frame()`, `build_components()`)
- `_snake_case()` - Private/internal functions prefixed with single underscore (e.g., `_configure_thread_limits()`, `_normalize()`, `_build_reconnect_config()`)

**Classes:**

- `PascalCase` - Standard classes in PascalCase (e.g., `ChannelProcessor`, `TrackAggregator`, `PlatePostProcessor`)
- `_PascalCase` - Private dataclasses prefixed with underscore (e.g., `_TrackOCRState`)

**Variables:**

- `snake_case` - Local variables and instance variables (e.g., `track_id`, `best_shots`, `reconnect_config`)

**Constants:**

- `UPPER_SNAKE_CASE` - Module-level constants (e.g., `DEFAULT_LEVEL`, `LOG_FILENAME_TIME_FORMAT`, `_EVICT_INTERVAL`)

**Dataclasses:**

- `PascalCase` - Public value objects (e.g., `ChannelMetrics`, `ChannelContext`, `ReconnectConfig`, `PlatePostprocessResult`)

**Pydantic Models:**

- `PascalCase` suffix - Request/response models typically end with `Payload` or have a suffix (e.g., `LoginRequest`, `LoginResponse`, `UserOut`)

**Test Files:**

- `test_<component>.py` - Test files named after component (e.g., `test_track_aggregator.py`, `test_plate_validator.py`, `test_motion_detector.py`)

**Test Classes:**

- `Test<Component>` - Test classes prefixed with `Test` (e.g., `TestTrackAggregator`, `TestLogin`, `TestRussiaConfig`)

**Test Methods:**

- `test_<behavior>` - Test methods start with `test_` and describe behavior in snake_case (e.g., `test_no_emission_below_quorum`, `test_emits_on_quorum`)

**Test Helpers:**

- `_<name>()` - Module-level builder/helper functions prefixed with underscore (e.g., `_blank()`, `_noisy()`, `_make_format()`, `_ru_country()`, `_processor_with_ru()`)

**Module-Level Variables:**

- `_UPPER_SNAKE_CASE` or `_snake_case` - Private module-level variables prefixed with underscore (e.g., `_EVICT_INTERVAL`, `_LOG_QUEUE`, `_CLEANUP_THREAD`, `_failed_attempts`)

## Code Style

**Formatting:**

- No automated formatter configured (no .prettierrc, biome.json, or equivalent)
- Consistent 4-space indentation expected throughout codebase
- No ESLint or equivalent JavaScript linter

**Type Hints:**

- Required on all function signatures
- Use `from __future__ import annotations` at the top of every Python file
- Use PEP 604 union syntax: `str | None` instead of `Optional[str]`
- Use `TYPE_CHECKING` blocks for annotation-only imports to avoid circular dependencies:
  ```python
  if TYPE_CHECKING:
      from anpr.recognition.crnn_recognizer import CRNNRecognizer
  ```

**Import Organization:**

- Order: standard library, third-party packages, local project imports
- Absolute imports from project root preferred: `from common.logging import get_logger`
- Relative imports within same package acceptable: `from .country_config import CountryConfig`
- Example structure:
  ```python
  from __future__ import annotations
  
  import time
  from typing import TYPE_CHECKING
  
  from fastapi import FastAPI
  
  from app.api.container import AppContainer
  from common.logging import get_logger
  
  if TYPE_CHECKING:
      from some.type import OnlyForAnnotations
  ```

## Error Handling

**Strategy:**

- Broad `except Exception` blocks allowed in infrastructure/database code with explicit `# noqa: BLE001` comment
- Custom exceptions used for domain errors (e.g., `StorageUnavailableError`)
- Pydantic validators raise `ValueError` with Russian messages for domain validation
- FastAPI endpoints raise `HTTPException` with appropriate status codes and Russian error messages

**Pattern:**

```python
except Exception as exc:  # noqa: BLE001 - хотим логировать любые сбои инференса
    logger.warning("%s: ошибка: %s", self._channel_label, exc)
```

## Logging

**Framework:** Python standard `logging` module

**Initialization:**

- Always use `get_logger(__name__)` from `common/logging.py`, never `logging.getLogger()` directly
- Module-level logger instance: `logger = get_logger(__name__)`

**Log Message Formatting:**

- Use lazy `%` formatting: `logger.info("%s: %d frames", channel_name, count)`
- Never use f-strings in log calls (they evaluate eagerly)
- Channel context prefix pattern for ANPR pipeline: `"Канал {name} (id={id})"`

**Language:**

- Russian log messages for pipeline/domain logic (`anpr/`, `runtime/`)
- English log messages for infrastructure/API code
- Use Russian log messages when channel context is included

**Log Levels:**

- `DEBUG`: Per-frame diagnostics, detailed state tracking, validation results
- `INFO`: Consensus reached, budget exhausted, important state changes
- `WARNING`: Errors, retries, unusual conditions
- `ERROR`: Serious failures, data loss risks
- `CRITICAL`: System-level failures

**Example:**

```python
logger = get_logger(__name__)
logger.debug("%s: OCR result: '%s' (confidence=%.2f)", self._channel_label, text, confidence)
logger.info("%s: consensus reached: %s", self._channel_label, plate_text)
```

## Comments

**When to Comment:**

- Document non-obvious business logic (especially plate format rules, country-specific handling)
- Explain algorithm choices and edge cases
- Note workarounds, constraints, or version-specific quirks
- Mark technical debt with inline notes

**Language:**

- Russian for business logic and domain explanations
- English for infrastructure, API, and general technical notes

**Documentation:**

- Russian docstrings for classes and methods that implement business logic
- English docstrings for infrastructure, utility, and API functions
- Example:
  ```python
  class TrackAggregator:
      """Агрегирует результаты распознавания в рамках одного трека."""
      
  def _configure_thread_limits() -> None:
      """Limit internal threading for PyTorch/OpenCV to prevent CPU oversubscription."""
  ```

**Inline Comments:**

- Use `# noqa: <CODE>` with explanatory comment for linter suppressions
- Example: `except Exception as exc:  # noqa: BLE001 - хотим логировать любые сбои`

## Function Design

**Keyword-Only Arguments:**

- Use `*` to mark optional/config parameters as keyword-only:
  ```python
  def _reopen_capture(
      self,
      *,
      channel_id: int,
      source: str,
      stop_event: threading.Event,
  ) -> cv2.VideoCapture:
  ```

**Value Clamping:**

- Clamp config/parameter values in `__init__` with `max()`/`min()`:
  ```python
  self.best_shots = max(1, best_shots)
  self.ttl_seconds = max(5.0, float(ttl_seconds))
  ```

**Return Types:**

- Explicit return type hints on all function signatures
- Use empty string `""` for "no result" in string-returning functions (not `None`)
- Use boolean for detection/validation functions

## Module Design

**Private Functions:**

- Prefix internal module functions with `_`
- Private dataclasses prefixed with `_PascalCase`
- Private module variables prefixed with `_`

**Public API:**

- Functions/classes without `_` are public API
- Use `__all__` to define explicit exports (optional but recommended)

**Dataclasses vs Pydantic:**

- Dataclasses for internal domain models: `ChannelMetrics`, `ChannelContext`, `PlatePostprocessResult`
- Pydantic `BaseModel` for API request/response validation: `LoginRequest`, `LoginResponse`, `UserOut`

**Protocol Usage:**

- Use `Protocol` from `typing` for duck-typing interfaces instead of inheritance:
  ```python
  class BatchRecognizer(Protocol):
      """Minimal contract for OCR recognizer."""
      def recognize_batch(self, plate_images: List[np.ndarray]) -> List[tuple[str, float]]:
          ...
  ```

## Import Guidelines

**What NOT to do:**

- Do not create "utils" dumping grounds for unrelated logic
- Do not import from `controllers/` in `config/` (known coupling, is tech debt)
- Do not use `logging.getLogger()` directly (use `get_logger()`)

**What to do:**

- Always add `from __future__ import annotations` as the first import
- Group imports: stdlib → third-party → local
- Use `TYPE_CHECKING` blocks for annotation-only imports

---

*Convention analysis: 2026-09-24*

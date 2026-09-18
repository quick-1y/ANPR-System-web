# Coding Conventions

**Analysis Date:** 2026-09-18

## Naming Patterns

**Files:**
- Snake case: `auth_utils.py`, `yolo_detector.py`, `motion_detector.py`
- Test files: `test_*.py` (e.g., `test_auth_utils.py`, `test_auth_router.py`)
- Modules group related functionality: `detection/`, `postprocessing/`, `recognition/`

**Functions and Methods:**
- Snake case: `hash_password()`, `verify_password()`, `create_access_token()`
- Private functions prefixed with underscore: `_check_rate_limit()`, `_reset_tracker_state()`
- Method names are descriptive: `find_by_login()`, `list_all_users()`, `update_user()`

**Classes:**
- PascalCase: `YOLODetector`, `PlatePostProcessor`, `MotionDetector`, `UserOut`, `LoginRequest`
- Private classes prefixed with underscore: `_FallbackRecognizer`

**Constants:**
- UPPER_CASE: `JWT_SECRET_KEY`, `MAX_FAILED_ATTEMPTS`, `RATE_WINDOW_SECONDS`, `DEFAULT_LOG_DIR`
- Module-level private constants: `_OPERATOR_FORBIDDEN_PERMISSIONS`, `_MAX_FAILED_ATTEMPTS`

**Variables:**
- Snake case: `current_user`, `model_path`, `frame_shape`
- Private module-level variables: `_failed_attempts`, `_QUEUE_LISTENER`, `_FILE_HANDLER`

**Type Variables:**
- Use modern type hints: `dict[str, Any]`, `list[str]`, `Optional[int]` (from typing)
- Union types: `str | None` (Python 3.10+ syntax)

## Code Style

**File Structure:**
- Begin with shebang if executable: `#!/usr/bin/env python3`
- Import `from __future__ import annotations` for forward reference support
- Module-level docstring describing purpose
- Imports organized by group (stdlib, third-party, local)
- Constants at module level before functions/classes
- Functions and classes follow

**Function Documentation:**
- All public functions have docstrings in triple-quote format
- One-line summary or multi-line with description and return/raises info
- Example from `app/api/auth_utils.py`:
  ```python
  def decode_access_token(token: str) -> Dict[str, Any]:
      """Decode and validate a JWT access token.

      Returns the payload dict on success.
      Raises ``jwt.ExpiredSignatureError`` or ``jwt.InvalidTokenError`` on failure.
      """
  ```

**Method Documentation:**
- Router endpoints document what they do: `"""Authenticate with login + password, receive a JWT."""`
- Complex logic includes inline comments: `# Allow some tolerance for timing`
- Private methods may have brief docstrings

**Section Comments:**
- Major sections separated with ASCII comment lines:
  ```python
  # ---------------------------------------------------------------------------
  # Brute-force rate limiter (in-memory, per-IP, Phase 6)
  # ---------------------------------------------------------------------------
  ```

**Decorators:**
- Use `@staticmethod` for utility functions not needing state
- Use `@classmethod` with `cls` parameter for class methods
- `@field_validator` and `@model_validator` for Pydantic validation
- `@asynccontextmanager` for async context managers

## Import Organization

**Order:**
1. `from __future__ import annotations` (first if present)
2. Standard library imports (`os`, `sys`, `threading`, `datetime`, etc.)
3. Third-party imports (`fastapi`, `pydantic`, `torch`, `cv2`, etc.)
4. Local imports (relative or absolute from project root)

**Patterns:**
- Avoid `from module import *`
- Use explicit imports: `from app.api.auth_utils import hash_password, verify_password`
- Group related third-party imports together
- Example from `app/api/routers/auth.py`:
  ```python
  from __future__ import annotations

  import time
  from collections import defaultdict
  from threading import Lock
  from typing import Any, Dict

  from fastapi import APIRouter, Depends, HTTPException, Request

  from app.api.auth_utils import create_access_token, verify_password
  from app.api.container import AppContainer
  from app.api.deps import get_container, get_current_user, require_permission
  from app.api.schemas import LoginRequest, LoginResponse, UserOut

  from common.logging import get_logger
  ```

**Type Checking Imports:**
- Use `TYPE_CHECKING` guard for forward references to avoid circular imports:
  ```python
  from typing import TYPE_CHECKING

  if TYPE_CHECKING:
      from anpr.model_config import AnprModelConfig
  ```

## Type Hints

**Usage:**
- All function parameters should have type hints
- All function return types should be specified
- Use modern syntax: `dict[str, Any]`, `list[str]`, `str | None`
- Import types from `typing`: `Optional`, `Dict`, `List`, `Any`, `Tuple`

**Examples:**
```python
def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plain-text password."""
    ...

def create_access_token(
    user_id: int,
    role: str,
    exp_minutes: Optional[int] = None,
) -> str:
    """Create a signed JWT access token."""
    ...

def _make_user(user_id=1, login="superadmin") -> dict[str, Any]:
    return {...}
```

## Error Handling

**HTTP Errors:**
- Raise `HTTPException` with appropriate status codes:
  ```python
  raise HTTPException(status_code=401, detail="Неверный логин или пароль")
  raise HTTPException(status_code=404, detail="Пользователь не найден")
  raise HTTPException(status_code=409, detail="Пользователь с таким логином уже существует")
  raise HTTPException(status_code=429, detail="Слишком много попыток входа...")
  ```

**Exception Propagation:**
- Let library exceptions bubble up with logging context
- Example from `anpr/detection/yolo_detector.py`:
  ```python
  def _maybe_handle_cuda_op_error(self, exc: Exception, context: str) -> bool:
      if self.device.type == "cpu":
          return False
      if self._is_cuda_op_missing(exc):
          self._fallback_to_cpu(f"{context}: {exc}")
          return True
      return False
  ```

**Logging on Error:**
- Use `logger.warning()` for authentication failures and recoverable issues
- Use `logger.debug()` with `exc_info=True` for full stack traces
- Use `logger.info()` for important state changes
- Example:
  ```python
  logger.warning(
      "login_failed login='%s' ip='%s' reason='user_not_found'",
      body.login, ip,
  )
  logger.debug("Не удалось сбросить состояние трекера YOLO", exc_info=True)
  ```

**Validation:**
- Pydantic `@field_validator` for individual field validation
- Pydantic `@model_validator` for cross-field validation
- Raise `ValueError` with descriptive Russian messages
- Example from `app/api/schemas.py`:
  ```python
  @field_validator("login")
  @classmethod
  def validate_login(cls, v: str) -> str:
      v = v.strip()
      if not v:
          raise ValueError("Логин не может быть пустым")
      return v
  ```

## Logging

**Framework:** Python's built-in `logging` module via `get_logger(__name__)` from `common/logging.py`

**Patterns:**
- Get logger at module level: `logger = get_logger(__name__)`
- Use format strings, not f-strings: `logger.info("msg key=%s", value)`
- Log levels match severity:
  - `logger.info()` - State changes, successful operations
  - `logger.warning()` - Recoverable issues, degraded operations
  - `logger.debug()` - Detailed diagnostic info (usually with `exc_info=True`)

**Examples:**
```python
logger = get_logger(__name__)

logger.info("Детектор YOLO успешно загружен (model=%s, device=%s)", model_path, device)
logger.warning("Переключаем YOLO на CPU: %s", reason)
logger.warning(
    "login_failed login='%s' ip='%s' reason='inactive'",
    body.login, ip,
)
logger.info(
    "Создан пользователь: '%s' (role=%s, admin: %s)",
    body.login,
    body.role,
    current_user["login"],
)
logger.debug("Не удалось сбросить состояние трекера YOLO", exc_info=True)
```

**Structured Data:**
- Log additional context as key-value pairs (positional args, not dict)
- Include IDs, names, states needed for debugging
- Use consistent key names across codebase

## Comments

**When to Comment:**
- Explain complex business logic: rate limiting, permission checks, format validation
- Document non-obvious algorithmic choices
- Mark phase-specific code: `# Phase 5 user management`, `# Phase 6`
- Document known limitations: `# CRNN quantization with prepare_fx is not thread-safe`

**When NOT to Comment:**
- Don't repeat what code obviously does
- Don't comment simple assignments or loops
- Docstrings replace inline comments for function intent

**Format:**
- Use section separators for logical grouping:
  ```python
  # ---------------------------------------------------------------------------
  # Endpoints
  # ---------------------------------------------------------------------------
  ```
- Inline comments on same line or line above:
  ```python
  # Activate motion
  md.update(_noisy())
  ```

## Function Design

**Size:**
- Keep functions focused and single-purpose
- Aim for functions under 50 lines (exceptions for complex algorithms)
- Extract complex conditional chains into helper functions

**Parameters:**
- Use descriptive names: `model_path`, `detection_confidence_threshold`
- Default sensible values for optional parameters
- Group related parameters or use dataclasses/Pydantic for many params
- Type hint all parameters

**Return Values:**
- Return explicit types matching the type hint
- Return early to reduce nesting: `if not condition: return None`
- Avoid returning `None` without documenting the case

**Example:**
```python
def _check_rate_limit(ip: str) -> None:
    """Raise HTTP 429 if the IP has exceeded the failed-login limit."""
    now = time.monotonic()
    with _attempts_lock:
        attempts = [t for t in _failed_attempts[ip] if now - t < _RATE_WINDOW_SECONDS]
        _failed_attempts[ip] = attempts
        if len(attempts) >= _MAX_FAILED_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Слишком много попыток входа...")
```

## Module Design

**Exports:**
- Put public API at module level
- Use `__all__` only if you want to restrict `from module import *` (discouraged)
- Private functions/classes prefixed with underscore are not part of public API

**Barrel Files:**
- Avoid `__init__.py` files that re-export many items
- Example from `anpr/__init__.py`: typically empty or minimal
- Each module explicitly imports what it needs

**Dependencies:**
- Avoid circular imports using `TYPE_CHECKING` guard
- Keep module dependencies clear and acyclic
- Inject dependencies via function parameters or constructor

**Example Module Structure:**
```python
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from common.logging import get_logger

logger = get_logger(__name__)

# Constants
DEFAULT_TIMEOUT = 30

# Private module-level state
_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()

# Classes
class MyService:
    """Public service class."""
    ...

# Functions
def public_function(param: str) -> str:
    """Public function."""
    ...

def _private_helper(data: dict) -> bool:
    """Private helper function."""
    ...
```

## Pydantic Models

**Schema Definition:**
- Use `BaseModel` from pydantic v2
- Include default values where sensible
- Use `Field()` for additional constraints:
  ```python
  unit: str = Field(default="percent", pattern="^(px|percent)$")
  ```

**Validation:**
- Use `@field_validator` for individual field validation
- Use `@model_validator` for cross-field logic
- Raise `ValueError` with user-facing error message in Russian

**Example:**
```python
from pydantic import BaseModel, Field, field_validator

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
```

## Language Preference

- Code comments and docstrings: English
- User-facing messages (validation, error details): Russian
- Log messages: Russian for human readability
- Variable/function names: English (standard programming convention)

---

*Convention analysis: 2026-09-18*

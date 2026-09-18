# Testing Patterns

**Analysis Date:** 2026-09-18

## Test Framework

**Runner:**
- pytest (>=9.0.2, <10.0.0)
- Config: inline in `pyproject.toml` (minimal config, uses pytest defaults)

**Assertion Library:**
- Built-in `assert` statements
- `pytest.raises()` for exception testing

**Run Commands:**
```bash
pytest                    # Run all tests
pytest -xvs              # Run with verbose output and stop on first failure
pytest tests/test_auth_utils.py  # Run specific test file
pytest -k "test_login"   # Run tests matching pattern
```

**Coverage:**
- No enforced coverage requirements detected
- No coverage config in pyproject.toml

## Test File Organization

**Location:**
- Tests co-located in `tests/` directory (separate from source)
- Directory structure: `tests/` at project root, parallel to `anpr/`, `app/`, etc.

**Naming:**
- Test files: `test_*.py` (e.g., `test_auth_utils.py`, `test_motion_detector.py`)
- Test classes: `TestXxx` (e.g., `TestHashPassword`, `TestDecodeAccessToken`, `TestLogin`)
- Test methods: `test_xxx_yyy` (e.g., `test_returns_bcrypt_hash`, `test_wrong_password`)

**File List (17 test files):**
- `tests/test_auth_utils.py` - Auth utility functions (password hashing, JWT)
- `tests/test_auth_router.py` - Login/logout/me endpoints
- `tests/test_auth_deps.py` - Authentication dependencies
- `tests/test_users_router.py` - User management endpoints
- `tests/test_user_repository.py` - User database operations
- `tests/test_motion_detector.py` - Motion detection algorithm
- `tests/test_model_config.py` - Model configuration
- `tests/test_plate_validator.py` - License plate validation
- `tests/test_lists_repository.py` - List/client database operations
- `tests/test_channel_repository_zones.py` - Channel/zone database operations
- `tests/test_events_repository_zones.py` - Event database operations
- `tests/test_zones_repository.py` - Zone database operations
- `tests/test_zone_eligibility.py` - Zone eligibility logic
- `tests/test_track_aggregator.py` - Track aggregation logic
- `tests/test_direction_estimator.py` - Direction estimation
- `tests/test_permission_guards.py` - Permission validation
- `tests/test_settings_storage_cleanup.py` - Settings cleanup logic

## Test Structure

**Class-Based Organization:**
- Tests grouped by functionality under class with `Test` prefix
- Each class tests one component/function
- Allows shared setup via `setup_method()`

**Example from `tests/test_auth_utils.py`:**
```python
class TestHashPassword:
    def test_returns_bcrypt_hash(self):
        hashed = hash_password("hello")
        assert hashed.startswith("$2")
        assert len(hashed) == 60

    def test_different_calls_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


class TestVerifyPassword:
    def test_correct_password(self):
        hashed = hash_password("secret")
        assert verify_password("secret", hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("secret")
        assert verify_password("wrong", hashed) is False
```

**Section Comments:**
- Separate test classes with ASCII comment lines for readability:
  ```python
  # ---------------------------------------------------------------------------
  # Password hashing / verification
  # ---------------------------------------------------------------------------

  class TestHashPassword:
      ...

  # ---------------------------------------------------------------------------
  # JWT creation
  # ---------------------------------------------------------------------------

  class TestCreateAccessToken:
      ...
  ```

**Module Docstrings:**
- All test files begin with module-level docstring explaining scope:
  ```python
  """Tests for app/api/auth_utils.py

  Covers JWT creation/validation and password hashing/verification.
  """
  ```

## Test Setup and Teardown

**setup_method():**
- Called before each test method in a class
- Used to reset shared state (e.g., rate limiter state)
- Example from `tests/test_auth_router.py`:
  ```python
  class TestLogin:
      def setup_method(self):
          # Clear rate-limiter state before each test
          _failed_attempts.clear()
  ```

**No conftest.py:**
- Project does not use pytest fixtures
- All test data creation done via helper functions
- Fixtures created inline within test files

## Mocking

**Framework:**
- `unittest.mock.MagicMock` for creating mock objects
- `unittest.mock.patch` decorator for patching
- No third-party mocking library (requests-mock, responses, etc.)

**Helper Functions:**
- Private functions (prefixed with `_`) create test objects
- Located at top of test file or in test class

**Example from `tests/test_auth_router.py`:**
```python
def _make_user(user_id=1, login="superadmin", role="superadmin", is_active=True,
               permissions=None, password="1234", password_changed_at=None):
    return {
        "id": user_id,
        "login": login,
        "password": hash_password(password),
        "role": role,
        "permissions": permissions or [],
        "is_active": is_active,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "password_changed_at": password_changed_at,
    }


def _make_container(user=None):
    container = MagicMock()
    container.user_db.find_by_login.return_value = user
    return container


def _make_request(ip="127.0.0.1"):
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = ip
    return req
```

**Context Manager Mocking:**
- When mocking database connections with context manager protocol:
  ```python
  def _mock_conn(fetchone=None, fetchall=None, rowcount=1):
      cursor = MagicMock()
      cursor.__enter__ = lambda s: s
      cursor.__exit__ = MagicMock(return_value=False)
      cursor.fetchone.return_value = fetchone
      cursor.fetchall.return_value = fetchall or []
      cursor.rowcount = rowcount

      conn = MagicMock()
      conn.__enter__ = lambda s: s
      conn.__exit__ = MagicMock(return_value=False)
      conn.cursor.return_value = cursor
      conn.commit = MagicMock()
      return conn, cursor
  ```

**Testing Private Methods:**
- Private module-level constants can be tested by importing them
- Private class initialization uses `object.__new__()` to create uninitialized instance:
  ```python
  db = object.__new__(ListDatabase)
  db._dsn = "postgresql://mock"
  db._initialized = True
  db._init_lock = threading.Lock()
  db._pool = None
  ```

## Fixtures and Test Data

**Test Data Creation:**
- Factory functions build realistic test objects
- Located in test file, not in separate fixtures directory
- Named with `_make_xxx` pattern

**Examples:**
```python
# From tests/test_motion_detector.py
def _blank(h: int = 120, w: int = 160) -> np.ndarray:
    """Return a black BGR frame."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _noisy(h: int = 120, w: int = 160, value: int = 200) -> np.ndarray:
    """Return a uniform non-black BGR frame to simulate motion."""
    return np.full((h, w, 3), value, dtype=np.uint8)

# From tests/test_plate_validator.py
def _make_format(name: str, regex: str, display_format: str = "") -> PlateFormat:
    return PlateFormat(name=name, regex=regex, pattern=re.compile(regex), display_format=display_format)


def _ru_country() -> CountryConfig:
    """Minimal Russia-like config with one standard format А000АА77."""
    return CountryConfig(
        name="Russia",
        code="RU",
        priority=1,
        formats=[_make_format("standard", r"([АВЕКМНОРСТУХ])(\d{3})([АВЕКМНОРСТУХ]{2})(\d{2,3})", "{0} {1} {2} {3}")],
        valid_letters="АВЕКМНОРСТУХ",
        valid_digits="0123456789",
        corrections=CorrectionRules(
            digit_to_letter={"0": "О"},
            letter_to_digit={},
            common_mistakes=[{"from": "I", "to": "1"}],
        ),
        stop_words=["СТОП"],
        invalid_sequences=["000"],
    )
```

**Inline Subclasses:**
- Create custom mock implementations by subclassing:
  ```python
  def _inline_loader(configs):
      class _InlineLoader(CountryConfigLoader):
          def __init__(self, cfgs):
              self._cfgs = cfgs

          def load(self, enabled_codes=None):
              return self._cfgs

      return _InlineLoader(configs)
  ```

## Exception Testing

**Pattern:**
- Use `pytest.raises()` context manager
- Check exception type and details (status_code, message)
- Example from `tests/test_auth_router.py`:
  ```python
  def test_expired_token_raises(self):
      token = create_access_token(user_id=1, role="superadmin", exp_minutes=-1)
      with pytest.raises(pyjwt.ExpiredSignatureError):
          decode_access_token(token)

  def test_wrong_password(self):
      user = _make_user(password="1234")
      container = _make_container(user=user)
      body = LoginRequest(login="superadmin", password="wrong")

      with pytest.raises(HTTPException) as exc_info:
          login(body, _make_request(), container)
      assert exc_info.value.status_code == 401
  ```

**Exception Info Capture:**
- Use `as exc_info` to inspect exception details
- Access attributes like `.status_code`, `.detail`, `.value`

## Mocking Patterns

**What to Mock:**
- Database operations (psycopg connections, queries)
- External HTTP calls (if tested)
- File I/O
- Complex object dependencies (AppContainer, repositories)

**What NOT to Mock:**
- Utility functions under test (hash_password, verify_password)
- Pydantic models and validation
- Simple conditional logic
- datetime, time operations (use directly or patch if needed for time-dependent tests)

**Example: Mocking Database Calls**
```python
def test_valid_credentials(self):
    user = _make_user(password="1234")
    container = _make_container(user=user)
    body = LoginRequest(login="superadmin", password="1234")

    result = login(body, _make_request(), container)

    assert result.access_token
    assert result.token_type == "bearer"
    container.user_db.find_by_login.assert_called_once_with("superadmin")
```

**Example: Mocking with patch**
```python
from unittest.mock import patch

def test_with_patch(self):
    with patch('module.function') as mock_func:
        mock_func.return_value = "test"
        # test code
        assert mock_func.called
```

## Test Coverage Areas

**Unit Tests (main focus):**
- Password hashing/verification: `test_auth_utils.py`
- JWT token creation and validation: `test_auth_utils.py`
- Authorization endpoints: `test_auth_router.py`, `test_users_router.py`
- Permission guards: `test_permission_guards.py`
- Database operations: `test_user_repository.py`, `test_lists_repository.py`, etc.
- Validation logic: `test_plate_validator.py`, `test_zone_eligibility.py`
- Algorithms: `test_motion_detector.py`, `test_track_aggregator.py`, `test_direction_estimator.py`

**Not Tested:**
- Web UI (frontend JavaScript/React)
- Full end-to-end API flows (would require integration tests)
- Real video processing pipelines
- External service integrations (if any)

## Test Writing Checklist

When adding new tests:

1. **File Structure:**
   - [ ] Create `test_xxx.py` in `tests/` directory
   - [ ] Add module docstring explaining what's tested
   - [ ] Import all needed components

2. **Organization:**
   - [ ] Group related tests in `TestXxx` classes
   - [ ] Use `# ---` comment separators for major sections
   - [ ] Name test methods `test_xxx_yyy` describing what's tested

3. **Setup:**
   - [ ] Add `setup_method()` if shared state needs reset
   - [ ] Use `_make_xxx()` helper functions for test data
   - [ ] Keep test data realistic but minimal

4. **Assertions:**
   - [ ] Use simple `assert` statements
   - [ ] Check specific values, not just truthiness
   - [ ] Use `pytest.raises()` for exception cases

5. **Mocking:**
   - [ ] Mock external dependencies (DB, HTTP, file I/O)
   - [ ] Don't mock code under test
   - [ ] Verify mock calls when testing interactions

6. **Edge Cases:**
   - [ ] Test success path
   - [ ] Test error cases
   - [ ] Test boundary conditions (empty strings, zero values, None)
   - [ ] Test invalid inputs

## Example: Complete Test Class

```python
"""Tests for app/api/auth_utils.py

Covers JWT creation/validation and password hashing/verification.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import jwt as pyjwt
import pytest

from app.api.auth_utils import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    create_access_token,
    decode_access_token,
)


class TestDecodeAccessToken:
    def test_valid_token(self):
        token = create_access_token(user_id=7, role="superadmin")
        payload = decode_access_token(token)
        assert payload["sub"] == "7"
        assert payload["role"] == "superadmin"

    def test_expired_token_raises(self):
        token = create_access_token(user_id=1, role="superadmin", exp_minutes=-1)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_invalid_token_raises(self):
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token("not.a.valid.token")

    def test_tampered_token_raises(self):
        token = create_access_token(user_id=1, role="superadmin")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token(tampered)
```

---

*Testing analysis: 2026-09-18*

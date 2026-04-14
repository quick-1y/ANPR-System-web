# Testing Patterns

**Analysis Date:** 2026-04-14

## Test Framework

**Runner:**
- pytest (declared in `pyproject.toml` dev dependencies: `pytest>=9.0.2,<10.0.0`)
- No `pyproject.toml` pytest config section, no `pytest.ini`, no `conftest.py`

**Assertion Library:**
- Built-in `assert` statements (pytest rewrites)
- `pytest.approx()` for floating-point comparisons

**Run Commands:**
```bash
pytest                                     # Run all tests
pytest tests/                              # Run all tests in tests/
pytest tests/test_track_aggregator.py      # Run single file
pytest -v                                  # Verbose output
pytest -k "TestLogin"                      # Run specific class
```

## Test File Organization

**Location:**
- Separate `tests/` directory at project root (not co-located with source)

**Files (13 test files, ~2762 total lines):**

| File | Lines | Tests For |
|------|-------|-----------|
| `tests/test_auth_deps.py` | 193 | `get_current_user`, `require_role`, `require_permission` |
| `tests/test_auth_router.py` | 341 | Login, logout, me endpoints; rate limiter |
| `tests/test_auth_utils.py` | 110 | JWT create/verify, bcrypt hash/verify |
| `tests/test_direction_estimator.py` | 83 | `TrackDirectionEstimator` |
| `tests/test_lists_repository.py` | 510 | `ListDatabase`, `ClientDatabase` |
| `tests/test_motion_detector.py` | 92 | `MotionDetector` |
| `tests/test_permission_guards.py` | 172 | Permission guard dependencies |
| `tests/test_plate_validator.py` | 274 | `PlatePostProcessor` |
| `tests/test_settings_storage_cleanup.py` | 122 | Settings + storage lifecycle |
| `tests/test_track_aggregator.py` | 246 | `TrackAggregator` |
| `tests/test_user_repository.py` | 360 | `UserDatabase` CRUD |
| `tests/test_users_router.py` | 259 | Users API router |

**Naming:**
- Files: `test_{component_name}.py`
- Classes: `Test{ComponentName}` (e.g., `TestTrackAggregator`, `TestLogin`, `TestLoginAuth`)
- Methods: `test_{behavior_description}` in snake_case

## Test Structure

**Suite Organization:**
```python
"""Tests for app/api/routers/auth.py — login, logout, me endpoints.

Uses mocks to test auth router logic without a live server or DB.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

class TestLogin:
    def test_valid_credentials_return_token(self):
        """Returns JWT token for valid user credentials."""
        ...
```

**Patterns:**
- Module-level docstring describes what is tested and where the source lives
- Group related tests in classes (multiple classes per file for different aspects)
- Each test method has a one-line English docstring
- No `setUp`/`tearDown` in most tests — fresh objects per test
- `setup_method` when multiple tests share the same object:
```python
class TestRussiaConfig:
    def setup_method(self):
        self.proc = _processor_with_ru()
```

**Section separators between test classes:**
```python
# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------

class TestLogin:
    ...
```

## Mocking

**Two mocking patterns coexist:**

**Pattern 1 — Custom stub classes (pure domain tests):**
```python
class _EmptyLoader(CountryConfigLoader):
    def load(self, enabled_codes=None):
        return []

def _inline_loader(configs):
    class _InlineLoader(CountryConfigLoader):
        def __init__(self, cfgs):
            self._cfgs = cfgs
        def load(self, enabled_codes=None):
            return self._cfgs
    return _InlineLoader(configs)
```
Used for: ANPR pipeline, plate validator, config loaders — any pure logic test.

**Pattern 2 — `unittest.mock` (API router/dependency tests):**
```python
from unittest.mock import MagicMock, patch

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
Used for: auth router, users router, auth dependencies — anything that needs FastAPI request/container mocking.

**What NOT to mock:**
- The class under test — always use the real implementation
- Pure computation (validators, aggregators, estimators) — test directly

## Fixtures and Factories

**Inline builder functions (module-level helpers, prefixed with `_`):**
```python
def _blank(h: int = 120, w: int = 160) -> np.ndarray:
    """Return a black BGR frame."""
    return np.zeros((h, w, 3), dtype=np.uint8)

def _make_user(user_id=1, login="superadmin", role="superadmin", is_active=True,
               permissions=None, password="1234"):
    return {
        "id": user_id,
        "login": login,
        "password": hash_password(password),
        "role": role,
        "permissions": permissions or [],
        "is_active": is_active,
    }

def _processor_with_ru() -> PlatePostProcessor:
    return PlatePostProcessor(_inline_loader([_ru_country()]))
```

**Pattern:** Helpers are module-level, prefixed `_`, have docstrings. No `@pytest.fixture` decorators. No shared `conftest.py`. Helpers defined at top of each test file.

**pytest built-in fixtures used:**
- `tmp_path` for temporary file creation in YAML loading tests

## Coverage

**Requirements:** Not enforced. No coverage config or CI integration.

**View coverage:**
```bash
pytest --cov=anpr --cov=app --cov=database tests/   # requires pytest-cov
```

## Test Types

**Unit Tests (primary):**
- All 13 test files are unit tests
- Test individual classes in isolation
- No real database, network, or filesystem access (except `tmp_path`)
- Use synthetic data (numpy arrays, hand-built config objects, MagicMock containers)

**API Tests (via direct function calls, not HTTP):**
- `test_auth_router.py`, `test_users_router.py` — call router functions directly with mocked requests and containers
- Pattern: `result = login(body=LoginRequest(...), request=_make_request(), container=_make_container(user))`

**Integration Tests:** Not present  
**E2E Tests:** Not present  
**Tests hitting real DB:** Not present (all DB tests use mocks or in-memory data)

## Common Patterns

**Direct instantiation (no fixtures):**
```python
def test_first_frame_returns_false(self):
    md = MotionDetector(MotionDetectorConfig())
    assert md.update(_blank()) is False
```

**Sequence testing (stateful objects):**
```python
def test_motion_triggers_after_activation_frames(self):
    cfg = MotionDetectorConfig(threshold=0.001, activation_frames=3)
    md = MotionDetector(cfg)
    md.update(_blank())           # seed
    md.update(_noisy())           # motion 1
    md.update(_noisy(value=100))  # motion 2
    result = md.update(_noisy(value=50))  # motion 3 — activates
    assert result is True
```

**API test with MagicMock:**
```python
def test_valid_login_returns_token(self):
    user = _make_user()
    container = _make_container(user=user)
    result = login(
        body=LoginRequest(login="superadmin", password="1234"),
        request=_make_request(),
        container=container,
    )
    assert isinstance(result.token, str)
    assert result.token != ""
```

**Stale eviction with time manipulation:**
```python
def test_stale_eviction_cleans_state(self):
    agg = TrackAggregator(best_shots=3, ttl_seconds=5.0)
    agg.add_result(1, "ABC", 0.9)
    agg._track_ts[1] = _time.monotonic() - 60.0  # backdate timestamp
    agg._evict_stale(_time.monotonic())
    assert agg.should_process(1) is True
```

**Boundary / edge case testing:**
```python
def test_empty_bbox_returns_unknown(self):
    est = TrackDirectionEstimator()
    result = est.update(1, [])
    assert result["direction"] == UNKNOWN
```

**Float comparison:**
```python
assert est.confidence_threshold == pytest.approx(0.4)
```

**Assertions style:**
- `assert result == "expected"` for equality
- `assert result is True` / `assert result is False` for booleans
- `assert result in (APPROACHING, RECEDING, UNKNOWN)` for set membership
- `assert isinstance(result, bool)` for type checks
- Access private attributes when needed for state verification: `assert md._motion_active is True`

**Testing HTTPException raised by dependencies:**
```python
def test_rate_limit_raises_429(self):
    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit("127.0.0.1")
    assert exc_info.value.status_code == 429
```

---

*Testing analysis: 2026-04-14*

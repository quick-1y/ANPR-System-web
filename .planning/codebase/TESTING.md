---
last_mapped_commit: 9cfd79b3a864f23127a46c35300f838c212d0007
last_mapped_at: 2026-09-24
---
# Testing Patterns

**Analysis Date:** 2026-09-24

## Test Framework

**Runner:**

- pytest 9.0.2+ (specified in `pyproject.toml` as `pytest (>=9.0.2,<10.0.0)`)
- No pytest.ini config file; uses defaults
- No conftest.py — test utilities are module-level functions

**Run Commands:**

```bash
pytest                                          # Run all tests
pytest tests/test_track_aggregator.py           # Run single test file
pytest tests/test_track_aggregator.py::TestTrackAggregator::test_emits_on_quorum  # Run single test
pytest -v                                       # Verbose output with test names
pytest --tb=short                               # Brief traceback format
```

## Test File Organization

**Location:**

- Test files in `tests/` directory at project root
- Mirrors component structure but not strictly enforced
- Examples: `tests/test_track_aggregator.py`, `tests/test_plate_validator.py`, `tests/test_motion_detector.py`

**Naming:**

- Files: `test_<component>.py` (e.g., `test_auth_router.py`, `test_settings_service.py`)
- Classes: `Test<Component>` or `Test<Behavior>` (e.g., `TestTrackAggregator`, `TestLogin`, `TestNormalize`)
- Methods: `test_<behavior>` (e.g., `test_no_emission_below_quorum`, `test_valid_standard_plate`)

## Test Structure

**Class-Based Organization:**

```python
class TestTrackAggregator:
    def test_no_emission_below_quorum(self):
        """Does not emit until best_shots results are accumulated."""
        agg = TrackAggregator(best_shots=3)
        assert agg.add_result(1, "А123ВС77", 0.9) == ""
        assert agg.add_result(1, "А123ВС77", 0.9) == ""

    def test_emits_on_quorum(self):
        """Emits consensus text when quorum is reached."""
        agg = TrackAggregator(best_shots=3)
        agg.add_result(1, "А123ВС77", 0.9)
        agg.add_result(1, "А123ВС77", 0.9)
        result = agg.add_result(1, "А123ВС77", 0.9)
        assert result == "А123ВС77"
```

**Setup Per Test:**

```python
class TestLogin:
    def setup_method(self):
        """Called before each test in the class."""
        _failed_attempts.clear()  # Reset rate limiter state
        self.proc = _processor_with_ru()  # Initialize shared test fixture
```

**Per-File Helpers:**

```python

# Module-level builder functions with _ prefix

def _blank(h: int = 120, w: int = 160) -> np.ndarray:
    """Return a black BGR frame."""
    return np.zeros((h, w, 3), dtype=np.uint8)

def _noisy(h: int = 120, w: int = 160, value: int = 200) -> np.ndarray:
    """Return a uniform non-black BGR frame to simulate motion."""
    return np.full((h, w, 3), value, dtype=np.uint8)

def _make_format(name: str, regex: str, display_format: str = "") -> PlateFormat:
    """Helper to build PlateFormat test data."""
    return PlateFormat(name=name, regex=regex, pattern=re.compile(regex), display_format=display_format)

def _ru_country() -> CountryConfig:
    """Minimal Russia-like config for tests."""
    return CountryConfig(
        name="Russia",
        code="RU",
        priority=1,
        formats=[_make_format("standard", r"([АВЕКМНОРСТУХ])(\d{3})([АВЕКМНОРСТУХ]{2})(\d{2,3})")],
        # ... rest of config
    )
```

## Mocking

**Framework:** `unittest.mock` from Python standard library (imported as `from unittest.mock import MagicMock, patch`)

**Note:** AGENTS.md prescribes "no mocking libraries" and "inline stub classes," but the codebase actively uses `unittest.mock`. Tests use both approaches:

- `MagicMock` for FastAPI Request/Container mocks
- Inline builder functions for domain models

**Pattern Examples:**

**Using MagicMock for infrastructure:**

```python
def _make_container(user=None, stored=None):
    container = MagicMock()
    container.user_db.find_by_login.return_value = user
    container.settings_service = SettingsService(_Repo(stored), clock=_Clock())
    return container

def _make_request(ip="127.0.0.1"):
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = ip
    return req
```

**Using patch for time manipulation:**

```python
def test_password_expiry(self):
    hashed = hash_password("secret")
    with patch('time.time', return_value=base_time + 90_000_000):
        assert is_password_expired(hashed, days=1) is True
```

**Inline stubs for domain objects (preferred for domain logic):**

```python
class _InlineLoader(CountryConfigLoader):
    def __init__(self, cfgs):
        self._cfgs = cfgs
    
    def load(self, enabled_codes=None):
        return self._cfgs

processor = PlatePostProcessor(_InlineLoader([_ru_country()]))
```

## Test Patterns

**Simple Unit Test with Inline Data:**

```python
def test_empty_text_ignored(self):
    """Empty strings are not added to the bucket."""
    agg = TrackAggregator(best_shots=3)
    assert agg.add_result(1, "", 0.9) == ""
    assert agg.add_result(1, "", 0.9) == ""
    assert agg.add_result(1, "", 0.9) == ""
    assert agg.add_result(1, "А123ВС77", 0.9) == ""
```

**Parametrized Tests:**

```python
@pytest.mark.parametrize("name", sorted(REPO_DDL))
def test_repository_ddl_matches_schema_sql(name):
    owner, statement = REPO_DDL[name]
    assert name in SCHEMA_DDL, f"{owner} creates {name!r} but schema.sql does not"
    assert SCHEMA_DDL[name] == statement, f"{name!r}: schema.sql differs from {owner}"
```

**Testing with caplog (log capture):**

```python
def test_stale_eviction_is_logged_at_debug(self, caplog):
    """Verify logging behavior when tracks are evicted."""
    import time as _time
    
    agg = TrackAggregator(best_shots=3, ttl_seconds=5.0)
    agg.add_result(1, "ABC", 0.9)
    agg._track_ts[1] = _time.monotonic() - 60.0
    
    with caplog.at_level(logging.DEBUG, logger="anpr.pipeline.anpr_pipeline"):
        agg._evict_stale(_time.monotonic())
    
    assert any("устаревших треков" in r.message for r in caplog.records)
```

**Testing with pytest.approx() for floating-point:**

```python
def test_fps_calculation(self):
    # When comparing floats, use pytest.approx()
    assert processor.fps == pytest.approx(30.0, rel=0.1)
```

## Fixtures and Test Data

**Location:**

- No conftest.py — utilities live as module-level functions in test files
- Builders are per-file, shared across tests in that file

**Naming Convention:**

- Builder functions prefixed with `_`: `_blank()`, `_noisy()`, `_ru_country()`, `_make_user()`
- Builders return constructed test objects, not fixtures

**Pattern:**

```python
def _make_user(user_id=1, login="admin", role="superadmin", is_active=True):
    """Construct a DB-row user dict for tests."""
    return {
        "id": user_id,
        "login": login,
        "password": hash_password("password"),
        "role": role,
        "is_active": is_active,
        "created_at": datetime.now(timezone.utc),
    }

class TestUserRepository:
    def test_find_by_id(self):
        user = _make_user(user_id=42)
        repo.insert(user)
        assert repo.find_by_id(42) == user
```

## Test Structure by Type

**Unit Tests - Core Domain Logic:**

- Location: `tests/test_<component>.py`
- Scope: Single class/function, mocked dependencies
- Examples:
  - `tests/test_track_aggregator.py` - TrackAggregator consensus and budget logic
  - `tests/test_plate_validator.py` - PlatePostProcessor validation and corrections
  - `tests/test_motion_detector.py` - MotionDetector frame-by-frame logic

**Router/API Tests:**

- Location: `tests/test_<router_name>_router.py`
- Scope: Endpoint handlers with mocked container/DB
- Use `MagicMock` for FastAPI Request and container objects
- Examples:
  - `tests/test_auth_router.py` - Login, logout, rate limiting
  - `tests/test_users_router.py` - User CRUD endpoints
  - `tests/test_data_router.py` - Data export endpoints

**Schema Integrity Tests:**

- Location: `tests/test_schema_sync.py` (specific to database schema)
- Scope: Verify schema.sql matches repository DDL definitions
- Parametrized across all tables/indexes

**Environment/Config Tests:**

- Location: `tests/test_env_*.py`, `tests/test_*_settings.py`
- Scope: Settings loading, normalization, validation
- Examples:
  - `tests/test_env_settings.py` - EnvConfig loading and defaults
  - `tests/test_settings_service.py` - SettingsService cache and updates
  - `tests/test_deployment_env.py` - Production/development config validation

**Integration Tests:**

- Location: `tests/test_*_integration.py` (few exist; mostly unit-scoped)
- Scope: Multiple components together, real database if needed

## Coverage

**Requirements:** No explicit coverage target enforced in pyproject.toml

**Current Practice:**

- Core domain logic heavily tested (ANPR, aggregator, validators)
- Most API routers have corresponding test files
- Schema consistency verified via test_schema_sync.py
- No CI/CD enforced (manual testing before commits)

## Common Test Patterns

**Arrange-Act-Assert Pattern:**

```python
def test_motion_triggers_after_activation_frames(self):
    """Motion activates only after activation_frames consecutive frames."""
    # Arrange
    cfg = MotionDetectorConfig(threshold=0.001, activation_frames=3)
    md = MotionDetector(cfg)
    
    # Act
    md.update(_blank())
    md.update(_noisy())
    md.update(_noisy(value=100))
    result = md.update(_noisy(value=50))
    
    # Assert
    assert result is True
```

**Testing State Transitions:**

```python
def test_finalized_track_ignores_further_results(self):
    """After consensus, the track is finalized — further add_result returns empty."""
    agg = TrackAggregator(best_shots=3, max_ocr_attempts=100)
    agg.add_result(1, "ABC", 0.9)
    agg.add_result(1, "ABC", 0.9)
    result = agg.add_result(1, "ABC", 0.9)  # consensus
    assert result == "ABC"
    
    # Further attempts are silently ignored
    assert agg.add_result(1, "ABC", 0.9) == ""
    assert agg.add_result(1, "DEF", 0.99) == ""
```

**Testing Error Conditions:**

```python
def test_raises_on_invalid_config(self):
    """Invalid config raises ValueError on initialization."""
    with pytest.raises(ValueError, match="frame_timeout_seconds must be > 0"):
        ReconnectConfig(signal_loss_frame_timeout_seconds=-1)
```

**Testing Async Code (if present):**

- Use `pytest-asyncio` or `pytest.mark.asyncio` (if configured)
- Current codebase has minimal async test coverage; most async code runs in containers

## Test Docstring Convention

**Format:** English one-line summary describing the behavior being tested

**Examples:**

- `"""Does not emit until best_shots results are accumulated."""`
- `"""Emits consensus text when quorum is reached."""`
- `"""Empty strings are not added to the bucket."""`
- `"""Motion activates only after activation_frames consecutive frames."""`

## Assertion Guidelines

**Use plain `assert` statements:**

```python
assert agg.add_result(1, "А123ВС77", 0.9) == ""  # pytest rewrites these
```

**Use `pytest.approx()` for float comparisons:**

```python
assert result == pytest.approx(expected, rel=0.01)  # within 1% tolerance
```

**Use `pytest.raises()` for exception testing:**

```python
with pytest.raises(ValueError, match="invalid option"):
    process(bad_input)
```

**Use context managers for state setup:**

```python
with caplog.at_level(logging.DEBUG):
    function_that_logs()
```

## File Placement

**New test file:**

- `tests/test_<component>.py` if testing a single component
- `tests/test_<router>_router.py` if testing API endpoints
- `tests/test_<area>_*.py` for grouped tests (e.g., `test_auth_*.py` for authentication)

**Test organization within file:**

- Import statements (libraries, modules under test, builders)
- Builder functions (module-level `_*` functions)
- Test classes (`Test*` classes)
- Parametrized test data (if using `@pytest.mark.parametrize`)

---

*Testing analysis: 2026-09-24*

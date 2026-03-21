# Testing Patterns

**Analysis Date:** 2026-03-21

## Test Framework

**Runner:**
- pytest (no explicit version pinned in `requirements.txt`)
- Config: pytest.ini not detected; uses pytest defaults
- Test discovery: automatic via `test_*.py` naming convention

**Assertion Library:**
- pytest's built-in assertions (no additional library)

**Run Commands:**
```bash
pytest                    # Run all tests
pytest tests/            # Run tests directory only
pytest -v                # Verbose output
pytest --tb=short        # Short traceback format
pytest -k test_name      # Run tests matching pattern
```

## Test File Organization

**Location:**
- Separate `tests/` directory at project root: `/tests/`
- Not co-located with source files
- Test files exist in `/d/Users/qu1ck1y/Documents/pyProjects/ANPR-System-v0.8_web/tests/`

**Naming:**
- Pattern: `test_<component>.py`
- Examples: `test_motion_detector.py`, `test_plate_validator.py`, `test_track_aggregator.py`, `test_direction_estimator.py`

**Structure:**
```
tests/
├── __init__.py
├── test_motion_detector.py
├── test_plate_validator.py
├── test_track_aggregator.py
└── test_direction_estimator.py
```

## Test Structure

**Suite Organization:**
```python
class TestMotionDetector:
    def test_first_frame_returns_false(self):
        """Docstring describes test behavior."""
        md = MotionDetector(MotionDetectorConfig())
        assert md.update(_blank()) is False
```

**Patterns:**

- Tests organized in classes prefixed with `Test`: `TestMotionDetector`, `TestTrackAggregator`
- Individual tests as methods named `test_<behavior>`: `test_first_frame_returns_false()`
- Docstrings on test methods explain expected behavior (not all tests have docstrings)
- Setup via class methods when needed: `setup_method(self)` in `test_plate_validator.py` line 97

**Example from `test_plate_validator.py`:**
```python
class TestRussiaConfig:
    def setup_method(self):
        self.proc = _processor_with_ru()

    def test_valid_standard_plate(self):
        result = self.proc.process("А123ВС77")
        assert result.is_valid is True
        assert result.country == "RU"
        assert result.plate == "А123ВС77"
```

## Mocking

**Framework:** None detected in requirements.txt
- No `unittest.mock` imports in test files
- Tests use in-memory construction instead of mocking

**Patterns:**
```python
# From test_plate_validator.py — mock config with inline loader
class _InlineLoader(CountryConfigLoader):
    def __init__(self, configs):
        self._configs = configs

    def load(self, enabled_codes=None):
        return self._configs

loader = _InlineLoader([_ru_country()])
processor = PlatePostProcessor(loader)
```

- Custom test doubles (simple implementations) rather than mock library
- Inline fixture constructors: `_ru_country()`, `_processor_with_ru()`, `_blank()`, `_noisy()`

**What to Mock:**
- External dependencies (database, file system) — construct test doubles instead
- Complex configuration — provide inline builders like `_ru_country()`

**What NOT to Mock:**
- Classes under test — use real instances
- Internal calculations — test full behavior end-to-end
- String operations, arithmetic — test with real implementations

## Fixtures and Factories

**Test Data:**
```python
# From test_motion_detector.py
def _blank(h: int = 120, w: int = 160) -> np.ndarray:
    """Return a black BGR frame."""
    return np.zeros((h, w, 3), dtype=np.uint8)

def _noisy(h: int = 120, w: int = 160, value: int = 200) -> np.ndarray:
    """Return a uniform non-black BGR frame to simulate motion."""
    return np.full((h, w, 3), value, dtype=np.uint8)
```

**Location:**
- Fixture builders as module-level functions prefixed with underscore: `_blank()`, `_noisy()`, `_ru_country()`
- Inline in test file, not in conftest.py
- No pytest fixtures decorator; plain functions called directly in tests

## Coverage

**Requirements:** Not enforced
- No `.coveragerc` or coverage configuration detected
- No minimum coverage threshold in codebase

**View Coverage:**
```bash
pytest --cov=tests --cov-report=term-missing     # Terminal report
pytest --cov=tests --cov-report=html             # HTML report
```

## Test Types

**Unit Tests:**
- Scope: Individual functions and classes in isolation
- Approach: Test one responsibility per test method
- Examples: `test_motion_detector.py` tests `MotionDetector` class behavior without video input
- Use synthetic numpy arrays instead of real frames
- Testing state transitions: `test_motion_triggers_after_activation_frames()` validates state machine logic

**Integration Tests:**
- Scope: Not explicitly present in current test suite
- Would test multiple components working together
- Could extend to test `ANPRPipeline` with real `PlatePostProcessor`, `PlatePreprocessor`

**E2E Tests:**
- Framework: Not used
- Would require real camera stream or video file input
- Manual testing via API endpoints used instead (see debug router)

## Common Patterns

**Async Testing:**
```
Not detected — codebase is synchronous, no async tests needed
```

**Error Testing:**
```python
# From test_plate_validator.py — testing invalid inputs
def test_invalid_format(self):
    result = self.proc.process("123456")
    assert result.is_valid is False

def test_invalid_chars_rejected(self):
    result = self.proc.process("Z123ВС77")
    assert result.is_valid is False
```

- Tests validate error conditions by checking returned state/properties
- No exception assertions; errors are communicated via result objects
- Pattern: Pydantic models and validators prevent invalid data from entering code paths

**Parametrization:**
```
Not detected — no @pytest.mark.parametrize usage
```

- Tests use loops to cover multiple scenarios: see `test_motion_releases_after_release_frames()` lines 59-62
- Could be improved with parametrization

## Test Execution Context

**Data Setup:**
- Tests construct all objects from scratch in each test method
- No shared fixtures across tests
- `setup_method(self)` used in `TestRussiaConfig` for per-test initialization

**Assertions:**
- Direct equality assertions: `assert result is False`
- Checking object properties: `assert result.is_valid is True`
- Checking dictionary contents: `assert result["direction"] == UNKNOWN`
- `pytest.approx()` for floating point comparisons: `assert est.confidence_threshold == pytest.approx(0.4)`

---

*Testing analysis: 2026-03-21*

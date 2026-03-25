# Testing Patterns

**Analysis Date:** 2026-03-25

## Test Framework

**Runner:**
- pytest (no config file detected — uses defaults)
- No `pyproject.toml`, `pytest.ini`, `setup.cfg`, or `conftest.py` at project root

**Assertion Library:**
- Built-in `assert` statements (pytest rewrites)
- `pytest.approx()` for floating-point comparisons

**Run Commands:**
```bash
pytest                         # Run all tests
pytest tests/                  # Run all tests in tests/
pytest tests/test_track_aggregator.py  # Run single file
pytest -v                      # Verbose output
```

## Test File Organization

**Location:**
- Separate `tests/` directory at project root (not co-located with source)

**Files:**
- `tests/__init__.py` (empty)
- `tests/test_track_aggregator.py` — tests for `TrackAggregator` from `anpr/pipeline/anpr_pipeline.py`
- `tests/test_plate_validator.py` — tests for `PlatePostProcessor` from `anpr/postprocessing/validator.py`
- `tests/test_motion_detector.py` — tests for `MotionDetector` from `anpr/detection/motion_detector.py`
- `tests/test_direction_estimator.py` — tests for `TrackDirectionEstimator` from `anpr/pipeline/anpr_pipeline.py`

**Naming:**
- Files: `test_{component_name}.py`
- Classes: `Test{ComponentName}` (e.g., `TestTrackAggregator`, `TestMotionDetector`, `TestRussiaConfig`)
- Methods: `test_{behavior_description}` using snake_case (e.g., `test_no_emission_below_quorum`, `test_valid_standard_plate`)

**Structure:**
```
tests/
├── __init__.py
├── test_direction_estimator.py
├── test_motion_detector.py
├── test_plate_validator.py
└── test_track_aggregator.py
```

## Test Structure

**Suite Organization:**
```python
"""Tests for TrackAggregator consensus and OCR budget logic in anpr/pipeline/anpr_pipeline.py"""
import pytest
from anpr.pipeline.anpr_pipeline import TrackAggregator


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

**Patterns:**
- Module-level docstring describes what is tested and where the source lives
- Group related tests in classes (multiple classes per file when testing different aspects)
- Each test method has a one-line English docstring explaining expected behavior
- No `setUp`/`tearDown` in most tests — fresh objects created per test
- `setup_method` used when multiple tests share the same object:
```python
class TestRussiaConfig:
    def setup_method(self):
        self.proc = _processor_with_ru()
```

**Multiple test classes per file for logical grouping:**
- `test_track_aggregator.py`: `TestTrackAggregator` (consensus) + `TestTrackOCRBudget` (budget management)
- `test_plate_validator.py`: `TestNormalize`, `TestNoCountries`, `TestRussiaConfig`, `TestDisplayFormat`, `TestYAMLDisplayFormat`

**Section separators between test classes:**
```python
# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalize:
    ...
```

## Mocking

**Framework:** No mocking library (no unittest.mock, no pytest-mock)

**Custom test doubles — inline stub classes:**
```python
def _inline_loader(configs):
    class _InlineLoader(CountryConfigLoader):
        def __init__(self, cfgs):
            self._cfgs = cfgs
        def load(self, enabled_codes=None):
            return self._cfgs
    return _InlineLoader(configs)
```

```python
class _EmptyLoader(CountryConfigLoader):
    def __init__(self):
        pass
    def load(self, enabled_codes=None):
        return []
```

**What to mock (via custom doubles):**
- Configuration loaders to avoid filesystem dependency
- Replace YAML file loading with in-memory config objects

**What NOT to mock:**
- The class under test — always use the real implementation
- Pure computation (validators, aggregators, estimators) — test directly

## Fixtures and Factories

**Inline builder functions (module-level helpers):**
```python
def _blank(h: int = 120, w: int = 160) -> np.ndarray:
    """Return a black BGR frame."""
    return np.zeros((h, w, 3), dtype=np.uint8)

def _noisy(h: int = 120, w: int = 160, value: int = 200) -> np.ndarray:
    """Return a uniform non-black BGR frame to simulate motion."""
    return np.full((h, w, 3), value, dtype=np.uint8)
```

```python
def _make_format(name: str, regex: str, display_format: str = "") -> PlateFormat:
    return PlateFormat(name=name, regex=regex, pattern=re.compile(regex), display_format=display_format)

def _ru_country() -> CountryConfig:
    """Minimal Russia-like config with one standard format."""
    return CountryConfig(name="Russia", code="RU", priority=1, ...)

def _processor_with_ru() -> PlatePostProcessor:
    return PlatePostProcessor(_inline_loader([_ru_country()]))
```

```python
def _bbox(y: int, size: int) -> list[int]:
    """Convenience: square bbox centred around y."""
    half = size // 2
    return [100 - half, y - half, 100 + half, y + half]
```

**Pattern:** Helper functions are module-level, prefixed with underscore `_`, and have docstrings. No pytest fixtures (`@pytest.fixture`) are used. No shared `conftest.py`.

**Location:** Helpers are defined at the top of each test file, not in a shared utilities module.

## Coverage

**Requirements:** Not enforced. No coverage configuration or CI integration detected.

**View Coverage:**
```bash
pytest --cov=anpr --cov=common tests/   # If pytest-cov is installed
```

## Test Types

**Unit Tests:**
- All 4 test files are pure unit tests
- Test individual classes in isolation (TrackAggregator, PlatePostProcessor, MotionDetector, TrackDirectionEstimator)
- No database, network, or filesystem dependencies (except `tmp_path` for YAML loading test)
- Use synthetic data (numpy arrays for frames, hand-built config objects for validators)

**Integration Tests:**
- Not present

**E2E Tests:**
- Not present

**API Tests:**
- Not present (no tests for FastAPI routers)

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
    cfg = MotionDetectorConfig(threshold=0.001, activation_frames=3, release_frames=100)
    md = MotionDetector(cfg)
    md.update(_blank())           # seed
    md.update(_noisy())           # motion 1
    md.update(_noisy(value=100))  # motion 2
    result = md.update(_noisy(value=50))  # motion 3 — activates
    assert result is True
```

**Boundary/edge case testing:**
```python
def test_empty_bbox_returns_unknown(self):
    est = TrackDirectionEstimator()
    result = est.update(1, [])
    assert result["direction"] == UNKNOWN

def test_empty_frame_returns_false(self):
    md = MotionDetector(MotionDetectorConfig())
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    assert md.update(empty) is False
```

**Testing internal state when needed (pragmatic, not dogmatic):**
```python
def test_shape_change_resets_state(self):
    ...
    assert md._motion_active is True  # access private attr to verify state
```

**Stale eviction with time manipulation:**
```python
def test_stale_eviction_cleans_state(self):
    import time as _time
    agg = TrackAggregator(best_shots=3, ttl_seconds=5.0)
    agg.add_result(1, "ABC", 0.9)
    agg._track_ts[1] = _time.monotonic() - 60.0  # backdate timestamp
    agg._evict_stale(_time.monotonic())
    assert agg.should_process(1) is True
```

**pytest built-in fixtures used:**
- `tmp_path` for temporary file creation in YAML loading tests

**Float comparison:**
```python
assert est.confidence_threshold == pytest.approx(0.4)
```

**Assertions style:**
- `assert result == "expected"` for equality
- `assert result is True` / `assert result is False` for explicit boolean checks
- `assert result in (APPROACHING, RECEDING, UNKNOWN)` for set membership
- `assert isinstance(result, bool)` for type checks

---

*Testing analysis: 2026-03-25*

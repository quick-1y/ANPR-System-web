"""Runs the Node-based unit tests of the browser modules (roadmap phase 7).

`app/web/js/datetime.js` and `appearance-core.js` are written without imports
or DOM access at load time exactly so they can be tested here. The suite is
run under several process time zones: the display zone must come from the
server's setting, never from the machine the browser runs on.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS_TESTS = sorted((ROOT / "tests" / "js").glob("*.test.mjs"))

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")


@pytest.mark.parametrize("process_zone", ["UTC", "America/New_York", "Asia/Tokyo", "Pacific/Auckland"])
def test_browser_modules_behave_the_same_in_any_machine_zone(process_zone):
    result = subprocess.run(
        ["node", "--test", *map(str, JS_TESTS)],
        cwd=ROOT,
        env={**os.environ, "TZ": process_zone},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]

import importlib.util
import os
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("WSMCP_INTEGRATION") != "1", reason="Set WSMCP_INTEGRATION=1 on interactive Windows")
def test_real_windows_sandbox(tmp_path):
    spec = importlib.util.spec_from_file_location("integration_runner", Path(__file__).parents[1] / "scripts/integration.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    report = Path(__file__).parents[1] / "evidence/integration-pytest.json"
    assert runner.run(tmp_path, report)["passed"]

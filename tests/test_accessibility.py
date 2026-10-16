import copy

import pytest

from winsandbox_mcp.errors import SandboxError
from winsandbox_mcp.protocol import validate_result


@pytest.mark.parametrize("arguments", ["--flag", ["x\0y"], ["x"] * 129, [7], ["x" * 4097]])
def test_launch_rejects_invalid_arguments(session, arguments):
    with pytest.raises(SandboxError) as error:
        session.launch(arguments=arguments)
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("backend,view,timeout", [("other", "raw", 8), ("uia3", "other", 8),
                                                ("auto", "control", float("nan")), ("auto", "raw", 1)])
def test_inspection_options_validated(session, backend, view, timeout):
    with pytest.raises(SandboxError) as error:
        session.inspect(backend=backend, view=view, timeout=timeout)
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("options", [{"port": 80}, {"port": True}, {"port": 9222, "action": "evaluate"},
    {"port": 9222, "target_id": "http://host"}, {"port": 9222, "reference": "';command"},
    {"port": 9222, "text": "x\0"}])
def test_no_arbitrary_cdp_methods_or_endpoints(session, options):
    with pytest.raises(SandboxError) as error:
        session.browser(**options)
    assert error.value.code == "INVALID_ARGUMENT"


def browser_snapshot():
    return {"backend": "cdp", "target_id": "page-1", "snapshot_id": "a" * 32,
            "coordinate_space": "viewport-css", "nodes": [{"ref": "a" * 32 + ":0", "tag": "input",
            "role": "", "name": "Password", "value": None, "password": True, "enabled": True,
            "bounds": {"x": 1, "y": 2, "width": 100, "height": 20}}]}


def test_browser_snapshot_redacts_password_and_preserves_reference():
    result = browser_snapshot()
    assert validate_result("browser", result) == result


@pytest.mark.parametrize("change", ["password", "bounds", "reference", "identity", "oversize", "node"])
def test_host_rejects_malformed_browser_snapshot(change):
    result = copy.deepcopy(browser_snapshot())
    if change == "password":
        result["nodes"][0]["value"] = "secret"
    elif change == "bounds":
        result["nodes"][0]["bounds"]["x"] = float("inf")
    elif change == "reference":
        result["nodes"][0]["ref"] = "b" * 32 + ":0"
    elif change == "identity":
        result["target_id"] = "http://host"
    elif change == "oversize":
        result["nodes"][0]["name"] = "x" * 257
    else:
        result["nodes"][0] = None
    with pytest.raises(SandboxError) as error:
        validate_result("browser", result)
    assert error.value.code == "PROTOCOL_ERROR"

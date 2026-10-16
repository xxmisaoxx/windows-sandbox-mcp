import base64
import json

import pytest

from winsandbox_mcp.errors import SandboxError
from winsandbox_mcp.protocol import (
    MAX_BINARY,
    MAX_WIRE,
    binary,
    bounded_number,
    decode_response,
    encode,
    validate_result,
)

SID, RID = "a" * 32, "b" * 32


def response(**changes):
    value = {"v": 1, "session": SID, "id": RID, "ok": True, "result": {"ready": True}, "error": None}
    value.update(changes)
    return json.dumps(value).encode()


def test_valid_envelope_and_bom():
    assert decode_response(b"\xef\xbb\xbf" + response(), SID, RID) == {"ready": True}


@pytest.mark.parametrize("data", [b"null", b"[]", b"{", b"\xff", b'{"v":1,"v":1}', b'{"x":NaN}',
                                  b"[" * 2000 + b"]" * 2000,
                                  response(v=True), response(v=2), response(session="c" * 32),
                                  response(id="c" * 32), response(ok=1), response(result=[]),
                                  response(error={}), response(extra="callback"),
                                  response(ok=False, result=None, error={"code": 1, "message": "x"}),
                                  response(ok=False, result=None, error={"code": "x", "message": "y", "extra": 1}),
                                  response(ok=False, result=None, error={"code": "x", "message": "z" * 4097}),
                                  b" " * (MAX_WIRE + 1)], ids=lambda data: "case-" + __import__("hashlib").sha256(data).hexdigest()[:12])
def test_reject_hostile_envelopes(data):
    with pytest.raises(SandboxError, match="."):
        decode_response(data, SID, RID)


def test_guest_error_is_data():
    with pytest.raises(SandboxError) as error:
        decode_response(response(ok=False, result=None, error={"code": "FAILED", "message": "hello"}), SID, RID)
    assert error.value.code == "GUEST_ERROR"
    assert error.value.details == {"guest_code": "FAILED"}


@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf"), -1, 301])
def test_timeout_validation(value):
    with pytest.raises(SandboxError):
        bounded_number(value, .1, 300, "timeout")


def test_payload_caps():
    with pytest.raises(SandboxError):
        encode({"x": "x" * MAX_WIRE})
    with pytest.raises(SandboxError):
        binary(base64.b64encode(b"x" * (MAX_BINARY + 1)).decode())


@pytest.mark.parametrize("data", [None, 1, "!", "eA=", "é"])
def test_invalid_binary(data):
    with pytest.raises(SandboxError):
        binary(data)


def test_binary_roundtrip():
    data = bytes(range(256)) * 100
    assert binary(base64.b64encode(data).decode()) == data


@pytest.mark.parametrize("operation,result", [("ping", {"ready": 1}), ("exec", {"stdout": []}),
    ("exec", {"stdout": "", "stderr": "", "timed_out": False, "exit_code": None}),
    ("windows", {"windows": {}}), ("inspect", {"nodes": [], "hwnd": "123"}),
    ("launch", {"pid": True}), ("click", {"applied": 1}), ("upload", {"size": -1})])
def test_semantic_result_schema(operation, result):
    with pytest.raises(SandboxError):
        validate_result(operation, result)

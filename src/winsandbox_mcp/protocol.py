"""Data-only wire protocol. Never deserialize objects or evaluate guest strings."""

import base64
import json
import math
import re

from .errors import SandboxError

VERSION = 1
MAX_BINARY = 4 * 1024 * 1024
MAX_WIRE = 6 * 1024 * 1024
ID = re.compile(r"^[0-9a-f]{32}$")
OPERATIONS = frozenset({"ping", "exec", "upload", "download", "screenshot", "windows", "inspect",
                        "click", "text", "keys", "launch", "shutdown", "browser"})


def bounded_number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SandboxError("INVALID_ARGUMENT", f"{name} must be a finite number")
    if not low <= value <= high:
        raise SandboxError("INVALID_ARGUMENT", f"{name} must be between {low} and {high}")
    return value


def encode(value):
    data = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_WIRE:
        raise SandboxError("PAYLOAD_TOO_LARGE", "JSON exceeds bridge limit", limit=MAX_WIRE)
    return data


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def decode_response(data: bytes, session: str, request: str):
    if len(data) > MAX_WIRE:
        raise SandboxError("PROTOCOL_ERROR", "Response exceeds bridge limit")
    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SandboxError("PROTOCOL_ERROR", "Invalid guest JSON") from exc
    if not isinstance(value, dict) or set(value) != {"v", "session", "id", "ok", "result", "error"}:
        raise SandboxError("PROTOCOL_ERROR", "Invalid response envelope")
    if type(value["v"]) is not int or value["v"] != VERSION or value["session"] != session or value["id"] != request:
        raise SandboxError("PROTOCOL_ERROR", "Response identity/version mismatch")
    if type(value["ok"]) is not bool:
        raise SandboxError("PROTOCOL_ERROR", "Response status must be boolean")
    if value["ok"]:
        if not isinstance(value["result"], dict) or value["error"] is not None:
            raise SandboxError("PROTOCOL_ERROR", "Invalid success response")
        return value["result"]
    err = value["error"]
    if value["result"] is not None or not isinstance(err, dict) or set(err) != {"code", "message"}:
        raise SandboxError("PROTOCOL_ERROR", "Invalid guest error")
    if not all(isinstance(err[k], str) and len(err[k]) <= 4096 for k in err):
        raise SandboxError("PROTOCOL_ERROR", "Invalid guest error fields")
    raise SandboxError("GUEST_ERROR", err["message"], guest_code=err["code"])


def binary(data: str) -> bytes:
    if not isinstance(data, str) or len(data) > 4 * ((MAX_BINARY + 2) // 3):
        raise SandboxError("PAYLOAD_TOO_LARGE", "Binary payload exceeds limit", limit=MAX_BINARY)
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError as exc:
        raise SandboxError("PROTOCOL_ERROR", "Invalid base64 payload") from exc
    if len(raw) > MAX_BINARY:
        raise SandboxError("PAYLOAD_TOO_LARGE", "Binary payload exceeds limit", limit=MAX_BINARY)
    return raw


def validate_result(operation, result):
    """Bound semantic fields before exposing them to a client as successful results."""
    def require(condition):
        if not condition:
            raise SandboxError("PROTOCOL_ERROR", f"Invalid {operation} result schema")

    if operation == "ping":
        require(result.get("ready") is True)
    elif operation == "exec":
        require(all(isinstance(result.get(k), str) and len(result[k]) <= 65536 for k in ("stdout", "stderr")))
        require(type(result.get("timed_out")) is bool)
        code = result.get("exit_code")
        require(code is None if result["timed_out"] else type(code) is int)
    elif operation == "windows":
        windows = result.get("windows")
        require(isinstance(windows, list) and len(windows) <= 300)
        for window in windows:
            require(isinstance(window, dict) and type(window.get("hwnd")) is int and
                    type(window.get("pid")) is int and isinstance(window.get("title"), str) and
                    len(window["title"]) <= 1024)
    elif operation == "inspect":
        nodes = result.get("nodes")
        require(isinstance(nodes, list) and len(nodes) <= 1000 and type(result.get("hwnd")) is int)
        for node in nodes:
            require(isinstance(node, dict) and isinstance(node.get("type"), str))
            require(node.get("value") is None or isinstance(node["value"], str) and len(node["value"]) <= 16384)
            bounds = node.get("bounds")
            require(isinstance(bounds, dict))
            for field in ("x", "y", "width", "height"):
                value = bounds.get(field)
                require(type(value) in (int, float) and math.isfinite(value))
    elif operation in ("screenshot", "download"):
        binary(result.get("data"))
    elif operation == "upload":
        require(type(result.get("size")) is int and 0 <= result["size"] <= MAX_BINARY)
    elif operation == "launch":
        require(type(result.get("pid")) is int and result["pid"] > 0)
    elif operation in ("click", "text", "keys"):
        require(result.get("applied") is True)
    elif operation == "browser":
        require(result.get("backend") == "cdp" and isinstance(result.get("target_id"), str) and
                re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", result["target_id"]) is not None)
        if "nodes" in result:
            require(isinstance(result["nodes"], list) and len(result["nodes"]) <= 500)
            token = result.get("snapshot_id")
            require(isinstance(token, str) and ID.fullmatch(token) is not None and
                    result.get("coordinate_space") == "viewport-css")
            for index, node in enumerate(result["nodes"]):
                require(isinstance(node, dict) and node.get("ref") == f"{token}:{index}")
                require(all(isinstance(node.get(k), str) and len(node[k]) <= 256
                            for k in ("tag", "role", "name")))
                require(type(node.get("password")) is bool and type(node.get("enabled")) is bool)
                require(node.get("value") is None if node["password"] else
                        isinstance(node.get("value"), str) and len(node["value"]) <= 256)
                bounds = node.get("bounds")
                require(isinstance(bounds, dict))
                require(all(type(bounds.get(k)) in (int, float) and math.isfinite(bounds[k])
                            for k in ("x", "y", "width", "height")))
        else:
            require(result.get("applied") is True)
    return result

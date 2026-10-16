"""Exercise real guest through official MCP stdio client, including binary resources."""
import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run():
    project = Path(__file__).resolve().parents[1]
    report = {"passed": False}
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "winsandbox_mcp", "--state-root",
                                                                   str(project / ".runtime/mcp-live")])
    try:
        async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as client:
            await client.initialize()
            tools = await client.list_tools()
            assert len(tools.tools) == 18 and any(t.name == "sandbox_browser" for t in tools.tools)

            async def call(name, arguments=None):
                result = await client.call_tool(name, arguments or {})
                assert not result.isError, result.structuredContent
                return result

            try:
                await call("sandbox_start")
                print("MCP start succeeded", flush=True)
                result = await call("sandbox_exec", {"command": "[Console]::Out.Write('MCP-GUEST-OK');exit 0"})
                assert result.structuredContent["result"]["stdout"] == "MCP-GUEST-OK"
                await call("sandbox_launch", {"executable": "notepad.exe", "arguments": []})
                notepad = None
                for _ in range(40):
                    windows = (await call("sandbox_windows")).structuredContent["result"]["windows"]
                    notepad = next((w for w in windows if "notepad" in w["title"].lower()), None)
                    if notepad:
                        break
                    await asyncio.sleep(.25)
                assert notepad, "Guest Notepad window did not appear"
                tree = (await call("sandbox_inspect", {"hwnd": notepad["hwnd"], "backend": "uia3",
                                                       "view": "raw", "timeout": 8})).structuredContent["result"]
                assert tree["backend"] == "uia3" and any(n["type"] == "ControlType.Edit" for n in tree["nodes"])
                disabled = await client.call_tool("sandbox_browser", {"port": 9222})
                assert disabled.isError and disabled.structuredContent["error"]["details"]["guest_code"] == "CDP_NOT_ENABLED"
                html = (project / "examples/browser-demo.html").read_bytes()
                await call("sandbox_upload", {"path": r"C:\work\form.html", "data_base64": base64.b64encode(html).decode()})
                edge = (await call("sandbox_exec", {"command": "@('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe','C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe') | Where-Object {Test-Path -LiteralPath $_} | Select-Object -First 1"})).structuredContent["result"]["stdout"].strip()
                assert edge
                await call("sandbox_launch", {"executable": edge, "arguments": ["--user-data-dir=C:\\work\\mcp-profile",
                           "--no-first-run", "--start-maximized", "file:///C:/work/form.html"], "accessibility": True, "cdp_port": 9223})
                for _ in range(30):
                    candidate = await client.call_tool("sandbox_browser", {"port": 9223})
                    if not candidate.isError and candidate.structuredContent["result"]["nodes"]:
                        break
                    await asyncio.sleep(.5)
                assert not candidate.isError, candidate.structuredContent
                snapshot = candidate.structuredContent["result"]
                field = next(n for n in snapshot["nodes"] if n["tag"] == "input")
                await call("sandbox_browser", {"port": 9223, "action": "fill", "target_id": snapshot["target_id"],
                           "reference": field["ref"], "text": "MCP-DOM-OK"})
                after = (await call("sandbox_browser", {"port": 9223})).structuredContent["result"]
                assert any(n["value"] == "MCP-DOM-OK" for n in after["nodes"])
                button = next(n for n in after["nodes"] if n["tag"] == "button")
                await call("sandbox_browser", {"port": 9223, "action": "click", "target_id": after["target_id"],
                           "reference": button["ref"]})
                clicked = (await call("sandbox_browser", {"port": 9223})).structuredContent["result"]
                assert any(n["name"] == "Applied" for n in clicked["nodes"])
                listeners = (await call("sandbox_exec", {"command": "[Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object Port -eq 9223 | ForEach-Object {$_.Address.ToString()}"})).structuredContent["result"]["stdout"].splitlines()
                assert listeners and set(listeners) <= {"127.0.0.1", "::1"}, listeners
                data = b"synthetic MCP byte transfer\x00\xff"
                await call("sandbox_upload", {"path": r"C:\work\mcp-test.bin", "data_base64": base64.b64encode(data).decode()})
                download = (await call("sandbox_download", {"path": r"C:\work\mcp-test.bin"})).structuredContent["result"]
                result = await call("sandbox_artifact", {"artifact_id": download["id"]})
                assert base64.b64decode(result.structuredContent["result"]["data_base64"]) == data
                screenshot = (await call("sandbox_screenshot")).structuredContent["result"]
                image = await call("sandbox_artifact", {"artifact_id": screenshot["id"]})
                native = next(content for content in image.content if content.type == "image")
                png = base64.b64decode(native.data)
                assert png.startswith(b"\x89PNG\r\n\x1a\n")
                assert hashlib.sha256(png).hexdigest() == screenshot["sha256"]
                resource = await client.read_resource(screenshot["uri"])
                assert base64.b64decode(resource.contents[0].blob) == png
                report.update({"passed": True, "command": "MCP-GUEST-OK", "binary_roundtrip": True,
                               "native_png_image": True, "binary_resource": True, "screenshot": screenshot,
                               "tool_count": 18, "uia3_inspection": True, "cdp_requires_opt_in": True,
                               "cdp_fill_click_verified": True, "guest_debug_listeners": listeners})
            finally:
                await call("sandbox_stop")
    finally:
        (project / "evidence/mcp-live.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(run())

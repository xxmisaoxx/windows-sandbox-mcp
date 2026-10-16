import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_real_stdio_handshake_tools_errors_and_resources(tmp_path):
    parameters = StdioServerParameters(command=sys.executable,
                                      args=["-m", "winsandbox_mcp", "--state-root", str(tmp_path)])
    async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as client:
        await client.initialize()
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        assert len(names) == 18
        assert {"sandbox_exec", "sandbox_screenshot", "sandbox_inspect", "sandbox_collect_evidence"} <= names
        result = await client.call_tool("sandbox_doctor")
        assert not result.isError
        assert result.structuredContent["result"]["bridge"] == "offline-json-mailbox"
        result = await client.call_tool("sandbox_exec", {"command": "whoami"})
        assert result.isError
        assert result.structuredContent["error"]["code"] == "SESSION_NOT_READY"
        result = await client.call_tool("sandbox_artifact", {"artifact_id": "../../secret"})
        assert result.isError
        templates = await client.list_resource_templates()
        assert len(templates.resourceTemplates) == 1

"""MCP server tests.

Module-skips if the optional `mcp` package isn't installed. Tool-discovery and
the SDK-free `build_schema` tool run anywhere (validating MCP interaction on CI);
the `respond` tests hit the live model and self-skip via `require_model`.
"""

import asyncio
import json

import pytest

pytest.importorskip("mcp")

try:
    from fmx import mcp_server
except Exception:  # mcp_server pulls FastMCP; bail cleanly if anything's off
    pytest.skip("fmx.mcp_server unavailable", allow_module_level=True)

mcp = mcp_server.mcp


def _text(call_result) -> str:
    """Flatten FastMCP.call_tool output to text across SDK versions.

    Older FastMCP returns ``list[ContentBlock]``; newer returns
    ``(content, structured_content)``. Handle both.
    """
    content = call_result[0] if isinstance(call_result, tuple) else call_result
    return "".join(getattr(block, "text", "") for block in content)


# --- SDK-free: validate we can interact with the MCP server (runs on CI) ---


def test_server_exposes_expected_tools():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert {"respond", "respond_schema", "build_schema"} <= names


def test_build_schema_tool_roundtrips():
    # A real tools/call that doesn't touch the model — proves the MCP path works.
    result = asyncio.run(mcp.call_tool("build_schema", {"fields": ["name:str", "age:int"]}))
    payload = json.loads(_text(result))
    assert payload["properties"]["age"] == {"type": "integer"}
    assert payload["required"] == ["name", "age"]


# --- Live model: a create-then-edit code flow over the MCP `respond` tool ---

_CODER = "You are a terse Python expert. Return only code."


def _respond(prompt: str) -> str:
    return _text(
        asyncio.run(mcp.call_tool("respond", {"prompt": prompt, "instructions": _CODER}))
    )


@pytest.mark.require_model
def test_respond_tool_live():
    result = asyncio.run(mcp.call_tool("respond", {"prompt": "Reply with exactly the word: pong"}))
    assert "pong" in _text(result).lower()


@pytest.mark.require_model
def test_create_then_edit_code_flow():
    # 1) Create a function.
    created = _respond("Write a Python function add(a, b) that returns their sum.")
    assert "def add" in created  # substring tolerates the model's ``` fences

    # 2) Edit it: rename add -> total, feeding step 1's output straight back in.
    #    Rename is a transform the on-device model performs reliably (docstring
    #    insertion is not), and substring asserts survive the fence-wrapping.
    edited = _respond(f"Rename the function 'add' to 'total'. Return the code:\n\n{created}")
    assert "def total" in edited
    assert "def add" not in edited  # the edit actually replaced the name

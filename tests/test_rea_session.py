"""Exercise the real Node bridge with a stub MCP transport, not a real REA server."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for the stub-transport bridge regression")
BRIDGE = Path(__file__).resolve().parents[1] / "src/rea_backend/rea_android_session.mjs"
TOOLS = (
    "inspect_android_package", "search_android_classes", "inspect_android_class",
    "inspect_android_method", "trace_android_references",
)


@pytest.fixture
def stub_modules(tmp_path):
    modules = tmp_path / "node_modules"
    sdk = modules / "@modelcontextprotocol/client/dist"
    sdk.mkdir(parents=True)
    tools = json.dumps([{"name": name} for name in (*TOOLS, "../../../escaped_android")])
    (sdk / "index.mjs").write_text('''
export class Client {
  async connect() {}
  getServerVersion() { return { name: 'stub-rea-boundary', version: 'fixture-1' }; }
  async listTools() { return { tools: TOOLS }; }
  async callTool(request) {
    return { structuredContent: { received: request }, _meta: { fixture: true } };
  }
  async close() {}
}
'''.replace("TOOLS", tools))
    (sdk / "stdio.mjs").write_text('''
export class StdioClientTransport {
  constructor() { this.stderr = null; }
}
''')
    return modules


def invoke(tmp_path, stub_modules, requests):
    input_path = tmp_path / "requests.jsonl"
    input_path.write_text("\n".join(json.dumps(request) for request in requests) + "\n")
    output = tmp_path / "session"
    result = subprocess.run(
        ["node", str(BRIDGE), str(output), "--requests", str(input_path)],
        env={**os.environ, "REA_NODE_MODULES": str(stub_modules)},
        cwd=tmp_path, text=True, capture_output=True, timeout=15,
    )
    metadata = json.loads((output / "session-metadata.json").read_text())
    return result, output, metadata


def test_allowed_android_tools_preserve_requests_replies_and_session_metadata(tmp_path, stub_modules):
    requests = [{"name": name, "arguments": {"path": "/synthetic/input.apk", "fixture_index": index}}
                for index, name in enumerate(TOOLS, 1)]
    result, output, metadata = invoke(tmp_path, stub_modules, requests)
    assert result.returncode == 0, result.stderr
    assert metadata["server"] == {"name": "stub-rea-boundary", "version": "fixture-1"}
    assert metadata["connection_status"] == "closed"
    assert metadata["session_status"] == "requests-finished"
    assert len(metadata["requests"]) == len(requests)
    for index, (request, record) in enumerate(zip(requests, metadata["requests"]), 1):
        prefix = f"{index:03}-{request['name']}"
        assert record["name"] == request["name"]
        assert record["arguments"] == request["arguments"]
        assert record["status"] == "mcp_success"
        assert record["request_file"] == prefix + ".request.json"
        assert record["response_file"] == prefix + ".json"
        assert json.loads((output / record["request_file"]).read_text()) == request
        assert json.loads((output / record["response_file"]).read_text()) == {
            "structuredContent": {"received": request}, "_meta": {"fixture": True},
        }
        assert json.loads((output / (prefix + ".timing.json")).read_text())["seconds"] >= 0


def test_unapproved_tool_name_cannot_write_outside_output_or_be_dispatched(tmp_path, stub_modules):
    # The stub advertises this name, so the bridge must enforce its own whitelist.
    sentinel = tmp_path / "escaped_android.request.json"
    sentinel.write_bytes(b"original evidence")
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    request = {"name": "../../../escaped_android", "arguments": {"path": "/synthetic/input.apk"}}
    result, output, metadata = invoke(tmp_path, stub_modules, [request])
    assert result.returncode != 0
    assert metadata["session_status"] == "failed"
    assert metadata["connection_status"] == "closed"
    assert metadata["requests"] == []
    assert set(path.name for path in output.iterdir()) == {"session-metadata.json", "android-tools.json"}
    for relative, content in before.items():
        assert (tmp_path / relative).read_bytes() == content
    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")
             if path.is_file() and not path.is_relative_to(output)}
    assert after == set(before) | {Path("requests.jsonl")}


@pytest.mark.parametrize("arguments", [None, [], "invalid", 17])
def test_invalid_arguments_are_rejected_before_request_files_or_dispatch(tmp_path, stub_modules, arguments):
    result, output, metadata = invoke(tmp_path, stub_modules, [{"name": TOOLS[0], "arguments": arguments}])
    assert result.returncode != 0
    assert metadata["session_status"] == "failed"
    assert metadata["connection_status"] == "closed"
    assert metadata["requests"] == []
    assert not list(output.glob("*.request.json"))
    assert not list(output.glob("*.timing.json"))

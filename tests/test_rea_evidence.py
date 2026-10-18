"""Public REA response shapes, failure provenance and APK identity boundaries.

These are adapter fixtures, not assertions of real decompiler behavior or SRS
semantic completeness. The bridge test uses a clearly simulated MCP client.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from rea_backend.preparation import collect_rea, digest, write_json
from rea_backend.rea_evidence import APKIdentityError, normalize_response, observation_evidence_ids


APK_SHA = "a" * 64


def evidence(operation="inspect_android_method"):
    return {
        "evidence_id": "ev_" + "e" * 64,
        "subject": {"digest": {"sha256": APK_SHA}, "name": "fixture.apk",
                    "local_path": "/fixture.apk", "format": "apk", "architecture": None},
        "provider": {"id": "jadx", "name": "JADX", "version": "fixture-version"},
        "operation": operation, "parameters": {"class_name": "Example", "method_name": "test", "overload_index": 2},
        "predicate_type": "rea.analysis", "confidence": "observed", "authority": "shipped-artifact",
        "analysis_profile": None, "environment": None, "raw_result": {"provider_field": "retained"},
        "normalized_result": {"body_status": "not_available", "fell_back": True,
                              "representation": "smali", "source": {"text": "", "truncated": True},
                              "coverage": {"status": "partial", "omitted": 3}},
        "limitations": ["Only this selected overload was examined."],
        "relationship_coverage": None, "locations": [], "evidence_links": [],
    }


def typed_error(partial=None):
    result = {"code": "provider_timeout", "category": "timeout", "message": "Provider deadline reached",
              "retryable": True, "remediation": {"action": "Retry the selected observation"},
              "details": {"operation": "inspect_android_method", "captured_output": {"stderr": "bounded output", "truncated": True}}}
    if partial is not None:
        result["details"]["partial_observation"] = partial
    return result


def normalize(value):
    return normalize_response(value, APK_SHA, file="001.json", sha256="f" * 64)


@pytest.mark.parametrize("legacy", [False, True])
def test_old_and_new_success_preserve_all_metadata_and_body_limits(legacy):
    source = evidence()
    content = {"evidence": source, "result": source["normalized_result"], "evidence_id": source["evidence_id"]} if legacy else source
    record = normalize({"structuredContent": content})
    assert record["status"] == "success"
    assert record["evidence"] == source
    assert record["sha256"] == "f" * 64
    assert observation_evidence_ids(record) == {source["evidence_id"]}
    assert record["reported_availability"]["status"] == "limited"
    assert any(item["path"] == "evidence.normalized_result.source.truncated" and item["value"] is True
               for item in record["reported_availability"]["signals"])


@pytest.mark.parametrize("result,limitations,expected", [
    ({}, [], "unknown"),
    ({"source": {"text": "some retained text", "truncated": False}}, [], "unknown"),
    ({"coverage": {"status": "complete"}, "fell_back": False}, [], "unknown"),
    ({"body_status": "future-provider-value"}, [], "unknown"),
    ({"source": {"truncated": "true"}}, [], "unknown"),
    ({"body_status": "available", "source": {"truncated": False}}, [], "available"),
    ({"body_status": "available", "fell_back": True}, [], "available"),
    ({"body_status": "not_available"}, [], "limited"),
    ({"body_status": "available", "source": {"truncated": True}}, [], "limited"),
    ({"body_status": "available", "coverage": {"status": "partial"}}, [], "limited"),
    ({"body_status": "available"}, ["Only one selected overload was inspected."], "limited"),
])
def test_availability_never_infers_complete_material_from_success_or_text(result, limitations, expected):
    source = evidence()
    source["normalized_result"], source["limitations"] = result, limitations
    record = normalize({"structuredContent": source})
    assert record["status"] == "success"
    assert record["evidence"] == source
    assert record["reported_availability"]["status"] == expected
    assert observation_evidence_ids(record) == {source["evidence_id"]}


def test_legacy_duplicate_result_disagreement_is_not_silently_normalized():
    source = evidence()
    result = normalize({"structuredContent": {"evidence": source, "result": {}, "evidence_id": source["evidence_id"]}})
    assert result["status"] == "malformed"
    assert "disagrees" in result["normalization_issues"][0]


@pytest.mark.parametrize("text_only", [False, True])
def test_typed_error_wire_surfaces_retain_error_and_embedded_partial(text_only):
    source = evidence()
    error = typed_error(source)
    payload = {"content": [{"type": "text", "text": json.dumps({"error": error})}]} if text_only else {"structuredContent": {"error": error}}
    record = normalize({"isError": True, **payload})
    assert record["status"] == "typed_error"
    assert record["error"] == error
    assert record["partial"]["evidence"] == source
    assert record["partial"]["apk_binding"] == "matched"
    assert observation_evidence_ids(record) == {source["evidence_id"]}
    assert record["reported_availability"]["status"] == "limited"


@pytest.mark.parametrize("partial_kind", ["evidence", "provider"])
def test_partial_apk_binding_rejects_foreign_facts(partial_kind):
    partial = evidence() if partial_kind == "evidence" else {
        "provider_id": "jadx", "operation": "inspect_android_method",
        "target": {"path": "/fixture.apk", "sha256": APK_SHA, "format": "apk"},
        "provider_facts": {"engine_version": "fixture"}, "calls": [{"operation": "load", "input": {}, "response": {}}],
    }
    good = normalize({"isError": True, "content": [{"type": "text", "text": json.dumps({"error": typed_error(partial)})}]})
    assert good["partial"]["apk_binding"] == "matched"
    if partial_kind == "evidence":
        partial["subject"]["digest"]["sha256"] = "b" * 64
    else:
        partial["target"]["sha256"] = "b" * 64
    with pytest.raises(APKIdentityError, match="different APK"):
        normalize({"isError": True, "structuredContent": {"error": typed_error(partial)}})


def test_partial_reference_is_preserved_without_assuming_subject_or_success():
    reference = {"kind": "retained-evidence", "evidence_id": "ev_not-fetched"}
    record = normalize({"isError": True, "structuredContent": {"error": typed_error(reference)}})
    assert record["status"] == "typed_error"
    assert record["partial"] == {"kind": "retained-reference", "apk_binding": "unverified", "reference": reference}
    assert observation_evidence_ids(record) == set()


def test_missing_partial_subject_stays_an_unusable_partial_with_original_error():
    partial = evidence()
    partial["subject"] = None
    error = typed_error(partial)
    record = normalize({"isError": True, "structuredContent": {"error": error}})
    assert record["status"] == "typed_error"
    assert record["partial"]["kind"] == "malformed"
    assert record["error"] == error
    assert observation_evidence_ids(record) == set()


@pytest.mark.parametrize("reply", [
    {"structuredContent": {"unknown": {"observations": []}}},
    {"isError": True, "content": [{"type": "text", "text": "Provider timed out"}]},
    {"isError": True, "structuredContent": {"error": {"message": "incomplete typed error"}}},
    {"isError": "false", "structuredContent": evidence()},
    ["unknown", "envelope"],
])
def test_unknown_or_malformed_envelopes_are_visible_and_never_success(reply):
    record = normalize(reply)
    assert record["status"] == "malformed"
    assert record["file"] == "001.json"
    assert record["normalization_issues"]
    assert observation_evidence_ids(record) == set()


@pytest.mark.parametrize("payload", [
    {"error": "MCP request timed out"},
    {"transport_error": {"name": "Error", "message": "MCP disconnected", "code": -32000}},
])
def test_bridge_transport_errors_are_not_typed_provider_errors(payload):
    record = normalize({"isError": True, **payload})
    assert record["status"] == "transport_error"
    assert record["error"] == payload.get("transport_error", payload.get("error"))


def test_error_text_json_is_bounded_and_not_extracted_from_prose(monkeypatch):
    import rea_backend.rea_evidence as boundary
    encoded = json.dumps({"error": typed_error()})
    monkeypatch.setattr(boundary, "MAX_ERROR_TEXT_BYTES", len(encoded) - 1)
    record = normalize({"isError": True, "content": [{"type": "text", "text": encoded}]})
    assert record["status"] == "malformed"
    assert "byte bound" in record["normalization_issues"][0]
    monkeypatch.setattr(boundary, "MAX_ERROR_TEXT_BYTES", 10000)
    for text in ("Server says: " + encoded, '[' * 65 + '0' + ']' * 65,
                 '{"error": 1, "error": 2}'):
        assert normalize({"isError": True, "content": [{"type": "text", "text": text}]})["status"] == "malformed"


def test_collect_keeps_error_only_unknown_and_bad_json_replies_but_skips_sidecars(tmp_path):
    source = tmp_path / "source"
    write_json(source / "001.json", {"isError": True, "content": [{"type": "text", "text": json.dumps({"error": typed_error()})}]})
    write_json(source / "001.request.json", {"name": "inspect_android_method", "arguments": {"path": "/fixture.apk"}})
    write_json(source / "001.timing.json", {"seconds": 1})
    write_json(source / "android-tools.json", [{"name": "inspect_android_method"}])
    write_json(source / "session-metadata.json", {"server": {"name": "rea", "version": "6.5.0"}})
    write_json(source / "002-unknown.json", {"unknown": "kept"})
    (source / "003-bad.json").write_bytes(b'{"broken":')
    records = collect_rea(source, APK_SHA, tmp_path / "copy")
    assert [r["status"] for r in records] == ["typed_error", "malformed", "malformed"]
    assert records[0]["request_reference"]["sha256"] == digest(source / "001.request.json")
    for record in records:
        original = source / record["file"]
        copied = tmp_path / "copy" / record["file"]
        assert copied.read_bytes() == original.read_bytes()
        assert record["sha256"] == digest(copied)


def selected_request():
    return {"name": "inspect_android_method", "arguments": {
        "path": "/relocated/fixture.apk", "class_name": "Example", "method_name": "test", "overload_index": 2,
    }}


def test_collect_compares_all_provided_selectors_and_keeps_exact_request_and_reply(tmp_path):
    source = tmp_path / "session/nested"
    source.mkdir(parents=True)
    reply = evidence()
    reply["parameters"]["path"] = "/original/fixture.apk"
    request_bytes = (json.dumps(selected_request(), indent=3) + "  \n").encode()
    reply_bytes = (json.dumps({"structuredContent": reply}, indent=5) + "\n").encode()
    (source / "001.request.json").write_bytes(request_bytes)
    (source / "001.json").write_bytes(reply_bytes)
    records = collect_rea(source.parent, APK_SHA, tmp_path / "copied")
    record = records[0]
    binding = record["request_binding"]
    assert binding["status"] == "matched"
    assert binding["compared_fields"] == ["operation", "arguments.class_name", "arguments.method_name", "arguments.overload_index"]
    assert binding["unchecked_fields"] == binding["mismatched_fields"] == []
    assert binding["ignored_fields"] == ["arguments.path"]
    assert record["request_reference"] == {"file": "nested/001.request.json", "sha256": digest(source / "001.request.json")}
    assert (tmp_path / "copied/nested/001.request.json").read_bytes() == request_bytes
    assert (tmp_path / "copied/nested/001.json").read_bytes() == reply_bytes
    assert observation_evidence_ids(record) == {reply["evidence_id"]}


@pytest.mark.parametrize("selector,value,field", [
    ("name", "inspect_android_class", "operation"),
    ("overload_index", 1, "arguments.overload_index"),
    ("overload_index", True, "arguments.overload_index"),
    ("overload_index", 2.0, "arguments.overload_index"),
    ("options", {"nested": [True]}, "arguments.options"),
])
def test_request_mismatch_is_retained_without_becoming_a_plan_evidence_id(tmp_path, selector, value, field):
    source = tmp_path / "session"
    request, reply = selected_request(), evidence()
    reply["parameters"]["overload_index"] = 1 if value is True else 2
    if selector == "name":
        request["name"] = value
    else:
        request["arguments"][selector] = value
    if selector == "options":
        reply["parameters"][selector] = {"nested": [1]}
    write_json(source / "001.json", {"structuredContent": reply})
    write_json(source / "001.request.json", request)
    record = collect_rea(source, APK_SHA, tmp_path / "copy")[0]
    assert record["status"] == "success"
    assert record["evidence"] == reply
    assert record["request_binding"]["status"] == "mismatch"
    assert record["request_binding"]["mismatched_fields"] == [field]
    assert record["request_reference"]["sha256"] == digest(source / "001.request.json")
    assert (tmp_path / "copy/001.json").read_bytes() == (source / "001.json").read_bytes()
    assert observation_evidence_ids(record) == set()


@pytest.mark.parametrize("request_bytes", [
    None,
    b'{"name":"inspect_android_method","arguments":',
    b'{"name":"wrong","name":"inspect_android_method","arguments":{}}',
    b'{"name":"inspect_android_method","arguments":{"overload_index":1,"overload_index":2}}',
    b'{"name":"inspect_android_method","arguments":{"overload_index":NaN}}',
    b'\xff',
    b'{"name":"inspect_android_method","arguments":[]}',
])
def test_missing_or_malformed_request_stays_unverified_with_raw_reference(tmp_path, request_bytes):
    source = tmp_path / "session"
    reply = evidence()
    write_json(source / "001.json", {"structuredContent": reply})
    if request_bytes is not None:
        (source / "001.request.json").write_bytes(request_bytes)
    record = collect_rea(source, APK_SHA, tmp_path / "copy")[0]
    assert record["status"] == "success"
    assert record["request_binding"]["status"] == "unverified"
    assert record["request_binding"]["unchecked_fields"] == ["operation", "arguments"]
    assert record["request_binding"]["diagnostics"]
    assert observation_evidence_ids(record) == {reply["evidence_id"]}
    if request_bytes is None:
        assert "request_reference" not in record
    else:
        assert record["request_reference"]["sha256"] == digest(source / "001.request.json")
        assert (tmp_path / "copy/001.request.json").read_bytes() == request_bytes


def test_unechoed_request_selector_prevents_matched_binding_without_guessing_defaults(tmp_path):
    source = tmp_path / "session"
    request, reply = selected_request(), evidence()
    del reply["parameters"]["overload_index"]
    write_json(source / "001.json", {"structuredContent": reply})
    write_json(source / "001.request.json", request)
    record = collect_rea(source, APK_SHA, tmp_path / "copy")[0]
    assert record["request_binding"]["status"] == "unverified"
    assert record["request_binding"]["compared_fields"] == ["operation", "arguments.class_name", "arguments.method_name"]
    assert record["request_binding"]["unchecked_fields"] == ["arguments.overload_index"]
    assert observation_evidence_ids(record) == {reply["evidence_id"]}


@pytest.mark.parametrize("mismatch", [False, True])
def test_request_binding_applies_to_matched_apk_partial_evidence(tmp_path, mismatch):
    source = tmp_path / "session"
    request, reply = selected_request(), evidence()
    if mismatch:
        request["arguments"]["overload_index"] = 9
    write_json(source / "001.json", {"isError": True, "structuredContent": {"error": typed_error(reply)}})
    write_json(source / "001.request.json", request)
    record = collect_rea(source, APK_SHA, tmp_path / "copy")[0]
    assert record["status"] == "typed_error"
    assert record["partial"]["evidence"] == reply
    assert record["request_binding"]["status"] == ("mismatch" if mismatch else "matched")
    assert observation_evidence_ids(record) == (set() if mismatch else {reply["evidence_id"]})


def test_historical_plan_evidence_ids_still_resolve():
    assert observation_evidence_ids({"evidence_id": "ev_old", "operation": "inspect_android_package", "result": {}}) == {"ev_old"}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for the bridge boundary test")
def test_bridge_records_actual_handshake_requests_and_status_without_environment(tmp_path):
    modules = tmp_path / "node_modules"
    sdk = modules / "@modelcontextprotocol/client/dist"
    sdk.mkdir(parents=True)
    (sdk / "index.mjs").write_text('''
export class Client {
  async connect() {}
  getServerVersion() { return { name: 'fixture-rea', version: '6.5.0-fixture' }; }
  async listTools() { return { tools: [{ name: 'inspect_android_package' }] }; }
  async callTool(request) {
    if (request.arguments.mode === 'transport') throw Object.assign(new Error('fixture disconnect'), { code: -32000 });
    if (request.arguments.mode === 'typed') return { isError: true, content: [{type:'text',text:'{"error":{"fixture":true}}'}] };
    return { structuredContent: { fixture: 'complete-original-reply' }, _meta: { retained: true } };
  }
  async close() {}
}
''')
    (sdk / "stdio.mjs").write_text("export class StdioClientTransport { constructor() { this.stderr = null; } }\n")
    requests = tmp_path / "requests.jsonl"
    selected = [{"name": "inspect_android_package", "arguments": {"mode": mode, "path": "/fixture.apk"}}
                for mode in ("success", "typed", "transport")]
    requests.write_text("\n".join(json.dumps(r) for r in selected) + "\nexit\n")
    output = tmp_path / "session"
    bridge = Path(__file__).resolve().parents[1] / "src/rea_backend/rea_android_session.mjs"
    environment = {**os.environ, "REA_NODE_MODULES": str(modules), "DO_NOT_RECORD_FIXTURE_SECRET": "fixture-secret-marker"}
    subprocess.run(["node", str(bridge), str(output), "--requests", str(requests)], env=environment, check=True, capture_output=True, text=True, timeout=30)
    metadata = json.loads((output / "session-metadata.json").read_text())
    assert metadata["server"] == {"name": "fixture-rea", "version": "6.5.0-fixture"}
    assert [r["status"] for r in metadata["requests"]] == ["mcp_success", "mcp_error", "transport_error"]
    assert [r["arguments"] for r in metadata["requests"]] == [r["arguments"] for r in selected]
    assert metadata["connection_status"] == "closed"
    assert metadata["session_status"] == "requests-finished"
    first = json.loads((output / "001-inspect_android_package.json").read_text())
    assert first == {"structuredContent": {"fixture": "complete-original-reply"}, "_meta": {"retained": True}}
    assert "fixture-secret-marker" not in "".join(p.read_text() for p in output.glob("*.json"))

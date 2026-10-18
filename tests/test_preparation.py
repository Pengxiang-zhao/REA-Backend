"""APK preparation retains input identity and raw evidence without claiming completeness."""
import json
import zipfile

import pytest

from rea_backend.preparation import (
    collect_rea, decoded_inventory, digest, prepare, verify_decoded_reuse,
    _verify_run, write_json,
)


def write_decode_record(record, apk, decoded):
    """Use the identity and inventory shapes emitted by prepare itself."""
    write_json(record / "decoded-manifest.json", decoded_inventory(decoded))
    write_json(record / "input.json", {
        "schema_version": 1,
        "apk": {"path": str(apk), "sha256": digest(apk), "bytes": apk.stat().st_size},
        "decoded_root": str(decoded),
        "decode_origin": {"mode": "fresh-apktool", "executable": "synthetic-fixture"},
        "decoded_manifest_sha256": digest(record / "decoded-manifest.json"),
    })


def cache_fixture(tmp_path):
    apk = tmp_path / "input.apk"
    apk.write_bytes(b"test-identity-only-not-an-executable-apk")
    decoded = tmp_path / "decoded"
    decoded.mkdir()
    (decoded / "AndroidManifest.xml").write_text("<manifest/>\n")
    (decoded / "Example.smali").write_text(".class public Lexample/Example;\n")
    record = tmp_path / "record"
    write_decode_record(record, apk, decoded)
    return apk, decoded, record


def test_cache_bound_to_apk_and_complete_file_set(tmp_path):
    apk, decoded, record = cache_fixture(tmp_path)
    assert verify_decoded_reuse(apk, decoded, record)
    (decoded / "Unexpected.smali").write_text(".class public Lextra;\n")
    with pytest.raises(ValueError, match="cache has changed"):
        verify_decoded_reuse(apk, decoded, record)
    (decoded / "Unexpected.smali").unlink()
    apk.write_bytes(b"different-apk")
    with pytest.raises(ValueError, match="different APK"):
        verify_decoded_reuse(apk, decoded, record)


def test_cache_inventory_is_bound_to_preparation_identity(tmp_path):
    apk, decoded, record = cache_fixture(tmp_path)
    (decoded / "Unexpected.smali").write_text(".class public Lextra;\n")
    # Updating the manifest alone cannot silently approve a changed decode tree.
    write_json(record / "decoded-manifest.json", decoded_inventory(decoded))
    with pytest.raises(ValueError, match="inventory has changed"):
        verify_decoded_reuse(apk, decoded, record)


def test_rea_cache_rejects_unrelated_binary(tmp_path):
    session = tmp_path / "session"
    write_json(session / "001-package.json", {"structuredContent": {
        "result": {"package_name": "example"}, "evidence_id": "ev_test",
        "evidence": {"subject": {"digest": {"sha256": "a" * 64}}, "operation": "inspect_android_package"}}})
    with pytest.raises(ValueError, match="different APK"):
        collect_rea(session, "b" * 64, tmp_path / "copy")
    assert not (tmp_path / "copy").exists()


def test_rea_transport_failure_is_preserved(tmp_path):
    session = tmp_path / "session"
    write_json(session / "001-package.json", {"structuredContent": {
        "result": {}, "evidence_id": "ev_test",
        "evidence": {"subject": {"digest": {"sha256": "a" * 64}}, "operation": "inspect_android_package"}}})
    write_json(session / "002-method.json", {"isError": True, "error": "MCP request timed out"})
    records = collect_rea(session, "a" * 64, tmp_path / "copy")
    assert len(records) == 2
    assert records[1]["error"] == "MCP request timed out"


def prepared_inputs(tmp_path):
    apk, decoded, rebuild = cache_fixture(tmp_path)
    # This fixture tests orchestration and archive profiling only. It is not an
    # installable APK and establishes no real provider or application behavior.
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", "<manifest package='fixture'/>")
        archive.writestr("classes.dex", b"fixture-directory-entry")
    write_decode_record(rebuild, apk, decoded)
    session = tmp_path / "session"
    write_json(session / "001-package.json", {"structuredContent": {
        "result": {"package_name": "fixture"}, "evidence_id": "ev_fixture",
        "evidence": {"subject": {"digest": {"sha256": digest(apk)}}, "operation": "inspect_android_package"}}})
    return apk, decoded, rebuild, session


def test_prepare_defaults_to_srs_analysis_handoff_not_behavior_completion(tmp_path):
    from rea_backend.srs import load_config
    apk, decoded, rebuild, session = prepared_inputs(tmp_path)
    output = tmp_path / "prepared"
    result = prepare(apk, output, decoded=decoded, rebuild_record=rebuild, rea_evidence=session)
    assert result["complete"] is True
    assert result["complete_scope"] == "material-preparation"
    assert result["analysis_complete"] is False
    assert result["workflow"] == "srs"
    assert result["endpoint_declarations"] == 0
    assert result["rea_successes"] == 1
    assert result["rea_availability_counts"] == {"limited": 0, "unknown": 1, "available": 0}
    assert result["rea_request_binding_counts"] == {"matched": 0, "mismatch": 0, "unverified": 1}
    handoff = (output / "srs-handoff.md").read_text()
    assert "srs-explore" in handoff
    assert "srs-analysis-check" in handoff and "--require-settled" in handoff
    assert "srs-init" in handoff and "--analysis" in handoff
    assert not (output / "inference-task.md").exists()
    assert "plan.json" not in handoff
    config = json.loads((output / "srs-inputs.json").read_text())
    assert config["route"] == "apk"
    assert config["inputs"][0]["sha256"] == digest(apk)
    assert all(item["limitations"] for item in config["inputs"])
    load_config(output / "srs-inputs.json")
    observations = json.loads((output / "rea-observations.json").read_text())
    raw_inventory = json.loads((output / "rea-raw-inventory.json").read_text())
    assert observations[0]["sha256"] == raw_inventory["001-package.json"]["sha256"]
    _verify_run(output)
    (output / "rea/001-package.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="raw REA evidence was changed"):
        _verify_run(output)


def test_prepare_output_can_be_used_as_its_own_decode_cache_record(tmp_path):
    apk, decoded, seed_record, session = prepared_inputs(tmp_path)
    first = tmp_path / "first-preparation"
    prepare(apk, first, decoded=decoded, rebuild_record=seed_record, rea_evidence=session)
    # The second run consumes actual prepare output, with no conversion or
    # records created by another project or a removed rebuild command.
    second = tmp_path / "second-preparation"
    result = prepare(apk, second, decoded=decoded, rebuild_record=first, rea_evidence=first / "rea")
    assert result["complete"] is True
    identity = json.loads((second / "input.json").read_text())
    assert identity["apk"]["sha256"] == digest(apk)
    assert identity["decode_origin"] == {"mode": "verified-cache", "record": str(first.resolve())}
    assert (second / "decoded-manifest.json").read_bytes() == (first / "decoded-manifest.json").read_bytes()
    assert (second / "rea/001-package.json").read_bytes() == (first / "rea/001-package.json").read_bytes()
    assert verify_decoded_reuse(apk, decoded, second) == decoded_inventory(decoded)
    _verify_run(second)


@pytest.mark.parametrize("has_declaration", [False, True])
def test_endpoint_harvest_diagnostics_prompt_investigation_without_blocking(tmp_path, has_declaration):
    apk, decoded, rebuild, session = prepared_inputs(tmp_path)
    if has_declaration:
        (decoded / "smali").mkdir()
        (decoded / "smali/Example.smali").write_text(""".class public interface abstract Lexample/Example;
.super Ljava/lang/Object;
.method public abstract list()Ljava/lang/String;
    .annotation runtime Lretrofit2/http/GET;
        value = "items"
    .end annotation
.end method
""")
        write_decode_record(rebuild, apk, decoded)
    output = tmp_path / "prepared"
    result = prepare(apk, output, decoded=decoded, rebuild_record=rebuild,
                     rea_evidence=session)
    # A legitimate local-only App must remain usable as an analysis input. Zero
    # declarations are a search result, not an inferred missing feature or gap.
    assert result["stage"] == "prepared" and result["complete"] is True
    assert result["complete_scope"] == "material-preparation"
    assert result["analysis_complete"] is False
    assert result["endpoint_declarations"] == int(has_declaration)
    reports = [result, json.loads((output / "status.json").read_text()),
               json.loads((output / "evidence-pack.json").read_text())]
    diagnostics = result["preparation_diagnostics"]
    assert all(report["preparation_diagnostics"] == diagnostics for report in reports)
    handoff = (output / result["handoff"]).read_text()
    if has_declaration:
        assert diagnostics == []
        assert "no_endpoint_declarations" not in handoff
    else:
        assert len(diagnostics) == 1
        notice = diagnostics[0]
        assert notice["code"] == "no_endpoint_declarations" and notice["blocking"] is False
        assert notice["source"] == "contract.json"
        assert "does not establish that the App has no backend" in notice["message"]
        assert all(isinstance(action, str) and action for action in notice["next_actions"])
        assert any("REA catalog" in action and "smali" in action for action in notice["next_actions"])
        assert any("local-only" in action and "unresolved" in action for action in notice["next_actions"])
        assert notice["code"] in handoff and notice["message"] in handoff
        assert all(action in handoff for action in notice["next_actions"])
    assert not (output / "analysis.json").exists()
    _verify_run(output)


def test_prepare_reports_error_only_material_and_does_not_require_app_features(tmp_path):
    apk, decoded, rebuild, session = prepared_inputs(tmp_path)
    write_json(session / "001-package.json", {"isError": True, "error": "MCP fixture disconnected"})
    write_json(session / "002-unknown.json", {"unknown_envelope": True})
    result = prepare(apk, tmp_path / "prepared", decoded=decoded, rebuild_record=rebuild, rea_evidence=session)
    assert result["complete"] is True and result["analysis_complete"] is False
    assert result["stage"] == "prepared_with_issues"
    assert result["rea_collection_status"] == "failed"
    assert result["rea_status_counts"] == {"success": 0, "typed_error": 0, "transport_error": 1, "malformed": 1}
    config = json.loads((tmp_path / "prepared/srs-inputs.json").read_text())
    rea = next(item for item in config["inputs"] if item["id"] == "rea")
    assert rea["complete"] is False
    assert "failed" in rea["limitations"][0]


def test_prepare_successful_but_limited_evidence_surfaces_separate_counts_and_issues(tmp_path):
    from rea_backend.srs import load_config
    apk, decoded, rebuild, session = prepared_inputs(tmp_path)
    raw_path = session / "001-package.json"
    reply = json.loads(raw_path.read_text())
    reply["structuredContent"]["result"] = {
        "body_status": "not_available", "source": {"text": "", "truncated": True},
        "coverage": {"status": "partial"},
    }
    write_json(raw_path, reply)
    write_json(session / "001-package.request.json", {
        "name": "inspect_android_package", "arguments": {"path": "/old/location.apk"},
    })
    output = tmp_path / "prepared"
    result = prepare(apk, output, decoded=decoded, rebuild_record=rebuild, rea_evidence=session)
    assert result["stage"] == "prepared_with_issues"
    assert result["complete"] is True and result["analysis_complete"] is False
    assert result["rea_successes"] == 1 and result["rea_errors"] == 0
    assert result["rea_collection_status"] == "completed_requested_calls"
    availability = {"limited": 1, "unknown": 0, "available": 0}
    bindings = {"matched": 1, "mismatch": 0, "unverified": 0}
    for report in [result, json.loads((output / "status.json").read_text()), json.loads((output / "evidence-pack.json").read_text())]:
        assert report["rea_availability_counts"] == availability
        assert report["rea_request_binding_counts"] == bindings
    handoff = (output / result["handoff"]).read_text()
    assert json.dumps(availability, sort_keys=True) in handoff
    assert json.dumps(bindings, sort_keys=True) in handoff
    assert "neither semantic completeness nor actual" in handoff
    assert "not cryptographic invocation pairing" in handoff
    config = load_config(output / "srs-inputs.json")
    rea = next(item for item in config["inputs"] if item["id"] == "rea")
    assert rea["complete"] is False
    assert any(json.dumps(availability, sort_keys=True) in note for note in rea["limitations"])
    assert any(json.dumps(bindings, sort_keys=True) in note for note in rea["limitations"])
    assert (output / "rea/001-package.json").read_bytes() == raw_path.read_bytes()
    _verify_run(output)


def test_prepare_request_mismatch_keeps_available_reply_and_records_binding_failure(tmp_path):
    apk, decoded, rebuild, session = prepared_inputs(tmp_path)
    raw_path = session / "001-package.json"
    reply = json.loads(raw_path.read_text())
    reply["structuredContent"]["result"] = {"body_status": "available"}
    write_json(raw_path, reply)
    write_json(session / "001-package.request.json", {
        "name": "inspect_android_method", "arguments": {"path": "/old/location.apk"},
    })
    output = tmp_path / "prepared"
    result = prepare(apk, output, decoded=decoded, rebuild_record=rebuild, rea_evidence=session)
    assert result["stage"] == "prepared_with_issues"
    assert result["rea_successes"] == 1 and result["rea_errors"] == 0
    assert result["rea_availability_counts"] == {"limited": 0, "unknown": 0, "available": 1}
    assert result["rea_request_binding_counts"] == {"matched": 0, "mismatch": 1, "unverified": 0}
    observations = json.loads((output / "rea-observations.json").read_text())
    _verify_run(output)
    assert observations[0]["request_binding"]["status"] == "mismatch"
    assert observations[0]["evidence"]["normalized_result"] == {"body_status": "available"}
    assert (output / "rea/001-package.request.json").read_bytes() == (session / "001-package.request.json").read_bytes()

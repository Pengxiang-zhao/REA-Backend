"""Prepare version-bound APK evidence for agent-authored backend requirements."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import time
from typing import Any

from .rea_evidence import bind_request, is_sidecar, read_response

ANDROID_TOOLS = {
    "inspect_android_package", "search_android_classes", "inspect_android_class",
    "inspect_android_method", "trace_android_references",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def fresh_directory(path: Path) -> Path:
    path = path.resolve()
    if path.exists():
        raise ValueError(f"Output already exists; choose a new run directory: {path}")
    path.mkdir(parents=True)
    return path


def decoded_inventory(root: Path) -> dict:
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] in {"build", "dist"} or not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError(f"Decoded input must not contain symlinks: {relative}")
        result[relative.as_posix()] = {"sha256": digest(path), "bytes": path.stat().st_size}
    if "AndroidManifest.xml" not in result or not any(p.endswith(".smali") for p in result):
        raise ValueError("Decoded input requires a manifest and smali code")
    return result


def verify_decoded_reuse(apk: Path, decoded: Path, rebuild_record: Path) -> dict:
    """Reuse only a complete tree bound to the same APK and prior inventory."""
    identity = read_json(rebuild_record / "input.json")
    if identity["apk"]["sha256"] != digest(apk):
        raise ValueError("Decoded cache belongs to a different APK")
    inventory_path = rebuild_record / "decoded-manifest.json"
    if digest(inventory_path) != identity["decoded_manifest_sha256"]:
        raise ValueError("Decoded cache inventory has changed")
    before = read_json(inventory_path)
    if not isinstance(before, dict):
        raise ValueError("Decoded cache inventory must be an object")
    actual = decoded_inventory(decoded)
    if before != actual:
        changed = sorted(k for k in before.keys() | actual.keys() if before.get(k) != actual.get(k))
        raise ValueError(f"Decoded cache has changed: {changed[:5]}")
    return actual


def run_logged(argv: list[str], output: Path, name: str, *, timeout: int) -> None:
    from .build_validation import _cleanup

    started = time.monotonic()
    process = None
    record = {"argv": argv, "returncode": None, "status": "starting"}
    try:
        with (output / f"{name}.stdout.log").open("w") as stdout, (output / f"{name}.stderr.log").open("w") as stderr:
            process = subprocess.Popen(argv, cwd=Path.cwd(), stdout=stdout, stderr=stderr,
                                       start_new_session=(os.name == "posix"))
            record["status"] = "running"
            process.wait(timeout=timeout)
            record["status"] = "completed" if process.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        record["status"] = "timed_out"
        raise RuntimeError(f"{name} timed out; inspect {output}") from None
    except OSError as error:
        record["status"] = "failed_to_start"
        record["error"] = str(error)
        raise
    finally:
        if process is not None:
            record["cleanup"] = _cleanup(process)
            record["returncode"] = process.returncode
        record["seconds"] = round(time.monotonic() - started, 3)
        write_json(output / f"{name}.command.json", record)
    if record["returncode"]:
        raise RuntimeError(f"{name} failed; see {output / (name + '.stderr.log')}")


def collect_rea(source: Path, apk_sha256: str, destination: Path) -> list[dict]:
    """Keep complete raw replies and normalize every non-sidecar JSON record."""
    records = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"REA input must not contain symlinks: {path.relative_to(source)}")
    for path in sorted(source.rglob("*.json")):
        if not path.is_file() or is_sidecar(path):
            continue
        record = bind_request(read_response(path, apk_sha256), path.with_suffix(".request.json"))
        record["file"] = path.relative_to(source).as_posix()
        if "request_reference" in record:
            record["request_reference"]["file"] = path.with_suffix(".request.json").relative_to(source).as_posix()
        records.append(record)
    if source.resolve() != destination.resolve():
        shutil.copytree(source, destination)
    for record in records:
        for reference in [record, *([record["request_reference"]] if "request_reference" in record else [])]:
            if digest(destination / reference["file"]) != reference["sha256"]:
                raise ValueError(f"REA file changed during collection: {reference['file']}")
    return records


def _preparation_diagnostics(contract: dict) -> list[dict]:
    """Describe extraction limits without deciding whether networking exists."""
    if contract["endpoints"]:
        return []
    return [{
        "code": "no_endpoint_declarations", "blocking": False,
        "source": "contract.json",
        "message": ("The declaration harvester found no supported endpoint declarations. "
                    "This does not establish that the App has no backend or that decoding failed; "
                    "the harvester only recognizes supported Retrofit declaration patterns."),
        "next_actions": [
            "Inspect permitted UI/background entrypoints, resources and dependencies for actual network consumers.",
            "Use the current REA catalog for targeted class, method and reference queries; inspect decoded smali when declarations or method projections are insufficient.",
            "Retain the zero result and any failed or fallback observations. Record evidence-supported local-only behavior or unresolved questions in the analysis; do not invent endpoints or gaps.",
        ],
    }]


def _preparation_summary(diagnostics: list[dict]) -> str:
    if not diagnostics:
        return ""
    lines = ["\n## Nonblocking preparation diagnostics\n"]
    for item in diagnostics:
        lines.append(f"`{item['code']}`: {item['message']}\n")
        lines.extend(f"- {action}" for action in item["next_actions"])
        lines.append("")
    return "\n".join(lines)


def prepare(apk: Path, output: Path, *, decoded: Path | None = None,
            rebuild_record: Path | None = None, rea_evidence: Path | None = None,
            rea_requests: Path | None = None, apktool: str | None = None) -> dict:
    from .harvest import harvest

    apk = apk.resolve(strict=True)
    apk_hash = digest(apk)
    output = fresh_directory(output)
    write_json(output / "status.json", {"stage": "preparing", "complete": False})
    try:
        if decoded is not None:
            if rebuild_record is None:
                raise ValueError("Reusing decoded input requires --rebuild-record")
            decoded = decoded.resolve(strict=True)
            inventory = verify_decoded_reuse(apk, decoded, rebuild_record.resolve(strict=True))
            decode_origin = {"mode": "verified-cache", "record": str(rebuild_record.resolve())}
        else:
            if rebuild_record:
                raise ValueError("--rebuild-record only applies with --decoded")
            decoded = output / "decoded"
            executable = apktool or os.environ.get("REA_APKTOOL_COMMAND") or shutil.which("apktool") or "apktool"
            run_logged([executable, "decode", "--all-src", "--jobs", "4", "--frame-path",
                        str(output / "framework"), "--output", str(decoded), str(apk)],
                       output, "apktool-decode", timeout=900)
            inventory = decoded_inventory(decoded)
            decode_origin = {"mode": "fresh-apktool", "executable": executable}
        write_json(output / "decoded-manifest.json", inventory)
        if rea_evidence is None:
            requests = [{"name": "inspect_android_package", "arguments": {"path": str(apk)}}]
            if rea_requests:
                requests += [json.loads(line) for line in rea_requests.read_text().splitlines()
                             if line.strip() and line.strip() != "exit"]
            for request in requests:
                if request["name"] not in ANDROID_TOOLS:
                    raise ValueError("Only read-only Android REA analysis requests are accepted")
                request["arguments"]["path"] = str(apk)
            request_path = output / "rea-requests.jsonl"
            request_path.write_text("".join(json.dumps(r) + "\n" for r in requests) + "exit\n")
            rea_evidence = output / "rea"
            run_logged(["node", str(Path(__file__).with_name("rea_android_session.mjs")), str(rea_evidence),
                        "--requests", str(request_path)], output, "rea", timeout=180 * len(requests) + 60)
        rea_records = collect_rea(rea_evidence.resolve(strict=True), apk_hash, output / "rea")
        rea_counts = {status: sum(record["status"] == status for record in rea_records)
                      for status in ("success", "typed_error", "transport_error", "malformed")}
        availability_counts = {status: sum(record["reported_availability"]["status"] == status for record in rea_records)
                               for status in ("limited", "unknown", "available")}
        binding_counts = {status: sum(record["request_binding"]["status"] == status for record in rea_records)
                          for status in ("matched", "mismatch", "unverified")}
        rea_errors = sum(rea_counts[status] for status in ("typed_error", "transport_error", "malformed"))
        rea_status = ("partial_failure" if rea_counts["success"] else "failed") if rea_errors else (
            "completed_requested_calls" if rea_counts["success"] else "no_observations")
        raw_inventory = {p.relative_to(output / "rea").as_posix(): {"sha256": digest(p), "bytes": p.stat().st_size}
                         for p in sorted((output / "rea").rglob("*")) if p.is_file()}
        write_json(output / "rea-raw-inventory.json", raw_inventory)
        contract = harvest(decoded, apk_hash)
        preparation_diagnostics = _preparation_diagnostics(contract)
        from .capabilities import profile_apk
        capabilities = profile_apk(apk, contract)
        if capabilities["status"] != "profiled":
            raise ValueError(f"APK profiling failed: {capabilities.get('error')}")
        write_json(output / "contract.json", contract)
        write_json(output / "capabilities.json", capabilities)
        write_json(output / "rea-observations.json", rea_records)
        identity = {
            "schema_version": 1, "apk": {"path": str(apk), "sha256": apk_hash, "bytes": apk.stat().st_size},
            "decoded_root": str(decoded), "decode_origin": decode_origin,
            "decoded_manifest_sha256": digest(output / "decoded-manifest.json"),
            "contract_sha256": digest(output / "contract.json"),
            "rea_observations_sha256": digest(output / "rea-observations.json"),
            "rea_raw_inventory_sha256": digest(output / "rea-raw-inventory.json"),
            "extractor_sha256": digest(Path(__file__).with_name("harvest.py")),
            "capabilities_sha256": digest(output / "capabilities.json"),
        }
        write_json(output / "input.json", identity)
        write_json(output / "evidence-pack.json", {
            "schema_version": 2, "apk_sha256": apk_hash, "contract": contract,
            "rea_observations": rea_records,
            "rea_collection_status": rea_status, "rea_status_counts": rea_counts,
            "rea_availability_counts": availability_counts, "rea_request_binding_counts": binding_counts,
            "rea_raw_inventory": "rea-raw-inventory.json",
            "capabilities": capabilities,
            "preparation_diagnostics": preparation_diagnostics,
            "workflow": "srs", "analysis_complete": False,
            "semantic_stage": "agent-authored SRS analysis required; evidence preparation does not establish app-wide coverage",
            "unknowns": ["Server-side constraints, authorization semantics and errors are not determined by DTOs",
                         "Network interceptors and HTML bootstrapping may lie outside Retrofit declarations",
                         "Client compatibility and reference-backend fidelity need separate execution evidence"],
        })
        handoff = "srs-handoff.md"
        write_json(output / "srs-inputs.json", _srs_inputs(apk, apk_hash, decoded, output, rea_status, rea_counts,
                                                       availability_counts, binding_counts))
        handoff_text = _srs_handoff(output, rea_status, rea_counts, availability_counts, binding_counts)
        (output / handoff).write_text(handoff_text + _preparation_summary(preparation_diagnostics), encoding="utf-8")
        has_issues = rea_errors or not rea_records or availability_counts["limited"] or binding_counts["mismatch"]
        result = {"stage": "prepared_with_issues" if has_issues else "prepared",
                  "complete": True, "complete_scope": "material-preparation", "analysis_complete": False,
                  "workflow": "srs", "handoff": handoff, "apk_sha256": apk_hash,
                  "endpoint_declarations": len(contract["endpoints"]), "models": len(contract["models"]),
                  "rea_successes": rea_counts["success"], "rea_errors": rea_errors,
                  "rea_collection_status": rea_status, "rea_status_counts": rea_counts,
                  "rea_availability_counts": availability_counts, "rea_request_binding_counts": binding_counts,
                  "preparation_diagnostics": preparation_diagnostics,
                  "note": "Only material preparation is complete. App-wide analysis and SRS authoring remain unfinished.",
                  "output": str(output)}
        write_json(output / "status.json", result)
        return result
    except Exception as error:
        write_json(output / "status.json", {"stage": "failed", "complete": False, "error": str(error)})
        raise


def _srs_inputs(apk: Path, apk_hash: str, decoded: Path, output: Path,
                rea_status: str, rea_counts: dict, availability_counts: dict, binding_counts: dict) -> dict:
    version = f"sha256:{apk_hash}"
    return {
        "format": "rea-backend.srs-config/v1",
        "app": {"id": f"apk-{apk_hash[:12]}", "name": apk.name, "version": version,
                "platform": "Android", "variant": "selected-apk"},
        "route": "apk",
        "context": {"mode": "client_only", "notes": "Identity comes from the selected APK file. The filename and hash do not claim a product version or build variant."},
        "inputs": [
            {"id": "apk", "kind": "client_apk", "path": str(apk), "version": version,
             "sha256": apk_hash, "access": "generation", "complete": True,
             "limitations": ["The complete selected file is retained; this does not establish behavioral coverage."], "exclude": []},
            {"id": "decoded", "kind": "decoded_apk", "path": str(decoded), "version": version,
             "access": "generation", "complete": False,
             "limitations": ["The decoded tree is inventoried; decoding does not establish complete source recovery or semantic analysis."], "exclude": []},
            {"id": "rea", "kind": "rea_evidence", "path": str(output / "rea"), "version": version,
             "access": "generation", "complete": False,
             "limitations": [f"REA collection status: {rea_status}; response counts: {json.dumps(rea_counts, sort_keys=True)}.",
                             f"Provider-reported availability counts: {json.dumps(availability_counts, sort_keys=True)}; request binding counts: {json.dumps(binding_counts, sort_keys=True)}.",
                             "Availability describes explicit provider surfaces only; available does not establish semantic completeness or actual reading. Binding compares echoed metadata, not cryptographic invocation pairing.",
                             "Only requested observations are retained. Review errors, partial observations, coverage, body availability and fallback before making claims."], "exclude": []},
        ],
        "environment": {"goals": ["Describe an independent backend from this APK and explicitly declared target-environment needs."],
                        "constraints": ["Discover capabilities from evidence; do not assume a fixed feature list or contact original business services."]},
    }


def _rea_summary(rea_status: str, rea_counts: dict, availability_counts: dict, binding_counts: dict) -> str:
    return f"""REA collection status is `{rea_status}`; response counts are
`{json.dumps(rea_counts, sort_keys=True)}`. Provider-reported availability counts
are `{json.dumps(availability_counts, sort_keys=True)}`; request binding counts
are `{json.dumps(binding_counts, sort_keys=True)}`.
A successful envelope can still report unavailable or truncated bodies or
limited coverage. Availability is only an explicit provider surface: unknown
stays unknown, and available proves neither semantic completeness nor actual
reading. Inspect each observation and its limitations. Request binding compares
echoed operation and provided arguments, excluding relocated APK paths; it is
not cryptographic invocation pairing. Unchecked selectors remain unverified;
explicit mismatches cannot support evidence claims for this request.
"""


def _srs_handoff(output: Path, rea_status: str, rea_counts: dict, availability_counts: dict, binding_counts: dict) -> str:
    config = shlex.quote(str(output / "srs-inputs.json"))
    analysis = shlex.quote(str(output.parent / (output.name + "-analysis")))
    bundle = shlex.quote(str(output.parent / (output.name + "-srs")))
    return f"""# APK evidence handoff for SRS analysis

Material preparation is complete. App-wide analysis, semantic interpretation,
SRS authoring and independent review are not complete.
{_rea_summary(rea_status, rea_counts, availability_counts, binding_counts)}

Export the bundled workflow with `rea-backend init-workspace --out workspace`.
Use workspace/skills/rea-backend/SKILL.md and its linked discovery, format,
and requirements references. Review srs-inputs.json:
its app identity uses the selected filename and verified APK hash, and its
environment text is a starting declaration to align with the requested scope.
No capabilities or backend semantics have been inferred by this preparation.

Start the analysis ledger before freezing an SRS bundle:

```sh
rea-backend srs-explore --config {config} --out {analysis}
```

Discover the whole App from the allowed materials. Use the ledger to track
questions, boundaries and missing evidence, then collect focused package,
class, method or reference observations where they resolve those questions.
Keep additional sessions in new directories and explicitly include their input
provenance. Work item update formats and settlement rules are owned by
the exported docs/srs-format.md; submit complete items with srs-analysis-update --config,
--analysis, --updates and --expected-revision.

```sh
rea-backend srs-analysis-check --config {config} --analysis {analysis} --require-settled
rea-backend srs-init --config {config} --analysis {analysis} --out {bundle}
```

Author the human-readable SRS and evidence index, retain unknown server behavior,
and perform independent review using the SRS workflow. Deterministic checks do
not certify behavioral completeness or equivalence to an original server.

input.json binds the APK, decoded inventory, contract candidates and normalized
REA observations. rea-raw-inventory.json hashes the complete original replies,
requests and session metadata in rea/. rea-observations.json is the sole adapter
for old and new REA envelopes; raw files remain the authority. Neither a retained
Evidence reference without a matching subject nor an error proves an observation.
The analysis has no authorization to read upstream app/server source or contact
public business services. Existing context is not erased by these instructions.
"""


def _verify_run(run: Path) -> tuple[dict, dict, dict]:
    identity = read_json(run / "input.json")
    for filename, key in (("contract.json", "contract_sha256"),
                          ("decoded-manifest.json", "decoded_manifest_sha256"),
                          ("rea-observations.json", "rea_observations_sha256")):
        if digest(run / filename) != identity[key]:
            raise ValueError(f"Prepared artifact was changed: {filename}")
    if "capabilities_sha256" in identity and digest(run / "capabilities.json") != identity["capabilities_sha256"]:
        raise ValueError("Prepared artifact was changed: capabilities.json")
    if "rea_raw_inventory_sha256" in identity:
        if digest(run / "rea-raw-inventory.json") != identity["rea_raw_inventory_sha256"]:
            raise ValueError("Prepared artifact was changed: rea-raw-inventory.json")
        for relative, record in read_json(run / "rea-raw-inventory.json").items():
            path = (run / "rea" / relative).resolve(strict=True)
            if not path.is_relative_to((run / "rea").resolve()) or digest(path) != record["sha256"]:
                raise ValueError(f"Prepared raw REA evidence was changed: {relative}")
    return identity, read_json(run / "contract.json"), read_json(run / "decoded-manifest.json")

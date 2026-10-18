"""Normalize retained REA replies once, without interpreting target semantics.

The original reply remains the authority, addressed by ``file`` and ``sha256``.
This adapter accepts the 6.1 Evidence projection and the complete Evidence used
by 6.5. It checks APK binding, not REA's semantic Evidence-ID algorithm or the
truth of a provider's observations. Unknown envelopes are explicit diagnostics.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

# Only error text needs a second JSON parse. Bound its aggregate input, block
# count and nesting rather than trying to recover JSON fragments from prose.
MAX_ERROR_TEXT_BYTES = 1024 * 1024
MAX_ERROR_TEXT_BLOCKS = 32
MAX_ERROR_JSON_DEPTH = 64
SIDECAR_NAMES = {"android-tools.json", "session-metadata.json"}


class APKIdentityError(ValueError):
    """An observation explicitly names a different APK."""


class EvidenceFormatError(ValueError):
    """The reply cannot safely be used as an Evidence observation."""


def is_sidecar(path: Path) -> bool:
    return path.name in SIDECAR_NAMES or path.name.endswith((".request.json", ".timing.json"))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceFormatError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise EvidenceFormatError(f"Non-JSON numeric constant: {value}")


def _json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _bounded_error_json(text: str) -> Any:
    # Inspect nesting without interpreting quoted brackets, before json.loads
    # allocates recursively. A lexical failure is still handled by the parser.
    depth, quoted, escaped = 0, False, False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_ERROR_JSON_DEPTH:
                raise EvidenceFormatError("Error text JSON exceeds nesting bound")
        elif character in "]}":
            depth -= 1
    return _json(text)


def _binding(sha256: Any, expected: str, context: str) -> None:
    if not isinstance(sha256, str) or len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise EvidenceFormatError(f"{context} has no usable APK SHA-256 identity")
    if sha256 != expected:
        raise APKIdentityError(f"REA evidence belongs to a different APK ({context})")


def _evidence(value: Any, expected: str) -> tuple[dict, str]:
    if not isinstance(value, dict):
        raise EvidenceFormatError("Evidence must be an object")
    if "evidence" in value:
        evidence = value["evidence"]
        if not isinstance(evidence, dict) or "result" not in value:
            raise EvidenceFormatError("Incomplete legacy Evidence envelope")
        evidence = deepcopy(evidence)
        if "normalized_result" in evidence and evidence["normalized_result"] != value["result"]:
            raise EvidenceFormatError("Legacy result disagrees with embedded Evidence")
        if "evidence_id" in evidence and evidence["evidence_id"] != value.get("evidence_id"):
            raise EvidenceFormatError("Legacy Evidence identifiers disagree")
        evidence["normalized_result"] = value["result"]
        evidence["evidence_id"] = value.get("evidence_id")
        envelope = "legacy-evidence"
    else:
        evidence, envelope = deepcopy(value), "rea-evidence"
    subject = evidence.get("subject")
    digest = subject.get("digest") if isinstance(subject, dict) else None
    _binding(digest.get("sha256") if isinstance(digest, dict) else None, expected, "Evidence.subject")
    if isinstance(subject, dict) and subject.get("format", "apk") != "apk":
        raise EvidenceFormatError("Evidence subject is not an APK")
    if not isinstance(evidence.get("evidence_id"), str) or not evidence["evidence_id"]:
        raise EvidenceFormatError("Evidence identifier is missing")
    if not isinstance(evidence.get("operation"), str) or not evidence["operation"]:
        raise EvidenceFormatError("Evidence operation is missing")
    if "normalized_result" not in evidence:
        raise EvidenceFormatError("Evidence normalized_result is missing")
    return evidence, envelope


def _typed_error(value: Any) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        raise EvidenceFormatError("No typed REA error object")
    error = value["error"]
    if any(not isinstance(error.get(key), str) or not error[key] for key in ("code", "category", "message")):
        raise EvidenceFormatError("Typed REA error lacks code, category or message")
    remediation = error.get("remediation")
    if type(error.get("retryable")) is not bool or not isinstance(remediation, dict) or not isinstance(remediation.get("action"), str) or not remediation["action"]:
        raise EvidenceFormatError("Typed REA error lacks retryable or remediation")
    if "details" in error and not isinstance(error["details"], dict):
        raise EvidenceFormatError("Typed REA error details must be an object")
    return deepcopy(error)


def _text_error(value: dict) -> dict:
    content = value.get("content")
    if not isinstance(content, list) or len(content) > MAX_ERROR_TEXT_BLOCKS:
        raise EvidenceFormatError("Error content is missing or exceeds block bound")
    texts = [item.get("text") for item in content if isinstance(item, dict) and item.get("type") == "text"]
    if not texts or any(not isinstance(item, str) for item in texts):
        raise EvidenceFormatError("Error content has no JSON text")
    # Check code units first to avoid allocating an unbounded UTF-8 encoding.
    if sum(len(item) for item in texts) > MAX_ERROR_TEXT_BYTES or sum(len(item.encode("utf-8")) for item in texts) > MAX_ERROR_TEXT_BYTES:
        raise EvidenceFormatError("Error text exceeds JSON byte bound; see raw reply")
    parsed = [_typed_error(_bounded_error_json(item)) for item in texts]
    if any(item != parsed[0] for item in parsed[1:]):
        raise EvidenceFormatError("Multiple conflicting error text envelopes")
    return parsed[0]


def _partial(value: Any, expected: str) -> dict:
    if isinstance(value, dict) and value.get("kind") == "retained-evidence":
        return {"kind": "retained-reference", "apk_binding": "unverified", "reference": deepcopy(value)}
    if isinstance(value, dict) and ("normalized_result" in value or "evidence" in value):
        evidence, _ = _evidence(value, expected)
        return {"kind": "evidence", "apk_binding": "matched", "evidence": evidence}
    if isinstance(value, dict) and "target" in value:
        target = value["target"]
        _binding(target.get("sha256") if isinstance(target, dict) else None, expected, "partial_observation.target")
        if target.get("format", "apk") != "apk":
            raise EvidenceFormatError("Partial observation target is not an APK")
        return {"kind": "provider-observation", "apk_binding": "matched", "observation": deepcopy(value)}
    # Even an unfamiliar partial shape cannot smuggle a known foreign subject
    # through the unknown branch. Matching identity alone still proves no facts.
    if isinstance(value, dict) and "subject" in value:
        subject = value["subject"]
        digest = subject.get("digest") if isinstance(subject, dict) else None
        _binding(digest.get("sha256") if isinstance(digest, dict) else None, expected, "partial_observation.subject")
        return {"kind": "unknown", "apk_binding": "matched", "observation": deepcopy(value)}
    return {"kind": "unknown", "apk_binding": "unverified", "observation": deepcopy(value)}


def _normalize_response(value: Any, apk_sha256: str, *, file: str, sha256: str) -> dict:
    """Return one tagged record; only an explicit foreign APK raises.

    Malformed and unrecognized replies remain hash-addressed records. A retained
    Evidence reference alone does not prove APK ownership and is never promoted
    into an observation. Provider fields and operation payloads remain intact.
    """
    record = {"schema_version": 1, "file": file, "sha256": sha256}
    try:
        if not isinstance(value, dict):
            raise EvidenceFormatError("REA reply must be a JSON object")
        if "isError" in value and type(value["isError"]) is not bool:
            raise EvidenceFormatError("MCP isError must be a boolean")
        if value.get("isError"):
            # New bridge errors are explicitly tagged. The old bridge's sole
            # string error field is retained for compatibility, without parsing
            # or guessing a provider failure from the string's contents.
            transport = value.get("transport_error")
            if isinstance(transport, dict) and isinstance(transport.get("message"), str):
                return {**record, "status": "transport_error", "format": "bridge-transport-error", "error": deepcopy(transport)}
            if isinstance(value.get("error"), str) and "structuredContent" not in value and "content" not in value:
                return {**record, "status": "transport_error", "format": "legacy-bridge-error", "error": value["error"]}
            error = _typed_error(value["structuredContent"]) if "structuredContent" in value else _text_error(value)
            record.update(status="typed_error", format="rea-error", error=error)
            details = error.get("details", {})
            if "partial_observation" in details:
                try:
                    record["partial"] = _partial(details["partial_observation"], apk_sha256)
                except EvidenceFormatError as issue:
                    record["partial"] = {"kind": "malformed", "apk_binding": "unverified"}
                    record["normalization_issues"] = [str(issue)]
            return record
        candidate = value.get("structuredContent", value)
        evidence, envelope = _evidence(candidate, apk_sha256)
        return {**record, "status": "success", "format": envelope, "evidence": evidence}
    except (EvidenceFormatError, json.JSONDecodeError, RecursionError, UnicodeError) as error:
        return {**record, "status": "malformed", "format": "unrecognized", "normalization_issues": [str(error)]}


def _reported_availability(record: dict) -> dict:
    """Summarize explicit provider surfaces, never inferred semantic coverage.

    Missing fields, empty limitations and ``truncated=false`` do not establish
    availability. Unknown values are retained as unknown signals. A fallback is
    a representation choice, not by itself proof of missing material.
    """
    signals = []

    def signal(path, value, assessment):
        signals.append({"path": path, "value": deepcopy(value), "assessment": assessment})

    def inspect(evidence, prefix):
        containers = [(evidence, prefix)]
        result = evidence.get("normalized_result")
        if isinstance(result, dict):
            containers.append((result, prefix + ".normalized_result"))
        for container, location in containers:
            if "limitations" in container:
                value = container["limitations"]
                nonempty = isinstance(value, (list, str)) and bool(value)
                signal(location + ".limitations", value, "limited" if nonempty else "unknown")
            if "body_status" in container:
                value = container["body_status"]
                assessment = "unknown"
                if isinstance(value, str):
                    if value in {"not_available", "unavailable", "partial", "incomplete", "truncated"}:
                        assessment = "limited"
                    elif value in {"available", "complete"}:
                        assessment = "available"
                signal(location + ".body_status", value, assessment)
            for key in ("source", "coverage", "relationship_coverage"):
                surface = container.get(key)
                if not isinstance(surface, dict):
                    continue
                if "truncated" in surface:
                    value = surface["truncated"]
                    signal(location + f".{key}.truncated", value, "limited" if value is True else "unknown")
                if key != "source" and "status" in surface:
                    value = surface["status"]
                    limited = isinstance(value, str) and value in {"partial", "incomplete", "truncated", "unavailable", "not_available"}
                    # Complete coverage is a provider claim about its own scope;
                    # it does not prove that a method body was made available.
                    signal(location + f".{key}.status", value, "limited" if limited else "unknown")
            if "truncated" in container:
                value = container["truncated"]
                signal(location + ".truncated", value, "limited" if value is True else "unknown")
            if "fell_back" in container:
                signal(location + ".fell_back", container["fell_back"], "unknown")

    evidence = record.get("evidence")
    if record.get("status") == "success" and isinstance(evidence, dict):
        inspect(evidence, "evidence")
    partial = record.get("partial")
    if isinstance(partial, dict) and partial.get("apk_binding") == "matched" and partial.get("kind") in {"evidence", "provider-observation"}:
        signal("partial.kind", partial["kind"], "limited")
        inspect(partial.get("evidence", partial.get("observation", {})), "partial." + ("evidence" if partial["kind"] == "evidence" else "observation"))
    details = record.get("error", {})
    details = details.get("details", {}) if isinstance(details, dict) else {}
    captured = details.get("captured_output", {}) if isinstance(details, dict) else {}
    if isinstance(captured, dict) and "truncated" in captured:
        value = captured["truncated"]
        signal("error.details.captured_output.truncated", value, "limited" if value is True else "unknown")
    assessments = {item["assessment"] for item in signals}
    status = "limited" if "limited" in assessments else "available" if "available" in assessments else "unknown"
    return {"status": status, "signals": signals}


def normalize_response(value: Any, apk_sha256: str, *, file: str, sha256: str) -> dict:
    """Preserve envelope success separately from provider-reported availability."""
    record = _normalize_response(value, apk_sha256, file=file, sha256=sha256)
    return {**record, "reported_availability": _reported_availability(record)}


def read_response(path: Path, apk_sha256: str) -> dict:
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        value = _json(raw.decode("utf-8"))
    except (EvidenceFormatError, json.JSONDecodeError, RecursionError, UnicodeError) as error:
        return {"schema_version": 1, "file": path.name, "sha256": sha256,
                "status": "malformed", "format": "invalid-json", "normalization_issues": [str(error)],
                "reported_availability": {"status": "unknown", "signals": []}}
    return normalize_response(value, apk_sha256, file=path.name, sha256=sha256)


def _same_json(left: Any, right: Any) -> bool:
    """Compare explicit JSON values without Python's bool/int coercion."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_json(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


def bind_request(record: dict, path: Path) -> dict:
    """Compare an optional sidecar to echoed metadata, not invocation identity.

    The original sidecar bytes are hashed before duplicate-key-safe parsing.
    Every provided argument except the relocatable APK ``path`` must be echoed
    and compared before a binding is called matched. Missing echo/defaults are
    unverified; explicitly conflicting fields are mismatches. Raw replies and
    request references remain usable for inspection in either case.
    """
    record = {**record}
    binding = {"status": "unverified", "compared_fields": [], "unchecked_fields": [],
               "mismatched_fields": [], "ignored_fields": [], "diagnostics": []}
    record["request_binding"] = binding
    if not path.is_file():
        binding["unchecked_fields"] = ["operation", "arguments"]
        binding["diagnostics"].append("Request sidecar is absent; no invocation pairing was verified.")
        return record
    raw = path.read_bytes()
    record["request_reference"] = {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest()}
    try:
        request = _json(raw.decode("utf-8"))
        if not isinstance(request, dict) or not isinstance(request.get("name"), str) or not request["name"] or not isinstance(request.get("arguments"), dict):
            raise EvidenceFormatError("Request sidecar requires a nonempty name and arguments object")
    except (EvidenceFormatError, json.JSONDecodeError, RecursionError, UnicodeError) as error:
        binding["unchecked_fields"] = ["operation", "arguments"]
        binding["diagnostics"].append(f"Request sidecar cannot be compared: {error}")
        return record
    arguments = request["arguments"]
    if "path" in arguments:
        binding["ignored_fields"].append("arguments.path")
    evidence = record.get("evidence") if record.get("status") == "success" else None
    partial = record.get("partial")
    if isinstance(partial, dict) and partial.get("apk_binding") == "matched" and partial.get("kind") == "evidence":
        evidence = partial.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    operation = evidence.get("operation")
    if isinstance(operation, str) and operation:
        binding["compared_fields"].append("operation")
        if operation != request["name"]:
            binding["mismatched_fields"].append("operation")
    else:
        binding["unchecked_fields"].append("operation")
    parameters = evidence.get("parameters")
    for key in sorted(arguments):
        if key == "path":
            continue
        field = "arguments." + key
        if isinstance(parameters, dict) and key in parameters:
            binding["compared_fields"].append(field)
            if not _same_json(arguments[key], parameters[key]):
                binding["mismatched_fields"].append(field)
        else:
            binding["unchecked_fields"].append(field)
    if binding["mismatched_fields"]:
        binding["status"] = "mismatch"
        binding["diagnostics"].append("Explicit request fields disagree with the retained Evidence metadata.")
    elif binding["unchecked_fields"]:
        binding["diagnostics"].append("Some provided fields have no comparable echo; defaults and omitted selectors were not inferred.")
    else:
        binding["status"] = "matched"
    return record


def observation_evidence_ids(record: dict) -> set[str]:
    """Read current records and already-frozen historical plan observations."""
    binding = record.get("request_binding")
    if isinstance(binding, dict) and binding.get("status") == "mismatch":
        return set()
    if "status" not in record:
        return {record["evidence_id"]} if isinstance(record.get("evidence_id"), str) else set()
    evidence = record.get("evidence") if record.get("status") == "success" else None
    partial = record.get("partial")
    if isinstance(partial, dict) and partial.get("apk_binding") == "matched" and partial.get("kind") == "evidence":
        evidence = partial.get("evidence")
    return {evidence["evidence_id"]} if isinstance(evidence, dict) and isinstance(evidence.get("evidence_id"), str) else set()

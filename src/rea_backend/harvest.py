"""Evidence-preserving Retrofit and DTO candidates from Apktool smali (stdlib).

This is a declaration harvester, not a server-semantics or JSON-schema inference
engine. It never executes decoded code or reads upstream application source.
"""

from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
import re

_HTTP = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "HTTP"}
_PARAMS = {
    "Body": "body", "Field": "form", "FieldMap": "form", "Query": "query",
    "QueryMap": "query", "QueryName": "query", "Path": "path", "Url": "url",
    "Header": "header", "HeaderMap": "header", "Part": "part", "PartMap": "part", "Tag": "tag",
}
_METHOD_MARKERS = {"FormUrlEncoded", "Multipart", "Headers", "Streaming", "SkipCallbackExecutor"}
_SIGNATURE = "Ldalvik/annotation/Signature;"
_BUILTIN_PREFIXES = (
    "Ljava/", "Ljavax/", "Landroid/", "Landroidx/", "Lkotlin/", "Lkotlinx/",
    "Lretrofit/", "Lretrofit2/", "Lokhttp/", "Lokhttp3/", "Lokio/",
    "Lio/reactivex/", "Lorg/reactivestreams/", "Lcom/google/common/",
)
_CLASS = re.compile(r"^[ \t]*\.class[ \t]+(.*?)(L[^\s;]+;)[ \t]*(?:#.*)?$", re.M)
_RETROFIT = re.compile(r"^Lretrofit2?/http/([^;]+);$")


def _source(path: str, sha: str, line: int) -> dict:
    return {"path": path, "sha256": sha, "line": line}


def _diagnostic(items: list, code: str, message: str, source: dict, **extra) -> None:
    items.append({"code": code, "message": message, "source": source, **extra})


def _strip_comment(line: str) -> str:
    quoted = escaped = False
    for i, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "#" and not quoted:
            return line[:i].strip()
    return line.strip()


def _split_values(value: str) -> list[str]:
    result, start, depth = [], 0, 0
    quoted = escaped = False
    for i, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted:
            if char in "{(":
                depth += 1
            elif char in "})":
                depth -= 1
            elif char == "," and depth == 0:
                result.append(value[start:i].strip())
                start = i + 1
    result.append(value[start:].strip())
    return [x for x in result if x]


def _literal(value: str, source: dict, diagnostics: list):
    value = value.strip()
    if value.startswith('"'):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            _diagnostic(diagnostics, "unknown_string_encoding", "String literal could not be decoded; raw value retained.", source, raw=value)
            return {"raw": value}
    if value.startswith("{") and value.endswith("}"):
        return [_literal(x, source, diagnostics) for x in _split_values(value[1:-1])]
    if value in {"true", "false", "null"}:
        return {"true": True, "false": False, "null": None}[value]
    if re.fullmatch(r"-?(?:0x[0-9a-fA-F]+|\d+)[tTsSlL]?", value):
        number = re.sub(r"[tTsSlL]$", "", value)
        return int(number, 16 if "0x" in number.lower() else 10)
    # Enums, class literals, floats, subannotations and unknown encodings remain
    # inspectable without pretending to know the annotation's value semantics.
    return {"raw": value}


def _annotation(lines: list[str], start: int, limit: int, path: str, sha: str, diagnostics: list) -> tuple[dict, int]:
    declaration = _strip_comment(lines[start]).split()
    descriptor = declaration[-1]
    source = _source(path, sha, start + 1)
    nested = 0
    end = start + 1
    terminated = False
    while end < limit:
        text = _strip_comment(lines[end])
        if ".subannotation " in text:
            nested += 1
        elif text == ".end subannotation":
            nested -= 1
        elif text == ".end annotation" and nested == 0:
            terminated = True
            break
        elif nested == 0 and (text.startswith((".method ", ".field ", ".class ")) or text in {".end method", ".end field", ".end param"}):
            break
        end += 1
    raw_end = end + 1 if terminated else end
    raw_lines = lines[start:raw_end]
    if not terminated:
        _diagnostic(diagnostics, "unterminated_annotation", "Annotation ended at a structural boundary; no following declaration was consumed.", source, raw="\n".join(raw_lines))
    values, raw_values = {}, {}
    key, parts, subdepth = None, [], 0

    def flush():
        if key is not None:
            raw = "\n".join(parts).strip()
            raw_values[key] = raw
            values[key] = _literal(raw, source, diagnostics)

    for line in lines[start + 1:end]:
        text = _strip_comment(line)
        match = re.match(r"^(\w+)\s*=\s*(.*)$", text) if subdepth == 0 else None
        if match:
            flush()
            key, parts = match.group(1), [match.group(2)]
        elif key is not None and text:
            parts.append(text)
        if ".subannotation " in text:
            subdepth += 1
        elif text == ".end subannotation":
            subdepth -= 1
    flush()
    return {"descriptor": descriptor, "visibility": declaration[1] if len(declaration) > 2 else None,
            "values": values, "raw_values": raw_values, "raw_lines": raw_lines,
            "source": source, "terminated": terminated}, max(start + 1, raw_end)


def _signature(annotations: list, diagnostics: list, source: dict) -> str | None:
    signatures = [a for a in annotations if a["descriptor"] == _SIGNATURE]
    if not signatures:
        return None
    values = signatures[0]["values"].get("value")
    if len(signatures) == 1 and isinstance(values, list) and all(isinstance(v, str) for v in values):
        return "".join(values)
    _diagnostic(diagnostics, "unknown_generic_signature", "Generic signature is not a single string-array annotation.", source, annotations=signatures)
    return None


def _types(arguments: str) -> list[str]:
    result, pos = [], 0
    while pos < len(arguments):
        start = pos
        while pos < len(arguments) and arguments[pos] == "[":
            pos += 1
        if pos >= len(arguments):
            raise ValueError("Incomplete array descriptor")
        if arguments[pos] == "L":
            pos = arguments.index(";", pos) + 1
        elif arguments[pos] in "ZBSCIJFD":
            pos += 1
        else:
            raise ValueError("Unsupported DEX parameter descriptor")
        result.append(arguments[start:pos])
    return result


def _next_content(lines: list[str], index: int, limit: int) -> int:
    while index < limit and not _strip_comment(lines[index]):
        index += 1
    return index


def _attached_annotations(lines, index, limit, terminator, path, sha, diagnostics):
    """An explicit .end field/.end param establishes annotation ownership."""
    cursor = _next_content(lines, index, limit)
    annotations = []
    speculative_diagnostics = []
    while cursor < limit and _strip_comment(lines[cursor]).startswith(".annotation "):
        annotation, cursor = _annotation(lines, cursor, limit, path, sha, speculative_diagnostics)
        annotations.append(annotation)
        cursor = _next_content(lines, cursor, limit)
    if cursor < limit and _strip_comment(lines[cursor]) == terminator:
        diagnostics.extend(speculative_diagnostics)
        return annotations, cursor + 1
    return [], index


def _parse_method(lines, start, end, path, sha, diagnostics):
    declaration = _strip_comment(lines[start])[len(".method "):]
    match = re.search(r"([^\s(]+)\(([^)]*)\)(\S+)$", declaration)
    source = _source(path, sha, start + 1)
    if not match:
        _diagnostic(diagnostics, "invalid_method_declaration", "Could not parse method descriptor.", source, raw=lines[start])
        return None
    name, arguments, result = match.groups()
    try:
        types = _types(arguments)
    except ValueError as exc:
        _diagnostic(diagnostics, "invalid_parameter_descriptor", str(exc), source, raw=lines[start])
        return None
    flags = declaration[:match.start()].split()
    parameters, registers = [], {}
    register = 0 if "static" in flags else 1
    for index, descriptor in enumerate(types):
        param = {"index": index, "type": descriptor, "register": f"p{register}", "annotations": [], "source": source}
        parameters.append(param)
        registers[param["register"]] = param
        register += 2 if descriptor in {"J", "D"} else 1
    annotations = []
    cursor = start + 1
    while cursor < end:
        text = _strip_comment(lines[cursor])
        if text.startswith(".param "):
            param_match = re.match(r"\.param\s+([pv]\d+)(?:\s*,\s*(.*))?$", text)
            attached, after = _attached_annotations(lines, cursor + 1, end, ".end param", path, sha, diagnostics)
            if param_match and param_match.group(1) in registers:
                param = registers[param_match.group(1)]
                param["source"] = _source(path, sha, cursor + 1)
                param["annotations"].extend(attached)
                if param_match.group(2):
                    param["debug_name"] = _literal(param_match.group(2), param["source"], diagnostics)
            else:
                _diagnostic(diagnostics, "unmapped_parameter_register", "Parameter annotation register does not map to the DEX arguments.", _source(path, sha, cursor + 1), raw=lines[cursor], annotations=attached)
            cursor = after
        elif text.startswith(".annotation "):
            annotation, cursor = _annotation(lines, cursor, end, path, sha, diagnostics)
            annotations.append(annotation)
        else:
            cursor += 1
    return {"method_name": name, "dex_signature": f"{name}({arguments}){result}", "return_type": result,
            "parameters": parameters, "annotations": annotations, "source": source, "access_flags": flags,
            "generic_signature": _signature(annotations, diagnostics, source)}


def _parse_file(path: Path, root: Path, diagnostics: list) -> dict | None:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    match = _CLASS.search(text)
    if not match:
        return None
    relative, sha = path.relative_to(root).as_posix(), hashlib.sha256(raw).hexdigest()
    lines = text.splitlines()
    result = {"class_descriptor": match.group(2), "access_flags": match.group(1).split(),
              "source": _source(relative, sha, text[:match.start()].count("\n") + 1),
              "annotations": [], "fields": [], "methods": [], "superclass": None}
    index = 0
    while index < len(lines):
        line = _strip_comment(lines[index])
        if line.startswith(".super "):
            result["superclass"] = line.split()[-1]
            index += 1
        elif line.startswith(".annotation "):
            annotation, index = _annotation(lines, index, len(lines), relative, sha, diagnostics)
            result["annotations"].append(annotation)
        elif line.startswith(".field "):
            field_match = re.match(r"\.field\s+(.*?)\s*([^\s:]+):(\S+?)(?:\s*=\s*(.*))?$", line)
            annotations, after = _attached_annotations(lines, index + 1, len(lines), ".end field", relative, sha, diagnostics)
            source = _source(relative, sha, index + 1)
            if field_match:
                flags, name, field_type, _ = field_match.groups()
                result["fields"].append({"name": name, "type": field_type, "access_flags": flags.split(),
                    "annotations": annotations, "source": source,
                    "generic_signature": _signature(annotations, diagnostics, source)})
            else:
                _diagnostic(diagnostics, "invalid_field_declaration", "Could not parse field descriptor.", source, raw=lines[index])
            index = after
        elif line.startswith(".method "):
            end = index + 1
            while end < len(lines) and _strip_comment(lines[end]) != ".end method":
                if _strip_comment(lines[end]).startswith(".method "):
                    break
                end += 1
            if end == len(lines) or _strip_comment(lines[end]) != ".end method":
                _diagnostic(diagnostics, "unterminated_method", "Method lacks .end method; declaration remains a candidate.", _source(relative, sha, index + 1))
            method = _parse_method(lines, index, end, relative, sha, diagnostics)
            if method:
                result["methods"].append(method)
            index = end + (end < len(lines) and _strip_comment(lines[end]) == ".end method")
        else:
            index += 1
    return result


def _retrofit_name(annotation: dict) -> str | None:
    match = _RETROFIT.match(annotation["descriptor"])
    return match.group(1) if match else None


def _string(value):
    return value if isinstance(value, str) else None


def _endpoints(cls: dict, diagnostics: list) -> list:
    result = []
    for method in cls["methods"]:
        http = []
        media = []
        for annotation in method["annotations"]:
            name = _retrofit_name(annotation)
            if name in _HTTP:
                http.append(annotation)
            elif name == "FormUrlEncoded":
                media.append("application/x-www-form-urlencoded")
            elif name == "Multipart":
                media.append("multipart/form-data")
            elif name == "Headers":
                value = annotation["values"].get("value", [])
                for header in value if isinstance(value, list) else [value]:
                    if isinstance(header, str) and header.partition(":")[0].lower() == "content-type":
                        media.append(header.partition(":")[2].strip())
            elif name and name not in _METHOD_MARKERS:
                _diagnostic(diagnostics, "unknown_http_annotation", "Retrofit method annotation is unsupported or in an unexpected scope; raw text retained.", annotation["source"], descriptor=annotation["descriptor"], raw="\n".join(annotation["raw_lines"]))
        parameters = []
        for original in method["parameters"]:
            param = {**original, "location": None, "name": None, "annotation": None, "bindings": []}
            for annotation in original["annotations"]:
                name = _retrofit_name(annotation)
                if not name:
                    continue
                if name not in _PARAMS:
                    _diagnostic(diagnostics, "unknown_parameter_annotation", "Unsupported Retrofit parameter annotation; raw text retained.", annotation["source"], descriptor=annotation["descriptor"], raw="\n".join(annotation["raw_lines"]))
                    continue
                values = annotation["values"]
                binding = {"annotation": annotation["descriptor"], "location": _PARAMS[name], "name": _string(values.get("value")), "values": values}
                if "encoded" in values:
                    binding["encoded"] = values["encoded"] if isinstance(values["encoded"], bool) else None
                    if binding["encoded"] is None:
                        _diagnostic(diagnostics, "unknown_encoding", "encoded is not a boolean; no encoding behavior inferred.", annotation["source"], raw=annotation["raw_values"].get("encoded"))
                param["bindings"].append(binding)
            if len(param["bindings"]) == 1:
                param.update({key: param["bindings"][0][key] for key in ("location", "name", "annotation")})
                if "encoded" in param["bindings"][0]:
                    param["encoded"] = param["bindings"][0]["encoded"]
            elif len(param["bindings"]) > 1:
                _diagnostic(diagnostics, "multiple_parameter_bindings", "Multiple Retrofit bindings retained; primary location is unknown.", param["source"], bindings=param["bindings"])
            parameters.append(param)
        if len(http) > 1:
            _diagnostic(diagnostics, "multiple_http_annotations", "Each observed HTTP declaration is preserved; runtime validity is unverified.", method["source"])
        if http and any(p["type"] == "Lkotlin/coroutines/Continuation;" for p in parameters):
            _diagnostic(diagnostics, "kotlin_suspend_return_unknown", "Suspend continuation generics are preserved but not interpreted as a response DTO.", method["source"])
        for annotation in http:
            name, values = _retrofit_name(annotation), annotation["values"]
            verb = _string(values.get("method")) if name == "HTTP" else name
            path = _string(values.get("path" if name == "HTTP" else "value"))
            if verb is None:
                _diagnostic(diagnostics, "unknown_http_method", "@HTTP method was not a decodable string.", annotation["source"], raw="\n".join(annotation["raw_lines"]))
            if path is None and not any(p["location"] == "url" for p in parameters):
                _diagnostic(diagnostics, "unknown_http_path", "No literal path or observed @Url binding; path remains unknown.", annotation["source"], raw="\n".join(annotation["raw_lines"]))
            key = json.dumps([cls["class_descriptor"], method["dex_signature"], verb, path], ensure_ascii=False, separators=(",", ":"))
            contract = {"method": verb, "path": path}
            if name == "HTTP":
                contract["has_body"] = values.get("hasBody") if isinstance(values.get("hasBody"), bool) else None
            result.append({"id": hashlib.sha256(key.encode()).hexdigest(), "class_descriptor": cls["class_descriptor"],
                **{k: method[k] for k in ("method_name", "dex_signature", "return_type", "generic_signature", "annotations", "source")},
                "http": contract, "parameters": parameters, "status": "observed", "media_types": sorted(set(media)),
                "dynamic_url": any(p["location"] == "url" for p in parameters)})
    return result


def _references(signature: str | None) -> set[str]:
    return {"L" + name + ";" for name in re.findall(r"L([^;<:()\s]+)", signature or "")}


def _model(cls: dict, diagnostics: list) -> dict:
    fields, omitted = [], []
    for original in cls["fields"]:
        if set(original["access_flags"]) & {"static", "synthetic"}:
            omitted.append({"name": original["name"], "reason": "static_or_synthetic", "source": original["source"]})
            continue
        field = {**original, "serialized_name": original["name"], "serialized_name_evidence": "field_name_fallback",
                 "aliases": [], "required": None, "nullable": None, "serialization_excluded": "transient" in original["access_flags"]}
        names = []
        for annotation in original["annotations"]:
            values = annotation["values"]
            if annotation["descriptor"] == "Lcom/squareup/moshi/Json;":
                if values.get("ignore") is True:
                    field["serialization_excluded"] = True
                name = _string(values.get("name"))
                if name is not None and name != "\x00":
                    names.append(name)
            elif annotation["descriptor"] == "Lcom/google/gson/annotations/SerializedName;":
                name = _string(values.get("value"))
                if name is not None:
                    names.append(name)
                alternate = values.get("alternate", [])
                if isinstance(alternate, list):
                    field["aliases"].extend(x for x in alternate if isinstance(x, str))
        if names:
            field["serialized_name_evidence"] = "serialization_annotation"
            field["serialized_name"] = names[0] if len(set(names)) == 1 else None
            if field["serialized_name"] is None:
                _diagnostic(diagnostics, "conflicting_serialized_names", "Serializer annotations disagree; wire name remains unknown.", field["source"], candidates=names)
        fields.append(field)
    if any(a["descriptor"] == "Lkotlin/Metadata;" for a in cls["annotations"]):
        _diagnostic(diagnostics, "kotlin_semantics_unknown", "Kotlin metadata, constructor defaults and property/getter adapters are not interpreted; required and nullable remain unknown.", cls["source"])
    return {"class_descriptor": cls["class_descriptor"], "source": cls["source"], "status": "candidate",
            "superclass": cls["superclass"], "generic_signature": _signature(cls["annotations"], diagnostics, cls["source"]),
            "annotations": cls["annotations"], "fields": fields, "omitted_fields": omitted,
            "limitations": ["Field-name fallback may be overridden by naming policies or custom adapters.",
                            "Required, nullable, Kotlin properties, polymorphism and server-side validation are not inferred."]}


def harvest(decoded_root: Path, apk_sha256: str) -> dict:
    """Discover static Retrofit declarations and reachable DTO field candidates.

    IDs are stable over source relocation/line changes and preserve overloads.
    apk_sha256 is supplied provenance, not verified against an APK by this layer.
    """
    root = Path(decoded_root).resolve()
    if not root.is_dir():
        raise ValueError(f"decoded_root is not a directory: {root}")
    diagnostics, endpoints = [], []
    index, parsed = {}, {}
    files = sorted(p for p in root.rglob("*.smali") if p.is_file() and
                   any(re.fullmatch(r"smali(?:[_.].+)?", part) for part in (root.name, *p.relative_to(root).parts[:-1])))
    for path in files:
        if not path.resolve().is_relative_to(root):
            _diagnostic(diagnostics, "outside_decoded_root", "Symlink target outside decoded root was not read.", {"path": path.relative_to(root).as_posix(), "sha256": None, "line": 1})
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            _diagnostic(diagnostics, "unreadable_smali", str(exc), {"path": path.relative_to(root).as_posix(), "sha256": None, "line": 1})
            continue
        match = _CLASS.search(text)
        if not match:
            _diagnostic(diagnostics, "missing_class_declaration", "No class descriptor found.", _source(path.relative_to(root).as_posix(), hashlib.sha256(raw).hexdigest(), 1))
            continue
        descriptor = match.group(2)
        if descriptor in index:
            _diagnostic(diagnostics, "duplicate_class_descriptor", "First sorted source is used for DTO lookup; both files are scanned for endpoints.", _source(path.relative_to(root).as_posix(), hashlib.sha256(raw).hexdigest(), 1), class_descriptor=descriptor)
        else:
            index[descriptor] = path
        if re.search(r"^\s*\.annotation\s+\S+\s+Lretrofit2?/http/", text, re.M):
            cls = _parse_file(path, root, diagnostics)
            if cls:
                parsed.setdefault(descriptor, cls)
                endpoints.extend(_endpoints(cls, diagnostics))
    pending = set()
    for endpoint in endpoints:
        signature = endpoint["generic_signature"]
        pending |= _references(signature.split(")", 1)[1] if signature and ")" in signature else endpoint["return_type"])
        for parameter in endpoint["parameters"]:
            if parameter["location"] == "body":
                pending |= _references(parameter["type"])
    queue, visited, models, unresolved = deque(sorted(pending)), set(), [], []
    while queue:
        descriptor = queue.popleft()
        if descriptor in visited or descriptor.startswith(_BUILTIN_PREFIXES):
            continue
        visited.add(descriptor)
        if descriptor not in index:
            unresolved.append(descriptor)
            _diagnostic(diagnostics, "unresolved_model", "Referenced DTO descriptor has no smali definition in this decoded root.", {"path": None, "sha256": None, "line": None}, class_descriptor=descriptor)
            continue
        cls = parsed.get(descriptor) or _parse_file(index[descriptor], root, diagnostics)
        if not cls:
            continue
        model = _model(cls, diagnostics)
        models.append(model)
        dependencies = _references(cls["superclass"])
        for field in model["fields"]:
            if not field["serialization_excluded"]:
                dependencies |= _references(field["generic_signature"]) | _references(field["type"])
        queue.extend(sorted(dependencies - visited))
    endpoints.sort(key=lambda e: (e["class_descriptor"], e["dex_signature"], e["id"], e["source"]["path"]))
    models.sort(key=lambda m: m["class_descriptor"])
    return {"schema_version": 1, "apk_sha256": apk_sha256, "endpoints": endpoints, "models": models,
            "diagnostics": diagnostics, "coverage": {
                "smali_files": len(files), "class_count": len(index), "endpoint_count": len(endpoints),
                "endpoint_class_count": len({e["class_descriptor"] for e in endpoints}), "model_count": len(models),
                "unresolved_model_descriptors": sorted(unresolved), "network_requests_performed": False,
                "scope": "Retrofit declaration annotations and reachable DTO field candidates only",
                "limitations": ["APK/source integrity binding is the caller's responsibility.",
                    "Runtime reachability, base URLs, interceptors, custom serialization, native/RPC calls and backend semantics are not inferred."]}}

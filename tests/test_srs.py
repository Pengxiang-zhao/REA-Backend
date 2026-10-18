"""SRS bundles retain source provenance and distinguish validity from readiness."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from rea_backend.srs import check_srs, initialize_srs


SECTIONS = [
    "1. Document and product overview", "2. System boundary and operating environment", "3. Users, roles and use cases",
    "4. App capability overview", "5. Functional requirements", "6. Data requirements", "7. Interfaces and external integrations",
    "8. Quality and operation requirements", "9. Project extensions", "10. Delivery and acceptance criteria",
    "Appendix A. Inputs and evidence", "Appendix B. Assumptions, gaps and decisions", "Appendix C. Requirement traceability",
]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def materials(tmp_path):
    client = tmp_path / "client"
    client.mkdir()
    source = client / "Article.kt"
    source.write_text(
        'data class Article(val id: Int, val title: String)\n'
        'interface ArticleApi {\n'
        '    @GET("/articles") suspend fun articles(): List<Article>\n'
        '}\n', encoding="utf-8",
    )
    (client / "README.md").write_text("Synthetic reader source fixture.\n", encoding="utf-8")
    config = {
        "format": "rea-backend.srs-config/v1",
        "app": {"id": "reader", "name": "Reader", "version": "1.0", "platform": "Android", "variant": "main"},
        "route": "source",
        "context": {"mode": "client_only", "notes": "Fixed synthetic client; no server evidence."},
        "inputs": [{
            "id": "client", "kind": "client_source", "path": "client", "version": "fixture-v1",
            "access": "generation", "complete": True, "limitations": [], "exclude": [],
        }],
        "environment": {
            "goals": ["Provide an isolated local backend for the Android client."],
            "constraints": ["Runtime must not call the original service."],
        },
    }
    config_path = tmp_path / "inputs.json"
    write_json(config_path, config)
    template = tmp_path / "template.md"
    template.write_text(
        "# <App name> Backend Software Requirements Specification\n\n"
        + "\n".join(f"## {section}\n\nTo be completed.\n" for section in SECTIONS), encoding="utf-8",
    )
    return {"root": tmp_path, "source": source, "config": config_path, "template": template, "out": tmp_path / "bundle"}


def initialize(materials):
    return initialize_srs(materials["config"], materials["out"], template=materials["template"])


def valid_index(materials):
    return {
        "format": "rea-backend.srs-index/v1", "app_id": "reader", "scope": "app-wide", "status": "draft",
        "discovery": [{
            "area": area,
            "summary": f"Inspected the fixture's {area} entry points; only article retrieval is declared.",
            "evidence_ids": ["EV-GET"], "gap_ids": [],
        } for area in ["ui", "background", "protocol", "data_and_dependencies"]],
        "capabilities": [{
            "id": "CAP-articles", "title": "Retrieve articles", "module": "Articles", "trigger": "Article list synchronization",
            "execution": ["backend"], "backend_responsibility": "Return the article list in the client's declared format.",
            "analysis": "analyzed", "disposition": "planned", "reason": "Required by the only declared API call.",
            "evidence_ids": ["EV-GET"], "requirement_ids": ["FR-articles-001"], "gap_ids": [],
        }],
        "requirements": [{
            "id": "FR-articles-001", "title": "List articles", "kind": "functional", "status": "observed",
            "statement": "The backend shall accept GET /articles and return a list of Article objects.",
            "acceptance": "The client can deserialize a response containing one article with an integer id and string title.",
            "basis": "", "anchor": "FR-articles-001", "capability_ids": ["CAP-articles"],
            "evidence_ids": ["EV-GET"], "gap_ids": [],
        }],
        "evidence": [{
            "id": "EV-GET", "input_id": "client", "path": "Article.kt", "sha256": digest(materials["source"]),
            "start_line": 1, "end_line": 4,
            "note": "The DTO and request declaration establish response shape; they do not prove server authorization behavior.",
        }],
        "gaps": [], "limitations": ["This fixture checks structural provenance, not actual product completeness."],
    }


def write_document(path):
    sections = {
        "1.": "Reader 1.0 Android; this specification covers the fixture's article retrieval contract.",
        "2.": "The client displays articles; the local server supplies JSON and makes no outbound service calls.",
        "3.": "A local reader invokes synchronization. No additional product roles are established by this fixture.",
        "4.": "CAP-articles: article synchronization invokes the backend; it is planned for implementation.",
        "5.": '<a id="FR-articles-001"></a>\n\nThe backend shall accept GET /articles. The result is a JSON list of Article objects with integer id and string title. Verify by deserializing one seeded article. Source: EV-GET.',
        "6.": "Article has an integer id and a string title. Retrieval does not mutate article state.",
        "7.": "GET /articles returns the Article list consumed by ArticleApi. No other endpoint is established.",
        "8.": "The declared environment requires local operation without contacting the original service.",
        "9.": "No additional project extension is defined in this structural fixture.",
        "10.": "Implement CAP-articles first and verify FR-articles-001 through the client's declared DTO.",
        "Appendix A.": "EV-GET references Article.kt lines 1–4 in the frozen client input.",
        "Appendix B.": "No unresolved question is asserted in this minimal structural fixture.",
        "Appendix C.": "CAP-articles → FR-articles-001 → EV-GET; implementation and runtime verification remain separate work.",
    }
    path.write_text(
        "# Reader Backend Software Requirements Specification\n\n" + "\n".join(
            f"## {section}\n\n{next(text for prefix, text in sections.items() if section.startswith(prefix))}\n"
            for section in SECTIONS
        ), encoding="utf-8",
    )


@pytest.fixture
def bundle(materials):
    initialize(materials)
    write_json(materials["out"] / "index.json", valid_index(materials))
    write_document(materials["out"] / "backend-srs.md")
    return materials


def mutate_index(bundle, mutation):
    path = bundle["out"] / "index.json"
    index = read_json(path)
    mutation(index)
    write_json(path, index)


def reviewed(bundle):
    mutate_index(bundle, lambda index: index.update(status="reviewed"))
    out = bundle["out"]
    review = {
        "format": "rea-backend.srs-review/v1", "reviewer": "independent-fixture-reviewer", "independent": True,
        "verdict": "accepted", "document_sha256": digest(out / "backend-srs.md"),
        "index_sha256": digest(out / "index.json"), "inventory_sha256": digest(out / "inventory.json"),
        "summary": "Reviewed the complete synthetic fixture, its associations, source locators, and documented limits.",
        "issues": [],
    }
    if read_json(out / "run.json")["format"] == "rea-backend.srs-run/v2":
        review["format"] = "rea-backend.srs-review/v2"
        review.update({key: digest(out / name) for key, name in (
            ("run_sha256", "run.json"), ("analysis_sha256", "analysis/analysis.json"),
            ("method_sha256", "method/manifest.json"))})
        analysis = read_json(out / "analysis/analysis.json")
        if analysis["format"] == "rea-backend.analysis/v3":
            review["format"] = "rea-backend.srs-review/v3"
            review["sampling"] = {
                "selection_rationale": "Independently inspect the only declared request and response type in the synthetic client.",
                "not_inspected": ["This fixture contains no UI implementation, write operation, or runtime execution evidence."],
                "samples": [{
                    "id": "RS-articles", "entry": "ArticleApi.articles declaration",
                    "selection_reason": "Check whether the author's article contract is supported by the source declaration.",
                    "risk_focus": ["Declared endpoint and response type"],
                    "author_item_ids": [analysis["items"][0]["id"]],
                    "evidence": [{"id": "RAW-articles", "input_id": "client", "path": "Article.kt",
                                  "sha256": digest(bundle["source"]), "symbol": "ArticleApi.articles",
                                  "location": "lines 1-4", "note": "Raw synthetic declaration, not a runtime trace."}],
                    "reconstructed_chain": [{
                        "id": "RS-node", "kind": "request",
                        "observation": "The declaration binds GET /articles to List<Article> with integer id and string title; callers are absent.",
                        "evidence_ids": ["RAW-articles"],
                    }],
                    "comparison": {"status": "matched", "finding": "The author's declared shape matches the raw source; runtime callers remain outside this fixture.",
                                   "issue_ids": [], "work_item_ids": [], "gap_ids": []},
                }],
            }
    write_json(out / "review.json", review)
    return review


def check(bundle, *, require_reviewed=False):
    return check_srs(bundle["config"], bundle["out"], require_reviewed=require_reviewed)


def assert_error(report):
    assert report["status"] == "error"
    assert report["errors"]
    assert report["ready_for_implementation"] is False


def test_initializer_prepares_materials_but_does_not_claim_completed_srs(materials):
    result = initialize(materials)
    assert result["status"] == "initialized"
    assert {"backend-srs.md", "index.json", "inventory.json", "run.json"}.issubset(
        {path.name for path in materials["out"].iterdir()}
    )
    assert_error(check(materials))


def test_initializer_refuses_to_overwrite_existing_output(materials):
    initialize(materials)
    marker = materials["out"] / "keep.txt"
    marker.write_text("Do not overwrite")
    with pytest.raises((ValueError, OSError)):
        initialize(materials)
    assert marker.read_text() == "Do not overwrite"


def test_initializer_rejects_output_inside_generation_input(materials):
    with pytest.raises((ValueError, OSError)):
        initialize_srs(materials["config"], materials["source"].parent / "srs", template=materials["template"])


def test_structural_validity_does_not_imply_review_or_readiness(bundle):
    report = check(bundle)
    assert report["status"] == "checked"
    assert report["errors"] == []
    assert isinstance(report["warnings"], list)
    assert report["ready_for_implementation"] is False
    assert_error(check(bundle, require_reviewed=True))


def test_independent_current_review_allows_readiness_without_mutating_bundle(bundle):
    reviewed(bundle)
    before = {p.name: p.read_bytes() for p in bundle["out"].iterdir() if p.is_file()}
    report = check(bundle, require_reviewed=True)
    assert report["status"] == "checked"
    assert report["ready_for_implementation"] is True
    after = {p.name: p.read_bytes() for p in bundle["out"].iterdir() if p.is_file()}
    assert after == before


@pytest.mark.parametrize("mutation", [
    lambda i: i["evidence"][0].update(sha256="f" * 64),
    lambda i: i["evidence"][0].update(start_line=0),
    lambda i: i["evidence"][0].update(end_line=5),
    lambda i: i["evidence"][0].update(start_line=4, end_line=3),
    lambda i: i["evidence"][0].pop("end_line"),
    lambda i: i["evidence"][0].update(path="../Article.kt"),
    lambda i: i["evidence"][0].update(path="/tmp/Article.kt"),
    lambda i: i["evidence"][0].update(path="missing.kt"),
])
def test_unverifiable_source_locators_fail(bundle, mutation):
    mutate_index(bundle, mutation)
    assert_error(check(bundle))


@pytest.mark.parametrize("collection,field,value", [
    ("requirements", "evidence_ids", ["EV-missing"]),
    ("requirements", "capability_ids", ["CAP-missing"]),
    ("requirements", "gap_ids", ["GAP-missing"]),
    ("capabilities", "requirement_ids", ["FR-missing"]),
    ("capabilities", "evidence_ids", ["EV-missing"]),
    ("evidence", "input_id", "missing-input"),
])
def test_dangling_references_fail(bundle, collection, field, value):
    mutate_index(bundle, lambda i: i[collection][0].update({field: value}))
    assert_error(check(bundle))


@pytest.mark.parametrize("side", ["requirements", "capabilities"])
def test_capability_requirement_relationship_must_be_bidirectional(bundle, side):
    def mutation(index):
        if side == "requirements":
            # Quality requirements may omit capabilities, so only reciprocity is violated.
            index["requirements"][0].update(kind="quality", capability_ids=[])
        else:
            # Local capabilities may omit requirements, so only reciprocity is violated.
            index["capabilities"][0].update(execution=["client"], disposition="client_only", requirement_ids=[])
    mutate_index(bundle, mutation)
    assert_error(check(bundle))


@pytest.mark.parametrize("collection", ["requirements", "capabilities", "evidence"])
def test_duplicate_ids_are_rejected(bundle, collection):
    mutate_index(bundle, lambda i: i[collection].append(deepcopy(i[collection][0])))
    assert_error(check(bundle))


def test_id_uniqueness_extends_across_record_kinds(bundle):
    mutate_index(bundle, lambda i: i["gaps"].append({
        "id": "EV-GET", "question": "Is the call retried?", "impact": "Retry rules", "blocking": False,
        "status": "open", "resolution": "", "evidence_ids": [],
    }))
    assert_error(check(bundle))


@pytest.mark.parametrize("area", ["ui", "background", "protocol", "data_and_dependencies"])
def test_whole_app_discovery_must_cover_each_entry_point_class(bundle, area):
    mutate_index(bundle, lambda i: i.update(discovery=[d for d in i["discovery"] if d["area"] != area]))
    assert_error(check(bundle))


def test_discovery_claim_needs_evidence_or_explicit_gap(bundle):
    mutate_index(bundle, lambda i: i["discovery"][0].update(evidence_ids=[], gap_ids=[]))
    assert_error(check(bundle))


def test_requirement_anchor_must_resolve_to_the_document(bundle):
    mutate_index(bundle, lambda i: i["requirements"][0].update(anchor="absent-anchor"))
    assert_error(check(bundle))


def test_duplicate_document_anchor_is_not_unambiguous_traceability(bundle):
    path = bundle["out"] / "backend-srs.md"
    path.write_text(path.read_text() + '\n<a id="FR-articles-001"></a>\n')
    assert_error(check(bundle))


def test_required_document_chapter_cannot_be_dropped(bundle):
    path = bundle["out"] / "backend-srs.md"
    path.write_text(path.read_text().replace("## 6. Data requirements", "## Data information"))
    assert_error(check(bundle))


def add_gap(index, *, blocking=True):
    index["gaps"].append({
        "id": "GAP-retry", "question": "How does a retry affect list consistency?", "impact": "Retry behavior is not established.",
        "blocking": blocking, "status": "open", "resolution": "", "evidence_ids": ["EV-GET"],
    })


def test_reviewed_srs_with_blocking_gap_is_valid_but_not_ready(bundle):
    mutate_index(bundle, add_gap)
    reviewed(bundle)
    report = check(bundle, require_reviewed=True)
    assert report["status"] == "checked"
    assert report["ready_for_implementation"] is False


def test_nonblocking_documented_gap_does_not_block_readiness(bundle):
    mutate_index(bundle, lambda i: add_gap(i, blocking=False))
    reviewed(bundle)
    assert check(bundle, require_reviewed=True)["ready_for_implementation"] is True


def test_unknown_requirement_requires_an_open_gap(bundle):
    mutate_index(bundle, lambda i: i["requirements"][0].update(status="unknown"))
    assert_error(check(bundle))


def test_unknown_rule_remains_unready_even_if_its_gap_is_nonblocking(bundle):
    def mutation(index):
        add_gap(index, blocking=False)
        index["requirements"][0].update(status="unknown", gap_ids=["GAP-retry"])
    mutate_index(bundle, mutation)
    reviewed(bundle)
    report = check(bundle, require_reviewed=True)
    assert report["status"] == "checked"
    assert report["ready_for_implementation"] is False


@pytest.mark.parametrize("analysis", ["candidate", "blocked"])
def test_unanalyzed_capability_prevents_full_readiness(bundle, analysis):
    def mutation(index):
        add_gap(index, blocking=False)
        index["capabilities"][0].update(analysis=analysis, gap_ids=["GAP-retry"])
    mutate_index(bundle, mutation)
    reviewed(bundle)
    report = check(bundle, require_reviewed=True)
    assert report["status"] == "checked"
    assert report["ready_for_implementation"] is False


def test_project_extension_cannot_be_mislabeled_as_recovered_product_behavior(bundle):
    mutate_index(bundle, lambda i: i["requirements"][0].update(kind="extension", status="observed"))
    assert_error(check(bundle))


@pytest.mark.parametrize("status", ["inferred", "assumed", "project"])
def test_nonobserved_requirements_record_their_basis(bundle, status):
    mutate_index(bundle, lambda i: i["requirements"][0].update(status=status, basis=""))
    assert_error(check(bundle))


@pytest.mark.parametrize("change", ["modify", "add", "delete"])
def test_changed_input_snapshot_invalidates_the_existing_bundle(bundle, change):
    if change == "modify":
        bundle["source"].write_text("interface ChangedApi {}\n")
    elif change == "add":
        (bundle["source"].parent / "Extra.kt").write_text("class Extra\n")
    else:
        bundle["source"].unlink()
    assert_error(check(bundle))


def test_changed_configuration_invalidates_existing_bundle(bundle):
    config = read_json(bundle["config"])
    config["app"]["version"] = "2.0"
    write_json(bundle["config"], config)
    assert_error(check(bundle))


def test_input_symlink_cannot_escape_the_declared_material_root(materials):
    external = materials["root"] / "external.kt"
    external.write_text("class External\n")
    (materials["source"].parent / "Escaped.kt").symlink_to(external)
    with pytest.raises((ValueError, OSError)):
        initialize(materials)


def test_excluded_input_is_not_read_or_admitted_as_generation_evidence(materials):
    config = read_json(materials["config"])
    config["inputs"].append({
        "id": "oracle", "kind": "reference", "path": "does-not-exist/server", "version": "server-v1",
        "access": "excluded", "complete": True, "limitations": [], "exclude": [],
    })
    write_json(materials["config"], config)
    initialize(materials)  # Excluded evidence need not even exist on the generation host.
    index = valid_index(materials)
    index["evidence"][0]["input_id"] = "oracle"
    write_json(materials["out"] / "index.json", index)
    write_document(materials["out"] / "backend-srs.md")
    assert_error(check(materials))


def test_generation_root_cannot_reinclude_declared_excluded_subtree(materials):
    oracle = materials["source"].parent / "oracle"
    oracle.mkdir()
    (oracle / "Server.kt").write_text("class InternalServer {}\n", encoding="utf-8")
    config = read_json(materials["config"])
    config["inputs"].append({
        "id": "oracle", "kind": "reference", "path": "client/oracle", "version": "server-v1",
        "access": "excluded", "complete": True, "limitations": [], "exclude": [],
    })
    write_json(materials["config"], config)
    # A broad client path must not silently read the excluded subtree and let
    # evidence cite it under input_id="client" instead of input_id="oracle".
    with pytest.raises((ValueError, OSError)):
        initialize(materials)


def test_client_only_generation_rejects_reference_input(materials):
    config = read_json(materials["config"])
    config["inputs"].append({
        "id": "oracle", "kind": "reference", "path": "client", "version": "server-v1",
        "access": "generation", "complete": True, "limitations": [], "exclude": [],
    })
    write_json(materials["config"], config)
    with pytest.raises((ValueError, OSError)):
        initialize(materials)


@pytest.mark.parametrize("kind", ["client_source", "client_dependency"])
def test_apk_route_rejects_generation_source_material(materials, kind):
    apk = materials["root"] / "reader.apk"
    apk.write_bytes(b"synthetic-apk-for-input-validation")
    config = read_json(materials["config"])
    config["route"] = "apk"
    config["inputs"][0]["kind"] = kind
    config["inputs"].append({
        "id": "apk", "kind": "client_apk", "path": "reader.apk", "version": "1.0",
        "access": "generation", "complete": True, "limitations": [], "exclude": [], "sha256": digest(apk),
    })
    write_json(materials["config"], config)
    with pytest.raises((ValueError, OSError)):
        initialize(materials)


def test_declared_single_file_hash_is_verified(materials):
    config = read_json(materials["config"])
    config["inputs"][0].update(path="client/Article.kt", sha256="0" * 64)
    write_json(materials["config"], config)
    with pytest.raises((ValueError, OSError)):
        initialize(materials)


def test_incomplete_input_requires_declared_limitations(materials):
    config = read_json(materials["config"])
    config["inputs"][0]["complete"] = False
    write_json(materials["config"], config)
    with pytest.raises((ValueError, OSError)):
        initialize(materials)


def test_incomplete_input_needs_an_output_gap_and_never_becomes_fully_ready(materials):
    config = read_json(materials["config"])
    config["inputs"][0].update(complete=False, limitations=["The fixture omits the application's background job sources."])
    write_json(materials["config"], config)
    initialize(materials)
    write_json(materials["out"] / "index.json", valid_index(materials))
    write_document(materials["out"] / "backend-srs.md")
    assert_error(check(materials))
    def record_gap(index):
        index["limitations"].append("The client input omits background job sources.")
        index["gaps"].append({
            "id": "GAP-client", "question": "What jobs exist in the missing client sources?",
            "impact": "Background capabilities have not been inventoried.", "blocking": False,
            "status": "open", "resolution": "", "evidence_ids": [],
        })
    mutate_index(materials, record_gap)
    reviewed(materials)
    report = check(materials, require_reviewed=True)
    assert report["status"] == "checked"
    assert report["ready_for_implementation"] is False


def test_excluded_and_internal_cache_changes_do_not_invalidate_snapshot(materials):
    config = read_json(materials["config"])
    config["inputs"][0]["exclude"] = ["generated/*"]
    write_json(materials["config"], config)
    generated = materials["source"].parent / "generated"
    generated.mkdir()
    (generated / "Build.kt").write_text("class Build\n")
    initialize(materials)
    write_json(materials["out"] / "index.json", valid_index(materials))
    write_document(materials["out"] / "backend-srs.md")
    (generated / "Build.kt").write_text("class ChangedBuild\n")
    (materials["source"].parent / ".DS_Store").write_bytes(b"local metadata")
    assert check(materials)["status"] == "checked"


def test_single_file_material_uses_its_basename_for_evidence(materials):
    config = read_json(materials["config"])
    config["inputs"][0].update(path="client/Article.kt", sha256=digest(materials["source"]))
    write_json(materials["config"], config)
    initialize(materials)
    write_json(materials["out"] / "index.json", valid_index(materials))
    write_document(materials["out"] / "backend-srs.md")
    assert check(materials)["status"] == "checked"


@pytest.mark.parametrize("collection,field,value", [
    ("requirements", "status", []),
    ("capabilities", "execution", {}),
    ("requirements", "evidence_ids", [None, {}]),
    ("evidence", "start_line", True),
    ("evidence", "input_id", []),
])
def test_malformed_index_fields_produce_reports_not_incidental_exceptions(bundle, collection, field, value):
    mutate_index(bundle, lambda i: i[collection][0].update({field: value}))
    assert_error(check(bundle))


@pytest.mark.parametrize("filename", ["backend-srs.md", "index.json", "inventory.json"])
def test_review_hashes_bind_to_exact_final_artifacts(bundle, filename):
    reviewed(bundle)
    path = bundle["out"] / filename
    path.write_bytes(path.read_bytes() + b"\n")
    assert_error(check(bundle, require_reviewed=True))


@pytest.mark.parametrize("field,value", [("independent", False), ("verdict", "revisions_required")])
def test_nonindependent_or_unaccepted_review_cannot_pass_gate(bundle, field, value):
    review = reviewed(bundle)
    review[field] = value
    write_json(bundle["out"] / "review.json", review)
    assert_error(check(bundle, require_reviewed=True))


def test_accepted_review_cannot_hide_open_material_findings(bundle):
    review = reviewed(bundle)
    review["issues"] = [{
        "id": "ISSUE-auth", "severity": "high", "status": "open", "target_ids": ["FR-articles-001"],
        "finding": "The account isolation requirement is unsupported.", "resolution": "",
    }]
    write_json(bundle["out"] / "review.json", review)
    assert_error(check(bundle, require_reviewed=True))


def test_empty_document_sections_and_bare_anchor_do_not_form_a_completed_srs(bundle):
    (bundle["out"] / "backend-srs.md").write_text(
        "# Reader SRS\n\n" + "\n\n".join(f"## {section}" for section in SECTIONS)
        + '\n<a id="FR-articles-001"></a>\n', encoding="utf-8",
    )
    reviewed(bundle)
    assert_error(check(bundle, require_reviewed=True))


def test_requirement_anchor_needs_its_own_entry_text(bundle):
    path = bundle["out"] / "backend-srs.md"
    anchor = '<a id="FR-articles-001"></a>'
    path.write_text(path.read_text(encoding="utf-8").replace(anchor, "") + f"\n{anchor}\n", encoding="utf-8")
    reviewed(bundle)
    assert_error(check(bundle, require_reviewed=True))


def test_table_headers_with_empty_rows_do_not_count_as_srs_content(bundle):
    empty_table = "| Field | Content |\n|---|---|\n| | |\n"
    body = "# Reader SRS\n\n" + "\n".join(f"## {section}\n\n{empty_table}" for section in SECTIONS)
    body += '\n<a id="FR-articles-001"></a>\n' + empty_table
    (bundle["out"] / "backend-srs.md").write_text(body, encoding="utf-8")
    reviewed(bundle)
    assert_error(check(bundle, require_reviewed=True))


def test_new_legacy_initialization_is_explicit_without_rewriting_old_bundles(bundle):
    assert read_json(bundle["out"] / "run.json")["analysis_tracking"] == "legacy/untracked"
    # Historical v1 bundles have neither new flags nor frozen method/analysis files.
    run = read_json(bundle["out"] / "run.json")
    del run["analysis_tracking"]
    write_json(bundle["out"] / "run.json", run)
    reviewed(bundle)
    before = {p.name: p.read_bytes() for p in bundle["out"].iterdir()}
    report = check(bundle, require_reviewed=True)
    assert report["status"] == "checked"
    assert report["analysis_tracking"] == "legacy/untracked"
    assert any("Legacy/untracked" in message for message in report["warnings"])
    assert {p.name: p.read_bytes() for p in bundle["out"].iterdir()} == before


def test_tracked_review_binds_run_analysis_and_method(materials):
    from test_analysis import tracked_bundle
    tracked_bundle(materials)
    review = reviewed(materials)
    assert review["format"] == "rea-backend.srs-review/v3"
    assert {"run_sha256", "analysis_sha256", "method_sha256"} <= review.keys()
    report = check(materials, require_reviewed=True)
    assert report["status"] == "checked"
    assert report["analysis_tracking"] == "tracked"
    assert report["analysis_work"]["settled"] is True


@pytest.mark.parametrize("filename", ["run.json", "analysis/analysis.json", "method/manifest.json", "method/files/skill.md"])
def test_tracked_provenance_tamper_invalidates_review(materials, filename):
    from test_analysis import tracked_bundle
    tracked_bundle(materials)
    reviewed(materials)
    target = materials["out"] / filename
    target.write_bytes(target.read_bytes() + b"\n")
    report = check(materials, require_reviewed=True)
    assert_error(report)
    assert report["review"] == "not_accepted"


@pytest.mark.parametrize("mutation", ["remove", "resolve", "nonblocking"])
def test_frozen_blocked_analysis_maps_to_open_gaps_and_remains_unready(materials, mutation):
    from test_analysis import tracked_bundle
    tracked_bundle(materials, state="blocked")
    index = read_json(materials["out"] / "index.json")
    assert index["gaps"][0]["id"] == "G-analysis"
    if mutation == "remove":
        index["gaps"] = []
    elif mutation == "resolve":
        index["gaps"][0].update(status="resolved", resolution="Unsupported closure of frozen blocked work.")
    else:
        index["gaps"][0]["blocking"] = False
    write_json(materials["out"] / "index.json", index)
    reviewed(materials)
    report = check(materials, require_reviewed=True)
    assert report["ready_for_implementation"] is False
    assert report["status"] == ("checked" if mutation == "nonblocking" else "error")


def test_tracked_bundle_rejects_legacy_review(materials):
    from test_analysis import tracked_bundle
    tracked_bundle(materials)
    review = reviewed(materials)
    review["format"] = "rea-backend.srs-review/v1"
    for key in ("run_sha256", "analysis_sha256", "method_sha256"):
        del review[key]
    write_json(materials["out"] / "review.json", review)
    assert_error(check(materials, require_reviewed=True))


def test_repository_method_upgrade_does_not_rewrite_or_invalidate_frozen_method(materials):
    from rea_backend.method_bundle import DEFAULT_FILES
    from test_analysis import tracked_bundle
    method_root = materials["root"] / "method-source"
    method_root.mkdir()
    files = []
    for iid, _ in DEFAULT_FILES:
        path = method_root / f"{iid}.md"
        path.write_text(f"Normative fixture for {iid}.\n")
        files.append({"id": iid, "path": path.name})
    manifest = method_root / "method.json"
    write_json(manifest, {"format": "rea-backend.srs-method-spec/v1", "version": "fixture-method-1", "files": files})
    tracked_bundle(materials, method_manifest=manifest)
    reviewed(materials)
    frozen_dir = materials["out"] / "method"
    frozen = {p.relative_to(frozen_dir): p.read_bytes() for p in frozen_dir.rglob("*") if p.is_file()}
    for source in method_root.glob("*.md"):
        source.write_text("New repository method revision.\n")
    manifest.unlink()
    report = check(materials, require_reviewed=True)
    assert report["status"] == "checked"
    assert report["ready_for_implementation"] is True
    assert frozen == {p.relative_to(frozen_dir): p.read_bytes() for p in frozen_dir.rglob("*") if p.is_file()}
    copied_template = frozen_dir / "files/template.md"
    assert copied_template.read_bytes() == materials["template"].read_bytes()


def test_method_inventory_is_explicit_and_has_no_historical_app_artifacts(materials):
    from rea_backend.method_bundle import DEFAULT_FILES
    from test_analysis import tracked_bundle
    tracked_bundle(materials)
    rows = read_json(materials["out"] / "method/manifest.json")["files"]
    assert {r["id"] for r in rows} == {iid for iid, _ in DEFAULT_FILES}
    assert {r["id"] for r in rows} == {
        "skill", "template", "discovery", "behavior", "format", "review",
        "requirements", "build", "android", "agent",
    }
    assert not any("docs/results/" in r["source"] or "/refer/" in r["source"] for r in rows)

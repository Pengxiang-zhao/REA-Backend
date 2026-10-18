"""Discover backend requirements, package services, and validate them with the client."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from . import __version__


def export_workspace(output: Path) -> dict:
    """Copy the packaged method without modifying global agent configuration."""
    from .resource_files import resource_root
    output = output.resolve()
    if output.exists():
        raise ValueError(f"Output already exists; choose a new workspace: {output}")
    shutil.copytree(resource_root(), output)
    return {"status": "exported", "output": str(output),
            "skill": str(output / "skills/rea-backend/SKILL.md"),
            "config_template": str(output / "templates/srs-inputs.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"rea-backend {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("init-workspace", help="Export bundled skill, method docs, and templates to a new directory")
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("srs-explore", help="Start v3 discovery with scoped contracts and evidence-bound flow boundaries")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("android-run", help="Replay explicit emulator steps, own the local backend and retain fresh evidence")
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--adb", type=Path)
    p = commands.add_parser("android-doctor", help="Inspect explicit emulator/APK identity and development tools without resetting state")
    p.add_argument("--serial", required=True)
    p.add_argument("--avd", required=True)
    p.add_argument("--package", required=True)
    p.add_argument("--activity", required=True)
    p.add_argument("--apk-sha256")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--adb", type=Path)
    p = commands.add_parser("srs-analysis-update", help="Record analysis items with revision checking; existing items are retained")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--analysis", type=Path, required=True)
    p.add_argument("--updates", type=Path, required=True, help="JSON array of complete work-item updates")
    p.add_argument("--expected-revision", type=int, required=True)
    p = commands.add_parser("srs-analysis-check", help="Check discovered work items, evidence and unresolved questions")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--analysis", type=Path, required=True)
    p.add_argument("--require-settled", action="store_true")
    p = commands.add_parser("srs-init", help="Snapshot allowed inputs and prepare an app-wide SRS scaffold (no model call)")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--template", type=Path)
    p.add_argument("--analysis", type=Path, help="Settled exploration directory to freeze with the SRS")
    p.add_argument("--method-manifest", type=Path, help="Explicit method file manifest instead of the packaged default")
    p = commands.add_parser("srs-check", help="Check an app-wide SRS index, source evidence and optional independent review")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--require-reviewed", action="store_true")
    p = commands.add_parser("srs-build", help="Bind agent-written backend code to a reviewed SRS and package its declared scope")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--srs", type=Path, required=True)
    p.add_argument("--implementation", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("srs-validate-build", help="Run explicit checks on an isolated, hash-verified build copy and retain failures")
    p.add_argument("--build", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("prepare", help="Prepare version-bound APK evidence for requirements discovery")
    p.add_argument("--apk", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--decoded", type=Path, help="Reuse a previously inventoried decode tree")
    p.add_argument("--decode-record", "--rebuild-record", dest="rebuild_record", type=Path,
                   help="Previous prepare output containing the APK identity and decoded inventory")
    p.add_argument("--rea-evidence", type=Path, help="Reuse retained analysis responses for this exact APK")
    p.add_argument("--rea-requests", type=Path, help="Additional focused analysis requests as JSONL")
    p.add_argument("--apktool", help="Executable used to decode a fresh APK")
    p = commands.add_parser("rea-session", help="Collect additional APK evidence through the installed analysis provider")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--requests", type=Path, help="JSONL requests; interactive stdin when omitted")
    p = commands.add_parser("profile", help="Inspect APK packaging and extraction hints")
    p.add_argument("--apk", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "srs-explore":
            from .analysis import initialize_analysis
            result = initialize_analysis(args.config, args.out)
        elif args.command == "android-run":
            from .android_run import run_android
            result = run_android(args.build, args.plan, args.out, adb=args.adb)
        elif args.command == "android-doctor":
            from .android_run import android_doctor
            result = android_doctor(adb=args.adb, serial=args.serial, avd=args.avd, package=args.package,
                                    activity=args.activity, out=args.out, apk_sha256=args.apk_sha256)
        elif args.command == "srs-analysis-update":
            from .analysis import update_analysis
            updates = json.loads(args.updates.read_text(encoding="utf-8"))
            result = update_analysis(args.config, args.analysis, updates, args.expected_revision)
        elif args.command == "srs-analysis-check":
            from .analysis import check_analysis
            result = check_analysis(args.config, args.analysis, args.require_settled)
        elif args.command == "srs-init":
            from .srs import initialize_srs
            result = initialize_srs(args.config, args.out, args.template,
                                    analysis=args.analysis, method_manifest=args.method_manifest)
        elif args.command == "srs-check":
            from .srs import check_srs
            result = check_srs(args.config, args.bundle, args.require_reviewed)
        elif args.command == "srs-build":
            from .srs_build import build_from_srs
            result = build_from_srs(args.config, args.srs, args.implementation, args.out)
        elif args.command == "srs-validate-build":
            from .build_validation import validate_build
            result = validate_build(args.build, args.plan, args.out)
        elif args.command == "init-workspace":
            result = export_workspace(args.out)
        elif args.command == "prepare":
            from .preparation import prepare
            result = prepare(args.apk, args.out, decoded=args.decoded, rebuild_record=args.rebuild_record,
                             rea_evidence=args.rea_evidence, rea_requests=args.rea_requests, apktool=args.apktool)
        elif args.command == "rea-session":
            bridge = Path(__file__).with_name("rea_android_session.mjs")
            argv = ["node", str(bridge), str(args.out.resolve())]
            if args.requests:
                argv += ["--requests", str(args.requests.resolve(strict=True))]
            code = subprocess.run(argv, check=False).returncode
            if code:
                parser.exit(1, f"Analysis session failed (exit {code}); inspect {args.out}.\n")
            return
        elif args.command == "profile":
            from .capabilities import profile_apk
            from .preparation import fresh_directory, write_json
            output = fresh_directory(args.out)
            result = profile_apk(args.apk)
            write_json(output / "capabilities.json", result)
        else:
            parser.error("Unknown command")
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"rea-backend: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") in {"error", "failed"}:
        parser.exit(1)

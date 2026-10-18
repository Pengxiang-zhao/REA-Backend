"""APK artifact inventory, deliberately separate from runtime-support claims.

Only the ZIP directory and an optional already-extracted contract are inspected.
Archive entries are never extracted or read. Framework signatures are packaging
hints, not proof that a framework or networking stack is active at runtime.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
import zipfile


MAX_ENTRIES = 200_000
MAX_EVIDENCE_PATHS = 100
ROOT_DEX = re.compile(r'^classes(?:\d+)?\.dex$')
NATIVE = re.compile(r'^lib/([^/]+)/([^/]+\.so)$')
JS_BUNDLE_PATHS = frozenset({'assets/index.android.bundle', 'assets/index.bundle', 'assets/main.jsbundle'})
WEB_EXTENSIONS = frozenset({'.html', '.htm', '.js', '.mjs', '.css'})


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _paths(paths):
    ordered = sorted(set(paths))
    return {'path_count': len(ordered), 'paths': ordered[:MAX_EVIDENCE_PATHS],
            'paths_truncated': len(ordered) > MAX_EVIDENCE_PATHS}


def _hint(kind, paths, interpretation, *, status='artifact-hint'):
    return {'kind': kind, 'status': status, 'evidence': _paths(paths),
            'interpretation': interpretation, 'runtime_use_verified': False}


def _support():
    return {
        'validated_extraction': [],
        'implemented_extraction': [{'lane': 'retrofit-annotations',
                                    'validation_scope': 'synthetic-regression-tests',
                                    'generalization_validated': False}],
        'unvalidated_lanes': [
            {'lane': 'ktor', 'status': 'unvalidated', 'next_step': 'A separate contract extraction lane is required.'},
            {'lane': 'flutter', 'status': 'unvalidated',
             'next_step': 'Use a separate extraction lane; upstream REA includes Flutter analysis capabilities.'},
            {'lane': 'react-native', 'status': 'unvalidated',
             'next_step': 'A JavaScript/Hermes and native-bridge extraction lane is required.'},
            {'lane': 'native-only', 'status': 'unvalidated',
             'next_step': 'Native analysis and runtime evidence are required; directory names cannot establish native-only execution.'},
        ],
        'scope': 'The standalone package has synthetic regression coverage; real-app runs remain pending. '
                 'These declarations do not limit upstream REA capabilities.',
    }


def profile_apk(apk: Path, contract: dict | None = None) -> dict:
    """Return a deterministic directory profile or an explicit structured error.

    A profiled result means the ZIP directory was readable, not that the APK was
    decoded, signed, installable, exercised or semantically reconstructed. APK
    identity is a streamed whole-file SHA256. Optional contract counts require
    the same hash and never yield precision/recall without an independent oracle.
    """
    apk = Path(apk).resolve()
    result = {
        'schema_version': 1, 'status': 'error', 'apk_path': str(apk), 'apk_sha256': None,
        'zip_count': None, 'zip_file_count': None, 'dex_count': None, 'root_dex_count': None,
        'native_abis': [], 'hints': [], 'packaging': None, 'contract_summary': None,
        'runtime_network_stack': None, 'metrics': {'precision': None, 'recall': None},
        'pipeline_support': _support(),
        'limitations': [
            'Only ZIP directory metadata is inspected; archive entry contents are not read or extracted.',
            'DEX/native binaries, binary manifest, signatures, payload CRCs and installation identity are not validated.',
            'Artifact signatures do not prove active UI technology, networking stack or backend compatibility.',
            'A standalone APK may be a split; base presence and installation-set completeness remain unknown.',
            'Contract declaration/DTO counts and artifact hints do not establish precision, recall or API support rate.',
        ],
    }

    def fail(code, message):
        result['status'] = 'error'
        result['error'] = {'code': code, 'message': message}
        return result

    if not apk.is_file():
        return fail('not-a-file', f'APK path is not a readable file: {apk}')
    try:
        result['apk_sha256'] = _hash_file(apk)
        with zipfile.ZipFile(apk) as archive:
            entries = archive.infolist()
        result['zip_count'] = len(entries)
        if len(entries) > MAX_ENTRIES:
            return fail('directory-limit-exceeded', f'ZIP has more than {MAX_ENTRIES} directory entries.')
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError) as error:
        return fail('unreadable-zip', f'ZIP directory could not be parsed: {type(error).__name__}: {error}')

    files = [entry for entry in entries if not entry.is_dir()]
    result['zip_file_count'] = len(files)
    names = []
    unsafe = []
    for entry in files:
        name = entry.filename
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:
            unsafe.append(name)
        else:
            names.append(name)
    unique = sorted(set(names))
    result['directory_anomalies'] = {
        'unsafe_paths': _paths(unsafe),
        'duplicate_path_count': len(names) - len(unique),
        'encrypted_entry_count': sum(bool(entry.flag_bits & 1) for entry in files),
    }
    dex = [name for name in unique if name.endswith('.dex')]
    root_dex = [name for name in dex if ROOT_DEX.fullmatch(name)]
    native = [(name, NATIVE.fullmatch(name)) for name in unique if NATIVE.fullmatch(name)]
    native_paths = [name for name, _ in native]
    result.update(dex_count=len(dex), root_dex_count=len(root_dex),
                  dex_evidence=_paths(dex),
                  native_abis=sorted({match.group(1) for _, match in native}),
                  native_abi_evidence=[{'abi_hint': abi,
                                        'evidence': _paths(name for name, match in native if match.group(1) == abi)}
                                       for abi in sorted({match.group(1) for _, match in native})])
    nested_apks = [name for name in unique if name.endswith('.apk')]
    has_manifest = 'AndroidManifest.xml' in unique
    result['packaging'] = {
        'layout': 'single-apk-or-split' if has_manifest else 'nested-apk-container' if nested_apks else 'unknown',
        'manifest_path_present': has_manifest, 'nested_apks': _paths(nested_apks),
        'base_name_candidates': _paths(name for name in nested_apks
                                       if PurePosixPath(name).name in {'base.apk', 'base-master.apk'}),
        'base_presence': 'unknown', 'installation_set_completeness': 'unknown',
        'nested_archives_inspected': False,
    }
    if not has_manifest and not nested_apks:
        return fail('apk-manifest-not-found', 'Readable ZIP has neither a root AndroidManifest.xml nor nested APK candidates.')

    hints = result['hints']
    if dex:
        hints.append(_hint('dex-artifacts', dex, 'DEX-named files are packaged; their contents and networking APIs are uninspected.'))
    if len(root_dex) > 1:
        hints.append(_hint('multidex-layout', root_dex, 'Multiple conventional root DEX paths are present.'))
    if native_paths:
        hints.append(_hint('native-libraries', native_paths, 'lib/<ABI>/*.so paths provide ABI layout hints; ELF architecture and execution are unverified.'))
    flutter_app = [name for name, match in native if match.group(2) == 'libapp.so']
    flutter_assets = [name for name in unique if name.startswith('assets/flutter_assets/')]
    if flutter_app and flutter_assets:
        hints.append(_hint('flutter-artifacts', flutter_app + flutter_assets,
                           'Both libapp.so and assets/flutter_assets are present; a separate, currently unvalidated extraction lane is needed.'))
    elif flutter_app or flutter_assets:
        hints.append(_hint('flutter-signature-incomplete', flutter_app + flutter_assets,
                           'Only part of the paired packaging signature is present; framework use cannot be concluded.',
                           status='incomplete-artifact-signature'))
    js_bundles = [name for name in unique if name in JS_BUNDLE_PATHS or
                  (name.startswith('assets/') and PurePosixPath(name).suffix == '.jsbundle')]
    rn_native = [name for name, match in native if match.group(2) in {'libreactnative.so', 'libreactnativejni.so'}]
    if js_bundles:
        hints.append(_hint('javascript-bundle-candidates', js_bundles,
                           'Conventional bundle paths are present; JavaScript versus bytecode and runtime use are unverified.'))
    if js_bundles and rn_native:
        hints.append(_hint('react-native-artifacts', js_bundles + rn_native,
                           'Conventional JS bundle paths and React Native library paths coexist; active execution and networking remain unknown.'))
    elif rn_native:
        hints.append(_hint('react-native-signature-incomplete', rn_native,
                           'React Native-named native libraries are present without a recognized bundle path; no active framework inference is made.',
                           status='incomplete-artifact-signature'))
    web = [name for name in unique if (name.startswith('assets/') or name.startswith('res/raw/'))
           and PurePosixPath(name).suffix.lower() in WEB_EXTENSIONS]
    if web:
        hints.append(_hint('web-assets', web, 'Packaged HTML/JS/CSS assets do not prove a WebView interface or an active network stack.'))
    if native_paths and not root_dex:
        hints.append(_hint('native-without-root-dex', native_paths,
                           'Native libraries exist without conventional root DEX paths; native-only execution is unproven and needs another analysis lane.'))
    if nested_apks:
        hints.append(_hint('nested-apk-artifacts', nested_apks,
                           'Nested APK paths may represent an installation set; the base and required splits are not validated.'))

    if contract is not None:
        if not isinstance(contract, dict) or contract.get('apk_sha256') != result['apk_sha256']:
            return fail('contract-binding-mismatch', 'Contract must be bound to the exact APK SHA256 being profiled.')
        if not all(isinstance(contract.get(key), list) for key in ('endpoints', 'models')):
            return fail('invalid-contract', 'Contract endpoints and models must be lists.')
        result['contract_summary'] = {
            'apk_binding': 'verified', 'endpoint_declaration_count': len(contract['endpoints']),
            'model_candidate_count': len(contract['models']),
            'precision': None, 'recall': None,
            'scope': 'Counts from the supplied contract; no independent completeness or correctness oracle.',
        }
    result['status'] = 'profiled'
    return result

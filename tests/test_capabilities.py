"""Directory-only artifact hints must not become runtime-support claims."""
import hashlib
import zipfile

from rea_backend.capabilities import profile_apk


def apk_fixture(tmp_path, names):
    apk = tmp_path / 'synthetic.apk'
    with zipfile.ZipFile(apk, 'w') as archive:
        for name in names:
            archive.writestr(name, b'Synthetic test payload, not executable code')
    return apk


def test_mixed_framework_artifacts_are_hints_not_validated_support(tmp_path, monkeypatch):
    apk = apk_fixture(tmp_path, [
        'AndroidManifest.xml', 'classes2.dex', 'classes.dex',
        'lib/arm64-v8a/libapp.so', 'assets/flutter_assets/AssetManifest.bin',
        'lib/x86_64/libreactnative.so', 'assets/index.android.bundle',
        'assets/site/index.html', 'assets/site/main.css',
    ])
    # Hashing the APK and parsing its directory must never read archive payloads.
    monkeypatch.setattr(zipfile.ZipFile, 'open', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('entry read')))
    result = profile_apk(apk)
    assert result == profile_apk(apk)
    assert result['status'] == 'profiled'
    assert result['zip_count'] == 9
    assert (result['dex_count'], result['root_dex_count']) == (2, 2)
    assert result['native_abis'] == ['arm64-v8a', 'x86_64']
    hints = {hint['kind']: hint for hint in result['hints']}
    assert {'flutter-artifacts', 'react-native-artifacts', 'web-assets', 'multidex-layout'} <= hints.keys()
    assert all(not hint['runtime_use_verified'] for hint in hints.values())
    assert all(hint['evidence']['paths'] == sorted(hint['evidence']['paths']) for hint in hints.values())
    assert result['runtime_network_stack'] is None
    assert result['metrics'] == {'precision': None, 'recall': None}
    assert result['pipeline_support']['validated_extraction'] == []
    assert result['pipeline_support']['implemented_extraction'] == [
        {'lane': 'retrofit-annotations', 'validation_scope': 'synthetic-regression-tests',
         'generalization_validated': False}]
    lanes = result['pipeline_support']['unvalidated_lanes']
    assert {lane['lane'] for lane in lanes} == {'ktor', 'flutter', 'react-native', 'native-only'}
    assert all(lane['status'] == 'unvalidated' for lane in lanes)
    assert 'upstream REA includes Flutter' in next(lane['next_step'] for lane in lanes if lane['lane'] == 'flutter')


def test_malformed_zip_returns_explicit_error(tmp_path):
    apk = tmp_path / 'bad.apk'
    apk.write_bytes(b'not a ZIP file')
    result = profile_apk(apk)
    assert result['status'] == 'error'
    assert result['error']['code'] == 'unreadable-zip'
    assert result['apk_sha256'] == hashlib.sha256(apk.read_bytes()).hexdigest()
    assert result['zip_count'] is None


def test_native_abi_and_bundle_paths_do_not_alone_identify_framework(tmp_path):
    apk = apk_fixture(tmp_path, ['AndroidManifest.xml', 'lib/armeabi-v7a/libcustom.so',
                                 'assets/index.android.bundle', 'lib/x86/libreactnative-optional.so',
                                 'assets/docs/reactnative-guide.txt'])
    result = profile_apk(apk)
    assert result['native_abis'] == ['armeabi-v7a', 'x86']
    kinds = {hint['kind'] for hint in result['hints']}
    assert 'javascript-bundle-candidates' in kinds
    assert 'native-without-root-dex' in kinds
    assert 'react-native-artifacts' not in kinds
    assert 'flutter-artifacts' not in kinds


def test_single_library_is_only_an_incomplete_signature(tmp_path):
    apk = apk_fixture(tmp_path, ['AndroidManifest.xml', 'classes.dex',
                                 'lib/arm64-v8a/libapp.so', 'lib/arm64-v8a/libreactnative.so'])
    hints = {h['kind']: h for h in profile_apk(apk)['hints']}
    assert hints['flutter-signature-incomplete']['status'] == 'incomplete-artifact-signature'
    assert hints['react-native-signature-incomplete']['status'] == 'incomplete-artifact-signature'
    assert 'flutter-artifacts' not in hints
    assert 'react-native-artifacts' not in hints


def test_nested_splits_leave_base_presence_and_completeness_unknown(tmp_path):
    apk = apk_fixture(tmp_path, ['splits/config.arm64.apk', 'splits/config.en.apk'])
    result = profile_apk(apk)
    assert result['status'] == 'profiled'
    assert result['packaging']['layout'] == 'nested-apk-container'
    assert result['packaging']['base_presence'] == 'unknown'
    assert result['packaging']['installation_set_completeness'] == 'unknown'
    assert result['packaging']['nested_archives_inspected'] is False
    assert result['packaging']['base_name_candidates']['path_count'] == 0


def test_unrelated_zip_is_not_silent_apk_success(tmp_path):
    apk = apk_fixture(tmp_path, ['readme.txt'])
    result = profile_apk(apk)
    assert result['status'] == 'error'
    assert result['error']['code'] == 'apk-manifest-not-found'


def test_contract_counts_require_exact_apk_binding_and_do_not_measure_precision(tmp_path):
    apk = apk_fixture(tmp_path, ['AndroidManifest.xml', 'classes.dex'])
    sha = hashlib.sha256(apk.read_bytes()).hexdigest()
    contract = {'apk_sha256': sha, 'endpoints': [{}, {}], 'models': [{}]}
    result = profile_apk(apk, contract)
    assert result['contract_summary']['endpoint_declaration_count'] == 2
    assert result['contract_summary']['model_candidate_count'] == 1
    assert result['contract_summary']['precision'] is None
    assert result['contract_summary']['recall'] is None
    contract['apk_sha256'] = '0' * 64
    assert profile_apk(apk, contract)['error']['code'] == 'contract-binding-mismatch'


def test_missing_apk_and_unsafe_entry_paths_are_explicit(tmp_path):
    assert profile_apk(tmp_path / 'missing.apk')['error']['code'] == 'not-a-file'
    apk = apk_fixture(tmp_path, ['AndroidManifest.xml', '../lib/x86/libapp.so',
                                 '/lib/arm64-v8a/libreactnative.so'])
    result = profile_apk(apk)
    assert result['directory_anomalies']['unsafe_paths']['path_count'] == 2
    assert result['native_abis'] == []

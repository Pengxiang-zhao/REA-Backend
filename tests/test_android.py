"""Identity and mutation fences for AVD checkpoints; no device is used."""
import json
from pathlib import Path
import subprocess

import pytest

from rea_backend import android


HASH = 'a' * 64


class FakeAdb:
    def __init__(self):
        self.calls = []
        self.avd = 'rea_backend_test'
        self.hash = HASH
        self.fingerprint = 'test/system/build'
        self.snapshots = set()
        self.running = True
        self.ko = None
        self.after_load_hash = None
        self.split = False
        self.apk_path = '/data/app/~~HVP+Y=w-/org.example.app-QX_Ab==/base.apk'

    def __call__(self, argv, *, capture_output, timeout, check):
        assert argv[:3] == ['/test/adb', '-s', 'emulator-5582']
        assert capture_output and timeout > 0
        args = tuple(argv[3:])
        self.calls.append(args)
        output, status = b'', 0
        if args == ('get-state',):
            output = b'device\n'
        elif args == ('emu', 'avd', 'name'):
            output = (self.avd + '\r\nOK\r\n').encode()
        elif args == ('shell', 'getprop', 'ro.build.fingerprint'):
            output = (self.fingerprint + '\n').encode()
        elif args == ('shell', 'pm', 'path', 'org.example.app'):
            output = ('package:' + self.apk_path + '\n').encode()
            if self.split:
                output += b'package:/data/app/test/split_config.apk\n'
        elif args == ('shell', 'sha256sum', self.apk_path):
            output = (self.hash + '  ' + self.apk_path + '\n').encode()
        elif args == ('shell', 'am', 'force-stop', 'org.example.app'):
            self.running = False
        elif args == ('shell', 'pidof', 'org.example.app'):
            output, status = (b'123\n', 0) if self.running else (b'', 1)
        elif args == ('emu', 'avd', 'snapshot', 'list'):
            output = ('List of snapshots present on all disks:\r\n'
                      'ID        TAG                 VM SIZE                DATE       VM CLOCK\r\n' +
                      ''.join(f'--        {name}    74M 2026-10-16 15:11:45   00:42:42.840\r\n'
                              for name in sorted(self.snapshots)) + 'OK\r\n').encode()
        elif args[:4] == ('emu', 'avd', 'snapshot', 'save'):
            if self.ko == 'save':
                output = b'KO: snapshot save failed\r\n'
            else:
                self.snapshots.add(args[4])
                output = b'OK\r\n'
        elif args[:4] == ('emu', 'avd', 'snapshot', 'load'):
            if self.ko == 'load':
                output = b'KO: snapshot load failed\r\n'
            else:
                if self.after_load_hash:
                    self.hash = self.after_load_hash
                output = b'OK\r\n'
        elif args == ('wait-for-device',) or args[0] == 'reverse':
            pass
        else:
            raise AssertionError(args)
        result = subprocess.CompletedProcess(argv, status, stdout=output, stderr=b'')
        if check and status:
            raise subprocess.CalledProcessError(status, argv, output=output, stderr=b'')
        return result

    @property
    def mutations(self):
        return [c for c in self.calls if c[:3] == ('shell', 'am', 'force-stop')
                or c[:4] in {('emu', 'avd', 'snapshot', 'save'), ('emu', 'avd', 'snapshot', 'load')}
                or c[0] == 'reverse']


@pytest.fixture
def adb(monkeypatch):
    fake = FakeAdb()
    monkeypatch.setattr(android.subprocess, 'run', fake)
    return fake


@pytest.fixture
def device():
    return android.AndroidDevice(Path('/test/adb'), 'emulator-5582', 'rea_backend_test',
                                 'org.example.app', '.MainActivity')


def checkpoint(device, tmp_path):
    path = tmp_path / 'checkpoint'
    device.save_checkpoint('rb-test', path)
    return path


def test_explicit_emulator_and_matching_avd_are_required(adb, device, tmp_path):
    with pytest.raises(ValueError, match='explicit emulator'):
        android.AndroidDevice(Path('/test/adb'), 'usb-device', 'rea_backend_test', 'org.example.app', '.Main')
    adb.avd = 'someone_else'
    with pytest.raises(android.AndroidError, match='different AVD'):
        device.save_checkpoint('rb-test', tmp_path / 'out')
    assert not adb.mutations


def test_identity_binds_installed_single_apk_and_system(adb, device):
    identity = device.identity()
    assert identity['apk_sha256'] == HASH
    assert identity['fingerprint'] == 'test/system/build'
    assert identity['serial'] == 'emulator-5582'
    assert identity['apk_path'] == adb.apk_path
    adb.split = True
    with pytest.raises(android.AndroidError, match='exactly one'):
        device.identity()


def test_identity_rejects_device_path_with_shell_syntax(adb, device):
    adb.apk_path = '/data/app/$(touch unsafe)/base.apk'
    with pytest.raises(android.AndroidError, match='safe absolute'):
        device.identity()
    assert not any(call[:2] == ('shell', 'sha256sum') for call in adb.calls)


def test_save_and_restore_leave_app_stopped(adb, device, tmp_path):
    path = checkpoint(device, tmp_path)
    manifest = json.loads((path / 'manifest.json').read_text())
    assert manifest['app_force_stopped'] is True
    assert manifest['identity']['apk_sha256'] == HASH
    adb.running = True
    restored = device.restore_checkpoint(path)
    assert restored['app_force_stopped'] and not adb.running
    actions = adb.mutations
    assert actions.index(('shell', 'am', 'force-stop', 'org.example.app')) < actions.index(
        ('emu', 'avd', 'snapshot', 'save', 'rb-test'))


def test_save_refuses_existing_snapshot_or_output_before_mutation(adb, device, tmp_path):
    adb.snapshots.add('rb-existing')
    with pytest.raises(android.AndroidError, match='already exists'):
        device.save_checkpoint('rb-existing', tmp_path / 'out')
    assert not (tmp_path / 'out').exists() and not adb.mutations
    out = tmp_path / 'occupied'
    out.mkdir()
    with pytest.raises(ValueError, match='already exists'):
        device.save_checkpoint('rb-new', out)
    assert not adb.mutations


@pytest.mark.parametrize('operation', ['save', 'load'])
def test_console_ko_is_failure_even_with_exit_zero(adb, device, tmp_path, operation):
    if operation == 'load':
        path = checkpoint(device, tmp_path)
    adb.ko = operation
    with pytest.raises(android.AndroidError, match='did not confirm'):
        if operation == 'save':
            device.save_checkpoint('rb-test', tmp_path / 'failed')
        else:
            device.restore_checkpoint(path)
    if operation == 'save':
        assert not (tmp_path / 'failed' / 'manifest.json').exists()
        assert (tmp_path / 'failed' / 'failure.json').exists()


@pytest.mark.parametrize('field,value', [('hash', 'c' * 64), ('fingerprint', 'different/system')])
def test_restore_refuses_changed_identity_before_mutation(adb, device, tmp_path, field, value):
    path = checkpoint(device, tmp_path)
    adb.calls.clear()
    setattr(adb, field, value)
    with pytest.raises(android.AndroidError, match='identity mismatch'):
        device.restore_checkpoint(path)
    assert not adb.mutations


def test_restore_checks_identity_again_after_loading(adb, device, tmp_path):
    path = checkpoint(device, tmp_path)
    adb.after_load_hash = 'd' * 64
    with pytest.raises(android.AndroidError, match='apk_sha256'):
        device.restore_checkpoint(path)
    assert not adb.running

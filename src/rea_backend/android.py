"""Identity-bound checkpoints for one explicitly selected Android Emulator.

An emulator snapshot restores the whole selected AVD. It is not a portable or
app-only reset. Callers must reserve this AVD while checkpoint operations run;
the app is intentionally left force-stopped.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time


class AndroidError(RuntimeError):
    """The selected device, checkpoint, or reset could not be verified."""


_IDENTITY_KEYS = ('serial', 'avd', 'package', 'fingerprint', 'apk_sha256')
_SHA256 = re.compile(r'[0-9a-f]{64}')
_SNAPSHOT_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,95}')


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def _fresh_output(path: Path) -> Path:
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise ValueError('Output already exists; choose a new directory')
    return path


def _text(process: subprocess.CompletedProcess) -> str:
    return process.stdout.decode('utf-8', errors='strict').strip()


class AndroidDevice:
    def __init__(self, adb: Path, serial: str, avd: str, package: str, activity: str):
        if not re.fullmatch(r'emulator-[0-9]+', serial):
            raise ValueError('An explicit emulator-<port> serial is required')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', avd):
            raise ValueError('An explicit AVD name is required')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+', package):
            raise ValueError('Invalid Android package')
        if not isinstance(activity, str) or not activity or not re.fullmatch(r'[A-Za-z0-9_.$/]+', activity):
            raise ValueError('Invalid Android activity')
        self.adb, self.serial, self.avd = Path(adb), serial, avd
        self.package, self.activity = package, activity

    def run(self, *args: str, timeout: float = 30, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run([str(self.adb), '-s', self.serial, *map(str, args)],
                              capture_output=True, timeout=timeout, check=check)

    def _emu(self, *args: str, timeout: float = 45) -> str:
        result = self.run('emu', *args, timeout=timeout)
        output = _text(result)
        combined = output + '\n' + result.stderr.decode('utf-8', errors='replace')
        if re.search(r'(?m)^\s*KO(?:[:\s]|$)', combined) or not re.search(r'(?m)^OK\s*$', output):
            raise AndroidError('Emulator console did not confirm success')
        return output

    def verify(self) -> dict:
        # Recheck even after construction, and never use adb's implicit device.
        if not re.fullmatch(r'emulator-[0-9]+', self.serial):
            raise AndroidError('Refusing a non-emulator serial')
        if _text(self.run('get-state')) != 'device':
            raise AndroidError('Selected emulator is not ready')
        lines = [line.strip() for line in self._emu('avd', 'name').splitlines() if line.strip() != 'OK']
        if lines != [self.avd]:
            raise AndroidError('Selected emulator has a different AVD name')
        return {'serial': self.serial, 'avd': self.avd}

    def identity(self) -> dict:
        self.verify()
        fingerprint = _text(self.run('shell', 'getprop', 'ro.build.fingerprint'))
        if not fingerprint or '\n' in fingerprint or '\r' in fingerprint:
            raise AndroidError('Missing or invalid Android build fingerprint')
        lines = _text(self.run('shell', 'pm', 'path', self.package)).splitlines()
        if len(lines) != 1 or not lines[0].startswith('package:'):
            raise AndroidError('Checkpoint requires exactly one installed base APK; splits are not accepted')
        apk_path = lines[0][len('package:'):]
        # adb shell joins arguments; restrict this device-provided path before use.
        if not re.fullmatch(r'/[A-Za-z0-9_./=+@,~-]+/base\.apk', apk_path):
            raise AndroidError('Installed APK is not a safe absolute base.apk path')
        hashed = _text(self.run('shell', 'sha256sum', apk_path)).split()
        if len(hashed) != 2 or not _SHA256.fullmatch(hashed[0]) or hashed[1] != apk_path:
            raise AndroidError('Could not verify installed APK SHA-256')
        return {'serial': self.serial, 'avd': self.avd, 'package': self.package,
                'activity': self.activity, 'fingerprint': fingerprint,
                'apk_sha256': hashed[0], 'apk_path': apk_path}

    def _assert_stopped(self) -> None:
        result = self.run('shell', 'pidof', self.package, check=False)
        if result.returncode not in (0, 1) or result.stdout.strip() or result.stderr.strip():
            raise AndroidError('App process is still present or process check failed')

    def force_stop(self) -> None:
        self.verify()
        self.run('shell', 'am', 'force-stop', self.package)
        self._assert_stopped()

    def _snapshots(self) -> set[str]:
        output = self._emu('avd', 'snapshot', 'list')
        names = set()
        for raw in output.splitlines():
            line = raw.strip()
            if (not line or line == 'OK' or line.startswith('List of snapshots')
                    or ('TAG' in line and 'VM SIZE' in line)
                    or re.fullmatch(r'(?:There (?:is|are) )?[Nn]o snapshots?(?: available)?\.?', line)):
                continue
            match = re.match(r'(?:--|\d+)\s+(\S+)\s+', line)
            if not match:
                raise AndroidError('Unrecognized emulator snapshot inventory; refusing to guess')
            names.add(match[1])
        return names

    def save_checkpoint(self, name: str, out: Path) -> dict:
        if not _SNAPSHOT_NAME.fullmatch(name):
            raise ValueError('Invalid snapshot name')
        out = _fresh_output(out)
        identity = self.identity()
        if name in self._snapshots():
            raise AndroidError('Snapshot name already exists; refusing to overwrite')
        out.mkdir(parents=True)
        started = time.monotonic()
        try:
            self.force_stop()
            self._emu('avd', 'snapshot', 'save', name)
            if name not in self._snapshots():
                raise AndroidError('Saved snapshot is missing from emulator inventory')
            after = self.identity()
            self._same_identity(identity, after)
            self._assert_stopped()
            record = {'schema_version': 1, 'kind': 'android-avd-checkpoint', 'name': name,
                      'identity': after, 'app_force_stopped': True,
                      'created_at': datetime.now(timezone.utc).isoformat(),
                      'seconds': round(time.monotonic() - started, 3),
                      'scope': 'Whole selected AVD snapshot; app left force-stopped'}
            _write_json(out / 'manifest.json', record)
            return record
        except Exception as error:
            _write_json(out / 'failure.json', {'complete': False, 'stage': 'save_checkpoint',
                        'error_type': type(error).__name__, 'name': name})
            raise

    @staticmethod
    def _same_identity(expected: dict, actual: dict) -> None:
        for key in _IDENTITY_KEYS:
            if not expected.get(key) or expected[key] != actual.get(key):
                raise AndroidError(f'Checkpoint identity mismatch: {key}')

    def _checkpoint(self, directory: Path) -> dict:
        record = json.loads((Path(directory) / 'manifest.json').read_text())
        if (record.get('schema_version') != 1 or record.get('kind') != 'android-avd-checkpoint'
                or record.get('app_force_stopped') is not True
                or not isinstance(record.get('name'), str) or not _SNAPSHOT_NAME.fullmatch(record['name'])
                or not isinstance(record.get('identity'), dict)):
            raise AndroidError('Invalid or incomplete checkpoint manifest')
        self._same_identity(record['identity'], self.identity())
        if record['name'] not in self._snapshots():
            raise AndroidError('Checkpoint snapshot is absent from this AVD')
        return record

    def restore_checkpoint(self, checkpoint_dir: Path) -> dict:
        started = time.monotonic()
        record = self._checkpoint(checkpoint_dir)  # All identity checks precede mutation.
        self.force_stop()
        self._emu('avd', 'snapshot', 'load', record['name'])
        self.run('wait-for-device', timeout=45)
        self.verify()
        self.force_stop()  # Restored RAM must not leave the app running.
        after = self.identity()
        self._same_identity(record['identity'], after)
        self._assert_stopped()
        return {'name': record['name'], 'identity': after, 'app_force_stopped': True,
                'seconds': round(time.monotonic() - started, 3)}

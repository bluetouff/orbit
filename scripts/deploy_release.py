#!/usr/bin/env python3
"""Guarded collector + frontend release, run by the administrator on the host.

Preserves provider environment, service configuration, timer and generated data.
Default: read-only checks. --apply and --rollback require root.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time

import deploy_front as front

INSTALL = Path('/opt/orbit')
SNAPSHOT = Path('/var/lib/orbit/orbit.json')
ENV_FILE = Path('/etc/orbit/orbit.env')
FILES = {'build_snapshot.py': 'build_snapshot.py', 'validate_snapshot.py': 'scripts/validate_snapshot.py'}
SERVICE = 'orbit-snapshot.service'
TIMER = 'orbit-snapshot.timer'


class CollectionNotReady(ValueError):
    """A valid snapshot has not yet received current crypto and xStocks data."""


def systemctl(*args):
    # Never print journal entries or environment values containing credentials.
    result = subprocess.run(['/usr/bin/systemctl', *args], capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise ValueError(f'systemctl {args[0]} failed (exit {result.returncode}); inspect on the host')
    return result.stdout.strip()


def property_value(unit, name):
    return systemctl('show', unit, '--property=' + name, '--value')


def installed(name):
    return front.target(INSTALL, name)


def read_installed(name):
    file = installed(name)
    return file.read_bytes() if file.exists() else None


def preflight(revision):
    if not revision or not front.SHA.fullmatch(revision) or front.git('rev-parse', 'HEAD') != revision:
        raise ValueError('Checkout must match the full requested revision')
    if front.git('status', '--porcelain'):
        raise ValueError('Checkout must be clean')
    if INSTALL.is_symlink() or not INSTALL.is_dir() or INSTALL.resolve() != INSTALL.absolute():
        raise ValueError('Expected existing collector directory')
    if not installed('build_snapshot.py').is_file():
        raise ValueError('Existing collector is missing')
    for file in [INSTALL, *(installed(name) for name in FILES)]:
        if file.exists() and (file.stat().st_uid != 0 or file.stat().st_mode & 0o022):
            raise ValueError('Collector must be root-owned and not group/world writable')
    expected = {'User': 'orbit', 'ProtectSystem': 'strict', 'NoNewPrivileges': 'yes',
                'ReadWritePaths': '/var/lib/orbit'}
    for name, value in expected.items():
        if property_value(SERVICE, name) != value:
            raise ValueError(f'Unexpected service {name}; inspect configuration before release')
    command = property_value(SERVICE, 'ExecStart')
    if 'argv[]=/usr/bin/python3 /opt/orbit/build_snapshot.py ;' not in command:
        raise ValueError('Unexpected collector command')
    if property_value(SERVICE, 'EnvironmentFiles') != '/etc/orbit/orbit.env (ignore_errors=yes)':
        raise ValueError('Unexpected provider environment path')
    if property_value(TIMER, 'ActiveState') != 'active':
        raise ValueError('Collector timer must already be active')
    if not SNAPSHOT.is_file() or SNAPSHOT.is_symlink():
        raise ValueError('Expected existing snapshot')
    front.preflight(front.WEB_ROOT)
    print('Preflight OK: clean revision, hardened service, active timer, public front and snapshot.')


def check_environment_paths():
    # Only check output paths; never print or copy provider configuration.
    values = {}
    if ENV_FILE.exists():
        if ENV_FILE.is_symlink():
            raise ValueError('Unexpected environment symlink')
        for line in ENV_FILE.read_text().splitlines():
            key, separator, value = line.partition('=')
            if separator and key.strip() in ('ORBIT_OUT_DIR', 'ORBIT_LOGO_DIR'):
                values[key.strip()] = value.strip().strip('"\'')
    # Unit-level Environment= overrides must obey the same output contract.
    for assignment in shlex.split(property_value(SERVICE, 'Environment')):
        key, separator, value = assignment.partition('=')
        if separator and key in ('ORBIT_OUT_DIR', 'ORBIT_LOGO_DIR'):
            values[key] = value
    for key, expected in [('ORBIT_OUT_DIR', '/var/lib/orbit'), ('ORBIT_LOGO_DIR', '/var/lib/orbit/logos')]:
        if key in values and values[key] != expected:
            raise ValueError(f'Unexpected {key}; inspect paths before release')


@contextlib.contextmanager
def paused_timer():
    systemctl('stop', TIMER)
    try:
        deadline = time.monotonic() + 60
        while property_value(SERVICE, 'ActiveState') in ('active', 'activating', 'deactivating'):
            if time.monotonic() >= deadline:
                raise ValueError('Collector still running; no files replaced')
            time.sleep(1)
        yield
    finally:
        try:
            # A restored legacy collector does not understand the cooldown file.
            # Do not let restarting its timer bypass a freshly received 429.
            wait_for_provider(0, maximum=1800)
        except Exception:
            print('Provider cooldown could not be safely completed. Timer remains paused; inspect the reported deadline before resuming it.', flush=True)
            raise
        systemctl('start', TIMER)


def create_backup(revision):
    backup = Path(tempfile.mkdtemp(prefix='collector-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + revision[:12] + '-', dir=front.BACKUPS))
    record = {'revision': revision, 'files': {}, 'front_backup': None}
    for name, source in FILES.items():
        old = read_installed(name)
        if old is not None:
            (backup / name).write_bytes(old)
        record['files'][name] = {'old': front.body_hash(old), 'new': front.digest((front.REPO / source).read_bytes())}
    save_record(backup, record)
    return backup, record


def save_record(backup, record):
    front.atomic_write(backup / 'collector.json', (json.dumps(record, indent=2) + '\n').encode())


def check_restore(backup, record):
    if set(record['files']) != set(FILES):
        raise ValueError('Unexpected collector rollback manifest')
    for name, hashes in record['files'].items():
        if front.body_hash(read_installed(name)) not in (hashes['old'], hashes['new']):
            raise ValueError('Newer or modified collector exists; refusing rollback')
        if hashes['old'] is not None and front.digest((backup / name).read_bytes()) != hashes['old']:
            raise ValueError('Collector backup integrity check failed')


def restore_collector(backup, record):
    check_restore(backup, record)
    for name, hashes in record['files'].items():
        if hashes['old'] is None:
            installed(name).unlink(missing_ok=True)
        else:
            front.atomic_write(installed(name), (backup / name).read_bytes())


def validate_collected(started):
    result = subprocess.run(['/usr/bin/python3', str(front.REPO / 'scripts/validate_snapshot.py'), str(SNAPSHOT)], capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Generated snapshot failed contract validation')
    data = json.loads(SNAPSHOT.read_text())
    generated = dt.datetime.fromisoformat(data['snapshot'].replace('Z', '+00:00'))
    if generated.timestamp() < started:
        raise CollectionNotReady('Collector did not produce a new snapshot')
    for name in ('coingecko_markets', 'coingecko_xstocks'):
        status = data.get('status', {}).get(name, {})
        stamp = dt.datetime.fromisoformat((status.get('fetched_at') or '').replace('Z', '+00:00'))
        age = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
        if status.get('ok') is not True or not -60 <= age <= 180:
            raise CollectionNotReady(f'{name} is unavailable or stale; rolling back')
    count = sum(c.get('asset_type') == 'xstock' for c in data['coins'])
    if not count:
        raise CollectionNotReady('No xStocks collected; rolling back')
    print(f'New snapshot valid: {len(data["coins"])} assets, {count} xStocks, both market feeds current.')


def provider_retry_at():
    # Private numeric transport state only; never read provider credentials here.
    try:
        fd = os.open(SNAPSHOT.parent / '.coingecko-rate-limit.json', os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return 0
    with os.fdopen(fd) as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError('Invalid provider cooldown state')
    state = json.loads(raw)
    value = state.get('retry_at') if isinstance(state, dict) else None
    if type(value) is not int or not 0 <= value <= 253402300799:
        raise ValueError('Invalid provider cooldown state')
    return value


def wait_for_provider(minimum, maximum=180):
    now = time.time()
    deadline = max(now + minimum, provider_retry_at())
    if deadline - now > maximum:
        stamp = dt.datetime.fromtimestamp(deadline, dt.timezone.utc).isoformat()
        raise ValueError(f'CoinGecko cooldown until {stamp}; deployment deferred without a new request')
    if deadline > now:
        print(f'Provider quiet period: {int(deadline - now) + 1}s, collector timer paused.', flush=True)
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(30, remaining))


def collect_for_release():
    # One collection after a quiet minute; at most one retry, only after a
    # recorded 429 cooldown. No retry for schema, auth or service failures.
    for attempt in range(2):
        # A failed category fetch is cached for up to 180s as well. Let that
        # cache expire before the sole retry, even if Retry-After was shorter.
        wait_for_provider(60 if attempt == 0 else 180)
        started = int(time.time())
        systemctl('start', SERVICE)
        try:
            validate_collected(started)
            return
        except CollectionNotReady:
            if attempt == 0 and provider_retry_at() > time.time():
                print('CoinGecko rate limited this collection; waiting for its cooldown before one retry.', flush=True)
                continue
            raise


def rollback(name):
    if Path(name).name != name or not name.startswith('collector-'):
        raise ValueError('Expected a collector backup name')
    backup = front.BACKUPS / name
    if backup.is_symlink() or backup.resolve().parent != front.BACKUPS.resolve():
        raise ValueError('Unexpected backup path')
    record = json.loads((backup / 'collector.json').read_text())
    check_restore(backup, record)
    with paused_timer():
        if record.get('front_backup'):
            front.run(argparse.Namespace(revision=None, apply=False, rollback=record['front_backup']))
        restore_collector(backup, record)
    print('Previous collector and front restored. Timer resumed; generated data retained.')


def run(args):
    if args.rollback:
        rollback(args.rollback)
        return
    preflight(args.revision)
    if not args.apply:
        print('Read-only preflight complete. --apply requires administrator activation.')
        return
    check_environment_paths()
    with paused_timer():
        backup, record = create_backup(args.revision)
        command = f'sudo python3 {shlex.quote(str(Path(__file__).resolve()))} --rollback {backup.name}'
        print('Full rollback: ' + command, flush=True)
        try:
            for name, source in FILES.items():
                if front.body_hash(read_installed(name)) != record['files'][name]['old']:
                    raise ValueError('Collector changed during deployment')
                front.atomic_write(installed(name), (front.REPO / source).read_bytes())
            collect_for_release()
            def remember_front(front_backup):
                # Persist the full recovery path before either HTML page changes.
                record['front_backup'] = front_backup.name
                save_record(backup, record)
            front.run(argparse.Namespace(revision=args.revision, apply=True, rollback=None), on_backup=remember_front)
        except BaseException:
            if record.get('front_backup'):
                front.run(argparse.Namespace(revision=None, apply=False, rollback=record['front_backup']))
            restore_collector(backup, record)
            print('Release failed: previous collector restored. Timer restart follows the provider cooldown check.', flush=True)
            raise
    print(f'Release LIVE: {args.revision}. Configuration and generated-data paths preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--apply', action='store_true')
    action.add_argument('--rollback')
    args = parser.parse_args()
    with contextlib.ExitStack() as stack:
        if args.apply or args.rollback:
            if os.geteuid() != 0:
                parser.error('Activation and rollback require sudo')
            if front.BACKUPS.is_symlink():
                parser.error('Backup root cannot be a symlink')
            front.BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
            lock = stack.enter_context((front.BACKUPS / '.deploy.lock').open('a'))
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(args)


if __name__ == '__main__':
    main()

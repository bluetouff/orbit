#!/usr/bin/env python3
"""Guarded collector + frontend release, run by the administrator on the host.

Preserves secrets and service hardening; optionally activates the free Demo profile.
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
FILES = {'build_snapshot.py': 'build_snapshot.py', 'validate_snapshot.py': 'scripts/validate_snapshot.py', 'collect_xstocks.py': None, 'collection.profile': None}
DEMO_PROFILE = b'demo-250-v1\n'
UNIT_DIR = Path('/etc/systemd/system')
KRAKEN_SERVICE = 'orbit-xstocks.service'
KRAKEN_TIMER = 'orbit-xstocks.timer'
UNITS = (KRAKEN_SERVICE, KRAKEN_TIMER)
SERVICE = 'orbit-snapshot.service'
TIMER = 'orbit-snapshot.timer'


class CollectionNotReady(ValueError):
    """A valid snapshot has not yet received current crypto data."""


def systemctl(*args, timeout=180):
    # Never print journal entries or environment values containing credentials.
    result = subprocess.run(['/usr/bin/systemctl', *args], capture_output=True, text=True, timeout=timeout)
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


def preflight(revision, demo=False):
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
    profile = read_installed('collection.profile')
    if profile not in (None, DEMO_PROFILE):
        raise ValueError('Unknown installed collection profile')
    front.preflight(front.WEB_ROOT, allow_unavailable=demo)
    print('Preflight OK: clean revision, hardened service, active timer, public front and snapshot.')


def check_environment_paths():
    # Only check output paths; never print or copy provider configuration.
    values = {}
    # EnvironmentFile takes precedence over unit-level Environment assignments.
    for assignment in shlex.split(property_value(SERVICE, 'Environment')):
        key, separator, value = assignment.partition('=')
        if separator and key in ('ORBIT_OUT_DIR', 'ORBIT_LOGO_DIR'):
            values[key] = value
    if ENV_FILE.exists():
        if ENV_FILE.is_symlink():
            raise ValueError('Unexpected environment symlink')
        for line in ENV_FILE.read_text().splitlines():
            key, separator, value = line.partition('=')
            if separator and key.strip() in ('ORBIT_OUT_DIR', 'ORBIT_LOGO_DIR'):
                values[key.strip()] = value.strip().strip('"\'')
    for key, expected in [('ORBIT_OUT_DIR', '/var/lib/orbit'), ('ORBIT_LOGO_DIR', '/var/lib/orbit/logos')]:
        if key in values and values[key] != expected:
            raise ValueError(f'Unexpected {key}; inspect paths before release')


def check_demo_key():
    # Presence only. Values are never logged, copied to backups or sent here.
    values = {}
    try:
        for item in shlex.split(property_value(SERVICE, 'Environment')):
            key, sep, value = item.partition('=')
            if sep:
                values[key] = value
        if ENV_FILE.is_symlink() or not ENV_FILE.is_file():
            raise ValueError()
        for line in ENV_FILE.read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() in ('CG_API_KEY', 'CG_API_TIER'):
                parts = shlex.split(value)
                values[key.strip()] = parts[0] if len(parts) == 1 else ''
        valid = bool(values.get('CG_API_KEY', '').strip()) and values.get('CG_API_TIER', 'none').lower() in ('none', 'demo')
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise ValueError('Expected an existing Demo key in the service environment; configuration unchanged')


def release_body(name, source, demo=False):
    if name == 'collection.profile':
        return DEMO_PROFILE if demo else read_installed(name)
    return (front.REPO / source).read_bytes() if source else None


@contextlib.contextmanager
def paused_timer(on_error=None):
    safe_resume = True
    systemctl('stop', TIMER)
    try:
        deadline = time.monotonic() + 60
        while property_value(SERVICE, 'ActiveState') in ('active', 'activating', 'deactivating'):
            if time.monotonic() >= deadline:
                raise ValueError('Collector still running; no files replaced')
            time.sleep(1)
        yield
    except BaseException:
        if on_error is not None:
            safe_resume = False
            on_error()
            safe_resume = True
        raise
    finally:
        if not safe_resume:
            print('Rollback incomplete. Crypto timer remains paused; inspect the backup before resuming.', flush=True)
        else:
            try:
                # A restored legacy collector does not understand the cooldown file.
                # Do not let its timer bypass a freshly received 429.
                wait_for_provider(0, maximum=1800)
            except Exception:
                print('Provider cooldown could not be safely completed. Timer remains paused; inspect the reported deadline before resuming it.', flush=True)
                raise
            systemctl('start', TIMER)


def create_backup(revision, demo=False):
    backup = Path(tempfile.mkdtemp(prefix='collector-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + revision[:12] + '-', dir=front.BACKUPS))
    record = {'revision': revision, 'files': {}, 'units': {}, 'front_backup': None}
    (backup / 'units').mkdir(mode=0o700)
    for name in UNITS:
        target = front.target(UNIT_DIR, name)
        old = target.read_bytes() if target.exists() else None
        if old is not None:
            if target.stat().st_uid != 0 or target.stat().st_mode & 0o022:
                raise ValueError('Kraken units must be root-owned and not writable by others')
            (backup / 'units' / name).write_bytes(old)
        record['units'][name] = {'old': front.body_hash(old), 'new': None,
            'enabled': old is not None and property_value(name, 'UnitFileState') == 'enabled',
            'active': old is not None and property_value(name, 'ActiveState') == 'active'}
    for name, source in FILES.items():
        old = read_installed(name)
        if old is not None:
            (backup / name).write_bytes(old)
        record['files'][name] = {'old': front.body_hash(old), 'new': front.body_hash(release_body(name, source, demo))}
    save_record(backup, record)
    return backup, record


def save_record(backup, record):
    front.atomic_write(backup / 'collector.json', (json.dumps(record, indent=2) + '\n').encode())


def check_restore(backup, record):
    check_kraken_restore(backup, record)
    if set(record['files']) not in (set(FILES), set(FILES) - {'collection.profile'}, {'build_snapshot.py', 'validate_snapshot.py'}):
        raise ValueError('Unexpected collector rollback manifest')
    if 'collection.profile' not in record['files'] and read_installed('collection.profile') is not None:
        raise ValueError('Use the profile activation backup before rolling back an older release')
    for name, hashes in record['files'].items():
        if front.body_hash(read_installed(name)) not in (hashes['old'], hashes['new']):
            raise ValueError('Newer or modified collector exists; refusing rollback')
        if hashes['old'] is not None and front.digest((backup / name).read_bytes()) != hashes['old']:
            raise ValueError('Collector backup integrity check failed')


def restore_collector(backup, record):
    check_restore(backup, record)
    restore_kraken_units(backup, record)
    for name, hashes in record['files'].items():
        if hashes['old'] is None:
            installed(name).unlink(missing_ok=True)
        else:
            front.atomic_write(installed(name), (backup / name).read_bytes())
    resume_previous_kraken(record)


def check_kraken_restore(backup, record):
    if 'units' not in record:
        return
    if set(record['units']) != set(UNITS):
        raise ValueError('Unexpected Kraken rollback manifest')
    for name, hashes in record['units'].items():
        path = front.target(UNIT_DIR, name)
        current = path.read_bytes() if path.exists() else None
        if front.body_hash(current) not in (hashes['old'], hashes['new']):
            raise ValueError('Newer or modified Kraken unit; refusing rollback')
        if hashes['old'] is not None and front.digest((backup / 'units' / name).read_bytes()) != hashes['old']:
            raise ValueError('Kraken unit backup integrity check failed')


def restore_kraken_units(backup, record):
    if not record.get('kraken_activation_started'):
        return
    check_kraken_restore(backup, record)
    # Installation can fail before daemon-reload or after only one unit write.
    systemctl('daemon-reload')
    for name in (KRAKEN_TIMER, KRAKEN_SERVICE):
        if front.target(UNIT_DIR, name).exists():
            systemctl('stop', name)
    if front.target(UNIT_DIR, KRAKEN_TIMER).exists():
        systemctl('disable', KRAKEN_TIMER)
    for name, hashes in record['units'].items():
        path = front.target(UNIT_DIR, name)
        if hashes['old'] is None:
            path.unlink(missing_ok=True)
        else:
            front.atomic_write(path, (backup / 'units' / name).read_bytes())
    systemctl('daemon-reload')
    # The old collector script is restored by the caller before its timer restarts.


def resume_previous_kraken(record):
    if not record.get('kraken_activation_started'):
        return
    timer = record['units'][KRAKEN_TIMER]
    if timer['enabled']:
        systemctl('enable', KRAKEN_TIMER)
    if timer['active']:
        systemctl('start', KRAKEN_TIMER)


def retire_kraken(backup, record):
    check_kraken_restore(backup, record)
    # Persist the recovery point before stopping or removing anything.
    record['kraken_activation_started'] = True
    save_record(backup, record)
    if record['units'][KRAKEN_TIMER]['old'] is not None:
        systemctl('stop', KRAKEN_TIMER)
        systemctl('disable', KRAKEN_TIMER)
    if record['units'][KRAKEN_SERVICE]['old'] is not None:
        systemctl('stop', KRAKEN_SERVICE)
    for name in UNITS:
        if record['units'][name]['old'] is not None and property_value(name, 'ActiveState') in ('active', 'activating', 'deactivating'):
            raise ValueError('Retired collector still running; refusing removal')
        front.target(UNIT_DIR, name).unlink(missing_ok=True)
    systemctl('daemon-reload')
    print('Legacy xStocks collector and timer absent. Crypto timer configuration preserved.', flush=True)


def validate_collected(started, require_new=False):
    from validate_snapshot import market_max_age, demo_quotes_current
    result = subprocess.run(['/usr/bin/python3', str(front.REPO / 'scripts/validate_snapshot.py'), str(SNAPSHOT)], capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Generated snapshot failed contract validation')
    data = json.loads(SNAPSHOT.read_text())
    generated = dt.datetime.fromisoformat(data['snapshot'].replace('Z', '+00:00'))
    if generated.timestamp() < started:
        raise CollectionNotReady('Collector did not produce a new snapshot')
    for name in ('coingecko_markets',):
        status = data.get('status', {}).get(name, {})
        try:
            stamp = dt.datetime.fromisoformat((status.get('fetched_at') or '').replace('Z', '+00:00'))
        except ValueError:
            raise CollectionNotReady(f'{name} has no successful collection date') from None
        if stamp.tzinfo is None:
            raise CollectionNotReady(f'{name} has no timezone')
        age = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
        if status.get('ok') is not True or not -60 <= age <= market_max_age(status) or (require_new and stamp.timestamp() < started):
            raise CollectionNotReady(f'{name} is unavailable or stale; rolling back')
        if require_new and status.get('policy') != 'demo-250-v1':
            raise CollectionNotReady('Demo profile was not applied')
        if status.get('policy') == 'demo-250-v1' and not demo_quotes_current(data, time.time()):
            raise CollectionNotReady('Insufficient current dated crypto prices; rolling back')
    from validate_snapshot import is_crypto
    if not data['coins'] or any(not is_crypto(c) for c in data['coins']):
        raise ValueError('Expected exclusively crypto assets')
    if any('xstock' in key.lower() for key in data.get('status', {})):
        raise ValueError('Retired source remains in snapshot')
    print(f'New snapshot valid: {len(data["coins"])} crypto assets, collection current.')


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


def collect_for_release(require_new=False):
    # One collection after a quiet minute; at most one retry, only after a
    # recorded 429 cooldown. No retry for schema, auth or service failures.
    for attempt in range(2):
        # Let the active cache expire before the sole retry, even when
        # Retry-After is shorter (300 seconds under the Demo profile).
        minimum = 60 if attempt == 0 else 180
        if read_installed('collection.profile') == DEMO_PROFILE:
            previous = json.loads(SNAPSHOT.read_text()).get('status', {}).get('coingecko_markets', {})
            if previous.get('policy') == 'demo-250-v1':
                stamp = dt.datetime.fromisoformat((previous.get('attempted_at') or previous.get('fetched_at') or '').replace('Z', '+00:00'))
                minimum = max(minimum, int(stamp.timestamp() + 301 - time.time()))
            wait_for_provider(minimum, maximum=360)
        else:
            wait_for_provider(minimum)
        started = int(time.time())
        systemctl('start', SERVICE)
        try:
            validate_collected(started, require_new=True) if require_new else validate_collected(started)
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
    demo = getattr(args, 'demo_250', False)
    preflight(args.revision, demo=demo)
    if not args.apply:
        print('Read-only preflight complete. --apply requires administrator activation.')
        return
    check_environment_paths()
    if demo:
        check_demo_key()
    backup, record = create_backup(args.revision, demo=demo)
    command = f'sudo python3 {shlex.quote(str(Path(__file__).resolve()))} --rollback {backup.name}'
    print('Full rollback: ' + command, flush=True)
    def undo():
        if record.get('front_backup'):
            front.run(argparse.Namespace(revision=None, apply=False, rollback=record['front_backup']))
        restore_collector(backup, record)
        print('Release failed: previous collector, Kraken units and front restored.', flush=True)
    # Restore inside the pause, before its finally block restarts the timer.
    with paused_timer(on_error=undo):
        retire_kraken(backup, record)
        for name, source in FILES.items():
            if front.body_hash(read_installed(name)) != record['files'][name]['old']:
                raise ValueError('Collector changed during deployment')
            body = release_body(name, source, demo)
            if front.body_hash(body) != record['files'][name]['new']:
                raise ValueError('Release payload changed during deployment')
            if body is None:
                installed(name).unlink(missing_ok=True)
            else:
                front.atomic_write(installed(name), body)
        collect_for_release(require_new=True) if demo else collect_for_release()
        def remember_front(front_backup):
            record['front_backup'] = front_backup.name
            save_record(backup, record)
        front.run(argparse.Namespace(revision=args.revision, apply=True, rollback=None), on_backup=remember_front)
    print(f'Release LIVE: {args.revision}. Provider secrets and generated-data paths preserved.')
    if demo:
        print('Demo profile active: up to 250 crypto assets / 5 min; global / 1 h; local budget 10,000 requests / UTC month.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision')
    parser.add_argument('--demo-250', action='store_true', help='Activate the free Demo profile using the existing key; allow recovery preflight, require fresh postflight')
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

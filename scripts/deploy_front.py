#!/usr/bin/env python3
"""Publish an exact Orbit2 front revision, with immutable assets and rollback.

Run on the production host. Default is read-only preflight; --apply requires root.
Never writes provider data, secrets, Apache configuration, services or timers.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[1]
WEB_ROOT = Path('/var/www/html/orbit')
BACKUPS = Path('/var/backups/orbit')
ORIGIN = 'https://orbit.l0g.fr'
PAGES = ('index.html', 'legal/index.html')
SHA = re.compile(r'[0-9a-f]{40}')


def digest(body):
    return hashlib.sha256(body).hexdigest()


def git(*args):
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
    return subprocess.check_output(['git', '-c', f'safe.directory={REPO}', '-c', 'core.fsmonitor=false',
                                    '-c', 'core.hooksPath=/dev/null', *args], cwd=REPO, env=env).decode().strip()


class ReleaseHTML(HTMLParser):
    def __init__(self, page, revision, assets):
        super().__init__(convert_charrefs=False)
        self.page, self.revision, self.assets = page, revision, assets
        self.output = []

    def start(self, tag, attrs, ending):
        rewritten = []
        for key, value in attrs:
            if value and ((tag in ('img', 'script') and key == 'src') or (tag == 'link' and key == 'href')):
                url = urllib.parse.urlsplit(value)
                if url.scheme or url.netloc or url.path.startswith('/'):
                    raise ValueError('Release assets must be local relative paths')
                name = posixpath.normpath(posixpath.join(posixpath.dirname(self.page), url.path))
                if name not in self.assets:
                    raise ValueError(f'Unlisted asset: {name}')
                value = f'/releases/{self.revision}/{name}'
            rewritten.append(key if value is None else f'{key}="{html.escape(value, quote=True)}"')
        self.output.append('<' + tag + (' ' if rewritten else '') + ' '.join(rewritten) + ending)

    def handle_starttag(self, tag, attrs):
        self.start(tag, attrs, '>')

    def handle_startendtag(self, tag, attrs):
        self.start(tag, attrs, '/>')

    def handle_endtag(self, tag):
        if tag == 'head':
            self.output.append(f'<meta name="orbit-release" content="{self.revision}">\n')
        self.output.append(f'</{tag}>')

    def handle_data(self, data):
        self.output.append(data)

    def handle_entityref(self, name):
        self.output.append(f'&{name};')

    def handle_charref(self, name):
        self.output.append(f'&#{name};')

    def handle_decl(self, decl):
        self.output.append(f'<!{decl}>')

    def handle_comment(self, data):
        self.output.append(f'<!--{data}-->')


def payload(web, revision):
    if not SHA.fullmatch(revision):
        raise ValueError('A full 40-character Git revision is required')
    names = ['app.js', 'core.js', 'i18n.js', 'app.css', 'orbit.svg', 'icons/LICENSE']
    icons = sorted(str(p.relative_to(web)) for p in (web / 'icons').glob('*.svg'))
    if not icons:
        raise ValueError('Missing local icons')
    names += icons
    assets = {}
    for name in names:
        file = web / name
        if file.is_symlink() or not file.resolve().is_relative_to(web.resolve()):
            raise ValueError('Symlinked assets are not supported')
        assets[name] = file.read_bytes()
    pages = {}
    for name in PAGES:
        parser = ReleaseHTML(name, revision, assets)
        parser.feed((web / name).read_text(encoding='utf-8'))
        parser.close()
        pages[name] = ''.join(parser.output).encode()
    return assets, pages


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def public(path):
    url = ORIGIN + path + '?orbit_check=' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S%f')
    request = urllib.request.Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'Orbit2-release-check/1.0'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        body = response.read(6_000_001)
        if len(body) > 6_000_000:
            raise ValueError('Public response is too large')
        return body, response.headers


def check_snapshot():
    raw, _ = public('/data.json')
    data = json.loads(raw)
    markets = data.get('status', {}).get('coingecko_markets') or {}
    if markets.get('ok') is False:
        raise ValueError('Market source is unavailable; do not deploy yet')
    stamp = markets.get('fetched_at') or data.get('snapshot')
    parsed = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if parsed.tzinfo is None or not data.get('coins') or not isinstance(data['coins'], list):
        raise ValueError('Invalid public snapshot')
    age = (dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()
    if not -60 <= age <= 180:
        raise ValueError(f'Market snapshot is not current ({age:.0f}s); do not deploy yet')
    print(f'Public snapshot: {len(data["coins"])} coins, collection age {age:.0f}s')


def target(root, name):
    file = root / name
    if file.is_symlink() or file.resolve().parent != (root / name).absolute().parent:
        raise ValueError(f'Unexpected symlink in served path: {name}')
    return file


def preflight(root):
    if root.is_symlink() or not root.is_dir() or root.resolve() != root.absolute():
        raise ValueError('Expected a real existing web-root directory')
    for name in PAGES:
        served, headers = public('/' if name == 'index.html' else '/legal/')
        if served != target(root, name).read_bytes():
            raise ValueError(f'Public {name} does not match this web root; aborting')
        csp = headers.get('Content-Security-Policy', '')
        for directive in ("script-src 'self'", "connect-src 'self'", "frame-ancestors 'none'"):
            if directive not in csp:
                raise ValueError('Expected production CSP is missing; inspect Apache first')
    check_snapshot()


def atomic_write(file, body):
    fd, temporary = tempfile.mkstemp(prefix='.orbit-', dir=file.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare(root, backups, revision, assets, pages):
    # Only the entry HTML changes. Legacy assets remain usable by open tabs/rollback.
    releases = root / 'releases'
    if releases.is_symlink():
        raise ValueError('Release directory cannot be a symlink')
    releases.mkdir(mode=0o755, exist_ok=True)
    release = releases / revision
    if release.exists() or release.is_symlink():
        if release.is_symlink() or any(target(release, name).read_bytes() != body for name, body in assets.items()):
            raise ValueError('Existing immutable release differs')
    else:
        staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=releases))
        try:
            staging.chmod(0o755)
            for name, body in assets.items():
                file = staging / name
                file.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                atomic_write(file, body)
            os.rename(staging, release)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + revision[:12] + '-', dir=backups))
    record = {'revision': revision, 'pages': {}}
    for name, body in pages.items():
        old = target(root, name).read_bytes()
        saved = backup / name
        saved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        saved.write_bytes(old)
        record['pages'][name] = {'old': digest(old), 'new': digest(body)}
    (backup / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    return backup


def restore(root, backup):
    record = json.loads((backup / 'manifest.json').read_text())
    if set(record['pages']) != set(PAGES):
        raise ValueError('Unexpected rollback manifest')
    for name in PAGES:
        hashes = record['pages'][name]
        if digest(target(root, name).read_bytes()) not in (hashes['old'], hashes['new']):
            raise ValueError('A newer or modified front exists; refusing to overwrite it')
        if digest((backup / name).read_bytes()) != hashes['old']:
            raise ValueError('Rollback backup failed its integrity check')
    for name in PAGES:
        atomic_write(target(root, name), (backup / name).read_bytes())


def activate(root, backup, pages):
    record = json.loads((backup / 'manifest.json').read_text())
    for name in reversed(PAGES):
        if digest(target(root, name).read_bytes()) != record['pages'][name]['old']:
            raise ValueError('Front changed during deployment')
        atomic_write(target(root, name), pages[name])


def verify_pages(pages):
    for name, expected in pages.items():
        actual, _ = public('/' if name == 'index.html' else '/legal/')
        if actual != expected:
            raise ValueError(f'Public verification failed for {name}')


def run(args):
    if args.rollback:
        if os.geteuid() != 0 or Path(args.rollback).name != args.rollback:
            raise ValueError('Rollback requires root and a backup directory name, not a path')
        backup = BACKUPS / args.rollback
        if backup.is_symlink() or backup.resolve().parent != BACKUPS.resolve():
            raise ValueError('Invalid backup path')
        restore(WEB_ROOT, backup)
        verify_pages({name: (backup / name).read_bytes() for name in PAGES})
        print('Previous front restored and publicly verified. Versioned assets retained.')
        return
    if not args.revision or not SHA.fullmatch(args.revision) or git('rev-parse', 'HEAD') != args.revision:
        raise ValueError('Checkout HEAD must match the exact requested revision')
    if git('status', '--porcelain'):
        raise ValueError('Checkout must be clean before deployment')
    assets, pages = payload(REPO / 'web', args.revision)
    preflight(WEB_ROOT)
    print(f'Preflight OK: revision {args.revision}, {len(assets)} static assets, 2 entry pages')
    if not args.apply:
        print('Read-only check complete. Use --apply to activate this exact front.')
        return
    if os.geteuid() != 0:
        raise ValueError('--apply requires sudo')
    backup = prepare(WEB_ROOT, BACKUPS, args.revision, assets, pages)
    print(f'Rollback: sudo python3 scripts/deploy_front.py --rollback {backup.name}', flush=True)
    # Verify immutable assets over HTTPS before either entry page can reference them.
    for name, expected in assets.items():
        actual, headers = public(f'/releases/{args.revision}/{name}')
        if actual != expected:
            raise ValueError(f'Asset verification failed before activation: {name}')
        types = {'.js': ('text/javascript', 'application/javascript'), '.css': ('text/css',), '.svg': ('image/svg+xml',)}
        allowed = types.get(Path(name).suffix)
        if allowed and headers.get('Content-Type', '').split(';')[0] not in allowed:
            raise ValueError(f'Unexpected public content type: {name}')
    try:
        activate(WEB_ROOT, backup, pages)
        verify_pages(pages)
        check_snapshot()
    except BaseException:
        restore(WEB_ROOT, backup)
        print('Activation failed: previous entry pages restored.', flush=True)
        raise
    print(f'Front LIVE and verified: {args.revision}')
    print('Collector, API cadence, data.json, logos and Apache configuration were not changed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--apply', action='store_true')
    action.add_argument('--rollback', metavar='BACKUP_NAME')
    args = parser.parse_args()
    with contextlib.ExitStack() as stack:
        if args.apply or args.rollback:
            if os.geteuid() != 0:
                parser.error('Activation and rollback require sudo')
            if BACKUPS.is_symlink():
                parser.error('Backup root cannot be a symlink')
            BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
            lock = stack.enter_context((BACKUPS / '.deploy.lock').open('a'))
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(args)


if __name__ == '__main__':
    main()

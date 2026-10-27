#!/usr/bin/python3 -I
"""Install or roll back a reviewed bundle; never activate a desktop or Sunshine."""
import argparse
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'}
POLICY = Path('/etc/plasmactl/sunshine.json')
UNCONSTRAINED = object()


def run(argv):
    subprocess.run(argv, env=ENV, check=True, timeout=40)


def trusted(path):
    for item in (path, *path.parents):
        info = item.lstat()
        if item.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(f'Untrusted destination: {item}')


def snapshot(path):
    if not path.exists() and not path.is_symlink():
        return None, None
    trusted(path)
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_uid', 'st_gid')
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise ValueError(f'File changed during inspection: {path}')
    identity = {field: getattr(after, field) for field in fields}
    identity['sha256'] = hashlib.sha256(data).hexdigest()
    return data, identity


def unchanged(path, expected):
    if snapshot(path)[1] != expected:
        raise ValueError(f'File changed before replacement; preserve for review: {path}')


def atomic_write(path, content, mode, gid=0, expected=UNCONSTRAINED):
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o755)
        path.parent.chmod(0o755)
    trusted(path.parent)
    fd, candidate = tempfile.mkstemp(prefix='.plasmactl-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), 0, gid)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not UNCONSTRAINED:
            unchanged(path, expected)
        os.replace(candidate, path)
    finally:
        if os.path.exists(candidate):
            os.unlink(candidate)


def allowed_destination(name, uid):
    fixed = {'sunshine.json': '/etc/plasmactl/sunshine.json',
             'plasmactl-sunshine': '/usr/local/libexec/plasmactl-sunshine',
             'sudoers': '/etc/sudoers.d/plasmactl'}
    if re.fullmatch(rf'plasmactl-sunshine-u{uid}-(igpu|dgpu)@\.service', name):
        return '/etc/systemd/system/' + name
    if name not in fixed:
        raise ValueError('Unexpected bundle file')
    return fixed[name]


def require_idle(uid):
    result = subprocess.run(['/usr/bin/systemctl', 'list-units', '--all', '--output=json',
                             '--no-pager', 'plasmactl-sunshine-u*-*@*.service'],
                            env=ENV, capture_output=True, text=True, check=True, timeout=15)
    if any(unit['active'] not in ('inactive', 'failed') for unit in json.loads(result.stdout)):
        raise ValueError('Stop the managed Sunshine execution before changing its installation')


def require_single_uid(uid):
    if not POLICY.exists() and not POLICY.is_symlink():
        return
    data, _ = snapshot(POLICY)
    policy = json.loads(data)
    if (not isinstance(policy, dict) or policy.get('schema') != 1
            or not isinstance(policy.get('users'), dict) or set(policy['users']) != {str(uid)}):
        raise ValueError('Installed policy belongs to a different UID; explicit migration is required')


def restore(backup):
    trusted(backup)
    state = json.loads((backup / 'state.json').read_text())
    require_idle(state['uid'])
    require_single_uid(state['uid'])
    actions = []
    # Validate the entire rollback before changing any destination.
    for item in state['files']:
        path = Path(item['destination'])
        if not item['installed']:
            continue
        current, identity = snapshot(path)
        if current is None and not item['existed']:
            # Nothing was installed here. Do not unlink a file that might be
            # created after this check by another administrator.
            continue
        previous = (backup / item['backup']).read_bytes() if item['existed'] else None
        if (previous is not None and current == previous and identity
                and identity['st_mode'] & 0o777 == item['mode'] and identity['st_gid'] == item['gid']):
            continue
        digest = hashlib.sha256(current).hexdigest() if current is not None else None
        if digest != item['candidate_sha256']:
            raise ValueError(f'Installed file changed; preserve for review: {path}')
        actions.append((item, path, previous, identity))
    for item, path, previous, identity in reversed(actions):
        if item['existed']:
            atomic_write(path, previous, item['mode'], item['gid'], expected=identity)
        else:
            unchanged(path, identity)
            path.unlink()
    run(['/usr/bin/systemctl', 'daemon-reload'])
    print('Integration files restored. Package Sunshine autostart was not changed by this installer.')


def install(bundle, backup):
    manifest = json.loads((bundle / 'manifest.json').read_text())
    uid = manifest['uid']
    if manifest.get('schema') != 1 or type(uid) is not int or uid <= 0:
        raise ValueError('Invalid manifest')
    require_idle(uid)
    require_single_uid(uid)
    payloads = []
    for name, item in manifest['files'].items():
        destination = allowed_destination(name, uid)
        data = (bundle / name).read_bytes()
        if destination != item['destination'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('Bundle content or destination changed')
        mode = 0o755 if name == 'plasmactl-sunshine' else 0o440 if name == 'sudoers' else 0o644
        if item['mode'] != mode:
            raise ValueError('Invalid candidate permissions')
        payloads.append((name, Path(destination), data, mode, item['sha256']))
    if not {'sunshine.json', 'plasmactl-sunshine', 'sudoers'} <= set(manifest['files']):
        raise ValueError('Incomplete bundle')
    policy = json.loads(next(data for name, _, data, _, _ in payloads if name == 'sunshine.json'))
    if (not isinstance(policy, dict) or policy.get('schema') != 1
            or not isinstance(policy.get('users'), dict) or set(policy['users']) != {str(uid)}
            or not isinstance(policy['users'][str(uid)], dict)):
        raise ValueError('Candidate policy must contain exactly the manifest UID')
    roles = policy['users'][str(uid)].get('gpus', {})
    if not isinstance(roles, dict) or not roles or not set(roles) <= {'igpu', 'dgpu'}:
        raise ValueError('Invalid candidate GPU roles')
    expected_units = {f'plasmactl-sunshine-u{uid}-{role}@.service' for role in roles}
    if {name for name, _, _, _, _ in payloads if name.endswith('.service')} != expected_units:
        raise ValueError('Candidate units differ from the policy roles')
    # Native validators and installation consume the same immutable byte capture.
    # Stage under the trusted backup parent, not the caller's bundle directory.
    trusted(backup.parent)
    with tempfile.TemporaryDirectory(prefix='.plasmactl-validate-', dir=backup.parent) as directory:
        stage = Path(directory)
        for name, _, data, _, _ in payloads:
            (stage / name).write_bytes(data)
            (stage / name).chmod(0o600)
        run(['/usr/sbin/visudo', '-cf', str(stage / 'sudoers')])
        run(['/usr/bin/systemd-analyze', 'verify', *(str(stage / name) for name in sorted(expected_units))])
    # Refuse unrelated pre-existing sudoers failures before replacing any file.
    run(['/usr/sbin/visudo', '-c'])
    # All payload bytes are captured before privilege-changing writes. Never
    # reopen user-writable bundle files after validation.
    backup.mkdir(mode=0o700)
    trusted(backup)
    state = {'schema': 1, 'uid': uid, 'files': []}
    payloads.sort(key=lambda item: item[0] == 'sudoers')
    for index, (name, path, data, mode, digest) in enumerate(payloads):
        previous, identity = snapshot(path)
        existed = previous is not None
        oldmode = None
        oldgid = 0
        if existed:
            oldmode = identity['st_mode'] & 0o777
            oldgid = identity['st_gid']
            (backup / str(index)).write_bytes(previous)
            (backup / str(index)).chmod(0o600)
        state['files'].append({'destination': str(path), 'backup': str(index),
                               'existed': existed, 'mode': oldmode, 'gid': oldgid,
                               'before': identity, 'candidate_sha256': digest, 'installed': False})
    atomic_write(backup / 'state.json', json.dumps(state, indent=2).encode(), 0o600)
    try:
        for item, (_, path, data, mode, _) in zip(state['files'], payloads):
            # Record intent first, so interruption leaves an explicit recovery record.
            item['installed'] = True
            atomic_write(backup / 'state.json', json.dumps(state, indent=2).encode(), 0o600)
            atomic_write(path, data, mode, expected=item['before'])
        run(['/usr/sbin/visudo', '-c'])
        run(['/usr/bin/systemctl', 'daemon-reload'])
    except BaseException as original:
        try:
            restore(backup)
        except Exception as recovery:
            raise RuntimeError(f'Installation failed; rollback needs review at {backup}: {recovery}') from original
        raise
    print(f'Installed inactive integration. Rollback record: {backup}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    apply = actions.add_parser('install')
    apply.add_argument('bundle', type=Path)
    apply.add_argument('backup', type=Path)
    rollback = actions.add_parser('rollback')
    rollback.add_argument('backup', type=Path)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError('Run this installer as root after reviewing the bundle')
        os.umask(0o077)
        lock_path = Path('/run/plasmactl-integration.lock')
        if lock_path.exists() or lock_path.is_symlink():
            trusted(lock_path)
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.action == 'install':
                install(args.bundle.resolve(), args.backup.absolute())
            else:
                restore(args.backup.absolute())
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')

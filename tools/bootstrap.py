#!/usr/bin/python3 -I
"""Plan and install a user CLI; prepare configuration without starting services."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

if sys.version_info < (3, 10):
    raise SystemExit('Bootstrap requires Python 3.10 or newer')

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ('bash', 'python', 'coreutils', 'util-linux', 'procps-ng', 'gawk',
            'sed', 'grep', 'iproute2', 'dbus', 'systemd', 'tmux', 'jq', 'libcap',
            'kwin', 'plasma-workspace', 'sunshine')
PAYLOAD = ('plasmactl', 'install.sh', 'tools/bootstrap.py',
           'tools/prepare-sunshine-integration.py', 'tools/install-sunshine-integration.py',
           'libexec/plasmactl-sunshine', 'config/systemd/plasmactl-sunshine.service.in',
           'sunshine/plasmactl-safe.conf', 'sunshine/plasmactl-performance.conf',
           'sunshine/plasmactl-apps-safe.json', 'sunshine/plasmactl-apps-performance.json',
           'README.md', 'SPEC.md', 'LICENSE', 'CHANGELOG.md', 'docs/INSTALLATION.md')
EXECUTABLES = {'plasmactl', 'install.sh', 'libexec/plasmactl-sunshine'}


def query(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(argv, 127, '', str(error))


def layout(prefix):
    home = Path.home().absolute()
    prefix = Path(os.path.abspath(os.path.expanduser(prefix))) if prefix else home / '.local'
    if prefix == home or not prefix.is_relative_to(home):
        raise ValueError('The user installation prefix must be a directory inside HOME')
    return home, prefix


def check_directories(path, home):
    if path != home and not path.is_relative_to(home):
        raise ValueError(f'Path is outside HOME: {path}')
    # Inspect from HOME outward, without following a symlink at any level.
    for part in (home, *reversed(path.relative_to(home).parents), path):
        item = part if part.is_absolute() else home / part
        if not item.exists() and not item.is_symlink():
            continue
        info = item.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022):
            raise ValueError(f'Unsafe user directory: {item}')


def mkdir(path, home):
    check_directories(path, home)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def snapshot(path):
    if path.is_symlink():
        return ('link', os.readlink(path))
    if path.exists():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError(f'Unowned or unsupported file: {path}')
        return ('file', path.read_bytes(), stat.S_IMODE(info.st_mode))
    return None


def publish_missing(path, data, home):
    mkdir(path.parent, home)
    fd, temporary = tempfile.mkstemp(prefix='.plasmactl-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    finally:
        os.unlink(temporary)


def config_payloads(home):
    version = re.search(r'^VERSION="([^"]+)"', (ROOT / 'plasmactl').read_text(), re.M)[1]
    config = home / '.config'
    sunshine = config / 'sunshine'
    payloads = {config / 'plasmactl.conf': b'''# User configuration created by plasmactl bootstrap.
PLASMA_SESSION_BACKEND=systemd-scope
PLASMA_GPU_DEFAULT=igpu
PLASMA_GPU_ALLOW_FALLBACK=false
HEADLESS_MODE=none
SUNSHINE_SUPERVISE=true
SUNSHINE_PROFILE=performance
SUNSHINE_ARGS=
SUNSHINE_CONFIG_PATH=
'''}
    profiles = {}
    for profile in ('safe', 'performance'):
        name = f'plasmactl-{profile}.conf'
        text = (ROOT / 'sunshine' / name).read_text()
        text = re.sub(r'^wan_encryption_mode\s*=.*$', 'wan_encryption_mode = 2', text, flags=re.M)
        payloads[sunshine / name] = text.encode()
        apps = f'plasmactl-apps-{profile}.json'
        data = (ROOT / 'sunshine' / apps).read_bytes()
        json.loads(data)
        payloads[sunshine / apps] = data
        profiles[profile] = {'sunshine_config': str(sunshine / name), 'apps_json': str(sunshine / apps)}
    payloads[config / 'plasmactl/profiles.json'] = (json.dumps(
        {'version': version, 'active_profile': 'performance', 'profiles': profiles}, indent=2) + '\n').encode()
    return payloads


def discover(home, prefix):
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        release = {}
    family = {release.get('ID', ''), *release.get('ID_LIKE', '').split()}
    supported = bool(family & {'arch', 'cachyos'}) and bool(shutil.which('pacman'))
    packages = {'supported_installer': supported, 'missing': [], 'unavailable': [], 'error': None}
    if supported:
        installed = query(['pacman', '-Qq'])
        if installed.returncode:
            packages['error'] = 'Cannot read the installed package database: ' + installed.stderr.strip()
        else:
            packages['missing'] = sorted(set(PACKAGES) - set(installed.stdout.splitlines()))
            for name in packages['missing']:
                available = query(['pacman', '-Si', '--', name])
                if available.returncode:
                    packages['unavailable'].append(name)
    tty = query(['loginctl', 'list-sessions', '--no-legend', '--no-pager'])
    tmux = query(['tmux', 'has-session', '-t', 'plasma'])
    units = query(['systemctl', '--user', 'show', '-p', 'LoadState', '--value',
                   'plasma-kwin_wayland.service', 'plasma-plasmashell.service',
                   'plasma-workspace-wayland.target'])
    return {'schema': 1, 'platform': release.get('ID', 'unknown'), 'prefix': str(prefix),
            'packages': packages,
            'environment': {'session_listing_available': tty.returncode == 0,
                            'native_plasma_units_loaded': units.returncode == 0 and units.stdout.split() == ['loaded'] * 3,
                            'tmux_plasma_exists': tmux.returncode == 0,
                            'drm_render_nodes': sorted(str(p) for p in Path('/dev/dri/by-path').glob('*-render')),
                            'sunshine_credentials_exist': (home / '.config/sunshine/sunshine_state.json').is_file()},
            'next_actions': ['Review seat0 TTY login and selected GPU with plasmactl session-check/detect-gpu.',
                             'Prepare and review privileged integration with bootstrap integration prepare.',
                             'Initialize Sunshine credentials/pairing through its supported Web UI flow.',
                             'Activate only after reviewing existing Sunshine autostart and configuration.']}


def plan(args):
    home, prefix = layout(args.prefix)
    paths = [prefix / 'bin', prefix / 'share/plasmactl']
    if not args.no_configure:
        paths += [home / '.config/sunshine', home / '.config/plasmactl']
    for path in paths:
        check_directories(path, home)
    result = discover(home, prefix)
    files = {} if args.no_configure else config_payloads(home)
    result['configuration'] = {str(p): 'preserve' if p.exists() or p.is_symlink() else 'create'
                               for p in files}
    result['cli'] = str(prefix / 'bin/plasmactl')
    result['cli_exists'] = (prefix / 'bin/plasmactl').exists() or (prefix / 'bin/plasmactl').is_symlink()
    result['dependency_command'] = (['sudo', '--', 'pacman', '-S', '--needed',
                                    *(['--noconfirm'] if args.yes else []), '--',
                                    *result['packages']['missing']]
                                   if args.install_deps and result['packages']['missing'] else [])
    result['dry_run'] = True
    return result


def require_user():
    if os.geteuid() == 0:
        raise ValueError('Run user bootstrap without sudo; only explicit dependency/integration operations elevate')


def configure(home):
    created = []
    try:
        for path, data in config_payloads(home).items():
            if publish_missing(path, data, home):
                created.append((path, data))
    except BaseException:
        for path, data in reversed(created):
            if not path.is_symlink() and path.is_file() and path.read_bytes() == data:
                path.unlink()
        raise
    return [str(p) for p, _ in created]


def install(args, report):
    require_user()
    home, prefix = layout(args.prefix)
    payloads = {name: (ROOT / name).read_bytes() for name in PAYLOAD}
    digest = hashlib.sha256()
    for name, data in sorted(payloads.items()):
        digest.update(name.encode() + b'\0' + data + b'\0')
    version = digest.hexdigest()[:20]
    data_dir = prefix / 'share/plasmactl'
    release = data_dir / 'versions' / version
    entrypoint = prefix / 'bin/plasmactl'
    previous = snapshot(entrypoint)
    expected = ('link', str(release / 'plasmactl'))
    if previous is not None and previous != expected and not args.replace_cli:
        raise ValueError('An existing CLI would be replaced; review it and pass --replace-cli')
    packages = report['packages']
    if not args.skip_dependencies:
        if not packages['supported_installer']:
            raise ValueError('Automatic dependencies support Arch/CachyOS only; install requirements manually and use --skip-dependencies')
        if packages['error'] or packages['unavailable']:
            raise ValueError('Package preflight failed: ' + str(packages['error'] or packages['unavailable'])
                             + '. Use supported sources; no repositories or AUR helpers are added.')
        if packages['missing']:
            if not args.install_deps:
                raise ValueError('Missing packages: ' + ', '.join(packages['missing']) + '; review plan and pass --install-deps')
            # Never refresh databases alone or perform an implicit system upgrade.
            command = ['sudo', '--', 'pacman', '-S', '--needed']
            if args.yes:
                command.append('--noconfirm')
            subprocess.run([*command, '--', *packages['missing']], check=True)
            after = discover(home, prefix)['packages']
            if after['error'] or after['missing']:
                raise ValueError('Dependencies remain missing after installation; user files were not installed')
    mkdir(data_dir, home)
    lock_fd = os.open(data_dir / 'install.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a') as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('Unsafe installation lock')
        fcntl.flock(lock, fcntl.LOCK_EX)
        if snapshot(entrypoint) != previous:
            raise ValueError('The CLI changed concurrently; review before retrying')
        mkdir(release.parent, home)
        if release.exists() or release.is_symlink():
            check_directories(release, home)
            for name, content in payloads.items():
                path = release / name
                check_directories(path.parent, home)
                if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
                    raise ValueError('Existing release was modified; preserve it for review')
        else:
            stage = Path(tempfile.mkdtemp(prefix='.install-', dir=release.parent))
            try:
                for name, content in payloads.items():
                    path = stage / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    path.chmod(0o755 if name in EXECUTABLES else 0o644)
                stage.rename(release)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        mkdir(entrypoint.parent, home)
        # Retain the previous CLI before replacing the public entry point.
        receipt_dir = data_dir / 'receipts' / uuid.uuid4().hex
        mkdir(receipt_dir, home)
        receipt = {'schema': 1, 'release': str(release), 'entrypoint': str(entrypoint),
                   'previous': None, 'created_configuration': [],
                   'files': {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}}
        if previous:
            receipt['previous'] = {'kind': previous[0]}
            if previous[0] == 'file':
                (receipt_dir / 'previous-cli').write_bytes(previous[1])
                (receipt_dir / 'previous-cli').chmod(0o600)
                receipt['previous']['mode'] = previous[2]
            else:
                receipt['previous']['target'] = previous[1]
        # Record recovery information before publishing the entry point.
        (receipt_dir / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        candidate = entrypoint.parent / ('.plasmactl-' + uuid.uuid4().hex)
        try:
            candidate.symlink_to(release / 'plasmactl')
            if snapshot(entrypoint) != previous:
                raise ValueError('The CLI changed before publication; preserve it for review')
            os.replace(candidate, entrypoint)
        finally:
            candidate.unlink(missing_ok=True)
        if not args.no_configure:
            # Configuration publication never overwrites operator files. If a
            # path fails validation, retain the CLI and its recovery receipt.
            try:
                receipt['created_configuration'] = configure(home)
            except (ValueError, OSError) as error:
                raise RuntimeError(f'CLI installed but configuration failed; recovery receipt: {receipt_dir / "receipt.json"}: {error}') from error
        (receipt_dir / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return {'installed_cli': str(entrypoint), 'release': str(release),
            'receipt': str(receipt_dir / 'receipt.json'),
            'created_configuration': receipt['created_configuration'], 'services_started': False}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'integration':
        if len(argv) < 2 or argv[1] not in ('prepare', 'install', 'rollback'):
            raise ValueError('Use integration prepare|install|rollback followed by the existing tool arguments')
        tool = 'prepare-sunshine-integration.py' if argv[1] == 'prepare' else 'install-sunshine-integration.py'
        arguments = argv[2:] if argv[1] == 'prepare' else argv[1:]
        return subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / tool), *arguments]).returncode
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog='Integration tools: integration prepare|install|rollback [arguments]. '
               'Use integration prepare --help or integration install --help for their interfaces.')
    parser.add_argument('action', choices=('plan', 'install', 'configure'), nargs='?', default='plan')
    parser.add_argument('--prefix', help='User prefix inside HOME; default: ~/.local')
    parser.add_argument('--dry-run', action='store_true', help='Print a read-only plan without changing files or packages')
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--install-deps', action='store_true', help='Install missing packages from existing pacman repositories')
    choice.add_argument('--skip-dependencies', action='store_true', help='Explicitly leave runtime dependency installation to the operator')
    parser.add_argument('--yes', action='store_true', help='Use pacman --noconfirm with explicit --install-deps')
    parser.add_argument('--replace-cli', action='store_true', help='Back up and replace an existing user CLI')
    parser.add_argument('--no-configure', action='store_true', help='Install the CLI without creating user configuration')
    args = parser.parse_args(argv)
    if args.yes and not args.install_deps:
        parser.error('--yes requires --install-deps')
    if args.action == 'configure' and (args.install_deps or args.skip_dependencies or args.replace_cli or args.no_configure):
        parser.error('configure accepts only --prefix and --dry-run')
    report = plan(args)
    if args.action == 'plan' or args.dry_run:
        print(json.dumps(report, indent=2))
        return 0
    if args.action == 'configure':
        require_user()
        home, _ = layout(args.prefix)
        mkdir(home / '.config/plasmactl', home)
        fd = os.open(home / '.config/plasmactl/bootstrap.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as lock:
            info = os.fstat(lock.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError('Unsafe configuration lock')
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = {'created_configuration': configure(home), 'services_started': False}
    else:
        result = install(args, report)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(f'plasmactl bootstrap: {error}', file=sys.stderr)
        raise SystemExit(1)

import importlib.util
from importlib.machinery import SourceFileLoader
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load_bootstrap():
    sys.dont_write_bytecode = True
    name = 'bootstrap_under_test'
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(ROOT / 'tools/bootstrap.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap = load_bootstrap()


class BootstrapCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.prefix = self.home / '.local'
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.patches = [
            mock.patch.object(bootstrap.Path, 'home', return_value=self.home),
            mock.patch.object(bootstrap, 'require_user'),
            mock.patch.object(bootstrap, 'discover', side_effect=self.discover),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.state = {'supported_installer': True, 'missing': [], 'unavailable': [], 'error': None}

    def discover(self, home, prefix):
        return {'schema': 1, 'platform': 'arch', 'prefix': str(prefix),
                'packages': dict(self.state), 'environment': {}, 'next_actions': []}

    def args(self, *args):
        with redirect_stdout(io.StringIO()):
            return bootstrap.main(list(args))

    def installed_files(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob('*'))

    def install_args(self, *flags):
        return self.args('install', '--skip-dependencies', *flags)

    def test_dry_run_entrypoints_do_not_write_even_with_invalid_user_config(self):
        config_dir = self.home / '.config'
        config_dir.mkdir()
        config = config_dir / 'plasmactl.conf'
        config.write_text('printf executed > "$HOME/config-was-executed"\nthis is invalid shell syntax (\n')
        config.chmod(0o711)
        (config_dir / 'plasmactl').mkdir()
        (config_dir / 'plasmactl/config.json').write_text('{invalid json')
        before = {str(p.relative_to(self.home)): (p.is_symlink(), p.read_bytes() if p.is_file() else os.readlink(p) if p.is_symlink() else None,
                                                   p.lstat().st_mode) for p in self.home.rglob('*')}
        with mock.patch.object(bootstrap, 'query', return_value=subprocess.CompletedProcess([], 0, '', '')):
            self.args('plan', '--dry-run')
            subprocess.run([str(ROOT / 'install.sh'), 'install', '--dry-run', '--prefix', str(self.prefix)],
                           check=True, capture_output=True, text=True, env={**os.environ, 'HOME': str(self.home)})
            subprocess.run([str(ROOT / 'plasmactl'), 'bootstrap', 'install', '--dry-run', '--prefix', str(self.prefix)],
                           check=True, capture_output=True, text=True, env={**os.environ, 'HOME': str(self.home)})
        after = {str(p.relative_to(self.home)): (p.is_symlink(), p.read_bytes() if p.is_file() else os.readlink(p) if p.is_symlink() else None,
                                                  p.lstat().st_mode) for p in self.home.rglob('*')}
        self.assertEqual(after, before)

    def test_user_payload_and_installed_symlink_work_without_checkout(self):
        source = self.root / 'source checkout'
        for name in bootstrap.PAYLOAD:
            destination = source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        with mock.patch.object(bootstrap, 'ROOT', source), \
                mock.patch.object(bootstrap.shutil, 'which', return_value='/usr/bin/pacman'), \
                mock.patch.object(bootstrap.platform, 'freedesktop_os_release', return_value={'ID': 'arch'}), \
                mock.patch.object(bootstrap, 'query', return_value=subprocess.CompletedProcess([], 0, '\n'.join(bootstrap.PACKAGES), '')):
            self.install_args()
        source.rename(self.root / 'checkout-moved')
        cli = self.prefix / 'bin/plasmactl'
        self.assertTrue(cli.is_symlink())
        self.assertTrue((self.prefix / 'share/plasmactl/versions').is_dir())
        result = subprocess.run([str(cli), 'bootstrap', 'plan', '--prefix', str(self.prefix)],
                                cwd=self.root, env={**os.environ, 'HOME': str(self.home)},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['prefix'], str(self.prefix))
        self.assertFalse(str(ROOT) in result.stdout)

    def test_existing_config_apps_and_credentials_are_preserved(self):
        existing = {
            self.home / '.config/plasmactl.conf': b'operator config\n',
            self.home / '.config/plasmactl/profiles.json': b'{"operator": true}\n',
            self.home / '.config/sunshine/plasmactl-safe.conf': b'custom safe profile\n',
            self.home / '.config/sunshine/plasmactl-apps-performance.json': b'{"apps": []}\n',
            self.home / '.config/sunshine/sunshine_state.json': b'{"credentials": "keep"}\n',
        }
        for path, data in existing.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o640)
        with mock.patch.object(bootstrap.shutil, 'which', return_value='/usr/bin/pacman'), \
                mock.patch.object(bootstrap.platform, 'freedesktop_os_release', return_value={'ID': 'arch'}), \
                mock.patch.object(bootstrap, 'query', return_value=subprocess.CompletedProcess([], 0, '\n'.join(bootstrap.PACKAGES), '')):
            self.install_args()
        for path, data in existing.items():
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_wan_encryption_is_required_only_for_generated_profiles(self):
        safe = self.home / '.config/sunshine/plasmactl-safe.conf'
        safe.parent.mkdir(parents=True)
        safe.write_text('wan_encryption_mode = 0\noperator setting = true\n')
        with mock.patch.object(bootstrap.shutil, 'which', return_value='/usr/bin/pacman'), \
                mock.patch.object(bootstrap.platform, 'freedesktop_os_release', return_value={'ID': 'arch'}), \
                mock.patch.object(bootstrap, 'query', return_value=subprocess.CompletedProcess([], 0, '\n'.join(bootstrap.PACKAGES), '')):
            self.install_args()
        self.assertEqual(safe.read_text(), 'wan_encryption_mode = 0\noperator setting = true\n')
        generated = (self.home / '.config/sunshine/plasmactl-performance.conf').read_text()
        self.assertIn('wan_encryption_mode = 2', generated)

    def test_unsupported_distro_and_package_preflight_fail_before_user_writes(self):
        cases = [({'supported_installer': False, 'missing': [], 'unavailable': [], 'error': None}, 'Arch/CachyOS'),
                 ({'supported_installer': True, 'missing': [], 'unavailable': ['jq'], 'error': None}, 'Package preflight'),
                 ({'supported_installer': True, 'missing': ['jq'], 'unavailable': [], 'error': 'db unreadable'}, 'Package preflight')]
        for state, expected in cases:
            with self.subTest(state=state):
                self.state = state
                before = self.installed_files()
                with self.assertRaisesRegex(ValueError, expected):
                    self.args('install')
                self.assertEqual(self.installed_files(), before)

    def test_missing_dependencies_stop_without_explicit_install_deps(self):
        self.state['missing'] = ['jq']
        before = self.installed_files()
        with mock.patch.object(bootstrap.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Missing packages'):
                self.args('install')
        run.assert_not_called()
        self.assertEqual(self.installed_files(), before)

    def test_explicit_dependency_install_is_bounded_and_failure_stops_writes(self):
        self.state['missing'] = ['jq']
        calls = []
        def invoke(argv, **kwargs):
            calls.append(argv)
            if argv[:3] == ['sudo', '--', 'pacman']:
                raise subprocess.CalledProcessError(1, argv)
            return subprocess.CompletedProcess(argv, 0, '\n'.join(bootstrap.PACKAGES), '')
        with mock.patch.object(bootstrap.subprocess, 'run', side_effect=invoke):
            with self.assertRaises(subprocess.CalledProcessError):
                self.args('install', '--install-deps', '--yes')
        package_calls = [call for call in calls if 'pacman' in call]
        self.assertEqual(package_calls, [['sudo', '--', 'pacman', '-S', '--needed', '--noconfirm', '--', 'jq']])
        self.assertFalse(any('-Sy' in call or '-Syu' in call for call in package_calls))
        self.assertEqual(self.installed_files(), [])

    def test_successful_dependency_install_rechecks_before_publishing_cli(self):
        self.state['missing'] = ['jq']
        calls = []
        def invoke(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(argv, ['sudo', '--', 'pacman', '-S', '--needed', '--', 'jq'])
            self.state['missing'] = []
            return subprocess.CompletedProcess(argv, 0)
        with mock.patch.object(bootstrap.subprocess, 'run', side_effect=invoke):
            self.args('install', '--install-deps', '--no-configure')
        self.assertEqual(len(calls), 1)
        self.assertTrue((self.prefix / 'bin/plasmactl').is_symlink())

    def test_replace_cli_is_refused_without_flag_and_explicit_replace_receipts_exact_backup(self):
        cli = self.prefix / 'bin/plasmactl'
        cli.parent.mkdir(parents=True)
        previous = b'#!/bin/sh\nexit 17\n'
        cli.write_bytes(previous)
        cli.chmod(0o751)
        with self.assertRaisesRegex(ValueError, 'would be replaced'):
            self.install_args()
        self.assertEqual(cli.read_bytes(), previous)
        with mock.patch.object(bootstrap.shutil, 'which', return_value='/usr/bin/pacman'), \
                mock.patch.object(bootstrap.platform, 'freedesktop_os_release', return_value={'ID': 'arch'}), \
                mock.patch.object(bootstrap, 'query', return_value=subprocess.CompletedProcess([], 0, '\n'.join(bootstrap.PACKAGES), '')):
            self.install_args('--replace-cli')
        receipt = json.loads(next((self.prefix / 'share/plasmactl/receipts').glob('*/receipt.json')).read_text())
        backup_file = next((self.prefix / 'share/plasmactl/receipts').glob('*/previous-cli'))
        self.assertEqual(backup_file.read_bytes(), previous)
        self.assertEqual(backup_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(receipt['previous']['mode'], 0o751)

    def test_prefix_escape_and_symlink_directory_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'inside HOME'):
            self.args('install', '--prefix', str(self.root / 'outside'), '--skip-dependencies')
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        link = self.home / 'linked'
        link.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Unsafe user directory'):
            self.args('install', '--prefix', str(link / '.local'), '--skip-dependencies')

    def test_lock_and_modified_release_are_rejected(self):
        data_dir = self.prefix / 'share/plasmactl'
        data_dir.mkdir(parents=True)
        (data_dir / 'install.lock').symlink_to(self.root / 'target')
        with self.assertRaises(OSError):
            self.install_args()
        (data_dir / 'install.lock').unlink()
        with mock.patch.object(bootstrap.shutil, 'which', return_value='/usr/bin/pacman'), \
                mock.patch.object(bootstrap.platform, 'freedesktop_os_release', return_value={'ID': 'arch'}), \
                mock.patch.object(bootstrap, 'query', return_value=subprocess.CompletedProcess([], 0, '\n'.join(bootstrap.PACKAGES), '')):
            self.install_args('--no-configure')
        release = next((data_dir / 'versions').iterdir())
        (release / 'plasmactl').write_bytes(b'tampered')
        before = self.installed_files()
        with self.assertRaisesRegex(ValueError, 'Existing release was modified'):
            self.install_args('--no-configure')
        self.assertEqual(self.installed_files(), before)

    def test_repeat_install_preserves_existing_configuration(self):
        custom = self.home / '.config/plasmactl.conf'
        custom.parent.mkdir()
        custom.write_text('MY_SETTING=operator\n')
        with mock.patch.object(bootstrap.shutil, 'which', return_value='/usr/bin/pacman'), \
                mock.patch.object(bootstrap.platform, 'freedesktop_os_release', return_value={'ID': 'arch'}), \
                mock.patch.object(bootstrap, 'query', return_value=subprocess.CompletedProcess([], 0, '\n'.join(bootstrap.PACKAGES), '')):
            self.install_args()
            self.install_args()
        self.assertEqual(custom.read_text(), 'MY_SETTING=operator\n')

    def test_integration_arguments_are_delegated_exactly_without_sudo(self):
        for args, tool_args in ((['integration', 'prepare', '--uid', '1234', '--flag', 'a'], ['--uid', '1234', '--flag', 'a']),
                                (['integration', 'install', '--bundle', '/tmp/bundle'], ['install', '--bundle', '/tmp/bundle']),
                                (['integration', 'rollback', '--receipt', '/tmp/receipt'], ['rollback', '--receipt', '/tmp/receipt'])):
            with self.subTest(args=args), mock.patch.object(bootstrap.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                self.args(*args)
                command = run.call_args.args[0]
                self.assertEqual(command[:2], [sys.executable, '-I'])
                self.assertEqual(command[2], str(ROOT / 'tools' / ('prepare-sunshine-integration.py' if args[1] == 'prepare' else 'install-sunshine-integration.py')))
                self.assertEqual(command[3:], tool_args)
                self.assertNotIn('sudo', command)


if __name__ == '__main__':
    unittest.main()

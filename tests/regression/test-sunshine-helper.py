import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load(path):
    sys.dont_write_bytecode = True
    name = path.stem.replace('-', '_')
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load(ROOT / 'libexec/plasmactl-sunshine')
installer = load(ROOT / 'tools/install-sunshine-integration.py')
prepare = load(ROOT / 'tools/prepare-sunshine-integration.py')


class HelperArguments(unittest.TestCase):
    def test_rejects_injected_and_malformed_identity_arguments(self):
        bad = [
            ['start', 'a' * 32 + ';id', 'igpu', '1', 'wayland-0', 'safe'],
            ['start', 'a' * 32, 'igpu;id', '1', 'wayland-0', 'safe'],
            ['start', 'a' * 32, 'igpu', 'bad user', 'wayland-0', 'safe'],
            ['start', 'a' * 32, 'igpu', 'user', '../../bus', 'safe'],
            ['stop', 'a' * 32, 'igpu', 'not-an-invocation'],
        ]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                helper.validate_args(args)

    def test_accepts_only_declared_roles_profiles_and_actions(self):
        for args in (['status', 'a' * 32, 'igpu'],
                     ['start', 'a' * 32, 'dgpu', 'login_1', 'wayland-2', 'performance']):
            self.assertEqual(helper.validate_args(args)[0], args[0])
        for args in (['status', 'a' * 32, 'other'],
                     ['start', 'a' * 32, 'igpu', 'login', 'wayland-2', 'custom']):
            with self.subTest(args=args), self.assertRaises(ValueError):
                helper.validate_args(args)

    def test_policy_rejects_unauthorized_uid_and_invalid_role(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy = Path(temporary) / 'policy.json'
            policy.write_text(json.dumps({'schema': 1, 'users': {'1234': {
                'tty': 'tty2', 'gpus': {'command': '/bin/sh'}}}}))
            with mock.patch.object(helper, 'POLICY', policy), mock.patch.object(helper, 'trusted'):
                with self.assertRaisesRegex(ValueError, 'not enabled'):
                    helper.load_policy(5678)
                with self.assertRaisesRegex(ValueError, 'Invalid GPU policy'):
                    helper.load_policy(1234)
        with mock.patch.object(helper.os, 'geteuid', return_value=0), \
                mock.patch.dict(helper.os.environ, {'SUDO_UID': '0'}), \
                mock.patch.object(helper, 'operate') as operation:
            with self.assertRaisesRegex(ValueError, 'non-root sudo caller'):
                helper.main(['status', 'a' * 32, 'igpu'])
            operation.assert_not_called()

    def test_trusted_rejects_writable_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'policy'
            path.write_text('{}')
            path.chmod(0o666)
            with self.assertRaisesRegex(ValueError, 'Untrusted path'):
                helper.trusted(path)

    def test_validate_config_accepts_safe_paths_and_rejects_symlinks_or_writable_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'
            config_dir = home / '.config/sunshine'
            config_dir.mkdir(parents=True)
            config = config_dir / 'sunshine.conf'
            config.write_text('safe = true\n')
            uid = os.getuid()
            for path in (home, home / '.config', config_dir, config):
                path.chmod(0o700 if path.is_dir() else 0o600)
            helper.validate_config(config, home, uid)
            link = config_dir / 'linked.conf'
            link.symlink_to(config)
            with self.assertRaisesRegex(ValueError, 'Unsafe Sunshine config path'):
                helper.validate_config(link, home, uid)
            config_dir.chmod(0o777)
            with self.assertRaisesRegex(ValueError, 'Unsafe Sunshine config path'):
                helper.validate_config(config, home, uid)
            config_dir.chmod(0o700)
            config.chmod(0o666)
            with self.assertRaisesRegex(ValueError, 'Unsafe Sunshine config path'):
                helper.validate_config(config, home, uid)

    def test_listening_ports_uses_only_pid_owned_listener_sockets(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        try:
            ports = helper.listening_ports(os.getpid())
            self.assertIn(listener.getsockname()[1], ports)
        finally:
            listener.close()
        # A listener in the same network namespace but another process is not
        # evidence of readiness for this process.
        child = subprocess.Popen(['/usr/bin/python3', '-I', '-c',
            'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1",0)); '
            's.listen(); print(s.getsockname()[1],flush=True); sys.stdin.read(1)'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            foreign_port = int(child.stdout.readline())
            self.assertNotIn(foreign_port, helper.listening_ports(os.getpid()))
        finally:
            child.communicate('x', timeout=5)


class HelperLifecycle(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name)
        self.run = 'a' * 32
        self.invocation = 'b' * 32
        self.unit = helper.unit_name(1234, 'igpu', self.run)
        self.live = {'ActiveState': 'inactive', 'User': '1234', 'InvocationID': '', 'MainPID': '0'}
        self.calls = []
        patches = [mock.patch.object(helper, 'RUNTIME', self.runtime),
                   mock.patch.object(helper, 'trusted'), mock.patch.object(helper, 'validate_unit'),
                   mock.patch.object(helper, 'session_environment', return_value=({'PLASMACTL_RUN_ID': self.run}, '', '')),
                   mock.patch.object(helper, 'unit_properties', side_effect=lambda unit: dict(self.live)),
                   mock.patch.object(helper, 'command', side_effect=self.manager)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def manager(self, argv):
        self.calls.append(argv)
        if argv[1] == 'start':
            self.live.update(ActiveState='active', InvocationID=self.invocation)
        elif argv[1] == 'stop':
            self.live['ActiveState'] = 'inactive'

    def operate(self, action, extra):
        return helper.operate(1234, None, {}, action, self.run, 'igpu', extra)

    def test_start_and_stop_only_derived_unit_reject_replaced_invocation(self):
        result = self.operate('start', ['2', 'wayland-0', 'safe'])
        self.assertEqual(result['invocation'], self.invocation)
        self.assertEqual(self.calls, [['/usr/bin/systemctl', 'start', '--', self.unit]])
        self.live['InvocationID'] = 'c' * 32
        with self.assertRaisesRegex(ValueError, 'invocation or user changed'):
            self.operate('stop', [self.invocation])
        self.assertEqual(len(self.calls), 1)
        self.live['InvocationID'] = self.invocation
        result = self.operate('stop', [self.invocation])
        self.assertFalse(result['recorded'])
        self.assertEqual(self.calls[-1], ['/usr/bin/systemctl', 'stop', '--', self.unit])

    def test_failed_start_retains_record_and_inactive_cleanup_is_bounded(self):
        with mock.patch.object(helper, 'command', side_effect=RuntimeError('activation failed')):
            with self.assertRaises(RuntimeError):
                self.operate('start', ['2', 'wayland-0', 'safe'])
        self.assertTrue(self.operate('status', [])['recorded'])
        self.assertFalse(self.operate('stop', ['0' * 32])['recorded'])
        self.assertEqual(self.calls, [])

    def test_active_unit_without_root_record_is_never_adopted(self):
        self.live.update(ActiveState='active', InvocationID=self.invocation)
        with self.assertRaisesRegex(ValueError, 'Unowned Sunshine'):
            self.operate('status', [])
        with self.assertRaisesRegex(ValueError, 'refusing adoption'):
            self.operate('start', ['2', 'wayland-0', 'safe'])
        self.assertEqual(self.calls, [])


class InstallerBundle(unittest.TestCase):
    def fixture(self, root, uid=1234):
        bundle, backup, installed = root / 'bundle', root / 'backup', root / 'installed'
        installed.mkdir()
        home = root / 'home'
        home.mkdir()
        account = type('Account', (), {'pw_name': 'testuser', 'pw_uid': uid,
                                       'pw_gid': uid, 'pw_dir': str(home)})()
        with mock.patch.object(prepare.pwd, 'getpwuid', return_value=account):
            prepare.render(bundle, uid, 'tty2', {'igpu': '0000:00:02.0'}, ROOT)
        manifest = json.loads((bundle / 'manifest.json').read_text())
        for name, item in manifest['files'].items():
            item['destination'] = str(installed / name)
        (bundle / 'manifest.json').write_text(json.dumps(manifest))
        return bundle, backup, installed

    def test_preexisting_sudoers_failure_makes_no_installation_writes(self):
        account = type('Account', (), {'pw_name': 'testuser', 'pw_uid': 1234,
                                       'pw_gid': 1234, 'pw_dir': '/home/testuser'})()
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(prepare.pwd, 'getpwuid', return_value=account):
            root = Path(temporary)
            bundle, backup = root / 'bundle', root / 'backup'
            prepare.render(bundle, 1234, 'tty2', {'igpu': '0000:00:02.0'}, ROOT)

            def commands(argv):
                if argv == ['/usr/sbin/visudo', '-c']:
                    raise RuntimeError('pre-existing sudoers failure')

            with mock.patch.object(installer, 'run', side_effect=commands), \
                    mock.patch.object(installer, 'require_idle'), \
                    mock.patch.object(installer, 'trusted'), \
                    mock.patch.object(installer, 'POLICY', Path(temporary) / 'missing-policy'), \
                    mock.patch.object(installer, 'atomic_write') as write:
                with self.assertRaisesRegex(RuntimeError, 'pre-existing sudoers'):
                    installer.install(bundle, backup)
                write.assert_not_called()
            self.assertFalse(backup.exists())

    def test_running_managed_service_blocks_install_or_rollback(self):
        result = type('Result', (), {'stdout': '[{"active":"active"}]'})()
        with mock.patch.object(installer.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'Stop the managed Sunshine'):
                installer.require_idle(1234)

    def test_require_idle_blocks_another_managed_sunshine_uid(self):
        result = type('Result', (), {'stdout': '[{"active":"active","unit":"plasmactl-sunshine-u5678-igpu@x.service"}]'})()
        with mock.patch.object(installer.subprocess, 'run', return_value=result) as run:
            with self.assertRaisesRegex(ValueError, 'Stop the managed Sunshine'):
                installer.require_idle(1234)
        self.assertIn('plasmactl-sunshine-u*-*@*.service', run.call_args.args[0])

    def test_different_installed_uid_policy_rejects_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, backup, installed = self.fixture(root)
            policy = root / 'policy.json'
            policy.write_text(json.dumps({'schema': 1, 'users': {'5678': {'gpus': {'igpu': '0000:00:02.0'}}}}))
            with mock.patch.object(installer, 'POLICY', policy), mock.patch.object(installer, 'trusted'), \
                    mock.patch.object(installer, 'require_idle'), mock.patch.object(installer, 'run'):
                with self.assertRaisesRegex(ValueError, 'different UID'):
                    installer.install(bundle, backup)
            self.assertFalse(backup.exists())
            self.assertEqual(list(installed.iterdir()), [])

    def test_native_validators_and_install_use_captured_payload_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, backup, installed = self.fixture(root)
            expected = (bundle / 'sudoers').read_bytes()
            captured = {}
            def commands(argv):
                if argv[0] in ('/usr/sbin/visudo', '/usr/bin/systemd-analyze') and '-c' not in argv:
                    paths = [Path(arg) for arg in argv[2:] if Path(arg).is_file()]
                    for path in paths:
                        captured[path.name] = path.read_bytes()
                    if not captured:
                        for path in Path(argv[-1]).parent.iterdir():
                            captured[path.name] = path.read_bytes()
                    (bundle / 'sudoers').write_bytes(b'mutated after capture')
            with mock.patch.object(installer, 'allowed_destination', side_effect=lambda name, uid: str(installed / name)), \
                    mock.patch.object(installer, 'trusted'), mock.patch.object(installer, 'require_idle'), \
                    mock.patch.object(installer, 'POLICY', root / 'missing-policy'), \
                    mock.patch.object(installer, 'run', side_effect=commands), mock.patch.object(installer.os, 'fchown'):
                installer.install(bundle, backup)
            self.assertEqual(captured['sudoers'], expected)
            self.assertNotEqual((bundle / 'sudoers').read_bytes(), captured['sudoers'])
            self.assertEqual((installed / 'sudoers').read_bytes(), captured['sudoers'])

    def test_prepared_bundle_has_fixed_user_and_narrow_sudoers(self):
        account = type('Account', (), {'pw_name': 'testuser', 'pw_uid': 1234,
                                       'pw_gid': 1234, 'pw_dir': '/home/testuser'})()
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(prepare.pwd, 'getpwuid', return_value=account):
            out = Path(temporary) / 'bundle'
            prepare.render(out, 1234, 'tty2', {'igpu': '0000:00:02.0'}, ROOT)
            sudoers = (out / 'sudoers').read_text()
            self.assertIn('testuser ALL=(root) NOPASSWD:', sudoers)
            self.assertIn('/usr/local/libexec/plasmactl-sunshine', sudoers)
            self.assertNotRegex(sudoers, r'systemctl|systemd-run|loginctl|journalctl')
            self.assertEqual(json.loads((out / 'manifest.json').read_text())['uid'], 1234)
            unit = (out / 'plasmactl-sunshine-u1234-igpu@.service').read_text()
            self.assertIn('WorkingDirectory=/home/testuser/.config/sunshine\n', unit)

    def test_digest_mismatch_prevents_any_installed_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / 'bundle'
            bundle.mkdir()
            backup = root / 'backup'
            destination = Path('/etc/plasmactl/sunshine.json')
            payload = b'{"new": true}\n'
            manifest = {'schema': 1, 'uid': 1234, 'files': {
                'sunshine.json': {'destination': str(destination),
                                  'sha256': __import__('hashlib').sha256(payload).hexdigest(), 'mode': 0o644},
                'plasmactl-sunshine': {'destination': '/usr/local/libexec/plasmactl-sunshine',
                                       'sha256': '0' * 64, 'mode': 0o755},
                'sudoers': {'destination': '/etc/sudoers.d/plasmactl',
                            'sha256': '0' * 64, 'mode': 0o440},
                'plasmactl-sunshine-u1234-igpu@.service': {'destination': '/etc/systemd/system/plasmactl-sunshine-u1234-igpu@.service',
                            'sha256': '0' * 64, 'mode': 0o644}}}
            (bundle / 'sunshine.json').write_bytes(payload)
            for name in ('plasmactl-sunshine', 'sudoers', 'plasmactl-sunshine-u1234-igpu@.service'):
                (bundle / name).write_text('candidate')
            (bundle / 'manifest.json').write_text(json.dumps(manifest))
            # Validation reaches a deterministic digest mismatch before any privileged write.
            with self.assertRaises(ValueError), mock.patch.object(installer, 'run'), \
                    mock.patch.object(installer, 'require_idle'), \
                    mock.patch.object(installer, 'POLICY', root / 'missing-policy'):
                installer.install(bundle, backup)
            self.assertFalse(backup.exists())

    def test_install_failure_restores_old_bytes_and_removes_new_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, backup = root / 'bundle', root / 'backup'
            account = type('Account', (), {'pw_name': 'testuser', 'pw_uid': 1234,
                                           'pw_gid': 1234, 'pw_dir': str(root / 'home')})()
            (root / 'home').mkdir()
            with mock.patch.object(prepare.pwd, 'getpwuid', return_value=account):
                prepare.render(bundle, 1234, 'tty2', {'igpu': '0000:00:02.0'}, ROOT)
            manifest = json.loads((bundle / 'manifest.json').read_text())
            destination = root / 'installed'
            destination.mkdir()
            for name, item in manifest['files'].items():
                item['destination'] = str(destination / name)
            (bundle / 'manifest.json').write_text(json.dumps(manifest))
            old = destination / 'sudoers'
            old.write_bytes(b'original sudoers bytes\n')
            old.chmod(0o640)
            full_checks = 0

            def commands(argv):
                nonlocal full_checks
                if argv == ['/usr/sbin/visudo', '-c']:
                    full_checks += 1
                    if full_checks == 2:
                        raise RuntimeError('injected post-write validation failure')

            with mock.patch.object(installer, 'allowed_destination', side_effect=lambda name, uid: str(destination / name)), \
                    mock.patch.object(installer, 'trusted'), mock.patch.object(installer, 'require_idle'), \
                    mock.patch.object(installer, 'POLICY', root / 'missing-policy'), \
                    mock.patch.object(installer.os, 'fchown'), \
                    mock.patch.object(installer, 'run', side_effect=commands):
                with self.assertRaisesRegex(RuntimeError, 'injected post-write'):
                    installer.install(bundle, backup)
            self.assertEqual(old.read_bytes(), b'original sudoers bytes\n')
            self.assertEqual(old.stat().st_mode & 0o777, 0o640)
            self.assertEqual({path.name for path in destination.iterdir()}, {'sudoers'})

    def test_auto_rollback_preserves_externally_changed_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, backup, installed = self.fixture(root)
            checks = 0
            def commands(argv):
                nonlocal checks
                if argv == ['/usr/sbin/visudo', '-c']:
                    checks += 1
                    if checks == 2:
                        target = installed / 'sunshine.json'
                        target.write_text('external change')
                        raise RuntimeError('post-install validation failed')
            with mock.patch.object(installer, 'allowed_destination', side_effect=lambda name, uid: str(installed / name)), \
                    mock.patch.object(installer, 'trusted'), mock.patch.object(installer, 'require_idle'), \
                    mock.patch.object(installer, 'POLICY', root / 'missing-policy'), \
                    mock.patch.object(installer.os, 'fchown'), mock.patch.object(installer, 'run', side_effect=commands):
                with self.assertRaisesRegex(RuntimeError, 'rollback needs review') as caught:
                    installer.install(bundle, backup)
            self.assertIn('post-install validation failed', str(caught.exception.__cause__))
            self.assertEqual((installed / 'sunshine.json').read_text(), 'external change')

    def test_atomic_replacement_rejects_a_change_after_inspection(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(installer, 'trusted'), \
                mock.patch.object(installer.os, 'fchown'):
            path = Path(temporary) / 'destination'
            path.write_bytes(b'previous content')
            _, identity = installer.snapshot(path)
            path.write_bytes(b'external edit')
            with self.assertRaisesRegex(ValueError, 'File changed before replacement'):
                installer.atomic_write(path, b'candidate content', 0o600, expected=identity)
            self.assertEqual(path.read_bytes(), b'external edit')

    def test_auto_rollback_skips_later_independently_created_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, backup, installed = self.fixture(root)
            checks = 0
            rollback_started = False
            def commands(argv):
                nonlocal checks, rollback_started
                if argv == ['/usr/sbin/visudo', '-c']:
                    checks += 1
                    target = installed / 'sunshine.json'
                    if checks == 2:
                        target.unlink()
                        rollback_started = True
                        raise RuntimeError('post-install validation failed')
            snapshot = installer.snapshot
            def snapshot_with_concurrent_create(path):
                state = snapshot(path)
                if rollback_started and Path(path) == installed / 'sunshine.json' and state[0] is None:
                    Path(path).write_text('independent file')
                return state
            with mock.patch.object(installer, 'allowed_destination', side_effect=lambda name, uid: str(installed / name)), \
                    mock.patch.object(installer, 'trusted'), mock.patch.object(installer, 'require_idle'), \
                    mock.patch.object(installer, 'POLICY', root / 'missing-policy'), \
                    mock.patch.object(installer, 'snapshot', side_effect=snapshot_with_concurrent_create), \
                    mock.patch.object(installer.os, 'fchown'), mock.patch.object(installer, 'run', side_effect=commands):
                with self.assertRaisesRegex(RuntimeError, 'post-install validation failed'):
                    installer.install(bundle, backup)
            self.assertEqual((installed / 'sunshine.json').read_text(), 'independent file')


if __name__ == '__main__':
    unittest.main()

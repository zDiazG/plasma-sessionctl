#!/usr/bin/python3 -I
"""Render a reviewable host bundle. This command never installs host files."""
import argparse
import hashlib
import json
from pathlib import Path
import pwd
import re
import shutil


def render(output, uid, tty, gpus, repo):
    if uid <= 0 or not re.fullmatch(r'tty[1-9][0-9]*', tty):
        raise ValueError('A non-root UID and valid TTY are required')
    account = pwd.getpwuid(uid)
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', account.pw_name):
        raise ValueError('Unsupported account name for sudoers')
    if not gpus or len(set(gpus.values())) != len(gpus):
        raise ValueError('At least one distinct GPU PCI address is required')
    for role, pci in gpus.items():
        if role not in ('igpu', 'dgpu') or not re.fullmatch(r'[a-f0-9]{4}:[a-f0-9]{2}:[a-f0-9]{2}\.[0-7]', pci):
            raise ValueError('Invalid GPU role or PCI address')
    if not re.fullmatch(r'/[a-zA-Z0-9_./-]+', account.pw_dir):
        raise ValueError('Unsupported home path')
    output.mkdir(mode=0o700)  # Refuse reuse, including an existing symlink.
    policy = {'schema': 1, 'users': {str(uid): {'tty': tty, 'gpus': gpus}}}
    (output / 'sunshine.json').write_text(json.dumps(policy, indent=2) + '\n')
    shutil.copyfile(repo / 'libexec/plasmactl-sunshine', output / 'plasmactl-sunshine')
    template = (repo / 'config/systemd/plasmactl-sunshine.service.in').read_text()
    workdir = account.pw_dir + '/.config/sunshine'
    files = {'sunshine.json': '/etc/plasmactl/sunshine.json',
             'plasmactl-sunshine': '/usr/local/libexec/plasmactl-sunshine',
             'sudoers': '/etc/sudoers.d/plasmactl'}
    for role, pci in gpus.items():
        unit = f'plasmactl-sunshine-u{uid}-{role}@.service'
        text = template
        for key, value in {'UID': uid, 'GID': account.pw_gid, 'ROLE': role,
                           'PCI': pci, 'WORKDIR': workdir}.items():
            text = text.replace('@' + key + '@', str(value))
        (output / unit).write_text(text)
        files[unit] = '/etc/systemd/system/' + unit
    # Replaces the legacy project's broad grant. Generic systemctl/systemd-run,
    # loginctl and journalctl commands are deliberately absent.
    (output / 'sudoers').write_text(
        '# Managed plasmactl lifecycle interface\n' + account.pw_name +
        ' ALL=(root) NOPASSWD: /usr/local/libexec/plasmactl-sunshine, ' +
        '/usr/bin/chvt 1, /usr/bin/chvt ' + tty[3:] + '\n')
    manifest = {'schema': 1, 'uid': uid, 'files': {}}
    for name, destination in files.items():
        path = output / name
        path.chmod(0o600)
        manifest['files'][name] = {'destination': destination,
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'mode': 0o755 if name == 'plasmactl-sunshine' else
                                          0o440 if name == 'sudoers' else 0o644}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'manifest.json').chmod(0o600)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uid', required=True, type=int)
    parser.add_argument('--tty', default='tty2')
    parser.add_argument('--igpu')
    parser.add_argument('--dgpu')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        render(args.output, args.uid, args.tty,
               {role: value for role, value in [('igpu', args.igpu), ('dgpu', args.dgpu)] if value},
               Path(__file__).resolve().parents[1])
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f'{error}\n')
    print(f'Prepared {args.output}. Review files before installation; no host state changed.')

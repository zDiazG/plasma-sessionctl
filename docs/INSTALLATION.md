# Installation and recovery

The managed Sunshine backend is a development candidate. Prepare and inspect
the integration before changing a host. Static validation and isolated tests do
not establish a working stream. See [the lifecycle contract](../SPEC.md) for
backend limits and [the README](../README.md) for commands.

## User bootstrap

Use a complete checkout with Bash, coreutils and Python 3.10+. Both entry points
use the same implementation before sourcing any user configuration:

```bash
./install.sh plan
./plasmactl bootstrap install --dry-run --install-deps
./install.sh install --install-deps
```

Plan output is JSON and includes missing packages, repository availability,
CLI/configuration paths and read-only environment observations. A successful
plan command means the report was generated, not that the host is ready. It
never refreshes package databases or creates user directories. `--dry-run`
applies to bootstrap install/configure; the explicit integration wrapper retains
the existing tools' interfaces and has no implicit dry-run mode.

Automatic dependencies support Arch/CachyOS using existing pacman repositories.
All required missing package names must be queryable before installation. If
Sunshine is unavailable, arrange a supported package source manually and retry.
No AUR helper or repository is added. Pacman installation requires explicit
`--install-deps`; `--yes` additionally opts out of package prompts. No standalone
`-Sy` or automatic whole-system upgrade is performed. Package transactions can
have package-manager side effects and are not rolled back by the user installer.
On other distributions, install prerequisites manually, then use
`./install.sh install --skip-dependencies`.

Installation is per-user and refuses to run as root. `--prefix` must be inside
HOME and its existing directory components must be owned by that user, without
symlinks or group/other write access. The installed CLI points into
`PREFIX/share/plasmactl/versions/CONTENT_HASH`, containing its required resources.
Do not replace that symlink with a copy of only the Bash file if you need bootstrap.

An existing different CLI requires `--replace-cli`. Its previous file bytes/mode
or symlink target are recorded under `PREFIX/share/plasmactl/receipts/`. Existing
version payloads are verified before reuse. Installation does not replace any
existing user configuration, profile, application list, credential or pairing
file. New managed profiles require WAN encryption. New shell config selects
systemd-scope, performance and igpu without fallback. No JSON overlay is created;
existing overlays remain authoritative and must be reviewed.

`plasmactl bootstrap configure` performs only missing-file initialization.
`--no-configure` limits install to the user CLI/resources. If configuration
publication fails after the CLI has been published, the command fails and points
to its recovery receipt. It preserves the installed CLI; it does not claim that
the entire operation rolled back. Receipts retain previous CLI data for manual
recovery, while automatic user-CLI uninstall/rollback is not implemented yet.

This bootstrap does not prepare getty/PAM, autologin, tmux login attachment,
boot/EDID, pairing or service activation. Inspect the following prerequisites
before using the managed runtime. Initialize Sunshine credentials/pairing through
its supported Web UI flow once the reviewed service is running; existing
credentials are never reset by bootstrap.

## Preparation

Identify the desktop UID, existing seat0 TTY login, tmux session, installed native
Plasma units and GPU PCI addresses. Confirm a separate management connection and
the expected display interruption. The installer does not configure getty/PAM,
autologin, shell startup, boot/EDID or Sunshine pairing.

Initial support is one configured managed Sunshine UID per host. The generator
rejects unsupported account/home paths and duplicate GPU addresses. Existing
policy for another UID requires a deliberate migration; a second install is not
a way to add another user.

Use a new private output directory. Omit a GPU role if it is not supported by the
target host:

```bash
plasmactl bootstrap integration prepare --uid "$(id -u)" --tty tty2 \
  --igpu '<IGPU_PCI_ADDRESS>' --dgpu '<DGPU_PCI_ADDRESS>' \
  --output /tmp/plasmactl-integration
```

Review the helper, JSON policy, each generated service, sudoers and manifest.
The policy uses PCI addresses rather than unstable DRM card indices. The fixed
service runs `/usr/bin/sunshine` as the desktop UID with a DRM allowlist and a
capability bounding set. Installation does not grant new file capabilities or
add ambient capabilities. Verify the packaged binary has the capabilities needed
for the chosen capture method.

The sudoers candidate replaces `/etc/sudoers.d/plasmactl` with access to the
fixed helper and explicit TTY-switch arguments. It does not revoke unrelated
administrator grants or rules in other files. Do not reinstall the retired
static sudoers example or use an older `setup --system` implementation.

## Inactive installation

Stop existing managed executions before changing integration. The installer
checks all managed Sunshine UIDs because policy and helper paths are shared.
It refuses incompatible installed UID policy and unrelated global sudoers
validation failures before file replacement.

For an authorized installation, create a trusted backup parent and choose a new
backup directory for each attempt:

```bash
sudo install -d -m 0700 /var/lib/plasmactl
sudo "$HOME/.local/bin/plasmactl" bootstrap integration install \
  /tmp/plasmactl-integration /var/lib/plasmactl/before-sunshine-integration
```

The installer captures payload bytes and verifies their digests. Native unit and
sudoers validators read those same bytes from a private staging directory under
the trusted backup parent. Changes to the original bundle cannot substitute
different bytes during validation. This is consistency checking, not a signature
or a substitute for reviewing executable content.

Before replacement, the installer saves previous bytes, modes and groups and
records each destination's identity. Replacements are atomic per file; the whole
multi-file installation is not one atomic filesystem operation. It validates
global sudoers afterward and reloads system-manager unit definitions. It starts
no service and changes no user autostart or configuration.

Keep the backup and receipt private. Install the CLI version matching this
integration only after preserving any previous controller binary/configuration.
The helper's interpreter and manager paths are fixed under `/usr/bin` and the
validator uses `/usr/sbin/visudo`; check applicability on the target distribution.

## Activation

Check the installed helper for every enabled GPU role before starting a desktop:

```bash
sudo -n /usr/local/libexec/plasmactl-sunshine check \
  00000000000000000000000000000000 igpu
```

This verifies installed unit/user/device policy and device availability. It does
not start Sunshine or prove capture. Stop an existing Sunshine through its
original owner, and record the package user service's current enablement/state.
Only when the replacement is ready, disable its graphical-session autostart as
part of the approved migration. For packages using this unit name:

```bash
systemctl --user disable app-dev.lizardbyte.app.Sunshine.service
```

The command does not stop an already active service. Review package aliases and
custom desktop autostarts too; the controller's guard is not a complete inventory.
Do not edit package files under `/usr/lib`.

Set these Bash assignments in `~/.config/plasmactl.conf`, preserving other settings:

```bash
PLASMA_SESSION_BACKEND=systemd-scope
SUNSHINE_SUPERVISE=true
SUNSHINE_PROFILE=performance
SUNSHINE_ARGS=
SUNSHINE_CONFIG_PATH=
```

Review any JSON overrides. Profiles `normal`, `safe` and `performance` use fixed
paths described in [SPEC.md](../SPEC.md). The home, `.config`, Sunshine directory
and selected configuration must belong to the desktop UID, must not be symlinks
and must not allow group/other writes. Do not blindly change permissions on
shared directories to satisfy this requirement; resolve their ownership first.
Review referenced application files and existing encryption settings separately.

Scope start preserves existing profile/apps files. `setup --user`,
`sunshine-safe` and `sunshine-profiles` can overwrite generated assets; they are
not preservation or migration tools. Missing managed generated profiles use
mandatory WAN encryption. Existing and shipped profiles retain their settings.

An authorized runtime observation can then use:

```bash
./plasmactl --session-backend=systemd-scope --gpu=igpu start
./plasmactl status
./plasmactl stop
```

Use `--plasma-only` on start/restart to omit Sunshine. First acceptance should
observe unit identities, owned Wayland socket, selected DRM access and recovery.
Actual streaming acceptance additionally requires video, encoder and Moonlight
input observations. Socket listeners alone are insufficient. Stop may terminate
desktop applications with unsaved work; scope mode currently has no separate
console-lock, TTY-return or login-termination policy.

## Failure and rollback

If start fails, inspect its retained manifest and exact unit identities. Do not
delete ownership state, invoke legacy broad cleanup, restart the user manager or
terminate the UID to force recovery. A changed invocation or inaccessible state
requires inspection. Preserve management access throughout recovery.

Installation failure attempts restoration through the same guarded path as
manual rollback. Files are compared with their candidate/pre-install state and
revalidated immediately before mutation. An external edit causes refusal and
preserved backup evidence rather than a forced overwrite. A file absent both
before installation and during recovery is left alone. The installer/helper lock
serializes their operations; arbitrary administrator edits must still be kept
quiescent during installation or rollback.

After stopping the owned execution, rollback can use:

```bash
sudo "$HOME/.local/bin/plasmactl" bootstrap integration rollback \
  /var/lib/plasmactl/before-sunshine-integration
```

The command restores integration files and reloads definitions. It does not
restore user configuration, controller binary, package autostart, selected TTY
or every side effect of a desktop session. Restore those from their recorded
previous states and verify each. Re-enable the package user service only if it
was enabled before migration. Do not start it automatically merely because it
was previously enabled but inactive.

## Local checks

For the affected bootstrap or privileged installer/helper, run the corresponding
Python regression file without root or GPU access:

```bash
python3 -I tests/regression/test-bootstrap.py
python3 -I tests/regression/test-sunshine-helper.py
```

At an integration point, the isolated Bash cases can be grouped as follows:

```bash
bash -n plasmactl
for test_file in tests/smoke/*.bash tests/regression/*.bash; do
  bash tests/run-isolated.sh "$test_file"
done
git diff --check
```

The tests use temporary user state, command mocks and local socket fixtures;
Linux `/proc` and `jq` are needed for the relevant checks. They do not run the
real host installer, Plasma or Sunshine. Run only affected cases after a focused
correction. Native candidate validation and real lifecycle/capture tests provide
separate evidence; neither is implied by these regression results.

Bootstrap tests install real user payloads into temporary HOME directories and
simulate package queries/transactions. They do not install real system packages.
A clean-machine package installation and first-run client workflow remain
separate acceptance evidence.

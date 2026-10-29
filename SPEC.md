# Session lifecycle contract

Status: implemented development candidate. Plasma/managed Sunshine lifecycle,
Intel VAAPI initialization, device enforcement and one startup rollback scenario
have runtime evidence on one Intel setup. The maintainer reported working
Moonlight video/audio/input over a wired LAN, with occasional menu/Settings
opening flicker. Quantitative latency, loss and long-term reliability remain
unmeasured. This file describes current behavior, including its
limits; it does not certify deployment readiness.

## Supported boundary

The initial scope backend supports one graphical desktop per UID and one
configured managed Sunshine UID per host. It requires an existing seat0 TTY
login, tmux session and native Plasma user units. It does not create a PAM/login
session, configure autologin or prepare a getty.

SSH and independent background processes may coexist. Two complete graphical
desktops sharing a UID are unsupported because they share the user manager,
desktop unit names and session bus. The installer refuses to replace another
UID's managed policy and checks all managed Sunshine services for activity.

| Behavior | `legacy` | `systemd-scope` |
| --- | --- | --- |
| Default selection | Yes | Explicit configuration or CLI flag |
| Desktop identity | Process/session discovery | Boot, login, run and unit invocation record |
| Desktop shutdown | Includes UID/name-wide signals | Recorded native units and launcher scope |
| Sunshine | Legacy systemd-run/user-service/tmux modes | Fixed installed system service through helper |
| TTY return/console lock/logout settings | Existing legacy behavior | Not implemented |
| Automatic fallback on helper failure | Not applicable | None |

The retired `setup --system` command returns failure before its former getty,
shell-profile and sudoers mutations. `setup --user` remains a profile-generation
command and can replace existing generated profiles/apps.

## Configuration and CLI

Defaults that expose environment overrides are loaded first, followed by
`~/.config/plasmactl.conf`, the optional JSON overlay at
`~/.config/plasmactl/config.json`, then recognized explicit CLI overrides.
The shell configuration is sourced as the desktop user, so it is executable
configuration. It is never sourced by the root helper.

JSON requires an object; malformed configuration fails initialization. JSON
support can be controlled through `PLASMACTL_USE_JSON_CONFIG`. Without `jq`,
the legacy optional overlay can be skipped; the scope backend requires `jq`.
Help currently loads configuration and initializes directories too.

`--fix` is a compatibility flag. Diagnostics do not implement automatic repairs.

Recognized lifecycle flags include `--session-backend=legacy|systemd-scope`,
`--gpu=igpu|dgpu|auto`, `--igpu`, `--dgpu` and `--verbose`/`-v`.
`--plasma-only` is valid only for scope start/restart. Managed Sunshine requires
an explicit `igpu` or `dgpu` role. There is no config-file CLI flag or version
subcommand/flag; help displays the version.

Scope starts preserve existing Sunshine profiles/apps. Missing generated
profiles are published without overwriting existing files. New managed profiles
use mandatory WAN encryption; existing configuration retains its settings.
`normal` uses `sunshine.conf`, `safe` uses `plasmactl-safe.conf`, and
`performance` uses `plasmactl-performance.conf` under `~/.config/sunshine`.
Managed mode rejects custom Sunshine arguments and configuration paths.

## Bootstrap interface

`install.sh` and the first-position `plasmactl bootstrap` command enter the same
Python 3.10+ standard-library tool. Lifecycle remains Bash; the existing root
helper/installers remain Python. Bootstrap dispatch happens before user config,
user-context discovery and directory initialization. A malformed or executable
user shell/JSON config cannot block or execute through bootstrap plan.

- `plan`, the default action, emits a read-only JSON report.
- `install --dry-run` and `configure --dry-run` emit that report without mutation.
- `install` publishes a self-contained content-versioned user CLI and initializes
  absent configuration. It refuses existing CLI replacement without explicit
  `--replace-cli`, preserving previous data in a private receipt.
- `configure` creates absent assets without replacing operator files.
- `integration prepare|install|rollback` forwards arguments to the existing
  reviewed tools, without implicit privilege escalation or service activation.

Package installation requires explicit `--install-deps`, supports existing
Arch/CachyOS pacman repositories and rejects unavailable packages. Database-only
refresh, implicit full upgrades, AUR helpers and repository creation are excluded.
`--skip-dependencies` is an explicit manual-dependency path for other environments.
No credentials are accepted as arguments, generated, reset or printed. Bootstrap
reporting is not full runtime health: `session-check`, selected-unit status and
actual streaming acceptance remain separate checks.

Only absent bootstrap assets use secure new defaults. Existing overlays and
profiles retain their behavior. User installation is atomic per published file,
not one atomic package/configuration transaction. Package-manager effects are
not rolled back; partial configuration failure retains the published CLI and its
recovery receipt. Automatic user-CLI rollback/uninstall remain follow-up work.

## Identity, start and recovery

The private `~/.local/state/plasmactl/scope-session.json` records schema, UID,
boot/run IDs, live login/TTY, selected GPU, launcher scope, baseline active units,
tracked environment values and unit InvocationIDs. It is JSON data, not shell
code. Runtime state is not portable across boots/users.

Start refuses an existing record, competing desktop or unowned active native
unit. Duplicate start is a refusal, not idempotent success. Known native Sunshine
graphical-session autostart must be disabled or explicitly masked before start;
custom autostarts still require operator review.

The launcher receives a fresh tmux pane and a scope named
`plasmactl-plasma-<run>.scope`. KWin/plasmashell require exact run/login/GPU
process markers. Other desktop graph members require explicit membership and
absence from the pre-launch active-unit baseline when process inspection is
unavailable. Native units are not assumed to live inside the launcher scope.

Start requires active core native units and the owned shell's Wayland socket.
Managed Sunshine additionally requires its recorded invocation and TCP listeners
held by the service's current MainPID. These are startup checks, not proof of
capture, encoder selection, rendering quality or Moonlight input. Status checks
recorded unit liveness and managed Sunshine listeners; it is not an end-to-end
health check.

Stop validates the recorded desktop set, stops the recorded Sunshine first,
then stops the desktop units with a bounded wait. Changed invocations, unknown
desktop dependents and denied queries retain state for inspection. Native
service restart recovery is not automatic. Restart starts a fresh execution
only after stop succeeds and preserves backend/GPU/Plasma-only intent.

Failed start attempts clean up only their own identified execution and preserve
the original failure status. Cleanup can remain partial when ownership cannot
be proved. Tracked user-manager environment values are restored only if their
current values still match this execution's captured values. This is a whitelist,
not a complete rollback of every side effect Plasma can produce.

Lifecycle operations share a persistent `flock` inode. Cleanup does not unlink
it, and long-lived user command children close the inherited lock descriptor.
Do not mix controller generations or delete a lock while a controller is active.

## Privileged Sunshine interface

Scope launch sets both `KWIN_DRM_DEVICES` and the selected GPU's canonical
`KWIN_RENDER_NODES`. The latter limits render-device discovery on the observed
KWin 6.8.1 release. It is included in tracked environment restoration. These
compositor settings do not grant a device-access guarantee for arbitrary desktop
applications or KWin versions that ignore the render selector.

The installed `/usr/local/libexec/plasmactl-sunshine` derives the desktop UID
from sudo and accepts only:

```text
check  RUN ROLE
start  RUN ROLE SESSION WAYLAND PROFILE
status RUN ROLE
stop   RUN ROLE INVOCATION
```

Run/invocation IDs are 32 lowercase hex characters. Roles, profiles and display
identifiers have fixed validation rules. The caller cannot supply an executable,
unit name, arbitrary device path or systemd property. Root-owned policy maps
roles to stable PCI addresses. Configuration and its fixed user-owned directory
components must be non-symlink paths without group/other write access. Files
referenced from inside Sunshine configuration remain an operator responsibility.

Privilege wrappers request the intended operation with `sudo -n` directly and
preserve its failure status. They require no permission for an unrelated
`sudo true` precheck.

The service name is `plasmactl-sunshine-u<uid>-<role>@<run>.service`.
Its root-private environment record lives under `/run/plasmactl`. Sunshine runs
as the desktop UID with `DevicePolicy=closed` and explicit card/render/uinput
access. There are no added ambient capabilities; required packaged binary
capabilities must already exist. This restricts the service cgroup, not every
process owned by the user. Automatic Sunshine restart is initially disabled.

## Exit status and evidence

Successful commands return zero for their documented checks. Invalid CLI input
returns 2. Other failures return nonzero, including underlying operation failures;
there is no single exhaustive public numeric error taxonomy yet.

`session-check` returns 0 for clear known prerequisites, 1 for a detected conflict,
or 2 for unavailable/incomplete/failed prerequisite state. Unavailable state takes
precedence if both conditions occur. It activates no TTY or service.

Legacy `confirm-gpu`/`gpu-assert` diagnostics do not use the managed Sunshine
manifest. Missing journals/descriptors are inconclusive. Runtime acceptance must
observe the selected service identity, device policy, actual video/encoder/input
and recovery. See [installation and recovery](docs/INSTALLATION.md).

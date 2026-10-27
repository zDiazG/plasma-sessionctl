# plasma-sessionctl (`plasmactl`)

Bash controller for KDE Plasma Wayland sessions and Sunshine streaming, with selectable GPU roles.

Development candidate. The legacy backend remains the default. The managed backend has runtime evidence on one Intel setup; other deployments need their own acceptance checks.

![Shell](https://img.shields.io/badge/shell-bash-4EAA25?logo=gnubash&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Linux-informational)
![Desktop](https://img.shields.io/badge/desktop-KDE%20Plasma%20Wayland-blue)
![Streaming](https://img.shields.io/badge/streaming-Sunshine-orange)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)

`plasmactl` selects a DRM GPU, launches Plasma from an existing TTY/tmux setup,
and coordinates Sunshine. The opt-in `systemd-scope` backend records session and
unit identities; the legacy backend still uses process discovery and UID-wide
cleanup. These backends have different safety and privilege contracts.

See [SPEC.md](SPEC.md) for the implemented interfaces and limits, and
[docs/INSTALLATION.md](docs/INSTALLATION.md) for preparation, installation,
activation and recovery. A running unit or an open TCP port does not establish a
working Moonlight stream.

---

## Table of Contents

- [About](#about)
- [Requirements](#requirements)
- [Installation & Sudoers](#installation--sudoers)
- [Usage & Commands](#usage--commands)
- [Configuration (`plasmactl.conf`)](#configuration-plasmactlconf)

---

## About

Running a remote streaming desktop with KDE Plasma Wayland and Sunshine on multi-GPU setups (e.g. Intel iGPU + AMD/Nvidia dGPU) or headless nodes introduces a few recurring issues:

1. **GPU Binding & Interference**: KWin or Sunshine may bind to the discrete GPU during idle desktop streaming, wasting power or locking device nodes needed by passthrough/secondary tasks.
2. **Headless Display Output**: Plasma Wayland requires an active KMS connector/EDID to spawn display outputs.
3. **Session Lifecycle & Clean Termination**: Starting Plasma manually inside a headless session can leave orphaned processes (`kwin_wayland`, `sunshine`, `systemd-run` transient units) if interrupted.
4. **Privilege & Multi-User Safety**: Session commands must run strictly scoped under the target user (`REAL_USER`), preventing cross-user session termination on shared hosts.

### Current behavior

- Scope GPU selection passes `KWIN_DRM_DEVICES` and the matching `KWIN_RENDER_NODES` to Plasma. This selects the compositor's display and render devices; it does not restrict every process's device access. Legacy launch sets only the display selector.
- The managed Sunshine candidate uses a fixed system service under the desktop UID with a DRM device allowlist. The restriction covers that service and its children.
- The scope backend records launcher/native-unit identities and stops the recorded Sunshine before desktop teardown. The default legacy backend retains UID-wide process cleanup.
- Scope starts preserve existing Sunshine profiles and application lists. Explicit profile-generation commands can replace those assets.
- EDID/bootloader operations are separate commands and require a host-specific recovery plan.
- Legacy GPU diagnostics inspect processes, journals and descriptors. They have not been migrated to the managed Sunshine identity and can be inconclusive.

---

## Requirements

- **OS**: Linux with `systemd`, `loginctl`, and `chvt`.
- **Desktop**: KDE Plasma Wayland (`startplasma-wayland`, `kwin_wayland`).
- **Streamer**: Sunshine (`sunshine`).
- **Session Manager**: `tmux`.
- **Privileges**: reviewed caller-specific helper policy for the scope backend. The legacy unrestricted sudoers grant is retired.
- **Scope backend**: `jq`, `busctl`, `systemd-run` and `flock`; Python 3 for the managed Sunshine helper. Installed native Plasma units and an existing login/tmux session are required.
- **Legacy JSON overlay**: optional `jq`. Only the observed systemd/Plasma combination has runtime evidence; other versions need validation.

---

## Installation & Sudoers

Start from a checkout and inspect the supported commands:

```bash
git clone https://github.com/zDiazG/plasma-sessionctl.git
cd plasma-sessionctl
chmod +x plasmactl
./plasmactl --help
```

Follow [the installation guide](docs/INSTALLATION.md). It separates bundle
preparation, validation, inactive installation, user configuration and activation.
The old unrestricted sudoers example and `setup --system` installer are retired.
Getty/PAM, tmux console setup, autologin and boot changes remain separate host
operations.

### What installation currently covers

The central CLI is the Bash script `plasmactl`. It provides lifecycle commands,
`status`, `doctor`, `session-check`, `sanity` and configuration/profile generation.
It can be installed as an executable on your PATH; the managed Sunshine helper
has its own fixed privileged installation path.

To install only the user CLI from this checkout:

```bash
install -Dm755 plasmactl "$HOME/.local/bin/plasmactl"
```

Ensure `~/.local/bin` is on your PATH. This copies the controller; it does not
install its dependencies or privileged integration.

There is no `install.sh` or complete fresh-machine bootstrap yet. Install the
requirements listed above through your distribution's supported packages first.
Current setup tools assume Plasma, Sunshine, the existing seat0 login and tmux
environment are already available:

| Entry point | Current responsibility |
| --- | --- |
| `plasmactl setup --user` | Create a missing shell config and regenerate Sunshine profile/apps assets |
| `tools/prepare-sunshine-integration.py` | Render the host-specific helper, policy, units and sudoers bundle |
| `tools/install-sunshine-integration.py` | Install or restore reviewed integration files without activating services |
| `plasmactl doctor` / `session-check` | Diagnose prerequisites and conflicts; do not install dependencies or repair the host |
| `plasmactl status` | Inspect the selected backend; managed status checks owned units and Sunshine listeners |

Sunshine installation, initial credentials/pairing and a complete dependency
installer are not implemented by these commands. Some diagnostics still use
legacy discovery; see [the diagnostic limits](#gpu-selection-and-evidence-limits).

`setup --user`, `sunshine-safe` and `sunshine-profiles` regenerate profile assets;
back up customized profiles and application lists before using them. Preservation
of existing assets applies to scope startup, not all generation commands.

---

## Usage & Commands

### Subcommands

```bash
plasmactl start                 # Start using the configured backend and Sunshine setting
plasmactl --igpu start          # Select the integrated GPU role
plasmactl --dgpu start          # Select the discrete GPU role
plasmactl stop                  # Stop using the recorded/configured backend
plasmactl restart               # Stop active session and start a new one
plasmactl status                # Inspect backend state; does not prove streaming
plasmactl session-check         # Inspect login and user-unit prerequisites for a new execution
plasmactl sanity                # Validate binaries, DRM nodes, TTYs, and permissions
plasmactl detect-gpu            # Auto-detect available iGPU and dGPU cards and drivers
plasmactl confirm-gpu igpu       # Legacy GPU diagnostic (alias: confirm-igpu)
plasmactl confirm-gpu dgpu       # Legacy GPU diagnostic (alias: confirm-dgpu)
plasmactl setup --user          # Prepare user configuration and profiles
plasmactl debug                 # Print detailed runtime environment diagnostics
```

`doctor` completes its diagnostics and returns nonzero when critical checks fail.
`--fix` remains accepted for compatibility but performs no automatic repairs.

`session-check` queries logind and the user systemd manager. It returns `0` when
its known prerequisites are clear, `1` when it detects a conflicting desktop or
active desktop unit, and `2` when required state is unavailable, incomplete or
failed. If both conflict and unavailable state occur, `2` takes precedence.
It does not activate a TTY, start units or stop processes. It checks login types
and four desktop units; standalone compositors may require additional detection.
A successful check does not prove scope launch, GPU access or streaming works.
The default legacy backend has not migrated to this ownership model.

### Experimental scope backend

The opt-in `systemd-scope` backend manages Plasma and includes a candidate
Sunshine integration through a restricted installed helper. The default remains
`legacy`, whose existing UID-wide shutdown behavior has not been removed.

After reviewing the target TTY, GPU and recovery path, a controlled runtime probe
can use these commands from this checkout:

```bash
./plasmactl --session-backend=systemd-scope --plasma-only --gpu=igpu start
./plasmactl status
./plasmactl stop
```

Start may activate the configured physical TTY. This backend runs as the desktop
user and attempts activation without an interactive password prompt. It requires
`jq`, `busctl`, `systemd-run`, `flock`, the installed native Plasma units and the
configured tmux session. It creates a dedicated detached tmux window and passes
arguments directly, without injecting commands or Ctrl-C into an existing pane.

The private `scope-session.json` state records the boot, login, GPU, scope and
unit invocation identities. KWin and plasmashell require the execution marker,
login ID and GPU in their process environments. Auxiliary desktop units can
instead use their explicit desktop lifetime relationship and the pre-launch
active-unit baseline, including when MainPID is zero or /proc is protected.
Stop refuses changed invocations. It can refresh late desktop dependents only
while the recorded scope and both core process identities still match. An existing state
record routes stop/status through this backend even if the default configuration
is later changed; legacy start and cleanup cannot discard it.

Plasma and managed Sunshine start/status/restart/stop have been exercised on one
Intel/Plasma setup. A device-open probe confirmed that Sunshine's cgroup permits
the selected Intel nodes and denies the other GPU. KWin reported Intel rendering
and Sunshine initialized its Intel VAAPI H.264 encoder. The maintainer reported
working Moonlight video, audio and input over a wired LAN, with improved perceived
stability and occasional flicker when opening Plasma menus or Settings. This is
one observed workflow, not a measured performance or long-term reliability claim.
On KWin 6.8.1, the render selector also prevented KWin from retaining the other
GPU's render node. Older KWin releases may ignore that selector and need their
own descriptor checks.
Start checks the owned shell's Wayland socket before completing. Sunshine
readiness requires the recorded service invocation and TCP listeners held by its
main process. These checks do not prove video capture, encoding or Moonlight input.
Use `--plasma-only` to omit Sunshine. Known services enabled through graphical-session.target
must be disabled or explicitly runtime-masked first, otherwise start refuses
before desktop activation. Other custom desktop autostarts still require review.
Stop does not apply legacy console lock, TTY return or login/session termination
policies. Failed startup attempts rollback only for the execution created by that
attempt. Identity mismatches and unresolved partial states retain the record for
review. A rejected Sunshine configuration has exercised startup rollback on that
host; this does not cover every failure mode. Automatic native service restarts can change invocation IDs
and require review. Plasma can change other user-manager environment
values beyond the tracked session variables. These limits remain open work.

Lifecycle commands use a persistent kernel lock. Cleanup never unlinks that
lock file, and an active legacy PID lock is rejected. Use the same controller
version for all lifecycle operations; older versions do not understand the new
lock format. Reverting to an older controller requires an explicit migration
with all controllers stopped, rather than deleting a live lock.

#### Prepare managed Sunshine integration

Use [the installation guide](docs/INSTALLATION.md) to render and review a
caller-specific bundle. It contains the helper, fixed per-GPU units, policy and
sudoers, plus a separate installer/rollback command. It does not configure or
restart a getty. Initial support is one configured desktop UID per host.

The managed Sunshine path is a development candidate. Isolated tests and unit
syntax checks do not establish capture, device enforcement or streaming.

### Flags

- `--igpu` — Force session to run on the Integrated GPU (iGPU).
- `--dgpu` — Force session to run on the Discrete GPU (dGPU).
- `--gpu=<role>` — Select `igpu`, `dgpu` or `auto`; managed Sunshine requires an explicit role.
- `--verbose` — Enable verbose debug logging output during execution.
- `--session-backend=legacy|systemd-scope` — Select the lifecycle backend.
- `--plasma-only` — Omit Sunshine for scope `start` or `restart`.
- `--fix` — Auto-apply fixes where applicable (used with `sanity`).
- `-h`, `--help` — Show CLI help reference.

`-v` means verbose. `--config`, `--version`, `version`, `up` and `down` are not implemented. The help banner includes the script version.

### Sunshine streaming profiles

Pre-configured templates are located in the `sunshine/` directory:

- `plasmactl-performance.conf` — High bitrate (20 Mbps), VAAPI hardware encoding, lower quantization parameter (`qp=14`), KMS capture.
- `plasmactl-safe.conf` — Fallback profile using software encoding and conservative bitrate parameters for troubleshooting.
- `plasmactl-apps-performance.json` / `plasmactl-apps-safe.json` — Application rules with standard launch shortcuts for **Desktop** and **Steam Big Picture** (`setsid steam -gamepadui`).

### GPU selection and evidence limits

`confirm-gpu`, `confirm-igpu`, `confirm-dgpu` and `gpu-assert` still use legacy
unit/process discovery. They are not acceptance checks for a managed Sunshine
run. Prefer its recorded unit and invocation when collecting future runtime
evidence.

`KWIN_DRM_DEVICES` expresses the intended compositor selection. Open DRM
file descriptors show observed handles at one instant; missing or inaccessible
handles are inconclusive. A permission error alone does not identify which
access control caused it. Confirming device policy requires checking the unit
policy and an authorized runtime probe. Confirming streaming requires observed
video, encoding and client input.

Missing journal or `/proc` access should be reported as missing evidence.
Do not restore broad sudoers grants to make diagnostics pass. Client GPU logs
refer to client decoding hardware; idle host utilization also does not identify
the encoder selected during a stream.

---

## Configuration (`plasmactl.conf`)

`plasmactl` reads settings from `~/.config/plasmactl.conf` (sourced Bash assignments) and optionally merges JSON overlays from `~/.config/plasmactl/config.json`.

### Shell configuration

```bash
# Session & TTY Defaults
SESSION=plasma
TTY_NAME=tty2
ACTIVATE_TTY_ON_START=true
REQUIRE_ACTIVE_TTY_ON_START=true

# Stop Behavior & Locks
LOCK_TMUX_ON_STOP=true
KILL_TMUX_ON_STOP=false
TERMINATE_TTY_SESSION_ON_STOP=false
RETURN_TTY_ON_STOP=true
RETURN_TTY_NAME=tty2

# GPU Policy & Driver Filtering
PLASMA_GPU_DEFAULT=igpu
PLASMA_GPU_ALLOW_FALLBACK=false
PLASMA_GPU_IGPU_DRIVERS="i915 xe"
PLASMA_GPU_DGPU_DRIVERS="amdgpu nvidia nouveau"
PLASMA_DRM_DEVICE=auto
PLASMA_DRM_DRIVER_ORDER="i915 xe amdgpu"

# Headless & Display Output
HEADLESS_MODE=none                    # none | kernel-forced-edid | vkms
HEADLESS_FORCE_OUTPUT=HDMI-A-1
HEADLESS_FORCE_MODE=1920x1080@60
HEADLESS_EDID_FILE=edid_1080p.bin
REQUIRE_CONNECTED_OUTPUT_ON_START=true

# Sunshine Integration & Transient Unit Policy
SUNSHINE_START_MODE=systemd-run       # systemd-run | tmux | systemd | auto
SUNSHINE_PROFILE=performance          # performance | safe
SUNSHINE_IGPU_LIBVA_DRIVER_NAME=iHD
SUNSHINE_UDP_PORTS="47998 47999 48000 48002 48010"
SUNSHINE_SYSTEMD_ISOLATE_DRI=true
SUNSHINE_SYSTEMD_ASSERT_MODE=journal
```

### JSON overlay (`config.json`)

If `jq` is available, `plasmactl` can load configuration options from `~/.config/plasmactl/config.json`:

```json
{
  "drm": {
    "gpu_default": "igpu",
    "gpu_allow_fallback": false,
    "require_connected_output_on_start": true
  },
  "sunshine": {
    "profile": "performance",
    "start_mode": "systemd-run",
    "systemd": {
      "isolate_dri": true,
      "assert_mode": "journal"
    }
  }
}
```

---

## License

Source headers declare GNU General Public License v3.0 or later. A standalone
LICENSE file is not included in this checkout; distributing the license text
remains a packaging task.

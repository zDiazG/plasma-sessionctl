# plasma-sessionctl (`plasmactl`)

**Bash controller for isolated KDE Plasma Wayland sessions streamed via Sunshine, with multi-GPU (iGPU/dGPU) selection and systemd cgroup isolation.**

*README v0.4.3.1*

![Shell](https://img.shields.io/badge/shell-bash-4EAA25?logo=gnubash&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Linux-informational)
![Desktop](https://img.shields.io/badge/desktop-KDE%20Plasma%20Wayland-blue)
![Streaming](https://img.shields.io/badge/streaming-Sunshine-orange)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)

`plasmactl` (from `plasma-sessionctl`) is a Bash controller that manages isolated, headless, or remote-desktop KDE Plasma Wayland sessions streamed through [Sunshine](https://github.com/LizardByte/Sunshine) and Moonlight.

It handles TTY allocation, session lifecycle inside `tmux`, hardware-level GPU selection (`--igpu` vs `--dgpu`), systemd device-cgroup isolation via `systemd-run`, headless EDID injection, dynamic Sunshine configuration profile generation, and empirical isolation verification.

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

`plasmactl` orchestrates the entire session lifecycle to address these.

### What it actually does

- **GPU role isolation**: switches between `--igpu` and `--dgpu` on the fly; enforces device restrictions at the kernel DRM level (`KWIN_DRM_DEVICES`) and at the systemd cgroup level (`DeviceAllow`).
- **Systemd-run isolation**: runs Sunshine as a transient systemd scope with restricted `/dev/dri/cardX` and `/dev/dri/renderDX` access, preventing it from touching unassigned GPUs.
- **Headless EDID**: supports kernel/DRM connector forced EDID injection (`HEADLESS_MODE=kernel-forced-edid`), removing the need for physical HDMI dummy plugs.
- **Dynamic Sunshine profiles**: generates `safe` and `performance` configurations at startup with tuned encoder settings (VAAPI, bitrate, QP, FEC).
- **Process scoping**: all `pkill`/`pgrep` calls are bound to `REAL_USER` (`-u "$REAL_USER"`), ensuring multi-user safety.
- **Syslog reporting**: runtime failures emit structured alerts to `logger` / systemd journal (`plasma-sessionctl`).
- **Empirical verification**: `confirm-gpu` checks active isolation via `/proc/$PID/fd` file descriptors and systemd journal logs.

---

## Requirements

- **OS**: Linux (kernel 5.15+) with `systemd`, `loginctl`, and `chvt`.
- **Desktop**: KDE Plasma Wayland (`startplasma-wayland`, `kwin_wayland`).
- **Streamer**: Sunshine (`sunshine`).
- **Session Manager**: `tmux`.
- **Privileges**: sudoers snippet for `chvt` and `systemd-run` (see [Installation & Sudoers](#installation--sudoers)).
- **Optional**: `jq` (for JSON configuration overlays in `~/.config/plasmactl/config.json`).

---

## Installation & Sudoers

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-user/plasma-sessionctl.git
   cd plasma-sessionctl
   ```

2. **Make `plasmactl` executable and move to PATH**:
   ```bash
   chmod +x plasmactl
   sudo cp plasmactl /usr/local/bin/
   ```

3. **Install sudoers permissions**:
   `plasmactl` requires limited sudo privileges for virtual terminal switching (`chvt`) and launching transient systemd units (`systemd-run`).

   ```bash
   # Copy sudoers template and edit <USERNAME> to match your Linux user
   sudo cp config/sudoers.d/plasmactl /etc/sudoers.d/plasmactl
   sudo sed -i "s/<USERNAME>/$USER/g" /etc/sudoers.d/plasmactl
   sudo chmod 0440 /etc/sudoers.d/plasmactl
   sudo visudo -cf /etc/sudoers.d/plasmactl
   ```

4. **Initialize user configurations & Sunshine profiles**:
   ```bash
   # Automated setup via plasmactl
   plasmactl setup --user

   # Or manually copy templates:
   mkdir -p ~/.config/plasmactl ~/.config/sunshine
   cp config/plasmactl.conf.example ~/.config/plasmactl.conf
   cp sunshine/* ~/.config/sunshine/
   ```

---

## Usage & Commands

### Subcommands

```bash
plasmactl start                 # Start default Plasma + Sunshine session (alias: up)
plasmactl --igpu start          # Start session explicitly locked to iGPU
plasmactl --dgpu start          # Start session explicitly locked to dGPU
plasmactl stop                  # Stop current session & lock session state (alias: down)
plasmactl restart               # Stop active session and start a new one
plasmactl status                # Show active session, tmux, and GPU binding status
plasmactl sanity                # Validate binaries, DRM nodes, TTYs, and permissions
plasmactl sanity --fix          # Validate setup and attempt automatic correction
plasmactl detect-gpu            # Auto-detect available iGPU and dGPU cards and drivers
plasmactl confirm-gpu igpu      # Verify empirical GPU isolation for iGPU (or confirm-igpu)
plasmactl confirm-gpu dgpu      # Verify empirical GPU isolation for dGPU (or confirm-dgpu)
plasmactl setup --user          # Initialize user config directories and template files
plasmactl setup --system        # Check system sudoers configuration
plasmactl debug                 # Print detailed runtime environment diagnostics
plasmactl version               # Display plasmactl script version info
```

### Flags

- `--igpu` — Force session to run on the Integrated GPU (iGPU).
- `--dgpu` — Force session to run on the Discrete GPU (dGPU).
- `--gpu=<role>` — Select GPU role explicitly (`igpu` or `dgpu`).
- `--verbose` — Enable verbose debug logging output during execution.
- `--config=<path>` — Specify a custom configuration file path.
- `--fix` — Auto-apply fixes where applicable (used with `sanity`).
- `-h`, `--help` — Show CLI help reference.
- `-v`, `--version` — Display version information.

### Sunshine streaming profiles

Pre-configured templates are located in the `sunshine/` directory:

- `plasmactl-performance.conf` — High bitrate (20 Mbps), VAAPI hardware encoding, lower quantization parameter (`qp=14`), KMS capture.
- `plasmactl-safe.conf` — Fallback profile using software encoding and conservative bitrate parameters for troubleshooting.
- `plasmactl-apps-performance.json` / `plasmactl-apps-safe.json` — Application rules with standard launch shortcuts for **Desktop** and **Steam Big Picture** (`setsid steam -gamepadui`).

### GPU isolation verification

`plasmactl` does not rely on client-side reporting to verify GPU selection. The `confirm-gpu` command checks low-level kernel handles to verify true isolation:

```bash
plasmactl confirm-igpu
```

Sample output (verified iGPU isolation):
```text
CONFIRM_TAG=confirm:igpu
CONFIRM_RESULT=OK
KWIN_DRM_DEVICES=/dev/dri/card1
/dev/dri/card2: Operation not permitted
/dev/dri/card1 -> i915
Creating encoder [h264_vaapi]
Sunshine FDs: /dev/dri/card1 and /dev/dri/renderD128 only
```

- `KWIN_DRM_DEVICES` ensures KWin only sees the target card.
- `Operation not permitted` confirms systemd device cgroups successfully block Sunshine from accessing unassigned GPUs.
- File descriptors are inspected via `/proc/$PID/fd` of Sunshine to prove no open handles exist for non-target DRM nodes.

### Known caveats

- **Moonlight client logs** reflect client decoding hardware, not host encoding. Use `plasmactl confirm-gpu` on the host for authoritative proof.
- **Idle GPU utilization**: tools like `nvtop` or `intel_gpu_top` may show negligible GPU activity when the desktop is completely static.
- **Journal permissions**: if `confirm-gpu` reports inability to read systemd logs, ensure your user is in the `systemd-journal` group or that `/usr/bin/journalctl` is allowed in `/etc/sudoers.d/plasmactl`.

---

## Configuration (`plasmactl.conf`)

`plasmactl` reads settings from `~/.config/plasmactl.conf` (INI/bash syntax) and optionally merges JSON overlays from `~/.config/plasmactl/config.json`.

### INI configuration

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

This project is licensed under the [GNU General Public License v3.0 or later](LICENSE).

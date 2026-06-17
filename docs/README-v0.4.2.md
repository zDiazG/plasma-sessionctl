# plasma-sessionctl / plasmactl v0.4.2

`plasmactl` is a Bash controller for a headless KDE Plasma Wayland session streamed through Sunshine/Moonlight on a multi-GPU Linux workstation.

This release is built for the validated `WhiteDwarf` topology:

- iGPU: Intel UHD 630, driver `i915`, preferred/default session GPU.
- dGPU: AMD RX 5500 XT, driver `amdgpu`, may keep a dummy plug connected for compute/LLM availability.
- Session: `getty@tty2` autologin -> `tmux` session `plasma` -> `startplasma-wayland`.
- Streaming: Sunshine launched by transient `systemd-run`, not inside tmux, with only the selected GPU allowed.

## What v0.4.2 fixes

v0.4.x moved Sunshine from tmux to `systemd-run` because Sunshine KMS capture could select the dGPU when both iGPU and dGPU had connected outputs. The successful design is:

- Plasma/KWin still starts inside the real `tty2`/tmux session.
- Sunshine starts as a transient system unit.
- `DevicePolicy=closed` blocks all devices by default.
- `DeviceAllow=/dev/dri/cardX` and `DeviceAllow=/dev/dri/renderDY` expose only the selected GPU to Sunshine.
- `adapter_name` and `output_name` are intentionally unset. Sunshine auto-selects within the restricted device view.
- `confirm-gpu` commands provide tagged runtime proof for iGPU/dGPU.

v0.4.2 also fixes a stray `warn` call from v0.4.1 and rejects the common typo `-dgpu`/`-igpu`; use `--dgpu`/`--igpu`.

## File layout

```text
plasmactl                                      Main executable
README.md                                      This document
config/plasmactl.conf.example                  Shell runtime config
config/plasmactl/config.json                   Optional JSON overlay config
config/plasmactl/profiles.json                 Profile manifest
config/sudoers.d/plasmactl                     Example sudoers rule
sunshine/plasmactl-performance.conf            Sunshine performance profile
sunshine/plasmactl-apps-performance.json       Sunshine apps for performance profile
sunshine/plasmactl-safe.conf                   Sunshine safe fallback profile
sunshine/plasmactl-apps-safe.json              Sunshine apps for safe profile
docs/README-v0.4.2.md                          Copy of this README
```

## Install / update

```bash
cd ~/Projects/repos/plasma-sessionctl
cp ~/bin/plasmactl ~/bin/plasmactl.pre-v0.4.2.$(date +%Y%m%d-%H%M%S)
install -m 755 ./plasmactl ~/bin/plasmactl

mkdir -p ~/.config/plasmactl ~/.config/sunshine
cp ./config/plasmactl.conf.example ~/.config/plasmactl.conf
cp ./config/plasmactl/config.json ~/.config/plasmactl/config.json
cp ./config/plasmactl/profiles.json ~/.config/plasmactl/profiles.json
cp ./sunshine/plasmactl-performance.conf ~/.config/sunshine/
cp ./sunshine/plasmactl-apps-performance.json ~/.config/sunshine/
cp ./sunshine/plasmactl-safe.conf ~/.config/sunshine/
cp ./sunshine/plasmactl-apps-safe.json ~/.config/sunshine/
```

Recommended sudoers rule:

```bash
sudo install -m 440 ./config/sudoers.d/plasmactl /etc/sudoers.d/plasmactl
sudo visudo -cf /etc/sudoers.d/plasmactl
```

## Command reference

### Start default iGPU session

```bash
plasmactl --igpu start --verbose
```

Equivalent when `PLASMA_GPU_DEFAULT=igpu`:

```bash
plasmactl start --verbose
```

### Start dGPU session override

```bash
plasmactl --dgpu start --verbose
# or
plasmactl --gpu=dgpu start --verbose
```

Do not use `-dgpu`. v0.4.2 rejects that typo.

### Stop session

```bash
plasmactl stop
```

### Status and diagnostics

```bash
plasmactl status
plasmactl sanity
plasmactl detect-gpu
plasmactl debug
```

### Confirm selected GPU isolation

Use these after Moonlight has connected, or while Sunshine is online.

```bash
plasmactl confirm-gpu igpu
plasmactl confirm-gpu dgpu
plasmactl confirm-igpu
plasmactl confirm-dgpu
```

The confirmation output includes a stable tag:

```text
CONFIRM_TAG=confirm:igpu
CONFIRM_RESULT=OK
```

or:

```text
CONFIRM_TAG=confirm:dgpu
CONFIRM_RESULT=OK
```

For iGPU mode, the expected proof is:

```text
KWIN_DRM_DEVICES=/dev/dri/card1
/dev/dri/card2: Operation not permitted
/dev/dri/card1 -> i915
Screencasting with KMS
Creating encoder [h264_vaapi]
vaapi vendor: Intel iHD driver
Sunshine FDs: /dev/dri/card1 and /dev/dri/renderD128 only
```

For dGPU mode, the expected proof is:

```text
KWIN_DRM_DEVICES=/dev/dri/card2
/dev/dri/card1: Operation not permitted
/dev/dri/card2 -> amdgpu
vaapi vendor: Mesa Gallium ... AMD Radeon RX 5500 XT
Sunshine FDs: /dev/dri/card2 and /dev/dri/renderD129 only
```

## Configuration spec

### GPU role policy

```bash
PLASMA_GPU_DEFAULT=igpu
PLASMA_GPU_ALLOW_FALLBACK=false
PLASMA_GPU_IGPU_DRIVERS="i915 xe"
PLASMA_GPU_DGPU_DRIVERS="amdgpu nvidia nouveau"
```

`PLASMA_GPU_DEFAULT=igpu` keeps the stream session on the Intel iGPU. Use `--dgpu` for a one-shot dGPU override.

### DRM selection

```bash
PLASMA_DRM_DEVICE=auto
PLASMA_DRM_DRIVER_ORDER="i915 xe amdgpu"
REQUIRE_CONNECTED_OUTPUT_ON_START=true
ALLOW_VKMS=false
```

`auto` selects a real DRM card matching the requested GPU role. `REQUIRE_CONNECTED_OUTPUT_ON_START=true` prevents starting a KMS stream against a GPU with no active connector.

### Headless EDID

```bash
HEADLESS_MODE=kernel-forced-edid
HEADLESS_FORCE_OUTPUT=HDMI-A-1
HEADLESS_FORCE_MODE=1920x1080@60
HEADLESS_EDID_FILE=white_1080p.bin
```

The validated setup uses a forced EDID on the iGPU HDMI connector. BIOS must expose the iGPU even without a physical monitor.

### Sunshine systemd-run isolation

```bash
SUNSHINE_START_MODE=systemd-run
SUNSHINE_SYSTEMD_ISOLATE_DRI=true
SUNSHINE_SYSTEMD_UNIT_PREFIX=sunshine-plasmactl
SUNSHINE_SYSTEMD_REQUIRE_CAP_SYS_ADMIN=true
SUNSHINE_SYSTEMD_DEVICE_ALLOW_UINPUT=true
SUNSHINE_SYSTEMD_ASSERT_MODE=journal
SUNSHINE_SYSTEMD_FD_ASSERT_STRICT=false
```

`journal` assertion mode checks Sunshine journal proof without killing a valid unit before the first Moonlight launch. FD checks remain diagnostic unless strict mode is explicitly enabled.

### Sunshine adapter/output policy

```bash
SUNSHINE_ADAPTER_MODE=auto
SUNSHINE_ADAPTER_NAME=
SUNSHINE_OUTPUT_MODE=disabled
SUNSHINE_OUTPUT_NAME=
```

Do not set `adapter_name` or `output_name` in systemd-run isolation mode. The selected GPU is enforced by `DeviceAllow`.

### Performance profile

```bash
SUNSHINE_PERF_ENCODER=vaapi
SUNSHINE_PERF_CAPTURE=kms
SUNSHINE_PERF_MAX_BITRATE=20000
SUNSHINE_PERF_QP=14
SUNSHINE_PERF_FEC=5
SUNSHINE_PERF_FPS_TARGET=60
SUNSHINE_PERF_HEVC_MODE=1
SUNSHINE_PERF_AV1_MODE=1
SUNSHINE_IGPU_LIBVA_DRIVER_NAME=iHD
```

The iGPU baseline is H.264 VAAPI. HEVC/AV1 are disabled for stability on UHD 630-class hardware. Raise bitrate later only after the iGPU path remains stable.

## Validation workflow

```bash
plasmactl stop
plasmactl --igpu start --verbose
# connect Moonlight
plasmactl confirm-igpu

plasmactl stop
plasmactl --dgpu start --verbose
# connect Moonlight
plasmactl confirm-dgpu
```

## Known caveats

- Moonlight client logs showing the client GPU are not proof that the workstation dGPU is being used. The authoritative proof is Sunshine journal + Sunshine/KWin `/proc/$pid/fd`.
- `nvtop` may show very low usage on both GPUs while the desktop is idle. Use `confirm-gpu` for proof.
- If `confirm-gpu` cannot read systemd journal, add `/usr/bin/journalctl` to the `plasmactl` sudoers rule.
- A connected dummy on the dGPU is supported; Sunshine is blocked from it in iGPU mode by systemd device isolation.

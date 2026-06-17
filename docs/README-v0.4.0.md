# plasmactl v0.4.0 baseline

This config set keeps Plasma/KWin on tty2/tmux and starts Sunshine via a transient systemd-run unit.
The Sunshine unit uses `DevicePolicy=closed` and `DeviceAllow=` for only the selected DRM card/render node.

Default role: iGPU.
One-shot override: `plasmactl --dgpu start --verbose` or `plasmactl --igpu start --verbose`.

Important: in systemd-run mode, keep `SUNSHINE_ADAPTER_MODE=auto`, leave `SUNSHINE_ADAPTER_NAME=` empty, and keep `SUNSHINE_OUTPUT_MODE=disabled`.

# Changelog

## 0.5.0

- Add an opt-in owned systemd Plasma session backend and restricted Sunshine lifecycle integration.
- Pin Intel rendering to the selected GPU and improve CLI failure handling and recovery.
- Add read-only installation planning, explicit dependency installation, versioned user CLI installation, and configuration preservation through `install.sh` and `plasmactl bootstrap`.
- Document setup, privilege boundaries, rollback, and remaining acceptance limits.

Intel wired-LAN streaming has operator acceptance. Clean-machine bootstrap, reboot acceptance, and dGPU streaming remain unverified. The legacy session backend remains the default for existing setup paths; new bootstrap configuration selects systemd-scope.

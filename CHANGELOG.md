# Changelog

## Unreleased

- Document the Sunshine port map and the firewall requirement for non-default ports.
- Add `plasmactl display add|remove|list|firewall` for optional extra Moonlight displays on the scope backend: a virtual KWin output plus its own managed Sunshine instance per slot.
- Refuse `display add` while the primary profile uses KMS capture or has no output name, because KMS maps absolute mouse input over the real connectors only. `DISPLAY_ALLOW_PRIMARY_KMS=true` skips the check.
- Arrange outputs on add and remove: real outputs at the origin, extra outputs to their right.
- Extend the restricted Sunshine helper with display stream instances (`<run>-s<slot>`) and fixed `display<slot>` profiles. Reinstall the integration to use them.

## 0.5.1

- Recover validated execution records from previous boots without signalling current processes.
- Allow restart without an existing execution record and preserve pre-existing auxiliary services.
- Activate the configured TTY from SSH through the restricted fallback when logind requires interactive authentication.
- Align the README, CLI version banner, and source header with the release.

SSH start, stop, and restart passed on one Intel iGPU setup after reboot recovery. This does not establish recovery from every interrupted boot.

## 0.5.0

- Add an opt-in owned systemd Plasma session backend and restricted Sunshine lifecycle integration.
- Pin Intel rendering to the selected GPU and improve CLI failure handling and recovery.
- Add read-only installation planning, explicit dependency installation, versioned user CLI installation, and configuration preservation through `install.sh` and `plasmactl bootstrap`.
- Document setup, privilege boundaries, rollback, and remaining acceptance limits.

Intel wired-LAN streaming has operator acceptance. Clean-machine bootstrap, reboot acceptance, and dGPU streaming remain unverified. The legacy session backend remains the default for existing setup paths; new bootstrap configuration selects systemd-scope.

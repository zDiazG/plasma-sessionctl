set -euo pipefail

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

run_cli_expect_status() {
    local expected="$1" status=0
    shift
    if env -i \
        HOME="${TEST_HOME}/cli-home" \
        USER="${USER}" \
        PATH=/usr/bin:/bin \
        bash "${PLASMACTL_REPO_ROOT}/plasmactl" "$@" >/dev/null 2>&1; then
        status=0
    else
        status=$?
    fi
    [[ "${status}" -eq "${expected}" ]] || fail "expected exit ${expected} for '$*', got ${status}"
}

run_cli_expect_status 2 start --unknown-option
run_cli_expect_status 2 start unexpected
run_cli_expect_status 2 --gpu=other start
run_cli_expect_status 2 --gpu
run_cli_expect_status 2 --session-backend=unknown --help
run_cli_expect_status 2 --plasma-only start
run_cli_expect_status 2 --session-backend=systemd-scope --plasma-only stop
run_cli_expect_status 0 --session-backend=systemd-scope --help
run_cli_expect_status 0 --help
run_cli_expect_status 0 setup --user
run_cli_expect_status 1 setup --system
run_cli_expect_status 2 start --system

sudo_calls=()
sudo() {
    sudo_calls+=("$*")
    [[ "$*" == '-n /usr/bin/chvt 2' ]] && return 0
    return 17
}
_sudo /usr/bin/chvt 2 || fail 'narrow sudo permission required an unrelated precheck'
[[ "${#sudo_calls[@]}" == 1 && "${sudo_calls[0]}" == '-n /usr/bin/chvt 2' ]] || fail 'sudo wrapper issued an unexpected command'
sudo_status=0
_sudo /usr/bin/chvt 3 || sudo_status=$?
[[ "${sudo_status}" == 17 ]] || fail 'sudo wrapper did not preserve denial status'
unset -f sudo

doctor_status=0
env -i HOME="${TEST_HOME}/doctor-home" USER="${USER}" PATH=/usr/bin:/bin \
    PLASMACTL_REPO_ROOT="${PLASMACTL_REPO_ROOT}" bash --noprofile --norc -c '
        set -euo pipefail
        source "${PLASMACTL_REPO_ROOT}/plasmactl" --help >/dev/null
        REQUIRED_BINS=(plasmactl-fixture-missing-binary)
        resolve_plasma_drm_device() { return 1; }
        fixture_systemctl() { return 1; }
        SYSTEMCTL_BIN=fixture_systemctl
        check_tty_session() { return 1; }
        _print_drm_map() { :; }
        check_tmux_session() { return 1; }
        check_tmux_attached() { return 1; }
        check_sunshine_ready() { return 1; }
        check_sunshine_process() { return 1; }
        cmd_doctor
    ' > "${TEST_HOME}/doctor-output" 2>&1 || doctor_status=$?
[[ "${doctor_status}" == 1 ]] || fail 'doctor did not report failed prerequisites'
grep -Fq 'plasmactl-fixture-missing-binary' "${TEST_HOME}/doctor-output" || fail 'doctor did not inspect missing prerequisite'
grep -Fxq 'Summary' "${TEST_HOME}/doctor-output" || fail 'doctor exited before completing diagnostics'

TARGET_DRM_DEVICE=/dev/dri/card4
REQUIRE_CONNECTED_OUTPUT_ON_START=true
connected=false
_card_has_connected_display() { [[ "$1" == card4 && "${connected}" == true ]]; }
if _require_kms_output_ready 2>/dev/null; then fail 'KMS preflight accepted no connected output'; fi
connected=true
_require_kms_output_ready 2>/dev/null || fail 'KMS preflight rejected a connected output'
REQUIRE_CONNECTED_OUTPUT_ON_START=false
connected=false
_require_kms_output_ready 2>/dev/null || fail 'disabled KMS output requirement was not honored'

poll_count=0
check_after_two_polls() { (( poll_count += 1 )); [[ "${poll_count}" -ge 2 ]]; }
noop_sleep() { :; }
sleep() { noop_sleep; }
log() { :; }
err() { :; }
wait_for 'fixture' 2 check_after_two_polls || fail 'wait_for did not complete after the condition became true'
[[ "${poll_count}" -eq 2 ]] || fail "wait_for polled ${poll_count} times, expected 2"

SESSION=test-session
TMUX_BIN=/usr/bin/tmux
attached_call=
check_tmux_session() { return 0; }
_run_as_user() { attached_call="$*"; }
cmd_attach || fail 'attach failed with a successful tmux check'
[[ "${attached_call}" == '/usr/bin/tmux attach -t test-session' ]] || fail "unexpected attach call: ${attached_call}"

stub="${TEST_HOME}/plasmactl-stub"
export TEST_LOG="${TEST_HOME}/restart.log"
cat > "${stub}" <<'EOF_STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${TEST_LOG}"
if [[ "${*: -1}" == stop ]]; then exit "${TEST_EXIT_STOP:-0}"; fi
EOF_STUB
chmod 700 "${stub}"
BASH_ARGV0="${stub}"
VERBOSE=false
PLASMA_GPU_OVERRIDE=dgpu
cmd_restart || fail 'restart failed with a successful command stub'
mapfile -t restart_calls < "${TEST_LOG}"
[[ "${restart_calls[0]:-}" == '--gpu=dgpu stop' ]] || fail "restart did not preserve GPU selection for stop: ${restart_calls[*]:-none}"
[[ "${restart_calls[1]:-}" == '--gpu=dgpu start' ]] || fail "restart did not preserve GPU selection for start: ${restart_calls[*]:-none}"

: > "${TEST_LOG}"
PLASMA_SESSION_BACKEND=systemd-scope
PLASMA_ONLY=true
cmd_restart || fail 'scope restart failed with a command stub'
mapfile -t restart_calls < "${TEST_LOG}"
[[ "${restart_calls[0]}" == '--gpu=dgpu --session-backend=systemd-scope stop' ]] || fail 'scope backend was not preserved for stop'
[[ "${restart_calls[1]}" == '--gpu=dgpu --session-backend=systemd-scope --plasma-only start' ]] || fail 'Plasma-only intent was not preserved for start'
: > "${TEST_LOG}"
export TEST_EXIT_STOP=7
if cmd_restart; then fail 'restart ignored a failed stop'; fi
[[ "$(wc -l < "${TEST_LOG}")" -eq 1 ]] || fail 'restart launched after a failed stop'
unset TEST_EXIT_STOP
PLASMA_SESSION_BACKEND=legacy
PLASMA_ONLY=false

SUNSHINE_UNIT=test-sunshine.service
SYSTEMCTL_BIN=/usr/bin/systemctl
check_sunshine_exists() { return 0; }
_set_systemd_user_env_for_sunshine() { :; }
_run_as_user() { return 0; }
check_sunshine_enabled() { return 0; }
check_sunshine_service_active() { return 0; }
SUNSHINE_RESTART_ON_START=true
_wait_sunshine_ready() { return 1; }
_warn_if_sunshine_selected_vkms() { return 0; }
if _start_sunshine_systemd >/dev/null 2>&1; then fail 'systemd start hid a readiness failure'; fi

SUNSHINE_START_MODE=auto
systemd_attempted=false
fallback_attempted=false
_start_sunshine_systemd() { systemd_attempted=true; return 1; }
_stop_sunshine_if_active() { :; }
_start_sunshine_tmux() { fallback_attempted=true; return 0; }
_start_sunshine_supervised || fail 'auto mode failed after a successful tmux fallback'
[[ "${systemd_attempted}" == true && "${fallback_attempted}" == true ]] || fail 'auto mode did not attempt systemd followed by tmux'

PLASMACTL_JSON_CONFIG="${TEST_HOME}/config.json"
cat > "${PLASMACTL_JSON_CONFIG}" <<'EOF_JSON'
{"enabled":false,"empty":"","drivers":["i915","xe"]}
EOF_JSON
JSON_ENABLED=true
JSON_EMPTY=previous
JSON_DRIVERS=previous
_apply_json_scalar JSON_ENABLED '.enabled'
_apply_json_scalar JSON_EMPTY '.empty'
_apply_json_scalar JSON_DRIVERS '.drivers'
[[ "${JSON_ENABLED}" == false ]] || fail "JSON false did not override true: ${JSON_ENABLED}"
[[ -z "${JSON_EMPTY}" ]] || fail "JSON empty string did not override its previous value: ${JSON_EMPTY}"
[[ "${JSON_DRIVERS}" == 'i915 xe' ]] || fail "JSON array conversion failed: ${JSON_DRIVERS}"

udp_output=$'UNCONN 0 0 0.0.0.0:47998 0.0.0.0:*'
ss() { printf '%s\n' "${udp_output}"; }
_udp_port_listening 47998 || fail 'UDP listener in local-address column was not detected'
_udp_port_listening 47999 && fail 'UDP check accepted a different local port'

_validate_headless_edid_inputs HDMI-A-1 1920x1080@60 edid_1080p.bin || fail 'valid EDID inputs were rejected'
if _validate_headless_edid_inputs HDMI-A-1 1920x1080@60 ../../etc/passwd >/dev/null 2>&1; then
    fail 'EDID path traversal input was accepted'
fi
params='drm.edid_firmware=HDMI-A-1:edid/edid_1080p.bin video=HDMI-A-1:1920x1080@60e'
params+=' test.arg=one&two'
limine_file="${TEST_HOME}/limine.conf"
printf 'KERNEL_CMDLINE[default]+="quiet splash"\n' > "${limine_file}"
sed -i "$(_limine_cmdline_sed_expression "${params}")" "${limine_file}"
grep -Fq -- "${params}" "${limine_file}" || fail 'Limine parameter edit did not preserve and append the parameters'

mkdir -p "${TEST_HOME}/cli-home/.config/plasmactl"
printf '{"drm":{"device":{"invalid":true}}}\n' > "${TEST_HOME}/cli-home/.config/plasmactl/config.json"
json_status=0
env -i HOME="${TEST_HOME}/cli-home" USER="${USER}" PATH=/usr/bin:/bin \
    bash "${PLASMACTL_REPO_ROOT}/plasmactl" --help > "${TEST_HOME}/json-error" 2>&1 || json_status=$?
[[ "${json_status}" == 1 ]] || fail 'invalid JSON scalar did not fail initialization'
grep -Fq 'Invalid JSON value for PLASMA_DRM_DEVICE' "${TEST_HOME}/json-error" || fail 'invalid JSON scalar diagnostic is missing'
if grep -Fq 'command not found' "${TEST_HOME}/json-error"; then fail 'JSON initialization called an undefined logger'; fi
printf '{invalid json\n' > "${TEST_HOME}/cli-home/.config/plasmactl/config.json"
run_cli_expect_status 1 --help

printf 'PASS: CLI, KMS, wait loop, attach, restart, Sunshine fallback, JSON, UDP and EDID/Limine cases\n'

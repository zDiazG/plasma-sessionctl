set -euo pipefail

# No system manager, desktop, process signalling or TTY changes are used here.
fixture_mode=clear
LOGINCTL_BIN=fixture_loginctl
TTY_NAME=tty2
fixture_loginctl() {
    case "$1" in
        list-sessions)
            [[ "${fixture_mode}" != denied ]] || return 1
            printf 'fixture\n'
            [[ "${fixture_mode}" != graphical ]] || printf 'other\n'
            return 0 ;;
        show-session)
            printf 'User=%s\nSeat=seat0\nTTY=tty2\n' "${REAL_UID}"
            if [[ "${fixture_mode}" == graphical && "$2" == other ]]; then
                printf 'Type=wayland\n'
            else
                printf 'Type=tty\n'
            fi ;;
        *) printf 'Unexpected logind operation: %s\n' "$*" >&2; exit 90 ;;
    esac
}
_run_as_user() {
    [[ "$2" == --user && "$3" == show ]] || {
        printf 'Unexpected systemd operation: %s\n' "$*" >&2; exit 90;
    }
    if [[ "${fixture_mode}" == missing ]]; then
        printf 'LoadState=not-found\nActiveState=inactive\n'
    elif [[ "${fixture_mode}" == active ]]; then
        printf 'LoadState=loaded\nActiveState=active\n'
    elif [[ "${fixture_mode}" == failed ]]; then
        printf 'LoadState=loaded\nActiveState=failed\n'
    else
        printf 'LoadState=loaded\nActiveState=inactive\n'
    fi
}
expect_preflight() {
    local expected="$1" status=0
    fixture_mode="$2"
    cmd_session_check > "${TEST_HOME}/session-check.out" 2>&1 || status=$?
    [[ "${status}" == "${expected}" ]] || {
        cat "${TEST_HOME}/session-check.out" >&2
        printf 'FAIL: mode=%s expected=%s observed=%s\n' "${fixture_mode}" "${expected}" "${status}" >&2
        exit 1
    }
}
expect_preflight 0 clear
expect_preflight 1 active
expect_preflight 1 graphical
expect_preflight 2 denied
expect_preflight 2 missing
expect_preflight 2 failed
printf 'PASS: session preflight distinguishes clear, conflicting and unavailable state\n'

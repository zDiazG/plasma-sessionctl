set -euo pipefail
err() { :; }
fixture_masked=false
_scope_systemctl() {
    [[ "$1" == show ]] || { printf 'Unexpected mutation\n' >&2; exit 90; }
    if [[ "${!#}" == graphical-session.target ]]; then
        printf 'Wants=app-dev.lizardbyte.app.Sunshine.service\nRequires=basic.target\n'
    elif [[ "${fixture_masked}" == true ]]; then
        printf 'LoadState=masked\nActiveState=inactive\n'
    else
        printf 'LoadState=loaded\nActiveState=inactive\n'
    fi
}
if _scope_check_sunshine_autostart; then
    printf 'FAIL: enabled Sunshine autostart was ignored\n' >&2
    exit 1
fi
fixture_masked=true
_scope_check_sunshine_autostart
printf 'PASS: Plasma-only mode rejects conflicting Sunshine autostart\n'

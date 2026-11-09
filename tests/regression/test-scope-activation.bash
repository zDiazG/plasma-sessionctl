set -euo pipefail
fail() { echo "FAIL: $*" >&2; exit 1; }
LOGINCTL_BIN=false
ACTIVATE_TTY_ON_START=true
TTY_NAME=tty2
CHVT_BIN=/usr/bin/chvt
fixture_active=no
get_session_active_state() { echo "$fixture_active"; }
_scope_validate_login() { [[ "$1" == 2 ]]; }
_sudo() { [[ "$*" == '/usr/bin/chvt 2' ]] || return 1; fixture_active=yes; }
_scope_activate_login 2 || fail 'restricted fallback failed'
[[ "$fixture_active" == yes ]] || fail 'fallback did not activate configured TTY'
fixture_active=no
if _scope_activate_login 999; then fail 'foreign session reached fallback'; fi
[[ "$fixture_active" == no ]] || fail 'foreign session switched VT'
printf 'PASS: restricted activation fallback and session validation\n'

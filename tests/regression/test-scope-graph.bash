set -euo pipefail
escaped_unit='app-test\x2dtray@autostart.service'
_scope_systemctl() {
    if [[ "$1" == list-units ]]; then
        jq -n --arg u "${escaped_unit}" '[{unit:$u},{unit:"background.service"},{unit:"vanished.service"}]'
    elif [[ "$1" == show ]]; then
        local requested="${!#}"
        local requested="${!#}"
        if [[ "${requested}" == "${escaped_unit}" ]]; then
            printf 'LoadState=loaded\nActiveState=active\nPartOf=graphical-session.target\n'
        elif [[ "${requested}" == background.service ]]; then
            printf 'LoadState=loaded\nActiveState=active\nPartOf=other.target\n'
        else
            printf 'LoadState=not-found\nActiveState=inactive\n'
            return 1
        fi
    else
        printf 'Unexpected operation: %s\n' "$*" >&2
        exit 90
    fi
}
graph="$(_scope_graph_units)"
grep -Fxq -- "${escaped_unit}" <<< "${graph}"
grep -Fxq plasma-kwin_wayland.service <<< "${graph}"
if grep -Eq 'background|vanished' <<< "${graph}"; then
    printf 'FAIL: unrelated or collected unit was included\n' >&2
    exit 1
fi
printf 'PASS: graph enumeration preserves escaped names and handles collected units\n'

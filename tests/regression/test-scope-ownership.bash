set -euo pipefail

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
log() { :; }
err() { printf '%s\n' "$*" >&2; }
_scope_boot_id() { printf 'fixture-boot\n'; }
fixture_run=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
fixture_scope="plasmactl-plasma-${fixture_run}.scope"
fixture_db="${TEST_HOME}/units.json"
fixture_log="${TEST_HOME}/operations"
fixture_unknown=false
fixture_escaped=false
escaped_unit='app-fixture\x2dname@autostart.service'
_scope_graph_units() {
    printf '%s\n' graphical-session.target plasma-kwin_wayland.service plasma-plasmashell.service
    [[ "${fixture_unknown}" != true ]] || printf '%s\n' external.service
    [[ "${fixture_escaped}" != true ]] || printf '%s\n' "${escaped_unit}"
    return 0
}

fixture_manager_payload='{"type":"as","data":["PLASMACTL_RUN_ID=changed-by-another-actor"]}'
_run_as_user() { printf '%s\n' "${fixture_manager_payload}"; }
_scope_systemctl() {
    if [[ "$1" == show ]]; then
        local requested="${!#}"
        if [[ "${requested}" == missing.scope ]]; then
            printf 'LoadState=not-found\nActiveState=inactive\n'
            return 1
        fi
        [[ "${requested}" != denied.scope ]] || return 1
        jq -er --arg u "${requested}" '.[$u] | if . == null then error("missing fixture unit") else
            "Id=\($u)\nLoadState=loaded\nActiveState=\(.state)\nInvocationID=\(.inv)\nMainPID=42" end' "${fixture_db}"
        return $?
    fi
    printf '%s\n' "$*" >> "${fixture_log}"
    if [[ "$1" == --no-block && "$2" == stop ]]; then
        jq --arg u "${!#}" '.[$u].state = "inactive"' "${fixture_db}" > "${fixture_db}.new"
        mv "${fixture_db}.new" "${fixture_db}"
    elif [[ "$1" != set-environment && "$1" != unset-environment ]]; then
        fail "unexpected manager mutation: $*"
    fi
}
fixture() {
    fixture_unknown=false
    fixture_escaped=false
    : > "${fixture_log}"
    jq -n --arg scope "${fixture_scope}" '{
        ($scope):{state:"active",inv:"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
        "plasma-kwin_wayland.service":{state:"active",inv:"cccccccccccccccccccccccccccccccc"},
        "plasma-plasmashell.service":{state:"active",inv:"dddddddddddddddddddddddddddddddd"},
        "graphical-session.target":{state:"active",inv:"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"},
        "external.service":{state:"active",inv:"ffffffffffffffffffffffffffffffff"}
    }' > "${fixture_db}"
    jq -n --arg uid "${REAL_UID}" --arg run "${fixture_run}" --arg scope "${fixture_scope}" \
        --slurpfile db "${fixture_db}" '{schema:1,phase:"running",uid:$uid,boot:"fixture-boot",
        run:$run,scope:$scope,sid:"2",tty:"tty2",gpu:"/dev/dri/card4",units:($db[0]|del(."external.service")|map_values(.inv)),
        baseline_active:[],environment_before:{},environment_after:{PLASMACTL_RUN_ID:$run}}' > "${SCOPE_STATE_FILE}"
}
expect_failure() {
    if "$@" > "${TEST_HOME}/expected-failure" 2>&1; then fail "unexpected success: $*"; fi
}
fixture
_scope_load || fail 'valid state rejected'
_scope_status >/dev/null || fail 'valid running state rejected'

# State from another boot must never authorize a manager operation.
_scope_update '.boot = "old-boot"'
expect_failure _scope_stop
[[ ! -s "${fixture_log}" ]] || fail 'old boot caused mutation'

fixture
jq --arg u "${fixture_scope}" '.[$u].inv = "11111111111111111111111111111111"' "${fixture_db}" > "${fixture_db}.new"
mv "${fixture_db}.new" "${fixture_db}"
expect_failure _scope_stop
[[ ! -s "${fixture_log}" ]] || fail 'reused scope caused mutation'

fixture
fixture_unknown=true
expect_failure _scope_stop
[[ ! -s "${fixture_log}" ]] || fail 'unrecorded target dependent caused mutation'

fixture
# Startup is not healthy merely because the launcher scope exists.
_scope_update '.phase = "starting" | .units |= with_entries(select(.key|endswith(".scope")))'
expect_failure _scope_status

fixture
_scope_stop || fail 'owned stop failed'
[[ ! -e "${SCOPE_STATE_FILE}" ]] || fail 'completed stop retained the state file'
[[ "$(wc -l < "${fixture_log}")" -eq 4 ]] || fail 'stop targeted an unexpected number of units'
! grep -q external "${fixture_log}" || fail 'stop targeted an unrelated service'
jq -e '."external.service".state == "active"' "${fixture_db}" >/dev/null || fail 'unrelated service was modified'
! grep -q 'environment' "${fixture_log}" || fail 'stop overwrote environment changed by another actor'

# Escaped systemd names must survive storage and raw tab-separated iteration.
fixture
fixture_escaped=true
jq --arg u "${escaped_unit}" '.[$u] = {state:"active",inv:"11111111111111111111111111111111"}' "${fixture_db}" > "${fixture_db}.new"
mv "${fixture_db}.new" "${fixture_db}"
_scope_update --arg u "${escaped_unit}" '.units[$u] = "11111111111111111111111111111111"'
_scope_load || fail 'escaped unit name rejected by schema'
_scope_stop || fail 'escaped unit could not be stopped'
grep -Fxq -- "--no-block stop -- ${escaped_unit}" "${fixture_log}" || fail 'escaped unit name was changed during stop'

# Auxiliary graph members may protect /proc or have no MainPID. Their explicit
# desktop relation and the pre-launch baseline are independent manager evidence.
fixture
_scope_capture_unit external.service "${fixture_run}" true || fail 'new auxiliary graph member rejected'
_scope_update '.units |= del(."external.service") | .baseline_active = ["external.service"]'
expect_failure _scope_capture_unit external.service "${fixture_run}" true

# Rollback must preserve the failed start exit code and never adopt old state.
_scope_start_transaction() { fixture; SCOPE_ATTEMPT_RUN="${fixture_run}"; return 7; }
rollback_status=0
_scope_start >/dev/null 2>&1 || rollback_status=$?
[[ "${rollback_status}" == 7 && ! -e "${SCOPE_STATE_FILE}" ]] || fail 'owned rollback failed or hid the startup failure'
_scope_start_transaction() { fixture; SCOPE_ATTEMPT_RUN="${fixture_run}"; jq 'map_values(.state = "inactive")' "${fixture_db}" > "${fixture_db}.new"; mv "${fixture_db}.new" "${fixture_db}"; return 7; }
rollback_status=0
_scope_start >/dev/null 2>&1 || rollback_status=$?
[[ "${rollback_status}" == 7 && ! -e "${SCOPE_STATE_FILE}" && ! -s "${fixture_log}" ]] || fail 'pre-launch rollback touched manager units'
fixture
_scope_start_transaction() { return 1; }
expect_failure _scope_start
[[ -e "${SCOPE_STATE_FILE}" && ! -s "${fixture_log}" ]] || fail 'failed start adopted an existing execution'

# The manager environment parser preserves quoted/spaced values as data.
fixture_manager_payload='{"type":"as","data":["DISPLAY=old display","KWIN_RENDER_NODES=/dev/dri/renderD128","SECRET_TOKEN=not-exported"]}'
env_json="$(_scope_manager_environment)"
jq -e '.DISPLAY == "old display" and .KWIN_RENDER_NODES == "/dev/dri/renderD128" and (has("SECRET_TOKEN")|not)' <<< "${env_json}" >/dev/null || fail 'environment filtering failed'

fixture
fixture_manager_payload='{"type":"as","data":["DISPLAY=owned","KWIN_RENDER_NODES=/dev/dri/renderD128","PLASMACTL_RUN_ID=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}'
_scope_update '.environment_before = {DISPLAY:"old display"} | .environment_after = {DISPLAY:"owned",KWIN_RENDER_NODES:"/dev/dri/renderD128",PLASMACTL_RUN_ID:.run}'
_scope_restore_environment || fail 'environment restoration failed'
grep -Fxq 'set-environment DISPLAY=old display' "${fixture_log}" || fail 'previous display was not restored'
grep -Fxq 'unset-environment PLASMACTL_RUN_ID' "${fixture_log}" || fail 'run marker was not removed'
grep -Fxq 'unset-environment KWIN_RENDER_NODES' "${fixture_log}" || fail 'render-node selection was not restored'

_scope_unit missing.scope >/dev/null || fail 'collected scope was not treated as absence'
expect_failure _scope_unit denied.scope

# The kernel lock remains exclusive and reusable without deleting its inode.
acquire_lock || fail 'could not acquire the lifecycle lock'
if flock -n "${LOCK_FILE}" /bin/true; then fail 'a second holder acquired the lock'; fi
release_lock
[[ -f "${LOCK_FILE}" ]] || fail 'release deleted the lock inode'
flock -n "${LOCK_FILE}" /bin/true || fail 'released lock could not be acquired'

printf 'PASS: scope identity, stale state, invocation reuse, dependency conflicts and bounded stop\n'

set -euo pipefail
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
err() { :; }

tmp="${TEST_HOME}/scope-sunshine"
mkdir -p "${tmp}/config"
REAL_HOME="${tmp}"
SUNSHINE_CONFIG_DIR="${tmp}/config"
SUNSHINE_PROFILE=safe
SUNSHINE_SAFE_CONFIG="${SUNSHINE_CONFIG_DIR}/plasmactl-safe.conf"
SUNSHINE_SAFE_APPS="${SUNSHINE_CONFIG_DIR}/plasmactl-safe-apps.json"
SUNSHINE_PERF_CONFIG="${SUNSHINE_CONFIG_DIR}/plasmactl-performance.conf"
SUNSHINE_PERF_APPS="${SUNSHINE_CONFIG_DIR}/plasmactl-performance-apps.json"
printf 'operator config\n' > "${SUNSHINE_SAFE_CONFIG}"
printf '{"apps":[]}\n' > "${SUNSHINE_SAFE_APPS}"
_scope_prepare_sunshine_config || fail 'existing profile assets should be preserved'
[[ "$(cat "${SUNSHINE_SAFE_CONFIG}")" == 'operator config' ]] || fail 'config was overwritten'
[[ "$(cat "${SUNSHINE_SAFE_APPS}")" == '{"apps":[]}' ]] || fail 'apps list was overwritten'
rm -- "${SUNSHINE_SAFE_CONFIG}"
_write_sunshine_safe_assets() {
    printf 'wan_encryption_mode = 0\n' > "${SUNSHINE_SAFE_CONFIG}"
    printf '{"apps":[{"name":"generated"}]}\n' > "${SUNSHINE_SAFE_APPS}"
}
_scope_prepare_sunshine_config || fail 'missing profile could not be published'
grep -Fxq 'wan_encryption_mode = 2' "${SUNSHINE_SAFE_CONFIG}" || fail 'new profile disabled WAN encryption'
[[ "$(cat "${SUNSHINE_SAFE_APPS}")" == '{"apps":[]}' ]] || fail 'missing profile generation overwrote existing apps'

SCOPE_STATE_FILE="${tmp}/state.json"
REAL_UID=1234
SUNSHINE_REQUIRED_TCP_PORTS='47984 47989'
printf '{"run":"%032d","sunshine":{"role":"igpu","invocation":"%032d"}}\n' 1 2 > "${SCOPE_STATE_FILE}"
_scope_sunshine_helper() {
    [[ "$1" == status ]] || return 0
    printf '{"unit":"plasmactl-sunshine-u1234-igpu@%032d.service","state":"active","invocation":"%032d","recorded":true,"listeners":[47984,47989]}\n' 1 2
}
info="$(_scope_sunshine_info)" || fail 'valid status should pass'
_scope_sunshine_ready "${info}" || fail 'owned listeners should satisfy readiness'
[[ "$(jq -r '.unit' <<< "${info}")" == "plasmactl-sunshine-u1234-igpu@$(printf '%032d' 1).service" ]] || fail 'status did not use exact derived unit'

_scope_sunshine_helper() {
    [[ "$1" == status ]] || fail 'changed invocation must not be stopped'
    printf '{"unit":"plasmactl-sunshine-u1234-igpu@%032d.service","state":"active","invocation":"%032d","recorded":true,"listeners":[]}\n' 1 3
}
if _scope_stop_sunshine; then fail 'changed invocation was accepted'; fi

# A failed start must retain its record for later inspection and cleanup.
_scope_sunshine_helper() {
    [[ "$1" == status || "$1" == stop ]] || fail 'unexpected helper action'
    printf '{"unit":"plasmactl-sunshine-u1234-igpu@%032d.service","state":"failed","invocation":"","recorded":true,"listeners":[]}\n' 1
}
_scope_stop_sunshine || fail 'failed unit with an owned record should clean up'
[[ "$(jq -r '.sunshine.stopped' "${SCOPE_STATE_FILE}")" == true ]] || fail 'cleanup state was not recorded'

# Stop order is an operational property: the desktop must still be available
# when the streaming service receives its stop request.
events="${tmp}/stop-order"
: > "${events}"
run="$(printf '%032d' 1)"
inv="$(printf '%032d' 2)"
jq -n --arg run "${run}" --arg inv "${inv}" \
    '{run:$run,scope:("plasmactl-plasma-"+$run+".scope"),
      units:{("plasmactl-plasma-"+$run+".scope"):$inv,"plasma-plasmashell.service":$inv},
      sunshine:{role:"igpu",invocation:$inv}}' > "${SCOPE_STATE_FILE}"
_scope_load() { return 0; }
_scope_match_unit() { return 0; }
_scope_graph_units() { printf 'plasma-plasmashell.service\n'; }
_scope_unit() {
    if [[ "$1" == *.scope ]] || [[ -f "${tmp}/desktop-stopped" ]]; then
        printf 'ActiveState=inactive\n'
    else
        printf 'ActiveState=active\n'
    fi
}
_scope_systemctl() {
    [[ "$1 $2" == '--no-block stop' ]] || fail 'unexpected desktop action'
    printf 'desktop\n' >> "${events}"
    touch "${tmp}/desktop-stopped"
}
_scope_restore_environment() { return 0; }
_scope_sunshine_helper() {
    if [[ "$1" == stop ]]; then
        printf 'sunshine\n' >> "${events}"
    else
        printf '{"unit":"plasmactl-sunshine-u1234-igpu@%s.service","state":"active","invocation":"%s","recorded":true,"listeners":[]}' "${run}" "${inv}"
    fi
}
_scope_stop || fail 'ordered shutdown failed'
[[ "$(head -n 1 "${events}")" == sunshine ]] || fail 'desktop stopped before Sunshine'
[[ "$(tail -n 1 "${events}")" == desktop ]] || fail 'owned desktop was not stopped'

printf 'PASS: scoped Sunshine preserves operator config, validates unit/invocation/readiness, and cleans failed starts\n'

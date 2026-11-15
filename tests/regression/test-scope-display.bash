set -euo pipefail
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
log() { :; }
err() { printf '%s\n' "$*" >> "${TEST_HOME}/errors"; }
: > "${TEST_HOME}/errors"

tmp="${TEST_HOME}/display"
mkdir -p "${tmp}/config"
SUNSHINE_CONFIG_DIR="${tmp}/config"
SCOPE_STATE_FILE="${tmp}/state.json"
REAL_UID=1234
DISPLAY_PORT_BASE=47989
WAIT_DISPLAY_OUTPUT=1
WAIT_SUNSHINE_PORTS=1
WAIT_STOP=1
run=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
primary_inv=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb

# Pure derivation: ports follow the upstream offsets from the configured base.
_display_valid_index 1 && _display_valid_index 3 || fail 'valid index rejected'
! _display_valid_index 0 && ! _display_valid_index 4 && ! _display_valid_index x || fail 'bad index accepted'
_display_valid_resolution 1920x1080 && _display_valid_resolution 1366x768 || fail 'valid resolution rejected'
for bad in 1920 axb 100x100 99999x1080 1920x1080x2 '1920x1080;id'; do
    ! _display_valid_resolution "${bad}" || fail "resolution accepted: ${bad}"
done
[[ "$(_display_port 1)" == 48989 && "$(_display_port 3)" == 50989 ]] || fail 'port base not derived'
[[ "$(_display_tcp_ports 1)" == '48984 48989 48990 49010' ]] || fail 'TCP port set differs'
[[ "$(_display_udp_ports 1)" == '48998 48999 49000' ]] || fail 'UDP port set differs'
[[ "$(_display_sunshine_run "${run}" 2)" == "${run}-s2" ]] || fail 'stream run suffix differs'
[[ "$(_display_unit "${run}" 2)" == "plasmactl-display-${run}-2.service" ]] || fail 'output unit name differs'
fw="$(_display_print_firewall 1)"
grep -Fq 'port 48984,48989,48990,49010 proto tcp' <<< "${fw}" || fail 'firewall TCP line missing'
grep -Fq 'port 48998,48999,49000 proto udp' <<< "${fw}" || fail 'firewall UDP line missing'
grep -Fq '<client-network>' <<< "${fw}" || fail 'firewall text must not assume a network'

# Profile generation publishes absent files only and never rewrites operator edits.
_display_prepare_config 1 /dev/dri/by-path/pci-0000:00:02.0-render || fail 'profile not published'
conf="$(_display_config 1)"
for expected in 'port = 48989' 'stream_audio = disabled' 'capture = kwin' 'output_name = Virtual-plasmactl-d1' \
    'wan_encryption_mode = 2' 'lan_encryption_mode = 1' 'controller = disabled' 'origin_web_ui_allowed = lan' \
    "log_path = ${SUNSHINE_CONFIG_DIR}/sunshine-display1.log" 'file_state = sunshine_state_display1.json' 'adapter_name = /dev/dri/by-path/pci-0000:00:02.0-render'; do
    grep -Fxq "${expected}" "${conf}" || fail "generated profile lacks: ${expected}"
done
grep -Eq '^sunshine_name = .+-display1$' "${conf}" || fail 'generated name lacks the display suffix'
! grep -Eq '47989$' "${conf}" || fail 'display profile reuses the primary port'
jq -e '.apps[0].name == "Desktop"' "$(_display_apps 1)" >/dev/null || fail 'apps list not published'
[[ -z "$(find "${SUNSHINE_CONFIG_DIR}" -maxdepth 1 -name '.plasmactl-display.*')" ]] || fail 'staging directory left behind'
printf 'operator config\n' > "${conf}"
_display_prepare_config 1 /dev/dri/by-path/pci-0000:00:02.0-render || fail 'existing profile must be accepted'
[[ "$(cat "${conf}")" == 'operator config' ]] || fail 'operator profile was overwritten'
rm -- "${conf}"; ln -s /etc/passwd "${conf}"
! _display_prepare_config 1 /dev/dri/by-path/pci-0000:00:02.0-render || fail 'symlinked profile accepted'
rm -- "${conf}"

# Layout: real outputs anchor at the origin, extras follow in slot order.
bad='{"outputs":[{"name":"Virtual-plasmactl-d1","enabled":null,"pos":{"x":0,"y":0},"size":{"width":1920,"height":1080},"scale":1},{"name":"HDMI-A-1","enabled":true,"pos":{"x":1920,"y":0},"size":{"width":1920,"height":1080},"scale":1}]}'
[[ "$(_display_layout_args <<< "${bad}" | tr '\n' ' ')" == 'output.HDMI-A-1.position.0,0 output.Virtual-plasmactl-d1.position.1920,0 ' ]] || fail 'swapped layout not corrected'
scaled='{"outputs":[{"name":"DP-1","enabled":true,"pos":{"x":0,"y":0},"size":{"width":3840,"height":2160},"scale":2},{"name":"Virtual-plasmactl-d2","pos":{"x":0,"y":0},"size":{"width":1280,"height":720},"scale":1},{"name":"Virtual-plasmactl-d1","pos":{"x":9,"y":9},"size":{"width":1920,"height":1080},"scale":1}]}'
[[ "$(_display_layout_args <<< "${scaled}" | tr '\n' ' ')" == 'output.DP-1.position.0,0 output.Virtual-plasmactl-d1.position.1920,0 output.Virtual-plasmactl-d2.position.3840,0 ' ]] || fail 'scaled multi-slot layout wrong'
[[ -z "$(_display_layout_args <<< '{"outputs":[{"name":"Virtual-plasmactl-d1","pos":{"x":0,"y":0},"size":{"width":10,"height":10},"scale":1}]}')" ]] || fail 'layout without a real output must do nothing'

# Taskbar: the panel script targets the output by geometry, removes before the
# output goes, and refuses malformed geometry without evaluating anything.
_display_user_env() { printf '%s\n' "$*" >> "${TEST_HOME}/plasma-calls"; }
: > "${TEST_HOME}/plasma-calls"
_display_panel_eval remove '1920 0 1920 1080' >/dev/null || fail 'remove evaluation failed'
grep -Fq 'p.remove()' "${TEST_HOME}/plasma-calls" || fail 'remove does not delete the panel'
grep -Fq 'X=1920,Y=0,W=1920,H=1080' "${TEST_HOME}/plasma-calls" || fail 'geometry not passed to the script'
grep -Fq "action === 'remove'" "${TEST_HOME}/plasma-calls" || fail 'remove branch missing'
: > "${TEST_HOME}/plasma-calls"
_display_panel_eval add '1920 0 1920 1080' >/dev/null || fail 'add evaluation failed'
grep -Fq 'new Panel' "${TEST_HOME}/plasma-calls" || fail 'add does not create a panel'
grep -Fq "location = 'bottom'" "${TEST_HOME}/plasma-calls" || fail 'panel is not at the bottom'
: > "${TEST_HOME}/plasma-calls"
_display_panel_eval check '1920 0 1920 1080' >/dev/null || fail 'check evaluation failed'
grep -Fq "action === 'check'" "${TEST_HOME}/plasma-calls" || fail 'check action missing'
: > "${TEST_HOME}/plasma-calls"
! _display_panel_eval add '1920; id 0 1920 1080' >/dev/null 2>&1 || fail 'malformed geometry accepted'
[[ ! -s "${TEST_HOME}/plasma-calls" ]] || fail 'malformed geometry reached plasmashell'

# --- stateful fixture -------------------------------------------------------
out_file="${tmp}/out.state"; calls="${tmp}/calls"
sun_state() { printf '%s/sun-%s.state\n' "${tmp}" "${1##*-}"; }
reset_fixture() {
    jq -n --arg run "${run}" --arg inv "${primary_inv}" \
        '{schema:1,phase:"running",run:$run,sid:"2",wayland:"wayland-1",gpu:"/dev/dri/card1",
          sunshine:{role:"igpu",profile:"performance",display:"wayland-1",invocation:$inv}}' > "${SCOPE_STATE_FILE}"
    SUNSHINE_PERF_CONFIG="${tmp}/primary.conf"
    printf 'min_log_level = info\ncapture = kwin\noutput_name = HDMI-A-1\n' > "${SUNSHINE_PERF_CONFIG}"
    printf 'inactive\n\n' > "${out_file}"
    rm -f -- "${tmp}"/sun-*.state
    : > "${calls}"
    fixture_listen=false; fixture_output=true; fixture_taskbar=0; fixture_helper_start=ok; fixture_krfb=ok
}
eval "$(declare -f _scope_load | sed '1s/^_scope_load/_real_scope_load/')"
_scope_load() { return 0; }
_scope_stale_boot() { return 1; }
acquire_lock() { return 0; }
_tcp_port_listening() { [[ "${fixture_listen}" == true ]]; }
_udp_port_listening() { return 1; }
_display_adapter() { printf '/dev/dri/by-path/pci-0000:00:02.0-render\n'; }
command() { [[ "$1" == -v ]] && return 0; builtin command "$@"; }
_display_arrange() { printf 'arrange %s\n' "$1" >> "${calls}"; }
_display_taskbar() { printf 'taskbar %s %s %s\n' "$1" "$2" "$3" >> "${calls}"; return "${fixture_taskbar:-0}"; }
_display_output_present() { [[ "${fixture_output}" == true ]]; }
_display_user_env() {
    printf 'systemd-run %s\n' "$*" >> "${calls}"
    [[ "${fixture_krfb}" == ok ]] || return 1
    printf 'active\ncccccccccccccccccccccccccccccccc\n' > "${out_file}"
}
_scope_unit() {
    if [[ "$1" == plasmactl-display-* ]]; then
        printf 'LoadState=loaded\nActiveState=%s\nInvocationID=%s\nMainPID=7\n' "$(sed -n 1p "${out_file}")" "$(sed -n 2p "${out_file}")"
    else
        printf 'LoadState=loaded\nActiveState=active\nInvocationID=%s\nMainPID=8\n' "${primary_inv}"
    fi
}
_scope_systemctl() {
    printf 'systemctl %s\n' "$*" >> "${calls}"
    [[ "$1" == stop ]] || fail "unexpected manager call: $*"
    printf 'inactive\n\n' > "${out_file}"
}
_scope_sunshine_helper() {
    printf 'helper %s\n' "$*" >> "${calls}"
    local action="$1" srun="$2"
    if [[ "${srun}" == "${run}" ]]; then
        printf '{"unit":"plasmactl-sunshine-u1234-igpu@%s.service","state":"active","invocation":"%s","recorded":true,"listeners":[47990,48010]}\n' "${run}" "${primary_inv}"
        return 0
    fi
    local sun_file; sun_file="$(sun_state "${srun}")"
    [[ -f "${sun_file}" ]] || printf '{"state":"inactive","invocation":"","recorded":false,"listeners":[]}\n' > "${sun_file}"
    case "${action}" in
        status) ;;
        start)
            [[ "${fixture_helper_start}" != fail ]] || { printf '{"unit":"x","state":"failed","invocation":"dddddddddddddddddddddddddddddddd","recorded":true,"listeners":[]}\n' > "${sun_file}"; return 1; }
            local base=$(( 47989 + 1000 * ${srun##*-s} ))
            printf '{"state":"active","invocation":"dddddddddddddddddddddddddddddddd","recorded":true,"listeners":[%s,%s]}\n' $(( base + 1 )) $(( base + 21 )) > "${sun_file}" ;;
        stop) printf '{"state":"inactive","invocation":"","recorded":false,"listeners":[]}\n' > "${sun_file}" ;;
    esac
    jq -c --arg unit "plasmactl-sunshine-u1234-igpu@${srun}.service" '. + {unit:$unit}' "${sun_file}"
}
displays() { jq -c '.displays // {}' "${SCOPE_STATE_FILE}"; }

# A normal add records identities before use and ends with a ready stream.
reset_fixture
cmd_display add 1 1920x1080 > "${tmp}/add.out" || fail 'add failed'
grep -Fq -- "--name plasmactl-d1 --resolution 1920x1080" "${calls}" || fail 'virtual output was not requested with its name'
grep -Fq 'arrange wayland-1' "${calls}" || fail 'outputs were not arranged after creation'
grep -Fq 'taskbar add wayland-1 Virtual-plasmactl-d1' "${calls}" || fail 'taskbar not added for the new output'
grep -Fq "helper start ${run}-s1 igpu 2 wayland-1 display1" "${calls}" || fail 'extra Sunshine did not use the stream run and profile'
[[ "$(jq -r '.displays["1"].sunshine_invocation' "${SCOPE_STATE_FILE}")" == dddddddddddddddddddddddddddddddd ]] || fail 'Sunshine invocation not recorded'
[[ "$(jq -r '.displays["1"].output_invocation' "${SCOPE_STATE_FILE}")" == cccccccccccccccccccccccccccccccc ]] || fail 'output invocation not recorded'
[[ "$(jq -r '.displays["1"].port' "${SCOPE_STATE_FILE}")" == 48989 ]] || fail 'port not recorded'
grep -Fq 'ufw allow from <client-network>' "${tmp}/add.out" || fail 'next steps lack firewall guidance'
listing="$(cmd_display list)"
grep -Fq 'display 1: 1920x1080 output=active Sunshine=active port=48989' <<< "${listing}" || fail 'list does not report the stream'
rules="$(cmd_display firewall)"
grep -Fq 'port 48984,48989,48990,49010 proto tcp' <<< "${rules}" || fail 'firewall command lacks recorded stream'

# Slot reuse and conflicts are refused without touching resources.
: > "${calls}"
! cmd_display add 1 1920x1080 >/dev/null 2>&1 || fail 'duplicate index accepted'
[[ ! -s "${calls}" ]] || fail 'duplicate add touched resources'
cmd_display add > /dev/null || { cat "${TEST_HOME}/errors" >&2; fail 'automatic slot selection failed'; }
[[ "$(jq -r '.displays|keys|join(",")' "${SCOPE_STATE_FILE}")" == 1,2 ]] || fail 'automatic slot was not the lowest free one'

# Removal stops Sunshine before the output and clears only its own record.
reset_fixture
cmd_display add 1 1280x720 >/dev/null
: > "${calls}"
cmd_display remove 1 || fail 'remove failed'
order="$(grep -nE '^(helper stop|systemctl stop)' "${calls}" | cut -d: -f2 | cut -d' ' -f1-2 | tr '\n' ',')"
[[ "${order}" == 'helper stop,systemctl stop,' ]] || fail "stop order was: ${order}"
[[ "$(displays)" == '{}' ]] || fail 'removed stream still recorded'
jq -e '.sunshine.invocation == "'"${primary_inv}"'"' "${SCOPE_STATE_FILE}" >/dev/null || fail 'primary record changed'

# Absolute pointer input needs a primary stream that sees every output.
reset_fixture; printf 'capture = kms\noutput_name = HDMI-A-1\n' > "${SUNSHINE_PERF_CONFIG}"
! cmd_display add 1 1920x1080 >/dev/null 2>&1 || fail 'KMS primary capture accepted'
grep -Fq 'captures with "kms"' "${TEST_HOME}/errors" || fail 'KMS refusal does not explain the cause'
! grep -Eq '^(systemd-run|helper start|systemctl)' "${calls}" || fail 'KMS refusal created resources'
printf 'min_log_level = info\n' > "${SUNSHINE_PERF_CONFIG}"
! cmd_display add 1 1920x1080 >/dev/null 2>&1 || fail 'primary without a capture setting accepted'
printf 'capture = kwin\n' > "${SUNSHINE_PERF_CONFIG}"
! cmd_display add 1 1920x1080 >/dev/null 2>&1 || fail 'KWin capture without an output name accepted'
printf 'capture = kwin\noutput_name = 0\n' > "${SUNSHINE_PERF_CONFIG}"
! cmd_display add 1 1920x1080 >/dev/null 2>&1 || fail 'numeric output index accepted for KWin capture'
printf 'capture = kms\n' > "${SUNSHINE_PERF_CONFIG}"
DISPLAY_ALLOW_PRIMARY_KMS=true cmd_display add 1 1920x1080 >/dev/null || fail 'explicit KMS override refused'
reset_fixture

# Output that KWin never reports: nothing else starts, and the record is rolled back.
reset_fixture; fixture_output=false
! cmd_display add 1 1920x1080 >/dev/null 2>&1 || fail 'missing output accepted'
! grep -q '^helper start' "${calls}" || fail 'Sunshine started without an output'
grep -q '^systemctl stop' "${calls}" || fail 'orphaned output unit was not stopped'
[[ "$(displays)" == '{}' ]] || fail 'failed add left a record'

# systemd-run failure leaves no record and no Sunshine.
reset_fixture; fixture_krfb=fail
! cmd_display add 1 1920x1080 >/dev/null 2>&1 || fail 'failed output start accepted'
! grep -q '^helper start' "${calls}" || fail 'Sunshine started after output failure'
[[ "$(displays)" == '{}' ]] || fail 'failed output start left a record'

# A taskbar that cannot be removed keeps its output up: stopping the output
# would orphan the panel and crash plasmashell.
reset_fixture; cmd_display add 1 1920x1080 >/dev/null; fixture_taskbar=1; : > "${calls}"
! cmd_display remove 1 >/dev/null 2>&1 || fail 'output stopped with its taskbar still present'
! grep -q '^systemctl stop' "${calls}" || fail 'output stopped after a failed taskbar removal'
[[ "$(jq -r '.displays|keys|length' "${SCOPE_STATE_FILE}")" == 1 ]] || fail 'record dropped after refused removal'
fixture_taskbar=0

# A failed Sunshine start still stops what it created: Sunshine by identity, then the output.
reset_fixture; fixture_helper_start=fail
! cmd_display add 2 1920x1080 >/dev/null 2>&1 || fail 'failed Sunshine start accepted'
grep -Fq "helper stop ${run}-s2 igpu dddddddddddddddddddddddddddddddd" "${calls}" || fail 'failed Sunshine was not stopped by identity'
grep -q '^systemctl stop' "${calls}" || fail 'output survived a failed Sunshine start'
[[ "$(displays)" == '{}' ]] || fail 'failed start left a record'

# A changed Sunshine or output invocation blocks stop and retains the record.
reset_fixture; cmd_display add 1 1920x1080 >/dev/null
printf '{"state":"active","invocation":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","recorded":true,"listeners":[48990,49010]}\n' > "$(sun_state "${run}-s1")"
: > "${calls}"
! _scope_stop_displays >/dev/null 2>&1 || fail 'changed Sunshine invocation was stopped'
! grep -q '^helper stop' "${calls}" || fail 'helper stop issued for another invocation'
[[ "$(jq -r '.displays|keys|length' "${SCOPE_STATE_FILE}")" == 1 ]] || fail 'record dropped after refused stop'
reset_fixture; cmd_display add 1 1920x1080 >/dev/null
printf 'active\nffffffffffffffffffffffffffffffff\n' > "${out_file}"
! _scope_stop_displays >/dev/null 2>&1 || fail 'changed output invocation was stopped'
! grep -q '^systemctl stop' "${calls}" || fail 'output stopped despite a changed invocation'

# Session stop tears every stream down before the primary Sunshine is touched.
reset_fixture; cmd_display add 1 1920x1080 >/dev/null; cmd_display add 2 1920x1080 >/dev/null
: > "${calls}"
_scope_stop_displays || fail 'stop of all streams failed'
[[ "$(displays)" == '{}' ]] || fail 'streams remain recorded after stop'
! grep -q "helper stop ${run} " "${calls}" || fail 'primary Sunshine stopped by the display teardown'

# Preconditions: port conflict, no managed Sunshine, stopped session, bad arguments.
reset_fixture; fixture_listen=true
! cmd_display add 1 1920x1080 >/dev/null 2>&1 || fail 'busy port accepted'
! grep -Eq '^(systemd-run|helper start|systemctl)' "${calls}" || fail 'busy-port refusal created resources'
reset_fixture; jq '.sunshine = null' "${SCOPE_STATE_FILE}" > "${tmp}/s" && mv "${tmp}/s" "${SCOPE_STATE_FILE}"
! cmd_display add 1 1920x1080 >/dev/null 2>&1 || fail 'plasma-only execution accepted a display'
reset_fixture
rc=0; cmd_display add 7 >/dev/null 2>&1 || rc=$?; [[ "${rc}" == 2 ]] || fail 'bad index must return 2'
rc=0; cmd_display add 1 huge >/dev/null 2>&1 || rc=$?; [[ "${rc}" == 2 ]] || fail 'bad resolution must return 2'
rc=0; cmd_display bogus >/dev/null 2>&1 || rc=$?; [[ "${rc}" == 2 ]] || fail 'unknown action must return 2'
for badbase in abc 80 65000 ''; do
    rc=0; DISPLAY_PORT_BASE="${badbase}" cmd_display add 1 >/dev/null 2>&1 || rc=$?
    [[ "${rc}" == 2 ]] || fail "unsafe DISPLAY_PORT_BASE accepted: ${badbase}"
done

# The state schema accepts recorded streams and rejects malformed ones.
_scope_boot_id() { printf 'fixture-boot\n'; }
state_with() {
    jq -n --arg uid "${REAL_UID}" --arg run "${run}" --argjson d "$1" \
        '{schema:1,phase:"running",uid:$uid,boot:"fixture-boot",run:$run,scope:("plasmactl-plasma-"+$run+".scope"),
          sid:"2",tty:"tty2",gpu:"/dev/dri/card1",units:{},baseline_active:[],environment_before:{}} + (if $d == null then {} else {displays:$d} end)' > "${SCOPE_STATE_FILE}"
}
good='{"1":{"output_unit":"plasmactl-display-'"${run}"'-1.service","output_invocation":null,"sunshine_run":"'"${run}"'-s1","sunshine_invocation":null,"port":48989,"resolution":"1920x1080"}}'
state_with null; _real_scope_load || fail 'state without displays rejected'
state_with "${good}"; _real_scope_load || fail 'valid display record rejected'
for mutation in '.["4"] = .["1"]' '.["1"].output_unit = "evil.service"' '.["1"].sunshine_run = "../x"' \
    '.["1"].output_invocation = "nothex"' '.["1"].resolution = "big"' '.["1"].port = "48989"'; do
    state_with "$(jq -c "${mutation}" <<< "${good}")"
    ! _real_scope_load >/dev/null 2>&1 || fail "malformed display accepted: ${mutation}"
done

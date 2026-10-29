set -euo pipefail

[[ "${STATE_DIR}" == "${HOME}/.local/state/plasmactl" ]]
[[ -d "${STATE_DIR}" ]]
[[ -d "${LOG_DIR}" ]]
declare -F cmd_start >/dev/null
declare -F cmd_stop >/dev/null
[[ "${HOME}" == "${TEST_HOME}/home" ]]

printf 'PASS: plasmactl functions loaded with state under temporary HOME\n'

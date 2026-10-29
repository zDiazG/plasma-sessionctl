#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_file="${1:?Usage: tests/run-isolated.sh path/to/test.bash}"
test_file="$(realpath "${test_file}")"
[[ -f "${test_file}" ]] || { printf 'Test file not found: %s\n' "${test_file}" >&2; exit 2; }

test_home="$(mktemp -d "${TMPDIR:-/tmp}/plasmactl-test.XXXXXX")"
cleanup() { rm -rf -- "${test_home}"; }
trap cleanup EXIT

env -i \
    HOME="${test_home}/home" \
    TEST_HOME="${test_home}" \
    USER="$(id -un)" \
    PATH=/usr/bin:/bin \
    PLASMACTL_REPO_ROOT="${repo_root}" \
    bash --noprofile --norc -c '
        set -euo pipefail
        mkdir -p "${HOME}"
        unset SUDO_USER
        source "${PLASMACTL_REPO_ROOT}/plasmactl" --help >/dev/null
        source "$1"
    ' _ "${test_file}"

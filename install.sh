#!/usr/bin/env bash
set -euo pipefail

source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if ! command -v python3 >/dev/null 2>&1; then
    printf 'Python 3.10+ is required to run bootstrap. Install it with your distribution package manager, then retry.\n' >&2
    exit 1
fi
exec python3 -I "${source_root}/tools/bootstrap.py" "$@"

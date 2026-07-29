#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
lefthook_bin="$repo_root/.venv/bin/lefthook"

if [ ! -x "$lefthook_bin" ] || [ "$("$lefthook_bin" version 2>/dev/null || true)" != "2.1.10" ]; then
    cd "$repo_root"
    uv sync --only-group hooks --frozen
fi

exec "$lefthook_bin" "$@"

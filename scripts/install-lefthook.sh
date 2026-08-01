#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

# Keep the hook runner in the project environment. uvx caches are disposable,
# and a generated hook must not silently select an unrelated PATH binary.
uv sync --only-group hooks --frozen
.venv/bin/lefthook install -f

.venv/bin/python - <<'PY'
from pathlib import Path
import subprocess

marker = 'export LEFTHOOK_BIN="$(git rev-parse --show-toplevel)/scripts/run-lefthook.sh"'
for hook_name in ("pre-commit", "pre-push"):
    hook_path = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--git-path", f"hooks/{hook_name}"],
            text=True,
        ).strip()
    )
    contents = hook_path.read_text()
    lines = [line for line in contents.splitlines() if line != marker]
    lines.insert(1, marker)
    hook_path.write_text("\n".join(lines) + "\n")
PY

.venv/bin/lefthook validate
.venv/bin/lefthook check-install

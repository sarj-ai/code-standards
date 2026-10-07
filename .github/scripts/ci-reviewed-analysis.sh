#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
bash "$root/.github/scripts/release-python.sh" -m sarj_standards.libs.release.reviewed_analysis "$@"

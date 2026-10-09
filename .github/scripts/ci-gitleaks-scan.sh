#!/usr/bin/env bash
set -e

"$RUNNER_TEMP/gitleaks" dir . --config .gitleaks.toml --redact --no-banner
"$RUNNER_TEMP/gitleaks" git --config .gitleaks.toml --redact --no-banner --log-opts='--all'

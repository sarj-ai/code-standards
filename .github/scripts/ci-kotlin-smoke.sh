#!/usr/bin/env bash

set -euo pipefail
repo="$RUNNER_TEMP/mobile-kotlin-smoke"
mkdir -p "$repo/src/main/kotlin/smoke"
printf 'plugins { id("com.android.application") }\n' >"$repo/build.gradle.kts"
printf 'package smoke\n\ninternal const val MOBILE_SMOKE: Int = 1\n' >"$repo/src/main/kotlin/smoke/MobileSmoke.kt"
cli=(uv run --frozen code-standards --root "$repo")
"${cli[@]}" setup --no-install
"${cli[@]}" check --trust-repository-code --format json --output "$repo/report.json" \
  "$repo/src/main/kotlin/smoke/MobileSmoke.kt" || true
jq . "$repo/report.json"
jq --exit-status '.exitCode == 0 and .completion == "complete"' "$repo/report.json" >/dev/null

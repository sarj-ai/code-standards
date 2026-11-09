#!/usr/bin/env bash

set -euo pipefail
export XDG_CACHE_HOME="$RUNNER_TEMP/mobile-kotlin-native-cache"
mobile_cache="$XDG_CACHE_HOME/code-standards/mobile-tools"
mkdir -p "$mobile_cache"
ktlint_version=$(jq --exit-status --raw-output '.ktlint' src/sarj_standards/configs/mobile-tools.versions.json)
detekt_version=$(jq --exit-status --raw-output '.detekt' src/sarj_standards/configs/mobile-tools.versions.json)
# The native provisioner verifies the original checksums before executing these files.
timeout --kill-after=5s 60s gh release download "$ktlint_version" --repo pinterest/ktlint \
  --pattern ktlint --output "$mobile_cache/ktlint-$ktlint_version" --clobber
timeout --kill-after=5s 60s gh release download "v$detekt_version" --repo detekt/detekt \
  --pattern "detekt-cli-$detekt_version-all.jar" --output "$mobile_cache/detekt-$detekt_version.jar" --clobber
repo="$RUNNER_TEMP/mobile-kotlin-smoke"
mkdir -p "$repo/src/main/kotlin/smoke"
printf 'plugins { id("com.android.application") }\n' >"$repo/build.gradle.kts"
printf 'package smoke\n\ninternal const val MOBILE_SMOKE: Int = 1\n' >"$repo/src/main/kotlin/smoke/MobileSmoke.kt"
cli=(uv run --frozen code-standards --root "$repo")
uv run --frozen python -c 'import subprocess; from sarj_standards.libs.linting.mobile_tools import semgrep_command; subprocess.run((*semgrep_command(offline=False), "--version"), check=True)'
"${cli[@]}" setup --no-install
"${cli[@]}" check --trust-repository-code --format json --output "$repo/report.json" \
  "$repo/src/main/kotlin/smoke/MobileSmoke.kt" || true
jq . "$repo/report.json"
jq --exit-status '.exitCode == 0 and .completion == "complete"' "$repo/report.json" >/dev/null

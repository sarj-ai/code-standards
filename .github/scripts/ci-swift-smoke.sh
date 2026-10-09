#!/usr/bin/env bash

set -euo pipefail
repo="$RUNNER_TEMP/mobile-swift-smoke"
mkdir -p "$repo/Sources/Smoke"
printf '// swift-tools-version: 6.2\nimport PackageDescription\nlet package = Package(name: "Smoke", platforms: [.iOS(.v16)])\n' >"$repo/Package.swift"
printf 'import Foundation\n' >"$repo/Sources/Smoke/MobileSmoke.swift"
cli=(uv run --frozen code-standards --root "$repo")
"${cli[@]}" setup --no-install
"${cli[@]}" check --trust-repository-code --format json --output "$repo/report.json" \
  "$repo/Sources/Smoke/MobileSmoke.swift" || true
jq . "$repo/report.json"
jq --exit-status '.exitCode == 0 and .completion == "complete"' "$repo/report.json" >/dev/null

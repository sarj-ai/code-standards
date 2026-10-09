#!/usr/bin/env bash
set -e

echo "$EXPECTED_SHA256  verified-dist/SHA256SUMS" | sha256sum --check --strict
(cd verified-dist && sha256sum --check --strict SHA256SUMS)

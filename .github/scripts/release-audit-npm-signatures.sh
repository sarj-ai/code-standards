#!/usr/bin/env bash
set -euo pipefail

# The registry attestation endpoint intermittently returns a non-JSON body.
# Retry the complete audit; every attempt must verify every signature.
for attempt in 1 2 3; do
  if npm audit signatures --prefer-online --cache "$RUNNER_TEMP/npm-consumer-cache"; then
    exit 0
  fi
  if [[ "$attempt" != 3 ]]; then
    sleep 20
  fi
done
exit 1

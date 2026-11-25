#!/usr/bin/env bash
set -euo pipefail

cache=$1
key="make-fetch-happen:request-cache:$2"
purl=$3
digest=$4
output=$5

lookup=$(printf '%s' "$key" | sha256sum | cut -d ' ' -f 1)
index="$cache/index-v5/${lookup:0:2}/${lookup:2:2}/${lookup:4}"
if [[ ! -f $index ]]; then
  echo "The restored cache has no index entry for the requested attestation."
  exit 0
fi

mapfile -t records < <(
  jq -Rr --arg key "$key" 'try (split("\t")[1] | fromjson | select(.key == $key) | .integrity | strings) catch empty' "$index" | sort -u
)
for integrity in "${records[@]}"; do
  if [[ ! $integrity =~ ^sha512-([A-Za-z0-9+/]{86}==)$ ]]; then
    echo "The cache index contains an unsupported digest format." >&2
    exit 1
  fi
  hash=$(printf '%s' "${BASH_REMATCH[1]}" | base64 --decode | xxd -p -c 64)
  content="$cache/content-v2/sha512/${hash:0:2}/${hash:2:2}/${hash:4}"
  if [[ ! -f $content ]]; then
    continue
  fi
  if [[ $(sha512sum "$content" | cut -d ' ' -f 1) != "$hash" ]]; then
    echo "The cached content failed its recorded integrity check." >&2
    exit 1
  fi
  if jq -e --arg purl "$purl" --arg digest "$digest" -f .github/scripts/observe-npm-envelopes.jq "$content" >/dev/null 2>&1; then
    cp -- "$content" "$output"
    echo "Recovered the matching signed document from the restored cache."
    exit 0
  fi
done

echo "Inspected ${#records[@]} historical body digests. The signed document was absent."

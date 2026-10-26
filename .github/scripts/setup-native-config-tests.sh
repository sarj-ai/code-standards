#!/usr/bin/env bash
set -euo pipefail

directory="$1"
mkdir -p "$directory"
cd "$directory"
# Use the Ubuntu test runner's signed package metadata and native architecture.
# Extraction supplies validators without installing packages or starting services.
# A slow preferred mirror must leave time for APT's healthy alternates.
for attempt in 1 2; do
  if apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 \
    download nginx=1.24.0-2ubuntu7.18 kamailio=5.7.4-1build7 prometheus=2.45.3+ds-2ubuntu0.3; then
    break
  else
    download_status=$?
  fi
  if [[ "$attempt" == 2 ]]; then
    exit "$download_status"
  fi
done
for package in ./*.deb; do
  dpkg-deb --extract "$package" root
done
printf '%s\n' "$directory/root/usr/sbin" "$directory/root/usr/bin" >>"$GITHUB_PATH"

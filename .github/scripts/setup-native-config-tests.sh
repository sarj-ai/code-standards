#!/usr/bin/env bash
set -euo pipefail

directory="$1"
mkdir -p "$directory"
cd "$directory"
# Use the Ubuntu test runner's signed package metadata and native architecture.
# Extraction supplies validators without installing packages or starting services.
apt-get download nginx=1.24.0-2ubuntu7.19 kamailio=5.7.4-1build7 prometheus=2.45.3+ds-2ubuntu0.3
for package in ./*.deb; do
  dpkg-deb --extract "$package" root
done
printf '%s\n' "$directory/root/usr/sbin" "$directory/root/usr/bin" >>"$GITHUB_PATH"

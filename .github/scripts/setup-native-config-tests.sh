#!/usr/bin/env bash
set -euo pipefail

directory="$1"
mkdir -p "$directory"
cd "$directory"
# Use the Ubuntu test runner's signed package metadata and native architecture.
# Extraction supplies validators without installing packages or starting services.
packages=(nginx=1.24.0-2ubuntu7.18 kamailio=5.7.4-1build7 prometheus=2.45.3+ds-2ubuntu0.3)
architecture="$(dpkg --print-architecture)"
archives=()
checksums=()
for package in "${packages[@]}"; do
  archive="${package/=/_}_${architecture}.deb"
  checksum="$(apt-cache show "${package/=/:$architecture=}" | awk '$1 == "SHA256:" { print $2 }' | sort -u)"
  if [[ ! "$checksum" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Expected one repository SHA256 for %s\n' "$package" >&2
    exit 1
  fi
  archives+=("$archive")
  checksums+=("$checksum  $archive")
  # APT can accept an existing archive by size, so validate restored bytes first.
  if [[ -f "$archive" ]] && ! printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c - >/dev/null; then
    rm -- "$archive"
  fi
done
apt-get download "${packages[@]}"
printf '%s\n' "${checksums[@]}" | sha256sum -c - >/dev/null
for archive in "${archives[@]}"; do
  dpkg-deb --extract "$archive" root
done
printf '%s\n' "$directory/root/usr/sbin" "$directory/root/usr/bin" >>"$GITHUB_PATH"

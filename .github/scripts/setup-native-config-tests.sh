#!/usr/bin/env bash
set -euo pipefail

directory="$1"
mkdir -p "$directory"
cd "$directory"
directory="$PWD"
staging="$(mktemp -d "$directory/.native-packages.XXXXXXXX")"
trap 'rm -rf -- "$staging"' EXIT
cd "$staging"
packages=(nginx=1.24.0-2ubuntu7.19 kamailio=5.7.4-1build7 prometheus=2.45.3+ds-2ubuntu0.3)

# Use the Ubuntu test runner's signed package metadata and native architecture.
# apt-get trusts existing archive sizes; validate cached bytes against its metadata.
metadata_status=0
apt-get --print-uris download "${packages[@]}" >package-uris || metadata_status=$?
if [[ "$metadata_status" != 0 ]]; then
  if [[ "${GITHUB_ACTIONS-}" != true || "${RUNNER_ENVIRONMENT-}" != github-hosted ]]; then
    exit "$metadata_status"
  fi
  # Disposable hosted images can retain metadata from before these exact pins.
  apt-cache policy "${packages[@]%%=*}" | sed -E 's#[[:alpha:]][[:alnum:]+.-]*:[^[:space:]]+#[package-index]#g'
  sudo -n timeout 120s apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=15 \
    -o Acquire::https::Timeout=15 -o APT::Update::Error-Mode=any update
  apt-get --print-uris download "${packages[@]}" >package-uris
fi
archives=()
while read -r _uri archive _size checksum extra; do
  if [[ -n "$extra" || "$archive" == */* || "$archive" == -* || "$archive" != *.deb ]]; then
    printf '%s\n' 'Unexpected native package filename' >&2
    exit 1
  fi
  if [[ ! "$checksum" =~ ^SHA256:[[:xdigit:]]{64}$ && ! "$checksum" =~ ^SHA512:[[:xdigit:]]{128}$ ]]; then
    printf '%s\n' 'Native package metadata requires a strong checksum' >&2
    exit 1
  fi
  archives+=("$archive")
  cached="$directory/$archive"
  if [[ -f "$cached" && ! -L "$cached" ]]; then
    if ! /usr/lib/apt/apt-helper download-file "file:$cached" "$archive" "$checksum"; then
      rm -f -- "$archive"
    fi
  fi
done <package-uris
if [[ "${#archives[@]}" != "${#packages[@]}" ]]; then
  printf '%s\n' 'Native package metadata is incomplete' >&2
  exit 1
fi

# A slow preferred mirror must leave time for APT's healthy alternates.
for attempt in 1 2; do
  if apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 \
    download "${packages[@]}"; then
    break
  else
    download_status=$?
  fi
  if [[ "$attempt" == 2 ]]; then
    exit "$download_status"
  fi
done
for archive in "${archives[@]}"; do
  if [[ ! "$archive" -ef "$directory/$archive" ]]; then
    mv -T -- "$archive" "$directory/$archive"
  fi
  dpkg-deb --extract "$directory/$archive" "$directory/root"
done
printf '%s\n' "$directory/root/usr/sbin" "$directory/root/usr/bin" >>"$GITHUB_PATH"

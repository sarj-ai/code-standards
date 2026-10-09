#!/usr/bin/env bash
set -e

directory=$1
shopt -s nullglob
artifacts=("$directory"/*.tgz)
if ((${#artifacts[@]} != 1)); then
  echo 'expected exactly one npm artifact' >&2
  exit 1
fi
if [[ "${artifacts[0]}" != "$directory/package.tgz" ]]; then
  mv -- "${artifacts[0]}" "$directory/package.tgz"
fi

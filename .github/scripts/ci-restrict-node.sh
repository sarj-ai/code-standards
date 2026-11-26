#!/usr/bin/env bash
set -e

# Preinstalled runner Node can be group-writable; native bridges require owner-only write.
node="$(command -v node)"
node_path="$(readlink -f "$node")"
chmod go-w "$node_path"

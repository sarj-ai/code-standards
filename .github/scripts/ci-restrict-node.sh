#!/usr/bin/env bash
set -e

# Preinstalled runner Node can be group-writable; native bridges require owner-only write.
node_path="$(readlink -f "$(command -v node)")"
chmod go-w "$node_path"

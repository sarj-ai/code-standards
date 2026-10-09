#!/usr/bin/env bash
set -e

uv python install 3.15
uv sync --project packages/standards --locked --no-dev
npm --prefix packages/typescript ci --ignore-scripts --no-audit --no-fund
npm --prefix apps/docs ci --ignore-scripts --no-audit --no-fund

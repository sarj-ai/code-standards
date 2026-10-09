#!/usr/bin/env bash
set -e

uv build
uv build --project ../standards-compat --out-dir dist
uv build --wheel --project ../contracts --out-dir dist/deps
uv build --wheel --project ../python --out-dir dist/deps
uv build --wheel --project ../sql --out-dir dist/deps
uv build --wheel --project ../iac --out-dir dist/deps

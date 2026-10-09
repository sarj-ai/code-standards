#!/usr/bin/env bash
set -e

mkdir publish-dist
cp verified-dist/*.whl verified-dist/*.tar.gz publish-dist/

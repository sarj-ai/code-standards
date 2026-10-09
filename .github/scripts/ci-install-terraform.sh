#!/usr/bin/env bash
set -e

archive="$RUNNER_TEMP/terraform.zip"
install_dir="$RUNNER_TEMP/terraform-bin"
curl --fail --silent --show-error --location \
  --output "$archive" \
  "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip"
echo "$TERRAFORM_SHA256  $archive" | sha256sum --check --strict
mkdir --parents "$install_dir"
unzip -q "$archive" -d "$install_dir"
echo "$install_dir" >>"$GITHUB_PATH"

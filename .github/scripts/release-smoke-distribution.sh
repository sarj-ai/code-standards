#!/usr/bin/env bash
set -e

package=$1
format=$2
case "$package" in
  bootstrap)
    module=sarj_standards_bootstrap
    cli=code-standards
    ;;
  contracts)
    module=sarj_rule_contracts
    cli=
    ;;
  python)
    module=sarj_python_lint
    cli=sarj-python-lint
    ;;
  sql)
    module=sarj_sql_lint
    cli=sarj-sql-lint
    ;;
  iac)
    module=sarj_iac_lint
    cli=sarj-iac-lint
    ;;
  standards)
    module=
    cli=code-standards
    ;;
  *) exit 64 ;;
esac
environment="$RUNNER_TEMP/$package-$format"
uv venv --python "${STANDARDS_PYTHON:-3.15}" "$environment"
case "$format" in
  wheel) uv pip install --python "$environment/bin/python" dist/*.whl ;;
  sdist)
    if [[ "$package" == standards ]]; then
      uv pip install --python "$environment/bin/python" --find-links dist/deps dist/*.tar.gz
    else
      uv pip install --python "$environment/bin/python" dist/*.tar.gz
    fi
    ;;
  *) exit 64 ;;
esac
if [[ "$format" == wheel || "$package" == contracts ]]; then
  "$environment/bin/python" ../../.github/scripts/release-import-smoke.py "$module"
fi
if [[ "$package" == bootstrap ]]; then
  if [[ "$format" == wheel ]]; then
    mkdir -p "$RUNNER_TEMP/fake-bin"
    printf '%s\n' '#!/bin/sh' \
      "printf \"%s\\n\" \"\$@\" > \"\$BOOTSTRAP_CAPTURE\"" >"$RUNNER_TEMP/fake-bin/uvx"
    chmod +x "$RUNNER_TEMP/fake-bin/uvx"
  fi
  BOOTSTRAP_CAPTURE="$RUNNER_TEMP/$format-argv" PATH="$RUNNER_TEMP/fake-bin:$PATH" \
    "$environment/bin/code-standards" --root "$GITHUB_WORKSPACE" check
  grep -Fx -- 'code-standards' "$RUNNER_TEMP/$format-argv"
  grep -E '^code-standards==[0-9]+\.[0-9]+\.[0-9]+$' "$RUNNER_TEMP/$format-argv"
elif [[ -n "$cli" ]]; then
  "$environment/bin/$cli" --help
fi

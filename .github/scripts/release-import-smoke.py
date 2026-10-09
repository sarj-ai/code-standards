from __future__ import annotations  # ruff: ignore[implicit-namespace-package] -- standalone wheel smoke entrypoint.

import importlib
import sys


def main() -> None:
    module = sys.argv[1]
    if module not in {
        "sarj_standards_bootstrap",
        "sarj_rule_contracts",
        "sarj_python_lint",
        "sarj_sql_lint",
        "sarj_iac_lint",
    }:
        message = "unsupported release smoke module"
        raise SystemExit(message)
    importlib.import_module(module)


if __name__ == "__main__":
    main()

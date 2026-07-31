#!/usr/bin/env python3
"""Regenerate `rule-ledger.json` from the live registries, retiring what vanished.

Run via `make sync-rule-ledger`. The point of the script -- as opposed to editing
the ledger by hand -- is that it never DELETES an identifier. A rule that leaves a
registry is moved into `retired`, because that is the only record a consumer repo
can act on: ESLint exits 2 on a config naming a rule the plugin no longer defines,
and pre-commit fails on a hook id that no longer exists, so the removal has to
survive somewhere machine-readable or every upgrade past it is a hard crash.

The freshly-retired entry gets a placeholder note for a human to replace, and
`status: "removed"`. Change it to `renamed` with a `replacement` when that is what
happened; `tests/test_rule_ledger.py` checks the result either way.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Final


ROOT: Final = Path(__file__).resolve().parents[1]
LEDGER: Final = (
    ROOT / "packages/lint-configs/src/sarj_lint_configs/configs/rule-ledger.json"
)

#: `"rule-name": ruleImplementation,` inside the `const rules = {` map of index.ts.
#: Leading whitespace is optional because the map has been formatted both ways.
_ESLINT_KEY: Final = re.compile(r'^\s*"(?P<name>[a-z0-9-]+)":', re.MULTILINE)
_ESLINT_MAP: Final = re.compile(r"^const rules = \{$(?P<body>.*?)^\};$", re.M | re.S)

_PLACEHOLDER: Final = "TODO: say why it went, in one line a consumer can act on"

_PYTHON_FAMILIES: Final = ("python", "sql", "iac")

#: `"old-name": "new-name",` inside the plugin's `renamedRules` map.
_RENAME_ENTRY: Final = re.compile(r'^\s*"(?P<old>[a-z0-9-]+)": "(?P<new>[a-z0-9-]+)",', re.M)


def eslint_rules() -> list[str]:
    """Read the ESLint rule names out of the plugin's rules map.

    Parsed rather than imported because the plugin is TypeScript and this script
    has no build step; `strict-config-sync.test.ts` re-checks the same list
    against the real `rules` export, so a parse that drifts fails there.

    Returns:
        Rule names, without the `@sarj/` prefix, sorted.

    Raises:
        SystemExit: When the rules map cannot be found.

    """
    text = (ROOT / "packages/typescript/src/index.ts").read_text(encoding="utf-8")
    body = _ESLINT_MAP.search(text)
    if body is None:
        sys.exit("error: could not find `const rules = {` in packages/typescript/src/index.ts")
    return sorted(match.group("name") for match in _ESLINT_KEY.finditer(body.group("body")))


def eslint_renames() -> dict[str, str]:
    """Read the plugin's own rename map, so the ledger cannot disagree with it.

    A rename is recorded in two places by necessity: the plugin keeps the old name
    registered as a deprecated alias (so a stale config still resolves), and the
    ledger tells a consumer what to write instead. Deriving the second from the
    first is what stops them drifting.

    Returns:
        Old rule name to new rule name.

    """
    text = (ROOT / "packages/typescript/src/rules/_renames.ts").read_text(encoding="utf-8")
    return {match.group("old"): match.group("new") for match in _RENAME_ENTRY.finditer(text)}


def python_family(package: str, module: str) -> tuple[list[str], list[str]]:
    """Dump one Python package's registry through its own uv environment.

    Returns:
        Its rule ids and its rule codes, both sorted.

    Raises:
        SystemExit: When the package's environment cannot report its registry.

    """
    program = (
        f"import json; from {module}.rules import REGISTRY;"
        " print(json.dumps({'ids': sorted(REGISTRY),"
        " 'codes': sorted(rule.code for rule in REGISTRY.values())}))"
    )
    completed = subprocess.run(  # noqa: S603 -- fixed argv, no shell, dev-only script
        ["uv", "run", "--project", str(ROOT / "packages" / package), "python", "-c", program],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    if completed.returncode != 0:
        sys.exit(f"error: could not read the {package} registry:\n{completed.stderr}")
    parsed: dict[str, list[str]] = json.loads(completed.stdout.strip().splitlines()[-1])
    return parsed["ids"], parsed["codes"]


def main() -> int:
    """Rewrite the ledger in place.

    Returns:
        0 when the ledger already matched, 1 when it was rewritten.

    """
    previous: dict[str, object] = json.loads(LEDGER.read_text(encoding="utf-8"))
    rules: dict[str, list[str]] = {"eslint": eslint_rules()}
    codes: dict[str, list[str]] = {}
    for family in _PYTHON_FAMILIES:
        module = f"sarj_{family}_lint"
        rules[family], codes[family] = python_family(family, module)

    old_rules: dict[str, list[str]] = dict(previous.get("rules", {}))  # pyright: ignore[reportArgumentType]
    old_codes: dict[str, list[str]] = dict(previous.get("codes", {}))  # pyright: ignore[reportArgumentType]
    retired: list[dict[str, str | None]] = [
        entry
        for entry in previous.get("retired", [])  # pyright: ignore[reportArgumentType]
        if entry["kind"] != "eslint" or entry["status"] != "renamed"
    ]
    for old, new in sorted(eslint_renames().items()):
        retired.append({
            "id": f"@sarj/{old}",
            "kind": "eslint",
            "status": "renamed",
            "replacement": f"@sarj/{new}",
            "note": (
                f"renamed to {new}. The old name is still registered as a deprecated"
                " alias, so a stale config keeps resolving and ESLint reports the"
                " rename -- but the alias goes away eventually. Rewrite the reference."
            ),
        })
    known = {entry["id"] for entry in retired}

    for family, names in old_rules.items():
        prefix = "@sarj/" if family == "eslint" else ""
        for name in names:
            if name not in rules.get(family, []) and f"{prefix}{name}" not in known:
                retired.append({
                    "id": f"{prefix}{name}",
                    "kind": family,
                    "status": "removed",
                    "replacement": None,
                    "note": _PLACEHOLDER,
                })
    for family, family_codes in old_codes.items():
        for code in family_codes:
            if code not in codes.get(family, []) and code not in known:
                retired.append({
                    "id": code,
                    "kind": "code",
                    "status": "removed",
                    "replacement": None,
                    "note": _PLACEHOLDER,
                })

    updated = {
        "$comment": previous["$comment"],
        "rules": rules,
        "codes": codes,
        "retired": sorted(retired, key=lambda entry: str(entry["id"])),
    }
    rendered = json.dumps(updated, indent=2) + "\n"
    if rendered == LEDGER.read_text(encoding="utf-8"):
        print(f"ok: {LEDGER.name} already matches the registries")
        return 0
    _ = LEDGER.write_text(rendered, encoding="utf-8")
    print(f"wrote: {LEDGER}")
    if any(entry["note"] == _PLACEHOLDER for entry in retired):
        print("note:  a retired entry still carries the placeholder note -- replace it")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Every registered rule must be reachable from pre-commit, and every hook must be real.

A rule that is written, tested and registered but has no `.pre-commit-hooks.yaml` entry
is inert: it never runs in any consumer repo, and nothing fails to tell you. Fifteen of
the thirty-nine rules live at the 0.15.x line were in exactly that state — a
security- and SQL-heavy set including SARJ011 prefer-constant-time-secret-compare,
SARJ012 no-secret-in-log, SARJ028 no-cors-wildcard-with-credentials and SARJ018-021,
every one of which has a TypeScript twin that *was* wired. The same defect was caught
in a `.py` file and missed in a `.ts` file purely because the TypeScript package has
`strict-config-sync.test.ts` and Python had no equivalent.

This is that equivalent. It is deliberately bidirectional: an orphan hook naming a rule
that no longer exists is just as broken as a rule with no hook, and it is the shape a
rule rename leaves behind.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from sarj_python_lint.rules import REGISTRY


_HOOKS_PATH = Path(__file__).resolve().parents[3] / ".pre-commit-hooks.yaml"

# `- id: sarj-<rule-id>` — the hook id is the rule id under a `sarj-` prefix.
_HOOK_ID_RE = re.compile(r"^- id: sarj-([a-z0-9-]+)$", re.MULTILINE)

# `entry: sarj-python-lint check --rule <rule-id>` — only this package's hooks.
_PYTHON_ENTRY_RE = re.compile(r"^  entry: sarj-python-lint check --rule ([a-z0-9-]+)$", re.MULTILINE)


def _hooked_rule_ids() -> set[str]:
    return set(_PYTHON_ENTRY_RE.findall(_HOOKS_PATH.read_text(encoding="utf-8")))


def test_hooks_file_exists() -> None:
    assert _HOOKS_PATH.is_file(), f"expected pre-commit hooks at {_HOOKS_PATH}"


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_every_registered_rule_has_a_hook(rule_id: str) -> None:
    assert rule_id in _hooked_rule_ids(), (
        f"{rule_id} ({REGISTRY[rule_id].code}) is registered but has no pre-commit hook, "
        f"so it never runs in a consumer repo. Add a `- id: sarj-{rule_id}` stanza to "
        f"{_HOOKS_PATH.name}."
    )


def test_no_hook_names_an_unknown_rule() -> None:
    orphans = sorted(_hooked_rule_ids() - set(REGISTRY))
    assert not orphans, (
        f"pre-commit hooks name rules that are not in the REGISTRY: {orphans}. "
        "A renamed or retired rule leaves this behind, and the hook fails at run time."
    )


def test_hook_ids_match_their_entry_rule() -> None:
    text = _HOOKS_PATH.read_text(encoding="utf-8")
    hook_ids = _HOOK_ID_RE.findall(text)
    entries = _PYTHON_ENTRY_RE.findall(text)
    mismatched = [hid for hid in hook_ids if hid in REGISTRY and hid not in entries]
    assert not mismatched, f"hook id `sarj-{mismatched}` does not run `--rule {mismatched}`"

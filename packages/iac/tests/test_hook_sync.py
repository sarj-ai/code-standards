"""Tests rendering every registered rule reachable via pre-commit hooks."""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from sarj_iac_lint.rules import REGISTRY


_HOOKS_PATH = Path(__file__).resolve().parents[3] / ".pre-commit-hooks.yaml"

_HOOK_ID_RE = re.compile(r"^- id: sarj-([a-z0-9-]+)$", re.MULTILINE)
_ENTRY_RE = re.compile(r"^  entry: sarj-iac-lint check --rule ([a-z0-9-]+)$", re.MULTILINE)


def _hooked_rule_ids() -> set[str]:
    return set(_ENTRY_RE.findall(_HOOKS_PATH.read_text(encoding="utf-8")))


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
        f"pre-commit hooks name IaC rules that are not in the REGISTRY: {orphans}. "
        "A renamed or retired rule leaves this behind, and the hook fails at run time."
    )


def test_hook_ids_match_their_entry_rule() -> None:
    text = _HOOKS_PATH.read_text(encoding="utf-8")
    hook_ids = [match.group(1) for match in _HOOK_ID_RE.finditer(text)]
    entries = set(_ENTRY_RE.findall(text))
    mismatched = [hid for hid in hook_ids if hid in REGISTRY and hid not in entries]
    assert not mismatched, f"hook id `sarj-{mismatched}` does not run `--rule {mismatched}`"

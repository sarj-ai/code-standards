"""Every rule must be self-documenting: non-empty id, code, description, and a docstring.

Also the gate on code allocation. Two rules sharing a `SARJ###`, or a new rule claiming
a code the registry has already retired, are both invisible at runtime — the CLI keys on
`id`, so a duplicate code produces two findings under one label and `--rule` still works.
The failure mode is a merge: two branches developed in parallel each pick "the next free
code" against the main they branched from, and nothing objects when they meet. That
happened to the SARJ055-068 wave, which was authored as SARJ048-063 against a main that
had since allocated SARJ048-054 — five silent collisions, caught by reading a version
number rather than by any test. These three asserts are that test.
"""

from __future__ import annotations

import re

import pytest

from sarj_python_lint.rule_base import Rule
from sarj_python_lint.rules import REGISTRY


# `SARJ` + exactly three digits. Anything else breaks `# sarj-noqa: SARJ###` parsing and
# the ruff `external = ["SARJ"]` handoff.
_CODE_RE = re.compile(r"^SARJ\d{3}$")

# Codes that were allocated and then withdrawn. Reusing one silently rewrites history:
# an old `# sarj-noqa: SARJ033` in a consumer repo would begin suppressing a new,
# unrelated rule. Keep in sync with the retired-codes comment in rules/_registry.py.
_RETIRED_CODES = frozenset(
    {
        "SARJ004",
        "SARJ005",
        "SARJ027",
        "SARJ029",
        "SARJ030",
        "SARJ033",
        "SARJ035",
        "SARJ037",
        "SARJ055",
        "SARJ072",
        "SARJ073",
    }
)


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_rule_has_self_documenting_meta(rule_id: str) -> None:
    cls = REGISTRY[rule_id]
    assert issubclass(cls, Rule)

    assert cls.id == rule_id, f"REGISTRY key {rule_id!r} != cls.id {cls.id!r}"
    assert cls.id, f"{rule_id}: empty id"
    assert cls.id.replace("-", "").replace("_", "").isalnum(), f"{rule_id}: id must be kebab/snake-case, got {cls.id!r}"

    assert cls.code, f"{rule_id}: missing code"
    assert _CODE_RE.match(cls.code), f"{rule_id}: code {cls.code!r} must be SARJ + exactly three digits"

    assert cls.description, f"{rule_id}: empty description"
    assert len(cls.description) >= 10, f"{rule_id}: description too short ({cls.description!r})"

    assert cls.__doc__, f"{rule_id}: missing docstring"


def test_registry_keys_match_class_ids() -> None:
    for key, cls in REGISTRY.items():
        assert key == cls.id, f"REGISTRY[{key!r}].id = {cls.id!r} (mismatch)"


def test_no_two_rules_share_a_code() -> None:
    """Two rules on one `SARJ###` are indistinguishable in output and in suppressions."""
    seen: dict[str, str] = {}
    collisions: list[str] = []
    for rule_id in sorted(REGISTRY):
        code = REGISTRY[rule_id].code
        if code in seen:
            collisions.append(f"{code}: {seen[code]} and {rule_id}")
        else:
            seen[code] = rule_id
    assert not collisions, (
        "duplicate SARJ codes: "
        + "; ".join(collisions)
        + ". Two branches most likely each claimed the next free code against different bases — "
        "renumber the newer rule and check rules/_registry.py's retired-codes comment for the "
        "true high-water mark."
    )


def test_no_rule_reuses_a_retired_code() -> None:
    """A retired code stays burned: an old suppression must never bind to a new rule."""
    reused = sorted(f"{REGISTRY[r].code} ({r})" for r in REGISTRY if REGISTRY[r].code in _RETIRED_CODES)
    assert not reused, (
        f"rule(s) claim a retired code: {reused}. A `# sarj-noqa: <code>` written for the old "
        "rule would silently suppress the new one; pick the next unallocated code instead."
    )

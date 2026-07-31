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
import sys

import pytest

from sarj_python_lint.rule_base import Rule
from sarj_python_lint.rules import REGISTRY


# `SARJ` + exactly three digits. Anything else breaks `# sarj-noqa: SARJ###` parsing and
# the ruff `external = ["SARJ"]` handoff.
_CODE_RE = re.compile(r"^SARJ\d{3}$")

# The same shape unanchored, for finding the first code mentioned in prose.
_CODE_IN_TEXT_RE = re.compile(r"SARJ\d{3}")

# Codes that must never be reallocated. Reusing one rewrites history: a
# `# sarj-noqa: SARJ027` sitting in a consumer repo would begin silently
# suppressing whatever new rule took the code.
#
# THE CRITERION IS "could a consumer hold a suppression for this code", not "was
# it ever live in a published tag". Those are not the same question, and getting
# it wrong is silent in both directions.
#
# History, because this list has been wrong in both directions:
#
# 1. It first carried eleven codes, conflating "reserved then abandoned" with
#    "published then withdrawn". That made the gate reject
#    `no-implicit-attribute-access` (#147), which took SARJ055 legitimately.
# 2. Fixing that, it was narrowed to the three codes a `python-v*` tag walk
#    proved were live rule modules. That narrowing was WRONG. A scan of
#    first-party consumers found a live `# sarj-noqa: SARJ005 — pre-existing,
#    out of scope` (on a `pydantic.BaseModel` subclass in a store module) for a
#    code the tag walk says was never a shipped rule module. However that
#    suppression came to be written, it exists, and a new rule claiming SARJ005
#    would inherit it.
#
# So the tag walk is not sufficient evidence, and burning a code is nearly free:
# the space is `SARJ000`-`SARJ999` and 71 are allocated. Anything ever written
# down as retired stays retired.
#
# SARJ055 was the one code deliberately let through, because
# `no-implicit-attribute-access` had claimed it. #154 then renumbered that rule
# to SARJ083, so SARJ055 is unallocated again and goes back on the list — there
# is now no rule holding it and no reason to leave it reusable.
_RETIRED_CODES = frozenset(
    {
        # Live in a published tag, withdrawn in 0.11.1 as too noisy.
        "SARJ027",
        "SARJ029",
        "SARJ030",
        # Reserved and abandoned pre-release. Not provably shipped, but SARJ005
        # is proof that "not shipped" does not imply "not suppressed anywhere",
        # so the whole cohort stays burned.
        "SARJ004",
        "SARJ005",
        "SARJ033",
        "SARJ035",
        "SARJ037",
        "SARJ072",
        "SARJ073",
        # Briefly held `no-implicit-attribute-access` (#147) before #154 moved
        # that rule to SARJ083. Retired rather than recycled.
        "SARJ055",
        # Shipped, then withdrawn as redundant.
        #
        # SARJ075 `primary-export-file-name` gave actively harmful advice: it
        # told you to rename `0001_initial.py` to `migration.py` (breaking
        # Django's filename-ordered migration graph) and `tests.py` to
        # `thing_tests.py` (breaking test discovery), and to rename
        # domain-named modules like `pagination.py` after their one current
        # export — the exact regression SARJ022 `single-public-export`'s
        # docstring refuses to make. SARJ022 is silent on all three and covers
        # the junk-drawer-stem case that is worth flagging.
        "SARJ075",
        # SARJ079 `prefer-pattern-matching` was a copy-paste amalgam of
        # SARJ069/070/081/032 — same positions AND byte-identical message text,
        # so `# sarj-noqa: SARJ079` was an unreviewable blanket silencing four
        # independent judgements on one line.
        "SARJ079",
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


def test_docstring_header_code_matches_class_code() -> None:
    """A module docstring naming the wrong code hands users a suppression that silently does nothing.

    Module docstrings are the spec here, and they are also the user-facing
    documentation: several tell the reader which `# sarj-noqa: SARJ###` to write.
    When the header code and `cls.code` disagree, that instruction is wrong in
    the one way nothing catches — `is_suppressed` looks for the *real* code, so a
    reader who follows the docs gets no suppression and no error either.

    This drifted for 7 of the SARJ076-082 rules, all casualties of the two
    renumbering waves that moved the block from SARJ048-063 to its final codes.
    `prefer_non_nullable_collection` told readers to write
    `# sarj-noqa: SARJ074`, an unallocated code; the tests above gate uniqueness
    and retirement but never compared the prose to the class, which is why the
    other two asserts stayed green through the whole drift.
    """
    mismatches: list[str] = []
    for rule_id in sorted(REGISTRY):
        cls = REGISTRY[rule_id]
        doc = sys.modules[cls.__module__].__doc__ or ""
        found = _CODE_IN_TEXT_RE.search(doc)
        header = found.group(0) if found else None
        if header != cls.code:
            mismatches.append(f"{cls.__module__}: docstring says {header}, cls.code is {cls.code}")
    assert not mismatches, (
        "module docstring header code != cls.code:\n  "
        + "\n  ".join(mismatches)
        + "\nThe docstring is the spec and the user-facing suppression instruction; a wrong "
        "code there documents a `# sarj-noqa` that silently does nothing."
    )


def test_no_rule_reuses_a_retired_code() -> None:
    """A retired code stays burned: an old suppression must never bind to a new rule."""
    reused = sorted(f"{REGISTRY[r].code} ({r})" for r in REGISTRY if REGISTRY[r].code in _RETIRED_CODES)
    assert not reused, (
        f"rule(s) claim a retired code: {reused}. A `# sarj-noqa: <code>` written for the old "
        "rule would silently suppress the new one; pick the next unallocated code instead."
    )

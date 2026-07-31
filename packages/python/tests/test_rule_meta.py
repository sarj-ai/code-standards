"""Every rule must be self-documenting: non-empty id, code, description, and EXAMPLES.

The docstring gate used to read `assert cls.__doc__`, and it was measuring the wrong
thing. It could be satisfied by one restated sentence and it was equally satisfied by
260 lines of corpus tables, so it exerted upward pressure on prose and none at all on
whether the rule was actually documented. 45.5% of this package's rule source was
docstrings and comments, and none of the docstring-ceremony rules this repo ships
(SARJ049/050/051/084/085/086) flagged a line of it.

What replaced it: a rule is documented when its behaviour is pinned by a test module
and its links to that module resolve. `test_every_rule_has_an_examples_module` is the
new floor — examples cannot rot into vagueness the way prose can, because they run.
The links are DERIVED (`Rule.examples_path`, `Rule.evidence_path`) rather than written,
so a rename fails this file instead of leaving a dead URL in a docstring.

`_DOCSTRING_BUDGET` is the ratchet that gets the remaining rules there: an entry may
shrink or be deleted, never grow, and no rule may be added to it.

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

import json
from pathlib import Path
import re
import sys

import pytest

from sarj_python_lint.rule_base import REPO_BLOB, Rule
from sarj_python_lint.rules import REGISTRY


# tests/ -> packages/python -> packages -> repo root. The derived link paths are
# repo-relative, so they only resolve from here.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Rules still carrying a pre-doc-diet module docstring, with today's content-line
# count as the ceiling. SHRINK-ONLY: converting a rule deletes its entry, and a rule
# that is not listed must already match the strict shape. Nothing may be added.
_BUDGET_PATH = Path(__file__).parent / "rule_docstring_budget.json"

# Content lines allowed in a converted rule's module docstring: the `SARJ### — claim`
# summary, an optional short rationale, and the two derived link lines. The cap is what
# stops the 260-line docstring growing back one useful paragraph at a time.
_MAX_DOCSTRING_LINES = 6

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


def _module_docstring(cls: type[Rule]) -> str:
    return sys.modules[cls.__module__].__doc__ or ""


def _content_lines(doc: str) -> list[str]:
    return [line for line in doc.strip().splitlines() if line.strip()]


def _budget() -> dict[str, int]:
    if not _BUDGET_PATH.is_file():
        return {}
    raw: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped boundary; narrowed below
        _BUDGET_PATH.read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict), "budget file must be a {rule-id: line-count} object"
    return {
        k: v
        for k, v in raw.items()  # pyright: ignore[reportUnknownVariableType] — json.loads yields Any leaves
        if isinstance(k, str) and isinstance(v, int)
    }


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_every_rule_has_an_examples_module(rule_id: str) -> None:
    """The replacement for `assert cls.__doc__`: behaviour is pinned by tests, not prose.

    A docstring can restate the signature and still satisfy a truthiness check. A test
    module cannot — it runs, so it either describes the rule or fails.
    """
    cls = REGISTRY[rule_id]
    examples = _REPO_ROOT / cls.examples_path()
    assert examples.is_file(), (
        f"{rule_id}: no examples module at {cls.examples_path()}. Every rule's examples live at "
        f"tests/rules/test_<module>.py, derived from the rule's module name — create it, or rename "
        f"the rule module to match its tests."
    )
    assert examples.stat().st_size > 0, f"{rule_id}: {cls.examples_path()} is empty"


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_evidence_flag_matches_the_filesystem(rule_id: str) -> None:
    """`has_evidence` is declared, not probed, so this is what keeps it true.

    It has to be declared: the CLI prints the evidence link from an installed wheel,
    which does not ship `docs/`. This test is the only thing standing between a
    declared flag and a 404.
    """
    cls = REGISTRY[rule_id]
    exists = (_REPO_ROOT / cls.evidence_path()).is_file()
    assert cls.has_evidence == exists, (
        f"{rule_id}: has_evidence={cls.has_evidence} but {cls.evidence_path()} "
        f"{'exists' if exists else 'does not exist'}"
    )


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_module_docstring_is_a_summary_plus_derived_links(rule_id: str) -> None:
    """A converted rule's docstring is a one-line claim and the two generated links.

    Rules still listed in `_DOCSTRING_BUDGET` are exempt from the shape but not from the
    ceiling — see `test_docstring_budget_only_shrinks`.
    """
    cls = REGISTRY[rule_id]
    doc = _module_docstring(cls)
    lines = _content_lines(doc)
    if rule_id in _budget():
        pytest.skip(f"{rule_id} is still on the docstring budget")

    assert lines, f"{rule_id}: empty module docstring"
    assert len(lines) <= _MAX_DOCSTRING_LINES, (
        f"{rule_id}: module docstring is {len(lines)} content lines, cap is {_MAX_DOCSTRING_LINES}. "
        f"Measurements belong in {cls.evidence_path()}; examples belong in {cls.examples_path()}."
    )

    expected_examples = f"Examples: {cls.examples_url()}"
    assert expected_examples in lines, (
        f"{rule_id}: module docstring must carry the derived examples link.\n  expected: {expected_examples}"
    )
    expected_evidence = f"Evidence: {cls.evidence_url()}"
    if cls.has_evidence:
        assert expected_evidence in lines, (
            f"{rule_id}: has_evidence is set, so the docstring must carry\n  {expected_evidence}"
        )
    else:
        assert expected_evidence not in lines, f"{rule_id}: docstring links evidence that does not exist"


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_no_rule_hand_writes_a_link(rule_id: str) -> None:
    """Links are derived from `__module__` and `code`; a hand-typed one goes stale on rename."""
    cls = REGISTRY[rule_id]
    doc = _module_docstring(cls)
    derived = {cls.examples_url(), cls.evidence_url()}
    stray = [
        line.strip()
        for line in doc.splitlines()
        if REPO_BLOB in line and not any(url in line for url in derived)
    ]
    assert not stray, (
        f"{rule_id}: docstring hand-writes a repo link that `Rule.examples_url()` / "
        f"`Rule.evidence_url()` do not generate:\n  " + "\n  ".join(stray)
    )


def test_docstring_budget_only_shrinks() -> None:
    """The migration ratchet: an entry may shrink or vanish, never grow, and none may be added."""
    budget = _budget()
    unknown = sorted(set(budget) - set(REGISTRY))
    assert not unknown, f"budget names rules that do not exist: {unknown}. Delete the stale entries."

    over = [
        f"{rule_id}: {actual} content lines, budget {allowed}"
        for rule_id, allowed in sorted(budget.items())
        if (actual := len(_content_lines(_module_docstring(REGISTRY[rule_id])))) > allowed
    ]
    assert not over, (
        "module docstring grew past its budget:\n  "
        + "\n  ".join(over)
        + f"\nThe budget is shrink-only. Convert the rule instead: one `{'{code}'} — claim` line, the "
        "derived Examples/Evidence links, and the measurements moved to docs/rules/<CODE>.md."
    )

    slack = [
        f"{rule_id}: budget {allowed}, actual {actual}"
        for rule_id, allowed in sorted(budget.items())
        if (actual := len(_content_lines(_module_docstring(REGISTRY[rule_id])))) < allowed
    ]
    assert not slack, (
        "budget entries are looser than reality, which lets prose grow back silently:\n  "
        + "\n  ".join(slack)
        + "\nTighten them to the actual counts."
    )


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

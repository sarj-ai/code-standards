"""Every rule must be self-documenting: non-empty id, code, description, and EXAMPLES."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import warnings

import pytest

from sarj_python_lint.rule_base import REPO_BLOB, Rule
from sarj_python_lint.rules import REGISTRY


# tests/ -> packages/python -> packages -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Content lines allowed in a rule's module docstring: the `SARJ### — claim` summary, an optional short rationale, and the two derived link lines.
_MAX_DOCSTRING_LINES = 4

# `SARJ` + exactly three digits.
_CODE_RE = re.compile(r"^SARJ\d{3}$")

# The same shape unanchored, for finding the first code mentioned in prose.
_CODE_IN_TEXT_RE = re.compile(r"SARJ\d{3}")

# Every SARJ code ever allocated or reserved, mapped to the rule that held it (`null` = reserved but never a rule module).
_LEDGER_PATH = Path(__file__).parent / "code_ledger.json"

# The rules directory, relative to the repo root — the path git history is walked
# over to recover deleted rule modules.
_RULES_DIR = "packages/python/src/sarj_python_lint/rules"


def _ledger() -> dict[str, str | None]:
    raw: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped boundary; narrowed below
        _LEDGER_PATH.read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict), "code_ledger.json must be a {SARJ###: rule-id | null} object"
    entries: dict[str, str | None] = {}
    for code, rule_id in raw.items():  # pyright: ignore[reportUnknownVariableType] — json.loads yields Any leaves
        assert isinstance(code, str), f"ledger key {code!r} is not a string"
        assert _CODE_RE.match(code), f"ledger key {code!r} is not a SARJ### code"
        assert rule_id is None or isinstance(rule_id, str), f"ledger[{code}] must be a rule id or null"
        entries[code] = rule_id
    return entries


def _git(*args: str) -> str:
    """Run git at the repo root, or skip the calling test if history is unavailable."""
    try:
        done = subprocess.run(
            ("git", "-C", str(_REPO_ROOT), *args),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover — environment, not logic
        pytest.skip(f"git history unavailable ({exc}); this gate needs a full clone")
    return done.stdout


def _deleted_rule_modules() -> dict[str, str]:
    """`{SARJ###: module stem}` for every rule module git has ever seen deleted."""
    assert _git("rev-parse", "--is-shallow-repository").strip() == "false", (
        "this gate reads deleted rule modules out of git history; check out with fetch-depth: 0"
    )

    log = _git(
        "log",
        "--no-renames",
        "--diff-filter=D",
        "--name-only",
        "--format=%x00%H",
        "HEAD",
        "--",
        _RULES_DIR,
    )
    deleted: dict[str, str] = {}
    commit = ""
    for raw_line in log.splitlines():
        line = raw_line.strip()
        if line.startswith("\x00"):
            commit = line[1:]
            continue
        stem = line.rsplit("/", maxsplit=1)[-1]
        if not line.endswith(".py") or stem.startswith("_"):
            continue
        if found := _CODE_IN_TEXT_RE.search(_git("show", f"{commit}^:{line}")):
            deleted[found.group(0)] = stem[: -len(".py")]
    return deleted


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


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_every_rule_has_an_examples_module(rule_id: str) -> None:
    """The replacement for `assert cls.__doc__`: behaviour is pinned by tests, not prose."""
    cls = REGISTRY[rule_id]
    examples = _REPO_ROOT / cls.examples_path()
    assert examples.is_file(), (
        f"{rule_id}: no examples module at {cls.examples_path()}. Every rule's examples live at "
        f"tests/rules/test_<module>.py, derived from the rule's module name — create it, or rename "
        f"the rule module to match its tests."
    )
    assert examples.stat().st_size > 0, f"{rule_id}: {cls.examples_path()} is empty"


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_module_docstring_is_a_summary_plus_derived_links(rule_id: str) -> None:
    """Every rule's docstring is a concise claim plus its executable examples."""
    cls = REGISTRY[rule_id]
    doc = _module_docstring(cls)
    lines = _content_lines(doc)

    assert lines, f"{rule_id}: empty module docstring"
    assert len(lines) <= _MAX_DOCSTRING_LINES, (
        f"{rule_id}: module docstring is {len(lines)} content lines, cap is {_MAX_DOCSTRING_LINES}. "
        f"Put behavior in {cls.examples_path()}, not prose."
    )

    expected_examples = f"Examples: {cls.examples_url()}"
    assert expected_examples in lines, (
        f"{rule_id}: module docstring must carry the derived examples link.\n  expected: {expected_examples}"
    )


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_no_rule_hand_writes_a_link(rule_id: str) -> None:
    """The examples link is derived from `__module__`; other repo links go stale."""
    cls = REGISTRY[rule_id]
    doc = _module_docstring(cls)
    stray = [line.strip() for line in doc.splitlines() if REPO_BLOB in line and cls.examples_url() not in line]
    assert not stray, (
        f"{rule_id}: docstring hand-writes a repo link that `Rule.examples_url()` does not generate:\n  "
        + "\n  ".join(stray)
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
    """A module docstring naming the wrong code hands users a suppression that silently does nothing."""
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
    ledger = _ledger()
    reused = sorted(
        f"{cls.code} was {ledger[cls.code]!r}, now claimed by {rule_id!r}"
        for rule_id, cls in REGISTRY.items()
        if cls.code in ledger and ledger[cls.code] != rule_id
    )
    assert not reused, (
        "rule(s) claim a retired code:\n  "
        + "\n  ".join(reused)
        + f"\nA `# sarj-noqa: <code>` written for the old rule would silently suppress the new "
        f"one. Take the next unallocated code instead: SARJ{max(int(c[4:]) for c in ledger) + 1:03d}."
    )


def test_every_live_rule_is_in_the_code_ledger() -> None:
    """Allocation is recorded at the moment it happens, so the ledger cannot go stale."""
    ledger = _ledger()
    missing = sorted(f"{cls.code} ({rule_id})" for rule_id, cls in REGISTRY.items() if cls.code not in ledger)
    assert not missing, (
        f"rule(s) hold a code with no ledger entry: {missing}. Add "
        f'`"<code>": "<rule-id>"` to {_LEDGER_PATH.name} — it is what stops the code being '
        "recycled after the rule is deleted."
    )


def test_ledger_covers_every_deleted_rule_module() -> None:
    """The backstop: git history, not memory, decides which codes have been retired."""
    ledger = _ledger()
    unrecorded = sorted(
        f"{code} ({stem}) deleted from {_RULES_DIR}"
        for code, stem in _deleted_rule_modules().items()
        if code not in ledger
    )
    assert not unrecorded, (
        "git history has rule modules whose codes the ledger never recorded:\n  "
        + "\n  ".join(unrecorded)
        + f"\nAdd them to {_LEDGER_PATH.name}. A code that held a shipped rule must stay burned."
    )


def test_reports_whether_history_can_still_corroborate_the_ledger() -> None:
    """Make the subset gate's reach visible instead of leaving it inferred."""
    deleted = _deleted_rule_modules()
    recorded = len(_ledger())

    if not deleted and recorded:
        warnings.warn(
            f"history corroborates 0 of {recorded} ledger entries: `git log --diff-filter=D` "
            f"over {_RULES_DIR} is empty at {_git('rev-parse', '--short', 'HEAD').strip()}. "
            "The subset gate still catches a NEW deletion that forgets its entry; it cannot "
            "re-derive the existing ones. Expected after a history rewrite — investigate if "
            "the history was not rewritten.",
            stacklevel=1,
        )

    # Asserts the ledger is populated, not that history agrees with it: an empty ledger
    # alongside a truncated history would leave nothing checking anything.
    assert recorded > 0, f"{_LEDGER_PATH.name} is empty, so no code is burned and any code can be reused."

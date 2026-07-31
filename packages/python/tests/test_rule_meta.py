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
import subprocess
import sys

import pytest

from sarj_python_lint.rule_base import REPO_BLOB, Rule
from sarj_python_lint.rules import REGISTRY


# tests/ -> packages/python -> packages -> repo root. The derived link paths are
# repo-relative, so they only resolve from here.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Content lines allowed in a rule's module docstring: the `SARJ### — claim` summary, an
# optional short rationale, and the two derived link lines. The cap is what stops the
# 260-line docstring growing back one useful paragraph at a time.
#
# It is 4 because that is what the sentence above describes. It was 6 while the
# conversion was in flight, and 6 is two lines of slack PER RULE that nothing would ever
# have objected to — 71 rules x 2 = 142 lines of prose could have crept back in without
# a single test going red. Every rule in the registry sits at exactly 3, so the cap
# costs nothing today and forbids the drift it was written to forbid.
_MAX_DOCSTRING_LINES = 4

# `SARJ` + exactly three digits. Anything else breaks `# sarj-noqa: SARJ###` parsing and
# the ruff `external = ["SARJ"]` handoff.
_CODE_RE = re.compile(r"^SARJ\d{3}$")

# The same shape unanchored, for finding the first code mentioned in prose.
_CODE_IN_TEXT_RE = re.compile(r"SARJ\d{3}")

# Every SARJ code ever allocated or reserved, mapped to the rule that held it
# (`null` = reserved but never a rule module). THE LEDGER IS APPEND-ONLY AND
# DELETION NEVER TOUCHES IT: a rule that goes away just leaves its line behind,
# which is what makes the code retired.
#
# It replaces a hand-kept `_RETIRED_CODES` set that a deletion had to remember to
# update, and which therefore did not. `SARJ061 no-patching-system-under-test` was
# deleted in #183 and the set never learned about it, so a new rule could have
# claimed SARJ061 and inherited every `# sarj-noqa: SARJ061` a consumer had
# written. Nothing would have objected. The three tests below close that in two
# independent directions: `test_every_live_rule_is_in_the_code_ledger` fails the
# moment a rule is ADDED without a ledger line (so the ledger cannot go stale
# forwards), and `test_ledger_covers_every_deleted_rule_module` derives the
# deletions from git history and fails if the ledger is missing one (so it cannot
# have been wrong backwards, and a future deletion cannot quietly erase a line).
#
# THE CRITERION FOR RETIREMENT IS "could a consumer hold a suppression for this
# code", not "was it ever live in a published tag". Those are not the same
# question, and getting it wrong is silent in both directions. A scan of
# first-party consumers found a live `# sarj-noqa: SARJ005 — pre-existing, out of
# scope` for a code no `python-v*` tag ever shipped as a rule module. However that
# suppression came to be written, it exists, and a new rule claiming SARJ005 would
# inherit it. So the ledger also carries the codes that were only ever reserved,
# including `SARJ074`, which `prefer_non_nullable_collection`'s docstring told
# readers to write for three releases.
#
# Burning a code is nearly free: the space is `SARJ000`-`SARJ999`.
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
    """`{SARJ###: module stem}` for every rule module git has ever seen deleted.

    Derived, not declared. `--no-renames` is deliberate: a rule module renamed to a
    new name retires the old one exactly as a deletion does, and rename detection
    would hide that.
    """
    assert (
        _git("rev-parse", "--is-shallow-repository").strip() == "false"
    ), "this gate reads deleted rule modules out of git history; check out with fetch-depth: 0"

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
        found = _CODE_IN_TEXT_RE.search(_git("show", f"{commit}^:{line}"))
        if found is not None:
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
    """Every rule's docstring is a one-line claim and the two generated links."""
    cls = REGISTRY[rule_id]
    doc = _module_docstring(cls)
    lines = _content_lines(doc)

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
    """A retired code stays burned: an old suppression must never bind to a new rule.

    "Retired" is DERIVED, not listed: it is every ledger code whose recorded holder is
    not the rule holding it today. Deleting a rule retires its code with no edit
    anywhere, which is the whole point — the previous hand-kept set missed SARJ061.
    """
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
    """Allocation is recorded at the moment it happens, so the ledger cannot go stale.

    This is the half that makes the append-only ledger self-maintaining. A new rule
    fails here until its `SARJ###: <rule-id>` line exists, and from then on the line
    survives the rule itself.
    """
    ledger = _ledger()
    missing = sorted(f"{cls.code} ({rule_id})" for rule_id, cls in REGISTRY.items() if cls.code not in ledger)
    assert not missing, (
        f"rule(s) hold a code with no ledger entry: {missing}. Add "
        f'`"<code>": "<rule-id>"` to {_LEDGER_PATH.name} — it is what stops the code being '
        "recycled after the rule is deleted."
    )


def test_ledger_covers_every_deleted_rule_module() -> None:
    """The backstop: git history, not memory, decides which codes have been retired.

    `_RETIRED_CODES` was a list a human had to remember to edit on deletion, and #183
    deleted `no_patching_system_under_test` (SARJ061) without editing it. Deriving the
    deletions from history means the next one cannot be skipped, and it also means a
    ledger line cannot be quietly removed to free a code up again.
    """
    ledger = _ledger()
    unrecorded = sorted(
        f"{code} ({stem}) deleted from {_RULES_DIR}" for code, stem in _deleted_rule_modules().items() if code not in ledger
    )
    assert not unrecorded, (
        "git history has rule modules whose codes the ledger never recorded:\n  "
        + "\n  ".join(unrecorded)
        + f"\nAdd them to {_LEDGER_PATH.name}. A code that held a shipped rule must stay burned."
    )

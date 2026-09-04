from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import warnings

import pytest

from sarj_python_lint.rule_base import ExampleFile, ExampleOutcome, Rule, RuleExample
from sarj_python_lint.rules import REGISTRY


# tests/ -> packages/python -> packages -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# `SARJ` + exactly three digits.
_CODE_RE = re.compile(r"^SARJ\d{3}$")

# The same shape unanchored, for finding the first code mentioned in prose.
_CODE_IN_TEXT_RE = re.compile(r"SARJ\d{3}")

# Every SARJ code ever allocated or reserved. A list records an identity's
# ordered rename history; its final item is the live rule id.
_LEDGER_PATH = Path(__file__).parent / "code_ledger.json"

# The rules directory, relative to the repo root — the path git history is walked
# over to recover deleted rule modules.
_RULES_DIR = "packages/python/src/sarj_python_lint/rules"

_RENAMED_RULES = {
    "defect-xfail-requires-explicit-strict": (
        "SARJ046",
        ("xfail-requires-strict", "defect-xfail-requires-strict"),
    ),
    "fastapi-explicit-openapi-contract": ("SARJ094", ("fastapi-openapi-contract",)),
    "no-generic-single-export-module": ("SARJ022", ("single-public-export",)),
    "no-analytical-aggregation-in-postgres-store": ("SARJ020", ("no-aggregation-in-store-query",)),
    "no-copied-inherited-docstring": ("SARJ084", ("duplicated-override-docstring",)),
    "no-positional-psycopg-row-escape": ("SARJ414", ("require-validated-row-factory",)),
    "no-raw-source-text-test-oracle": ("SARJ402", ("source-coupled-test",)),
    "no-repeated-test-body": ("SARJ066", ("duplicate-test-body",)),
    "no-repeated-structured-string-literal": ("SARJ024", ("no-repeated-string-literal",)),
    "no-restated-closed-domain-description": ("SARJ423", ("no-redundant-literal-description",)),
    "no-string-concat-in-loop": ("SARJ002", ("inefficient-string-concat-in-loop",)),
    "opaque-parametrize-case-needs-id": ("SARJ042", ("parametrize-case-needs-id",)),
    "pytest-fixture-returns-bare-tuple": ("SARJ044", ("fixture-returns-bare-tuple",)),
    "repeated-kwarg-heavy-call-in-test": ("SARJ045", ("kwarg-heavy-construction-in-test",)),
    "store-get-delegates-to-bulk-read": ("SARJ421", ("get-delegates-to-get-many",)),
    "require-keyword-only-swap-prone-params": ("SARJ034", ("kwonly-same-type-params",)),
    "timestamp-order-requires-tiebreaker": ("SARJ407", ("created-at-order-requires-tiebreaker",)),
}


def _ledger() -> dict[str, tuple[str, ...] | None]:
    raw: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped boundary; narrowed below
        _LEDGER_PATH.read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict), (
        "code_ledger.json must map SARJ### to null, one rule id, or an ordered rule-id history"
    )
    entries: dict[str, tuple[str, ...] | None] = {}
    raw_items: list[tuple[object, object]] = list(raw.items())  # pyright: ignore[reportUnknownArgumentType]
    for code, value in raw_items:
        assert isinstance(code, str), f"ledger key {code!r} is not a string"
        assert _CODE_RE.match(code), f"ledger key {code!r} is not a SARJ### code"
        if value is None:
            entries[code] = None
            continue
        if isinstance(value, str):
            entries[code] = (value,)
            continue
        assert isinstance(value, list), f"ledger[{code}] rename history must be an array"
        assert value, f"ledger[{code}] rename history must not be empty"
        history_items: list[str] = []
        for index in range(len(value)):  # pyright: ignore[reportUnknownArgumentType]
            rule_id: object = value[index]  # pyright: ignore[reportUnknownVariableType]
            assert isinstance(rule_id, str), f"ledger[{code}] rename history must contain rule ids"
            assert rule_id, f"ledger[{code}] rename history must not contain empty ids"
            history_items.append(rule_id)
        history = tuple(history_items)
        assert len(history) == len(set(history)), f"ledger[{code}] rename history repeats an id"
        entries[code] = history
    return entries


def _git(*args: str) -> str:
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


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_every_rule_has_an_examples_module(rule_id: str) -> None:
    cls = REGISTRY[rule_id]
    examples = _REPO_ROOT / cls.examples_path()
    assert examples.is_file(), (
        f"{rule_id}: no examples module at {cls.examples_path()}. Every rule's examples live at "
        f"tests/rules/test_<module>.py, derived from the rule's module name — create it, or rename "
        f"the rule module to match its tests."
    )
    assert examples.stat().st_size > 0, f"{rule_id}: {cls.examples_path()} is empty"


def test_registry_keys_match_class_ids() -> None:
    for key, cls in REGISTRY.items():
        assert key == cls.id, f"REGISTRY[{key!r}].id = {cls.id!r} (mismatch)"


def test_renamed_rules_keep_codes_but_do_not_resolve_old_ids() -> None:
    ledger = _ledger()
    for new_id, (code, old_ids) in _RENAMED_RULES.items():
        assert new_id in REGISTRY
        assert set(old_ids).isdisjoint(REGISTRY)
        assert REGISTRY[new_id].code == code
        documentation = REGISTRY[new_id].documentation
        assert documentation is not None
        assert set(old_ids).issubset(documentation.aliases)
        assert ledger[code] == (*old_ids, new_id)


def test_every_rule_has_valid_source_owned_documentation() -> None:
    missing = sorted(rule_id for rule_id, cls in REGISTRY.items() if cls.documentation is None)
    assert not missing, f"rules missing source-owned documentation: {', '.join(missing)}"

    documented = {rule_id: cls.native_spec() for rule_id, cls in REGISTRY.items()}

    for rule_id, spec in documented.items():
        assert spec is not None
        assert spec.key == f"python:{rule_id}"
        assert spec.rule_id == rule_id
        assert spec.code == REGISTRY[rule_id].code
        assert spec.summary == REGISTRY[rule_id].description
        assert {example.outcome for example in spec.public_examples} == {"match", "no-match"}


def test_rule_examples_are_private_by_default_path_aware_and_multi_file() -> None:
    example = RuleExample(
        example_id="cross-module-case",
        title="Cross-module fixture",
        outcome=ExampleOutcome.NO_MATCH,
        files=(
            ExampleFile.python("app/service.py", "from .types import Item\n"),
            ExampleFile.python("app/types.py", "class Item: ...\n"),
        ),
        focus_path=PurePosixPath("app/service.py"),
        expected_count=0,
    )

    assert example.public is False
    assert example.focus_file.path == PurePosixPath("app/service.py")
    assert len(example.files) == 2


@pytest.mark.parametrize("path", ["/private/source.py", "../outside.py", "app/../../outside.py"])
def test_rule_example_files_reject_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError, match="safe relative paths"):
        ExampleFile.python(path, "value = 1\n")


def test_no_two_rules_share_a_code() -> None:
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
    ledger = _ledger()
    reused: list[str] = []
    for rule_id, cls in REGISTRY.items():
        history = ledger.get(cls.code)
        if history is not None and history[-1] != rule_id:
            reused.append(f"{cls.code} last belonged to {history!r}, now claimed by {rule_id!r}")
    reused.sort()
    assert not reused, (
        "rule(s) claim a retired code:\n  "
        + "\n  ".join(reused)
        + f"\nA `# sarj-noqa: <code>` written for the old rule would silently suppress the new "
        f"one. Take the next unallocated code instead: SARJ{max(int(c[4:]) for c in ledger) + 1:03d}."
    )


def test_every_live_rule_is_in_the_code_ledger() -> None:
    ledger = _ledger()
    missing = sorted(f"{cls.code} ({rule_id})" for rule_id, cls in REGISTRY.items() if cls.code not in ledger)
    assert not missing, (
        f"rule(s) hold a code with no ledger entry: {missing}. Add "
        f'`"<code>": "<rule-id>"` to {_LEDGER_PATH.name} — it is what stops the code being '
        "recycled after the rule is deleted."
    )


def test_ledger_covers_every_deleted_rule_module() -> None:
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

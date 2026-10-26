from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    from sarj_rule_contracts.contracts import NativeRuleSpec, RuleExample


@dataclass(frozen=True, slots=True)
class ExampleFinding:
    path: Path
    line: int
    col: int
    code: str
    message: str = ""


type ExampleAnalyzer = Callable[[Path, Path], Sequence[ExampleFinding]]
type ExampleFixer = Callable[[Path, Path, str], str]


def verify_examples(
    examples: Sequence[RuleExample],
    analyze: ExampleAnalyzer,
    *,
    expected_code: str | None = None,
    fix: ExampleFixer | None = None,
) -> int:
    public_outcomes = {example.outcome.value for example in examples if example.public}
    if public_outcomes != {"match", "no-match"}:
        msg = "rule requires public match and no-match examples"
        raise ValueError(msg)
    for example in examples:
        _verify_supported_setup(example, fix_available=fix is not None)
        with TemporaryDirectory(prefix="sarj-rule-example-") as directory:
            root = Path(directory).resolve()
            (root / ".git").mkdir()
            for file in example.files:
                path = root / file.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(file.source, encoding="utf-8", newline="")
            focus = root / example.focus_path
            findings = [finding for finding in analyze(root, focus) if finding.path.resolve() == focus.resolve()]
            _verify_findings(example, findings, expected_code)
            if example.fixed_files and fix is not None:
                _verify_fixes(example, root, analyze, fix)
    return len(examples)


def _verify_supported_setup(example: RuleExample, *, fix_available: bool) -> None:
    if example.fixed_files and not fix_available:
        msg = f"{example.example_id}: this analyzer has no fix adapter"
        raise ValueError(msg)
    if example.rule_options_json is not None:
        msg = f"{example.example_id}: this analyzer has no rule options adapter"
        raise ValueError(msg)
    if example.installed_dependencies:
        msg = f"{example.example_id}: this analyzer has no installed dependency adapter"
        raise ValueError(msg)


def _verify_fixes(example: RuleExample, root: Path, analyze: ExampleAnalyzer, fix: ExampleFixer) -> None:
    expected = {file.path: file.source for file in example.files}
    if any(file.path not in expected for file in example.fixed_files):
        msg = f"{example.example_id}: source fix adapter cannot create files"
        raise ValueError(msg)
    expected.update({file.path: file.source for file in example.fixed_files})
    for file in example.files:
        path = root / file.path
        actual = fix(root, path, file.source)
        if actual != expected[file.path]:
            msg = f"{example.example_id}: unexpected fixed source for {file.path}"
            raise ValueError(msg)
    for name, source in expected.items():
        (root / name).write_text(source, encoding="utf-8", newline="")
    for name, source in expected.items():
        if fix(root, root / name, source) != source:
            msg = f"{example.example_id}: fix does not converge for {name}"
            raise ValueError(msg)
    focus = root / example.focus_path
    if any(finding.path.resolve() == focus.resolve() for finding in analyze(root, focus)):
        msg = f"{example.example_id}: fixed source still reports the selected rule"
        raise ValueError(msg)


def _verify_findings(example: RuleExample, findings: Sequence[ExampleFinding], expected_code: str | None) -> None:
    lines = example.focus_file.source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # UTF-8 byte width bounds the native byte, codepoint and UTF-16 column conventions.
    if any(
        not 1 <= finding.line <= len(lines)
        or not 1 <= finding.col <= len(lines[finding.line - 1].encode("utf-8")) + 1
        or not finding.code.strip()
        for finding in findings
    ):
        msg = f"{example.example_id}: invalid diagnostic location or code"
        raise ValueError(msg)
    if expected_code is not None and any(finding.code != expected_code for finding in findings):
        msg = f"{example.example_id}: unexpected diagnostic code; expected {expected_code}"
        raise ValueError(msg)
    locations = {(finding.line, finding.col, finding.code) for finding in findings}
    if len(locations) != len(findings):
        msg = f"{example.example_id}: duplicate diagnostic locations"
        raise ValueError(msg)
    if len(findings) != example.expected_count:
        msg = f"{example.example_id}: expected {example.expected_count} diagnostics, found {len(findings)}"
        raise ValueError(msg)


class NativeRule(Protocol):
    id: str

    @classmethod
    def native_spec(cls) -> NativeRuleSpec | None: ...


class NativeFinding(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def line(self) -> int: ...

    @property
    def col(self) -> int: ...

    @property
    def code(self) -> str: ...

    @property
    def message(self) -> str: ...


type NativeAnalyzer = Callable[[list[str], list[Path]], Sequence[NativeFinding]]


@runtime_checkable
class _NativeFixer(Protocol):
    def fix_source(self, path: Path, source: str, *, rule_ids: Sequence[str] | None = None) -> str: ...


def verify_native_rule(rule: type[NativeRule], analyze: NativeAnalyzer) -> int:
    spec = rule.native_spec()
    if spec is None:
        msg = f"{rule.id}: missing source-owned documentation"
        raise ValueError(msg)

    def run(_root: Path, focus: Path) -> list[ExampleFinding]:
        return [ExampleFinding(d.path, d.line, d.col, d.code, d.message) for d in analyze([rule.id], [focus])]

    fix: ExampleFixer | None = None
    if any(example.fixed_files for example in spec.examples):
        module = import_module(f"{rule.__module__.partition('.')[0]}.autofix")
        if not isinstance(module, _NativeFixer):
            msg = f"{rule.id}: missing native fix adapter"
            raise TypeError(msg)

        def fix_source(_root: Path, path: Path, source: str) -> str:
            return module.fix_source(path, source, rule_ids=(rule.id,))

        fix = fix_source
    return verify_examples(spec.examples, run, expected_code=spec.code, fix=fix)

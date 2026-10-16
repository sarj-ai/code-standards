from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Protocol


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


def verify_examples(
    examples: Sequence[RuleExample], analyze: ExampleAnalyzer, *, expected_code: str | None = None
) -> int:
    public_outcomes = {example.outcome.value for example in examples if example.public}
    if public_outcomes != {"match", "no-match"}:
        msg = "rule requires public match and no-match examples"
        raise ValueError(msg)
    for example in examples:
        _verify_supported_setup(example)
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
    return len(examples)


def _verify_supported_setup(example: RuleExample) -> None:
    if example.fixed_files:
        msg = f"{example.example_id}: this analyzer has no fix adapter"
        raise ValueError(msg)
    if example.rule_options_json is not None:
        msg = f"{example.example_id}: this analyzer has no rule options adapter"
        raise ValueError(msg)
    if example.installed_dependencies:
        msg = f"{example.example_id}: this analyzer has no installed dependency adapter"
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


def verify_native_rule(rule: type[NativeRule], analyze: NativeAnalyzer) -> int:
    spec = rule.native_spec()
    if spec is None:
        msg = f"{rule.id}: missing source-owned documentation"
        raise ValueError(msg)

    def run(_root: Path, focus: Path) -> list[ExampleFinding]:
        return [ExampleFinding(d.path, d.line, d.col, d.code, d.message) for d in analyze([rule.id], [focus])]

    return verify_examples(spec.examples, run, expected_code=spec.code)

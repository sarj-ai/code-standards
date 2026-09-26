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


def verify_examples(examples: Sequence[RuleExample], analyze: ExampleAnalyzer) -> int:
    public_outcomes = {example.outcome.value for example in examples if example.public}
    if public_outcomes != {"match", "no-match"}:
        msg = "rule requires public match and no-match examples"
        raise ValueError(msg)
    for example in examples:
        if example.fixed_files:
            msg = f"{example.example_id}: this analyzer has no fix adapter"
            raise ValueError(msg)
        with TemporaryDirectory(prefix="sarj-rule-example-") as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            for file in example.files:
                path = root / file.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(file.source, encoding="utf-8")
            focus = root / example.focus_path
            findings = [finding for finding in analyze(root, focus) if finding.path.resolve() == focus.resolve()]
            locations = {(finding.line, finding.col, finding.code, finding.message) for finding in findings}
            if len(locations) != len(findings):
                msg = f"{example.example_id}: duplicate diagnostic locations"
                raise ValueError(msg)
            if len(findings) != example.expected_count:
                msg = f"{example.example_id}: expected {example.expected_count} diagnostics, found {len(findings)}"
                raise ValueError(msg)
    return len(examples)


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

    return verify_examples(spec.examples, run)

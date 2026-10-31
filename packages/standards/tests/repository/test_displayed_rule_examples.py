from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path, PurePosixPath
import subprocess
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, RootModel
import pytest
from sarj_rule_contracts import ExampleFile, ExpectedOutcome, RuleExample
from sarj_rule_contracts.examples import ExampleFinding, verify_examples

from sarj_standards.libs.repository.rule_examples import selected
from sarj_standards.libs.rules import RuleSelector


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sarj_rule_contracts.examples import ExampleAnalyzer, ExampleFixer


class _DisplayFile(BaseModel):
    path: str
    source: str


class _DisplayFiles(RootModel[tuple[_DisplayFile, ...]]):
    pass


class _DisplayExample(BaseModel):
    id: str
    files: tuple[_DisplayFile, ...]
    fixed_files: tuple[_DisplayFile, ...] = Field(alias="fixedFiles")


class _DisplayRule(BaseModel):
    examples: tuple[_DisplayExample, ...]


class _DisplayProjection(BaseModel):
    rules: dict[str, _DisplayRule]


@dataclass(frozen=True, slots=True)
class _FixGraphs:
    actual: dict[PurePosixPath, str]
    expected: dict[PurePosixPath, str]


_ROOT = Path(__file__).resolve().parents[4]
_DISPLAY = _DisplayProjection.model_validate_json(
    (_ROOT / "apps/docs/src/generated/formatted-code.v1.json").read_text(encoding="utf-8")
)


def _format_display_sources(files: tuple[_DisplayFile, ...]) -> tuple[_DisplayFile, ...]:
    try:
        result = subprocess.run(
            ["node", str(_ROOT / "apps/docs/scripts/format-code-examples.ts"), "--format-json"],
            input=json.dumps([file.model_dump() for file in files]),
            cwd=_ROOT,
            text=True,
            capture_output=True,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as error:
        stderr = dict[str, object](vars(error)).get("stderr")
        details = stderr.strip() if isinstance(stderr, str) else ""
        msg = f"Display formatter exited {error.returncode}: {details[-4000:]}"
        raise AssertionError(msg) from error
    formatted = _DisplayFiles.model_validate_json(result.stdout).root
    assert tuple(file.path for file in formatted) == tuple(file.path for file in files)
    return formatted


def _write_graph(root: Path, sources: dict[PurePosixPath, str]) -> None:
    for name, source in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8", newline="")


def _check_graph_paths(root: Path, sources: dict[PurePosixPath, str]) -> None:
    if {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()} != {
        str(name) for name in sources
    }:
        msg = "display source fix adapter cannot create or remove files"
        raise ValueError(msg)


def _check_fixed_graph(
    example: RuleExample, root: Path, sources: dict[PurePosixPath, str], analyze: ExampleAnalyzer, fix: ExampleFixer
) -> None:
    _write_graph(root, sources)
    for name, source in sources.items():
        if fix(root, root / name, source) != source:
            msg = f"{example.example_id}: raw fix does not converge for {name}"
            raise ValueError(msg)
    _check_graph_paths(root, sources)
    focus = root / example.focus_path
    if any(finding.path.resolve() == focus.resolve() for finding in analyze(root, focus)):
        msg = f"{example.example_id}: fixed source still reports the selected rule"
        raise ValueError(msg)


def _displayed_fix_graphs(
    example: RuleExample,
    root: Path,
    fix: ExampleFixer,
    format_sources: Callable[[tuple[_DisplayFile, ...]], tuple[_DisplayFile, ...]],
) -> _FixGraphs:
    original = {file.path: file.source for file in example.files}
    declared = {file.path: file.source for file in example.fixed_files}
    if not declared.keys() <= original.keys():
        msg = f"{example.example_id}: source fix adapter cannot create files"
        raise ValueError(msg)
    _write_graph(root, original)
    actual = {name: fix(root, root / name, source) for name, source in original.items()}
    _check_graph_paths(root, original)
    for name in original.keys() - declared.keys():
        if actual[name] != original[name]:
            msg = f"{example.example_id}: unexpected changed companion {name}"
            raise ValueError(msg)
    differing = tuple(
        _DisplayFile(path=str(name), source=actual[name]) for name in declared if actual[name] != declared[name]
    )
    for formatted in format_sources(differing) if differing else ():
        if formatted.source != declared[PurePosixPath(formatted.path)]:
            msg = f"{example.example_id}: unexpected displayed fixed source for {formatted.path}"
            raise ValueError(msg)
    return _FixGraphs(actual=actual, expected=original | declared)


def _verify_displayed_fixes(
    example: RuleExample,
    analyze: ExampleAnalyzer,
    fix: ExampleFixer,
    format_sources: Callable[[tuple[_DisplayFile, ...]], tuple[_DisplayFile, ...]] = _format_display_sources,
) -> None:
    with TemporaryDirectory(prefix="sarj-displayed-fix-") as directory:
        root = Path(directory).resolve()
        (root / ".git").mkdir()
        graphs = _displayed_fix_graphs(example, root, fix, format_sources)
        # Canonical comparison must never replace the raw graph being verified.
        _check_fixed_graph(example, root, graphs.actual, analyze, fix)
        _check_fixed_graph(example, root, graphs.expected, analyze, fix)


def _verify_displayed_examples(
    examples: Sequence[RuleExample], analyze: ExampleAnalyzer, *, expected_code: str | None, fix: ExampleFixer | None
) -> int:
    if any(example.fixed_files for example in examples) and fix is None:
        msg = "displayed fixed files require a native fix adapter"
        raise ValueError(msg)
    # Reuse every strict native input/finding check; the separate phase below
    # verifies all original fixed_files against both raw and displayed graphs.
    inputs = tuple(replace(example, fixed_files=()) for example in examples)
    count = verify_examples(inputs, analyze, expected_code=expected_code)
    if fix is not None:
        for example in examples:
            if example.fixed_files:
                _verify_displayed_fixes(example, analyze, fix)
    return count


def _compile_displayed_python(example: _DisplayExample) -> None:
    # Native analyzers may deliberately skip malformed sources as unprovable.
    for file in (*example.files, *example.fixed_files):
        if PurePosixPath(file.path).suffix == ".py":
            compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
                file.source, file.path, "exec", dont_inherit=True
            )


def _canonical_comparison(files: tuple[_DisplayFile, ...]) -> tuple[_DisplayFile, ...]:
    return tuple(file.model_copy(update={"source": f"{file.source.strip()}\n"}) for file in files)


def _guard_example(*, companion: bool = False, fixed: str = "good\n") -> RuleExample:
    files = (ExampleFile(PurePosixPath("focus.txt"), "bad\n"),)
    if companion:
        files += (ExampleFile(PurePosixPath("companion.txt"), "kept\n"),)
    return RuleExample(
        example_id="display-guard",
        outcome=ExpectedOutcome.MATCH,
        files=files,
        focus_path=PurePosixPath("focus.txt"),
        expected_count=1,
        title="Display comparison guard",
        fixed_files=(ExampleFile(PurePosixPath("focus.txt"), fixed),),
    )


def _no_findings(_root: Path, _focus: Path) -> tuple[ExampleFinding, ...]:
    return ()


def test_displayed_fix_comparison_preserves_raw_whitespace_convergence() -> None:
    def oscillate(_root: Path, _path: Path, source: str) -> str:
        return "\ngood\n" if source == "bad\n" else f"\n{source}"

    with pytest.raises(ValueError, match="raw fix does not converge"):
        _verify_displayed_fixes(_guard_example(), _no_findings, oscillate, _canonical_comparison)


def test_displayed_fix_comparison_rejects_raw_residual_diagnostics() -> None:
    def fix(_root: Path, _path: Path, source: str) -> str:
        return "\ngood\n" if source == "bad\n" else source

    def analyze(_root: Path, focus: Path) -> tuple[ExampleFinding, ...]:
        return (ExampleFinding(focus, 1, 1, "TEST001"),)

    with pytest.raises(ValueError, match="still reports the selected rule"):
        _verify_displayed_fixes(_guard_example(), analyze, fix, _canonical_comparison)


def test_displayed_fix_comparison_keeps_companions_byte_exact() -> None:
    def fix(_root: Path, path: Path, source: str) -> str:
        return "\nkept\n" if path.name == "companion.txt" else source.replace("bad", "good")

    with pytest.raises(ValueError, match="unexpected changed companion"):
        _verify_displayed_fixes(_guard_example(companion=True), _no_findings, fix, _canonical_comparison)


def test_displayed_fix_comparison_preserves_zero_byte_native_output() -> None:
    observed: list[bytes] = []

    def fix(_root: Path, path: Path, source: str) -> str:
        if not source:
            assert path.read_bytes() == b""
            observed.append(b"")
        return "" if source == "bad\n" else source

    def analyze(_root: Path, focus: Path) -> tuple[ExampleFinding, ...]:
        observed.append(focus.read_bytes())
        return ()

    _verify_displayed_fixes(_guard_example(fixed="\n"), analyze, fix, _canonical_comparison)
    assert observed == [b"", b"", b"\n"]


def test_displayed_fix_comparison_checks_the_expected_display_graph_too() -> None:
    def fix(_root: Path, _path: Path, source: str) -> str:
        return "\ngood\n" if source in {"bad\n", "good\n"} else source

    with pytest.raises(ValueError, match="raw fix does not converge"):
        _verify_displayed_fixes(_guard_example(), _no_findings, fix, _canonical_comparison)


def test_displayed_fix_comparison_rejects_file_creation() -> None:
    def fix(root: Path, _path: Path, source: str) -> str:
        (root / "created.txt").write_text("created\n", encoding="utf-8")
        return source.replace("bad", "good")

    with pytest.raises(ValueError, match="cannot create or remove files"):
        _verify_displayed_fixes(_guard_example(), _no_findings, fix, _canonical_comparison)


@pytest.mark.parametrize("collection", ["files", "fixed_files"])
@pytest.mark.parametrize("path", ["app/focus.py", "app/companion.py"])
def test_displayed_python_syntax_rejects_malformed_focus_companions_and_fixes(collection: str, path: str) -> None:
    example = _DisplayExample(
        id="no-match", files=(_DisplayFile(path="app/focus.py", source="value = 1\n"),), fixedFiles=()
    )
    malformed = example.model_copy(update={collection: (_DisplayFile(path=path, source="def broken(\n"),)})

    with pytest.raises(SyntaxError):
        _compile_displayed_python(malformed)


@pytest.mark.parametrize("key", tuple(key for key in _DISPLAY.rules if not key.startswith("eslint:")))
def test_displayed_examples_preserve_the_live_rule_outcome(key: str) -> None:
    rule = selected(RuleSelector.parse(key))
    displayed = _DISPLAY.rules[key].examples
    by_id = {example.id: example for example in displayed}
    public = tuple(example for example in rule.spec.examples if example.public)
    assert len(by_id) == len(displayed)
    assert set(by_id) == {example.example_id for example in public}
    for example in displayed:
        _compile_displayed_python(example)
    examples = tuple(
        replace(
            example,
            files=tuple(ExampleFile(PurePosixPath(file.path), file.source) for file in by_id[example.example_id].files),
            fixed_files=tuple(
                ExampleFile(PurePosixPath(file.path), file.source) for file in by_id[example.example_id].fixed_files
            ),
        )
        for example in public
    )

    assert _verify_displayed_examples(examples, rule.analyze, expected_code=rule.spec.code, fix=rule.fix) == len(public)

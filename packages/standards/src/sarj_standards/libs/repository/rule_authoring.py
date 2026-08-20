from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_standards.libs.adoption import transaction
from sarj_standards.libs.rules import RuleEngine, RuleSelector


if TYPE_CHECKING:
    from collections.abc import Iterable


_CODE = re.compile(r"SARJ(?P<number>[0-9]{3})")
_BANDS = MappingProxyType(
    {RuleEngine.PYTHON: range(400, 500), RuleEngine.SQL: range(100, 200), RuleEngine.IAC: range(200, 300)}
)


@dataclass(frozen=True, slots=True)
class AuthoringPlan:
    selector: RuleSelector
    code: str | None
    files: tuple[tuple[Path, str], ...]

    def render(self, root: Path) -> str:
        lines = [f"rule: {self.selector}", f"code: {self.code or 'engine-native'}"]
        lines.extend(f"create: {path.relative_to(root)}" for path, _ in self.files)
        registry = _registry_path(root, self.selector.engine).relative_to(root)
        lines.extend(
            (
                f"next: implement the TODOs and register the rule in {registry}",
                f"then: run the focused test and `code-standards maintain rules verify {self.selector}`",
                f"then: run `code-standards maintain rules evaluate --rule {self.selector} --scope corpus`",
                f"finally: run `code-standards maintain rules prepare {self.selector}`",
            )
        )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: int
    message: str


def verify(root: Path, selector: RuleSelector) -> VerificationResult:
    from sarj_standards.libs.repository import (  # ruff: ignore[import-outside-top-level] -- expensive engines load on demand
        rule_catalog_artifact,
    )

    repository = root.resolve()
    catalog = rule_catalog_artifact.build(repository)
    documented = next((item for item in catalog.rules if item.spec.key == str(selector)), None)
    if documented is None:
        msg = f"unknown live rule selector: {selector}; register the implementation, then rerun verify"
        return VerificationResult(2, msg)
    examples = tuple(example for example in documented.spec.examples if example.public)
    outcomes = {example.outcome.value for example in examples}
    if outcomes != {"match", "no-match"}:
        return VerificationResult(1, f"incomplete: {selector} needs public match and no-match examples")
    paths = (repository / documented.source, repository / documented.test)
    for path in paths:
        if not path.is_file():
            return VerificationResult(1, f"incomplete: expected authored file {path.relative_to(repository)}")
        if "TODO" in path.read_text(encoding="utf-8"):
            return VerificationResult(1, f"incomplete: resolve TODOs in {path.relative_to(repository)}")
    return VerificationResult(
        0,
        f"ok: {selector} is registered with complete metadata and public accept/reject examples",
    )


def plan_new(root: Path, selector: RuleSelector, *, category: str, summary: str) -> AuthoringPlan:
    if selector.engine is RuleEngine.TEXT:
        msg = "text rules use the shared textlint catalog and are not scaffolded yet"
        raise ValueError(msg)
    code = _next_code(root, selector.engine)
    slug = str(selector.rule_id)
    snake = slug.replace("-", "_")
    class_name = "".join(part.capitalize() for part in slug.split("-"))
    if selector.engine is RuleEngine.ESLINT:
        implementation = root / "packages/typescript/src/rules" / f"{slug}.ts"
        test = root / "packages/typescript/tests/rules" / f"{slug}.test.ts"
        files = (
            (implementation, _eslint_implementation(slug, class_name, category, summary)),
            (test, _eslint_test(slug, class_name)),
        )
    else:
        package = selector.engine.value
        module = f"sarj_{package}_lint"
        implementation = root / f"packages/{package}/src/{module}/rules" / f"{snake}.py"
        test = root / f"packages/{package}/tests/rules" / f"test_{snake}.py"
        files = (
            (
                implementation,
                _python_implementation(module, class_name, slug, code or "", category=category, summary=summary),
            ),
            (test, _python_test(module, class_name, snake)),
        )
    conflicts = [path for path, _ in files if path.exists()]
    if conflicts:
        msg = "rule scaffold target already exists: " + ", ".join(str(path.relative_to(root)) for path in conflicts)
        raise FileExistsError(msg)
    return AuthoringPlan(selector, code, files)


def apply(plan: AuthoringPlan, root: Path) -> None:
    mutation = transaction.FileTransaction.capture(root, tuple(path for path, _ in plan.files))
    try:
        for path, contents in plan.files:
            transaction.assert_expected(root, path, None)
            transaction.atomic_write_text(root, path, contents)
            mutation.mark_written(path)
    except BaseException:
        _ = mutation.rollback()
        raise


def _registry_path(root: Path, engine: RuleEngine) -> Path:
    if engine is RuleEngine.ESLINT:
        return root / "packages/typescript/src/index.ts"
    package = engine.value
    return root / f"packages/{package}/src/sarj_{package}_lint/rules/_registry.py"


def _next_code(root: Path, engine: RuleEngine) -> str | None:
    band = _BANDS.get(engine)
    if band is None:
        return None
    used = {number for number in _code_numbers(_source_texts(root)) if number in band}
    available = max(used, default=band.start - 1) + 1
    if available not in band:
        msg = f"no unreserved SARJ codes remain in the {engine.value} band"
        raise ValueError(msg)
    return f"SARJ{available:03d}"


def _source_texts(root: Path) -> Iterable[str]:
    for base in (root / "packages", root / "tests"):
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and path.suffix in {".py", ".ts", ".json"}:
                    try:
                        yield path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        continue


def _code_numbers(texts: Iterable[str]) -> Iterable[int]:
    for text in texts:
        for match in _CODE.finditer(text):
            yield int(match.group("number"))


def _python_implementation(module: str, class_name: str, slug: str, code: str, *, category: str, summary: str) -> str:
    example_factory = module.removeprefix("sarj_").removesuffix("_lint")
    return f'''"""{code} — {summary}"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from {module}.rule_base import AutofixPolicy, Diagnostic, ExampleFile, ExampleOutcome, Rule, RuleCategory, RuleDocumentation, RuleExample

if TYPE_CHECKING:
    from pathlib import Path


@final
class {class_name}(Rule):
    id = "{slug}"
    code = "{code}"
    documentation = RuleDocumentation(
        summary={summary!r},
        rationale="TODO: explain the concrete failure mode.",
        remediation="TODO: give the smallest safe remediation.",
        category=RuleCategory.{category.upper()},
        autofix=AutofixPolicy.NONE,
        limitations=("TODO: document the applicability boundary.",),
        examples=(
            RuleExample(example_id="rejects-antipattern", title="Reject the anti-pattern", outcome=ExampleOutcome.MATCH, files=(ExampleFile.{example_factory}("case.{example_factory}", "TODO invalid example\\n"),), focus_path=PurePosixPath("case.{example_factory}"), expected_count=1, public=True),
            RuleExample(example_id="accepts-alternative", title="Accept the preferred alternative", outcome=ExampleOutcome.NO_MATCH, files=(ExampleFile.{example_factory}("case.{example_factory}", "TODO valid example\\n"),), focus_path=PurePosixPath("case.{example_factory}"), expected_count=0, public=True),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        raise NotImplementedError("TODO: implement conservative detection")
'''


def _python_test(module: str, class_name: str, snake: str) -> str:
    return f"""from {module}.rules.{snake} import {class_name}


def test_documented_examples_are_present() -> None:
    outcomes = {{example.outcome.value for example in {class_name}.documentation.examples}}
    assert outcomes == {{"match", "no-match"}}
"""


def _eslint_implementation(slug: str, name: str, category: str, summary: str) -> str:
    message = name[0].lower() + name[1:]
    return f"""import {{ createRule, type RuleDocumentation }} from "./_docs.js";

type MessageIds = "{message}";
type Options = readonly [];

export const {message}Documentation = {{
  summary: {summary!r},
  rationale: "TODO: explain the concrete failure mode.",
  remediation: "TODO: give the smallest safe remediation.",
  category: "{category}",
  limitations: ["TODO: document the applicability boundary."],
  examples: [
    {{ id: "accepts-alternative", title: "Accept the preferred alternative", outcome: "no-match", files: [{{ path: "case.ts", source: "// TODO valid example" }}], focusPath: "case.ts", expectedCount: 0, public: true }},
    {{ id: "rejects-antipattern", title: "Reject the anti-pattern", outcome: "match", files: [{{ path: "case.ts", source: "// TODO invalid example" }}], focusPath: "case.ts", expectedCount: 1, public: true }},
  ],
}} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({{
  name: "{slug}",
  meta: {{ type: "problem", docs: {{ description: {message}Documentation.summary }}, schema: [], messages: {{ {message}: {summary!r} }} }},
  defaultOptions: [],
  create() {{ throw new Error("TODO: implement conservative detection"); }},
}});
"""


def _eslint_test(slug: str, name: str) -> str:
    message = name[0].lower() + name[1:]
    return f"""import {{ describe, expect, it }} from "vitest";
import {{ {message}Documentation }} from "../../src/rules/{slug}.js";

describe("{slug}", () => {{
  it("declares public accept and reject examples", () => {{
    expect({message}Documentation.examples.map((item) => item.outcome).sort()).toEqual(["match", "no-match"]);
  }});
}});
"""

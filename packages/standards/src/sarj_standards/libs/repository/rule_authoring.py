from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_rule_contracts import RuleDocumentation

from sarj_standards.libs.adoption import transaction
from sarj_standards.libs.adoption.manifest import as_table, list_field
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.repository import (
    rule_catalog_artifact,
    rule_checkout,
    rule_examples,
    rule_layout,
    rule_registration,
)
from sarj_standards.libs.rules import DefaultLevel, RuleCategory, RuleEngine, RuleSelector, RuleSpec


if TYPE_CHECKING:
    from collections.abc import Iterable


_CODE = re.compile(r"SARJ(?P<number>[0-9]{3})")
_BANDS = MappingProxyType(
    {
        RuleEngine.PYTHON: range(400, 500),
        RuleEngine.SQL: range(100, 200),
        RuleEngine.IAC: range(200, 300),
        RuleEngine.TEXT: range(300, 400),
    }
)


@dataclass(frozen=True, slots=True)
class AuthoringPlan:
    selector: RuleSelector
    code: str | None
    files: tuple[tuple[Path, str], ...]
    edits: tuple[rule_registration.FileEdit, ...] = ()

    def render(self, root: Path) -> str:
        lines = [f"rule: {self.selector}", f"code: {self.code or 'engine-native'}"]
        lines.extend(f"create: {path.relative_to(root)}" for path, _ in self.files)
        lines.extend(f"update: {edit.path.relative_to(root)}" for edit in self.edits)
        lines.extend(
            (
                "next: implement the detector and its examples; this plan includes registration and warning metadata",
                f"then: run `{rule_checkout.command(root, 'maintain', 'rules', 'prepare', str(self.selector))}` (examples, focused test and derived artifacts)",
                f"then: run `{rule_checkout.command(root, 'maintain', 'rules', 'evaluate', '--rule', str(self.selector), '--scope', 'corpus')}`",
                "finally: run `make verify`",
            )
        )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: int
    message: str
    typescript: tuple[RuleSpec, ...] | None = None


def verify(root: Path, selector: RuleSelector, *, run_tests: bool = False) -> VerificationResult:
    rule_checkout.ensure_current(root.resolve(), ("maintain", "rules", "verify", str(selector)), engine=selector.engine)
    try:
        count = rule_examples.verify(root.resolve(), selector)
        if run_tests:
            rule_examples.run_focused_tests(root.resolve(), selector)
    except (ValueError, NotImplementedError, AssertionError) as exc:
        return VerificationResult(1, f"incomplete: {selector}: {exc}")
    typescript = (
        rule_catalog_artifact.typescript_specs(root.resolve(), already_built=True)
        if selector.engine is RuleEngine.ESLINT
        else None
    )
    detail = " and focused tests" if run_tests else ""
    return VerificationResult(0, f"ok: {selector} passed {count} executable examples{detail}", typescript)


def plan_new(root: Path, selector: RuleSelector, *, category: str, summary: str) -> AuthoringPlan:
    layout = rule_layout.layout(root, selector.engine)
    documentation = RuleDocumentation(
        summary=summary,
        rationale="TODO: explain the concrete failure mode.",
        remediation="TODO: give the smallest safe remediation.",
        category=RuleCategory(category),
        default_level=DefaultLevel.WARNING,
        limitations=("TODO: document the applicability boundary.",),
    )
    rule_checkout.ensure_current(
        root.resolve(),
        ("maintain", "rules", "new", str(selector), "--category", category, "--summary", summary),
        engine=selector.engine,
    )
    live = rule_registration.live_codes(root, selector.engine)
    code = _next_code(root, selector.engine, live)
    slug = str(selector.rule_id)
    snake = rule_layout.module_name(selector.rule_id)
    class_name = rule_layout.class_name(selector.rule_id)
    implementation = layout.implementation(selector.rule_id)
    test = layout.test(selector.rule_id)
    if selector.engine is RuleEngine.ESLINT:
        files = (
            (implementation, _eslint_implementation(slug, class_name, documentation)),
            (test, _eslint_test(slug)),
        )
    elif selector.engine is RuleEngine.TEXT:
        files = (
            (implementation, _text_implementation(class_name, slug, code or "", documentation)),
            (test, _text_test(slug)),
        )
    else:
        module = layout.native_module.removesuffix(".rules")
        files = (
            (
                implementation,
                _python_implementation(module, class_name, slug, code or "", documentation),
            ),
            (test, _python_test(module, class_name, snake)),
        )
    conflicts = [path for path, _ in files if path.exists()]
    if conflicts:
        msg = "rule scaffold target already exists: " + ", ".join(str(path.relative_to(root)) for path in conflicts)
        raise FileExistsError(msg)
    return AuthoringPlan(selector, code, files, rule_registration.plan(root, selector, code, reserved=live))


def apply(plan: AuthoringPlan, root: Path) -> None:
    edits = (*tuple(rule_registration.FileEdit(path, None, source) for path, source in plan.files), *plan.edits)
    mutation = transaction.FileTransaction.capture(root, tuple(edit.path for edit in edits), explicit_only=True)
    try:
        for edit in edits:
            transaction.assert_expected(root, edit.path, edit.before)
            mutation.write_text(edit.path, edit.after)
    except BaseException:
        rollback = mutation.rollback()
        if not rollback.ok:
            raise RuntimeError(rollback.render() or "rule scaffolding rollback was incomplete") from None
        raise


def _next_code(root: Path, engine: RuleEngine, live: frozenset[str]) -> str | None:
    band = _BANDS.get(engine)
    if band is None:
        return None
    used = {number for number in _code_numbers((*live, *_source_texts(root))) if number in band}
    available = max(used, default=band.start - 1) + 1
    if available not in band:
        msg = f"no unreserved SARJ codes remain in the {engine.value} band"
        raise ValueError(msg)
    return f"SARJ{available:03d}"


def _source_texts(root: Path) -> Iterable[str]:
    ledger = root / rule_registration.LEDGER
    if ledger.is_file():
        data = as_table(parse_json(ledger.read_text(encoding="utf-8")))
        codes = as_table(data.get("codes"))
        for family in codes:
            yield from (code for code in list_field(codes, family) if isinstance(code, str))
        for raw in list_field(data, "retired"):
            item = as_table(raw)
            if item.get("kind") == "code" and isinstance(code := item.get("id"), str):
                yield code


def _code_numbers(texts: Iterable[str]) -> Iterable[int]:
    for text in texts:
        for match in _CODE.finditer(text):
            yield int(match.group("number"))


def _python_implementation(module: str, class_name: str, slug: str, code: str, documentation: RuleDocumentation) -> str:
    example_factory = module.removeprefix("sarj_").removesuffix("_lint")
    suffix = {"python": "py", "sql": "sql", "iac": "tf"}[example_factory]
    level = "Severity" if example_factory == "python" else "DefaultLevel"
    signature = (
        "def check_context(self, context: PythonFileContext)"
        if example_factory == "python"
        else "def check(self, path: Path, source: str)"
    )
    context_import = (
        "from sarj_python_lint._file_context import PythonFileContext"
        if example_factory == "python"
        else "from pathlib import Path"
    )
    header = json.dumps(f"{code} — {documentation.summary}", ensure_ascii=False)[1:-1]
    return f'''"""{header}"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from {module}.rule_base import AutofixPolicy, Diagnostic, ExampleFile, ExampleOutcome, Rule, RuleCategory, RuleDocumentation, RuleExample, {level}

if TYPE_CHECKING:
    {context_import}


@final
class {class_name}(Rule):
    id = "{slug}"
    code = "{code}"
    documentation = RuleDocumentation(
        default_level={level}.{documentation.default_level.name},
        summary={documentation.summary!r},
        rationale={documentation.rationale!r},
        remediation={documentation.remediation!r},
        category=RuleCategory.{documentation.category.name},
        autofix=AutofixPolicy.{documentation.autofix.name},
        limitations={documentation.limitations!r},
        examples=(
            RuleExample(example_id="rejects-antipattern", title="Reject the anti-pattern", outcome=ExampleOutcome.MATCH, files=(ExampleFile.{example_factory}("case.{suffix}", "TODO invalid example\\n"),), focus_path=PurePosixPath("case.{suffix}"), expected_count=1, public=True),
            RuleExample(example_id="accepts-alternative", title="Accept the preferred alternative", outcome=ExampleOutcome.NO_MATCH, files=(ExampleFile.{example_factory}("case.{suffix}", "TODO valid example\\n"),), focus_path=PurePosixPath("case.{suffix}"), expected_count=0, public=True),
        ),
    )
    description = documentation.summary

    @override
    {signature} -> list[Diagnostic]:
        raise NotImplementedError("TODO: implement conservative detection")
'''


def _python_test(module: str, class_name: str, snake: str) -> str:
    return f"""from sarj_rule_contracts.examples import verify_native_rule
from {module}.__main__ import analyze
from {module}.rules.{snake} import {class_name}


def test_documented_examples() -> None:
    verify_native_rule({class_name}, analyze)
"""


def _eslint_implementation(slug: str, name: str, metadata: RuleDocumentation) -> str:
    message = name[0].lower() + name[1:]
    documentation = f"{slug.upper().replace('-', '_')}_DOCUMENTATION"
    if not documentation.isidentifier():
        documentation = f"RULE_{documentation}"
    return f"""import {{ createRule, type RuleDocumentation }} from "./_docs.js";

type MessageIds = "{message}";
type Options = readonly [];

export const {documentation} = {{
  defaultLevel: {json.dumps(metadata.default_level.value)},
  summary: {json.dumps(metadata.summary, ensure_ascii=False)},
  rationale: {json.dumps(metadata.rationale)},
  remediation: {json.dumps(metadata.remediation)},
  category: {json.dumps(metadata.category.value)},
  limitations: {json.dumps(metadata.limitations)},
  examples: [
    {{ id: "accepts-alternative", title: "Accept the preferred alternative", outcome: "no-match", files: [{{ path: "case.ts", source: "// TODO valid example" }}], focusPath: "case.ts", expectedCount: 0, public: true }},
    {{ id: "rejects-antipattern", title: "Reject the anti-pattern", outcome: "match", files: [{{ path: "case.ts", source: "// TODO invalid example" }}], focusPath: "case.ts", expectedCount: 1, public: true }},
  ],
}} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({{
  name: "{slug}",
  documentation: {documentation},
  meta: {{ type: "problem", docs: {{ description: {documentation}.summary }}, schema: [], messages: {{ {message}: {documentation}.summary }} }},
  defaultOptions: [],
  create() {{ throw new Error("TODO: implement conservative detection"); }},
}});
"""


def _eslint_test(slug: str) -> str:
    return f"""import {{ it }} from "vitest";
import {{ verifyRuleExamples }} from "../../src/verify-rule-examples.js";
import rule from "../../src/rules/{slug}.js";

it("executes the documented examples", async () => {{
  await verifyRuleExamples(rule);
}});
"""


def _text_implementation(name: str, slug: str, code: str, documentation: RuleDocumentation) -> str:
    return f"""from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import final, override

from sarj_standards.libs.linting.text_rule_base import Finding, Rule, RuleMeta
from sarj_standards.libs.rules import DefaultLevel, ExampleFile, ExpectedOutcome, Language, RuleCategory, RuleExample


@final
class {name}(Rule):
    id = "{slug}"
    documentation = RuleMeta(
        code="{code}",
        default_level=DefaultLevel.{documentation.default_level.name},
        summary={documentation.summary!r},
        rationale={documentation.rationale!r},
        remediation={documentation.remediation!r},
        category=RuleCategory.{documentation.category.name},
        languages=frozenset({{Language.CONFIG}}),
        file_patterns=("**/*.yml",),
        examples=(
            RuleExample(example_id="rejects-antipattern", title="Reject the anti-pattern", outcome=ExpectedOutcome.MATCH, files=(ExampleFile(path=PurePosixPath("case.yml"), source="TODO invalid example\\n"),), focus_path=PurePosixPath("case.yml"), expected_count=1, public=True),
            RuleExample(example_id="accepts-alternative", title="Accept the alternative", outcome=ExpectedOutcome.NO_MATCH, files=(ExampleFile(path=PurePosixPath("case.yml"), source="TODO valid example\\n"),), focus_path=PurePosixPath("case.yml"), expected_count=0, public=True),
        ),
    )

    @override
    def check(self, path: Path, source: str) -> list[Finding]:
        raise NotImplementedError("TODO: implement conservative detection")
"""


def _text_test(slug: str) -> str:
    return f"""from sarj_rule_contracts.examples import verify_examples
from sarj_standards.libs.repository.rule_examples import selected
from sarj_standards.libs.rules import RuleSelector


def test_documented_examples() -> None:
    rule = selected(RuleSelector.parse("text:{slug}"))
    verify_examples(rule.spec.examples, rule.analyze)
"""

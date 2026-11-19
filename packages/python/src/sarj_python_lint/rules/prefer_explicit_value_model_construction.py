from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._collection_initialization import collection_initializers, constructor_collection_field
from sarj_python_lint.rules._declared_contracts import DeclaredClass, DeclaredContracts
from sarj_python_lint.rules._value_models import value_model


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_HOOKS = frozenset({"__post_init__", "model_post_init", "__post_init_post_parse__"})
_COLLECTION_MODEL = "from dataclasses import dataclass, field\n@dataclass\nclass Context:\n    cues: list[str] = field(default_factory=list, repr=False)\n"


@final
class PreferExplicitValueModelConstruction(ProjectRule):
    id = "prefer-explicit-value-model-construction"
    code = "SARJ572"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer declared validation and explicit factories over value-model initialization hooks.",
        rationale=(
            "Handwritten post-initialization hooks hide validation and normalization in a separate construction "
            "phase. Repeated scalar checks can diverge from field contracts, while implicit mutation and effects "
            "make a value model harder to construct and reason about."
        ),
        remediation=(
            "Express scalar constraints in Pydantic fields and keep cross-field validation in an explicit native "
            "validator. Use a named typed factory for deliberate construction work or side effects. Preserve "
            "strictness, immutability and cross-field invariants when replacing a hook; do not merely delete it."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Warns on direct declarations of __post_init__, model_post_init and __post_init_post_parse__ in module-level import-proven stdlib/Pydantic dataclasses and Pydantic BaseModel subclasses. Source-visible stable Pydantic ancestry is followed with a bounded cycle guard.",
            "Class names, hook bodies and field names do not establish model identity. Unknown decorators, class-creation keywords, generic class parameters, ambiguous or mutated native imports, wildcard imports, dynamic namespaces, generated sources and unresolved ancestry are excluded. Dataclass identity inherited without a native decorator and nested classes are outside this initial scope.",
            "Ordinary constructors, iteration and context-manager protocols, unrelated classes and free functions remain legal. Native field/model validators are supported alternatives. This is warning-first design guidance, not a claim that framework initialization hooks are invalid Python; no automatic rewrite changes validation or construction behavior.",
            "Also reviews a fresh source-owned plain stdlib dataclass immediately followed by assignment of a literal list to its directly declared constructor-enabled list field. A single stable Boolean-parameter branch is supported. Existing constructor arguments, custom constructors, frozen models, descriptors, unknown defaults, intervening caller effects and directly observed post-init fields abstain. Preserve conditional defaults and initialization-hook timing; this warning does not prove that moving a value across a hook is equivalent, and offers no autofix.",
        ),
        examples=(
            RuleExample(
                example_id="collection-after-construction",
                scenario="collection-initialization",
                title="Review a fresh field's second initialization phase",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/context.py",
                        _COLLECTION_MODEL
                        + "def context(enabled: bool):\n    value = Context()\n    if enabled:\n        value.cues = ['One moment.']\n    return value\n",
                    ),
                ),
                focus_path=PurePosixPath("app/context.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="collection-in-constructor",
                scenario="collection-initialization",
                title="The constructor receives each instance's initial collection",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/context.py",
                        _COLLECTION_MODEL
                        + "def context(enabled: bool):\n    return Context(cues=['One moment.'] if enabled else [])\n",
                    ),
                ),
                focus_path=PurePosixPath("app/context.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="manual-dataclass-validation",
                title="Post-initialization repeats a field contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from dataclasses import dataclass\n"
                        "@dataclass(frozen=True, slots=True)\n"
                        "class AudioObject:\n"
                        "    generation: int\n"
                        "    def __post_init__(self) -> None:\n"
                        "        if type(self.generation) is not int or self.generation <= 0:\n"
                        "            raise ValueError('generation must be a positive integer')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-native-validation",
                title="The value field owns strict validation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Annotated\n"
                        "from pydantic import BaseModel, ConfigDict, Field\n"
                        "class AudioObject(BaseModel):\n"
                        "    model_config = ConfigDict(frozen=True)\n"
                        "    generation: Annotated[int, Field(strict=True, gt=0)]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="pydantic-post-initialization",
                title="A native value model also keeps initialization explicit",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from pydantic import BaseModel\n"
                        "class AudioObject(BaseModel):\n"
                        "    generation: int\n"
                        "    def model_post_init(self, context: object) -> None:\n"
                        "        audit(self.generation)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        if context.has_wildcard_import or context.dynamic_namespace:
            return []
        initializers = collection_initializers(context)
        if not initializers and not any(hook in context.symbol_source for hook in _HOOKS):
            return []
        contracts = DeclaredContracts(context)
        if contracts.unit is None:
            return []
        findings = _hook_findings(context, contracts)
        findings.extend(
            Diagnostic(
                context.path,
                assignment.lineno,
                assignment.col_offset + 1,
                self.code,
                "Review initializing this fresh dataclass list field in its constructor. Preserve conditional defaults and initialization-hook observation timing; no automatic movement is proven safe.",
                severity=Severity.WARNING,
            )
            for assignment, call in initializers.items()
            if not context.suppressions.is_suppressed(assignment.lineno, self.code)
            and constructor_collection_field(call, assignment, contracts)
        )
        return findings


def _hook_findings(context: PythonFileContext, contracts: DeclaredContracts) -> list[Diagnostic]:
    if context.tree is None or contracts.unit is None:
        return []
    findings: list[Diagnostic] = []
    for owner in context.tree.body:
        if not isinstance(owner, ast.ClassDef):
            continue
        hooks = _declared_hooks(owner)
        if not hooks or not value_model(DeclaredClass(contracts.unit, owner), contracts):
            continue
        findings.extend(
            Diagnostic(
                context.path,
                hook.lineno,
                hook.col_offset + 1,
                PreferExplicitValueModelConstruction.code,
                f"Value-model hook `{hook.name}` hides a construction phase; use declared field constraints, "
                "native validators or a named typed factory while preserving its invariants.",
                severity=Severity.WARNING,
            )
            for hook in hooks
            if not context.suppressions.is_suppressed(hook.lineno, PreferExplicitValueModelConstruction.code)
        )
    return findings


def _declared_hooks(owner: ast.ClassDef) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    return tuple(
        member
        for member in owner.body
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and member.name in _HOOKS
    )

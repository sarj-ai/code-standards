from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._first_party import (
    FirstPartyFacts,
    has_first_party_source,
    is_first_party_module,
    own_top_package,
    same_distribution,
)


if TYPE_CHECKING:
    from pathlib import Path


class NoFirstPartyPrivateImport(Rule):
    id: str = "no-first-party-private-import"
    code: str = "SARJ048"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Code imports a private name or module from another first-party package.",
        rationale="Cross-package private imports couple callers to internals instead of a public surface the owning package can maintain.",
        remediation="Export the capability under a public name or move the caller behind an existing public function.",
        category=RuleCategory.ARCHITECTURE,
        limitations=(
            "First-party ownership is resolved from repository package manifests and source trees.",
            "Relative imports, public and dunder names, third-party and standard-library imports, and supported compiled extensions are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="cross-package-private-import",
                title="Service imports another package's private helper",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(".git/keep", "fixture\n"),
                    ExampleFile.python("python/service/pyproject.toml", '[project]\nname = "service"\n'),
                    ExampleFile.python("python/service/service/__init__.py", "\n"),
                    ExampleFile.python("python/service/tests/test_api.py", "from core.helpers import _decode\n"),
                    ExampleFile.python("python/core/pyproject.toml", '[project]\nname = "core"\n'),
                    ExampleFile.python("python/core/core/__init__.py", "\n"),
                    ExampleFile.python("python/core/core/helpers.py", "def _decode(value):\n    return value\n"),
                ),
                focus_path=PurePosixPath("python/service/tests/test_api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="cross-package-public-import",
                title="Service imports a public helper",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(".git/keep", "fixture\n"),
                    ExampleFile.python("python/service/pyproject.toml", '[project]\nname = "service"\n'),
                    ExampleFile.python("python/service/service/__init__.py", "\n"),
                    ExampleFile.python("python/service/tests/test_api.py", "from core.helpers import decode\n"),
                    ExampleFile.python("python/core/pyproject.toml", '[project]\nname = "core"\n'),
                    ExampleFile.python("python/core/core/__init__.py", "\n"),
                    ExampleFile.python("python/core/core/helpers.py", "def decode(value):\n    return value\n"),
                ),
                focus_path=PurePosixPath("python/service/tests/test_api.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        facts = self._analysis_session.first_party if self._analysis_session is not None else FirstPartyFacts()
        own_top = own_top_package(path, facts=facts)
        diags = [
            Diagnostic(path=path, line=hit.line, col=hit.col, code=self.code, message=_message(hit.module, hit.name))
            for hit in _private_imports(tree)
            if _is_ours(hit.module, path, own_top, facts) and not _is_our_own_internals(hit, path, facts)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


@dataclass(frozen=True, slots=True)
class _PrivateImport:
    line: int
    col: int
    module: str
    name: str
    #: The private thing is a segment of the module path, not an imported name.
    is_segment: bool
    #: Every name this statement imports is public (vacuously true for `import x._y`).
    names_public: bool


def _is_our_own_internals(hit: _PrivateImport, path: Path, facts: FirstPartyFacts) -> bool:
    if not hit.is_segment:
        return False
    if not has_first_party_source(hit.module, path, facts=facts):
        return True
    return hit.names_public and same_distribution(hit.module, path, facts=facts)


def _message(module: str, name: str) -> str:
    return (
        f"`{name}` is private to `{module}`, which is first-party — importing it reaches past a public "
        f"surface we own and can widen. Export it under a public name, or move the caller behind a "
        f"function `{module}` already exports. (Private imports from third-party packages are never flagged.)"
    )


def _is_ours(module: str, path: Path, own_top: str | None, facts: FirstPartyFacts) -> bool:
    top = module.partition(".")[0]
    if own_top is not None and top == own_top:
        return False
    return is_first_party_module(module, path, facts=facts)


def _private_imports(tree: ast.Module) -> list[_PrivateImport]:
    hits: list[_PrivateImport] = []
    for node in nodes(tree, ast.ImportFrom, ast.Import):
        if isinstance(node, ast.ImportFrom):
            hits.extend(_from_import_hits(node))
        else:
            hits.extend(_plain_import_hits(node))
    return hits


def _from_import_hits(node: ast.ImportFrom) -> list[_PrivateImport]:
    # `node.level` > 0 is a relative import: inside its own package by construction.
    if node.level or not node.module:
        return []
    private_segment = _private_segment(node.module)
    if private_segment is not None:
        return [
            _PrivateImport(
                line=node.lineno,
                col=node.col_offset + 1,
                module=node.module,
                name=private_segment,
                is_segment=True,
                names_public=not any(_is_private_name(alias.name) for alias in node.names),
            )
        ]
    return [
        _PrivateImport(
            line=alias.lineno,
            col=alias.col_offset + 1,
            module=node.module,
            name=name,
            is_segment=False,
            names_public=False,
        )
        for alias in node.names
        if _is_private_name(name := alias.name)
    ]


def _plain_import_hits(node: ast.Import) -> list[_PrivateImport]:
    hits: list[_PrivateImport] = []
    for alias in node.names:
        private_segment = _private_segment(alias.name)
        if private_segment is not None:
            hits.append(
                _PrivateImport(
                    line=alias.lineno,
                    col=alias.col_offset + 1,
                    module=alias.name,
                    name=private_segment,
                    is_segment=True,
                    names_public=True,
                )
            )
    return hits


def _private_segment(module: str) -> str | None:
    return next((part for part in module.split(".")[1:] if _is_private_name(part)), None)


def _is_private_name(name: str) -> bool:
    # `__version__` / `__all__` are module metadata by convention, not internals.
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))

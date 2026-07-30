"""SARJ050: a docstring that only re-spells the signature it sits under.

    def get_profile_by_national_id(self, national_id: str) -> Profile | None:
        \"\"\"Get profile by national ID.\"\"\"

Every content word of the docstring is already in the function's name, its
parameters or its annotations. It answers no question a reader could have — not
what the caller must guarantee, not what it raises, not why it exists — and it
takes a line of screen and a line of review for nothing.

**The fix is to delete the WHOLE docstring, not to trim it.** Removing only the
summary line leaves a docstring whose first line is an `Args:` header, which
ruff then flags (D212/D415), and shrinking a Google-style block to its sections
trips D417/DOC201. A function with no docstring at all is clean under this
repo's strict ruff config; a half-docstring is not.

**Never flagged**

- **`@function_tool` docstrings are LLM prompts.** In an agent framework
  (openai-agents, livekit-agents, langchain, FastMCP) the docstring is shipped
  to the model as the tool description — deleting it changes what the agent
  does at runtime. This is a hard exemption, not a heuristic one, and it is the
  single most dangerous autofix this rule could have offered.
- **CLI command docstrings are `--help` text** for click / typer, and a
  FastAPI / Flask route handler's docstring is the OpenAPI operation
  description. Same argument: the text is an artefact someone reads elsewhere.
- **Value markers**: a `Raises:` section, a doctest prompt, a URL, an RFC, a
  reST directive, or a number with a unit — plus the whole nine-signal protected
  class from `_comments`, which is what keeps "Should return 401 with invalid
  token" (a status code the signature cannot carry) off the list.
- **Stubs whose body IS the docstring** — a `Protocol` method or an abstract
  declaration. "Delete the whole docstring" would leave an empty suite, so the
  advice this rule gives would not compile.
- **Generated code**, whose docstrings mirror whatever the generator emits.
- **Negations count as content.** "Does NOT close the socket" restates the name
  and then contradicts the obvious reading of it, which is the most valuable
  sentence a docstring can contain; `not`, `no` and `never` are therefore NOT
  stopwords here even though they are in the comment tokenizer's list.

**Measured.** bulbul **5**, noura-be **105**, pydantic **22**, trio **4**,
attrs **8** — 144 findings. 40 were hand-read across the two maintained repos
and one was borderline (a test docstring adding "for protected endpoints"), so
≥95% precision. The FastAPI-route and docstring-only-body exemptions were both
found by that read, not predicted.

**Three shapes this rule structurally cannot reach**, each now owned by its own
code rather than folded in here (a consumer repo pins this package by caret and
runs SARJ050 at `error`, so widening it would land uncontrolled on a patch
release):
a `class` docstring, which this walker never inspects (SARJ085); a docstring
carrying a Google-style `Args:` block, where the literal word "args" is a
content word no signature contains and so nothing below it can ever be judged
(SARJ086); and an override that copies its base's docstring verbatim, which
restates the base, not the signature (SARJ084).

The stopword list, the value markers, the prompt-decorator set and the
restatement test moved to `rules/_docstrings` unchanged when those three
arrived — four rules asking the same question must not answer it four ways.

Suppress an intentional case with `# sarj-noqa: SARJ050 — <reason>`.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children
<<<<<<< HEAD
from sarj_python_lint.rules._comments import is_protected, split_identifier, stem
from sarj_python_lint.rules._paths import is_generated
||||||| parent of a303d90 (feat(python): three docstring-ceremony rules SARJ050 cannot reach)
from sarj_python_lint.rules._comments import is_protected, split_identifier, stem
from sarj_python_lint.rules._paths import is_generated_source
=======
from sarj_python_lint.rules._comments import is_protected
from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    decorator_markers,
    restates,
    signature_stems,
)
from sarj_python_lint.rules._paths import is_generated_source
>>>>>>> a303d90 (feat(python): three docstring-ceremony rules SARJ050 cannot reach)


if TYPE_CHECKING:
    from pathlib import Path


class RedundantDocstring(Rule):
    """A docstring whose every content word already appears in the signature."""

    id: str = "redundant-docstring"
    code: str = "SARJ050"
    description: str = (
        "Docstring only re-spells the signature — delete the whole docstring, "
        "or replace it with what the caller cannot read off the name."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        self._walk(tree, None, path, diags)
        return sorted(diags, key=lambda d: d.line)

    def _walk(
        self,
        node: ast.AST,
        class_name: str | None,
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        for child in children(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function(child, class_name, path, diags)
                self._walk(child, class_name, path, diags)
            elif isinstance(child, ast.ClassDef):
                self._walk(child, child.name, path, diags)
            else:
                self._walk(child, class_name, path, diags)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
        path: Path,
        diags: list[Diagnostic],
    ) -> None:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or VALUE_MARKER_RE.search(docstring) or is_protected(docstring):
            return
        if len(node.body) == 1:
            return  # the docstring IS the body; deleting it leaves a syntax error
        if decorator_markers(node) & PROMPT_DECORATOR_MARKERS:
            return
        if not restates(docstring, signature_stems(node, class_name)):
            return
        expr = node.body[0]
        diags.append(
            Diagnostic(
                path=path,
                line=expr.lineno,
                col=expr.col_offset + 1,
                code=self.code,
                message=self.description,
            )
        )

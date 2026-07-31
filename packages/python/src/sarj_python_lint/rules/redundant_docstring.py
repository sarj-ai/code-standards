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

Suppress an intentional case with `# sarj-noqa: SARJ050 — <reason>`.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected, split_identifier, stem
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


# Docstring filler that says nothing about *which* thing is being described.
# `not` / `no` / `none` / `never` are deliberately ABSENT: a docstring that
# negates the obvious reading of a name is the most useful kind there is.
_STOPWORDS = frozenset(
    {
        "a",
        "all",
        "an",
        "and",
        "are",
        "as",
        "at",
        "based",
        "be",
        "been",
        "being",
        "by",
        "class",
        "current",
        "do",
        "does",
        "false",
        "for",
        "from",
        "function",
        "get",
        "gets",
        "given",
        "helper",
        "if",
        "in",
        "instance",
        "instances",
        "into",
        "is",
        "it",
        "its",
        "method",
        "new",
        "object",
        "objects",
        "of",
        "on",
        "or",
        "provided",
        "return",
        "returned",
        "returns",
        "s",
        "set",
        "sets",
        "should",
        "specified",
        "that",
        "the",
        "these",
        "this",
        "those",
        "to",
        "true",
        "using",
        "value",
        "values",
        "was",
        "when",
        "whether",
        "which",
        "will",
        "with",
    }
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9']*")

# Content the signature cannot carry, so the docstring is earning its place.
_VALUE_MARKER_RE = re.compile(
    r"https?://|\bRFC\s?\d|:raises|\bRaises:|>>>|\bExamples?:|^\s*\.\. |"
    r"\b(?:ms|msec|milliseconds?|seconds?|secs?|minutes?|hours?|days?|bytes?|kb|mb|gb|hz|khz|"
    r"utc|iso.?8601|e\.?164|base64|utf-?8|px|dbfs?|db)\b|%",
    re.IGNORECASE | re.MULTILINE,
)

# Decorators whose docstring is consumed by something other than a reader, so
# deleting it changes an artefact rather than tidying a file:
#   - `function_tool` / `tool` hand it to a language model as the tool
#     description, which is what the agent reasons over;
#   - click and typer hand it to the terminal as `--help`;
#   - FastAPI / Starlette / Flask routing decorators hand it to the OpenAPI
#     schema as the operation description. That last one was found by the corpus
#     sweep: bulbul's `@router.post("/desk/create-ticket")` handler carries
#     "Create a ticket in Zoho Desk for the specified organization", which is the
#     text an API consumer reads.
_PROMPT_DECORATOR_MARKERS = frozenset(
    {
        "agent",
        "api_route",
        "app",
        "blueprint",
        "cli",
        "click",
        "command",
        "delete",
        "function_tool",
        "get",
        "group",
        "mcp",
        "option",
        "patch",
        "post",
        "put",
        "route",
        "router",
        "server",
        "tool",
        "tools",
        "typer",
        "websocket",
    }
)


def _decorator_markers(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    markers: set[str] = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        try:
            markers.update(part.lower() for part in re.split(r"\W+", ast.unparse(target)) if part)
        except AttributeError, ValueError:  # pragma: no cover — unparse is total for these nodes
            continue
    return markers


def _annotation_tokens(annotation: ast.expr | None) -> list[str]:
    if annotation is None:
        return []
    try:
        rendered = ast.unparse(annotation)
    except AttributeError, ValueError:  # pragma: no cover
        return []
    return [part for token in re.split(r"\W+", rendered) if token for part in split_identifier(token)]


def _signature_stems(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None) -> set[str]:
    tokens = list(split_identifier(node.name))
    if class_name is not None:
        tokens.extend(split_identifier(class_name))
    args = node.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
        if arg is None:
            continue
        if arg.arg not in {"self", "cls"}:
            tokens.extend(split_identifier(arg.arg))
        tokens.extend(_annotation_tokens(arg.annotation))
    tokens.extend(_annotation_tokens(node.returns))
    return {stem(token) for token in tokens}


def _restates_signature(docstring: str, signature: set[str]) -> bool:
    words = [match.group(0).lower() for match in _WORD_RE.finditer(docstring)]
    content = [word for word in words if word not in _STOPWORDS]
    if not words or not content:
        return False
    return all(stem(word) in signature for word in content)


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
        if not docstring or _VALUE_MARKER_RE.search(docstring) or is_protected(docstring):
            return
        if len(node.body) == 1:
            return  # the docstring IS the body; deleting it leaves a syntax error
        if _decorator_markers(node) & _PROMPT_DECORATOR_MARKERS:
            return
        if not _restates_signature(docstring, _signature_stems(node, class_name)):
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

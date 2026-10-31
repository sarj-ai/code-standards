from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint._secret_names import identifier_tokens, is_secret_name
from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_python_lint.rules._logging import LOG_METHODS, is_logger_expr
from sarj_python_lint.rules._loguru import logger_imports_untouched


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


# A whole redaction token (`token_prefix`, `password_hash`, `secret_masked`,
# `api_key_tag`) means the identifier names a masked/derived value. Whole-token
# matching avoids treating unrelated substrings as redaction evidence.
_REDACTION_TOKENS = frozenset(
    {"prefix", "suffix", "redact", "redacted", "mask", "masked", "hash", "hint", "len", "length", "tag"}
)
_LOGURU_OPT_PARAMETERS = frozenset({"exception", "record", "lazy", "colors", "raw", "capture", "depth", "ansi"})
_LOGURU_LOG_METHODS = frozenset(
    {"trace", "debug", "info", "success", "warning", "error", "critical", "exception", "log"}
)


@dataclass(frozen=True, slots=True)
class _OptBindingCandidate:
    root: ast.expr
    values: tuple[ast.expr, ...]


def _is_raw_secret_reference(value: ast.expr) -> bool:
    match value:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return _is_secret_keyword(name)
        case ast.Subscript(
            value=receiver,
            slice=ast.Slice(lower=None | ast.Constant(value=0), upper=None, step=None | ast.Constant(value=1)),
        ):
            return _is_raw_secret_reference(receiver)
        case ast.Subscript(slice=ast.Constant(value=str() as key)):
            return _is_secret_keyword(key)
        case _:
            return False


def _is_secret_keyword(name: str) -> bool:
    if any(token in _REDACTION_TOKENS for token in identifier_tokens(name)):
        return False
    return is_secret_name(name)


def _unsafe_message_values(value: ast.expr) -> tuple[ast.expr, ...]:
    if _is_raw_secret_reference(value):
        return (value,)
    match value:
        case ast.JoinedStr(values=parts):
            return _unsafe_formatted_values(parts)
        case ast.BinOp(op=ast.Add(), left=left, right=right):
            return (*_unsafe_message_values(left), *_unsafe_message_values(right))
        case ast.List(elts=elements) | ast.Tuple(elts=elements) | ast.Set(elts=elements):
            return tuple(secret for element in elements for secret in _unsafe_message_values(element))
        case ast.Dict():
            return _literal_mapping_secret_values(value)
        case ast.BinOp(op=ast.Mod(), right=right):
            values = right.elts if isinstance(right, (ast.Tuple, ast.List)) else (right,)
            return _raw_secret_values(values)
        case ast.Call(func=ast.Attribute(value=ast.Constant(value=str()), attr="format"), args=args, keywords=keywords):
            values = (*args, *(keyword.value for keyword in keywords))
            return _raw_secret_values(values)
        case _:
            return ()


def _raw_secret_values(values: Iterable[ast.expr]) -> tuple[ast.expr, ...]:
    return tuple(value for value in values if _is_raw_secret_reference(value))


class NoSecretInLog(Rule):
    id: str = "no-secret-in-log"
    code: str = "SARJ012"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="A direct credential-like reference is passed to a recognized logging call.",
        rationale="Raw credentials in logs can spread to durable sinks and readers outside the request boundary.",
        remediation="Omit the credential or log only approved non-sensitive metadata through a centralized sanitizer.",
        category=RuleCategory.SECURITY,
        limitations=(
            "Detection covers direct secret-named message and argument values, terminal attributes, constant secret-key subscripts, identity slices, f-string and literal format arguments, string concatenation, nested literal containers, literal keyword unpacking, and immediate structured-logger bindings.",
            "Immediate opt calls on a proven untouched native Loguru logger expose only the first bind's values. Positional or expanded chain arguments, unsupported opt keyword names, custom wrappers, stored aliases, and visibly mutated or escaped imports are excluded from this added coverage.",
            "This added coverage requires a native Loguru logging method and a positional message, with no terminal keyword or expanded arguments. Terminal fields are excluded even with capture=False, rather than evaluating option state or merging fields that may override bindings.",
            "Earlier inner bindings are not merged: a safe outer binding hides earlier bindings, including nonconflicting fields. Opaque runtime effects remain unresolved.",
            "Logger recognition and secret classification are lexical; general aliases, arbitrary calls, dynamic containers, and interprocedural dataflow are not inspected.",
        ),
        examples=(
            RuleExample(
                example_id="secret-logging-keyword",
                title="Raw token passed to a logger",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("service.py", "logger.info('request', token=token)\n"),),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="redacted-logging-keyword",
                title="Only non-sensitive authentication metadata is logged",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "logger.info('request authenticated', auth_method='bearer', credential_present=token is not None)\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        tree = context.tree
        if tree is None:
            return []
        provenance: ResourceProvenance | None = None
        untouched = False
        diags: list[Diagnostic] = []
        for node in context.nodes(ast.Call):
            function = node.func
            if not isinstance(function, ast.Attribute) or not _is_logging_call(node):
                continue
            _collect_message_secrets(path, node, self.code, diags)
            _collect_keyword_secrets(path, node, self.code, diags)
            bound_values = _bound_logger_values(function.value)
            candidate = _opt_binding_candidate(node)
            if candidate is not None:
                if provenance is None:
                    provenance = context.static_resource_provenance
                    untouched = logger_imports_untouched(context, provenance)
                if untouched and provenance.imported(candidate.root, "loguru.logger"):
                    bound_values = candidate.values
            diags.extend(_diagnostic(path, value, self.code, "structured logger binding") for value in bound_values)
        return diags


def _bound_logger_values(receiver: ast.expr) -> tuple[ast.expr, ...]:
    if not isinstance(receiver, ast.Call) or not isinstance(receiver.func, ast.Attribute):
        return ()
    if receiver.func.attr not in {"bind", "contextualize"}:
        return ()
    return tuple(secret for keyword in receiver.keywords for secret in _unsafe_message_values(keyword.value))


def _opt_binding_candidate(call: ast.Call) -> _OptBindingCandidate | None:
    receiver = _loguru_terminal_receiver(call)
    if receiver is None:
        return None
    binding = receiver
    if not isinstance(binding, ast.Call) or not isinstance(binding.func, ast.Attribute) or binding.func.attr != "opt":
        return None
    while isinstance(binding, ast.Call) and isinstance(binding.func, ast.Attribute) and binding.func.attr == "opt":
        binding = binding.func.value
    if not isinstance(binding, ast.Call) or not isinstance(binding.func, ast.Attribute) or binding.func.attr != "bind":
        return None
    values = _bound_logger_values(binding)
    if not values:
        return None
    root = _loguru_chain_root(receiver)
    if root is None:
        return None
    return _OptBindingCandidate(root=root, values=values)


def _loguru_terminal_receiver(call: ast.Call) -> ast.expr | None:
    function = call.func
    if (
        not isinstance(function, ast.Attribute)
        or function.attr not in _LOGURU_LOG_METHODS
        or len(call.args) <= int(function.attr == "log")
        or call.keywords
        or any(isinstance(argument, ast.Starred) for argument in call.args)
    ):
        return None
    return function.value


def _loguru_chain_root(receiver: ast.expr) -> ast.expr | None:
    root = receiver
    while isinstance(root, ast.Call) and isinstance(root.func, ast.Attribute):
        if root.func.attr not in {"bind", "opt"} or root.args or any(keyword.arg is None for keyword in root.keywords):
            return None
        if root.func.attr == "opt" and any(keyword.arg not in _LOGURU_OPT_PARAMETERS for keyword in root.keywords):
            return None
        root = root.func.value
    return root


def _diagnostic(path: Path, value: ast.expr, code: str, context: str) -> Diagnostic:
    return Diagnostic(
        path=path,
        line=value.lineno,
        col=value.col_offset + 1,
        code=code,
        message=f"Credential-like reference in {context} may expose sensitive data to log sinks — omit it.",
    )


def _is_logging_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in LOG_METHODS:
        return False
    return is_logger_expr(func.value)


def _unsafe_formatted_values(parts: list[ast.expr]) -> tuple[ast.expr, ...]:
    return tuple(
        part.value for part in parts if isinstance(part, ast.FormattedValue) and _is_raw_secret_reference(part.value)
    )


def _collect_message_secrets(path: Path, node: ast.Call, code: str, diags: list[Diagnostic]) -> None:
    function = node.func
    if not isinstance(function, ast.Attribute):
        return
    message_index = 1 if function.attr == "log" else 0
    for arg in node.args[message_index:]:
        diags.extend(
            Diagnostic(
                path=path,
                line=unsafe.lineno,
                col=unsafe.col_offset + 1,
                code=code,
                message="Credential-like reference is interpolated into a log message and may expose sensitive data — omit it.",
            )
            for unsafe in _unsafe_message_values(arg)
        )


def _collect_keyword_secrets(path: Path, node: ast.Call, code: str, diags: list[Diagnostic]) -> None:
    for kw in node.keywords:
        if kw.arg is None:
            if isinstance(kw.value, ast.Dict):
                diags.extend(
                    _diagnostic(path, value, code, "literal unpacked logging field")
                    for value in _literal_mapping_secret_values(kw.value)
                )
            continue
        if kw.arg == "extra" and isinstance(kw.value, ast.Dict):
            diags.extend(
                _diagnostic(path, value, code, "literal `extra` field")
                for value in _literal_mapping_secret_values(kw.value)
            )
        else:
            diags.extend(
                _diagnostic(path, value, code, f"`{kw.arg}` logging field")
                for value in _unsafe_message_values(kw.value)
            )


def _literal_mapping_secret_values(mapping: ast.Dict) -> tuple[ast.expr, ...]:
    return tuple(secret for _, value in _literal_mapping_items(mapping) for secret in _unsafe_message_values(value))


def _literal_mapping_items(mapping: ast.Dict) -> tuple[tuple[str, ast.expr], ...]:
    items: dict[str, ast.expr] = {}
    for key, value in zip(mapping.keys, mapping.values, strict=True):
        if key is None and isinstance(value, ast.Dict):
            items.update(_literal_mapping_items(value))
        elif isinstance(key, ast.Constant) and isinstance(key.value, str):
            items[key.value] = value
        else:
            items.clear()
    return tuple(items.items())

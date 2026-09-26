from __future__ import annotations

import ast
from dataclasses import dataclass, fields
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- checkout-local TypeScript parser.

from sarj_rule_contracts import RuleDocumentation

from sarj_standards.libs.adoption.manifest import as_table
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.rules import DefaultLevel, RuleEngine, RuleSelector


_TEXT_ENTRY = re.compile(r'(?m)^        "[a-z0-9-]+": RuleMeta\(')
_TEXT_LEVEL = re.compile(r"(?m)^            default_level=DefaultLevel\.(ERROR|WARNING),\n")
_NATIVE_LEVEL_POSITION = tuple(field.name for field in fields(RuleDocumentation)).index("default_level")


@dataclass(frozen=True, slots=True)
class _RenderedLevel:
    source: str
    current: DefaultLevel


@dataclass(frozen=True, slots=True)
class LevelEdit:
    path: Path
    before: str
    after: str
    current: DefaultLevel


def prepare(root: Path, selector: RuleSelector, relative_source: str, level: DefaultLevel) -> LevelEdit:
    path = root / relative_source
    before = path.read_text(encoding="utf-8")
    if selector.engine is RuleEngine.ESLINT:
        rendered = _typescript(root, before, level)
    elif selector.engine is RuleEngine.TEXT:
        rendered = _text(before, level, rule_id=str(selector.rule_id))
    else:
        rendered = _python(before, selector.engine, level)
    if selector.engine is not RuleEngine.ESLINT:
        compile(rendered.source, str(path), "exec", dont_inherit=True)
    return LevelEdit(path=path, before=before, after=rendered.source, current=rendered.current)


def _typescript(root: Path, source: str, level: DefaultLevel) -> _RenderedLevel:
    node = shutil.which("node")
    if node is None:
        msg = "cannot edit TypeScript severity: node is not installed"
        raise RuntimeError(msg)
    helper = Path(__file__).parents[2] / "configs/rule-level-source.mjs"
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed parser helper and severity.
        (node, str(helper), level.value),
        cwd=root / "packages/typescript",
        input=source,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode:
        raise ValueError(completed.stderr.strip() or "TypeScript severity edit failed")
    result = as_table(parse_json(completed.stdout))
    edited, current = result.get("source"), result.get("current")
    if not isinstance(edited, str) or not isinstance(current, str):
        msg = "TypeScript severity editor returned malformed output"
        raise ValueError(msg)  # ruff: ignore[type-check-without-type-error] -- malformed subprocess payload.
    return _RenderedLevel(edited, DefaultLevel(current))


def _python(source: str, engine: RuleEngine, level: DefaultLevel) -> _RenderedLevel:
    enum = "Severity" if engine is RuleEngine.PYTHON else "DefaultLevel"
    call = _documentation(source, "RuleDocumentation")
    field = next((keyword for keyword in call.keywords if keyword.arg == "default_level"), None)
    if field is not None:
        return _replace_level(source, field.value, level)
    if any(isinstance(argument, ast.Starred) for argument in call.args) or any(
        keyword.arg is None for keyword in call.keywords
    ):
        msg = "unpacked rule documentation must declare an explicit default_level keyword"
        raise ValueError(msg)
    if len(call.args) > _NATIVE_LEVEL_POSITION:
        return _replace_level(source, call.args[_NATIVE_LEVEL_POSITION], level)
    if level is DefaultLevel.ERROR:
        return _RenderedLevel(source, DefaultLevel.ERROR)
    updated = _insert_native_level(source, call, enum)
    return _RenderedLevel(_add_native_import(updated, engine, enum), DefaultLevel.ERROR)


def _insert_native_level(source: str, call: ast.Call, enum: str) -> str:
    field = f"default_level={enum}.WARNING"
    if not call.keywords and call.args:
        last = call.args[-1]
        position = _position(source, last.end_lineno or last.lineno, last.end_col_offset)
        return source[:position] + f", {field}" + source[position:]
    first = call.keywords[0] if call.keywords else None
    position = (
        _position(source, first.lineno, first.col_offset)
        if first
        else _position(source, call.end_lineno or call.lineno, call.end_col_offset) - 1
    )
    indent = source[source.rfind("\n", 0, position) + 1 : position]
    separator = "\n" + indent if not indent.strip() else " "
    return source[:position] + field + "," + separator + source[position:]


def _add_native_import(source: str, engine: RuleEngine, name: str) -> str:
    imports = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module == f"sarj_{engine.value}_lint.rule_base"
    ]
    if any(alias.name == name and alias.asname is None for node in imports for alias in node.names):
        return source
    if len(imports) != 1:
        msg = "native rule source must import its rule base"
        raise ValueError(msg)
    node = imports[0]
    following = next((alias for alias in node.names if alias.name.casefold() > name.casefold()), None)
    if following is not None:
        position = _position(source, following.lineno, following.col_offset)
        separator = _import_separator(source, node, following)
        return source[:position] + name + "," + separator + source[position:]
    last = node.names[-1]
    position = _position(source, last.end_lineno or last.lineno, last.end_col_offset)
    separator = _import_separator(source, node, last)
    return source[:position] + "," + separator + name + source[position:]


def _import_separator(source: str, node: ast.ImportFrom, alias: ast.alias) -> str:
    position = _position(source, alias.lineno, alias.col_offset)
    indent = source[source.rfind("\n", 0, position) + 1 : position]
    if indent.strip() or "\\\n" in (ast.get_source_segment(source, node) or ""):
        return " "
    return f"\n{indent}"


def _text(source: str, level: DefaultLevel, *, rule_id: str) -> _RenderedLevel:
    anchor = f'        "{rule_id}": RuleMeta(\n'
    if anchor not in source:
        return _modular_text(source, level)
    if source.count(anchor) != 1:
        msg = "text rule source must contain one registry entry"
        raise ValueError(msg)
    start = source.index(anchor) + len(anchor)
    next_entry = _TEXT_ENTRY.search(source[start:])
    end = len(source) if next_entry is None else start + next_entry.start()
    chunk = source[start:end]
    field = _TEXT_LEVEL.search(chunk)
    current = DefaultLevel.ERROR if field is None else DefaultLevel(field.group(1).lower())
    if current is level:
        return _RenderedLevel(source, current)
    if field is None:
        replacement = f"            default_level=DefaultLevel.{level.name},\n" + chunk
    elif level is DefaultLevel.ERROR:
        replacement = chunk[: field.start()] + chunk[field.end() :]
    else:
        replacement = (
            chunk[: field.start()] + f"            default_level=DefaultLevel.{level.name},\n" + chunk[field.end() :]
        )
    return _RenderedLevel(source[:start] + replacement + source[end:], current)


def _modular_text(source: str, level: DefaultLevel) -> _RenderedLevel:
    call = _documentation(source, "RuleMeta")
    field = next((keyword for keyword in call.keywords if keyword.arg == "default_level"), None)
    if field is None:
        msg = "modular text rule documentation must declare an explicit default_level"
        raise ValueError(msg)
    return _replace_level(source, field.value, level)


def _documentation(source: str, constructor: str) -> ast.Call:
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == constructor
    ]
    if len(calls) != 1:
        msg = "rule source must contain one documentation declaration"
        raise ValueError(msg)
    return calls[0]


def _replace_level(source: str, node: ast.expr, level: DefaultLevel) -> _RenderedLevel:
    if not isinstance(node, ast.Attribute):
        msg = "rule documentation must declare an explicit default_level enum value"
        raise ValueError(msg)  # ruff: ignore[type-check-without-type-error] -- unsupported authored syntax.
    current = DefaultLevel(node.attr.lower())
    if current is level:
        return _RenderedLevel(source, current)
    end = _position(source, node.end_lineno or node.lineno, node.end_col_offset)
    return _RenderedLevel(source[: end - len(node.attr)] + level.name + source[end:], current)


def _position(source: str, line: int, column: int | None) -> int:
    lines = source.splitlines(keepends=True)
    return sum(map(len, lines[: line - 1])) + len(lines[line - 1].encode()[:column].decode())

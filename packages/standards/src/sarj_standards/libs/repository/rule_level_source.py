from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from sarj_standards.libs.rules import DefaultLevel, RuleEngine, RuleSelector


_TYPESCRIPT_DOCUMENTATION = re.compile(r"(?m)^(?:export )?const \w+DOCUMENTATION = \{\n")
_PYTHON_DOCUMENTATION = re.compile(r"(RuleDocumentation\(\n)([ \t]+)")
_TEXT_ENTRY = re.compile(r'(?m)^        "[a-z0-9-]+": RuleMeta\(')
_TEXT_LEVEL = re.compile(r"(?m)^            default_level=DefaultLevel\.(ERROR|WARNING),\n")


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
        rendered = _typescript(before, level)
    elif selector.engine is RuleEngine.TEXT:
        rendered = _text(before, level, rule_id=str(selector.rule_id))
    else:
        rendered = _python(before, selector.engine, level)
    return LevelEdit(path=path, before=before, after=rendered.source, current=rendered.current)


def _typescript(source: str, level: DefaultLevel) -> _RenderedLevel:
    matches = tuple(_TYPESCRIPT_DOCUMENTATION.finditer(source))
    if len(matches) != 1:
        msg = "TypeScript rule source must contain one documentation declaration"
        raise ValueError(msg)
    end = matches[0].end()
    field = '  defaultLevel: "warning",\n'
    staged = source.startswith(field, end)
    current = DefaultLevel.WARNING if staged else DefaultLevel.ERROR
    if current is level:
        return _RenderedLevel(source, current)
    if level is DefaultLevel.WARNING:
        return _RenderedLevel(source[:end] + field + source[end:], current)
    return _RenderedLevel(source[:end] + source[end + len(field) :], current)


def _python(source: str, engine: RuleEngine, level: DefaultLevel) -> _RenderedLevel:
    matches = tuple(_PYTHON_DOCUMENTATION.finditer(source))
    if len(matches) != 1:
        msg = "Python rule source must contain one documentation declaration"
        raise ValueError(msg)
    end = matches[0].end()
    indent = matches[0].group(2)
    enum = "Severity" if engine is RuleEngine.PYTHON else "DefaultLevel"
    field = f"default_level={enum}.WARNING,\n{indent}"
    staged = source.startswith(field, end)
    current = DefaultLevel.WARNING if staged else DefaultLevel.ERROR
    if current is level:
        return _RenderedLevel(source, current)
    if level is DefaultLevel.WARNING:
        updated = source[:end] + field + source[end:]
        import_start = f"from sarj_{engine.value}_lint.rule_base import (\n"
        if updated.count(import_start) != 1:
            msg = "native rule source must import its rule base"
            raise ValueError(msg)
        import_field = f"    {enum},\n"
        if import_field not in updated:
            updated = _add_native_import(updated, import_start, enum)
        return _RenderedLevel(updated, current)
    updated = source[:end] + source[end + len(field) :]
    import_field = f"    {enum},\n"
    if updated.count(enum) == 1:
        updated = updated.replace(import_field, "", 1)
    return _RenderedLevel(updated, current)


def _add_native_import(source: str, import_start: str, name: str) -> str:
    start = source.index(import_start) + len(import_start)
    end = source.index("\n)", start)
    imports = source[start:end].splitlines()
    imports.append(f"    {name},")
    return source[:start] + "\n".join(sorted(imports, key=str.casefold)) + source[end:]


def _text(source: str, level: DefaultLevel, *, rule_id: str) -> _RenderedLevel:
    anchor = f'        "{rule_id}": RuleMeta(\n'
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

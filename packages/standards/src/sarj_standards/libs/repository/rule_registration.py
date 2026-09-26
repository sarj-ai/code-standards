from __future__ import annotations

import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re

from sarj_standards.libs.adoption.manifest import as_table, list_field
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.rules import RuleEngine, RuleSelector


LEDGER = Path("packages/standards/src/sarj_standards/configs/rule-ledger.json")


@dataclass(frozen=True, slots=True)
class FileEdit:
    path: Path
    before: bytes | None
    after: str


def registry_path(root: Path, engine: RuleEngine) -> Path:
    if engine is RuleEngine.ESLINT:
        return root / "packages/typescript/src/index.ts"
    if engine is RuleEngine.TEXT:
        return root / "packages/standards/src/sarj_standards/libs/linting/text_rules/_registry.py"
    package = engine.value
    return root / f"packages/{package}/src/sarj_{package}_lint/rules/_registry.py"


def plan(
    root: Path, selector: RuleSelector, code: str | None, *, reserved: frozenset[str] = frozenset()
) -> tuple[FileEdit, ...]:
    slug = str(selector.rule_id)
    name = "".join(part.capitalize() for part in slug.split("-"))
    registry = registry_path(root, selector.engine)
    before = registry.read_bytes() if registry.is_file() else None
    if selector.engine is RuleEngine.ESLINT:
        source = before.decode() if before is not None else "const RULES = {\n};\n"
        anchor = "const RULES = {\n"
        if source.count(anchor) != 1:
            msg = "ESLint registry must contain one RULES object"
            raise ValueError(msg)
        binding = name[0].lower() + name[1:]
        if re.search(rf"\b(?:import|const|let|class|function)\s+{re.escape(binding)}\b", source):
            msg = f"generated rule binding {binding} is already in use; choose a distinct rule ID"
            raise ValueError(msg)
        source = f'import {binding} from "./rules/{slug}.js";\n' + source.replace(
            anchor, anchor + f'  "{slug}": {binding},\n', 1
        )
    else:
        source = (
            before.decode()
            if before is not None
            else "from types import MappingProxyType\n\nREGISTRY = MappingProxyType({\n})\n"
        )
        module = (
            "sarj_standards.libs.linting.text_rules"
            if selector.engine is RuleEngine.TEXT
            else f"sarj_{selector.engine.value}_lint.rules"
        )
        source = _native(source, module, slug.replace("-", "_"), name)
    return FileEdit(registry, before, source), _reserve(root, selector, code, reserved)


def _native(source: str, module: str, snake: str, name: str) -> str:
    tree = ast.parse(source)
    if any(
        (alias.asname or alias.name.rsplit(".", 1)[-1]) == name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ):
        msg = f"generated rule class {name} is already in use; choose a distinct rule ID"
        raise ValueError(msg)
    dictionary = _registry_dictionary(tree)
    offset = _offset(source, dictionary.lineno, dictionary.col_offset) + 1
    source = source[:offset] + f"\n        {name}.id: {name}," + source[offset:]
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    line = max((node.end_lineno or node.lineno for node in imports), default=0)
    lines = source.splitlines(keepends=True)
    lines.insert(line, f"from {module}.{snake} import {name}\n")
    rendered = "".join(lines)
    ast.parse(rendered)
    return rendered


def _offset(source: str, line: int, column: int) -> int:
    lines = source.splitlines(keepends=True)
    return sum(map(len, lines[: line - 1])) + len(lines[line - 1].encode()[:column].decode())


def _reserve(root: Path, selector: RuleSelector, code: str | None, reserved: frozenset[str]) -> FileEdit:
    path = root / LEDGER
    before = path.read_bytes() if path.is_file() else None
    data = dict(as_table(parse_json(before.decode()))) if before is not None else {}
    family = selector.engine.value
    rules = dict(as_table(data.get("rules")))
    codes = dict(as_table(data.get("codes")))
    identifier = str(selector.rule_id)
    retired = list_field(data, "retired")
    retired_ids = {
        entry.get("id")
        for value in retired
        if (entry := as_table(value)).get("kind") in {family, "code"} and isinstance(entry.get("id"), str)
    }
    historical_id = f"@sarj/{identifier}" if selector.engine is RuleEngine.ESLINT else identifier
    if identifier in list_field(rules, family) or historical_id in retired_ids:
        msg = f"rule identity is already reserved: {selector}"
        raise ValueError(msg)
    rules[family] = sorted([*(_strings(list_field(rules, family))), identifier])
    if code is not None:
        if code in reserved or code in retired_ids or any(code in list_field(codes, key) for key in codes):
            msg = f"rule code is already reserved: {code}"
            raise ValueError(msg)
        codes[family] = sorted([*(_strings(list_field(codes, family))), code])
    data.update(rules=rules, codes=codes, retired=retired)
    return FileEdit(path, before, json.dumps(data, indent=2) + "\n")


def _strings(values: list[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            msg = "ledger rule identities must be strings"
            raise TypeError(msg)
        result.append(value)
    return result


def _registry_dictionary(tree: ast.Module) -> ast.Dict:
    dictionaries = [
        node.value.args[0]
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "MappingProxyType"
        and node.value.args
        and isinstance(node.value.args[0], ast.Dict)
    ]
    if len(dictionaries) != 1:
        msg = "native registry must contain one MappingProxyType dictionary"
        raise ValueError(msg)
    return dictionaries[0]


@dataclass(frozen=True, slots=True)
class _RegistryImport:
    module: str
    name: str


def live_codes(root: Path, engine: RuleEngine) -> frozenset[str]:
    if engine is RuleEngine.ESLINT:
        return frozenset()
    registry = registry_path(root, engine)
    codes: set[str] = _registered_codes(root, engine, registry) if registry.is_file() else set()
    legacy = root / "packages/standards/src/sarj_standards/libs/linting/textlint.py"
    if engine is RuleEngine.TEXT and legacy.is_file():
        codes.update(
            _literal_code(node)
            for node in ast.walk(ast.parse(legacy.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "RuleMeta"
        )
    return frozenset(codes)


def _registered_codes(root: Path, engine: RuleEngine, registry: Path) -> set[str]:
    tree = ast.parse(registry.read_text(encoding="utf-8"))
    dictionary = _registry_dictionary(tree)
    names = {node.id for node in dictionary.values if isinstance(node, ast.Name)}
    if len(names) != len(dictionary.values):
        msg = "live registry entries must reference distinct imported rule classes"
        raise ValueError(msg)
    prefix = (
        "sarj_standards.libs.linting.text_rules." if engine is RuleEngine.TEXT else f"sarj_{engine.value}_lint.rules."
    )
    bindings = _registry_imports(tree, prefix)
    if missing := names.difference(bindings):
        msg = "cannot resolve live registry bindings: " + ", ".join(sorted(missing))
        raise ValueError(msg)
    return {_import_code(root, engine, bindings[name]) for name in names}


def _registry_imports(tree: ast.Module, prefix: str) -> dict[str, _RegistryImport]:
    return {
        alias.asname or alias.name: _RegistryImport(node.module, alias.name)
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.module.startswith(prefix)
        for alias in node.names
    }


def _import_code(root: Path, engine: RuleEngine, binding: _RegistryImport) -> str:
    package = "standards" if engine is RuleEngine.TEXT else engine.value
    path = root / f"packages/{package}/src" / (binding.module.replace(".", "/") + ".py")
    source = ast.parse(path.read_text(encoding="utf-8"))
    declaration = next(
        (node for node in source.body if isinstance(node, ast.ClassDef) and node.name == binding.name), None
    )
    if declaration is None:
        msg = f"cannot resolve live rule declaration {binding.module}.{binding.name}"
        raise ValueError(msg)
    return _class_code(declaration, engine)


def _class_code(declaration: ast.ClassDef, engine: RuleEngine) -> str:
    name = "documentation" if engine is RuleEngine.TEXT else "code"
    for node in declaration.body:
        target = (
            node.target
            if isinstance(node, ast.AnnAssign)
            else node.targets[0]
            if isinstance(node, ast.Assign) and len(node.targets) == 1
            else None
        )
        if not isinstance(target, ast.Name) or target.id != name or not isinstance(node, (ast.AnnAssign, ast.Assign)):
            continue
        if engine is RuleEngine.TEXT and isinstance(node.value, ast.Call):
            return _literal_code(node.value)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    msg = f"live rule {declaration.name} must declare a literal rule code"
    raise ValueError(msg)


def _literal_code(call: ast.Call) -> str:
    value = next((field.value for field in call.keywords if field.arg == "code"), None)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    msg = "live text rule must declare a literal rule code"
    raise ValueError(msg)

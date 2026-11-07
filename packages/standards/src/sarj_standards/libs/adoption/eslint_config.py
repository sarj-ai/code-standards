from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Final

from pydantic import JsonValue

from sarj_standards.libs.rules import oxlint_ids

from . import manifest
from .configs import LEGACY_ESLINT_CONFIG_NAMES, LEGACY_ESLINT_PRESET_NAMES, LEGACY_ESLINT_SUPPRESSIONS


if TYPE_CHECKING:
    from collections.abc import Mapping


# Translates a repository's ESLint flat config into Oxlint entrypoint arguments. It reads a static subset
# of JavaScript, so no repository code runs during planning.

#: `createConfig` options oxlint.strict.mts still takes; the ESLint-only ones have no Oxlint meaning.
_PRESET_OPTIONS: Final = frozenset({"bunTestFiles", "playwrightTestFiles", "syntaxOnlyConfigFiles", "testFrameworks"})
#: Spreads of upstream ESLint config objects whose purpose Oxlint covers on its own.
_DROPPED_SPREADS: Final[Mapping[tuple[str, str], str]] = {
    ("typescript-eslint", "configs.disableTypeChecked"): (
        "Oxlint type-checks through tsrs, which gives files outside a tsconfig an inferred program"
    ),
}
_EVERY_FILE: Final = ("**/*",)
_ESCAPES: Final = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "0": "\0"}
_ESCAPE: Final = re.compile(r"\\(u\{[0-9A-Fa-f]+\}|u[0-9A-Fa-f]{4}|x[0-9A-Fa-f]{2}|\r\n|[\s\S])")
_TOKEN: Final = re.compile(
    r"""(?P<space>\s+)|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|(?P<string>"(?:\\[\s\S]|[^"\\\n])*"|'(?:\\[\s\S]|[^'\\\n])*')"""
    r"""|(?P<template>`(?:\\[\s\S]|[^`\\])*`)|(?P<number>\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)"""
    r"""|(?P<identifier>[A-Za-z_$][\w$]*)|(?P<punctuation>\.\.\.|=>|[^\s])"""
)


class UntranslatableError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Translation:
    options: JsonValue | None
    ignore_patterns: tuple[str, ...]
    overrides: tuple[JsonValue, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class _Binding:
    module: str
    name: str  # "default", "*" or the imported name


@dataclass(frozen=True, slots=True)
class _Strict:
    options: dict[str, JsonValue]


def translate(text: str) -> Translation:
    parser = _Parser(_tokens(text))
    entries = parser.program()
    if not entries or not isinstance(entries[0], _Strict) or any(isinstance(entry, _Strict) for entry in entries[1:]):
        msg = "it must spread the managed eslint.strict preset once, first"
        raise UntranslatableError(msg)
    notes = list(parser.notes)
    options = entries[0].options
    unsupported = sorted(options.keys() - _PRESET_OPTIONS)
    if unsupported:
        notes.append(f"dropped createConfig options Oxlint does not take: {', '.join(unsupported)}")
    supported = {key: value for key, value in options.items() if key in _PRESET_OPTIONS}
    ignores: list[str] = []
    overrides: list[JsonValue] = []
    for entry in entries[1:]:
        if isinstance(entry, dict):
            _translate_entry(entry, ignores, overrides, notes)
    return Translation(supported or None, tuple(ignores), tuple(overrides), tuple(notes))


def _translate_entry(
    entry: dict[str, JsonValue], ignores: list[str], overrides: list[JsonValue], notes: list[str]
) -> None:
    keys = entry.keys() - {"name"}
    if keys == {"ignores"}:
        patterns = _strings(entry["ignores"], "ignores")
        ignores.extend(pattern for pattern in patterns if not _names_eslint_file(pattern))
        return
    if not keys <= {"files", "rules", "settings"}:
        msg = f"entry keys {', '.join(sorted(keys - {'files', 'rules', 'settings'}))} have no Oxlint translation"
        raise UntranslatableError(msg)
    settings = entry.get("settings", {})
    if not isinstance(settings, dict):
        msg = "settings must be an object"
        raise UntranslatableError(msg)
    for plugin in settings:
        if not _plugin_dropped(plugin):
            msg = f"settings.{plugin} has no Oxlint translation"
            raise UntranslatableError(msg)
        notes.append(f"dropped settings.{plugin}: Oxlint does not run that plugin")
    rules = _translated_rules(entry.get("rules", {}), notes)
    if not rules:
        return
    files = _strings(entry["files"], "files") if "files" in entry else _EVERY_FILE
    overrides.append({"files": list(files), "rules": rules})


def _translated_rules(value: JsonValue, notes: list[str]) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        msg = "rules must be an object"
        raise UntranslatableError(msg)
    rule_map = oxlint_ids.bundled()
    translated: dict[str, JsonValue] = {}
    for rule, setting in value.items():
        targets = rule_map.rule_ids(rule)
        if not targets:
            if setting not in {"off", 0}:
                notes.append(f"dropped {rule}: Oxlint does not run it")
            continue
        if (
            rule not in rule_map.oxlint_ids
            and not rule.startswith("@sarj/")
            and rule not in manifest.managed_oxlint_rules()
        ):
            notes.append(f"kept {rule} as written: it is outside the managed rule set, so check Oxlint has it")
        translated.update(dict.fromkeys(targets, setting))
    return translated


def _plugin_dropped(plugin: str) -> bool:
    rules = [targets for rule, targets in oxlint_ids.bundled().oxlint_ids.items() if rule.startswith(f"{plugin}/")]
    return bool(rules) and not any(rules)


def _names_eslint_file(pattern: str) -> bool:
    name = pattern.rstrip("/").rsplit("/", 1)[-1]
    return name in {*LEGACY_ESLINT_CONFIG_NAMES, *LEGACY_ESLINT_PRESET_NAMES, LEGACY_ESLINT_SUPPRESSIONS}


def _strings(value: JsonValue, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"{label} must be a list of glob strings"
        raise UntranslatableError(msg)
    return tuple(item for item in value if isinstance(item, str))


def _tokens(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    for match in _TOKEN.finditer(text):
        kind = match.lastgroup or "punctuation"
        if kind not in {"space", "comment"}:
            tokens.append(_Token(kind, match.group(0)))
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.position = 0
        self.bindings: dict[str, _Binding] = {}
        self.strict: dict[str, _Strict] = {}
        self.notes: list[str] = []

    def program(self) -> list[_Strict | dict[str, JsonValue]]:
        entries: list[_Strict | dict[str, JsonValue]] | None = None
        while not self._done():
            if self._accept(";"):
                continue
            if self._accept("import"):
                self._import()
            elif self._peek() in {"const", "let"}:
                self.position += 1
                self._constant()
            elif self._accept("export"):
                self._expect("default")
                entries = self._export()
            else:
                msg = f"unsupported statement starting with `{self._peek()}`"
                raise UntranslatableError(msg)
        if entries is None:
            msg = "no `export default` config"
            raise UntranslatableError(msg)
        return entries

    def _import(self) -> None:
        if self._accept("type"):
            while not self._done() and self._peek() != "from":
                self.position += 1
            self._expect("from")
            self._string()
            self._import_attributes()
            return
        names: list[tuple[str, str]] = []
        if self._token().kind == "string":
            self._string()
            return
        if self._accept("*"):
            self._expect("as")
            names.append((self._identifier(), "*"))
        elif self._peek() != "{":
            names.append((self._identifier(), "default"))
            self._accept(",")
        if self._accept("{"):
            while not self._accept("}"):
                imported = self._identifier()
                names.append((self._identifier() if self._accept("as") else imported, imported))
                self._accept(",")
        self._expect("from")
        module = self._string()
        json_module = self._import_attributes()
        for local, imported in names:
            self.bindings[local] = _Binding("json" if json_module else module, imported)

    def _import_attributes(self) -> bool:
        if not (self._accept("with") or self._accept("assert")):
            return False
        self._literal()
        return True

    def _constant(self) -> None:
        name = self._identifier()
        if not self._accept("="):
            msg = f"constant `{name}` is not a plain createConfig(...) call"
            raise UntranslatableError(msg)
        self.strict[name] = self._strict_call()

    def _strict_call(self) -> _Strict:
        callee = self._identifier()
        binding = self.bindings.get(callee)
        if binding is None or binding.name != "createConfig" or not _is_preset(binding.module):
            msg = f"`{callee}(...)` is not the managed createConfig"
            raise UntranslatableError(msg)
        self._expect("(")
        options: JsonValue = {} if self._peek() == ")" else self._literal()
        self._expect(")")
        if not isinstance(options, dict):
            msg = "createConfig options must be an object"
            raise UntranslatableError(msg)
        return _Strict(options)

    def _export(self) -> list[_Strict | dict[str, JsonValue]]:
        if self._accept("["):
            entries = self._entries("]")
        elif self._token(1).value not in {"(", "."}:
            # `export default strict;` exports the preset itself.
            spread = self._spread()
            entries: list[_Strict | dict[str, JsonValue]] = [] if spread is None else [spread]
        else:
            callee = self._identifier()
            if self._accept("."):
                callee = f"{callee}.{self._identifier()}"
            if callee not in {"defineConfig", "tseslint.config"}:
                msg = f"`export default {callee}(...)` is not a flat config array"
                raise UntranslatableError(msg)
            self._expect("(")
            if self._accept("["):
                entries = self._entries("]")
                self._accept(",")
                self._expect(")")
            else:
                entries = self._entries(")")
        if self._accept("satisfies") or self._accept("as"):
            while not self._done() and self._peek() != ";":
                self.position += 1
        return entries

    def _entries(self, closing: str) -> list[_Strict | dict[str, JsonValue]]:
        entries: list[_Strict | dict[str, JsonValue]] = []
        while not self._accept(closing):
            if self._accept("..."):
                entry = self._spread()
            elif self._peek() == "{":
                entry = self._entry()
            else:
                msg = f"unsupported config entry `{self._peek()}`"
                raise UntranslatableError(msg)
            if entry is not None:
                entries.append(entry)
            if not self._accept(","):
                self._expect(closing)
                break
        return entries

    def _spread(self) -> _Strict | None:
        start = self.position
        name = self._identifier()
        if self._peek() == "(":
            self.position = start
            return self._strict_call()
        if name in self.strict:
            return self.strict[name]
        binding = self.bindings.get(name)
        if binding is not None and binding.name == "default" and _is_preset(binding.module):
            return _Strict({})
        self._dropped_spread(name)
        return None

    def _dropped_spread(self, name: str) -> None:
        path: list[str] = []
        while self._accept("."):
            path.append(self._identifier())
        binding = self.bindings.get(name)
        reason = None if binding is None else _DROPPED_SPREADS.get((binding.module, ".".join(path)))
        if reason is None:
            msg = f"spread of `{name}{''.join('.' + part for part in path)}`"
            raise UntranslatableError(msg)
        self.notes.append(f"dropped {binding.module if binding else name} {'.'.join(path)}: {reason}")

    def _entry(self) -> dict[str, JsonValue]:
        # A spread upstream config is dropped; the entry's own `files` and `rules` still translate.
        self._expect("{")
        entry: dict[str, JsonValue] = {}
        while not self._accept("}"):
            if self._accept("..."):
                self._dropped_spread(self._identifier())
            else:
                key = self._key()
                self._expect(":")
                entry[key] = self._literal()
            if not self._accept(","):
                self._expect("}")
                break
        return entry

    def _literal(self) -> JsonValue:
        token = self._token()
        if token.kind == "string":
            return self._string()
        if token.kind == "template":
            self.position += 1
            return _template(token.value, raw=False)
        if token.kind == "number":
            self.position += 1
            return _number(token.value)
        if token.value == "-" and self._token(1).kind == "number":
            self.position += 2
            return -_number(self._token(-1).value)
        if token.value in {"true", "false", "null"}:
            self.position += 1
            return {"true": True, "false": False, "null": None}[token.value]
        if token.value == "String" and self._token(1).value == "." and self._token(2).value == "raw":
            return self._raw_template()
        if self._accept("["):
            return self._array()
        if self._accept("{"):
            return self._object()
        msg = f"`{token.value}` is not a literal value"
        raise UntranslatableError(msg)

    def _raw_template(self) -> str:
        self.position += 3
        template = self._token()
        if template.kind != "template":
            msg = "String.raw must tag a template"
            raise UntranslatableError(msg)
        self.position += 1
        return _template(template.value, raw=True)

    def _array(self) -> list[JsonValue]:
        items: list[JsonValue] = []
        while not self._accept("]"):
            items.append(self._literal())
            if not self._accept(","):
                self._expect("]")
                break
        return items

    def _object(self) -> dict[str, JsonValue]:
        members: dict[str, JsonValue] = {}
        while not self._accept("}"):
            key = self._key()
            self._expect(":")
            members[key] = self._literal()
            if not self._accept(","):
                self._expect("}")
                break
        return members

    def _key(self) -> str:
        token = self._token()
        if token.kind == "string":
            return self._string()
        if token.kind in {"identifier", "number"}:
            self.position += 1
            return token.value
        msg = f"unsupported object key `{token.value}`"
        raise UntranslatableError(msg)

    def _string(self) -> str:
        token = self._token()
        if token.kind != "string":
            msg = f"expected a string, found `{token.value}`"
            raise UntranslatableError(msg)
        self.position += 1
        return _unescape(token.value[1:-1])

    def _identifier(self) -> str:
        token = self._token()
        if token.kind != "identifier":
            msg = f"expected a name, found `{token.value}`"
            raise UntranslatableError(msg)
        self.position += 1
        return token.value

    def _token(self, offset: int = 0) -> _Token:
        index = self.position + offset
        return self.tokens[index] if 0 <= index < len(self.tokens) else _Token("end", "<end>")

    def _peek(self) -> str:
        return self._token().value

    def _done(self) -> bool:
        return self.position >= len(self.tokens)

    def _accept(self, value: str) -> bool:
        if self._peek() == value and self._token().kind != "string":
            self.position += 1
            return True
        return False

    def _expect(self, value: str) -> None:
        if not self._accept(value):
            msg = f"expected `{value}`, found `{self._peek()}`"
            raise UntranslatableError(msg)


def _is_preset(module: str) -> bool:
    return module.removeprefix("./").removesuffix(".js") in {"eslint.strict", "eslint.strict.mjs", "eslint.strict.ts"}


def _template(token: str, *, raw: bool) -> str:
    body = token[1:-1]
    if "${" in body:
        msg = "template literals with substitutions"
        raise UntranslatableError(msg)
    return body if raw else _unescape(body)


def _number(value: str) -> int | float:
    cleaned = value.replace("_", "")
    return float(cleaned) if any(mark in cleaned for mark in ".eE") else int(cleaned)


def _unescape(body: str) -> str:
    def replace(match: re.Match[str]) -> str:
        escape = match.group(1)
        if escape.startswith("u{"):
            return chr(int(escape[2:-1], 16))
        if escape.startswith(("u", "x")) and len(escape) > 1:
            return chr(int(escape[1:], 16))
        if escape in {"\n", "\r\n", "\r"}:
            return ""
        return _ESCAPES.get(escape, escape)

    return _ESCAPE.sub(replace, body)

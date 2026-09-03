import ast
from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import RuleExample, Severity
from sarj_python_lint.rules.prefer_fstring_over_concat import PreferFstringOverConcat


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_PATH = Path("src/render.py")


def _check(source: str, path: Path = _PATH) -> list[Diagnostic]:
    return PreferFstringOverConcat().check(path, textwrap.dedent(source))


def _typed(source: str) -> str:
    tree = ast.parse(source)
    names = sorted(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    )
    declarations = "; ".join(f"{name}: str" for name in names)
    return f"{declarations}\n{source}" if declarations else source


_PUBLIC_EXAMPLES = PreferFstringOverConcat.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferFstringOverConcat().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        'def greeting(name: str) -> str:\n    return "Hello, " + name + "!"\n',
        'def label(user_id: str) -> str:\n    return "User " + user_id + " failed"\n',
        'def message():\n    name = "known"\n    return "Welcome, " + name\n',
        'def label(value: str) -> str:\n    return "Value: " + value.upper()\n',
        'def label(value: str) -> str:\n    return "Value: " + value[:3]\n',
    ],
)
def test_short_human_readable_interpolation_warns(source: str) -> None:
    [diagnostic] = _check(source)
    assert diagnostic.code == "SARJ068"
    assert diagnostic.severity is Severity.WARNING
    assert "human-readable" in diagnostic.message


def test_explicit_str_guidance_preserves_semantics() -> None:
    [diagnostic] = _check('def label(value):\n    return "Value: " + str(value)\n')
    assert "{value!s}" in diagnostic.message
    assert "disappears" not in diagnostic.message


def test_explicit_repr_guidance_preserves_semantics() -> None:
    [diagnostic] = _check('def label(value):\n    return "Value: " + repr(value)\n')
    assert "{value!r}" in diagnostic.message


def test_plain_interpolation_message_does_not_mention_string_coercion() -> None:
    [diagnostic] = _check('def label(value: str) -> str:\n    return "Value: " + value\n')
    assert "str(" not in diagnostic.message
    assert "join" not in diagnostic.message


@pytest.mark.parametrize(
    "source",
    [
        'def route(base_url: str) -> str:\n    return base_url + "/v1"\n',
        'def path(root: str, child: str) -> str:\n    return root + "/" + child\n',
        'def regex(prefix: str) -> str:\n    return r"^" + prefix + r"\\d+$"\n',
        'def like(value: str) -> str:\n    return "%" + value + "%"\n',
        'def quote(value: str) -> str:\n    return "\'" + value\n',
        'def suffix(value: str) -> str:\n    return value + "..."\n',
        'def ansi(code: str) -> str:\n    return "\\x1b[" + code\n',
        'def protocol(raw: str) -> str:\n    return "+" + raw\n',
        'def identity(prefix: str) -> str:\n    return prefix + "!pQw9"\n',
        'def module_name(modname: str) -> str:\n    return "_pytest." + modname\n',
        'def generated(index: str) -> str:\n    return "@py_assert" + index\n',
        'def attribute(name: str) -> str:\n    return "st_" + name\n',
    ],
)
def test_protocol_path_and_structural_fragments_are_clean(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'import re\ndef pattern(prefix: str):\n    return re.compile(r"^" + prefix + r"\\d+$")\n',
        'import re\ndef found(token: str, text: str):\n    return re.search(r"\\b" + token + r"\\b", text)\n',
        'from re import compile as rc\ndef pattern(prefix: str):\n    return rc("prefix-" + prefix)\n',
    ],
)
def test_regex_api_arguments_are_clean(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'def query(table: str):\n    return "select * from " + table\n',
        'def query(tail: str):\n    return "SELECT * FROM users " + tail\n',
        'def query(table: str):\n    return "WITH rows AS (SELECT 1) SELECT * FROM " + table\n',
    ],
)
def test_probable_sql_fragments_are_clean(source: str) -> None:
    assert _check(source) == []


def test_prose_with_sql_word_still_warns() -> None:
    assert len(_check('def note(source: str):\n    return "Selected from " + source + " today"\n')) == 1
    assert len(_check('def note(place: str):\n    return "Where " + place\n')) == 1
    assert len(_check('def note(value: str):\n    return "Set " + value\n')) == 1


def test_long_literal_template_is_clean() -> None:
    literal = "Explain this OCR field in detail. " * 8
    assert _check(f"def prompt(value: str):\n    return {literal!r} + value\n") == []


def test_literal_budget_boundary() -> None:
    assert len(_check(f'def prompt(value: str):\n    return {"a" * 160!r} + value\n')) == 1
    assert _check(f'def prompt(value: str):\n    return {"a" * 161!r} + value\n') == []


def test_unrelated_inline_comment_does_not_suppress_warning() -> None:
    source = """
        def greeting(name: str) -> str:
            return "Hello, " + name  # displayed in the account menu
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'def label(str, value):\n    return "Value: " + str(value)\n',
        'def label(repr, value):\n    return "Value: " + repr(value)\n',
        'class str: pass\ndef label(value: str):\n    return "Value: " + value\n',
        'def str(value):\n    return value\ndef label(item):\n    return "Value: " + str(item)\n',
        'json = serializer\ndef label(item):\n    return "Value: " + json.dumps(item)\n',
        'def label(item):\n    return "Value: " + str(item)\nstr = custom\n',
        'import json\ndef label(item):\n    return "Value: " + json.dumps(item)\njson = serializer\n',
        'import custom as builtins\ndef label(value: builtins.str):\n    return "Value: " + value\n',
        'from custom import str\ndef label(value):\n    return "Value: " + str(value)\n',
        'import custom as str\ndef label(value):\n    return "Value: " + str(value)\n',
        'from custom import Annotated\ndef label(value: Annotated[str, "x"]):\n    return "Value: " + value\n',
    ],
)
def test_shadowed_string_producers_are_clean(source: str) -> None:
    assert _check(source) == []


def test_imported_json_dumps_is_known_string() -> None:
    assert len(_check('import json\ndef label(item):\n    return "Payload: " + json.dumps(item)\n')) == 1


@pytest.mark.parametrize(
    "source",
    [
        'def label(flag: bool):\n    value: str = "ok"\n    if flag:\n        value = object()\n    return "Value: " + value\n',
        'def label(items: list[object]):\n    value: str = "ok"\n    for value in items:\n        pass\n    return "Value: " + value\n',
        'value: str = "ok"\nvalue = load()\nlabel = "Value: " + value\n',
        'def label():\n    value: str = "ok"\n    import module as value\n    return "Value: " + value\n',
        'def label():\n    value: str = "ok"\n    def value():\n        return object()\n    return "Value: " + value\n',
        'def label():\n    value: str = "ok"\n    (value := load())\n    return "Value: " + value\n',
    ],
)
def test_unknown_rebinding_clears_string_evidence(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'def emit(logger, user_id: str):\n    logger.info("User " + user_id)',
        'def emit(logging, user_id: str):\n    logging.warning("User " + user_id)',
        'def emit(self, user_id: str):\n    self.logger.error("User " + user_id)',
    ],
)
def test_logging_concatenation_is_left_to_logging_rules(source: str) -> None:
    assert _check(_typed(source)) == []


@pytest.mark.parametrize(
    "source",
    [
        'value = "x" + unknown',
        "value = left + right",
        'value = "x" + b"bytes"',
        'value = "x" + lazy("translated")',
        'value = "x" + literal(column)',
        'value = "x" + (name if flag else other)',
        'value = "x" + "y"',
        'value = f"{name + \'!\'}"',
    ],
)
def test_ambiguous_or_owned_shapes_are_clean(source: str) -> None:
    assert _check(source) == []


def test_multiline_comment_does_not_suppress_warning() -> None:
    source = """
        def label(value: str):
            return (
                "Value: "  # durable protocol prefix
                + value
            )
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'STYLE = "bold " + COLOR\n',
        'class Lexer:\n    TOKEN = r"[a-z]" + SUFFIX\n',
        'ANSI = "\\x1b[" + CODE\n',
    ],
)
def test_module_and_class_declarative_fragments_are_clean(source: str) -> None:
    assert _check(source) == []


def test_nested_url_receiver_chain_is_clean() -> None:
    source = 'def health(url: str):\n    return url.replace("/v1", "").rstrip("/") + "/health"\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [Path("src/generated/client.py"), Path("generated.py")],
    ids=["generated-directory", "generated-header"],
)
def test_generated_files_are_clean(path: Path) -> None:
    source = '# @generated\ndef label(value: str):\n    return "Value: " + value\n'
    assert _check(source, path) == []


@pytest.mark.parametrize(
    "path",
    [Path("tests/test_label.py"), Path("scripts/label.py"), Path(".agents/skills/x/a.py")],
    ids=["test", "script", "skill"],
)
def test_semantic_rule_is_not_path_routed(path: Path) -> None:
    source = 'def label(value: str):\n    return "Value: " + value\n'
    assert len(_check(source, path)) == 1


@pytest.mark.parametrize("source", ["", "# comment\n", "def broken(:\n"])
def test_empty_or_invalid_source_is_clean(source: str) -> None:
    assert _check(source) == []


def test_long_chain_does_not_exhaust_the_stack() -> None:
    source = 'value = "a" + ' + " + ".join(f"name_{index}" for index in range(5_000))
    assert _check(source) == []

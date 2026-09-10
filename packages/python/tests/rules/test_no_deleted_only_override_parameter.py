from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_deleted_only_override_parameter import NoDeletedOnlyOverrideParameter


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/handler.py") -> list[Diagnostic]:
    return NoDeletedOnlyOverrideParameter().check(Path(path), textwrap.dedent(source))


_PUBLIC_EXAMPLES = NoDeletedOnlyOverrideParameter.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


@pytest.mark.parametrize(
    ("import_line", "decorator"),
    [
        ("from typing import override", "override"),
        ("from typing_extensions import override as implements", "implements"),
        ("import typing", "typing.override"),
        ("import typing_extensions as tx", "tx.override"),
    ],
)
def test_flags_deleted_only_parameter_for_proven_override(import_line: str, decorator: str) -> None:
    diagnostics = _check(
        f"""
        {import_line}

        class Handler(BaseHandler):
            @{decorator}
            async def handle(self, request: Request, /, *, context: Context) -> None:
                del request, context
                await ready()
        """
    )

    assert [(item.line, item.code, item.severity) for item in diagnostics] == [
        (7, "SARJ442", Severity.WARNING),
        (7, "SARJ442", Severity.WARNING),
    ]
    assert diagnostics[0].col != diagnostics[1].col


def test_reports_each_parameter_once_across_multiple_delete_paths() -> None:
    diagnostics = _check(
        """
        from typing import override

        class Handler(BaseHandler):
            @override
            def handle(self, request: Request, enabled: bool) -> None:
                if enabled:
                    del request
                else:
                    del request
        """
    )
    assert len(diagnostics) == 1


def test_flags_parenthesized_delete_without_whitespace() -> None:
    diagnostics = _check(
        """
        from typing import override

        class Handler(Base):
            @override
            def handle(self, request: object) -> None:
                del(request)
        """
    )

    assert [(diagnostic.line, diagnostic.code) for diagnostic in diagnostics] == [(7, "SARJ442")]


@pytest.mark.parametrize(
    "body",
    [
        "consume(request)",
        "consume(request)\ndel request",
        "del request\nconsume(request)",
        "request = replacement\ndel request",
        "del request.value",
        "del request['value']",
        "def nested():\n    return request\ndel request",
        "def nested(request):\n    return request\ndel request",
    ],
)
def test_allows_any_other_same_spelling_occurrence(body: str) -> None:
    indented = textwrap.indent(body, " " * 8)
    assert (
        _check(
            "from typing import override\n\n"
            "class Handler(BaseHandler):\n"
            "    @override\n"
            "    def handle(self, request: Request) -> None:\n"
            f"{indented}\n"
        )
        == []
    )


def test_allows_non_override_and_unproven_decorators() -> None:
    assert (
        _check(
            """
            def override(function):
                return function

            class Handler(BaseHandler):
                @override
                def handle(self, request: Request) -> None:
                    del request
            """
        )
        == []
    )


def test_allows_shadowed_imported_decorator() -> None:
    assert (
        _check(
            """
            from typing import override
            override = custom_override

            class Handler(BaseHandler):
                @override
                def handle(self, request: Request) -> None:
                    del request
            """
        )
        == []
    )


def test_exact_suppression_is_respected() -> None:
    assert (
        _check(
            """
            from typing import override

            class Handler(BaseHandler):
                @override
                async def handle(self, request: Request) -> None:
                    del request  # sarj-noqa: SARJ442 -- release the request before the long-lived await
                    await wait_forever()
            """
        )
        == []
    )


@pytest.mark.parametrize("path", ["generated/client.py", "vendor/handler.py"])
def test_generated_files_are_excluded(path: str) -> None:
    assert (
        _check(
            "from typing import override\n"
            "class Handler(Base):\n"
            "    @override\n"
            "    def handle(self, request):\n"
            "        del request\n",
            path,
        )
        == []
    )


def test_malformed_source_is_ignored() -> None:
    assert _check("from typing import override\nclass Handler(") == []

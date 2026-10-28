from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.no_loguru_exc_info import NoLoguruExcInfo
from sarj_python_lint.rules.no_loguru_printf_format import NoLoguruPrintfFormat


PROBLEM = RuleProblem(
    key="no-loguru-printf-format",
    summary="Loguru leaves printf placeholders unchanged and ignores positional formatting values.",
    harm="Failure diagnostics lose request, provider and numeric values needed to investigate the operation.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=('from loguru import logger\nlogger.error("Request %s failed", request_id)\n',),
    good_examples=('from loguru import logger\nlogger.error("Request {} failed", request_id)\n',),
    exclusions=("Standard logging, unknown receivers, brace templates, dynamic messages and expanded arguments.",),
    autofix=AutofixPolicy.NONE,
)


def _case(case_id: str, source: str, *, matches: bool = False, path: str = "app/service.py") -> EvaluationCase:
    return EvaluationCase(
        case_id,
        Language.PYTHON,
        source,
        ExpectedOutcome.MATCH if matches else ExpectedOutcome.NO_MATCH,
        path=PurePosixPath(path),
    )


CASES = (
    *(
        _case(
            f"method-{method}",
            f'from loguru import logger\nlogger.{method}("Request %s failed", request_id)\n',
            matches=True,
        )
        for method in ("trace", "debug", "info", "success", "warning", "error", "critical", "exception")
    ),
    _case("custom-level", 'from loguru import logger\nlogger.log("NOTICE", "value=%s", value)\n', matches=True),
    _case("import-alias", 'from loguru import logger as events\nevents.error("value=%r", value)\n', matches=True),
    _case("module", 'import loguru\nloguru.logger.error("value=%s", value)\n', matches=True),
    _case("module-alias", 'import loguru as events\nevents.logger.info("value=%s", value)\n', matches=True),
    _case("bind", 'from loguru import logger\nlogger.bind(request_id=key).error("value=%s", value)\n', matches=True),
    _case(
        "opt-with-exception",
        'from loguru import logger\nlogger.opt(exception=True).error("value=%s", value)\n',
        matches=True,
    ),
    _case(
        "combined-chain",
        'from loguru import logger\nlogger.bind(component="worker").opt(depth=0).warning("value=%s", value)\n',
        matches=True,
    ),
    _case(
        "lazy-and-record-options",
        'from loguru import logger\nlogger.opt(lazy=True, record=True).info("value=%s", lambda: value)\n',
        matches=True,
    ),
    _case("precision", 'from loguru import logger\nlogger.info("ratio=%.2f count=%d", ratio, count)\n', matches=True),
    _case("width-and-flags", 'from loguru import logger\nlogger.info("%-12.2f %+08d", ratio, count)\n', matches=True),
    _case("zero-flags-and-width", 'from loguru import logger\nlogger.info("%00012.04f", value)\n', matches=True),
    _case("long-malformed-zero-width", 'from loguru import logger\nlogger.info("%' + "0" * 10_000 + 'q", value)\n'),
    _case("dynamic-width", 'from loguru import logger\nlogger.info("%*.*f", width, precision, ratio)\n', matches=True),
    _case("mapping-conversion", 'from loguru import logger\nlogger.info("%(name)s", {"name": value})\n', matches=True),
    _case("ascii-conversion", 'from loguru import logger\nlogger.info("%a", value)\n', matches=True),
    _case("escaped-braces", 'from loguru import logger\nlogger.info("{{value=%s}}", value)\n', matches=True),
    _case(
        "escaped-percent-and-value", 'from loguru import logger\nlogger.info("progress=%d%%", value)\n', matches=True
    ),
    _case(
        "tests-checked",
        'from loguru import logger\nlogger.info("%s", value)\n',
        matches=True,
        path="tests/test_service.py",
    ),
    _case("stdlib", 'import logging\nlogging.error("value=%s", value)\n'),
    _case("stdlib-instance", 'import logging\nlogger = logging.getLogger(__name__)\nlogger.error("%s", value)\n'),
    _case("custom-import", 'from app.events import logger\nlogger.error("%s", value)\n'),
    _case("unknown-receiver", 'logger.error("%s", value)\n'),
    _case(
        "stored-alias",
        'from loguru import logger\nevents = logger.bind(component="worker")\nevents.error("%s", value)\n',
    ),
    _case("self-logger", 'from loguru import logger\nself.logger.error("%s", value)\n'),
    _case("brace-formatting", 'from loguru import logger\nlogger.error("value={}", value)\n'),
    _case("named-brace-field", 'from loguru import logger\nlogger.error("%s {name}", value, name=name)\n'),
    _case("malformed-braces", 'from loguru import logger\nlogger.error("value={ %s", value)\n'),
    _case("escaped-percent", 'from loguru import logger\nlogger.error("%%s", value)\n'),
    _case("literal-percent", 'from loguru import logger\nlogger.error("100%% complete", value)\n'),
    _case("unsupported-percent-conversion", 'from loguru import logger\nlogger.error("%q", value)\n'),
    _case("unterminated-percent", 'from loguru import logger\nlogger.error("value=%s then %", value)\n'),
    _case("malformed-mapping", 'from loguru import logger\nlogger.error("%(name", value)\n'),
    _case("no-positional-value", 'from loguru import logger\nlogger.error("literal %s")\n'),
    _case("keyword-extra", 'from loguru import logger\nlogger.error("literal %s", value=value)\n'),
    _case("log-without-formatting-value", 'from loguru import logger\nlogger.log("ERROR", "%s")\n'),
    _case("dynamic-message", "from loguru import logger\nlogger.error(template, value)\n"),
    _case("fstring-message", 'from loguru import logger\nlogger.error(f"{prefix} %s", value)\n'),
    _case("starred-values", 'from loguru import logger\nlogger.error("%s", *values)\n'),
    _case("expanded-fields", 'from loguru import logger\nlogger.error("%s", value, **fields)\n'),
    _case("expanded-chain", 'from loguru import logger\nlogger.bind(**fields).error("%s", value)\n'),
    _case("custom-patch-chain", 'from loguru import logger\nlogger.patch(patcher).error("%s", value)\n'),
    _case("rebound", 'from loguru import logger\nlogger = other\nlogger.error("%s", value)\n'),
    _case("parameter-shadow", 'from loguru import logger\ndef report(logger):\n    logger.error("%s", value)\n'),
    _case("local-import", 'def report():\n    from loguru import logger\n    logger.error("%s", value)\n'),
    _case(
        "nested-custom-import",
        'from loguru import logger\ndef report():\n    from app import logger\n    logger.error("%s", value)\n',
    ),
    _case("relative-import", 'from loguru import logger\nfrom .events import logger\nlogger.error("%s", value)\n'),
    _case("wildcard-import", 'from loguru import logger\nfrom app import *\nlogger.error("%s", value)\n'),
    _case("method-override", 'from loguru import logger\nlogger.error = custom\nlogger.error("%s", value)\n'),
    _case("method-deletion", 'from loguru import logger\ndel logger.error\nlogger.error("%s", value)\n'),
    _case("method-setattr", 'from loguru import logger\nsetattr(logger, "error", custom)\nlogger.error("%s", value)\n'),
    _case("module-logger-replaced", 'import loguru\nloguru.logger = custom\nloguru.logger.error("%s", value)\n'),
    _case(
        "other-import-alias-mutated",
        'from loguru import logger as events\nfrom loguru import logger\nevents.error = custom\nlogger.error("%s", value)\n',
    ),
    _case(
        "module-alias-method-mutated",
        'import loguru\nfrom loguru import logger\nloguru.logger.error = custom\nlogger.error("%s", value)\n',
    ),
    _case(
        "other-import-alias-escaped",
        'from loguru import logger as events\nfrom loguru import logger\nconfigure(events)\nlogger.error("%s", value)\n',
    ),
    _case("escaped-logger", 'from loguru import logger\nconfigure(logger)\nlogger.error("%s", value)\n'),
    _case("namespace-mutation", 'from loguru import logger\nglobals().update(overrides)\nlogger.error("%s", value)\n'),
    _case(
        "suppression",
        'from loguru import logger\nlogger.error("%s", value)  # sarj-noqa: SARJ509 -- Reviewed literal diagnostic.\n',
    ),
    _case("generated", '# @generated\nfrom loguru import logger\nlogger.error("%s", value)\n'),
    _case("malformed-source", 'from loguru import logger\nlogger.error("%s",\n'),
    _case("comment-and-string", '# logger.error("%s", value)\nsource = "loguru %s"\n'),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = NoLoguruPrintfFormat().check(Path(case.path), case.source)
    assert len(diagnostics) == int(case.expected is ExpectedOutcome.MATCH)
    for diagnostic in diagnostics:
        assert diagnostic.code == "SARJ509"
        assert diagnostic.severity is Severity.ERROR
        assert "brace fields" in diagnostic.message


def test_repeated_placeholders_produce_one_diagnostic() -> None:
    source = 'from loguru import logger\nlogger.error("first=%s second=%r count=%d", first, second, count)\n'
    diagnostics = NoLoguruPrintfFormat().check(Path("app/service.py"), source)
    assert [(item.code, item.line, item.col) for item in diagnostics] == [("SARJ509", 2, 1)]


def test_format_and_exception_arguments_are_independent_defects() -> None:
    source = 'from loguru import logger\nlogger.error("value=%s", value, exc_info=True)\n'
    path = Path("app/service.py")
    diagnostics = NoLoguruPrintfFormat().check(path, source) + NoLoguruExcInfo().check(path, source)
    assert sorted(item.code for item in diagnostics) == ["SARJ508", "SARJ509"]


def test_explicit_exception_capture_only_resolves_the_exception_defect() -> None:
    source = 'from loguru import logger\nlogger.exception("value=%s", value, exc_info=True)\n'
    path = Path("app/service.py")
    assert NoLoguruExcInfo().check(path, source) == []
    assert len(NoLoguruPrintfFormat().check(path, source)) == 1


def test_rule_is_registered_once(tmp_path: Path) -> None:
    source = 'from loguru import logger\nlogger.error("value=%s", "marker")\n'
    path = tmp_path / "service.py"
    path.write_text(source, encoding="utf-8")
    diagnostics = analyze([NoLoguruPrintfFormat.id], [path])
    assert [(item.code, item.line) for item in diagnostics] == [("SARJ509", 2)]


def test_public_examples() -> None:
    verify_native_rule(NoLoguruPrintfFormat, analyze)


@pytest.mark.parametrize("escape", [r"\u0025", r"\x25"])
def test_decoded_percent_conversions_preserve_loguru_format_diagnostics(escape: str) -> None:
    source = (
        "from loguru import logger\n"
        f'logger.error("Request {escape}s failed with status {escape}d", "request-marker", 503)\n'
    )
    diagnostics = NoLoguruPrintfFormat().check(Path("app/service.py"), source)
    assert [(item.code, item.line) for item in diagnostics] == [("SARJ509", 2)]


def test_decoded_literal_percent_signs_do_not_create_a_conversion() -> None:
    source = 'from loguru import logger\nlogger.info("Progress \\u0025\\u0025", value)\n'
    assert NoLoguruPrintfFormat().check(Path("app/service.py"), source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('from ｌｏｇｕｒｕ import logger\nlogger.error("value %s", value)\n', 1),
        ('import ｌｏｇｕｒｕ as logs\nlogs.logger.error("value %s", value)\n', 1),
        ('from unrelated import logger\nlogger.error("value %s", value)\n', 0),
        ('source = "from ｌｏｇｕｒｕ import logger"\n', 0),
    ],
)
def test_native_normalized_module_identity_survives_the_prefilter(source: str, expected: int) -> None:
    diagnostics = NoLoguruPrintfFormat().check(Path("app/service.py"), source)
    assert len(diagnostics) == expected
    assert all(item.code == "SARJ509" and item.severity is Severity.ERROR for item in diagnostics)

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.no_loguru_exc_info import NoLoguruExcInfo


PROBLEM = RuleProblem(
    key="no-loguru-exc-info",
    summary="Loguru stores exc_info=True as a field instead of attaching the exception.",
    harm="Failure logs appear to request a traceback but lose the exception and its stack.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=('from loguru import logger\nlogger.warning("failed", exc_info=True)\n',),
    good_examples=('from loguru import logger\nlogger.opt(exception=True).warning("failed")\n',),
    exclusions=("Standard logging, unknown receivers, explicit exception capture, intentional template fields.",),
    autofix=AutofixPolicy.NONE,
)


def _case(case_id: str, source: str, *, matches: bool = False) -> EvaluationCase:
    return EvaluationCase(
        case_id,
        Language.PYTHON,
        source,
        ExpectedOutcome.MATCH if matches else ExpectedOutcome.NO_MATCH,
        path=PurePosixPath("app/service.py"),
    )


CASES = (
    *(
        _case(
            f"method-{method}",
            f'from loguru import logger\nlogger.{method}("failed", exc_info=True)\n',
            matches=True,
        )
        for method in ("trace", "debug", "info", "success", "warning", "error", "critical")
    ),
    _case("log-method", 'from loguru import logger\nlogger.log("ERROR", "failed", exc_info=True)\n', matches=True),
    _case("alias", 'from loguru import logger as events\nevents.warning("failed", exc_info=True)\n', matches=True),
    _case("module", 'import loguru\nloguru.logger.warning("failed", exc_info=True)\n', matches=True),
    _case("module-alias", 'import loguru as events\nevents.logger.warning("failed", exc_info=True)\n', matches=True),
    _case(
        "bind",
        'from loguru import logger\nlogger.bind(request_id="example").warning("failed", exc_info=True)\n',
        matches=True,
    ),
    _case("opt", 'from loguru import logger\nlogger.opt(depth=0).warning("failed", exc_info=True)\n', matches=True),
    _case(
        "opt-false",
        'from loguru import logger\nlogger.opt(exception=False).warning("failed", exc_info=True)\n',
        matches=True,
    ),
    _case(
        "opt-reset",
        'from loguru import logger\nlogger.opt(exception=True).opt(depth=0).warning("failed", exc_info=True)\n',
        matches=True,
    ),
    _case(
        "keyword-message", 'from loguru import logger\nlogger.warning(message="failed", exc_info=True)\n', matches=True
    ),
    _case("stdlib", 'import logging\nlogging.warning("failed", exc_info=True)\n'),
    _case("custom", 'from app.events import logger\nlogger.warning("failed", exc_info=True)\n'),
    _case("unproven", 'logger.warning("failed", exc_info=True)\n'),
    _case("self-logger", 'from loguru import logger\nself.logger.warning("failed", exc_info=True)\n'),
    _case("false", 'from loguru import logger\nlogger.warning("failed", exc_info=False)\n'),
    _case("dynamic", 'from loguru import logger\nlogger.warning("failed", exc_info=enabled)\n'),
    _case("exception-method", 'from loguru import logger\nlogger.exception("failed", exc_info=True)\n'),
    _case(
        "explicit-exception", 'from loguru import logger\nlogger.opt(exception=True).warning("failed", exc_info=True)\n'
    ),
    _case(
        "explicit-error", 'from loguru import logger\nlogger.opt(exception=error).warning("failed", exc_info=True)\n'
    ),
    _case(
        "bound-exception",
        'from loguru import logger\nlogger.opt(exception=True).bind(request_id="example").warning("failed", exc_info=True)\n',
    ),
    _case("opt-unknown", 'from loguru import logger\nlogger.opt(**options).warning("failed", exc_info=True)\n'),
    _case("field", 'from loguru import logger\nlogger.warning("field={exc_info}", exc_info=True)\n'),
    _case("nested-field", 'from loguru import logger\nlogger.warning("{value:{exc_info}}", value=1, exc_info=True)\n'),
    _case(
        "record-field",
        'from loguru import logger\nlogger.opt(record=True).warning("{record[extra][exc_info]}", exc_info=True)\n',
    ),
    _case("dynamic-message", "from loguru import logger\nlogger.warning(template, exc_info=True)\n"),
    _case("malformed-template", 'from loguru import logger\nlogger.warning("{", exc_info=True)\n'),
    _case("unknown-chain", 'from loguru import logger\nlogger.patch(patcher).warning("failed", exc_info=True)\n'),
    _case("rebound", 'from loguru import logger\nlogger = other\nlogger.warning("failed", exc_info=True)\n'),
    _case(
        "parameter-shadow", 'from loguru import logger\ndef run(logger):\n    logger.warning("failed", exc_info=True)\n'
    ),
    _case(
        "nested-import",
        'from loguru import logger\ndef run():\n    from app import logger\n    logger.warning("failed", exc_info=True)\n',
    ),
    _case(
        "relative-import",
        'from loguru import logger\nfrom .events import logger\nlogger.warning("failed", exc_info=True)\n',
    ),
    _case(
        "wildcard-import",
        'from loguru import logger\nfrom app.events import *\nlogger.warning("failed", exc_info=True)\n',
    ),
    _case("suppression", 'from loguru import logger\nlogger.warning("failed", exc_info=True)  # sarj-noqa: SARJ508\n'),
    _case("generated", '# @generated\nfrom loguru import logger\nlogger.warning("failed", exc_info=True)\n'),
    _case("malformed-source", "from loguru import logger\nlogger.warning(\n"),
    _case("comment-and-string", '# logger.warning("failed", exc_info=True)\nsource = "exc_info=True"\n'),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = NoLoguruExcInfo().check(Path(case.path), case.source)
    assert len(diagnostics) == int(case.expected is ExpectedOutcome.MATCH)
    for diagnostic in diagnostics:
        assert diagnostic.code == "SARJ508"
        assert diagnostic.severity is Severity.ERROR
        assert "opt(exception=True)" in diagnostic.message


def test_rule_is_registered_once(tmp_path: Path) -> None:
    source = 'from loguru import logger\nlogger.warning("failed", exc_info=True)\n'
    path = tmp_path / "service.py"
    path.write_text(source, encoding="utf-8")
    diagnostics = analyze([NoLoguruExcInfo.id], [path])
    assert [(item.code, item.line) for item in diagnostics] == [("SARJ508", 2)]


def test_public_examples() -> None:
    verify_native_rule(NoLoguruExcInfo, analyze)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('from loguru import logger\nlogger.error("failed", ｅｘｃ＿ｉｎｆｏ=True)\n', 1),
        ('from ｌｏｇｕｒｕ import logger\nlogger.error("failed", ｅｘｃ＿ｉｎｆｏ=True)\n', 1),
        ('from unrelated import logger\nlogger.error("failed", ｅｘｃ＿ｉｎｆｏ=True)\n', 0),
        ("source = \"logger.error('failed', ｅｘｃ＿ｉｎｆｏ=True)\"\n", 0),
    ],
)
def test_native_normalized_keyword_identity_survives_the_prefilter(source: str, expected: int) -> None:
    diagnostics = NoLoguruExcInfo().check(Path("app/service.py"), source)
    assert len(diagnostics) == expected
    assert all(item.code == "SARJ508" and item.severity is Severity.ERROR for item in diagnostics)

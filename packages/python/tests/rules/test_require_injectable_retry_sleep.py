from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.require_injectable_retry_sleep import RequireInjectableRetrySleep


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_IMPORTS = "from tenacity import AsyncRetrying, Retrying, retry, stop_after_attempt, wait_exponential, wait_fixed, wait_none, wait_random\n"


def _check(source: str, path: str = "app/retry.py") -> list[Diagnostic]:
    return RequireInjectableRetrySleep().check(Path(path), dedent(source))


def _policy(arguments: str, factory: str = "retry", imports: str = _IMPORTS) -> str:
    return f"{imports}\npolicy = {factory}({arguments})\n"


def test_documented_examples() -> None:
    verify_native_rule(RequireInjectableRetrySleep, analyze)


def test_reports_one_warning_at_the_policy_call() -> None:
    findings = _check(_policy("stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2), reraise=True"))

    assert [(item.code, item.line, item.col, item.severity) for item in findings] == [
        ("SARJ486", 3, 10, Severity.WARNING)
    ]


@pytest.mark.parametrize(
    ("imports", "factory", "wait"),
    [
        (_IMPORTS, "retry", "wait_fixed(2)"),
        (_IMPORTS, "Retrying", "wait_random(0, 1)"),
        (_IMPORTS, "AsyncRetrying", "wait_exponential()"),
        ("import tenacity\n", "tenacity.retry", "tenacity.wait_exponential_jitter()"),
        ("import tenacity as t\n", "t.AsyncRetrying", "t.wait_fixed(1)"),
        ("from tenacity import retry as r, wait_fixed as fixed\n", "r", "fixed(1)"),
        (
            "from tenacity.asyncio import AsyncRetrying\nfrom tenacity.wait import wait_fixed\n",
            "AsyncRetrying",
            "wait_fixed(1)",
        ),
        (_IMPORTS, "retry", "wait_fixed(1) + wait_random(0, 1)"),
        (_IMPORTS, "retry", "wait_none() + wait_none() + wait_fixed(1)"),
        (_IMPORTS, "retry", "wait_fixed(wait=1)"),
    ],
)
def test_reports_backoff_policies_and_aliases(imports: str, factory: str, wait: str) -> None:
    assert len(_check(_policy(f"wait={wait}", factory, imports))) == 1


@pytest.mark.parametrize("sleep", ["asyncio.sleep", "time.sleep", "anyio.sleep", "trio.sleep", "tenacity.nap.sleep"])
def test_reports_an_explicit_wall_clock_sleep_as_no_seam(sleep: str) -> None:
    module = sleep.rpartition(".")[0]
    source = _policy(f"wait=wait_fixed(1), sleep={sleep}", imports=f"{_IMPORTS}import {module}\n")

    assert len(_check(source)) == 1


def test_reports_decorator_factories_on_functions_and_methods() -> None:
    findings = _check(
        _IMPORTS
        + dedent(
            """
        class Client:
            @retry(wait=wait_exponential())
            async def fetch(self):
                return await self.session.get()

        @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
        def load():
            return read()
        """
        )
    )

    assert [finding.line for finding in findings] == [4, 8]


@pytest.mark.parametrize(
    "arguments",
    [
        "wait=wait_exponential(), sleep=sleep",
        "wait=wait_exponential(), sleep=self._sleep",
        "wait=wait_fixed(1), sleep=lambda seconds: None",
        "stop=stop_after_attempt(3)",
        "wait=wait_none()",
        "wait=wait_fixed(0)",
        "wait=wait_fixed(0.0)",
        "wait=wait_fixed(wait=0)",
        "wait=wait_none() + wait_fixed(0)",
        "wait=self._wait",
        "wait=WAIT",
        "wait=build_wait()",
        "wait=wait_fixed(1) + custom_wait",
        "wait=wait_fixed(1), **options",
        "",
    ],
)
def test_ignores_seamed_zero_injected_and_opaque_waits(arguments: str) -> None:
    assert _check(_policy(arguments)) == []


def test_ignores_bare_decorator_and_positional_arguments() -> None:
    source = _IMPORTS + dedent(
        """
        @retry
        def load():
            return read()

        policy = Retrying(sleep, stop_after_attempt(3), wait_fixed(1))
        """
    )

    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "def retry(**kwargs):\n    pass\n\npolicy = retry(wait=wait_fixed(1))\n",
        "from backoff import on_exception, expo\n\npolicy = on_exception(expo, Exception, max_tries=3)\n",
        "import other\nimport tenacity\n\npolicy = other.retry(wait=tenacity.wait_fixed(1))\n",
        "from tenacity import retry\nimport other\n\npolicy = retry(wait=other.wait_fixed(1))\n",
        "from tenacity import retry\n\npolicy = retry(wait=wait_fixed(1))\n",
    ],
)
def test_ignores_calls_that_do_not_resolve_to_tenacity(source: str) -> None:
    assert _check(f"# tenacity\n{source}") == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_retry.py",
        "app/test_retry.py",
        "app/retry_test.py",
        "tests/helpers.py",
        "conftest.py",
        "app/fakes/retry.py",
    ],
)
def test_ignores_test_and_test_support_paths(path: str) -> None:
    assert _check(_policy("wait=wait_fixed(1)"), path) == []


def test_ignores_generated_and_malformed_modules() -> None:
    assert _check("# @generated\n" + _policy("wait=wait_fixed(1)")) == []
    assert _check("from tenacity import retry\npolicy = retry(wait=\n") == []


def test_exact_suppression_silences_only_its_own_code() -> None:
    suppressed = _IMPORTS + "policy = retry(wait=wait_fixed(1))  # sarj-noqa: SARJ486 -- vendor-mandated pacing\n"
    other = _IMPORTS + "policy = retry(wait=wait_fixed(1))  # sarj-noqa: SARJ485\n"

    assert _check(suppressed) == []
    assert len(_check(other)) == 1


def test_reports_each_policy_once_through_the_analyzer(tmp_path: Path) -> None:
    module = tmp_path / "app" / "retry.py"
    module.parent.mkdir()
    module.write_text(
        _IMPORTS + "\nfirst = retry(wait=wait_fixed(1)); second = AsyncRetrying(wait=wait_fixed(2))\n",
        encoding="utf-8",
    )

    findings = analyze([RequireInjectableRetrySleep.id], [module])

    assert [(item.line, item.col) for item in findings] == [(3, 9), (3, 45)]


@pytest.mark.parametrize(
    "wait",
    [
        "wait_random(0, 0)",
        "wait_random(min=0, max=0)",
        "wait_random(max=0, min=0)",
        "wait_random(max=0)",
        "wait_random(0, max=0)",
        "wait_random(0.0, 0.0)",
        "wait_combine()",
        "wait_combine(wait_none(), wait_fixed(0))",
        "wait_chain(wait_none(), wait_fixed(0))",
        "wait_chain(wait_none())",
        "wait_combine(wait_chain(wait_none(), wait_fixed(0)), wait_random(max=0))",
        "wait_chain(wait_none(), wait_fixed(0)) + wait_random(0, 0)",
    ],
)
def test_native_literal_zero_waits_do_not_require_a_sleeper(wait: str) -> None:
    imports = _IMPORTS + "from tenacity import wait_chain, wait_combine\n"

    assert _check(_policy(f"wait={wait}", imports=imports)) == []


@pytest.mark.parametrize(
    "wait",
    [
        "wait_random()",
        "wait_random(1, 1)",
        "wait_random(max=1)",
        "wait_combine(wait_none(), wait_fixed(1))",
        "wait_chain(wait_none(), wait_fixed(1))",
        "wait_chain(wait_fixed(1), wait_none())",
        "wait_combine(wait_chain(wait_none()), wait_fixed(1))",
        "wait_chain(wait_none(), wait_fixed(0)) + wait_fixed(1)",
    ],
)
def test_native_wait_compositions_retain_positive_delay_ownership(wait: str) -> None:
    imports = _IMPORTS + "from tenacity import wait_chain, wait_combine\n"

    findings = _check(_policy(f"wait={wait}", imports=imports))

    assert [(finding.code, finding.line, finding.col) for finding in findings] == [("SARJ486", 4, 10)]


@pytest.mark.parametrize(
    "wait",
    [
        "wait_random(*bounds)",
        "wait_random(**bounds)",
        "wait_random(0, 0, 0)",
        "wait_random(0, min=0, max=0)",
        "wait_random(unknown=0)",
        "wait_combine(*strategies)",
        "wait_combine(strategies=wait_none())",
        "wait_combine(wait_fixed(1), custom_wait)",
        "wait_chain()",
        "wait_chain(*strategies)",
        "wait_chain(strategies=wait_none())",
        "wait_chain(wait_fixed(1), custom_wait)",
    ],
)
def test_native_constructor_uncertainty_keeps_an_injected_or_invalid_shape_opaque(wait: str) -> None:
    imports = _IMPORTS + "from tenacity import wait_chain, wait_combine\n"

    assert _check(_policy(f"wait={wait}", imports=imports)) == []


@pytest.mark.parametrize(
    ("imports", "sleep"),
    [
        ("import tenacity", "tenacity.sleep"),
        ("import tenacity as t", "t.sleep"),
        ("from tenacity import sleep", "sleep"),
        ("from tenacity import sleep as pause", "pause"),
        ("from tenacity.nap import sleep as pause", "pause"),
    ],
)
def test_public_tenacity_default_sleep_export_is_not_an_injected_seam(imports: str, sleep: str) -> None:
    findings = _check(_policy(f"wait=wait_fixed(1), sleep={sleep}", imports=f"{_IMPORTS}{imports}\n"))

    assert len(findings) == 1
    assert findings[0].code == "SARJ486"


@pytest.mark.parametrize(
    "source",
    [
        "from tenacity import Retrying, wait_fixed, sleep\ndef policy(sleep):\n return Retrying(wait=wait_fixed(1), sleep=sleep)\n",
        "from tenacity import Retrying, wait_fixed, sleep\nsleep = custom_sleep\npolicy = Retrying(wait=wait_fixed(1), sleep=sleep)\n",
        "from tenacity import Retrying, wait_fixed\npolicy = Retrying(wait=wait_fixed(1), sleep=clock.sleep)\n",
        "from typing import TYPE_CHECKING\nfrom tenacity import Retrying, wait_fixed\nif TYPE_CHECKING:\n from tenacity import sleep\ndef policy(sleep):\n return Retrying(wait=wait_fixed(1), sleep=sleep)\n",
    ],
)
def test_public_sleep_lookalikes_preserve_native_binding_abstention(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "wait",
    [
        "wait_fixed(-0.0)",
        "wait_fixed(+0)",
        "wait_fixed(wait=-0)",
        "wait_random(min=-0.0, max=+0.0)",
        "wait_random(-0, +0)",
        "wait_combine(wait_fixed(-0.0), wait_none())",
        "wait_chain(wait_fixed(+0), wait_fixed(-0))",
    ],
)
def test_signed_real_literal_zero_waits_do_not_require_a_sleeper(wait: str) -> None:
    imports = _IMPORTS + "from tenacity import wait_chain, wait_combine\n"

    assert _check(_policy(f"wait={wait}", imports=imports)) == []


@pytest.mark.parametrize(
    "wait",
    [
        "wait_fixed(+1)",
        "wait_fixed(-1)",
        "wait_random(min=+1, max=+1)",
        "wait_fixed(ZERO)",
        "wait_fixed(0 + 0)",
        "wait_fixed(-0j)",
    ],
)
def test_signed_nonzero_opaque_and_invalid_waits_keep_existing_ownership(wait: str) -> None:
    findings = _check(_policy(f"wait={wait}"))

    assert [(finding.code, finding.line, finding.col) for finding in findings] == [("SARJ486", 3, 10)]

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sarj_python_lint.__main__ import analyze
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint._source import symbol_prefilter_source
from sarj_python_lint.rules._project_index import ProjectIndexSet


_NATIVE_SYMBOL_CASES = (
    pytest.param(
        "async-cleanup-registered-synchronously",
        "app/resources.py",
        (
            (
                "app/resources.py",
                "from ｃｏｎｔｅｘｔｌｉｂ import ＡｓｙｎｃＥｘｉｔＳｔａｃｋ\nasync def ｃｌｏｓｅ():\n    await ｒｅｌｅａｓｅ()\nasync def ｒｕｎ():\n    async with ＡｓｙｎｃＥｘｉｔＳｔａｃｋ() as ｓｔａｃｋ:\n        ｓｔａｃｋ.ｃａｌｌｂａｃｋ(ｃｌｏｓｅ)\n",
            ),
        ),
        1,
        id="async-cleanup-registered-synchronously-dropped-cleanup-native-NFKC-identifiers",
    ),
    pytest.param(
        "async-mock-call-without-await-assertion",
        "tests/test_delivery.py",
        (
            (
                "tests/test_delivery.py",
                "from ｕｎｉｔｔｅｓｔ.ｍｏｃｋ import ＡｓｙｎｃＭｏｃｋ\n\nasync def ｔｅｓｔ_ｄｅｌｉｖｅｒｙ():\n    ｓｅｎｄ = ＡｓｙｎｃＭｏｃｋ()\n    await ｄｅｌｉｖｅｒ(ｓｅｎｄ)\n    ｓｅｎｄ.ａｓｓｅｒｔ_ｃａｌｌｅｄ_ｏｎｃｅ_ｗｉｔｈ('item')\n",
            ),
        ),
        1,
        id="async-mock-call-without-await-assertion-call-only-async-mock-native-NFKC-identifiers",
    ),
    pytest.param(
        "async-mock-call-without-await-assertion",
        "tests/test_delivery.py",
        (
            (
                "tests/test_delivery.py",
                "from ｕｎｉｔｔｅｓｔ.ｍｏｃｋ import ＡｓｙｎｃＭｏｃｋ\n\nasync def ｔｅｓｔ_ｄｅｌｉｖｅｒｙ():\n    ｓｅｎｄ = ＡｓｙｎｃＭｏｃｋ()\n    await ｄｅｌｉｖｅｒ(ｓｅｎｄ)\n    assert ｓｅｎｄ.ｃａｌｌ_ｃｏｕｎｔ == 1\n    assert ｓｅｎｄ.ａｗａｉｔ_ｃｏｕｎｔ >= 0\n",
            ),
        ),
        1,
        id="async-mock-call-without-await-assertion-vacuous-await-count-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-dunder-all",
        "diagnostics/__init__.py",
        (
            (
                "diagnostics/__init__.py",
                'from .ｍｏｄｅｌｓ import Ｄｉａｇｎｏｓｔｉｃ as Ｄｉａｇｎｏｓｔｉｃ\n\n__ａｌｌ__ = ["Diagnostic"]\n',
            ),
        ),
        1,
        id="no-dunder-all-duplicated-export-list-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-fixed-sleep-before-assert",
        "tests/test_monitor.py",
        (
            (
                "tests/test_monitor.py",
                "import ａｓｙｎｃｉｏ\n\n\nasync def ｔｅｓｔ_ｒｅｐｏｒｔｓ_ｓｉｌｅｎｃｅ(ｍｏｎｉｔｏｒ):\n    ｍｏｎｉｔｏｒ.ｓｔａｒｔ()\n    await ａｓｙｎｃｉｏ.ｓｌｅｅｐ(0.5)\n    assert ｍｏｎｉｔｏｒ.ｒｅａｓｏｎ == 'silence'\n",
            ),
        ),
        1,
        id="no-fixed-sleep-before-assert-test-sleeps-then-asserts-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-fixed-sleep-before-assert",
        "tests/test_worker.py",
        (
            (
                "tests/test_worker.py",
                "import ｔｉｍｅ\n\n\ndef ｔｅｓｔ_ｗｏｒｋｅｒ_ｄｒａｉｎｓ_ｑｕｅｕｅ(ｗｏｒｋｅｒ, ｑｕｅｕｅ):\n    ｗｏｒｋｅｒ.ｓｔａｒｔ()\n    ｔｉｍｅ.ｓｌｅｅｐ(1)\n    assert ｑｕｅｕｅ.ｐｅｎｄｉｎｇ() == 0\n",
            ),
        ),
        1,
        id="no-fixed-sleep-before-assert-test-blocks-then-asserts-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-fixed-sleep-in-loop",
        "app/jobs.py",
        (
            (
                "app/jobs.py",
                "import ａｓｙｎｃｉｏ\n\n\nasync def ｗａｉｔ_ｕｎｔｉｌ_ｄｏｎｅ(ｊｏｂ):\n    while not await ｊｏｂ.ｄｏｎｅ():\n        await ａｓｙｎｃｉｏ.ｓｌｅｅｐ(2)\n",
            ),
        ),
        1,
        id="no-fixed-sleep-in-loop-polling-loop-sleeps-literal-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-fixed-sleep-in-loop",
        "app/health.py",
        (
            (
                "app/health.py",
                "import ｔｉｍｅ\n\n\ndef ｗａｉｔ_ｆｏｒ_ｈｅａｌｔｈ(ｐｒｏｂｅ):\n    for _ in ｒａｎｇｅ(30):\n        if ｐｒｏｂｅ():\n            return\n        ｔｉｍｅ.ｓｌｅｅｐ(0.5)\n",
            ),
        ),
        1,
        id="no-fixed-sleep-in-loop-blocking-loop-sleeps-literal-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-hidden-constructor-fallback",
        "app/service.py",
        (
            ("pyproject.toml", "[project]\nname = 'example'\nversion = '0.1.0'\n"),
            ("app/__init__.py", "\n"),
            (
                "app/config.py",
                "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    MODEL: str = 'model'\nsettings = Settings()\n",
            ),
            (
                "app/service.py",
                "from ａｐｐ.ｃｏｎｆｉｇ import ｓｅｔｔｉｎｇｓ\n\nclass Ｇｅｎｅｒａｔｏｒ:\n    def __ｉｎｉｔ__(ｓｅｌｆ, *, ｍｏｄｅｌ: ｓｔｒ | None = None) -> None:\n        ｓｅｌｆ.ｍｏｄｅｌ = ｍｏｄｅｌ or ｓｅｔｔｉｎｇｓ.ＭＯＤＥＬ\n\nｇｅｎｅｒａｔｏｒ = Ｇｅｎｅｒａｔｏｒ(ｍｏｄｅｌ='explicit')\n",
            ),
        ),
        1,
        id="no-hidden-constructor-fallback-ambient-settings-fallback-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-positional-psycopg-row-escape",
        "app/task_store.py",
        (
            (
                "app/task_store.py",
                'import psycopg\n\nasync def load(dsn: str):\n    async with await psycopg. AsyncConnection. connect(dsn) as conn:\n        async with conn. cursor() as cursor:\n            await cursor. execute("SELECT id, state FROM task")\n            return await cursor. fetchone()\n',
            ),
        ),
        1,
        id="no-positional-psycopg-row-escape-escaping-positional-record-attribute-whitespace",
    ),
    pytest.param(
        "no-positional-psycopg-row-escape",
        "app/task_store.py",
        (
            (
                "app/task_store.py",
                'import ｐｓｙｃｏｐｇ\n\nasync def ｌｏａｄ(ｄｓｎ: ｓｔｒ):\n    async with await ｐｓｙｃｏｐｇ.ＡｓｙｎｃＣｏｎｎｅｃｔｉｏｎ.ｃｏｎｎｅｃｔ(ｄｓｎ) as ｃｏｎｎ:\n        async with ｃｏｎｎ.ｃｕｒｓｏｒ() as ｃｕｒｓｏｒ:\n            await ｃｕｒｓｏｒ.ｅｘｅｃｕｔｅ("SELECT id, state FROM task")\n            return await ｃｕｒｓｏｒ.ｆｅｔｃｈｏｎｅ()\n',
            ),
        ),
        1,
        id="no-positional-psycopg-row-escape-escaping-positional-record-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-redundant-module-alias-exports",
        "legacy/settings.py",
        (
            (
                "legacy/settings.py",
                "import ｓｙｓ\n\nfrom ｃａｎｏｎｉｃａｌ import ｓｅｔｔｉｎｇｓ as _ｃａｎｏｎｉｃａｌ\n\n\nｓｙｓ.ｍｏｄｕｌｅｓ[__ｎａｍｅ__] = _ｃａｎｏｎｉｃａｌ\n",
            ),
        ),
        1,
        id="no-redundant-module-alias-exports-current-module-replacement-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-service-behavior-in-settings",
        "app/batch_settings.py",
        (
            (
                "app/batch_settings.py",
                "class ＢａｔｃｈＳｅｔｔｉｎｇｓ:\n    def __ｉｎｉｔ__(ｓｅｌｆ, ｓｔｏｒｅ: ＳｃｈｅｄｕｌｅＳｔｏｒｅ) -> None:\n        ｓｅｌｆ._ｓｔｏｒｅ = ｓｔｏｒｅ\n\n    async def ｒｅｐｏｉｎｔ(ｓｅｌｆ, ｂａｔｃｈ_ｉｄ: ｓｔｒ) -> ｉｎｔ:\n        return await ｓｅｌｆ._ｓｔｏｒｅ.ｒｅｐｏｉｎｔ(ｂａｔｃｈ_ｉｄ)\n",
            ),
        ),
        1,
        id="no-service-behavior-in-settings-settings-orchestrates-store-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-swallowed-asyncio-cancellation",
        "worker.py",
        (
            (
                "worker.py",
                "import ａｓｙｎｃｉｏ\n\nasync def ｗｏｒｋｅｒ():\n    try:\n        await ａｓｙｎｃｉｏ.ｓｌｅｅｐ(10)\n    except ａｓｙｎｃｉｏ.ＣａｎｃｅｌｌｅｄＥｒｒｏｒ:\n        return None\n",
            ),
        ),
        1,
        id="no-swallowed-asyncio-cancellation-cancelled-operation-returns-success-native-NFKC-identifiers",
    ),
    pytest.param(
        "no-unique-violation-message-match",
        "app/store.py",
        (
            (
                "app/store.py",
                "from ｐｓｙｃｏｐｇ import ｅｒｒｏｒｓ\n\ntry:\n    ｓａｖｅ()\nexcept ｅｒｒｏｒｓ.ＵｎｉｑｕｅＶｉｏｌａｔｉｏｎ as ｅｘｃ:\n    if 'user_email_key' in ｓｔｒ(ｅｘｃ):\n        raise ＤｕｐｌｉｃａｔｅＥｍａｉｌ from ｅｘｃ\n    raise\n",
            ),
        ),
        1,
        id="no-unique-violation-message-match-message-matched-constraint-native-NFKC-identifiers",
    ),
    pytest.param(
        "prefer-autospec-for-callable-mock",
        "tests/test_delivery.py",
        (
            (
                "tests/test_delivery.py",
                "from ｕｎｉｔｔｅｓｔ.ｍｏｃｋ import Ｍｏｃｋ\ndef ｓｅｎｄ(*, ｒｅｃｉｐｉｅｎｔ: ｓｔｒ) -> None:\n    pass\ndef ｔｅｓｔ_ｓｅｎｄ():\n    ｄｏｕｂｌｅ = Ｍｏｃｋ(ｓｐｅｃ=ｓｅｎｄ)\n    ｄｏｕｂｌｅ(ｒｅｃｉｐｉｅｎｔ='sample')\n",
            ),
        ),
        1,
        id="prefer-autospec-for-callable-mock-specced-function-direct-call-native-NFKC-identifiers",
    ),
    pytest.param(
        "prefer-monotonic-for-elapsed-time",
        "app/metrics.py",
        (
            (
                "app/metrics.py",
                "import ｔｉｍｅ\n\ndef ｍｅａｓｕｒｅ():\n    ｓｔａｒｔｅｄ = ｔｉｍｅ.ｔｉｍｅ()\n    ｗｏｒｋ()\n    return ｔｉｍｅ.ｔｉｍｅ() - ｓｔａｒｔｅｄ\n",
            ),
        ),
        1,
        id="prefer-monotonic-for-elapsed-time-wall-clock-elapsed-native-NFKC-identifiers",
    ),
    pytest.param(
        "prefer-native-string-check",
        "tests/test_receipt.py",
        (
            (
                "tests/test_receipt.py",
                'from ｐｙｄａｎｔｉｃ import ＴｙｐｅＡｄａｐｔｅｒ\ndef ｔｅｓｔ_ｒｅｃｅｉｐｔ():\n    assert ＴｙｐｅＡｄａｐｔｅｒ(ｓｔｒ).ｖａｌｉｄａｔｅ_ｐｙｔｈｏｎ(ｒｅｃｅｉｐｔ["id"]) == "abc"\n',
            ),
        ),
        1,
        id="prefer-native-string-check-adapter-for-string-check-native-NFKC-identifiers",
    ),
    pytest.param(
        "prefer-native-string-check",
        "app/responses.py",
        (
            (
                "app/responses.py",
                "from ｐｙｄａｎｔｉｃ import ＴｙｐｅＡｄａｐｔｅｒ, ＪｓｏｎＶａｌｕｅ\nfrom ｆａｓｔａｐｉ.ｅｎｃｏｄｅｒｓ import ｊｓｏｎａｂｌｅ_ｅｎｃｏｄｅｒ\ndef ｒｅｓｐｏｎｓｅ_ｃｏｎｔｅｎｔ(ｂｏｄｙ):\n    return ＴｙｐｅＡｄａｐｔｅｒ(ｄｉｃｔ[ｓｔｒ, ＪｓｏｎＶａｌｕｅ]).ｖａｌｉｄａｔｅ_ｐｙｔｈｏｎ(ｊｓｏｎａｂｌｅ_ｅｎｃｏｄｅｒ({'body': ｂｏｄｙ}, ｃｕｓｔｏｍ_ｅｎｃｏｄｅｒ={ｂｙｔｅｓ: lambda ｖａｌｕｅ: ｖａｌｕｅ.ｄｅｃｏｄｅ('utf-8', ｅｒｒｏｒｓ='replace')}))\n",
            ),
        ),
        1,
        id="prefer-native-string-check-generic-json-after-encoding-native-NFKC-identifiers",
    ),
    pytest.param(
        "prefer-pydantic-json-value",
        "src/app/types.py",
        (
            ("pyproject.toml", '[project]\nname = "app"\nversion = "0.1.0"\ndependencies = ["pydantic>=2"]\n'),
            (
                "src/app/types.py",
                "type ＪｓｏｎＶａｌｕｅ = ｓｔｒ | ｉｎｔ | ｆｌｏａｔ | ｂｏｏｌ | None | ｌｉｓｔ[ＪｓｏｎＶａｌｕｅ] | ｄｉｃｔ[ｓｔｒ, ＪｓｏｎＶａｌｕｅ]\n",
            ),
        ),
        1,
        id="prefer-pydantic-json-value-home-grown-json-value-native-NFKC-identifiers",
    ),
    pytest.param(
        "prefer-set-isdisjoint",
        "app/policy.py",
        (
            ("pyproject.toml", '[project]\nname = "example"\nversion = "0.1.0"\n'),
            (
                "app/policy.py",
                "class\tAccessCase:\n    tags: frozenset[str]\n\ndef accepts(case: AccessCase):\n    if\tcase.tags & {'read', 'write'}:\n        allow()\n",
            ),
        ),
        1,
        id="prefer-set-isdisjoint-discarded-intersection-keyword-whitespace",
    ),
    pytest.param(
        "prefer-str-enum",
        "app/order.py",
        (
            (
                "app/order.py",
                'class Ｏｒｄｅｒ:\n    ｓｔａｔｕｓｅｓ = ("pending", "shipped")\n    ｓｔａｔｕｓ: ｓｔｒ = "pending"\n',
            ),
        ),
        1,
        id="prefer-str-enum-raw-string-choice-field-native-NFKC-identifiers",
    ),
    pytest.param(
        "prefer-struct-over-namedtuple",
        "models.py",
        (
            (
                "models.py",
                "from ｃｏｌｌｅｃｔｉｏｎｓ import ｎａｍｅｄｔｕｐｌｅ\n\nＲｏｗ = ｎａｍｅｄｔｕｐｌｅ('Row', ['id', 'name'])\n",
            ),
        ),
        1,
        id="prefer-struct-over-namedtuple-collections-namedtuple-native-NFKC-identifiers",
    ),
    pytest.param(
        "prefer-walrus-regex-match",
        "app/parser.py",
        (
            (
                "app/parser.py",
                'import ｒｅ\n\ndef ｆｉｒｓｔ_ｎｕｍｂｅｒ(ｔｅｘｔ: ｓｔｒ) -> ｓｔｒ | None:\n    match = ｒｅ.ｓｅａｒｃｈ(r"\\d+", ｔｅｘｔ)\n    if match:\n        return match.ｇｒｏｕｐ(0)\n    return None\n',
            ),
        ),
        1,
        id="prefer-walrus-regex-match-assigned-regex-result-native-NFKC-identifiers",
    ),
    pytest.param(
        "production-derived-test-cases",
        "app/tests/test_models.py",
        (
            (
                "app/tests/test_models.py",
                "import ｐｙｔｅｓｔ\nfrom ａｐｐ.ｍｏｄｅｌｓ import ＥＬＩＧＩＢＬＥ_ＭＯＤＥＬＳ\n\n@ｐｙｔｅｓｔ.ｍａｒｋ.ｐａｒａｍｅｔｒｉｚｅ('model', ＥＬＩＧＩＢＬＥ_ＭＯＤＥＬＳ)\ndef ｔｅｓｔ_ｍｏｄｅｌ(ｍｏｄｅｌ):\n    assert ｂｕｉｌｄ(ｍｏｄｅｌ).ｔｉｅｒ == 'priority'\n",
            ),
        ),
        1,
        id="production-derived-test-cases-production-derived-model-cases-native-NFKC-identifiers",
    ),
    pytest.param(
        "require-explicit-psycopg-transaction",
        "repository.py",
        (
            (
                "repository.py",
                'from ｐｓｙｃｏｐｇ_ｐｏｏｌ import ＡｓｙｎｃＣｏｎｎｅｃｔｉｏｎＰｏｏｌ\nasync def ｓａｖｅ(ｐｏｏｌ: ＡｓｙｎｃＣｏｎｎｅｃｔｉｏｎＰｏｏｌ):\n    async with ｐｏｏｌ.ｃｏｎｎｅｃｔｉｏｎ() as ｃｏｎｎ:\n        await ｃｏｎｎ.ｅｘｅｃｕｔｅ("SELECT id FROM items FOR UPDATE")\n        await ｃｏｎｎ.ｅｘｅｃｕｔｅ("UPDATE items SET n = 1")\n',
            ),
        ),
        1,
        id="require-explicit-psycopg-transaction-unprotected-lock-native-NFKC-identifiers",
    ),
    pytest.param(
        "require-injectable-retry-sleep",
        "app/retry.py",
        (
            (
                "app/retry.py",
                "from ｔｅｎａｃｉｔｙ import ｒｅｔｒｙ, ｓｔｏｐ_ａｆｔｅｒ_ａｔｔｅｍｐｔ, ｗａｉｔ_ｅｘｐｏｎｅｎｔｉａｌ\n\nｃｌｉｅｎｔ_ｒｅｔｒｙ = ｒｅｔｒｙ(ｓｔｏｐ=ｓｔｏｐ_ａｆｔｅｒ_ａｔｔｅｍｐｔ(4), ｗａｉｔ=ｗａｉｔ_ｅｘｐｏｎｅｎｔｉａｌ(ｍｕｌｔｉｐｌｉｅｒ=2))\n",
            ),
        ),
        1,
        id="require-injectable-retry-sleep-retry-backoff-without-sleep-native-NFKC-identifiers",
    ),
    pytest.param(
        "require-nodecode-for-splitting-settings-field",
        "app/settings.py",
        (
            (
                "app/settings.py",
                "import ｏｓ\nfrom ｐｙｄａｎｔｉｃ import ｆｉｅｌｄ_ｖａｌｉｄａｔｏｒ\nfrom ｐｙｄａｎｔｉｃ_ｓｅｔｔｉｎｇｓ import ＢａｓｅＳｅｔｔｉｎｇｓ\n\nclass Ｓｅｔｔｉｎｇｓ(ＢａｓｅＳｅｔｔｉｎｇｓ):\n    ｅｍａｉｌｓ: ｌｉｓｔ[ｓｔｒ]\n    @ｆｉｅｌｄ_ｖａｌｉｄａｔｏｒ('emails', ｍｏｄｅ='before')\n    @ｃｌａｓｓｍｅｔｈｏｄ\n    def ｓｐｌｉｔ_ｅｍａｉｌｓ(ｃｌｓ, ｖａｌｕｅ):\n        return ｖａｌｕｅ.ｓｐｌｉｔ(',')\n\nｏｓ.ｅｎｖｉｒｏｎ['EMAILS'] = 'one@example.com,two@example.com'\nＳｅｔｔｉｎｇｓ()\n",
            ),
        ),
        1,
        id="require-nodecode-for-splitting-settings-field-complex-setting-split-without-nodecode-native-NFKC-identifiers",
    ),
    pytest.param(
        "require-port-for-service",
        "app/native.py",
        (
            ("pyproject.toml", '[project]\nname = "boundary-example"\nversion = "0.1.0"\n'),
            (
                "app/native.py",
                "from typing import Protocol\n\nclass\tBackend(Protocol):\n    def read(self) -> str: ...\n    def write(self, value: str) -> None: ...\n\nclass\tCoordinator:\n    def __init__(self) -> None:\n        self.backend: Backend = native_backend()\n    def read(self) -> str:\n        return\tself.backend.read()\n    def write(self, value: str) -> None:\n        self.backend.write(value)\n\nclass\tConsumer:\n    def receive(self) -> str:\n        return\tCoordinator().read()\n    def send(self, value: str) -> None:\n        Coordinator().write(value)\n",
            ),
        ),
        1,
        id="require-port-for-service-factory-created-boundary-keyword-whitespace",
    ),
    pytest.param(
        "require-port-for-service",
        "app/services/thing_service.py",
        (
            (
                "app/services/thing_service.py",
                "class\tThingService:\n    def __init__(self, client: ThingClient) -> None:\n        self.client = client\n\n    def read(self, key: str) -> str:\n        return\tself.client.get(key)\n\n    def write(self, key: str, value: str) -> None:\n        self.client.put(key, value)\n\ndef sync(service: ThingService) -> None:\n    service.write('inbox', service.read('outbox'))\n",
            ),
        ),
        1,
        id="require-port-for-service-concrete-service-boundary-keyword-whitespace",
    ),
    pytest.param(
        "require-public-dependency-contract",
        "app/consumer.py",
        (
            ("app/__init__.py", "# package\n"),
            (
                "app/publisher.py",
                "from abc import ABC, abstractmethod\nclass Publisher(ABC):\n    @abstractmethod\n    def publish(self) -> None: ...\nclass HttpPublisher(Publisher):\n    def publish(self) -> None: ...\nclass QueuePublisher(Publisher):\n    def publish(self) -> None: ...\n",
            ),
            (
                "app/consumer.py",
                "from app.publisher import Publisher, HttpPublisher\nclass\tConsumer:\n    def __init__(self, publisher: HttpPublisher) -> None: self.publisher = publisher\n    def run(self) -> None: self.publisher.publish()\n",
            ),
        ),
        1,
        id="require-public-dependency-contract-existing-contract-httppublisher-keyword-whitespace",
    ),
    pytest.param(
        "require-pydantic-for-external-json",
        "protocol.py",
        (
            (
                "protocol.py",
                "import httpx\n\ndef fetch() -> object:\n    report = httpx. get('https://api.example/report'). json()\n    return report. get('version')\n",
            ),
        ),
        1,
        id="require-pydantic-for-external-json-manual-external-json-access-attribute-whitespace",
    ),
    pytest.param(
        "require-pydantic-for-external-json",
        "protocol.py",
        (
            (
                "protocol.py",
                "import httpx\n\ndef fetch\t() -> object:\n    report = httpx.get\t('https://api.example/report').json\t()\n    return report.get\t('version')\n",
            ),
        ),
        1,
        id="require-pydantic-for-external-json-manual-external-json-access-call-whitespace",
    ),
    pytest.param(
        "require-pydantic-for-external-json",
        "protocol.py",
        (
            (
                "protocol.py",
                "import ｈｔｔｐｘ\n\ndef ｆｅｔｃｈ() -> ｏｂｊｅｃｔ:\n    ｒｅｐｏｒｔ = ｈｔｔｐｘ.ｇｅｔ('https://api.example/report').ｊｓｏｎ()\n    return ｒｅｐｏｒｔ.ｇｅｔ('version')\n",
            ),
        ),
        1,
        id="require-pydantic-for-external-json-manual-external-json-access-native-NFKC-identifiers",
    ),
    pytest.param(
        "require-pydantic-for-external-json",
        "protocol.py",
        (
            (
                "protocol.py",
                "import httpx\n\nclass Envelope:\n    def __init__(self, body):\n        self. body = body\n    def payload(self):\n        return self. body\n\ndef wrap(body):\n    result = Envelope(body)\n    return result\n\ndef fetch():\n    raw = httpx. get('https://api.example/report'). json()\n    return wrap(raw). payload()['version']\n",
            ),
        ),
        1,
        id="require-pydantic-for-external-json-factory-forwarded-external-json-attribute-whitespace",
    ),
    pytest.param(
        "require-pydantic-for-external-json",
        "protocol.py",
        (
            (
                "protocol.py",
                "import httpx\n\nclass Envelope:\n    def __init__\t(self, body):\n        self.body = body\n    def payload\t(self):\n        return self.body\n\ndef wrap\t(body):\n    result = Envelope\t(body)\n    return result\n\ndef fetch\t():\n    raw = httpx.get\t('https://api.example/report').json\t()\n    return wrap\t(raw).payload\t()['version']\n",
            ),
        ),
        1,
        id="require-pydantic-for-external-json-factory-forwarded-external-json-call-whitespace",
    ),
    pytest.param(
        "require-pydantic-for-external-json",
        "protocol.py",
        (
            (
                "protocol.py",
                "import ｈｔｔｐｘ\n\nclass Ｅｎｖｅｌｏｐｅ:\n    def __ｉｎｉｔ__(ｓｅｌｆ, ｂｏｄｙ):\n        ｓｅｌｆ.ｂｏｄｙ = ｂｏｄｙ\n    def ｐａｙｌｏａｄ(ｓｅｌｆ):\n        return ｓｅｌｆ.ｂｏｄｙ\n\ndef ｗｒａｐ(ｂｏｄｙ):\n    ｒｅｓｕｌｔ = Ｅｎｖｅｌｏｐｅ(ｂｏｄｙ)\n    return ｒｅｓｕｌｔ\n\ndef ｆｅｔｃｈ():\n    ｒａｗ = ｈｔｔｐｘ.ｇｅｔ('https://api.example/report').ｊｓｏｎ()\n    return ｗｒａｐ(ｒａｗ).ｐａｙｌｏａｄ()['version']\n",
            ),
        ),
        1,
        id="require-pydantic-for-external-json-factory-forwarded-external-json-native-NFKC-identifiers",
    ),
    pytest.param(
        "require-pydantic-ordinal-lower-bound",
        "api.py",
        (
            (
                "api.py",
                'from pydantic import BaseModel, Field\n\nclass CallDetail(BaseModel):\n    retry_attempt_number: int = Field(default=1, description="\\x57\\x68\\x69\\x63\\x68 \\x64\\x69\\x61\\x6c \\x74\\x68\\x69\\x73 \\x63\\x61\\x6c\\x6c \\x69\\x73 \\x77\\x69\\x74\\x68\\x69\\x6e \\x69\\x74\\x73 \\x72\\x65\\x74\\x72\\x79 \\x67\\x72\\x6f\\x75\\x70 (1 \\x66\\x6f\\x72 \\x74\\x68\\x65 \\x66\\x69\\x72\\x73\\x74 \\x61\\x74\\x74\\x65\\x6d\\x70\\x74).")\n',
            ),
        ),
        1,
        id="require-pydantic-ordinal-lower-bound-ordinal-prose-only-escaped-string-values",
    ),
    pytest.param(
        "shared-mutable-pydantic-factory",
        "app/models.py",
        (
            (
                "app/models.py",
                "from ｐｙｄａｎｔｉｃ import ＢａｓｅＭｏｄｅｌ, Ｆｉｅｌｄ\nＳＨＡＲＥＤ = []\nclass Ｍｏｄｅｌ(ＢａｓｅＭｏｄｅｌ):\n    ｖａｌｕｅｓ: ｌｉｓｔ[ｉｎｔ] = Ｆｉｅｌｄ(ｄｅｆａｕｌｔ_ｆａｃｔｏｒｙ=lambda: ＳＨＡＲＥＤ)\n",
            ),
        ),
        1,
        id="shared-mutable-pydantic-factory-captured-list-native-NFKC-identifiers",
    ),
    pytest.param(
        "subprocess-kill-without-reap",
        "app/processes.py",
        (
            (
                "app/processes.py",
                "import ｓｕｂｐｒｏｃｅｓｓ\ndef ｒｕｎ(ａｒｇｓ):\n    ｐｒｏｃｅｓｓ = ｓｕｂｐｒｏｃｅｓｓ.Ｐｏｐｅｎ(ａｒｇｓ)\n    try:\n        ｐｒｏｃｅｓｓ.ｃｏｍｍｕｎｉｃａｔｅ(ｔｉｍｅｏｕｔ=1)\n    except ｓｕｂｐｒｏｃｅｓｓ.ＴｉｍｅｏｕｔＥｘｐｉｒｅｄ:\n        ｐｒｏｃｅｓｓ.ｋｉｌｌ()\n",
            ),
        ),
        1,
        id="subprocess-kill-without-reap-unreaped-child-native-NFKC-identifiers",
    ),
    pytest.param(
        "typed-error-reasons",
        "app/errors.py",
        (
            (
                "app/errors.py",
                "class MissingFilesError(Exception):\n    def __init__(self, paths: list[str]) -> None:\n        super(). __init__(', '. join(paths))\n",
            ),
        ),
        1,
        id="typed-error-reasons-dynamic-context-review-attribute-whitespace",
    ),
    pytest.param(
        "typed-error-reasons",
        "app/errors.py",
        (
            (
                "app/errors.py",
                "class MissingFilesError\t(Exception):\n    def __init__\t(self, paths: list[str]) -> None:\n        super\t().__init__\t(', '.join\t(paths))\n",
            ),
        ),
        1,
        id="typed-error-reasons-dynamic-context-review-call-whitespace",
    ),
    pytest.param(
        "typed-error-reasons",
        "app/errors.py",
        (
            (
                "app/errors.py",
                "class MissingFilesError(Exception):\n    def __init__(self, paths: list [ str ] ) -> None:\n        super().__init__(', '.join(paths))\n",
            ),
        ),
        1,
        id="typed-error-reasons-dynamic-context-review-subscript-whitespace",
    ),
    pytest.param(
        "typed-error-reasons",
        "app/errors.py",
        (
            (
                "app/errors.py",
                "class ＭｉｓｓｉｎｇＦｉｌｅｓＥｒｒｏｒ(Ｅｘｃｅｐｔｉｏｎ):\n    def __ｉｎｉｔ__(ｓｅｌｆ, ｐａｔｈｓ: ｌｉｓｔ[ｓｔｒ]) -> None:\n        ｓｕｐｅｒ().__ｉｎｉｔ__(', '.ｊｏｉｎ(ｐａｔｈｓ))\n",
            ),
        ),
        1,
        id="typed-error-reasons-dynamic-context-review-native-NFKC-identifiers",
    ),
    pytest.param(
        "typed-error-reasons",
        "app/errors.py",
        (
            (
                "app/errors.py",
                "class DomainError(Exception): ...\n\nclass IncompleteError(DomainError):\n    def __init__(self, reasons: list[str]) -> None:\n        self. reasons = reasons\n        super(). __init__(f\"Incomplete: {'; '. join(reasons)}\")\n",
            ),
        ),
        1,
        id="typed-error-reasons-rendered-reason-list-attribute-whitespace",
    ),
    pytest.param(
        "typed-error-reasons",
        "app/errors.py",
        (
            (
                "app/errors.py",
                "class DomainError\t(Exception): ...\n\nclass IncompleteError\t(DomainError):\n    def __init__\t(self, reasons: list[str]) -> None:\n        self.reasons = reasons\n        super\t().__init__\t(f\"Incomplete: {'; '.join\t(reasons)}\")\n",
            ),
        ),
        1,
        id="typed-error-reasons-rendered-reason-list-call-whitespace",
    ),
    pytest.param(
        "typed-error-reasons",
        "app/errors.py",
        (
            (
                "app/errors.py",
                "class DomainError(Exception): ...\n\nclass IncompleteError(DomainError):\n    def __init__(self, reasons: list [ str ] ) -> None:\n        self.reasons = reasons\n        super().__init__(f\"Incomplete: {'; '.join(reasons)}\")\n",
            ),
        ),
        1,
        id="typed-error-reasons-rendered-reason-list-subscript-whitespace",
    ),
    pytest.param(
        "typed-error-reasons",
        "app/errors.py",
        (
            (
                "app/errors.py",
                "class ＤｏｍａｉｎＥｒｒｏｒ(Ｅｘｃｅｐｔｉｏｎ): ...\n\nclass ＩｎｃｏｍｐｌｅｔｅＥｒｒｏｒ(ＤｏｍａｉｎＥｒｒｏｒ):\n    def __ｉｎｉｔ__(ｓｅｌｆ, ｒｅａｓｏｎｓ: ｌｉｓｔ[ｓｔｒ]) -> None:\n        ｓｅｌｆ.ｒｅａｓｏｎｓ = ｒｅａｓｏｎｓ\n        ｓｕｐｅｒ().__ｉｎｉｔ__(f\"Incomplete: {'; '.ｊｏｉｎ(ｒｅａｓｏｎｓ)}\")\n",
            ),
        ),
        1,
        id="typed-error-reasons-rendered-reason-list-native-NFKC-identifiers",
    ),
    pytest.param(
        "unused-test-factory-option",
        "tests/test_widget.py",
        (
            (
                "tests/test_widget.py",
                "def ｔｅｓｔ_ｗｉｄｇｅｔｓ():\n    def _ｍａｋｅ_ｗｉｄｇｅｔ(*, ｓｉｚｅ=3):\n        return Ｗｉｄｇｅｔ(ｓｉｚｅ=ｓｉｚｅ)\n    _ｍａｋｅ_ｗｉｄｇｅｔ()\n    _ｍａｋｅ_ｗｉｄｇｅｔ(ｓｉｚｅ=3)\n",
            ),
        ),
        1,
        id="unused-test-factory-option-invariant-size-option-native-NFKC-identifiers",
    ),
    pytest.param(
        "unused-test-factory-option",
        "tests/test_widget.py",
        (
            (
                "tests/test_widget.py",
                "def _ｒｅａｄ():\n    return 'ready'\ndef _ｍａｋｅ_ｗｉｄｇｅｔ(*, ｒｅａｄ=_ｒｅａｄ):\n    return Ｗｉｄｇｅｔ(ｒｅａｄ=ｒｅａｄ)\n_ｍａｋｅ_ｗｉｄｇｅｔ()\n_ｍａｋｅ_ｗｉｄｇｅｔ()\n",
            ),
        ),
        1,
        id="unused-test-factory-option-unused-local-callable-option-native-NFKC-identifiers",
    ),
    pytest.param(
        "async-cleanup-registered-synchronously",
        "app/resources.py",
        (
            (
                "app/resources.py",
                "from ｃｏｎｔｅｘｔｌｉｂ import ＡｓｙｎｃＥｘｉｔＳｔａｃｋ\nasync def ｃｌｏｓｅ():\n    await ｒｅｌｅａｓｅ()\nasync def ｒｕｎ():\n    async with ＡｓｙｎｃＥｘｉｔＳｔａｃｋ() as ｓｔａｃｋ:\n        ｓｔａｃｋ.ｐｕｓｈ_ａｓｙｎｃ_ｃａｌｌｂａｃｋ(ｃｌｏｓｅ)\n",
            ),
        ),
        0,
        id="async-cleanup-registered-synchronously-native-excluded-semantic-control",
    ),
    pytest.param(
        "async-mock-call-without-await-assertion",
        "tests/test_delivery.py",
        (
            (
                "tests/test_delivery.py",
                "from ｕｎｉｔｔｅｓｔ.ｍｏｃｋ import ＡｓｙｎｃＭｏｃｋ\n\nasync def ｔｅｓｔ_ｄｅｌｉｖｅｒｙ():\n    ｓｅｎｄ = ＡｓｙｎｃＭｏｃｋ()\n    await ｄｅｌｉｖｅｒ(ｓｅｎｄ)\n    ｓｅｎｄ.ａｓｓｅｒｔ_ｃａｌｌｅｄ_ｏｎｃｅ_ｗｉｔｈ('item')\n    ｓｅｎｄ.ａｓｓｅｒｔ_ａｗａｉｔｅｄ_ｏｎｃｅ_ｗｉｔｈ('item')\n",
            ),
        ),
        0,
        id="async-mock-call-without-await-assertion-native-excluded-semantic-control",
    ),
    pytest.param(
        "no-dunder-all",
        "diagnostics/__init__.py",
        (("diagnostics/__init__.py", "from .ｍｏｄｅｌｓ import Ｄｉａｇｎｏｓｔｉｃ as Ｄｉａｇｎｏｓｔｉｃ\n"),),
        0,
        id="no-dunder-all-native-excluded-semantic-control",
    ),
    pytest.param(
        "no-fixed-sleep-before-assert",
        "tests/test_monitor.py",
        (
            (
                "tests/test_monitor.py",
                "import ａｓｙｎｃｉｏ\n\n\nasync def ｔｅｓｔ_ｒｅｐｏｒｔｓ_ｓｉｌｅｎｃｅ(ｍｏｎｉｔｏｒ):\n    ｍｏｎｉｔｏｒ.ｓｔａｒｔ()\n    await ａｓｙｎｃｉｏ.ｗａｉｔ_ｆｏｒ(ｍｏｎｉｔｏｒ.ｆｉｒｅｄ.ｗａｉｔ(), ｔｉｍｅｏｕｔ=5)\n    assert ｍｏｎｉｔｏｒ.ｒｅａｓｏｎ == 'silence'\n",
            ),
        ),
        0,
        id="no-fixed-sleep-before-assert-native-excluded-semantic-control",
    ),
    pytest.param(
        "no-fixed-sleep-in-loop",
        "app/jobs.py",
        (
            (
                "app/jobs.py",
                "import ａｓｙｎｃｉｏ\n\n\nclass ＪｏｂＷａｉｔｅｒ:\n    def __ｉｎｉｔ__(ｓｅｌｆ, ｐｏｌｌ_ｓｅｃｏｎｄｓ: ｆｌｏａｔ) -> None:\n        ｓｅｌｆ._ｐｏｌｌ_ｓｅｃｏｎｄｓ = ｐｏｌｌ_ｓｅｃｏｎｄｓ\n\n    async def ｗａｉｔ_ｕｎｔｉｌ_ｄｏｎｅ(ｓｅｌｆ, ｊｏｂ):\n        while not await ｊｏｂ.ｄｏｎｅ():\n            await ａｓｙｎｃｉｏ.ｓｌｅｅｐ(ｓｅｌｆ._ｐｏｌｌ_ｓｅｃｏｎｄｓ)\n",
            ),
        ),
        0,
        id="no-fixed-sleep-in-loop-native-excluded-semantic-control",
    ),
    pytest.param(
        "no-hidden-constructor-fallback",
        "app/service.py",
        (
            ("pyproject.toml", "[project]\nname = 'example'\nversion = '0.1.0'\n"),
            ("app/__init__.py", "\n"),
            (
                "app/config.py",
                "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    MODEL: str = 'model'\nsettings = Settings()\n",
            ),
            (
                "app/service.py",
                "class Ｇｅｎｅｒａｔｏｒ:\n    def __ｉｎｉｔ__(ｓｅｌｆ, *, ｍｏｄｅｌ: ｓｔｒ) -> None:\n        ｓｅｌｆ.ｍｏｄｅｌ = ｍｏｄｅｌ\n\nｇｅｎｅｒａｔｏｒ = Ｇｅｎｅｒａｔｏｒ(ｍｏｄｅｌ='explicit')\n",
            ),
        ),
        0,
        id="no-hidden-constructor-fallback-native-excluded-semantic-control",
    ),
    pytest.param(
        "no-positional-psycopg-row-escape",
        "app/task_store.py",
        (
            (
                "app/task_store.py",
                'from ｐｓｙｃｏｐｇ import ＡｓｙｎｃＣｏｎｎｅｃｔｉｏｎ\nfrom ｐｓｙｃｏｐｇ.ｒｏｗｓ import ｃｌａｓｓ_ｒｏｗ\nfrom ｐｙｄａｎｔｉｃ import ＢａｓｅＭｏｄｅｌ\n\nclass ＴａｓｋＲｏｗ(ＢａｓｅＭｏｄｅｌ):\n    ｉｄ: ｓｔｒ\n    ｓｔａｔｅ: ｓｔｒ\n\nasync def ｌｏａｄ(ｃｏｎｎ: ＡｓｙｎｃＣｏｎｎｅｃｔｉｏｎ[ｔｕｐｌｅ[ｏｂｊｅｃｔ, ...]]):\n    async with ｃｏｎｎ.ｃｕｒｓｏｒ(ｒｏｗ_ｆａｃｔｏｒｙ=ｃｌａｓｓ_ｒｏｗ(ＴａｓｋＲｏｗ)) as ｃｕｒｓｏｒ:\n        await ｃｕｒｓｏｒ.ｅｘｅｃｕｔｅ("SELECT id, state FROM task")\n        return await ｃｕｒｓｏｒ.ｆｅｔｃｈｏｎｅ()\n',
            ),
        ),
        0,
        id="no-positional-psycopg-row-escape-native-excluded-semantic-control",
    ),
    pytest.param(
        "no-redundant-module-alias-exports",
        "pagination.py",
        (
            (
                "pagination.py",
                "def ｅｎｃｏｄｅ_ｐｈｏｎｅ_ｎｕｍｂｅｒ_ｃｕｒｓｏｒ(ｖａｌｕｅ: ｓｔｒ) -> ｓｔｒ:\n    return ｖａｌｕｅ\n",
            ),
        ),
        0,
        id="no-redundant-module-alias-exports-native-excluded-semantic-control",
    ),
    pytest.param(
        "no-service-behavior-in-settings",
        "app/batch_settings.py",
        (
            (
                "app/batch_settings.py",
                "from ｄａｔａｃｌａｓｓｅｓ import ｄａｔａｃｌａｓｓ\n\n@ｄａｔａｃｌａｓｓ(ｆｒｏｚｅｎ=True, ｓｌｏｔｓ=True)\nclass ＢａｔｃｈＳｅｔｔｉｎｇｓ:\n    ｒｅｔｒｙ_ｌｉｍｉｔ: ｉｎｔ\n",
            ),
        ),
        0,
        id="no-service-behavior-in-settings-native-excluded-semantic-control",
    ),
    pytest.param(
        "no-swallowed-asyncio-cancellation",
        "worker.py",
        (
            (
                "worker.py",
                "import ａｓｙｎｃｉｏ\n\nasync def ｗｏｒｋｅｒ():\n    try:\n        await ａｓｙｎｃｉｏ.ｓｌｅｅｐ(10)\n    except ａｓｙｎｃｉｏ.ＣａｎｃｅｌｌｅｄＥｒｒｏｒ:\n        raise\n",
            ),
        ),
        0,
        id="no-swallowed-asyncio-cancellation-native-excluded-semantic-control",
    ),
    pytest.param(
        "no-unique-violation-message-match",
        "app/store.py",
        (
            (
                "app/store.py",
                "from ｐｓｙｃｏｐｇ import ｅｒｒｏｒｓ\n\ntry:\n    ｓａｖｅ()\nexcept ｅｒｒｏｒｓ.ＵｎｉｑｕｅＶｉｏｌａｔｉｏｎ as ｅｘｃ:\n    if ｅｘｃ.ｄｉａｇ.ｃｏｎｓｔｒａｉｎｔ_ｎａｍｅ == 'user_email_key':\n        raise ＤｕｐｌｉｃａｔｅＥｍａｉｌ from ｅｘｃ\n    raise\n",
            ),
        ),
        0,
        id="no-unique-violation-message-match-native-excluded-semantic-control",
    ),
    pytest.param(
        "prefer-autospec-for-callable-mock",
        "tests/test_delivery.py",
        (
            (
                "tests/test_delivery.py",
                "from ｕｎｉｔｔｅｓｔ.ｍｏｃｋ import ｃｒｅａｔｅ_ａｕｔｏｓｐｅｃ\ndef ｓｅｎｄ(*, ｒｅｃｉｐｉｅｎｔ: ｓｔｒ) -> None:\n    pass\ndef ｔｅｓｔ_ｓｅｎｄ():\n    ｄｏｕｂｌｅ = ｃｒｅａｔｅ_ａｕｔｏｓｐｅｃ(ｓｅｎｄ, ｓｐｅｃ_ｓｅｔ=True)\n    ｄｏｕｂｌｅ(ｒｅｃｉｐｉｅｎｔ='sample')\n",
            ),
        ),
        0,
        id="prefer-autospec-for-callable-mock-native-excluded-semantic-control",
    ),
    pytest.param(
        "prefer-monotonic-for-elapsed-time",
        "app/metrics.py",
        (
            (
                "app/metrics.py",
                "import ｔｉｍｅ\n\ndef ｍｅａｓｕｒｅ():\n    ｓｔａｒｔｅｄ = ｔｉｍｅ.ｍｏｎｏｔｏｎｉｃ()\n    ｗｏｒｋ()\n    return ｔｉｍｅ.ｍｏｎｏｔｏｎｉｃ() - ｓｔａｒｔｅｄ\n",
            ),
        ),
        0,
        id="prefer-monotonic-for-elapsed-time-native-excluded-semantic-control",
    ),
    pytest.param(
        "prefer-native-string-check",
        "tests/test_receipt.py",
        (
            (
                "tests/test_receipt.py",
                'def ｔｅｓｔ_ｒｅｃｅｉｐｔ():\n    ｖａｌｕｅ = ｒｅｃｅｉｐｔ["id"]\n    assert ｉｓｉｎｓｔａｎｃｅ(ｖａｌｕｅ, ｓｔｒ)\n    assert ｖａｌｕｅ == "abc"\n',
            ),
        ),
        0,
        id="prefer-native-string-check-native-excluded-semantic-control",
    ),
    pytest.param(
        "prefer-pydantic-json-value",
        "src/app/types.py",
        (("src/app/types.py", "from ｐｙｄａｎｔｉｃ import ＪｓｏｎＶａｌｕｅ\nｖａｌｕｅ: ＪｓｏｎＶａｌｕｅ\n"),),
        0,
        id="prefer-pydantic-json-value-native-excluded-semantic-control",
    ),
    pytest.param(
        "prefer-set-isdisjoint",
        "app/policy.py",
        (
            (
                "app/policy.py",
                "ａｌｌｏｗｅｄ = {'read', 'write'}\nｒｅｑｕｅｓｔｅｄ = ｓｅｔ(ｓｃｏｐｅｓ)\nif ａｌｌｏｗｅｄ.ｉｓｄｉｓｊｏｉｎｔ(ｒｅｑｕｅｓｔｅｄ):\n    ｄｅｎｙ()\n",
            ),
        ),
        0,
        id="prefer-set-isdisjoint-native-excluded-semantic-control",
    ),
    pytest.param(
        "prefer-str-enum",
        "app/order.py",
        (
            (
                "app/order.py",
                'from ｅｎｕｍ import ＳｔｒＥｎｕｍ\n\nclass Ｓｔａｔｕｓ(ＳｔｒＥｎｕｍ):\n    ＰＥＮＤＩＮＧ = "pending"\n    ＳＨＩＰＰＥＤ = "shipped"\n\nclass Ｏｒｄｅｒ:\n    ｓｔａｔｕｓ: Ｓｔａｔｕｓ = Ｓｔａｔｕｓ.ＰＥＮＤＩＮＧ\n',
            ),
        ),
        0,
        id="prefer-str-enum-native-excluded-semantic-control",
    ),
    pytest.param(
        "prefer-struct-over-namedtuple",
        "models.py",
        (
            (
                "models.py",
                "from ｔｙｐｉｎｇ import ＮａｍｅｄＴｕｐｌｅ\n\nclass Ｒｏｗ(ＮａｍｅｄＴｕｐｌｅ):\n    ｉｄ: ｉｎｔ\n    ｎａｍｅ: ｓｔｒ\n\nｒｏｗ = Ｒｏｗ(1, 'Ada')\nｉｄ, ｎａｍｅ = ｒｏｗ\n",
            ),
        ),
        0,
        id="prefer-struct-over-namedtuple-native-excluded-semantic-control",
    ),
    pytest.param(
        "prefer-walrus-regex-match",
        "app/parser.py",
        (
            (
                "app/parser.py",
                'import ｒｅ\n\ndef ｆｉｒｓｔ_ｎｕｍｂｅｒ(ｔｅｘｔ: ｓｔｒ) -> ｓｔｒ | None:\n    if (match := ｒｅ.ｓｅａｒｃｈ(r"\\d+", ｔｅｘｔ)):\n        return match.ｇｒｏｕｐ(0)\n    return None\n',
            ),
        ),
        0,
        id="prefer-walrus-regex-match-native-excluded-semantic-control",
    ),
    pytest.param(
        "production-derived-test-cases",
        "app/tests/test_models.py",
        (
            (
                "app/tests/test_models.py",
                "import ｐｙｔｅｓｔ\nfrom ａｐｐ.ｍｏｄｅｌｓ import ＥＬＩＧＩＢＬＥ_ＭＯＤＥＬＳ\n\nＥＸＰＥＣＴＥＤ_ＭＯＤＥＬＳ = ('a', 'b')\n\ndef ｔｅｓｔ_ｍｏｄｅｌ_ｍｅｍｂｅｒｓｈｉｐ():\n    assert ＥＬＩＧＩＢＬＥ_ＭＯＤＥＬＳ == ＥＸＰＥＣＴＥＤ_ＭＯＤＥＬＳ\n\n@ｐｙｔｅｓｔ.ｍａｒｋ.ｐａｒａｍｅｔｒｉｚｅ('model', ＥＸＰＥＣＴＥＤ_ＭＯＤＥＬＳ)\ndef ｔｅｓｔ_ｍｏｄｅｌ(ｍｏｄｅｌ):\n    assert ｂｕｉｌｄ(ｍｏｄｅｌ).ｔｉｅｒ == 'priority'\n",
            ),
        ),
        0,
        id="production-derived-test-cases-native-excluded-semantic-control",
    ),
    pytest.param(
        "require-explicit-psycopg-transaction",
        "repository.py",
        (
            (
                "repository.py",
                'from ｐｓｙｃｏｐｇ_ｐｏｏｌ import ＡｓｙｎｃＣｏｎｎｅｃｔｉｏｎＰｏｏｌ\nasync def ｓａｖｅ(ｐｏｏｌ: ＡｓｙｎｃＣｏｎｎｅｃｔｉｏｎＰｏｏｌ):\n    async with ｐｏｏｌ.ｃｏｎｎｅｃｔｉｏｎ() as ｃｏｎｎ, ｃｏｎｎ.ｔｒａｎｓａｃｔｉｏｎ():\n        await ｃｏｎｎ.ｅｘｅｃｕｔｅ("SELECT id FROM items FOR UPDATE")\n        await ｃｏｎｎ.ｅｘｅｃｕｔｅ("UPDATE items SET n = 1")\n',
            ),
        ),
        0,
        id="require-explicit-psycopg-transaction-native-excluded-semantic-control",
    ),
    pytest.param(
        "require-injectable-retry-sleep",
        "app/retry.py",
        (
            (
                "app/retry.py",
                "from ｃｏｌｌｅｃｔｉｏｎｓ.ａｂｃ import Ａｗａｉｔａｂｌｅ, Ｃａｌｌａｂｌｅ\n\nfrom ｔｅｎａｃｉｔｙ import ＡｓｙｎｃＲｅｔｒｙｉｎｇ, ｓｔｏｐ_ａｆｔｅｒ_ａｔｔｅｍｐｔ, ｗａｉｔ_ｅｘｐｏｎｅｎｔｉａｌ\n\n\ndef ｃｌｉｅｎｔ_ｒｅｔｒｙｉｎｇ(ｓｌｅｅｐ: Ｃａｌｌａｂｌｅ[[ｆｌｏａｔ], Ａｗａｉｔａｂｌｅ[None]]) -> ＡｓｙｎｃＲｅｔｒｙｉｎｇ:\n    return ＡｓｙｎｃＲｅｔｒｙｉｎｇ(ｓｌｅｅｐ=ｓｌｅｅｐ, ｓｔｏｐ=ｓｔｏｐ_ａｆｔｅｒ_ａｔｔｅｍｐｔ(4), ｗａｉｔ=ｗａｉｔ_ｅｘｐｏｎｅｎｔｉａｌ(ｍｕｌｔｉｐｌｉｅｒ=2))\n",
            ),
        ),
        0,
        id="require-injectable-retry-sleep-native-excluded-semantic-control",
    ),
    pytest.param(
        "require-nodecode-for-splitting-settings-field",
        "app/settings.py",
        (
            (
                "app/settings.py",
                "import ｏｓ\nfrom ｔｙｐｉｎｇ import Ａｎｎｏｔａｔｅｄ\nfrom ｐｙｄａｎｔｉｃ import ｆｉｅｌｄ_ｖａｌｉｄａｔｏｒ\nfrom ｐｙｄａｎｔｉｃ_ｓｅｔｔｉｎｇｓ import ＢａｓｅＳｅｔｔｉｎｇｓ, ＮｏＤｅｃｏｄｅ\n\nclass Ｓｅｔｔｉｎｇｓ(ＢａｓｅＳｅｔｔｉｎｇｓ):\n    ｅｍａｉｌｓ: Ａｎｎｏｔａｔｅｄ[ｌｉｓｔ[ｓｔｒ], ＮｏＤｅｃｏｄｅ]\n    @ｆｉｅｌｄ_ｖａｌｉｄａｔｏｒ('emails', ｍｏｄｅ='before')\n    @ｃｌａｓｓｍｅｔｈｏｄ\n    def ｓｐｌｉｔ_ｅｍａｉｌｓ(ｃｌｓ, ｖａｌｕｅ):\n        return ｖａｌｕｅ.ｓｐｌｉｔ(',')\n\nｏｓ.ｅｎｖｉｒｏｎ['EMAILS'] = 'one@example.com,two@example.com'\nＳｅｔｔｉｎｇｓ()\n",
            ),
        ),
        0,
        id="require-nodecode-for-splitting-settings-field-native-excluded-semantic-control",
    ),
    pytest.param(
        "require-port-for-service",
        "app/native.py",
        (
            ("pyproject.toml", '[project]\nname = "boundary-example"\nversion = "0.1.0"\n'),
            (
                "app/native.py",
                "from ｔｙｐｉｎｇ import Ｐｒｏｔｏｃｏｌ, ｆｉｎａｌ\n\nclass Ｂａｃｋｅｎｄ(Ｐｒｏｔｏｃｏｌ):\n    def ｒｅａｄ(ｓｅｌｆ) -> ｓｔｒ: ...\n    def ｗｒｉｔｅ(ｓｅｌｆ, ｖａｌｕｅ: ｓｔｒ) -> None: ...\n\nclass Ｏｐｅｒａｔｉｏｎｓ(Ｐｒｏｔｏｃｏｌ):\n    def ｒｅａｄ(ｓｅｌｆ) -> ｓｔｒ: ...\n    def ｗｒｉｔｅ(ｓｅｌｆ, ｖａｌｕｅ: ｓｔｒ) -> None: ...\n\n@ｆｉｎａｌ\nclass Ｃｏｏｒｄｉｎａｔｏｒ:\n    def __ｉｎｉｔ__(ｓｅｌｆ) -> None:\n        ｓｅｌｆ.ｂａｃｋｅｎｄ: Ｂａｃｋｅｎｄ = ｎａｔｉｖｅ_ｂａｃｋｅｎｄ()\n    def ｒｅａｄ(ｓｅｌｆ) -> ｓｔｒ:\n        return ｓｅｌｆ.ｂａｃｋｅｎｄ.ｒｅａｄ()\n    def ｗｒｉｔｅ(ｓｅｌｆ, ｖａｌｕｅ: ｓｔｒ) -> None:\n        ｓｅｌｆ.ｂａｃｋｅｎｄ.ｗｒｉｔｅ(ｖａｌｕｅ)\n\ndef ｃｏｏｒｄｉｎａｔｏｒ() -> Ｏｐｅｒａｔｉｏｎｓ:\n    return Ｃｏｏｒｄｉｎａｔｏｒ()\n\nclass Ｃｏｎｓｕｍｅｒ:\n    def ｒｅｃｅｉｖｅ(ｓｅｌｆ) -> ｓｔｒ:\n        return ｃｏｏｒｄｉｎａｔｏｒ().ｒｅａｄ()\n    def ｓｅｎｄ(ｓｅｌｆ, ｖａｌｕｅ: ｓｔｒ) -> None:\n        ｃｏｏｒｄｉｎａｔｏｒ().ｗｒｉｔｅ(ｖａｌｕｅ)\n",
            ),
        ),
        0,
        id="require-port-for-service-native-excluded-semantic-control",
    ),
    pytest.param(
        "require-public-dependency-contract",
        "app/consumer.py",
        (
            ("app/__init__.py", "# package\n"),
            (
                "app/publisher.py",
                "from abc import ABC, abstractmethod\nclass Publisher(ABC):\n    @abstractmethod\n    def publish(self) -> None: ...\nclass HttpPublisher(Publisher):\n    def publish(self) -> None: ...\nclass QueuePublisher(Publisher):\n    def publish(self) -> None: ...\n",
            ),
            (
                "app/consumer.py",
                "from ａｐｐ.ｐｕｂｌｉｓｈｅｒ import Ｐｕｂｌｉｓｈｅｒ, ＨｔｔｐＰｕｂｌｉｓｈｅｒ\nclass Ｃｏｎｓｕｍｅｒ:\n    def __ｉｎｉｔ__(ｓｅｌｆ, ｐｕｂｌｉｓｈｅｒ: Ｐｕｂｌｉｓｈｅｒ) -> None: ｓｅｌｆ.ｐｕｂｌｉｓｈｅｒ = ｐｕｂｌｉｓｈｅｒ\n    def ｒｕｎ(ｓｅｌｆ) -> None: ｓｅｌｆ.ｐｕｂｌｉｓｈｅｒ.ｐｕｂｌｉｓｈ()\n",
            ),
        ),
        0,
        id="require-public-dependency-contract-native-excluded-semantic-control",
    ),
    pytest.param(
        "require-pydantic-for-external-json",
        "protocol.py",
        (
            (
                "protocol.py",
                "import ｈｔｔｐｘ\n\nclass Ｅｎｖｅｌｏｐｅ:\n    def __ｉｎｉｔ__(ｓｅｌｆ, ｂｏｄｙ):\n        ｓｅｌｆ.ｂｏｄｙ = ｂｏｄｙ\n    def ｐａｙｌｏａｄ(ｓｅｌｆ):\n        return ｓｅｌｆ.ｂｏｄｙ\n\ndef ｗｒａｐ(ｂｏｄｙ):\n    return Ｅｎｖｅｌｏｐｅ(ｂｏｄｙ)\n\ndef ｆｅｔｃｈ():\n    ｒｅｍｏｔｅ = ｈｔｔｐｘ.ｇｅｔ('https://api.example/report').ｊｓｏｎ()\n    return ｗｒａｐ({'version': 1}).ｐａｙｌｏａｄ()['version']\n",
            ),
        ),
        0,
        id="require-pydantic-for-external-json-native-excluded-semantic-control",
    ),
    pytest.param(
        "require-pydantic-ordinal-lower-bound",
        "api.py",
        (
            (
                "api.py",
                "from ｐｙｄａｎｔｉｃ import ＢａｓｅＭｏｄｅｌ, Ｆｉｅｌｄ, ＰｏｓｉｔｉｖｅＩｎｔ\n\nclass ＣａｌｌＤｅｔａｉｌ(ＢａｓｅＭｏｄｅｌ):\n    ｒｅｔｒｙ_ａｔｔｅｍｐｔ_ｎｕｍｂｅｒ: ＰｏｓｉｔｉｖｅＩｎｔ = Ｆｉｅｌｄ(ｄｅｆａｕｌｔ=1, ｄｅｓｃｒｉｐｔｉｏｎ='Which dial this call is within its retry group (1 for the first attempt).')\n",
            ),
        ),
        0,
        id="require-pydantic-ordinal-lower-bound-native-excluded-semantic-control",
    ),
    pytest.param(
        "shared-mutable-pydantic-factory",
        "app/models.py",
        (
            (
                "app/models.py",
                "from ｐｙｄａｎｔｉｃ import ＢａｓｅＭｏｄｅｌ, Ｆｉｅｌｄ\nclass Ｍｏｄｅｌ(ＢａｓｅＭｏｄｅｌ):\n    ｖａｌｕｅｓ: ｌｉｓｔ[ｉｎｔ] = Ｆｉｅｌｄ(ｄｅｆａｕｌｔ_ｆａｃｔｏｒｙ=ｌｉｓｔ)\n",
            ),
        ),
        0,
        id="shared-mutable-pydantic-factory-native-excluded-semantic-control",
    ),
    pytest.param(
        "subprocess-kill-without-reap",
        "app/processes.py",
        (
            (
                "app/processes.py",
                "import ｓｕｂｐｒｏｃｅｓｓ\ndef ｒｕｎ(ａｒｇｓ):\n    ｐｒｏｃｅｓｓ = ｓｕｂｐｒｏｃｅｓｓ.Ｐｏｐｅｎ(ａｒｇｓ)\n    try:\n        ｐｒｏｃｅｓｓ.ｃｏｍｍｕｎｉｃａｔｅ(ｔｉｍｅｏｕｔ=1)\n    except ｓｕｂｐｒｏｃｅｓｓ.ＴｉｍｅｏｕｔＥｘｐｉｒｅｄ:\n        ｐｒｏｃｅｓｓ.ｋｉｌｌ()\n        ｐｒｏｃｅｓｓ.ｃｏｍｍｕｎｉｃａｔｅ()\n",
            ),
        ),
        0,
        id="subprocess-kill-without-reap-native-excluded-semantic-control",
    ),
    pytest.param(
        "typed-error-reasons",
        "app/errors.py",
        (
            (
                "app/errors.py",
                "class ＭｉｓｓｉｎｇＦｉｌｅｓＥｒｒｏｒ(Ｅｘｃｅｐｔｉｏｎ):\n    def __ｉｎｉｔ__(ｓｅｌｆ, ｐａｔｈｓ: ｌｉｓｔ[ｓｔｒ]) -> None:\n        ｓｅｌｆ.ｐａｔｈｓ = ｐａｔｈｓ\n        ｓｕｐｅｒ().__ｉｎｉｔ__('Files are missing')\n\ndef ｒｅｎｄｅｒ_ｅｒｒｏｒ(ｅｒｒｏｒ: ＭｉｓｓｉｎｇＦｉｌｅｓＥｒｒｏｒ) -> ｓｔｒ:\n    return ', '.ｊｏｉｎ(ｅｒｒｏｒ.ｐａｔｈｓ)\n",
            ),
        ),
        0,
        id="typed-error-reasons-native-excluded-semantic-control",
    ),
    pytest.param(
        "unused-test-factory-option",
        "tests/test_widget.py",
        (
            (
                "tests/test_widget.py",
                "def _ｒｅａｄ():\n    return 'ready'\ndef _ｍａｋｅ_ｗｉｄｇｅｔ(*, ｒｅａｄ=_ｒｅａｄ):\n    return Ｗｉｄｇｅｔ(ｒｅａｄ=ｒｅａｄ)\n_ｍａｋｅ_ｗｉｄｇｅｔ()\n_ｍａｋｅ_ｗｉｄｇｅｔ(ｒｅａｄ=_ｒｅａｄ)\n",
            ),
        ),
        0,
        id="unused-test-factory-option-native-excluded-semantic-control",
    ),
)


@pytest.mark.parametrize(("rule_id", "focus", "files", "expected"), _NATIVE_SYMBOL_CASES)
def test_native_semantic_contract_reaches_existing_ast_owner(
    tmp_path: Path, rule_id: str, focus: str, files: tuple[tuple[str, str], ...], expected: int
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="public-native-gate"\nversion="0.1.0"\n')
    paths: list[Path] = []
    for relative, source in files:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        paths.append(path)
        if relative == focus:
            compile(source, relative, "exec")
    findings = analyze([rule_id], paths)
    assert sum(finding.path == tmp_path / focus for finding in findings) == expected
    assert analyze([rule_id], paths) == findings


def test_ascii_symbol_view_preserves_original_object() -> None:
    source = "value = 'original ASCII data'\n"
    context = PythonFileContext(Path("service.py"), source)
    assert context.symbol_source is source
    assert context.source is source


def test_compatibility_symbol_view_never_replaces_parser_data_or_locations() -> None:
    source = "ｖａｌｕｅ = 'ｄａｔａ'\n"
    context = PythonFileContext(Path("service.py"), source)
    assert context.symbol_source == "value = 'data'\n"
    assert context.symbol_source is context.symbol_source
    assert context.source is source
    assert context.source_lines == ["ｖａｌｕｅ = 'ｄａｔａ'"]
    tree = context.tree
    assert tree is not None
    [statement] = tree.body
    assert isinstance(statement, ast.Assign)
    assert isinstance(statement.value, ast.Constant)
    assert statement.value.value == "ｄａｔａ"
    assert ast.get_source_segment(source, statement.value) == "'ｄａｔａ'"


def test_symbol_hints_do_not_make_non_native_source_parseable() -> None:
    source = "value ＝ 1\n"
    assert symbol_prefilter_source(source) == "value = 1\n"
    assert PythonFileContext(Path("service.py"), source).tree is None


def test_symbol_view_is_cached_once_without_changing_original_native_positions() -> None:
    source = "π = 0; ｖａｌｕｅ = 'ｄａｔａ'\n"
    context = PythonFileContext(Path("service.py"), source)
    assert "symbol_source" not in vars(context)
    first = context.symbol_source
    assert vars(context)["symbol_source"] is first
    assert context.symbol_source is first
    assert context.source is source
    assert context.source.encode("utf-8") == source.encode("utf-8")
    assert context.source_lines == [source.rstrip("\n")]
    tree = context.tree
    assert tree is not None
    native_tree = ast.parse(source)
    assert ast.dump(tree, include_attributes=True) == ast.dump(native_tree, include_attributes=True)
    statement = tree.body[1]
    assert isinstance(statement, ast.Assign)
    literal = statement.value
    assert isinstance(literal, ast.Constant)
    assert literal.value == "ｄａｔａ"
    assert literal.col_offset == len("π = 0; ｖａｌｕｅ = ".encode())
    assert ast.get_source_segment(context.source, literal) == "'ｄａｔａ'"


def test_normalized_module_export_name_keeps_original_utf8_diagnostic_column(tmp_path: Path) -> None:
    source = 'π = 0; __ａｌｌ__ = ["value"]\nvalue = 1\n'
    path = tmp_path / "service.py"
    path.write_text(source)
    compile(source, str(path), "exec")
    [finding] = analyze(["no-dunder-all"], [path])
    assert (finding.line, finding.col, finding.code) == (1, 9, "SARJ438")
    assert path.read_text() == source


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("class\tRecord:\n    value: set[str]\n", id="tab-native-class-header"),
        pytest.param("class Record:\n    value: set[str]\n", id="ascii-native-class-header"),
        pytest.param("class Ｒｅｃｏｒｄ:\n    ｖａｌｕｅ: ｓｅｔ[ｓｔｒ]\n", id="normalized-native-class-fields"),
        pytest.param("from typing import NewType\nToken = NewType ('Token', int)\n", id="spaced-native-nominal-call"),
        pytest.param(
            "from ｔｙｐｉｎｇ import ＮｅｗＴｙｐｅ\nＴｏｋｅｎ = ＮｅｗＴｙｐｅ ('Token', ｉｎｔ)\n",
            id="normalized-native-nominal-call",
        ),
        pytest.param(
            "def display(value):\n    match\tvalue:\n        case str () as text: return text\n",
            id="spaced-native-match-header",
        ),
    ],
)
def test_project_admission_retains_original_native_ast_and_source(source: str) -> None:
    compile(source, "models.py", "exec")
    index = ProjectIndexSet.single(Path("models.py"), source)
    unit = index.unit(Path("models.py"))
    assert unit is not None
    assert unit.source is source
    assert unit.tree is not None
    assert ast.dump(unit.tree, include_attributes=True) == ast.dump(ast.parse(source), include_attributes=True)


def test_project_symbol_hint_in_literal_does_not_create_a_class_fact() -> None:
    source = "text = 'class Fake: pass'\n"
    index = ProjectIndexSet.single(Path("models.py"), source)
    unit = index.unit(Path("models.py"))
    assert unit is not None
    assert unit.tree is not None
    assert index.class_for(unit, ast.Name(id="Fake")) is None
    [statement] = unit.tree.body
    assert isinstance(statement, ast.Assign)
    assert isinstance(statement.value, ast.Constant)
    assert statement.value.value == "class Fake: pass"

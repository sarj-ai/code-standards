from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_class_row import PreferClassRow
from sarj_python_lint.rules.prefer_collection_comprehension import PreferCollectionComprehension
from sarj_python_lint.rules.prefer_declarative_batch_validation import PreferDeclarativeBatchValidation


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_PATH = Path("app/batches.py")
_MODEL = "from pydantic import BaseModel, ValidationError\nfrom loguru import logger\n\nclass Item(BaseModel):\n    value: int\n\n"


def _check(source: str, *, header: str = _MODEL, path: Path = _PATH) -> list[Diagnostic]:
    return PreferDeclarativeBatchValidation().check(path, header + textwrap.dedent(source))


BATCH_CASES = tuple(
    EvaluationCase(
        case_id=case_id,
        language=Language.PYTHON,
        source=_MODEL + source,
        expected=expected,
    )
    for case_id, source, expected in (
        (
            "homogeneous-list-comprehension",
            "def load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]\n",
            ExpectedOutcome.MATCH,
        ),
        (
            "drop-with-append-in-try",
            "def load(rows: list[object]):\n    result = []\n    for row in rows:\n        try:\n            result.append(Item.model_validate(row))\n        except ValidationError as exc:\n            logger.warning('invalid record', error=str(exc))\n    return result\n",
            ExpectedOutcome.MATCH,
        ),
        (
            "drop-then-append-after-try",
            "def load(rows: list[object]):\n    result: list[Item] = []\n    for row in rows:\n        try:\n            item = Item.model_validate(row)\n        except ValidationError:\n            logger.exception('invalid record')\n            continue\n        result.append(item)\n    return result\n",
            ExpectedOutcome.MATCH,
        ),
        (
            "reject-batch-declaratively",
            "from pydantic import RootModel\nclass Items(RootModel[list[Item]]):\n    pass\ndef load(rows: list[object]):\n    return Items.model_validate(rows).root\n",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "ruff-owns-simple-append-loop",
            "def load(rows: list[object]):\n    result = []\n    for row in rows:\n        result.append(Item.model_validate(row))\n    return result\n",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "explicit-rejection-report",
            "def load(rows: list[object]):\n    result = []\n    errors = []\n    for row in rows:\n        try:\n            result.append(Item.model_validate(row))\n        except ValidationError as exc:\n            errors.append(exc)\n    return result, errors\n",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "streaming-contract",
            "from collections.abc import Iterator\ndef load(rows: Iterator[object]):\n    return [Item.model_validate(row) for row in rows]\n",
            ExpectedOutcome.NO_MATCH,
        ),
    )
)


@pytest.mark.parametrize("case", BATCH_CASES, ids=tuple(case.case_id for case in BATCH_CASES))
def test_labeled_batch_cases(case: EvaluationCase) -> None:
    findings = PreferDeclarativeBatchValidation().check(_PATH, case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1


@pytest.mark.parametrize(
    "body",
    [
        "try:\n    item = Item.model_validate(row)\n    result.append(item)\nexcept ValidationError:\n    logger.warning('invalid')",
        "try:\n    item = Item.model_validate(row)\nexcept ValidationError:\n    logger.warning('invalid')\nelse:\n    result.append(item)",
        "try:\n    result.append(Item.model_validate(row))\nexcept ValidationError:\n    logger.warning('invalid')\n    continue",
    ],
    ids=["local-in-try", "append-in-else", "explicit-continue"],
)
def test_supported_drop_loop_shapes(body: str) -> None:
    source = "def load(rows: list[object]):\n    result = []\n    for row in rows:\n"
    source += textwrap.indent(body, "        ") + "\n    return result\n"
    [finding] = _check(source)
    assert finding.code == "SARJ494"
    assert finding.severity is Severity.WARNING
    assert finding.line == 9
    assert "RootModel" in finding.message
    assert "class_row" in finding.message
    assert "reject" in finding.message
    assert "TypeAdapter" not in finding.message


@pytest.mark.parametrize(
    ("header", "source"),
    [
        (
            "import pydantic as pd\nclass Item(pd.BaseModel):\n    value: int\n",
            "def load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]",
        ),
        (
            "from pydantic.main import BaseModel as Schema\nclass Parent(Schema):\n    value: int\nclass Item(Parent):\n    pass\n",
            "def load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]",
        ),
        (
            _MODEL + "Alias = Item\n",
            "def load(rows: list[object]):\n    return [Alias.model_validate(row) for row in rows]",
        ),
        (
            _MODEL + "from collections.abc import Sequence as Batch\n",
            "def load(rows: Batch[object]):\n    return [Item.model_validate(row) for row in rows]",
        ),
        (
            _MODEL,
            "def load():\n    rows = [{'value': 1}]\n    return [Item.model_validate(row) for row in rows]",
        ),
        (
            _MODEL,
            "def load(rows: tuple[object, ...]):\n    return [Item.model_validate(row) for row in rows]",
        ),
        (
            _MODEL,
            "def unrelated(Item):\n    return Item\ndef load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]",
        ),
        (
            _MODEL,
            "class Owner:\n    Item = custom\n    def load(self, rows: list[object]):\n        return [Item.model_validate(row) for row in rows]",
        ),
    ],
    ids=[
        "module-alias",
        "inherited-model",
        "model-alias",
        "sequence-alias",
        "literal-batch",
        "tuple-batch",
        "separate-scope-shadow",
        "class-scope-is-not-method-scope",
    ],
)
def test_proven_models_and_batch_aliases(header: str, source: str) -> None:
    assert len(_check(source, header=header)) == 1


@pytest.mark.parametrize(
    "logging_call",
    [
        "logger.success('invalid')",
        "logger.trace('invalid')",
        "logger.log('WARNING', 'invalid')",
        "logging.warn('invalid')",
        "logging.fatal('invalid')",
    ],
    ids=["loguru-success", "loguru-trace", "loguru-log", "logging-warn", "logging-fatal"],
)
def test_shared_logging_methods(logging_call: str) -> None:
    source = (
        "import logging\ndef load(rows: list[object]):\n    result = []\n    for row in rows:\n"
        "        try:\n            result.append(Item.model_validate(row))\n"
        f"        except ValidationError:\n            {logging_call}\n"
        "    return result\n"
    )
    assert len(_check(source)) == 1


def test_exception_and_logger_import_aliases() -> None:
    source = """
        from pydantic_core import ValidationError as Invalid
        from loguru import logger as log
        def load(rows: list[object]):
            result = []
            for row in rows:
                try:
                    result.append(Item.model_validate(row))
                except Invalid:
                    log.warning('invalid')
            return result
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize("inside_cursor", [True, False], ids=["inside-cursor", "after-cursor"])
def test_materialized_attribute_rows_use_the_original_incident_shape(inside_cursor: bool) -> None:
    source = """
        from typing import NamedTuple
        from psycopg.rows import class_row
        class StoredRow(NamedTuple):
            value: int
        async def load(conn):
            async with conn.cursor(row_factory=class_row(StoredRow)) as cursor:
                rows = await cursor.fetchall()
            result: list[Item] = []
            for row in rows:
                try:
                    item = Item.model_validate(row, from_attributes=True)
                except ValidationError:
                    logger.exception('invalid stored row', value=row.value)
                    continue
                result.append(item)
            return result
    """
    if inside_cursor:
        source = textwrap.dedent(source)
        start = source.index("    result: list[Item] = []")
        source = source[:start] + textwrap.indent(source[start:], "    ")
    assert len(_check(source)) == 1


def test_parent_model_has_a_proven_row_factory_and_collection_consumer() -> None:
    source = """
        from psycopg.rows import class_row
        from pydantic import RootModel
        class Display(Item):
            pass
        class Items(RootModel[list[Item]]):
            pass
        async def names(conn):
            async with conn.cursor(row_factory=class_row(Item)) as cursor:
                return await cursor.fetchall()
        async def load(conn):
            async with conn.cursor(row_factory=class_row(Item)) as cursor:
                rows = await cursor.fetchall()
                result: list[Display] = []
                for row in rows:
                    try:
                        item = Display.model_validate(row, from_attributes=True)
                    except ValidationError:
                        logger.exception('invalid', value=row.value)
                        continue
                    result.append(item)
                return result
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "mutation",
    ["cursor.fetchall = lazy_stream", "cursor.row_factory = custom"],
    ids=["fetch-method", "row-factory"],
)
def test_mutated_cursor_does_not_prove_materialized_rows(mutation: str) -> None:
    source = "from psycopg.rows import class_row\nasync def load(conn):\n    async with conn.cursor(row_factory=class_row(Item)) as cursor:\n"
    source += f"        {mutation}\n        return [Item.model_validate(row) for row in await cursor.fetchall()]\n"
    assert _check(source) == []


def test_fetch_after_cursor_context_does_not_prove_materialized_rows() -> None:
    source = """
        from psycopg.rows import class_row
        async def load(conn):
            async with conn.cursor(row_factory=class_row(Item)) as cursor:
                pass
            return [Item.model_validate(row) for row in await cursor.fetchall()]
    """
    assert _check(source) == []


def test_existing_class_row_owner_takes_precedence() -> None:
    source = _MODEL + textwrap.dedent("""
        from psycopg.rows import dict_row
        async def load(conn):
            async with conn.cursor(row_factory=dict_row) as cursor:
                rows = await cursor.fetchall()
                return [Item.model_validate(row) for row in rows]
    """)
    assert len(PreferClassRow().check(_PATH, source)) == 1
    assert PreferDeclarativeBatchValidation().check(_PATH, source) == []


def test_dict_row_drop_loop_is_not_owned_by_the_existing_conversion_rule() -> None:
    source = _MODEL + textwrap.dedent("""
        from psycopg.rows import dict_row
        async def load(conn):
            async with conn.cursor(row_factory=dict_row) as cursor:
                result = []
                for row in await cursor.fetchall():
                    try:
                        result.append(Item.model_validate(row))
                    except ValidationError:
                        logger.warning('invalid')
                return result
    """)
    assert PreferClassRow().check(_PATH, source) == []
    assert len(PreferDeclarativeBatchValidation().check(_PATH, source)) == 1


def test_database_precedence_does_not_hide_an_independent_batch() -> None:
    source = _MODEL + textwrap.dedent("""
        from psycopg.rows import dict_row
        async def load(conn, payload: list[object]):
            async with conn.cursor(row_factory=dict_row) as cursor:
                rows = await cursor.fetchall()
                first = [Item.model_validate(row) for row in rows]
                second = [Item.model_validate(row) for row in payload]
                return first, second
    """)
    [finding] = PreferDeclarativeBatchValidation().check(_PATH, source)
    assert finding.line == 13


@pytest.mark.parametrize(
    "source",
    [
        "def load(rows):\n    return [Item.model_validate(row) for row in rows]",
        "def load(rows: list[object], Item):\n    return [Item.model_validate(row) for row in rows]",
        "def load(rows: list[object]):\n    Item = custom\n    return [Item.model_validate(row) for row in rows]",
        "def load(rows: list[object]):\n    return [Item.model_validate(row, context=row) for row in rows]",
        "def load(rows: list[object]):\n    return [Item.model_validate(row, strict=True) for row in rows]",
        "def load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows if row]",
        "def load(rows: list[object]):\n    return [choose(row).model_validate(row) for row in rows]",
        "def load(rows: list[object]):\n    return [Item.model_validate(transform(row)) for row in rows]",
        "def load(rows: list[object]):\n    return [Item.model_validate(row) for row in iter(rows)]",
        "async def load(rows: list[object]):\n    return [Item.model_validate(row) async for row in rows]",
        "def load(rows: list[object]):\n    return (Item.model_validate(row) for row in rows)",
        "def load(rows: list[object]):\n    return [Item.model_validate(row) for batch in rows for row in batch]",
        "Item.model_validate = custom\ndef load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]",
        "borrow(Item)\ndef load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]",
        "Alias = Item\nAlias.model_validate = custom\ndef load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]",
        "def load(rows: list[object]):\n    global Item\n    return [Item.model_validate(row) for row in rows]",
        "def load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]\nItem = custom",
    ],
    ids=[
        "unknown-input",
        "model-parameter",
        "local-model-shadow",
        "varying-context",
        "validation-options",
        "filtered",
        "dynamic-model",
        "preprocessing",
        "iterator-call",
        "async-iterator",
        "lazy-generator",
        "nested-generator",
        "method-mutation",
        "model-escape",
        "alias-mutation",
        "global-model",
        "module-model-rebound",
    ],
)
def test_ambiguous_or_behavioral_comprehensions_are_clean(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "header",
    [
        "from app.models import Item\n",
        "class Item:\n    @classmethod\n    def model_validate(cls, row):\n        return row\n",
        "from pydantic import BaseModel\nclass Item(BaseModel):\n    @classmethod\n    def model_validate(cls, row):\n        return row\n",
        "from pydantic import BaseModel\nBaseModel = custom\nclass Item(BaseModel):\n    value: int\n",
        "import pydantic as pd\npd.BaseModel = custom\nclass Item(pd.BaseModel):\n    value: int\n",
        "from pydantic import BaseModel\nfrom app import *\nclass Item(BaseModel):\n    value: int\n",
        "from pydantic import BaseModel\n@decorate\nclass Item(BaseModel):\n    value: int\n",
        "from pydantic.v1 import BaseModel\nclass Item(BaseModel):\n    value: int\n",
        "from pydantic import BaseModel\nclass Item(BaseModel):\n    value: int\n    if True:\n        @classmethod\n        def model_validate(cls, row):\n            return row\n",
        "from pydantic import BaseModel\nclass Item(BaseModel):\n    value: int\n    if True:\n        from custom import model_validate\n",
        "import pydantic as pd\nother = pd\nother.BaseModel = custom\nclass Item(pd.BaseModel):\n    value: int\n",
        "from pydantic import BaseModel\nAlias = BaseModel\nAlias.model_validate = custom\nclass Item(BaseModel):\n    value: int\n",
        "import pydantic as pd\nAlias = pd.BaseModel\nAlias.model_validate = custom\nclass Item(pd.BaseModel):\n    value: int\n",
        "from pydantic import BaseModel\nborrow(BaseModel)\nclass Item(BaseModel):\n    value: int\n",
        "import pydantic as pd\npd.__setattr__('BaseModel', custom)\nclass Item(pd.BaseModel):\n    value: int\n",
    ],
    ids=[
        "unresolved-import",
        "same-method-name",
        "validation-override",
        "base-shadow",
        "module-mutation",
        "wildcard",
        "decorated-model",
        "pydantic-v1",
        "conditional-validation-method",
        "conditional-validation-import",
        "module-alias-mutation",
        "imported-base-alias-mutation",
        "qualified-base-alias-mutation",
        "imported-base-escape",
        "module-attribute-mutator",
    ],
)
def test_unproven_model_semantics_are_clean(header: str) -> None:
    source = "def load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]"
    assert _check(source, header=header) == []


@pytest.mark.parametrize(
    "handler",
    [
        "errors.append(exc)",
        "logger.warning('invalid')\nrejected.append(row)",
        "logger.warning('invalid')\nreturn result",
        "logger.warning('invalid')\nraise",
        "notify(row)",
        "logger.warning(format_error(exc))",
        "unknown_logger.warning('invalid')",
    ],
    ids=[
        "error-report",
        "rejection-report",
        "partial-return",
        "raise",
        "secondary-effect",
        "formatting-effect",
        "unknown-logger",
    ],
)
def test_handler_reporting_and_side_effects_are_clean(handler: str) -> None:
    source = "def load(rows: list[object]):\n    result = []\n    for row in rows:\n        try:\n            result.append(Item.model_validate(row))\n        except ValidationError as exc:\n"
    source += textwrap.indent(handler, "            ") + "\n    return result\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "def load(rows: list[object]):\n    result = shared\n    for row in rows:\n        try:\n            result.append(Item.model_validate(row))\n        except ValidationError:\n            logger.warning('invalid')\n    return result",
        "def load(rows: list[object]):\n    result = []\n    alias = result\n    for row in rows:\n        try:\n            result.append(Item.model_validate(row))\n        except ValidationError:\n            logger.warning('invalid')\n    return alias",
        "def load(rows: list[object]):\n    result = []\n    for row in rows:\n        try:\n            result.append(Item.model_validate(row))\n        except ValueError:\n            logger.warning('invalid')\n    return result",
        "def load(rows: list[object]):\n    result = []\n    for row in rows:\n        try:\n            result.append(Item.model_validate(row))\n        except ValidationError:\n            logger.warning('invalid')\n        finally:\n            cleanup(row)\n    return result",
        "def load(rows: list[object]):\n    result = []\n    for row in rows:\n        try:\n            result.append(Item.model_validate(row))\n            audit(row)\n        except ValidationError:\n            logger.warning('invalid')\n    return result",
        "def load(rows: list[object]):\n    result = []\n    for row in rows:\n        try:\n            result.append(Item.model_validate(row))\n        except ValidationError:\n            logger.warning('invalid')\n    print(row)\n    return result",
    ],
    ids=[
        "existing-collection",
        "collection-alias",
        "broad-error-contract",
        "finally",
        "success-side-effect",
        "leaking-loop-target",
    ],
)
def test_mutation_and_error_contract_near_misses_are_clean(source: str) -> None:
    assert _check(source) == []


def test_no_overlap_with_collection_comprehension_rule() -> None:
    case = next(case for case in BATCH_CASES if case.case_id == "drop-with-append-in-try")
    assert PreferCollectionComprehension().check(_PATH, case.source) == []
    assert len(PreferDeclarativeBatchValidation().check(_PATH, case.source)) == 1


def test_suppression_uses_the_reported_comprehension_line() -> None:
    source = "def load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]  # sarj-noqa: SARJ494 — collection error indices are intentionally stable"
    assert _check(source) == []


@pytest.mark.parametrize("path", [Path("vendor/batches.py"), Path("generated/batches.py")], ids=["vendor", "generated"])
def test_generated_and_vendor_sources_are_clean(path: Path) -> None:
    assert (
        _check("def load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]", path=path) == []
    )


def test_malformed_source_is_clean() -> None:
    assert _check("def load(:") == []


_PUBLIC_EXAMPLES = PreferDeclarativeBatchValidation.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferDeclarativeBatchValidation().check(Path(focus.path), focus.source)) == example.expected_count

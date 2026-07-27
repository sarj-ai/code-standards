"""SARJ059: a hand-rolled double of a third-party service should use the library that fakes it properly.

A dict standing in for S3, a class with a `.chat.completions.create` that returns a
canned string, a `FakeRedis` backed by a plain dict — each of these encodes one
engineer's memory of a wire protocol. They get the happy path right and every edge
wrong: S3 key prefixes and 404-vs-NoSuchKey, an LLM provider's streaming chunk shape
and `finish_reason`, Redis TTL semantics, SMTP envelope-vs-header addressing. The test
then passes against a protocol that does not exist, and the bug ships. For every one of
these services somebody has already written the fake properly and maintains it against
the real service; the fix is to delete the hand-rolled class and use it.

Fires when ALL of these hold:

* the file is a test file or a test-double module (`tests/`, `conftest.py`, a
  `testing/` or `test_fakes/` directory, or a `fakes.py` / `mocks.py` / `*_stub.py`
  stem) — this rule deliberately reaches the shared fake modules that
  `is_test_path` alone misses (noura-be's `common/testing/fakes.py`, bulbul's
  `bulbul/observability/langfuse_stub.py`),
* a module-level class name carries a test-double marker (`Mock`, `Fake`, `Stub`,
  `Dummy`, `InMemory`, `Scripted`, `Recording`, `Spy`),
* the class name — or the name of a base class it inherits — names a recognised
  *external* service with a maintained fake: S3/boto, other AWS services, GCS,
  BigQuery, Pub/Sub, Kafka, an LLM provider brand, Redis, Postgres/MySQL, Mongo,
  SMTP, httpx, requests, aiohttp, or the clock,
* the double has substance — at least 3 non-dunder methods, or at least 25 lines
  (`end_lineno - lineno + 1`, so a class spanning exactly 25 fires and one spanning
  24 does not) exposing at least two entry points (methods, or a nested connection
  class). A four-line stub is not worth a diagnostic, and it is certainly not worth
  a new dependency,
* and the recommended library is not already imported in the file.

The message names the specific library per service, because that is the entire value
of the rule: `moto` for S3, `fakeredis` for Redis, `respx`/`vcrpy` for an LLM
provider, `aiosmtpd` for SMTP, a `testcontainers` emulator for the rest.

Corpus evidence. Measured over 16 repositories, ~48,000 Python files: bulbul
(`/Users/nasrmaswood/code/bulbul/python`), noura-be
(`/Users/nasrmaswood/code/noura-be/python`), django, fastapi, celery, litellm,
langchain, prefect, sentry-python, airflow, mlflow, warehouse, superset, zulip,
dagster and saleor. Final counts: litellm 6, noura-be 2, warehouse 1, and **zero**
on the other thirteen — including airflow and mlflow, whose provider suites are
dense with cloud-service doubles but keep them small or already depend on `moto`.
Every one of the 9 findings was read against its source and classified a true
positive (0% FP). Each guard below marked *(FP found)* removed a real finding
during hardening. bulbul fires zero times: its doubles are all of its own ports or
of LiveKit plugin ABCs, and its `_StubGeminiClient` is a three-line namespace
holder.

The design is dominated by what the corpora actually contain: the overwhelming
majority of hand-written doubles in both first-party repos are doubles of the
project's *own* ports (`InMemoryUserStore`, `FakeCallService`,
`RecordingKnowledgeBaseService`, `FakeSubjectService`, ~60 of them), for which no
library exists and none should. Only a recognised external-service token fires.

**The complementary `monkeypatch`/`mock.patch` shape is deliberately out of scope.**
A sweep for patches of SDK entry points (`boto3.client`, `time.time`,
`httpx.AsyncClient.request`, `<module>.datetime`) returns a large population that is
dominated, on django and celery, by a library patching the `datetime` or `boto3`
symbol *inside its own module under test* (celery's `t/unit/backends/test_elasticsearch.py`
alone does it 13 times, django's `tests/schema/tests.py:5476`, `tests/utils_tests/test_http.py:414`).
Those are not hand-rolled service doubles, and nothing in the AST distinguishes them
from bulbul's genuine `mock.patch("agent.lk.silence_monitor.time.time")` clock
patches. Adding the shape would have traded a 0% FP rate for a majority-FP one.

Deliberately NOT flagged:

* **pytest's collection classes** *(FP found)*. `Test` is not a double marker, it is
  pytest's class-collection convention. bulbul and noura-be contain 150+
  `class TestFoo:` grouping classes and zero `Test`-prefixed doubles. The first
  version of this rule reported bulbul's
  `worker/tests/test_post_call_service_data_extraction.py:216`
  `class TestGeminiNullDataCollected` — a plain pytest group that happened to contain
  the words "Gemini" and "Null". Any class whose name starts with `test` is skipped,
  which also covers celery's lowercase spelling (`class test_MongoBackend_no_mock`),
* **doubles of the project's own domain types.** `FakeSubjectService`,
  `InMemoryUserStore`, `RecordingCronMonitor`, `FakeCallCapacityService` — a fake of
  your own port is the correct design and has no library. Only the branded external
  tokens in `_SERVICES` fire,
* **doubles of a framework's own extension point** *(FP found)*. LiveKit's `FakeRoom`,
  `FakeJobContext`, `FakeAgentSession`, `FakeSTT`, `FakeTTS`, `FakeVAD` and
  `ScriptedLLM` (noura-be `voice/tests/fakes.py`, bulbul `agent/tests/_infra/fakes.py`)
  implement plugin ABCs that no library fakes. Two defences. First, the LLM tokens are
  provider *brands* (`openai`, `anthropic`, `gemini`, `groq`, …) and never the generic
  `llm`, `completion`, `chat`, `session`, `room` or `job`, so `ScriptedLLM(lk_llm.LLM)`
  stays silent. Second, a class whose base is shaped like an abstract extension point
  (`Base…`, `Abstract…`, `…ABC`, `…Interface`, `…Mixin`) is skipped outright: langchain's
  `libs/langchain/tests/unit_tests/runnables/test_openai_functions.py:14`
  `FakeChatOpenAI(BaseChatModel)` and
  `libs/langchain_v1/tests/unit_tests/agents/middleware/implementations/test_summarization.py:1931`
  `_MockBedrockChatModel(BaseChatModel)` both fired before that guard, and both are
  plugin implementations whose brand names describe which provider they *imitate*,
  not an HTTP double `respx` could replace,
* **recording spies that delegate to the real client.** bulbul's
  `worker/tests/fakes/object_store.py:7` `RecordingObjectStore` forwards 8 of its 10
  methods straight to an injected `GCSObjectStore` — it hand-rolls nothing, it
  observes. Any class where at least half the methods, and at least two of them, are
  single-statement forwards to a same-named method on a `self.<attr>` is a decorator,
  not a fake. Both arms are boundaries, not slack: 2 forwards of 4 methods is a spy,
  2 of 5 is not, and 1 of 2 is not — the count arm is what keeps a single delegating
  convenience method on an otherwise hand-rolled double from silencing it,
* **data holders.** `MockSession(pydantic.BaseModel)`, `_FakeDtmfResult(NamedTuple)`,
  `FakeConnError(Exception)` — a canned value object is not a protocol implementation.
  Bases of `BaseModel`, `NamedTuple`, `TypedDict`, `Enum`, `Exception`, `Protocol`,
  `ABC` and any `unittest`/django `TestCase` are excluded. `@dataclass` is
  deliberately *not* excluded: litellm's
  `tests/test_litellm/proxy/utils/prisma_and_spend/conftest.py:249` `FakeClock` and
  `:323` `InMemorySMTP` are both dataclasses and both are genuine behaviour doubles.
  Counting only non-dunder methods separates the two shapes without needing the
  decorator,
* **classes nested inside functions or other classes.** A double declared inside one
  test function is scoped to that test; the 80-line shared fake this rule targets is
  always module-level. celery and django between them declare ~40 nested
  `class MockX:` throwaways, all of them noise,
* **files that already import the recommended library.** Importing `moto` and still
  writing a small S3 helper on top of it is fine — the protocol fidelity is already
  there. This is load-bearing on real code: litellm's
  `tests/llm_translation/test_vcr_redis_persister.py:413` defines
  `_FakeRedisWithInfo` in a module that already imports `fakeredis`, and airflow's AWS
  provider suite pairs its `FakeS3*` helpers with `moto`,
* **canned-data factories** *(FP found)*. dagster's
  `examples/ingestion-patterns/tests/conftest.py:32`
  `MockKafkaConsumerResource(dg.ConfigurableResource)` is 30 lines with a single
  `poll_messages` that returns a list comprehension of fabricated message dicts. It
  implements no part of the Kafka protocol, so "run a broker via testcontainers" is
  not a fix for it. The line-count arm therefore requires a second entry point,
* **small doubles.** django's `tests/humanize_tests/tests.py:20`
  `class MockDateTime(datetime.datetime)` is a single `now()` classmethod;
  django's `tests/forms_tests/tests/test_forms.py:2945` `class FakeTime` is three
  lines; django's own `django/test/utils.py:991` `NullTimeKeeper` is seven; prefect's
  `src/integrations/prefect-email/tests/conftest.py:32` `SMTPMock` has two real
  methods; airflow's `providers/mysql/tests/unit/mysql/hooks/test_mysql.py:322`
  `MockMySQLConnectorConnection` is a 13-line property holder. All of them name a
  service in `_SERVICES`, all of them are correct as written, and all of them fall
  under the substance floor. Django additionally ships its own `locmem` email backend
  and cache backends, so the SMTP recommendation must never reach it.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, NamedTuple, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


class _Service(NamedTuple):
    """A recognised external service and the maintained fake for it."""

    subject: str
    words: frozenset[str]
    infixes: tuple[str, ...]
    imports: frozenset[str]
    advice: str


# Ordered most-specific first; the first match wins. `words` match a single
# CamelCase word of the class name exactly (so `Requests` fires but celery's
# `FakeRequest` does not); `infixes` match the whole name with separators
# stripped (so `FakeBigQueryClient`, which splits into Big/Query, still matches).
_SERVICES: tuple[_Service, ...] = (
    _Service(
        subject="AWS S3",
        words=frozenset({"s3", "boto", "boto3"}),
        infixes=("s3client", "s3bucket", "boto"),
        imports=frozenset({"moto", "testcontainers", "s3fs"}),
        advice=(
            "use `moto`'s `mock_aws` (or MinIO via `testcontainers`) so the double enforces the real "
            "bucket/key/versioning and NoSuchKey behaviour instead of a dict"
        ),
    ),
    _Service(
        subject="an AWS service",
        words=frozenset({"sqs", "sns", "dynamodb", "dynamo", "kinesis", "ses"}),
        infixes=("dynamodb", "kinesis"),
        imports=frozenset({"moto", "testcontainers"}),
        advice="use `moto`'s `mock_aws`, which tracks the real service's state machine and error codes",
    ),
    _Service(
        subject="Google Cloud Storage",
        words=frozenset({"gcs", "gcsclient"}),
        infixes=("gcs", "cloudstorage", "googlestorage"),
        imports=frozenset({"testcontainers", "gcp_storage_emulator"}),
        advice=(
            "run `fake-gcs-server` via `testcontainers` and drive the real `google-cloud-storage` client, "
            "so generation/precondition/signed-URL behaviour stays honest"
        ),
    ),
    _Service(
        subject="Google BigQuery",
        words=frozenset({"bigquery", "bq"}),
        infixes=("bigquery",),
        imports=frozenset({"testcontainers"}),
        advice=(
            "run the `bigquery-emulator` container via `testcontainers` and drive the real "
            "`google-cloud-bigquery` client, so query parameters, job config and schema coercion are "
            "actually exercised"
        ),
    ),
    _Service(
        subject="Google Pub/Sub",
        words=frozenset({"pubsub"}),
        infixes=("pubsub",),
        imports=frozenset({"testcontainers"}),
        advice=(
            "run the Pub/Sub emulator (`gcloud beta emulators pubsub`, or via `testcontainers`) and keep "
            "the real publisher client, so ordering keys, ack deadlines and message encoding are real"
        ),
    ),
    _Service(
        subject="Kafka",
        words=frozenset({"kafka"}),
        infixes=("kafka",),
        imports=frozenset({"testcontainers"}),
        advice="run a Kafka broker via `testcontainers`, so partitioning, offsets and rebalancing are real",
    ),
    _Service(
        subject="an LLM provider's HTTP API",
        words=frozenset({"openai", "anthropic", "gemini", "groq", "bedrock", "cohere", "mistral", "vertexai"}),
        infixes=("openai", "anthropic", "gemini", "bedrock", "vertexai", "chatcompletion"),
        imports=frozenset({"respx", "vcr", "pytest_recording", "pytest_httpx", "responses", "aioresponses"}),
        advice=(
            "point the real SDK at a `respx` mock transport (or record cassettes with `vcrpy`) so the "
            "double keeps the provider's real request shape, streaming chunks, finish reasons and error "
            "envelopes"
        ),
    ),
    _Service(
        subject="Redis",
        words=frozenset({"redis", "valkey"}),
        infixes=("redis", "valkey"),
        imports=frozenset({"fakeredis", "testcontainers"}),
        advice="use `fakeredis`, which implements the real command set, TTL semantics and type errors",
    ),
    _Service(
        subject="MongoDB",
        words=frozenset({"mongo", "mongodb", "pymongo"}),
        infixes=("mongo",),
        imports=frozenset({"mongomock", "testcontainers"}),
        advice="use `mongomock`, or run mongod via `testcontainers`, so query and update operators are real",
    ),
    _Service(
        subject="a SQL database",
        words=frozenset({"postgres", "postgresql", "psycopg", "mysql", "mariadb"}),
        infixes=("postgres", "psycopg", "mysql"),
        imports=frozenset({"testcontainers", "pytest_postgresql"}),
        advice=(
            "run the real database via `testcontainers` (or a per-test schema fixture) — a dict cannot "
            "enforce constraints, transactions or SQL semantics, which is the only thing worth testing here"
        ),
    ),
    _Service(
        subject="SMTP mail delivery",
        words=frozenset({"smtp", "smtplib", "aiosmtplib", "sendgrid", "mailgun"}),
        infixes=("smtp", "sendgrid", "mailgun"),
        imports=frozenset({"aiosmtpd", "mailpit", "testcontainers"}),
        advice=(
            "use an `aiosmtpd` `Controller` (or your framework's own locmem/console email backend) so "
            "envelope addressing, MIME encoding and delivery errors are the real ones"
        ),
    ),
    _Service(
        subject="an httpx client",
        words=frozenset({"httpx"}),
        infixes=("httpx",),
        imports=frozenset({"respx", "pytest_httpx"}),
        advice=(
            "use `respx` (or `pytest-httpx`) against the real `httpx` client, so routing, redirects, "
            "timeouts and response decoding stay real"
        ),
    ),
    _Service(
        subject="an aiohttp client",
        words=frozenset({"aiohttp"}),
        infixes=("aiohttp",),
        imports=frozenset({"aioresponses"}),
        advice="use `aioresponses` against the real `aiohttp` session rather than re-implementing it",
    ),
    _Service(
        subject="a requests client",
        words=frozenset({"requests"}),
        infixes=(),
        imports=frozenset({"responses", "requests_mock"}),
        advice=(
            "use the `responses` library (or `requests-mock`) against the real `requests` session, so "
            "status handling, redirects and `raise_for_status` behave as they do in production"
        ),
    ),
    _Service(
        subject="the system clock",
        words=frozenset({"clock"}),
        infixes=("datetime", "monotonic"),
        imports=frozenset({"time_machine", "freezegun", "timemachine"}),
        advice=(
            "use `time-machine` (or `freezegun`), which moves the clock for every reader — `time.time`, "
            "`datetime.now`, `monotonic` — instead of only the one call site the double happens to cover"
        ),
    ),
)

# Words / infixes that mark a class as a test double. `Test` is deliberately absent:
# it is pytest's class-collection convention, not a double marker.
_MARKER_INFIXES = ("mock", "fake", "stub", "dummy", "inmemory", "scripted", "recording")
_MARKER_WORDS = frozenset({"spy"})

# pytest's own collection prefix, in both spellings the corpora use
# (`TestGeminiNullDataCollected` in bulbul, `test_MongoBackend_no_mock` in celery).
_COLLECTED_PREFIX = "test"

# Bases that mean "canned value object" or "test case", never "protocol implementation".
_DATA_HOLDER_BASES = frozenset(
    {
        "ABC",
        "BaseModel",
        "Enum",
        "Exception",
        "Flag",
        "IntEnum",
        "IsolatedAsyncioTestCase",
        "NamedTuple",
        "Protocol",
        "SimpleTestCase",
        "StrEnum",
        "TestCase",
        "TransactionTestCase",
        "TypedDict",
    }
)

# Base-class name shapes that say "this is the framework's declared extension point".
# A double implementing one of these fills a plugin slot whose contract the framework
# already defines and type-checks; the wire-level fake libraries live at another layer.
_EXTENSION_POINT_PREFIXES = ("Base", "Abstract")
_EXTENSION_POINT_SUFFIXES = ("ABC", "Base", "Interface", "Protocol", "Mixin")

# Splits CamelCase (and screaming acronyms) into words. `[A-Z][a-z0-9]+` must come
# first so `FakeS3Client` yields `s3` rather than a bare `s`.
_CAMEL_RE = re.compile(r"[A-Z][a-z0-9]+|[A-Z]+(?![a-z])|[a-z0-9]+")

# A double this small is not worth a diagnostic, let alone a new dependency.
_MIN_METHODS = 3
_MIN_LINES = 25

# The line-count arm needs a second entry point (method or nested class) before a
# long class counts as a protocol implementation rather than a canned-data factory.
_MIN_ENTRY_POINTS = 2

# Directory segments that hold shared test doubles but are not `tests/`.
_DOUBLE_DIR_NAMES = frozenset({"testing", "test_fakes", "testfixtures", "test_doubles"})

# Module stems that hold shared test doubles.
_DOUBLE_STEMS = frozenset({"fakes", "mocks", "stubs", "doubles"})
_DOUBLE_STEM_SUFFIXES = ("_fakes", "_mocks", "_stubs", "_fake", "_mock", "_stub")

type _Method = ast.FunctionDef | ast.AsyncFunctionDef

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class PreferLibraryFake(Rule):
    """A hand-rolled double of a third-party service should use the maintained fake instead."""

    id: str = "prefer-library-fake"
    code: str = "SARJ059"
    description: str = (
        "Hand-rolled double of a third-party service (S3, Redis, an LLM provider, SMTP, …) where a "
        "maintained fake library exists."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag substantial hand-written doubles of services that have a maintained fake.

        Returns:
            One diagnostic per hand-rolled service double, sorted by position.

        """
        if not _is_double_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        imported = _imported_roots(tree)
        diags: list[Diagnostic] = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            service = _hand_rolled_service(node, imported)
            if service is None:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`{node.name}` hand-rolls {service.subject}; a hand-written double only encodes "
                        f"what its author remembered of the protocol, so the test passes against a service "
                        f"that does not exist. {service.advice}."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_double_module(path: Path) -> bool:
    """Report whether `path` holds tests or shared test doubles.

    Broader than `is_test_path`: a repo's shared fakes routinely live in a
    `testing/` or `test_fakes/` package, or in a `*_stub.py` module beside the
    production code it doubles.

    Returns:
        True when the module is a test or a test-double module.

    """
    if is_test_path(path):
        return True
    if any(part in _DOUBLE_DIR_NAMES for part in path.parts):
        return True
    stem = path.stem
    return stem in _DOUBLE_STEMS or stem.endswith(_DOUBLE_STEM_SUFFIXES)


def _imported_roots(tree: ast.Module) -> frozenset[str]:
    """Collect the top-level module name of every import in the file.

    Returns:
        The set of root module names imported anywhere in the module.

    """
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            roots.add(node.module.split(".", 1)[0])
    return frozenset(roots)


def _hand_rolled_service(node: ast.ClassDef, imported: frozenset[str]) -> _Service | None:
    """Identify the external service `node` hand-rolls, if any.

    Returns:
        The matched service, or None when the class is not a substantial
        hand-rolled double of a recognised external service.

    """
    if not _is_double_name(node.name) or _is_data_holder(node) or _is_extension_point(node):
        return None
    methods: list[_Method] = [child for child in node.body if isinstance(child, _FUNC_NODES)]
    if not _has_substance(node, methods) or _is_delegating_spy(methods):
        return None
    service = _match_service(node.name)
    if service is None:
        service = next((matched for base in _base_names(node) if (matched := _match_service(base))), None)
    if service is None or imported & service.imports:
        return None
    return service


def _is_double_name(name: str) -> bool:
    """Report whether `name` carries a test-double marker.

    Returns:
        True when the class name says it is a mock/fake/stub/spy, and is not a
        pytest-collected grouping class.

    """
    flat = _flatten(name)
    if flat.startswith(_COLLECTED_PREFIX):
        return False
    if any(marker in flat for marker in _MARKER_INFIXES):
        return True
    return bool(_words(name) & _MARKER_WORDS)


def _match_service(name: str) -> _Service | None:
    """Find the external service named by `name`.

    Returns:
        The first matching service, or None.

    """
    flat = _flatten(name)
    words = _words(name)
    for service in _SERVICES:
        if words & service.words or any(infix in flat for infix in service.infixes):
            return service
    return None


def _flatten(name: str) -> str:
    return name.replace("_", "").lower()


def _words(name: str) -> frozenset[str]:
    words: list[str] = _CAMEL_RE.findall(name)
    return frozenset(word.lower() for word in words)


def _base_names(node: ast.ClassDef) -> list[str]:
    """Collect the simple name of every base class of `node`.

    Returns:
        Base class names, with any module qualifier dropped.

    """
    names: list[str] = []
    for base in node.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names


def _is_data_holder(node: ast.ClassDef) -> bool:
    """Report whether `node` is a record type rather than a behaviour double.

    Returns:
        True for pydantic models, NamedTuples, enums, exceptions, protocols and
        unittest cases.

    """
    return any(base in _DATA_HOLDER_BASES for base in _base_names(node))


def _is_extension_point(node: ast.ClassDef) -> bool:
    """Report whether `node` implements a framework's declared extension point.

    langchain's `FakeChatOpenAI(BaseChatModel)` and `_MockBedrockChatModel(BaseChatModel)`
    are plugin implementations, not doubles of a provider's HTTP API — the brand in
    the name describes which provider the plugin *imitates*, and there is no library
    that fakes a `BaseChatModel`.

    Returns:
        True when any base class name is shaped like an abstract extension point.

    """
    return any(
        base.startswith(_EXTENSION_POINT_PREFIXES) or base.endswith(_EXTENSION_POINT_SUFFIXES)
        for base in _base_names(node)
    )


def _has_substance(node: ast.ClassDef, methods: list[_Method]) -> bool:
    """Report whether the double is big enough to be worth replacing.

    Counts only non-dunder methods, so a record type with a long field list and a
    `__init__` never clears the bar on line count alone. The line-count arm
    additionally demands a second entry point — another method, or a nested
    connection/session class anywhere inside the body — because a lone method
    returning a big canned payload is a data factory, not a protocol
    implementation. litellm's `InMemorySMTP` builds its `_Conn` inside
    `server_factory`, which is why the nested scan is a full subtree walk.

    Returns:
        True when the class defines at least 3 real methods, or is long and
        exposes at least two entry points.

    """
    behaviour = sum(1 for method in methods if not _is_dunder(method))
    if behaviour >= _MIN_METHODS:
        return True
    span = (node.end_lineno or node.lineno) - node.lineno + 1
    if behaviour < 1 or span < _MIN_LINES:
        return False
    nested = sum(1 for child in ast.walk(node) if isinstance(child, ast.ClassDef) and child is not node)
    return behaviour + nested >= _MIN_ENTRY_POINTS


def _is_dunder(method: _Method) -> bool:
    return method.name.startswith("__") and method.name.endswith("__")


def _is_delegating_spy(methods: list[_Method]) -> bool:
    """Report whether the class mostly forwards to an injected real client.

    A recording decorator (bulbul's `RecordingObjectStore`, which wraps a real
    `GCSObjectStore`) hand-rolls no protocol at all — it observes one. Replacing
    it with a library fake would defeat its purpose.

    Returns:
        True when at least half the methods, and at least two of them, are
        single-statement forwards to a same-named method on a `self` attribute.

    """
    forwards = sum(1 for method in methods if _forwards_to_inner(method))
    return forwards >= 2 and forwards * 2 >= len(methods)  # ruff:ignore[magic-value-comparison] — "at least half", not a magic threshold


def _forwards_to_inner(method: _Method) -> bool:
    """Report whether `method` is a one-line pass-through to `self.<attr>.<same name>`.

    Returns:
        True when the whole body forwards to a same-named method on a self attribute.

    """
    body = [stmt for stmt in method.body if not _is_docstring(stmt)]
    if len(body) != 1:
        return False
    stmt = body[0]
    if not isinstance(stmt, (ast.Return, ast.Expr)) or stmt.value is None:
        return False
    value = stmt.value
    if isinstance(value, ast.Await):
        value = value.value
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == method.name
        and isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "self"
    )


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)

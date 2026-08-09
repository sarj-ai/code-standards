"""SARJ059 — A hand-rolled double of a third-party service should use the library that fakes it properly.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_library_fake.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
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


# Ordered most-specific first; the first match wins.
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

# Names alone are especially weak evidence for provider clients: projects often
# expose their own typed LLM port, while analytics tests commonly record a
# single BigQuery query seam. Require a distinctive raw provider envelope before
# claiming that either class re-implements the external wire protocol.
_WIRE_GATED_SUBJECTS = frozenset({"Google BigQuery", "an LLM provider's HTTP API"})
_LLM_WIRE_KEY_SETS = (
    frozenset({"choices", "usage"}),
    frozenset({"content", "stop_reason"}),
    frozenset({"candidates", "usageMetadata"}),
)
_BIGQUERY_WIRE_KEY_SETS = (
    frozenset({"jobReference", "jobComplete"}),
    frozenset({"schema", "rows", "totalRows"}),
)

# Words / infixes that mark a class as a test double.
_MARKER_INFIXES = ("mock", "fake", "stub", "dummy", "inmemory", "scripted", "recording")
_MARKER_WORDS = frozenset({"spy"})
_SERVICE_SUFFIXES = (
    "adapter",
    "api",
    "backend",
    "bucket",
    "cache",
    "client",
    "clock",
    "collection",
    "connection",
    "emulator",
    "gateway",
    "mailer",
    "pool",
    "producer",
    "publisher",
    "queue",
    "server",
    "service",
    "session",
    "store",
    "stream",
    "table",
    "transport",
)

# pytest's own collection prefix, in both spellings the corpora use
# (`TestGeminiNullResults` in a first-party repo, `test_MongoBackend_no_mock` in celery).
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
_EXTENSION_POINT_PREFIXES = ("Base", "Abstract")
_EXTENSION_POINT_SUFFIXES = ("ABC", "Base", "Interface", "Protocol", "Mixin")

# Splits CamelCase (and screaming acronyms) into words.
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
    id: str = "prefer-library-fake"
    code: str = "SARJ059"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Tests should use maintained service fakes or emulators instead of hand-rolled third-party doubles.",
        rationale="Hand-written doubles model only remembered protocol behavior and can let invalid requests pass.",
        remediation="Use the recognized library fake, emulator, or test container while keeping the production client.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only test and shared-double paths are analyzed.",
            "Only recognized external services and substantial hand-rolled doubles are reported.",
            "LLM and BigQuery doubles require a distinctive raw provider response envelope.",
        ),
        examples=(
            RuleExample(
                example_id="hand-rolled-s3-client",
                title="Test defines its own S3 client",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fakes/s3.py",
                        "class FakeS3Client:\n    def put_object(self, **kwargs):\n        return kwargs\n\n    def get_object(self, **kwargs):\n        return kwargs\n\n    def delete_object(self, **kwargs):\n        return kwargs\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/fakes/s3.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="maintained-s3-fake",
                title="Test uses the maintained AWS fake",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_upload.py",
                        "from moto import mock_aws\n\n@mock_aws\ndef test_upload():\n    assert upload_with_real_client()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_upload.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag substantial hand-written doubles of services that have a maintained fake."""
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
    """Report whether `path` holds tests or shared test doubles."""
    if is_test_path(path):
        return True
    if any(part in _DOUBLE_DIR_NAMES for part in path.parts):
        return True
    stem = path.stem
    return stem in _DOUBLE_STEMS or stem.endswith(_DOUBLE_STEM_SUFFIXES)


def _imported_roots(tree: ast.Module) -> frozenset[str]:
    """Collect the top-level module name of every import in the file."""
    roots: set[str] = set()
    for node in nodes(tree, ast.Import, ast.ImportFrom):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif node.module is not None and node.level == 0:
            roots.add(node.module.split(".", 1)[0])
    return frozenset(roots)


def _hand_rolled_service(node: ast.ClassDef, imported: frozenset[str]) -> _Service | None:
    """Identify the external service `node` hand-rolls, if any."""
    if not _is_double_name(node.name) or _is_data_holder(node) or _is_extension_point(node):
        return None
    methods: list[_Method] = [child for child in node.body if isinstance(child, _FUNC_NODES)]
    if not _has_substance(node, methods) or _is_delegating_spy(methods):
        return None
    service = _match_service(node.name)
    if service is None:
        service = next((matched for base in _base_names(node) if (matched := _match_service(base))), None)
    if (
        service is None
        or imported & service.imports
        or _implements_clock_port(node, service)
        or not _has_wire_protocol_evidence(node, service)
    ):
        return None
    return service


def _has_wire_protocol_evidence(node: ast.ClassDef, service: _Service) -> bool:
    """Require raw provider envelopes for easily misidentified LLM/BigQuery ports."""
    if service.subject not in _WIRE_GATED_SUBJECTS:
        return True
    keys = {
        key.value
        for mapping in walk(node)
        if isinstance(mapping, ast.Dict)
        for key in mapping.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    expected = _LLM_WIRE_KEY_SETS if service.subject == "an LLM provider's HTTP API" else _BIGQUERY_WIRE_KEY_SETS
    return any(group <= keys for group in expected)


def _implements_clock_port(node: ast.ClassDef, service: _Service) -> bool:
    """Keep injected `Clock` ports distinct from replacements for the global clock."""
    return service.subject == "the system clock" and "Clock" in _base_names(node)


def _is_double_name(name: str) -> bool:
    """Report whether `name` carries a test-double marker."""
    flat = _flatten(name)
    if flat.startswith(_COLLECTED_PREFIX):
        return False
    if any(marker in flat for marker in _MARKER_INFIXES):
        return True
    return bool(_words(name) & _MARKER_WORDS)


def _match_service(name: str) -> _Service | None:
    """Find the external service named by `name`."""
    flat = _flatten(name)
    words = _words(name)
    payloads = tuple(flat.removeprefix(marker) for marker in _MARKER_INFIXES if flat.startswith(marker))
    for service in _SERVICES:
        if words & service.words or any(
            payload == infix or any(payload == infix + suffix for suffix in _SERVICE_SUFFIXES)
            for payload in payloads
            for infix in service.infixes
        ):
            return service
    return None


def _flatten(name: str) -> str:
    return name.replace("_", "").lower()


def _words(name: str) -> frozenset[str]:
    words: list[str] = _CAMEL_RE.findall(name)
    return frozenset(word.lower() for word in words)


def _base_names(node: ast.ClassDef) -> list[str]:
    """Collect the simple name of every base class of `node`."""
    names: list[str] = []
    for base in node.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names


def _is_data_holder(node: ast.ClassDef) -> bool:
    """Report whether `node` is a record type rather than a behaviour double."""
    return any(base in _DATA_HOLDER_BASES for base in _base_names(node))


def _is_extension_point(node: ast.ClassDef) -> bool:
    """Report whether `node` implements a framework's declared extension point."""
    return any(
        base.startswith(_EXTENSION_POINT_PREFIXES) or base.endswith(_EXTENSION_POINT_SUFFIXES)
        for base in _base_names(node)
    )


def _has_substance(node: ast.ClassDef, methods: list[_Method]) -> bool:
    """Report whether the double is big enough to be worth replacing."""
    behaviour = sum(1 for method in methods if not _is_dunder(method))
    if behaviour >= _MIN_METHODS:
        return True
    span = (node.end_lineno or node.lineno) - node.lineno + 1
    if behaviour < 1 or span < _MIN_LINES:
        return False
    nested = sum(1 for child in walk(node) if isinstance(child, ast.ClassDef) and child is not node)
    return behaviour + nested >= _MIN_ENTRY_POINTS


def _is_dunder(method: _Method) -> bool:
    return method.name.startswith("__") and method.name.endswith("__")


def _is_delegating_spy(methods: list[_Method]) -> bool:
    """Report whether the class mostly forwards to an injected real client."""
    forwards = sum(1 for method in methods if _forwards_to_inner(method))
    return forwards >= 2 and forwards * 2 >= len(methods)  # ruff:ignore[magic-value-comparison] — "at least half", not a magic threshold


def _forwards_to_inner(method: _Method) -> bool:
    """Report whether `method` is a one-line pass-through to its receiver's real client."""
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
    positional = method.args.posonlyargs + method.args.args
    if not positional:
        return False
    receiver = positional[0].arg
    return (
        isinstance(func, ast.Attribute)
        and func.attr == method.name
        and isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == receiver
    )


def _is_docstring(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)

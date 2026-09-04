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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


class _Service(NamedTuple):
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
        imports=frozenset({"moto", "testcontainers.localstack"}),
        advice=(
            "consider `moto`'s `mock_aws`, or a containerized compatible service when the test needs behavior "
            "outside Moto's supported S3 model"
        ),
    ),
    _Service(
        subject="an AWS service",
        words=frozenset({"sqs", "sns", "dynamodb", "dynamo", "kinesis", "ses"}),
        infixes=("dynamodb", "kinesis"),
        imports=frozenset({"moto"}),
        advice="consider `moto`'s `mock_aws` for its maintained model of supported AWS behavior",
    ),
    _Service(
        subject="Google Cloud Storage",
        words=frozenset({"gcs", "gcsclient"}),
        infixes=("gcs", "cloudstorage", "googlestorage"),
        imports=frozenset({"gcp_storage_emulator"}),
        advice=(
            "consider `fake-gcs-server` and drive the production `google-cloud-storage` client for the "
            "server behaviors the emulator supports"
        ),
    ),
    _Service(
        subject="Google BigQuery",
        words=frozenset({"bigquery", "bq"}),
        infixes=("bigquery",),
        imports=frozenset(),
        advice=(
            "consider a `bigquery-emulator` container with the production client for its supported query, job, "
            "and schema behavior"
        ),
    ),
    _Service(
        subject="Google Pub/Sub",
        words=frozenset({"pubsub"}),
        infixes=("pubsub",),
        imports=frozenset(),
        advice=(
            "consider the Pub/Sub emulator with the production client for its supported publish, pull, and "
            "acknowledgement behavior"
        ),
    ),
    _Service(
        subject="Kafka",
        words=frozenset({"kafka"}),
        infixes=("kafka",),
        imports=frozenset({"testcontainers.kafka"}),
        advice="consider a Kafka broker via `testcontainers` when the test depends on broker protocol behavior",
    ),
    _Service(
        subject="an LLM provider's HTTP API",
        words=frozenset({"openai", "anthropic", "gemini", "groq", "cohere", "mistral", "vertexai"}),
        infixes=("openai", "anthropic", "gemini", "vertexai", "chatcompletion"),
        imports=frozenset({"respx", "vcr", "pytest_recording", "pytest_httpx", "responses", "aioresponses"}),
        advice=(
            "consider a transport interceptor such as `respx` or a reviewed `vcrpy` cassette while keeping "
            "the production SDK request and response parsing path"
        ),
    ),
    _Service(
        subject="Redis",
        words=frozenset({"redis", "valkey"}),
        infixes=("redis", "valkey"),
        imports=frozenset({"fakeredis", "testcontainers.redis"}),
        advice="consider `fakeredis` for its broader maintained model of supported Redis commands and errors",
    ),
    _Service(
        subject="MongoDB",
        words=frozenset({"mongo", "mongodb", "pymongo"}),
        infixes=("mongo",),
        imports=frozenset({"mongomock", "testcontainers.mongodb"}),
        advice="consider `mongomock`, or a MongoDB container when the test depends on database behavior",
    ),
    _Service(
        subject="a SQL database",
        words=frozenset({"postgres", "postgresql", "psycopg", "mysql", "mariadb"}),
        infixes=("postgres", "psycopg", "mysql"),
        imports=frozenset({"pytest_postgresql", "testcontainers.mysql", "testcontainers.postgres"}),
        advice=(
            "consider the database via `testcontainers` or a per-test schema fixture when constraints, "
            "transactions, or SQL semantics are part of the contract"
        ),
    ),
    _Service(
        subject="SMTP mail delivery",
        words=frozenset({"smtp", "smtplib", "aiosmtplib"}),
        infixes=("smtp",),
        imports=frozenset({"aiosmtpd", "mailpit"}),
        advice=(
            "consider an `aiosmtpd` `Controller`, Mailpit, or the framework's maintained test backend when "
            "SMTP envelope and MIME behavior matter"
        ),
    ),
    _Service(
        subject="an httpx client",
        words=frozenset({"httpx"}),
        infixes=("httpx",),
        imports=frozenset({"respx", "pytest_httpx"}),
        advice=("consider `respx` or `pytest-httpx` while keeping the production `httpx` request and response path"),
    ),
    _Service(
        subject="an aiohttp client",
        words=frozenset({"aiohttp"}),
        infixes=("aiohttp",),
        imports=frozenset({"aioresponses"}),
        advice="consider `aioresponses` while keeping the production `aiohttp` session path",
    ),
    _Service(
        subject="a requests client",
        words=frozenset({"requests"}),
        infixes=(),
        imports=frozenset({"responses", "requests_mock"}),
        advice=("consider `responses` or `requests-mock` while keeping the production `requests` session path"),
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

_PROTOCOL_METHODS: dict[str, tuple[frozenset[str], int]] = {
    "AWS S3": (
        frozenset(
            {
                "create_bucket",
                "delete_bucket",
                "delete_object",
                "download_file",
                "get_object",
                "head_object",
                "list_objects",
                "list_objects_v2",
                "put_object",
                "upload_file",
            }
        ),
        2,
    ),
    "an AWS service": (
        frozenset(
            {
                "acknowledge",
                "delete_item",
                "delete_message",
                "get_item",
                "get_records",
                "publish",
                "put_item",
                "query",
                "receive_message",
                "scan",
                "send_email",
                "send_message",
            }
        ),
        2,
    ),
    "Google Cloud Storage": (
        frozenset(
            {
                "blob",
                "bucket",
                "delete",
                "download_as_bytes",
                "download_as_text",
                "exists",
                "get_blob",
                "list_blobs",
                "reload",
                "download",
                "upload",
                "upload_from_file",
                "upload_from_string",
            }
        ),
        2,
    ),
    "Google Pub/Sub": (
        frozenset({"acknowledge", "modify_ack_deadline", "publish", "pull", "subscribe"}),
        2,
    ),
    "Kafka": (frozenset({"commit", "consume", "flush", "poll", "produce", "send", "subscribe"}), 2),
    "Redis": (
        frozenset({"delete", "expire", "get", "hget", "hset", "mget", "mset", "set", "ttl"}),
        3,
    ),
    "MongoDB": (
        frozenset({"aggregate", "delete_one", "find", "find_one", "insert_one", "replace_one", "update_one"}),
        2,
    ),
    "a SQL database": (
        frozenset({"begin", "commit", "execute", "executemany", "fetchall", "fetchone", "rollback"}),
        2,
    ),
    "SMTP mail delivery": (
        frozenset({"ehlo", "login", "quit", "send_message", "sendmail", "starttls"}),
        2,
    ),
    "an httpx client": (frozenset({"delete", "get", "patch", "post", "put", "request", "stream"}), 2),
    "an aiohttp client": (frozenset({"delete", "get", "patch", "post", "put", "request", "ws_connect"}), 2),
    "a requests client": (frozenset({"delete", "get", "head", "patch", "post", "put", "request"}), 2),
}

_STATE_PRODUCERS = frozenset({"add", "append", "extend", "insert", "setdefault", "update"})
_BOOKKEEPING_FIELDS = frozenset({"calls", "invocations", "outcomes", "sideeffects"})

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
        summary="Prefer a maintained fake, emulator, recorder, or test service for substantial third-party protocols.",
        rationale=(
            "A substantial hand-written protocol model can drift from supported request, state, and error behavior."
        ),
        remediation=(
            "When the test depends on protocol fidelity, use a maintained fake, emulator, recorder, or test service "
            "while keeping the production client. Keep narrow application-port and failure-scripting doubles local."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only test and shared-double paths are analyzed.",
            "Most service families require module-level cross-method state plus multiple recognized protocol methods.",
            "LLM and BigQuery doubles instead require a distinctive raw provider response envelope.",
            "Generated files, application-owned ports, thin response seams without provider envelopes, and structurally injected clocks are excluded.",
            "A matching unconditional module-level maintained-tool import suppresses that service family.",
        ),
        examples=(
            RuleExample(
                example_id="hand-rolled-s3-client",
                title="Test defines its own S3 client",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fakes/s3.py",
                        "class FakeS3Client:\n"
                        "    def __init__(self):\n"
                        "        self.objects = {}\n\n"
                        "    def put_object(self, Bucket, Key, Body):\n"
                        "        self.objects[(Bucket, Key)] = Body\n"
                        '        return {"ResponseMetadata": {"HTTPStatusCode": 200}}\n\n'
                        "    def get_object(self, Bucket, Key):\n"
                        '        return {"Body": self.objects[(Bucket, Key)]}\n\n'
                        "    def delete_object(self, Bucket, Key):\n"
                        "        self.objects.pop((Bucket, Key), None)\n",
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
                        "import boto3\n"
                        "from moto import mock_aws\n\n"
                        "@mock_aws\n"
                        "def test_upload():\n"
                        '    client = boto3.client("s3", region_name="us-east-1")\n'
                        '    client.create_bucket(Bucket="uploads")\n'
                        '    upload(client, bucket="uploads", key="avatar", body=b"image")\n'
                        '    result = client.get_object(Bucket="uploads", Key="avatar")\n'
                        '    assert result["Body"].read() == b"image"\n',
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
        if not _is_double_module(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        imported = _imported_modules(tree)
        base_aliases = _imported_base_aliases(tree)
        diags: list[Diagnostic] = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            service = _hand_rolled_service(node, imported, base_aliases)
            if service is None:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`{node.name}` appears to reimplement substantial {service.subject} protocol behavior; "
                        f"a maintained test double usually covers a broader supported behavior surface. "
                        f"{service.advice[:1].upper()}{service.advice[1:]}."
                    ),
                    severity=Severity.WARNING,
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_double_module(path: Path) -> bool:
    if is_test_path(path):
        return True
    if any(part in _DOUBLE_DIR_NAMES for part in path.parts):
        return True
    stem = path.stem
    return stem in _DOUBLE_STEMS or stem.endswith(_DOUBLE_STEM_SUFFIXES)


def _imported_modules(tree: ast.Module) -> frozenset[str]:
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module)
    return frozenset(modules)


def _imported_base_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.level != 0:
            continue
        for imported in node.names:
            aliases[imported.asname or imported.name] = imported.name
    return aliases


def _hand_rolled_service(node: ast.ClassDef, imported: frozenset[str], base_aliases: dict[str, str]) -> _Service | None:
    base_names = _base_names(node, base_aliases)
    if (
        not _is_double_name(node.name)
        or "scripted" in _words(node.name)
        or _is_data_holder(base_names)
        or _is_extension_point(base_names)
    ):
        return None
    methods: list[_Method] = [child for child in node.body if isinstance(child, _FUNC_NODES)]
    if not _has_substance(node, methods) or _is_delegating_spy(methods):
        return None
    service = _match_service(node.name)
    if service is None:
        service = next((matched for base in base_names if (matched := _match_service(base))), None)
    if (
        service is None
        or _has_matching_import(imported, service.imports)
        or not _has_wire_protocol_evidence(node, service)
    ):
        return None
    return service


def _has_wire_protocol_evidence(node: ast.ClassDef, service: _Service) -> bool:
    if service.subject not in _WIRE_GATED_SUBJECTS:
        methods, threshold = _PROTOCOL_METHODS[service.subject]
        implemented = [method for method in node.body if isinstance(method, _FUNC_NODES) and method.name in methods]
        return len(implemented) >= threshold and _has_cross_method_protocol_state(implemented)
    keys = {
        key.value
        for mapping in walk(node)
        if isinstance(mapping, ast.Dict)
        for key in mapping.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    expected = _LLM_WIRE_KEY_SETS if service.subject == "an LLM provider's HTTP API" else _BIGQUERY_WIRE_KEY_SETS
    return any(group <= keys for group in expected)


def _has_cross_method_protocol_state(methods: list[_Method]) -> bool:
    writes: dict[str, set[str]] = {}
    reads: dict[str, set[str]] = {}
    for method in methods:
        for child in _method_body_nodes(method):
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else (child.target,)
                for target in targets:
                    if (field := _receiver_field(target)) is not None:
                        writes.setdefault(field, set()).add(method.name)
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _STATE_PRODUCERS
                and (field := _receiver_field(child.func.value)) is not None
            ):
                writes.setdefault(field, set()).add(method.name)
            expressions: tuple[ast.expr, ...] = ()
            if isinstance(child, ast.Return) and child.value is not None:
                expressions = (child.value,)
            elif isinstance(child, (ast.If, ast.While)):
                expressions = (child.test,)
            elif isinstance(child, ast.Match):
                expressions = (child.subject,)
            for expression in expressions:
                for descendant in walk(expression):
                    if (field := _receiver_field(descendant)) is not None:
                        reads.setdefault(field, set()).add(method.name)
    return any(
        _flatten(field) not in _BOOKKEEPING_FIELDS
        and any(writer != reader for writer in writers_by for reader in reads.get(field, set()))
        for field, writers_by in writes.items()
    )


def _method_body_nodes(method: _Method) -> list[ast.AST]:
    found: list[ast.AST] = []
    queue: list[ast.AST] = list(method.body)
    while queue:
        child = queue.pop()
        found.append(child)
        if not isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            queue.extend(ast.iter_child_nodes(child))
    return found


def _receiver_field(value: ast.AST) -> str | None:
    while isinstance(value, ast.Subscript):
        value = value.value
    if (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id in {"self", "cls", "outer"}
    ):
        return value.attr
    return None


def _has_matching_import(imported: frozenset[str], candidates: frozenset[str]) -> bool:
    return any(
        module == candidate or module.startswith(f"{candidate}.") for module in imported for candidate in candidates
    )


def _is_double_name(name: str) -> bool:
    flat = _flatten(name)
    if flat.startswith(_COLLECTED_PREFIX):
        return False
    if any(marker in flat for marker in _MARKER_INFIXES):
        return True
    return bool(_words(name) & _MARKER_WORDS)


def _match_service(name: str) -> _Service | None:
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


def _base_names(node: ast.ClassDef, aliases: dict[str, str] | None = None) -> list[str]:
    names: list[str] = []
    for base in node.bases:
        target = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(target, ast.Name):
            names.append((aliases or {}).get(target.id, target.id))
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names


def _is_data_holder(base_names: list[str]) -> bool:
    return any(base in _DATA_HOLDER_BASES for base in base_names)


def _is_extension_point(base_names: list[str]) -> bool:
    return any(
        base.startswith(_EXTENSION_POINT_PREFIXES) or base.endswith(_EXTENSION_POINT_SUFFIXES) for base in base_names
    )


def _has_substance(node: ast.ClassDef, methods: list[_Method]) -> bool:
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
    forwards = sum(1 for method in methods if _forwards_to_inner(method))
    return forwards >= 2 and forwards * 2 >= len(methods)  # ruff:ignore[magic-value-comparison] — "at least half", not a magic threshold


def _forwards_to_inner(method: _Method) -> bool:
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

from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_library_fake import PreferLibraryFake


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = "python/dashboard/tests/analytics_data.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return PreferLibraryFake().check(Path(path), textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferLibraryFake.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferLibraryFake().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize("name", ["FakeRedistributor", "FakeRobotoFontLoader"])
def test_ignores_service_name_substrings_inside_domain_words(name: str) -> None:
    source = f"""
class {name}:
    def first(self): return 1
    def second(self): return 2
    def third(self): return 3
"""

    assert _check(source) == []


# The public Before example is the canonical shape this rule exists for.
_FAKE_S3 = _PUBLIC_EXAMPLES[0].focus_file.source


# File-scope gating.                                                          #


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_thing.py",
        "a/b/thing_test.py",
        "app/tests/analytics_data.py",
        "app/conftest.py",
    ],
)
def test_fires_in_ordinary_test_paths(path: str):
    assert len(_check(_FAKE_S3, path)) == 1


@pytest.mark.parametrize(
    "path",
    [
        "common/testing/fakes.py",
        "webserver/test_fakes/clerk.py",
        "common/testfixtures/redis.py",
        "common/test_doubles/redis.py",
        "app/fakes.py",
        "app/mocks.py",
        "app/stubs.py",
        "app/doubles.py",
        "app/redis_fake.py",
        "app/redis_mock.py",
        "app/observability/langfuse_stub.py",
        "app/llm_fakes.py",
        "app/llm_mocks.py",
        "app/llm_stubs.py",
    ],
)
def test_reaches_shared_double_modules_that_is_test_path_misses(path: str):
    # One first-party repo keeps its shared fakes in `common/testing/fakes.py`
    # and another keeps one in `app/observability/langfuse_stub.py`; neither
    # lives under `tests/`.
    assert len(_check(_FAKE_S3, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "app/adapters/s3_client.py", "app/main.py"])
def test_skips_production_paths(path: str):
    # One first-party service module ships a production `MockMessageEnqueuer`;
    # a dev-mode stand-in is not a test double.
    assert _check(_FAKE_S3, path) == []


# Positive: one diagnostic per recognised service, each naming its library.    #


@pytest.mark.parametrize(
    ("name", "library"),
    [
        ("FakeS3Client", "moto"),
        ("MockBoto3Client", "moto"),
        ("FakeSqsQueue", "moto"),
        ("FakeSnsPublisher", "moto"),
        ("FakeDynamoDbTable", "moto"),
        ("FakeKinesisStream", "moto"),
        ("FakeSesMailer", "moto"),
        ("FakeGcsBucket", "fake-gcs-server"),
        ("FakePubSubPublisher", "emulator"),
        ("StubKafkaProducer", "testcontainers"),
        ("FakeRedisCache", "fakeredis"),
        ("FakeValkeyCache", "fakeredis"),
        ("FakeMongoCollection", "mongomock"),
        ("FakePostgresPool", "testcontainers"),
        ("FakePsycopgConnection", "testcontainers"),
        ("FakeMySQLConnection", "testcontainers"),
        ("FakeMariadbConnection", "testcontainers"),
        ("FakeSmtpServer", "aiosmtpd"),
        ("FakeSmtplibServer", "aiosmtpd"),
        ("FakeAiosmtplibServer", "aiosmtpd"),
        ("FakeSendGridClient", "aiosmtpd"),
        ("FakeMailgunClient", "aiosmtpd"),
        ("MockHttpxTransport", "respx"),
        ("FakeAiohttpSession", "aioresponses"),
        ("FakeRequestsSession", "responses"),
        ("FakeClock", "time-machine"),
        ("FakeDateTime", "time-machine"),
        ("FakeMonotonicClock", "time-machine"),
    ],
)
def test_each_service_names_its_own_library(name: str, library: str):
    src = f"""
class {name}:
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    [diag] = _check(src)
    assert library in diag.message
    assert f"`{name}`" in diag.message


def test_message_names_the_class_and_the_service():
    [diag] = _check(_FAKE_S3)
    assert "`FakeS3Client`" in diag.message
    assert "AWS S3" in diag.message
    assert "mock_aws" in diag.message


def test_the_exact_message_text():
    [diag] = _check(_FAKE_S3)
    assert diag.message == (
        "`FakeS3Client` hand-rolls AWS S3; a hand-written double only encodes what its author "
        "remembered of the protocol, so the test passes against a service that does not exist. "
        "use `moto`'s `mock_aws` (or MinIO via `testcontainers`) so the double enforces the real "
        "bucket/key/versioning and NoSuchKey behaviour instead of a dict."
    )


@pytest.mark.parametrize(
    "marker",
    ["Fake", "Mock", "Stub", "Dummy", "InMemory", "Scripted", "Recording"],
)
def test_every_double_marker_is_recognised(marker: str):
    src = f"""
class {marker}RedisClient:
    def get(self, k):
        return None

    def set(self, k, v):
        return True

    def delete(self, k):
        return 1
"""
    assert len(_check(src)) == 1


def test_spy_is_recognised_as_a_word():
    src = """
class RedisSpy:
    def get(self, k):
        return None

    def set(self, k, v):
        return True

    def delete(self, k):
        return 1
"""
    assert len(_check(src)) == 1


def test_leading_underscores_do_not_hide_the_marker():
    src = """
class _FakeRedisCache:
    def get(self, k):
        return None

    def set(self, k, v):
        return True

    def delete(self, k):
        return 1
"""
    assert len(_check(src)) == 1


def test_service_token_may_come_from_a_base_class():
    # A first-party typed LLM port is not evidence of a provider wire fake.
    src = """
class FakeLLMClient(OpenAILLMClient):
    def generate(self):
        return "hi"

    def generate_structured(self):
        return {}

    def script(self, *responses):
        pass
"""
    assert _check(src) == []


def test_dotted_base_class_is_resolved_to_its_attribute():
    src = """
class FakeThing(openai_sdk.OpenAIClient):
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "name",
    [
        "FakeBigQueryClient",
        "FakeOpenAIClient",
        "StubAnthropicClient",
        "_StubGeminiClient",
        "FakeGroqClient",
        "FakeBedrockClient",
        "FakeCohereClient",
        "FakeMistralClient",
        "FakeVertexAIClient",
        "FakeChatCompletion",
    ],
)
def test_provider_name_without_a_raw_wire_envelope_is_not_enough(name: str):
    src = f"""
class {name}:
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert _check(src) == []


def test_llm_raw_wire_envelope_still_fires():
    src = """
class FakeOpenAIClient:
    def create(self):
        return {"choices": [], "usage": {"total_tokens": 0}}

    def stream(self):
        return {"choices": [{"delta": {"content": "hello"}}], "usage": {}}

    def close(self):
        return None
"""
    [diag] = _check(src)
    assert "respx" in diag.message


def test_bigquery_raw_wire_envelope_still_fires():
    src = """
class FakeBigQueryClient:
    def query(self):
        return {"jobReference": {"jobId": "1"}, "jobComplete": True}

    def get_query_results(self):
        return {"schema": {}, "rows": [], "totalRows": "0"}

    def close(self):
        return None
"""
    [diag] = _check(src)
    assert "bigquery-emulator" in diag.message


def test_single_bigquery_query_recording_seam_without_wire_envelopes_is_exempt():
    src = """
class FakeBigQueryClient:
    def __init__(self):
        self.queued = []
        self.queries = []
        self.job_configs = []

    def enqueue(self, rows):
        self.queued.append(rows)

    def query(self, query, job_config=None):
        self.queries.append(query)
        self.job_configs.append(job_config)
        return FakeQueryJob(self.queued.pop(0))

    def as_client(self):
        return cast("bigquery.Client", self)
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "patch",
    [
        'mock.patch("app.service.boto3.client")',
        'mock.patch("app.service.datetime")',
        'monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)',
        'monkeypatch.setattr(time, "time", lambda: 0)',
    ],
)
def test_sdk_symbol_patches_are_out_of_scope(patch: str):
    src = f"""
def test_request(monkeypatch):
    with {patch}:
        call_service()
"""
    assert _check(src) == []


# FP guard: pytest's own collection classes.


@pytest.mark.parametrize("name", ["TestGeminiNullDataCollected", "test_MongoBackend_no_mock", "TestFakeRedisCache"])
def test_pytest_collection_classes_are_never_doubles(name: str):
    src = f"""
class {name}:
    def test_a(self):
        assert 1

    def test_b(self):
        assert 2

    def test_c(self):
        assert 3
"""
    assert _check(src) == []


def test_llm_double_name_without_wire_evidence_stays_silent():
    src = """
class MockGeminiClient:
    def test_a(self):
        assert 1

    def test_b(self):
        assert 2

    def test_c(self):
        assert 3
"""
    assert _check(src) == []


# FP guard: doubles of the project's own domain ports. ~60 of these exist in   #
# two first-party repos; none of them has a library and none should fire.      #


@pytest.mark.parametrize(
    "name",
    [
        "FakeSubjectService",
        "InMemoryUserStore",
        "RecordingCronMonitor",
        "FakeCallCapacityService",
        "StubNumberAssignmentService",
        "RecordingKnowledgeBaseService",
        "FakeGlobalPromptService",
    ],
)
def test_doubles_of_first_party_ports_are_exempt(name: str):
    src = f"""
class {name}:
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert _check(src) == []


def test_injected_clock_port_fake_is_exempt():
    src = """
class FakeClock(Clock):
    def now(self):
        return 0

    def monotonic(self):
        return 0

    def sleep(self, seconds):
        return None
"""
    assert _check(src) == []


# FP guard: framework extension points.


@pytest.mark.parametrize(
    "name",
    ["FakeRoom", "FakeJobContext", "FakeAgentSession", "ScriptedLLM", "FakeSTT", "FakeVAD", "_RecordingLLMStream"],
)
def test_livekit_style_extension_point_doubles_are_exempt(name: str):
    # Generic words — llm, session, room, job, stt — are deliberately absent from
    # the service tables precisely so these stay silent.
    src = f"""
class {name}:
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "base",
    ["BaseChatModel", "AbstractLLM", "ChatModelABC", "LLMInterface", "ModelMixin"],
)
def test_a_double_of_an_abstract_extension_point_is_exempt(base: str):
    src = f"""
class FakeChatOpenAI({base}):
    def _generate(self, messages):
        return "x"

    def _stream(self, messages):
        yield "x"

    def _llm_type(self):
        return "fake"
"""
    assert _check(src) == []


def test_concrete_llm_base_without_wire_evidence_stays_silent():
    src = """
class FakeChatOpenAI(ChatOpenAI):
    def _generate(self, messages):
        return "x"

    def _stream(self, messages):
        yield "x"

    def _llm_type(self):
        return "fake"
"""
    assert _check(src) == []


# FP guard: recording decorators around the real client.


def test_delegating_spy_is_exempt():
    src = """
class RecordingRedisClient:
    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def get(self, key):
        return self._inner.get(key)

    def set(self, key, value):
        return self._inner.set(key, value)

    def delete(self, key):
        return self._inner.delete(key)
"""
    assert _check(src) == []


def test_async_delegating_spy_is_exempt():
    src = """
class RecordingS3Store:
    def __init__(self, inner):
        self._inner = inner

    async def download(self, path):
        return await self._inner.download(path)

    async def upload(self, path, data):
        return await self._inner.upload(path, data)

    def sign(self, path):
        return self._inner.sign(path)
"""
    assert _check(src) == []


def test_classmethod_delegating_spy_is_exempt():
    src = """
class RecordingRedisClient:
    @classmethod
    def get(cls, key):
        return cls.inner.get(key)

    @classmethod
    def set(cls, key, value):
        return cls.inner.set(key, value)

    @classmethod
    def delete(cls, key):
        return cls.inner.delete(key)
"""
    assert _check(src) == []


def test_non_receiver_forward_is_not_a_spy():
    src = """
class RecordingRedisClient:
    def get(self, key):
        return global_client.get(key)

    def set(self, key, value):
        return global_client.set(key, value)

    def delete(self, key):
        return global_client.delete(key)
"""
    assert len(_check(src)) == 1


def test_a_docstring_does_not_break_forward_detection():
    src = """
class RecordingS3Store:
    def __init__(self, inner):
        self._inner = inner

    def download(self, path):
        \"\"\"Forward.\"\"\"
        return self._inner.download(path)

    def upload(self, path, data):
        \"\"\"Forward.\"\"\"
        return self._inner.upload(path, data)

    def sign(self, path):
        return self._inner.sign(path)
"""
    assert _check(src) == []


def test_a_single_forwarding_method_is_not_a_spy():
    src = """
class FakeS3Client:
    def __init__(self, inner):
        self._inner = inner
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return self.objects[(Bucket, Key)]

    def sign(self, path):
        return self._inner.sign(path)
"""
    assert len(_check(src)) == 1


def test_forwarding_under_a_different_method_name_is_not_a_forward():
    # Renaming the call is reimplementation, not delegation.
    src = """
class FakeRedisClient:
    def __init__(self, inner):
        self._inner = inner

    def get(self, key):
        return self._inner.read(key)

    def set(self, key, value):
        return self._inner.write(key, value)

    def delete(self, key):
        return self._inner.remove(key)
"""
    assert len(_check(src)) == 1


def test_exactly_half_the_methods_forwarding_is_still_a_spy():
    # The `>= half` boundary: 2 forwards of 4 methods.
    src = """
class RecordingRedisClient:
    def get(self, key):
        return self._inner.get(key)

    def set(self, key, value):
        return self._inner.set(key, value)

    def delete(self, key):
        self._calls.append(key)
        del self._store[key]

    def flush(self):
        self._store.clear()
"""
    assert _check(src) == []


def test_two_forwards_of_five_methods_is_not_a_spy():
    # One method past the halfway mark: the class reimplements more than it
    # observes, so dropping the `forwards * 2 >= len(methods)` arm loses this.
    src = """
class RecordingRedisClient:
    def get(self, key):
        return self._inner.get(key)

    def set(self, key, value):
        return self._inner.set(key, value)

    def delete(self, key):
        self._calls.append(key)
        del self._store[key]

    def flush(self):
        self._store.clear()

    def expire(self, key, seconds):
        self._ttls[key] = seconds
"""
    assert len(_check(src)) == 1


def test_a_lone_forward_among_two_methods_is_not_a_spy():
    # `forwards >= 2` carries this one alone: half of two methods forward, so
    # dropping the arm — or lowering the 2 to 1 — silences a real hand-roll.
    rows = "\n".join(f'            "key_{i}": {i},' for i in range(20))
    src = f"""
class FakeRedisClient:
    def get(self, key):
        return self._inner.get(key)

    def snapshot(self):
        return {{
{rows}
        }}
"""
    assert len(_check(src)) == 1


def test_forwarding_to_a_module_level_object_is_not_a_spy():
    src = """
class FakeRedisClient:
    def get(self, key):
        return backend.get(key)

    def set(self, key, value):
        return backend.set(key, value)

    def delete(self, key):
        return backend.delete(key)
"""
    assert len(_check(src)) == 1


# FP guard: data holders.                                                      #


@pytest.mark.parametrize(
    "base",
    [
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
    ],
)
def test_record_type_bases_are_exempt(base: str):
    src = f"""
class FakeRedisResult({base}):
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert _check(src) == []


def test_dotted_record_type_base_is_exempt():
    src = """
class MockRedisSession(pydantic.BaseModel):
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert _check(src) == []


def test_a_dataclass_with_real_behaviour_still_fires():
    # litellm `.../prisma_and_spend/conftest.py:249` FakeClock is a dataclass and is
    # a genuine behaviour double — excluding every `@dataclass` would lose it.
    src = """
@dataclass
class FakeClock:
    now: float = 0.0

    def advance(self, seconds):
        self.now += seconds

    def time(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
"""
    assert len(_check(src)) == 1


def test_a_field_only_dataclass_does_not_reach_the_substance_floor():
    src = """
@dataclass
class FakeS3Response:
    status: int = 200
    body: bytes = b""
    etag: str = ""
    version_id: str = ""
    content_type: str = "application/octet-stream"
    last_modified: str = ""
    metadata: dict = field(default_factory=dict)
    request_id: str = ""
    checksum: str = ""
    storage_class: str = "STANDARD"
"""
    assert _check(src) == []


# FP guard: substance floor.                                                   #


def test_two_method_double_is_below_the_floor():
    # A first-party `FakeSmtpSender` in a shared testing package is exactly this.
    src = """
class FakeSmtpSender:
    def __init__(self, error=None):
        self.calls = []
        self._error = error

    async def __call__(self, message, **kwargs):
        self.calls.append((message, kwargs))
"""
    assert _check(src) == []


def test_dunder_methods_do_not_count_toward_the_floor():
    src = """
class FakeRedisClient:
    def __init__(self):
        self.store = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def get(self, key):
        return self.store.get(key)
"""
    assert _check(src) == []


def test_three_real_methods_clears_the_floor():
    src = """
class FakeRedisClient:
    def get(self, key):
        return None

    def set(self, key, value):
        return True

    def delete(self, key):
        return 1
"""
    assert len(_check(src)) == 1


def test_a_long_double_with_two_real_methods_clears_the_floor():
    body = "\n".join(f"        self.field_{i} = {i}" for i in range(24))
    src = f"""
class InMemorySmtpServer:
    def __init__(self):
{body}

    def send_message(self, msg):
        return None

    def login(self, user, password):
        return None
"""
    assert len(_check(src)) == 1


def _two_real_methods_spanning(span: int) -> str:
    """Build a two-method double whose class spans exactly `span` lines."""
    body = "\n".join(f"        self.field_{i} = {i}" for i in range(span - 8))
    return f"""
class InMemorySmtpServer:
    def __init__(self):
{body}

    def send_message(self, msg):
        return None

    def login(self, user, password):
        return None
"""


def test_two_real_methods_one_line_below_the_span_floor_stay_silent():
    # Pins `_MIN_LINES` and the `<` from below: two real methods is under
    # `_MIN_METHODS`, so a 24-line class has to fall through to silence.
    assert _check(_two_real_methods_spanning(24)) == []


def test_two_real_methods_exactly_at_the_span_floor_fire():
    # Pins `_MIN_LINES` and the `<` from above, and the `+ 1` in the span
    # arithmetic: without it a 25-line class measures 24 and goes quiet.
    assert len(_check(_two_real_methods_spanning(25))) == 1


def test_three_methods_of_which_two_are_real_are_below_the_method_floor():
    # `_MIN_METHODS` counts behaviour, not `def`s: three methods, one dunder.
    src = """
class FakeRedisClient:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value
"""
    assert _check(src) == []


def test_a_long_double_with_no_real_method_stays_silent():
    body = "\n".join(f"        self.field_{i} = {i}" for i in range(30))
    src = f"""
class InMemorySmtpServer:
    def __init__(self):
{body}
"""
    assert _check(src) == []


# FP guard: a long class with one method returning canned data is a data        #
# factory, not a protocol hand-roll. dagster's MockKafkaConsumerResource.       #


def test_a_long_single_method_canned_data_factory_is_exempt():
    # dagster `examples/ingestion-patterns/tests/conftest.py:32` —
    # `MockKafkaConsumerResource.poll_messages` fabricates message dicts and
    # implements no part of the Kafka protocol.
    rows = "\n".join(f'            {{"offset": {i}, "value": "v{i}"}},' for i in range(22))
    src = f"""
class MockKafkaConsumerResource:
    def poll_messages(self, topic, timeout_seconds=60):
        return [
{rows}
        ]
"""
    assert _check(src) == []


def test_a_nested_connection_class_counts_as_the_second_entry_point():
    # litellm `.../prisma_and_spend/conftest.py:323` — `InMemorySMTP` exposes one method, but that method defines a `_Conn` that hand-rolls starttls/login/ send_message.
    src = """
@dataclass
class InMemorySMTP:
    \"\"\"Captures outbound SMTP traffic for send_email tests.\"\"\"

    sent: list = field(default_factory=list)
    raise_on_send: Exception | None = None

    def server_factory(self):
        outer = self

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def starttls(self, **kwargs):
                self._starttls_called = True

            def login(self, user, password):
                self._login_args = (user, password)

            def send_message(self, msg, from_addr=None, to_addrs=None):
                outer.sent.append(msg)

        return _Conn
"""
    assert len(_check(src)) == 1


def test_the_nested_class_alone_without_a_method_stays_silent():
    body = "\n".join(f"    field_{i}: int = {i}" for i in range(26))
    src = f"""
@dataclass
class InMemorySMTP:
{body}

    class _Conn:
        pass
"""
    assert _check(src) == []


# FP guard: the library is already in use.                                     #


@pytest.mark.parametrize(
    ("import_line", "name"),
    [
        ("import fakeredis", "FakeRedisWithInfo"),
        ("from fakeredis import FakeAsyncRedis", "FakeRedisWithInfo"),
        ("import moto", "FakeS3Client"),
        ("from moto import mock_aws", "FakeS3Client"),
        ("import s3fs", "FakeS3Client"),
        ("import respx", "FakeOpenAIClient"),
        ("import vcr", "FakeOpenAIClient"),
        ("import pytest_recording", "FakeOpenAIClient"),
        ("import pytest_httpx", "FakeOpenAIClient"),
        ("import responses", "FakeOpenAIClient"),
        ("import aioresponses", "FakeOpenAIClient"),
        ("import testcontainers.postgres", "FakePostgresPool"),
        ("import gcp_storage_emulator", "FakeGcsBucket"),
        ("import mongomock", "FakeMongoCollection"),
        ("import pytest_postgresql", "FakePostgresPool"),
        ("import aiosmtpd", "FakeSmtpServer"),
        ("import mailpit", "FakeSmtpServer"),
        ("import requests_mock", "FakeRequestsSession"),
        ("import time_machine", "FakeClock"),
        ("import freezegun", "FakeClock"),
        ("import timemachine", "FakeClock"),
    ],
)
def test_a_file_already_using_the_library_is_exempt(import_line: str, name: str):
    # litellm `tests/llm_translation/test_vcr_redis_persister.py:413` defines
    # `_FakeRedisWithInfo` in a module that already imports fakeredis.
    src = f"""
{import_line}

class {name}:
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert _check(src) == []


def test_importing_an_unrelated_library_does_not_exempt():
    src = """
import moto

class FakeRedisClient:
    def get(self, key):
        return None

    def set(self, key, value):
        return True

    def delete(self, key):
        return 1
"""
    assert len(_check(src)) == 1


def test_a_relative_import_of_a_same_named_local_module_does_not_exempt():
    src = """
from . import responses

class FakeRequestsSession:
    def get(self, url):
        return None

    def post(self, url, data):
        return None

    def close(self):
        return None
"""
    assert len(_check(src)) == 1


# FP guard: scope.


def test_class_nested_in_a_function_is_exempt():
    src = """
def test_upload(tmp_path):
    class FakeS3Client:
        def put_object(self, Bucket, Key, Body):
            return {}

        def get_object(self, Bucket, Key):
            return {}

        def delete_object(self, Bucket, Key):
            return {}

    assert upload(FakeS3Client())
"""
    assert _check(src) == []


def test_class_nested_in_another_class_is_exempt():
    src = """
class TestUpload:
    class FakeS3Client:
        def put_object(self, Bucket, Key, Body):
            return {}

        def get_object(self, Bucket, Key):
            return {}

        def delete_object(self, Bucket, Key):
            return {}
"""
    assert _check(src) == []


def test_class_guarded_by_a_type_checking_block_is_exempt():
    # Not module-level, and never instantiated at runtime anyway.
    src = """
if TYPE_CHECKING:
    class FakeS3Client:
        def put_object(self, Bucket, Key, Body):
            return {}

        def get_object(self, Bucket, Key):
            return {}

        def delete_object(self, Bucket, Key):
            return {}
"""
    assert _check(src) == []


# Token-matching precision.                                                    #


@pytest.mark.parametrize(
    "name",
    [
        "FakeRequest",
        "FakeResponse",
        "FakeSession",
        "MockProcesses",
        "FakeTimer",
        "FakeTimeout",
        "MockDateFormatter",
        "FakeNowhereService",
    ],
)
def test_a_word_that_merely_contains_a_token_does_not_match(name: str):
    # `Requests` matches, `Request` does not; `ses` never matches as an infix, so
    # `Responses`/`Processes`/`Session` stay silent; `time`/`now` are not clock
    # tokens at all because `Timer`/`Timeout`/`Nowhere` are everywhere.
    src = f"""
class {name}:
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert _check(src) == []


@pytest.mark.parametrize("name", ["FakeRequestsSession", "MockSesClient", "FakeClockSource"])
def test_the_same_token_as_a_whole_word_does_match(name: str):
    src = f"""
class {name}:
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert len(_check(src)) == 1


def test_screaming_acronyms_split_correctly():
    src = """
class FakeGCSBucket:
    def upload(self, path):
        return None

    def download(self, path):
        return None

    def delete(self, path):
        return None
"""
    [diag] = _check(src)
    assert "fake-gcs-server" in diag.message


def test_a_double_naming_no_service_is_exempt():
    src = """
class FakeThing:
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3
"""
    assert _check(src) == []


def test_a_service_name_without_a_double_marker_is_exempt():
    src = """
class S3Client:
    def put_object(self, Bucket, Key, Body):
        return {}

    def get_object(self, Bucket, Key):
        return {}

    def delete_object(self, Bucket, Key):
        return {}
"""
    assert _check(src) == []


# Edge cases.                                                                  #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("class FakeS3Client(:\n    pass\n") == []


def test_reports_line_and_column_of_the_class():
    [diag] = _check(_FAKE_S3)
    assert (diag.line, diag.col) == (1, 1)
    assert diag.code == "SARJ059"


def test_multiple_hits_in_one_file_are_sorted_by_position():
    src = """
class FakeRedisClient:
    def get(self, k):
        return None

    def set(self, k, v):
        return True

    def delete(self, k):
        return 1


class FakeThing:
    def a(self):
        return 1

    def b(self):
        return 2

    def c(self):
        return 3


class FakeS3Client:
    def put_object(self, b, k, body):
        return {}

    def get_object(self, b, k):
        return {}

    def delete_object(self, b, k):
        return {}
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [d.line for d in diags] == sorted(d.line for d in diags)
    assert "fakeredis" in diags[0].message
    assert "moto" in diags[1].message


def test_decorated_class_reports_the_class_line_not_the_decorator():
    src = """
@dataclass
class FakeClock:
    now: float = 0.0

    def advance(self, seconds):
        self.now += seconds

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
"""
    [diag] = _check(src)
    assert diag.line == 3

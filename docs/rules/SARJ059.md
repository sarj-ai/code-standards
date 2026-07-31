# SARJ059 `prefer-library-fake` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_library_fake.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

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
  `is_test_path` alone misses (a first-party `common/testing/fakes.py`, and an
  observability `*_stub.py` module that sits outside any test directory),
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

Corpus evidence. Measured over 16 repositories, ~48,000 Python files: two
first-party repos — repo A (the flagship product) and repo B — plus django,
fastapi, celery, litellm,
langchain, prefect, sentry-python, airflow, mlflow, warehouse, superset, zulip,
dagster and saleor. Final counts: litellm 6, repo B 2, warehouse 1, and **zero**
on the other thirteen — including airflow and mlflow, whose provider suites are
dense with cloud-service doubles but keep them small or already depend on `moto`.
Every one of the 9 findings was read against its source and classified a true
positive (0% FP). Each guard below marked *(FP found)* removed a real finding
during hardening. repo A fires zero times: its doubles are all of its own ports or
of LiveKit plugin ABCs, and its one brand-named LLM stub is a three-line
namespace holder.

The design is dominated by what the corpora actually contain: the overwhelming
majority of hand-written doubles in both first-party repos are doubles of the
project's *own* ports (`InMemoryUserStore`, `FakeOrderService`,
`RecordingDocumentService`, `FakeWidgetService`, ~60 of them), for which no
library exists and none should. Only a recognised external-service token fires.

**The complementary `monkeypatch`/`mock.patch` shape is deliberately out of scope.**
A sweep for patches of SDK entry points (`boto3.client`, `time.time`,
`httpx.AsyncClient.request`, `<module>.datetime`) returns a large population that is
dominated, on django and celery, by a library patching the `datetime` or `boto3`
symbol *inside its own module under test* (celery's `t/unit/backends/test_elasticsearch.py`
alone does it 13 times, django's `tests/schema/tests.py:5476`, `tests/utils_tests/test_http.py:414`).
Those are not hand-rolled service doubles, and nothing in the AST distinguishes them
from repo A's genuine `mock.patch("app.audio.silence_monitor.time.time")` clock
patches. Adding the shape would have traded a 0% FP rate for a majority-FP one.

Deliberately NOT flagged:

* **pytest's collection classes** *(FP found)*. `Test` is not a double marker, it is
  pytest's class-collection convention. The two first-party repos contain 150+
  `class TestFoo:` grouping classes and zero `Test`-prefixed doubles. The first
  version of this rule reported one first-party data-extraction test's
  `class TestGeminiNullResults` — a plain pytest group that happened to contain
  the words "Gemini" and "Null". Any class whose name starts with `test` is skipped,
  which also covers celery's lowercase spelling (`class test_MongoBackend_no_mock`),
* **doubles of the project's own domain types.** `FakeWidgetService`,
  `InMemoryUserStore`, `RecordingCronMonitor`, `FakeOrderCapacityService` — a fake of
  your own port is the correct design and has no library. Only the branded external
  tokens in `_SERVICES` fire,
* **doubles of a framework's own extension point** *(FP found)*. LiveKit's `FakeRoom`,
  `FakeJobContext`, `FakeAgentSession`, `FakeSTT`, `FakeTTS`, `FakeVAD` and
  `ScriptedLLM` (the shared `fakes.py` module of each of two first-party repos)
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
* **recording spies that delegate to the real client.** One first-party site's
  `RecordingObjectStore` forwards 8 of its 10
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

## Implementation notes

### `_is_delegating_spy`

A recording decorator (a first-party `RecordingObjectStore`, which wraps a real
`GCSObjectStore`) hand-rolls no protocol at all — it observes one. Replacing
it with a library fake would defeat its purpose.

### `_has_substance`

Counts only non-dunder methods, so a record type with a long field list and a
`__init__` never clears the bar on line count alone. The line-count arm
additionally demands a second entry point — another method, or a nested
connection/session class anywhere inside the body — because a lone method
returning a big canned payload is a data factory, not a protocol
implementation. litellm's `InMemorySMTP` builds its `_Conn` inside
`server_factory`, which is why the nested scan is a full subtree walk.

### `_is_extension_point`

langchain's `FakeChatOpenAI(BaseChatModel)` and `_MockBedrockChatModel(BaseChatModel)`
are plugin implementations, not doubles of a provider's HTTP API — the brand in
the name describes which provider the plugin *imitates*, and there is no library
that fakes a `BaseChatModel`.

### `_is_double_module`

Broader than `is_test_path`: a repo's shared fakes routinely live in a
`testing/` or `test_fakes/` package, or in a `*_stub.py` module beside the
production code it doubles.

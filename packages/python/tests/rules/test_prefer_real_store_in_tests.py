from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_real_store_in_tests import PreferRealStoreInTests


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/fakes/user_store.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return PreferRealStoreInTests().check(Path(path), textwrap.dedent(source))


def _container_id(container: str) -> str:
    return container.replace(" ", "")


# The canonical shape: a dict written by one method and read by another.
_DICT_BACKED = """
class InMemoryUserStore(UserStore):
    def __init__(self) -> None:
        self._by_id: dict[str, User] = {}

    def add(self, user):
        self._by_id[user.id] = user

    async def get(self, id_):
        return self._by_id.get(id_)
"""


# --------------------------------------------------------------------------- #
# Path gating. Wider than `is_test_path` on purpose: both repos park reusable   #
# fakes in `testing/`, `test_fakes/` and `mock_*.py` inside production packages.#
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "tests/fakes/user_store.py",
        "tests/test_auth_service.py",
        # Not `user_store_test.py`: a module named for the port is the port's own
        # test, which the port-under-test guard below suppresses on purpose.
        "a/auth_service_test.py",
        "tests/conftest.py",
        "common/testing/fakes.py",
        "webserver/webserver/test_fakes/user_store.py",
        "common/adapters/fake_user_store.py",
        "common/adapters/mock_data_store.py",
        "app/doubles/user_store.py",
        "app/mocks/user_store.py",
        "app/stub_user_store.py",
    ],
)
def test_fires_in_test_and_test_double_paths(path: str):
    assert len(_check(_DICT_BACKED, path)) == 1


@pytest.mark.parametrize(
    "path",
    [
        "app/stores/user_store.py",
        "src/service.py",
        "app/adapters/postgres.py",
        "app/attestation/store.py",
    ],
)
def test_skips_production_paths(path: str):
    assert _check(_DICT_BACKED, path) == []


# --------------------------------------------------------------------------- #
# Positive: the dict-backed re-implementation.                                 #
# --------------------------------------------------------------------------- #


def test_flags_the_canonical_dict_backed_fake():
    assert len(_check(_DICT_BACKED)) == 1


@pytest.mark.parametrize(
    "container",
    [
        "{}",
        "[]",
        "set()",
        "dict()",
        "list()",
        "defaultdict(list)",
        "collections.defaultdict(set)",
        "OrderedDict()",
        "deque()",
        "{k: v for k, v in seed}",
        "[row for row in seed]",
    ],
    ids=_container_id,
)
def test_every_container_form_backs_a_store(container: str):
    src = f"""
class InMemoryUserStore(UserStore):
    def __init__(self) -> None:
        self._rows = {container}

    def add(self, user):
        self._rows.append(user)

    async def get(self, id_):
        return [r for r in self._rows if r.id == id_]
"""
    assert len(_check(src)) == 1


def test_dataclass_default_factory_backs_a_store():
    src = """
@dataclass
class FakeUserStore(UserStore):
    rows: dict[str, User] = field(default_factory=dict)

    def add(self, user):
        self.rows[user.id] = user

    async def get(self, id_):
        return self.rows.get(id_)
"""
    assert len(_check(src)) == 1


def test_class_level_container_backs_a_store():
    src = """
class FakeUserStore(UserStore):
    rows: dict[str, User] = {}

    def add(self, user):
        self.rows[user.id] = user

    async def get(self, id_):
        return self.rows.get(id_)
"""
    assert len(_check(src)) == 1


def test_container_bound_outside_init_still_counts():
    src = """
class FakeUserStore(UserStore):
    def reset(self):
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user

    async def get(self, id_):
        return self._rows.get(id_)
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "name",
    [
        "InMemoryUserStore",
        "MockUserStore",
        "FakeUserStore",
        "StubUserStore",
        "DummyUserStore",
        "_InMemoryUserStore",
        "InMemoryUserRepository",
        "FakeUserRepo",
        "MockUserDao",
        "StubUserDAO",
        "FakeAccountsDb",
        "FakeAccountsDatabase",
    ],
)
def test_double_marker_plus_port_tail_fires(name: str):
    src = f"""
class {name}(UserStore):
    def __init__(self) -> None:
        self._rows = {{}}

    def add(self, user):
        self._rows[user.id] = user

    async def get(self, id_):
        return self._rows.get(id_)
"""
    assert len(_check(src)) == 1


def test_trailing_marker_is_recognised_through_the_base_class():
    # `UserStoreFake` has no port tail of its own; the base supplies it.
    src = """
class UserStoreFake(UserStore):
    def __init__(self) -> None:
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user

    async def get(self, id_):
        return self._rows.get(id_)
"""
    [diag] = _check(src)
    assert "`UserStore`" in diag.message


def test_dotted_base_class_is_resolved():
    src = """
class FakeUsers(stores.UserRepository):
    def __init__(self) -> None:
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user

    async def get(self, id_):
        return self._rows.get(id_)
"""
    assert len(_check(src)) == 1


def test_generic_base_class_is_resolved():
    src = """
class FakeUsers(UserRepository[User]):
    def __init__(self) -> None:
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user

    async def get(self, id_):
        return self._rows.get(id_)
"""
    assert len(_check(src)) == 1


def test_fires_without_any_base_class_when_the_name_says_store():
    src = """
class InMemoryUserStore:
    def __init__(self) -> None:
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user

    async def get(self, id_):
        return self._rows.get(id_)
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "mutator",
    ["self._rows[user.id] = user", "self._rows.append(user)", "self._rows.update(user)", "del self._rows[user.id]"],
    ids=["setitem", "append", "update", "delitem"],
)
def test_every_mutation_form_counts_as_a_write(mutator: str):
    src = f"""
class FakeUserStore(UserStore):
    def __init__(self) -> None:
        self._rows = {{}}

    def add(self, user):
        {mutator}

    async def get(self, id_):
        return self._rows.get(id_)
"""
    assert len(_check(src)) == 1


def test_nested_class_inside_a_test_is_still_reached():
    src = """
def test_thing():
    class InMemoryUserStore(UserStore):
        def __init__(self) -> None:
            self._rows = {}

        def add(self, user):
            self._rows[user.id] = user

        async def get(self, id_):
            return self._rows.get(id_)

    assert InMemoryUserStore() is not None
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Positive: the hollow re-implementation. One first-party site's                #
# `StubUserStore` answers three calls from preset fields and abandons           #
# seven more.                                                                  #
# --------------------------------------------------------------------------- #


_HOLLOW = """
class StubUserStore(UserStore):
    def __init__(self, *, by_email) -> None:
        self._by_email = by_email

    async def get_by_email(self, *, email):
        return self._by_email

    async def update_last_login(self, *, user_id):
        return True

    async def upsert(self, *, data):
        raise NotImplementedError

    async def delete(self, *, user_id):
        raise NotImplementedError
"""


def test_flags_the_hollow_port_implementation():
    assert len(_check(_HOLLOW)) == 1


def test_house_style_message_assignment_before_the_raise_still_counts():
    src = """
class InMemoryUserStore(UserStore):
    async def get(self, id_):
        return None

    async def list_users(self):
        msg = "InMemoryUserStore.list_users is not implemented"
        raise NotImplementedError(msg)

    async def delete(self, id_):
        msg = "InMemoryUserStore.delete is not implemented"
        raise NotImplementedError(msg)
"""
    assert len(_check(src)) == 1


def test_a_docstring_above_the_raise_still_counts():
    src = """
class InMemoryUserStore(UserStore):
    async def get(self, id_):
        return None

    async def list_users(self):
        \"\"\"Not needed by these tests.\"\"\"
        raise NotImplementedError

    async def delete(self, id_):
        \"\"\"Not needed by these tests.\"\"\"
        raise NotImplementedError
"""
    assert len(_check(src)) == 1


# ---- false-positive guards -------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Guard: an in-memory backend that IS the product. `Cache`, `Storage`, `Queue`  #
# and `Session` are not persistence ports. django ships `DummyStorage(          #
# storage.Storage)` and `InMemoryStorage`; both must stay silent.               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    [
        "InMemoryCache",
        "InMemoryStorage",
        "DummyStorage",
        "DummyCache",
        "InMemorySessionRegistry",
        "InMemoryQueue",
        "InMemoryBackend",
        "FakeTable",
        "InMemoryBuffer",
    ],
)
def test_in_memory_product_backends_do_not_fire(name: str):
    src = f"""
class {name}:
    def __init__(self) -> None:
        self._rows = {{}}

    def set(self, key, value):
        self._rows[key] = value

    def get(self, key):
        return self._rows.get(key)
"""
    assert _check(src) == []


def test_the_same_body_named_for_a_persistence_port_does_fire():
    src = """
class InMemoryCacheStore:
    def __init__(self) -> None:
        self._rows = {}

    def set(self, key, value):
        self._rows[key] = value

    def get(self, key):
        return self._rows.get(key)
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize("name", ["Restore", "MockBookstore", "FakeRestoreHelper", "MockStorageAdapter"])
def test_a_lowercase_store_inside_a_word_is_not_a_port(name: str):
    src = f"""
class {name}:
    def __init__(self) -> None:
        self._rows = {{}}

    def add(self, key, value):
        self._rows[key] = value

    def get(self, key):
        return self._rows.get(key)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Guard: a double whose backing really is a real backend. A first-party         #
# `MockDataStore` in a production adapter package is a Redis-backed             #
# demo-mode feature, not a test double.                                         #
# --------------------------------------------------------------------------- #


def test_a_double_that_delegates_to_a_real_backend_does_not_fire():
    src = """
class MockDataStore:
    def __init__(self, cache_client, device_id) -> None:
        self.cache = cache_client
        self.device_id = device_id

    async def get_accounts(self):
        return await self.cache.get(self._key("accounts"))

    async def set_accounts(self, accounts):
        await self.cache.set(self._key("accounts"), accounts)
"""
    assert _check(src) == []


def test_the_same_class_keeping_its_own_rows_does_fire():
    src = """
class MockDataStore:
    def __init__(self, device_id) -> None:
        self.rows = {}
        self.device_id = device_id

    async def get_accounts(self):
        return self.rows.get("accounts")

    async def set_accounts(self, accounts):
        self.rows["accounts"] = accounts
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Guard: recording spies and canned-response doubles. A first-party             #
# `FakeAnalyticsStore` in a shared test-fakes module records a call and         #
# replays a canned row; each list is touched by exactly one method.             #
# --------------------------------------------------------------------------- #


def test_recording_spy_does_not_fire():
    src = """
class FakeAnalyticsStore(AnalyticsStore):
    def __init__(self, kpi_returns, series_return) -> None:
        self._kpi_returns = list(kpi_returns)
        self.kpi_calls = []
        self._series_return = list(series_return)
        self.series_calls = []

    async def get_kpi_metrics(self, organization_id, start, end):
        self.kpi_calls.append((organization_id, start, end))
        return self._kpi_returns[len(self.kpi_calls) - 1]

    async def get_time_series_data(self, organization_id, start, end):
        self.series_calls.append((organization_id, start, end))
        return list(self._series_return)
"""
    assert _check(src) == []


def test_a_spy_whose_recording_is_read_back_by_another_method_does_fire():
    src = """
class FakeAnalyticsStore(AnalyticsStore):
    def __init__(self) -> None:
        self.rows = []

    async def record(self, row):
        self.rows.append(row)

    async def get_kpi_metrics(self, organization_id):
        return [r for r in self.rows if r.org == organization_id]
"""
    assert len(_check(src)) == 1


def test_a_container_only_ever_written_does_not_fire():
    src = """
class FakeUserStore(UserStore):
    def __init__(self) -> None:
        self.calls = []

    async def upsert(self, user):
        self.calls.append(user)

    async def delete(self, id_):
        self.calls.append(id_)
"""
    assert _check(src) == []


def test_a_container_only_ever_read_does_not_fire():
    # Seeded in `__init__` and served read-only: canned data, not a second
    # implementation. `__init__` is deliberately not counted as a writer.
    src = """
class FakeUserStore(UserStore):
    def __init__(self, rows) -> None:
        self._rows = dict(rows)

    async def get(self, id_):
        return self._rows.get(id_)

    async def list_users(self):
        return list(self._rows.values())
"""
    assert _check(src) == []


def test_seeded_rows_that_a_method_also_writes_do_fire():
    src = """
class FakeUserStore(UserStore):
    def __init__(self, rows) -> None:
        self._rows = dict(rows)

    async def upsert(self, user):
        self._rows[user.id] = user

    async def get(self, id_):
        return self._rows.get(id_)
"""
    assert len(_check(src)) == 1


def test_a_local_container_inside_a_method_is_not_an_attribute():
    # `rows = {}` is a local. Counting it would make `self.rows`, which is bound
    # to an injected backend, look dict-backed.
    src = """
class FakeUserStore(UserStore):
    def __init__(self, backend) -> None:
        self.rows = backend

    async def upsert(self, user):
        rows = {}
        self.rows[user.id] = user

    async def get(self, id_):
        return self.rows.get(id_)
"""
    assert _check(src) == []


def test_the_same_class_with_the_container_bound_to_self_does_fire():
    src = """
class FakeUserStore(UserStore):
    def __init__(self, backend) -> None:
        self.rows = {}

    async def upsert(self, user):
        self.rows[user.id] = user

    async def get(self, id_):
        return self.rows.get(id_)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Guard: the never-touched port. A first-party `_UnusedTaskStore(TaskStore)`    #
# in an integration test raises from every method to assert that route          #
# discovery never invokes a handler.                                            #
# --------------------------------------------------------------------------- #


def test_a_port_that_raises_from_every_method_does_not_fire():
    src = """
class StubTaskStore(TaskStore):
    async def create(self, *, message):
        raise NotImplementedError

    async def get(self, task_id):
        raise NotImplementedError

    async def try_start(self, task_id):
        raise NotImplementedError
"""
    assert _check(src) == []


def test_one_live_method_beside_the_abandoned_ones_does_fire():
    src = """
class StubTaskStore(TaskStore):
    async def create(self, *, message):
        return self._preset

    async def get(self, task_id):
        raise NotImplementedError

    async def try_start(self, task_id):
        raise NotImplementedError
"""
    assert len(_check(src)) == 1


def test_a_single_abandoned_method_is_not_a_second_implementation():
    src = """
class StubTaskStore(TaskStore):
    async def create(self, *, message):
        return self._preset

    async def get(self, task_id):
        return self._preset

    async def try_start(self, task_id):
        raise NotImplementedError
"""
    assert _check(src) == []


def test_hollow_shape_requires_an_actual_port_base_class():
    # Without a base there is no port being implemented — just a throwaway class
    # that happens to be named for one.
    src = """
class StubTaskStore:
    async def create(self, *, message):
        return None

    async def get(self, task_id):
        raise NotImplementedError

    async def try_start(self, task_id):
        raise NotImplementedError
"""
    assert _check(src) == []


def test_raising_something_other_than_not_implemented_is_not_abandonment():
    src = """
class StubTaskStore(TaskStore):
    async def create(self, *, message):
        return None

    async def get(self, task_id):
        raise LookupError

    async def try_start(self, task_id):
        raise LookupError
"""
    assert _check(src) == []


def test_dunder_methods_are_not_counted_as_abandoned():
    src = """
class StubTaskStore(TaskStore):
    def __enter__(self):
        raise NotImplementedError

    def __exit__(self, *exc):
        raise NotImplementedError

    async def get(self, task_id):
        return None
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Guard: fault injectors built on the real store. This is the practice the rule #
# is asking for — one first-party repo has a dozen subclassing `Psql*`.         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "base",
    [
        "PsqlUserStore",
        "PostgresUserStore",
        "SqlUserStore",
        "SqliteUserStore",
        "ClickHouseAnalyticsStore",
        "RedisSessionStore",
        "MongoUserStore",
        "GcsObjectStore",
        "GCSObjectStore",
        "S3ObjectStore",
        "BigQueryAnalyticsStore",
    ],
)
def test_a_subclass_of_the_real_implementation_does_not_fire(base: str):
    src = f"""
class FakeUserStore({base}):
    def __init__(self, pool) -> None:
        super().__init__(pool)
        self._seen = {{}}

    async def upsert(self, user):
        self._seen[user.id] = user
        return await super().upsert(user)

    async def get(self, id_):
        return self._seen.get(id_)
"""
    assert _check(src) == []


def test_the_same_class_over_an_abstract_port_does_fire():
    src = """
class FakeUserStore(UserStore):
    def __init__(self, pool) -> None:
        self._seen = {}

    async def upsert(self, user):
        self._seen[user.id] = user

    async def get(self, id_):
        return self._seen.get(id_)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Guard: abstract bases, Protocols and TypedDicts are the port itself.          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("base", ["ABC", "abc.ABC", "Protocol", "TypedDict"])
def test_abstract_declarations_do_not_fire(base: str):
    src = f"""
class InMemoryUserStore({base}):
    def __init__(self) -> None:
        self._rows = {{}}

    def add(self, user):
        self._rows[user.id] = user

    def get(self, id_):
        return self._rows.get(id_)
"""
    assert _check(src) == []


def test_abc_metaclass_does_not_fire():
    src = """
class InMemoryUserStore(metaclass=ABCMeta):
    def __init__(self) -> None:
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user

    def get(self, id_):
        return self._rows.get(id_)
"""
    assert _check(src) == []


def test_an_abstractmethod_anywhere_makes_it_the_port():
    src = """
class InMemoryUserStore(UserStore):
    def __init__(self) -> None:
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user

    @abstractmethod
    def get(self, id_):
        return self._rows.get(id_)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Guard: ports that are not persistence. A queue, a pub/sub topic and a         #
# third-party HTTP API have no SQL implementation to prefer.                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    [
        "MockMessageEnqueuer",
        "FakeEventPublisher",
        "FakeCallService",
        "FakeBellClient",
        "StubVerifier",
        "MockPaymentsGateway",
        "FakeSallaApi",
        "InMemoryTaskQueue",
        "FakeGlobalSettingsService",
    ],
)
def test_non_persistence_ports_do_not_fire(name: str):
    src = f"""
class {name}:
    def __init__(self) -> None:
        self._sent = []

    def send(self, message):
        self._sent.append(message)

    def received(self):
        return list(self._sent)
"""
    assert _check(src) == []


def test_the_same_body_behind_a_store_name_does_fire():
    src = """
class FakeMessageStore:
    def __init__(self) -> None:
        self._sent = []

    def send(self, message):
        self._sent.append(message)

    def received(self):
        return list(self._sent)
"""
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "store = MagicMock(spec=AudioFileStore)",
        "store = AsyncMock()",
        "worker.store = MagicMock(spec=UserStore)",
    ],
)
def test_mock_objects_without_a_handwritten_class_are_out_of_scope(source: str):
    assert _check(source) == []


# --------------------------------------------------------------------------- #
# Guard: null objects and behaviour injectors are not doubles of the store.     #
# Four first-party doubles — `NullUpsertTokenStore`, `RecordingCrmDAO`,         #
# `AlwaysFailingProductsDAO` and `_NoneModelSettingsCallStore` — all live       #
# in the test tree and are all correct as written.                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    [
        "NullUpsertTokenStore",
        "NoopUserStore",
        "RecordingCrmDAO",
        "CountingGlobalPromptStore",
        "RaisingObjectStore",
        "AlwaysFailingProductsDAO",
        "_NoneModelSettingsCallStore",
        "MockeryUserStore",
    ],
)
def test_non_double_markers_do_not_fire(name: str):
    src = f"""
class {name}(UserStore):
    def __init__(self) -> None:
        self._rows = {{}}

    def add(self, user):
        self._rows[user.id] = user

    def get(self, id_):
        return self._rows.get(id_)
"""
    assert _check(src) == []


def test_a_class_with_no_methods_does_not_fire():
    src = """
class FakeUserStore(UserStore):
    rows: dict[str, User] = {}
"""
    assert _check(src) == []


def test_a_single_method_store_does_not_fire():
    src = """
class FakeUserStore(UserStore):
    def __init__(self) -> None:
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user
        return self._rows.get(user.id)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Guard: ports whose backend is not a relational database. There is no `Psql*`  #
# sibling to prefer for a vector index, a Redis lock or a task-state bag, so    #
# the advice would be wrong. All five of the rule's OSS hits were this shape or #
# the next one.                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "base"),
    [
        # langchain ships this: tests/unit_tests/indexes/test_indexing.py:40.
        ("InMemoryVectorStore", "VectorStore"),
        # litellm: test_pod_lock_manager.py:367, no base class at all.
        ("FakeRedisLockStore", ""),
        # airflow: test_spark_submit.py:489.
        ("FakeTaskStateStore", ""),
        ("FakeConversationMemoryStore", ""),
        ("MockRedisStore", ""),
        ("MockBlobStore", ""),
        ("StubDocRepository", ""),
        ("FakeGraphDb", ""),
        ("MockArtifactRepo", ""),
        ("FakeTraceStore", ""),
        # The qualifier may arrive only through the base class.
        ("FakeIndex", "VectorStore"),
    ],
)
def test_non_relational_ports_do_not_fire(name: str, base: str):
    src = f"""
class {name}({base}):
    def __init__(self) -> None:
        self._rows = {{}}

    def add(self, key, value):
        self._rows[key] = value

    def get(self, key):
        return self._rows.get(key)
"""
    assert _check(src) == []


@pytest.mark.parametrize("name", ["InMemoryApiKeyStore", "InMemoryObjectStore"])
def test_key_and_object_qualifiers_still_fire(name: str):
    # `Key` and `Object` are deliberately absent from the qualifier list: adding
    # them was measured and it kills these two first-party true positives,
    # both shared in-memory doubles living in a test-fakes package.
    src = f"""
class {name}:
    def __init__(self) -> None:
        self._rows = {{}}

    def add(self, key, value):
        self._rows[key] = value

    def get(self, key):
        return self._rows.get(key)
"""
    assert len(_check(src)) == 1


def test_a_bare_in_memory_store_is_not_read_as_the_memory_qualifier():
    # The double marker is stripped before the qualifier is matched, so
    # `InMemoryStore` reduces to `Store` rather than to `MemoryStore`.
    src = """
class InMemoryStore(UserStore):
    def __init__(self) -> None:
        self._rows = {}

    def add(self, key, value):
        self._rows[key] = value

    def get(self, key):
        return self._rows.get(key)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Guard: the port under test. mlflow's `MockAbstractStore(AbstractStore)`       #
# (tests/store/model_registry/test_abstract_store.py:23) is the minimal         #
# concrete subclass needed to exercise the ABC's template methods — the ABC is  #
# the system under test.                                                        #
# --------------------------------------------------------------------------- #


_PORT_UNDER_TEST = """
class MockAbstractStore(AbstractStore):
    def __init__(self) -> None:
        self.model_versions = {}

    def create_model_version(self, name, version):
        self.model_versions[name] = version

    def get_model_version(self, name):
        return self.model_versions.get(name)
"""


@pytest.mark.parametrize("path", ["tests/store/test_abstract_store.py", "tests/store/abstract_store_test.py"])
def test_the_module_that_tests_the_port_does_not_fire(path: str):
    assert _check(_PORT_UNDER_TEST, path) == []


@pytest.mark.parametrize("path", ["tests/store/test_registry.py", "tests/store/test_abstract_store_extras.py"])
def test_the_same_class_in_any_other_module_does_fire(path: str):
    assert len(_check(_PORT_UNDER_TEST, path)) == 1


def test_the_port_under_test_is_recognised_without_a_base_class():
    # airflow's `FakeTaskStateStore` in test_task_state_store.py:47 names no base;
    # the subject comes from the class name with its double marker stripped.
    src = """
class FakeUserStore:
    def __init__(self) -> None:
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user

    def get(self, id_):
        return self._rows.get(id_)
"""
    assert _check(src, "tests/test_user_store.py") == []
    assert len(_check(src, "tests/test_user_service.py")) == 1


# --------------------------------------------------------------------------- #
# Message and edge cases.                                                      #
# --------------------------------------------------------------------------- #


_EXPECTED_MESSAGE = (
    "`InMemoryUserStore` re-implements the `UserStore` persistence port in memory, so every test that "
    "uses it verifies a dict rather than the real store — unique and foreign-key constraints, "
    "`ON CONFLICT` upserts, transaction rollback, `ORDER BY` and NULL ordering, pagination and "
    "concurrent writes all differ in the backend, and the suite stays green while production breaks. "
    "Drive the real `UserStore` implementation — the one named for its backend, `Psql*` by this "
    "codebase's convention — against the test database fixture, and subclass it if you need to inject "
    "a failure."
)

_EXPECTED_PORTLESS_MESSAGE = (
    "`FakeMessageStore` re-implements a persistence port in memory, so every test that uses it "
    "verifies a dict rather than the real store — unique and foreign-key constraints, `ON CONFLICT` "
    "upserts, transaction rollback, `ORDER BY` and NULL ordering, pagination and concurrent writes "
    "all differ in the backend, and the suite stays green while production breaks. Drive the real "
    "implementation — the one named for its backend, `Psql*` by this codebase's convention — against "
    "the test database fixture, and subclass it if you need to inject a failure."
)


def test_message_is_exactly_this():
    [diag] = _check(_DICT_BACKED)
    assert diag.message == _EXPECTED_MESSAGE


def test_a_class_with_no_port_base_is_not_named_as_its_own_port():
    # The old fallback read "`FakeMessageStore` re-implements the `FakeMessageStore`
    # persistence port", which was 3 of the rule's 5 false positives on OSS.
    src = """
class FakeMessageStore:
    def __init__(self) -> None:
        self._rows = {}

    def put(self, message):
        self._rows[message.id] = message

    def get(self, id_):
        return self._rows.get(id_)
"""
    [diag] = _check(src)
    assert diag.message == _EXPECTED_PORTLESS_MESSAGE
    assert "the `FakeMessageStore` persistence port" not in diag.message


def test_reports_line_and_column_of_the_class():
    [diag] = _check(_DICT_BACKED)
    assert (diag.line, diag.col) == (2, 1)
    assert diag.code == "SARJ058"


def test_reports_the_position_of_a_nested_class():
    src = """
class TestUserService:
    def test_lookup(self):
        with pytest.raises(LookupError):
            class InMemoryUserStore(UserStore):
                def __init__(self) -> None:
                    self._rows = {}

                def add(self, user):
                    self._rows[user.id] = user

                async def get(self, id_):
                    return self._rows.get(id_)
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (5, 13)


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("class InMemoryUserStore(:\n    pass\n") == []


def test_multiple_stores_in_one_module():
    src = """
class InMemoryUserStore(UserStore):
    def __init__(self) -> None:
        self._rows = {}

    def add(self, user):
        self._rows[user.id] = user

    def get(self, id_):
        return self._rows.get(id_)


class GoodService:
    pass


class InMemoryApiKeyStore(ApiKeyStore):
    def __init__(self) -> None:
        self._rows = {}

    def add(self, key):
        self._rows[key.hash] = key

    def get(self, key_hash):
        return self._rows.get(key_hash)
"""
    diags = _check(src)
    assert len(diags) == 2
    assert [d.line for d in diags] == sorted(d.line for d in diags)

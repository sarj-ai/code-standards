from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_service_behavior_in_settings import NoServiceBehaviorInSettings


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/scheduler_batch_settings.py") -> list[Diagnostic]:
    return NoServiceBehaviorInSettings().check(Path(path), textwrap.dedent(source))


_PUBLIC_EXAMPLES = NoServiceBehaviorInSettings.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_flags_settings_class_that_orchestrates_injected_stores() -> None:
    diagnostics = _check(
        """
        class SchedulerBatchSettings:
            def __init__(self, schedule_store: ScheduleConfigStore, call_store: ScheduledCallStore) -> None:
                self._schedule_store = schedule_store
                self._call_store = call_store

            async def policy_for_new_batch(self, batch_id: str) -> str:
                return (await self._schedule_store.create(batch_id)).id

            async def repoint(self, batch_id: str) -> int:
                return await self._call_store.repoint(batch_id)
        """
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ441"
    assert diagnostics[0].severity is Severity.ERROR
    assert "`policy_for_new_batch`, `repoint`" in diagnostics[0].message


def test_flags_explicit_record_that_calls_a_collaborator() -> None:
    diagnostics = _check(
        """
        @dataclass
        class DeliveryConfig:
            publisher: EventPublisher

            async def deliver(self, event: Event) -> None:
                await self.publisher.publish(event)
        """
    )
    assert len(diagnostics) == 1


def test_allows_passive_plain_container() -> None:
    assert (
        _check(
            """
        class BatchSettings:
            def __init__(self, retry_limit: int) -> None:
                self.retry_limit = retry_limit
        """
        )
        == []
    )


def test_allows_pure_computed_behavior() -> None:
    assert (
        _check(
            """
        class RetryConfig:
            def __init__(self, attempts: int) -> None:
                self.attempts = attempts

            def permits_retry(self, completed: int) -> bool:
                return completed < self.attempts
        """
        )
        == []
    )


@pytest.mark.parametrize("decorator", ["property", "computed_field", "field_validator('name')"])
def test_allows_framework_data_methods(decorator: str) -> None:
    source = f"""
        class AppSettings:
            client: MetadataClient

            @{decorator}
            def display_name(self) -> str:
                return self.client.name()
    """
    assert _check(source) == []


def test_allows_same_behavior_under_honest_service_name() -> None:
    assert (
        _check(
            """
        class SchedulerBatchPolicyService:
            def __init__(self, store: ScheduleStore) -> None:
                self.store = store

            async def repoint(self, batch_id: str) -> int:
                return await self.store.repoint(batch_id)
        """
        )
        == []
    )


@pytest.mark.parametrize("path", ["tests/test_settings.py", "app/tests/fakes/settings.py"])
def test_allows_tests(path: str) -> None:
    source = "class AppSettings:\n    client: ApiClient\n    def load(self): return self.client.load()\n"
    assert _check(source, path) == []


def test_exact_suppression_is_respected() -> None:
    source = """
        class LegacySettings:  # sarj-noqa: SARJ441 -- migration boundary owns behavior until cutover
            client: ApiClient

            def load(self):
                return self.client.load()
    """
    assert _check(source) == []


def test_malformed_source_is_ignored() -> None:
    assert _check("class BrokenSettings(") == []


@pytest.mark.parametrize(
    "method",
    [
        "def build(self):\n    def callback(self):\n        return self.client.fetch()\n    return callback",
        "def build(self):\n    class Local:\n        def run(self):\n            return self.client.fetch()\n    return Local",
        "def build(self):\n    self = other\n    return self.client.fetch()",
    ],
)
def test_does_not_attribute_unrelated_receiver_calls_to_settings(method: str) -> None:
    source = "class AppSettings:\n    client: RemoteClient\n" + textwrap.indent(method, "    ")
    assert _check(source) == []


@pytest.mark.parametrize("annotation", ["list[RemoteClient]", "dict[str, RemoteClient]", "type[RemoteClient]"])
def test_collection_or_class_of_collaborators_is_not_an_injected_service(annotation: str) -> None:
    assert (
        _check(f"class AppSettings:\n    clients: {annotation}\n    def clear(self):\n        self.clients.clear()\n")
        == []
    )


@pytest.mark.parametrize(
    "annotation",
    [
        "RemoteClient | None",
        "Optional[RemoteClient]",
        "Union[RemoteClient, None]",
        "Annotated[RemoteClient, 'service']",
        "RemoteClient[str]",
    ],
)
def test_wrapped_collaborator_still_reports_direct_orchestration(annotation: str) -> None:
    source = f"class AppSettings:\n    client: {annotation}\n    def fetch(self): return self.client.fetch()\n"
    assert len(_check(source)) == 1

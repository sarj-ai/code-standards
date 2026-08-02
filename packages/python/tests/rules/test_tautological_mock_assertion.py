from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.tautological_mock_assertion import TautologicalMockAssertion


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/agent/tests/test_main_helpers.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return TautologicalMockAssertion().check(Path(path), source)


# The canonical shape: the literal handed to the stub is handed straight back.
_TAUTOLOGY = """
def test_get_user():
    store = MagicMock()
    store.get.return_value = {"id": 7}
    result = service.get_user(store)
    assert result == {"id": 7}
"""


# --------------------------------------------------------------------------- #
# Path gating.                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "a/tests/test_y.py"])
def test_fires_in_collected_test_paths(path: str):
    assert len(_check(_TAUTOLOGY, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py", "agent/main.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_TAUTOLOGY, path) == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/helpers.py",
        "tests/conftest.py",
        "black/tests/data/cases/fmtonoff5.py",
    ],
)
def test_skips_modules_pytest_never_collects(path: str):
    assert _check(_TAUTOLOGY, path) == []


def test_skips_uncollected_script_probes():
    assert _check(_TAUTOLOGY, "chat/scripts/test_llm_providers.py") == []


# --------------------------------------------------------------------------- #
# Positive: the shapes that stub a value and then assert on it.                #
# --------------------------------------------------------------------------- #


def test_flags_return_value_literal_round_trip():
    assert len(_check(_TAUTOLOGY)) == 1


def test_flags_sentinel_name_bound_to_a_literal():
    src = """
def test_get_user():
    expected = {"id": 7, "name": "ada"}
    store = MagicMock()
    store.get.return_value = expected
    result = service.get_user(store)
    assert result == expected
"""
    assert len(_check(src)) == 1


def test_flags_mock_sentinel_attribute():
    src = """
def test_decode():
    kv_decode.return_value = sentinel.decoded
    result = backend.decode(payload)
    assert result == sentinel.decoded
"""
    assert len(_check(src)) == 1


def test_flags_patch_keyword_return_value():
    src = """
def test_run():
    with patch("mod.fetch", return_value={"a": 1, "b": 2}):
        result = mod.run()
    assert result == {"a": 1, "b": 2}
"""
    assert len(_check(src)) == 1


def test_flags_patch_used_as_a_decorator():
    src = """
@patch("mod.fetch", return_value="payload-v3")
def test_run(fetch):
    result = mod.run()
    assert result == "payload-v3"
"""
    assert len(_check(src)) == 1


def test_flags_mocker_patch_return_value():
    src = """
def test_run(mocker):
    mocker.patch("mod.fetch", return_value="payload-v3")
    result = mod.run()
    assert result == "payload-v3"
"""
    assert len(_check(src)) == 1


def test_flags_side_effect_list_echoed_as_a_list():
    src = """
def test_all():
    client.fetch.side_effect = ["first", "second"]
    results = drain(client)
    assert results == ["first", "second"]
"""
    assert len(_check(src)) == 1


def test_flags_comparison_against_return_value_itself():
    src = """
def test_acquire_connection_without_pool():
    with patch.object(app, "connection_for_write") as conn:
        result = app.acquire(pool=False)
    assert result == conn.return_value
"""
    assert len(_check(src)) == 1


def test_flags_monkeypatch_setattr_lambda_stub():
    # The mock-free spelling of `return_value=`; this standard's ruff config
    # bans `unittest.mock`, so this is the shape it meets most.
    src = """
def test_load(monkeypatch):
    monkeypatch.setattr(main, "load_config", lambda: "prompt-cfg")
    result = load_after_pool()
    assert result == "prompt-cfg"
"""
    assert len(_check(src)) == 1


def test_flags_identity_comparison():
    src = """
def test_returns_transcript():
    transcript = Mock()
    adapter.get_transcript.return_value = transcript
    result = manager.parse(adapter)
    assert result is transcript
"""
    assert len(_check(src)) == 1


def test_flags_awaited_result():
    src = """
async def test_get_settings():
    service.get = AsyncMock(return_value="settings-data")
    assert await load_settings(service) == "settings-data"
"""
    assert len(_check(src)) == 1


def test_flags_reversed_operand_order():
    src = """
def test_get_user():
    store.get.return_value = {"id": 7}
    result = service.get_user(store)
    assert {"id": 7} == result
"""
    assert len(_check(src)) == 1


def test_flags_test_method_in_a_class():
    src = """
class TestUsers:
    def test_get_user(self):
        store.get.return_value = {"id": 7}
        result = service.get_user(store)
        assert result == {"id": 7}
"""
    assert len(_check(src)) == 1


def test_flags_a_test_whose_every_assertion_is_an_echo():
    src = """
def test_both():
    left.get.return_value = {"id": 7}
    right.get.return_value = {"id": 8}
    a = service.a(left)
    b = service.b(right)
    assert a == {"id": 7}
    assert b == {"id": 8}
"""
    assert len(_check(src)) == 1


def test_message_explains_the_fix():
    [diag] = _check(_TAUTOLOGY)
    assert "configured the mock to return" in diag.message
    assert "Assert on what the code *did*" in diag.message


def test_the_exact_message_text():
    [diag] = _check(_TAUTOLOGY)
    assert diag.message == (
        "this is the test's only assertion and it compares against the value the test itself configured "
        "the mock to return, so it holds however the code under test behaves — it verifies "
        "`unittest.mock`, not this codebase. Assert on what the code *did*: the arguments it passed, the "
        "transformation it applied, or the effect it performed."
    )


# --------------------------------------------------------------------------- #
# FP guard: an assertion that reaches into the result. 16 of the 44 structural #
# matches across the audited corpora were this shape, all real assertions.     #
# --------------------------------------------------------------------------- #


def test_attribute_of_the_result_is_exempt():
    # A first-party test site — patching `time.time` and asserting the
    # debounce timestamp was recorded is real behaviour, not a mock echo.
    src = """
def test_last_send_time_updated():
    with patch.object(nav.time, "time", return_value=4242.0):
        tool.send_dtmf(ctx, "1")
    assert tool._last_send_time == 4242.0
"""
    assert _check(src) == []


def test_the_same_test_without_the_attribute_hop_fires():
    src = """
def test_last_send_time_updated():
    with patch.object(nav.time, "time", return_value=4242.0):
        stamp = tool.send_dtmf(ctx, "1")
    assert stamp == 4242.0
"""
    assert len(_check(src)) == 1


def test_subscript_of_the_result_is_exempt():
    # A first-party test site — a FastAPI TestClient envelope assertion.
    src = """
def test_recording_url(client):
    object_store.sign.return_value = "https://signed.example/abc.mp4"
    r = client.get("/calls/1")
    assert r.json()["data"]["recording_url"] == "https://signed.example/abc.mp4"
"""
    assert _check(src) == []


def test_the_same_test_without_the_subscript_hop_fires():
    src = """
def test_recording_url(client):
    object_store.sign.return_value = "https://signed.example/abc.mp4"
    url = client.signed_url("/calls/1", store=object_store)
    assert url == "https://signed.example/abc.mp4"
"""
    assert len(_check(src)) == 1


def test_a_local_bound_to_a_subscript_of_the_result_is_exempt():
    # saleor `graphql/shop/tests/queries/test_shop.py:515` — a full GraphQL round
    # trip whose envelope is unpacked into `data` before the comparison. Same
    # assertion as `test_subscript_of_the_result_is_exempt`, spelled over two
    # statements.
    src = """
def test_query_available_external_authentications(external_auths, user_api_client, monkeypatch):
    monkeypatch.setattr(
        "saleor.plugins.manager.PluginsManager.list_external_authentications",
        lambda self, active_only: external_auths,
    )
    response = user_api_client.post_graphql(QUERY)
    content = get_graphql_content(response)
    data = content["data"]["shop"]["availableExternalAuthentications"]
    assert data == external_auths
"""
    assert _check(src) == []


def test_a_local_bound_to_an_attribute_of_the_result_is_exempt():
    src = """
def test_last_send_time_updated():
    with patch.object(nav.time, "time", return_value=4242.0):
        tool.send_dtmf(ctx, "1")
    stamp = tool._last_send_time
    assert stamp == 4242.0
"""
    assert _check(src) == []


def test_a_local_bound_to_the_whole_result_still_fires():
    # The same two-statement shape without the reach-in: `result` is the whole
    # thing the code produced, so the echo is still an echo.
    src = """
def test_query_available_external_authentications(external_auths, user_api_client, monkeypatch):
    monkeypatch.setattr(
        "saleor.plugins.manager.PluginsManager.list_external_authentications",
        lambda self, active_only: external_auths,
    )
    response = user_api_client.post_graphql(QUERY)
    data = get_graphql_content(response)
    assert data == external_auths
"""
    assert len(_check(src)) == 1


def test_a_rebound_local_is_too_ambiguous_to_resolve():
    # `data` names two different things; the rule does not guess which one the
    # assertion is about, so the reach-in exemption does not apply.
    src = """
def test_recording_url(client):
    object_store.sign.return_value = "https://signed.example/abc.mp4"
    data = client.get("/calls/1", store=object_store)
    data = data.json()["data"]["recording_url"]
    assert data == "https://signed.example/abc.mp4"
"""
    assert len(_check(src)) == 1


def test_an_alias_chain_is_followed_to_the_reach_in():
    # `expected` renames `url`, which reaches into `body`; one hop is not enough.
    src = """
def test_recording_url(client):
    object_store.sign.return_value = "https://signed.example/abc.mp4"
    body = client.get("/calls/1").json()
    url = body["data"]["recording_url"]
    expected = url
    assert expected == "https://signed.example/abc.mp4"
"""
    assert _check(src) == []


def test_a_circular_alias_pair_terminates():
    # Each name is still bound exactly once, so both survive into the alias map
    # and resolving one walks into the other. Without a visited set this hangs.
    src = """
def test_swap():
    store.get.return_value = {"id": 7}
    service.run(store)
    a = b
    b = a
    assert a == {"id": 7}
"""
    assert len(_check(src)) == 1


def test_a_chained_assignment_binds_every_name_it_names():
    src = """
def test_recording_url(client):
    object_store.sign.return_value = "https://signed.example/abc.mp4"
    body = client.get("/calls/1").json()
    url = shown = body["data"]["recording_url"]
    assert shown == "https://signed.example/abc.mp4"
"""
    assert _check(src) == []


def test_real_end_to_end_client_assertion_never_fires():
    src = """
def test_read_main(client):
    response = client.get("/items/42")
    assert response.json() == {"id": 42, "name": "widget"}
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: a stub on a *piece* of a double the body never hands over. The      #
# code has to navigate the chain for the comparison to hold, so the assertion   #
# also says it navigated correctly. 27 of the 137 census findings were this.    #
# --------------------------------------------------------------------------- #


def test_stub_on_a_sub_object_of_an_unconnected_double_is_exempt():
    # airflow common SQL `test_dbapi.py:600`. `self.cur` is wired to `self.db_hook`
    # in `setUp`, so a single-file rule cannot show the hook reaches the cursor —
    # and `run(...)` really does have to walk connection -> cursor -> fetchall.
    src = """
class TestDbApiHook:
    def test_run_fetch_all_handler_select_1(self):
        rows = [[1]]
        self.cur.fetchall.return_value = rows
        assert rows == self.db_hook.run(sql="SELECT 1", handler=fetch_all_handler)
"""
    assert _check(src) == []


def test_the_same_stub_fires_once_the_body_hands_the_double_over():
    src = """
class TestDbApiHook:
    def test_run_fetch_all_handler_select_1(self):
        rows = [[1]]
        self.cur.fetchall.return_value = rows
        hook = DbApiHook(cursor=self.cur)
        assert rows == hook.run(sql="SELECT 1", handler=fetch_all_handler)
"""
    assert len(_check(src)) == 1


def test_stub_on_the_whole_double_still_fires():
    # airflow `test_glue_databrew.py:38` — the patch replaces the very method the
    # test then calls, so there is no chain to navigate and nothing else can hold.
    src = """
class TestGlueDataBrewHook:
    def test_get_job_state(self, get_job_state_mock):
        get_job_state_mock.return_value = "SUCCEEDED"
        hook = GlueDataBrewHook()
        result = hook.get_job_state("job", "run")
        assert result == "SUCCEEDED"
"""
    assert len(_check(src)) == 1


def test_double_assigned_onto_the_unit_counts_as_handed_over():
    # airflow `test_openai.py:66`: `operator.hook = mock_hook_instance` is an
    # attribute assignment, but the double is on its *value* side, so it is
    # handed over rather than configured.
    src = """
def test_execute_with_input_text():
    mock_hook_instance = Mock(spec=OpenAIHook)
    mock_hook_instance.create_embeddings.return_value = [1.0, 2.0, 3.0]
    operator.hook = mock_hook_instance
    embeddings = operator.execute(Context())
    assert embeddings == [1.0, 2.0, 3.0]
"""
    assert len(_check(src)) == 1


def test_an_alias_naming_a_piece_of_a_double_does_not_dodge_the_guard():
    # airflow `test_gcs.py:1874`. Each binding only gives part of the double a
    # shorter name, so following the aliases lands back on `mock_service`, which
    # the body never hands to the hook.
    src = """
class TestGCSHook:
    def test_object_get_blob(self, mock_service):
        mock_blob = mock.MagicMock()
        bucket_method = mock_service.return_value.bucket
        get_blob_method = bucket_method.return_value.get_blob
        get_blob_method.return_value = mock_blob
        response = self.gcs_hook._get_blob(bucket_name="b", object_name="o")
        assert response == mock_blob
"""
    assert _check(src) == []


def test_a_chain_rooted_in_a_call_can_never_be_shown_reachable():
    # mlflow `tests/metrics/genai/test_model_utils.py:523`.
    src = """
def test_call_deployments_api_no_endpoint_type():
    with mock.patch("mlflow.deployments.get_deploy_client") as mock_get_deploy_client:
        mock_get_deploy_client().predict.return_value = {"result": "ok"}
        response = call_deployments_api(deployment_uri="my-endpoint")
        assert response == {"result": "ok"}
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "installer",
    [
        'monkeypatch.setattr(main, "load_config", lambda: "prompt-cfg")',
        'mock.patch("main.load_config", return_value="prompt-cfg")',
        'mock.patch("main.load_config", lambda: "prompt-cfg")',
    ],
)
def test_a_spelling_that_installs_the_double_names_what_it_replaces(installer: str):
    # The guard only applies to `<recv>.return_value = X`. An installer call says
    # which symbol the double stands in for, so reachability is not in doubt.
    src = f"""
def test_prompt_config(monkeypatch):
    {installer}
    result = load_prompt_config()
    assert result == "prompt-cfg"
"""
    assert len(_check(src)) == 1


def test_a_bare_self_prefix_is_not_evidence_of_reach():
    # Every attribute of a `TestCase` shares `self`, so `self.db_hook` in the
    # compared call must not license a stub on `self.cur`.
    src = """
class TestHook:
    def test_records(self):
        rows = [("a",), ("b",)]
        self.cur.fetchall.return_value = rows
        assert rows == self.db_hook.get_records("SQL")
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: round trips. The value also flows into the code under test, so the #
# comparison pins a passthrough the code could have broken.                    #
# --------------------------------------------------------------------------- #


def test_value_also_passed_to_the_code_under_test_is_exempt():
    src = """
def test_save():
    store.save.return_value = record
    assert service.save(store, record) == record
"""
    assert _check(src) == []


def test_value_not_passed_in_still_fires():
    src = """
def test_save():
    store.save.return_value = record
    assert service.save(store) == record
"""
    assert len(_check(src)) == 1


def test_serialization_round_trip_is_exempt():
    src = """
def test_round_trip():
    codec.encode.return_value = blob
    assert loads(dumps(payload)) == payload
"""
    assert _check(src) == []


def test_configuring_the_double_does_not_count_as_a_third_use():
    # `participant.identity = ...` configures the double; it does not hand the
    # double to the code under test.
    src = """
async def test_participant_joined_returns_participant():
    participant = Mock()
    participant.identity = "caller-1"
    ctx.wait_for_participant = AsyncMock(return_value=participant)
    result = await wait_for_participant_with_timeout(ctx=ctx)
    assert result is participant
"""
    assert len(_check(src)) == 1


def test_interrogating_the_double_does_not_count_as_a_third_use():
    src = """
def test_room():
    rtc.Room.return_value = room
    result = executor.connect(rtc)
    assert result is room
    log(room.name)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: the test also verifies what the code did. This is most of the      #
# rule — it removed the only false positives in celery and fastapi.            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "verification",
    [
        "store.get.assert_called_once_with(7)",
        "store.get.assert_called_once()",
        "store.get.assert_awaited_once()",
        "store.get.assert_not_called()",
        "self.assertEqual(store.get.call_count, 1)",
        "_assert_request_shape(store.get.call_args)",
        "assert_valid(store)",
    ],
)
def test_any_other_verification_exempts_the_test(verification: str):
    src = f"""
def test_get_user():
    store.get.return_value = {{"id": 7}}
    result = service.get_user(store)
    assert result == {{"id": 7}}
    {verification}
"""
    assert _check(src) == []


def test_dropping_the_verification_call_fires():
    src = """
def test_get_user():
    store.get.return_value = {"id": 7}
    result = service.get_user(store)
    assert result == {"id": 7}
    log(store)
"""
    assert len(_check(src)) == 1


def test_pytest_raises_exempts_the_test():
    src = """
def test_retry():
    task.run.return_value = "payload-v3"
    assert task.execute() == "payload-v3"
    with pytest.raises(ValueError):
        task.execute(bad=True)
"""
    assert _check(src) == []


def test_delegation_test_with_a_call_count_check_is_exempt():
    # celery test_app.py:2075 — the passthrough IS the branch under test.
    src = """
def test_acquire_connection_without_pool():
    with patch.object(app, "connection_for_write") as conn:
        result = app.acquire(pool=False)
        conn.assert_called_once()
        assert result == conn.return_value
"""
    assert _check(src) == []


def test_coverage_only_delegation_test_with_a_close_check_is_exempt():
    # fastapi test_tutorial007.py:23 — `close.assert_called_once()` checks the
    # dependency tears the session down.
    src = """
def test_get_db():
    session = Mock()
    with patch("docs_src.dependencies.DBSession", return_value=session):
        value = run_dependency()
    assert value is session
    session.close.assert_called_once()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: a real assertion alongside the echo. Every assertion must be an    #
# echo, or the test is doing real work.                                        #
# --------------------------------------------------------------------------- #


def test_real_assertion_alongside_the_echo_is_exempt():
    # A first-party test site — the echo is a redundant first line in a
    # test that then checks the request it built.
    src = """
async def test_builds_request_and_returns_response():
    ctx.api.sip.create = AsyncMock(return_value=sip_response)
    result = await create_participant(ctx, settings)
    assert result is sip_response
    request = capture(ctx)
    assert request.sip_call_to == "+15550001111"
"""
    assert _check(src) == []


def test_removing_the_real_assertion_fires():
    src = """
async def test_builds_request_and_returns_response():
    ctx.api.sip.create = AsyncMock(return_value=sip_response)
    result = await create_participant(ctx, settings)
    assert result is sip_response
"""
    assert len(_check(src)) == 1


def test_a_test_with_no_assertions_at_all_is_exempt():
    src = """
def test_get_user():
    store.get.return_value = {"id": 7}
    service.get_user(store)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: trivial stub values. `return_value = None` + `assert x is None`    #
# pins a code path that genuinely could have returned something.               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["None", "True", "False", "0", "1", '""', "b''", "[]", "{}", "()", "0.0", "1.0"])
def test_trivial_stub_values_are_exempt(value: str):
    src = f"""
def test_get_user():
    store.get.return_value = {value}
    result = service.get_user(store)
    assert result == {value}
"""
    assert _check(src) == []


@pytest.mark.parametrize("value", ["2", "-1", '"ok"', '{"id": 7}', "[1, 2]", "(1, 2)", "3.5"])
def test_non_trivial_stub_values_fire(value: str):
    src = f"""
def test_get_user():
    store.get.return_value = {value}
    result = service.get_user(store)
    assert result == {value}
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: the expected value was never stubbed.                             #
# --------------------------------------------------------------------------- #


def test_expectation_the_body_never_stubbed_is_exempt():
    src = """
def test_get_user():
    store.get.return_value = {"id": 7}
    result = service.get_user(store)
    assert result == {"id": 7, "name": "ada"}
"""
    assert _check(src) == []


def test_parametrized_expected_column_is_exempt():
    src = """
@pytest.mark.parametrize(("raw", "expected"), [(1, "one"), (2, "two")])
def test_render(raw, expected):
    store.get.return_value = raw
    result = service.render(store)
    assert result == expected
"""
    assert _check(src) == []


def test_parametrized_value_used_as_both_stub_and_expectation_fires():
    src = """
@pytest.mark.parametrize("payload", [{"a": 1}, {"b": 2}])
def test_passthrough(payload):
    store.get.return_value = payload
    result = service.get(store)
    assert result == payload
"""
    assert len(_check(src)) == 1


def test_a_plain_attribute_assignment_is_not_a_stub():
    src = """
def test_status():
    response.status_code = 200
    result = client.send()
    assert result == 200
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: assertion shapes that are not a single equality comparison.        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "assertion",
    [
        'result != {"id": 7}',
        'result in [{"id": 7}]',
        'result is not {"id": 7}',
        '{"id": 7} < result < {"id": 9}',
        "result",
        'result == {"id": 7} or fallback',
        'len(result) == 1 and result == {"id": 7}',
    ],
)
def test_non_equality_assertion_shapes_are_exempt(assertion: str):
    src = f"""
def test_get_user():
    store.get.return_value = {{"id": 7}}
    result = service.get_user(store)
    assert {assertion}
"""
    assert _check(src) == []


def test_the_plain_equality_variant_fires():
    src = """
def test_get_user():
    store.get.return_value = {"id": 7}
    result = service.get_user(store)
    assert result == {"id": 7}
"""
    assert len(_check(src)) == 1


def test_comparing_two_stubbed_values_to_each_other_is_exempt():
    src = """
def test_same():
    a.get.return_value = payload
    b.get.return_value = payload
    assert payload == payload
"""
    assert _check(src) == []


def test_precedence_between_two_stubbed_collaborators_remains_reported():
    src = """
def test_registry_uri_precedence():
    tracking.get_uri.return_value = "tracking-uri"
    spark.get_uri.return_value = "spark-uri"
    result = resolve_registry_uri(tracking, spark)
    assert result == "spark-uri"
"""
    assert len(_check(src)) == 1


def test_tuple_unpacking_is_not_resolved_as_a_result_reach_in():
    src = """
def test_recording_url(client, monkeypatch):
    monkeypatch.setattr(object_store, "sign", lambda: "https://signed.example/abc.mp4")
    body = client.get("/calls/1").json()
    url, status = body["recording_url"], body["status"]
    assert url == "https://signed.example/abc.mp4"
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: functions pytest does not collect as tests.                        #
# --------------------------------------------------------------------------- #


def test_helper_function_is_exempt():
    src = """
def build_expectation():
    store.get.return_value = {"id": 7}
    result = service.get_user(store)
    assert result == {"id": 7}
"""
    assert _check(src) == []


def test_nested_function_named_test_is_exempt():
    src = """
def make_probe():
    def test_get_user():
        store.get.return_value = {"id": 7}
        result = service.get_user(store)
        assert result == {"id": 7}
    return test_get_user
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge cases.                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("def test_x(:\n    thing()\n") == []


def test_reports_the_position_of_the_assertion():
    [diag] = _check(_TAUTOLOGY)
    assert (diag.line, diag.col) == (6, 5)
    assert diag.code == "SARJ060"


def test_reports_the_position_of_an_assertion_nested_in_a_class_and_a_with_block():
    src = """
class TestUsers:
    def test_get_user(self):
        store.get.return_value = {"id": 7}
        with freeze_time("2026-01-01"):
            result = service.get_user(store)
            assert result == {"id": 7}
"""
    [diag] = _check(src)
    assert (diag.line, diag.col) == (7, 13)


def test_one_diagnostic_per_test_function():
    src = """
def test_one():
    a.get.return_value = {"id": 1}
    assert service.one(a) == {"id": 1}

def test_two():
    b.get.return_value = {"id": 2}
    result = service.two(b)
    assert result == {"id": 2}
    b.get.assert_called_once_with(2)

def test_three():
    c.get.return_value = {"id": 3}
    assert service.three(c) == {"id": 3}
"""
    diags = _check(src)
    assert [d.line for d in diags] == [4, 14]


def test_diagnostics_are_sorted_by_position():
    src = """
def test_b():
    b.get.return_value = {"id": 2}
    assert service.b() == {"id": 2}

def test_a():
    a.get.return_value = {"id": 1}
    assert service.a() == {"id": 1}
"""
    diags = _check(src)
    assert [d.line for d in diags] == sorted(d.line for d in diags)

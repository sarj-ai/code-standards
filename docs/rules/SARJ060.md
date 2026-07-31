# SARJ060 `tautological-mock-assertion` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_tautological_mock_assertion.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

```python
def test_prompt_config_awaits_pool_then_loads(monkeypatch):
    monkeypatch.setattr(main, "load_config_or_empty", AsyncMock(return_value="prompt-cfg"))
    result = await _load_prompt_config_after_pool(pool_task=done, global_prompt_service=Mock())
    assert result == "prompt-cfg"
```

The test's name promises it awaits the pool *and then* loads. Nothing in the body
checks either half: the sole assertion says the string handed to the stub came
back out of it. Nobody is told when the ordering breaks, when the pool task is
dropped, or when the service is never consulted — the assertion holds for every
one of those regressions. That is the shape this rule looks for, and only that
shape: a test in which **every** assertion is a mock echo and **nothing else**
is verified.

Fires when, inside one `test_*` function body, ALL of these hold:

* the body configures a stub value — `m.get.return_value = X`,
  `patch(..., return_value=X)`, `AsyncMock(side_effect=X)`, or a hand-rolled
  `monkeypatch.setattr(mod, "fn", lambda: X)`,
* the stubbed value is **non-trivial** (not `None`/`True`/`False`/`0`/`1`/`""`/
  `[]`/`{}`) — `return_value = None` followed by `assert result is None` pins a
  code path that genuinely could have returned something else,
* every `assert` in the function is a single `==`/`is` comparison whose one side
  is structurally identical to that stubbed value (compared by `ast.dump`, so
  dict/list/tuple literals match cheaply) — or is a bare read of
  `<mock>.return_value`,
* the other side of the comparison is the **whole** result (`result`,
  `svc.get(1)`, `await svc.get(1)`), not a piece of it,
* the stubbed value is mentioned exactly twice in the body: the stub and the
  assertion,
* the stub configures a double the body shows the code under test can *reach* —
  either the whole double (`m.return_value = X`, or any spelling that installs
  one), or a sub-object hanging off something the body hands over,
* and the function contains **no other verification at all** — no
  `mock.assert_called_with(...)`, no `pytest.raises`, no `self.assertEqual`, no
  project-local `_assert_*` helper.

**The guards are the rule, and the last one is most of it.** Measured over
22,388 collected test functions in two first-party repos, django, fastapi and
celery:
958 tests configure a stub in their own body, 866 with a non-trivial value, 462
of those also assert — yet only 44 assertions structurally compare against the
stubbed value at all. Narrowing those 44 to the ones that are genuinely
zero-value takes four separate guards and leaves 2. A version of this rule
without them would be wrong roughly four times in five.

Deliberately NOT flagged:

* **an assertion that reaches into the result**, whether it does so inline or
  through a local. `assert result.name == X` or
  `assert response.json()["data"]["url"] == X` asserts *where the value ended
  up*, which is behaviour the stub does not decide — the code could have put it
  in the wrong field, dropped it, or transformed it. The same is true written
  across two statements, so a local bound exactly once to an attribute or
  subscript expression is resolved back to it before the exemption is applied
  (`data = content["data"]["shop"][...]` / `assert data == external_auths`).
  A name the function binds more than once is left alone: the alias is then
  ambiguous and the rule does not guess. Measured over 19 repositories this
  costs one finding — saleor's
  `saleor/graphql/shop/tests/queries/test_shop.py:515`, a full GraphQL round
  trip through `user_api_client.post_graphql` whose parametrized
  `external_auths` list is stubbed onto `PluginsManager` and then compared
  against the serialized envelope — and it is a false positive; total 138 -> 137,
  with repo A unchanged at 2 and repo B at 0 (repo labels are stable within this
  docstring only). 16 of the 44 structural
  matches are this shape and every one was a real assertion, including one
  first-party navigation test
  (`assert tool._last_send_time == post_send_sentinel` after patching
  `time.time` — it checks the debounce timestamp was recorded) and one
  first-party public-API test
  (`assert r.json()["data"]["recording_url"] == "https://signed.example/abc.mp4"`
  with a stubbed `object_store.sign`, driven through a FastAPI `TestClient` —
  a real end-to-end assertion about the serialized envelope),
* **a stub configured on a *piece* of a double the test never hands over.**
  `self.cur.fetchall.return_value = rows` followed by
  `assert rows == self.db_hook.run(sql=query, handler=fetch_all_handler)` is not a
  mock echo, because the hook has to reach `get_conn().cursor().fetchall()` for the
  comparison to hold at all — the assertion says the unit navigated the DBAPI
  correctly, which the stub does not decide. The wiring that connects `self.cur` to
  `self.db_hook` lives in `setUp`, so a single-file rule cannot see it, and the
  honest reading of `self.cur.fetchall.return_value = X` alone is "the code gets `X`
  *if* it walks this chain". Two shapes therefore keep firing: a stub on the whole
  double (`m.return_value = X`, where nothing has to be navigated), and a stub on a
  sub-object whose root the body hands to the code under test — `repo.fetch.
  return_value = X` beside `UserService(repo)`, or `hook._poll.return_value = X`
  beside `operator._hook = hook`. Aliases that only rename a piece of a double
  (`get_blob_method = bucket_method.return_value.get_blob`) are followed through, so
  the spelling cannot dodge the guard, and a chain whose root is a call rather than a
  name (`mock_get_deploy_client().predict.return_value = X`) can never be shown
  reachable. **Measured cost: 137 -> 110 over the 21-corpus census, -27 and +0** —
  airflow 56 -> 35, superset 23 -> 19, mlflow 25 -> 24, dagster 3 -> 2, and litellm
  (22), prefect (3), warehouse (2), saleor (1) unchanged.
  Every removal is the external-boundary shape — DBAPI cursors (airflow presto
  `test_presto.py:293`, trino `test_trino.py:391`, pinot `test_pinot.py:261`, common
  SQL `test_dbapi.py:600,618`), SDK chains (`test_gcs.py:1874`,
  `test_display_video.py:117`, `test_asb.py:96`, four in `test_data_lake.py`,
  superset's `test_celery_task.py:59` SQLAlchemy chain and `screenshot_test.py:74`
  webdriver chain) and HTTP transports. **No unambiguous true positive is lost**: the
  most egregious shape — patch a method of the unit, then call that very method
  (airflow `test_glue_databrew.py:38`, `test_lockbox.py:86,97`,
  `test_pagerduty.py:77`, `test_bteq.py:265`, dagster's self-named `test_mocks`) —
  stubs the *whole* double and keeps firing. repo A stays at 2 and every other
  first-party repo at 0, so the guard costs nothing first-party in either direction.
  Two weaker readings were measured and rejected: requiring the receiver to appear in
  the compared expression drops 59 including airflow `test_openai.py:66`, and applying
  the requirement to every stub spelling drops 106 including both repo A findings,
* **a round trip.** `assert store.save(record) == record` is not a mock echo:
  the value is also handed to the code under test, so the comparison pins a
  passthrough the code could have broken. Detected by counting mentions —
  exactly two means stub-then-assert. Uses as the receiver of an attribute or
  subscript do not count towards it, because
  `participant.identity = "caller-1"` and `room.disconnect.assert_awaited()`
  configure or interrogate the double rather than feed it to the code,
* **a test that also verifies what the code did.** A `mock.assert_called_once_with(user_id)`
  next to the echo pins the arguments the code passed, and a
  `pytest.raises` pins a failure path; neither is decided by the stub, so the
  test is not zero-value even if one of its assertions is redundant. Also
  covers the *delegation* test, where the passthrough itself is the behaviour
  under test — `celery/t/unit/app/test_app.py:2075`
  (`test_acquire_connection_without_pool`: `assert result == mock_conn.return_value`
  next to `mock_conn.assert_called_once()`, checking that `pool=False` takes the
  non-pooled branch) and `celery/t/unit/backends/test_elasticsearch.py:922`
  (`test_decode_not_dict`) are exactly this, as is
  `fastapi/tests/test_tutorial/test_dependencies/test_tutorial007.py:23`, whose
  `dbsession_moock.close.assert_called_once()` checks the dependency closes the
  session. All three would otherwise be false positives, one of them in mature
  OSS,
* **a test with a real assertion alongside the echo.** Every assertion must be
  an echo. One first-party test
  (`test_builds_request_and_returns_response`) opens with `assert result is
  sip_response` and then checks `request.sip_call_to` and
  `request.headers["X-S-CallId"]` off the captured call args — the echo is a
  redundant first line in a test that does real work,
* **`return_value = None` / `= []` / `= 0`** and the other trivial stubs, where
  the assertion usually distinguishes a real code path,
* an `==` comparison with a value the body never stubbed (a `parametrize`
  `expected` column, a fixture, a hand-built expectation) — only a structural
  match against the stubbed value counts,
* a chained or non-equality comparison (`a < b < c`, `x in y`), and any
  assertion that is not a comparison at all,
* a `test_*` nested inside another function, a non-collected module, and
  anything under `scripts/` — pytest runs none of them.

**Known limit: precedence claims.** A test that stubs two collaborators and
asserts the result equals *one* of them is asserting which source wins, not
echoing a stub — mlflow's
`tests/tracking/_model_registry/test_utils.py:172`
(`test_registry_uri_from_spark_session_overrides_databricks_default`) stubs both
`get_tracking_uri` and `_get_registry_uri_from_spark_session` and asserts the
Spark URI is the one that comes back. The rule reports it. No narrow predicate
separates it from a genuine echo: "two or more stubbed values exempts" was
measured over the 137 surviving findings and would silence 33 of them (24%),
most of which stub the same value twice or stub an unrelated collaborator, so
the cure is far worse than the disease. The shape is left firing and recorded
here.

Note that this standard's own ruff config bans `unittest.mock` outright, so the
`return_value` spelling is rare in the audited first-party code by construction;
the `monkeypatch.setattr(..., lambda: X)` spelling is the one it will meet most
often, and it is treated identically.

## Implementation notes

### `_is_verification_call`

`mock.assert_called_once_with(user_id)` pins the arguments the code passed,
`pytest.raises(ValueError)` pins a failure path, `self.assertEqual(a, b)`
and a project-local `_assert_shape(result)` pin whatever they were written
to pin. A test carrying any of them is not zero-value, even if one of its
assertions is a redundant echo. Bare call-count checks
(`mock.assert_called_once()`) count too: on the audited corpora they mark
*delegation* tests, where the passthrough is itself the behaviour under
test, and treating them as noise produced false positives in celery and
fastapi.

### `_appears_only_at_the_stub`

A third occurrence means the value is also handed to the code under test —
`assert store.save(record) == record` is a round trip, and the stub is not
the sole reason the comparison holds. Uses as the receiver of an attribute
or subscript (`participant.identity = "caller-1"`,
`room.disconnect.assert_awaited_once()`) do not count: those configure or
interrogate the double, they do not feed it to the code under test.

### `_reaches_into_the_result`

`data = content["data"]["shop"]["availableExternalAuthentications"]` followed by
`assert data == external_auths` is the subscript exemption written across two
statements — the assertion still says *where the value ended up*, which is
behaviour the stub does not decide. Resolving the alias is what lets the
exemption see it (saleor
`saleor/graphql/shop/tests/queries/test_shop.py:515`, a full GraphQL round
trip through `user_api_client.post_graphql`).

### `_is_trivial`

`return_value = None` followed by `assert result is None` genuinely pins a
code path that could have returned something; so does an empty list.

### `_record`

`receiver` is None for the spellings that *install* the double
(`AsyncMock(return_value=X)`, `patch(..., return_value=X)`,
`monkeypatch.setattr(mod, "fn", lambda: X)`): those name what they replace, so
the double reaches the code under test by construction.

### `_installs_a_replacement`

`monkeypatch.setattr(mod, "fn", lambda: X)` and `patch("mod.fn", lambda: X)`
are the mock-free spelling of `return_value=X`, and this standard's ruff
config bans `unittest.mock`, so it is the spelling the rule meets most.

### `_record_alias`

Only plain-name targets are recorded — a tuple unpack binds a piece of the
value, not the value. The caller then discards every name the function binds
more than once, so what survives is an unambiguous alias.

### `_names_handed_to_the_code`

An assignment to an attribute only *configures* a double
(`self.cur.fetchall.return_value = rows`, `self.cur.rowcount = -1`), and an
assignment *from* an attribute chain only gives part of one a shorter name
(`bucket_method = mock_service.return_value.bucket`). Everything else hands it
over: `UserService(repo)`, `hook.run(sql)`, `operator._hook = double`.

### `_configured_sub_object`

`m.return_value = X` replaces the whole double, so there is nothing for the
code under test to navigate to. `self.cur.fetchall.return_value = rows` and
`mock_service.return_value.bucket.return_value.get_blob.return_value = blob`
decide what the code gets only *after* it walks a chain, so the comparison
also asserts that walk. Single-assignment aliases whose value is itself an
attribute chain are followed, because naming a piece of a double
(`get_blob_method = bucket_method.return_value.get_blob`) is not handing it
over. A bare `self`/`cls` prefix is dropped: every attribute of the test case
shares it, so it proves nothing.

### `_collectible_tests`

Only module-level functions and methods of a class qualify; a `test_*`
nested inside another function is a callback, not a test.

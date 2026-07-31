# SARJ063 `interaction-only-test` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_interaction_only_test.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

```python
def test_send_notification():
    mailer = MagicMock()
    notify(mailer, user)
    mailer.send.assert_called_once_with(user.email)   # the only assertion
```

A test like this passes exactly as long as `notify` keeps calling `mailer.send`
with that argument list. Reorder the two collaborators, inline a helper, batch
two sends into one — nothing observable changed, and the test goes red. Send the
wrong body, send to the wrong user, drop the record that was supposed to be
written — nothing the test checks moved, and it stays green. It records today's
implementation, not the behaviour. The fix is to assert the outcome the caller
can see (the returned value, the persisted row, the rendered message body) and
keep interaction assertions for the side effects that genuinely have no
observable result.

**How this divides the space with SARJ043 `zero-assertion-test`.** SARJ043 fires
on a test with *no* assertion of any kind; every `m.assert_called_*()` counts as
an assertion there, so SARJ043 is silent on this shape by construction. SARJ063
is the adjacent case: at least one assertion, and every one of them is mock call
bookkeeping. The two never fire on the same function. SARJ043's notion of "what
counts as an assertion" is re-stated privately in this module rather than shared,
so the two rules can drift apart without either editing the other.

Fires when ALL of these hold for a pytest-collected test function:

* it makes at least one assertion, counting `assert` statements, `pytest.raises`
  / `pytest.warns` blocks, `self.assert*` calls, `assert*` / `expect*` /
  `verify*` / `validate*` helpers, and `m.assert_called*()` — including
  assertions made inside a helper defined in the same module,
* **every** one of those assertions is mock call bookkeeping: an
  `assert_called*` / `assert_not_called` / `assert_any_call` / `assert_has_calls`
  / `assert_awaited*` call, or an assertion reading `.called`, `.call_count`,
  `.call_args`, `.call_args_list`, `.mock_calls`, `.method_calls`,
  `.await_count`, `.await_args`,
* it pins **two or more distinct root objects** — so the test is describing a
  call *sequence across collaborators*, not one collaborator asked several
  questions. `mock_hook.return_value.get_instance` and
  `mock_hook.return_value.start_pipeline` are one root, `mock_hook`,
* none of those assertions is negative,
* the test name does not declare the interaction as the contract, and the pinned
  targets are neither all callback registrations nor all patched free functions.

**The guards are the rule.** Across 49,363 collected tests in six repos, 4,361
tests assert only on mock bookkeeping. Shipping that population would have been
indefensible: 61 of django's 62 raw findings are legitimate. The funnel:

| corpus   |   raw | ≥2 roots | non-negative |  name | registration | free fn |
|----------|-------|----------|--------------|-------|--------------|---------|
| repo A   |   107 |       16 |            7 |     7 |            5 |       5 |
| repo B   |     3 |        0 |            0 |     0 |            0 |       0 |
| django   |    62 |        6 |            2 |     2 |            2 |       1 |
| fastapi  |     4 |        0 |            0 |     0 |            0 |       0 |
| celery   |   473 |       78 |           52 |    50 |           50 |      38 |
| airflow  | 3,712 |      757 |          540 |   521 |          521 |     293 |

(repo labels are stable within this docstring only.)

Counting *root objects* rather than dotted target paths at the second stage is
what makes the funnel hold on a large corpus. Before that reduction the rule
returned 1,261 findings over the 14-repo OSS sweep plus the first-party repos;
after it, 462 — 799 removed, 63%. It cost nothing on the calibration corpus
(repo A 5→5, repo B 0→0, django 1→1, fastapi 0→0, and 0→0 across three
further first-party repos); airflow went 999→293. The removals are
adapter passthroughs asking one collaborator several questions —
`airflow/providers/google/tests/unit/google/cloud/hooks/test_dataproc_metastore.py:265`
pins `mock_client` and `mock_client.return_value.restore_service`,
`.../operators/test_datafusion.py:221` pins three methods of
`mock_hook.return_value` — and those tests are correct as written, because a
thin adapter has no observable output but the call it forwards. One true
positive goes with them, `celery/t/unit/tasks/test_result.py:504`: `test_get`
replaces `x.join` and `x.join_native` on the `ResultSet` it is testing and then
asserts they were called, so both roots are the system under test. That is
SARJ061 `no-patching-system-under-test`'s shape, not this rule's.

Treating a leading `self.` / `cls.` as transparent was tried and rejected: it
restores 20 findings, all airflow, all the same DBAPI-hook shape
(`self.conn.commit` + `self.cur.execute` in
`providers/common/sql/.../test_dbapi.py:116` and its siblings), and 0 anywhere
else. Those are the adapter passthroughs the guard exists to remove, so the
plain root split is the calibrated behaviour.

Manual read of 22 findings (5 repo A, 1 django, 16 celery) classed 20 true
positives and 2 false positives (9%). The root reduction took one of those two
with it: `celery/t/unit/utils/test_debug.py:16` (`test_blockdetection`) pins
`signals.arm_alarm`, `signals.__setitem__` and `signals.reset_alarm`, one
object, and no longer fires. The one that remains is
`celery/t/unit/worker/test_autoscale.py:200` (`test_thread_crash` asserts
`os._exit` was called with 1, which cannot be observed without exiting). That is
"the effect is on process-global machinery"; a guard for that shape would be
overfitting to one corpus, so `# sarj-noqa: SARJ063` is the intended escape.

Deliberately NOT flagged:

* **a test pinning a single collaborator**, however many of its methods or
  bookkeeping attributes it reads. Asserting `call_count` *and* `call_args` on
  one mock is one fact — "this collaborator was told once, with this payload" —
  and for a notifier that is the whole contract; asking the same object two
  questions (`mock_source_db.backup` then `mock_source_db.close`) is still one
  fact about one object. A collaborator is an object, not one of its methods —
  the same reduction SARJ062 `over-mocked-test` applies when it counts
  substituted collaborators, and the two rules have to agree or a shape can be
  "one collaborator" to one rule and "two" to the other. This guard alone
  removed 56 of the 62 raw django findings and all four raw fastapi
  findings, without touching the motivating shape above. Every one of the ten
  file-watcher tests in `django/tests/utils_tests/test_autoreload.py` (`test_glob`
  at :642, `test_multiple_globs` at :655, and their siblings) reads
  `notify_mock.call_count` then `notify_mock.call_args`; the reloader's entire
  observable output *is* that callback. So do
  `django/tests/auth_tests/test_models.py:295` (`test_user_double_save`, whose
  docstring says "should trigger password_changed() once"),
  `django/tests/auth_tests/test_validators.py:164` and
  `django/tests/backends/base/test_base.py:204`,
* **any negative interaction assertion.** `assert_not_called`,
  `assert_not_awaited`, `assert not m.called`, `m.call_count == 0`,
  `self.assertFalse(m.called)`. Two shapes hide here and both are legitimate: the
  pure negative-space contract ("does not charge the card twice") has no outcome
  to assert on by construction, and the mixed positive/negative test is a
  *routing* claim — `django/tests/check_framework/test_multi_db.py:23` asserts
  `mock_check_field_default.called` and `not mock_check_field_other.called`,
  which is the only way to say "this went to the default database". 13 findings
  across repo A and django, all legitimate,
* **a test whose name says the interaction is the contract** — `publish`,
  `emit`, `dispatch`, `broadcast`, `retry`, `backoff`, `cache`, `idempoten`,
  `debounce`, `throttl`, `not_called`, `only_once`. Measured, not guessed: this
  list removes 2 celery findings (`test_broadcast` and `test_broadcast_limit` in
  `celery/t/unit/app/test_control.py:213`/`:221`, where broadcasting the command
  *is* the contract) and 19 airflow ones — `retry`, `dispatch` and `emit`
  wrappers such as `airflow/providers/git/tests/unit/git/bundles/
  test_git.py:1348` (`test_clone_bare_repo_invalid_repository_error_retry`) —
  and none in repo A, repo B, django or fastapi. Any wider and it guts the
  rule — an earlier draft that also matched `never`, `does_not`, `lazy` and
  `memo` was cut back for that reason,
* **a test that only pins callback registration** — every target ends in
  `connect`, `on`, `off`, `subscribe`, `register`, `add_listener`, … Wiring a
  handler onto a collaborator returns nothing and changes nothing until the event
  fires, so the registration is the only checkable fact. Two first-party sites
  that register then deregister on two objects (`room.on`/`session.on`, then
  `room.off`/`session.off`) are the shape, and the only two findings this guard
  still removes across the six repos: `celery/t/unit/fixups/test_django.py:183`
  (`test_install` asserts four `sigs.*.connect` calls) used to reach it and is
  now cut earlier, by the distinct-root guard, since all four hang off one
  `sigs` object,
* **a test where every pinned target is a patched free function** — a bare name
  with no receiver, which means the collaborator was swapped in by `@patch` at
  module scope rather than handed to the code as an object. There is no instance
  whose state the test could have asserted on instead.
  `celery/t/unit/utils/test_platforms.py:327` (`test_setuid` pins `parse_uid`
  and `os.setuid`), `celery/t/unit/concurrency/test_eventlet.py:47`
  (`monkey_patch`, `hub_blocking_detection`) and
  `django/tests/test_utils/test_simpletestcase.py:88` (`test_debug_cleanup`
  pins the patched `_pre_setup` / `_post_teardown` lifecycle hooks) are all
  cleared by it. A test that pins even one method on an object it holds
  (`mock_blob.download_as_bytes`, `client.delete_one`) still fires,
* a test that also asserts anything else — a returned value, a raised error, a
  row read back from a fixture. One non-interaction assertion is enough,
* **a file pytest would never collect**, and a skipped test, a fixture, a stub
  body, a `test_*` nested inside another function, or a test that re-runs another
  module's `test_*` — the same collection gating SARJ043 applies, for the same
  reasons.

## Implementation notes

### `_root_objects`

`mock_hook.return_value.get_instance` and
`mock_hook.return_value.start_pipeline` are two questions asked of one
collaborator, so both reduce to `mock_hook`. This is SARJ062's reduction —
a collaborator is an object, not one of its methods — and the two rules have
to agree on it.

### `_interaction_targets`

`notify_mock.call_count` and `notify_mock.call_args` both name
`notify_mock`; `mailer.send.assert_called_once_with(...)` names
`mailer.send`. Counting distinct targets is what separates "one collaborator
must be told" from "this exact sequence of collaborator calls must happen".

### `_direct_counts`

Calls to functions this module defines are skipped: their own bodies are
merged in separately, so counting the call site too would let a helper named
`_assert_wiring` pass as an outcome assertion on the strength of its name.

### `_test_profiles`

Assertions reached through a helper defined in the same module count too, so
a test delegating to `_assert_saved(...)` is profiled by what that helper
actually checks.

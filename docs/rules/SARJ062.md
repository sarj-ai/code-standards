# SARJ062 `over-mocked-test` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_over_mocked_test.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Past a certain ratio the system under test is gone. Every collaborator answers
whatever the test told it to answer, so the assertions can only re-read the
script the test itself wrote: `mock_a.assert_called_once_with(...)` proves the
test called the test. Such a test goes green when the real collaborators change
shape, when the call order that mattered is wrong, and when the integration it
is named after has never worked. It is also the most expensive kind of test to
change, because every refactor of the real code invalidates the whole scaffold.

The remedy is a real dependency: a test database, an in-process app, `respx`
for HTTP, a hand-rolled fake implementing the ABC — with a double only at the
true external boundary (the payment provider, the LLM, the telephony vendor).
This is already the house position: the shared strict ruff config bans
`unittest.mock.Mock`/`MagicMock`/`AsyncMock`/`patch` and `pytest_mock` outright
via `flake8-tidy-imports`, so every mock in the audited repos already carries an
inline `# noqa: TID251 — <reason>`. That ban is per import; it cannot see that
six separately-justified doubles have added up to a test with no subject. This
rule measures the sum.

WHAT COUNTS AS ONE SUBSTITUTION
-------------------------------

Per collected test function, the **distinct collaborators** replaced:

* `@patch(...)`, `@patch.object(...)`, `@patch.multiple(...)` decorators on the
  test itself — `patch.multiple` expands to one target per replaced attribute
  rather than being read as a single opaque decorator, so its attributes are
  filtered and de-duplicated exactly like separately spelled `@patch`es,
* `patch(...)` / `patch.object(...)` / `mocker.patch(...)` /
  `monkeypatch.setattr(...)` anywhere in the body, `with` blocks included,
* `Mock()` / `MagicMock()` / `AsyncMock()` / `create_autospec()` bound to a
  name,
* mock-shaped fixture parameters — `mock_*`, `*_mock`, `*_mocks`.

A collaborator is an **object, not one of its methods, and not one of the names
that point at it**. Four reductions make that true, and every one was forced by
a measured false positive:

* a dotted patch target loses its last segment, so `patch("os.fork")`,
  `patch("os.setsid")` and `patch("os.dup2")` are one substituted collaborator —
  the OS. Without this, `celery/t/unit/utils/test_platforms.py:467`
  (`test_open`, eleven `@patch`es of `os.*` around a `DaemonContext`) scored 14
  and `:220` (`test_with_uid`) scored 10, and both are *correct* code: those
  syscalls are the true external boundary this rule tells you to mock. They now
  score 4 and 3 and never fire,
* an attribute chain assigned a double collapses to its root, because
  `ctx.api.room.delete_room = AsyncMock()` does not add a collaborator — it
  fills in one more corner of the double already bound to `ctx`. Without this,
  one first-party call-timeout test scored 6 for building out a single
  `mock.Mock(spec=SessionContext)` in six statements, while using a **real**
  `PsqlOrderStore` against a real database — the exact test this rule wants
  people to write. Five of its sibling tests scored 6 the same way. It now
  scores 1. `self`/`cls` is the exception: it is the test case, not a double, so
  `self.client` and `self.session` stay two collaborators,
* **a name hoisted out of an object graph is that graph.** `mock_room = Mock()`
  followed by `ctx.room = mock_room` is one object written in two statements,
  and the attribute-chain collapse above cannot see it because the double is
  bound to a local first. Every wiring edge is therefore resolved to a fixpoint
  before the count is taken: `A.b = n`, `A.b.return_value = n`,
  `A.b.side_effect = [n1, n2]`, `A.b = Mock(return_value=n)` and
  `A.b.return_value = ok(n)` (a name handed to a one-level wrapper call is
  still placed inside `A`), the chained `a = b.c = Mock()`, the handle of a
  `with patch.object(store, "m") as h`, and the parameter a `@patch` decorator
  injects. Without this,
  `superset/tests/unit_tests/utils/webdriver_test.py:847` scored 9 for one
  Playwright chain (`browser` → `context` → `page` → locators) and
  `mlflow/.../test_unity_catalog_rest_store.py:900` scored 6 for five
  `patch.object(store, ...)` handles and the response objects hung off them.
  This is the single largest correction: it removes 300 of the 597 findings the
  uncorrected counter produced,
* **a bare name is resolved through the file's import table.** `from app import
  gateway` then `patch.object(gateway, "call")` names the same collaborator as
  `patch("app.gateway.send")`; counting `gateway` and `app.gateway` separately
  reported one object twice. A *relative* import is not resolved — `.app` is not
  the top-level `app`, and rewriting onto it would merge two different objects.

`patch(f"{MODULE}.Client")` is reconstructed as `MODULE.Client` rather than
collapsing to an opaque `?`. The old behaviour made every f-string target in a
file the same anonymous collaborator, which both under-counted files that
templated several distinct targets and mis-keyed the infrastructure filter
(`patch(f"{MODULE}.sleep")` is a clock knob and has to read as one). At the
shipping threshold this changes no finding either way; it is here so the
identity model has no hole in it.

MEASURED DISTRIBUTION, AND WHERE THE THRESHOLD CAME FROM
--------------------------------------------------------

Distinct collaborators per collected test function, over 170,354 collected
tests in 19 repositories (five first-party repos and 14 large OSS Python
suites; repo labels are stable within this docstring only):

    corpus         tests       0      1     2     3     4    5   6  7  8 9+  >5
    repo A         4,279   3,989    201    64    20     3    2   -  -  -  -   0
    repo B         2,861   2,593    264     4     -     -    -   -  -  -  -   0
    repo C           521     485     36     -     -     -    -   -  -  -  -   0
    repo D           113     112      1     -     -     -    -   -  -  -  -   0
    repo E           259     198     50     7     1     2    1   -  -  -  -   0
    airflow       27,827  15,573  8,657 2,678   668   172   58  16  4  1  -  21
    dagster       11,196   9,971    976   143    60    14   11  14  7  -  -  21
    litellm       32,880  22,328  6,168 2,751 1,003   362  155  61 28 12 12 113
    saleor        12,669   9,910  2,128   449   129    45    4   4  -  -  -   4
    django        18,044  17,643    354    39     7     -    1   -  -  -  -   0
    mlflow        13,718   9,743  2,500 1,070   286    79   23   9  3  4  1  17
    langchain      5,427   4,955    379    63    26     3    -   1  -  -  -   1
    superset      10,931   6,514  2,582 1,008   503   233   54  23  8  4  2  37
    zulip          4,384   3,855    470    44    12     2    -   -  -  -  1   1
    prefect       13,784  11,298  1,463   584   251   103   62  12  9  -  2  23
    fastapi        2,290   2,260     27     2     -     1    -   -  -  -  -   0
    warehouse      3,524   2,704    703    94    21     2    -   -  -  -  -   0
    sentry-python  2,443   1,920    466    29    17     9    2   -  -  -  -   0
    celery         3,204   2,162    772   190    46    24    9   -  -  1  -   1
    ALL          170,354 128,213 28,197 9,219 3,050 1,054  382 140 59 22 18 239

75.3% of tests substitute nothing at all, and 99.86% stay at five or below. The
rule fires **above five**: 239 findings in 170,354 tests (0.14%).

The previous table in this docstring was wrong and has been replaced. It was
built by a counter that read one object graph as several — a hoisted
`mock_room = Mock(); ctx.room = mock_room` scored 2, pytest-mock's `mocker`
handle scored as a collaborator of its own, and every f-string target in a file
collapsed onto the same key. Its tail was inflated, so the "99.96th percentile"
it reported was an artefact. Correcting the counter took the corpus from 597
findings to 239 without introducing a single new one.

Re-deriving the threshold from the corrected distribution:

    fire above   findings   % of tests   first-party findings
    >6                 99      0.058%    0
    >5                239      0.140%    0
    >4                621      0.365%    3  (repo A 2, repo E 1)
    >3              1,675      0.983%    8  (repo A 5, repo E 3)

`>5` survives, for a reason the corrected data still supports: firing above
four drags in honest tests. django's only test in the 5 band is
`tests/backends/sqlite/test_creation.py:47`, which uses a *real* connection and
a real creation class and mocks the three `sqlite3.connect` calls under it;
repo A's two are agent-tool tests, five doubles apiece around a real tool
object. Five is still where honest tests live.

What has changed is the rule's standing in the first-party repositories: at `>5`
it now finds **nothing** in any of repos A through E,
so it is a **ratchet** — like `no-patching-system-under-test`. Nothing has to be
fixed to adopt it, and nothing may regress past it. It earns its place on the
OSS evidence, where 239 findings concentrate in the suites that are mostly mock
by volume (litellm 113, superset 37, prefect 23, airflow 21, dagster 21) —
exactly the population the rule exists to name. celery's worst,
`t/unit/test_loops.py:9`, still scores 8: eight bare `Mock()`s named `obj`,
`connection`, `consumer`, `blueprint`, `hub`, `qos`, `heartbeat` and `clock`,
and then an assertion that `synloop` called them.

The two repo A findings that used to justify the threshold were both counting
one hoisted object graph twice — the shape this docstring says must collapse,
merely written with the mock hoisted. They are correctly gone.

DELIBERATELY NOT COUNTED
------------------------

* **`monkeypatch.setenv` / `delenv`.** That is the environment, not a
  collaborator. Only `monkeypatch.setattr` counts. `setitem`/`delitem` (editing
  a settings dict), `chdir` and `syspath_prepend` are likewise process state.
* **`patch.dict(...)`.** It edits a mapping in place — `os.environ`, a settings
  dict, a handler registry — rather than replacing a collaborator; django alone
  uses `@mock.patch.dict(os.environ, ...)` as a class decorator on the very
  tests this rule looks at.
* **`mocker` itself.** pytest-mock's `mocker` fixture is the handle you patch
  *through*, not a collaborator that got replaced; what it patches is counted at
  the `mocker.patch(...)` call. Counting the handle as well added a phantom
  substitution to every pytest-mock test: putting it back adds 30 findings.
* **Test-infrastructure knobs, by target name.** A target naming the
  environment, configuration, logging, the clock, or the retry/timeout dials
  (`env`, `settings`, `config`, `logger`, `time`, `sleep`, `now`, `datetime`,
  `timeout`, `retry`, `backoff`, `delay`, `interval`, `random`, `seed`, `uuid`,
  `stdout`, ...) is a dial the test turns, not a piece of the system it
  replaced. Shortening a timeout or freezing the clock is how you make a *real*
  integration test fast; counting it would penalise exactly the tests this rule
  is trying to produce.
* **`client.patch("/items/1")`.** An HTTP PATCH request, not a mock — the
  single most dangerous name collision in this rule's vocabulary, and endemic in
  fastapi's and django's suites. A `.patch` attribute only counts when its
  receiver is an import-backed `unittest.mock` alias or pytest-mock's `mocker`;
  a locally-defined `patch` helper never counts.
* **Class-level `@patch` decorators on a `TestCase`.** Those are the class's
  shared fixture — written once, amortised over every method — so attributing
  them to each method reports one design decision N times and points the
  diagnostic at the wrong line. django's `tests/backends/base/test_creation.py`
  is the proof: `TestDbCreationTests` carries four class-level patches
  (`connection.ensure_connection`, `connection.prepare_database`,
  `MigrationRecorder.has_table`, `Command.sync_apps`) that stub the database out
  of the database-creation machinery, and attributing them produced five
  findings in that one class (`:79`, `:104`, `:129`, `:154`, `:175`) for a
  single stack of decorators. Counting only what the test itself declares — its
  own decorators, its own signature, its own body — takes django to zero
  findings and changes nothing anywhere else in the corpus. The parameters those
  class decorators inject are still skipped, or they would be recounted as mock
  fixtures.
* **Parameters injected by the test's own `@patch` decorators.** A `@patch`
  prepends a positional argument that is conventionally named `mock_*`; the
  first N parameters are skipped so a five-patch test scores 5, not 10. Each
  such parameter is also aliased to the target its decorator replaced, so a
  double wired onto it (`mock_browser_manager.get_browser.return_value =
  mock_browser`) joins that collaborator rather than starting a new one; that
  alias alone accounts for 47 findings.
* **Composition-root tests.** A test whose name, class, or path says `wiring`,
  `startup`, `lifespan`, `bootstrap`, `container`, `di` or `smoke` must stub
  every adapter — that is the point of it. This exempts 1,133 tests across the
  corpora (celery's whole `t/smoke/` suite, three first-party composition-root
  suites — a `test_main_wiring.py`, an auth-provider smoke test and a
  `TestWidgetToolWiring` class — and fastapi's lifespan
  tests). Four of the 1,133 would otherwise fire, and three are the guard
  working as intended — litellm's `test_proxy_cli.py:518`, `:1814` and `:1881`
  stub the world around the proxy's startup path. The fourth,
  prefect's `test_container_instance.py:2212`, is a name collision: `container`
  there is an Azure Container Instance, not a DI container. The token list is
  the cost of matching on names; it errs toward suppression.

  The path arm reads only from the **test root** down — the first `t` / `test` /
  `tests` component and everything below it. It used to tokenise the whole
  absolute path, which meant an ancestor directory nobody chose could exempt a
  file: the identical test fires at `app/tests/test_billing.py` and was silent
  at `my-container-app/tests/test_billing.py`, under `~/di/svc/`, or on a CI
  runner whose workspace directory is `smoke-repo`. That disabled the rule for
  an entire checkout, and since it reports zero on compliant code the silence
  was indistinguishable from success. Scoping to the test root keeps every real
  case (celery's `t/smoke/tests/` still reads `smoke` two levels up) and changes
  no finding in any corpus.
* A `test_*` nested inside another function — pytest collects only module-level
  functions and class methods, so a nested one is a callback.

## Implementation notes

### `_joined_text`

`patch(f"{MODULE}.Client")` names `MODULE.Client`. Collapsing it to an
opaque placeholder instead made every templated target in a file the same
anonymous collaborator.

### `_mock_parameters`

The first `injected` parameters are the ones `@patch` decorators prepend;
they are conventionally named `mock_*` and are already counted.

### `_owner_of`

`patch("os.fork")`, `patch("os.setsid")` and `patch("os.dup2")` all replace
parts of one collaborator — the OS — not three.

### `_collaborator_of`

`ctx.api.room.delete_room = AsyncMock()` does not introduce a collaborator —
it configures one more corner of the double already bound to `ctx`, and a
six-line build-out of one mock's object graph must count once, not six
times. So an attribute chain collapses to its root. `self`/`cls` is the
exception: it is the test case, not a double, so `self.client` and
`self.session` are two collaborators hung off it.

### `_record_handle_facet`

`with patch.object(store, "_call_endpoint") as mock_call:` binds a name to a
substitution already counted against `store`; anything wired onto it belongs
to `store` too.

### `_record_facets`

`ctx.room = mock_room` and `mock_call.side_effect = [first, second]` both
say the right-hand names are corners of the left-hand object graph, as does
the chained `consumer = app.amqp.TaskConsumer.return_value = Mock()`.

### `_injected_owners`

A `@patch`/`@patch.object` decorator prepends one positional argument to the
test signature, and it is conventionally named `mock_*`; those parameters
must not be counted a second time as mock fixtures. `patch.multiple` injects
one per replaced attribute, by keyword, so which is which is not knowable
from the signature.

### `_substitutions`

A substitution is recorded as `(replaced target, owning object)`: the target
decides whether it is an infrastructure knob, the owner decides identity.
Three patches of three methods on one client replace one collaborator, not
three, and so do three names pointing into one object graph.

### `_BodyScan`

`facets` maps a name onto the object it is merely a part of, so that a
hoisted `mock_room = Mock(); ctx.room = mock_room` resolves to one
collaborator instead of two.

### `_MockNames`

Name resolution is load-bearing, not decoration: `client.patch("/items/1")`
is an HTTP PATCH request and appears all over FastAPI/Django/DRF suites, so
a bare `.patch` attribute is only a substitution when its receiver is an
import-backed mock module (or pytest-mock's `mocker`). The same table
carries every other import, so that `patch.object(gateway, "call")` and
`patch("app.gateway.send")` name one collaborator rather than two.

### `_seam_path_tokens`

The seam exemption reads the path because a composition-root suite is often
a *directory* rather than a suffixed filename — celery's `t/smoke/` is the
motivating case. Tokenising `str(path)` reads the absolute path, so any
ancestor supplied by whoever cloned the repo counts too: the identical file
fires at `app/tests/test_billing.py` and is silent at
`my-container-app/tests/test_billing.py`, under `~/di/svc/`, or on a CI
runner whose workspace is `smoke-repo`. That turns the rule off for a whole
checkout, and because it reports zero on compliant code the silence is
indistinguishable from success.

The dividing line is the test root: everything from the first `t` / `test` /
`tests` component downward is how the author organised their suite, and
everything above it is where the repository happens to sit on disk. So
`t/smoke/tests/test_worker.py` still reads `smoke` (celery's layout, where
the marker is two levels up), while `my-container-app/tests/test_billing.py`
reads only `test_billing.py`.

`t` is included as a marker because celery's suite is rooted there. It is
short enough to appear as an ordinary directory name, so a repository stored
under a path component named exactly `t` would still read its descendants —
a much narrower leak than reading the whole path, and one no corpus exhibits.

### `_test_functions`

Only module-level functions and direct methods of a class qualify; a
`test_*` nested inside another function is a callback, never a test.

### `_over_mocked_tests`

`threshold` is a parameter so the corpus-calibration sweep can walk the
whole distribution rather than only the tail.

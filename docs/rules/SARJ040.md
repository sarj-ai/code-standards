# SARJ040 `mock-without-spec` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_mock_without_spec.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

An unspecced `Mock()` is the reason mock-based suites go green while production
breaks. It answers *every* attribute access with a fresh child mock, so a test
keeps passing after the collaborator it stands in for has been renamed, had a
parameter added, or lost the method entirely. The mock has no contract, so
nothing about it can rot loudly. `spec=`/`autospec=` restores the contract:
attribute access outside the real object's surface raises `AttributeError`, and
the double fails the moment the real type moves.

This is genuinely uncovered. The `flake8-tidy-imports` ban in the shared strict
config gates the *import* of `unittest.mock`, never the call-site keywords, and
ruff has no rule for spec discipline at any severity. In the audited corpora
only 60 of 556 mock constructions in one repo, and 0 of 59 in the other, passed
any spec argument.

Fires when ALL of these hold:

* the file is a test file (`test_*.py`, `*_test.py`, `conftest.py`, or under a
  `tests`/`test` directory) — spec discipline outside tests is a different
  argument, and production `Mock` use is already banned outright,
* the file actually imports `unittest.mock` in some form, and the callee
  resolves through that import to `Mock`, `MagicMock`, `AsyncMock`, `patch`, or
  `patch.object` — a locally-defined class that happens to be named `Mock` is
  never flagged, because the name is only trusted when the import backs it,
* and the call passes none of `spec=`, `spec_set=`, `autospec=`, `new=`,
  `new_callable=`, or `wraps=`.

Deliberately NOT flagged:

* `new=` / `new_callable=` on `patch` — the replacement is already a concrete
  object or factory chosen by the author, so autospec has nothing left to
  constrain,
* the SAME arguments passed positionally, which is how they are almost always
  spelled — see the exemptions below,
* `wraps=` — the double delegates to a real object, which supplies the same
  attribute-surface enforcement `spec=` would,
* `create_autospec(...)`, `mock.ANY`, `mock.sentinel`, `mock.call` — specced by
  construction or not doubles at all,
* bare `Mock` referenced without being called (annotations, `isinstance`
  checks) — only a construction can carry a spec argument,
* a canned callable stub bound to an attribute (`receiver.method =
  AsyncMock(return_value=...)`) — see exemption 4 below.

The import-backed name check is the load-bearing false-positive guard. Test
suites routinely define their own `Mock`-suffixed fakes (`MockPaymentGatewayClient`,
`MockSession`); those are hand-written doubles implementing a real interface,
which is precisely the pattern this rule steers toward, and flagging them would
invert the rule's intent.

EXEMPTIONS, WITH CORPUS EVIDENCE
--------------------------------

Measured over 2,657 files of popular third-party Python (fastapi, pydantic,
black, sqlmodel, rich, flask, httpx, requests, anyio), the keyword-only version
of this rule reported 137 hits, of which 38 were false positives:

1. **The replacement/spec passed POSITIONALLY (35 hits, 26%).** Every one of
   these signatures takes the escape hatch as a positional parameter:

       Mock(spec=None, wraps=None, ...)             # arg 1 is `spec`
       patch(target, new=DEFAULT, ...)              # arg 2 is `new`
       patch.object(target, attribute, new=DEFAULT) # arg 3 is `new`

   so `patch("black.dump_to_file", dump_to_stderr)` IS `new=dump_to_stderr` and
   `Mock(Process)` IS `spec=Process`. Checking only `node.keywords` made the
   rule's own documented `new=`/`spec=` carve-outs unreachable for the spelling
   authors actually use. Evidence: `black/tests/test_black.py:149` (`@patch(
   "black.dump_to_file", dump_to_stderr)`, 29 hits in that file alone),
   `anyio/tests/test_to_process.py:127` (`Mock(Process)`),
   `anyio/tests/test_sockets.py:1133` (`MagicMock(SocketListener)`),
   `requests/tests/test_requests.py:1020` (`mock.patch("os.environ", env)`),
   `anyio/tests/test_tempfile.py:71` (`patch.object(stf, "rollover",
   fake_rollover)`). Guard: an arity check per callee.

2. **The double is a stub function / call recorder (2 hits).** A mock that the
   file only ever *calls*, reading back nothing but the mock API
   (`assert_called_once_with`, `call_args_list`, `reset_mock`, ...), is not
   standing in for a typed object — it is the test's own recording apparatus,
   and `spec=<RealType>` has no referent to name. Evidence:
   `pydantic/tests/test_validators.py:1755` (`check_values = MagicMock()`,
   invoked from inside a field validator and read back only through
   `assert_called_once_with`) and `:1812` (`validate_stub`). Guard: exempt a
   double bound to a name that is called at least once and whose every
   attribute read belongs to the mock API. A double that is *handed to* the
   system under test stays flagged — production code can attribute-access it
   where the test cannot see, which is exactly what `spec=` guards.

3. **An import-failure stand-in (1 hit).** A mock built inside `except
   ImportError:` substitutes for a module that is *definitionally absent* on
   this platform; there is no importable type to spec against, by construction.
   Evidence: `anyio/tests/conftest.py:37` (`uvloop = Mock()` in the
   `except ImportError` arm of the uvloop/winloop probe). Guard: exempt
   constructions lexically inside an `ImportError`/`ModuleNotFoundError`
   handler.

4. **A canned callable stub bound to an attribute (146 hits, 18.8%).** Measured
   over the two first-party repos (777 hits), the single
   largest shape was `receiver.method = Mock(...)` — 283 hits, 36.4%. It is not
   an unspecced *collaborator*; it replaces one callable on a receiver that
   already exists, and the contract this rule protects belongs to that receiver.
   Either the receiver carries `spec=` — in which case production's call through
   a renamed attribute raises `AttributeError` off the specced parent and the
   test fails loudly, which is exactly the rot this rule wants — or the receiver
   is itself flagged here at its own construction, and reporting the leaf as
   well says the same thing twice. Evidence: one first-party conftest where
   `receiver = mock.Mock(spec=AudioReceiver)` is followed by
   `receiver.start_audio = mock.AsyncMock()` / `.run = ...` / `.stop = ...`
   — model spec discipline, and three findings; and one first-party integration
   test where `crm_service.get_record = mock.AsyncMock(return_value=record)`,
   and the only thing the file reads off `crm_service.get_record` is
   `assert_awaited_once_with`. `AsyncMock` dominates the shape (164 of 283)
   because `Mock(spec=X)` children are not awaitable, so a specced double *must*
   have its async methods stubbed this way to be usable at all.

   The guard demands POSITIVE evidence of callability — a canned
   `return_value=`/`side_effect=`, a mock-API read off the path
   (`recv.method.assert_called_once_with(...)`), or an invocation — on top of
   the absence of any domain-attribute read. Absence alone is not enough: one
   first-party site assigning `room.local_participant = mock.Mock()` is an
   object double that file never happens to walk, and it stays flagged, as do
   the 60 namespace doubles the corpus does walk — three further sites in the
   same file (`api.room` / `api.sip` / `api.egress`, read back as
   `.delete_room`, `.create_sip_participant`, `.start_room_composite_egress`)
   and two in a conftest (`job_context.api`, `job_context.api.sip`).

   What this gives up is arity: `AsyncMock(spec=Store.get)` would reject a call
   whose signature no longer matches, and the exempted stubs will not. That is
   the narrower half of the defect, and it is the half `patch.object(mod,
   "func")` still gets flagged for, since `autospec=True` is a one-word fix
   there and there is no equivalent for a raw attribute assignment.

The 99 survivors are true positives: unspecced `MagicMock()` doubles for real
types (`black/tests/test_black.py:2933`, a `MagicMock()` standing in for `Path`
and answering `.relative_to`/`.resolve`/`.is_dir`/`.is_file`), and
`patch.object(mod, "func")` replacements that `autospec=True` would give a
signature to (29 in `rich/tests/test_win32_console.py`). Not flagged as a false
positive after review: `patch()` used only as a context-manager side effect
(`black/tests/test_blackd.py:34`, `with patch("blackd.web.run_app"):`) — the
target is importable and `autospec=True` applies to it unchanged.

## Implementation notes

### `_FileFacts`

Two of the three guards are about how a double is *used*, not how it is
built, so they need a whole-file view: which name each construction is bound
to, what is read back off that name, and which constructions sit inside an
import-failure handler.

### `_FileFacts.is_method_stub`

`receiver.method = AsyncMock(return_value=...)` replaces a single
callable, not an object. The contract this rule protects belongs to the
*receiver* — it is the receiver's construction that either carries
`spec=` or is itself flagged here — and a callable has no attribute
surface for `spec=` to fence. Two conditions must hold:

* nothing but the mock API is read back off the assigned path, so the
  double is not standing in for an object the test walks, and
* something positively marks it as a callable — a canned
  `return_value=`/`side_effect=`, an `assert_called*`-style read, or an
  invocation of the path.

The second condition is what keeps `room.local_participant = Mock()`
flagged: absence of attribute reads is not evidence of callability, and
a namespace double that this file happens never to walk is exactly the
case `spec=` exists for.

### `_FileFacts.is_call_recorder`

Such a double is a stub function / call recorder: the file invokes it and
reads back nothing but the mock API, so there is no collaborator type for
`spec=` to name. A double merely *handed* somewhere (a `return_value=`, an
argument to the system under test) is not covered — production code can
attribute-access it out of this file's sight.

### `_MockNames`

`unittest.mock` is nearly always imported as a module (`from unittest import
mock`) in the audited corpora, but the direct-symbol and aliased forms are
equally valid, so all three are resolved. Names are only trusted when an
import backs them — that is what keeps hand-written `MockFoo` doubles out.

### `_MockNames.resolve`

Handles the bare (`Mock(...)`), module-qualified (`mock.Mock(...)`,
`unittest.mock.Mock(...)`) and `patch.object(...)` spellings.

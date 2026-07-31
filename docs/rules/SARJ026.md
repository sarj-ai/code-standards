# SARJ026 `prefer-namedtuple-over-tuple-return` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_namedtuple_over_tuple_return.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A multi-field value returned across a boundary — from a public function (name not
starting `_`) — must be a `NamedTuple` (or a frozen pydantic model when it needs
validation), never a positional `tuple[A, B]` the caller has to unpack by position.
A bare `tuple[bytes, dict, str | None]` return forces every caller to remember which
slot is which; a typo swaps two fields silently. A named result gives each field a
name and lets pyright catch a wrong-order access.

    # flagged
    def download_to_memory(...) -> tuple[bytes, dict[str, str], str | None]:
        ...

    # preferred
    class Download(NamedTuple):
        body: bytes
        headers: dict[str, str]
        content_type: str | None

    def download_to_memory(...) -> Download:
        ...

The three tuple uses CLAUDE.md permits are deliberately NOT flagged:
- `tuple[X, ...]` — an immutable homogeneous sequence (Ellipsis form),
- `tuple[X, X]` — structurally homogeneous (every element identical, e.g.
  `tuple[int, int]`), a pair of the same thing rather than distinct fields,
- `tuple[Literal["both"], A, B]` — a discriminated-union tag (first element a
  `Literal[...]`).

Also NOT flagged: private (`_`-prefixed) functions, single-element `tuple[X]`,
a bare unsubscripted `tuple`, and any non-tuple / unannotated return.

Famous-repo sweep hardening also exempts:
- test files (`_paths.is_test_path`) — test helpers returning ad-hoc pairs
  (`make_pipe() -> tuple[Send, Receive]`) are local scaffolding, not a public
  boundary;
- interface stubs whose body only raises `NotImplementedError` (plus a
  docstring), `@overload` stubs, and `@abstractmethod` declarations with no
  implementation — the tuple shape mirrors an external protocol (trio's
  `SocketType.accept` mirrors stdlib `socket.accept`;
  `anyio/src/anyio/abc/_sockets.py:230` `receive_fds` mirrors
  `socket.recvmsg`) and cannot change unilaterally. A bare `...` body on an
  *undecorated* function is NOT exempt — it is also the shorthand for an
  ordinary unwritten function;
- **nested functions.** A closure has no callers outside its enclosing
  function, so it never crosses the boundary this rule protects, and the pair
  it returns is usually mandated by the consumer: 2 of the 3 sweep hits are
  `sorted(key=...)` functions that MUST return a tuple
  (`rich/rich/_inspect.py:128`, `rich/rich/scope.py:45`), the third a local
  stack popper (`rich/rich/markup.py:146`);
- **declared overrides.** A method implementing an inherited contract does not
  own its signature. Recognised, in order of directness: an `@override`
  decorator; a `super().<same name>(...)` call in the body
  (`fastapi/fastapi/routing.py:825`, `:1244`); a base whose trailing name
  repeats the class's own name, the "concrete implementation of my ABC" idiom
  (`anyio/src/anyio/_backends/_trio.py:514` `class UNIXSocketStream(SocketStream,
  abc.UNIXSocketStream)`, `:617`, `_asyncio.py:1502`, `:1693`); and an imported
  (non-structural) base combined with a sibling class in the same module
  declaring the same method name — one shared shape across sibling classes is a
  contract, not a local design choice (`fastapi/fastapi/routing.py` declares
  `matches(scope) -> tuple[Match, Scope]`, starlette's `BaseRoute` protocol, on
  6 classes).

An override of a third-party base that carries none of those marks is still
flagged; adding `@override` (which the type checker wants anyway) both
documents the inheritance and silences the rule.

Suppress a deliberate positional return with `# sarj-noqa: SARJ026 — <reason>`.

References:
- https://docs.python.org/3/library/typing.html#typing.NamedTuple

* **generated files** (`_paths.is_generated`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across two first-party repos — a single Speakeasy-generated
  SDK package accounts for all of them.

## Implementation notes

### `_is_bare_positional_tuple`

Exempts the three permitted forms: `tuple[X, ...]` (Ellipsis), structurally
homogeneous `tuple[X, X]`, and the `tuple[Literal[...], ...]` discriminated tag.

### `_is_interface_stub`

Such a function declares an interface pinned elsewhere; its tuple shape is
not this module's to change. A bare `...` body is NOT a stub here — it is
also the shorthand for an ordinary unwritten function.

### `_is_abstract_declaration`

Like the `NotImplementedError` stub, such a declaration states a contract
whose shape usually mirrors something external (anyio's `receive_fds`
mirrors `socket.recvmsg`), and the concrete side is elsewhere.

### `_is_declared_override`

An override does not own its signature: the tuple shape is pinned by the
base, so changing it here is not an option this module has.

### `_iter_boundary_functions`

Functions nested inside another function are skipped outright: a closure has
no callers outside the frame that defines it, so its return shape never
crosses the boundary this rule guards.

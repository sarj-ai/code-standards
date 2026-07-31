# SARJ011 `prefer-constant-time-secret-compare` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_constant_time_secret_compare.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Comparing secrets (tokens, signatures, HMACs, password hashes, API keys) with
`==`/`!=` is timing-attack-prone: short-circuiting on the first differing byte
leaks information about how many leading bytes matched. Use
`hmac.compare_digest(a, b)`, which compares in constant time.

`signature` is polysemous: in crypto code it is a MAC to verify, but in
reflection-heavy code it is a *function* signature (`inspect.signature`,
`default_model_signature`). A name whose only secret token is `signature`
therefore fires only when the module imports crypto machinery (`hmac`,
`hashlib`, `secrets`, `jwt`, `cryptography`, ...) — code verifying a MAC
computes the expected value with exactly those modules (pydantic's signature
merging was the sweep false positive).

A comparison inside an `__eq__` / `__ne__` method is exempt. Those dunders
implement *value equality* between two objects the process already holds; they
are not an authentication gate, and nothing grants access on their result. A
2,657-file third-party sweep produced 8 findings and 2 were exactly this shape
(requests' `HTTPBasicAuth.__eq__` / `HTTPDigestAuth.__eq__`, which compare
`self.password == getattr(other, "password", None)` so two auth objects can be
compared for identity). A real credential check (`if token != expected:`) sits
in a request handler, not in a dunder, and still fires.

References:
- https://docs.python.org/3/library/hmac.html#hmac.compare_digest

## Implementation notes

### `_is_excluded_operand`

Covers `None`/`True`/`False`, numeric literals, any str/bytes literal, and an
ALL-CAPS constant reference (`TOKEN_TYPE_SYSTEM`, `HTTP_DIGEST_AUTHENTICATION`,
`PASSWORD_NOT_CHANGED`) — all compile-time sentinels/enum members, not a
runtime secret an attacker can extract by timing the compare.

### `_is_auth_secret_name`

Narrows the shared `is_secret_name` for SARJ011: strips category/handle
descriptors, `type`/`kind` discriminators, and integrity-only hashes, none
of which are a timing-attack surface. A name whose only auth token is the
polysemous `signature` needs the module to import crypto machinery —
otherwise it is a function signature, not a MAC.

Boolean flags (`is_token`, `hasSecret`) are NOT handled here: the shared
`is_secret_name` now rejects a leading flag word for both SARJ011 and
SARJ012, so the gate above has already returned. A duplicate local check
used to live here and was dead once that landed — worse, it read
`tokens[0]`, which is the whole snake segment (`"hassecret"`), so it never
matched a camelCase flag in the first place.

### `_imports_crypto`

Naming a module is a precondition for importing it, so the substring test
gates the traversal without narrowing what qualifies.

### `_equality_dunder_compares`

A nested `def`/`lambda` declared inside the dunder is its own callable and
can be invoked from anywhere, so it is not covered by the exemption.

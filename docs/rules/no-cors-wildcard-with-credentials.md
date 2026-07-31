# `no-cors-wildcard-with-credentials` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-cors-wildcard-with-credentials.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS port of Python SARJ028
(`no-cors-wildcard-with-credentials`). Flags CORS configuration that reflects
ANY origin (`"*"`) while ALSO allowing credentials. The browser treats
`Access-Control-Allow-Origin: *` together with
`Access-Control-Allow-Credentials: true` as a directive to reflect the
request's Origin and expose authenticated (cookie/session) responses — which
lets any website read them cross-origin. That is a credential-theft surface.

Two shapes are detected, and BOTH the wildcard origin and credentials=true
must co-occur before the rule fires (a `"*"` origin without credentials, or
credentials with a specific origin, is safe and is NOT reported):

  1. A `cors(...)` / `new Cors(...)` call whose options `ObjectExpression`
     has `credentials: true` AND an `origin` property whose value subtree
     contains a `"*"` string literal anywhere — the bare `"*"`, the `["*"]`
     array, or a `flag ? origins : "*"` conditional branch. Reported at the
     call.

  2. Manual header setting where, within the SAME function (or module) scope,
     `Access-Control-Allow-Origin` is set to `"*"` AND
     `Access-Control-Allow-Credentials` is set to `"true"` — via
     `res.setHeader(...)`, `headers.set(...)` / `.append(...)` (covers
     `NextResponse` header objects), or a single object literal
     `{ "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Credentials": "true" }`.
     Header-name matching is case-insensitive. The object-literal form is
     reported at the object; the split `setHeader`/`set` form is reported at
     the wildcard-origin call.

References:
- https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#credentialed_requests_and_wildcards

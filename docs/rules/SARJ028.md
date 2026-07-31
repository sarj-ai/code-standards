# SARJ028 `no-cors-wildcard-with-credentials` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_cors_wildcard_with_credentials.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`CORSMiddleware(allow_credentials=True, allow_origins=[..., "*", ...])` tells the
browser to reflect the request's `Origin` back in
`Access-Control-Allow-Origin` AND to send `Access-Control-Allow-Credentials:
true`. Together these let *any* website read authenticated (cookie/session)
responses — a cross-origin credential-theft surface.

The rule fires on an `ast.Call` that has BOTH `allow_credentials=True`
(literal) AND an `allow_origins` value whose subtree contains a `"*"` string
literal anywhere — so it catches the bare `["*"]` form as well as the
`allowed if flag else ["*"]` conditional branch. The keyword pair is unique to
Starlette's CORSMiddleware, so matching the callee name is unnecessary (though it
would be a valid further tightening).

References:
- https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#credentialed_requests_and_wildcards

## Implementation notes

### `_contains_star_literal`

Walking the whole subtree catches both `["*"]` and the `allowed if flag else
["*"]` conditional branch. A dynamic `allow_origins=some_var` has no `"*"`
literal, so it does not fire.

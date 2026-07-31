# `no-secret-in-log` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-secret-in-log.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS port of SARJ012 (`no-secret-in-log`). Passing a secret value
(token, password, api key, jwt, credential, signature, ...) to a logging call
leaks it into log sinks — files, stdout, log aggregators — where it persists
far beyond its intended lifetime and is readable by anyone with log access.
Prefer redaction (`tokenPrefix: token.slice(0, 6)`) or omission.

We fire on a logging call (`logger.info(...)`, `log.error(...)`, loguru/bind
builder chains, etc.) that passes a secret-named value either as a property of
an object argument (`logger.error("msg", { token, apiKey })`) or as a bare
secret-named positional identifier (`logger.info("x", password)`).

Log recognition is shared with the catch rules via `_logging`, so the
`logFunctions` option applies here too. That matters: a structured logger is
usually a free function with no logger receiver, and `logEvent("slack.auth",
{ botToken })` was previously never even examined by this rule. Declaring the
project's logger closes that hole.

The secret-name predicate matches a secret word only as a WHOLE token (after
snake_case / camelCase splitting) and disqualifies identifiers whose trailing
token is a counter / row-id / flag marker (`tokenCount`, `apiKeyId`,
`passwordEnabled`) or whose LEADING word is a boolean predicate (`hasSecret`,
`is_token`), so metadata *about* a secret is not mistaken for the secret
itself. Both guards live in the shared `_secret-names` predicate. Redaction
markers (prefix/mask/hash/redact/tag) are exempt on top of that.

## The raw-blob arm (`noRawBodyInLog`)

A second, separately-messaged arm covers what the name-based arm structurally
cannot: a whole request/response **blob** — `logEvent("ashby.response",
{ status, body })`, `console.log(res.body)`. No property of that object is
secret-*named*; the object itself is the leak. Bodies are candidate PII and
routinely echo credentials back (an auth response containing the token it just
minted, a webhook payload carrying its own signing header), and a log sink has
no retention policy for either. The advice differs from the secret arm's —
"redact or omit the blob", not "this named field is a credential" — so it gets
its own messageId.

This arm is deliberately name-driven and narrow. **Only these words, matched as
the identifier's TRAILING camel/snake word, count as a raw blob**: `body`,
`bodies`, `payload`, `payloads`, `params` (so `rawBody`, `requestBody`,
`responsePayload`, `webhookPayload`, `searchParams` all qualify), plus the
single whole identifier `formData` (whose camel split ends in the far too
generic `data`). Generic containers — `data`, `input`, `args`, `event`,
`result`, `record`, `req`, `res` — are NOT blob words: they name everything, so
firing on them would make the rule noise and get it switched off.

A leak is reported only when the logged VALUE is the blob verbatim: a shorthand
property (`{ body }`), a bare identifier (`{ meta: body }`, `logEvent("x",
payload)`), or a non-computed member access whose PROPERTY is blob-named
(`{ body: res.body }`, `console.log(res.body)`). Judging the value rather than
the key is what keeps `{ payload: body.id }` silent.

Deliberately NOT reported:
- **A narrowed field** — `{ id: body.id }`, `{ bodyLength: body.length }`. The
  member property, not the object, decides; picking a field is the fix.
- **Anything passed through a call** — `redact(body)`, `sanitize(payload)`,
  `pick(body, ["id"])`, `JSON.stringify(body).slice(0, 200)`,
  `summarizeIssues(body)`. Summarising is the behaviour we want, and no name
  list can enumerate every project's summariser, so the *shape* is the exemption.
- **A string literal or template** — `{ body: "ok" }`, `` { body: `n=${n}` } ``.
  Already a rendered, author-chosen string.
- **Redaction / derivation markers in the name** — `redactedBody`,
  `sanitizedPayload`, `truncatedBody`, `bodyHash`, `bodyPreview`, `safeBody`.
- **Boolean flags** — `hasBody`, `isPayload`: a leading predicate word.
- **Object spread** — `{ ...body }`. Real, but no observed instances; left out
  rather than shipped unmeasured.
- **Test files** (`_paths.isTestFile`) — a body there is a fixture the author
  wrote, not production PII. The secret arm is deliberately NOT exempted this
  way: its behaviour is unchanged by this port.

Both arms sit behind the same `_logging` gate, so `logFunctions` /
`loggerNames` govern the blob arm identically — `logEvent("x", { body })` is
invisible until the project declares `logEvent`, exactly like `{ botToken }`.

References:
- https://owasp.org/www-community/vulnerabilities/Information_exposure_through_log_files

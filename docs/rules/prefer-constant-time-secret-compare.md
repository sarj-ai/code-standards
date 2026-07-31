# `prefer-constant-time-secret-compare` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-constant-time-secret-compare.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS port of SARJ011 (`prefer-constant-time-secret-compare`).
Comparing secrets (bearer tokens, signatures, HMACs, password hashes, API
keys) with `===`/`!==`/`==`/`!=` is timing-attack-prone: the engine's string
comparison short-circuits on the first differing byte, so the time it takes to
return `false` leaks how many leading bytes the attacker got right. Over enough
requests that is enough to recover the secret byte by byte.

On Cloudflare Workers the correct primitive is `crypto.subtle.timingSafeEqual`
(over equal-length `ArrayBuffer`s — SHA-256 both sides first so the lengths
match and no length is leaked), or a hand-rolled XOR-accumulate loop over the
digests. Node exposes `crypto.timingSafeEqual`. `===` is never the answer.

The secret-name predicate is shared with `no-secret-in-log` and then narrowed
(`isAuthSecretName`): a timing-attack surface is only an *authenticator* whose
bytes gate access, so the following are deliberately NOT flagged even though
they are secret-shaped by name:

- Category / handle metadata: `tokenType === "Bearer"`, `tokenName`,
  `credentialKind`, `apiKeyId` — a discriminator or row id, not the credential.
- Boolean flags: `isTokenValid`, `hasSecret` — a decision, not the bytes.
- Integrity-only content hashes: `contentHash === previousHash` — a change
  detector, not an authenticator. `passwordHash` / `tokenHash` still fire
  because those DO gate access.
- Presence checks and literal sentinels: `token === null`, `secret !== undefined`,
  `token.length === 0`, `tokenType === "bearer"`, `x === TOKEN_TYPE_SYSTEM` —
  comparing against a compile-time constant or a null check reveals nothing
  about a runtime secret.
- Marker values whose camelCase name merely ENDS in a secret word:
  `queryFn === skipToken`. A `skipToken` is a unique `Symbol` compared by
  identity, so there are no bytes to walk and no timing to leak. This was the
  rule's entire false-positive surface on the 2026-07 corpus sweep — 10 hits
  out of 10, all `skipToken`; see `SENTINEL_PREFIX_RE`.
- Anything in a test file: no attacker measures a test's clock, and fixture
  assertions (`expect(res.apiKey === "known")`) are not an auth path.

References:
- https://developers.cloudflare.com/workers/runtime-apis/web-crypto/#timingsafeequal
- https://codahale.com/a-lesson-in-timing-attacks/

## Evidence relocated from the source

### `*`

Corpus evidence (2220 files across zod / TanStack Query / react-router / swr /
zustand, 2026-07): the rule fired 10 times and ALL TEN were
`options.queryFn === skipToken`, e.g.
`query/packages/query-core/src/queryClient.ts:604`. The list is deliberately
limited to modifiers that can only introduce a marker; `default`/`invalid`
are excluded because `defaultApiKey` really can hold a live credential.


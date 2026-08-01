# `no-insecure-random-id` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-insecure-random-id.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow using `Math.random()` to generate identifiers,
tokens, keys, or other security-sensitive values. `Math.random()` is not
cryptographically secure and is predictable — using it for tokens/secrets
can lead to collisions and trivially guessable values. Prefer
`crypto.randomUUID()` or `crypto.getRandomValues(...)` instead.

Precision matters here: the rule runs at `error` in the `strict` config, so a
false positive blocks a real PR. Large open-source sweeps (VS Code, NestJS,
Next.js) showed the bare `id`/`key`/`session` substring heuristic firing on a
flood of NON-security correlation/ephemeral ids — temp-file suffixes, HMR
session numbers, dev request/execution/trace ids, in-process RPC handles.
None of those are security tokens. So the rule now requires a STRONG security
signal, and actively exempts names that read as ephemeral/correlation ids or
random values concatenated into a filename/path/DOM id.

The rule flags a `Math.random()` call when, and only when:
  1. Its enclosing binding/property NAME carries a strong security signal
     (`token`, `secret`, `apiKey`, `csrf`, `password`, `nonce`, `salt`,
     `uuid`, `authId`) — even a `sessionToken` counts because of `token`; or
  2. Its result is fed into a `.toString(36)` chain (the classic insecure
     random-id idiom, e.g. `Math.random().toString(36).slice(2)`) AND the
     value is not an exempt ephemeral/correlation id or path fragment.

It does NOT flag when the enclosing name signals a non-security
correlation/ephemeral id (`temp`, `tmp`, `cache`, `correlation`, `request`,
`req`, `trace`, `execution`, `dev`, `hmr`, `mock`, `test`, `perf`, `marker`),
nor when the random value is concatenated into a filename/path/DOM id. A
strong security name still wins over these exemptions.

Bare `Math.random()` used for non-identifier purposes (jitter, sampling,
rolls, etc.) is NOT flagged, and neither is the bare `id`/`key`/`session`
substring on its own — we err toward suppressing ambiguous correlation ids.

Test files are out of scope entirely. A fixture generator is not a token
mint, and the `.toString(36)` idiom is how tests cheaply produce distinct
keys. Measured on 2,186 real TypeScript files (zod / TanStack Query /
react-router / swr / zustand): 3 of 6 hits were exactly that —
zod/packages/zod/src/v3/tests/Mocker.ts:13 (a mock-data string generator) and
two in
react-router/packages/react-router/__tests__/vendor/turbo-stream-test.ts:215
(random map keys for a serialization round-trip). None is a credential.

KNOWN GAP (false-negative): an arithmetic expression between `Math.random()`
and `.toString(36)` breaks the member-chain walk, e.g.
`(Math.random() * 1e9).toString(36)`. The intervening `BinaryExpression`
means `Math.random()` is no longer the object end of the `.toString` chain,
so trigger 2 does not fire. Such code is only caught if its binding/property
name looks security-like (trigger 1). See the documented test case.

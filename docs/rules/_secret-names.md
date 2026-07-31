# `_secret-names` — evidence

Shared helper. This file holds what the code cannot: the measurements behind
each threshold, the false-positive families the guards exist to stop, and the
alternatives that were rejected.

Shared predicate for deciding whether an identifier names secret
material. TS port of Python's `_secret_names.py`, used by `no-secret-in-log`
(SARJ012) and `prefer-constant-time-secret-compare` (SARJ011) so the two rules
never diverge on what counts as a secret.

A naive implementation matches a secret word as a bare *substring*, which
misfires on a large false-positive class observed in real audits:

- LLM usage counters that merely embed `token`: `tokenCount`, `promptTokens`,
  `completionTokens`, `totalTokens`, `maxTokens`, `tokenize`, `tokenizer`,
  `tokenBudget`.
- Row-id / handle names: `apiKeyId`, `*KeyId` — the id of a key row, not the
  key material.
- Boolean feature / presence / state flags: `passwordEnabled`, `tokenPresent`,
  `passwordSet`, `passwordConfigured` — a boolean answering "is it there / was
  it set", not the credential itself. A `type` discriminator is the same:
  `tokenType` is `"Bearer"`, `credentialType` is a class name.
- Innocent words embedding a secret word: `secretary` (embeds `secret`),
  `keyboardEvent` (embeds `key`).

Two rules fix this:

1. Match a secret word only as a WHOLE token (after snake_case / camelCase
   splitting), never a substring. This alone clears `tokenize`, `tokenizer`,
   `secretary`, and every *pluralized* `tokens` counter (plural `tokens` is not
   the singular secret word `token`).
2. Disqualify an identifier whose TRAILING token is a counter / row-id / flag
   marker (`count`, `budget`, `id`, `enabled`, ...) even when a secret word is
   also present — this clears `tokenCount`, `apiKeyId`, `passwordEnabled`,
   while still catching a credential that merely leads with such a word
   (`validToken`, `presentToken` are secrets, not flags).

`isAuthSecretName` narrows further for SARJ011: a *timing-attack* surface is
only an authenticator whose bytes gate access, so category discriminators,
boolean flags, and integrity-only content hashes are stripped there while
`no-secret-in-log` keeps its broader reach.

## Evidence relocated from the source

### `"kind",`

Trailing token that makes the identifier metadata *about* a secret (its
category / handle / label), not the credential: `tokenType`, `tokenName`,
`sessionId`, `credentialKind`. `type`/`id` are already dropped by the shared
innocuous set; `name`/`kind` are added here because logging them can still
matter (SARJ012) but they are never a timing surface.

### `hasApiKey`

`tokenize` deliberately emits each whole snake/kebab segment before its camel
parts, so `tokens[0]` for the camelCase `hasSecret` is the useless `hassecret`
rather than `has`. Reading `tokens[0]` directly — as the Python original's
local check did — therefore never matched a camelCase flag at all, and Python's
shared predicate had no leading check whatsoever; both were false positives,
fixed on both sides. The leading-word check has to split the first segment
explicitly or every `isToken` / `hasSecret` flag is mistaken for a credential.

### `if`

Narrows `isSecretName` for SARJ011: strips category/handle descriptors and
`type`/`kind` discriminators, neither of which is a timing-attack surface even
though logging them may still matter. Leading boolean-predicate flags are no
longer stripped here — `isSecretName` now rejects them for every consumer, so
repeating the check would be dead code.


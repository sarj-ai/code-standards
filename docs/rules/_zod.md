# `_zod` — evidence

Shared helper. This file holds what the code cannot: the measurements behind
each threshold, the false-positive families the guards exist to stop, and the
alternatives that were rejected.

The single source of truth for "does this name read as a Zod
schema?". Shared by `zod-naming-convention` (which ENFORCES a convention) and
`require-zod-form-validation` (which RECOGNISES a schema receiver), because
the two disagreeing is a bug: a plugin that accepts `SubmitFormSchema` as a
validator in one rule must not call the same symbol non-conforming in another.

Two conventions are recognised, and both are correct:
  - PREFIX (`ZUser`) — lets a schema and its inferred type share a base name
    (`type User = z.infer<typeof ZUser>`) without collision.
  - SUFFIX (`userSchema`, `SubmitFormDataSchema`) — the dominant convention in
    the wider Zod ecosystem and in most existing codebases.

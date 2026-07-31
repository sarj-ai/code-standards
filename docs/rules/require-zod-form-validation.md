# `require-zod-form-validation` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/require-zod-form-validation.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Require Zod validation on values read out of a `FormData`.
`formData.get(k)` returns `FormDataEntryValue | null` — an unvalidated,
attacker-controlled value. Pipe it through a schema before use.

Validation is recognised two ways:
  - INLINE: the `.get(...)` call sits inside a Zod `.parse(...)` /
    `.safeParse(...)` — found by walking up the parent chain.
  - VIA A BINDING: the value is bound and validated one or more statements
    later, which is how a real handler reads. Tracked through the scope
    manager (the same approach `prefer-schema-for-api-payload` uses for
    `response.json()`), so this is not reported:
      const tokenRaw = formData.get("t");
      const parsed = ZForm.safeParse({ t: typeof tokenRaw === "string" ? tokenRaw : undefined });

A binding narrowed by `instanceof File` / `instanceof Blob` is also exempt: a
Zod schema has nothing useful to say about a `File`, and `instanceof` IS the
validation for that branch.

A Zod receiver is recognised by name — `Schema`-suffixed (`userSchema`), the
`Z<Capital>` house form (`ZUser`), or the bare `z` builder — matching
`zod-naming-convention`, which accepts both conventions.

TEST FILES ARE EXEMPT. Corpus sweep (2220 files across zod / TanStack Query /
react-router / swr / zustand, 2026-07): 42 raw hits, 40 of them in
react-router suites and every one an assertion rather than a trust boundary.
`react-router/packages/react-router/__tests__/dom/data-browser-router-test.tsx:4183`
is the shape — `let formData = await actionSpy.mock.calls[0][0].request.formData();
expect(formData.get("a")).toBe("1")`. The FormData was built by the test two
lines earlier; there is no attacker, and validating it with a schema would
assert the schema instead of the router. The rule's premise — "this value is
attacker-controlled" — is false by construction in a fixture.

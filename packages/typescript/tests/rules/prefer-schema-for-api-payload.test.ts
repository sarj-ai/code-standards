import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-schema-for-api-payload.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("prefer-schema-for-api-payload", rule, {
  valid: [
    // FP guard, corpus: react-router/integration/request-test.ts:120 — the
    // assertion IS the validation, and the suite is hyphen-named so no path
    // predicate sees it.
    {
      code: "async function t(page) { const loaderData = JSON.parse(await page.innerHTML()); expect(loaderData.method).toEqual('GET'); }",
    },
    // FP guard, corpus: zod/scripts/check-versions.ts:13 — JSON off local disk
    // is not a peer's payload.
    {
      code: "const packageJson = JSON.parse(readFileSync(p, 'utf8')); const v = packageJson.version;",
    },
    {
      code: "async function f(metaPath) { const meta = JSON.parse(await fs.readFile(metaPath, 'utf-8')); return meta.pages; }",
    },
    // Test files: a fixture parses what it just produced.
    {
      code: "async function t(res) { const body = await res.json(); use(body.id); }",
      filename: "/repo/src/__tests__/api.test.ts",
    },
    // Generated API clients own their payload typing at the generator/template boundary.
    {
      code: "async function f(r) { const body = await r.json(); return body.id; }",
      filename: "/repo/src/openapi-gen/client.ts",
    },
    // No json() involved.
    { code: "const x = { foo: 1 }; doStuff(x.foo);" },
    // Parsed through Zod.
    {
      code: "async function f(r) { const data = ZUser.parse(await r.json()); return data.name; }",
    },
    // safeParse.
    {
      code: "async function f(r) { const data = ZUser.safeParse(await r.json()); }",
    },
    // json() result used as opaque value, never field-accessed.
    {
      code: "async function f(r) { const data = await r.json(); return data; }",
    },
    // Direct `.parse()` chained off `.json()` is fine.
    {
      code: "async function f(r) { return ZUser.parse(await r.json()); }",
    },
    // Chained `.safeParse()` directly on the json() result is a validation.
    {
      code: "async function f(r) { return (await r.json()).safeParse(); }",
    },
    // Reassignment untracks: once `data` is reassigned to a parse result, later
    // field access is validated and must not be flagged.
    {
      code: "async function f(r) { let data = await r.json(); data = ZUser.parse(data); return data.name; }",
    },
    // Hand-written type-guard predicate (isX) validates before field access.
    {
      code: "async function f(r) { const body = await r.json(); if (isProtectedResourceMetadata(body)) { return body.resource; } }",
    },
    // Negated guard narrowing in the test position also counts.
    {
      code: "async function f(r) { const body = await r.json(); if (!isValidPayload(body)) throw new Error('x'); return body.id; }",
    },
    // A guard used purely as an `if` test narrows even without the `is` prefix.
    {
      code: "async function f(r) { const body = await r.json(); if (validate(body)) { return body.value; } }",
    },

    // === The read IS the validation =======================================
    // FP guard, corpus: trpc/packages/next/src/app-dir/server.ts:200-202 —
    // `const { cacheTag } = await req.json(); if (typeof cacheTag !== 'string')`
    // is how most of this corpus validates, and it is a complete check.
    {
      code: "async function f(req) { const { cacheTag } = await req.json(); if (typeof cacheTag !== 'string') { return new Response(null, { status: 400 }); } return cacheTag; }",
    },
    // The same shape as a field read rather than a destructure.
    {
      code: "async function f(r) { const body = await r.json(); if (typeof body.id !== 'string') { throw new Error('bad'); } }",
    },
    {
      code: "async function f(r) { const body = await r.json(); if (!Array.isArray(body.items)) { throw new Error('bad'); } }",
    },
    // FP guard, corpus: formbricks/apps/web/modules/ee/license-check/lib/
    // license.ts:389 — `validateLicenseDetails` is literally
    // `LicenseDetailsSchema.parse(data)` at :271, so the field read is consumed
    // by a validator and never trusted.
    {
      code: "async function f(r) { const responseJson = await r.json(); return validateLicenseDetails(responseJson.data); }",
    },
    {
      code: "async function f(r) { const body = await r.json(); return decodeToken(body.token); }",
    },

    // === `.json()` promise chains =========================================
    // FP guard: `<json()>.catch(f)` / `.then(f)` is a chain link, not a field
    // read — reporting the `.catch` both landed on the wrong node AND lost
    // tracking of the value, so the real unvalidated read was missed.
    // Corpus: midday/packages/workbench/src/ui/lib/api.ts:73.
    {
      code: "async function f(r) { const e = await r.json().catch(() => ({})); return e; }",
    },
    // A chain terminated by a schema parse is validated.
    {
      code: "async function f(r) { const d = await r.json().then(ZUser.parse); return d.name; }",
    },

    // === `JSON.parse` source ==============================================
    // The recommended shape: park it in an `unknown` and validate. Nothing is
    // read off the raw value, so nothing is reported.
    { code: "const raw = JSON.parse(text); const data = Schema.parse(raw); use(data.foo);" },
    { code: "const data = Schema.parse(JSON.parse(text)); use(data.foo);" },
    { code: "const r = Schema.safeParse(JSON.parse(text));" },
    // Parsed but never dereferenced.
    { code: "const raw = JSON.parse(text); send(raw);" },
    // A `.parse()` that is not `JSON.parse` is the validation we are asking for.
    { code: "const data = YAML.parse(text); use(data.foo);" },
    { code: "const data = Schema.parse(text); use(data.foo);" },
    // A hand-written guard narrows just as a schema does.
    { code: "const d = JSON.parse(text); if (isConfig(d)) { use(d.foo); }" },
  ],
  invalid: [
    // The trust boundary still fires: a network payload read outside an assertion.
    {
      code: "async function f(res) { const body = await res.json(); return body.id; }",
      filename: "/repo/src/clients/user-client.ts",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r) { const data = await r.json(); return data.name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r) { const payload = await r.json(); console.log(payload.id); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Destructuring directly off a json() call.
    {
      code: "async function f(r) { const { name } = await r.json(); return name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Array-pattern destructuring directly off a json() call.
    {
      code: "async function f(r) { const [first] = await r.json(); return first; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Array-pattern destructuring off a tracked variable.
    {
      code: "async function f(r) { const data = await r.json(); const [first] = data; return first; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Direct field access on the json() result (no schema parse).
    {
      code: "async function f(r) { return (await r.json()).name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Post-first-access untracking: only the FIRST unvalidated read is flagged.
    {
      code: "async function f(r) { const d = await r.json(); console.log(d.a); console.log(d.b); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // === `JSON.parse` source ==============================================
    // Field read off an unvalidated `JSON.parse` result.
    {
      code: "const data = JSON.parse(text); use(data.foo);",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Direct field access on the call result.
    {
      code: "const name = JSON.parse(text).name;",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // Destructuring the raw result.
    {
      code: "const { foo } = JSON.parse(text);",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    // === Upper bounds on the new guards ===================================
    // Narrowing ONE field does not bless the rest: the `typeof` read is skipped
    // without untracking, so the next unguarded read still fires.
    {
      code: "async function f(r) { const body = await r.json(); if (typeof body.id !== 'string') { throw new Error('bad'); } return body.email; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // A destructure is only exempt when EVERY binding it introduces is narrowed.
    {
      code: "async function f(r) { const { id, email } = await r.json(); if (typeof id !== 'string') { throw new Error('bad'); } return email; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // The validator-name widening is anchored: `validated` is not `validateX`.
    {
      code: "async function f(r) { const body = await r.json(); return validated(body.data); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    // The `.catch()` chain link is now tracked rather than reported, which moves
    // the report onto the real unvalidated field read one line down. Corpus:
    // midday/packages/workbench/src/ui/lib/api.ts:73-74 and
    // papermark/ee/features/dataroom-freeze/components/freeze-settings.tsx:110-112.
    {
      code: "async function f(r) { const error = await r.json().catch(() => ({})); throw new Error(error.error); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r) { const data = await r.json().catch(() => ({})); throw new Error(data.error || data.message); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r) { const d = await r.json().then((x) => x); return d.name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
  ],
});

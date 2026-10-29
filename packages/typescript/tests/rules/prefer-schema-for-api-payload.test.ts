// vitest: shared-module-graph
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_SCHEMA_FOR_API_PAYLOAD_DOCUMENTATION } from "../../src/rules/prefer-schema-for-api-payload.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("prefer-schema-for-api-payload", rule, {
  valid: [
    {
      name: "validates payloads fetched through a destructured native alias",
      code: "const {fetch: transport} = globalThis; async function load() { const response = await transport('/items'); const body = ItemSchema.parse(await response.json()); return body.id; }",
    },
    {
      name: "does not infer native fetch from a shadowed receiver",
      code: "async function load(globalThis) { const {fetch: transport} = globalThis; const response = await transport('/items'); const body = await response.json(); return body.id; }",
    },
    {
      name: "does not infer native fetch from a dynamic computed member",
      code: "async function load(method) { const response = await globalThis[method]('/items'); const body = await response.json(); return body.id; }",
    },

    { name: "native JSON round trip is not an external payload source", code: "function normalize(schema) { const normalized = JSON.parse(JSON.stringify(schema)); return normalized.properties; }" },
    { name: "shadowed Response annotation is not a native response", code: "type Response = { json(): { id: string } }; function render(model: Response) { const value = model.json(); return value.id; }" },
    { name: "reassigned response is not proven native", code: "async function render() { let response = await fetch('/items'); response = model; const value = response.json(); return value.id; }" },
    { name: "untyped response name alone does not establish provenance", code: "async function render(response) { const value = await response.json(); return value.id; }" },
    { name: "arbitrary model json is not a network response", code: "function render(model) { const value = model.json(); return value.id; }" },
    { name: "shadowed JSON parser is not native JSON", code: "function render(JSON) { const value = JSON.parse(raw); return value.id; }" },
    { name: "public no-match example", filename: PREFER_SCHEMA_FOR_API_PAYLOAD_DOCUMENTATION.examples[0].focusPath, code: PREFER_SCHEMA_FOR_API_PAYLOAD_DOCUMENTATION.examples[0].files[0].source },
    {
      name: "allows integration scripts to inspect the real transport payload",
      filename: "/repo/scripts/e2e-scenario.mjs",
      code: "const payload = await response.json(); console.log(payload.id);",
    },

    {
      code: "async function t(page) { const loaderData = JSON.parse(await page.innerHTML()); expect(loaderData.method).toEqual('GET'); }",
    },

    {
      code: "const packageJson = JSON.parse(readFileSync(p, 'utf8')); const v = packageJson.version;",
    },
    {
      code: "async function f(metaPath) { const meta = JSON.parse(await fs.readFile(metaPath, 'utf-8')); return meta.pages; }",
    },
    {
      code: "const manifest = JSON.parse(readJsonSync(path)); return manifest.version;",
    },
    {
      name: "allows a local file read stored before JSON parsing",
      code: "const text = readFileSync(path, 'utf8'); const manifest = JSON.parse(text); return manifest.version;",
    },
    {
      name: "allows an awaited local file read stored before JSON parsing",
      code: "async function f(path) { const text = await fs.readFile(path, 'utf8'); const manifest = JSON.parse(text); return manifest.version; }",
    },
    {
      name: "allows a same-scope alias of local file text",
      code: "const text = readFileSync(path, 'utf8'); const alias = text; const manifest = JSON.parse(alias); return manifest.version;",
    },

    {
      code: "async function t(res: Response) { const body = await res.json(); use(body.id); }",
      filename: "/repo/src/__tests__/api.test.ts",
    },

    {
      code: "async function f(r: Response) { const body = await r.json(); return body.id; }",
      filename: "/repo/src/openapi-gen/client.ts",
    },

    { code: "const x = { foo: 1 }; doStuff(x.foo);" },

    {
      code: "async function f(r: Response) { const data = ZUser.parse(await r.json()); return data.name; }",
    },

    {
      code: "async function f(r: Response) { const data = ZUser.safeParse(await r.json()); }",
    },

    {
      code: "async function f(r: Response) { const data = await r.json(); return data; }",
    },

    {
      code: "async function f(r: Response) { return ZUser.parse(await r.json()); }",
    },

    {
      code: "async function f(r: Response) { return (await r.json()).safeParse(); }",
    },


    {
      code: "async function f(r: Response) { let data = await r.json(); data = ZUser.parse(data); return data.name; }",
    },

    {
      code: "async function f(r: Response) { const body = await r.json(); if (isProtectedResourceMetadata(body)) { return body.resource; } }",
    },

    {
      code: "async function f(r: Response) { const body = await r.json(); if (!isValidPayload(body)) throw new Error('x'); return body.id; }",
    },

    {
      code: "async function f(r: Response) { const body = await r.json(); if (validate(body)) { return body.value; } }",
    },

    {
      code: "async function f(r: Response) { const body = await r.json(); return accepts(body) ? body.value : null; }",
    },
    {
      code: "async function f(r: Response) { const body = await r.json(); while (accepts(body) && ready) { return body.value; } }",
    },


    {
      code: "async function f(req: Request) { const { cacheTag } = await req.json(); if (typeof cacheTag !== 'string') { return new Response(null, { status: 400 }); } return cacheTag; }",
    },

    {
      code: "async function f(r: Response) { const body = await r.json(); if (typeof body.id !== 'string') { throw new Error('bad'); } }",
    },
    {
      code: "async function f(r: Response) { const body = await r.json(); if (!Array.isArray(body.items)) { throw new Error('bad'); } }",
    },
    {
      code: "async function f(r: Response) { const body = await r.json(); if (typeof (body.id as unknown) !== 'string') { throw new Error('bad'); } }",
    },
    {
      code: "async function f(r: Response) { const responseJson = await r.json(); return validateLicenseDetails(responseJson.data); }",
    },
    {
      code: "async function f(r: Response) { const body = await r.json(); return decodeToken(body.token); }",
    },
    {
      code: "async function f(r: Response) { const body = await r.json(); assertIdentifier(body.id); return coerceCount(body.count); }",
    },


    {
      code: "async function f(r: Response) { const e = await r.json().catch(() => ({})); return e; }",
    },

    {
      code: "async function f(r: Response) { const d = await r.json().then(ZUser.parse); return d.name; }",
    },
    {
      code: "async function f(r: Response) { const d = await r.json().then(ZUser.safeParse); return d.success; }",
    },


    { code: "const raw = JSON.parse(text); const data = Schema.parse(raw); use(data.foo);" },
    { code: "const data = Schema.parse(JSON.parse(text)); use(data.foo);" },
    { code: "const r = Schema.safeParse(JSON.parse(text));" },

    { code: "const raw = JSON.parse(text); send(raw);" },
    {
      name: "allows a simple alias that remains opaque",
      code: "async function f(r: Response) { const raw = await r.json(); const alias = raw; return alias; }",
    },
    {
      name: "allows an alias reassigned to a parsed value",
      code: "async function f(r: Response) { const raw = await r.json(); let alias = raw; alias = Schema.parse(alias); return alias.id; }",
    },
    {
      name: "validation through the source clears its local aliases",
      code: "async function f(r: Response) { const raw = await r.json(); const alias = raw; if (isPayload(raw)) return alias.id; }",
    },
    {
      name: "validation through an alias clears the shared source payload",
      code: "async function f(r: Response) { const raw = await r.json(); const alias = raw; if (isPayload(alias)) return raw.id; }",
    },
    {
      name: "does not taint an alias of an ordinary local value",
      code: "const raw = { id: 'local' }; const alias = raw; return alias.id;",
    },

    { code: "const data = YAML.parse(text); use(data.foo);" },
    { code: "const data = Schema.parse(text); use(data.foo);" },

    { code: "const d = JSON.parse(text); if (isConfig(d)) { use(d.foo); }" },
    {
      name: "allows an extracted primitive used only in its validated conditional branch",
      code: "const payload = JSON.parse(text); const exp = payload.exp; return typeof exp === 'number' ? exp : null;",
    },
    {
      name: "allows an extracted array used only in its validated conditional branch",
      code: "const payload = JSON.parse(text); const items = payload.items; return Array.isArray(items) ? items : [];",
    },
    {
      name: "allows a parsed root used inside its proven array branch",
      code: "const parsed = JSON.parse(text); if (Array.isArray(parsed)) return parsed.map(String); return [];",
    },
    {
      name: "allows a field used inside its proven primitive branch",
      code: "async function f(r: Response) { const body = await r.json(); return typeof body.id === 'string' ? body.id.trim() : null; }",
    },
  ],
  invalid: [
    {
      name: "requires validation after a static computed native fetch",
      code: "async function load() { const response = await globalThis['fetch']('/items'); const body = await response.json(); return body.id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "requires validation after a stable native fetch alias",
      code: "const transport = globalThis.fetch; async function load() { const response = await transport('/items'); const body = await response.json(); return body.id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "requires validation after a destructured native fetch alias",
      code: "const {fetch: transport} = globalThis; async function load() { const response = await transport('/items'); const body = await response.json(); return body.id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    { name: "destructured validation in only one branch does not dominate use", code: "async function f(r: Response) { const { id } = await r.json(); if (flag) { if (typeof id !== 'string') throw new Error('bad'); } return id; }", errors: [{ messageId: "unparsedJsonAccess" }] },
    { name: "fetch derived response remains a positive", code: "async function f() { const response = await fetch('/items'); const body = await response.json(); return body.id; }", errors: [{ messageId: "unparsedJsonAccess" }] },
    { name: "Request construction remains a positive", code: "async function f() { const request = new Request('/items'); const body = await request.json(); return body.id; }", errors: [{ messageId: "unparsedJsonAccess" }] },
    { name: "guarded closure does not prove later execution safety", code: "async function f(r: Response) { const body = await r.json(); if (isPayload(body)) return () => body.id; }", errors: [{ messageId: "unparsedJsonAccess" }] },
    { name: "conditional validation does not validate the following path", code: "async function f(r: Response) { const body = await r.json(); if (isPayload(body)) consume(body); return body.id; }", errors: [{ messageId: "unparsedJsonAccess" }] },
    { name: "validation in a deferred function does not dominate outer reads", code: "async function f(r: Response) { const body = await r.json(); const check = () => validatePayload(body); return body.id; }", errors: [{ messageId: "unparsedJsonAccess" }] },
    { name: "an ignored predicate result does not validate a payload", code: "async function f(r: Response) { const body = await r.json(); isPayload(body); return body.id; }", errors: [{ messageId: "unparsedJsonAccess" }] },
    { name: "public match example", filename: PREFER_SCHEMA_FOR_API_PAYLOAD_DOCUMENTATION.examples[1].focusPath, code: PREFER_SCHEMA_FOR_API_PAYLOAD_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "unparsedJsonAccess" }] },

    {
      code: "async function f(res: Response) { const body = await res.json(); return body.id; }",
      filename: "/repo/src/clients/user-client.ts",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r: Response) { const data = await r.json(); return data.name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r: Response) { const payload = await r.json(); console.log(payload.id); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(r: Response) { const { name } = await r.json(); return name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(r: Response) { const [first] = await r.json(); return first; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(r: Response) { const data = await r.json(); const [first] = data; return first; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(r: Response) { return (await r.json()).name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(r: Response) { const d = await r.json(); console.log(d.a); console.log(d.b); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "const data = JSON.parse(text); use(data.foo);",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "const name = JSON.parse(text).name;",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "const { foo } = JSON.parse(text);",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "let foo; ({ foo } = JSON.parse(text));",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r: Response) { const body = await r.json(); let id; ({ id } = body); return id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(a: Response, b: Response) { let body = await a.json(); body = await b.json(); return body.id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "tracks a simple local alias of an unvalidated payload",
      code: "async function f(r: Response) { const raw = await r.json(); const alias = raw; return alias.id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "tracks a multi-hop local alias chain",
      code: "async function f(r: Response) { const raw = await r.json(); const first = raw; const second = first; return second.id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "tracks an alias introduced by assignment",
      code: "async function f(r: Response) { const raw = await r.json(); let alias = {}; alias = raw; return alias.id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "keeps an alias tainted when the source binding is parsed later",
      code: "async function f(r: Response) { let raw = await r.json(); const alias = raw; raw = Schema.parse(raw); return alias.id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "keeps the source tainted when only the alias binding is replaced",
      code: "async function f(r: Response) { const raw = await r.json(); let alias = raw; alias = Schema.parse(alias); return raw.id; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "reassignment detaches local-file provenance",
      code: "let text = readFileSync(path, 'utf8'); text = externalText; const data = JSON.parse(text); return data.id;",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "an extracted property escaping before validation remains unsafe",
      code: "const payload = JSON.parse(text); const exp = payload.exp; consume(exp);",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "a mutable extracted property remains unsafe",
      code: "const payload = JSON.parse(text); let exp = payload.exp; return typeof exp === 'number' ? exp : null;",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "mixed guarded and unguarded uses remain unsafe",
      code: "const payload = JSON.parse(text); const exp = payload.exp; log(exp); return typeof exp === 'number' ? exp : null;",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "an array guard does not validate a parsed root after the guarded branch",
      code: "const parsed = JSON.parse(text); if (Array.isArray(parsed)) consume(parsed); return parsed.id;",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "a field guard does not validate that field after the guarded branch",
      code: `async function f(r: Response) {
        const body = await r.json();
        if (typeof body.id === "string") {
          consume(body.id);
        }
        return body.id;
      }`,
      errors: [{ messageId: "unparsedJsonAccess", line: 6 }],
    },
    {
      name: "validating one extracted field does not clear a sibling field",
      code: "const payload = JSON.parse(text); const exp = payload.exp; const safe = typeof exp === 'number' ? exp : null; return payload.email;",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "a nested-scope extraction does not inherit same-scope validation",
      code: "const payload = JSON.parse(text); function nested() { const exp = payload.exp; return typeof exp === 'number' ? exp : null; } return nested();",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      name: "reports once for multiple bindings of the same payload",
      code: "async function f(r: Response) { const raw = await r.json(); const alias = raw; consume(alias.id); return raw.email; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },


    {
      code: "async function f(r: Response) { const body = await r.json(); if (typeof body.id !== 'string') { throw new Error('bad'); } return body.email; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(r: Response) { const { id, email } = await r.json(); if (typeof id !== 'string') { throw new Error('bad'); } return email; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(r: Response) { const body = await r.json(); return validated(body.data); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r: Response) { const body = await r.json(); return parser(body.data); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(r: Response) { const body = await r.json(); expect(body.id).toBe('x'); return body.email; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(r: Response) { const error = await r.json().catch(() => ({})); throw new Error(error.error); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r: Response) { const data = await r.json().catch(() => ({})); throw new Error(data.error || data.message); }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r: Response) { const d = await r.json().then((x) => x); return d.name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
    {
      code: "async function f(r: Response) { const d = await r.json().finally(cleanup); return d.name; }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },

    {
      code: "async function f(res: Response) { if (!res.ok) { const error = await res.json(); toast(error.message); } }",
      errors: [{ messageId: "unparsedJsonAccess" }],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "unvalidated-payload-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/client.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/client.ts",
        "source": "async function load(response: Response) { const body = await response[\"json\"](); return body[\"id\"]; }"
      }
    ]
  },
  {
    "id": "unvalidated-payload-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/client.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/client.ts",
        "source": "async function load(response: Response) { const body = await response[auditDynamicMember](); return body[auditDynamicMember]; }"
      }
    ]
  }
] } });
});

// vitest: shared-module-graph
import rule from "../../src/rules/no-generic-json-parser.js";
import { ruleTester } from "./_tester.js";

const TESTER = ruleTester();

TESTER.run("no-generic-json-parser", rule, {
  valid: [
    "import { z } from 'zod'; function load(raw: unknown) { const result = z.object({ id: z.string() }).safeParse(raw); if (!result.success) return; return result.data.id; }",
    { name: "opaque JSON forwarding", code: "import { z } from 'zod'; function load(raw) { return z.json().parse(raw); }" },
    { name: "Promise chaining is not a payload field read", code: "import { z } from 'zod'; z.json().parseAsync(raw).then(forward);" },
    { name: "dynamic dictionary index", code: "import { z } from 'zod'; const body = z.record(z.string(), z.string()).parse(raw); consume(body[key]);" },
    { name: "custom parser namespace", code: "import { z } from './parser.js'; const body = z.json().parse(raw); consume(body.version);" },
    { name: "shadowed import", code: "import { z } from 'zod'; function f(z) { return z.json().parse(raw).version; }" },
    { name: "custom refining schema", code: "import { z } from 'zod'; const Schema = z.unknown().transform(decode); const body = Schema.parse(raw); consume(body.version);" },
    { name: "type-only import", code: "import type { z } from 'zod'; const body = z.json().parse(raw); consume(body.version);" },
    { name: "mutable alias is unresolved", code: "import { z } from 'zod'; let body = z.json().parse(raw); body = validated; consume(body.version);" },
    { name: "generated artifact", filename: "src/generated/parser.ts", code: "import { z } from 'zod'; function load(raw: unknown) { const result = z.record(z.string(), z.unknown()).safeParse(raw); if (!result.success) return; return result.data.id; }" },
  ],
  invalid: [
    { name: "local suppression (reported: Oxlint's RuleTester ignores disable directives)", code: "import { z } from 'zod';\n// eslint-disable-next-line @rule-tester/no-generic-json-parser -- compatibility parser has a separate contract\nconst body = z.record(z.string(), z.unknown()).parse(raw); consume(body.version);", errors: [{ messageId: "genericParser" }] },
    { code: "import { z } from 'zod'; function load(raw: unknown) { const result = z.record(z.string(), z.unknown()).safeParse(raw); if (!result.success) return; return result.data.id; }", errors: [{ messageId: "genericParser" }] },
    ...[
      ["direct unknown parser", "import { z } from 'zod'; consume(z.unknown().parse(raw).version);"],
      ["direct JSON parser", "import { z } from 'zod'; consume(z.json().parse(raw)['version']);"],
      ["aliased Zod namespace", "import { z as schema } from 'zod'; const body = schema.any().parse(raw); consume(body.version);"],
      ["namespace import", "import * as schema from 'zod'; const body = schema.json().parse(raw); consume(body.version);"],
      ["named factory", "import { json } from 'zod'; const body = json().parse(raw); consume(body.version);"],
      ["schema aliases", "import { z } from 'zod'; const JsonSchema = z.json(); const AliasSchema = JsonSchema; const body = AliasSchema.parse(raw); consume(body.version);"],
      ["output aliases", "import { z } from 'zod'; const body = z.json().parse(raw); const result = body; consume(result.version);"],
      ["transparent wrappers", "import { z } from 'zod'; const body = z.json().nullable().parse(raw); consume(body.version);"],
      ["asynchronous parser", "import { z } from 'zod'; async function f() { const body = await z.json().parseAsync(raw); return body.version; }"],
      ["one report per parse", "import { z } from 'zod'; const body = z.json().parse(raw); consume(body.version, body.limit);"],
    ].map(([name, code]) => ({ name, code, errors: [{ messageId: "genericParser" as const }] })),
  ],
});

TESTER.run("no-generic-json-parser retained extensions", rule, {
  valid: [
    { name: "preserves success-envelope handling", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (!result.success) report(result.error); else forward(result.data);" },
    { name: "preserves direct field validation", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (result.success) consume(z.string().parse(result.data.id));" },
    { name: "preserves an alias consumed only by field validation", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (result.success) { const id = result.data.id; consume(z.string().parse(id)); }" },
    { name: "preserves staged throwing-parse validation", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const data = Schema.parse(raw); consume(z.string().parse(data.id));" },
    { name: "preserves concrete dictionary values", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.string()); const result = Schema.safeParse(raw); if (result.success) consume(result.data.id);" },
    { name: "preserves finite declared dictionary keys", code: "import { z } from 'zod'; const Schema = z.record(z.enum(['id']), z.string()); const result = Schema.safeParse(raw); if (result.success) consume(result.data.id);" },
    { name: "preserves dynamic keys", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (result.success) consume(result.data[key]);" },
    { name: "does not use a failed result as a successful payload", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (!result.success) consume(result.data.id);" },
    { name: "rejects mutation through an original result alias", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); const alias = result; result.data = changed; if (alias.success) consume(alias.data.id);" },
    { name: "rejects mutation through a data alias", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (result.success) { const data = result.data; data.id = changed; consume(data.id); }" },
    { name: "rejects escaped async producer promises", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); async function load() { const promise = Schema.safeParseAsync(raw); promise.then(mutate); const result = await promise; if (result.success) return result.data.id; }" },
    { name: "does not guess a custom schema result", code: "import { z } from './schema.js'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (result.success) consume(result.data.id);" },
  ],
  invalid: [
    { name: "reads a field in a success branch", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (result.success) consume(result.data.id);", output: null, errors: [{ messageId: "genericParser" }] },
    { name: "reads a field after an early return", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); function load(raw) { const result = Schema.safeParse(raw); if (!result.success) return null; return result.data.id; }", output: null, errors: [{ messageId: "genericParser" }] },
    { name: "reads a field in a success else branch", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (!result.success) report(result.error); else consume(result.data.id);", output: null, errors: [{ messageId: "genericParser" }] },
    { name: "reads a successful async parse", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); async function load(raw) { const result = await Schema.safeParseAsync(raw); if (!result.success) return null; return result.data.id; }", output: null, errors: [{ messageId: "genericParser" }] },
    { name: "follows a stable result alias", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); const alias = result; if (alias.success) consume(alias.data.id);", output: null, errors: [{ messageId: "genericParser" }] },
    { name: "follows stable data aliases", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (result.success) { const data = result.data; const alias = data; consume(alias.id); }", output: null, errors: [{ messageId: "genericParser" }] },
    { name: "reports one origin for several fields", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (result.success) consume(result.data.id, result.data.name);", output: null, errors: [{ messageId: "genericParser" }] },
    { name: "requires every field-alias use to validate", code: "import { z } from 'zod'; const Schema = z.record(z.string(), z.unknown()); const result = Schema.safeParse(raw); if (result.success) { const id = result.data.id; z.string().safeParse(id); consume(id); }", output: null, errors: [{ messageId: "genericParser" }] },
  ],
});
TESTER.run("no-generic-json-parser audited boundaries", rule, {
  valid: [
    { name: "preserves imported subsequent validators", code: "import { z } from 'zod'; import { IdSchema } from './contracts.js'; function load(raw: unknown) { const r = z.record(z.string(), z.unknown()).safeParse(raw); if (r.success) return IdSchema.parse(r.data.id); }" },
    { name: "preserves explicit opaque subfield forwarding", code: "import { z } from 'zod'; function load(raw: unknown): unknown { const r = z.record(z.string(), z.unknown()).safeParse(raw); if (!r.success) return; return r.data.payload; }" },
    { name: "preserves union-valued dictionaries", code: "import { z } from 'zod'; function load(raw: unknown) { return z.record(z.string(), z.union([z.string(), z.number()])).parse(raw).id; }" },
    { name: "preserves custom value schema contracts", code: "import { z } from 'zod'; function load(raw: unknown) { return z.record(z.string(), z.custom<{ id: string }>()).parse(raw).entry; }" },
    { name: "preserves imported record value contracts", code: "import { z } from 'zod'; import { EntrySchema } from './contracts.js'; function load(raw: unknown) { return z.record(z.string(), EntrySchema).parse(raw).entry; }" },
    { name: "preserves observed schema method replacement", code: "import { z } from 'zod'; const Raw = z.record(z.string(), z.unknown()); Raw.safeParse = custom; function load(raw: unknown) { const r = Raw.safeParse(raw); if (r.success) return r.data.id; }" },
    { name: "preserves schema alias method replacement", code: "import { z } from 'zod'; const Raw = z.record(z.string(), z.unknown()); const Alias = Raw; Alias.parse = custom; function load(raw: unknown) { return Raw.parse(raw).id; }" },
    { name: "preserves escaped schema identity", code: "import { z } from 'zod'; const Raw = z.record(z.string(), z.unknown()); mutate(Raw); function load(raw: unknown) { return Raw.parse(raw).id; }" },
    { name: "preserves destructured result writes", code: "import { z } from 'zod'; function load(raw: unknown) { const r = z.record(z.string(), z.unknown()).safeParse(raw); ({ success: r.success } = replacement); if (r.success) return r.data.id; }" },
  ],
  invalid: [
    { name: "does not treat a second open parser as a specific validator", code: "import { z } from 'zod'; function load(raw: unknown) { const r = z.record(z.string(), z.unknown()).safeParse(raw); if (r.success) return z.unknown().parse(r.data.id); }", output: null, errors: [{ messageId: "genericParser" }] },
  ],
});

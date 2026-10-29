// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_GENERIC_JSON_PARSER_DOCUMENTATION } from "../../src/rules/no-generic-json-parser.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser } });

TESTER.run("no-generic-json-parser", rule, {
  valid: [
    NO_GENERIC_JSON_PARSER_DOCUMENTATION.examples[1].files[0].source,
    { name: "opaque JSON forwarding", code: "import { z } from 'zod'; function load(raw) { return z.json().parse(raw); }" },
    { name: "Promise chaining is not a payload field read", code: "import { z } from 'zod'; z.json().parseAsync(raw).then(forward);" },
    { name: "dynamic dictionary index", code: "import { z } from 'zod'; const body = z.record(z.string(), z.string()).parse(raw); consume(body[key]);" },
    { name: "custom parser namespace", code: "import { z } from './parser.js'; const body = z.json().parse(raw); consume(body.version);" },
    { name: "shadowed import", code: "import { z } from 'zod'; function f(z) { return z.json().parse(raw).version; }" },
    { name: "custom refining schema", code: "import { z } from 'zod'; const Schema = z.unknown().transform(decode); const body = Schema.parse(raw); consume(body.version);" },
    { name: "type-only import", code: "import type { z } from 'zod'; const body = z.json().parse(raw); consume(body.version);" },
    { name: "mutable alias is unresolved", code: "import { z } from 'zod'; let body = z.json().parse(raw); body = validated; consume(body.version);" },
    { name: "generated artifact", filename: "src/generated/parser.ts", code: NO_GENERIC_JSON_PARSER_DOCUMENTATION.examples[0].files[0].source },
    { name: "local suppression", code: "import { z } from 'zod';\n// eslint-disable-next-line @rule-tester/no-generic-json-parser -- compatibility parser has a separate contract\nconst body = z.record(z.string(), z.unknown()).parse(raw); consume(body.version);" },
  ],
  invalid: [
    { code: NO_GENERIC_JSON_PARSER_DOCUMENTATION.examples[0].files[0].source, errors: [{ messageId: "genericParser" }] },
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

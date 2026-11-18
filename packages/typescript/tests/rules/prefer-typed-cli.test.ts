// vitest: shared-module-graph
import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/prefer-typed-cli.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { ruleTester } from "./_tester.js";

ruleTester().run("prefer-typed-cli", rule, {
  valid: [
  "const result = JSON.parse(process.argv[2], (_key, value) => value);",
  "const result = Schema.parse(process.argv[2], options);",

  "const result = Schema.parse(process.argv.includes(\"--dry\"));",
  "const result = Schema.safeParse(process.argv.indexOf(\"--dry\"));",
  "const result = Schema.parseAsync(process.argv[2]);",

  "const z = fake; z.string().parse(process.argv[2]);",
  "import { z } from 'zod'; z.string = replaced; z.string().parse(process.argv[2]);",
  "import { z } from 'zod'; configure(z); z.string().parse(process.argv[2]);",
  "const Schema = opaque; Schema.parse(process.argv[2]);",
  "import { z } from 'zod'; const Metadata = z.record(z.string(), z.string()); const arg = z.string().min(1).parse(process.argv[2]);",

  "import { z } from 'zod'; const response = z.string().min(1).parse(process.argv[2]);",
  "import * as schema from 'zod/v4'; schema.string().max(10).safeParse(process.argv.at(2));",
  "import { string as text } from 'zod'; text().parse(process.argv[2]);",
  "const payload = JSON.parse(process.argv[2]);",
  "const payload = JSON.parse(process.argv[2] ?? readStdin());",
  "import { z } from 'zod'; const value = z.string().parse(process.argv[2] || 'fallback');",

  "import { defineCommand, runMain } from 'citty'; runMain(defineCommand({ args: { service: { type: 'positional', required: true } }, run({ args }) { deploy(args.service); } }));",
  "console.log(process.argv[0], process.argv[1]);",
  "import { parseArgs } from 'node:util'; const parsed = parseArgs({ args: process.argv.slice(2), options: { dry: { type: 'boolean' } } }); consume(parsed.values.dry);",
  "forward(process.argv.slice(2));",
  "function run(process: { argv: string[] }) { consume(process.argv[2]); }",
  "import process from './process.js'; consume(process.argv[2]);",
  "const args = values.slice(2); consume(args[0]);",
  "const args = process.argv.slice(2); let changed = args; changed = other; consume(changed[0]);",
  "process.argv = configured; consume(process.argv[2]);",
  "const args = process.argv; consume(args[index]);",
  "consume(process.argv.includes(\"README\"));",
  "globalThis.process.argv = ['node', 'script', 'internal']; consume(process.argv[2]);",
  "Object.defineProperty(globalThis, 'process', { value: configured }); consume(process.argv[2]);",
  "import { argv } from 'node:process'; argv[2] = 'internal'; consume(argv[2]);",
  "const args = process.argv.slice(2); args[0] = 'internal'; consume(args[0]);",
  "const args = process.argv.slice(2); configure(args); consume(args[0]);",
  "const args = process.argv.slice(2); args.shift(); consume(args[0]);",
  "import { argv } from 'node:process'; Object.defineProperty(argv, '2', { value: 'internal' }); consume(argv[2]);"
],
  invalid: [
  { code: "Schema.parse('input', process.argv[2]);", errors: [{ messageId: "preferTypedCli" }] },

  {
    "code": "deploy(process.argv[2]);",
    "errors": [
      {
        "messageId": "preferTypedCli"
      }
    ]
  },
  {
    "code": "const args = process.argv.slice(2); deploy(args[0]);",
    "errors": [
      {
        "messageId": "preferTypedCli"
      }
    ]
  },
  {
    "code": "import { argv as argumentsList } from 'node:process'; deploy(argumentsList[2]);",
    "errors": [
      {
        "messageId": "preferTypedCli"
      }
    ]
  },
  {
    "code": "import runtime from 'node:process'; deploy(runtime.argv[3]);",
    "errors": [
      {
        "messageId": "preferTypedCli"
      }
    ]
  },
  {
    "code": "const args = process.argv.slice(2); const forwarded = args; consume(forwarded.at(0));",
    "errors": [
      {
        "messageId": "preferTypedCli"
      }
    ]
  },
  {
    "code": "consume(process.argv.includes(\"--dry-run\"));",
    "errors": [
      {
        "messageId": "preferTypedCli"
      }
    ]
  },
  {
    "code": "const args = process.argv; consume(args.indexOf(\"-v\"));",
    "errors": [
      {
        "messageId": "preferTypedCli"
      }
    ]
  },
  { code: "import { z } from 'zod'; z.string().parse(process.argv[2]); use(process.argv[3]);", errors: [{ messageId: "preferTypedCli" }] },

],
});

it("executes the documented examples", async () => {
  await expect(verifyRuleExamples(RULES["prefer-typed-cli"])).resolves.toBeGreaterThan(0);
});

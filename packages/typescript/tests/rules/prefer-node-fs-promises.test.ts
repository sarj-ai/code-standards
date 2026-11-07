// vitest: shared-module-graph
import rule from "../../src/rules/prefer-node-fs-promises.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("prefer-node-fs-promises", rule, {
  valid: [
    { name: "does not inherit fs identity through a second var initializer", code: "var fs = require('node:fs'); var fs = custom; fs.readFileSync('x');" },
    { name: "does not treat reassigned namespace as fs", code: "let fs = require('node:fs'); fs = custom; fs.readFileSync('x');" },
    { name: "accounts for later namespace writes before visiting an earlier use", code: "let fs = require('node:fs'); function read() { return fs.readFileSync('x'); } fs = custom;" },
    { name: "does not propagate an alias from a reassigned namespace", code: "let fs = require('node:fs'); const alias = fs; alias.readFileSync('x'); fs = custom;" },
    { name: "does not inherit an imported namespace through shadowing", code: "import fs from 'node:fs'; function run(fs) { return fs.readFileSync(); }" },
    { name: "does not inherit a loaded namespace through shadowing", code: "const fs = require('node:fs'); function run(fs) { return fs.readFileSync(); }" },
    { name: "does not treat injected require as a Node loader", code: "function run(require) { const fs = require('node:fs'); return fs.readFileSync(); }" },
    { name: "does not treat injected process as a Node loader", code: "function run(process) { const fs = process.getBuiltinModule('node:fs'); return fs.readFileSync(); }" },
    "import { readFile } from 'node:fs/promises'; export async function load(path: string) { return readFile(path, 'utf8'); }",
    "import { createReadStream } from 'node:fs'; createReadStream('x');",
    "import * as fs from 'node:fs'; fs.createReadStream('x');",
    "const fs = require('node:fs'); fs.createReadStream('x');",
    "const { createReadStream } = process.getBuiltinModule('fs'); createReadStream('x');",
    "const fs = await import('node:fs'); fs.createReadStream('x');",
    "const fs = custom; fs.readFileSync('x');",
    { filename: "src/store.test.ts", code: "import { readFileSync } from 'node:fs'; readFileSync('x');" },
    { filename: "src/store.test.ts", code: "const fs = require('node:fs'); fs.readFileSync('x');" },
    { filename: "src/generated/store.ts", code: "import { readFileSync } from 'node:fs'; readFileSync('x');" },
    { filename: "src/generated/store.ts", code: "(await import('node:fs')).readFileSync('x');" },
    { filename: "src/rules/check-files.ts", code: "import { readFileSync } from 'node:fs'; readFileSync('x');" },
  ],
  invalid: [
    { name: "reports a sync import under eslint-disable-next-line (valid under ESLint; Oxlint's RuleTester ignores disable directives)", code: "// eslint-disable-next-line @rule-tester/prefer-node-fs-promises -- synchronous transaction boundary\nimport { readFileSync, writeFileSync } from 'node:fs';", errors: [{ messageId: "preferAsyncFs", data: { name: "readFileSync, writeFileSync" } }] },
    { name: "retains a native fs binding through a bare var redeclaration", code: "var fs = require('node:fs'); var fs; fs.readFileSync('x');", errors: [{ messageId: "preferAsyncFs", data: { name: "readFileSync" } }] },
    {
      code: "import { readFileSync } from 'node:fs'; export function load(path: string) { return readFileSync(path, 'utf8'); }",
      errors: [{ messageId: "preferAsyncFs", data: { name: "readFileSync" } }],
    },
    {
      code: "import { writeFileSync as write } from 'fs'; write('x', 'y');",
      errors: [{ messageId: "preferAsyncFs", data: { name: "writeFileSync" } }],
    },
    {
      code: "import { readFileSync, writeFileSync } from 'node:fs';",
      errors: [
        {
          messageId: "preferAsyncFs",
          data: { name: "readFileSync, writeFileSync" },
        },
      ],
    },
    {
      code: "import * as fs from 'node:fs'; fs.readFileSync('x'); fs['writeFileSync']('x', 'y');",
      errors: [
        { messageId: "preferAsyncFs", data: { name: "readFileSync" } },
        { messageId: "preferAsyncFs", data: { name: "writeFileSync" } },
      ],
    },
    {
      code: "const fs = require('node:fs'); fs.readFileSync('x'); fs['writeFileSync']('x', 'y');",
      errors: [
        { messageId: "preferAsyncFs", data: { name: "readFileSync" } },
        { messageId: "preferAsyncFs", data: { name: "writeFileSync" } },
      ],
    },
    {
      code: "const fs = require('node:fs'); const alias = fs; const { readFileSync } = alias;",
      errors: [{ messageId: "preferAsyncFs", data: { name: "readFileSync" } }],
    },
    {
      code: "const { readFileSync: read, writeFileSync } = require('fs');",
      errors: [{ messageId: "preferAsyncFs", data: { name: "readFileSync, writeFileSync" } }],
    },
    {
      code: "const fs = process.getBuiltinModule('node:fs'); fs.readFileSync('x');",
      errors: [{ messageId: "preferAsyncFs", data: { name: "readFileSync" } }],
    },
    {
      code: "process.getBuiltinModule('fs').writeFileSync('x', 'y');",
      errors: [{ messageId: "preferAsyncFs", data: { name: "writeFileSync" } }],
    },
    {
      code: "const { readFileSync } = await import('node:fs');",
      errors: [{ messageId: "preferAsyncFs", data: { name: "readFileSync" } }],
    },
    {
      code: "(await import('fs')).readFileSync('x');",
      errors: [{ messageId: "preferAsyncFs", data: { name: "readFileSync" } }],
    },
  ],
});

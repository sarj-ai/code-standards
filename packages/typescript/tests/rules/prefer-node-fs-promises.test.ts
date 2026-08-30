import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_NODE_FS_PROMISES_DOCUMENTATION } from "../../src/rules/prefer-node-fs-promises.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, sourceType: "module" } });

RULE_TESTER.run("prefer-node-fs-promises", rule, {
  valid: [
    PREFER_NODE_FS_PROMISES_DOCUMENTATION.examples[0].files[0].source,
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
    "// eslint-disable-next-line @rule-tester/prefer-node-fs-promises -- synchronous transaction boundary\nimport { readFileSync, writeFileSync } from 'node:fs';",
  ],
  invalid: [
    {
      code: PREFER_NODE_FS_PROMISES_DOCUMENTATION.examples[1].files[0].source,
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

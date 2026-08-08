import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { noStorageInStatelessModulesDocumentation } from "../../src/rules/no-storage-in-stateless-modules.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const STATELESS_MODULE_FILENAME = "/repo/src/engineer-digest/post.ts";
const STATELESS_MODULE_OPTIONS = [
  { modules: ["[\\\\/]engineer-digest[\\\\/]"] },
];

ruleTester.run("no-storage-in-stateless-modules", rule, {
  valid: [
    { name: "accepts the documented system-of-record read", filename: noStorageInStatelessModulesDocumentation.examples[0].focusPath, code: noStorageInStatelessModulesDocumentation.examples[0].files[0].source, options: STATELESS_MODULE_OPTIONS },
    {
      name: "allows prepare until a stateless module is configured",
      code: "db.prepare('select 1');",
      filename: STATELESS_MODULE_FILENAME,
    },
    {
      name: "allows put until a stateless module is configured",
      code: "kv.put(key, value);",
      filename: STATELESS_MODULE_FILENAME,
    },
    {
      name: "allows getWithMetadata until a stateless module is configured",
      code: "kv.getWithMetadata(key);",
      filename: STATELESS_MODULE_FILENAME,
    },
    {
      name: "treats an empty modules list as disabled",
      code: "kv.put(key, value);",
      filename: STATELESS_MODULE_FILENAME,
      options: [{ modules: [] }],
    },
    {
      name: "allows storage outside configured stateless module paths",
      code: "db.prepare('select 1'); kv.put(k, v);",
      filename: "/repo/src/referral-tracker/store.ts",
      options: STATELESS_MODULE_OPTIONS,
    },
    {
      name: "allows reads against a system of record",
      code: "const issues = await linear.listIssues();",
      filename: STATELESS_MODULE_FILENAME,
      options: STATELESS_MODULE_OPTIONS,
    },
    {
      name: "allows one-argument put calls that are unlikely to be KV writes",
      code: "queue.put(job);",
      filename: STATELESS_MODULE_FILENAME,
      options: STATELESS_MODULE_OPTIONS,
    },
    {
      name: "allows computed method names that cannot be resolved statically",
      code: "store['put'](k, v);",
      filename: STATELESS_MODULE_FILENAME,
      options: STATELESS_MODULE_OPTIONS,
    },
    {
      name: "allows method names outside the configured storage set",
      code: "map.set(k, v);",
      filename: STATELESS_MODULE_FILENAME,
      options: STATELESS_MODULE_OPTIONS,
    },
    {
      name: "replaces default storage methods when methods is configured",
      code: "kv.put(k, v);",
      filename: STATELESS_MODULE_FILENAME,
      options: [
        { modules: ["[\\\\/]engineer-digest[\\\\/]"], methods: ["prepare"] },
      ],
    },
    {
      name: "skips malformed module patterns",
      code: "kv.put(k, v);",
      filename: STATELESS_MODULE_FILENAME,
      options: [{ modules: ["([unterminated"] }],
    },
  ],
  invalid: [
    { name: "reports the documented private storage", filename: noStorageInStatelessModulesDocumentation.examples[1].focusPath, code: noStorageInStatelessModulesDocumentation.examples[1].files[0].source, options: STATELESS_MODULE_OPTIONS, errors: [{ messageId: "storageInStatelessModule" }] },
    {
      name: "reports SQL prepare inside a configured stateless module",
      code: "const row = db.prepare('select * from digest_state').first();",
      filename: STATELESS_MODULE_FILENAME,
      options: STATELESS_MODULE_OPTIONS,
      errors: [{ messageId: "storageInStatelessModule" }],
    },
    {
      name: "reports KV put inside a configured stateless module",
      code: "await kv.put('digest:last', ts);",
      filename: STATELESS_MODULE_FILENAME,
      options: STATELESS_MODULE_OPTIONS,
      errors: [{ messageId: "storageInStatelessModule" }],
    },
    {
      name: "reports KV getWithMetadata inside a configured stateless module",
      code: "const cached = await kv.getWithMetadata('digest:last');",
      filename: STATELESS_MODULE_FILENAME,
      options: STATELESS_MODULE_OPTIONS,
      errors: [{ messageId: "storageInStatelessModule" }],
    },
    {
      name: "reports each storage access in the same stateless module",
      code: "await kv.put(a, b); const r = db.prepare(q);",
      filename: STATELESS_MODULE_FILENAME,
      options: STATELESS_MODULE_OPTIONS,
      errors: [
        { messageId: "storageInStatelessModule" },
        { messageId: "storageInStatelessModule" },
      ],
    },
    {
      name: "matches every configured stateless module pattern",
      code: "await kv.put(a, b);",
      filename: "/repo/src/weekly-digest/post.ts",
      options: [
        {
          modules: [
            "[\\\\/]engineer-digest[\\\\/]",
            "[\\\\/]weekly-digest[\\\\/]",
          ],
        },
      ],
      errors: [{ messageId: "storageInStatelessModule" }],
    },
    {
      name: "reports a custom configured storage method",
      code: "await store.write(k, v);",
      filename: STATELESS_MODULE_FILENAME,
      options: [
        { modules: ["[\\\\/]engineer-digest[\\\\/]"], methods: ["write"] },
      ],
      errors: [{ messageId: "storageInStatelessModule" }],
    },
  ],
});

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-storage-in-stateless-modules.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

/** A file inside a module the consumer declared stateless. */
const DIGEST = "/repo/src/engineer-digest/post.ts";
/** The option that declares it. */
const SCOPED = [{ modules: ["[\\\\/]engineer-digest[\\\\/]"] }];

ruleTester.run("no-storage-in-stateless-modules", rule, {
  valid: [
    // --- Opt-in: a no-op until `modules` is configured ----------------------
    // This is the shared-preset default. Without it the rule would fire on
    // every `.put()` in every repo.
    { code: "db.prepare('select 1');", filename: DIGEST },
    { code: "kv.put(key, value);", filename: DIGEST },
    { code: "kv.getWithMetadata(key);", filename: DIGEST },
    { code: "kv.put(key, value);", filename: DIGEST, options: [{ modules: [] }] },

    // --- Configured, but the file is outside the declared modules -----------
    {
      code: "db.prepare('select 1'); kv.put(k, v);",
      filename: "/repo/src/referral-tracker/store.ts",
      options: SCOPED,
    },

    // --- Configured and in scope, but not storage access --------------------
    // Reads against the systems of record are exactly what we want instead.
    {
      code: "const issues = await linear.listIssues();",
      filename: DIGEST,
      options: SCOPED,
    },
    // A one-argument `put` is more often a builder/queue helper than a KV write.
    { code: "queue.put(job);", filename: DIGEST, options: SCOPED },
    // A computed method name we cannot resolve statically.
    { code: "store['put'](k, v);", filename: DIGEST, options: SCOPED },
    // A method outside the configured set.
    {
      code: "map.set(k, v);",
      filename: DIGEST,
      options: SCOPED,
    },
    // `methods` replaces the defaults, so `put` is no longer watched.
    {
      code: "kv.put(k, v);",
      filename: DIGEST,
      options: [
        { modules: ["[\\\\/]engineer-digest[\\\\/]"], methods: ["prepare"] },
      ],
    },
    // A malformed pattern is skipped rather than throwing; nothing matches, so
    // the rule stays silent.
    {
      code: "kv.put(k, v);",
      filename: DIGEST,
      options: [{ modules: ["([unterminated"] }],
    },
  ],
  invalid: [
    // SQL inside a module declared stateless.
    {
      code: "const row = db.prepare('select * from digest_state').first();",
      filename: DIGEST,
      options: SCOPED,
      errors: [{ messageId: "storageInStatelessModule" }],
    },
    // KV write.
    {
      code: "await kv.put('digest:last', ts);",
      filename: DIGEST,
      options: SCOPED,
      errors: [{ messageId: "storageInStatelessModule" }],
    },
    // KV read.
    {
      code: "const cached = await kv.getWithMetadata('digest:last');",
      filename: DIGEST,
      options: SCOPED,
      errors: [{ messageId: "storageInStatelessModule" }],
    },
    // Several accesses in one file are each reported.
    {
      code: "await kv.put(a, b); const r = db.prepare(q);",
      filename: DIGEST,
      options: SCOPED,
      errors: [
        { messageId: "storageInStatelessModule" },
        { messageId: "storageInStatelessModule" },
      ],
    },
    // A second declared module in the same option list.
    {
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
    // A custom `methods` entry.
    {
      code: "await store.write(k, v);",
      filename: DIGEST,
      options: [
        { modules: ["[\\\\/]engineer-digest[\\\\/]"], methods: ["write"] },
      ],
      errors: [{ messageId: "storageInStatelessModule" }],
    },
  ],
});

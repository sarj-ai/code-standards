import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_NODE_CRYPTO_HASH_DOCUMENTATION } from "../../src/rules/prefer-node-crypto-hash.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, sourceType: "module" } });

RULE_TESTER.run("prefer-node-crypto-hash", rule, {
  valid: [
    PREFER_NODE_CRYPTO_HASH_DOCUMENTATION.examples[0].files[0].source,
    "import { createHash } from 'node:crypto'; const digest = createHash('sha256').update(first).update(second).digest('hex');",
    "import { createHash } from 'node:crypto'; const stream = createHash('sha256'); stream.write(value);",
    "import { createHash } from 'legacy-crypto'; createHash('sha256').update(value).digest('hex');",
  ],
  invalid: [
    {
      code: PREFER_NODE_CRYPTO_HASH_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "import * as crypto from 'node:crypto'; crypto.createHash('sha512').update(value).digest();",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "import { createHash as makeHash } from 'node:crypto'; makeHash('sha256').update(value).digest('base64');",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
  ],
});

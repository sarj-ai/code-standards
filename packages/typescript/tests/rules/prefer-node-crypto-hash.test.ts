// vitest: shared-module-graph
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
    { name: "keeps non-const namespace loads outside the proof boundary", code: 'var crypto = require("node:crypto"); var crypto; crypto.createHash("sha256").update(value).digest("hex");' },
    { name: "keeps a replaced native module member's custom contract", code: PREFER_NODE_CRYPTO_HASH_DOCUMENTATION.examples[3].files[0].source },
    { name: "keeps replacement through an erased namespace wrapper", code: 'const crypto = require("node:crypto"); (crypto as Custom).createHash = custom; crypto.createHash("sha256").update(value).digest("hex");' },
    { name: "keeps a namespace that escapes through an alias", code: 'const crypto = require("node:crypto"); const alias = crypto; alias.createHash = custom; crypto.createHash("sha256").update(value).digest("hex");' },
    { name: "keeps namespace mutations through Object.assign", code: 'const crypto = require("node:crypto"); Object.assign(crypto, { createHash: custom }); crypto.createHash("sha256").update(value).digest("hex");' },
    { name: "keeps replacement through an inherited getter mutator", code: 'const crypto = require("node:crypto"); crypto["__defineGetter__"]("createHash", () => custom); crypto.createHash("sha256").update(value).digest("hex");' },
    { name: "keeps replacement through an inherited setter mutator", code: 'const crypto = require("node:crypto"); crypto.__defineSetter__("createHash", custom); crypto.createHash("sha256").update(value).digest("hex");' },
    { name: "keeps aliases returned by the inherited valueOf method", code: 'const crypto = require("node:crypto"); const alias = crypto.valueOf(); alias.createHash = custom; crypto.createHash("sha256").update(value).digest("hex");' },
    { name: "keeps directly exported namespace declarations", code: 'export const crypto = process.getBuiltinModule("node:crypto"); export function digest(value: string) { return crypto.createHash("sha256").update(value).digest("hex"); }' },
    { name: "keeps namespace exports through specifiers", code: 'const crypto = require("node:crypto"); export { crypto }; export function digest(value: string) { return crypto.createHash("sha256").update(value).digest("hex"); }' },
    { name: "keeps destructuring writes to a module member", code: 'const crypto = require("node:crypto"); ({ factory: crypto.createHash } = replacements); crypto.createHash("sha256").update(value).digest("hex");' },
    { name: "keeps interpolated algorithms opaque", code: 'import { createHash } from "node:crypto"; createHash(`sha${size}`).update(value).digest("hex");' },
    { name: "keeps incremental hashing with a literal template algorithm", code: 'import { createHash } from "node:crypto"; createHash(`sha256`).update(first).update(second).digest("hex");' },
    { name: "keeps shadowed constructors outside native provenance", code: 'import { createHash } from "node:crypto"; function digest(createHash) { return createHash(("sha256" as const)).update(value).digest("hex"); }' },

    PREFER_NODE_CRYPTO_HASH_DOCUMENTATION.examples[0].files[0].source,
    "import { createHash } from 'node:crypto'; const digest = createHash('sha256').update(first).update(second).digest('hex');",
    "import { createHash } from 'node:crypto'; const stream = createHash('sha256'); stream.write(value);",
    "import { createHash } from 'node:crypto'; createHash(algorithm).update(value).digest('hex');",
    "import { createHash } from 'legacy-crypto'; createHash('sha256').update(value).digest('hex');",
    "const crypto = require(source); crypto.createHash('sha256').update(value).digest('hex');",
    "let crypto = require('node:crypto'); crypto.createHash('sha256').update(value).digest('hex');",
    "const crypto = custom; crypto.createHash('sha256').update(value).digest('hex');",
    "const crypto = require('@vendor/crypto'); crypto.createHash('sha256').update(value).digest('hex');",
    "function require(name: string) { return custom(name); } const crypto = require('node:crypto'); crypto.createHash('sha256').update(value).digest('hex');",
    "const process = custom; const crypto = process.getBuiltinModule('node:crypto'); crypto.createHash('sha256').update(value).digest('hex');",
    "import { createHash } from 'node:crypto'; function digest(createHash: Factory) { return createHash('sha256').update(value).digest('hex'); }",
    "import * as crypto from 'node:crypto'; function digest(crypto: Crypto) { return crypto.createHash('sha256').update(value).digest('hex'); }",
    "const crypto = require('node:crypto'); crypto[method]('sha256').update(value).digest('hex');",
  ],
  invalid: [
    { name: "retains separate type-space declarations", code: 'const crypto = require("node:crypto"); interface crypto { metadata: string } crypto.createHash("sha256").update(value).digest("hex");', errors: [{ messageId: "preferNodeCryptoHash" }] },
    { name: "retains an unchanged native namespace", code: PREFER_NODE_CRYPTO_HASH_DOCUMENTATION.examples[2].files[0].source, errors: [{ messageId: "preferNodeCryptoHash" }] },
    { name: "retains a namespace with other native method calls", code: 'const crypto = require("node:crypto"); const value = crypto.randomBytes(16); crypto.createHash("sha256").update(value).digest("hex");', errors: [{ messageId: "preferNodeCryptoHash" }] },
    { name: "retains harmless inherited inspection calls", code: 'const crypto = require("node:crypto"); crypto.hasOwnProperty("createHash"); crypto.createHash("sha256").update(value).digest("hex");', errors: [{ messageId: "preferNodeCryptoHash" }] },
    { name: "retains type-only namespace references", code: 'import * as crypto from "node:crypto"; type Crypto = typeof crypto; crypto.createHash("sha256").update(value).digest("hex");', errors: [{ messageId: "preferNodeCryptoHash" }] },
    { name: "retains qualified type-only namespace references", code: 'import * as crypto from "node:crypto"; type Factory = typeof crypto.createHash; crypto.createHash("sha256").update(value).digest("hex");', errors: [{ messageId: "preferNodeCryptoHash" }] },
    { name: "retains nested qualified type-only namespace references", code: 'import * as crypto from "node:crypto"; type Constants = typeof crypto.constants.defaultCoreCipherList; crypto.createHash("sha256").update(value).digest("hex");', errors: [{ messageId: "preferNodeCryptoHash" }] },
    { name: "retains a no-substitution template algorithm", code: 'import { createHash } from "node:crypto"; createHash(`sha256`).update(value).digest(`hex`);', errors: [{ messageId: "preferNodeCryptoHash" }] },
    { name: "retains a literal algorithm through a const assertion", code: 'import { createHash } from "node:crypto"; createHash(("sha256" as const)).update(value).digest(("hex" as const));', errors: [{ messageId: "preferNodeCryptoHash" }] },

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
    {
      code: "import { createHash } from 'crypto'; createHash('sha256')['update'](value)['digest']('hex');",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "import crypto from 'node:crypto'; crypto['createHash']('sha256').update(value).digest('hex');",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "const crypto = require('node:crypto'); crypto.createHash('sha256').update(value).digest('hex');",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "const { createHash: makeHash } = require('crypto'); makeHash('sha256').update(value).digest();",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "const { 'createHash': makeHash } = require('node:crypto'); makeHash('sha256').update(value).digest('hex');",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "require('crypto')['createHash']('sha256')['update'](value)['digest']('base64');",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "const crypto = process.getBuiltinModule('node:crypto'); crypto.createHash('sha256').update(value).digest('hex');",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "const { createHash } = process['getBuiltinModule']('crypto'); createHash('sha256').update(value).digest('hex');",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "process.getBuiltinModule('crypto').createHash('sha256').update(value).digest('hex');",
      errors: [{ messageId: "preferNodeCryptoHash" }],
    },
    {
      code: "const crypto = require('crypto'); crypto.createHash('sha256').update(first).digest('hex'); crypto['createHash']('sha512')['update'](second)['digest']('hex');",
      errors: [
        { messageId: "preferNodeCryptoHash" },
        { messageId: "preferNodeCryptoHash" },
      ],
    },
  ],
});

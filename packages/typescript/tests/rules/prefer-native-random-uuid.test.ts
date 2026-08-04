import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-native-random-uuid.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tsParser },
});

ruleTester.run("prefer-native-random-uuid", rule, {
  valid: [
    { code: 'import { v4 } from "other"; v4();' },
    { code: 'import { v1 } from "uuid"; v1();' },
    { code: 'import { v4 } from "uuid"; v4({ random: bytes });' },
    { code: 'import { v4 } from "uuid"; consume(v4);' },
    { code: 'export { v4 } from "uuid";' },
    { code: 'const uuid = require(name); uuid.v4();' },
    { code: 'let uuid = require("uuid"); uuid.v4();' },
    { code: 'const { v7 } = require("uuid"); v7();' },
    { code: 'const { v4 } = require("other"); v4();' },
    {
      code: 'function load(require: (name: string) => { v4(): string }) { const uuid = require("uuid"); return uuid.v4(); }',
    },
    { code: 'uuid.v4();' },
    { code: 'globalThis.crypto.randomUUID();' },
    {
      code: 'import { v4 as makeId } from "uuid"; function f(makeId: () => string) { return makeId(); }',
    },
  ],
  invalid: [
    {
      code: 'import { v4 } from "uuid"; v4();',
      output: null,
      errors: [
        {
          messageId: "preferNative",
          suggestions: [
            {
              messageId: "replaceWithNative",
              output:
                'import { v4 } from "uuid"; globalThis.crypto.randomUUID();',
            },
          ],
        },
      ],
    },
    {
      code: 'import { v4 as makeId } from "uuid"; makeId();',
      output: null,
      errors: [
        {
          messageId: "preferNative",
          suggestions: [
            {
              messageId: "replaceWithNative",
              output:
                'import { v4 as makeId } from "uuid"; globalThis.crypto.randomUUID();',
            },
          ],
        },
      ],
    },
    {
      code: 'import * as uuid from "uuid"; uuid.v4();',
      output: null,
      errors: [
        {
          messageId: "preferNative",
          suggestions: [
            {
              messageId: "replaceWithNative",
              output:
                'import * as uuid from "uuid"; globalThis.crypto.randomUUID();',
            },
          ],
        },
      ],
    },
    {
      code: 'const { v4: makeId } = require("uuid"); makeId();',
      output: null,
      errors: [
        {
          messageId: "preferNative",
          suggestions: [
            {
              messageId: "replaceWithNative",
              output:
                'const { v4: makeId } = require("uuid"); globalThis.crypto.randomUUID();',
            },
          ],
        },
      ],
    },
    {
      code: 'const uuid = require("uuid"); uuid.v4();',
      output: null,
      errors: [
        {
          messageId: "preferNative",
          suggestions: [
            {
              messageId: "replaceWithNative",
              output:
                'const uuid = require("uuid"); globalThis.crypto.randomUUID();',
            },
          ],
        },
      ],
    },
    {
      code: 'const uuid = require("uuid"); uuid.v4();',
      languageOptions: { globals: { require: "readonly" } },
      output: null,
      errors: [
        {
          messageId: "preferNative",
          suggestions: [
            {
              messageId: "replaceWithNative",
              output:
                'const uuid = require("uuid"); globalThis.crypto.randomUUID();',
            },
          ],
        },
      ],
    },
  ],
});

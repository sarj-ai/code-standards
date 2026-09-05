import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_RESTATED_JSDOC_DOCUMENTATION } from "../../src/rules/no-restated-jsdoc.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("no-restated-jsdoc", rule, {
  valid: [
    { name: "preserves unary negation", code: "/** Returns !value. */\nfunction invertValue(value: boolean) { return !value; }" },
    { name: "preserves subtraction", code: "/** Return x - y. */\nfunction subtract(x: number, y: number) { return x - y; }" },
    { name: "preserves bitwise exclusive or", code: "/** Return x ^ y. */\nfunction combine(x: number, y: number) { return x ^ y; }" },
    { name: "preserves a relation between signature parameters", code: "/** Return x < y. */\nfunction compare(x: number, y: number) { return x < y; }" },
    { name: "preserves nested parameter shape documentation", code: "/** @param config.secret */\nfunction useConfig(config) { return config; }" },
    { name: "preserves optional parameter documentation", code: "/** @param [config] */\nfunction useConfig(config) { return config; }" },
    { name: "preserves asynchronous behavior tags", code: "/** Read user.\n * @async\n */\nfunction readUser() { return user; }" },
    { name: "preserves a one-letter value absent from the signature", code: "/** Returns x. */\nexport function getY(y: number) { return y; }" },
    { name: "preserves an optional parameter default", code: "/** @param [amount=0] The amount. */\nexport function formatAmount(amount: number) { return amount; }" },
    { name: "preserves constraints also present in declaration names", code: "/** Optional user. */\nexport interface OptionalUser {}" },
    { name: "preserves JavaScript parameter types", code: "/** @param {number} value */\nfunction convert(value) { return value; }", filename: "src/convert.js" },
    { name: "preserves JavaScript return types", code: "/** @returns {number} */\nfunction count() { return 1; }", filename: "src/count.js" },
    { name: "preserves non-Latin documentation", code: "/** يعيد المستخدم */\nfunction getUser() { return user; }" },
    { name: "preserves non-Latin details mixed with signature words", code: "/** Get user بدون تخزين */\nfunction getUser() { return user; }" },
    { name: "does not delete intervening trailing comments", code: "/** Get user. */ // Preserve audit boundary.\nfunction getUser() { return user; }" },
    { name: "preserves negation even when every remaining word repeats the signature", code: "/** Does not cache the user. */\nexport function cacheUser(user: unknown) { return user; }" },
    { name: "preserves required parameter constraints", code: "/** @param user The user is required. */\nexport function getUser(user: unknown) { return user; }" },
    { name: "preserves a return sentinel contract", code: "/** @returns false */\nexport function getUser(user: unknown) { return user; }" },
    { name: "preserves numeric behavior absent from the signature", code: "/** Get 2 users. */\nexport function getUsers() { return []; }" },
    { name: "preserves conditional behavior", code: "/** Cache the user if the user is new. */\nexport function cacheUser(user: unknown) { return user; }" },
    { name: "preserves quoted value spelling", code: "/** Returns 'user'. */\nexport function getUser() { return 'user'; }" },
    { name: "accepts the documented behavioral JSDoc", code: NO_RESTATED_JSDOC_DOCUMENTATION.examples[0].files[0].source },
    // One word the signature does not carry and the block earns its place.
    { code: "/** Get the user, bypassing the read replica. */\nexport function getUser(id: string) { return id; }" },
    // A value tag is content the signature cannot hold.
    { code: "/**\n * Formats the amount.\n * @deprecated use formatMoney\n */\nexport function formatAmount(amount: number) { return amount; }" },
    { code: "/**\n * Formats the amount.\n * @see formatMoney\n */\nexport function formatAmount(amount: number) { return amount; }" },
    { code: "/**\n * Formats the amount.\n * @throws when amount is negative\n */\nexport function formatAmount(amount: number) { return amount; }" },
    // A tag the rule does not model — it cannot judge what it cannot read.
    { code: "/**\n * Formats the amount.\n * @satisfies Formatter\n */\nexport function formatAmount(amount: number) { return amount; }" },
    // A `@param` description that adds a word of its own.
    {
      code: "/**\n * Formats the amount.\n * @param amount minor units, not major\n */\nexport function formatAmount(amount: number) { return amount; }",
    },
    {
      name: "allows a return description with information absent from the signature",
      code: "/**\n * Formats the amount.\n * @returns The amount in minor units.\n */\nexport function formatAmount(amount: number) { return amount; }",
    },
    {
      name: "keeps novel information carried by an at-description tag",
      code: "/**\n * Get the user by id.\n * @description Bypasses the read replica.\n */\nexport function getUserById(id: string) { return id; }",
    },
    {
      name: "keeps an unknown parameter tag instead of treating it as signature repetition",
      code: "/**\n * Get the user by id.\n * @param account Account.\n */\nexport function getUserById(id: string) { return id; }",
    },
    {
      name: "defers fully typed param and return sections to no-typed-doc-sections",
      code: "/** @param id The id. @returns The id. */\nexport function getUserById(id: string): string { return id; }",
    },
    // The protected class is an exemption floor.
    { code: "/** Retries the request, because the gateway 502s under load. */\nexport function retryRequest(times: number) { return times; }" },
    { code: "/** Formats the amount (PLT-812). */\nexport function formatAmount(amount: number) { return amount; }" },
    // A non-JSDoc block comment is `no-comment-cruft`'s business.
    { code: "/* get the user */\nexport function getUser(id: string) { return id; }" },
    // An empty block claims nothing.
    { code: "/** */\nexport function getUser(id: string) { return id; }" },
    // A block not attached to a declaration.
    { code: "/** Get the user by id. */\n\nconst x = 1;\nexport { x };" },
    // Generated files: 87% of the raw hits for this shape were OpenAPI codegen,
    // where the template rewrites the block on every run.
    {
      name: "ignores a generated header marker",
      code: "// @generated by openapi-generator. DO NOT EDIT.\n/** Get the user by id. */\nexport function getUserById(id: string) { return id; }",
      filename: "api.ts",
    },
    {
      name: "ignores a generated file path without a header marker",
      code: NO_RESTATED_JSDOC_DOCUMENTATION.examples[1].files[0].source,
      filename: "/repo/src/openapi-gen/api.ts",
    },
  ],
  invalid: [
    {
      name: "offers deletion as a suggestion without applying an autofix",
      code: "/** Get the user by id. */\nexport function getUserById(id: string) { return id; }",
      output: null,
      errors: [
        {
          messageId: "restatesSignature",
          suggestions: [
            {
              messageId: "deleteBlock",
              output: "export function getUserById(id: string) { return id; }",
            },
          ],
        },
      ],
    },
    {
      name: "counts a restated at-description tag as documentation text",
      code: "/** @description Get the user by id. */\nexport function getUserById(id: string) { return id; }",
      output: null,
      errors: [
        {
          messageId: "restatesSignature",
          suggestions: [
            {
              messageId: "deleteBlock",
              output: "export function getUserById(id: string) { return id; }",
            },
          ],
        },
      ],
    },
    // Description plus parroting `@param` / `@returns`.
    {
      code: "/**\n * Formats the amount.\n * @param amount The amount.\n * @returns The amount.\n */\nexport function formatAmount(amount: number) { return amount; }",
      errors: [
        {
          messageId: "restatesSignature",
          suggestions: [
            {
              messageId: "deleteBlock",
              output: "export function formatAmount(amount: number) { return amount; }",
            },
          ],
        },
      ],
    },
    // An arrow-function const.
    {
      code: "/** Logout function */\nexport const useLogout = () => logout();",
      errors: [
        {
          messageId: "restatesSignature",
          suggestions: [
            { messageId: "deleteBlock", output: "export const useLogout = () => logout();" },
          ],
        },
      ],
    },
    // A class method.
    {
      code: "class Processor {\n  /**\n   * Calculate bounds for features\n   */\n  calculateBounds(features: number[]) { return features; }\n}",
      errors: [
        {
          messageId: "restatesSignature",
          suggestions: [
            {
              messageId: "deleteBlock",
              output: "class Processor {\n  calculateBounds(features: number[]) { return features; }\n}",
            },
          ],
        },
      ],
    },
    // An interface property.
    {
      code: "export interface Options {\n  /** the fetcher function */\n  fetcher?: () => void;\n}",
      errors: [
        {
          messageId: "restatesSignature",
          suggestions: [
            { messageId: "deleteBlock", output: "export interface Options {\n  fetcher?: () => void;\n}" },
          ],
        },
      ],
    },
    // Bare `@param` tags with no description at all.
    {
      code: "/**\n * @param mutationCache\n * @param options\n */\nexport function injectMutationState(mutationCache: unknown, options: unknown) { return [mutationCache, options]; }",
      errors: [
        {
          messageId: "restatesSignature",
          suggestions: [
            {
              messageId: "deleteBlock",
              output:
                "export function injectMutationState(mutationCache: unknown, options: unknown) { return [mutationCache, options]; }",
            },
          ],
        },
      ],
    },
  ],
});

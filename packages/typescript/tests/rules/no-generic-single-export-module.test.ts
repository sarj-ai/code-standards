import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-generic-single-export-module.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tsParser, sourceType: "module" },
});

ruleTester.run("no-generic-single-export-module", rule, {
  valid: [
    { filename: "/repo/src/order-parser.ts", code: "export function parseOrder() { return {}; }" },
    { filename: "/repo/src/utils.ts", code: "export function parseOrder() { return {}; }\nexport function formatOrder() { return ''; }" },
    { filename: "/repo/src/types.ts", code: "export interface Order { id: string }" },
    { filename: "/repo/src/utils.ts", code: "export default function () { return 1; }" },
    { filename: "/repo/src/utils.ts", code: "export * from './order-parser.js';" },
    { filename: "/repo/src/index.ts", code: "export { parseOrder } from './order-parser.js';" },
    { filename: "/repo/src/utils.test.ts", code: "export function buildOrder() { return {}; }" },
    { filename: "/repo/src/generated/utils.ts", code: "export function buildOrder() { return {}; }" },
    { filename: "/repo/src/utils.ts", code: "module.exports = function buildOrder() {};" },
    { filename: "/repo/src/utils.ts", code: "Object.defineProperty(exports, 'x', { value: 1 }); export const parseOrder = () => ({});" },
    { filename: "/repo/src/utils.ts", code: "Object.assign(exports, { x: 1 }); export const parseOrder = () => ({});" },
    { filename: "/repo/src/utils.ts", code: "Object.defineProperties(exports, { x: { value: 1 } }); export const parseOrder = () => ({});" },
    { filename: "/repo/src/utils.ts", code: "module['exports'] = {}; export const parseOrder = () => ({});" },
    { filename: "/repo/src/utils.ts", code: "Object['defineProperty'](exports, 'x', { value: 1 }); export const parseOrder = () => ({});" },
    { filename: "/repo/src/lib/utils.ts", code: "export function cn(...inputs: unknown[]) { return inputs.join(' '); }" },
    { filename: "/repo/src/base.ts", code: "export class OrderBase {}" },
    { filename: "/repo/src/models.ts", code: "export class OrderModel {}" },
    { filename: "/repo/src/utils.ts", code: "export const utils = {};" },
    { filename: "/repo/src/utils.module.ts", code: "export class UtilsModule {}" },
    { filename: "/repo/src/types.ts", code: "export declare class Order {}" },
    { filename: "/repo/src/utils.ts", code: "interface Order { id: string } export { Order };" },
    { filename: "/repo/src/utils.ts", code: "type Order = { id: string }; export { Order };" },
    { filename: "/repo/src/utils.ts", code: "import type { Order } from './order.js'; export { Order };" },
    { filename: "/repo/src/utils.ts", code: "import { type Order } from './order.js'; export { Order };" },
    { filename: "/repo/src/utils.ts", code: "const enum Order { Open } export { Order };" },
    { filename: "/repo/src/utils.ts", code: "declare class Order {} export { Order };" },
    { filename: "/repo/src/utils.ts", code: "declare function parseOrder(): void; export { parseOrder };" },
    { filename: "/repo/src/utils.ts", code: "declare const orderSchema: object; export { orderSchema };" },
    { filename: "/repo/src/utils.ts", code: "declare namespace Order {} export { Order };" },
    { filename: "/repo/src/utils.ts", code: "declare enum Order { Open } export { Order };" },
    { filename: "/repo/src/utils.ts", code: "interface Order { id: string } export default Order;" },
    { filename: "/repo/src/utils.ts", code: "declare const orderSchema: object; export default orderSchema;" },
    { filename: "/repo/src/utils.ts", code: "declare function parseOrder(): void; export default parseOrder;" },
    { filename: "/repo/src/utils.ts", code: "declare class Order {} export default Order;" },
    { filename: "/repo/src/utils.ts", code: "import type { Order } from './order.js'; export default Order;" },
    {
      filename: "/repo/src/utils.ts",
      code: "const parseOrder = () => ({}); export { parseOrder, parseOrder as default };",
    },
  ],
  invalid: [
    {
      name: "runtime declaration merging wins over an interface of the same name",
      filename: "/repo/src/utils.ts",
      code: "interface Order { id: string } class Order { id = ''; } export { Order };",
      errors: [{ messageId: "genericSingleExport", data: { stem: "utils", exported: "Order", expected: "order.ts" } }],
    },
    {
      name: "reports a sole exported function in utils",
      filename: "/repo/src/utils.ts",
      code: "function normalize(value: string) { return value.trim(); }\nexport function parseOrder() { return normalize('x'); }",
      errors: [{ messageId: "genericSingleExport", data: { stem: "utils", exported: "parseOrder", expected: "parse-order.ts" } }],
    },
    {
      name: "does not mistake CommonJS words in a string for an export",
      filename: "/repo/src/utils.ts",
      code: "const note = 'module.exports and exports.build'; export function parseOrder() { return note; }",
      errors: [{ messageId: "genericSingleExport", data: { stem: "utils", exported: "parseOrder", expected: "parse-order.ts" } }],
    },
    {
      name: "does not mistake a locally shadowed exports object for CommonJS",
      filename: "/repo/src/utils.ts",
      code: "const exports = {}; exports.local = 1; export function parseOrder() { return exports; }",
      errors: [{ messageId: "genericSingleExport", data: { stem: "utils", exported: "parseOrder", expected: "parse-order.ts" } }],
    },
    {
      name: "does not mistake a locally shadowed Object helper for CommonJS",
      filename: "/repo/src/utils.ts",
      code: "const Object = { defineProperty() {} }; Object.defineProperty(exports, 'x', {}); export function parseOrder() { return {}; }",
      errors: [{ messageId: "genericSingleExport", data: { stem: "utils", exported: "parseOrder", expected: "parse-order.ts" } }],
    },
    {
      name: "reports a sole exported class in helpers",
      filename: "/repo/src/helpers.tsx",
      code: "export class OrderBuilder { build() { return {}; } }",
      errors: [{ messageId: "genericSingleExport", data: { stem: "helpers", exported: "OrderBuilder", expected: "order-builder.tsx" } }],
    },
    {
      name: "reports a sole named export specifier",
      filename: "/repo/src/common.ts",
      code: "const orderSchema = {}; export { orderSchema };",
      errors: [{ messageId: "genericSingleExport", data: { stem: "common", exported: "orderSchema", expected: "order-schema.ts" } }],
    },
    {
      name: "reports a sole runtime constant",
      filename: "/repo/src/constants.ts",
      code: "export const orderStatuses = ['open', 'closed'] as const;",
      errors: [{ messageId: "genericSingleExport", data: { stem: "constants", exported: "orderStatuses", expected: "order-statuses.ts" } }],
    },
    {
      name: "reports a named default export and preserves acronym words",
      filename: "/repo/src/utils.mts",
      code: "export default class OAuthClient {}",
      errors: [{ messageId: "genericSingleExport", data: { stem: "utils", exported: "OAuthClient", expected: "oauth-client.mts" } }],
    },
    {
      name: "preserves a conventional middle suffix",
      filename: "/repo/src/utils.server.ts",
      code: "export function parseOrder() { return {}; }",
      errors: [{ messageId: "genericSingleExport", data: { stem: "utils", exported: "parseOrder", expected: "parse-order.server.ts" } }],
    },
    {
      name: "canonicalizes a mixed-case suffix in the suggested filename",
      filename: "/repo/src/utils.graphQL.ts",
      code: "export class OrderGraphQL {}",
      errors: [{ messageId: "genericSingleExport", data: { stem: "utils", exported: "OrderGraphQL", expected: "order.graphql.ts" } }],
    },
    {
      name: "does not duplicate a suffix already carried by the export",
      filename: "/repo/src/helpers.service.ts",
      code: "export class OrderService {}",
      errors: [{ messageId: "genericSingleExport", data: { stem: "helpers", exported: "OrderService", expected: "order.service.ts" } }],
    },
    {
      name: "uses the local name of a default export specifier",
      filename: "/repo/src/utils.ts",
      code: "const parseOrder = () => ({}); export { parseOrder as default };",
      errors: [{ messageId: "genericSingleExport", data: { stem: "utils", exported: "parseOrder", expected: "parse-order.ts" } }],
    },
    {
      name: "ignores type-only reexports beside one runtime export",
      filename: "/repo/src/helpers.ts",
      code: "export type { Order } from './types.js'; export function parseOrder() { return {}; }",
      errors: [{ messageId: "genericSingleExport", data: { stem: "helpers", exported: "parseOrder", expected: "parse-order.ts" } }],
    },
  ],
});

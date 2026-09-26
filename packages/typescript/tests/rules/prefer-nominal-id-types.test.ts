import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-nominal-id-types.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("prefer-nominal-id-types", rule, {
  valid: [
    "function parse(accountIds: string | undefined, defaultAccountId: string | undefined) {}",
    "function load(accountId: string) {}",
    "function load(accountId: string, invoiceId: number) {}",
    "function load(accountId: string, accountIds: string[]) {}",
    "function load(accountId: string, account_id: string) {}",
    "function load(accountId: string, label: string) {}",
    "function load(requestId: string, traceId: string, accountId: string) {}",
    "function load(timeout_id: number, intervalId: number) {}",
    "function load(accountIds: string[], invoiceId: string) {}",
    "function load(accountIds: (string | number)[], invoiceIds: string[]) {}",
    "function load(accountId: string | number, invoiceId: string) {}",
    "type AccountId = string & { readonly brand: unique symbol }; type InvoiceId = string & { readonly brand: unique symbol }; function load(accountId: AccountId, invoiceId: InvoiceId) {}",
    "import type { AccountId, InvoiceId } from './ids'; function load(accountId: AccountId, invoiceId: InvoiceId) {}",
    "type A = B; type B = A; function load(accountId: A, invoiceId: B) {}",
    "type Id = string; function load<Id>(accountId: Id, invoiceId: Id) {}",
    "type Id = string; function outer() { type Id = { value: string }; function load(accountId: Id, invoiceId: Id) {} }",
    "type Array<T> = { value: T }; function load(accountIds: Array<string>, invoiceIds: Array<string>) {}",
    "interface Request { accountId: string; invoiceId: string }",
    "type Request = { accountId: string; invoiceId: string }",
    { filename: "src/generated/client.ts", code: "function load(accountId: string, invoiceId: string) {}" },
    { code: "// @generated\nfunction load(accountId: string, invoiceId: string) {}" },
    { code: "// eslint-disable-next-line @rule-tester/prefer-nominal-id-types -- raw wire protocol requires positional strings\nfunction load(accountId: string, invoiceId: string) {}" },
  ],
  invalid: [
    { code: "function load(accountId: string, invoiceId: string) {}", errors: [{ messageId: "preferNominalIds" }] },
    { code: "function load(accountId: string, invoiceId: string, workspaceId: string) {}", errors: [{ messageId: "preferNominalIds" }] },
    { code: "const load = (account_id: number, invoice_id: number) => {};", errors: [{ messageId: "preferNominalIds" }] },
    { code: "const load = function(accountId: string, invoiceId: string) {};", errors: [{ messageId: "preferNominalIds" }] },
    { code: "class Store { load(accountId: string, invoiceId: string) {} }", errors: [{ messageId: "preferNominalIds" }] },
    { code: "interface Store { load(accountId: string, invoiceId: string): void }", errors: [{ messageId: "preferNominalIds" }] },
    { code: "type Load = (accountId: string, invoiceId: string) => void;", errors: [{ messageId: "preferNominalIds" }] },
    { code: "declare function load(accountId: string, invoiceId: string): void;", errors: [{ messageId: "preferNominalIds" }] },
    { code: "abstract class Store { abstract load(accountId: string, invoiceId: string): void }", errors: [{ messageId: "preferNominalIds" }] },
    { code: "type Id = string; type OtherId = Id; function load(accountId: Id, invoiceId: OtherId) {}", errors: [{ messageId: "preferNominalIds" }] },
    { code: "function load(accountId: string | null, invoiceId?: string | undefined) {}", errors: [{ messageId: "preferNominalIds" }] },
    { code: "function load(accountIds: readonly string[], invoiceIds: ReadonlyArray<string>) {}", errors: [{ messageId: "preferNominalIds" }] },
    { code: "type Ids = string[]; function load(accountIds: Ids, invoiceIds: Array<string>) {}", errors: [{ messageId: "preferNominalIds" }] },
    { code: "function load(accountId: string = '', invoiceId: string = '') {}", errors: [{ messageId: "preferNominalIds" }] },
    { code: "function outer() { type Id = number; return (accountId: Id, invoiceId: Id) => {}; }", errors: [{ messageId: "preferNominalIds" }] },
    { filename: "src/api/adapters/store.ts", code: "function load(accountId: string, invoiceId: string) {}", errors: [{ messageId: "preferNominalIds" }] },
    { filename: "tests/store.test.ts", code: "function load(accountId: string, invoiceId: string) {}", errors: [{ messageId: "preferNominalIds" }] },
  ],
});

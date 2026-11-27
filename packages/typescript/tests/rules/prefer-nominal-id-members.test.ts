import rule from "../../src/rules/prefer-nominal-id-members.js";
import { ruleTester } from "./_tester.js";

const RAW_MEMBERS = "interface Receipt { accountId: string; invoiceId: string }";
const WARNING = { messageId: "preferNominalIdMembers" };

ruleTester().run("prefer-nominal-id-members", rule, {
  valid: [
    "import type { AccountId, InvoiceId } from './ids'; interface Receipt { accountId: AccountId; invoiceId: InvoiceId }",
    "interface Receipt { requestId: string; traceId: string; accountId: string }",
    "interface Receipt { accountId: string; label: string }",
    "interface Receipt { accountIds: string[]; invoiceId: string }",
    "interface Receipt { accountIds: string; invoiceId: string }",
    "interface Receipt { accountId: string; 'account_id': string }",
    "interface Receipt { accountId: string; invoiceId: number }",
    "interface Receipt { accountId: string; invoiceId: string | number }",
    "type Id = string; interface Receipt<Id extends string> { accountId: Id; invoiceId: Id }",
    "type Receipt = { [key: string]: string };",
    "type Receipt = { [Key in 'accountId' | 'invoiceId']: string };",
    "interface Receipt { accountId: string; ['invoiceId']: string }",
    "class Receipt { accountId = ''; invoiceId = ''; }",
    "interface Receipt { load(accountId: string, invoiceId: string): void }",
    "type Receipt = { account: { accountId: string }; invoice: { invoiceId: string } };",
    { filename: "src/generated/client.ts", code: RAW_MEMBERS },
    { code: `// @generated\n${RAW_MEMBERS}` },
  ],
  invalid: [
    {
      name: "checks a destructured options parameter",
      code: "function OptimizationOpportunities({ organizationId, scenarioId }: { organizationId: string; scenarioId: string }) {}",
      errors: [WARNING],
    },
    {
      name: "checks an exported interface with unrelated members",
      code: "export interface ReconcileConfig { channelId: string; checklistTab: string; sheetId: string }",
      errors: [WARNING],
    },
    {
      name: "checks an element type inside a readonly options array",
      code: "function save(entries: readonly { userId: string; teamId: string }[]) {}",
      errors: [WARNING],
    },
    {
      name: "checks object types inside a tagged union",
      code: "type Event = { kind: 'comment_created'; recordId: string; commentId: string } | { kind: 'created'; recordId: string };",
      errors: [WARNING],
    },
    {
      name: "checks annotated class fields including abstract and quoted properties",
      code: "abstract class Receipt { abstract accountId: number; readonly 'invoice_id': number = 1; }",
      errors: [WARNING],
    },
    {
      name: "resolves local aliases and nullable array carriers",
      code: "type AccountIds = ReadonlyArray<string>; interface Receipt { accountIds: AccountIds; invoiceIds?: readonly string[] | null }",
      errors: [WARNING],
    },
    {
      name: "reports the first pair on its second member once with no fix",
      code: "interface Receipt {\n  accountId: string;\n  invoiceId: string;\n  teamId: string;\n  userId: number;\n  vendorId: number;\n}",
      errors: [{ ...WARNING, type: "TSPropertySignature", line: 3, column: 3 }],
      output: null,
    },
  ],
});

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-non-nullable-collection.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

ruleTester.run("prefer-non-nullable-collection", rule, {
  valid: [
    "interface Input { organizationIds: OrganizationId[]; }",
    "type Response = { items: Array<string> };",
    "interface Input { value: string | string[] | null; }",
    "interface Input { id: string | null; }",
    "function search(ids: string[] | null): Item[] | undefined { return undefined; }",
    "type Result = Promise<Item[] | null>;",
    "type MaybeItem = Item | null;",
    // A declaration alone cannot prove that nullish and empty carry the same meaning.
    "interface Input { organizationIds: OrganizationId[] | null; }",
    "type Response = { items: null | string[] | undefined };",
    "class State { statuses!: Array<Status> | undefined; }",
    "type MaybeItems = Item[] | null;",
    "function parse(raw: string): { text: string; chips: string[] | null } { return { text: raw, chips: null }; }",
    "type Parser = (raw: string) => { text: string; chips: string[] | null };",
    {
      name: "preserves undefined as a loading state",
      code: [
        "interface Props { options: Option[] | undefined; }",
        "function Menu({ options }: Props) {",
        "  if (options === undefined) return 'Loading';",
        "  return options.map(renderOption);",
        "}",
      ].join("\n"),
    },
    {
      name: "preserves a null cache sentinel",
      code: [
        "interface Cache { values: string[] | null; }",
        "function read(cache: Cache) {",
        "  if (cache.values === null) cache.values = loadValues();",
        "  return cache.values;",
        "}",
      ].join("\n"),
    },
    {
      name: "preserves destructive null versus empty semantics",
      code: [
        "interface Input { wipeExceptNames: string[] | null; }",
        "function sync({ wipeExceptNames }: Input) {",
        "  return wipeExceptNames === null ? overlay() : wipeExcept(wipeExceptNames);",
        "}",
      ].join("\n"),
    },
    {
      name: "preserves explicit type-mismatch state",
      code: [
        "interface Form { allowedTools: string[] | null; }",
        "function save({ allowedTools }: Form) {",
        "  if (allowedTools === null) return showYamlTypeError();",
        "  return writeTools(allowedTools);",
        "}",
      ].join("\n"),
    },
    {
      name: "does not rewrite exported wire DTOs",
      code: [
        "export interface DockerResponse { ImagesDeleted: string[] | null; }",
        "export async function prune(): Promise<DockerResponse> { return request(); }",
      ].join("\n"),
    },
    {
      name: "does not infer semantics through pass-through",
      code: [
        "interface Props { items: Item[] | undefined; }",
        "function Panel(props: Props) { return renderPanel(props); }",
      ].join("\n"),
    },
    {
      name: "allows omission without an explicit nullish collection value",
      code: "interface Input { ids?: string[]; }",
    },
    {
      name: "allows optional API fields where omission and null can differ",
      code: "interface Input { ids?: string[] | null | undefined; }",
    },
    {
      code: "interface Input { ids: string[] | null; }",
      filename: "src/search.test.ts",
    },
    {
      code: "interface Input { ids: string[] | null; }",
      filename: "src/generated/api.ts",
    },
    {
      name: "ignores generated declaration files",
      code: "interface Input { ids: string[] | null; }",
      filename: "src/api.d.ts",
    },
    {
      code: "interface Input { ids: string[] | null; }",
      filename: "src/vendor/api.ts",
    },
  ],
  invalid: [
    {
      name: "reports an undefined array defaulted during destructuring",
      code: [
        "interface Input { organizationIds: OrganizationId[] | undefined; }",
        "function search({ organizationIds = [] }: Input) { return organizationIds.map(load); }",
      ].join("\n"),
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
    {
      name: "reports an inline parameter defaulted to empty",
      code: "function search({ items = [] }: { items: string[] | undefined }) { return items.length; }",
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
    {
      name: "reports a leading guard that treats absent and empty identically",
      code: [
        "interface Props { variables: string[] | undefined; }",
        "function Variables({ variables }: Props) {",
        "  if (!variables || variables.length === 0) return null;",
        "  return variables.map(renderVariable);",
        "}",
      ].join("\n"),
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
    {
      name: "reports a member used only through empty coalescing",
      code: [
        "function sections(input: { services: Service[] | null | undefined }) {",
        "  return [...(input.services ?? [])];",
        "}",
      ].join("\n"),
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
    {
      name: "reports a destructured binding used only through empty coalescing",
      code: [
        "interface Input { pages: ReadonlyArray<Page> | undefined; }",
        "function load({ pages }: Input) { return (pages ?? []).map(copyPage); }",
      ].join("\n"),
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
  ],
});

// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION } from "../../src/rules/prefer-non-nullable-collection.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

RULE_TESTER.run("prefer-non-nullable-collection", rule, {
  valid: [
    {name: "preserves exported normalized collection signatures", code: "export {}; export function count({ items = [] }: { items: string[] | undefined }) { return items.length; }" },
    { name: "does not borrow a shadowed outer contract", code: "interface Input { items: string[] | undefined } function outer() { interface Input { items: string[] } function read({ items = [] }: Input) { return items.length; } }" },
    { name: "does not borrow a contract through a generic parameter", code: "interface Input { items: string[] | undefined } function read<Input extends { items: string[] }>({ items = [] }: Input) { return items.length; }" },
    { name: "does not associate declaration-merged contracts", code: "interface Input { items: string[] | undefined } interface Input { source: string } function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a separately exported wire contract", code: "interface Input { items: string[] | undefined } export type { Input }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a renamed exported wire contract", code: "type Input = { items: string[] | undefined }; export { type Input as WireInput }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a wire contract exported through an exact local alias", code: "interface Input { items: string[] | undefined } export type WireInput = Input; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a wire contract through an exported alias chain", code: "interface Input { items: string[] | undefined } type First = Input; type WireInput = First; export { type WireInput }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a wire contract inherited by an exported interface", code: "interface Input { items: string[] | undefined } export interface WireInput extends Input {} function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a wire contract inherited by a default exported interface", code: "interface Input { items: string[] | undefined } export default interface WireInput extends Input {} function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a wire contract in an exported union", code: "interface Input { items: string[] | undefined } export type WireInput = Input | { fallback: true }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a wire contract in an exported intersection", code: "interface Input { items: string[] | undefined } export type WireInput = Input & { source: string }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a wire contract nested in an exported object type", code: "interface Input { items: string[] | undefined } export type WireInput = { payload: Input }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves recursive exported type ownership without following cycles repeatedly", code: "interface Input { items: string[] | undefined; next?: WireInput } export type WireInput = Input; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a private type in an exported function signature", code: "interface Input { items: string[] | undefined } export function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a private type in an exported constant arrow signature", code: "interface Input { items: string[] | undefined } export const read = ({ items = [] }: Input) => items.length;" },
    { name: "preserves a separately exported local function signature", code: "interface Input { items: string[] | undefined } function read({ items = [] }: Input) { return items.length; } export { read };" },
    { name: "preserves an exported inline parameter contract", code: "export function read({ items = [] }: { items: string[] | undefined }) { return items.length; }" },
    { name: "preserves a default anonymous function signature", code: "export default function ({ items = [] }: { items: string[] | undefined }) { return items.length; }" },
    { name: "preserves a direct default arrow signature", code: "export default ({ items = [] }: { items: string[] | undefined }) => items.length;" },
    { name: "preserves a default identifier callable signature", code: "interface Input { items: string[] | undefined } function read({ items = [] }: Input) { return items.length; } export default read;" },
    { name: "preserves a CTS callable export assignment", filename: "src/input.cts", code: "interface Input { items: string[] | undefined } const read = ({ items = [] }: Input) => items.length; export = read;" },
    { name: "preserves constant callable aliases by value binding", code: "interface Input { items: string[] | undefined } function read({ items = [] }: Input) { return items.length; } const first = read; const api = first; export { api };" },
    { name: "preserves annotations on constant callable aliases", code: "interface Input { items: string[] | undefined } const read = (input: Input) => (input.items ?? []).length; const api: (input: Input) => number = read; export { api }; function local({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a type used only by an explicit exported return annotation", code: "interface Input { items: string[] | undefined } export function create(): Input { return { items: undefined }; } function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a type used by an exported generic constraint", code: "interface Input { items: string[] | undefined } export function identity<T extends Input>(value: T) { return value; } function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves an explicit exported opaque value annotation", code: "interface Input { items: string[] | undefined } export const sample: Input = getInput(); function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a separately exported explicit value annotation", code: "interface Input { items: string[] | undefined } const sample: Input = getInput(); export { sample }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "value exports resolve callable definitions independently of same-named types", code: "type read = number; function read({ items = [] }: { items: string[] | undefined }) { return items.length; } export { read };" },
    { name: "a type-only function export preserves its queryable signature", code: "function read({ items = [] }: { items: string[] | undefined }) { return items.length; } export type { read };" },
    { name: "a type-only export preserves a same-named callable signature too", code: "function read({ items = [] }: { items: string[] | undefined }) { return items.length; } type read = number; export type { read };" },
    { name: "preserves a directly exported declaration signature", code: "interface Input { items: string[] | undefined } export declare function api(input: Input): number; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a separately exported declaration signature", code: "interface Input { items: string[] | undefined } declare function api(input: Input): number; export { api }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves an exported overload signature with an unknown implementation", code: "interface Input { items: string[] | undefined } export function api(input: Input): number; export function api(input: unknown) { return 0; } function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves separately exported overload headers", code: "interface Input { items: string[] | undefined } function api(input: Input): number; function api(input: unknown) { return 0; } export { api }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves overload headers reached through a constant callable alias", code: "interface Input { items: string[] | undefined } function api(input: Input): number; function api(input: unknown) { return 0; } const published = api; export { published }; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves an exported query of a private callable signature", code: "interface Input { items: string[] | undefined } function read({ items = [] }: Input): number { return items.length; } export type Api = typeof read;" },
    { name: "preserves a callable query inside an exported interface", code: "function read({ items = [] }: { items: string[] | undefined }): number { return items.length; } export interface Api { read: typeof read }" },
    { name: "preserves a declaration header reached by an exported query", code: "interface Input { items: string[] | undefined } declare function api(input: Input): number; export type Api = typeof api; function read({ items = [] }: Input) { return items.length; }" },
    { name: "preserves a callable query in an exported variable annotation", code: "function read({ items = [] }: { items: string[] | undefined }) { return items.length; } export const api: typeof read = getHandler();" },
    { name: "terminates an alternating exported type and callable signature cycle", code: "interface Input { items: string[] | undefined; next?: typeof read } function read({ items = [] }: Input): Input { return { items }; } export type Api = typeof read; function local({ items = [] }: Input) { return items.length; }" },
    { name: "a type query resolves its value independently of a generic type name", code: "function read({ items = [] }: { items: string[] | undefined }) { return items.length; } export type Api<read> = typeof read;" },
    { name: "preserves a CTS export assignment of the wire type", filename: "src/input.cts", code: "interface Input { items: string[] | undefined } function read({ items = [] }: Input) { return items.length; } export = Input;" },
    { name: "preserves a default export of the wire type", code: "interface Input { items: string[] | undefined } function read({ items = [] }: Input) { return items.length; } export default Input;" },
    { name: "does not infer arrays from a local generic name", code: "type Array<T> = { length: number }; interface Input { items: Array<string> | undefined } function read({ items = [] }: Input) { return items.length; }" },
    { name: "does not infer arrays from an imported generic name", code: "import type { ReadonlyArray } from './wire'; interface Input { items: ReadonlyArray<string> | undefined } function read({ items = [] }: Input) { return items.length; }" },
    { name: "resolves array names at the property declaration", code: "type Array<T> = { length: number }; interface Input { items: Array<string> | undefined } function outer() { type Array<T> = T[]; function read({ items = [] }: Input) { return items.length; } }" },
    { name: "negating a guard reverses its meaning", code: "interface Input { items: string[] | null } function f({items}: Input) { if (!(items === null || items.length === 0)) return 'present'; return items; }" },
    { name: "an escaping input can preserve its null state", code: "interface Input { items: string[] | null } function f(input: Input) { observe(input); return (input.items ?? []).length; }" },
    { name: "reversed less than comparison is not an empty check", code: "interface Input { items: string[] | null } function f({items}: Input) { if (items === null || 0 <= items.length) return 'present'; return items; }" },
    { name: "public no-match example", filename: PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION.examples[0].focusPath, code: PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION.examples[0].files[0].source },
    { name: "public exported-input boundary example", filename: PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION.examples[2].focusPath, code: PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION.examples[2].files[0].source },
    "interface Input { organizationIds: OrganizationId[]; }",
    "type Response = { items: Array<string> };",
    "interface Input { value: string | string[] | null; }",
    "interface Input { id: string | null; }",
    "function search(ids: string[] | null): Item[] | undefined { return undefined; }",
    "type Result = Promise<Item[] | null>;",
    "type MaybeItem = Item | null;",

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
      name: "preserves a terminating guard that distinguishes null from empty",
      code: [
        "interface Props { items: Item[] | null; }",
        "function Panel({ items }: Props) {",
        "  if (items === null || items.length === 0) return items === null ? loading() : empty();",
        "  return items.map(renderItem);",
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
    {name: "corrects an unused private normalized inline collection", code: "export {}; function count({ items = [] }: { items: string[] | undefined }) { return items.length; }", output: "export {}; function count({ items = [] }: { items: string[] }) { return items.length; }", errors: [{messageId: "preferNonNullableCollection"}]},
    {name: "preserves consumed normalized collection signatures", code: "export {}; function count({ items = [] }: { items: string[] | undefined }) { return items.length; } consume(count);", output: null, errors: [{messageId: "preferNonNullableCollection"}]},
    {name: "preserves annotated collection comments", code: "export {}; function count({ items = [] }: { items: string[] | /* wire state */ undefined }) { return items.length; }", output: null, errors: [{messageId: "preferNonNullableCollection"}]},
    { name: "value names do not shadow array types", code: "const Array = 1; interface Input { items: Array<string> | undefined } function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "value names do not shadow local contracts", code: "interface Input { items: string[] | undefined } function outer() { const Input = 1; function read({ items = [] }: Input) { return items.length; } }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "re-exports do not publish an unrelated local contract", code: "interface Input { items: string[] | undefined } export type { Input } from './wire'; function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "later local shadows do not change declaration-site array meaning", code: "interface Input { items: Array<string> | undefined } function outer() { type Array<T> = { length: number }; function read({ items = [] }: Input) { return items.length; } }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "exporting a namespace does not publish an unrelated local wire type", filename: "src/input.cts", code: "interface Input { items: string[] | undefined } namespace Wire { export interface Input { items: string[] } } function read({ items = [] }: Input) { return items.length; } export = Wire;", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "default namespace exports do not publish an unrelated local wire type", code: "interface Input { items: string[] | undefined } namespace Wire { export interface Input { items: string[] } } function read({ items = [] }: Input) { return items.length; } export default Wire;", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "an unexported alias does not publish its local wire contract", code: "interface Input { items: string[] | undefined } type WireInput = Input; function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "an unexported child interface does not publish its parent contract", code: "interface Input { items: string[] | undefined } interface WireInput extends Input {} function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "an exported generic parameter does not borrow a same-named local contract", code: "interface Input { items: string[] | undefined } export type WireInput<Input> = Input; function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "an exported qualified alias does not borrow an unrelated local contract", code: "interface Input { items: string[] | undefined } namespace Wire { export interface Input { items: string[] } } export type WireInput = Wire.Input; function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "an invalid alias cycle neither loops nor publishes an unrelated contract", code: "type First = Second; type Second = First; export { type First }; interface Input { items: string[] | undefined } function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "a public body does not publish a private implementation signature", code: "interface Input { items: string[] | undefined } export function main() { function read({ items = [] }: Input) { return items.length; } return read({ items: [] }); }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "a public generic parameter does not borrow a same-named private type", code: "interface Input { items: string[] | undefined } export function identity<Input>(value: Input) { return value; } function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "an unrelated type export does not publish a private callable", code: "function read({ items = [] }: { items: string[] | undefined }) { return items.length; } type Published = number; export type { Published };", output: "function read({ items = [] }: { items: string[] }) { return items.length; } type Published = number; export type { Published };", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "an arbitrary exported invocation does not export its argument callable", code: "function read({ items = [] }: { items: string[] | undefined }) { return items.length; } export default wrap(read);", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "a callable alias cycle does not publish an unrelated private signature", code: "const first = second; const second = first; export { first }; interface Input { items: string[] | undefined } function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "a public default initializer does not publish a nested implementation signature", code: "export function main(callback = () => { function read({ items = [] }: { items: string[] | undefined }) { return items.length; } return read({ items: [] }); }) { return callback(); }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "a private declaration signature does not publish its input", code: "interface Input { items: string[] | undefined } declare function api(input: Input): number; function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "an unrelated public declaration return does not publish a private input", code: "interface Input { items: string[] | undefined } export declare function api(): string; function read({ items = [] }: Input) { return items.length; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "a private type query does not publish a private signature", code: "function read({ items = [] }: { items: string[] | undefined }) { return items.length; } type Api = typeof read;", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "a query of another value does not publish a private signature", code: "function read({ items = [] }: { items: string[] | undefined }) { return items.length; } function other() { return 0; } export type Api = typeof other;", output: "function read({ items = [] }: { items: string[] }) { return items.length; } function other() { return 0; } export type Api = typeof other;", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "a private query inside a public body does not publish a private signature", code: "function read({ items = [] }: { items: string[] | undefined }) { return items.length; } export function main() { type Api = typeof read; return 0; }", errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "public match example", filename: PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION.examples[1].focusPath, code: PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "preferNonNullableCollection" }] },
    { name: "public private-input review example", filename: PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION.examples[3].focusPath, code: PREFER_NON_NULLABLE_COLLECTION_DOCUMENTATION.examples[3].files[0].source, errors: [{ messageId: "preferNonNullableCollection" }] },
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
      name: "reports an optional-length guard that treats absent and empty identically",
      code: [
        "interface Props { variables: string[] | undefined; }",
        "function Variables({ variables }: Props) {",
        "  if (!variables?.length) return null;",
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

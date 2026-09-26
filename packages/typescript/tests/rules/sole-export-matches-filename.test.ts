import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import genericRule from "../../src/rules/no-generic-single-export-module.js";

import rule, { SOLE_EXPORT_MATCHES_FILENAME_DOCUMENTATION } from "../../src/rules/sole-export-matches-filename.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, sourceType: "module" } });

RULE_TESTER.run("sole-export-matches-filename", rule, {
  valid: [
    { name: "exported import-equals leaves the runtime surface unknown", filename: "src/items.ts", code: "namespace Domain { export class Entry {} } export import Entry = Domain.Entry; export const only = 1;" },
    { name: "export equals leaves a mixed runtime surface unresolved", filename: "src/artifacts.ts", code: "export = other; export class ArtifactStore {}" },
    { name: "exported import aliases remain unresolved", filename: "src/artifacts.ts", code: "export import Other = Domain.Other; export class ArtifactStore {}" },
    { name: "case enforcement belongs to filename-case", filename: "src/Artifact-Store.ts", code: "export class ArtifactStore {}" },
    { name: "identifier default resolves a local value", filename: "src/artifact-store.ts", code: "class ArtifactStore {} export default ArtifactStore;" },
    { name: "two public names for one value are two exports", filename: "src/artifacts.ts", code: "class ArtifactStore {} export { ArtifactStore, ArtifactStore as default };" },
    { name: "imported bindings have an unknown runtime surface", filename: "src/artifacts.ts", code: "import { Contract } from './contracts.js'; export { Contract }; export class ArtifactStore {}" },
    { name: "imported default is unresolved", filename: "src/artifacts.ts", code: "import Contract from './contracts.js'; export default Contract;" },
    { name: "const enum beside a runtime value is emission dependent", filename: "src/artifacts.ts", code: "export const enum State { Ready } export class ArtifactStore {}" },
    { name: "const enum alias is emission dependent", filename: "src/artifacts.ts", code: "const enum State { Ready } export { State }; export class ArtifactStore {}" },
    { name: "runtime namespace adds another public key", filename: "src/artifacts.ts", code: "export namespace Other { export const count = 1; } export class ArtifactStore {}" },
    { name: "empty namespace is not assumed to emit", filename: "src/artifacts.ts", code: "export namespace Other {} export class ArtifactStore {}" },
    { name: "mixed CommonJS is ambiguous", filename: "src/artifacts.ts", code: "module.exports.other = 1; export class ArtifactStore {}" },
    { name: "computed CommonJS is ambiguous", filename: "src/artifacts.ts", code: "module['exports'] = {}; export class ArtifactStore {}" },
    { name: "CommonJS property definitions are ambiguous", filename: "src/artifacts.ts", code: "Object.defineProperty(exports, 'other', { value: 1 }); export class ArtifactStore {}" },
    { name: "ambient aliases are not runtime exports", filename: "src/artifacts.ts", code: "declare const value: object; export { value };" },
    { name: "type aliases are not runtime exports", filename: "src/artifacts.ts", code: "interface Contract {} export { Contract };" },
    { name: "generic helper is owned by the generic rule", filename: "src/helper.ts", code: "export class ArtifactStore {}" },
    { name: "generic stuff is owned by the generic rule", filename: "src/stuff.ts", code: "export class ArtifactStore {}" },
    { name: "type only namespaces are erased", filename: "src/artifacts.ts", code: "export namespace Contracts { export interface Contract {} }" },
    { name: "does not call an export sole alongside destructured bindings", filename: "src/items.ts", code: "export function build() {} export const {first, second} = pair;" },
    { name: "does not overlook array export patterns", filename: "src/items.ts", code: "export function build() {} export const [first, ...rest] = values;" },
    { name: "private helper prefix is preserved", filename: "src/_build-record.ts", code: "export function buildRecord() {}" },
    { name: "Next client instrumentation has a fixed export contract", filename: "src/instrumentation-client.ts", code: "export function onRouterTransitionStart() {}" },
    { name: "Astro collections have a framework-owned config filename", filename: "src/content.config.ts", code: "import { defineCollection } from 'astro:content'; export const collections = { posts: defineCollection({}) };" },
    {filename: "app/error.tsx", code: "'use client'; export default function ErrorBoundary(){return null;}"},
    {filename: "/repo/src/app/orders/global-error.tsx", code: "'use client'; export default function GlobalBoundary(){return null;}"},
    {filename: "C:\\repo\\app\\orders\\error.tsx", code: "'use client'; export default function Boundary(){return null;}"},
    { filename: "src/artifact-store.ts", code: SOLE_EXPORT_MATCHES_FILENAME_DOCUMENTATION.examples[0].files[0].source },
    { filename: "src/oauth-client.server.ts", code: "export class OAuthClient {}" },
    { filename: "src/artifacts.ts", code: "export class ArtifactStore {} export const version = 1;" },
    { filename: "src/index.ts", code: "export class ArtifactStore {}" },
    { filename: "src/page.tsx", code: "export default function PoetPage() { return null; }" },
    { filename: "src/pages/robots.txt.ts", code: "export function GET() { return new Response(); }" },
    { filename: "src/artifacts.ts", code: "export * from './artifact-store.js';" },
    { filename: "src/artifacts.ts", code: "export { ArtifactStore } from './artifact-store.js';" },
    { filename: "src/artifacts.test.ts", code: "export class ArtifactStore {}" },
    { filename: "src/generated/artifacts.ts", code: "export class ArtifactStore {}" },
    { filename: "src/artifacts.ts", code: "export default function () {}" },
    { filename: "src/artifacts.ts", code: "export type ArtifactStore = object;" },
  ],
  invalid: [
    { name: "qualified namespace exports use their root runtime key", filename: "src/artifacts.ts", code: "export namespace ArtifactStore.Internal { export const count = 1; }", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "supporting type exports do not hide a runtime mismatch", filename: "src/provider-contract.ts", code: "export const ProviderSchema = {}; export type Provider = string;", errors: [{ messageId: "matchSoleExport", data: { exported: "ProviderSchema", expected: "provider-schema" } }] },
    { name: "leading phrases must use the complete export name", filename: "src/html.ts", code: "export function htmlEscape() {}", errors: [{ messageId: "matchSoleExport", data: { exported: "htmlEscape", expected: "html-escape" } }] },
    { name: "trailing phrases must use the complete export name", filename: "src/person-name.ts", code: "export function sanitizePersonName() {}", errors: [{ messageId: "matchSoleExport", data: { exported: "sanitizePersonName", expected: "sanitize-person-name" } }] },
    { name: "acronym token conversion is exact", filename: "src/github-repo-url.ts", code: "export function matchGitHubRepoUrl() {}", errors: [{ messageId: "matchSoleExport", data: { exported: "matchGitHubRepoUrl", expected: "match-git-hub-repo-url" } }] },
    { name: "only one private underscore is allowed", filename: "src/__artifact-store.ts", code: "export class ArtifactStore {}", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "_artifact-store" } }] },
    { name: "identifier default reports its local responsibility", filename: "src/artifacts.ts", code: "class ArtifactStore {} export default ArtifactStore;", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "named aliases use the public runtime name", filename: "src/artifacts.ts", code: "class Internal {} export { Internal as ArtifactStore };", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "default aliases use the local name", filename: "src/artifacts.ts", code: "class ArtifactStore {} export { ArtifactStore as default };", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "type only export stars do not hide runtime names", filename: "src/artifacts.ts", code: "export type * from './contracts.js'; export class ArtifactStore {}", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "type only local aliases do not hide runtime names", filename: "src/artifacts.ts", code: "interface Contract {} export { Contract }; export class ArtifactStore {}", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "ambient exports do not hide runtime names", filename: "src/artifacts.ts", code: "export declare const value: object; export class ArtifactStore {}", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "runtime declaration merging wins over a type", filename: "src/artifacts.ts", code: "interface ArtifactStore {} class ArtifactStore {} export { ArtifactStore };", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "runtime namespaces have a responsibility", filename: "src/artifacts.ts", code: "export namespace ArtifactStore { export const count = 1; }", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "type only namespaces do not add runtime keys", filename: "src/artifacts.ts", code: "export namespace Contracts { export interface Contract {} } export class ArtifactStore {}", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "shadowed CommonJS identifiers remain ordinary code", filename: "src/artifacts.ts", code: "const exports = {}; exports.value = 1; export class ArtifactStore {}", errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }] },
    { name: "private helper mismatches retain the prefix", filename: "src/_record.ts", code: "export function buildRecord() {}", errors: [{ messageId: "matchSoleExport", data: { exported: "buildRecord", expected: "_build-record" } }] },
    { name: "instrumentation filename does not exempt unrelated exports", filename: "src/instrumentation-client.ts", code: "export function trackChanges() {}", errors: [{ messageId: "matchSoleExport" }] },
    { name: "Astro import outside content config does not exempt a mirror filename", filename: "src/services/content.config.ts", code: "import { defineCollection } from 'astro:content'; export const collections = {};", errors: [{ messageId: "matchSoleExport" }] },
    { name: "content config without Astro provenance remains ordinary code", filename: "src/content.config.ts", code: "export const collections = {};", errors: [{ messageId: "matchSoleExport" }] },
    {filename: "src/error.ts", code: "export class DomainFailure {}", errors: [{messageId: "matchSoleExport"}]},
    { name: "very short suffixes do not create accidental containment", filename: "src/id.ts", code: "export function invalidId() {}", errors: [{ messageId: "matchSoleExport" }] },
    { name: "unrelated multi-token stems remain mismatches", filename: "src/user-rate.ts", code: "export function generateUser() {}", errors: [{ messageId: "matchSoleExport" }] },
    { name: "partial export tokens do not count as a leading phrase", filename: "src/user-rate.ts", code: "export function UserRater() {}", errors: [{ messageId: "matchSoleExport" }] },
    {
      filename: "src/artifacts.ts",
      code: SOLE_EXPORT_MATCHES_FILENAME_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "matchSoleExport", data: { exported: "ArtifactStore", expected: "artifact-store" } }],
    },
    {
      filename: "src/client.ts",
      code: "export default class OAuthClient {}",
      errors: [{ messageId: "matchSoleExport", data: { exported: "OAuthClient", expected: "oauth-client" } }],
    },
    {
      filename: "src/parser.ts",
      code: "function parsePoem() { return {}; } export { parsePoem };",
      errors: [{ messageId: "matchSoleExport", data: { exported: "parsePoem", expected: "parse-poem" } }],
    },
    {
      filename: "src/config.ts",
      code: "export class RuntimeConfig {}",
      errors: [{ messageId: "matchSoleExport", data: { exported: "RuntimeConfig", expected: "runtime-config" } }],
    },
    {
      filename: "src/worker.ts",
      code: "export class CollectionWorker {}",
      errors: [{ messageId: "matchSoleExport", data: { exported: "CollectionWorker", expected: "collection-worker" } }],
    },
  ],
});

for (const stem of ["helper", "stuff", "utils"]) {
  it(`gives the generic rule exclusive ownership of ${stem}`, () => {
    const messages = new Linter().verify("export class ArtifactStore {}", [{
      files: ["**/*.ts"],
      languageOptions: { parser: tsParser },
      plugins: { sarj: { rules: { sole: rule, generic: genericRule } } },
      rules: { "sarj/sole": "error", "sarj/generic": "error" },
    }], { filename: `src/${stem}.ts` });
    expect(messages.map((message) => message.ruleId)).toEqual(["sarj/generic"]);
  });
}

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { SOLE_EXPORT_MATCHES_FILENAME_DOCUMENTATION } from "../../src/rules/sole-export-matches-filename.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, sourceType: "module" } });

RULE_TESTER.run("sole-export-matches-filename", rule, {
  valid: [
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
    { filename: "src/provider-contract.ts", code: "export const ProviderSchema = {}; export type Provider = string;" },
  ],
  invalid: [
    { name: "private helper mismatches retain the prefix", filename: "src/_record.ts", code: "export function buildRecord() {}", errors: [{ messageId: "matchSoleExport", data: { exported: "buildRecord", expected: "_build-record" } }] },
    { name: "instrumentation filename does not exempt unrelated exports", filename: "src/instrumentation-client.ts", code: "export function trackChanges() {}", errors: [{ messageId: "matchSoleExport" }] },
    { name: "Astro import outside content config does not exempt a mirror filename", filename: "src/services/content.config.ts", code: "import { defineCollection } from 'astro:content'; export const collections = {};", errors: [{ messageId: "matchSoleExport" }] },
    { name: "content config without Astro provenance remains ordinary code", filename: "src/content.config.ts", code: "export const collections = {};", errors: [{ messageId: "matchSoleExport" }] },
    {filename: "src/error.ts", code: "export class DomainFailure {}", errors: [{messageId: "matchSoleExport"}]},
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

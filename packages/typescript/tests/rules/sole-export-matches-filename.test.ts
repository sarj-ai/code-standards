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

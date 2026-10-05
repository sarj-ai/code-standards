/**
 * @fileoverview sole-export-matches-filename — a single public runtime responsibility should be findable by filename.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/sole-export-matches-filename.test.ts
 */



import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isFrameworkEntrypoint } from "./_is-framework-entrypoint.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { GENERIC_MODULE_STEMS, isCommonJsExportReference, runtimeExports } from "./_runtime-exports.js";

type MessageIds = "matchSoleExport";
type Options = [];

export const SOLE_EXPORT_MATCHES_FILENAME_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Make a module filename reflect its sole named public runtime export.",
  rationale: "When a module owns one runtime responsibility, matching names make that responsibility directly discoverable.",
  remediation: "Name the module for the exported responsibility, using the full kebab-case export name; otherwise colocate genuinely related exports.",
  category: "maintainability",
  limitations: [
    "Framework entrypoints, generic stems covered by no-generic-single-export-module, tests, generated files, anonymous defaults, CommonJS, unresolved re-exports, and emission-dependent exports are excluded.",
    "The rule compares the primary filename stem and preserves a single private underscore prefix and conventional suffixes such as .server or .worker. Supporting types do not exempt a sole runtime export; public runtime aliases count as distinct exports.",
    "Exported destructuring patterns are excluded rather than undercounted as public exports.",
    "Next.js metadata routes, instrumentation, and other Next.js and Astro entrypoint exemptions require the nearest package.json to declare the framework, a conventional entrypoint path, and its expected runtime export. Custom routing roots and pageExtensions are not inferred.",
  ],
  examples: [
    { id: "matching-class", title: "Match a class and module", outcome: "no-match", files: [{ path: "src/artifact-store.ts", source: "export class ArtifactStore {}" }], focusPath: "src/artifact-store.ts", expectedCount: 0, public: true },
    { id: "mismatched-class", title: "Do not hide a sole class behind another filename", outcome: "match", files: [{ path: "src/artifacts.ts", source: "export class ArtifactStore {}" }], focusPath: "src/artifacts.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const EXCLUDED_STEMS: ReadonlySet<string> = new Set([
  "global", "index", "types",
]);

function stem(filename: string): string {
  const base = filename.replaceAll("\\", "/").split("/").at(-1) ?? "";
  return base.replace(/\.[cm]?[jt]sx?$/u, "").split(".")[0] ?? "";
}

function kebabCase(name: string): string {
  return name
    .replace(/([A-Z]{2,})([A-Z][a-z])/gu, "$1-$2")
    .replace(/([a-z0-9])([A-Z])/gu, "$1-$2")
    .replaceAll(/[^a-z0-9]+/giu, "-")
    .replaceAll(/^-+|-+$/gu, "")
    .toLowerCase();
}

export default createRule<Options, MessageIds>({
  name: "sole-export-matches-filename",
  documentation: SOLE_EXPORT_MATCHES_FILENAME_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: SOLE_EXPORT_MATCHES_FILENAME_DOCUMENTATION.summary },
    schema: [],
    messages: {
      matchSoleExport: "This module's sole runtime export is `{{exported}}`; rename the file stem to `{{expected}}`.",
    },
  },
  defaultOptions: [],
  create(context) {
    const fileStem = stem(sourceOrigin(context).filename);
    const normalizedFilename = sourceOrigin(context).filename.replaceAll("\\", "/");
    if (
      EXCLUDED_STEMS.has(fileStem) ||
      GENERIC_MODULE_STEMS.has(fileStem) ||
      sourceOrigin(context).filename.endsWith(".d.ts") ||
      isTestFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
    ) return {};
    let hasCommonJsExport = false;
    return {
      "CallExpression, MemberExpression"(node): void {
        if (isCommonJsExportReference(node, context.sourceCode)) hasCommonJsExport = true;
      },
      "Program:exit"(program): void {
        if (hasCommonJsExport) return;
        const exports = runtimeExports(program);
        if (exports.ambiguous || exports.exports.length !== 1) return;
        const only = exports.exports[0];
        if (only === undefined) return;
        if (isFrameworkEntrypoint(normalizedFilename, only.key)) return;
        if (
          only.name === "onRouterTransitionStart" &&
          /(?:^|\/)instrumentation-client\.[jt]s$/u.test(normalizedFilename)
        ) return;
        if (
          only.name === "collections" &&
          /(?:^|\/)src\/content\.config\.(?:ts|js|mjs)$/u.test(normalizedFilename) &&
          program.body.some((statement) => statement.type === "ImportDeclaration" &&
            statement.source.value === "astro:content")
        ) return;
        const exportedStem = kebabCase(only.name);
        if (exportedStem === "") return;
        const expected = `${fileStem.startsWith("_") ? "_" : ""}${exportedStem}`;
        if (expected === fileStem.toLowerCase()) return;
        context.report({ node: only.node, messageId: "matchSoleExport", data: { exported: only.name, expected } });
      },
    };
  },
});

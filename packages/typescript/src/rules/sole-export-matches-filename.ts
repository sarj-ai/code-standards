/**
 * @fileoverview sole-export-matches-filename — a single public runtime responsibility should be findable by filename.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/sole-export-matches-filename.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "matchSoleExport";
type Options = [];

export const SOLE_EXPORT_MATCHES_FILENAME_DOCUMENTATION = {
  summary: "Make a module filename reflect its sole named public runtime export.",
  rationale: "When a module owns one runtime responsibility, matching names make that responsibility directly discoverable.",
  remediation: "Name the module for the exported responsibility, using either the full export name or a clear leading or trailing domain phrase; otherwise colocate genuinely related exports.",
  category: "maintainability",
  limitations: [
    "Framework entrypoints, generic stems covered by no-generic-single-export-module, tests, generated files, anonymous defaults, CommonJS, and re-exports are excluded.",
    "The rule compares the primary filename stem and preserves a single private underscore prefix and conventional suffixes such as .server or .worker. A leading or trailing export-name phrase is accepted only at token boundaries; multi-token stems also tolerate established acronym spelling such as github versus GitHub.",
    "Exported destructuring patterns are excluded rather than undercounted as public exports.",
  ],
  examples: [
    { id: "matching-class", title: "Match a class and module", outcome: "no-match", files: [{ path: "src/artifact-store.ts", source: "export class ArtifactStore {}" }], focusPath: "src/artifact-store.ts", expectedCount: 0, public: true },
    { id: "mismatched-class", title: "Do not hide a sole class behind another filename", outcome: "match", files: [{ path: "src/artifacts.ts", source: "export class ArtifactStore {}" }], focusPath: "src/artifacts.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const EXCLUDED_STEMS: ReadonlySet<string> = new Set([
  "common", "global", "helpers", "index", "layout", "loading", "middleware", "misc", "not-found", "page",
  "route", "shared", "template", "types", "util", "utils",
]);
const WEAK_DOMAIN_TOKENS: ReadonlySet<string> = new Set([
  "adapter", "client", "config", "controller", "factory", "handler", "manager",
  "provider", "record", "repository", "router", "schema", "service", "store", "worker",
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

function reflectsExportName(fileStem: string, exportedStem: string): boolean {
  if (fileStem.startsWith("_")) return false;
  const visibleFileStem = fileStem.toLowerCase();
  const fileTokens = visibleFileStem.split("-").filter(Boolean);
  const exportTokens = exportedStem.split("-").filter(Boolean);
  if (fileTokens.length === 0 || exportTokens.length === 0) return false;
  if (fileTokens.length === 1) {
    const [token] = fileTokens;
    return token !== undefined && token.length >= 4 && !WEAK_DOMAIN_TOKENS.has(token) &&
      (exportTokens[0] === token || exportTokens.at(-1) === token);
  }
  const compactFile = fileTokens.join("");
  if (compactFile.length < 6) return false;
  const boundaryPhrases = new Set<string>();
  for (let index = 1; index <= exportTokens.length; index += 1) {
    boundaryPhrases.add(exportTokens.slice(0, index).join(""));
    boundaryPhrases.add(exportTokens.slice(-index).join(""));
  }
  return boundaryPhrases.has(compactFile);
}

interface NamedExport {
  readonly name: string;
  readonly node: TSESTree.Node;
}

function declarationExport(statement: TSESTree.ExportNamedDeclaration): NamedExport[] {
  const declaration = statement.declaration;
  if (declaration === null || (declaration as { declare?: boolean }).declare === true) return [];
  if (
    declaration.type === AST_NODE_TYPES.ClassDeclaration ||
    declaration.type === AST_NODE_TYPES.FunctionDeclaration ||
    declaration.type === AST_NODE_TYPES.TSEnumDeclaration
  ) return declaration.id === null ? [] : [{ name: declaration.id.name, node: declaration }];
  if (declaration.type !== AST_NODE_TYPES.VariableDeclaration) return [];
  return declaration.declarations.flatMap((item) =>
    item.id.type === AST_NODE_TYPES.Identifier ? [{ name: item.id.name, node: item }] : [],
  );
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
    const fileStem = stem(context.filename);
    const normalizedFilename = context.filename.replaceAll("\\", "/");
    if (
      EXCLUDED_STEMS.has(fileStem) ||
      /(?:^|\/)app\/(?:.*\/)?(?:global-)?error\.[jt]sx?$/u.test(normalizedFilename) ||
      normalizedFilename.includes("/pages/") ||
      context.filename.endsWith(".d.ts") ||
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    ) return {};
    return {
      "Program:exit"(program): void {
        const exports: NamedExport[] = [];
        const publicExports = new Set<string>();
        for (const statement of program.body) {
          if (statement.type === AST_NODE_TYPES.ExportAllDeclaration ||
              (statement.type === AST_NODE_TYPES.ExportNamedDeclaration && statement.source !== null)) return;
          if (statement.type === AST_NODE_TYPES.ExportDefaultDeclaration) {
            publicExports.add("default");
            const declaration = statement.declaration;
            if (
              (declaration.type === AST_NODE_TYPES.ClassDeclaration || declaration.type === AST_NODE_TYPES.FunctionDeclaration) &&
              declaration.id !== null
            ) exports.push({ name: declaration.id.name, node: declaration });
            else return;
          }
          if (statement.type !== AST_NODE_TYPES.ExportNamedDeclaration) continue;
          const declaration = statement.declaration;
          if (declaration !== null && "id" in declaration && declaration.id?.type === AST_NODE_TYPES.Identifier) {
            publicExports.add(declaration.id.name);
          }
          if (declaration?.type === AST_NODE_TYPES.VariableDeclaration) {
            if (declaration.declarations.some((item) => item.id.type !== AST_NODE_TYPES.Identifier)) return;
            for (const item of declaration.declarations) {
              if (item.id.type === AST_NODE_TYPES.Identifier) publicExports.add(item.id.name);
            }
          }
          for (const specifier of statement.specifiers) {
            const exported = specifier.exported.type === AST_NODE_TYPES.Identifier ? specifier.exported.name : specifier.exported.value;
            publicExports.add(String(exported));
          }
          if (statement.exportKind === "type") continue;
          exports.push(...declarationExport(statement));
          for (const specifier of statement.specifiers) {
            const exported = specifier.exported.type === AST_NODE_TYPES.Identifier ? specifier.exported.name : specifier.exported.value;
            publicExports.add(String(exported));
            if (specifier.exportKind === "type") continue;
            if (exported === "default") exports.push({ name: specifier.local.name, node: specifier });
            else exports.push({ name: String(exported), node: specifier });
          }
        }
        const unique = new Map(exports.map((item) => [item.name, item]));
        if (unique.size !== 1 || publicExports.size !== 1) return;
        const only = [...unique.values()][0];
        if (only === undefined) return;
        if (
          only.name === "onRouterTransitionStart" &&
          /(?:^|\/)instrumentation-client\.[jt]s$/u.test(normalizedFilename)
        ) return;
        if (
          only.name === "collections" &&
          /(?:^|\/)src\/content\.config\.(?:ts|js|mjs)$/u.test(normalizedFilename) &&
          program.body.some((statement) => statement.type === AST_NODE_TYPES.ImportDeclaration &&
            statement.source.value === "astro:content")
        ) return;
        const exportedStem = kebabCase(only.name);
        if (exportedStem === "") return;
        const expected = `${fileStem.startsWith("_") ? "_" : ""}${exportedStem}`;
        if (
          expected === fileStem.toLowerCase() ||
          reflectsExportName(fileStem, exportedStem)
        ) return;
        context.report({ node: only.node, messageId: "matchSoleExport", data: { exported: only.name, expected } });
      },
    };
  },
});

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
  summary: "Match a module filename to its sole named public runtime export.",
  rationale: "When a module owns one runtime responsibility, matching names make that responsibility directly discoverable.",
  remediation: "Rename the module stem to the kebab-case export name, or colocate genuinely related exports.",
  category: "maintainability",
  limitations: [
    "Framework entrypoints, generic stems covered by no-generic-single-export-module, tests, generated files, anonymous defaults, CommonJS, and re-exports are excluded.",
    "The rule compares the primary filename stem and preserves conventional suffixes such as .server or .worker.",
  ],
  examples: [
    { id: "matching-class", title: "Match a class and module", outcome: "no-match", files: [{ path: "src/artifact-store.ts", source: "export class ArtifactStore {}" }], focusPath: "src/artifact-store.ts", expectedCount: 0, public: true },
    { id: "mismatched-class", title: "Do not hide a sole class behind another filename", outcome: "match", files: [{ path: "src/artifacts.ts", source: "export class ArtifactStore {}" }], focusPath: "src/artifacts.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const EXCLUDED_STEMS: ReadonlySet<string> = new Set([
  "common", "config", "constants", "error", "errors", "global", "handler", "helpers", "index", "layout",
  "loading", "middleware", "misc", "models", "not-found", "page", "route", "schema", "shared", "template",
  "types", "util", "utils", "worker",
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
    docs: { description: "Match a module filename to its sole named public runtime export." },
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
        const expected = kebabCase(only.name);
        if (expected === "" || expected === fileStem.toLowerCase()) return;
        context.report({ node: only.node, messageId: "matchSoleExport", data: { exported: only.name, expected } });
      },
    };
  },
});

/**
 * @fileoverview sole-export-matches-filename — a module's filename should reflect its sole runtime export.
 *
 * Port of the 18.x `sole-export-matches-filename` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { GENERIC_MODULE_STEMS, isCommonJsExportReference, runtimeExports } from "../utils/runtime-exports.js";
import { isFrameworkEntrypoint } from "./_is-framework-entrypoint.js";

const NAME = "sole-export-matches-filename";

const EXCLUDED_STEMS: ReadonlySet<string> = new Set(["global", "index", "types"]);

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

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Make a module filename reflect its sole named public runtime export.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      matchSoleExport: "This module's sole runtime export is `{{exported}}`; rename the file stem to `{{expected}}`.",
    },
  },
  createOnce(context) {
    let fileStem = "";
    let normalizedFilename = "";
    let hasCommonJsExport = false;
    function checkCommonJs(node: ESTree.CallExpression | ESTree.MemberExpression): void {
      if (isCommonJsExportReference(node, context.sourceCode)) hasCommonJsExport = true;
    }
    return {
      before() {
        hasCommonJsExport = false;
        const filename = context.filename;
        fileStem = stem(filename);
        normalizedFilename = filename.replaceAll("\\", "/");
        const scoped = { filename, cwd: context.cwd };
        if (
          EXCLUDED_STEMS.has(fileStem) ||
          GENERIC_MODULE_STEMS.has(fileStem) ||
          filename.endsWith(".d.ts") ||
          isTestFile(scoped) ||
          isGeneratedFile(scoped, context.sourceCode.text)
        ) return false;
        return undefined;
      },
      CallExpression: checkCommonJs,
      MemberExpression: checkCommonJs,
      "Program:exit"(program: ESTree.Program): void {
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

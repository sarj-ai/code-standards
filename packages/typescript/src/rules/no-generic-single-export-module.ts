/**
 * @fileoverview no-generic-single-export-module — a generic module name hides the responsibility expressed by its sole runtime export.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-generic-single-export-module.test.ts
 */

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { GENERIC_MODULE_STEMS, isCommonJsExportReference, runtimeExports } from "./_runtime-exports.js";

type MessageIds = "genericSingleExport";
type Options = [];

export const NO_GENERIC_SINGLE_EXPORT_MODULE_DOCUMENTATION = {
  summary: "Disallow generic module stems when one runtime export already names the responsibility.",
  rationale: "A generic filename hides the sole exported responsibility and makes navigation less descriptive.",
  remediation: "Choose a responsibility-bearing module name or colocate the export with its domain.",
  category: "maintainability",
  limitations: ["Only the fixed generic-stem vocabulary with exactly one public runtime export is checked; exported destructuring patterns are excluded rather than undercounted."],
  examples: [
    { id: "responsibility-named-module", title: "Name the module after its export", outcome: "no-match", files: [{ path: "src/parse-order.ts", source: "export function parseOrder() { return {}; }" }], focusPath: "src/parse-order.ts", expectedCount: 0, public: true },
    { id: "generic-module-name", title: "Do not hide one export in a generic module", outcome: "match", files: [{ path: "src/utils.ts", source: "export function parseOrder() { return {}; }" }], focusPath: "src/utils.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

interface FileParts {
  readonly stem: string;
  readonly suffixes: string[];
}

function fileParts(filename: string): FileParts {
  const base = filename.replaceAll("\\", "/").split("/").at(-1) ?? "";
  const extension = base.match(/(\.[cm]?[jt]sx?)$/u)?.[1] ?? ".ts";
  const [stem = "", ...suffixes] = base.slice(0, -extension.length).split(".");
  return { stem, suffixes: suffixes.map((suffix) => suffix.toLowerCase()) };
}

function isConventionalFrameworkUtility(filename: string, exported: string): boolean {
  const normalized = filename.replaceAll("\\", "/");
  return exported === "cn" && /(?:^|\/)lib\/utils\.[cm]?[jt]sx?$/u.test(normalized);
}

export default createRule<Options, MessageIds>({
  name: "no-generic-single-export-module",
  documentation: NO_GENERIC_SINGLE_EXPORT_MODULE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Disallow generic module stems when one runtime export already names the responsibility." },
    schema: [],
    messages: {
      genericSingleExport:
        "Module stem `{{stem}}` is generic and its only runtime export is `{{exported}}`; choose a responsibility-bearing module name or colocate the export with its domain.",
    },
  },
  defaultOptions: [],
  create(context) {
    const file = fileParts(context.filename);
    const { stem } = file;
    if (
      !GENERIC_MODULE_STEMS.has(stem) ||
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
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
        const onlyExport = exports.exports[0];
        if (onlyExport === undefined) return;
        const { name: exported, node } = onlyExport;
        if (isConventionalFrameworkUtility(context.filename, exported)) return;
        const exportedRole = exported.replaceAll(/[^a-z0-9]/giu, "").toLowerCase();
        const pathRole = [stem, ...file.suffixes].join("").replaceAll(/[^a-z0-9]/giu, "");
        if (exportedRole === pathRole && file.suffixes.length > 0) return;
        context.report({
          node,
          messageId: "genericSingleExport",
          data: { stem, exported },
        });
      },
    };
  },
});

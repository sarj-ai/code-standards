/**
 * @fileoverview no-generic-single-export-module — generic module stems should not hide a single responsibility.
 *
 * Port of the 18.x `no-generic-single-export-module` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { GENERIC_MODULE_STEMS, isCommonJsExportReference, runtimeExports } from "../utils/runtime-exports.js";

const NAME = "no-generic-single-export-module";

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

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Disallow generic module stems when one runtime export already names the responsibility.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      genericSingleExport:
        "Module stem `{{stem}}` is generic and its only runtime export is `{{exported}}`; choose a responsibility-bearing module name or colocate the export with its domain.",
    },
  },
  createOnce(context) {
    let file: FileParts = { stem: "", suffixes: [] };
    let hasCommonJsExport = false;
    function checkCommonJs(node: ESTree.CallExpression | ESTree.MemberExpression): void {
      if (isCommonJsExportReference(node, context.sourceCode)) hasCommonJsExport = true;
    }
    return {
      before() {
        hasCommonJsExport = false;
        file = fileParts(context.filename);
        const scoped = { filename: context.filename, cwd: context.cwd };
        if (
          !GENERIC_MODULE_STEMS.has(file.stem) ||
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
        const onlyExport = exports.exports[0];
        if (onlyExport === undefined) return;
        const { name: exported, node } = onlyExport;
        if (isConventionalFrameworkUtility(context.filename, exported)) return;
        const { stem } = file;
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

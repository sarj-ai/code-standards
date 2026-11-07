/**
 * @fileoverview no-credential-in-browser-storage — credentials stay out of script-readable browser storage.
 *
 * Port of the 18.x `no-credential-in-browser-storage` rule. Same
 * algorithm; generated files are skipped in `before()`.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { isAuthSecretName, tokenize } from "../utils/secret-names.js";
import { findVariable, scopedStaticString } from "../utils/static-string.js";

const NAME = "no-credential-in-browser-storage";
const STORAGE_NAMES: ReadonlySet<string> = new Set(["localStorage", "sessionStorage"]);
/** Words that make a token-named key pagination, expiry or hint metadata rather than the credential. */
const METADATA_WORDS: ReadonlySet<string> = new Set(["page", "cursor", "next", "hint", "expires", "expiry", "expiration"]);
const GLOBAL_OBJECTS: ReadonlySet<string> = new Set(["window", "globalThis", "self"]);

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Do not write credential-named values to browser storage or script-readable cookies.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noCredentialInBrowserStorage:
        "`{{key}}` names a credential written to script-readable browser storage. Keep it in an httpOnly cookie set by the server or in memory.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    const report = (node: Node, key: string | null): void => {
      if (key !== null && isAuthSecretName(key) && !tokenize(key).some((word) => METADATA_WORDS.has(word))) {
        context.report({ node, messageId: "noCredentialInBrowserStorage", data: { key } });
      }
    };
    return {
      before(): boolean | void {
        sourceCode = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
      },
      CallExpression(node: ESTree.CallExpression): void {
        const callee = unwrapExpression(node.callee);
        if (
          callee.type !== "MemberExpression" ||
          callee.computed ||
          callee.property.type !== "Identifier" ||
          callee.property.name !== "setItem" ||
          !isStorage(sourceCode, callee.object)
        ) {
          return;
        }
        const [key] = node.arguments;
        if (key !== undefined) report(node, scopedStaticString(key, sourceCode));
      },
      AssignmentExpression(node: ESTree.AssignmentExpression): void {
        const target = node.left as Node;
        if (target.type !== "MemberExpression") return;
        if (isStorage(sourceCode, target.object)) {
          report(node, storedPropertyKey(sourceCode, target));
          return;
        }
        if (
          !target.computed &&
          target.property.type === "Identifier" &&
          target.property.name === "cookie" &&
          globalMemberName(sourceCode, target.object) === "document"
        ) {
          report(node, cookieName(node.right));
        }
      },
    };
  },
});

function isStorage(sourceCode: SourceCode, node: Node): boolean {
  const name = globalMemberName(sourceCode, node);
  return name !== null && STORAGE_NAMES.has(name);
}

function globalMemberName(sourceCode: SourceCode, node: Node): string | null {
  const value = unwrapExpression(node);
  if (value.type === "Identifier") return isUnshadowed(sourceCode, value) ? value.name : null;
  if (
    value.type === "MemberExpression" &&
    !value.computed &&
    value.object.type === "Identifier" &&
    GLOBAL_OBJECTS.has(value.object.name) &&
    value.property.type === "Identifier" &&
    isUnshadowed(sourceCode, value.object)
  ) {
    return value.property.name;
  }
  return null;
}

function isUnshadowed(sourceCode: SourceCode, node: Node & { name: string }): boolean {
  const variable = findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

function storedPropertyKey(sourceCode: SourceCode, target: ESTree.MemberExpression): string | null {
  if (!target.computed) return target.property.type === "Identifier" ? target.property.name : null;
  return scopedStaticString(target.property, sourceCode);
}

function cookieName(value: Node): string | null {
  let expression: Node = unwrapExpression(value);
  while (expression.type === "BinaryExpression" && expression.operator === "+") {
    expression = unwrapExpression(expression.left);
  }
  let text: string | null = null;
  if (expression.type === "Literal" && typeof expression.value === "string") text = expression.value;
  if (expression.type === "TemplateLiteral") text = expression.quasis[0]?.value.cooked ?? null;
  if (text === null || !text.includes("=")) return null;
  return text.slice(0, text.indexOf("=")).trim();
}

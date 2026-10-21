/**
 * @fileoverview no-credential-in-browser-storage — credentials stay out of script-readable browser storage.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-credential-in-browser-storage.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { isAuthSecretName, tokenize } from "./_secret-names.js";
import { scopedStaticString } from "./_static-string.js";
import { unwrapExpression } from "./_unwrap-expression.js";

type MessageIds = "noCredentialInBrowserStorage";
type Options = readonly [];

const STORAGE_NAMES: ReadonlySet<string> = new Set(["localStorage", "sessionStorage"]);
/** Words that make a token-named key pagination, expiry or hint metadata rather than the credential. */
const METADATA_WORDS: ReadonlySet<string> = new Set(["page", "cursor", "next", "hint", "expires", "expiry", "expiration"]);
const GLOBAL_OBJECTS: ReadonlySet<string> = new Set(["window", "globalThis", "self"]);

export const NO_CREDENTIAL_IN_BROWSER_STORAGE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Do not write credential-named values to browser storage or script-readable cookies.",
  rationale:
    "localStorage, sessionStorage and cookies written through document.cookie are readable by any script on the origin, so one injected script can copy the credential and replay it elsewhere.",
  remediation:
    "Keep the credential on the server and send it as an httpOnly, Secure, SameSite cookie set by a server response, or hold a short-lived token in memory only.",
  category: "security",
  limitations: [
    "Only static keys and cookie names whose words name an access credential (token, secret, password, jwt, credential, api key) are checked.",
    "Storage wrappers, computed keys and values stored under neutral names are not followed.",
  ],
  examples: [
    {
      id: "server-cookie",
      title: "Store a non-credential preference in localStorage",
      outcome: "no-match",
      files: [{ path: "src/theme.ts", source: "localStorage.setItem(\"sidebar-collapsed\", \"true\");\n" }],
      focusPath: "src/theme.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "token-in-local-storage",
      title: "Do not store an access token in localStorage",
      outcome: "match",
      files: [{
        path: "src/session.ts",
        source: "export function remember(token: string): void {\n  localStorage.setItem(\"accessToken\", token);\n}\n",
      }],
      focusPath: "src/session.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-credential-in-browser-storage",
  documentation: NO_CREDENTIAL_IN_BROWSER_STORAGE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_CREDENTIAL_IN_BROWSER_STORAGE_DOCUMENTATION.summary },
    schema: [],
    messages: {
      noCredentialInBrowserStorage:
        "`{{key}}` names a credential written to script-readable browser storage. Keep it in an httpOnly cookie set by the server or in memory.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    const { sourceCode } = context;
    const report = (node: TSESTree.Node, key: string | null): void => {
      if (key !== null && isAuthSecretName(key) && !tokenize(key).some((word) => METADATA_WORDS.has(word))) {
        context.report({ node, messageId: "noCredentialInBrowserStorage", data: { key } });
      }
    };
    return {
      CallExpression(node): void {
        const callee = unwrapExpression(node.callee);
        if (
          callee.type !== AST_NODE_TYPES.MemberExpression ||
          callee.computed ||
          callee.property.type !== AST_NODE_TYPES.Identifier ||
          callee.property.name !== "setItem" ||
          !isStorage(sourceCode, callee.object)
        ) {
          return;
        }
        const [key] = node.arguments;
        if (key !== undefined) report(node, scopedStaticString(key, sourceCode));
      },
      AssignmentExpression(node): void {
        const target = node.left;
        if (target.type !== AST_NODE_TYPES.MemberExpression) return;
        if (isStorage(sourceCode, target.object)) {
          report(node, storedPropertyKey(sourceCode, target));
          return;
        }
        if (
          !target.computed &&
          target.property.type === AST_NODE_TYPES.Identifier &&
          target.property.name === "cookie" &&
          globalMemberName(sourceCode, target.object) === "document"
        ) {
          report(node, cookieName(node.right));
        }
      },
    };
  },
});

function isStorage(sourceCode: Readonly<TSESLint.SourceCode>, node: TSESTree.Expression): boolean {
  const name = globalMemberName(sourceCode, node);
  return name !== null && STORAGE_NAMES.has(name);
}

function globalMemberName(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Expression,
): string | null {
  const value = unwrapExpression(node);
  if (value.type === AST_NODE_TYPES.Identifier) return isUnshadowed(sourceCode, value) ? value.name : null;
  if (
    value.type === AST_NODE_TYPES.MemberExpression &&
    !value.computed &&
    value.object.type === AST_NODE_TYPES.Identifier &&
    GLOBAL_OBJECTS.has(value.object.name) &&
    value.property.type === AST_NODE_TYPES.Identifier &&
    isUnshadowed(sourceCode, value.object)
  ) {
    return value.property.name;
  }
  return null;
}

function isUnshadowed(sourceCode: Readonly<TSESLint.SourceCode>, node: TSESTree.Identifier): boolean {
  const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

function storedPropertyKey(
  sourceCode: Readonly<TSESLint.SourceCode>,
  target: TSESTree.MemberExpression,
): string | null {
  if (!target.computed) return target.property.type === AST_NODE_TYPES.Identifier ? target.property.name : null;
  return scopedStaticString(target.property, sourceCode);
}

function cookieName(value: TSESTree.Expression): string | null {
  let expression: TSESTree.Node = unwrapExpression(value);
  while (expression.type === AST_NODE_TYPES.BinaryExpression && expression.operator === "+") {
    expression = unwrapExpression(expression.left);
  }
  let text: string | null = null;
  if (expression.type === AST_NODE_TYPES.Literal && typeof expression.value === "string") text = expression.value;
  if (expression.type === AST_NODE_TYPES.TemplateLiteral) text = expression.quasis[0]?.value.cooked ?? null;
  if (text === null || !text.includes("=")) return null;
  return text.slice(0, text.indexOf("=")).trim();
}

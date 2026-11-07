/**
 * @fileoverview no-insecure-random-id — `Math.random()` is predictable, so an id, token or key built from it is guessable.
 *
 * Port of the 18.x `no-insecure-random-id` rule. Untyped.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { existingUuidProviderFix } from "../utils/existing-uuid-provider-fix.js";
import { isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "no-insecure-random-id";

const STRONG_SECURITY_WORDS: ReadonlySet<string> = new Set([
  "apikey",
  "csrf",
  "nonce",
  "otp",
  "password",
  "passwd",
  "pin",
  "salt",
  "secret",
  "token",
  "uuid",
  "verificationcode",
]);

function isStrongSecurityName(name: string): boolean {
  const words = nameWords(name);
  return (
    words.some((word) => STRONG_SECURITY_WORDS.has(word)) ||
    words.some(
      (word, index) =>
        (word === "api" && words[index + 1] === "key") ||
        (word === "auth" && words[index + 1] === "id") ||
        (word === "verification" && words[index + 1] === "code"),
    )
  );
}

function nameWords(name: string): string[] {
  return name
    .replaceAll(/([a-z0-9])([A-Z])/gu, "$1 $2")
    .split(/[^A-Za-z0-9]+/u)
    .filter(Boolean)
    .map((word) => word.toLowerCase());
}

/** Returns true if `node` is a `Math.random()` CallExpression. */
function isMathRandomCall(node: ESTree.CallExpression): boolean {
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") return false;
  const object = unwrapExpression(callee.object);
  return object.type === "Identifier" && object.name === "Math" && getPropertyName(callee) === "random";
}

/** Statements and function boundaries end the search for a name. */
const NAME_BOUNDARIES: ReadonlySet<string> = new Set([
  "ExpressionStatement",
  "IfStatement",
  "ForStatement",
  "WhileStatement",
  "DoWhileStatement",
  "FunctionExpression",
  "ArrowFunctionExpression",
]);

/** Finds the nearest binding or property name without leaving its value. */
function findEnclosingNames(node: Node): string[] {
  const names: string[] = [];
  let directBinding = true;
  for (let current: Node = node, parent = parentOf(node); parent !== null; current = parent, parent = parentOf(current)) {
    if (parent.type === "VariableDeclarator" && parent.init === current) {
      appendDirectBindingName(parent.id, directBinding, names);
      return names;
    }
    if (parent.type === "FunctionDeclaration") {
      appendDirectBindingName(parent.id, directBinding, names);
      return names;
    }
    if (NAME_BOUNDARIES.has(parent.type)) return names;
    directBinding = appendStepName(parent, current, directBinding, names);
  }
  return names;
}

/** Records the name `parent` gives `child`; returns whether the value still is the bound value itself. */
function appendStepName(parent: Node, child: Node, directBinding: boolean, names: string[]): boolean {
  if ((parent.type === "Property" || parent.type === "PropertyDefinition") && parent.value === child) {
    appendPropertyName(parent as ESTree.ObjectProperty | ESTree.PropertyDefinition, names);
    return false;
  }
  if (parent.type === "AssignmentExpression" && parent.right === child && directBinding) appendAssignedName(parent, names);
  return directBinding && parent.type !== "ObjectExpression" && parent.type !== "ArrayExpression";
}

function appendPropertyName(property: ESTree.ObjectProperty | ESTree.PropertyDefinition, names: string[]): void {
  const key = property.key;
  if (!property.computed && key.type === "Identifier") names.push(key.name);
  if (key.type === "Literal" && typeof key.value === "string") names.push(key.value);
}

function appendAssignedName(assignment: ESTree.AssignmentExpression, names: string[]): void {
  const left = assignment.left;
  const name = left.type === "Identifier" ? left.name : left.type === "MemberExpression" ? getPropertyName(left) : null;
  if (name !== null) names.push(name);
}

function appendDirectBindingName(id: Node | null, directBinding: boolean, names: string[]): void {
  if (directBinding && id?.type === "Identifier") names.push(id.name);
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow using `Math.random()` to generate identifiers, tokens, or secrets; use `crypto.randomUUID()` or `crypto.getRandomValues(...)` instead.",
      url: docsUrl(NAME),
    },
    fixable: "code",
    schema: [],
    messages: {
      insecureRandomId:
        "`Math.random()` is not cryptographically secure and is predictable; do not use it to generate IDs, tokens, or secrets. Use `crypto.randomUUID()` or `crypto.getRandomValues(...)` instead.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    return {
      before() {
        sourceCode = context.sourceCode;
        return !isTestFile({ filename: context.filename, cwd: context.cwd });
      },
      CallExpression(node) {
        if (!isMathRandomCall(node)) return;
        if ((findVariable(sourceCode.getScope(node), "Math")?.defs.length ?? 0) > 0) return;
        if (!findEnclosingNames(node).some(isStrongSecurityName)) return;
        const fix = existingUuidProviderFix(sourceCode, node, "recipe");
        context.report(fix === null ? { node, messageId: "insecureRandomId" } : { node, messageId: "insecureRandomId", fix });
      },
    };
  },
});

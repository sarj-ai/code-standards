/**
 * @fileoverview no-unsafe-test-double-cast — keep mock-backed test doubles inside collaborator contracts.
 *
 * Port of the 18.x `no-unsafe-test-double-cast` rule. The rule is untyped, so the port
 * covers all of it.
 *
 * Under Oxlint the original never offers its fix: it requires `declaration.id.typeAnnotation ===
 * undefined`, and Oxlint passes `null` for an absent field. The port accepts both, so the fix
 * matches ESLint.
 */

import type { FixFn as ReportFix } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { getPropertyName } from "../utils/static-string.js";
import { importedTestMockNamespace, isUnshadowedTestMockGlobal } from "../utils/test-mock-provenance.js";
import { retainsNamedTypeUses } from "../utils/type-binding.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

const NAME = "no-unsafe-test-double-cast";

const MOCK_FACTORIES: ReadonlySet<string> = new Set(["fn", "spyOn"]);
const SIMPLE_LITERAL_TYPES: ReadonlySet<string> = new Set(["string", "number", "boolean", "bigint"]);

function containsMockFactory(node: Node, source: SourceCode): boolean {
  node = unwrapExpression(node);
  if (isMockFactory(node, source)) return true;
  if (node.type === "ObjectExpression") {
    return node.properties.some((property) =>
      property.type === "Property"
        ? containsMockFactory(property.value, source)
        : containsMockFactory(property.argument, source));
  }
  if (node.type === "ArrayExpression") {
    return node.elements.some((element) => element !== null && containsMockFactory(element, source));
  }
  return false;
}

function isMockFactory(node: Node, source: SourceCode): boolean {
  if (node.type !== "CallExpression") return false;
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") return false;
  const receiver = unwrapExpression(callee.object);
  return receiver.type === "Identifier" &&
    (importedTestMockNamespace(source, receiver) !== null || isUnshadowedTestMockGlobal(source, receiver)) &&
    MOCK_FACTORIES.has(getPropertyName(callee) ?? "");
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Disallow mock-backed test doubles that bypass collaborator contracts through double assertions.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { noUnsafeTestDoubleCast: "This mock-backed partial object bypasses the collaborator contract through `unknown`. Use a narrow injected port and typed recording fake, or make the fixture satisfy the real contract." },
  },
  createOnce(context) {
    function check(node: ESTree.TSAsExpression | ESTree.TSTypeAssertion): void {
      const sourceCode = context.sourceCode;
      if ((node.expression.type === "TSAsExpression" || node.expression.type === "TSTypeAssertion") && node.expression.typeAnnotation.type === "TSUnknownKeyword" && containsMockFactory(node.expression.expression, sourceCode)) {
        const fix = privateMockObjectFix(sourceCode, node, context.filename);
        context.report({ node, messageId: "noUnsafeTestDoubleCast", ...(fix !== null && { fix }) });
      }
    }
    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        return undefined;
      },
      TSAsExpression: check,
      TSTypeAssertion: check,
    };
  },
});

function privateMockObjectFix(
  sourceCode: SourceCode,
  node: ESTree.TSAsExpression | ESTree.TSTypeAssertion,
  filename: string,
): ReportFix | null {
  const declaration = parentOf(node);
  const inner = node.expression;
  if ((inner.type !== "TSAsExpression" && inner.type !== "TSTypeAssertion") ||
    declaration?.type !== "VariableDeclarator" || declaration.init !== node ||
    declaration.id.type !== "Identifier" || isPresent(declaration.id.typeAnnotation) ||
    (parentOf(declaration) as ESTree.VariableDeclaration | null)?.kind !== "const" || !isUnusedPrivateBinding(sourceCode, declaration, declaration.id, filename) ||
    sourceCode.getCommentsInside(node).length > 0 || !simpleMockObject(inner.expression, sourceCode) ||
    !retainsNamedTypeUses(sourceCode, node.typeAnnotation)) return null;
  const expression = sourceCode.getText(inner.expression);
  const expressionNewlines = expression.replace(/[^\r\n]/gu, "");
  const removedNewlines = sourceCode.getText(node).replace(/[^\r\n]/gu, "").slice(expressionNewlines.length);
  const replacement = expression + removedNewlines;
  return (fixer) => fixer.replaceText(node, replacement);
}

function simpleMockObject(node: Node, sourceCode: SourceCode): boolean {
  if (node.type !== "ObjectExpression") return false;
  return node.properties.every((property) => {
    if (property.type !== "Property" || property.computed || property.method || property.kind !== "init") return false;
    const value = property.value;
    if (value.type === "Literal") return value.value === null ||
      SIMPLE_LITERAL_TYPES.has(typeof value.value);
    if (value.type === "ObjectExpression") return simpleMockObject(value, sourceCode);
    return value.type === "CallExpression" && !value.optional && value.arguments.length === 0 &&
      !isPresent(value.typeArguments) && value.callee.type === "MemberExpression" && !value.callee.optional &&
      getPropertyName(value.callee) === "fn" && isMockFactory(value, sourceCode);
  });
}

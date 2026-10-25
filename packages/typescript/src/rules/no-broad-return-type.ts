/**
 * @fileoverview no-broad-return-type — Report explicit broad return annotations that erase a known return value.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-broad-return-type.test.ts
 */
import {
  AST_NODE_TYPES,
  ESLintUtils,
  type TSESTree,
} from "@typescript-eslint/utils";
import ts from "typescript";
import { retainsNamedTypeUses } from "./_type-binding.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isUnusedPrivateBinding } from "./_unused-private-binding.js";
import { isGeneratedFile } from "./_paths.js";

export const NO_BROAD_RETURN_TYPE_DOCUMENTATION = {
  summary:
    "Report explicit broad return annotations that erase a known return value.",
  rationale:
    "An unknown, object, or unknown-valued dictionary return hides fields that the implementation already knows.",
  remediation:
    "Return the existing domain type or retain the inferred return contract. Keep unknown at unparsed input boundaries.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Requires TypeScript type information and an implemented function with an explicit return annotation. Checks unknown, object, and unknown-valued index-only dictionaries, including aliases and Promise results.",
    "Unparsed unknown/any values, generics, empty object literals, and declaration-only signatures are excluded. Parameter contracts are not inferred from names. Intentional opaque return boundaries require an explained local suppression. Automatic fixes remove the annotation only from an unused private function declaration in a module or block; referenced and public contracts remain manual.",
  ],
  examples: [
    {
      id: "before",
      title: "Preserve the explicit contract",
      outcome: "match",
      files: [
        {
          path: "src/example.ts",
          source:
            "type Invoice = { reference: string; total: number };\nfunction toRequest(invoice: Invoice): Record<string, unknown> { return invoice; }",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "after",
      title: "Use the direct contract",
      outcome: "no-match",
      files: [
        {
          path: "src/example.ts",
          source:
            "type Invoice = { reference: string; total: number };\nfunction toRequest(invoice: Invoice): Invoice { return invoice; }",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; function request(value: { id: string }): unknown { return value; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; function request(value: { id: string }) { return value; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

type FunctionNode =
  | TSESTree.ArrowFunctionExpression
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression;
interface ReturnFrame {
  readonly node: FunctionNode;
  readonly annotation: TSESTree.TSTypeAnnotation | undefined;
  known: boolean;
  opaque: boolean;
}

function isBroad(type: ts.Type, checker: ts.TypeChecker): boolean {
  if ((type.flags & (ts.TypeFlags.Unknown | ts.TypeFlags.NonPrimitive)) !== 0)
    return true;
  const indexes = checker.getIndexInfosOfType(type);
  return (
    indexes.length > 0 &&
    type.getProperties().length === 0 &&
    indexes.every((index) => (index.type.flags & ts.TypeFlags.Unknown) !== 0)
  );
}

function hasKnownContract(type: ts.Type, checker: ts.TypeChecker): boolean {
  if (type.isUnion())
    return type.types.every((part) => hasKnownContract(part, checker));
  const excluded =
    ts.TypeFlags.Any |
    ts.TypeFlags.Unknown |
    ts.TypeFlags.Never |
    ts.TypeFlags.TypeParameter |
    ts.TypeFlags.Conditional |
    ts.TypeFlags.IndexedAccess |
    ts.TypeFlags.Substitution |
    ts.TypeFlags.Null |
    ts.TypeFlags.Undefined |
    ts.TypeFlags.Void;
  if ((type.flags & excluded) !== 0 || isBroad(type, checker)) return false;
  return (
    (type.flags & ts.TypeFlags.Object) === 0 || type.getProperties().length > 0
  );
}

function isOpaque(type: ts.Type, checker: ts.TypeChecker): boolean {
  if (type.isUnion()) return type.types.some((part) => isOpaque(part, checker));
  return (
    (type.flags &
      (ts.TypeFlags.Any |
        ts.TypeFlags.Unknown |
        ts.TypeFlags.TypeParameter |
        ts.TypeFlags.Conditional |
        ts.TypeFlags.IndexedAccess |
        ts.TypeFlags.Substitution)) !==
      0 || isBroad(type, checker)
  );
}

export default createRule<[], "avoid">({
  name: "no-broad-return-type",
  documentation: NO_BROAD_RETURN_TYPE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: NO_BROAD_RETURN_TYPE_DOCUMENTATION.summary },
    schema: [],
    messages: {
      avoid:
        "This return annotation erases a known value's contract. Return the domain type or retain inference; preserve unknown only at an intentional opaque boundary.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    if (
      !context.sourceCode.parserServices?.program ||
      !context.sourceCode.parserServices.esTreeNodeToTSNodeMap
    )
      return {};
    const services = ESLintUtils.getParserServices(context);
    if (!services.program) return {};
    const checker = services.program.getTypeChecker();
    const frames: ReturnFrame[] = [];
    const valueType = (node: TSESTree.Node): ts.Type => {
      const type = checker.getTypeAtLocation(
        services.esTreeNodeToTSNodeMap.get(node),
      );
      return (type.flags & ts.TypeFlags.TypeParameter) !== 0
        ? type
        : (checker.getAwaitedType(type) ?? type);
    };
    const inspectReturn = (value: TSESTree.Expression): void => {
      const frame = frames.at(-1);
      if (!frame?.annotation) return;
      const type = valueType(value);
      frame.known ||= hasKnownContract(type, checker);
      frame.opaque ||= isOpaque(type, checker);
    };
    const enter = (node: FunctionNode): void => {
      const annotation = node.returnType;
      frames.push({
        node,
        annotation:
          !node.typeParameters &&
          annotation &&
          isBroad(valueType(annotation.typeAnnotation), checker)
            ? annotation
            : undefined,
        known: false,
        opaque: false,
      });
      if (node.body && node.body.type !== AST_NODE_TYPES.BlockStatement)
        inspectReturn(node.body);
    };
    const leave = (): void => {
      const frame = frames.pop();
      if (frame?.annotation && frame.known && !frame.opaque) {
        const annotation = frame.annotation;
        const node = frame.node;
        const canFix = node.type === AST_NODE_TYPES.FunctionDeclaration && node.id !== null &&
          isUnusedPrivateBinding(context.sourceCode, node, node.id, context.filename) &&
          context.sourceCode.getCommentsInside(annotation).length === 0 &&
          retainsNamedTypeUses(context.sourceCode, annotation);
        context.report({ node: annotation, messageId: "avoid", fix: canFix ? (fixer) => fixer.replaceText(annotation, context.sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")) : null });
      }
    };
    return {
      FunctionDeclaration: enter,
      FunctionExpression: enter,
      ArrowFunctionExpression: enter,
      "FunctionDeclaration:exit": leave,
      "FunctionExpression:exit": leave,
      "ArrowFunctionExpression:exit": leave,
      ReturnStatement(node): void {
        if (node.argument) inspectReturn(node.argument);
      },
    };
  },
});

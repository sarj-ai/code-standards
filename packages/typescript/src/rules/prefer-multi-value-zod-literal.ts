/**
 * @fileoverview prefer-multi-value-zod-literal — use the Zod 4 multi-value literal API instead of a union of literal schemas.
 *
 * Port of the 18.x `prefer-multi-value-zod-literal` rule. Same
 * algorithm; test and generated files are skipped and per-file bindings are
 * reset in `before()`.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "prefer-multi-value-zod-literal";

type Identifier = Extract<Node, { type: "Identifier" }>;

function isStaticPrimitive(
  node: Node,
  sourceCode: SourceCode,
): boolean {
  node = unwrapExpression(node);
  if (node.type === "Literal") {
    return (
      node.value === null ||
      ["bigint", "boolean", "number", "string"].includes(typeof node.value)
    );
  }
  if (
    node.type === "TemplateLiteral" &&
    node.expressions.length === 0
  )
    return true;
  if (node.type === "Identifier" && node.name === "undefined") {
    const binding = findVariable(
      sourceCode.getScope(node),
      node.name,
    );
    return binding === null || binding.defs.length === 0;
  }
  return (
    node.type === "UnaryExpression" &&
    node.operator === "-" &&
    node.argument.type === "Literal" &&
    ["bigint", "number"].includes(typeof node.argument.value)
  );
}

function isStaticString(node: Node): boolean {
  node = unwrapExpression(node);
  return (
    (node.type === "Literal" && typeof node.value === "string") ||
    (node.type === "TemplateLiteral" &&
      node.expressions.length === 0)
  );
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "suggestion",
    docs: {
      description:
        "Use the Zod 4 multi-value literal API instead of a union of literal schemas.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          zodMajorVersion: { description: "Installed Zod major version used to validate multi-value literal support.", type: "integer", minimum: 4, maximum: 4 },
        },
      },
    ],
    messages: {
      useMultiValueLiteral:
        "Replace this literal-schema union with {{zod}}.literal([…]).",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let options: { zodMajorVersion?: 4 } | undefined;
    const zodBindings = new Set<TsVariable>();
    const zod4Bindings = new Set<TsVariable>();

    function resolvedBinding(
      identifier: Identifier,
    ): TsVariable | null {
      return findVariable(
        sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function primitiveLiteralValues(
      argument: ESTree.ArrayExpression,
      binding: TsVariable,
    ): Node[] | null {
      const values: Node[] = [];
      for (const writtenElement of argument.elements) {
        const element =
          writtenElement === null ? null : unwrapExpression(writtenElement);
        if (
          element === null ||
          element.type !== "CallExpression" ||
          !directMemberCall(element, binding, "literal") ||
          element.arguments.length !== 1
        )
          return null;
        const [value] = element.arguments;
        if (value === undefined || !isStaticPrimitive(value, sourceCode))
          return null;
        values.push(value);
      }
      return values;
    }

    function directMemberCall(
      node: ESTree.CallExpression,
      binding: TsVariable,
      method: string,
    ): boolean {
      const callee = unwrapExpression(node.callee);
      if (callee.type !== "MemberExpression" || getPropertyName(callee) !== method) return false;
      const receiver = unwrapExpression(callee.object);
      return receiver.type === "Identifier" && resolvedBinding(receiver) === binding;
    }

    /** The Zod namespace binding `receiver` names, when that Zod has the multi-value literal API. */
    function zod4Binding(receiver: Identifier): TsVariable | null {
      const binding = resolvedBinding(receiver);
      return binding !== null && zodBindings.has(binding) && (options?.zodMajorVersion === 4 || zod4Bindings.has(binding))
        ? binding
        : null;
    }

    return {
      before(): boolean | void {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        sourceCode = context.sourceCode;
        [options] = context.options as unknown as readonly [{ zodMajorVersion?: 4 }?];
        zodBindings.clear();
        zod4Bindings.clear();
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        const isExplicitV4 = /^zod\/v4(?:$|[-/])/.test(node.source.value);
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportDefaultSpecifier" ||
            specifier.type === "ImportNamespaceSpecifier" ||
            (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "z")
          ) {
            const binding = resolvedBinding(specifier.local);
            if (binding === null) continue;
            zodBindings.add(binding);
            if (isExplicitV4) zod4Bindings.add(binding);
          }
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "MemberExpression" || getPropertyName(callee) !== "union" || node.arguments.length !== 1) return;
        const receiver = unwrapExpression(callee.object);
        const [written] = node.arguments;
        const argument = written === undefined ? undefined : unwrapExpression(written);
        if (receiver.type !== "Identifier" || argument?.type !== "ArrayExpression" || argument.elements.length < 2) return;
        const binding = zod4Binding(receiver);
        if (binding === null) return;
        const values = primitiveLiteralValues(argument, binding);
        if (values === null || values.every(isStaticString)) return;
        context.report({
          node,
          messageId: "useMultiValueLiteral",
          data: { zod: receiver.name },
        });
      },
    };
  },
});

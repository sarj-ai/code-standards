/**
 * @fileoverview require-assert-never — a switch over a union whose `default` does no runtime work stops being exhaustive the day the union grows.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-assert-never.test.ts
 */



import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode } from "@oxlint/plugins";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import {
  isGlobalReference,
  resolveVariable,
  unwrapExpression,
} from "./_scope.js";

type MessageIds = "missingAssertNever";
type Options = readonly [];

export const REQUIRE_ASSERT_NEVER_DOCUMENTATION = {
  summary:
    "Require an empty switch default to call `assertNever` so discriminated unions remain exhaustive at compile time.",
  rationale:
    "An empty default silently accepts new union members instead of making the compiler identify the missing case.",
  remediation:
    "Call `assertNever` with the discriminant in the exhaustive switch default.",
  category: "correctness",
  limitations: [
    "Only explicit same-file literal unions or discriminated object unions are checked, with literal cases or immutable local literal aliases covering every declared member. Imported unions, enums, inference, and control-flow narrowing are not resolved. Any runtime handling or documented intentional no-op is accepted; helper signatures are not checked.",
  ],
  examples: [
    {
      id: "assert-never-default",
      title: "Make the default exhaustive",
      outcome: "no-match",
      files: [
        {
          path: "src/render.ts",
          source:
            "declare const kind: 'a' | 'b';\nswitch (kind) { case 'a': break; case 'b': break; default: assertNever(kind); }",
        },
      ],
      focusPath: "src/render.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "empty-default",
      title: "Do not leave an exhaustive default empty",
      outcome: "match",
      files: [
        {
          path: "src/render.ts",
          source:
            "declare const kind: 'a' | 'b';\nswitch (kind) { case 'a': break; case 'b': break; default: }",
        },
      ],
      focusPath: "src/render.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

/** Empty statements and empty blocks are not runtime handling. */
const isRuntimeHandlingStatement = (statement: ESTree.Statement): boolean => {
  if (statement.type === "EmptyStatement") return false;
  if (statement.type === "BreakStatement") {
    return statement.label !== null;
  }
  if (
    statement.type === "TSTypeAliasDeclaration" ||
    statement.type === "TSInterfaceDeclaration"
  ) {
    return false;
  }
  if (statement.type === "BlockStatement") {
    return statement.body.some(isRuntimeHandlingStatement);
  }
  return true;
};

/** An empty non-final default falls through to a case that handles it. */
const isFallthroughDefault = (
  node: ESTree.SwitchStatement,
  defaultIndex: number,
): boolean => {
  const defaultCase = node.cases[defaultIndex];
  return (
    defaultCase !== undefined &&
    defaultCase.consequent.length === 0 &&
    defaultIndex < node.cases.length - 1
  );
};

/** Honor a comment that makes an empty default an intentional no-op. */
const isCommentOnlyNoopDefault = (
  defaultCase: ESTree.SwitchCase,
  sourceCode: SourceCode,
): boolean => {
  if (defaultCase.consequent.length === 0) {
    const defaultToken = sourceCode.getFirstToken(defaultCase);
    const colonToken = defaultToken
      ? sourceCode.getTokenAfter(defaultToken)
      : null;
    return (
      colonToken !== null && sourceCode.getCommentsAfter(colonToken).length > 0
    );
  }
  const only = defaultCase.consequent[0];
  if (
    only !== undefined &&
    defaultCase.consequent.length === 1 &&
    only.type === "BlockStatement" &&
    !only.body.some(isRuntimeHandlingStatement)
  ) {
    return sourceCode.getCommentsInside(only).length > 0;
  }
  return false;
};

function literalKey(node: ESTree.Node): string | null {
  if (node.type === "Literal") {
    if (node.value === null) return "null";
    if (["string", "number", "boolean", "bigint"].includes(typeof node.value))
      return `${typeof node.value}:${String(node.value)}`;
  }
  if (
    node.type === "UnaryExpression" &&
    (node.operator === "-" || node.operator === "+") &&
    node.argument.type === "Literal" &&
    typeof node.argument.value === "number"
  ) {
    return `number:${node.operator === "-" ? -node.argument.value : node.argument.value}`;
  }
  return null;
}

function finiteType(
  source: SourceCode,
  type: ESTree.TSType,
  property: string | null = null,
  seen = new Set<ESTree.Node>(),
): Set<string> | null {
  if (seen.has(type)) return null;
  seen.add(type);
  const resolved = localType(source, type);
  if (resolved === null) return null;
  if (resolved.type === "TSUnionType") {
    const values = new Set<string>();
    for (const member of resolved.types) {
      const domain = finiteType(source, member, property, new Set(seen));
      if (domain === null) return null;
      for (const value of domain) values.add(value);
    }
    return values;
  }
  if (property !== null)
    return finitePropertyType(source, resolved, property, seen);
  if (resolved.type === "TSLiteralType") {
    const key = literalKey(resolved.literal);
    return key === null ? null : new Set([key]);
  }
  return resolved.type === "TSNullKeyword"
    ? new Set(["null"])
    : resolved.type === "TSUndefinedKeyword"
      ? new Set(["undefined"])
      : null;
}

function localType(
  source: SourceCode,
  type: ESTree.TSType,
  seen = new Set<ESTree.Node>(),
): ESTree.TSType | ESTree.TSInterfaceDeclaration | null {
  if (seen.has(type)) return null;
  seen.add(type);
  if (type.type !== "TSTypeReference") return type;
  if (type.typeName.type !== "Identifier" || type.typeArguments?.params.length)
    return null;
  const defs = resolveVariable(source, type.typeName)?.defs;
  if (defs?.length !== 1) return null;
  const declaration = defs[0]?.node;
  if (
    declaration?.type === "TSTypeAliasDeclaration" &&
    !declaration.typeParameters
  )
    return localType(source, declaration.typeAnnotation, seen);
  return declaration?.type === "TSInterfaceDeclaration" &&
    !declaration.typeParameters &&
    !declaration.extends.length
    ? declaration
    : null;
}

function finitePropertyType(
  source: SourceCode,
  resolved: ESTree.TSType | ESTree.TSInterfaceDeclaration,
  property: string,
  seen: Set<ESTree.Node>,
): Set<string> | null {
    const members =
      resolved.type === "TSTypeLiteral"
        ? resolved.members
        : resolved.type === "TSInterfaceDeclaration"
          ? resolved.body.body
          : [];
    const field = members.find(
      (member) =>
        member.type === "TSPropertySignature" &&
        !member.computed &&
        member.key.type === "Identifier" &&
        member.key.name === property,
    );
    return field?.type === "TSPropertySignature" &&
      field.typeAnnotation &&
      !field.optional
      ? finiteType(
          source,
          field.typeAnnotation.typeAnnotation,
          null,
          new Set(seen),
        )
      : null;
}

function caseKey(node: ESTree.Expression, source: SourceCode): string | null {
  const expression = unwrapExpression(node);
  const direct = literalKey(expression);
  if (direct !== null) return direct;
  if (expression.type !== "Identifier") return null;
  if (
    expression.name === "undefined" &&
    isGlobalReference(source, expression, "undefined")
  )
    return "undefined";
  const variable = resolveVariable(source, expression);
  if (
    variable?.defs.length !== 1 ||
    variable.references.some(
      (reference) => reference.isWrite() && !reference.init,
    )
  )
    return null;
  const declaration = variable.defs[0]?.node;
  return declaration?.type === "VariableDeclarator" &&
    declaration.parent.type === "VariableDeclaration" &&
    declaration.parent.kind === "const" &&
    declaration.init
    ? literalKey(unwrapExpression(declaration.init))
    : null;
}

function isExhaustiveFiniteSwitch(
  node: ESTree.SwitchStatement,
  source: SourceCode,
): boolean {
  const expected = discriminantDomain(node.discriminant, source);
  if (
    expected === null ||
    expected.size < 2 ||
    [...expected].every((key) => key.startsWith("boolean:"))
  )
    return false;
  const handled = new Set(
    node.cases.flatMap((item) =>
      item.test ? [caseKey(item.test, source)] : [],
    ),
  );
  return [...expected].every((key) => handled.has(key));
}

function discriminantDomain(
  node: ESTree.Expression,
  source: SourceCode,
): Set<string> | null {
  const expression = unwrapExpression(node);
  const identifier =
    expression.type === "Identifier"
      ? expression
      : expression.type === "MemberExpression" &&
          !expression.computed &&
          expression.object.type === "Identifier" &&
          expression.property.type === "Identifier"
        ? expression.object
        : null;
  if (identifier === null) return null;
  const defs = resolveVariable(source, identifier)?.defs;
  if (defs?.length !== 1 || !defs[0]?.name.typeAnnotation) return null;
  const property =
    expression.type === "MemberExpression" &&
    expression.property.type === "Identifier"
      ? expression.property.name
      : null;
  return finiteType(
    source,
    defs[0].name.typeAnnotation.typeAnnotation,
    property,
  );
}

export default createRule<Options, MessageIds>({
  name: "require-assert-never",
  documentation: REQUIRE_ASSERT_NEVER_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Require an empty switch default to call `assertNever` so discriminated unions remain exhaustive at compile time.",
    },
    schema: [],
    messages: {
      missingAssertNever:
        "Empty switch `default` case — add runtime handling or call `assertNever()` so the discriminated union is exhaustively checked at compile time.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};

    return {
      SwitchStatement(node: ESTree.SwitchStatement): void {
        const defaultIndex = node.cases.findIndex(
          (caseNode) => caseNode.test === null,
        );
        // Only present no-op defaults opt into this syntactic check.
        if (defaultIndex === -1) return;
        const defaultCase = node.cases[defaultIndex];
        if (defaultCase === undefined) return;

        // Any runtime work, including assertNever(), handles the default.
        if (defaultCase.consequent.some(isRuntimeHandlingStatement)) return;

        // A non-final empty default is handled by its following case.
        if (isFallthroughDefault(node, defaultIndex)) return;

        // Comments distinguish deliberate no-ops without requiring type info.
        if (isCommentOnlyNoopDefault(defaultCase, context.sourceCode)) return;
        if (!isExhaustiveFiniteSwitch(node, context.sourceCode)) return;

        context.report({
          node: defaultCase,
          messageId: "missingAssertNever",
        });
      },
    };
  },
});

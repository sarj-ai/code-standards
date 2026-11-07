/**
 * @fileoverview prefer-nominal-id-types — distinguish identifier roles at callable boundaries.
 *
 * Port of the 18.x `prefer-nominal-id-types` rule. The rule is untyped.
 * The original only follows a type alias whose `typeParameters` is
 * `undefined`; Oxlint gives null there, so under Oxlint the original never
 * resolves an alias to its primitive carrier. This port accepts null and
 * undefined, which matches the original under ESLint.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-nominal-id-types.test.ts
 */

import { defineRule, type Context, type ESTree, type Node, type Scope, type TsDefinition } from "../types.js";
import { tsVariable } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { existingOverloadBrandFix } from "./_existing-overload-brand-fix.js";

const NAME = "prefer-nominal-id-types";

type Carrier = "string" | "number" | "string[]" | "number[]";
type Boundary = Node & { readonly params: readonly Node[] };
type Identifier = Extract<Node, { type: "Identifier" }>;

const OPERATIONAL_ROLES: ReadonlySet<string> = new Set([
  "request",
  "trace",
  "span",
  "correlation",
  "process",
  "thread",
  "timeout",
  "interval",
]);
const MAX_ALIAS_DEPTH = 16;
const ARRAY_TYPE_NAMES: ReadonlySet<string> = new Set(["Array", "ReadonlyArray"]);

function arrayCarrier(carrier: Carrier | undefined): Carrier | undefined {
  if (carrier === "string") return "string[]";
  if (carrier === "number") return "number[]";
  return undefined;
}

function isNullish(node: Node): boolean {
  return (
    node.type === "TSUndefinedKeyword" ||
    node.type === "TSNullKeyword" ||
    (node.type === "TSLiteralType" &&
      node.literal.type === "Literal" &&
      node.literal.value === null)
  );
}

function referenceCarrier(
  node: ESTree.TSTypeReference,
  context: Context,
  depth: number,
): Carrier | undefined {
  if (node.typeName.type !== "Identifier") return undefined;
  const definitions = typeDefinitions(node, context);
  const args = node.typeArguments?.params;
  if (
    definitions.length === 0 &&
    ARRAY_TYPE_NAMES.has(node.typeName.name) &&
    args?.length === 1
  ) {
    return arrayCarrier(rawCarrier(args[0], context, depth + 1));
  }
  if (args !== undefined || definitions.length !== 1) return undefined;
  const declaration = definitions[0]?.node;
  if (
    declaration?.type !== "TSTypeAliasDeclaration" ||
    isPresent(declaration.typeParameters)
  )
    return undefined;
  return rawCarrier(declaration.typeAnnotation, context, depth + 1);
}

function typeDefinitions(
  node: ESTree.TSTypeReference,
  context: Context,
): readonly TsDefinition[] {
  if (node.typeName.type !== "Identifier") return [];
  let scope: Scope | null = context.sourceCode.getScope(node);
  while (scope !== null) {
    const found = scope.set.get(node.typeName.name);
    const variable = found === undefined ? undefined : tsVariable(found);
    const definitions =
      variable?.defs.filter((definition) => definition.isTypeDefinition) ?? [];
    if (definitions.length > 0 || variable?.isTypeVariable === true)
      return definitions;
    scope = scope.upper;
  }
  return [];
}

function rawCarrier(
  node: Node | undefined,
  context: Context,
  depth = 0,
): Carrier | undefined {
  if (node === undefined || depth >= MAX_ALIAS_DEPTH) return undefined;
  switch (node.type) {
    case "TSStringKeyword":
      return "string";
    case "TSNumberKeyword":
      return "number";
    case "TSArrayType":
      return arrayCarrier(rawCarrier(node.elementType, context, depth + 1));
    case "TSTypeOperator":
      return node.operator === "readonly"
        ? rawCarrier(node.typeAnnotation, context, depth + 1)
        : undefined;
    case "TSUnionType": {
      const members = node.types.filter((member) => !isNullish(member));
      if (members.length !== 1) return undefined;
      return rawCarrier(members[0], context, depth + 1);
    }
    case "TSTypeReference":
      return referenceCarrier(node, context, depth);
    default:
      return undefined;
  }
}

function checkBoundary(node: Boundary, context: Context): void {
  const roles = new Map<Carrier, string>();
  for (const parameter of node.params) {
    const identifier = parameterIdentifier(parameter);
    if (identifier === undefined || !isPresent(identifier.typeAnnotation)) continue;
    const role = identifierRole(identifier.name);
    if (role === undefined) continue;
    const carrier = rawCarrier(
      identifier.typeAnnotation.typeAnnotation,
      context,
    );
    if (
      carrier === undefined ||
      (/(?:Ids|_ids)$/u.test(identifier.name) && !carrier.endsWith("[]"))
    )
      continue;
    const previous = roles.get(carrier);
    if (previous !== undefined && previous !== role) {
      const fix = existingOverloadBrandFix(context.sourceCode, node);
      context.report({
        node: identifier,
        messageId: "preferNominalIds",
        ...(fix !== null && { fix }),
      });
      return;
    }
    roles.set(carrier, role);
  }
}

function identifierRole(name: string): string | undefined {
  const match = /^(.*?)(?:Ids?|_ids?)$/u.exec(name);
  const stem = match?.[1];
  if (stem === undefined || stem.length === 0) return undefined;
  const role = stem.replaceAll("_", "").toLowerCase();
  return OPERATIONAL_ROLES.has(role) ? undefined : role;
}

function parameterIdentifier(parameter: Node): Identifier | undefined {
  if (parameter.type === "Identifier") return parameter;
  if (
    parameter.type === "AssignmentPattern" &&
    parameter.left.type === "Identifier"
  )
    return parameter.left;
  if (parameter.type === "TSParameterProperty")
    return parameterIdentifier(parameter.parameter);
  return undefined;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Distinguish identifier roles sharing primitive types at callable boundaries.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferNominalIds:
        "Distinct identifier roles share an interchangeable primitive type. Use distinct branded identifier types at this callable boundary.",
    },
  },
  createOnce(context) {
    const check = (node: Boundary): void => checkBoundary(node, context);
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      ArrowFunctionExpression: check,
      FunctionDeclaration: check,
      FunctionExpression: check,
      TSDeclareFunction: check,
      TSEmptyBodyFunctionExpression: check,
      TSCallSignatureDeclaration: check,
      TSConstructSignatureDeclaration: check,
      TSConstructorType: check,
      TSFunctionType: check,
      TSMethodSignature: check,
    };
  },
});

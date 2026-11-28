/** @fileoverview _nominal-id-roles — share identifier roles and primitive carriers across nominal-ID rules. */

import { tsVariable, type Context, type ESTree, type Node, type Scope, type TsDefinition } from "../types.js";
import { isPresent } from "../utils/is-present.js";

export type Carrier = "string" | "number" | "string[]" | "number[]";

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

export function rawCarrier(
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

export function identifierRole(name: string): string | undefined {
  const match = /^(.*?)(?:Ids?|_ids?)$/u.exec(name);
  const stem = match?.[1];
  if (stem === undefined || stem.length === 0) return undefined;
  const role = stem.replaceAll("_", "").toLowerCase();
  return OPERATIONAL_ROLES.has(role) ? undefined : role;
}

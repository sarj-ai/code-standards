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

import { defineRule, type Context, type Node } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { existingOverloadBrandFix } from "./_existing-overload-brand-fix.js";
import { identifierRole, rawCarrier, type Carrier } from "./_nominal-id-roles.js";

const NAME = "prefer-nominal-id-types";

type Boundary = Node & { readonly params: readonly Node[] };
type Identifier = Extract<Node, { type: "Identifier" }>;

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

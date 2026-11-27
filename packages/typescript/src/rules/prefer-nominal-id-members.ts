/** @fileoverview prefer-nominal-id-members — distinguish identifier roles in object types. */

import { defineRule, type Context, type ESTree, type Node } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { identifierRole, rawCarrier, type Carrier } from "./_nominal-id-roles.js";

const NAME = "prefer-nominal-id-members";

function checkMembers(members: readonly Node[], context: Context): void {
  const roles = new Map<Carrier, string>();
  for (const member of members) {
    if (
      member.type !== "TSPropertySignature" &&
      member.type !== "PropertyDefinition" &&
      member.type !== "TSAbstractPropertyDefinition" &&
      member.type !== "AccessorProperty" &&
      member.type !== "TSAbstractAccessorProperty"
    ) continue;
    if (member.computed || !isPresent(member.typeAnnotation)) continue;

    const name = memberName(member.key);
    if (name === undefined) continue;

    const role = identifierRole(name);
    if (role === undefined) continue;
    const carrier = rawCarrier(member.typeAnnotation.typeAnnotation, context);
    if (carrier === undefined || (/(?:Ids|_ids)$/u.test(name) && !carrier.endsWith("[]"))) continue;

    const previous = roles.get(carrier);
    if (previous !== undefined && previous !== role) {
      context.report({ node: member, messageId: "preferNominalIdMembers" });
      return;
    }
    roles.set(carrier, role);
  }
}

function memberName(key: Node): string | undefined {
  if (key.type === "Identifier") return key.name;
  return key.type === "Literal" && typeof key.value === "string" ? key.value : undefined;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Distinguish identifier roles sharing primitive types in object types.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferNominalIdMembers:
        "Distinct identifier roles share an interchangeable primitive type in this object type. Parse them with distinct branded Zod schemas.",
    },
  },
  createOnce(context) {
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      TSInterfaceBody(node: ESTree.TSInterfaceBody) {
        checkMembers(node.body, context);
      },
      TSTypeLiteral(node: ESTree.TSTypeLiteral) {
        checkMembers(node.members, context);
      },
      ClassBody(node: ESTree.ClassBody) {
        checkMembers(node.body, context);
      },
    };
  },
});

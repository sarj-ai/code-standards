import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds = "noImplicitAttributeAccess";

const FORBIDDEN_PROPERTIES = new Set(["attributes", "payload", "meta"]);

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<[], MessageIds>({
  name: "no-implicit-attribute-access",
  meta: {
    type: "problem",
    docs: {
      description: "Disallow implicit dictionary access on loosely-typed payloads; use Zod schemas.",
    },
    schema: [],
    messages: {
      noImplicitAttributeAccess:
        "Implicit access on loosely-typed `{{property}}` payload. Use a Zod schema to explicitly parse and validate this data instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      MemberExpression(node: TSESTree.MemberExpression): void {
        const objectNode = node.object;
        
        // We are looking for something like: ctx.participant.attributes.get("...")
        // or ctx.participant.attributes["foo"]
        if (objectNode.type === AST_NODE_TYPES.MemberExpression) {
            const propertyName = 
                objectNode.property.type === AST_NODE_TYPES.Identifier 
                ? objectNode.property.name 
                : null;
                
            if (propertyName && FORBIDDEN_PROPERTIES.has(propertyName)) {
                context.report({
                    node,
                    messageId: "noImplicitAttributeAccess",
                    data: { property: propertyName },
                });
            }
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        const callee = node.callee;
        if (callee.type === AST_NODE_TYPES.MemberExpression) {
            const method = callee.property.type === AST_NODE_TYPES.Identifier ? callee.property.name : null;
            if (method === "get") {
                const objectNode = callee.object;
                if (objectNode.type === AST_NODE_TYPES.MemberExpression) {
                    const propertyName = 
                        objectNode.property.type === AST_NODE_TYPES.Identifier 
                        ? objectNode.property.name 
                        : null;
                        
                    if (propertyName && FORBIDDEN_PROPERTIES.has(propertyName)) {
                        context.report({
                            node,
                            messageId: "noImplicitAttributeAccess",
                            data: { property: propertyName },
                        });
                    }
                }
            }
        }
      }
    };
  },
});

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds = "noImplicitAttributeAccess";

const EXCLUDED_BASES = new Set([
  "environ", "headers", "cookies", "session", "redis", "cache", 
  "state", "config", "env", "process", "localStorage", "sessionStorage"
]);

function getBaseName(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.Identifier) {
    return node.name;
  }
  if (node.type === AST_NODE_TYPES.MemberExpression && node.property.type === AST_NODE_TYPES.Identifier) {
    return node.property.name;
  }
  return null;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<[], MessageIds>({
  name: "no-implicit-attribute-access",
  meta: {
    type: "problem",
    docs: {
      description: "Disallow imperative dictionary access with string literals; use declarative Zod schemas.",
    },
    schema: [],
    messages: {
      noImplicitAttributeAccess:
        "Imperative lookup for '{{key}}' — if the key is known, parse the object declaratively with a Zod schema instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      MemberExpression(node: TSESTree.MemberExpression): void {
        if (!node.computed) {
            return;
        }
        
        // We are looking for something like: foo["price"]
        if (node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string") {
            const baseName = getBaseName(node.object);
            if (!baseName || !EXCLUDED_BASES.has(baseName)) {
                context.report({
                    node,
                    messageId: "noImplicitAttributeAccess",
                    data: { key: node.property.value },
                });
            }
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        const callee = node.callee;
        if (callee.type === AST_NODE_TYPES.MemberExpression) {
            const method = callee.property.type === AST_NODE_TYPES.Identifier ? callee.property.name : null;
            if (method === "get") {
                const arg = node.arguments[0];
                if (arg && arg.type === AST_NODE_TYPES.Literal && typeof arg.value === "string") {
                    const baseName = getBaseName(callee.object);
                    if (!baseName || !EXCLUDED_BASES.has(baseName)) {
                        context.report({
                            node,
                            messageId: "noImplicitAttributeAccess",
                            data: { key: arg.value },
                        });
                    }
                }
            }
        }
      }
    };
  },
});

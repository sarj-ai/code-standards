import { uniqueBy } from './unique-by.js';
export const ASTUtils = {
    isNodeOfOneOf(node, types) {
        return types.includes(node.type);
    },
    isIdentifier(node) {
        return node.type === "Identifier";
    },
    isIdentifierWithName(node, name) {
        return ASTUtils.isIdentifier(node) && node.name === name;
    },
    isIdentifierWithOneOfNames(node, name) {
        return ASTUtils.isIdentifier(node) && name.includes(node.name);
    },
    isProperty(node) {
        return node.type === "Property";
    },
    isObjectExpression(node) {
        return node.type === "ObjectExpression";
    },
    isPropertyWithIdentifierKey(node, key) {
        return (ASTUtils.isProperty(node) && ASTUtils.isIdentifierWithName(node.key, key));
    },
    findPropertyWithIdentifierKey(properties, key) {
        return properties.find((x) => ASTUtils.isPropertyWithIdentifierKey(x, key));
    },
    traverseUpOnly(identifier, allowedNodeTypes) {
        const parent = identifier.parent;
        if (parent !== undefined && allowedNodeTypes.includes(parent.type)) {
            return ASTUtils.traverseUpOnly(parent, allowedNodeTypes);
        }
        return identifier;
    },
    traverseUpMemberExpression(node) {
        const parent = node.parent;
        if (parent !== undefined &&
            ((parent.type === "MemberExpression" &&
                parent.object === node) ||
                parent.type === "ChainExpression" ||
                parent.type === "TSNonNullExpression")) {
            return ASTUtils.traverseUpMemberExpression(parent);
        }
        return node;
    },
    isDeclaredInNode(params) {
        const { functionNode, reference, scopeManager } = params;
        const scope = scopeManager.acquire(functionNode);
        if (scope === null) {
            return false;
        }
        return scope.set.has(reference.identifier.name);
    },
    getExternalRefs(params) {
        const { scopeManager, sourceCode, node } = params;
        const scope = scopeManager.acquire(node);
        if (scope === null) {
            return [];
        }
        const collectReferences = (currentScope) => {
            const references = [...currentScope.references];
            for (const childScope of currentScope.childScopes) {
                references.push(...collectReferences(childScope));
            }
            return references;
        };
        const references = collectReferences(scope)
            .filter((x) => x.isRead() && !scope.set.has(x.identifier.name))
            .map((x) => {
            const memberPath = ASTUtils.traverseUpMemberExpression(x.identifier);
            const memberExpression = memberPath.parent;
            const isComputedCallProperty = memberExpression !== undefined &&
                memberExpression.type === "MemberExpression" &&
                memberExpression.computed &&
                memberExpression.property === memberPath &&
                memberExpression.parent.type === "CallExpression" &&
                memberExpression.parent.callee === memberExpression;
            const referenceNode = isComputedCallProperty
                ? memberPath
                : ASTUtils.traverseUpOnly(x.identifier, [
                    "MemberExpression",
                    "Identifier",
                ]);
            return {
                variable: x,
                node: referenceNode,
                text: sourceCode.getText(referenceNode),
            };
        });
        const localRefIds = new Set([...scope.set.values()].map((x) => sourceCode.getText(x.identifiers[0])));
        const externalRefs = references.filter((x) => x.variable.resolved === null || !localRefIds.has(x.text));
        return uniqueBy(externalRefs, (x) => x.text).map((x) => x.variable);
    },
    isValidReactComponentOrHookName(identifier) {
        return (identifier !== null &&
            identifier !== undefined &&
            /^(use|[A-Z])/.test(identifier.name));
    },
    getFunctionAncestor(sourceCode, node) {
        for (const ancestor of sourceCode.getAncestors(node)) {
            if (ASTUtils.isNodeOfOneOf(ancestor, [
                "FunctionDeclaration",
                "FunctionExpression",
                "ArrowFunctionExpression",
            ])) {
                return ancestor;
            }
            if (ancestor.parent?.type === "VariableDeclarator" &&
                ancestor.parent.id.type === "Identifier" &&
                ASTUtils.isNodeOfOneOf(ancestor, [
                    "FunctionDeclaration",
                    "FunctionExpression",
                    "ArrowFunctionExpression",
                ])) {
                return ancestor;
            }
        }
        return undefined;
    },
    getReferencedExpressionByIdentifier(params) {
        const { node, context } = params;
        const scope = context.sourceCode.getScope(node);
        const resolvedNode = scope.references.find((ref) => ref.identifier === node)
            ?.resolved?.defs[0]?.node;
        if (resolvedNode?.type !== "VariableDeclarator") {
            return null;
        }
        return resolvedNode.init;
    },
};

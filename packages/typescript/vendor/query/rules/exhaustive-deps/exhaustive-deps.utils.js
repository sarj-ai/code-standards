import { ASTUtils } from '../../utils/ast-utils.js';
export const ExhaustiveDepsUtils = {
    isRelevantReference(params) {
        const { sourceCode, reference, scopeManager, node, filename } = params;
        const component = ASTUtils.getFunctionAncestor(sourceCode, node);
        const queryFnScope = scopeManager.acquire(node);
        if (queryFnScope === null || reference.isValueReference === false) {
            return false;
        }
        let currentScope = reference.resolved?.scope ?? null;
        while (currentScope !== null) {
            if (currentScope === queryFnScope) {
                return false;
            }
            currentScope = currentScope.upper;
        }
        if (component !== undefined) {
            if (!ASTUtils.isDeclaredInNode({
                scopeManager,
                reference,
                functionNode: component,
            })) {
                return false;
            }
        }
        else {
            const isVueFile = filename.endsWith('.vue');
            if (!isVueFile) {
                return false;
            }
            const definition = reference.resolved?.defs[0];
            const isGlobalVariable = definition === undefined;
            const isImport = definition?.type === 'ImportBinding';
            if (isGlobalVariable || isImport) {
                return false;
            }
        }
        return (reference.identifier.name !== 'undefined' &&
            !ExhaustiveDepsUtils.isFunctionCallTarget(reference.identifier) &&
            reference.identifier.parent.type !== "NewExpression" &&
            !ExhaustiveDepsUtils.isInstanceOfKind(reference.identifier.parent));
    },
    isFunctionCallTarget(identifier) {
        const callee = ASTUtils.traverseUpMemberExpression(identifier);
        return (callee.parent !== undefined &&
            callee.parent.type === "CallExpression" &&
            callee.parent.callee === callee);
    },
    /**
     * Given required refs and existing queryKey entries, compute missing dependency paths
     * respecting allowlisted variables and types.
     */
    computeFilteredMissingPaths(params) {
        const { requiredRefs, allowlistedVariables, existingRootIdentifiers, existingFullPaths, } = params;
        const missingPaths = new Set();
        for (const { root, path, allowlistedByType } of requiredRefs) {
            // If root itself is present in the key, it covers all members
            if (existingRootIdentifiers.has(root))
                continue;
            if (allowlistedVariables.has(root))
                continue;
            if (existingFullPaths.has(path))
                continue;
            if (allowlistedByType)
                continue;
            missingPaths.add(path);
        }
        // Collapse descendants: if a root is already missing, drop deeper paths
        for (const path of missingPaths) {
            const root = path.split('.')[0];
            if (root !== path && root !== undefined && missingPaths.has(root)) {
                missingPaths.delete(path);
            }
        }
        return Array.from(missingPaths);
    },
    /**
     * Extract existing queryKey deps as root identifiers and full member paths.
     */
    collectQueryKeyDeps(params) {
        const { sourceCode, scopeManager, queryKeyNode } = params;
        const roots = new Set();
        const paths = new Set();
        const visitorKeys = sourceCode.visitorKeys;
        function addRoot(name) {
            const cleaned = ExhaustiveDepsUtils.normalizeChain(name);
            roots.add(cleaned);
            paths.add(cleaned);
        }
        function addFull(text) {
            const cleaned = ExhaustiveDepsUtils.normalizeChain(text);
            paths.add(cleaned);
        }
        function addRefPath(refPath) {
            if (!refPath)
                return;
            if (refPath.coversRootMembers) {
                addRoot(refPath.root);
                return;
            }
            addFull(refPath.path);
        }
        function visitChildren(node) {
            const keys = (visitorKeys[node.type] ?? []);
            for (const key of keys) {
                const value = node[key];
                if (Array.isArray(value)) {
                    for (const item of value) {
                        if (ExhaustiveDepsUtils.isNode(item)) {
                            visit(item);
                        }
                    }
                    continue;
                }
                if (ExhaustiveDepsUtils.isNode(value)) {
                    visit(value);
                }
            }
        }
        function visit(node) {
            if (!node)
                return;
            switch (node.type) {
                case "Identifier": {
                    addRefPath(ExhaustiveDepsUtils.computeRefPath({
                        identifier: node,
                        sourceCode: sourceCode,
                    }));
                    return;
                }
                case "ArrowFunctionExpression":
                case "FunctionExpression":
                    for (const reference of ExhaustiveDepsUtils.collectExternalRefsInFunction({
                        functionNode: node,
                        scopeManager: scopeManager,
                    })) {
                        if (reference.identifier.type !== "Identifier") {
                            continue;
                        }
                        addRefPath(ExhaustiveDepsUtils.computeRefPath({
                            identifier: reference.identifier,
                            sourceCode: sourceCode,
                        }));
                    }
                    return;
                case "Property":
                    visit(node.value);
                    return;
                case "MemberExpression":
                    if (node.parent.type === "CallExpression" &&
                        node.parent.callee === node &&
                        node.object.type === "Identifier") {
                        addRoot(node.object.name);
                    }
                    else {
                        visit(node.object);
                    }
                    return;
                case "CallExpression":
                    node.arguments.forEach((argument) => visit(argument));
                    switch (node.callee.type) {
                        case "Identifier":
                        case "MemberExpression":
                        case "ChainExpression":
                        case "TSNonNullExpression":
                            visit(node.callee);
                            break;
                    }
                    return;
            }
            visitChildren(node);
        }
        visit(queryKeyNode);
        return { roots, paths };
    },
    isNode(value) {
        return (typeof value === 'object' &&
            value !== null &&
            'type' in value &&
            typeof value.type === 'string');
    },
    /**
     * Checks whether the resolved variable is allowlisted by its type annotation
     */
    variableIsAllowlistedByType(params) {
        const { allowlistedTypes, variable } = params;
        if (allowlistedTypes.size === 0)
            return false;
        if (!variable)
            return false;
        for (const id of variable.identifiers) {
            if (id.typeAnnotation) {
                const typeIdentifiers = new Set();
                ExhaustiveDepsUtils.collectTypeIdentifiers(id.typeAnnotation.typeAnnotation, typeIdentifiers);
                for (const typeIdentifier of typeIdentifiers) {
                    if (allowlistedTypes.has(typeIdentifier))
                        return true;
                }
            }
        }
        return false;
    },
    isInstanceOfKind(node) {
        return (node.type === "BinaryExpression" &&
            node.operator === 'instanceof');
    },
    /**
     * Normalizes a chain by removing optional chaining operators
     *
     * Example: `a?.b.c!` -> `a.b.c`
     */
    normalizeChain(text) {
        return text.replace(/(?:\?(\.)|!)/g, '$1').replace(/\s+/g, '');
    },
    /**
     * Computes the reference path for an identifier
     *
     * Example: `a.b.c!` -> `{ path: 'a.b.c', root: 'a' }`
     */
    computeRefPath(params) {
        const { identifier, sourceCode } = params;
        const fullChainNode = ASTUtils.traverseUpMemberExpression(identifier);
        const fullText = ExhaustiveDepsUtils.normalizeChain(sourceCode.getText(fullChainNode));
        const parent = fullChainNode.parent;
        let dependencyPath = fullText;
        let coversRootMembers = fullText === identifier.name;
        if (parent &&
            parent.type === "CallExpression" &&
            parent.callee === fullChainNode) {
            const segments = fullText.split('.');
            if (segments.length > 1) {
                dependencyPath = segments.slice(0, -1).join('.');
            }
            coversRootMembers = false;
        }
        dependencyPath =
            dependencyPath.split('.')[0] === '' ? identifier.name : dependencyPath;
        const root = dependencyPath.split('.')[0];
        return {
            path: dependencyPath,
            root: root ?? identifier.name,
            coversRootMembers: coversRootMembers && dependencyPath === root,
        };
    },
    collectExternalRefsInFunction(params) {
        const { functionNode, scopeManager } = params;
        const functionScope = scopeManager.acquire(functionNode);
        if (functionScope === null) {
            return [];
        }
        const externalRefs = [];
        function collect(scope) {
            for (const reference of scope.references) {
                if (!reference.isRead() || reference.resolved === null) {
                    continue;
                }
                let currentScope = reference.resolved.scope;
                let declaredInsideFunction = false;
                while (currentScope !== null) {
                    if (currentScope === functionScope) {
                        declaredInsideFunction = true;
                        break;
                    }
                    currentScope = currentScope.upper;
                }
                if (!declaredInsideFunction) {
                    externalRefs.push(reference);
                }
            }
            for (const childScope of scope.childScopes) {
                collect(childScope);
            }
        }
        collect(functionScope);
        return externalRefs;
    },
    /**
     * Recursively collects type identifiers from a type annotation
     */
    collectTypeIdentifiers(typeNode, out) {
        switch (typeNode.type) {
            case "TSTypeReference": {
                if (typeNode.typeName.type === "Identifier") {
                    out.add(typeNode.typeName.name);
                }
                break;
            }
            case "TSUnionType":
            case "TSIntersectionType": {
                typeNode.types.forEach((t) => ExhaustiveDepsUtils.collectTypeIdentifiers(t, out));
                break;
            }
            case "TSArrayType": {
                ExhaustiveDepsUtils.collectTypeIdentifiers(typeNode.elementType, out);
                break;
            }
            case "TSTupleType": {
                typeNode.elementTypes.forEach((et) => ExhaustiveDepsUtils.collectTypeIdentifiers(et, out));
                break;
            }
        }
    },
    /**
     * Gets the function expression nodes from a queryFn property, handling conditional expressions.
     * When neither branch is skipToken, returns both branches so all deps are scanned.
     */
    getQueryFnNodes(queryFn) {
        if (queryFn.value.type !== "ConditionalExpression") {
            return [queryFn.value];
        }
        if (queryFn.value.consequent.type === "Identifier" &&
            queryFn.value.consequent.name === 'skipToken') {
            return [queryFn.value.alternate];
        }
        if (queryFn.value.alternate.type === "Identifier" &&
            queryFn.value.alternate.name === 'skipToken') {
            return [queryFn.value.consequent];
        }
        return [queryFn.value.consequent, queryFn.value.alternate];
    },
};

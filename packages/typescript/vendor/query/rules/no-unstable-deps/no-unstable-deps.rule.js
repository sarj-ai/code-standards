import { RuleCreator } from '../../../rule-options/RuleCreator.cjs';
import { getDocsUrl } from '../../utils/get-docs-url.js';
import { detectTanstackQueryImports } from '../../utils/detect-react-query-imports.js';
export const name = 'no-unstable-deps';
export const reactHookNames = ['useEffect', 'useCallback', 'useMemo'];
export const useQueryHookNames = [
    'useQuery',
    'useSuspenseQuery',
    'useQueries',
    'useSuspenseQueries',
    'useInfiniteQuery',
    'useSuspenseInfiniteQuery',
];
const allHookNames = ['useMutation', ...useQueryHookNames];
const createRule = RuleCreator(getDocsUrl);
export const rule = createRule({
    name,
    meta: {
        type: 'problem',
        docs: {
            description: 'Disallow putting the result of query hooks directly in a React hook dependency array',
            recommended: 'error',
        },
        messages: {
            noUnstableDeps: `The result of {{queryHook}} is not referentially stable, so don't pass it directly into the dependencies array of {{reactHook}}. Instead, destructure the return value of {{queryHook}} and pass the destructured values into the dependency array of {{reactHook}}.`,
        },
        schema: [],
    },
    defaultOptions: [],
    create: detectTanstackQueryImports((context, _options, helpers) => {
        const trackedVariables = Object.create(null);
        const trackedCustomHooks = Object.create(null);
        const hookAliasMap = Object.create(null);
        const pendingVariableDeclarators = [];
        const pendingDependencyChecks = [];
        function getReactHook(node) {
            if (node.callee.type === 'Identifier') {
                const calleeName = node.callee.name;
                // Check if the identifier is a known React hook or an alias
                if (reactHookNames.includes(calleeName) || calleeName in hookAliasMap) {
                    return calleeName;
                }
            }
            else if (node.callee.type === 'MemberExpression' &&
                node.callee.object.type === 'Identifier' &&
                node.callee.object.name === 'React' &&
                node.callee.property.type === 'Identifier' &&
                reactHookNames.includes(node.callee.property.name)) {
                // Member expression case: `React.useCallback`
                return node.callee.property.name;
            }
            return undefined;
        }
        function collectVariableNames(pattern, queryHook) {
            if (pattern.type === "Identifier") {
                trackedVariables[pattern.name] = queryHook;
            }
            else if (pattern.type === "ArrayPattern") {
                for (const element of pattern.elements) {
                    if (element === null) {
                        continue;
                    }
                    if (element.type === "Identifier") {
                        trackedVariables[element.name] = queryHook;
                    }
                    else if (element.type === "RestElement" &&
                        element.argument.type === "Identifier") {
                        trackedVariables[element.argument.name] = queryHook;
                    }
                }
            }
        }
        function isCustomHookName(hookName) {
            return /^use[A-Z0-9]/.test(hookName);
        }
        function hasCombineProperty(callExpression) {
            if (callExpression.arguments.length === 0)
                return false;
            const firstArg = callExpression.arguments[0];
            if (!firstArg || firstArg.type !== "ObjectExpression")
                return false;
            return firstArg.properties.some((prop) => prop.type === "Property" &&
                prop.key.type === "Identifier" &&
                prop.key.name === 'combine');
        }
        function getDirectQueryHook(callExpression) {
            if (callExpression.callee.type !== "Identifier" ||
                !allHookNames.includes(callExpression.callee.name) ||
                !helpers.isTanstackQueryImport(callExpression.callee)) {
                return undefined;
            }
            if ((callExpression.callee.name === 'useQueries' ||
                callExpression.callee.name === 'useSuspenseQueries') &&
                hasCombineProperty(callExpression)) {
                return undefined;
            }
            return callExpression.callee.name;
        }
        function getTrackedQueryHook(callExpression) {
            const directQueryHook = getDirectQueryHook(callExpression);
            if (directQueryHook !== undefined) {
                return directQueryHook;
            }
            if (callExpression.callee.type === "Identifier") {
                return trackedCustomHooks[callExpression.callee.name];
            }
            return undefined;
        }
        function getReturnedQueryHook(body) {
            if (body.type === "CallExpression") {
                return getDirectQueryHook(body);
            }
            if (body.type !== "BlockStatement") {
                return undefined;
            }
            const returnStatements = body.body.filter((statement) => statement.type === "ReturnStatement");
            if (returnStatements.length !== 1) {
                return undefined;
            }
            const returnArgument = returnStatements[0]?.argument;
            if (returnArgument?.type === "CallExpression") {
                return getDirectQueryHook(returnArgument);
            }
            return undefined;
        }
        function checkDependencyArray(reactHook, depsArray) {
            depsArray.elements.forEach((dep) => {
                if (dep !== null &&
                    dep.type === "Identifier" &&
                    trackedVariables[dep.name] !== undefined) {
                    const queryHook = trackedVariables[dep.name];
                    context.report({
                        node: dep,
                        messageId: 'noUnstableDeps',
                        data: {
                            queryHook,
                            reactHook,
                        },
                    });
                }
            });
        }
        return {
            ImportDeclaration(node) {
                if (node.specifiers.length > 0 &&
                    node.importKind === 'value' &&
                    node.source.value === 'React') {
                    node.specifiers.forEach((specifier) => {
                        if (specifier.type === "ImportSpecifier" &&
                            specifier.imported.type === "Identifier" &&
                            reactHookNames.includes(specifier.imported.name)) {
                            // Track alias or direct import
                            hookAliasMap[specifier.local.name] = specifier.imported.name;
                        }
                    });
                }
            },
            FunctionDeclaration(node) {
                if (node.id === null || !isCustomHookName(node.id.name)) {
                    return;
                }
                const queryHook = getReturnedQueryHook(node.body);
                if (queryHook !== undefined) {
                    trackedCustomHooks[node.id.name] = queryHook;
                }
            },
            VariableDeclarator(node) {
                if (node.id.type === "Identifier" &&
                    isCustomHookName(node.id.name) &&
                    node.init !== null &&
                    (node.init.type === "ArrowFunctionExpression" ||
                        node.init.type === "FunctionExpression")) {
                    const queryHook = getReturnedQueryHook(node.init.body);
                    if (queryHook !== undefined) {
                        trackedCustomHooks[node.id.name] = queryHook;
                    }
                }
                if (node.init !== null &&
                    node.init.type === "CallExpression") {
                    pendingVariableDeclarators.push(node);
                }
            },
            CallExpression: (node) => {
                const reactHook = getReactHook(node);
                if (reactHook !== undefined &&
                    node.arguments.length > 1 &&
                    node.arguments[1]?.type === "ArrayExpression") {
                    pendingDependencyChecks.push({
                        reactHook,
                        depsArray: node.arguments[1],
                    });
                }
            },
            'Program:exit'() {
                pendingVariableDeclarators.forEach((node) => {
                    if (node.init?.type !== "CallExpression") {
                        return;
                    }
                    const queryHook = getTrackedQueryHook(node.init);
                    if (queryHook !== undefined) {
                        collectVariableNames(node.id, queryHook);
                    }
                });
                pendingDependencyChecks.forEach(({ reactHook, depsArray }) => {
                    checkDependencyArray(reactHook, depsArray);
                });
            },
        };
    }),
});

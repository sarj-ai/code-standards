import { resolveVariable } from '../../../../src/rules/_scope.ts';
import { RuleCreator } from '../../../rule-options/RuleCreator.cjs';
import { getDocsUrl } from '../../utils/get-docs-url.js';
import { ASTUtils } from '../../utils/ast-utils.js';
import { detectTanstackQueryImports } from '../../utils/detect-react-query-imports.js';
import { NoRestDestructuringUtils } from './no-rest-destructuring.utils.js';
export const name = 'no-rest-destructuring';
const queryHooks = [
    'useQuery',
    'useQueries',
    'useInfiniteQuery',
    'useSuspenseQuery',
    'useSuspenseQueries',
    'useSuspenseInfiniteQuery',
];
const createRule = RuleCreator(getDocsUrl);
export const rule = createRule({
    name,
    meta: {
        type: 'problem',
        docs: {
            description: 'Disallows rest destructuring in direct queries and same-file custom query hooks',
            recommended: 'warn',
        },
        messages: {
            objectRestDestructure: `Object rest destructuring on a query will observe all changes to the query, leading to excessive re-renders.`,
        },
        schema: [],
    },
    defaultOptions: [],
    create: detectTanstackQueryImports((context, _, helpers) => {
        const queryResultVariables = new Set();
        return {
            CallExpression: (node) => {
                if (node.parent.type !== "VariableDeclarator") {
                    return;
                }
                const returnValue = node.parent.id;
                const isDirectHook = ASTUtils.isIdentifierWithOneOfNames(node.callee, queryHooks) &&
                    helpers.isTanstackQueryImport(node.callee);
                if (!isDirectHook) {
                    const canReportQueryResult = returnValue.type === "Identifier" ||
                        NoRestDestructuringUtils.isObjectRestDestructuring(returnValue);
                    if (!canReportQueryResult ||
                        !NoRestDestructuringUtils.isQueryResultCall(node, context.sourceCode)) {
                        return;
                    }
                }
                const calleeName = ASTUtils.isIdentifier(node.callee)
                    ? node.callee.name
                    : null;
                if (calleeName !== 'useQueries' &&
                    calleeName !== 'useSuspenseQueries') {
                    if (NoRestDestructuringUtils.isObjectRestDestructuring(returnValue)) {
                        return context.report({
                            node: node.parent,
                            messageId: 'objectRestDestructure',
                        });
                    }
                    if (returnValue.type === "Identifier") {
                        queryResultVariables.add(resolveVariable(context.sourceCode, returnValue));
                    }
                    return;
                }
                if (returnValue.type !== "ArrayPattern") {
                    if (returnValue.type === "Identifier") {
                        queryResultVariables.add(resolveVariable(context.sourceCode, returnValue));
                    }
                    return;
                }
                returnValue.elements.forEach((queryResult) => {
                    if (queryResult === null) {
                        return;
                    }
                    if (NoRestDestructuringUtils.isObjectRestDestructuring(queryResult)) {
                        context.report({
                            node: queryResult,
                            messageId: 'objectRestDestructure',
                        });
                    }
                });
            },
            VariableDeclarator: (node) => {
                if (node.init?.type === "Identifier" &&
                    queryResultVariables.has(resolveVariable(context.sourceCode, node.init)) &&
                    NoRestDestructuringUtils.isObjectRestDestructuring(node.id)) {
                    context.report({
                        node,
                        messageId: 'objectRestDestructure',
                    });
                }
            },
            SpreadElement: (node) => {
                if (node.argument.type === "Identifier" &&
                    queryResultVariables.has(resolveVariable(context.sourceCode, node.argument))) {
                    context.report({
                        node,
                        messageId: 'objectRestDestructure',
                    });
                }
            },
        };
    }),
});

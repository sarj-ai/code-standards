import { RuleCreator } from '../../../rule-options/RuleCreator.cjs';
import { ASTUtils } from '../../utils/ast-utils.js';
import { getDocsUrl } from '../../utils/get-docs-url.js';
import { detectTanstackQueryImports } from '../../utils/detect-react-query-imports.js';
import { ExhaustiveDepsUtils } from './exhaustive-deps.utils.js';
const QUERY_KEY = 'queryKey';
const QUERY_FN = 'queryFn';
export const name = 'exhaustive-deps';
const createRule = RuleCreator(getDocsUrl);
export const rule = createRule({
    name,
    meta: {
        type: 'problem',
        docs: {
            description: 'Exhaustive deps rule for useQuery',
            recommended: 'error',
        },
        messages: {
            missingDeps: `The following dependencies are missing in your queryKey: {{deps}}`,
            fixTo: 'Fix to {{result}}',
        },
        hasSuggestions: true,
        fixable: 'code',
        schema: [
            {
                type: 'object',
                properties: {
                    allowlist: {
                        type: 'object',
                        properties: {
                            variables: { type: 'array', items: { type: 'string' } },
                            types: { type: 'array', items: { type: 'string' } },
                        },
                        additionalProperties: false,
                    },
                },
                additionalProperties: false,
            },
        ],
    },
    defaultOptions: [],
    create: detectTanstackQueryImports((context) => {
        return {
            ObjectExpression: (node) => {
                const scopeManager = context.sourceCode.scopeManager;
                const queryKey = ASTUtils.findPropertyWithIdentifierKey(node.properties, QUERY_KEY);
                const queryFn = ASTUtils.findPropertyWithIdentifierKey(node.properties, QUERY_FN);
                if (scopeManager === null ||
                    queryKey === undefined ||
                    queryFn === undefined ||
                    !ASTUtils.isNodeOfOneOf(queryFn.value, [
                        "ArrowFunctionExpression",
                        "FunctionExpression",
                        "ConditionalExpression",
                    ])) {
                    return;
                }
                const queryKeyNode = dereferenceVariablesAndTypeAssertions(queryKey.value, context);
                const queryFnNodes = ExhaustiveDepsUtils.getQueryFnNodes(queryFn);
                const externalRefs = queryFnNodes.flatMap((fnNode) => ASTUtils.getExternalRefs({
                    scopeManager,
                    sourceCode: context.sourceCode,
                    node: fnNode,
                }));
                const relevantRefs = externalRefs.filter((reference) => queryFnNodes.some((fnNode) => ExhaustiveDepsUtils.isRelevantReference({
                    sourceCode: context.sourceCode,
                    reference,
                    scopeManager,
                    node: fnNode,
                    filename: context.filename,
                })));
                const ruleOptions = context.options.at(0);
                const allowlistedVariables = new Set(ruleOptions?.allowlist?.variables ?? []);
                const allowlistedTypes = new Set(ruleOptions?.allowlist?.types ?? []);
                const requiredRefs = relevantRefs.flatMap((ref) => {
                    if (ref.identifier.type !== "Identifier")
                        return [];
                    const refPath = ExhaustiveDepsUtils.computeRefPath({
                        identifier: ref.identifier,
                        sourceCode: context.sourceCode,
                    });
                    if (refPath === null)
                        return [];
                    return [
                        {
                            ...refPath,
                            allowlistedByType: ExhaustiveDepsUtils.variableIsAllowlistedByType({
                                allowlistedTypes,
                                variable: ref.resolved ?? null,
                            }),
                        },
                    ];
                });
                if (requiredRefs.length === 0)
                    return;
                const queryKeyDeps = ExhaustiveDepsUtils.collectQueryKeyDeps({
                    sourceCode: context.sourceCode,
                    scopeManager: scopeManager,
                    queryKeyNode: queryKeyNode,
                });
                const missingPaths = ExhaustiveDepsUtils.computeFilteredMissingPaths({
                    requiredRefs: requiredRefs,
                    allowlistedVariables: allowlistedVariables,
                    existingRootIdentifiers: queryKeyDeps.roots,
                    existingFullPaths: queryKeyDeps.paths,
                });
                if (missingPaths.length === 0)
                    return;
                const missingAsText = missingPaths.join(', ');
                const suggestions = buildSuggestions({
                    queryKeyNode,
                    missingPaths,
                    missingAsText,
                    sourceCode: context.sourceCode,
                });
                context.report({
                    node,
                    messageId: 'missingDeps',
                    data: { deps: missingAsText },
                    suggest: suggestions,
                });
            },
        };
    }),
});
function buildSuggestions(params) {
    const { queryKeyNode, missingPaths, missingAsText, sourceCode } = params;
    if (queryKeyNode.type !== "ArrayExpression") {
        return [];
    }
    const closingBracket = sourceCode.getLastToken(queryKeyNode);
    if (!closingBracket)
        return [];
    const existingElements = queryKeyNode.elements
        .filter((el) => el !== null)
        .map((el) => sourceCode.getText(el));
    const resultText = `[${[...existingElements, ...missingPaths].join(', ')}]`;
    if (queryKeyNode.elements.length === 0) {
        return [
            {
                messageId: 'fixTo',
                data: { result: resultText },
                fix: (fixer) => fixer.replaceText(queryKeyNode, resultText),
            },
        ];
    }
    const tokenBefore = sourceCode.getTokenBefore(closingBracket);
    const separator = tokenBefore?.value === ',' ? ' ' : ', ';
    return [
        {
            messageId: 'fixTo',
            data: { result: resultText },
            fix: (fixer) => fixer.insertTextBefore(closingBracket, `${separator}${missingAsText}`),
        },
    ];
}
function dereferenceVariablesAndTypeAssertions(queryKeyNode, context) {
    const visitedNodes = new Set();
    for (let i = 0; i < 1 << 8; ++i) {
        if (visitedNodes.has(queryKeyNode)) {
            return queryKeyNode;
        }
        visitedNodes.add(queryKeyNode);
        switch (queryKeyNode.type) {
            case "TSAsExpression":
                queryKeyNode = queryKeyNode.expression;
                break;
            case "Identifier": {
                const expression = ASTUtils.getReferencedExpressionByIdentifier({
                    context,
                    node: queryKeyNode,
                });
                if (expression == null) {
                    return queryKeyNode;
                }
                queryKeyNode = expression;
                break;
            }
            default:
                return queryKeyNode;
        }
    }
    return queryKeyNode;
}

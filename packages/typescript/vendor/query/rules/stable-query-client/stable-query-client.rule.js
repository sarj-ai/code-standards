import { RuleCreator } from '../../../rule-options/RuleCreator.cjs';
import { ASTUtils } from '../../utils/ast-utils.js';
import { getDocsUrl } from '../../utils/get-docs-url.js';
import { detectTanstackQueryImports } from '../../utils/detect-react-query-imports.js';
export const name = 'stable-query-client';
const createRule = RuleCreator(getDocsUrl);
export const rule = createRule({
    name,
    meta: {
        type: 'problem',
        docs: {
            description: 'Makes sure that QueryClient is stable',
            recommended: 'error',
        },
        messages: {
            unstable: [
                'QueryClient is not stable. It should be either extracted from the component or wrapped in React.useState.',
                'See https://tkdodo.eu/blog/react-query-fa-qs#2-the-queryclient-is-not-stable',
            ].join('\n'),
            fixTo: 'Fix to {{result}}',
        },
        hasSuggestions: true,
        fixable: 'code',
        schema: [],
    },
    defaultOptions: [],
    create: detectTanstackQueryImports((context, _, helpers) => {
        return {
            NewExpression: (node) => {
                if (node.callee.type !== "Identifier" ||
                    node.callee.name !== 'QueryClient' ||
                    node.parent.type !== "VariableDeclarator" ||
                    !helpers.isSpecificTanstackQueryImport(node.callee, '@tanstack/react-query')) {
                    return;
                }
                const fnAncestor = ASTUtils.getFunctionAncestor(context.sourceCode, node);
                const isReactServerComponent = fnAncestor?.async === true;
                if (!ASTUtils.isValidReactComponentOrHookName(fnAncestor?.id) ||
                    isReactServerComponent) {
                    return;
                }
                context.report({
                    node: node.parent,
                    messageId: 'unstable',
                    fix: (() => {
                        const { parent } = node;
                        if (parent.id.type !== "Identifier") {
                            return;
                        }
                        const sourceCode = context.sourceCode;
                        const nodeText = sourceCode.getText(node);
                        const variableName = parent.id.name;
                        return (fixer) => {
                            return fixer.replaceTextRange([parent.range[0], parent.range[1]], `[${variableName}] = React.useState(() => ${nodeText})`);
                        };
                    })(),
                });
            },
        };
    }),
});

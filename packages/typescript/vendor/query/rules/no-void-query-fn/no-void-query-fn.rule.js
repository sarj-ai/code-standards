import { returnsVoid } from '../../../../src/upstream/query-semantics.js';
import { RuleCreator } from '../../../rule-options/RuleCreator.cjs';
import { ASTUtils } from '../../utils/ast-utils.js';
import { detectTanstackQueryImports } from '../../utils/detect-react-query-imports.js';
import { getDocsUrl } from '../../utils/get-docs-url.js';
export const name = 'no-void-query-fn';
const createRule = RuleCreator(getDocsUrl);
export const rule = createRule({
    name,
    meta: {
        type: 'problem',
        docs: {
            description: 'Ensures queryFn returns a non-undefined value using same-file bodies and explicit return annotations',
            recommended: 'error',
        },
        messages: {
            noVoidReturn: 'queryFn must return a non-undefined value',
        },
        schema: [],
    },
    defaultOptions: [],
    create: detectTanstackQueryImports((context) => {
        return {
            Property(node) {
                if (!ASTUtils.isObjectExpression(node.parent) ||
                    !ASTUtils.isIdentifierWithName(node.key, 'queryFn')) {
                    return;
                }
                if (returnsVoid(node.value, context.sourceCode)) {
                    context.report({ node: node.value, messageId: 'noVoidReturn' });
                }
            },
        };
    }),
});

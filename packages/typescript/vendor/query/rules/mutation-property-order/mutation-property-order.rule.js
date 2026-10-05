import { createPropertyOrderRule } from '../../utils/create-property-order-rule.js';
import { mutationFunctions, sortRules } from './constants.js';
export const name = 'mutation-property-order';
export const rule = createPropertyOrderRule({
    name,
    meta: {
        type: 'problem',
        docs: {
            description: 'Ensure correct order of inference-sensitive properties in useMutation()',
            recommended: 'error',
        },
        messages: {
            invalidOrder: 'Invalid order of properties for `{{function}}`.',
        },
        schema: [],
        hasSuggestions: true,
        fixable: 'code',
    },
    defaultOptions: [],
}, mutationFunctions, sortRules);

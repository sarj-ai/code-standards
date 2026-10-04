import { createPropertyOrderRule } from '../../utils/create-property-order-rule.js';
import { infiniteQueryFunctions, sortRules } from './constants.js';
export const name = 'infinite-query-property-order';
export const rule = createPropertyOrderRule({
    name,
    meta: {
        type: 'problem',
        docs: {
            description: 'Ensure correct order of inference sensitive properties for infinite queries',
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
}, infiniteQueryFunctions, sortRules);

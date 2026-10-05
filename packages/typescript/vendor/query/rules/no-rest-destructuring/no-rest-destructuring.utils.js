import { returnsQueryResult } from '../../../../src/upstream/query-semantics.js';
export const NoRestDestructuringUtils = {
    isObjectRestDestructuring(node) { return node.type === 'ObjectPattern' && node.properties.some(property => property.type === 'RestElement'); },
    isQueryResultCall(node, sourceCode) { return returnsQueryResult(node, sourceCode); },
};

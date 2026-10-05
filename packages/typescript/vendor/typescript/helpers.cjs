"use strict";
const utils_1=require("../ast-node-types/index.cjs");const visitor_keys_1=require("./visitor-keys.cjs");
const { RuleCreator }=require("../rule-options/RuleCreator.cjs");
function getNameFromIndexSignature(node) {
    const propName = node.parameters.find((parameter) => parameter.type === utils_1.AST_NODE_TYPES.Identifier);
    return propName ? propName.name : '(index signature)';
}
function getNameFromMember(member, sourceCode) {
    if (member.key.type === utils_1.AST_NODE_TYPES.Identifier) {
        return {
            name: member.key.name,
            type: MemberNameType.Normal,
        };
    }
    if (member.key.type === utils_1.AST_NODE_TYPES.PrivateIdentifier) {
        return {
            name: `#${member.key.name}`,
            type: MemberNameType.Private,
        };
    }
    if (member.key.type === utils_1.AST_NODE_TYPES.Literal) {
        const name = `${member.key.value}`;
        if (requiresQuoting(name)) {
            return {
                name: `"${name}"`,
                type: MemberNameType.Quoted,
            };
        }
        return {
            name,
            type: MemberNameType.Normal,
        };
    }
    return {
        name: sourceCode.text.slice(...member.key.range),
        type: MemberNameType.Expression,
    };
}
function getEnumNames(myEnum) {
    return Object.keys(myEnum).filter(x => isNaN(Number(x)));
}
const MemberNameType={Private:1,Quoted:2,Normal:3,Expression:4};
function isESTreeNodeLike(node) {
    return (typeof node === 'object' &&
        node != null &&
        'type' in node &&
        // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
        typeof node.type === 'string');
}
function forEachChildESTree(node, callback) {
    function visit(currentNode) {
        const result = callback(currentNode);
        if (result) {
            return result;
        }
        const currentKeys = visitor_keys_1.visitorKeys[currentNode.type];
        if (!currentKeys) {
            return undefined;
        }
        for (const key of currentKeys) {
            const currentProperty = currentNode[key];
            if (Array.isArray(currentProperty)) {
                for (const child of currentProperty) {
                    if (isESTreeNodeLike(child)) {
                        const result = visit(child);
                        if (result) {
                            return result;
                        }
                    }
                }
            }
            else if (isESTreeNodeLike(currentProperty)) {
                const result = visit(currentProperty);
                if (result) {
                    return result;
                }
            }
        }
        return undefined;
    }
    return visit(node);
}function getStaticStringValue(node) {
    switch (node.type) {
        case utils_1.AST_NODE_TYPES.Literal:
            // eslint-disable-next-line eqeqeq, @typescript-eslint/internal/eqeq-nullish -- intentional strict comparison for literal value
            if (node.value === null) {
                if ((node.type === "Literal" && node.value === null)) {
                    return String(node.value); // "null"
                }
                if ('regex' in node) {
                    return `/${node.regex.pattern}/${node.regex.flags}`;
                }
                if ('bigint' in node) {
                    return node.bigint;
                }
                // Otherwise, this is an unknown literal. The function will return null.
            }
            else {
                return String(node.value);
            }
            break;
        case utils_1.AST_NODE_TYPES.TemplateLiteral:
            if (node.expressions.length === 0 && node.quasis.length === 1) {
                return node.quasis[0].value.cooked;
            }
            break;
        // no default
    }
    return null;
}
"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.NullThrowsReasons = void 0;
exports.nullThrows = nullThrows;
/**
 * A set of common reasons for calling nullThrows
 */
exports.NullThrowsReasons = {
    MissingParent: 'Expected node to have a parent.',
    MissingToken: (token, thing) => `Expected to find a ${token} for the ${thing}.`,
};
/**
 * Assert that a value must not be null or undefined.
 * This is a nice explicit alternative to the non-null assertion operator.
 */
function nullThrows(value, message) {
    if (value == null) {
        throw new Error(`Non-null Assertion Failed: ${message}`);
    }
    return value;
}
//# sourceMappingURL=nullThrows.js.map
function requiresQuoting(name) { return !/^[\p{ID_Start}$_][\p{ID_Continue}$\u200c\u200d]*$/u.test(name); }
const createRule=RuleCreator(name=>`https://typescript-eslint.io/rules/${name}`);

module.exports={...module.exports,createRule,MemberNameType,getNameFromIndexSignature,getNameFromMember,getEnumNames,forEachChildESTree,getStaticStringValue,requiresQuoting};

import { definePlugin, defineRule } from "@oxlint/plugins";
import { parse as parseComment } from "comment-parser";
import { parse as parseType } from "jsdoc-type-pratt-parser";

function hasTypeContract(comment) {
  return parseComment(comment).some((block) =>
    block.tags.some((tag) => {
      if (tag.tag === "template") return true;
      if (tag.type.length === 0) return false;
      try {
        parseType(tag.type, "typescript");
        return true;
      } catch {
        return false;
      }
    }),
  );
}

function attachedJsdoc(sourceCode, node) {
  let owner = node;
  if (
    owner.parent?.type === "VariableDeclarator" &&
    owner.parent.init === owner
  ) {
    owner = owner.parent.parent;
  } else if (
    owner.parent?.type === "Property" &&
    owner.parent.value === owner
  ) {
    owner = owner.parent;
  } else if (
    owner.parent?.type === "MethodDefinition" &&
    owner.parent.value === owner
  ) {
    owner = owner.parent;
  }
  if (
    owner.parent?.type === "ExportNamedDeclaration" ||
    owner.parent?.type === "ExportDefaultDeclaration"
  ) {
    owner = owner.parent;
  }
  const comments = sourceCode.getCommentsBefore(owner);
  const comment = comments.at(-1);
  return comment?.type === "Block" &&
    comment.value.startsWith("*") &&
    owner.loc.start.line - comment.loc.end.line <= 1
    ? comment
    : null;
}

const noImplementationJsdoc = defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Keep implementation details in code and preserve required JavaScript type contracts",
      url: "https://github.com/gajus/eslint-plugin-jsdoc/blob/main/docs/rules/no-restricted-syntax.md",
    },
    schema: [
      {
        type: "object",
        properties: { allowTypedContracts: { type: "boolean" } },
        additionalProperties: false,
      },
    ],
    messages: {
      implementation:
        "Do not attach JSDoc to an implementation; preserve required type contracts and keep behavior in code or tests.",
    },
  },
  create(context) {
    const allowTypedContracts =
      context.options[0]?.allowTypedContracts === true;
    const inspect = (node) => {
      const comment = attachedJsdoc(context.sourceCode, node);
      if (comment === null) return;
      if (
        allowTypedContracts &&
        hasTypeContract(context.sourceCode.getText(comment))
      )
        return;
      context.report({ node: comment, messageId: "implementation" });
    };
    return {
      ArrowFunctionExpression: inspect,
      "FunctionDeclaration[body.type='BlockStatement']": inspect,
      "FunctionExpression[body.type='BlockStatement']": inspect,
    };
  },
});

export default definePlugin({
  meta: { name: "sarj-upstream-jsdoc" },
  rules: { "no-implementation-jsdoc": noImplementationJsdoc },
});

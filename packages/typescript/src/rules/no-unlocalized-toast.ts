/**
 * @fileoverview no-unlocalized-toast — statically proven UI policy violations receive actionable diagnostics.
 *
 * Port of the 18.x `no-unlocalized-toast` rule. The rule is untyped, so
 * the port covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import {
  COMPONENT_IMPORT_SCHEMA,
  type ComponentImport,
  importedComponent,
  staticText,
} from "../utils/jsx-accessibility.js";
import {
  LOCALIZATION_PROPERTIES,
  localizationExcluded,
  type LocalizationOptions,
  needsTranslation,
} from "../utils/localization.js";
import { getPropertyName } from "../utils/static-string.js";

const NAME = "no-unlocalized-toast";

type Options = LocalizationOptions & {
  readonly functions?: readonly ComponentImport[];
  readonly methods?: readonly string[];
};

const DEFAULT_FUNCTIONS: readonly ComponentImport[] = [
  { module: "sonner", export: "toast" },
  { module: "react-hot-toast", export: "default" },
];
const DEFAULT_METHODS: readonly string[] = ["success", "error", "info", "warning", "loading", "message"];

export default defineRule({
  meta: {
    defaultOptions: [{ enabled: true }],
    type: "suggestion",
    docs: {
      description: "Require translation for literal toast messages in opted-in localized interfaces.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          ...LOCALIZATION_PROPERTIES,
          functions: COMPONENT_IMPORT_SCHEMA,
          methods: {
            description: "Toast method names whose user-visible messages require localization.",
            type: "array",
            items: { type: "string", minLength: 1 },
            uniqueItems: true,
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      unlocalized: "Translate this user-facing literal or add an explicit localization exception.",
    },
  },
  createOnce(context) {
    let options: Options | undefined;
    let functions = DEFAULT_FUNCTIONS;
    let methods = DEFAULT_METHODS;
    function toastMethodReceiver(callee: Node): Extract<Node, { type: "Identifier" }> | null {
      if (callee.type !== "MemberExpression") return null;
      const receiver = unwrapExpression(callee.object);
      const method = getPropertyName(callee);
      return receiver.type === "Identifier" && method !== null && methods.includes(method) ? receiver : null;
    }
    return {
      before() {
        options = context.options[0] as Options | undefined;
        if (localizationExcluded({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text, options))
          return false;
        functions = options?.functions ?? DEFAULT_FUNCTIONS;
        methods = options?.methods ?? DEFAULT_METHODS;
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        const callee = unwrapExpression(node.callee);
        const receiver = callee.type === "Identifier" ? callee : toastMethodReceiver(callee);
        if (receiver === null) return;
        const imported = importedComponent(receiver, context.sourceCode);
        if (!functions.some((entry) => entry.module === imported?.module && entry.export === imported.export)) return;
        const argument = node.arguments[0];
        if (argument === undefined) return;
        const text = staticText(argument);
        if (text !== null && needsTranslation(text, options))
          context.report({ node: argument, messageId: "unlocalized" });
      },
    };
  },
});

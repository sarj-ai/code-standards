/**
 * @fileoverview no-unlocalized-toast — statically proven UI policy violations receive actionable diagnostics.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unlocalized-toast.test.ts
 */

import { AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  COMPONENT_IMPORT_SCHEMA,
  type ComponentImport,
  importedComponent,
  staticText,
} from "./_jsx-accessibility.js";
import {
  LOCALIZATION_PROPERTIES,
  localizationExcluded,
  type LocalizationOptions,
  needsTranslation,
} from "./_localization.js";

type Options = readonly [
  (LocalizationOptions & {
    readonly functions?: readonly ComponentImport[];
    readonly methods?: readonly string[];
  })?,
];

export const NO_UNLOCALIZED_TOAST_DOCUMENTATION = {
  summary:
    "Require translation for literal toast messages in opted-in localized interfaces.",
  rationale:
    "User-facing notifications remain in a fixed language when their messages bypass translation.",
  remediation:
    "Pass the user-facing message through the configured translation API, or explicitly exempt text that must remain literal.",
  category: "correctness",
  limitations: [
    "Shared presets set enabled:false. Standalone rule activation opts into localization for the selected files. No particular locale or translation function name is required. Generated files, tests, fixtures and stories are excluded.",
    "Recognizes configured imported functions and their configured methods with message in argument zero. Defaults cover sonner toast and react-hot-toast default exports. Imports and shadows are scope-resolved. Promise/config-object notifications and dynamic messages are not analyzed.",
  ],
  examples: [
    {
      id: "literal-message",
      title: "Translate a user-facing message",
      outcome: "match",
      files: [
        {
          path: "src/message.tsx",
          source: 'import { toast } from "sonner"; toast.success("Saved");',
        },
      ],
      focusPath: "src/message.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "translated-message",
      title: "Resolve the message through translation",
      outcome: "no-match",
      files: [
        {
          path: "src/message.tsx",
          source: 'import { toast } from "sonner"; toast.success(t("saved"));',
        },
      ],
      focusPath: "src/message.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, "unlocalized">({
  name: "no-unlocalized-toast",
  documentation: NO_UNLOCALIZED_TOAST_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_UNLOCALIZED_TOAST_DOCUMENTATION.summary },
    schema: [
      {
        type: "object",
        properties: {
          ...LOCALIZATION_PROPERTIES,
          functions: COMPONENT_IMPORT_SCHEMA,
          methods: {
            type: "array",
            items: { type: "string", minLength: 1 },
            uniqueItems: true,
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      unlocalized:
        "Translate this user-facing literal or add an explicit localization exception.",
    },
  },
  defaultOptions: [{ enabled: true }],
  create(context, [options]) {
    if (
      localizationExcluded(context.filename, context.sourceCode.text, options)
    )
      return {};
    const functions = options?.functions ?? [
      { module: "sonner", export: "toast" },
      { module: "react-hot-toast", export: "default" },
    ];
    const methods = options?.methods ?? [
      "success",
      "error",
      "info",
      "warning",
      "loading",
      "message",
    ];
    return {
      CallExpression(node): void {
        const callee = node.callee;
        const receiver =
          callee.type === AST_NODE_TYPES.Identifier
            ? callee
            : callee.type === AST_NODE_TYPES.MemberExpression &&
                !callee.computed &&
                callee.object.type === AST_NODE_TYPES.Identifier &&
                callee.property.type === AST_NODE_TYPES.Identifier &&
                methods.includes(callee.property.name)
              ? callee.object
              : null;
        if (receiver === null) return;
        const imported = importedComponent(receiver, context.sourceCode);
        if (
          !functions.some(
            (entry) =>
              entry.module === imported?.module &&
              entry.export === imported.export,
          )
        )
          return;
        const argument = node.arguments[0];
        if (argument === undefined) return;
        const text = staticText(argument);
        if (text !== null && needsTranslation(text, options))
          context.report({ node: argument, messageId: "unlocalized" });
      },
    };
  },
});

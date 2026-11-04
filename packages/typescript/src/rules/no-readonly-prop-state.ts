/**
 * @fileoverview no-readonly-prop-state — review unmodified React state initialized from props.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-readonly-prop-state.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { getTypeServices, type TypeScriptSourceCode } from "./_eslint-rule.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import {
  firstParameterBindings,
  parameterPath,
  reactHook,
  renderFunction,
} from "./_react-prop-bindings.js";
import {
  stableValueBinding,
  typeOnlyReference,
} from "./_stable-value-binding.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";
import { hasIdentifierNamed } from "./_unused-private-binding.js";

type Options = readonly [];
type MessageIds = "readonlyPropState";

const BEFORE =
  "import { useState } from 'react'; export function Status({ status }: { status: string }) { const [savedStatus] = useState(status); return <p>{savedStatus}</p>; }";
const AFTER =
  "export function Status({ status }: { status: string }) { return <p>{status}</p>; }";

const CONFIG = {
  path: "tsconfig.json",
  source:
    '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler","jsx":"preserve"},"include":["src/**/*"]}',
} as const;
const OPAQUE_TYPES =
  ts.TypeFlags.Any |
  ts.TypeFlags.Unknown |
  ts.TypeFlags.Never |
  ts.TypeFlags.TypeParameter |
  ts.TypeFlags.Conditional |
  ts.TypeFlags.IndexedAccess |
  ts.TypeFlags.Substitution;
const MAX_TYPE_DEPTH = 16;
const FUNCTION_MEMBERS = ["apply", "bind", "call"] as const;

export const NO_READONLY_PROP_STATE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Review props copied into state without a usable updater.",
  rationale:
    "State initialized from props retains the first render's value. Without an observed updater, later props can leave the displayed value stale and add a second source of truth.",
  remediation:
    "Derive the value from current props when it should stay current. For an intentional mount-time snapshot, retain that lifecycle explicitly, for example with a ref; independently editable drafts keep their updater. Review the intended lifecycle before changing behavior.",
  category: "correctness",
  limitations: [
    "Advisory only: initial snapshots can be intentional. There is no automatic fix because replacing state with current props changes how later updates behave.",
    "Recognizes direct React useState imports and default/namespace member calls, including renamed imports, through lexical binding identity. Checks a direct array destructure in a function containing its own JSX and a direct first-parameter property path, or a zero-argument synchronous lazy initializer returning that path.",
    "Eager initializers require parser-owned TypeScript services and a non-callable type without Any, unknown or unresolved generics. Callable unions, constructors and legacy function-like types exposing apply/bind/call are excluded because React executes function arguments as lazy initializers. Explicit zero-argument lazy callbacks returning the prop directly do not require type information. Type annotations cannot prove runtime identity under opaque casts; lifecycle changes stay manual.",
    "An updater read, escape, reassignment or nontrivial destructuring excludes the finding. Unused state values remain owned by unused-variable checks. Opaque initialization, property aliases, optional/dynamic paths, rest/default bindings, dynamic eval, non-JSX hooks, generated source and tests are outside scope. This does not ban interactive useState or replace the upstream set-state-in-effect rule.",
  ],
  references: [
    "https://react.dev/learn/choosing-the-state-structure",
    "https://react.dev/reference/eslint-plugin-react-hooks/lints/set-state-in-effect",
  ],
  examples: [
    {
      id: "frozen-prop",
      title: "A prop snapshot has no updater",
      outcome: "match",
      files: [{ path: "src/status.tsx", source: BEFORE }, CONFIG],
      focusPath: "src/status.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "current-prop",
      title: "Render the current prop directly",
      outcome: "no-match",
      files: [{ path: "src/status.tsx", source: AFTER }, CONFIG],
      focusPath: "src/status.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-readonly-prop-state",
  documentation: NO_READONLY_PROP_STATE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_READONLY_PROP_STATE_DOCUMENTATION.summary },
    schema: [],
    messages: {
      readonlyPropState:
        "This prop is copied into state without an observed updater. Derive it from current props, or make an intentional initial snapshot explicit; review the lifecycle before changing it.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isGeneratedFile(context, context.sourceCode.text) ||
      isTestFile(context) ||
      !context.sourceCode.ast.body.some(
        (statement) =>
          statement.type === AST_NODE_TYPES.ImportDeclaration &&
          statement.source.value === "react" &&
          statement.importKind !== "type",
      ) ||
      hasIdentifierNamed(context.sourceCode.ast, "eval")
    )
      return {};
    return {
      CallExpression(node): void {
        if (
          node.optional ||
          node.arguments.length !== 1 ||
          !reactHook(context.sourceCode, node.callee, "useState")
        )
          return;
        const declaration = outerExpression(node).parent;
        if (
          declaration.type !== AST_NODE_TYPES.VariableDeclarator ||
          declaration.parent.kind !== "const" ||
          !hasReadonlyStateBinding(context.sourceCode, declaration)
        )
          return;
        const component = renderFunction(node);
        const argument = node.arguments[0];
        if (
          component === null ||
          argument === undefined ||
          argument.type === AST_NODE_TYPES.SpreadElement
        )
          return;
        const initial = initializerValue(argument);
        if (
          initial === null ||
          !parameterPath(
            context.sourceCode,
            initial,
            firstParameterBindings(context.sourceCode, component),
          )
        )
          return;
        const lazy = unwrapExpression(argument);
        if (
          lazy.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
          lazy.type !== AST_NODE_TYPES.FunctionExpression
        ) {
          if (
            !context.sourceCode.parserServices?.program ||
            !context.sourceCode.parserServices.esTreeNodeToTSNodeMap
          )
            return;
          const services = getTypeServices(context);
          const type = services.program
            .getTypeChecker()
            .getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(initial));
          if (!isNonCallableType(type)) return;
        }
        context.report({ node, messageId: "readonlyPropState" });
      },
    };
  },
});

function hasReadonlyStateBinding(
  source: Readonly<TypeScriptSourceCode>,
  declaration: TSESTree.VariableDeclarator,
): boolean {
  if (declaration.id.type !== AST_NODE_TYPES.ArrayPattern) return false;
  const [value, setter] = declaration.id.elements;
  if (
    value?.type !== AST_NODE_TYPES.Identifier ||
    declaration.id.elements.length > 2 ||
    (setter !== undefined &&
      setter !== null &&
      setter.type !== AST_NODE_TYPES.Identifier)
  )
    return false;
  const variables = source.getDeclaredVariables(declaration);
  const state = variables.find((variable) =>
    variable.identifiers.includes(value),
  );
  if (
    state === undefined ||
    !stableValueBinding(state) ||
    !state.references.some(
      (reference) => reference.isRead() && !typeOnlyReference(reference),
    )
  )
    return false;
  if (setter?.type === AST_NODE_TYPES.Identifier) {
    const updater = variables.find((variable) =>
      variable.identifiers.includes(setter),
    );
    if (
      updater === undefined ||
      !stableValueBinding(updater) ||
      updater.eslintUsed ||
      updater.references.some(
        (reference) => !typeOnlyReference(reference) && reference.isRead(),
      )
    )
      return false;
  }
  return true;
}

function initializerValue(
  node: TSESTree.Expression,
): TSESTree.Expression | null {
  node = unwrapExpression(node);
  if (
    node.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
    node.type !== AST_NODE_TYPES.FunctionExpression
  )
    return node;
  if (node.async || node.generator || node.params.length !== 0) return null;
  if (node.body.type !== AST_NODE_TYPES.BlockStatement) return node.body;
  const [statement] = node.body.body;
  return node.body.body.length === 1 &&
    statement?.type === AST_NODE_TYPES.ReturnStatement
    ? statement.argument
    : null;
}

function isNonCallableType(type: ts.Type, depth = 0): boolean {
  if (
    depth >= MAX_TYPE_DEPTH ||
    (type.flags & OPAQUE_TYPES) !== 0 ||
    type.getCallSignatures().length !== 0 ||
    type.getConstructSignatures().length !== 0 ||
    FUNCTION_MEMBERS.every((member) => type.getProperty(member) !== undefined)
  )
    return false;
  return (
    !type.isUnionOrIntersection() ||
    type.types.every((member) => isNonCallableType(member, depth + 1))
  );
}

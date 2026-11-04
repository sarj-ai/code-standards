/**
 * @fileoverview prefer-server-data-preparation — prepare data projections before interactive client views.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-server-data-preparation.test.ts
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESTree,
} from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { getTypeServices, type TypeScriptSourceCode } from "./_eslint-rule.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import {
  firstParameterBindings,
  parameterPath,
  reactHook,
  renderFunction,
} from "./_react-prop-bindings.js";
import { typeOnlyReference } from "./_stable-value-binding.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

type Options = readonly [];
type MessageIds = "prepareData";

const BEFORE =
  "'use client'; import { useState } from 'react'; export function Options({ rows }: { rows: readonly { language: string }[] }) { const [selected, setSelected] = useState(''); const languages = rows.map(row => row.language); return <select value={selected} onChange={event => setSelected(event.target.value)}>{languages.map(language => <option key={language}>{language}</option>)}</select>; }";
const AFTER =
  "'use client'; import { useState } from 'react'; export function Options({ languages }: { languages: readonly string[] }) { const [selected, setSelected] = useState(''); return <select value={selected} onChange={event => setSelected(event.target.value)}>{languages.map(language => <option key={language}>{language}</option>)}</select>; }";
const CONFIG = {
  path: "tsconfig.json",
  source:
    '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler","jsx":"preserve"},"include":["src/**/*"]}',
} as const;
const METHODS: ReadonlySet<string> = new Set(["map", "filter", "flatMap"]);
const DOM_EVENTS: ReadonlySet<string> = new Set([
  "onClick",
  "onChange",
  "onInput",
  "onSubmit",
]);
const BINARY: ReadonlySet<string> = new Set([
  "===",
  "!==",
  "==",
  "!=",
  ">",
  ">=",
  "<",
  "<=",
  "+",
  "-",
  "*",
  "/",
  "%",
]);

export const PREFER_SERVER_DATA_PREPARATION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary:
    "Prepare data-only input collections before an interactive client view when possible.",
  rationale:
    "Preparing display data where its inputs are loaded can reduce browser work, payloads and knowledge of server data shapes. A small client component can receive the values its interaction actually needs.",
  remediation:
    "When these inputs are available on the server, prepare the collection in its loader or Server Component and pass the prepared values. Otherwise lift the projection to the owning producer when useful. Keep unsaved edits, browser-dependent values and interactive filtering reactive in the client; review callers before moving anything.",
  category: "architecture",
  limitations: [
    "Advisory only. Local syntax cannot establish whether a caller is a Server Component, whether props change interactively or whether server preparation reduces the total cost. This rule is a review lead, never proof that code can be moved to the server. No automatic fix is provided.",
    "Requires an explicit use client directive and parser-owned TypeScript services resolving map/filter/flatMap to the standard Array or ReadonlyArray library signature. The containing view must have an independent React useState/useReducer call or an intrinsic DOM onClick/onChange/onInput/onSubmit handler. Noninteractive boundaries remain owned by no-unnecessary-use-client; custom hooks and other indirect client requirements are unsupported.",
    "Every runtime reference to the source parameter binding must be a supported native data projection or a field-only JSX display loop. Inputs also needed for editing, whole-record forwarding, lookup, mutation, other fields or opaque helpers are excluded. Only direct first-parameter paths and synchronous single-expression callbacks are supported. Whole-row identity maps and constant maps are excluded; supported projections must read a fixed input field.",
    "JSX-rendering callbacks are never reported as preparation findings. Callback calls, captured values, destructuring defaults/rest/nesting, async callbacks, event handlers, effects, memo callbacks, opaque helpers, dynamic/optional paths, custom collection signatures, missing type services, generated source and tests are excluded. First-parameter provenance is syntactic; annotations cannot prove absence of runtime getters or patched array methods. Analysis does not claim callback purity or preserve semantics of a hypothetical move.",
    "Reports the direct source projection once; chained operations with a call receiver are not independently reported. A static subprojection may still be prepared by its producer while a union with pending local edits remains in the client.",
  ],
  references: [
    "https://nextjs.org/docs/app/getting-started/server-and-client-components",
    "https://react.dev/learn/you-might-not-need-an-effect",
  ],
  examples: [
    {
      id: "client-projection",
      title: "Prepare data before the client view when possible",
      outcome: "match",
      files: [{ path: "src/options.tsx", source: BEFORE }, CONFIG],
      focusPath: "src/options.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "prepared-values",
      title: "The client receives prepared language values",
      outcome: "no-match",
      files: [{ path: "src/options.tsx", source: AFTER }, CONFIG],
      focusPath: "src/options.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "prefer-server-data-preparation",
  documentation: PREFER_SERVER_DATA_PREPARATION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: PREFER_SERVER_DATA_PREPARATION_DOCUMENTATION.summary },
    schema: [],
    messages: {
      prepareData:
        "Review preparing this prop-only collection in its producer or Server Component when the inputs are available there. Keep operations depending on unsaved edits or browser interaction reactive in the client.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isGeneratedFile(context, context.sourceCode.text) ||
      isTestFile(context) ||
      !clientDirective(context.sourceCode.ast) ||
      !context.sourceCode.parserServices?.program ||
      !context.sourceCode.parserServices.esTreeNodeToTSNodeMap
    )
      return {};
    const services = getTypeServices(context);
    const checker = services.program.getTypeChecker();
    const interactions = new WeakMap<TSESTree.Node, boolean>();
    const nativeArray = (node: TSESTree.CallExpression): boolean => {
      const declaration = checker.getResolvedSignature(
        services.esTreeNodeToTSNodeMap.get(node),
      )?.declaration;
      return (
        declaration !== undefined &&
        services.program.isSourceFileDefaultLibrary(
          declaration.getSourceFile(),
        ) &&
        ts.isInterfaceDeclaration(declaration.parent) &&
        ["Array", "ReadonlyArray"].includes(declaration.parent.name.text)
      );
    };
    return {
      CallExpression(node): void {
        const callee = unwrapExpression(node.callee);
        if (
          node.optional ||
          callee.type !== AST_NODE_TYPES.MemberExpression ||
          callee.optional ||
          node.arguments.length !== 1 ||
          !METHODS.has(ASTUtils.getPropertyName(callee) ?? "")
        )
          return;
        const callback = node.arguments[0];
        if (
          callback?.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
          callback?.type !== AST_NODE_TYPES.FunctionExpression
        )
          return;
        const component = renderFunction(node);
        if (
          component === null ||
          !parameterPath(
            context.sourceCode,
            callee.object,
            firstParameterBindings(context.sourceCode, component),
          ) ||
          !projection(context.sourceCode, callback) ||
          !nativeArray(node) ||
          !onlyProjectedInput(context.sourceCode, callee.object, nativeArray)
        )
          return;
        let interactive = interactions.get(component);
        if (interactive === undefined) {
          interactive = clientInteraction(context.sourceCode, component.body);
          interactions.set(component, interactive);
        }
        if (!interactive) return;
        context.report({ node, messageId: "prepareData" });
      },
    };
  },
});

function clientDirective(program: TSESTree.Program): boolean {
  for (const statement of program.body) {
    if (
      statement.type !== AST_NODE_TYPES.ExpressionStatement ||
      statement.directive === undefined
    )
      return false;
    if (statement.directive === "use client") return true;
  }
  return false;
}

function projection(
  source: Readonly<TypeScriptSourceCode>,
  callback: TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression,
  mode: "data" | "view" = "data",
): boolean {
  if (callback.async || callback.generator || callback.params.length !== 1)
    return false;
  const parameter = callback.params[0];
  if (
    parameter?.type === AST_NODE_TYPES.ObjectPattern &&
    parameter.properties.some(
      (property) =>
        property.type !== AST_NODE_TYPES.Property ||
        property.computed ||
        property.value.type !== AST_NODE_TYPES.Identifier,
    )
  )
    return false;
  const parameters = firstParameterBindings(source, callback);
  if (parameters.size === 0) return false;
  let body: TSESTree.Node = callback.body;
  if (body.type === AST_NODE_TYPES.BlockStatement) {
    const [statement] = body.body;
    if (
      body.body.length !== 1 ||
      statement?.type !== AST_NODE_TYPES.ReturnStatement ||
      statement.argument === null
    )
      return false;
    body = statement.argument;
  }
  let fieldRead = false;
  const inspect = (node: TSESTree.Node, depth: number): boolean => {
    if (depth > 64) return false;
    node = unwrapExpression(node);
    if (parameterPath(source, node, parameters)) {
      if (
        node.type !== AST_NODE_TYPES.MemberExpression &&
        callback.params[0]?.type !== AST_NODE_TYPES.ObjectPattern
      )
        return false;
      fieldRead = true;
      return true;
    }
    if (node.type === AST_NODE_TYPES.Literal) return !("regex" in node);
    if (node.type === AST_NODE_TYPES.UnaryExpression)
      return (
        ["!", "+", "-", "~", "typeof"].includes(node.operator) &&
        inspect(node.argument, depth + 1)
      );
    if (node.type === AST_NODE_TYPES.BinaryExpression)
      return (
        BINARY.has(node.operator) &&
        inspect(node.left, depth + 1) &&
        inspect(node.right, depth + 1)
      );
    if (node.type === AST_NODE_TYPES.LogicalExpression)
      return inspect(node.left, depth + 1) && inspect(node.right, depth + 1);
    if (node.type === AST_NODE_TYPES.ConditionalExpression)
      return (
        inspect(node.test, depth + 1) &&
        inspect(node.consequent, depth + 1) &&
        inspect(node.alternate, depth + 1)
      );
    if (node.type === AST_NODE_TYPES.ObjectExpression)
      return node.properties.every(
        (property) =>
          property.type === AST_NODE_TYPES.Property &&
          property.kind === "init" &&
          !property.method &&
          !property.computed &&
          inspect(property.value, depth + 1),
      );
    return (
      mode === "view" &&
      displayProjection(node, (child) => inspect(child, depth + 1))
    );
  };
  return inspect(body, 0) && fieldRead;
}

function displayProjection(
  node: TSESTree.Node,
  inspectChild: (child: TSESTree.Node) => boolean,
): boolean {
  if (node.type === AST_NODE_TYPES.JSXElement)
    return (
      node.openingElement.attributes.every(
        (attribute) =>
          attribute.type === AST_NODE_TYPES.JSXAttribute &&
          (attribute.value === null || inspectChild(attribute.value)),
      ) && node.children.every(inspectChild)
    );
  if (node.type === AST_NODE_TYPES.JSXFragment)
    return node.children.every(inspectChild);
  if (node.type === AST_NODE_TYPES.JSXText) return true;
  if (node.type === AST_NODE_TYPES.JSXExpressionContainer)
    return (
      node.expression.type === AST_NODE_TYPES.JSXEmptyExpression ||
      inspectChild(node.expression)
    );
  return false;
}

function onlyProjectedInput(
  source: Readonly<TypeScriptSourceCode>,
  receiver: TSESTree.Node,
  nativeArray: (node: TSESTree.CallExpression) => boolean,
): boolean {
  let root = unwrapExpression(receiver);
  while (root.type === AST_NODE_TYPES.MemberExpression)
    root = unwrapExpression(root.object);
  if (root.type !== AST_NODE_TYPES.Identifier) return false;
  const variable = ASTUtils.findVariable(source.getScope(root), root.name);
  return (
    variable !== null &&
    variable.references.every((reference) => {
      if (typeOnlyReference(reference)) return true;
      if (!reference.isRead()) return false;
      let access = outerExpression(reference.identifier);
      let parent = access.parent;
      while (
        parent?.type === AST_NODE_TYPES.MemberExpression &&
        parent.object === access
      ) {
        access = outerExpression(parent);
        parent = access.parent;
      }
      const member = unwrapExpression(access);
      const call = parent;
      if (call?.type !== AST_NODE_TYPES.CallExpression) return false;
      if (
        member.type !== AST_NODE_TYPES.MemberExpression ||
        member.optional ||
        !METHODS.has(ASTUtils.getPropertyName(member) ?? "") ||
        call.optional ||
        call.arguments.length !== 1 ||
        !nativeArray(call)
      )
        return false;
      const callback = call.arguments[0];
      return (
        (callback?.type === AST_NODE_TYPES.ArrowFunctionExpression ||
          callback?.type === AST_NODE_TYPES.FunctionExpression) &&
        (projection(source, callback) ||
          projection(source, callback, "view")) &&
        call.callee === access
      );
    })
  );
}

function clientInteraction(
  source: Readonly<TypeScriptSourceCode>,
  node: TSESTree.Node,
): boolean {
  if (
    node.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    node.type === AST_NODE_TYPES.FunctionExpression ||
    node.type === AST_NODE_TYPES.FunctionDeclaration
  )
    return false;
  if (
    node.type === AST_NODE_TYPES.CallExpression &&
    (reactHook(source, node.callee, "useState") ||
      reactHook(source, node.callee, "useReducer"))
  )
    return true;
  if (
    node.type === AST_NODE_TYPES.JSXOpeningElement &&
    node.name.type === AST_NODE_TYPES.JSXIdentifier &&
    /^[a-z]/u.test(node.name.name) &&
    node.attributes.some(
      (attribute) =>
        attribute.type === AST_NODE_TYPES.JSXAttribute &&
        attribute.name.type === AST_NODE_TYPES.JSXIdentifier &&
        DOM_EVENTS.has(attribute.name.name) &&
        attribute.value !== null,
    )
  )
    return true;
  return forEachOwnAstChild(
    node,
    (child) => clientInteraction(source, child),
    (key) => key !== "tokens" && key !== "comments",
  );
}

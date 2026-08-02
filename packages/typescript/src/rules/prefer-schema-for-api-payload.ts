/**
 * @fileoverview prefer-schema-for-api-payload — reading a field off `response.json()` propagates `any` inward from the network boundary.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-schema-for-api-payload.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "unparsedJsonAccess";
type Options = readonly [];

type Ctx = Readonly<RuleContext<MessageIds, Options>>;

/** Peel TypeScript wrappers that do not affect the underlying value. */
const unwrap = (
  node: TSESTree.Node | null | undefined,
): TSESTree.Node | null => {
  let current: TSESTree.Node | null | undefined = node;
  while (current !== null && current !== undefined) {
    if (
      current.type === AST_NODE_TYPES.TSAsExpression ||
      current.type === AST_NODE_TYPES.TSTypeAssertion ||
      current.type === AST_NODE_TYPES.TSNonNullExpression ||
      current.type === AST_NODE_TYPES.TSSatisfiesExpression
    ) {
      current = current.expression;
    } else if (current.type === AST_NODE_TYPES.ChainExpression) {
      current = current.expression;
    } else {
      break;
    }
  }
  return current ?? null;
};

/** Promise methods that preserve an unvalidated payload. */
const PROMISE_CHAIN_METHODS: ReadonlySet<string> = new Set([
  "then",
  "catch",
  "finally",
]);

/** True for `ZUser.parse` / `ZUser.safeParse` handed to a chain link as a callback. */
const isSchemaParseReference = (
  node: TSESTree.Node | null | undefined,
): boolean => {
  const inner = unwrap(node);
  return (
    inner !== null &&
    inner.type === AST_NODE_TYPES.MemberExpression &&
    !inner.computed &&
    inner.property.type === AST_NODE_TYPES.Identifier &&
    (inner.property.name === "parse" || inner.property.name === "safeParse")
  );
};

/** Match optionally awaited `.json()` calls and non-local `JSON.parse()` calls. */
const isRawPayloadSource = (
  node: TSESTree.Node | null | undefined,
): boolean => {
  let current = unwrap(node);
  if (current === null) return false;
  if (current.type === AST_NODE_TYPES.AwaitExpression) {
    current = unwrap(current.argument);
  }
  if (current === null || current.type !== AST_NODE_TYPES.CallExpression) {
    return false;
  }
  const callee = unwrap(current.callee);
  if (callee === null || callee.type !== AST_NODE_TYPES.MemberExpression) {
    return false;
  }
  const property = unwrap(callee.property);
  if (property === null || property.type !== AST_NODE_TYPES.Identifier) {
    return false;
  }
  if (property.name === "json") {
    return true;
  }
  // Promise methods preserve taint unless their callback is a schema parser.
  if (PROMISE_CHAIN_METHODS.has(property.name)) {
    return (
      !current.arguments.some(isSchemaParseReference) &&
      isRawPayloadSource(callee.object)
    );
  }
  // Other `.parse()` calls may be the requested schema validation.
  const object = unwrap(callee.object);
  return (
    property.name === "parse" &&
    object !== null &&
    object.type === AST_NODE_TYPES.Identifier &&
    object.name === "JSON" &&
    !isLocalFileRead(current.arguments[0])
  );
};

/** Filesystem readers whose result is repo-local text, not a peer's payload. */
const FILE_READ_RE = /^(readFile|readFileSync|readJson|readJsonSync|readJSON)$/;

/** Exempt repository-local JSON read through a recognized filesystem reader. */
const isLocalFileRead = (node: TSESTree.Node | null | undefined): boolean => {
  let found = false;
  const visit = (current: TSESTree.Node | null | undefined): void => {
    if (found || current === null || current === undefined) return;
    if (current.type === AST_NODE_TYPES.CallExpression) {
      const callee = unwrap(current.callee);
      const name =
        callee?.type === AST_NODE_TYPES.Identifier
          ? callee.name
          : callee?.type === AST_NODE_TYPES.MemberExpression &&
              !callee.computed &&
              callee.property.type === AST_NODE_TYPES.Identifier
            ? callee.property.name
            : null;
      if (name !== null && FILE_READ_RE.test(name)) {
        found = true;
        return;
      }
    }
    for (const key of Object.keys(current) as (keyof TSESTree.Node)[]) {
      if (key === "parent") continue;
      const value = current[key];
      for (const child of (Array.isArray(value) ? value : [value]) as unknown[]) {
        if (
          child !== null &&
          typeof child === "object" &&
          typeof (child as { type?: unknown }).type === "string"
        ) {
          visit(child as TSESTree.Node);
        }
      }
    }
  };
  visit(node);
  return found;
};

/** Assertion helpers whose argument is being checked, not consumed. */
const ASSERTION_CALLEE_RE = /^(expect|assert|should|invariant)$/;

/** Exempt reads consumed by an assertion such as `expect(value.id).toBe(1)`. */
const isInsideAssertion = (node: TSESTree.Node): boolean => {
  for (
    let current: TSESTree.Node | undefined | null = node.parent;
    current !== undefined && current !== null;
    current = current.parent
  ) {
    if (current.type !== AST_NODE_TYPES.CallExpression) continue;
    let callee: TSESTree.Node = current.callee;
    while (callee.type === AST_NODE_TYPES.MemberExpression) {
      callee = callee.object;
    }
    if (callee.type === AST_NODE_TYPES.CallExpression) {
      callee = callee.callee;
    }
    if (
      callee.type === AST_NODE_TYPES.Identifier &&
      ASSERTION_CALLEE_RE.test(callee.name)
    ) {
      return true;
    }
  }
  return false;
};

const findVariable = (
  scope: Scope.Scope | null,
  name: string,
): Scope.Variable | null => {
  let current: Scope.Scope | null = scope;
  while (current !== null) {
    const variable = current.set.get(name);
    if (variable !== undefined) return variable;
    current = current.upper;
  }
  return null;
};

/** Names that conventionally identify guards or validators. */
const GUARD_NAME_RE = /^(?:is|validate|parse|assert|decode|coerce)[A-Z]/;

/** Exempt a field read used by `typeof`, `Array.isArray`, or a named validator. */
const isValidationRead = (node: TSESTree.Node): boolean => {
  let current: TSESTree.Node = node;
  let parent: TSESTree.Node | null | undefined = current.parent;
  while (
    parent !== null &&
    parent !== undefined &&
    (parent.type === AST_NODE_TYPES.TSAsExpression ||
      parent.type === AST_NODE_TYPES.TSTypeAssertion ||
      parent.type === AST_NODE_TYPES.TSNonNullExpression ||
      parent.type === AST_NODE_TYPES.TSSatisfiesExpression ||
      parent.type === AST_NODE_TYPES.ChainExpression)
  ) {
    current = parent;
    parent = parent.parent;
  }
  if (parent === null || parent === undefined) return false;

  if (
    parent.type === AST_NODE_TYPES.UnaryExpression &&
    parent.operator === "typeof" &&
    parent.argument === current
  ) {
    return true;
  }
  if (
    parent.type !== AST_NODE_TYPES.CallExpression ||
    !parent.arguments.some((arg): boolean => arg === current)
  ) {
    return false;
  }
  const callee = parent.callee;
  if (
    callee.type === AST_NODE_TYPES.MemberExpression &&
    !callee.computed &&
    callee.object.type === AST_NODE_TYPES.Identifier &&
    callee.object.name === "Array" &&
    callee.property.type === AST_NODE_TYPES.Identifier &&
    callee.property.name === "isArray"
  ) {
    return parent.arguments.length === 1;
  }
  return (
    callee.type === AST_NODE_TYPES.Identifier && GUARD_NAME_RE.test(callee.name)
  );
};

/** Detect calls in boolean-test positions, including logical wrappers. */
const isGuardTestPosition = (node: TSESTree.Node): boolean => {
  let current: TSESTree.Node = node;
  let parent: TSESTree.Node | null | undefined = current.parent;
  while (parent !== undefined && parent !== null) {
    switch (parent.type) {
      case AST_NODE_TYPES.UnaryExpression:
      case AST_NODE_TYPES.LogicalExpression:
      case AST_NODE_TYPES.ChainExpression:
        current = parent;
        parent = parent.parent;
        continue;
      case AST_NODE_TYPES.IfStatement:
      case AST_NODE_TYPES.ConditionalExpression:
      case AST_NODE_TYPES.WhileStatement:
      case AST_NODE_TYPES.DoWhileStatement:
      case AST_NODE_TYPES.ForStatement:
        return parent.test === current;
      default:
        return false;
    }
  }
  return false;
};

const isUnvalidatedVariableRef = (
  node: TSESTree.Node | null | undefined,
  scope: Scope.Scope,
  tracked: ReadonlySet<Scope.Variable>,
): boolean => {
  const unwrapped = unwrap(node);
  if (unwrapped === null || unwrapped.type !== AST_NODE_TYPES.Identifier) {
    return false;
  }
  const variable = findVariable(scope, unwrapped.name);
  return variable !== null && tracked.has(variable);
};

export default createRule<Options, MessageIds>({
  name: "prefer-schema-for-api-payload",
  meta: {
    type: "problem",
    docs: {
      description:
        "Require Zod (or similar) schema validation on `response.json()` / `JSON.parse()` results before property access.",
    },
    schema: [],
    messages: {
      unparsedJsonAccess:
        "Property access on an unvalidated payload (`response.json()` / `JSON.parse()`) without a schema parse. Pipe through `XSchema.parse(...)` (Zod) before reading fields.",
    },
  },
  defaultOptions: [],
  create(context: Ctx) {
    // Fixtures and generated clients own validation at a different boundary.
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    const unvalidatedVariables = new Set<Scope.Variable>();

    /** Require every destructured binding to be validated. */
    const isFullyNarrowedPattern = (
      declarator: TSESTree.VariableDeclarator,
    ): boolean => {
      const declared = context.sourceCode.getDeclaredVariables(declarator);
      return (
        declared.length > 0 &&
        declared.every((variable) =>
          variable.references.some((reference) =>
            isValidationRead(reference.identifier),
          ),
        )
      );
    };

    const trackInitializer = (
      declarator: TSESTree.VariableDeclarator,
    ): void => {
      if (!isRawPayloadSource(declarator.init)) return;
      const declaredVars = context.sourceCode.getDeclaredVariables(declarator);
      const variable = declaredVars[0];
      if (variable !== undefined) {
        unvalidatedVariables.add(variable);
      }
    };

    return {
      VariableDeclarator(node): void {
        const scope = context.sourceCode.getScope(node);

        if (node.id.type === AST_NODE_TYPES.Identifier) {
          trackInitializer(node);
          return;
        }

        if (
          node.id.type === AST_NODE_TYPES.ObjectPattern ||
          node.id.type === AST_NODE_TYPES.ArrayPattern
        ) {
          if (isRawPayloadSource(node.init)) {
            if (!isFullyNarrowedPattern(node)) {
              context.report({ node: node.id, messageId: "unparsedJsonAccess" });
            }
            return;
          }
          if (
            isUnvalidatedVariableRef(node.init, scope, unvalidatedVariables)
          ) {
            context.report({ node: node.id, messageId: "unparsedJsonAccess" });
          }
        }
      },
      AssignmentExpression(node): void {
        const scope = context.sourceCode.getScope(node);

        if (node.left.type === AST_NODE_TYPES.Identifier) {
          const variable = findVariable(scope, node.left.name);
          if (variable === null) return;
          if (isRawPayloadSource(node.right)) {
            unvalidatedVariables.add(variable);
          } else {
            unvalidatedVariables.delete(variable);
          }
          return;
        }

        if (
          node.left.type === AST_NODE_TYPES.ObjectPattern ||
          node.left.type === AST_NODE_TYPES.ArrayPattern
        ) {
          if (isRawPayloadSource(node.right)) {
            context.report({
              node: node.left,
              messageId: "unparsedJsonAccess",
            });
            return;
          }
          if (
            isUnvalidatedVariableRef(node.right, scope, unvalidatedVariables)
          ) {
            context.report({
              node: node.left,
              messageId: "unparsedJsonAccess",
            });
          }
        }
      },
      CallExpression(node): void {
        if (node.callee.type !== AST_NODE_TYPES.Identifier) return;
        if (!GUARD_NAME_RE.test(node.callee.name) && !isGuardTestPosition(node)) {
          return;
        }
        const scope = context.sourceCode.getScope(node);
        for (const arg of node.arguments) {
          if (arg.type === AST_NODE_TYPES.SpreadElement) continue;
          const unwrapped = unwrap(arg);
          if (unwrapped === null || unwrapped.type !== AST_NODE_TYPES.Identifier) {
            continue;
          }
          const variable = findVariable(scope, unwrapped.name);
          if (variable !== null) unvalidatedVariables.delete(variable);
        }
      },
      MemberExpression(node): void {
        if (isInsideAssertion(node)) return;
        if (isValidationRead(node)) return;
        const scope = context.sourceCode.getScope(node);
        const obj = unwrap(node.object);

        if (isRawPayloadSource(obj)) {
          // Validation and promise methods are calls, not payload field reads.
          const parent = node.parent;
          if (
            parent.type === AST_NODE_TYPES.CallExpression &&
            parent.callee === node &&
            node.property.type === AST_NODE_TYPES.Identifier &&
            (node.property.name === "parse" ||
              node.property.name === "safeParse" ||
              PROMISE_CHAIN_METHODS.has(node.property.name))
          ) {
            return;
          }
          context.report({ node, messageId: "unparsedJsonAccess" });
          return;
        }

        if (
          obj !== null &&
          obj.type === AST_NODE_TYPES.Identifier &&
          isUnvalidatedVariableRef(obj, scope, unvalidatedVariables)
        ) {
          context.report({ node, messageId: "unparsedJsonAccess" });
          const variable = findVariable(scope, obj.name);
          if (variable !== null) {
            unvalidatedVariables.delete(variable);
          }
        }
      },
    };
  },
});

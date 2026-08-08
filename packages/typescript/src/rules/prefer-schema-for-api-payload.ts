/**
 * @fileoverview prefer-schema-for-api-payload — reading a field off `response.json()` propagates `any` inward from the network boundary.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-schema-for-api-payload.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "unparsedJsonAccess";

export const preferSchemaForApiPayloadDocumentation = {
  summary: "Require Zod (or similar) schema validation on `response.json()` / `JSON.parse()` results before property access.",
  rationale: "External JSON is untrusted at runtime even when its expected TypeScript shape is known statically.",
  remediation: "Parse the payload through a schema or establish a recognized runtime validation guard before reading fields.",
  category: "correctness",
  limitations: ["Test fixtures, generated clients, local JSON files, and recognized validation guards are excluded."],
  examples: [
    { id: "validated-payload", title: "Validate before property access", outcome: "no-match", files: [{ path: "src/client.ts", source: "async function load(response) { const body = UserSchema.parse(await response.json()); return body.id; }" }], focusPath: "src/client.ts", expectedCount: 0, public: true },
    { id: "unvalidated-payload", title: "Do not trust response JSON directly", outcome: "match", files: [{ path: "src/client.ts", source: "async function load(response) { const body = await response.json(); return body.id; }" }], focusPath: "src/client.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
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
  isKnownLocalText?: (candidate: TSESTree.Node | null | undefined) => boolean,
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
    !isLocalFileRead(current.arguments[0]) &&
    isKnownLocalText?.(current.arguments[0]) !== true
  );
};

/** Filesystem readers whose result is repo-local text, not a peer's payload. */
const FILE_READ_RE = /^(readFile|readFileSync|readJson|readJsonSync|readJSON)$/;

/** A direct filesystem reader expression, optionally wrapped in `await` or TS syntax. */
const isDirectLocalFileRead = (
  node: TSESTree.Node | null | undefined,
): boolean => {
  let current = unwrap(node);
  if (current?.type === AST_NODE_TYPES.AwaitExpression) {
    current = unwrap(current.argument);
  }
  if (current?.type !== AST_NODE_TYPES.CallExpression) return false;
  const callee = unwrap(current.callee);
  const name =
    callee?.type === AST_NODE_TYPES.Identifier
      ? callee.name
      : callee?.type === AST_NODE_TYPES.MemberExpression &&
          !callee.computed &&
          callee.property.type === AST_NODE_TYPES.Identifier
        ? callee.property.name
        : null;
  return name !== null && FILE_READ_RE.test(name);
};

/** Exempt repository-local JSON read through a recognized filesystem reader. */
const isLocalFileRead = (node: TSESTree.Node | null | undefined): boolean => {
  let found = false;
  const visit = (current: TSESTree.Node | null | undefined): void => {
    if (found || current === null || current === undefined) return;
    if (isDirectLocalFileRead(current)) {
      found = true;
      return;
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

type ValidationPolarity = "valid-when-true" | "valid-when-false";

const PRIMITIVE_TYPEOF_RESULTS: ReadonlySet<string> = new Set([
  "bigint",
  "boolean",
  "number",
  "string",
  "symbol",
  "undefined",
]);

/** Whether `test` proves one binding's primitive/array shape, and on which branch. */
const bindingValidationPolarity = (
  test: TSESTree.Expression,
  bindingName: string,
): ValidationPolarity | null => {
  if (test.type === AST_NODE_TYPES.UnaryExpression && test.operator === "!") {
    const inner = bindingValidationPolarity(test.argument, bindingName);
    return inner === "valid-when-true"
      ? "valid-when-false"
      : inner === "valid-when-false"
        ? "valid-when-true"
        : null;
  }
  if (test.type === AST_NODE_TYPES.BinaryExpression) {
    const typeofName = (
      node: TSESTree.Expression | TSESTree.PrivateIdentifier,
    ): string | null =>
      node.type === AST_NODE_TYPES.UnaryExpression &&
      node.operator === "typeof" &&
      node.argument.type === AST_NODE_TYPES.Identifier
        ? node.argument.name
        : null;
    const literalType = (
      node: TSESTree.Expression | TSESTree.PrivateIdentifier,
    ): string | null =>
      node.type === AST_NODE_TYPES.Literal &&
      typeof node.value === "string" &&
      PRIMITIVE_TYPEOF_RESULTS.has(node.value)
        ? node.value
        : null;
    const matches =
      (typeofName(test.left) === bindingName && literalType(test.right) !== null) ||
      (typeofName(test.right) === bindingName && literalType(test.left) !== null);
    if (!matches) return null;
    if (test.operator === "===" || test.operator === "==") {
      return "valid-when-true";
    }
    return test.operator === "!==" || test.operator === "!="
      ? "valid-when-false"
      : null;
  }
  return test.type === AST_NODE_TYPES.CallExpression &&
    test.arguments.length === 1 &&
    test.arguments[0]?.type === AST_NODE_TYPES.Identifier &&
    test.arguments[0].name === bindingName &&
    test.callee.type === AST_NODE_TYPES.MemberExpression &&
    !test.callee.computed &&
    test.callee.object.type === AST_NODE_TYPES.Identifier &&
    test.callee.object.name === "Array" &&
    test.callee.property.type === AST_NODE_TYPES.Identifier &&
    test.callee.property.name === "isArray"
    ? "valid-when-true"
    : null;
};

const nodeWithin = (node: TSESTree.Node, container: TSESTree.Node): boolean =>
  node.range[0] >= container.range[0] && node.range[1] <= container.range[1];

/**
 * A field extracted into a same-scope `const` is safe only when every later use
 * is either its validation test or confined to the proven-valid branch.
 */
const isFullyValidatedExtractedBinding = (
  member: TSESTree.MemberExpression,
  source: Scope.Variable,
  context: Ctx,
): boolean => {
  const isValidationReference = (identifier: TSESTree.Identifier): boolean => {
    for (
      let current: TSESTree.Node | undefined | null = identifier.parent;
      current !== undefined && current !== null;
      current = current.parent
    ) {
      if (
        (current.type === AST_NODE_TYPES.BinaryExpression ||
          current.type === AST_NODE_TYPES.CallExpression ||
          current.type === AST_NODE_TYPES.UnaryExpression) &&
        bindingValidationPolarity(current, identifier.name) !== null
      ) {
        return true;
      }
      if (
        current.type !== AST_NODE_TYPES.UnaryExpression &&
        current.type !== AST_NODE_TYPES.MemberExpression &&
        current.type !== AST_NODE_TYPES.CallExpression
      ) {
        return false;
      }
    }
    return false;
  };

  const isGuardedUse = (identifier: TSESTree.Identifier): boolean => {
    for (
      let current: TSESTree.Node | undefined | null = identifier.parent;
      current !== undefined && current !== null;
      current = current.parent
    ) {
      if (current.type === AST_NODE_TYPES.ConditionalExpression) {
        const polarity = bindingValidationPolarity(current.test, identifier.name);
        if (polarity === "valid-when-true" && nodeWithin(identifier, current.consequent)) {
          return true;
        }
        if (polarity === "valid-when-false" && nodeWithin(identifier, current.alternate)) {
          return true;
        }
      }
      if (current.type === AST_NODE_TYPES.IfStatement) {
        const polarity = bindingValidationPolarity(current.test, identifier.name);
        if (polarity === "valid-when-true" && nodeWithin(identifier, current.consequent)) {
          return true;
        }
        if (
          polarity === "valid-when-false" &&
          current.alternate !== null &&
          nodeWithin(identifier, current.alternate)
        ) {
          return true;
        }
      }
      if (
        current.type === AST_NODE_TYPES.FunctionDeclaration ||
        current.type === AST_NODE_TYPES.FunctionExpression ||
        current.type === AST_NODE_TYPES.ArrowFunctionExpression
      ) {
        return false;
      }
    }
    return false;
  };

  const declarator = member.parent;
  if (
    declarator.type !== AST_NODE_TYPES.VariableDeclarator ||
    declarator.init !== member ||
    declarator.id.type !== AST_NODE_TYPES.Identifier ||
    declarator.parent.type !== AST_NODE_TYPES.VariableDeclaration ||
    declarator.parent.kind !== "const"
  ) {
    return false;
  }
  const extracted = context.sourceCode.getDeclaredVariables(declarator)[0];
  if (extracted === undefined || extracted.scope !== source.scope) return false;
  let hasValueUse = false;
  for (const reference of extracted.references) {
    const identifier = reference.identifier;
    if (identifier.type !== AST_NODE_TYPES.Identifier) return false;
    if (nodeWithin(identifier, declarator)) continue;
    if (isValidationReference(identifier)) continue;
    hasValueUse = true;
    if (!isGuardedUse(identifier)) return false;
  }
  return hasValueUse;
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

const unvalidatedVariableRef = (
  node: TSESTree.Node | null | undefined,
  scope: Scope.Scope,
  tracked: ReadonlySet<Scope.Variable>,
): Scope.Variable | null => {
  const unwrapped = unwrap(node);
  if (unwrapped === null || unwrapped.type !== AST_NODE_TYPES.Identifier) {
    return null;
  }
  const variable = findVariable(scope, unwrapped.name);
  return variable !== null && tracked.has(variable) ? variable : null;
};

export default createRule<Options, MessageIds>({
  name: "prefer-schema-for-api-payload",
  documentation: preferSchemaForApiPayloadDocumentation,
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
    const aliasGroups = new Map<Scope.Variable, Set<Scope.Variable>>();
    const localFileTextVariables = new Set<Scope.Variable>();

    /** Resolve a same-scope binding already proven to hold repository-local file text. */
    const localFileTextRef = (
      node: TSESTree.Node | null | undefined,
      scope: Scope.Scope,
    ): Scope.Variable | null => {
      const unwrapped = unwrap(node);
      if (unwrapped?.type !== AST_NODE_TYPES.Identifier) return null;
      const variable = findVariable(scope, unwrapped.name);
      return variable !== null && localFileTextVariables.has(variable)
        ? variable
        : null;
    };

    /** Record direct file reads and simple same-scope aliases; detach on every other write. */
    const updateLocalFileText = (
      target: Scope.Variable,
      value: TSESTree.Node | null | undefined,
      scope: Scope.Scope,
    ): void => {
      const source = localFileTextRef(value, scope);
      if (
        isDirectLocalFileRead(value) ||
        (source !== null && source.scope === target.scope)
      ) {
        localFileTextVariables.add(target);
      } else {
        localFileTextVariables.delete(target);
      }
    };

    /** Stop tracking one binding without changing aliases of its previous value. */
    const clearBinding = (variable: Scope.Variable): void => {
      unvalidatedVariables.delete(variable);
      const group = aliasGroups.get(variable);
      aliasGroups.delete(variable);
      group?.delete(variable);
    };

    /** A validation read proves the shared payload behind every simple local alias. */
    const clearAliasGroup = (variable: Scope.Variable): void => {
      const group = aliasGroups.get(variable);
      if (group === undefined) {
        unvalidatedVariables.delete(variable);
        return;
      }
      for (const alias of group) {
        unvalidatedVariables.delete(alias);
        aliasGroups.delete(alias);
      }
      group.clear();
    };

    /** Reassignment to a fresh payload detaches the binding from any older aliases. */
    const trackRawBinding = (variable: Scope.Variable): void => {
      clearBinding(variable);
      const group = new Set([variable]);
      unvalidatedVariables.add(variable);
      aliasGroups.set(variable, group);
    };

    /** Track `target = source` as two bindings of the same unvalidated payload. */
    const trackAlias = (target: Scope.Variable, source: Scope.Variable): void => {
      if (target === source) return;
      const group = aliasGroups.get(source) ?? new Set([source]);
      if (aliasGroups.get(target) === group) return;
      clearBinding(target);
      unvalidatedVariables.add(target);
      group.add(target);
      aliasGroups.set(source, group);
      aliasGroups.set(target, group);
    };

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
      scope: Scope.Scope,
    ): void => {
      const declaredVars = context.sourceCode.getDeclaredVariables(declarator);
      const variable = declaredVars[0];
      if (variable === undefined) return;
      const localText = (candidate: TSESTree.Node | null | undefined): boolean =>
        localFileTextRef(candidate, scope) !== null;
      if (isRawPayloadSource(declarator.init, localText)) {
        trackRawBinding(variable);
        return;
      }
      const source = unvalidatedVariableRef(declarator.init, scope, unvalidatedVariables);
      if (source !== null) trackAlias(variable, source);
    };

    return {
      VariableDeclarator(node): void {
        const scope = context.sourceCode.getScope(node);

        if (node.id.type === AST_NODE_TYPES.Identifier) {
          const variable = context.sourceCode.getDeclaredVariables(node)[0];
          if (variable !== undefined) {
            updateLocalFileText(variable, node.init, scope);
          }
          trackInitializer(node, scope);
          return;
        }

        if (
          node.id.type === AST_NODE_TYPES.ObjectPattern ||
          node.id.type === AST_NODE_TYPES.ArrayPattern
        ) {
          if (
            isRawPayloadSource(
              node.init,
              (candidate): boolean => localFileTextRef(candidate, scope) !== null,
            )
          ) {
            if (!isFullyNarrowedPattern(node)) {
              context.report({ node: node.id, messageId: "unparsedJsonAccess" });
            }
            return;
          }
          if (unvalidatedVariableRef(node.init, scope, unvalidatedVariables) !== null) {
            context.report({ node: node.id, messageId: "unparsedJsonAccess" });
          }
        }
      },
      AssignmentExpression(node): void {
        const scope = context.sourceCode.getScope(node);

        if (node.left.type === AST_NODE_TYPES.Identifier) {
          const variable = findVariable(scope, node.left.name);
          if (variable === null) return;
          const isLocalText = (candidate: TSESTree.Node | null | undefined): boolean =>
            localFileTextRef(candidate, scope) !== null;
          updateLocalFileText(variable, node.right, scope);
          if (isRawPayloadSource(node.right, isLocalText)) {
            trackRawBinding(variable);
          } else {
            const source = unvalidatedVariableRef(node.right, scope, unvalidatedVariables);
            if (source === null) clearBinding(variable);
            else trackAlias(variable, source);
          }
          return;
        }

        if (
          node.left.type === AST_NODE_TYPES.ObjectPattern ||
          node.left.type === AST_NODE_TYPES.ArrayPattern
        ) {
          if (
            isRawPayloadSource(
              node.right,
              (candidate): boolean => localFileTextRef(candidate, scope) !== null,
            )
          ) {
            context.report({
              node: node.left,
              messageId: "unparsedJsonAccess",
            });
            return;
          }
          if (unvalidatedVariableRef(node.right, scope, unvalidatedVariables) !== null) {
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
          if (variable !== null) clearAliasGroup(variable);
        }
      },
      MemberExpression(node): void {
        if (isInsideAssertion(node)) return;
        if (isValidationRead(node)) return;
        const scope = context.sourceCode.getScope(node);
        const obj = unwrap(node.object);

        if (
          isRawPayloadSource(
            obj,
            (candidate): boolean => localFileTextRef(candidate, scope) !== null,
          )
        ) {
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

        const variable =
          obj?.type === AST_NODE_TYPES.Identifier
            ? unvalidatedVariableRef(obj, scope, unvalidatedVariables)
            : null;
        if (variable !== null) {
          if (isFullyValidatedExtractedBinding(node, variable, context)) {
            return;
          }
          context.report({ node, messageId: "unparsedJsonAccess" });
          clearAliasGroup(variable);
        }
      },
    };
  },
});

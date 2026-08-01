/**
 * @fileoverview prefer-schema-for-api-payload — reading a field off `response.json()` propagates `any` inward from the network boundary.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-schema-for-api-payload.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/prefer-schema-for-api-payload.md
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "unparsedJsonAccess";
type Options = readonly [];

type Ctx = Readonly<RuleContext<MessageIds, Options>>;

/**
 * Peel TypeScript wrapper nodes that don't affect the underlying value
 * (`as Foo`, `<Foo>x`, `x!`, `x satisfies Foo`, parentheses, optional chain
 * wrappers). Returns the inner expression we actually care about.
 */
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

/**
 * Promise-chain links that pass the payload along unchanged. `.parse` /
 * `.safeParse` are NOT here — those are the validation the rule is asking for.
 */
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

/**
 * Returns true if the expression is (optionally awaited) a raw payload source:
 * `<x>.json()` (a fetch/Request body) or `JSON.parse(<x>)`.
 *
 * Both hand back `any`, and the failure mode is the same: `payload.user.id`
 * type-checks against a shape the peer never sent, and surfaces at runtime as
 * `undefined` several frames away. Note this only matters at the point a FIELD
 * is read — `const raw: unknown = JSON.parse(body)` is the recommended shape and
 * is never reported, because nothing is accessed off it.
 */
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
  // A promise-chain link does not change what the value IS: the result of
  // `res.json().catch(() => ({}))` is still an unvalidated payload, and before
  // this the binding went untracked so the real field read below it was missed.
  // Unless the chain ends in a schema parse, in which case it is validated.
  if (PROMISE_CHAIN_METHODS.has(property.name)) {
    return (
      !current.arguments.some(isSchemaParseReference) &&
      isRawPayloadSource(callee.object)
    );
  }
  // `JSON.parse(...)` specifically — not any `.parse()`, which is usually the
  // schema validation we are asking for.
  const object = unwrap(callee.object);
  return (
    property.name === "parse" &&
    object !== null &&
    object.type === AST_NODE_TYPES.Identifier &&
    object.name === "JSON" &&
    // ...but not `JSON.parse(readFileSync(p, "utf8"))` — see isLocalFileRead.
    !isLocalFileRead(current.arguments[0])
  );
};

/** Filesystem readers whose result is repo-local text, not a peer's payload. */
const FILE_READ_RE = /^(readFile|readFileSync|readJson|readJsonSync|readJSON)$/;

/**
 * True when the expression tree contains a filesystem read, i.e. the JSON came
 * off local disk rather than off the wire.
 *
 * The rule's premise is that the value is "unvalidated and attacker-controlled".
 * `JSON.parse(readFileSync("package.json", "utf8"))` is neither: the bytes ship
 * with the repo, nobody else can write them, and a Zod schema over a file the
 * build already depends on adds a second place to update.
 */
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

/**
 * True when the node sits inside an assertion call, e.g.
 * `expect(loaderData.method).toEqual("GET")`.
 *
 * The rule's premise is that the field is READ and trusted. Inside an assertion
 * it is neither: the assertion states what the value must be, which is the same
 * check a schema would perform, and a schema parse would move the failure away
 * from the assertion that explains it.
 */
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

/**
 * Calls that CHECK their argument rather than trust it: a type-guard predicate
 * (`isProtectedResourceMetadata`) or a named validator.
 */
const GUARD_NAME_RE = /^(?:is|validate|parse|assert|decode|coerce)[A-Z]/;

/**
 * True when the read is being TYPE-TESTED rather than trusted — the operand of
 * a `typeof`, the sole argument of `Array.isArray(...)`, or an argument to a
 * guard/validator call.
 *
 * This SKIPS the report without untracking the variable, so a later unguarded
 * read of a different field still fires. Recall cost 0 of 45.
 */
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

/**
 * True when a call sits in a boolean-test position (`if`/`while`/`for`/`?:`),
 * seen through `!`, `&&`/`||`, and optional-chaining wrappers — i.e. it narrows.
 */
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
    // A fixture parses what it just produced and asserts on it; see @fileoverview.
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    const unvalidatedVariables = new Set<Scope.Variable>();

    /**
     * True when every binding a destructuring pattern introduces is type-tested
     * somewhere. Requiring EVERY binding (not any) keeps the report when one
     * field is checked and another is used unvalidated.
     */
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
            // `const { cacheTag } = await req.json()` where EVERY binding the
            // pattern introduces is then type-tested is the same "the read IS
            // the validation" case as `isValidationRead`, one node up.
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
            // Reassigned to a parse call or something else: drop tracking.
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
        // The read is inside an assertion — the assertion IS the validation.
        if (isInsideAssertion(node)) return;
        // The read is being type-tested, not trusted. Skipping WITHOUT
        // untracking leaves a later unguarded read of another field reportable.
        if (isValidationRead(node)) return;
        const scope = context.sourceCode.getScope(node);
        const obj = unwrap(node.object);

        if (isRawPayloadSource(obj)) {
          // Direct `.foo` access on `(await r.json()).foo` is always bad,
          // unless the parent call is a `.parse()`/`.safeParse()` (a
          // validation) or a `.then()`/`.catch()`/`.finally()` (a promise-chain
          // link, not a field read — `isRawPayloadSource` carries the taint
          // through it so the real read below still fires).
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

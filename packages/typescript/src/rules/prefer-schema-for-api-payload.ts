/**
 * @fileoverview prefer-schema-for-api-payload — reading a field off `response.json()` propagates `any` inward from the network boundary.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-schema-for-api-payload.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Context, Scope, Variable } from "@oxlint/plugins";


import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "unparsedJsonAccess";

export const PREFER_SCHEMA_FOR_API_PAYLOAD_DOCUMENTATION = {
  summary:
    "Require Zod (or similar) schema validation on `response.json()` / `JSON.parse()` results before property access.",
  rationale:
    "External JSON is untrusted at runtime even when its expected TypeScript shape is known statically.",
  remediation:
    "For external payloads, parse through a schema or establish runtime validation before reading fields. Review validator implementations separately rather than recursively requiring another schema.",
  category: "correctness",
  limitations: [
    "A JSON.parse call alone does not prove external input; exact native JSON stringify/parse round trips are excluded. Validator implementations and other non-network parsing can still require manual review rather than a schema rewrite.",
    "JSON.parse must resolve to the global JSON object. json() receivers require an unshadowed global Request/Response annotation or construction, or stable local aliases of global fetch results; imported, inferred and unknown response types are deliberately not inferred.",
    "Named validators remain conventions, not proof of their implementation. Their exemptions are confined to a valid branch or a preceding same-block validation statement; ignored predicate results and deferred callbacks do not validate later reads.",
    "Test fixtures, generated clients and recognized local-file reads are excluded. This is bounded local analysis, not a general control-flow or mutation proof.",
  ],
  examples: [
    {
      id: "validated-payload",
      title: "Validate before property access",
      outcome: "no-match",
      files: [
        {
          path: "src/client.ts",
          source:
            "async function load(response: Response) { const body = UserSchema.parse(await response.json()); return body.id; }",
        },
      ],
      focusPath: "src/client.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "unvalidated-payload",
      title: "Do not trust response JSON directly",
      outcome: "match",
      files: [
        {
          path: "src/client.ts",
          source:
            "async function load(response: Response) { const body = await response.json(); return body.id; }",
        },
      ],
      focusPath: "src/client.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
type Options = readonly [];

type Ctx = Readonly<Context>;

/** Peel TypeScript wrappers that do not affect the underlying value. */
const unwrap = (node: ESTree.Node | null | undefined): ESTree.Node | null => {
  let current: ESTree.Node | null | undefined = node;
  while (current !== null && current !== undefined) {
    if (
      current.type === "TSAsExpression" ||
      current.type === "TSTypeAssertion" ||
      current.type === "TSNonNullExpression" ||
      current.type === "TSSatisfiesExpression"
    ) {
      current = current.expression;
    } else if (current.type === "ChainExpression") {
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
  node: ESTree.Node | null | undefined,
): boolean => {
  const inner = unwrap(node);
  return (
    inner !== null &&
    inner.type === "MemberExpression" &&
    !inner.computed &&
    inner.property.type === "Identifier" &&
    (inner.property.name === "parse" || inner.property.name === "safeParse")
  );
};

/** Match optionally awaited `.json()` calls and non-local `JSON.parse()` calls. */
const isRawPayloadSource = (
  node: ESTree.Node | null | undefined,
  context: Ctx,
  isKnownLocalText?: (candidate: ESTree.Node | null | undefined) => boolean,
): boolean => {
  let current = unwrap(node);
  if (current === null) return false;
  if (current.type === "AwaitExpression") {
    current = unwrap(current.argument);
  }
  if (current === null || current.type !== "CallExpression") {
    return false;
  }
  const callee = unwrap(current.callee);
  if (callee === null || callee.type !== "MemberExpression") {
    return false;
  }
  const property = unwrap(callee.property);
  if (property === null || property.type !== "Identifier") {
    return false;
  }
  if (property.name === "json") {
    return (
      !callee.computed &&
      current.arguments.length === 0 &&
      isResponseSource(callee.object, context)
    );
  }
  // Promise methods preserve taint unless their callback is a schema parser.
  if (PROMISE_CHAIN_METHODS.has(property.name)) {
    return (
      !current.arguments.some(isSchemaParseReference) &&
      isRawPayloadSource(callee.object, context, isKnownLocalText)
    );
  }
  // Other `.parse()` calls may be the requested schema validation.
  const object = unwrap(callee.object);
  const input = unwrap(current.arguments[0]);
  if (
    input?.type === "CallExpression" &&
    input.arguments.length === 1 &&
    input.callee.type === "MemberExpression" &&
    !input.callee.computed &&
    input.callee.object.type === "Identifier" &&
    input.callee.object.name === "JSON" &&
    input.callee.property.type === "Identifier" &&
    input.callee.property.name === "stringify" &&
    (findVariable(context.sourceCode.getScope(input.callee.object), "JSON")
      ?.defs.length ?? 0) === 0
  )
    return false;
  return (
    property.name === "parse" &&
    object !== null &&
    object.type === "Identifier" &&
    object.name === "JSON" &&
    (findVariable(context.sourceCode.getScope(object), "JSON")?.defs.length ??
      0) === 0 &&
    !isLocalFileRead(current.arguments[0]) &&
    isKnownLocalText?.(current.arguments[0]) !== true
  );
};

const isResponseSource = (
  node: ESTree.Node,
  context: Ctx,
  seen = new Set<ESTree.Node>(),
): boolean => {
  let current = unwrap(node);
  if (current?.type === "AwaitExpression") current = unwrap(current.argument);
  if (current === null || seen.has(current)) return false;
  seen.add(current);
  const isGlobal = (identifier: ESTree.BindingIdentifier): boolean =>
    (findVariable(context.sourceCode.getScope(identifier), identifier.name)
      ?.defs.length ?? 0) === 0;
  if (current.type === "CallExpression")
    return (
      current.callee.type === "Identifier" &&
      current.callee.name === "fetch" &&
      isGlobal(current.callee)
    );
  if (current.type === "NewExpression")
    return (
      current.callee.type === "Identifier" &&
      ["Request", "Response"].includes(current.callee.name) &&
      isGlobal(current.callee)
    );
  if (current.type !== "Identifier") return false;
  const binding = findVariable(
    context.sourceCode.getScope(current),
    current.name,
  );
  if (
    binding?.defs.length !== 1 ||
    binding.references.some(
      (reference) => reference.isWrite() && reference.init !== true,
    )
  )
    return false;
  const definition = binding.defs[0];
  const annotation =
    definition?.name.type === "Identifier"
      ? definition.name.typeAnnotation?.typeAnnotation
      : undefined;
  if (
    annotation?.type === "TSTypeReference" &&
    annotation.typeName.type === "Identifier" &&
    ["Request", "Response"].includes(annotation.typeName.name) &&
    isGlobal(annotation.typeName)
  )
    return true;
  return (
    definition?.type === "Variable" &&
    definition.parent?.type === "VariableDeclaration" &&
    definition.parent.kind === "const" &&
    definition.node.type === "VariableDeclarator" &&
    definition.node.init !== null &&
    isResponseSource(definition.node.init, context, seen)
  );
};

/** Filesystem readers whose result is repo-local text, not a peer's payload. */
const FILE_READ_RE = /^(readFile|readFileSync|readJson|readJsonSync|readJSON)$/;

/** A direct filesystem reader expression, optionally wrapped in `await` or TS syntax. */
const isDirectLocalFileRead = (
  node: ESTree.Node | null | undefined,
): boolean => {
  let current = unwrap(node);
  if (current?.type === "AwaitExpression") {
    current = unwrap(current.argument);
  }
  if (current?.type !== "CallExpression") return false;
  const callee = unwrap(current.callee);
  const name =
    callee?.type === "Identifier"
      ? callee.name
      : callee?.type === "MemberExpression" &&
          !callee.computed &&
          callee.property.type === "Identifier"
        ? callee.property.name
        : null;
  return name !== null && FILE_READ_RE.test(name);
};

/** Exempt repository-local JSON read through a recognized filesystem reader. */
const isLocalFileRead = (node: ESTree.Node | null | undefined): boolean => {
  let found = false;
  const visit = (current: ESTree.Node | null | undefined): void => {
    if (found || current === null || current == null) return;
    if (isDirectLocalFileRead(current)) {
      found = true;
      return;
    }
    forEachOwnAstChild(current, (child) => {
      visit(child);
      return found;
    });
  };
  visit(node);
  return found;
};

/** Assertion helpers whose argument is being checked, not consumed. */
const ASSERTION_CALLEE_RE = /^(expect|assert|should|invariant)$/;

/** Exempt reads consumed by an assertion such as `expect(value.id).toBe(1)`. */
const isInsideAssertion = (node: ESTree.Node): boolean => {
  for (
    let current: ESTree.Node | null | undefined = node.parent;
    current !== undefined && current !== null;
    current = current.parent
  ) {
    if (current.type !== "CallExpression") continue;
    let callee: ESTree.Node = current.callee;
    while (callee.type === "MemberExpression") {
      callee = callee.object;
    }
    if (callee.type === "CallExpression") {
      callee = callee.callee;
    }
    if (callee.type === "Identifier" && ASSERTION_CALLEE_RE.test(callee.name)) {
      return true;
    }
  }
  return false;
};

const findVariable = (scope: Scope | null, name: string): Variable | null => {
  let current: Scope | null = scope;
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
const isValidationRead = (node: ESTree.Node): boolean => {
  let current: ESTree.Node = node;
  let parent: ESTree.Node | null | undefined = current.parent;
  while (
    parent !== null &&
    parent !== undefined &&
    (parent.type === "TSAsExpression" ||
      parent.type === "TSTypeAssertion" ||
      parent.type === "TSNonNullExpression" ||
      parent.type === "TSSatisfiesExpression" ||
      parent.type === "ChainExpression")
  ) {
    current = parent;
    parent = parent.parent;
  }
  if (parent === null || parent == null) return false;

  if (
    parent.type === "UnaryExpression" &&
    parent.operator === "typeof" &&
    parent.argument === current
  ) {
    return true;
  }
  if (
    parent.type !== "CallExpression" ||
    !parent.arguments.some((arg): boolean => arg === current)
  ) {
    return false;
  }
  const callee = parent.callee;
  if (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.object.type === "Identifier" &&
    callee.object.name === "Array" &&
    callee.property.type === "Identifier" &&
    callee.property.name === "isArray"
  ) {
    return parent.arguments.length === 1;
  }
  return callee.type === "Identifier" && GUARD_NAME_RE.test(callee.name);
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
  test: ESTree.Expression,
  bindingName: string,
): ValidationPolarity | null => {
  if (test.type === "UnaryExpression" && test.operator === "!") {
    const inner = bindingValidationPolarity(test.argument, bindingName);
    return invertValidationPolarity(inner);
  }
  if (test.type === "BinaryExpression") {
    const typeofName = (
      node: ESTree.Expression | ESTree.PrivateIdentifier,
    ): string | null =>
      node.type === "UnaryExpression" &&
      node.operator === "typeof" &&
      node.argument.type === "Identifier"
        ? node.argument.name
        : null;
    const literalType = (
      node: ESTree.Expression | ESTree.PrivateIdentifier,
    ): string | null =>
      node.type === "Literal" &&
      typeof node.value === "string" &&
      PRIMITIVE_TYPEOF_RESULTS.has(node.value)
        ? node.value
        : null;
    const matches =
      (typeofName(test.left) === bindingName &&
        literalType(test.right) !== null) ||
      (typeofName(test.right) === bindingName &&
        literalType(test.left) !== null);
    if (!matches) return null;
    if (test.operator === "===" || test.operator === "==") {
      return "valid-when-true";
    }
    return test.operator === "!==" || test.operator === "!="
      ? "valid-when-false"
      : null;
  }
  return test.type === "CallExpression" &&
    test.arguments.length === 1 &&
    test.arguments[0]?.type === "Identifier" &&
    test.arguments[0].name === bindingName &&
    test.callee.type === "MemberExpression" &&
    !test.callee.computed &&
    test.callee.object.type === "Identifier" &&
    test.callee.object.name === "Array" &&
    test.callee.property.type === "Identifier" &&
    test.callee.property.name === "isArray"
    ? "valid-when-true"
    : null;
};

type PlainMemberAccess = {
  readonly object: string;
  readonly property: string;
};

const plainMemberAccess = (node: ESTree.Node): PlainMemberAccess | null =>
  node.type === "MemberExpression" &&
  !node.computed &&
  node.object.type === "Identifier" &&
  node.property.type === "Identifier"
    ? { object: node.object.name, property: node.property.name }
    : null;

const isSamePlainMember = (
  node: ESTree.Node,
  access: PlainMemberAccess,
): boolean => {
  const candidate = plainMemberAccess(node);
  return (
    candidate !== null &&
    candidate.object === access.object &&
    candidate.property === access.property
  );
};

const nodeWithin = (node: ESTree.Node, container: ESTree.Node): boolean =>
  node.range[0] >= container.range[0] && node.range[1] <= container.range[1];

/** Whether this use is dominated by a branch that validates the whole binding. */
const isUseWithinValidatedBranch = (
  node: ESTree.Node,
  bindingName: string,
): boolean => {
  for (
    let current: ESTree.Node | null | undefined = node.parent;
    current !== undefined && current !== null;
    current = current.parent
  ) {
    if (current.type === "ConditionalExpression") {
      const polarity = bindingValidationPolarity(current.test, bindingName);
      if (
        (polarity === "valid-when-true" &&
          nodeWithin(node, current.consequent)) ||
        (polarity === "valid-when-false" && nodeWithin(node, current.alternate))
      ) {
        return true;
      }
    }
    if (current.type === "IfStatement") {
      const polarity = bindingValidationPolarity(current.test, bindingName);
      if (validatedBranchContains(node, current, polarity)) {
        return true;
      }
    }
    if (
      current.type === "FunctionDeclaration" ||
      current.type === "FunctionExpression" ||
      current.type === "ArrowFunctionExpression"
    ) {
      return false;
    }
  }
  return false;
};

/** Whether this field use is dominated by validation of the identical field. */
const isMemberUseWithinValidatedBranch = (
  node: ESTree.MemberExpression,
  access: PlainMemberAccess,
): boolean => {
  for (
    let current: ESTree.Node | null | undefined = node.parent;
    current !== undefined && current !== null;
    current = current.parent
  ) {
    if (current.type === "ConditionalExpression") {
      const polarity = memberValidationPolarity(current.test, access);
      if (
        (polarity === "valid-when-true" &&
          nodeWithin(node, current.consequent)) ||
        (polarity === "valid-when-false" && nodeWithin(node, current.alternate))
      ) {
        return true;
      }
    }
    if (current.type === "IfStatement") {
      const polarity = memberValidationPolarity(current.test, access);
      if (validatedBranchContains(node, current, polarity)) {
        return true;
      }
    }
    if (
      current.type === "FunctionDeclaration" ||
      current.type === "FunctionExpression" ||
      current.type === "ArrowFunctionExpression"
    ) {
      return false;
    }
  }
  return false;
};

/** Whether a branch test validates one plain member access. */
const memberValidationPolarity = (
  test: ESTree.Expression,
  access: PlainMemberAccess,
): ValidationPolarity | null => {
  if (test.type === "UnaryExpression" && test.operator === "!") {
    const inner = memberValidationPolarity(test.argument, access);
    return invertValidationPolarity(inner);
  }
  if (test.type === "BinaryExpression") {
    const isMatchingTypeof = (node: ESTree.Node): boolean =>
      node.type === "UnaryExpression" &&
      node.operator === "typeof" &&
      isSamePlainMember(node.argument, access);
    const isPrimitiveType = (node: ESTree.Node): boolean =>
      node.type === "Literal" &&
      typeof node.value === "string" &&
      PRIMITIVE_TYPEOF_RESULTS.has(node.value);
    if (
      !(
        (isMatchingTypeof(test.left) && isPrimitiveType(test.right)) ||
        (isMatchingTypeof(test.right) && isPrimitiveType(test.left))
      )
    ) {
      return null;
    }
    if (test.operator === "===" || test.operator === "==") {
      return "valid-when-true";
    }
    return test.operator === "!==" || test.operator === "!="
      ? "valid-when-false"
      : null;
  }
  return test.type === "CallExpression" &&
    test.arguments.length === 1 &&
    test.arguments[0] !== undefined &&
    test.arguments[0].type !== "SpreadElement" &&
    isSamePlainMember(test.arguments[0], access) &&
    test.callee.type === "MemberExpression" &&
    !test.callee.computed &&
    test.callee.object.type === "Identifier" &&
    test.callee.object.name === "Array" &&
    test.callee.property.type === "Identifier" &&
    test.callee.property.name === "isArray"
    ? "valid-when-true"
    : null;
};

/**
 * A field extracted into a same-scope `const` is safe only when every later use
 * is either its validation test or confined to the proven-valid branch.
 */
const isFullyValidatedExtractedBinding = (
  member: ESTree.MemberExpression,
  source: Variable,
  context: Ctx,
): boolean => {
  const isValidationReference = (
    identifier: ESTree.BindingIdentifier,
  ): boolean => {
    for (
      let current: ESTree.Node | null | undefined = identifier.parent;
      current !== undefined && current !== null;
      current = current.parent
    ) {
      if (
        (current.type === "BinaryExpression" ||
          current.type === "CallExpression" ||
          current.type === "UnaryExpression") &&
        bindingValidationPolarity(current, identifier.name) !== null
      ) {
        return true;
      }
      if (
        current.type !== "UnaryExpression" &&
        current.type !== "MemberExpression" &&
        current.type !== "CallExpression"
      ) {
        return false;
      }
    }
    return false;
  };

  const isGuardedUse = (identifier: ESTree.BindingIdentifier): boolean =>
    isUseWithinValidatedBranch(identifier, identifier.name);

  const declarator = member.parent;
  if (
    declarator.type !== "VariableDeclarator" ||
    declarator.init !== member ||
    declarator.id.type !== "Identifier" ||
    declarator.parent?.type !== "VariableDeclaration" ||
    declarator.parent.kind !== "const"
  ) {
    return false;
  }
  const extracted = context.sourceCode.getDeclaredVariables(declarator)[0];
  if (extracted === undefined || extracted.scope !== source.scope) return false;
  let hasValueUse = false;
  for (const reference of extracted.references) {
    const identifier = reference.identifier;
    if (identifier.type !== "Identifier") return false;
    if (nodeWithin(identifier, declarator)) continue;
    if (isValidationReference(identifier)) continue;
    hasValueUse = true;
    if (!isGuardedUse(identifier)) return false;
  }
  return hasValueUse;
};

/** Detect calls in boolean-test positions, including logical wrappers. */
const isGuardTestPosition = (node: ESTree.Node): boolean => {
  let current: ESTree.Node = node;
  let parent: ESTree.Node | null | undefined = current.parent;
  while (parent !== undefined && parent !== null) {
    switch (parent.type) {
      case "UnaryExpression":
      case "LogicalExpression":
      case "ChainExpression":
        current = parent;
        parent = parent.parent;
        continue;
      case "IfStatement":
      case "ConditionalExpression":
      case "WhileStatement":
      case "DoWhileStatement":
      case "ForStatement":
        return parent.test === current;
      default:
        return false;
    }
  }
  return false;
};

const unvalidatedVariableRef = (
  node: ESTree.Node | null | undefined,
  scope: Scope,
  tracked: ReadonlySet<Variable>,
): Variable | null => {
  const unwrapped = unwrap(node);
  if (unwrapped === null || unwrapped.type !== "Identifier") {
    return null;
  }
  const variable = findVariable(scope, unwrapped.name);
  return variable !== null && tracked.has(variable) ? variable : null;
};

export default createRule<Options, MessageIds>({
  name: "prefer-schema-for-api-payload",
  documentation: PREFER_SCHEMA_FOR_API_PAYLOAD_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Require Zod (or similar) schema validation on `response.json()` / `JSON.parse()` results before property access.",
    },
    schema: [],
    messages: {
      unparsedJsonAccess:
        "Review property access on parsed JSON without a recognized validation boundary. For external payloads, validate before reading fields; validator implementations need manual review, not a recursive schema rewrite.",
    },
  },
  defaultOptions: [],
  create(context: Ctx) {
    // Fixtures and generated clients own validation at a different boundary.
    if (
      isTestFile(sourceOrigin(context).filename) ||
      isScriptFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
    ) {
      return {};
    }

    const unvalidatedVariables = new Set<Variable>();
    const aliasGroups = new Map<Variable, Set<Variable>>();
    const localFileTextVariables = new Set<Variable>();
    const namedGuards = new Map<Variable, ESTree.CallExpression[]>();

    const guardDominates = (
      use: ESTree.Node,
      call: ESTree.CallExpression,
    ): boolean => {
      if (
        context.sourceCode.getScope(use).variableScope !==
        context.sourceCode.getScope(call).variableScope
      )
        return false;
      let guard: ESTree.Node = call;
      let positive = true;
      while (
        guard.parent?.type === "UnaryExpression" &&
        guard.parent.operator === "!"
      ) {
        positive = !positive;
        guard = guard.parent;
      }
      while (
        positive &&
        guard.parent?.type === "LogicalExpression" &&
        guard.parent.operator === "&&"
      )
        guard = guard.parent;
      const branch = guard.parent;
      if (branch.type === "IfStatement" && branch.test === guard) {
        const dominated = ifGuardDominates(use, branch, positive);
        if (dominated !== null) return dominated;
      }
      if (branch.type === "ConditionalExpression" && branch.test === guard)
        return nodeWithin(use, positive ? branch.consequent : branch.alternate);
      if (positive && branch.type === "WhileStatement" && branch.test === guard)
        return nodeWithin(use, branch.body);
      if (
        call.parent?.type !== "ExpressionStatement" ||
        call.callee.type !== "Identifier" ||
        /^(?:is|has)[A-Z]/u.test(call.callee.name)
      )
        return false;
      return followsInSameContainer(use, call.parent);
    };

    /** Resolve a same-scope binding already proven to hold repository-local file text. */
    const localFileTextRef = (
      node: ESTree.Node | null | undefined,
      scope: Scope,
    ): Variable | null => {
      const unwrapped = unwrap(node);
      if (unwrapped?.type !== "Identifier") return null;
      const variable = findVariable(scope, unwrapped.name);
      return variable !== null && localFileTextVariables.has(variable)
        ? variable
        : null;
    };

    /** Record direct file reads and simple same-scope aliases; detach on every other write. */
    const updateLocalFileText = (
      target: Variable,
      value: ESTree.Node | null | undefined,
      scope: Scope,
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
    const clearBinding = (variable: Variable): void => {
      unvalidatedVariables.delete(variable);
      namedGuards.delete(variable);
      const group = aliasGroups.get(variable);
      aliasGroups.delete(variable);
      group?.delete(variable);
    };

    /** A validation read proves the shared payload behind every simple local alias. */
    const clearAliasGroup = (variable: Variable): void => {
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
    const trackRawBinding = (variable: Variable): void => {
      clearBinding(variable);
      const group = new Set([variable]);
      unvalidatedVariables.add(variable);
      aliasGroups.set(variable, group);
    };

    /** Track `target = source` as two bindings of the same unvalidated payload. */
    const trackAlias = (target: Variable, source: Variable): void => {
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
      declarator: ESTree.VariableDeclarator,
    ): boolean => {
      const declared = context.sourceCode.getDeclaredVariables(declarator);
      const statement = declarator.parent;
      const block = statement?.parent;
      const followsRejectingGuard = (
        identifier: ESTree.BindingIdentifier,
      ): boolean => {
        if (block?.type !== "BlockStatement" && block?.type !== "Program")
          return false;
        if (
          context.sourceCode.getScope(identifier).variableScope !==
          context.sourceCode.getScope(declarator).variableScope
        )
          return false;
        return block.body.some((candidate) => {
          if (
            candidate.type !== "IfStatement" ||
            candidate.range[1] >= identifier.range[0] ||
            bindingValidationPolarity(candidate.test, identifier.name) !==
              "valid-when-false"
          )
            return false;
          const terminal =
            candidate.consequent.type === "BlockStatement"
              ? candidate.consequent.body.at(-1)
              : candidate.consequent;
          return (
            terminal?.type === "ThrowStatement" ||
            terminal?.type === "ReturnStatement"
          );
        });
      };
      return (
        declared.length > 0 &&
        declared.every(
          (variable) =>
            variable.references.some((reference) =>
              isValidationRead(reference.identifier),
            ) &&
            variable.references.every((reference) => {
              const identifier = reference.identifier;
              if (reference.init === true) return true;
              if (reference.isWrite() || identifier.type !== "Identifier")
                return false;
              return (
                isValidationRead(identifier) ||
                isUseWithinValidatedBranch(identifier, identifier.name) ||
                followsRejectingGuard(identifier)
              );
            }),
        )
      );
    };

    const trackInitializer = (
      declarator: ESTree.VariableDeclarator,
      scope: Scope,
    ): void => {
      const declaredVars = context.sourceCode.getDeclaredVariables(declarator);
      const variable = declaredVars[0];
      if (variable === undefined) return;
      const localText = (candidate: ESTree.Node | null | undefined): boolean =>
        localFileTextRef(candidate, scope) !== null;
      if (isRawPayloadSource(declarator.init, context, localText)) {
        trackRawBinding(variable);
        return;
      }
      const source = unvalidatedVariableRef(
        declarator.init,
        scope,
        unvalidatedVariables,
      );
      if (source !== null) trackAlias(variable, source);
    };

    return {
      VariableDeclarator(node): void {
        const scope = context.sourceCode.getScope(node);

        if (node.id.type === "Identifier") {
          const variable = context.sourceCode.getDeclaredVariables(node)[0];
          if (variable !== undefined) {
            updateLocalFileText(variable, node.init, scope);
          }
          trackInitializer(node, scope);
          return;
        }

        if (
          node.id.type === "ObjectPattern" ||
          node.id.type === "ArrayPattern"
        ) {
          if (
            isRawPayloadSource(
              node.init,
              context,
              (candidate): boolean =>
                localFileTextRef(candidate, scope) !== null,
            )
          ) {
            if (!isFullyNarrowedPattern(node)) {
              context.report({
                node: node.id,
                messageId: "unparsedJsonAccess",
              });
            }
            return;
          }
          if (
            unvalidatedVariableRef(node.init, scope, unvalidatedVariables) !==
            null
          ) {
            context.report({ node: node.id, messageId: "unparsedJsonAccess" });
          }
        }
      },
      AssignmentExpression(node): void {
        const scope = context.sourceCode.getScope(node);

        if (node.left.type === "Identifier") {
          const variable = findVariable(scope, node.left.name);
          if (variable === null) return;
          const isLocalText = (
            candidate: ESTree.Node | null | undefined,
          ): boolean => localFileTextRef(candidate, scope) !== null;
          updateLocalFileText(variable, node.right, scope);
          if (isRawPayloadSource(node.right, context, isLocalText)) {
            trackRawBinding(variable);
          } else {
            const source = unvalidatedVariableRef(
              node.right,
              scope,
              unvalidatedVariables,
            );
            if (source === null) clearBinding(variable);
            else trackAlias(variable, source);
          }
          return;
        }

        if (
          node.left.type === "ObjectPattern" ||
          node.left.type === "ArrayPattern"
        ) {
          if (
            isRawPayloadSource(
              node.right,
              context,
              (candidate): boolean =>
                localFileTextRef(candidate, scope) !== null,
            )
          ) {
            context.report({
              node: node.left,
              messageId: "unparsedJsonAccess",
            });
            return;
          }
          if (
            unvalidatedVariableRef(node.right, scope, unvalidatedVariables) !==
            null
          ) {
            context.report({
              node: node.left,
              messageId: "unparsedJsonAccess",
            });
          }
        }
      },
      CallExpression(node): void {
        if (node.callee.type !== "Identifier") return;
        if (
          !GUARD_NAME_RE.test(node.callee.name) &&
          !isGuardTestPosition(node)
        ) {
          return;
        }
        const scope = context.sourceCode.getScope(node);
        for (const arg of node.arguments) {
          if (arg.type === "SpreadElement") continue;
          const unwrapped = unwrap(arg);
          if (unwrapped === null || unwrapped.type !== "Identifier") {
            continue;
          }
          const variable = findVariable(scope, unwrapped.name);
          if (variable !== null) {
            for (const alias of aliasGroups.get(variable) ?? [variable]) {
              const guards = namedGuards.get(alias) ?? [];
              guards.push(node);
              namedGuards.set(alias, guards);
            }
          }
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
            context,
            (candidate): boolean => localFileTextRef(candidate, scope) !== null,
          )
        ) {
          // Validation and promise methods are calls, not payload field reads.
          const parent = node.parent;
          if (
            parent.type === "CallExpression" &&
            parent.callee === node &&
            node.property.type === "Identifier" &&
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
          obj?.type === "Identifier"
            ? unvalidatedVariableRef(obj, scope, unvalidatedVariables)
            : null;
        if (variable !== null && obj?.type === "Identifier") {
          if (
            namedGuards
              .get(variable)
              ?.some((call) => guardDominates(node, call))
          )
            return;
          if (isUseWithinValidatedBranch(node, obj.name)) {
            return;
          }
          const access = plainMemberAccess(node);
          if (
            access !== null &&
            isMemberUseWithinValidatedBranch(node, access)
          ) {
            return;
          }
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

function invertValidationPolarity(
  polarity: ValidationPolarity | null,
): ValidationPolarity | null {
  if (polarity === "valid-when-true") return "valid-when-false";
  return polarity === "valid-when-false" ? "valid-when-true" : null;
}

function validatedBranchContains(
  node: ESTree.Node,
  branch: ESTree.IfStatement,
  polarity: ValidationPolarity | null,
): boolean {
  return (
    (polarity === "valid-when-true" && nodeWithin(node, branch.consequent)) ||
    (polarity === "valid-when-false" &&
      branch.alternate !== null &&
      nodeWithin(node, branch.alternate))
  );
}

function followsInSameContainer(
  use: ESTree.Node,
  preceding: ESTree.Node,
): boolean {
  let statement = use;
  while (
    statement.parent != null &&
    statement.parent !== preceding.parent &&
    statement.parent?.type !== "Program"
  ) {
    if (
      statement.type === "FunctionDeclaration" ||
      statement.type === "FunctionExpression" ||
      statement.type === "ArrowFunctionExpression"
    )
      return false;
    statement = statement.parent;
  }
  return (
    statement.parent === preceding.parent &&
    statement.range[0] > preceding.range[1]
  );
}

function ifGuardDominates(
  use: ESTree.Node,
  branch: ESTree.IfStatement,
  positive: boolean,
): boolean | null {
  if (positive && nodeWithin(use, branch.consequent)) return true;
  if (
    !positive &&
    branch.alternate !== null &&
    nodeWithin(use, branch.alternate)
  )
    return true;
  const terminal =
    branch.consequent.type === "BlockStatement"
      ? branch.consequent.body.at(-1)
      : branch.consequent;
  if (
    !positive &&
    (terminal?.type === "ThrowStatement" ||
      terminal?.type === "ReturnStatement")
  ) {
    return followsInSameContainer(use, branch);
  }
  return null;
}

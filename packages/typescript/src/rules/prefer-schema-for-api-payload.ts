/**
 * @fileoverview prefer-schema-for-api-payload — reading a field off `response.json()` propagates `any` inward from the network boundary.
 *
 * Port of the 18.x `prefer-schema-for-api-payload` rule. Same
 * algorithm; the test/script/generated file gate and per-file state reset run
 * in `before()`. Parent walks use `parentOf()` because Oxlint's
 * `Program.parent` is `null`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-schema-for-api-payload.test.ts
 */

import { defineRule, type Context, type ESTree, type Node, type Scope, type SourceCode, type TsVariable } from "../types.js";
import { tsVariable } from "../types.js";
import { forEachOwnAstChild, isErasedExpression, parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { nativeFetchReference } from "../utils/native-fetch-reference.js";
import { isGeneratedFile, isScriptFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "prefer-schema-for-api-payload";

type Identifier = Extract<Node, { type: "Identifier" }>;
type IsKnownLocalText = (candidate: Node | null | undefined) => boolean;

/** Peel TypeScript wrappers and optional chains, which do not affect the underlying value. */
const unwrap = (node: Node | null | undefined): Node | null => {
  let current = node ?? null;
  while (current !== null && (isErasedExpression(current) || current.type === "ChainExpression")) current = current.expression;
  return current;
};

/** Promise methods that preserve an unvalidated payload. */
const PROMISE_CHAIN_METHODS: ReadonlySet<string> = new Set(["then", "catch", "finally"]);

/** True for `ZUser.parse` / `ZUser.safeParse` handed to a chain link as a callback. */
const isSchemaParseReference = (node: Node | null | undefined): boolean => {
  const inner = unwrap(node);
  if (inner?.type !== "MemberExpression") return false;
  const name = getPropertyName(inner);
  return name === "parse" || name === "safeParse";
};

/** Match optionally awaited `.json()` calls and non-local `JSON.parse()` calls. */
const isRawPayloadSource = (node: Node | null | undefined, context: Context, isKnownLocalText: IsKnownLocalText): boolean => {
  let current = unwrap(node);
  if (current?.type === "AwaitExpression") current = unwrap(current.argument);
  if (current?.type !== "CallExpression") return false;
  const callee = unwrap(current.callee);
  if (callee?.type !== "MemberExpression") return false;
  const property = getPropertyName(callee);
  if (property === "json") return current.arguments.length === 0 && isResponseSource(callee.object, context);
  // Promise methods preserve taint unless their callback is a schema parser.
  if (property !== null && PROMISE_CHAIN_METHODS.has(property)) {
    return !current.arguments.some(isSchemaParseReference) && isRawPayloadSource(callee.object, context, isKnownLocalText);
  }
  // Other `.parse()` calls may be the requested schema validation.
  return property === "parse" && isJsonParseOfPeerText(current, callee.object, context, isKnownLocalText);
};

/** `JSON.parse(text)` where `text` is neither `JSON.stringify(...)` nor repository-local file text. */
const isJsonParseOfPeerText = (
  call: ESTree.CallExpression,
  receiver: Node,
  context: Context,
  isKnownLocalText: IsKnownLocalText,
): boolean => {
  const object = unwrap(receiver);
  const [text] = call.arguments;
  return object?.type === "Identifier" && object.name === "JSON" && isUnshadowedGlobal(object, context) &&
    !isJsonStringifyCall(unwrap(text), context) && !isLocalFileRead(text) && !isKnownLocalText(text);
};

const isJsonStringifyCall = (node: Node | null, context: Context): boolean =>
  node?.type === "CallExpression" &&
  node.arguments.length === 1 &&
  node.callee.type === "MemberExpression" &&
  node.callee.object.type === "Identifier" &&
  node.callee.object.name === "JSON" &&
  getPropertyName(node.callee) === "stringify" &&
  isUnshadowedGlobal(node.callee.object, context);

const isUnshadowedGlobal = (identifier: Identifier, context: Context): boolean =>
  (findVariable(context.sourceCode.getScope(identifier), identifier.name)?.defs.length ?? 0) === 0;

const RESPONSE_GLOBALS: ReadonlySet<string> = new Set(["Request", "Response"]);

const isResponseGlobal = (node: Node, context: Context): boolean =>
  node.type === "Identifier" && RESPONSE_GLOBALS.has(node.name) && isUnshadowedGlobal(node, context);

const isResponseSource = (node: Node, context: Context, seen = new Set<Node>()): boolean => {
  let current = unwrap(node);
  if (current?.type === "AwaitExpression") current = unwrap(current.argument);
  if (current === null || seen.has(current)) return false;
  seen.add(current);
  if (current.type === "CallExpression") return nativeFetchReference(current.callee, context.sourceCode);
  if (current.type === "NewExpression") return isResponseGlobal(current.callee, context);
  return current.type === "Identifier" && isResponseBinding(current, context, seen);
};

/** A never-reassigned binding annotated `Request`/`Response`, or a `const` initialized from a response source. */
const isResponseBinding = (identifier: Identifier, context: Context, seen: Set<Node>): boolean => {
  const binding = findVariable(context.sourceCode.getScope(identifier), identifier.name);
  if (binding?.defs.length !== 1 || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
  const [definition] = binding.defs;
  if (definition === undefined) return false;
  if (hasResponseAnnotation(definition.name, context)) return true;
  if (definition.type !== "Variable" || (definition.parent as ESTree.VariableDeclaration | null)?.kind !== "const") return false;
  const declarator = definition.node as ESTree.VariableDeclarator;
  return declarator.init !== null && isResponseSource(declarator.init, context, seen);
};

/** `name: Request` or `name: Response`, naming the globals. */
const hasResponseAnnotation = (name: Node, context: Context): boolean => {
  const annotation = name.type === "Identifier" ? name.typeAnnotation?.typeAnnotation : undefined;
  return annotation?.type === "TSTypeReference" && isResponseGlobal(annotation.typeName, context);
};

/** Filesystem readers whose result is repo-local text, not a peer's payload. */
const FILE_READ_RE = /^(readFile|readFileSync|readJson|readJsonSync|readJSON)$/;

/** A direct filesystem reader expression, optionally wrapped in `await` or TS syntax. */
const isDirectLocalFileRead = (node: Node | null | undefined): boolean => {
  let current = unwrap(node);
  if (current?.type === "AwaitExpression") current = unwrap(current.argument);
  if (current?.type !== "CallExpression") return false;
  const callee = unwrap(current.callee);
  const name =
    callee?.type === "Identifier"
      ? callee.name
      : callee?.type === "MemberExpression"
        ? getPropertyName(callee)
        : null;
  return name !== null && FILE_READ_RE.test(name);
};

/** Exempt repository-local JSON read through a recognized filesystem reader. */
const isLocalFileRead = (node: Node | null | undefined): boolean => {
  let found = false;
  const visit = (current: Node | null | undefined): void => {
    if (found || current === null || current === undefined) return;
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

/** Validation and promise methods called on a payload are not field reads. */
const isPayloadMethodCall = (node: ESTree.MemberExpression): boolean => {
  const parent = parentOf(node);
  const method = getPropertyName(node);
  return parent?.type === "CallExpression" && parent.callee === node && method !== null &&
    (method === "parse" || method === "safeParse" || PROMISE_CHAIN_METHODS.has(method));
};

/** Reads an assertion consumes or a validator inspects. */
const isExemptRead = (node: Node): boolean => isInsideAssertion(node) || isValidationRead(node);

/** Assertion helpers whose argument is being checked, not consumed. */
const ASSERTION_CALLEE_RE = /^(expect|assert|should|invariant)$/;

/** Exempt reads consumed by an assertion such as `expect(value.id).toBe(1)`. */
const isInsideAssertion = (node: Node): boolean => {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type !== "CallExpression") continue;
    let callee: Node = current.callee;
    while (callee.type === "MemberExpression") callee = callee.object;
    if (callee.type === "CallExpression") callee = callee.callee;
    if (callee.type === "Identifier" && ASSERTION_CALLEE_RE.test(callee.name)) return true;
  }
  return false;
};

/** Names that conventionally identify guards or validators. */
const GUARD_NAME_RE = /^(?:is|validate|parse|assert|decode|coerce)[A-Z]/;

const isArrayIsArrayCallee = (callee: Node): boolean =>
  callee.type === "MemberExpression" &&
  callee.object.type === "Identifier" &&
  callee.object.name === "Array" &&
  getPropertyName(callee) === "isArray";

/** Exempt a field read used by `typeof`, `Array.isArray`, or a named validator. */
const isValidationRead = (node: Node): boolean => {
  let current: Node = node;
  let parent = parentOf(current);
  while (
    parent !== null &&
    (parent.type === "TSAsExpression" ||
      parent.type === "TSTypeAssertion" ||
      parent.type === "TSNonNullExpression" ||
      parent.type === "TSSatisfiesExpression" ||
      parent.type === "ChainExpression")
  ) {
    current = parent;
    parent = parentOf(parent);
  }
  if (parent === null) return false;
  if (parent.type === "UnaryExpression" && parent.operator === "typeof" && parent.argument === current) return true;
  if (parent.type !== "CallExpression" || !parent.arguments.some((arg) => arg === current)) return false;
  const callee = parent.callee;
  if (isArrayIsArrayCallee(callee)) return parent.arguments.length === 1;
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

/** Whether `test` proves the primitive/array shape of the value `isSubject` matches, and on which branch. */
const validationPolarity = (test: Node, isSubject: (node: Node) => boolean): ValidationPolarity | null => {
  if (test.type === "UnaryExpression" && test.operator === "!") {
    return invertValidationPolarity(validationPolarity(test.argument, isSubject));
  }
  if (test.type === "BinaryExpression") {
    const isSubjectTypeof = (node: Node): boolean =>
      node.type === "UnaryExpression" && node.operator === "typeof" && isSubject(node.argument);
    const left = test.left as Node;
    const matches =
      (isSubjectTypeof(left) && isPrimitiveTypeLiteral(test.right)) ||
      (isSubjectTypeof(test.right) && isPrimitiveTypeLiteral(left));
    return matches ? comparisonPolarity(test.operator) : null;
  }
  if (test.type !== "CallExpression" || test.arguments.length !== 1) return null;
  const [argument] = test.arguments;
  return argument !== undefined && argument.type !== "SpreadElement" && isSubject(argument) && isArrayIsArrayCallee(test.callee)
    ? "valid-when-true"
    : null;
};

const isPrimitiveTypeLiteral = (node: Node): boolean =>
  node.type === "Literal" && typeof node.value === "string" && PRIMITIVE_TYPEOF_RESULTS.has(node.value);

const comparisonPolarity = (operator: string): ValidationPolarity | null => {
  if (operator === "===" || operator === "==") return "valid-when-true";
  return operator === "!==" || operator === "!=" ? "valid-when-false" : null;
};

/** Whether `test` proves one binding's primitive/array shape, and on which branch. */
const bindingValidationPolarity = (test: Node, bindingName: string): ValidationPolarity | null =>
  validationPolarity(test, (node) => node.type === "Identifier" && node.name === bindingName);

interface PlainMemberAccess {
  readonly object: string;
  readonly property: string;
}

const plainMemberAccess = (node: Node): PlainMemberAccess | null => {
  if (node.type !== "MemberExpression" || node.object.type !== "Identifier") return null;
  const property = getPropertyName(node);
  return property === null ? null : { object: node.object.name, property };
};

const isSamePlainMember = (node: Node, access: PlainMemberAccess): boolean => {
  const candidate = plainMemberAccess(node);
  return candidate !== null && candidate.object === access.object && candidate.property === access.property;
};

const nodeWithin = (node: Node, container: Node): boolean =>
  node.range[0] >= container.range[0] && node.range[1] <= container.range[1];

const isFunctionNode = (node: Node): boolean =>
  node.type === "FunctionDeclaration" || node.type === "FunctionExpression" || node.type === "ArrowFunctionExpression";

/** Walk enclosing branches up to the function boundary, asking `polarityOf` for each test. */
const withinValidatedBranch = (node: Node, polarityOf: (test: Node) => ValidationPolarity | null): boolean => {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if ((current.type === "ConditionalExpression" || current.type === "IfStatement") &&
      validatedBranchContains(node, current, polarityOf(current.test))) return true;
    if (isFunctionNode(current)) return false;
  }
  return false;
};

/** Whether this use is dominated by a branch that validates the whole binding. */
const isUseWithinValidatedBranch = (node: Node, bindingName: string): boolean =>
  withinValidatedBranch(node, (test) => bindingValidationPolarity(test, bindingName));

/** Whether this field use is dominated by validation of the identical field. */
const isMemberUseWithinValidatedBranch = (node: ESTree.MemberExpression, access: PlainMemberAccess): boolean =>
  withinValidatedBranch(node, (test) => memberValidationPolarity(test, access));

/** Whether a branch test validates one plain member access. */
const memberValidationPolarity = (test: Node, access: PlainMemberAccess): ValidationPolarity | null =>
  validationPolarity(test, (node) => isSamePlainMember(node, access));

/**
 * A field extracted into a same-scope `const` is safe only when every later use
 * is either its validation test or confined to the proven-valid branch.
 */
const isFullyValidatedExtractedBinding = (
  member: ESTree.MemberExpression,
  source: TsVariable,
  context: Context,
): boolean => {
  const declarator = parentOf(member);
  if (declarator?.type !== "VariableDeclarator" || declarator.init !== member || declarator.id.type !== "Identifier") return false;
  const declaration = parentOf(declarator);
  if (declaration?.type !== "VariableDeclaration" || declaration.kind !== "const") return false;
  const declared = context.sourceCode.getDeclaredVariables(declarator)[0];
  return declared !== undefined && declared.scope === source.scope && onlyValidatedUses(tsVariable(declared), declarator);
};

/** Every use of `extracted` outside its declarator validates it or sits in its proven-valid branch, and at least one is such a branch use. */
const onlyValidatedUses = (extracted: TsVariable, declarator: ESTree.VariableDeclarator): boolean => {
  let hasValueUse = false;
  for (const reference of extracted.references) {
    const identifier = reference.identifier as Node;
    if (identifier.type !== "Identifier") return false;
    if (nodeWithin(identifier, declarator)) continue;
    if (isValidationReference(identifier)) continue;
    hasValueUse = true;
    if (!isUseWithinValidatedBranch(identifier, identifier.name)) return false;
  }
  return hasValueUse;
};

/** Whether this reference sits inside a test that validates its own binding. */
const isValidationReference = (identifier: Identifier): boolean => {
  for (let current = parentOf(identifier); current !== null; current = parentOf(current)) {
    if (
      (current.type === "BinaryExpression" || current.type === "CallExpression" || current.type === "UnaryExpression") &&
      bindingValidationPolarity(current, identifier.name) !== null
    ) return true;
    if (current.type !== "UnaryExpression" && current.type !== "MemberExpression" && current.type !== "CallExpression") return false;
  }
  return false;
};

/** Detect calls in boolean-test positions, including logical wrappers. */
const isGuardTestPosition = (node: Node): boolean => {
  let current: Node = node;
  let parent = parentOf(current);
  while (parent !== null) {
    switch (parent.type) {
      case "UnaryExpression":
      case "LogicalExpression":
      case "ChainExpression":
        current = parent;
        parent = parentOf(parent);
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
  node: Node | null | undefined,
  scope: Scope,
  tracked: ReadonlySet<TsVariable>,
): TsVariable | null => {
  const unwrapped = unwrap(node);
  if (unwrapped === null || unwrapped.type !== "Identifier") return null;
  const variable = findVariable(scope, unwrapped.name);
  return variable !== null && tracked.has(variable) ? variable : null;
};

function invertValidationPolarity(polarity: ValidationPolarity | null): ValidationPolarity | null {
  if (polarity === "valid-when-true") return "valid-when-false";
  return polarity === "valid-when-false" ? "valid-when-true" : null;
}

function validatedBranchContains(
  node: Node,
  branch: ESTree.IfStatement | ESTree.ConditionalExpression,
  polarity: ValidationPolarity | null,
): boolean {
  return (polarity === "valid-when-true" && nodeWithin(node, branch.consequent)) ||
    (polarity === "valid-when-false" && branch.alternate !== null && nodeWithin(node, branch.alternate));
}

function followsInSameContainer(use: Node, preceding: Node): boolean {
  const container = parentOf(preceding);
  let statement = use;
  for (let parent = parentOf(statement); parent !== null && parent !== container && parent.type !== "Program"; parent = parentOf(statement)) {
    if (isFunctionNode(statement)) return false;
    statement = parent;
  }
  return parentOf(statement) === container && statement.range[0] > preceding.range[1];
}

function terminalStatement(branch: ESTree.IfStatement): Node | undefined {
  const consequent = branch.consequent as Node;
  return consequent.type === "BlockStatement" ? (consequent.body as readonly Node[]).at(-1) : consequent;
}

function isAbruptTerminal(node: Node | undefined): boolean {
  return node?.type === "ThrowStatement" || node?.type === "ReturnStatement";
}

/** Predicates (`isX`, `hasX`) only guard as branch tests; any other named guard statement asserts what follows it. */
const PREDICATE_NAME_RE = /^(?:is|has)[A-Z]/u;

function guardDominates(sourceCode: SourceCode, use: Node, call: ESTree.CallExpression): boolean {
  if (sourceCode.getScope(use).variableScope !== sourceCode.getScope(call).variableScope) return false;
  const { test, positive } = guardTest(call);
  const dominated = branchGuardDominates(use, test, positive);
  if (dominated !== null) return dominated;
  const statement = parentOf(call);
  return statement?.type === "ExpressionStatement" && call.callee.type === "Identifier" &&
    !PREDICATE_NAME_RE.test(call.callee.name) && followsInSameContainer(use, statement);
}

/** The outermost test a guard call decides through `!` and `&&`, and whether that test being true means the guard passed. */
function guardTest(call: ESTree.CallExpression): { readonly test: Node; readonly positive: boolean } {
  let test: Node = call;
  let positive = true;
  for (let parent = parentOf(test); parent?.type === "UnaryExpression" && parent.operator === "!"; parent = parentOf(test)) {
    positive = !positive;
    test = parent;
  }
  for (let parent = parentOf(test); positive && parent?.type === "LogicalExpression" && parent.operator === "&&"; parent = parentOf(test)) {
    test = parent;
  }
  return { test, positive };
}

/** Whether a guard that is a branch test dominates `use`; null when it is no branch test or proves nothing there. */
function branchGuardDominates(use: Node, test: Node, positive: boolean): boolean | null {
  const branch = parentOf(test);
  if (branch?.type === "IfStatement" && branch.test === test) return ifGuardDominates(use, branch, positive);
  if (branch?.type === "ConditionalExpression" && branch.test === test) return nodeWithin(use, positive ? branch.consequent : branch.alternate);
  if (positive && branch?.type === "WhileStatement" && branch.test === test) return nodeWithin(use, branch.body);
  return null;
}

function ifGuardDominates(use: Node, branch: ESTree.IfStatement, positive: boolean): boolean | null {
  if (positive && nodeWithin(use, branch.consequent)) return true;
  if (!positive && branch.alternate !== null && nodeWithin(use, branch.alternate)) return true;
  if (!positive && isAbruptTerminal(terminalStatement(branch))) return followsInSameContainer(use, branch);
  return null;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Require Zod (or similar) schema validation on `response.json()` / `JSON.parse()` results before property access.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      unparsedJsonAccess:
        "Review property access on parsed JSON without a recognized validation boundary. For external payloads, validate before reading fields; validator implementations need manual review, not a recursive schema rewrite.",
    },
  },
  createOnce(context) {
    const unvalidatedVariables = new Set<TsVariable>();
    const aliasGroups = new Map<TsVariable, Set<TsVariable>>();
    const localFileTextVariables = new Set<TsVariable>();
    const namedGuards = new Map<TsVariable, ESTree.CallExpression[]>();

    const declaredVariables = (node: ESTree.VariableDeclarator): TsVariable[] =>
      context.sourceCode.getDeclaredVariables(node).map(tsVariable);

    /** Resolve a same-scope binding already proven to hold repository-local file text. */
    const localFileTextRef = (node: Node | null | undefined, scope: Scope): TsVariable | null => {
      const unwrapped = unwrap(node);
      if (unwrapped?.type !== "Identifier") return null;
      const variable = findVariable(scope, unwrapped.name);
      return variable !== null && localFileTextVariables.has(variable) ? variable : null;
    };

    const isLocalTextIn = (scope: Scope): IsKnownLocalText => (candidate) => localFileTextRef(candidate, scope) !== null;

    /** Record direct file reads and simple same-scope aliases; detach on every other write. */
    const updateLocalFileText = (target: TsVariable, value: Node | null | undefined, scope: Scope): void => {
      const source = localFileTextRef(value, scope);
      if (isDirectLocalFileRead(value) || (source !== null && source.scope === target.scope)) {
        localFileTextVariables.add(target);
      } else {
        localFileTextVariables.delete(target);
      }
    };

    /** Stop tracking one binding without changing aliases of its previous value. */
    const clearBinding = (variable: TsVariable): void => {
      unvalidatedVariables.delete(variable);
      namedGuards.delete(variable);
      const group = aliasGroups.get(variable);
      aliasGroups.delete(variable);
      group?.delete(variable);
    };

    /** A validation read proves the shared payload behind every simple local alias. */
    const clearAliasGroup = (variable: TsVariable): void => {
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
    const trackRawBinding = (variable: TsVariable): void => {
      clearBinding(variable);
      const group = new Set([variable]);
      unvalidatedVariables.add(variable);
      aliasGroups.set(variable, group);
    };

    /** Track `target = source` as two bindings of the same unvalidated payload. */
    const trackAlias = (target: TsVariable, source: TsVariable): void => {
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
    const isFullyNarrowedPattern = (declarator: ESTree.VariableDeclarator): boolean => {
      const sourceCode = context.sourceCode;
      const declared = declaredVariables(declarator);
      const statement = parentOf(declarator);
      const block = statement === null ? null : parentOf(statement);
      const followsRejectingGuard = (identifier: Identifier): boolean => {
        if (block?.type !== "BlockStatement" && block?.type !== "Program") return false;
        if (sourceCode.getScope(identifier).variableScope !== sourceCode.getScope(declarator).variableScope) return false;
        return (block.body as readonly Node[]).some((candidate) => {
          if (candidate.type !== "IfStatement" || candidate.range[1] >= identifier.range[0] ||
            bindingValidationPolarity(candidate.test, identifier.name) !== "valid-when-false") return false;
          return isAbruptTerminal(terminalStatement(candidate));
        });
      };
      return (
        declared.length > 0 &&
        declared.every((variable) =>
          variable.references.some((reference) => isValidationRead(reference.identifier)) && variable.references.every((reference) => {
            const identifier = reference.identifier as Node;
            if (reference.init === true) return true;
            if (reference.isWrite() || identifier.type !== "Identifier") return false;
            return isValidationRead(identifier) || isUseWithinValidatedBranch(identifier, identifier.name) || followsRejectingGuard(identifier);
          }),
        )
      );
    };

    const trackInitializer = (declarator: ESTree.VariableDeclarator, scope: Scope): void => {
      const variable = declaredVariables(declarator)[0];
      if (variable === undefined) return;
      if (isRawPayloadSource(declarator.init, context, isLocalTextIn(scope))) {
        trackRawBinding(variable);
        return;
      }
      const source = unvalidatedVariableRef(declarator.init, scope, unvalidatedVariables);
      if (source !== null) trackAlias(variable, source);
    };

    /** Destructuring a raw payload, unless `narrowed`, or an alias of one reads its fields without validation. */
    const isUnvalidatedDestructuring = (value: Node | null, scope: Scope, narrowed: () => boolean): boolean =>
      isRawPayloadSource(value, context, isLocalTextIn(scope))
        ? !narrowed()
        : unvalidatedVariableRef(value, scope, unvalidatedVariables) !== null;

    const isValidatedUse = (node: ESTree.MemberExpression, variable: TsVariable): boolean => {
      if (namedGuards.get(variable)?.some((call) => guardDominates(context.sourceCode, node, call))) return true;
      if (isUseWithinValidatedBranch(node, variable.name)) return true;
      const access = plainMemberAccess(node);
      return (access !== null && isMemberUseWithinValidatedBranch(node, access)) ||
        isFullyValidatedExtractedBinding(node, variable, context);
    };

    const mayReadPayload = (object: Node): boolean =>
      object.type === "Identifier"
        ? unvalidatedVariables.size > 0
        : object.type === "CallExpression" || object.type === "AwaitExpression";

    return {
      before() {
        unvalidatedVariables.clear();
        aliasGroups.clear();
        localFileTextVariables.clear();
        namedGuards.clear();
        // Fixtures and generated clients own validation at a different boundary.
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isScriptFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        return undefined;
      },
      VariableDeclarator(node) {
        const scope = context.sourceCode.getScope(node);
        if (node.id.type === "Identifier") {
          const variable = declaredVariables(node)[0];
          if (variable !== undefined) updateLocalFileText(variable, node.init, scope);
          trackInitializer(node, scope);
          return;
        }
        if ((node.id.type === "ObjectPattern" || node.id.type === "ArrayPattern") &&
          isUnvalidatedDestructuring(node.init, scope, () => isFullyNarrowedPattern(node))) {
          context.report({ node: node.id, messageId: "unparsedJsonAccess" });
        }
      },
      AssignmentExpression(node) {
        const scope = context.sourceCode.getScope(node);
        const left = node.left as Node;
        if (left.type === "Identifier") {
          const variable = findVariable(scope, left.name);
          if (variable === null) return;
          updateLocalFileText(variable, node.right, scope);
          if (isRawPayloadSource(node.right, context, isLocalTextIn(scope))) {
            trackRawBinding(variable);
          } else {
            const source = unvalidatedVariableRef(node.right, scope, unvalidatedVariables);
            if (source === null) clearBinding(variable);
            else trackAlias(variable, source);
          }
          return;
        }
        if ((left.type === "ObjectPattern" || left.type === "ArrayPattern") &&
          isUnvalidatedDestructuring(node.right, scope, () => false)) {
          context.report({ node: left, messageId: "unparsedJsonAccess" });
        }
      },
      CallExpression(node) {
        if (node.callee.type !== "Identifier") return;
        if (!GUARD_NAME_RE.test(node.callee.name) && !isGuardTestPosition(node)) return;
        const scope = context.sourceCode.getScope(node);
        for (const arg of node.arguments) {
          if (arg.type === "SpreadElement") continue;
          const unwrapped = unwrap(arg);
          if (unwrapped === null || unwrapped.type !== "Identifier") continue;
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
      MemberExpression(node) {
        const obj = unwrap(node.object);
        // Only a raw payload call or a tracked binding can be read here; skip the scope and ancestor walks otherwise.
        if (obj === null || !mayReadPayload(obj)) return;
        const scope = context.sourceCode.getScope(node);
        if (isRawPayloadSource(obj, context, isLocalTextIn(scope))) {
          if (!isPayloadMethodCall(node) && !isExemptRead(node)) context.report({ node, messageId: "unparsedJsonAccess" });
          return;
        }
        const variable = unvalidatedVariableRef(obj, scope, unvalidatedVariables);
        if (variable === null || isExemptRead(node) || isValidatedUse(node, variable)) return;
        context.report({ node, messageId: "unparsedJsonAccess" });
        clearAliasGroup(variable);
      },
    };
  },
});

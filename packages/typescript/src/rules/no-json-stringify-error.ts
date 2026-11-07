/**
 * @fileoverview no-json-stringify-error — `JSON.stringify` on an Error yields `{}` — `message` and `stack` are non-enumerable.
 *
 * Port of the 18.x `no-json-stringify-error` rule. Same algorithm. The
 * per-file write summary is keyed by `sourceCode.ast` (the original keys it by
 * `sourceCode`, which Oxlint reuses for every file), and parents are read with
 * `parentOf()` because Oxlint's `Program.parent` is `null`.
 */

import { defineRule, type ESTree, type Node, type Scope, type SourceCode, type TsVariable } from "../types.js";
import { forEachAstChild, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { findVariable, scopedStaticString, staticPropertyName } from "../utils/static-string.js";

const NAME = "no-json-stringify-error";

type Identifier = Extract<Node, { type: "Identifier" }>;

const BUILTIN_ERROR_CONSTRUCTORS: ReadonlySet<string> = new Set([
  "AggregateError",
  "DOMException",
  "Error",
  "EvalError",
  "RangeError",
  "ReferenceError",
  "SyntaxError",
  "TypeError",
  "URIError",
]);

const TRACKED_BUILTINS: ReadonlySet<string> = new Set([...BUILTIN_ERROR_CONSTRUCTORS, "JSON", "JSON.stringify"]);

function nativeObjectName(expression: Node, sourceCode: SourceCode): "globalThis" | "JSON" | null {
  const value = unwrapExpression(expression);
  if (value.type === "Identifier" && (value.name === "globalThis" || value.name === "JSON") && isGlobalIdentifier(value.name, sourceCode.getScope(value))) return value.name;
  if (value.type === "MemberExpression" && nativeObjectName(value.object, sourceCode) === "globalThis" && staticPropertyName(value, sourceCode) === "JSON") return "JSON";
  return null;
}

function globalBuiltinName(expression: Node, sourceCode: SourceCode): string | null {
  const value = unwrapExpression(expression);
  if (value.type === "Identifier") return TRACKED_BUILTINS.has(value.name) && isGlobalIdentifier(value.name, sourceCode.getScope(value)) ? value.name : null;
  if (value.type !== "MemberExpression") return null;
  const receiver = nativeObjectName(value.object, sourceCode);
  const name = staticPropertyName(value, sourceCode);
  if (receiver === "JSON") return name === "stringify" ? "JSON.stringify" : null;
  return receiver === "globalThis" && name !== null && name !== "JSON.stringify" && TRACKED_BUILTINS.has(name) ? name : null;
}

/** Self-assignment and native truthy/non-null defaults do not replace the tracked built-in. */
function writePreservesBuiltin(target: Identifier | ESTree.MemberExpression, sourceCode: SourceCode): boolean {
  const assignment = parentOf(target);
  if (assignment?.type !== "AssignmentExpression" || assignment.left !== target) return false;
  const name = globalBuiltinName(target, sourceCode);
  if (name === null) return false;
  if (assignment.operator === "||=" || assignment.operator === "??=") return true;
  return (assignment.operator === "=" || assignment.operator === "&&=") && globalBuiltinName(assignment.right, sourceCode) === name;
}

const PATTERN_VALUE_TYPES: ReadonlySet<string> = new Set(["AssignmentPattern", "ArrayPattern", "ObjectPattern", "TSEmptyBodyFunctionExpression"]);

/** Property values that only occur in patterns or bodiless declarations, never as serialized data. */
function isPatternValue(value: Node): boolean {
  return PATTERN_VALUE_TYPES.has(value.type);
}

const NON_CALLABLE_VALUE_TYPES: ReadonlySet<string> = new Set(["Literal", "TemplateLiteral", "ObjectExpression", "ArrayExpression"]);
const MUTATION_OWNERS: ReadonlySet<string> = new Set(["Reflect", "Object"]);

function mayBeCallable(value: Node): boolean {
  return !NON_CALLABLE_VALUE_TYPES.has(value.type);
}

interface WriteSummary { earliestStatementStart: number; unknownOrder: boolean }
// Cache each file's explicit writes, with constant-cost queries per read. Oxlint
// reuses one SourceCode object for every file, so key by the file's AST.
const BUILTIN_WRITES = new WeakMap<object, ReadonlyMap<string | TsVariable, WriteSummary>>();

const DEFERRED_OR_REPEATED: ReadonlySet<string> = new Set(["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression", "ClassBody", "StaticBlock", "ForStatement", "ForInStatement", "ForOfStatement", "WhileStatement", "DoWhileStatement"]);

/** A top-level statement executes once; deferred functions and repeated loops do not prove ordering. */
function directProgramStatement(node: Node): Node | null {
  let current = node;
  for (let parent = parentOf(current); parent !== null; parent = parentOf(current)) {
    if (parent.type === "Program") return current;
    if (DEFERRED_OR_REPEATED.has(parent.type)) return null;
    current = parent;
  }
  return null;
}

function hasUnchangedBuiltin(name: string | TsVariable, read: Node, sourceCode: SourceCode): boolean {
  const summary = builtinWrites(sourceCode).get(name);
  if (summary === undefined) return true;
  const statement = directProgramStatement(read);
  return !summary.unknownOrder && statement !== null && statement.range[1] <= summary.earliestStatementStart;
}

function builtinWrites(sourceCode: SourceCode): ReadonlyMap<string | TsVariable, WriteSummary> {
  const cached = BUILTIN_WRITES.get(sourceCode.ast);
  if (cached !== undefined) return cached;
  const writes = new Map<string | TsVariable, WriteSummary>();
  const record = (name: string | TsVariable, node: Node): void => {
    const statement = directProgramStatement(node);
    const existing = writes.get(name);
    writes.set(name, { earliestStatementStart: Math.min(existing?.earliestStatementStart ?? Infinity, statement?.range[0] ?? Infinity), unknownOrder: (existing?.unknownOrder ?? false) || statement === null });
  };
  for (const scope of sourceCode.scopeManager?.scopes ?? []) {
    for (const reference of scope.references) {
      const name = reference.identifier.name;
      if (reference.identifier.type === "Identifier" && reference.isWrite() && TRACKED_BUILTINS.has(name) && (reference.resolved === null || reference.resolved.defs.length === 0) && !writePreservesBuiltin(reference.identifier, sourceCode)) record(name, reference.identifier);
    }
  }
  const propertyReceiver = (expression: Node): string | TsVariable | null => {
    const native = nativeObjectName(expression, sourceCode);
    if (native !== null) return native;
    const value = unwrapExpression(expression);
    if (value.type === "Identifier") return findVariable(sourceCode.getScope(value), value.name);
    if (value.type === "MemberExpression" && staticPropertyName(value, sourceCode) === "prototype") {
      const constructor = globalBuiltinName(value.object, sourceCode);
      if (constructor !== null && BUILTIN_ERROR_CONSTRUCTORS.has(constructor)) return constructor + ".prototype";
    }
    return null;
  };
  const propertyWrite = (receiver: string | TsVariable, name: string | null, node: Node): void => {
    if (receiver === "JSON") { if (name === null || name === "stringify") record("JSON.stringify", node); }
    else if (receiver === "globalThis") { if (name === null) { for (const builtin of TRACKED_BUILTINS) record(builtin, node); } else if (name !== "JSON.stringify" && TRACKED_BUILTINS.has(name)) record(name, node); }
    else if (name === null || name === "toJSON") record(receiver, node);
  };
  const visit = (node: Node): void => {
    if (node.type === "AssignmentExpression") propertyTarget(node.left);
    else if (node.type === "UpdateExpression") propertyTarget(node.argument);
    else if (node.type === "ForInStatement" || node.type === "ForOfStatement") propertyTarget(node.left);
    else if (node.type === "UnaryExpression" && node.operator === "delete") propertyTarget(node.argument);
    else if (node.type === "CallExpression") mutationCall(node);
    forEachAstChild(node, sourceCode.visitorKeys, visit);
  };
  function propertyTarget(target: Node): void {
    if (target.type === "MemberExpression") { memberPropertyWrite(target); return; }
    switch (target.type) {
      case "ObjectPattern":
        for (const property of target.properties) propertyTarget(property.type === "RestElement" ? property.argument : property.value);
        return;
      case "ArrayPattern":
        for (const element of target.elements) if (element !== null) propertyTarget(element);
        return;
      case "AssignmentPattern":
        propertyTarget(target.left);
        return;
      case "RestElement":
        propertyTarget(target.argument);
    }
  }

  // Pattern traversal finds member lvalues; this boundary proves which native value or hook changes.
  function memberPropertyWrite(target: ESTree.MemberExpression): void {
    const receiver = propertyReceiver(target.object);
    if (receiver === null || writePreservesBuiltin(target, sourceCode)) return;
    const name = staticPropertyName(target, sourceCode);
    if (name === "toJSON") {
      const assignment = parentOf(target);
      if (assignment?.type === "UnaryExpression" && assignment.operator === "delete") return;
      if (assignment?.type === "AssignmentExpression" && assignment.operator === "=" && !mayBeCallable(assignment.right)) return;
    }
    propertyWrite(receiver, name, target);
  }

  function mutationCall(node: ESTree.CallExpression): void {
    const callee = unwrapExpression(node.callee);
    if (callee.type !== "MemberExpression" || callee.object.type !== "Identifier") return;
    const owner = callee.object.name;
    if (!MUTATION_OWNERS.has(owner) || !isGlobalIdentifier(owner, sourceCode.getScope(callee))) return;
    const method = staticPropertyName(callee, sourceCode);
    const [target, key, value, receiver] = node.arguments;
    if (target === undefined || target.type === "SpreadElement" || key === undefined) return;
    const object = propertyReceiver(target);
    if (object === null) return;
    switch (method) {
      case "set":
        if (owner === "Reflect") reflectSet(object, scopedStaticString(key, sourceCode), value, receiver, node);
        return;
      case "defineProperty":
        descriptorWrite(object, scopedStaticString(key, sourceCode), value, node);
        return;
      case "defineProperties":
        if (owner === "Object") descriptorBatch(object, key, node);
    }
  }

  // Reflect.set can direct the write to a distinct receiver and preserve an existing native value.
  function reflectSet(object: string | TsVariable, name: string | null, value: Node | undefined, receiver: Node | undefined, node: ESTree.CallExpression): void {
    if (receiver !== undefined && receiver.type !== "SpreadElement" && ["ObjectExpression", "ArrayExpression", "Literal"].includes(unwrapExpression(receiver).type)) return;
    const builtin = builtinPropertyName(object, name);
    if (value !== undefined && value.type !== "SpreadElement" && builtin !== null && globalBuiltinName(value, sourceCode) === builtin) return;
    if (name === "toJSON" && value !== undefined && !mayBeCallable(value)) return;
    propertyWrite(object, name, node);
  }

  // Object.defineProperties supplies a descriptor per key, unlike the single-descriptor API.
  function descriptorBatch(object: string | TsVariable, descriptors: Node, node: ESTree.CallExpression): void {
    if (descriptors.type !== "ObjectExpression") { propertyWrite(object, null, node); return; }
    for (const property of descriptors.properties) {
      if (property.type !== "Property") { propertyWrite(object, null, node); continue; }
      descriptorWrite(object, staticPropertyName(property, sourceCode), property.value, node);
    }
  }

  function descriptorWrite(object: string | TsVariable, name: string | null, descriptor: Node | undefined, node: ESTree.CallExpression): void {
    if (descriptor !== undefined && !descriptorChangesValue(descriptor, builtinPropertyName(object, name))) return;
    propertyWrite(object, name, node);
  }

  function descriptorChangesValue(descriptor: Node, name: string | null): boolean {
    if (descriptor.type !== "ObjectExpression") return true;
    return descriptor.properties.some(property => {
      if (property.type !== "Property") return true;
      const key = staticPropertyName(property, sourceCode);
      if (key === "value" && name === "toJSON" && !mayBeCallable(property.value)) return false;
      if (key === "value" && !isPatternValue(property.value)) return name === null || globalBuiltinName(property.value, sourceCode) !== name;
      return key === null || key === "get" || key === "set";
    });
  }

  function builtinPropertyName(object: string | TsVariable, name: string | null): string | null {
    return object === "JSON" && name === "stringify" ? "JSON.stringify" : name;
  }
  visit(sourceCode.ast);
  BUILTIN_WRITES.set(sourceCode.ast, writes);
  return writes;
}

/** Explicit own/prototype hooks defer to their serializer contract, without evaluating hook bodies. */
function hasDefaultErrorSerialization(expression: Node, call: Node, sourceCode: SourceCode): boolean {
  let constructor: string | null = null;
  if (expression.type === "Identifier") {
    const variable = findVariable(sourceCode.getScope(expression), expression.name);
    if (variable !== null && !hasUnchangedBuiltin(variable, call, sourceCode)) return false;
    const definition = variable?.defs[0];
    const initializer = definition?.type === "Variable" ? (definition.node as ESTree.VariableDeclarator).init : null;
    if (initializer?.type === "NewExpression" && initializer.callee.type === "Identifier") constructor = initializer.callee.name;
  } else if (expression.type === "NewExpression" && expression.callee.type === "Identifier") constructor = expression.callee.name;
  const families = constructor === null ? BUILTIN_ERROR_CONSTRUCTORS : ["Error", constructor];
  return [...families].every(name => hasUnchangedBuiltin(name + ".prototype", call, sourceCode));
}

function isBuiltinErrorConstructor(identifier: Identifier, sourceCode: SourceCode): boolean {
  return sourceCode.scopeManager !== null && BUILTIN_ERROR_CONSTRUCTORS.has(identifier.name) && isGlobalIdentifier(identifier.name, sourceCode.getScope(identifier)) && hasUnchangedBuiltin(identifier.name, identifier, sourceCode);
}

function isGlobalIdentifier(name: string, scope: Scope): boolean {
  const binding = findVariable(scope, name);
  return binding === null || binding.defs.length === 0;
}

function positiveErrorSubject(
  test: Node,
  sourceCode: SourceCode,
): Node | null {
  return instanceofErrorSubject(test, sourceCode) ?? typeGuardSubject(test);
}

/** Names of a user-defined type-guard predicate: `isErrorLike`, `isError`, `hasErrorShape`. */
const TYPE_GUARD_PATTERN = /^(is|has)[A-Z]/;

function instanceofErrorSubject(
  test: Node,
  sourceCode: SourceCode,
): Node | null {
  if (
    test.type === "BinaryExpression" &&
    test.operator === "instanceof" &&
    test.right.type === "Identifier" &&
    test.right.name === "Error" &&
    isBuiltinErrorConstructor(test.right, sourceCode)
  ) {
    return test.left;
  }
  return null;
}

/** The narrowed subject `x` of a user-defined type-guard call `isFoo(x)`, or null. */
function typeGuardSubject(
  test: Node,
): Node | null {
  if (test.type !== "CallExpression" || test.arguments.length !== 1) return null;
  const callee = unwrapExpression(test.callee);
  const arg = test.arguments[0] as Node;
  return callee.type === "Identifier" && TYPE_GUARD_PATTERN.test(callee.name) && arg.type !== "SpreadElement"
    ? arg : null;
}

/**
 * True if an earlier guard `if (isErrorLike(arg)) return …` (or `instanceof Error`)
 * in an enclosing block narrows `argExpr` away from the error case before `node`,
 * so by the time `JSON.stringify(arg)` runs the value is the non-Error fallback.
 */
function isNarrowedByEarlyReturn(
  node: Node,
  argExpr: Node,
  sourceCode: SourceCode,
): boolean {
  let current: Node | null = parentOf(node);
  while (current) {
    if (current.type === "BlockStatement" || current.type === "Program") {
      if (hasEarlierErrorGuard(current.body, node, argExpr, sourceCode)) return true;
    }
    current = parentOf(current);
  }
  return false;
}

function isGuardedByInstanceofError(
  node: Node,
  argExpr: Node,
  sourceCode: SourceCode,
): boolean {
  const sameSubject = (subject: Node): boolean =>
    sameSubjectBinding(subject, argExpr, sourceCode);

  let current: Node | null = parentOf(node);
  while (current) {
    if (current.type === "ConditionalExpression" || current.type === "IfStatement") {
      const subject = positiveErrorSubject(current.test, sourceCode);
      if (subject && sameSubject(subject) && nodeWithin(node, current.alternate)) {
        return true;
      }
      const negated = negatedInstanceofErrorSubject(current.test, sourceCode);
      if (negated && sameSubject(negated) && nodeWithin(node, current.consequent)) {
        return true;
      }
    }
    current = parentOf(current);
  }
  return false;
}

/** The subject `x` of a negated error-narrowing test — `!(x instanceof Error)` / `!isErrorLike(x)`. */
function negatedInstanceofErrorSubject(
  test: Node,
  sourceCode: SourceCode,
): Node | null {
  if (test.type === "UnaryExpression" && test.operator === "!") {
    return positiveErrorSubject(test.argument, sourceCode);
  }
  return null;
}

function sameSubjectBinding(
  subject: Node,
  value: Node,
  sourceCode: SourceCode,
): boolean {
  const left = unwrapExpression(subject);
  const right = unwrapExpression(value);
  if (left.type === "Identifier" && right.type === "Identifier") {
    const binding = findVariable(sourceCode.getScope(left), left.name);
    return binding !== null && binding === findVariable(sourceCode.getScope(right), right.name);
  }
  return sourceCode.getText(subject) === sourceCode.getText(value);
}

function nodeWithin(node: Node, container: Node | null): boolean {
  return (
    container !== null &&
    node.range[0] >= container.range[0] &&
    node.range[1] <= container.range[1]
  );
}

function isJsonStringify(callee: Node, sourceCode: SourceCode): boolean {
  if (callee.type !== "MemberExpression") return false;
  const receiver = unwrapExpression(callee.object);
  return (
    receiver.type === "Identifier" &&
    receiver.name === "JSON" &&
    staticPropertyName(callee, sourceCode) === "stringify"
  );
}

/** Direct values serialized by a one-level object or array literal. */
function directLiteralValues(
  argument: Node,
  sourceCode: SourceCode,
): readonly Node[] {
  argument = unwrapExpression(argument);
  if (argument.type === "ObjectExpression") {
    if (literalHasSerializer(argument, sourceCode)) return [];
    return argument.properties.flatMap((property) => {
      if (property.type !== "Property" || staticPropertyName(property, sourceCode) === null) return [];
      const value = property.value;
      if (isPatternValue(value)) {
        return [];
      }
      return [value];
    });
  }
  if (argument.type === "ArrayExpression") {
    return argument.elements.flatMap((element) =>
      element !== null && element.type !== "SpreadElement" ? [element] : [],
    );
  }
  return argument.type === "SpreadElement" ? [] : [argument];
}

function literalHasSerializer(argument: ESTree.ObjectExpression, sourceCode: SourceCode): boolean {
  for (const property of argument.properties.toReversed()) {
    if (property.type !== "Property") return true;
    const key = staticPropertyName(property, sourceCode);
    if (key === null) return true;
    if (key === "toJSON") return mayBeCallable(property.value);
  }
  for (const property of argument.properties) {
    if (property.type !== "Property" || property.computed || property.method || property.shorthand || property.kind !== "init" || staticPropertyName(property, sourceCode) !== "__proto__") continue;
    const prototype = property.value;
    return prototype.type === "ObjectExpression" ? literalHasSerializer(prototype, sourceCode) : prototype.type !== "Literal" || ("regex" in prototype && prototype.regex !== undefined);
  }
  return false;
}

function expressionSuggestsError(
  expression: Node,
  sourceCode: SourceCode,
): boolean {
  expression = unwrapExpression(expression);
  if (expression.type === "Identifier") {
    return identifierIsProvenError(expression, sourceCode);
  }
  if (expression.type !== "NewExpression") return false;
  const callee = unwrapExpression(expression.callee);
  return callee.type === "Identifier" && isBuiltinErrorConstructor(callee, sourceCode);
}

/** Whether a stable local binding is constructively proven to hold an Error. */
function identifierIsProvenError(
  identifier: Identifier,
  sourceCode: SourceCode,
): boolean {
  const variable = findVariable(sourceCode.getScope(identifier), identifier.name);
  if (variable === null || variable.defs.length !== 1 || variable.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
  const definition = variable.defs[0];
  if (definition?.type === "CatchClause") return true;
  if (definition?.type !== "Variable") return false;
  const initializer = (definition.node as ESTree.VariableDeclarator).init;
  return (
    initializer?.type === "NewExpression" &&
    initializer.callee.type === "Identifier" &&
    isBuiltinErrorConstructor(initializer.callee, sourceCode)
  );
}

function hasEarlierErrorGuard(statements: readonly ESTree.Statement[], node: Node, argExpr: Node, sourceCode: SourceCode): boolean {
  for (const stmt of statements) {
    if (stmt.range[0] >= node.range[0]) {
      break;
    }
    if (
      stmt.type === "IfStatement" &&
      stmt.alternate === null &&
      branchTerminates(stmt.consequent)
    ) {
      const subject = positiveErrorSubject(stmt.test, sourceCode);
      if (subject && sameSubjectBinding(subject, argExpr, sourceCode)) {
        return true;
      }
    }
  }
  return false;
}


/** Whether a branch statement unconditionally exits (its last statement returns/throws). */
function branchTerminates(branch: ESTree.Statement): boolean {
  const body = branch.type === "BlockStatement" ? branch.body : [branch];
  const last = body[body.length - 1];
  return (
    last !== undefined &&
    (last.type === "ReturnStatement" || last.type === "ThrowStatement")
  );
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Avoid generic JSON serialization that can omit native Error details.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noJsonStringifyError:
        "Generic `JSON.stringify` can omit non-enumerable Error details such as message and stack. Serialize explicit fields or use an error-aware serializer.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    return {
      before(): void {
        sourceCode = context.sourceCode;
      },
      CallExpression(node: ESTree.CallExpression): void {
        const unwrappedNodeCallee = unwrapExpression(node.callee);
        if (!isJsonStringify(unwrappedNodeCallee, sourceCode)) {
          return;
        }

        const firstArg = node.arguments[0];
        if (!firstArg) {
          return;
        }

        const scope = sourceCode.getScope(firstArg);
        if (!isGlobalIdentifier("JSON", scope) || !hasUnchangedBuiltin("JSON", node, sourceCode) || !hasUnchangedBuiltin("JSON.stringify", node, sourceCode)) return;
        const replacer = node.arguments[1] === undefined ? undefined : unwrapExpression(node.arguments[1]);
        if (replacer !== undefined && !(replacer.type === "Literal" && replacer.value === null) && !(replacer.type === "Identifier" && replacer.name === "undefined" && isGlobalIdentifier("undefined", scope))) return;
        const unsafeValue = directLiteralValues(firstArg, sourceCode).find(
          (value) =>
            expressionSuggestsError(value, sourceCode) &&
            hasDefaultErrorSerialization(unwrapExpression(value), node, sourceCode) &&
            !isGuardedByInstanceofError(node, value, sourceCode) &&
            !isNarrowedByEarlyReturn(node, value, sourceCode),
        );
        if (unsafeValue === undefined) {
          return;
        }

        context.report({
          node,
          messageId: "noJsonStringifyError",
        });
      },
    };
  },
});

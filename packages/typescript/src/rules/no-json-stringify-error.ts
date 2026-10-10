/**
 * @fileoverview no-json-stringify-error — `JSON.stringify` on an Error yields `{}` — `message` and `stack` are non-enumerable.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-json-stringify-error.test.ts
 */

import { ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { forEachAstChild } from "./_for-each-ast-child.js";
import { scopedStaticString, staticPropertyName } from "./_static-string.js";
import type { Scope, SourceCode } from "@typescript-eslint/utils/ts-eslint";

type MessageIds = "noJsonStringifyError";
type Options = readonly [];

export const NO_JSON_STRINGIFY_ERROR_DOCUMENTATION = {
  summary: "Avoid generic JSON serialization that can omit native Error details.",
  rationale: "Native Error details are non-enumerable, so generic JSON serialization discards diagnostic information.",
  remediation: "Serialize explicit error fields or use an error-aware serializer.",
  category: "correctness",
  limitations: ["The rule uses stable local catch bindings and unshadowed built-in constructors, not runtime type information. Custom replacers and explicit toJSON hooks are left to their serializer contract; a catch value is not guaranteed to be an Error. Member values, including cause, do not inherit the base Error's provenance; even an Error-valued member requires explicit value/dataflow proof outside this rule. Known literal __proto__ initializer chains preserve native hook inheritance and own toJSON precedence; computed __proto__ keys remain data. Unknown prototype expressions, hook values/spreads and deferred hook writes conservatively lose default serializer proof. Explicit writes invalidate constructor provenance except a later, separate top-level statement; deferred functions, loops, and unknown property keys conservatively lose constructor proof. Statically owned global/property writes and native Reflect.set/Reflect.defineProperty/Object.defineProperty/Object.defineProperties calls are tracked. Mutator aliases, replaced Reflect/Object methods, external calls, and runtime-only property names are not resolved; uncertain ordering conservatively loses proof."],
  examples: [
    { id: "explicit-error-message", title: "Narrow an unknown catch value before selecting fields", outcome: "no-match", files: [{ path: "src/report.ts", source: "try { f(); } catch (err) { JSON.stringify({ error: err instanceof Error ? err.message : String(err) }); }" }], focusPath: "src/report.ts", expectedCount: 0, public: true },
    { id: "stringified-error", title: "Do not stringify an Error object", outcome: "match", files: [{ path: "src/report.ts", source: "try { f(); } catch (err) { JSON.stringify({ error: err }); }" }], focusPath: "src/report.ts", expectedCount: 1, public: true },
    { id: "shadowed-error-binding", scenarioId: "binding-provenance", title: "Keep native binding provenance", outcome: "match", files: [{ path: "src/error.ts", source: "function probe(){try{throw {id:1};}catch(err){if(err instanceof Error)return err.message;{const err=new Error(\"lost\");return JSON.stringify(err);}}}\nconsole.log(probe());" }], focusPath: "src/error.ts", expectedCount: 1, public: true },
    { id: "escaped-fallback-binding", scenarioId: "binding-provenance", title: "Keep native binding provenance", outcome: "no-match", files: [{ path: "src/error.ts", source: "function probe(){try{throw {id:1};}catch(err){if(err instanceof Error)return err.message;return JSON.stringify(\\u0065rr);}}\nconsole.log(probe());" }], focusPath: "src/error.ts", expectedCount: 0, public: true },
    { id: "constructor-before-write", scenarioId: "explicit-constructor-write", title: "A later write does not change an already constructed native Error", outcome: "match", files: [{ path: "src/error.js", source: "const value=new Error('lost');Error=class Other{message='kept'};JSON.stringify(value);" }], focusPath: "src/error.js", expectedCount: 1, public: true },
    { id: "constructor-after-write", scenarioId: "explicit-constructor-write", title: "A replaced constructor does not prove a native Error", outcome: "no-match", files: [{ path: "src/error.js", source: "Error=class Other{message='kept'};const value=new Error();JSON.stringify(value);" }], focusPath: "src/error.js", expectedCount: 0, public: true },
    {"id": "native-serializer-before-write", "scenarioId": "explicit-serializer-write", "title": "A later write does not change an earlier native serialization", "outcome": "match", "files": [{"path": "src/error.js", "source": "const result=JSON.stringify(new Error('lost'));JSON.stringify=value=>'kept:'+value.message;"}], "focusPath": "src/error.js", "expectedCount": 1, "public": true},
    {"id": "native-serializer-after-write", "scenarioId": "explicit-serializer-write", "title": "A replaced serializer owns its error-field contract", "outcome": "no-match", "files": [{"path": "src/error.js", "source": "JSON.stringify=value=>'kept:'+value.message;JSON.stringify(new Error('lost'));"}], "focusPath": "src/error.js", "expectedCount": 0, "public": true},
    {"id": "static-serializer-key", "scenarioId": "static-property-provenance", "title": "A constant computed serializer still loses native Error details", "outcome": "match", "files": [{"path": "src/error.js", "source": "const key='stringify';JSON[key](new Error('lost'));"}], "focusPath": "src/error.js", "expectedCount": 1, "public": true},
    {"id": "static-error-field", "scenarioId": "static-property-provenance", "title": "A constant message field selects the explicit string escape hatch", "outcome": "no-match", "files": [{"path": "src/error.js", "source": "const key='message';const error=new Error('lost');JSON.stringify(error[key]);"}], "focusPath": "src/error.js", "expectedCount": 0, "public": true},
    {"id": "scalar-cause", "scenarioId": "member-value-provenance", "title": "Native Error cause can be a string value", "outcome": "no-match", "files": [{"path": "src/error.js", "source": "const error=new Error('lost',{cause:'kept'});JSON.stringify(error.cause);"}], "focusPath": "src/error.js", "expectedCount": 0, "public": true},
    {"id": "whole-error-with-cause", "scenarioId": "member-value-provenance", "title": "Serializing the whole Error still loses its native details", "outcome": "match", "files": [{"path": "src/error.js", "source": "const error=new Error('lost',{cause:'kept'});JSON.stringify(error);"}], "focusPath": "src/error.js", "expectedCount": 1, "public": true},
    {"id": "explicit-to-json-hook", "scenarioId": "custom-serializer-contract", "title": "An explicit callable toJSON owns its serialization contract", "outcome": "no-match", "files": [{"path": "src/error.js", "source": "JSON.stringify({error:new Error('lost'),toJSON(){return {message:'kept'};}});"}], "focusPath": "src/error.js", "expectedCount": 0, "public": true},
    {"id": "noncallable-to-json", "scenarioId": "custom-serializer-contract", "title": "A noncallable toJSON does not replace native serialization", "outcome": "match", "files": [{"path": "src/error.js", "source": "JSON.stringify({error:new Error('lost'),toJSON:42});"}], "focusPath": "src/error.js", "expectedCount": 1, "public": true},
    {"id": "literal-prototype-hook", "scenarioId": "native-prototype-serializer", "title": "A literal prototype hook owns the payload serializer contract", "outcome": "no-match", "files": [{"path": "src/error.js", "source": "JSON.stringify({error:new Error('lost'),__proto__:{toJSON(){return {message:'kept'};}}});"}], "focusPath": "src/error.js", "expectedCount": 0, "public": true},
    {"id": "computed-prototype-data", "scenarioId": "native-prototype-serializer", "title": "A computed prototype name remains ordinary serialized data", "outcome": "match", "files": [{"path": "src/error.js", "source": "JSON.stringify({error:new Error('lost'),['__proto__']:{toJSON(){return {message:'kept'};}}});"}], "focusPath": "src/error.js", "expectedCount": 1, "public": true},
  ],
} as const satisfies RuleDocumentation;

const BUILTIN_ERROR_CONSTRUCTORS: ReadonlySet<string> = new Set([
  "AggregateError",
  "Error",
  "EvalError",
  "RangeError",
  "ReferenceError",
  "SyntaxError",
  "TypeError",
  "URIError",
]);

const TRACKED_BUILTINS: ReadonlySet<string> = new Set([...BUILTIN_ERROR_CONSTRUCTORS, "JSON", "JSON.stringify"]);

function nativeObjectName(expression: TSESTree.Expression, sourceCode: Readonly<SourceCode>): "globalThis" | "JSON" | null {
  const value = unwrapExpression(expression);
  const scope = sourceCode.getScope(value);
  if (value.type === "Identifier" && (value.name === "globalThis" || value.name === "JSON") && isGlobalIdentifier(value.name, scope)) return value.name;
  if (value.type === "MemberExpression" && nativeObjectName(value.object, sourceCode) === "globalThis" && staticPropertyName(value, sourceCode) === "JSON") return "JSON";
  return null;
}

function globalBuiltinName(expression: TSESTree.Expression, sourceCode: Readonly<SourceCode>): string | null {
  const value = unwrapExpression(expression);
  const scope = sourceCode.getScope(value);
  if (value.type === "Identifier") return TRACKED_BUILTINS.has(value.name) && isGlobalIdentifier(value.name, scope) ? value.name : null;
  if (value.type !== "MemberExpression") return null;
  const receiver = nativeObjectName(value.object, sourceCode);
  const name = staticPropertyName(value, sourceCode);
  if (receiver === "JSON") return name === "stringify" ? "JSON.stringify" : null;
  return receiver === "globalThis" && name !== null && name !== "JSON.stringify" && TRACKED_BUILTINS.has(name) ? name : null;
}

/** Self-assignment and native truthy/non-null defaults do not replace the tracked built-in. */
function writePreservesBuiltin(target: TSESTree.Identifier | TSESTree.MemberExpression, sourceCode: Readonly<SourceCode>): boolean {
  const assignment = target.parent;
  if (assignment?.type !== "AssignmentExpression" || assignment.left !== target) return false;
  const name = globalBuiltinName(target, sourceCode);
  if (name === null) return false;
  if (assignment.operator === "||=" || assignment.operator === "??=") return true;
  return (assignment.operator === "=" || assignment.operator === "&&=") && globalBuiltinName(assignment.right, sourceCode) === name;
}

function mayBeCallable(value: TSESTree.Node): boolean {
  return !["Literal", "TemplateLiteral", "ObjectExpression", "ArrayExpression"].includes(value.type);
}

interface WriteSummary { earliestStatementStart: number; unknownOrder: boolean }
// Cache this immutable source object's explicit writes, with constant-cost queries per read.
const BUILTIN_WRITES = new WeakMap<Readonly<SourceCode>, ReadonlyMap<string | Scope.Variable, WriteSummary>>();

/** A top-level statement executes once; deferred functions and repeated loops do not prove ordering. */
function directProgramStatement(node: TSESTree.Node): TSESTree.Node | null {
  let current = node;
  while (current.parent !== undefined) {
    if (current.parent.type === "Program") return current;
    if (["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression", "ClassBody", "StaticBlock", "ForStatement", "ForInStatement", "ForOfStatement", "WhileStatement", "DoWhileStatement"].includes(current.parent.type)) return null;
    current = current.parent;
  }
  return null;
}

function hasUnchangedBuiltin(name: string | Scope.Variable, read: TSESTree.Node, sourceCode: Readonly<SourceCode>): boolean {
  const summary = builtinWrites(sourceCode).get(name);
  if (summary === undefined) return true;
  const statement = directProgramStatement(read);
  return !summary.unknownOrder && statement !== null && statement.range[1] <= summary.earliestStatementStart;
}

function builtinWrites(sourceCode: Readonly<SourceCode>): ReadonlyMap<string | Scope.Variable, WriteSummary> {
  const cached = BUILTIN_WRITES.get(sourceCode);
  if (cached !== undefined) return cached;
  const writes = new Map<string | Scope.Variable, WriteSummary>();
  const record = (name: string | Scope.Variable, node: TSESTree.Node): void => {
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
  const propertyReceiver = (expression: TSESTree.Expression): string | Scope.Variable | null => {
    const native = nativeObjectName(expression, sourceCode);
    if (native !== null) return native;
    const value = unwrapExpression(expression);
    if (value.type === "Identifier") return ASTUtils.findVariable(sourceCode.getScope(value), value.name);
    if (value.type === "MemberExpression" && staticPropertyName(value, sourceCode) === "prototype") {
      const constructor = globalBuiltinName(value.object, sourceCode);
      if (constructor !== null && BUILTIN_ERROR_CONSTRUCTORS.has(constructor)) return constructor + ".prototype";
    }
    return null;
  };
  const propertyWrite = (receiver: string | Scope.Variable, name: string | null, node: TSESTree.Node): void => {
    if (receiver === "JSON") { if (name === null || name === "stringify") record("JSON.stringify", node); }
    else if (receiver === "globalThis") { if (name === null) { for (const builtin of TRACKED_BUILTINS) record(builtin, node); } else if (name !== "JSON.stringify" && TRACKED_BUILTINS.has(name)) record(name, node); }
    else if (name === null || name === "toJSON") record(receiver, node);
  };
  const visit = (node: TSESTree.Node): void => {
    if (node.type === "AssignmentExpression") propertyTarget(node.left);
    else if (node.type === "UpdateExpression") propertyTarget(node.argument);
    else if (node.type === "ForInStatement" || node.type === "ForOfStatement") propertyTarget(node.left);
    else if (node.type === "UnaryExpression" && node.operator === "delete") propertyTarget(node.argument);
    else if (node.type === "CallExpression") mutationCall(node);
    forEachAstChild(node, sourceCode.visitorKeys, visit);
  };
  function propertyTarget(target: TSESTree.Node): void {
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
  function memberPropertyWrite(target: TSESTree.MemberExpression): void {
    const receiver = propertyReceiver(target.object);
    if (receiver === null || writePreservesBuiltin(target, sourceCode)) return;
    const name = staticPropertyName(target, sourceCode);
    if (name === "toJSON") {
      const assignment = target.parent;
      if (assignment?.type === "UnaryExpression" && assignment.operator === "delete") return;
      if (assignment?.type === "AssignmentExpression" && assignment.operator === "=" && !mayBeCallable(assignment.right)) return;
    }
    propertyWrite(receiver, name, target);
  }

  function mutationCall(node: TSESTree.CallExpression): void {
    const callee = unwrapExpression(node.callee);
    if (callee.type !== "MemberExpression" || callee.object.type !== "Identifier") return;
    const owner = callee.object.name;
    if (!["Reflect", "Object"].includes(owner) || !isGlobalIdentifier(owner, sourceCode.getScope(callee))) return;
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
  function reflectSet(object: string | Scope.Variable, name: string | null, value: TSESTree.CallExpressionArgument | undefined, receiver: TSESTree.CallExpressionArgument | undefined, node: TSESTree.CallExpression): void {
    if (receiver !== undefined && receiver.type !== "SpreadElement" && ["ObjectExpression", "ArrayExpression", "Literal"].includes(unwrapExpression(receiver).type)) return;
    const builtin = builtinPropertyName(object, name);
    if (value !== undefined && value.type !== "SpreadElement" && builtin !== null && globalBuiltinName(value, sourceCode) === builtin) return;
    if (name === "toJSON" && value !== undefined && !mayBeCallable(value)) return;
    propertyWrite(object, name, node);
  }

  // Object.defineProperties supplies a descriptor per key, unlike the single-descriptor API.
  function descriptorBatch(object: string | Scope.Variable, descriptors: TSESTree.Node, node: TSESTree.CallExpression): void {
    if (descriptors.type !== "ObjectExpression") { propertyWrite(object, null, node); return; }
    for (const property of descriptors.properties) {
      if (property.type !== "Property") { propertyWrite(object, null, node); continue; }
      descriptorWrite(object, staticPropertyName(property, sourceCode), property.value, node);
    }
  }

  function descriptorWrite(object: string | Scope.Variable, name: string | null, descriptor: TSESTree.Node | undefined, node: TSESTree.CallExpression): void {
    if (descriptor !== undefined && !descriptorChangesValue(descriptor, builtinPropertyName(object, name))) return;
    propertyWrite(object, name, node);
  }

  function descriptorChangesValue(descriptor: TSESTree.Node, name: string | null): boolean {
    if (descriptor.type !== "ObjectExpression") return true;
    return descriptor.properties.some(property => {
      if (property.type !== "Property") return true;
      const key = staticPropertyName(property, sourceCode);
      if (key === "value" && name === "toJSON" && !mayBeCallable(property.value)) return false;
      if (key === "value" && property.value.type !== "AssignmentPattern" && property.value.type !== "ArrayPattern" && property.value.type !== "ObjectPattern" && property.value.type !== "TSEmptyBodyFunctionExpression") return name === null || globalBuiltinName(property.value, sourceCode) !== name;
      return key === null || key === "get" || key === "set";
    });
  }

  function builtinPropertyName(object: string | Scope.Variable, name: string | null): string | null {
    return object === "JSON" && name === "stringify" ? "JSON.stringify" : name;
  }
  visit(sourceCode.ast);
  BUILTIN_WRITES.set(sourceCode, writes);
  return writes;
}

/** Explicit own/prototype hooks defer to their serializer contract, without evaluating hook bodies. */
function hasDefaultErrorSerialization(expression: TSESTree.Expression, call: TSESTree.Node, sourceCode: Readonly<SourceCode>): boolean {
  let constructor: string | null = null;
  if (expression.type === "Identifier") {
    const variable = ASTUtils.findVariable(sourceCode.getScope(expression), expression.name);
    if (variable !== null && !hasUnchangedBuiltin(variable, call, sourceCode)) return false;
    const definition = variable?.defs[0];
    const initializer = definition?.type === "Variable" ? definition.node.init : null;
    if (initializer?.type === "NewExpression" && initializer.callee.type === "Identifier") constructor = initializer.callee.name;
  } else if (expression.type === "NewExpression" && expression.callee.type === "Identifier") constructor = expression.callee.name;
  const families = constructor === null ? BUILTIN_ERROR_CONSTRUCTORS : ["Error", constructor];
  return [...families].every(name => hasUnchangedBuiltin(name + ".prototype", call, sourceCode));
}

function isBuiltinErrorConstructor(identifier: TSESTree.Identifier, sourceCode: Readonly<SourceCode>): boolean {
  return sourceCode.scopeManager !== null && BUILTIN_ERROR_CONSTRUCTORS.has(identifier.name) && isGlobalIdentifier(identifier.name, sourceCode.getScope(identifier)) && hasUnchangedBuiltin(identifier.name, identifier, sourceCode);
}

function isGlobalIdentifier(name: string, scope: Scope.Scope): boolean {
  const binding = ASTUtils.findVariable(scope, name);
  return binding === null || binding.defs.length === 0;
}

function positiveErrorSubject(
  test: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): TSESTree.Expression | null {
  return instanceofErrorSubject(test, sourceCode) ?? typeGuardSubject(test);
}

/** Names of a user-defined type-guard predicate: `isErrorLike`, `isError`, `hasErrorShape`. */
const TYPE_GUARD_PATTERN = /^(is|has)[A-Z]/;

function instanceofErrorSubject(
  test: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): TSESTree.Expression | null {
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
  test: TSESTree.Expression,
): TSESTree.Expression | null {
  const unwrappedTestCallee = test.type === "CallExpression" || test.type === "NewExpression" ? unwrapExpression(test.callee) : null;
  const arg = test.type === "CallExpression" ? test.arguments[0] : undefined;
  if (
    test.type === "CallExpression" &&
    unwrappedTestCallee?.type === "Identifier" &&
    TYPE_GUARD_PATTERN.test(unwrappedTestCallee.name) &&
    test.arguments.length === 1 &&
    arg !== undefined &&
    arg.type !== "SpreadElement"
  ) {
    return arg;
  }
  return null;
}

/**
 * True if an earlier guard `if (isErrorLike(arg)) return …` (or `instanceof Error`)
 * in an enclosing block narrows `argExpr` away from the error case before `node`,
 * so by the time `JSON.stringify(arg)` runs the value is the non-Error fallback.
 */
function isNarrowedByEarlyReturn(
  node: TSESTree.Node,
  argExpr: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): boolean {
  let current: TSESTree.Node | undefined = node.parent;
  while (current) {
    if (current.type === "BlockStatement" || current.type === "Program") {
      if (hasEarlierErrorGuard(current.body, node, argExpr, sourceCode)) return true;
    }
    current = current.parent;
  }
  return false;
}

function isGuardedByInstanceofError(
  node: TSESTree.Node,
  argExpr: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): boolean {
  const sameSubject = (subject: TSESTree.Expression): boolean =>
    sameSubjectBinding(subject, argExpr, sourceCode);

  let current: TSESTree.Node | undefined = node.parent;
  while (current) {
    if (current.type === "ConditionalExpression") {
      const subject = positiveErrorSubject(current.test, sourceCode);
      if (subject && sameSubject(subject) && nodeWithin(node, current.alternate)) {
        return true;
      }
      const negated = negatedInstanceofErrorSubject(current.test, sourceCode);
      if (negated && sameSubject(negated) && nodeWithin(node, current.consequent)) {
        return true;
      }
    } else if (current.type === "IfStatement") {
      const subject = positiveErrorSubject(current.test, sourceCode);
      if (subject && sameSubject(subject) && nodeWithin(node, current.alternate)) {
        return true;
      }
      const negated = negatedInstanceofErrorSubject(current.test, sourceCode);
      if (negated && sameSubject(negated) && nodeWithin(node, current.consequent)) {
        return true;
      }
    }
    current = current.parent;
  }
  return false;
}

/** The subject `x` of a negated error-narrowing test — `!(x instanceof Error)` / `!isErrorLike(x)`. */
function negatedInstanceofErrorSubject(
  test: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): TSESTree.Expression | null {
  if (test.type === "UnaryExpression" && test.operator === "!") {
    return positiveErrorSubject(test.argument, sourceCode);
  }
  return null;
}

function sameSubjectBinding(
  subject: TSESTree.Expression,
  value: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): boolean {
  const left = unwrapExpression(subject);
  const right = unwrapExpression(value);
  if (left.type === "Identifier" && right.type === "Identifier") {
    const binding = ASTUtils.findVariable(sourceCode.getScope(left), left.name);
    return binding !== null && binding === ASTUtils.findVariable(sourceCode.getScope(right), right.name);
  }
  return sourceCode.getText(subject) === sourceCode.getText(value);
}

function nodeWithin(node: TSESTree.Node, container: TSESTree.Node | null): boolean {
  return (
    container !== null &&
    node.range[0] >= container.range[0] &&
    node.range[1] <= container.range[1]
  );
}

function isJsonStringify(callee: TSESTree.Expression, sourceCode: Readonly<SourceCode>): boolean {
  if (callee.type !== "MemberExpression") return false;
  const receiver = unwrapExpression(callee.object);
  return (
    callee.type === "MemberExpression" &&
    receiver.type === "Identifier" &&
    receiver.name === "JSON" &&
    staticPropertyName(callee, sourceCode) === "stringify"
  );
}

/** Direct values serialized by a one-level object or array literal. */
function directLiteralValues(
  argument: TSESTree.CallExpressionArgument,
  sourceCode: Readonly<SourceCode>,
): readonly TSESTree.Expression[] {
  argument = unwrapExpression(argument);
  if (argument.type === "ObjectExpression") {
    if (literalHasSerializer(argument, sourceCode)) return [];
    return argument.properties.flatMap((property) => {
      if (property.type !== "Property" || staticPropertyName(property, sourceCode) === null) return [];
      const value = property.value;
      if (
        value.type === "AssignmentPattern" ||
        value.type === "ArrayPattern" ||
        value.type === "ObjectPattern" ||
        value.type === "TSEmptyBodyFunctionExpression"
      ) {
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

function literalHasSerializer(argument: TSESTree.ObjectExpression, sourceCode: Readonly<SourceCode>): boolean {
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
  expression: TSESTree.Expression,
  sourceCode: Readonly<SourceCode>,
): boolean {
  expression = unwrapExpression(expression);
  const unwrappedExpressionCallee = expression.type === "CallExpression" || expression.type === "NewExpression" ? unwrapExpression(expression.callee) : null;
  if (expression.type === "Identifier") {
    return identifierIsProvenError(expression, sourceCode);
  }
  if (
    expression.type === "NewExpression" &&
    unwrappedExpressionCallee?.type === "Identifier"
  ) {
    return isBuiltinErrorConstructor(unwrappedExpressionCallee, sourceCode);
  }
  return false;
}

/** Whether a stable local binding is constructively proven to hold an Error. */
function identifierIsProvenError(
  identifier: TSESTree.Identifier,
  sourceCode: Readonly<SourceCode>,
): boolean {
  const variable = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
  if (variable === null || variable.defs.length !== 1 || variable.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
  const definition = variable.defs[0];
  if (definition?.type === "CatchClause") return true;
  if (definition?.type !== "Variable") return false;
  const initializer = definition.node.init;
  return (
    initializer?.type === "NewExpression" &&
    initializer.callee.type === "Identifier" &&
    isBuiltinErrorConstructor(initializer.callee, sourceCode)
  );
}

export default createRule<Options, MessageIds>({
  name: "no-json-stringify-error",
  documentation: NO_JSON_STRINGIFY_ERROR_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Avoid generic JSON serialization that can omit native Error details.",
    },
    schema: [],
    messages: {
      noJsonStringifyError:
        "Generic `JSON.stringify` can omit non-enumerable Error details such as message and stack. Serialize explicit fields or use an error-aware serializer.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const unwrappedNodeCallee = unwrapExpression(node.callee);
        if (!isJsonStringify(unwrappedNodeCallee, context.sourceCode)) {
          return;
        }

        const firstArg = node.arguments[0];
        if (!firstArg) {
          return;
        }

        const scope = context.sourceCode.getScope(firstArg);
        if (!isGlobalIdentifier("JSON", scope) || !hasUnchangedBuiltin("JSON", node, context.sourceCode) || !hasUnchangedBuiltin("JSON.stringify", node, context.sourceCode)) return;
        const replacer = node.arguments[1] === undefined ? undefined : unwrapExpression(node.arguments[1]);
        if (replacer !== undefined && !(replacer.type === "Literal" && replacer.value === null) && !(replacer.type === "Identifier" && replacer.name === "undefined" && isGlobalIdentifier("undefined", scope))) return;
        const unsafeValue = directLiteralValues(firstArg, context.sourceCode).find(
          (value) =>
            expressionSuggestsError(value, context.sourceCode) &&
            hasDefaultErrorSerialization(unwrapExpression(value), node, context.sourceCode) &&
            !isGuardedByInstanceofError(node, value, context.sourceCode) &&
            !isNarrowedByEarlyReturn(node, value, context.sourceCode),
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

function hasEarlierErrorGuard(statements: readonly TSESTree.Statement[], node: TSESTree.Node, argExpr: TSESTree.Expression, sourceCode: Readonly<SourceCode>): boolean {
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
function branchTerminates(branch: TSESTree.Statement): boolean {
  const body = branch.type === "BlockStatement" ? branch.body : [branch];
  const last = body[body.length - 1];
  return (
    last !== undefined &&
    (last.type === "ReturnStatement" || last.type === "ThrowStatement")
  );
}

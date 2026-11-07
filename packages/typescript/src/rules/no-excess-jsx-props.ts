/**
 * @fileoverview no-excess-jsx-props — report statically known fields spread outside a resolved component props contract.
 *
 * Port of the 18.x `no-excess-jsx-props` rule. Typed: without tsrs types
 * it reports nothing, as the original returns no visitors without a program.
 * The walk collects single-spread private elements; their proofs run against
 * tsrs in `Program:exit`, as the original's do. Where the original maps a
 * TypeScript node back to ESTree, the port finds the ESTree node with the same
 * range (`getNodeByRangeIndex`, then up its parents).
 */

import type { ElementAccessExpression, Expression, Identifier, Node as TsNode, PropertyAccessExpression, SourceFile } from "tsrs/ast";
import type { Signature, Symbol as TsSymbol, Type } from "tsrs/sync";

import { defineRule, type ESTree, type Node, type Scope, type SourceCode, type TsReference, type TsVariable } from "../types.js";
import { outerExpression, parentOf } from "../utils/ast.js";
import { declarationNode, nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import { closedObjectContract } from "../utils/closed-object-contract.js";
import { docsUrl } from "../utils/docs-url.js";
import { constInitializer, unassertedValue } from "../utils/native-const-value.js";
import { ordinaryObjectEffects } from "../utils/ordinary-object-effects.js";
import { isGeneratedFile } from "../utils/paths.js";
import { directEval, exportedSymbols } from "../utils/private-scalar-consumer.js";
import { returnedOperands, scalarParameterView, scalarType } from "../utils/scalar-parameter-view.js";
import { stableValueBinding, typeOnlyReference } from "../utils/stable-value-binding.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";

const NAME = "no-excess-jsx-props";
const RESERVED_PROPS: ReadonlySet<string> = new Set(["key", "ref", "__self", "__source"]);
const JSX_DIRECTIVE = /@jsx(?:ImportSource|Runtime|Frag)?(?:\s|$)/iu;
const MAX_VALUE_DEPTH = 64;
// TypeScript 6's ScriptTarget.ES5; TypeScript 7 dropped the member but keeps ES2015 = 2.
const ES5_TARGET = 1;

type Property = ESTree.ObjectProperty;

function plainLiteralFields(node: ESTree.ObjectExpression): Map<string, Property> | null {
  const fields = new Map<string, Property>();
  for (const property of node.properties) {
    if (property.type !== "Property" || property.kind !== "init") return null;
    const key = property.key;
    let name: string;
    if (!property.computed && key.type === "Identifier") name = key.name;
    else if (key.type === "Literal" && (typeof key.value === "string" || typeof key.value === "number")) name = String(key.value);
    else return null;
    if (name === "__proto__") return null;
    fields.set(name, property);
  }
  return fields;
}

function literalFields(node: ESTree.ObjectExpression): ReadonlyMap<string, Property> | null {
  const fields = plainLiteralFields(node);
  if (fields) for (const name of fields.keys()) if (RESERVED_PROPS.has(name) || name.includes("-")) fields.delete(name);
  return fields;
}

function signatureDeclaration(native: NativeTypes, signature: Signature): TsNode | undefined {
  return signature.declaration === undefined ? undefined : declarationNode(native, signature.declaration);
}

/** A declared finite surface alone cannot establish that a wrapper ignores extras. */
function receiverReads(native: NativeTypes, signature: Signature): ReadonlySet<string> | null {
  const { ast } = native;
  const declaration = signatureDeclaration(native, signature);
  if (!declaration || !ast.isArrowFunction(declaration) || declaration.modifiers?.some((modifier) => modifier.kind === ast.SyntaxKind.AsyncKeyword) ||
    signature.thisParameter || declaration.parameters.length !== 1) return null;
  const parameter = declaration.parameters[0];
  return parameter ? scalarParameterView(native, parameter, declaration.body) : null;
}

function stableReceiver(native: NativeTypes, tag: TsNode, signature: Signature, overrides: Map<string, boolean>): boolean {
  const { ast } = native;
  if (!ast.isIdentifier(tag)) return false;
  const initializer = immutableInitializer(native, tag);
  if (!initializer || initializer !== signatureDeclaration(native, signature) || !ast.isArrowFunction(initializer)) return false;
  return supportedImplementation(native, initializer.getSourceFile(), tag.getSourceFile(), overrides);
}

function immutableInitializer(native: NativeTypes, tag: TsNode): Expression | undefined {
  const { ast, checker, sync } = native;
  let symbol: TsSymbol | undefined = checker.getSymbolAtLocation(tag);
  const seen = new Set<number>();
  while (symbol && !seen.has(symbol.id)) {
    seen.add(symbol.id);
    if ((symbol.flags & sync.SymbolFlags.Alias) !== 0) {
      symbol = checker.getAliasedSymbol(symbol);
      continue;
    }
    const declaration = symbol.valueDeclaration && declarationNode(native, symbol.valueDeclaration);
    const initializer = constInitializer(ast, declaration);
    if (!initializer || !ast.isIdentifier(initializer)) return initializer;
    symbol = checker.getSymbolAtLocation(initializer);
  }
  return undefined;
}

function supportedImplementation(native: NativeTypes, source: SourceFile, caller: SourceFile, overrides: Map<string, boolean>): boolean {
  const { ast, program, sync } = native;
  if (!ast.isExternalModule(source) || impliedNodeFormat(native, source) === sync.ModuleKind.CommonJS ||
    program.isSourceFileFromExternalLibrary(source)) return false;
  if (source === caller) return true;
  if (projectReferences(native)) return false;
  if (!overrides.has(source.path)) {
    overrides.set(source.path, (ast.getLeadingCommentRanges(source.text, 0) ?? []).some((range) => JSX_DIRECTIVE.test(source.text.slice(range.pos, range.end))));
  }
  return !overrides.get(source.path);
}

/**
 * TypeScript 6's `sourceFile.impliedNodeFormat`: set by extension (.mts/.cts and their JS and
 * declaration forms), otherwise read from package.json only under node16/nodenext resolution or
 * inside node_modules, and undefined elsewhere. TypeScript 7 always records a format, so its
 * metadata is consulted only where TypeScript 6 would have looked it up.
 */
function impliedNodeFormat(native: NativeTypes, source: SourceFile): number | undefined {
  const { sync } = native;
  const name = source.fileName;
  if (/\.(?:d\.mts|mts|mjs)$/u.test(name)) return sync.ModuleKind.ESNext;
  if (/\.(?:d\.cts|cts|cjs)$/u.test(name)) return sync.ModuleKind.CommonJS;
  const options = native.program.getCompilerOptions();
  const resolution = options.moduleResolution ?? (options.module === sync.ModuleKind.NodeNext ? sync.ModuleResolutionKind.NodeNext
    : options.module !== undefined && options.module >= sync.ModuleKind.Node16 && options.module < sync.ModuleKind.NodeNext ? sync.ModuleResolutionKind.Node16
      : undefined);
  const lookup = (resolution !== undefined && resolution >= sync.ModuleResolutionKind.Node16 && resolution <= sync.ModuleResolutionKind.NodeNext) ||
    /[\\/]node_modules[\\/]/u.test(name);
  return lookup ? native.program.getSourceFileMetadataByPath(source.path)?.impliedNodeFormat : undefined;
}

function projectReferences(native: NativeTypes): boolean {
  const project = native.program.getProject() as unknown as { readonly parsedCommandLine?: { readonly projectReferences?: readonly unknown[] } };
  return (project.parsedCommandLine?.projectReferences?.length ?? 0) > 0;
}

function supportedJSX(native: NativeTypes, comments: readonly { readonly value: string }[]): boolean {
  const { sync } = native;
  const options = native.program.getCompilerOptions();
  const modules: ReadonlySet<number> = new Set([sync.ModuleKind.ES2015, sync.ModuleKind.ES2020, sync.ModuleKind.ES2022, sync.ModuleKind.ESNext]);
  return (options.target ?? ES5_TARGET) >= native.ast.ScriptTarget.ES2015 &&
    modules.has(options.module ?? sync.ModuleKind.None) &&
    (options.jsx === sync.JsxEmit.ReactJSX || options.jsx === sync.JsxEmit.ReactJSXDev) &&
    !options.jsxFactory && !options.reactNamespace && (!options.jsxImportSource || options.jsxImportSource === "react") &&
    !comments.some((comment) => JSX_DIRECTIVE.test(comment.value));
}

interface ReceivingContract {
  readonly tag: TsNode;
  readonly signature: Signature;
  readonly props: Type;
}

function receivingContract(native: NativeTypes, opening: ESTree.JSXOpeningElement, contracts: Map<Type, boolean>): ReceivingContract | null {
  const { ast, checker, sync } = native;
  const element = native.node(opening);
  if (!element || (!ast.isJsxOpeningElement(element) && !ast.isJsxSelfClosingElement(element))) return null;
  const receiver = checker.getTypeAtLocation(element.tagName);
  const signatures = checker.getSignaturesOfType(receiver, sync.SignatureKind.Call);
  const signature = signatures[0];
  if (receiver.isUnionType() || signatures.length !== 1 || !signature || signature.typeParameters?.length) return null;
  const props = checker.getContextualType(element.attributes);
  if (!props) return null;
  if (!contracts.has(props)) contracts.set(props, closedObjectContract(native, props));
  return contracts.get(props) ? { tag: element.tagName, signature, props } : null;
}

interface PrimitiveProof {
  readonly native: NativeTypes;
  readonly sourceCode: SourceCode;
  readonly exports: ReadonlySet<number>;
  readonly values: Set<TsNode>;
  readonly objects: Map<number, ReadonlyMap<string, Property> | null>;
  readonly invocations: Map<Scope, boolean>;
  readonly primitiveOperators: ReadonlySet<number>;
}

function primitiveOperators(native: NativeTypes): ReadonlySet<number> {
  const k = native.ast.SyntaxKind;
  return new Set([
    k.PlusToken, k.MinusToken, k.AsteriskToken, k.SlashToken, k.PercentToken, k.AsteriskAsteriskToken,
    k.LessThanToken, k.LessThanEqualsToken, k.GreaterThanToken, k.GreaterThanEqualsToken,
    k.EqualsEqualsEqualsToken, k.ExclamationEqualsEqualsToken, k.EqualsEqualsToken, k.ExclamationEqualsToken,
    k.AmpersandToken, k.BarToken, k.CaretToken, k.LessThanLessThanToken, k.GreaterThanGreaterThanToken, k.GreaterThanGreaterThanGreaterThanToken,
  ]);
}

/** The spread's read fields are primitives, the element stays closed, and neither module patches Object. */
function closedSpread({ declaration, fields }: Candidate, opening: ESTree.JSXOpeningElement, contract: ReceivingContract,
  reads: ReadonlySet<string>, proof: PrimitiveProof): boolean {
  const { native } = proof;
  if (!ownScalarReads(fields, reads, proof) || !closedElementValue(opening, declaration, fields, reads, proof)) return false;
  const implementation = signatureDeclaration(native, contract.signature);
  return implementation !== undefined && !ordinaryObjectEffects(native, contract.tag.getSourceFile()) &&
    !ordinaryObjectEffects(native, implementation.getSourceFile());
}

function ownScalarReads(fields: ReadonlyMap<string, Property>, reads: ReadonlySet<string>, proof: PrimitiveProof): boolean {
  for (const key of reads) {
    const field = fields.get(key);
    if (!field) return false;
    const value = proof.native.node(field.value);
    if (!value || !primitiveValue(value, proof, new Set())) return false;
  }
  return true;
}

/** Scalar annotations cannot witness the runtime value of an asserted alias or getter. */
function primitiveValue(node: TsNode, proof: PrimitiveProof, active: Set<TsNode>): boolean {
  const value = unassertedValue(proof.native.ast, node);
  if (proof.values.has(value)) return true;
  if (active.has(value) || active.size >= MAX_VALUE_DEPTH) return false;
  active.add(value);
  const result = scalarType(proof.native, proof.native.checker.getTypeAtLocation(value), false) && primitiveResult(value, proof, active);
  active.delete(value);
  // A failed proof may depend on the current depth or active path, so never cache it.
  if (result) proof.values.add(value);
  return result;
}

function primitiveResult(value: TsNode, proof: PrimitiveProof, active: Set<TsNode>): boolean {
  const { ast } = proof.native;
  if (primitiveLiteral(ast, value)) return true;
  if (ast.isPropertyAccessExpression(value) || ast.isElementAccessExpression(value)) return primitiveMember(value, proof, active);
  if (ast.isIdentifier(value)) return primitiveIdentifier(value, proof, active);
  const operands = primitiveOperands(value, proof);
  return operands !== null && operands.every((operand) => primitiveValue(operand, proof, active));
}

function primitiveLiteral(ast: NativeTypes["ast"], value: TsNode): boolean {
  const k = ast.SyntaxKind;
  return ast.isStringLiteralLikeNode(value) || ast.isNumericLiteral(value) || ast.isBigIntLiteral(value) ||
    value.kind === k.TrueKeyword || value.kind === k.FalseKeyword || value.kind === k.NullKeyword;
}

/** The operands of a primitive-producing operator, or null for any other expression. */
function primitiveOperands(value: TsNode, proof: PrimitiveProof): readonly TsNode[] | null {
  const { ast } = proof.native;
  const k = ast.SyntaxKind;
  if (ast.isTemplateExpression(value)) return value.templateSpans.map((span) => span.expression);
  if (ast.isTypeOfExpression(value)) return [value.expression];
  if (ast.isPrefixUnaryExpression(value)) {
    const operator = value.operator;
    return operator === k.PlusToken || operator === k.MinusToken || operator === k.ExclamationToken || operator === k.TildeToken
      ? [value.operand] : null;
  }
  if (ast.isConditionalExpression(value)) return [value.condition, value.whenTrue, value.whenFalse];
  if (!ast.isBinaryExpression(value)) return null;
  const operator = value.operatorToken.kind;
  return proof.primitiveOperators.has(operator) || returnedOperands(ast).has(operator) || operator === k.CommaToken
    ? [value.left, value.right] : null;
}

function primitiveIdentifier(value: Identifier, proof: PrimitiveProof, active: Set<TsNode>): boolean {
  const { ast, checker, sync } = proof.native;
  // Follow one local const edge so intermediate values share the same memoized proof.
  const symbol = ast.isShorthandPropertyAssignment(value.parent)
    ? checker.getShorthandAssignmentValueSymbol(value.parent) : checker.getSymbolAtLocation(value);
  const declaration = symbol && (symbol.flags & sync.SymbolFlags.Alias) === 0 && symbol.valueDeclaration
    ? declarationNode(proof.native, symbol.valueDeclaration) : undefined;
  const initializer = constInitializer(ast, declaration);
  return initializer !== undefined && initializer.getSourceFile() === value.getSourceFile() && primitiveValue(initializer, proof, active);
}

/** A const binding alone does not prevent its object's fields being mutated or exposed. */
function primitiveMember(node: TsNode, proof: PrimitiveProof, active: Set<TsNode>): boolean {
  const { ast, checker, sync } = proof.native;
  if (!ast.isPropertyAccessExpression(node) && !ast.isElementAccessExpression(node)) return false;
  if (!ast.isIdentifier(node.expression)) return false;
  const key = accessKey(ast, node);
  const symbol = checker.getSymbolAtLocation(node.expression);
  if (!symbol || key === undefined || (symbol.flags & sync.SymbolFlags.Alias) !== 0) return false;
  if (!proof.objects.has(symbol.id)) proof.objects.set(symbol.id, localObjectFields(symbol, node.getSourceFile(), proof));
  const field = proof.objects.get(symbol.id)?.get(key);
  const value = field && proof.native.node(field.value);
  return value !== undefined && primitiveValue(value, proof, active);
}

function accessKey(ast: NativeTypes["ast"], node: PropertyAccessExpression | ElementAccessExpression): string | undefined {
  if (ast.isPropertyAccessExpression(node)) return ast.isIdentifier(node.name) ? node.name.text : undefined;
  const argument = node.argumentExpression;
  return argument && (ast.isStringLiteralLikeNode(argument) || ast.isNumericLiteral(argument)) ? argument.text : undefined;
}

function localObjectFields(symbol: TsSymbol, source: SourceFile, proof: PrimitiveProof): ReadonlyMap<string, Property> | null {
  const local = localObjectLiteral(symbol, source, proof);
  if (local === null) return null;
  const { declaration, literal } = local;
  const list = parentOf(declaration);
  if (list?.type !== "VariableDeclaration" || list.kind !== "const" || declaration.id.type !== "Identifier" ||
    parentOf(list)?.type === "ExportNamedDeclaration") return null;
  const fields = plainLiteralFields(literal);
  const binding = declaratorBinding(proof.sourceCode, declaration);
  if (!fields || !binding || binding.defs.length !== 1 || !stableValueBinding(binding, (reference) => {
    if (!reference.isReadOnly() || reference.isTypeReference) return false;
    const member = parentOf(reference.identifier);
    return member?.type === "MemberExpression" && member.object === reference.identifier && readonlyFieldValue(member, fields);
  })) return null;
  return fields;
}

/** The same-file declarator whose const initializer is an object literal. */
function localObjectLiteral(symbol: TsSymbol, source: SourceFile, proof: PrimitiveProof):
  { readonly declaration: ESTree.VariableDeclarator; readonly literal: ESTree.ObjectExpression } | null {
  const { ast } = proof.native;
  const handle = symbol.valueDeclaration;
  // A declaration in another file fails the same-file check below; never fetch that file.
  if (!handle || handle.path !== source.path) return null;
  const declarationNative = declarationNode(proof.native, handle);
  const initial = constInitializer(ast, declarationNative);
  const initializer = initial && unassertedValue(ast, initial);
  if (!declarationNative || declarationNative.getSourceFile() !== source || !initializer || !ast.isObjectLiteralExpression(initializer)) return null;
  const declaration = proof.native.esTreeNode(declarationNative);
  const literal = proof.native.esTreeNode(initializer);
  return declaration?.type === "VariableDeclarator" && literal?.type === "ObjectExpression" ? { declaration, literal } : null;
}

function declaratorBinding(sourceCode: SourceCode, declaration: ESTree.VariableDeclarator): TsVariable | undefined {
  return sourceCode.getDeclaredVariables(declaration).find((variable) =>
    variable.defs.some((definition) => definition.type === "Variable" && definition.node === declaration)) as TsVariable | undefined;
}

function staticMemberKey(member: ESTree.MemberExpression): string | undefined {
  const property = member.property;
  return !member.computed && property.type === "Identifier" ? property.name :
    property.type === "Literal" && (typeof property.value === "string" || typeof property.value === "number") ? String(property.value) : undefined;
}

/** Only direct own-field values in data/JSX/local bindings are initially supported. */
function readonlyFieldValue(member: ESTree.MemberExpression, fields: ReadonlyMap<string, Property>): boolean {
  const key = staticMemberKey(member);
  if (key === undefined || !fields.has(key)) return false;
  const parent = parentOf(member);
  if (parent === null) return false;
  const object = parent.type === "Property" && parent.value === member ? parentOf(parent) : null;
  if (object?.type === "ObjectExpression") {
    const owner = parentOf(object);
    return owner !== null && ((owner.type === "JSXSpreadAttribute" && owner.argument === object) || initializes(owner, object));
  }
  return (parent.type === "JSXExpressionContainer" && parent.expression === member) || initializes(parent, member);
}

function initializes(owner: Node, value: Node): boolean {
  return owner.type === "VariableDeclarator" && owner.init === value;
}

/** An escaping or unbound element cannot satisfy the later closed-value proof. */
function privateElementDeclaration(opening: ESTree.JSXOpeningElement): ESTree.VariableDeclarator | null {
  const element = parentOf(opening);
  if (element === null) return null;
  const value = outerExpression(element);
  const declaration = parentOf(value);
  if (declaration?.type !== "VariableDeclarator" || declaration.init !== value || declaration.id.type !== "Identifier") return null;
  const list = parentOf(declaration);
  return list?.type === "VariableDeclaration" && list.kind === "const" && parentOf(list)?.type !== "ExportNamedDeclaration" ? declaration : null;
}

/** Only unused private const elements or fixed consumed scalar inspections are closed. */
function closedElementValue(opening: ESTree.JSXOpeningElement, declaration: ESTree.VariableDeclarator, fields: ReadonlyMap<string, Property>,
  reads: ReadonlySet<string>, proof: PrimitiveProof): boolean {
  const { ast, checker } = proof.native;
  if (!closedInvocation(opening, proof) || !constInitializer(ast, proof.native.node(declaration))) return false;
  const binding = declaratorBinding(proof.sourceCode, declaration);
  const id = proof.native.node(declaration.id);
  const symbol = id && checker.getSymbolAtLocation(id);
  if (!symbol || proof.exports.has(symbol.id)) return false;
  return binding !== undefined && binding.defs.length === 1 && stableValueBinding(binding, (reference) => {
    if (!reference.isReadOnly() || reference.isTypeReference || reference.from.variableScope !== binding.scope.variableScope) return false;
    return consumedElementRead(reference.identifier, fields, reads);
  });
}

/** An argument or captured object can invoke a getter before element creation. */
function closedInvocation(node: Node, proof: PrimitiveProof): boolean {
  for (let scope: Scope | null = proof.sourceCode.getScope(node); scope; scope = scope.upper) {
    if (scope.type !== "function") continue;
    let closed = proof.invocations.get(scope);
    if (closed === undefined) {
      closed = independentInvocation(scope, proof);
      proof.invocations.set(scope, closed);
    }
    if (!closed) return false;
  }
  return true;
}

function independentInvocation(scope: Scope, proof: PrimitiveProof): boolean {
  const block = scope.block;
  if (block.type !== "ArrowFunctionExpression" && block.type !== "FunctionDeclaration" && block.type !== "FunctionExpression") return false;
  const argumentsBinding = scope.set.get("arguments");
  if (block.async || block.generator ||
    argumentsBinding?.references.some((reference) => !typeOnlyReference(reference as TsReference))) return false;
  for (const parameter of block.params) {
    if (parameter.type !== "Identifier" || parameter.name === "this") return false;
    const binding = scope.set.get(parameter.name);
    if (!binding || binding.references.some((reference) => !typeOnlyReference(reference as TsReference))) return false;
  }
  return scope.through.every((entry) => {
    const reference = entry as TsReference;
    if (typeOnlyReference(reference)) return true;
    const value = outerExpression(reference.identifier);
    const parent = parentOf(value);
    const read = parent?.type === "MemberExpression" && parent.object === value ? parent : value;
    const native = proof.native.node(read);
    return native !== undefined && primitiveValue(native, proof, new Set());
  });
}

/** A scalar field read exposes its value without exposing the element or props object. */
function consumedElementRead(node: Node, fields: ReadonlyMap<string, Property>, reads: ReadonlySet<string>): boolean {
  const identifier = outerExpression(node);
  const props = parentOf(identifier);
  if (!props || props.type !== "MemberExpression" || props.object !== identifier || props.optional || staticMemberKey(props) !== "props") return false;
  const member = parentOf(props);
  if (member?.type !== "MemberExpression" || member.object !== props || member.optional) return false;
  const key = staticMemberKey(member);
  return key !== undefined && reads.has(key) && readonlyFieldValue(member, fields);
}

function closedObjectType(native: NativeTypes): boolean {
  const { checker, sync } = native;
  const object = checker.resolveName("Object", sync.SymbolFlags.Type, undefined, false);
  return object !== undefined && closedObjectContract(native, checker.getDeclaredTypeOfSymbol(object));
}

interface Candidate {
  readonly node: ESTree.JSXSpreadAttribute;
  readonly declaration: ESTree.VariableDeclarator;
  readonly fields: ReadonlyMap<string, Property>;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Report statically known fields spread outside a resolved component props contract.", url: docsUrl(NAME) },
    schema: [],
    messages: {
      excess: "This spread forwards fields outside the receiving component's declared contract: {{fields}}. Forward the needed fields explicitly or review the contract; an annotation alone does not remove runtime fields.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let dynamic = false;
    let candidates: Candidate[] = [];

    /** The original's per-file `evaluate`, against tsrs; returns the excess fields to report, or null. */
    function evaluator(native: NativeTypes) {
      const { checker } = native;
      const sourceCode = context.sourceCode;
      let objectContract: boolean | undefined;
      let standardJSX: boolean | undefined;
      let proof: PrimitiveProof | undefined;
      const contracts = new Map<Type, boolean>();
      const receivers = new Map<Signature, ReadonlySet<string> | null>();
      const overrides = new Map<string, boolean>();
      return (candidate: Candidate): string | null => {
        const opening = parentOf(candidate.node) as ESTree.JSXOpeningElement;
        standardJSX ??= supportedJSX(native, sourceCode.getAllComments());
        if (!standardJSX) return null;
        objectContract ??= closedObjectType(native);
        if (!objectContract) return null;
        const contract = receivingContract(native, opening, contracts);
        if (!contract) return null;
        const excess = [...candidate.fields.keys()].filter((key) => checker.getPropertyOfType(contract.props, key) === undefined).sort();
        if (!excess.length || !stableReceiver(native, contract.tag, contract.signature, overrides)) return null;
        const signature = contract.signature;
        if (!receivers.has(signature)) receivers.set(signature, receiverReads(native, signature));
        const reads = receivers.get(signature);
        proof ??= { native, sourceCode, exports: exportedSymbols(native, native.source), values: new Set(), objects: new Map(),
          invocations: new Map(), primitiveOperators: primitiveOperators(native) };
        return reads && closedSpread(candidate, opening, contract, reads, proof) ? excess.join(", ") : null;
      };
    }

    return {
      before() {
        tsrs = null;
        dynamic = false;
        candidates = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      JSXSpreadAttribute(node) {
        if (node.argument.type !== "ObjectExpression") return;
        const opening = parentOf(node);
        if (opening?.type !== "JSXOpeningElement" || !opening.selfClosing || opening.attributes.length !== 1 ||
          opening.name.type !== "JSXIdentifier" || /^[a-z]/u.test(opening.name.name)) return;
        const declaration = privateElementDeclaration(opening);
        if (!declaration) return;
        const fields = literalFields(node.argument);
        if (!fields?.size) return;
        candidates.push({ node, declaration, fields });
      },
      CallExpression(node) {
        if (directEval(node)) dynamic = true;
      },
      "Program:exit"() {
        if (!candidates.length || dynamic || tsrs === null) return;
        const excess = tsrs.run((file) => candidates.map(evaluator(nativeTypes(file))));
        if (excess === null) return;
        candidates.forEach(({ node }, i) => {
          const fields = excess[i];
          if (fields !== null && fields !== undefined) context.report({ node, messageId: "excess", data: { fields } });
        });
      },
    };
  },
});

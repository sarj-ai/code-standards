/**
 * @fileoverview no-excess-jsx-props — compare known runtime keys with a resolved component contract.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-excess-jsx-props.test.ts
 */
import { AST_NODE_TYPES, ESLintUtils, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { currentNativeSource } from "./_checked-native-source.js";
import { closedObjectContract } from "./_closed-object-contract.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { constInitializer, unassertedValue } from "./_native-const-value.js";
import { ordinaryObjectEffects } from "./_ordinary-object-effects.js";
import { isGeneratedFile } from "./_paths.js";
import { directEval, exportedSymbols } from "./_private-scalar-consumer.js";
import { RETURNED_OPERANDS, scalarParameterView, scalarType } from "./_scalar-parameter-view.js";
import { stableValueBinding, typeOnlyReference } from "./_stable-value-binding.js";
import { outerExpression } from "./_unwrap-expression.js";

const EXAMPLE_TSCONFIG = { path: "tsconfig.json", source: '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler","jsx":"react-jsx"}}' } as const;
const EXAMPLE_JSX = { path: "jsx.d.ts", source: 'declare module "react/jsx-runtime" { export namespace JSX { interface Element {} interface IntrinsicElements {span: {children?: unknown}} } }' } as const;

export const NO_EXCESS_JSX_PROPS_DOCUMENTATION = {
  summary: "Report statically known fields spread outside a resolved component props contract.",
  rationale: "A spread can forward unrelated data even when structural typing accepts the larger object. Changing its annotation does not remove runtime fields.",
  remediation: "Forward the declared fields explicitly or review the receiving contract. A projection changes object identity and allocations; this rule never constructs one automatically.",
  category: "maintainability",
  defaultLevel: "warning",
  autofix: "none",
  limitations: [
    "The created JSX value must initialize a private actual const binding. Only unused values or same-function-scope fixed reads of already proven consumed scalar props are supported. Enclosing invocations must have no runtime argument or arguments-object dependency, async/generator suspension, or unproved captured values. Unused simple arguments and captured scalar data reuse the existing provenance proof; destructured/default/rest arguments remain unsupported. Exported, returned, aliased, captured, aggregated or forwarded elements, whole-props access, opaque calls, type observations and writes abstain. A caller can mutate production React props after creation even when development React freezes them; initial source provenance alone is insufficient. This restriction intentionally excludes ordinary exported and rendered elements until their consumers can be proved.",
    "The rule abstains when the receiving or calling project runtime dependency context contains a known ordinary Object-prototype effect or exposure, native eval/Function capabilities, any explicit call, constructor or tagged-template invocation, for-of or for-in iteration, an ambient or uninitialized value declaration or a declaration-file value read, an unresolved lexical value (including a shorthand or a type-only name used as a value), an erased const-enum value without a runtime binding proof, an opaque globalThis member, an implicit this/super/module-metadata capability, an extracted reflective method, or a member-write target not proven to be a fresh unrelated object/array literal. Callable and class metadata writes, including through erased const aliases, abstain: runtime metadata can observe omitted fields even when it is absent from the native JSX contract. Native shorthand value symbols preserve global capability identity instead of trusting a newly created property symbol. Property keys, control-flow labels, intrinsic JSX names and erased type positions do not evaluate lexical values; their missing symbols or Any types do not alone veto a finding. Native ESM imports/re-exports and literal dynamic imports are followed in both dependency and known-importer directions, including other dependencies of those importers and resolved bare path aliases; whole-clause import type/export type forms are skipped. Import-equals and other loader forms are unsupported. Per-specifier type imports/exports retain their runtime edges when native verbatimModuleSyntax emit keeps an empty import/export. Unresolved runtime imports and declaration-only or external-library runtime imports abstain. Literal dynamic imports retain their module-resolution proof. External code outside the analyzed project context and standard library implementations remain opaque; standard ordinary Object built-ins are assumed. Connected runtime dependency contexts beyond 128 files or const-alias proofs beyond 64 steps abstain. Safe reflective code may therefore be excluded. This finite known-effect exclusion does not prove universal prototype pristineness.",
    "Requires parser-owned TypeScript information, a strict module implementation, a complete Object base, a self-closing identifier tag with one plain object-literal spread and no other attributes, and one nongeneric implemented synchronous arrow receiver with a resolved finite props surface. Sibling attributes or children could override the proven source values. Unknown, opaque, union, overloaded, generic, intrinsic and class receivers are excluded.",
    "Mapped types, index signatures, namespace/value-derived contracts, unresolved inherited or computed receiver keys, nonliteral computed source keys, nested spreads, accessors and explicit __proto__ keys are excluded. Source type properties alone do not prove enumerable own runtime keys. key, ref, React's __self/__source development metadata and TypeScript's hyphenated JSX attribute names are preserved.",
    "Native member lookup includes inherited, optional, readonly and implicit Object capabilities. The rule reports runtime keys outside the contract; it does not infer unused component fields, demand smaller public APIs, or erase producer type information.",
    "Runtime alias references require active native checking of each reached local implementation, with no located syntax or semantic errors. Checking disabled by noCheck or native-shaped TypeScript suppression directives is unavailable evidence. JavaScript, declaration/default/external-library files, foreign SourceFile objects and project-reference programs are unsupported for this alias proof. Importer indexing does not request full semantic checks; reached files reuse the parser-owned Program's diagnostic caches. Unlocated/global diagnostics are not treated as a clean project or as proof of runtime binding presence. Namespace value reads, including merged and const-enum-only namespace carriers, abstain because a ValueModule symbol can survive erased runtime output without a native error. Pure type namespaces and nonambient namespace declaration names remain non-value positions; explicit ambient namespace declarations retain their existing exclusion. A non-import-alias value declared in another source also abstains: inclusion in the type Program does not establish that a script/global implementation executes or that an ambient binding is supplied as a data property. Native standard global identities retain their existing assumptions.",
    "Requires a single returned view made from intrinsic JSX, literals and scalar parameter reads/operators. JSX objects may be rendered as children or returned branches, but cannot be operands of scalar coercions or intrinsic attribute values. Free runtime values, helper calls, callbacks, object-valued consumed fields, custom tags, rest/spread, reflection and dynamic access prevent a finding; indirect element.props aliases cannot be inferred safe. Every inspected or destructured root field must be an own source-literal key; an omitted field could invoke an inherited getter. Bound/read source values require concrete scalar types without undefined, Any or unknown and runtime primitive provenance: literals, operators/templates with proven primitive operands, proven conditional tests and branches, or local immutable const initializers after removing assertions. Direct own fields of a same-file const object literal are supported only when every object reference is a fixed field value in a direct object initializer, inline JSX spread, JSX expression or local binding, with no direct eval. Mutation, accessors, method receivers, dynamic keys, reflection, whole-object aliases and exports abstain. Opaque calls, getters, parameters, mutable bindings and imported source values abstain even when annotated as scalars. Unproven source paths beyond 64 expressions abstain as an analysis resource limit. Only successful value proofs are memoized. An alias or assertion cannot turn an object into a primitive; undefined can activate runtime defaults. Opaque HOC and declaration-file signatures remain unsupported.",
    "The actual tag must resolve through immutable identifier aliases to a const arrow initializer. Constructible ordinary functions, mutable, member, proxy, call-produced and asserted receiver values are excluded even when their callable type resembles a known implementation; inherited runtime metadata can change ordinary function dispatch. Exactly one actual parameter and no explicit this parameter are supported.",
    "Reached files containing actual JSX additionally require their compiler-owned implicit runtime import and the native module symbol's declaration owners. Known non-declaration runtime implementations are unsupported even when their bodies have no ordinary Object effects: a custom factory can reinterpret forwarded fields. External declaration files and owned top-level ambient module declarations in declaration files retain the explicit standard-React library assumption; those declarations do not prove the actual runtime JavaScript identity. Missing or ambiguous internal import metadata, missing native symbols, foreign owners and local nonambient declaration-module sources abstain. Non-JSX dependencies do not acquire a runtime edge merely because the compiler records an unused synthetic JSX import. Runtime rebinding outside the compiler-visible module context remains opaque, not validated by this proof.",
    "Requires target ES2015 or newer, explicit native ES-module output and the standard React automatic JSX runtime (react-jsx or react-jsxdev). Downlevel arrows become constructible functions; CommonJS exports remain mutable. Preserve/classic JSX, custom factories, namespaces, import sources and per-file JSX directives are unsupported. Imported library implementations and cross-project source redirects are opaque; relative imports within this program remain supported.",
  ],
  references: ["https://github.com/jsx-eslint/eslint-plugin-react/blob/master/docs/rules/jsx-props-no-spreading.md"],
  examples: [
    { id: "excess-runtime-field", title: "An unrelated field is forwarded at runtime", outcome: "match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; const Avatar = ({ displayName }: { displayName: string }) => <span>{displayName}</span>;\nconst avatar = <Avatar {...{ displayName: 'Ada', email: 'ada@example.test' }} />;" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 1, public: true },
    { id: "explicit-fields", title: "Forward only the declared field", outcome: "no-match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; const Avatar = ({ displayName }: { displayName: string }) => <span>{displayName}</span>;\nconst avatar = <Avatar displayName='Ada' />;" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 0, public: true },
    { id: "asserted-source-alias", scenarioId: "source-provenance", title: "An asserted alias can still observe forwarded data", outcome: "no-match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; let element: any; const opaque = {toString() {return element.props.email;}}; const name = opaque as unknown as string; const Avatar = ({displayName}: {displayName: string}) => <span>{`${displayName}`}</span>; element = <Avatar {...{displayName: name, email: 'needed'}}/>;" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 0, public: true },
    { id: "literal-source-alias", scenarioId: "source-provenance", title: "A proven primitive alias preserves the finding", outcome: "match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; const name = 'Ada'; const Avatar = ({displayName}: {displayName: string}) => <span>{`${displayName}`}</span>; const element = <Avatar {...{displayName: name, email: 'unused'}}/>;" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 1, public: true },
    { id: "inherited-runtime-hook", scenarioId: "prototype-effects", title: "An inherited runtime hook can observe forwarded data", outcome: "no-match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; let element: any; const Avatar = ({displayName}: {displayName: string}) => <span>{displayName}</span>; element = <Avatar {...{displayName: 'Ada', email: 'needed'}}/>; Object.defineProperty(Object.prototype, 'ref', {configurable: true, get() {Object.defineProperty(this, 'children', {configurable: true, value: element.props.email}); return null;}});" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 0, public: true },
    { id: "unrelated-runtime-object", scenarioId: "prototype-effects", title: "An unrelated own-property write preserves the finding", outcome: "match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; const target = {ref: null}; target.ref = null; const Avatar = ({displayName}: {displayName: string}) => <span>{displayName}</span>; const element = <Avatar {...{displayName: 'Ada', email: 'unused'}}/>;" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 1, public: true },
    { id: "erased-callable-metadata", scenarioId: "callable-metadata", title: "Runtime metadata can observe an omitted field", outcome: "no-match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; const target = {ref: 0}; const Avatar = ({displayName}: {displayName: string}) => <span>{displayName}</span>; (Avatar as unknown as {defaultProps: {email: string}}).defaultProps = {get email() {target.ref = 1; return 'fallback';}}; const element = <Avatar {...{displayName: 'Ada', email: 'needed'}}/>; const observation = target.ref; export {observation};" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 0, public: true },
    { id: "unrelated-object-metadata", scenarioId: "callable-metadata", title: "An unrelated data object's metadata preserves the finding", outcome: "match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; const settings = {defaultProps: {email: 'fallback'}}; settings.defaultProps = {email: 'updated'}; const Avatar = ({displayName}: {displayName: string}) => <span>{displayName}</span>; const element = <Avatar {...{displayName: 'Ada', email: 'unused'}}/>;" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 1, public: true },
    { id: "consumed-scalar-inspection", scenarioId: "created-value", title: "A private element exposes only its consumed scalar", outcome: "match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; const Avatar = ({displayName}: {displayName: string}) => <span>{displayName}</span>; const element = <Avatar {...{displayName: 'Ada', email: 'unused'}}/>; const summary = {displayName: (element as {props: {displayName: string}}).props.displayName}; export {summary};" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 1, public: true },
    { id: "opaque-element-consumer", scenarioId: "created-value", title: "An opaque consumer can observe or mutate element props", outcome: "no-match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; declare function inspect(value: unknown): void; const Avatar = ({displayName}: {displayName: string}) => <span>{displayName}</span>; const element = <Avatar {...{displayName: 'Ada', email: 'needed'}}/>; inspect(element);" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

const RESERVED_PROPS: ReadonlySet<string> = new Set(["key", "ref", "__self", "__source"]);
const ESM_MODULES: ReadonlySet<ts.ModuleKind> = new Set([ts.ModuleKind.ES2015, ts.ModuleKind.ES2020, ts.ModuleKind.ES2022, ts.ModuleKind.ESNext]);
const JSX_DIRECTIVE = /@jsx(?:ImportSource|Runtime|Frag)?(?:\s|$)/iu;
const MAX_VALUE_DEPTH = 64;
const PRIMITIVE_OPERATORS: ReadonlySet<ts.SyntaxKind> = new Set([
  ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken, ts.SyntaxKind.SlashToken, ts.SyntaxKind.PercentToken, ts.SyntaxKind.AsteriskAsteriskToken,
  ts.SyntaxKind.LessThanToken, ts.SyntaxKind.LessThanEqualsToken, ts.SyntaxKind.GreaterThanToken, ts.SyntaxKind.GreaterThanEqualsToken,
  ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken,
  ts.SyntaxKind.AmpersandToken, ts.SyntaxKind.BarToken, ts.SyntaxKind.CaretToken, ts.SyntaxKind.LessThanLessThanToken, ts.SyntaxKind.GreaterThanGreaterThanToken, ts.SyntaxKind.GreaterThanGreaterThanGreaterThanToken,
]);
function plainLiteralFields(node: TSESTree.ObjectExpression): Map<string, TSESTree.Property> | null {
  const fields = new Map<string, TSESTree.Property>();
  for (const property of node.properties) {
    if (property.type !== AST_NODE_TYPES.Property || property.kind !== "init") return null;
    const key = property.key;
    let name: string;
    if (!property.computed && key.type === AST_NODE_TYPES.Identifier) name = key.name;
    else if (key.type === AST_NODE_TYPES.Literal && (typeof key.value === "string" || typeof key.value === "number")) name = String(key.value);
    else return null;
    if (name === "__proto__") return null;
    fields.set(name, property);
  }
  return fields;
}

function literalFields(node: TSESTree.ObjectExpression): ReadonlyMap<string, TSESTree.Property> | null {
  const fields = plainLiteralFields(node);
  if (fields) for (const name of fields.keys()) if (RESERVED_PROPS.has(name) || name.includes("-")) fields.delete(name);
  return fields;
}

/** A declared finite surface alone cannot establish that a wrapper ignores extras. */
function receiverReads(signature: ts.Signature, checker: ts.TypeChecker): ReadonlySet<string> | null {
  const declaration = signature.getDeclaration();
  if (!declaration || !ts.isArrowFunction(declaration) || declaration.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.AsyncKeyword) || signature.thisParameter || declaration.parameters.length !== 1) return null;
  const parameter = declaration.parameters[0];
  return parameter ? scalarParameterView(parameter, declaration.body, checker) : null;
}

function stableReceiver(tag: ts.JsxTagNameExpression, signature: ts.Signature, checker: ts.TypeChecker, program: ts.Program, overrides: WeakMap<ts.SourceFile, boolean>): boolean {
  if (!ts.isIdentifier(tag)) return false;
  const initializer = immutableInitializer(tag, checker);
  if (!initializer || initializer !== signature.getDeclaration() || !ts.isArrowFunction(initializer)) return false;
  return supportedImplementation(initializer.getSourceFile(), tag.getSourceFile(), program, overrides);
}

function immutableInitializer(tag: ts.Identifier, checker: ts.TypeChecker): ts.Expression | undefined {
  let symbol = checker.getSymbolAtLocation(tag);
  const seen = new Set<ts.Symbol>();
  while (symbol && !seen.has(symbol)) {
    seen.add(symbol);
    if ((symbol.flags & ts.SymbolFlags.Alias) !== 0) {
      symbol = checker.getAliasedSymbol(symbol);
      continue;
    }
    const initializer = constInitializer(symbol.valueDeclaration);
    if (!initializer || !ts.isIdentifier(initializer)) return initializer;
    symbol = checker.getSymbolAtLocation(initializer);
  }
  return undefined;
}

function supportedImplementation(source: ts.SourceFile, caller: ts.SourceFile, program: ts.Program, overrides: WeakMap<ts.SourceFile, boolean>): boolean {
  if (!ts.isExternalModule(source) || source.impliedNodeFormat === ts.ModuleKind.CommonJS || program.isSourceFileFromExternalLibrary(source)) return false;
  if (source === caller) return true;
  if (program.getProjectReferences()?.length) return false;
  if (!overrides.has(source)) overrides.set(source, (ts.getLeadingCommentRanges(source.text, 0) ?? []).some((range) => JSX_DIRECTIVE.test(source.text.slice(range.pos, range.end))));
  return !overrides.get(source);
}

function supportedJSX(options: ts.CompilerOptions, comments: readonly TSESTree.Comment[]): boolean {
  return (options.target ?? ts.ScriptTarget.ES5) >= ts.ScriptTarget.ES2015 &&
    ESM_MODULES.has(options.module ?? ts.ModuleKind.None) &&
    (options.jsx === ts.JsxEmit.ReactJSX || options.jsx === ts.JsxEmit.ReactJSXDev) &&
    !options.jsxFactory && !options.reactNamespace && (!options.jsxImportSource || options.jsxImportSource === "react") &&
    !comments.some((comment) => JSX_DIRECTIVE.test(comment.value));
}

function receivingContract(opening: TSESTree.JSXOpeningElement, services: ParserServicesWithTypeInformation, checker: ts.TypeChecker, contracts: WeakMap<ts.Type, boolean>): { tag: ts.JsxTagNameExpression; signature: ts.Signature; props: ts.Type } | null {
  const native = services.esTreeNodeToTSNodeMap.get(opening);
  if (!ts.isJsxOpeningElement(native) && !ts.isJsxSelfClosingElement(native)) return null;
  const receiver = checker.getTypeAtLocation(native.tagName);
  const signatures = checker.getSignaturesOfType(receiver, ts.SignatureKind.Call);
  const signature = signatures[0];
  if (receiver.isUnion() || signatures.length !== 1 || !signature || signature.typeParameters?.length) return null;
  const props = checker.getContextualType(native.attributes);
  if (!props) return null;
  if (!contracts.has(props)) contracts.set(props, closedObjectContract(props, checker));
  return contracts.get(props) ? { tag: native.tagName, signature, props } : null;
}

interface PrimitiveProof {
  readonly checker: ts.TypeChecker;
  readonly services: ParserServicesWithTypeInformation;
  readonly sourceCode: TSESLint.SourceCode;
  readonly staticScope: boolean;
  readonly exports: ReadonlySet<ts.Symbol>;
  readonly values: WeakSet<ts.Node>;
  readonly objects: WeakMap<ts.Symbol, ReadonlyMap<string, TSESTree.Property> | null>;
  readonly invocations: WeakMap<TSESLint.Scope.Scope, boolean>;
}

function ownScalarReads(fields: ReadonlyMap<string, TSESTree.Property>, reads: ReadonlySet<string>, proof: PrimitiveProof): boolean {
  for (const key of reads) {
    const field = fields.get(key);
    if (!field) return false;
    if (!primitiveValue(proof.services.esTreeNodeToTSNodeMap.get(field.value), proof, new Set())) return false;
  }
  return true;
}

/** Scalar annotations cannot witness the runtime value of an asserted alias or getter. */
function primitiveValue(node: ts.Node, proof: PrimitiveProof, active: Set<ts.Node>): boolean {
  const value = unassertedValue(node);
  if (proof.values.has(value)) return true;
  if (active.has(value) || active.size >= MAX_VALUE_DEPTH) return false;
  active.add(value);
  const result = scalarType(proof.checker.getTypeAtLocation(value), false) && primitiveResult(value, proof, active);
  active.delete(value);
  // A failed proof may depend on the current depth or active path, so never cache it.
  if (result) proof.values.add(value);
  return result;
}

function primitiveResult(value: ts.Node, proof: PrimitiveProof, active: Set<ts.Node>): boolean {
  if (ts.isStringLiteralLike(value) || ts.isNumericLiteral(value) || ts.isBigIntLiteral(value) ||
    value.kind === ts.SyntaxKind.TrueKeyword || value.kind === ts.SyntaxKind.FalseKeyword || value.kind === ts.SyntaxKind.NullKeyword) return true;
  if (ts.isTemplateExpression(value)) return value.templateSpans.every((span) => primitiveValue(span.expression, proof, active));
  if (ts.isTypeOfExpression(value)) return primitiveValue(value.expression, proof, active);
  if (ts.isPrefixUnaryExpression(value)) return (value.operator === ts.SyntaxKind.PlusToken || value.operator === ts.SyntaxKind.MinusToken ||
    value.operator === ts.SyntaxKind.ExclamationToken || value.operator === ts.SyntaxKind.TildeToken) && primitiveValue(value.operand, proof, active);
  if (ts.isConditionalExpression(value)) return primitiveValue(value.condition, proof, active) &&
    primitiveValue(value.whenTrue, proof, active) && primitiveValue(value.whenFalse, proof, active);
  if (ts.isBinaryExpression(value)) {
    return (PRIMITIVE_OPERATORS.has(value.operatorToken.kind) || RETURNED_OPERANDS.has(value.operatorToken.kind) || value.operatorToken.kind === ts.SyntaxKind.CommaToken) &&
      primitiveValue(value.left, proof, active) && primitiveValue(value.right, proof, active);
  }
  if (ts.isPropertyAccessExpression(value) || ts.isElementAccessExpression(value)) return primitiveMember(value, proof, active);
  if (!ts.isIdentifier(value)) return false;
  // Follow one local const edge so intermediate values share the same memoized proof.
  const symbol = ts.isShorthandPropertyAssignment(value.parent)
    ? proof.checker.getShorthandAssignmentValueSymbol(value.parent) : proof.checker.getSymbolAtLocation(value);
  const initializer = symbol && (symbol.flags & ts.SymbolFlags.Alias) === 0 ? constInitializer(symbol.valueDeclaration) : undefined;
  return initializer !== undefined && initializer.getSourceFile() === value.getSourceFile() && primitiveValue(initializer, proof, active);
}

/** A const binding alone does not prevent its object's fields being mutated or exposed. */
function primitiveMember(node: ts.PropertyAccessExpression | ts.ElementAccessExpression, proof: PrimitiveProof, active: Set<ts.Node>): boolean {
  if (!proof.staticScope || !ts.isIdentifier(node.expression)) return false;
  const key = ts.isPropertyAccessExpression(node) ? node.name.text : node.argumentExpression &&
    (ts.isStringLiteralLike(node.argumentExpression) || ts.isNumericLiteral(node.argumentExpression)) ? node.argumentExpression.text : undefined;
  const symbol = proof.checker.getSymbolAtLocation(node.expression);
  if (!symbol || key === undefined || (symbol.flags & ts.SymbolFlags.Alias) !== 0) return false;
  if (!proof.objects.has(symbol)) proof.objects.set(symbol, localObjectFields(symbol, node.getSourceFile(), proof));
  const field = proof.objects.get(symbol)?.get(key);
  return field !== undefined && primitiveValue(proof.services.esTreeNodeToTSNodeMap.get(field.value), proof, active);
}

function localObjectFields(symbol: ts.Symbol, source: ts.SourceFile, proof: PrimitiveProof): ReadonlyMap<string, TSESTree.Property> | null {
  const native = symbol.valueDeclaration;
  const initial = constInitializer(native);
  const initializer = initial && unassertedValue(initial);
  if (!native || native.getSourceFile() !== source || !initializer || !ts.isObjectLiteralExpression(initializer)) return null;
  const declaration = proof.services.tsNodeToESTreeNodeMap.get(native);
  const literal = proof.services.tsNodeToESTreeNodeMap.get(initializer);
  if (declaration.type !== AST_NODE_TYPES.VariableDeclarator || declaration.parent.kind !== "const" || declaration.id.type !== AST_NODE_TYPES.Identifier || literal.type !== AST_NODE_TYPES.ObjectExpression ||
    declaration.parent.parent.type === AST_NODE_TYPES.ExportNamedDeclaration) return null;
  const fields = plainLiteralFields(literal);
  const binding = proof.sourceCode.getDeclaredVariables(declaration).find((variable) => variable.defs.some((definition) => definition.type === "Variable" && definition.node === declaration));
  if (!fields || !binding || binding.defs.length !== 1 || !stableValueBinding(binding, (reference) => {
    if (!reference.isReadOnly() || reference.isTypeReference) return false;
    const member = reference.identifier.parent;
    return member.type === AST_NODE_TYPES.MemberExpression && member.object === reference.identifier && readonlyFieldValue(member, fields);
  })) return null;
  return fields;
}

function staticMemberKey(member: TSESTree.MemberExpression): string | undefined {
  const property = member.property;
  return !member.computed && property.type === AST_NODE_TYPES.Identifier ? property.name :
    property.type === AST_NODE_TYPES.Literal && (typeof property.value === "string" || typeof property.value === "number") ? String(property.value) : undefined;
}

/** Only direct own-field values in data/JSX/local bindings are initially supported. */
function readonlyFieldValue(member: TSESTree.MemberExpression, fields: ReadonlyMap<string, TSESTree.Property>): boolean {
  const key = staticMemberKey(member);
  if (key === undefined || !fields.has(key)) return false;
  const parent = member.parent;
  if (parent.type === AST_NODE_TYPES.Property && parent.value === member && parent.parent.type === AST_NODE_TYPES.ObjectExpression) {
    const object = parent.parent;
    const owner = object.parent;
    return (owner.type === AST_NODE_TYPES.JSXSpreadAttribute && owner.argument === object) ||
      (owner.type === AST_NODE_TYPES.VariableDeclarator && owner.init === object);
  }
  return (parent.type === AST_NODE_TYPES.JSXExpressionContainer && parent.expression === member) ||
    (parent.type === AST_NODE_TYPES.VariableDeclarator && parent.init === member);
}

/** An escaping or unbound element cannot satisfy the later closed-value proof. */
function privateElementDeclaration(opening: TSESTree.JSXOpeningElement): TSESTree.VariableDeclarator | null {
  const value = outerExpression(opening.parent);
  const declaration = value.parent;
  return declaration.type === AST_NODE_TYPES.VariableDeclarator && declaration.init === value && declaration.id.type === AST_NODE_TYPES.Identifier &&
    declaration.parent.kind === "const" && declaration.parent.parent.type !== AST_NODE_TYPES.ExportNamedDeclaration ? declaration : null;
}

/** Only unused private const elements or fixed consumed scalar inspections are closed. */
function closedElementValue(opening: TSESTree.JSXOpeningElement, declaration: TSESTree.VariableDeclarator, fields: ReadonlyMap<string, TSESTree.Property>, reads: ReadonlySet<string>, proof: PrimitiveProof): boolean {
  if (!proof.staticScope || !closedInvocation(opening, proof) || !constInitializer(proof.services.esTreeNodeToTSNodeMap.get(declaration))) return false;
  const binding = proof.sourceCode.getDeclaredVariables(declaration).find((variable) => variable.defs.some((definition) => definition.type === "Variable" && definition.node === declaration));
  const symbol = proof.checker.getSymbolAtLocation(proof.services.esTreeNodeToTSNodeMap.get(declaration.id));
  if (!symbol || proof.exports.has(symbol)) return false;
  return binding !== undefined && binding.defs.length === 1 && stableValueBinding(binding, (reference) => {
    if (!reference.isReadOnly() || reference.isTypeReference || reference.from.variableScope !== binding.scope.variableScope) return false;
    return consumedElementRead(reference.identifier, fields, reads);
  });
}

/** An argument or captured object can invoke a getter before element creation. */
function closedInvocation(node: TSESTree.Node, proof: PrimitiveProof): boolean {
  for (let scope: TSESLint.Scope.Scope | null = proof.sourceCode.getScope(node); scope; scope = scope.upper) {
    if (scope.type !== "function") continue;
    let closed = proof.invocations.get(scope);
    if (closed === undefined) { closed = independentInvocation(scope, proof); proof.invocations.set(scope, closed); }
    if (!closed) return false;
  }
  return true;
}

function independentInvocation(scope: TSESLint.Scope.Scope, proof: PrimitiveProof): boolean {
  const block = scope.block;
  if (block.type !== AST_NODE_TYPES.ArrowFunctionExpression && block.type !== AST_NODE_TYPES.FunctionDeclaration && block.type !== AST_NODE_TYPES.FunctionExpression) return false;
  if (block.async || block.generator || scope.set.get("arguments")?.references.some((reference) => !typeOnlyReference(reference))) return false;
  for (const parameter of block.params) {
    if (parameter.type !== AST_NODE_TYPES.Identifier || parameter.name === "this") return false;
    const binding = scope.set.get(parameter.name);
    if (!binding || binding.references.some((reference) => !typeOnlyReference(reference))) return false;
  }
  return scope.through.every((reference) => {
    if (typeOnlyReference(reference)) return true;
    const value = outerExpression(reference.identifier);
    const parent = value.parent;
    const read = parent?.type === AST_NODE_TYPES.MemberExpression && parent.object === value ? parent : value;
    return primitiveValue(proof.services.esTreeNodeToTSNodeMap.get(read), proof, new Set());
  });
}

/** A scalar field read exposes its value without exposing the element or props object. */
function consumedElementRead(node: TSESTree.Identifier | TSESTree.JSXIdentifier, fields: ReadonlyMap<string, TSESTree.Property>, reads: ReadonlySet<string>): boolean {
  const identifier = outerExpression(node);
  const props = identifier.parent;
  if (!props || props.type !== AST_NODE_TYPES.MemberExpression || props.object !== identifier || props.optional || staticMemberKey(props) !== "props") return false;
  const member = props.parent;
  if (member.type !== AST_NODE_TYPES.MemberExpression || member.object !== props || member.optional) return false;
  const key = staticMemberKey(member);
  return key !== undefined && reads.has(key) && readonlyFieldValue(member, fields);
}

export default createRule<[], "excess">({
  name: "no-excess-jsx-props",
  documentation: NO_EXCESS_JSX_PROPS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_EXCESS_JSX_PROPS_DOCUMENTATION.summary },
    schema: [],
    messages: { excess: "This spread forwards fields outside the receiving component's declared contract: {{fields}}. Forward the needed fields explicitly or review the contract; an annotation alone does not remove runtime fields." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || !context.sourceCode.parserServices?.program || !context.sourceCode.parserServices.esTreeNodeToTSNodeMap) return {};
    let services: ParserServicesWithTypeInformation | undefined;
    let objectContract: boolean | undefined;
    const contracts = new WeakMap<ts.Type, boolean>();
    const receivers = new WeakMap<ts.Signature, ReadonlySet<string> | null>();
    const overrides = new WeakMap<ts.SourceFile, boolean>();
    let proof: PrimitiveProof | undefined;
    let dynamic = false;
    const candidates: { readonly node: TSESTree.JSXSpreadAttribute; readonly declaration: TSESTree.VariableDeclarator; readonly fields: ReadonlyMap<string, TSESTree.Property> }[] = [];
    let standardJSX: boolean | undefined;
    const evaluate = (node: TSESTree.JSXSpreadAttribute, declaration: TSESTree.VariableDeclarator, fields: ReadonlyMap<string, TSESTree.Property>): void => {
      const keys = [...fields.keys()];
      const opening = node.parent;
      services ??= ESLintUtils.getParserServices(context);
      standardJSX ??= supportedJSX(services.program.getCompilerOptions(), context.sourceCode.getAllComments());
      if (!standardJSX) return;
      const checker = services.program.getTypeChecker();
      if (objectContract === undefined) {
        const object = checker.resolveName("Object", undefined, ts.SymbolFlags.Type, false);
        objectContract = object !== undefined && closedObjectContract(checker.getDeclaredTypeOfSymbol(object), checker);
      }
      if (!objectContract) return;
      const contract = receivingContract(opening, services, checker, contracts);
      if (!contract) return;
      const excess = keys.filter((key) => checker.getPropertyOfType(contract.props, key) === undefined).sort();
      if (!excess.length || !stableReceiver(contract.tag, contract.signature, checker, services.program, overrides)) return;
      const signature = contract.signature;
      if (!receivers.has(signature)) receivers.set(signature, receiverReads(signature, checker));
      const reads = receivers.get(signature);
      proof ??= { checker, services, sourceCode: context.sourceCode, staticScope: !dynamic,
        exports: exportedSymbols(services.esTreeNodeToTSNodeMap.get(context.sourceCode.ast), checker), values: new WeakSet(), objects: new WeakMap(), invocations: new WeakMap() };
      if (!reads || !ownScalarReads(fields, reads, proof) || !closedElementValue(opening, declaration, fields, reads, proof)) return;
      const implementation = signature.getDeclaration();
      if (!implementation || ordinaryObjectEffects(services.program, contract.tag.getSourceFile()) || ordinaryObjectEffects(services.program, implementation.getSourceFile())) return;
      context.report({ node, messageId: "excess", data: { fields: excess.join(", ") } });
    };
    return {
      JSXSpreadAttribute(node): void {
        if (node.argument.type !== AST_NODE_TYPES.ObjectExpression) return;
        const opening = node.parent;
        if (!opening.selfClosing || opening.attributes.length !== 1 || opening.name.type !== AST_NODE_TYPES.JSXIdentifier || /^[a-z]/u.test(opening.name.name)) return;
        const declaration = privateElementDeclaration(opening);
        if (!declaration) return;
        const fields = literalFields(node.argument);
        if (!fields?.size) return;
        candidates.push({ node, declaration, fields });
      },
      CallExpression(node): void { if (directEval(node)) dynamic = true; },
      "Program:exit"(): void {
        if (!candidates.length) return;
        services = ESLintUtils.getParserServices(context);
        if (!currentNativeSource(context.sourceCode, services)) return;
        for (const {node, declaration, fields} of candidates) evaluate(node, declaration, fields);
      },
    };
  },
});

/**
 * @fileoverview no-excess-jsx-props — compare known runtime keys with a resolved component contract.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-excess-jsx-props.test.ts
 */
import { AST_NODE_TYPES, ESLintUtils, type ParserServicesWithTypeInformation, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { closedObjectContract } from "./_closed-object-contract.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { scalarParameterView, scalarType } from "./_scalar-parameter-view.js";

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
    "Requires parser-owned TypeScript information, a strict module implementation, a complete Object base, a self-closing identifier tag with one plain object-literal spread and no other attributes, and one nongeneric implemented synchronous arrow receiver with a resolved finite props surface. Sibling attributes or children could override the proven source values. Unknown, opaque, union, overloaded, generic, intrinsic and class receivers are excluded.",
    "Mapped types, index signatures, namespace/value-derived contracts, unresolved inherited or computed receiver keys, nonliteral computed source keys, nested spreads, accessors and explicit __proto__ keys are excluded. Source type properties alone do not prove enumerable own runtime keys. key, ref, React's __self/__source development metadata and TypeScript's hyphenated JSX attribute names are preserved.",
    "Native member lookup includes inherited, optional, readonly and implicit Object capabilities. The rule reports runtime keys outside the contract; it does not infer unused component fields, demand smaller public APIs, or erase producer type information.",
    "Requires a single returned view made from intrinsic JSX, literals and scalar parameter reads/operators. Free runtime values, helper calls, callbacks, object-valued consumed fields, custom tags, rest/spread, reflection and dynamic access prevent a finding; indirect element.props aliases cannot be inferred safe. Every inspected or destructured root field must be an own source-literal key; an omitted field could invoke an inherited getter. Bound/read source values must have concrete scalar types without undefined, Any or unknown after removing assertions; undefined can activate runtime defaults. Opaque HOC and declaration-file signatures are unsupported rather than assumed to ignore extra fields.",
    "The actual tag must resolve through immutable identifier aliases to a const arrow initializer. Constructible ordinary functions, mutable, member, proxy, call-produced and asserted receiver values are excluded even when their callable type resembles a known implementation; inherited runtime metadata can change ordinary function dispatch. Exactly one actual parameter and no explicit this parameter are supported.",
    "Requires target ES2015 or newer, explicit native ES-module output and the standard React automatic JSX runtime (react-jsx or react-jsxdev). Downlevel arrows become constructible functions; CommonJS exports remain mutable. Preserve/classic JSX, custom factories, namespaces, import sources and per-file JSX directives are unsupported. Imported library implementations and cross-project source redirects are opaque; relative imports within this program remain supported.",
  ],
  references: ["https://github.com/jsx-eslint/eslint-plugin-react/blob/master/docs/rules/jsx-props-no-spreading.md"],
  examples: [
    { id: "excess-runtime-field", title: "An unrelated field is forwarded at runtime", outcome: "match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; const Avatar = ({ displayName }: { displayName: string }) => <span>{displayName}</span>;\nconst avatar = <Avatar {...{ displayName: 'Ada', email: 'ada@example.test' }} />;" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 1, public: true },
    { id: "explicit-fields", title: "Forward only the declared field", outcome: "no-match", files: [EXAMPLE_JSX, { path: "src/avatar.tsx", source: "export {}; const Avatar = ({ displayName }: { displayName: string }) => <span>{displayName}</span>;\nconst avatar = <Avatar displayName='Ada' />;" }, EXAMPLE_TSCONFIG], focusPath: "src/avatar.tsx", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

const RESERVED_PROPS: ReadonlySet<string> = new Set(["key", "ref", "__self", "__source"]);
const ESM_MODULES: ReadonlySet<ts.ModuleKind> = new Set([ts.ModuleKind.ES2015, ts.ModuleKind.ES2020, ts.ModuleKind.ES2022, ts.ModuleKind.ESNext]);
const JSX_DIRECTIVE = /@jsx(?:ImportSource|Runtime|Frag)?(?:\s|$)/iu;
function literalFields(node: TSESTree.ObjectExpression): ReadonlyMap<string, TSESTree.Property> | null {
  const fields = new Map<string, TSESTree.Property>();
  for (const property of node.properties) {
    if (property.type !== AST_NODE_TYPES.Property || property.kind !== "init") return null;
    const key = property.key;
    let name: string;
    if (!property.computed && key.type === AST_NODE_TYPES.Identifier) name = key.name;
    else if (key.type === AST_NODE_TYPES.Literal && (typeof key.value === "string" || typeof key.value === "number")) name = String(key.value);
    else return null;
    if (name === "__proto__") return null;
    if (!RESERVED_PROPS.has(name) && !name.includes("-")) fields.set(name, property);
  }
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

function constInitializer(declaration: ts.Declaration | undefined): ts.Expression | undefined {
  if (!declaration || !ts.isVariableDeclaration(declaration) || !ts.isVariableDeclarationList(declaration.parent) || (declaration.parent.flags & ts.NodeFlags.Const) === 0) return undefined;
  let initializer = declaration.initializer;
  while (initializer && ts.isParenthesizedExpression(initializer)) initializer = initializer.expression;
  return initializer;
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

function ownScalarReads(fields: ReadonlyMap<string, TSESTree.Property>, reads: ReadonlySet<string>, services: ParserServicesWithTypeInformation, checker: ts.TypeChecker): boolean {
  for (const key of reads) {
    const field = fields.get(key);
    if (!field) return false;
    const value = unassertedValue(services.esTreeNodeToTSNodeMap.get(field.value));
    if (!scalarType(checker.getTypeAtLocation(value), false)) return false;
  }
  return true;
}

function unassertedValue(node: ts.Node): ts.Node {
  let value = node;
  while (ts.isParenthesizedExpression(value) || ts.isAsExpression(value) || ts.isTypeAssertionExpression(value) || ts.isNonNullExpression(value) || ts.isSatisfiesExpression(value)) value = value.expression;
  return value;
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
    let standardJSX: boolean | undefined;
    return {
      JSXSpreadAttribute(node): void {
        if (node.argument.type !== AST_NODE_TYPES.ObjectExpression) return;
        const fields = literalFields(node.argument);
        if (!fields?.size) return;
        const keys = [...fields.keys()];
        const opening = node.parent;
        if (!opening.selfClosing || opening.attributes.length !== 1 || opening.name.type !== AST_NODE_TYPES.JSXIdentifier || /^[a-z]/u.test(opening.name.name)) return;
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
        if (!reads || !ownScalarReads(fields, reads, services, checker)) return;
        context.report({ node, messageId: "excess", data: { fields: excess.join(", ") } });
      },
    };
  },
});

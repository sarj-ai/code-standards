/**
 * @fileoverview ordinary-object-effects — abstain on known or unresolved ordinary-Object prototype effects, over tsrs.
 *
 * Differences forced by tsrs, none observable in the result:
 * - files are identified by path; a file's AST is fetched only when it must be walked, so
 *   declaration files (whose facts never need their AST) are never transferred;
 * - symbols are compared by tsrs id, declarations by handle;
 * - `checker.resolveName` takes `(name, meaning, location, excludeGlobals)` in tsrs.
 * TypeScript 7 spells `import type` as `ImportClause.phaseModifier === TypeKeyword`.
 */

import type { Node, SourceFile } from "tsrs/ast";
import type { NodeHandle, Program, Symbol as TsSymbol } from "tsrs/sync";

import { checkedNativeSource, declarationNode, type NativeAst, type NativeTypes } from "./checked-native-source.js";
import { constInitializer, unassertedValue } from "./native-const-value.js";

type Identity = "unknown" | "fresh" | "object" | "reflect" | "prototype" | "globalThis" | "dynamic" | "incomplete";
/** A file by path; its AST is fetched on demand. */
type FileKey = string;
interface FileFacts { readonly unsafe: boolean; readonly imports: readonly FileKey[]; readonly jsx: boolean }
interface Analysis {
  readonly native: NativeTypes;
  readonly program: Program;
  readonly globals: ReadonlyMap<number, Identity>;
  readonly files: Map<FileKey, FileFacts>;
  readonly roots: Map<FileKey, boolean>;
  readonly importers: ReadonlyMap<FileKey, ReadonlySet<FileKey>>;
  readonly aliasValues: Set<FileKey>;
  readonly jsxRuntimes: Map<FileKey, boolean>;
  readonly sources: Map<FileKey, SourceFile | null>;
}
const ANALYSES = new WeakMap<Program, Analysis>();
const MAX_ALIAS_DEPTH = 64;
const MAX_SOURCE_GRAPH = 128;
const GLOBAL_IDENTITIES = [["Object", "object"], ["Reflect", "reflect"], ["globalThis", "globalThis"], ["eval", "dynamic"], ["Function", "dynamic"]] as const;
const OBJECT_REFLECTION: ReadonlySet<string> = new Set([
  "assign", "defineProperty", "defineProperties", "freeze", "seal", "preventExtensions", "setPrototypeOf",
  "getPrototypeOf", "getOwnPropertyDescriptor", "getOwnPropertyDescriptors",
]);
// TypeScript's isDeclarationFileName.
const DECLARATION_FILE = /\.d\.(?:[^./]+\.)?[cm]?ts$/u;

/** Sources are implementation files in one immutable parser-owned Program. */
export function ordinaryObjectEffects(native: NativeTypes, source: SourceFile): boolean {
  const program = native.program;
  let analysis = ANALYSES.get(program);
  if (!analysis) {
    analysis = programFacts(native);
    ANALYSES.set(program, analysis);
  }
  const root = source.path;
  analysis.sources.set(root, source);
  const known = analysis.roots.get(root);
  if (known !== undefined) return known;
  const visited = new Set<FileKey>();
  const queue: FileKey[] = [root];
  while (queue.length) {
    const current = queue.pop();
    if (current === undefined || visited.has(current)) continue;
    if (analysis.roots.get(current) || visited.size >= MAX_SOURCE_GRAPH) { analysis.roots.set(root, true); return true; }
    visited.add(current);
    const facts = fileFacts(current, analysis);
    if (facts.unsafe || (facts.jsx && !standardJSXRuntime(current, analysis)) ||
      (analysis.aliasValues.has(current) && !checkedSource(current, analysis))) { analysis.roots.set(root, true); return true; }
    queue.push(...facts.imports, ...(analysis.importers.get(current) ?? []));
  }
  // Every reachable local source was inspected, so each visited sub-root is also clean.
  for (const file of visited) analysis.roots.set(file, false);
  return false;
}

function sourceOf(key: FileKey, analysis: Analysis): SourceFile | null {
  let source = analysis.sources.get(key);
  if (source === undefined) {
    source = analysis.program.getSourceFileByPath(key as Parameters<Program["getSourceFileByPath"]>[0]) ?? null;
    analysis.sources.set(key, source);
  }
  return source;
}

function checkedSource(key: FileKey, analysis: Analysis): boolean {
  const source = sourceOf(key, analysis);
  return source !== null && checkedNativeSource(analysis.native, source);
}

/** A known importer can initialize another dependency before evaluating this module. */
function programFacts(native: NativeTypes): Analysis {
  const { checker, sync, program } = native;
  const globals = new Map<number, Identity>();
  for (const [name, identity] of GLOBAL_IDENTITIES) {
    const symbol = checker.resolveName(name, sync.SymbolFlags.Value, undefined, false);
    if (symbol) globals.set(symbol.id, identity);
  }
  const importers = new Map<FileKey, Set<FileKey>>();
  const analysis: Analysis = { native, program, globals, importers, aliasValues: new Set(), jsxRuntimes: new Map(), files: new Map(),
    roots: new Map(), sources: new Map() };
  for (const fileName of program.getSourceFileNames()) {
    // Declaration files have no imports in their facts, so only implementation files are fetched.
    if (DECLARATION_FILE.test(fileName)) continue;
    const source = program.getSourceFile(fileName);
    if (source === undefined) continue;
    analysis.sources.set(source.path, source);
    for (const dependency of fileFacts(source.path, analysis).imports) {
      let parents = importers.get(dependency);
      if (!parents) { parents = new Set(); importers.set(dependency, parents); }
      parents.add(source.path);
    }
  }
  return analysis;
}

function fileFacts(key: FileKey, analysis: Analysis): FileFacts {
  let facts = analysis.files.get(key);
  if (!facts) { facts = sourceFacts(key, analysis); analysis.files.set(key, facts); }
  return facts;
}

function sourceFacts(key: FileKey, analysis: Analysis): FileFacts {
  // Declaration files never execute. A value dependency on one remains opaque
  // in resolvedDependency; indexing its type-only AST adds no runtime evidence.
  if (DECLARATION_FILE.test(key)) return { unsafe: true, imports: [], jsx: false };
  const source = sourceOf(key, analysis);
  if (source === null || source.isDeclarationFile) return { unsafe: true, imports: [], jsx: false };
  const { ast } = analysis.native;
  const k = ast.SyntaxKind;
  const references: Node[] = [];
  const imports: FileKey[] = [];
  let unsafe = analysis.program.isSourceFileFromExternalLibrary(source);
  let jsx = false;
  const visit = (node: Node): undefined => {
    if (ast.isInterfaceDeclaration(node) || ast.isTypeAliasDeclaration(node) || ast.isTypeLiteralNode(node) || ast.isTypeQueryNode(node) ||
      ast.isTypeReferenceNode(node) || ast.isImportTypeNode(node) || ast.isTypeParameterDeclaration(node) ||
      (ast.isHeritageClause(node) && node.token === k.ImplementsKeyword)) return undefined;
    jsx ||= ast.isJsxElement(node) || ast.isJsxSelfClosingElement(node) || ast.isJsxFragment(node);
    // Keep collecting native module edges after an unsafe statement. Stopping here
    // would hide the very importer whose earlier dependency installs an effect.
    const dependency = moduleEffect(node, imports, analysis);
    if (dependency !== undefined) unsafe ||= dependency;
    // Binding/type names do not evaluate their imported values. The native
    // runtime edge above remains required, including verbatim empty imports.
    if (ast.isImportDeclaration(node) || (ast.isExportDeclaration(node) && (node.isTypeOnly || node.moduleSpecifier)) ||
      (ast.isExportSpecifier(node) && node.isTypeOnly)) return undefined;
    if (!unsafe) {
      if (ast.isIdentifier(node) || ast.isPropertyAccessExpression(node) || ast.isElementAccessExpression(node)) references.push(node);
      unsafe ||= runtimeEffect(node, analysis);
    }
    node.forEachChild(visit);
    return undefined;
  };
  visit(source);
  // All module edges are now collected; an already unsafe file needs no more
  // native identity queries. Checking value references replaces the alias-name
  // prepass and also covers ambient globals whose spelling is not known here.
  if (unsafe) return { unsafe, imports, jsx };
  for (const node of references) {
    // Reflective methods need a separate invocation/receiver proof.
    if (reflectiveMember(node, analysis)) unsafe = true;
    const value = identity(node, analysis);
    if (value === "incomplete" || value === "dynamic" || (protectedIdentity(value) && !containedUse(node, analysis))) unsafe = true;
    if (unsafe) break;
  }
  return { unsafe, imports, jsx };
}

function moduleEffect(node: Node, imports: FileKey[], analysis: Analysis): boolean | undefined {
  const { ast } = analysis.native;
  if (ast.isImportDeclaration(node) || ast.isExportDeclaration(node)) return !moduleDependency(node, imports, analysis);
  if (!ast.isCallExpression(node) || node.expression.kind !== ast.SyntaxKind.ImportKeyword) return undefined;
  const specifier = node.arguments[0];
  const resolved = specifier && ast.isStringLiteralLikeNode(specifier) && resolvedDependency(specifier, imports, analysis);
  return node.arguments.length !== 1 || !resolved;
}

/** Type signatures cannot prove invocation effects or the values of ambient bindings. */
function runtimeEffect(node: Node, analysis: Analysis): boolean {
  const { ast } = analysis.native;
  const k = ast.SyntaxKind;
  if (node.kind === k.ThisKeyword || node.kind === k.SuperKeyword || ast.isMetaProperty(node)) return true;
  if (ast.isVariableDeclaration(node)) return !node.initializer;
  if (ast.isFunctionDeclaration(node)) return !node.body;
  // Iteration invokes iterator/enumeration capabilities and may also write an
  // expression target. A fresh write target does not prove its input harmless.
  if (ast.isForOfStatement(node) || ast.isForInStatement(node) || ast.isNewExpression(node) || ast.isTaggedTemplateExpression(node)) return true;
  if (!ast.isCallExpression(node)) return mutationEffect(node, analysis);
  return node.expression.kind !== k.ImportKeyword;
}

/** Every explicit write shares the same native target-identity proof. */
function mutationEffect(node: Node, analysis: Analysis): boolean {
  const { ast } = analysis.native;
  const k = ast.SyntaxKind;
  if (ast.isBinaryExpression(node) && node.operatorToken.kind >= k.FirstAssignment && node.operatorToken.kind <= k.LastAssignment) {
    return unsafeTarget(node.left, analysis);
  }
  if (ast.isDeleteExpression(node)) return unsafeTarget(node.expression, analysis);
  return (ast.isPrefixUnaryExpression(node) || ast.isPostfixUnaryExpression(node)) &&
    (node.operator === k.PlusPlusToken || node.operator === k.MinusMinusToken) && unsafeTarget(node.operand, analysis);
}

function identity(node: Node, analysis: Analysis, active = new Set<Node>()): Identity {
  const { ast } = analysis.native;
  const value = unassertedValue(ast, node);
  if (active.has(value) || active.size >= MAX_ALIAS_DEPTH) return "incomplete";
  active.add(value);
  let result: Identity = "unknown";
  if (ast.isObjectLiteralExpression(value) || ast.isArrayLiteralExpression(value)) result = "fresh";
  else if (ast.isIdentifier(value)) result = identifierIdentity(value, analysis, active);
  else if (ast.isPropertyAccessExpression(value) || ast.isElementAccessExpression(value)) result = memberIdentity(value, analysis, active);
  active.delete(value);
  return result;
}

/** Alias bindings use native symbols; annotations cannot change runtime identity. */
function identifierIdentity(value: Node & { readonly text: string }, analysis: Analysis, active: Set<Node>): Identity {
  const { ast, checker, sync } = analysis.native;
  const parent = value.parent;
  if (nonValueName(value, analysis)) return "unknown";
  let symbol: TsSymbol | undefined = ast.isShorthandPropertyAssignment(parent) && parent.name === value
    ? checker.getShorthandAssignmentValueSymbol(parent) : checker.getSymbolAtLocation(value);
  const alias = symbol !== undefined && (symbol.flags & sync.SymbolFlags.Alias) !== 0;
  if (symbol && alias) symbol = checker.getAliasedSymbol(symbol);
  if (symbol && checker.isUnknownSymbol(symbol)) return "incomplete";
  // A shorthand needs its native value symbol, not its newly created property.
  // Missing or type-only runtime bindings cannot exclude a supplied getter.
  if (!symbol || (symbol.flags & sync.SymbolFlags.Value) === 0) {
    const erasedBinding = (ast.isModuleDeclaration(parent) && parent.name === value) ||
      (ast.isExportSpecifier(parent) && symbol !== undefined && (symbol.flags & (sync.SymbolFlags.Type | sync.SymbolFlags.Namespace)) !== 0);
    return erasedBinding ? "unknown" : "incomplete";
  }
  // A concrete alias target can still have an erased import/export binding.
  // Defer native source checking until this file is reached, not while indexing
  // every source's incoming runtime edges in programFacts.
  if (alias) analysis.aliasValues.add(value.getSourceFile().path);
  return runtimeBindingIdentity(value, symbol, alias, analysis, active);
}

/** Resolved value bindings retain namespace, global and initializer runtime identity. */
function runtimeBindingIdentity(value: Node, symbol: TsSymbol, alias: boolean, analysis: Analysis, active: Set<Node>): Identity {
  const { ast, sync } = analysis.native;
  const parent = value.parent;
  if (symbol.declarations.some((declaration) => declaration.kind === ast.SyntaxKind.ModuleDeclaration)) {
    // Declaration names do not read a value. Preserve the existing explicit
    // ambient-module veto; const-enum-only namespaces can erase without errors.
    return ast.isModuleDeclaration(parent) && parent.name === value &&
      (ast.getCombinedModifierFlags(parent) & ast.ModifierFlags.Ambient) === 0 ? "unknown" : "incomplete";
  }
  if ((symbol.flags & sync.SymbolFlags.Property) !== 0) return "unknown";
  // A const-enum symbol can survive checking while its runtime binding is erased.
  if ((symbol.flags & sync.SymbolFlags.ConstEnum) !== 0) return "incomplete";
  const global = analysis.globals.get(symbol.id);
  if (global !== undefined) return global;
  const handle: NodeHandle | undefined = symbol.valueDeclaration;
  // A Program's script/global declaration is not a runtime import. Its source
  // may never execute, and an ambient global can instead be supplied by a getter.
  if (handle && !alias && handle.path !== value.getSourceFile().path) return "incomplete";
  if (handle && DECLARATION_FILE.test(handle.path)) return "incomplete";
  const declaration = handle && declarationNode(analysis.native, handle);
  if (declaration && (declaration.getSourceFile().isDeclarationFile ||
    (ast.getCombinedModifierFlags(declaration as Parameters<typeof ast.getCombinedModifierFlags>[0]) & ast.ModifierFlags.Ambient) !== 0)) return "incomplete";
  const initializer = constInitializer(ast, declaration);
  return initializer ? identity(initializer, analysis, active) : "unknown";
}

/** These names are keys, labels or intrinsic strings, not evaluated bindings. */
function nonValueName(value: Node & { readonly text: string }, analysis: Analysis): boolean {
  const { ast } = analysis.native;
  const parent = value.parent;
  if ((ast.isPropertyAccessExpression(parent) || ast.isPropertyAssignment(parent) || ast.isJsxAttribute(parent) || ast.isEnumDeclaration(parent) ||
    ast.isEnumMember(parent)) && parent.name === value) return true;
  if (ast.isBindingElement(parent) && parent.propertyName === value) return true;
  if ((ast.isLabeledStatement(parent) || ast.isBreakStatement(parent) || ast.isContinueStatement(parent)) && parent.label === value) return true;
  if (ast.isJsxNamespacedName(parent)) return true;
  return (ast.isJsxOpeningElement(parent) || ast.isJsxSelfClosingElement(parent) || ast.isJsxClosingElement(parent)) &&
    parent.tagName === value && (/^[a-z]/u.test(value.text) || value.text.includes("-"));
}

function memberIdentity(value: Node, analysis: Analysis, active: Set<Node>): Identity {
  const { ast, checker, sync } = analysis.native;
  if (!ast.isPropertyAccessExpression(value) && !ast.isElementAccessExpression(value)) return "unknown";
  const base = identity(value.expression, analysis, active);
  if (base === "incomplete") return base;
  const key = memberKey(value, analysis);
  if (base === "object" && key === "prototype") return "prototype";
  if (base !== "globalThis" || key === undefined) return "unknown";
  // The proven runtime globalThis identity survives erased/Any annotations.
  const symbol = checker.resolveName(key, sync.SymbolFlags.Value, undefined, false);
  return symbol && analysis.globals.get(symbol.id) || "incomplete";
}

function memberKey(node: Node, analysis: Analysis): string | undefined {
  const { ast } = analysis.native;
  if (ast.isPropertyAccessExpression(node)) return ast.isIdentifier(node.name) || ast.isPrivateIdentifier(node.name) ? node.name.text : undefined;
  if (!ast.isElementAccessExpression(node)) return undefined;
  const key = node.argumentExpression && unassertedValue(ast, node.argumentExpression);
  return key && (ast.isStringLiteralLikeNode(key) || ast.isNumericLiteral(key)) ? key.text : undefined;
}

function protectedIdentity(value: Identity): boolean {
  return value === "object" || value === "reflect" || value === "prototype" || value === "globalThis" || value === "dynamic";
}

function containedUse(node: Node, analysis: Analysis): boolean {
  const { ast } = analysis.native;
  const value = expressionUse(node, analysis);
  const parent = value.parent;
  if (!parent) return false;
  if ((ast.isPropertyAccessExpression(parent) || ast.isElementAccessExpression(parent)) && parent.expression === value) {
    return memberKey(parent, analysis) !== undefined;
  }
  if (ast.isVariableDeclaration(parent) && parent.name === value) return true;
  if (ast.isVariableDeclaration(parent) && parent.initializer === value) {
    const statement = parent.parent.parent;
    return constInitializer(ast, parent) !== undefined && ast.isIdentifier(parent.name) &&
      (!ast.isVariableStatement(statement) || !statement.modifiers?.some((modifier) => modifier.kind === ast.SyntaxKind.ExportKeyword));
  }
  return false;
}

function expressionUse(node: Node, analysis: Analysis): Node {
  const { ast } = analysis.native;
  let value = node;
  while (value.parent && unassertedValue(ast, value.parent) === unassertedValue(ast, value)) value = value.parent;
  return value;
}

function unsafeTarget(node: Node, analysis: Analysis): boolean {
  const { ast } = analysis.native;
  const value = unassertedValue(ast, node);
  if (ast.isIdentifier(value)) return protectedIdentity(identity(value, analysis));
  if (ast.isPropertyAccessExpression(value) || ast.isElementAccessExpression(value)) return identity(value.expression, analysis) !== "fresh";
  // Destructuring member writes require another target/escape proof and remain unsupported.
  return true;
}

function reflectiveMember(node: Node, analysis: Analysis): boolean {
  const { ast } = analysis.native;
  if (!ast.isPropertyAccessExpression(node) && !ast.isElementAccessExpression(node)) return false;
  const base = identity(node.expression, analysis);
  const key = memberKey(node, analysis);
  return base === "reflect" || (base === "object" && (key === undefined || OBJECT_REFLECTION.has(key)));
}

function moduleDependency(node: Node, imports: FileKey[], analysis: Analysis): boolean {
  const { ast } = analysis.native;
  if (!ast.isImportDeclaration(node) && !ast.isExportDeclaration(node)) return true;
  const typeOnlyClause = ast.isImportDeclaration(node) && node.importClause?.phaseModifier === ast.SyntaxKind.TypeKeyword;
  if (typeOnlyClause || (ast.isExportDeclaration(node) && node.isTypeOnly)) return true;
  const clause = ast.isImportDeclaration(node) ? node.importClause?.namedBindings : node.exportClause;
  // Verbatim emit retains an empty import/export for per-specifier type names.
  const erasesNamedBindings = !analysis.program.getCompilerOptions().verbatimModuleSyntax;
  if (erasesNamedBindings && ast.isImportDeclaration(node) && clause && ast.isNamedImports(clause) && !node.importClause?.name &&
    clause.elements.length && clause.elements.every((item) => item.isTypeOnly)) return true;
  if (erasesNamedBindings && clause && ast.isNamedExports(clause) && clause.elements.length && clause.elements.every((item) => item.isTypeOnly)) return true;
  if (!node.moduleSpecifier) return true;
  return resolvedDependency(node.moduleSpecifier, imports, analysis);
}

function resolvedDependency(specifier: Node, imports: FileKey[], analysis: Analysis): boolean {
  const { ast, checker, program } = analysis.native;
  const declarations = checker.getSymbolAtLocation(specifier)?.declarations;
  if (!declarations?.length) return false;
  let resolved = true;
  for (const declaration of declarations) {
    if (declaration.kind !== ast.SyntaxKind.SourceFile) { resolved = false; continue; }
    imports.push(declaration.path);
    if (DECLARATION_FILE.test(declaration.path) || program.getSourceFileMetadataByPath(declaration.path)?.isFromExternalLibrary === true) resolved = false;
  }
  return resolved;
}

/** Defer implicit-runtime symbol queries to reached files containing actual JSX. */
function standardJSXRuntime(key: FileKey, analysis: Analysis): boolean {
  const known = analysis.jsxRuntimes.get(key);
  if (known !== undefined) return known;
  const source = sourceOf(key, analysis);
  const standard = source !== null && analysis.program.getSourceFile(source.fileName) === source && declaredJSXRuntime(source, analysis);
  analysis.jsxRuntimes.set(key, standard);
  return standard;
}

function declaredJSXRuntime(source: SourceFile, analysis: Analysis): boolean {
  const { sync, program } = analysis.native;
  const mode = program.getCompilerOptions().jsx;
  const name = mode === sync.JsxEmit.ReactJSX ? "react/jsx-runtime" : mode === sync.JsxEmit.ReactJSXDev ? "react/jsx-dev-runtime" : undefined;
  if (name === undefined || implicitJSXImport(source, analysis) !== name) return false;
  const declarations = implicitJSXModule(source, name, analysis)?.declarations;
  return declarations !== undefined && declarations.length > 0 &&
    declarations.every((declaration) => declaredReactRuntime(declaration, name, analysis));
}

/**
 * The module TypeScript 6 adds as the file's synthetic JSX import (`getJSXImplicitImportBase` and
 * `getJSXRuntimeImport` in its `collectExternalModuleReferences`). The original reads that import from
 * `source.imports`; tsrs leaves synthesized imports out of `imports`, so the name is rebuilt from the
 * same options and leading-comment pragmas.
 */
function implicitJSXImport(source: SourceFile, analysis: Analysis): string | undefined {
  const { ast, sync, program } = analysis.native;
  const options = program.getCompilerOptions();
  if (!(options.isolatedModules || ast.isExternalModule(source)) || source.isDeclarationFile) return undefined;
  const { importSource, runtime } = jsxPragmas(source, ast);
  if (runtime === "classic") return undefined;
  const configuredSource = options.jsxImportSource;
  const hasConfiguredSource = configuredSource !== undefined && configuredSource !== "";
  const automatic = options.jsx === sync.JsxEmit.ReactJSX || options.jsx === sync.JsxEmit.ReactJSXDev || hasConfiguredSource ||
    importSource !== undefined || runtime === "automatic";
  const defaultSource = hasConfiguredSource ? configuredSource : "react";
  const base = automatic ? importSource ?? defaultSource : undefined;
  return base === undefined ? undefined : `${base}/${options.jsx === sync.JsxEmit.ReactJSXDev ? "jsx-dev-runtime" : "jsx-runtime"}`;
}

/** The last `@jsxImportSource` and `@jsxRuntime` values in the file's leading block comments. */
function jsxPragmas(source: SourceFile, ast: NativeAst): { importSource: string | undefined; runtime: string | undefined } {
  let importSource: string | undefined;
  let runtime: string | undefined;
  for (const range of ast.getLeadingCommentRanges(source.text, 0) ?? []) {
    if (range.kind !== ast.SyntaxKind.MultiLineCommentTrivia) continue;
    for (const match of source.text.slice(range.pos, range.end).matchAll(/@(\S+)(\s+(?:\S.*)?)?$/gmu)) {
      const pragma = match[1]?.toLowerCase();
      const factory = match[2]?.trim().split(/\s+/u)[0];
      if (!factory) continue;
      if (pragma === "jsximportsource") importSource = factory;
      if (pragma === "jsxruntime") runtime = factory;
    }
  }
  return { importSource, runtime };
}

/** The symbol the checker gives that import: an ambient module first, as TypeScript resolves one, else the resolved file. */
function implicitJSXModule(source: SourceFile, name: string, analysis: Analysis): TsSymbol | undefined {
  const { checker, sync, program } = analysis.native;
  const ambient = checker.resolveName(`"${name}"`, sync.SymbolFlags.ValueModule, undefined, false);
  if (ambient) return ambient;
  const resolved = program.getResolvedModule(source.fileName, name, sync.ModuleKind.ESNext) ??
    program.getResolvedModule(source.fileName, name, sync.ModuleKind.CommonJS);
  return resolved?.resolvedFileName === undefined ? undefined : checker.getSymbolOfSourceFile(resolved.resolvedFileName);
}

/** Declaration providers retain the explicit standard-React assumption, not runtime identity proof. */
function declaredReactRuntime(handle: NodeHandle, name: string, analysis: Analysis): boolean {
  const { ast, program } = analysis.native;
  const declaration = declarationNode(analysis.native, handle);
  if (!declaration) return false;
  const source = declaration.getSourceFile();
  if (!source.isDeclarationFile || program.getSourceFile(source.fileName) !== source) return false;
  if (ast.isSourceFile(declaration)) return program.isSourceFileFromExternalLibrary(source);
  // Public examples use an owned .d.ts ambient module exposing the JSX namespace.
  // This is declaration-only evidence under the same opaque-library assumption.
  return ast.isModuleDeclaration(declaration) && declaration.parent === source && ast.isStringLiteral(declaration.name) && declaration.name.text === name;
}

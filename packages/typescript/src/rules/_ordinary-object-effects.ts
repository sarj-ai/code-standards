/** @fileoverview _ordinary-object-effects — abstain on known or unresolved ordinary-Object prototype effects. */
import ts from "typescript";

import { constInitializer, unassertedValue } from "./_native-const-value.js";
import { checkedNativeSource } from "./_checked-native-source.js";

type Identity = "unknown" | "fresh" | "object" | "reflect" | "prototype" | "globalThis" | "dynamic" | "incomplete";
interface FileFacts { readonly unsafe: boolean; readonly imports: readonly ts.SourceFile[]; readonly jsx: boolean }
interface Analysis {
  readonly program: ts.Program;
  readonly checker: ts.TypeChecker;
  readonly globals: ReadonlyMap<ts.Symbol, Identity>;
  readonly files: WeakMap<ts.SourceFile, FileFacts>;
  readonly roots: WeakMap<ts.SourceFile, boolean>;
  readonly importers: ReadonlyMap<ts.SourceFile, ReadonlySet<ts.SourceFile>>;
  readonly aliasValues: WeakSet<ts.SourceFile>;
  readonly jsxRuntimes: WeakMap<ts.SourceFile, boolean>;
}
const ANALYSES = new WeakMap<ts.Program, Analysis>();
const MAX_ALIAS_DEPTH = 64;
const MAX_SOURCE_GRAPH = 128;
const GLOBAL_IDENTITIES = [["Object", "object"], ["Reflect", "reflect"], ["globalThis", "globalThis"], ["eval", "dynamic"], ["Function", "dynamic"]] as const;
const OBJECT_REFLECTION: ReadonlySet<string> = new Set([
  "assign", "defineProperty", "defineProperties", "freeze", "seal", "preventExtensions", "setPrototypeOf",
  "getPrototypeOf", "getOwnPropertyDescriptor", "getOwnPropertyDescriptors",
]);

/** Sources are implementation files in one immutable parser-owned Program. */
export function ordinaryObjectEffects(program: ts.Program, source: ts.SourceFile): boolean {
  let analysis = ANALYSES.get(program);
  if (!analysis) {
    analysis = programFacts(program);
    ANALYSES.set(program, analysis);
  }
  const known = analysis.roots.get(source);
  if (known !== undefined) return known;
  const visited = new Set<ts.SourceFile>();
  const queue = [source];
  while (queue.length) {
    const current = queue.pop();
    if (!current || visited.has(current)) continue;
    if (analysis.roots.get(current) || visited.size >= MAX_SOURCE_GRAPH) { analysis.roots.set(source, true); return true; }
    visited.add(current);
    const facts = fileFacts(current, analysis);
    if (facts.unsafe || (facts.jsx && !standardJSXRuntime(current, analysis)) || (analysis.aliasValues.has(current) && !checkedNativeSource(program, current))) { analysis.roots.set(source, true); return true; }
    queue.push(...facts.imports, ...(analysis.importers.get(current) ?? []));
  }
  // Every reachable local source was inspected, so each visited sub-root is also clean.
  for (const file of visited) analysis.roots.set(file, false);
  return false;
}

/** A known importer can initialize another dependency before evaluating this module. */
function programFacts(program: ts.Program): Analysis {
  const checker = program.getTypeChecker();
  const globals = new Map<ts.Symbol, Identity>();
  for (const [name, identity] of GLOBAL_IDENTITIES) {
    const symbol = checker.resolveName(name, undefined, ts.SymbolFlags.Value, false);
    if (symbol) globals.set(symbol, identity);
  }
  const importers = new Map<ts.SourceFile, Set<ts.SourceFile>>();
  const analysis = { program, checker, globals, importers, aliasValues: new WeakSet<ts.SourceFile>(), jsxRuntimes: new WeakMap<ts.SourceFile, boolean>(), files: new WeakMap<ts.SourceFile, FileFacts>(), roots: new WeakMap<ts.SourceFile, boolean>() };
  for (const source of program.getSourceFiles()) {
    for (const dependency of fileFacts(source, analysis).imports) {
      let parents = importers.get(dependency);
      if (!parents) { parents = new Set(); importers.set(dependency, parents); }
      parents.add(source);
    }
  }
  return analysis;
}

function fileFacts(source: ts.SourceFile, analysis: Analysis): FileFacts {
  let facts = analysis.files.get(source);
  if (!facts) { facts = sourceFacts(source, analysis); analysis.files.set(source, facts); }
  return facts;
}

function sourceFacts(source: ts.SourceFile, analysis: Analysis): FileFacts {
  // Declaration files never execute. A value dependency on one remains opaque
  // in resolvedDependency; indexing its type-only AST adds no runtime evidence.
  if (source.isDeclarationFile) return { unsafe: true, imports: [], jsx: false };
  const references: ts.Node[] = [];
  const imports: ts.SourceFile[] = [];
  let unsafe = analysis.program.isSourceFileFromExternalLibrary(source);
  let jsx = false;
  const visit = (node: ts.Node): void => {
    if (ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) || ts.isTypeLiteralNode(node) || ts.isTypeQueryNode(node) || ts.isTypeReferenceNode(node) || ts.isImportTypeNode(node) || ts.isTypeParameterDeclaration(node) ||
      (ts.isHeritageClause(node) && node.token === ts.SyntaxKind.ImplementsKeyword)) return;
    jsx ||= ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node) || ts.isJsxFragment(node);
    // Keep collecting native module edges after an unsafe statement. Stopping here
    // would hide the very importer whose earlier dependency installs an effect.
    const dependency = moduleEffect(node, imports, analysis);
    if (dependency !== undefined) unsafe ||= dependency;
    // Binding/type names do not evaluate their imported values. The native
    // runtime edge above remains required, including verbatim empty imports.
    if (ts.isImportDeclaration(node) || (ts.isExportDeclaration(node) && (node.isTypeOnly || node.moduleSpecifier)) || (ts.isExportSpecifier(node) && node.isTypeOnly)) return;
    if (!unsafe) {
      if (ts.isIdentifier(node) || ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) references.push(node);
      unsafe ||= runtimeEffect(node, analysis);
    }
    ts.forEachChild(node, visit);
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
    if (value === "incomplete" || value === "dynamic" || (protectedIdentity(value) && !containedUse(node))) unsafe = true;
    if (unsafe) break;
  }
  return { unsafe, imports, jsx };
}

function moduleEffect(node: ts.Node, imports: ts.SourceFile[], analysis: Analysis): boolean | undefined {
  if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return !moduleDependency(node, imports, analysis);
  if (!ts.isCallExpression(node) || node.expression.kind !== ts.SyntaxKind.ImportKeyword) return undefined;
  const specifier = node.arguments[0];
  const resolved = specifier && ts.isStringLiteralLike(specifier) && resolvedDependency(specifier, imports, analysis);
  return node.arguments.length !== 1 || !resolved;
}

/** Type signatures cannot prove invocation effects or the values of ambient bindings. */
function runtimeEffect(node: ts.Node, analysis: Analysis): boolean {
  if (node.kind === ts.SyntaxKind.ThisKeyword || node.kind === ts.SyntaxKind.SuperKeyword || ts.isMetaProperty(node)) return true;
  if (ts.isVariableDeclaration(node)) return !node.initializer;
  if (ts.isFunctionDeclaration(node)) return !node.body;
  // Iteration invokes iterator/enumeration capabilities and may also write an
  // expression target. A fresh write target does not prove its input harmless.
  if (ts.isForOfStatement(node) || ts.isForInStatement(node) || ts.isNewExpression(node) || ts.isTaggedTemplateExpression(node)) return true;
  if (!ts.isCallExpression(node)) return mutationEffect(node, analysis);
  return node.expression.kind !== ts.SyntaxKind.ImportKeyword;
}

/** Every explicit write shares the same native target-identity proof. */
function mutationEffect(node: ts.Node, analysis: Analysis): boolean {
  if (ts.isBinaryExpression(node) && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && node.operatorToken.kind <= ts.SyntaxKind.LastAssignment) return unsafeTarget(node.left, analysis);
  if (ts.isDeleteExpression(node)) return unsafeTarget(node.expression, analysis);
  return (ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) &&
    (node.operator === ts.SyntaxKind.PlusPlusToken || node.operator === ts.SyntaxKind.MinusMinusToken) && unsafeTarget(node.operand, analysis);
}

function identity(node: ts.Node, analysis: Analysis, active = new Set<ts.Node>()): Identity {
  const value = unassertedValue(node);
  if (active.has(value) || active.size >= MAX_ALIAS_DEPTH) return "incomplete";
  active.add(value);
  let result: Identity = "unknown";
  if (ts.isObjectLiteralExpression(value) || ts.isArrayLiteralExpression(value)) result = "fresh";
  else if (ts.isIdentifier(value)) result = identifierIdentity(value, analysis, active);
  else if (ts.isPropertyAccessExpression(value) || ts.isElementAccessExpression(value)) result = memberIdentity(value, analysis, active);
  active.delete(value);
  return result;
}

/** Alias bindings use native symbols; annotations cannot change runtime identity. */
function identifierIdentity(value: ts.Identifier, analysis: Analysis, active: Set<ts.Node>): Identity {
  const parent = value.parent;
  if (nonValueName(value)) return "unknown";
  let symbol = ts.isShorthandPropertyAssignment(parent) && parent.name === value ?
    analysis.checker.getShorthandAssignmentValueSymbol(parent) : analysis.checker.getSymbolAtLocation(value);
  const alias = symbol !== undefined && (symbol.flags & ts.SymbolFlags.Alias) !== 0;
  if (symbol && alias) symbol = analysis.checker.getAliasedSymbol(symbol);
  if (symbol && analysis.checker.isUnknownSymbol(symbol)) return "incomplete";
  // A shorthand needs its native value symbol, not its newly created property.
  // Missing or type-only runtime bindings cannot exclude a supplied getter.
  if (!symbol || (symbol.flags & ts.SymbolFlags.Value) === 0) {
    const erasedBinding = (ts.isModuleDeclaration(parent) && parent.name === value) ||
      (ts.isExportSpecifier(parent) && symbol !== undefined && (symbol.flags & (ts.SymbolFlags.Type | ts.SymbolFlags.Namespace)) !== 0);
    return erasedBinding ? "unknown" : "incomplete";
  }
  // A concrete alias target can still have an erased import/export binding.
  // Defer native source checking until this file is reached, not while indexing
  // every source's incoming runtime edges in programFacts.
  if (alias) analysis.aliasValues.add(value.getSourceFile());
  return runtimeBindingIdentity(value, symbol, alias, analysis, active);
}

/** Resolved value bindings retain namespace, global and initializer runtime identity. */
function runtimeBindingIdentity(value: ts.Identifier, symbol: ts.Symbol, alias: boolean, analysis: Analysis, active: Set<ts.Node>): Identity {
  const parent = value.parent;
  if (symbol.declarations?.some(ts.isModuleDeclaration)) {
    // Declaration names do not read a value. Preserve the existing explicit
    // ambient-module veto; const-enum-only namespaces can erase without errors.
    return ts.isModuleDeclaration(parent) && parent.name === value &&
      (ts.getCombinedModifierFlags(parent) & ts.ModifierFlags.Ambient) === 0 ? "unknown" : "incomplete";
  }
  if ((symbol.flags & ts.SymbolFlags.Property) !== 0) return "unknown";
  // A const-enum symbol can survive checking while its runtime binding is erased.
  if ((symbol.flags & ts.SymbolFlags.ConstEnum) !== 0) return "incomplete";
  const global = analysis.globals.get(symbol);
  if (global !== undefined) return global;
  const declaration = symbol.valueDeclaration;
  // A Program's script/global declaration is not a runtime import. Its source
  // may never execute, and an ambient global can instead be supplied by a getter.
  if (declaration && !alias && declaration.getSourceFile() !== value.getSourceFile()) return "incomplete";
  if (declaration && (declaration.getSourceFile().isDeclarationFile || (ts.getCombinedModifierFlags(declaration) & ts.ModifierFlags.Ambient) !== 0)) return "incomplete";
  const initializer = constInitializer(declaration);
  return initializer ? identity(initializer, analysis, active) : "unknown";
}

/** These names are keys, labels or intrinsic strings, not evaluated bindings. */
function nonValueName(value: ts.Identifier): boolean {
  const parent = value.parent;
  if ((ts.isPropertyAccessExpression(parent) || ts.isPropertyAssignment(parent) || ts.isJsxAttribute(parent) || ts.isEnumDeclaration(parent) || ts.isEnumMember(parent)) && parent.name === value) return true;
  if (ts.isBindingElement(parent) && parent.propertyName === value) return true;
  if ((ts.isLabeledStatement(parent) || ts.isBreakStatement(parent) || ts.isContinueStatement(parent)) && parent.label === value) return true;
  if (ts.isJsxNamespacedName(parent)) return true;
  return (ts.isJsxOpeningElement(parent) || ts.isJsxSelfClosingElement(parent) || ts.isJsxClosingElement(parent)) &&
    parent.tagName === value && (/^[a-z]/u.test(value.text) || value.text.includes("-"));
}

function memberIdentity(value: ts.PropertyAccessExpression | ts.ElementAccessExpression, analysis: Analysis, active: Set<ts.Node>): Identity {
  const base = identity(value.expression, analysis, active);
  if (base === "incomplete") return base;
  const key = memberKey(value);
  if (base === "object" && key === "prototype") return "prototype";
  if (base !== "globalThis" || key === undefined) return "unknown";
  // The proven runtime globalThis identity survives erased/Any annotations.
  const symbol = analysis.checker.resolveName(key, undefined, ts.SymbolFlags.Value, false);
  return symbol && analysis.globals.get(symbol) || "incomplete";
}

function memberKey(node: ts.PropertyAccessExpression | ts.ElementAccessExpression): string | undefined {
  if (ts.isPropertyAccessExpression(node)) return node.name.text;
  const key = node.argumentExpression && unassertedValue(node.argumentExpression);
  return key && (ts.isStringLiteralLike(key) || ts.isNumericLiteral(key)) ? key.text : undefined;
}

function protectedIdentity(value: Identity): boolean {
  return value === "object" || value === "reflect" || value === "prototype" || value === "globalThis" || value === "dynamic";
}

function containedUse(node: ts.Node): boolean {
  const value = expressionUse(node);
  const parent = value.parent;
  if (!parent) return false;
  if ((ts.isPropertyAccessExpression(parent) || ts.isElementAccessExpression(parent)) && parent.expression === value) return memberKey(parent) !== undefined;
  if (ts.isVariableDeclaration(parent) && parent.name === value) return true;
  if (ts.isVariableDeclaration(parent) && parent.initializer === value) {
    const statement = parent.parent.parent;
    return constInitializer(parent) !== undefined && ts.isIdentifier(parent.name) &&
      (!ts.isVariableStatement(statement) || !statement.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword));
  }
  return false;
}

function expressionUse(node: ts.Node): ts.Node {
  let value = node;
  while (value.parent && unassertedValue(value.parent) === unassertedValue(value)) value = value.parent;
  return value;
}

function unsafeTarget(node: ts.Node, analysis: Analysis): boolean {
  const value = unassertedValue(node);
  if (ts.isIdentifier(value)) return protectedIdentity(identity(value, analysis));
  if (ts.isPropertyAccessExpression(value) || ts.isElementAccessExpression(value)) return identity(value.expression, analysis) !== "fresh";
  // Destructuring member writes require another target/escape proof and remain unsupported.
  return true;
}

function reflectiveMember(node: ts.Node, analysis: Analysis): boolean {
  if (!ts.isPropertyAccessExpression(node) && !ts.isElementAccessExpression(node)) return false;
  const base = identity(node.expression, analysis);
  const key = memberKey(node);
  return base === "reflect" || (base === "object" && (key === undefined || OBJECT_REFLECTION.has(key)));
}

function moduleDependency(node: ts.ImportDeclaration | ts.ExportDeclaration, imports: ts.SourceFile[], analysis: Analysis): boolean {
  if ((ts.isImportDeclaration(node) && node.importClause?.isTypeOnly) || (ts.isExportDeclaration(node) && node.isTypeOnly)) return true;
  const clause = ts.isImportDeclaration(node) ? node.importClause?.namedBindings : node.exportClause;
  // Verbatim emit retains an empty import/export for per-specifier type names.
  const erasesNamedBindings = !analysis.program.getCompilerOptions().verbatimModuleSyntax;
  if (erasesNamedBindings && ts.isImportDeclaration(node) && clause && ts.isNamedImports(clause) && !node.importClause?.name && clause.elements.length && clause.elements.every((item) => item.isTypeOnly)) return true;
  if (erasesNamedBindings && clause && ts.isNamedExports(clause) && clause.elements.length && clause.elements.every((item) => item.isTypeOnly)) return true;
  if (!node.moduleSpecifier) return true;
  return resolvedDependency(node.moduleSpecifier, imports, analysis);
}

function resolvedDependency(specifier: ts.Expression, imports: ts.SourceFile[], analysis: Analysis): boolean {
  const symbol = analysis.checker.getSymbolAtLocation(specifier);
  const declarations = symbol?.declarations;
  if (!declarations?.length) return false;
  let resolved = true;
  for (const declaration of declarations) {
    if (!ts.isSourceFile(declaration)) { resolved = false; continue; }
    imports.push(declaration);
    if (declaration.isDeclarationFile || analysis.program.isSourceFileFromExternalLibrary(declaration)) resolved = false;
  }
  return resolved;
}

/** Defer implicit-runtime symbol queries to reached files containing actual JSX. */
function standardJSXRuntime(source: ts.SourceFile, analysis: Analysis): boolean {
  const known = analysis.jsxRuntimes.get(source);
  if (known !== undefined) return known;
  const standard = analysis.program.getSourceFile(source.fileName) === source && declaredJSXRuntime(source, analysis);
  analysis.jsxRuntimes.set(source, standard);
  return standard;
}

function declaredJSXRuntime(source: ts.SourceFile, analysis: Analysis): boolean {
  const mode = analysis.program.getCompilerOptions().jsx;
  const name = mode === ts.JsxEmit.ReactJSX ? "react/jsx-runtime" : mode === ts.JsxEmit.ReactJSXDev ? "react/jsx-dev-runtime" : undefined;
  if (name === undefined) return false;
  const specifier = implicitJSXImport(source, name);
  const declarations = specifier && analysis.checker.getSymbolAtLocation(specifier)?.declarations;
  return declarations !== undefined && declarations.length > 0 &&
    declarations.every((declaration) => declaredReactRuntime(declaration, name, analysis.program));
}

/** Optional compiler-owned metadata; missing or ambiguous evidence must abstain. */
function implicitJSXImport(source: ts.SourceFile, name: string): ts.StringLiteral | undefined {
  const imports = (source as ts.SourceFile & {readonly imports?: readonly ts.Node[]}).imports;
  if (!Array.isArray(imports)) return undefined;
  let selected: ts.StringLiteral | undefined;
  for (const node of imports as readonly (ts.Node | undefined)[]) {
    if (!node || !ts.isStringLiteral(node) || node.text !== name || !node.parent || !ts.isImportDeclaration(node.parent) ||
      node.parent.moduleSpecifier !== node || node.parent.parent !== source || source.statements.includes(node.parent) || node.getSourceFile() !== source) continue;
    if (selected) return undefined;
    selected = node;
  }
  return selected;
}

/** Declaration providers retain the explicit standard-React assumption, not runtime identity proof. */
function declaredReactRuntime(declaration: ts.Declaration, name: string, program: ts.Program): boolean {
  const source = declaration.getSourceFile();
  if (!source.isDeclarationFile || program.getSourceFile(source.fileName) !== source) return false;
  if (ts.isSourceFile(declaration)) return program.isSourceFileFromExternalLibrary(source);
  // Public examples use an owned .d.ts ambient module exposing the JSX namespace.
  // This is declaration-only evidence under the same opaque-library assumption.
  return ts.isModuleDeclaration(declaration) && declaration.parent === source && ts.isStringLiteral(declaration.name) && declaration.name.text === name;
}

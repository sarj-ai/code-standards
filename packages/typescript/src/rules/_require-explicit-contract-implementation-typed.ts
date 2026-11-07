/**
 * @fileoverview _require-explicit-contract-implementation-typed — the original's typed proof, on tsrs.
 *
 * The original reads the TypeScript AST and checker of the whole program.
 * tsrs serves the same TypeScript 7 nodes (same property names, TypeScript 7
 * `SyntaxKind` numbering) and checker, so this is the original's logic with
 * `ts.is*` taken from `tsrs/ast`, and these changes:
 *
 * - tsrs builds a new remote node object per lookup, so nodes compare by file,
 *   kind and range (`same`), and symbols by id;
 * - `ts.getDecorators`/`ts.getModifiers` split `node.modifiers` by kind, as
 *   TypeScript does;
 * - a declaration's source file comes from its handle's path
 *   (`getSourceFileByPath`) or from its parent chain;
 * - `escapedClasses`, the original's walk of every owned file in the program,
 *   resolves each file's identifiers, member accesses and aliases in batched
 *   requests instead of one checker call per node. It runs only when a
 *   candidate reaches `closedNominalBoundary`, cached per program, as in the
 *   original.
 */

import { isGeneratedFile, scopedFilename } from "../utils/paths.js";
import { nullTolerantAst, type TsrsFile, type TsrsNode, type TsrsNodeHandle, type TsrsRequest, type TsrsType } from "../utils/tsrs-services.js";

/** A tsrs remote node: TypeScript's node shape, every child optional. */
export interface RemoteNode extends TsrsNode {
  readonly parent?: RemoteNode | undefined;
  readonly [field: string]: unknown;
}
export interface RemoteSourceFile extends RemoteNode {
  readonly fileName: string;
  readonly text: string;
  readonly isDeclarationFile?: boolean;
  readonly statements: readonly RemoteNode[];
}
type Field = RemoteNode | undefined;
type List = readonly RemoteNode[] | undefined;
interface Handle extends TsrsNodeHandle {
  readonly kind: number;
  resolve(): RemoteNode | undefined;
}
export interface Symbol {
  readonly id: number;
  readonly name: string;
  readonly flags: number;
  readonly declarations: readonly Handle[];
}
interface Signature {
  readonly declaration?: Handle | undefined;
  getParameters(): readonly Symbol[];
}
interface Type extends Omit<TsrsType, "getTypes"> {
  getTypes(): readonly Type[];
  getSymbol: (() => Symbol | undefined) & { gen(): TsrsRequest<Symbol | undefined> };
  getCallSignatures(): readonly Signature[];
}
interface Checker {
  getSymbolAtLocation: ((nodes: readonly TsrsNode[]) => (Symbol | undefined)[]) & ((node: TsrsNode) => Symbol | undefined);
  readonly getAliasedSymbol: ((symbol: Symbol) => Symbol) & { gen(symbol: Symbol): TsrsRequest<Symbol> };
  getTypeAtLocation: ((nodes: readonly TsrsNode[]) => Type[]) & ((node: TsrsNode) => Type);
  getResolvedSignature(node: TsrsNode): Signature | undefined;
  getTypeOfSymbolAtLocation(symbol: Symbol, location: TsrsNode): Type;
  getPropertiesOfType(type: Type): readonly Symbol[];
  isTypeAssignableTo(source: Type, target: Type): boolean;
  getExportsOfModule(symbol: Symbol): readonly Symbol[];
}
interface Program {
  getSourceFileNames(): readonly string[];
  readonly getSourceFile: { gen(file: string): TsrsRequest<RemoteSourceFile | undefined> };
  getSourceFileByPath(path: string): RemoteSourceFile | undefined;
}

type Is = (node: RemoteNode | undefined) => boolean;
export interface Ast {
  readonly SyntaxKind: Readonly<Record<string, number>>;
  readonly isTypeNode: Is;
  readonly isImportDeclaration: Is;
  readonly isIdentifier: Is;
  readonly isPropertyAccessExpression: Is;
  readonly isElementAccessExpression: Is;
  readonly isParenthesizedExpression: Is;
  readonly isClassDeclaration: Is;
  readonly isNewExpression: Is;
  readonly isExpressionWithTypeArguments: Is;
  readonly isBinaryExpression: Is;
  readonly isCallExpression: Is;
  readonly isConstructorDeclaration: Is;
  readonly isIfStatement: Is;
  readonly isPrefixUnaryExpression: Is;
  readonly isThrowStatement: Is;
  readonly isBlock: Is;
  readonly isClassStaticBlockDeclaration: Is;
  readonly isPropertyDeclaration: Is;
  readonly isComputedPropertyName: Is;
}

/** The root of a remote node's parent chain: its source file. */
export function sourceOf(node: RemoteNode): RemoteSourceFile {
  let current = node;
  while (current.parent !== undefined) current = current.parent;
  return current as RemoteSourceFile;
}

/** Node identity across tsrs lookups. */
export function same(left: RemoteNode | undefined, right: RemoteNode | undefined): boolean {
  return left !== undefined && right !== undefined && left.kind === right.kind && left.pos === right.pos && left.end === right.end &&
    sourceOf(left).fileName === sourceOf(right).fileName;
}

// Per program: prototype mutation by file name, escaped class symbol ids by cwd.
const PROTOTYPE_MUTATIONS = new WeakMap<object, Map<string, boolean>>();
const ESCAPED_CLASSES = new WeakMap<object, Map<string, ReadonlySet<number>>>();

const OWNED_PATH_RE = /(?:^|[/\\])(?:node_modules|vendor|vendored|generated|dist)(?:[/\\])/u;
const DECLARATION_FILE_RE = /\.d\.(?:[cm]?ts|[^/.]+\.ts)$/;

export interface MissingImplementation {
  readonly implementation: RemoteNode;
  readonly contractSymbol: Symbol;
}

export interface Finding {
  readonly argument: number;
  readonly implementation: string;
  readonly contract: string;
  readonly fix: { readonly call: RemoteNode; readonly consumer: RemoteNode; readonly implementation: RemoteNode; readonly contract: RemoteNode } | null;
}

/** The original's `inspect`, for one `new` expression, without the report. */
export function contractFindings(file: TsrsFile, cwd: string, call: RemoteNode, argumentIndexes: readonly number[]): Finding[] {
  const a = nullTolerantAst<Ast>(file);
  const k = a.SyntaxKind;
  const flags = file.flags;
  const flagsOfSymbol = file.sync.SymbolFlags;
  const checker = file.checker as unknown as Checker;
  const program = file.program as unknown as Program;
  const sourceFiles = new Map<string, RemoteSourceFile | undefined>();

  function sourceByPath(path: string): RemoteSourceFile | undefined {
    if (!sourceFiles.has(path)) sourceFiles.set(path, program.getSourceFileByPath(path));
    return sourceFiles.get(path);
  }
  const decorators = (node: RemoteNode): RemoteNode[] => (node["modifiers"] as List ?? []).filter((item) => item.kind === k["Decorator"]);
  const modifiersOf = (node: RemoteNode): RemoteNode[] => (node["modifiers"] as List ?? []).filter((item) => item.kind !== k["Decorator"]);
  const text = (node: Field): string | undefined => node?.["text"] as string | undefined;

  function classDeclaration(symbol: Symbol | undefined): RemoteNode | undefined {
    return symbol?.declarations.find((handle) => handle.kind === k["ClassDeclaration"])?.resolve();
  }

  function unparenthesized(expression: RemoteNode): RemoteNode {
    let current = expression;
    while (a.isParenthesizedExpression(current)) current = current["expression"] as RemoteNode;
    return current;
  }

  function canonicalSymbol(node: RemoteNode): Symbol | undefined {
    if (a.isParenthesizedExpression(node)) node = unparenthesized(node);
    const symbol = checker.getSymbolAtLocation(node);
    return symbol === undefined ? undefined : (symbol.flags & flagsOfSymbol.Alias) !== 0 ? checker.getAliasedSymbol(symbol) : symbol;
  }

  function memberName(node: RemoteNode): string | null {
    if (a.isPropertyAccessExpression(node)) return text(node["name"] as Field) ?? null;
    const argument = node["argumentExpression"] as Field;
    if (a.isElementAccessExpression(node) && (argument?.kind === k["StringLiteral"] || argument?.kind === k["NoSubstitutionTemplateLiteral"])) {
      return text(argument) ?? null;
    }
    return null;
  }

  function hasPrototypeMutation(source: RemoteSourceFile): boolean {
    let cache = PROTOTYPE_MUTATIONS.get(program);
    if (cache === undefined) PROTOTYPE_MUTATIONS.set(program, cache = new Map<string, boolean>());
    const cached = cache.get(source.fileName);
    if (cached !== undefined) return cached;
    function visit(node: RemoteNode): true | undefined {
      const member = memberName(node);
      if (member === "setPrototypeOf" || member === "__proto__" || member === "hasInstance") return true;
      const operator = (node["operatorToken"] as Field)?.kind;
      if (a.isBinaryExpression(node) && operator !== undefined && operator >= k["FirstAssignment"]! && operator <= k["LastAssignment"]! &&
        memberName(node["left"] as RemoteNode) === "prototype") return true;
      return node.forEachChild((child) => visit(child as RemoteNode));
    }
    const mutated = visit(source) === true;
    cache.set(source.fileName, mutated);
    return mutated;
  }

  function ownedSource(source: RemoteSourceFile | undefined): boolean {
    if (source === undefined) return false;
    const path = { filename: source.fileName, cwd };
    return source.isDeclarationFile !== true && !OWNED_PATH_RE.test(scopedFilename(path)) && !isGeneratedFile(path, source.text);
  }

  const ownedValues = new Map<number, ReadonlySet<number>>();
  function ownedClassValues(original: Symbol, seen = new Set<number>()): ReadonlySet<number> {
    const top = seen.size === 0;
    if (top) {
      const cached = ownedValues.get(original.id);
      if (cached !== undefined) return cached;
    }
    const symbol = (original.flags & flagsOfSymbol.Alias) !== 0 ? checker.getAliasedSymbol(original) : original;
    const values = new Set<number>();
    if (!seen.has(symbol.id)) {
      seen.add(symbol.id);
      if (symbol.declarations.some((handle) => handle.kind === k["ClassDeclaration"] && ownedSource(sourceByPath(handle.path)))) values.add(symbol.id);
      if (symbol.declarations.some((handle) => (handle.kind === k["SourceFile"] || handle.kind === k["ModuleDeclaration"]) &&
        ownedSource(sourceByPath(handle.path)))) {
        for (const exported of checker.getExportsOfModule(symbol)) {
          for (const value of ownedClassValues(exported, seen)) values.add(value);
        }
      }
    }
    if (top) ownedValues.set(original.id, values);
    return values;
  }

  function safeClassReference(node: RemoteNode): boolean {
    let reference: RemoteNode = a.isPropertyAccessExpression(node.parent) && same(node.parent!["name"] as Field, node) ? node.parent! : node;
    while (a.isParenthesizedExpression(reference.parent)) reference = reference.parent!;
    const parent = reference.parent;
    return (a.isClassDeclaration(parent) && same(parent!["name"] as Field, reference)) ||
      (a.isNewExpression(parent) && same(parent!["expression"] as Field, reference)) ||
      (a.isExpressionWithTypeArguments(parent) && same(parent!["expression"] as Field, reference)) ||
      (a.isBinaryExpression(parent) && (parent!["operatorToken"] as Field)?.kind === k["InstanceOfKeyword"] &&
        same(parent!["right"] as Field, reference));
  }

  function namespacePrefix(symbol: Symbol, node: RemoteNode): boolean {
    const parent = node.parent;
    const access = a.isPropertyAccessExpression(parent) || a.isElementAccessExpression(parent);
    const memberCall = access && a.isCallExpression(parent!.parent) && same(parent!.parent!["expression"] as Field, parent);
    return !symbol.declarations.some((handle) => handle.kind === k["ClassDeclaration"]) && access &&
      same(parent!["expression"] as Field, node) && !memberCall;
  }

  function closedNominalBoundary(consumer: RemoteNode, missing: MissingImplementation): boolean {
    const { implementation, contractSymbol } = missing;
    const implementationName = implementation["name"] as Field;
    const consumerName = consumer["name"] as Field;
    const implementationSymbol = implementationName === undefined ? undefined : canonicalSymbol(implementationName);
    const consumerSymbol = consumerName === undefined ? undefined : canonicalSymbol(consumerName);
    if (implementationSymbol === undefined || consumerSymbol === undefined) return false;
    const contract = classDeclaration(contractSymbol);
    if (contract === undefined) return false;
    const targets = new Set([consumerSymbol.id, ...classHierarchySymbols(contract), ...classHierarchySymbols(implementation)]);
    const sources = new Map<string, RemoteSourceFile | undefined>();
    for (const source of [sourceOf(call), sourceOf(consumer), sourceOf(implementation)]) sources.set(source.fileName, source);
    for (const handle of contractSymbol.declarations) {
      const source = sourceByPath(handle.path);
      sources.set(source?.fileName ?? handle.path, source);
    }
    if ([...sources.values()].some((source) => source !== undefined && hasPrototypeMutation(source))) return false;
    const escaped = escapedClasses();
    return ![...targets].some((target) => escaped.has(target));
  }

  function classHierarchySymbols(declaration: RemoteNode, seen = new Set<number>()): Set<number> {
    const name = declaration["name"] as Field;
    const symbol = name === undefined ? undefined : canonicalSymbol(name);
    if (symbol === undefined || seen.has(symbol.id)) return seen;
    seen.add(symbol.id);
    for (const clause of declaration["heritageClauses"] as List ?? []) {
      if (clause["token"] !== k["ExtendsKeyword"]) continue;
      for (const parent of clause["types"] as List ?? []) {
        const ancestor = classDeclaration(canonicalSymbol(parent["expression"] as RemoteNode));
        if (ancestor !== undefined) classHierarchySymbols(ancestor, seen);
      }
    }
    return seen;
  }

  /** The original's whole-program walk, one batched symbol request per owned file. */
  function escapedClasses(): ReadonlySet<number> {
    let scopes = ESCAPED_CLASSES.get(program);
    if (scopes === undefined) ESCAPED_CLASSES.set(program, scopes = new Map<string, ReadonlySet<number>>());
    const cached = scopes.get(cwd);
    if (cached !== undefined) return cached;
    const escaped = new Set<number>();
    const namespaceValues = new Map<number, ReadonlySet<number>>();
    // A declaration file or a path under an excluded directory is never owned; skip fetching it.
    const names = program.getSourceFileNames().filter((name) =>
      !DECLARATION_FILE_RE.test(name) && !OWNED_PATH_RE.test(scopedFilename({ filename: name, cwd })));
    const sources = file.batch(names.map((name) => program.getSourceFile.gen(name)));
    for (const source of sources) {
      if (!ownedSource(source)) continue;
      const nodes: RemoteNode[] = [];
      const visit = (node: RemoteNode): undefined => {
        if (a.isTypeNode(node) || a.isImportDeclaration(node)) return undefined;
        if (a.isIdentifier(node) || a.isPropertyAccessExpression(node) || a.isElementAccessExpression(node)) nodes.push(node);
        node.forEachChild((child) => visit(child as RemoteNode));
        return undefined;
      };
      visit(source!);
      if (nodes.length === 0) continue;
      // canonicalSymbol unwraps parentheses first; an element access also reads its receiver.
      const receivers = nodes.flatMap((node) => a.isElementAccessExpression(node) && !safeClassReference(node)
        ? [unparenthesized(node["expression"] as RemoteNode)] : []);
      const queried = [...nodes.map((node) => a.isParenthesizedExpression(node) ? unparenthesized(node) : node), ...receivers];
      const symbols = checker.getSymbolAtLocation(queried);
      const aliases = [...new Set(symbols.filter((symbol) => symbol !== undefined).filter((symbol) => (symbol.flags & flagsOfSymbol.Alias) !== 0))];
      const targets = file.batch(aliases.map((symbol) => checker.getAliasedSymbol.gen(symbol)));
      const aliased = new Map(aliases.map((symbol, i) => [symbol, targets[i]!]));
      const canonical = symbols.map((symbol) => symbol === undefined ? undefined : aliased.get(symbol) ?? symbol);
      // Receivers without a symbol fall back to their type's symbol.
      const untyped = receivers.flatMap((receiver, i) => canonical[nodes.length + i] === undefined ? [receiver] : []);
      const types = untyped.length === 0 ? [] : checker.getTypeAtLocation(untyped);
      const typeSymbols = file.batch(types.map((type) => type.getSymbol.gen()));
      let nextReceiver = 0;
      let nextUntyped = 0;
      nodes.forEach((node, i) => {
        const symbol = canonical[i];
        if (symbol !== undefined) {
          let values = namespaceValues.get(symbol.id);
          if (values === undefined) {
            values = ownedClassValues(symbol);
            namespaceValues.set(symbol.id, values);
          }
          if (!namespacePrefix(symbol, node) && !safeClassReference(node)) for (const value of values) escaped.add(value);
        }
        if (a.isElementAccessExpression(node) && !safeClassReference(node)) {
          const receiver = canonical[nodes.length + nextReceiver++] ?? typeSymbols[nextUntyped++];
          if (receiver !== undefined) for (const value of ownedClassValues(receiver)) escaped.add(value);
        }
      });
    }
    scopes.set(cwd, escaped);
    return escaped;
  }

  function missingImplementation(signature: Signature, parameter: Symbol, argument: RemoteNode): MissingImplementation | null {
    const parameterType = checker.getTypeOfSymbolAtLocation(parameter, call);
    const contractType = behavioralContract(parameterType);
    if (contractType === null) return null;
    const contractSymbol = contractType.getSymbol();
    if (contractSymbol === undefined || !hasNominalRejectionGuard(signature, parameter, contractSymbol)) return null;
    const actualType = checker.getTypeAtLocation(argument);
    if (!checker.isTypeAssignableTo(actualType, contractType)) return null;
    const implementation = ownedClass(argument);
    if (implementation === null) return null;
    if (nominallyInherits(implementation, contractSymbol, new Set()) !== false) return null;
    return { implementation, contractSymbol };
  }

  function nominallyInherits(declaration: RemoteNode, target: Symbol, seen: Set<number>): boolean | null {
    if (decorators(declaration).length > 0) return null;
    if (hasPrototypeMutation(sourceOf(declaration)) || (declaration["members"] as List ?? []).some((member) =>
      a.isConstructorDeclaration(member) || a.isClassStaticBlockDeclaration(member) ||
      (a.isPropertyDeclaration(member) && member["initializer"] !== undefined))) return null;
    const name = declaration["name"] as Field;
    const symbol = name === undefined ? undefined : canonicalSymbol(name);
    if (symbol !== undefined) {
      if (seen.has(symbol.id)) return null;
      seen.add(symbol.id);
    }
    const parents = (declaration["heritageClauses"] as List)?.find((clause) => clause["token"] === k["ExtendsKeyword"])?.["types"] as List;
    if (parents === undefined) return false;
    if (parents.length !== 1) return null;
    const parentSymbol = canonicalSymbol(parents[0]!["expression"] as RemoteNode);
    if (parentSymbol === undefined) return null;
    if (parentSymbol.id === target.id) return true;
    const inherited = classDeclaration(parentSymbol);
    return inherited === undefined ? null : nominallyInherits(inherited, target, new Set(seen));
  }

  function ownedClass(expression: RemoteNode): RemoteNode | null {
    if (!a.isNewExpression(expression)) return null;
    const type = checker.getTypeAtLocation(expression);
    if ((type.flags & (flags.Any | flags.Unknown)) !== 0) return null;
    const declaration = classDeclaration(type.getSymbol());
    const constructed = classDeclaration(canonicalSymbol(expression["expression"] as RemoteNode));
    if (declaration === undefined || !same(declaration, constructed)) return null;
    const source = sourceOf(declaration);
    if (source.isDeclarationFile === true || /(?:^|[/\\])(?:node_modules|vendor|generated)(?:[/\\])/u.test(source.fileName)) return null;
    return declaration;
  }

  function behavioralContract(type: Type): Type | null {
    if (type.isUnionType()) {
      const substantive = type.getTypes().filter((member) => (member.flags & (flags.Null | flags.Undefined)) === 0);
      if (substantive.length !== 1) return null;
      return behavioralContract(substantive[0]!);
    }
    if ((type.flags & (flags.Any | flags.Unknown)) !== 0) return null;
    const declaration = type.getSymbol()?.declarations.filter((handle) => handle.kind === k["ClassDeclaration"])
      .map((handle) => handle.resolve())
      .find((item) => item !== undefined && modifiersOf(item).some((modifier) => modifier.kind === k["AbstractKeyword"]));
    if (declaration === undefined) return null;
    return checker.getPropertiesOfType(type).some((property) => {
      if (!property.declarations.some((handle) => handle.kind === k["MethodSignature"] || handle.kind === k["MethodDeclaration"])) return false;
      return checker.getTypeOfSymbolAtLocation(property, declaration).getCallSignatures().length > 0;
    }) ? type : null;
  }

  function hasNominalRejectionGuard(signature: Signature, parameter: Symbol, contract: Symbol): boolean {
    const declaration = signature.declaration?.resolve();
    if (declaration === undefined || !a.isConstructorDeclaration(declaration)) return false;
    if (declaration.parent !== undefined && decorators(declaration.parent).length > 0) return false;
    if (hasPrototypeMutation(sourceOf(declaration))) return false;
    const comparison = rejectedInstanceCheck(declaration);
    if (comparison === null || canonicalSymbol(comparison["left"] as RemoteNode)?.id !== parameter.id ||
      canonicalSymbol(comparison["right"] as RemoteNode)?.id !== contract.id) return false;
    const target = classDeclaration(contract);
    return target !== undefined && hasOrdinaryInstanceCheck(target, []);
  }

  /** The `left instanceof right` of a constructor that opens with `if (!(left instanceof right)) throw …`. */
  function rejectedInstanceCheck(constructor: RemoteNode): RemoteNode | null {
    const first = ((constructor["body"] as Field)?.["statements"] as List)?.[0];
    if (first === undefined || !a.isIfStatement(first) || !alwaysThrows(first["thenStatement"] as RemoteNode)) return null;
    const condition = unparenthesized(first["expression"] as RemoteNode);
    if (!a.isPrefixUnaryExpression(condition) || condition["operator"] !== k["ExclamationToken"]) return null;
    const comparison = unparenthesized(condition["operand"] as RemoteNode);
    return a.isBinaryExpression(comparison) && (comparison["operatorToken"] as Field)?.kind === k["InstanceOfKeyword"] ? comparison : null;
  }

  function alwaysThrows(statement: RemoteNode): boolean {
    const statements = statement["statements"] as List ?? [];
    return a.isThrowStatement(statement) || (a.isBlock(statement) && statements.length === 1 && a.isThrowStatement(statements[0]));
  }

  function hasOrdinaryInstanceCheck(declaration: RemoteNode, seen: RemoteNode[]): boolean {
    const members = declaration["members"] as List ?? [];
    if (seen.some((item) => same(item, declaration)) || decorators(declaration).length > 0 || hasPrototypeMutation(sourceOf(declaration)) ||
      members.some((member) => a.isClassStaticBlockDeclaration(member))) return false;
    seen.push(declaration);
    if (members.some((member) => a.isComputedPropertyName(member["name"] as Field) &&
      modifiersOf(member).some((modifier) => modifier.kind === k["StaticKeyword"]))) return false;
    for (const clause of declaration["heritageClauses"] as List ?? []) {
      if (clause["token"] !== k["ExtendsKeyword"]) continue;
      for (const parent of clause["types"] as List ?? []) {
        const ancestor = classDeclaration(canonicalSymbol(parent["expression"] as RemoteNode));
        if (ancestor === undefined || !hasOrdinaryInstanceCheck(ancestor, seen)) return false;
      }
    }
    return true;
  }

  if (!a.isNewExpression(call)) return [];
  const consumer = classDeclaration(canonicalSymbol(call["expression"] as RemoteNode));
  if (consumer === undefined) return [];
  const signature = checker.getResolvedSignature(call);
  if (signature === undefined || !same(signature.declaration?.resolve()?.parent, consumer)) return [];
  const parameters = signature.getParameters();
  const argumentNodes = call["arguments"] as List ?? [];
  const findings: Finding[] = [];
  for (const index of argumentIndexes) {
    const parameter = parameters[index];
    const argument = argumentNodes[index];
    if (parameter === undefined || argument === undefined) continue;
    const missing = missingImplementation(signature, parameter, argument);
    if (missing === null || !closedNominalBoundary(consumer, missing)) continue;
    const contract = classDeclaration(missing.contractSymbol);
    findings.push({
      argument: index,
      implementation: text(missing.implementation["name"] as Field) ?? "class",
      contract: missing.contractSymbol.name,
      fix: contract === undefined ? null : { call, consumer, implementation: missing.implementation, contract },
    });
  }
  return findings;
}

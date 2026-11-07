/**
 * @fileoverview _service-class — syntax-only facts about a module's service
 * classes, shared by `require-port-for-service` and
 * `require-explicit-service-contract`: which constructor parameters a class
 * retains as collaborators, which public operations invoke them, and which
 * declared contracts cover those operations.
 *
 * The module-level indexes are built once per file, on the first class either
 * rule inspects, and shared by both rules.
 */

import type { ESTree, Node } from "../types.js";
import { forEachOwnAstChild, isErasedExpression, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { getPropertyName } from "../utils/static-string.js";

export type ClassNode = ESTree.Class;
type ProgramStatement = ESTree.Program["body"][number];
type TypeNode = ESTree.TSType;
type TypeElement = ESTree.TSSignature;
type Parameter = ESTree.ParamPattern;

const CONFIGISH_TYPE_RE =
  /(?:Options|Opts|Config|Configuration|Settings|Params|Props|Args|Env|Environment|Callbacks|Flags)$/;

/** Configuration names plus logger and clock, which alone do not establish a service seam. */
const CONFIGISH_NAME_RE =
  /^(?:options|opts|config|configuration|settings|params|props|args|env|environment|callbacks|flags|logger|log|clock)$/i;

/** Containers and mapped helpers describe data rather than substitutable implementations. */
const BUILTIN_CONTAINER_TYPE_RE =
  /^(?:Record|Map|WeakMap|Set|WeakSet|Array|ReadonlyArray|ReadonlyMap|ReadonlySet|Promise|Partial|Required|Readonly|Pick|Omit|Exclude|Extract|NonNullable|Awaited|Parameters|ReturnType|InstanceType)$/;

/** Nominal leaf values are constructor data, not collaborators with swappable behavior. */
const VALUE_TYPE_RE =
  /^(?:ArrayBuffer|Blob|Buffer|Date|NodePath|RegExp|URL|URLSearchParams)$/;

const STORAGE_ASSIGNMENT_OPERATORS: ReadonlySet<string> = new Set(["=", "&&=", "??=", "||="]);

/** Nested functions and classes run later, if at all, so they do not store constructor fields. */
const NESTED_SCOPE_TYPES: ReadonlySet<string> = new Set([
  "ArrowFunctionExpression", "FunctionExpression", "FunctionDeclaration", "ClassExpression", "ClassDeclaration",
]);

export interface Collaborator {
  readonly name: string;
  /** Rightmost segment of the type name — what the config-ish guards test. */
  readonly typeName: string;
  /** Full source spelling, including any namespace qualifier, for the message. */
  readonly display: string;
  /** Instance fields that retain this constructor parameter. */
  readonly fields: readonly string[];
}

export interface ConstructorFacts {
  /** Parameters assigned to an instance field, either as a parameter property or in the body. */
  readonly collaborators: readonly Collaborator[];
  /** How many instance fields the constructor fills with a `new` expression. */
  readonly constructedFields: number;
}

type TypeReference = { readonly typeName: string; readonly display: string };
type MemberTypes = ReadonlyMap<string, TypeReference>;
type StoredMemberFields = ReadonlyMap<string, ReadonlyMap<string, ReadonlySet<string>>>;

/** The module-level declarations a service class is resolved against, in this file only. */
export interface ServiceFile {
  /** Local names exported by `export { … }`, `export default name` or `export = name`. */
  readonly detachedExports: ReadonlySet<string>;
  /** `interface Deps { … }` / `type Deps = { … }`, by name: constructor bags. */
  readonly objects: ReadonlyMap<string, MemberTypes>;
  /** `type Replayer = (e: Event) => void` — a callback with a nominal name. */
  readonly functionAliases: ReadonlySet<string>;
  /** Callable members of each local interface or type alias, `*` when part of it is unresolved. */
  readonly interfaces: ReadonlyMap<string, ReadonlySet<string>>;
  /** Top-level class declarations, by name. */
  readonly classes: ReadonlyMap<string, ClassNode>;
}

const SERVICE_FILES = new WeakMap<ESTree.Program, ServiceFile>();

export function serviceFile(program: ESTree.Program): ServiceFile {
  let file = SERVICE_FILES.get(program);
  if (file === undefined) {
    const functionAliases = localFunctionAliases(program);
    file = {
      detachedExports: detachedValueExports(program),
      objects: localObjectTypes(program),
      functionAliases,
      interfaces: localInterfaceSurfaces(program, functionAliases),
      classes: localClassDeclarations(program),
    };
    SERVICE_FILES.set(program, file);
  }
  return file;
}

function addToSetMap(map: Map<string, Set<string>>, key: string, value: string): void {
  const values = map.get(key);
  if (values === undefined) map.set(key, new Set([value]));
  else values.add(value);
}

function staticMemberName(member: ESTree.MemberExpression): string | null {
  if (member.property.type === "PrivateIdentifier") return `#${member.property.name}`;
  return getPropertyName(member);
}

function exportedOrOwn(statement: ProgramStatement): Node | null {
  return statement.type === "ExportNamedDeclaration" ? statement.declaration : statement;
}

function detachedValueExports(program: ESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type === "ExportNamedDeclaration" &&
      statement.declaration === null &&
      statement.source === null &&
      statement.exportKind !== "type"
    ) {
      // Without a `from` clause every local is an identifier.
      for (const specifier of statement.specifiers) {
        if (specifier.exportKind !== "type" && specifier.local.type === "Identifier") names.add(specifier.local.name);
      }
    } else if (statement.type === "ExportDefaultDeclaration" && statement.declaration.type === "Identifier") {
      names.add(statement.declaration.name);
    } else if (statement.type === "TSExportAssignment" && statement.expression.type === "Identifier") {
      names.add(statement.expression.name);
    }
  }
  return names;
}

export function isExportedServiceClass(node: ClassNode, file: ServiceFile): boolean {
  const parent = parentOf(node);
  return (
    parent?.type === "ExportNamedDeclaration" ||
    parent?.type === "ExportDefaultDeclaration" ||
    (node.id !== null && file.detachedExports.has(node.id.name))
  );
}

/** The rightmost segment plus the full spelling of a bare type reference, or null for anything else. */
function readTypeReference(annotation: TypeNode | undefined): TypeReference | null {
  if (annotation?.type === "TSUnionType") {
    const members = annotation.types.filter(
      (member) => member.type !== "TSUndefinedKeyword" && member.type !== "TSNullKeyword",
    );
    annotation = members.length === 1 ? members[0] : undefined;
  }
  if (annotation?.type !== "TSTypeReference") return null;
  const { typeName } = annotation;
  const rightmost =
    typeName.type === "Identifier" ? typeName.name : typeName.type === "TSQualifiedName" ? typeName.right.name : null;
  if (rightmost === null) return null;
  return { typeName: rightmost, display: qualifiedName(typeName) };
}

/** `catalog.Client` -> `"catalog.Client"`; a nested qualifier is flattened the same way. */
function qualifiedName(name: ESTree.TSTypeName): string {
  return name.type === "Identifier"
    ? name.name
    : name.type === "TSQualifiedName"
      ? `${qualifiedName(name.left)}.${name.right.name}`
      : "";
}

/** Property signatures of a `{ a: A; b: B }` body, keyed by property name. */
function propertySignatureTypes(members: readonly TypeElement[]): Map<string, TypeReference> {
  const types = new Map<string, TypeReference>();
  for (const member of members) {
    if (member.type !== "TSPropertySignature") continue;
    if (member.computed || member.key.type !== "Identifier") continue;
    const reference = readTypeReference(member.typeAnnotation?.typeAnnotation);
    if (reference === null) continue;
    types.set(member.key.name, reference);
  }
  return types;
}

/** Locally declared object shapes used to resolve constructor bags. */
function localObjectTypes(program: ESTree.Program): ReadonlyMap<string, MemberTypes> {
  const objects = new Map<string, MemberTypes>();
  for (const statement of program.body) {
    const declaration = exportedOrOwn(statement);
    if (declaration?.type === "TSInterfaceDeclaration") {
      objects.set(declaration.id.name, propertySignatureTypes(declaration.body.body));
      continue;
    }
    if (declaration?.type !== "TSTypeAliasDeclaration") continue;
    const aliased = declaration.typeAnnotation;
    // `type Deps = { … }` and `type Deps = Base & { … }` both resolve; the
    // intersection form is how a bag is usually extended.
    const literals: ESTree.TSTypeLiteral[] =
      aliased.type === "TSTypeLiteral"
        ? [aliased]
        : aliased.type === "TSIntersectionType"
          ? aliased.types.filter((part) => part.type === "TSTypeLiteral")
          : [];
    if (literals.length === 0) continue;
    const merged = new Map<string, TypeReference>();
    for (const literal of literals) {
      for (const [name, reference] of propertySignatureTypes(literal.members)) {
        merged.set(name, reference);
      }
    }
    objects.set(declaration.id.name, merged);
  }
  return objects;
}

/** Direct callable aliases and local aliases to them share the same capability. */
function localFunctionAliases(program: ESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  const parents = new Map<string, string>();
  for (const statement of program.body) {
    const declaration = exportedOrOwn(statement);
    if (declaration?.type !== "TSTypeAliasDeclaration") continue;
    const annotation = declaration.typeAnnotation;
    if (annotation.type === "TSFunctionType" || annotation.type === "TSConstructorType")
      names.add(declaration.id.name);
    if (annotation.type === "TSTypeReference" && annotation.typeName.type === "Identifier")
      parents.set(declaration.id.name, annotation.typeName.name);
  }
  for (let pass = 0; pass < parents.size; pass += 1) {
    let changed = false;
    for (const [name, parent] of parents) {
      if (names.has(parent) && !names.has(name)) {
        names.add(name);
        changed = true;
      }
    }
    if (!changed) break;
  }
  return names;
}

function localInterfaceSurfaces(
  program: ESTree.Program,
  functionAliases: ReadonlySet<string>,
): ReadonlyMap<string, ReadonlySet<string>> {
  const interfaces = new Map<string, Set<string>>();
  const parents = new Map<string, string[]>();
  for (const statement of program.body) {
    const declaration = exportedOrOwn(statement);
    if (declaration?.type !== "TSTypeAliasDeclaration" && declaration?.type !== "TSInterfaceDeclaration") continue;
    // Declaration merging: a repeated name adds to the surface already read.
    const name = declaration.id.name;
    const callables = interfaces.get(name) ?? new Set<string>();
    const inherited = parents.get(name) ?? [];
    readSurface(declaration, callables, inherited, functionAliases);
    interfaces.set(name, callables);
    parents.set(name, inherited);
  }
  for (let pass = 0; pass <= interfaces.size; pass += 1) {
    if (!inheritParentSurfaces(interfaces, parents)) break;
  }
  return interfaces;
}

/** Add a declaration's own callable members and its named parents. */
function readSurface(
  declaration: ESTree.TSInterfaceDeclaration | ESTree.TSTypeAliasDeclaration,
  callables: Set<string>,
  inherited: string[],
  functionAliases: ReadonlySet<string>,
): void {
  if (declaration.type === "TSInterfaceDeclaration") {
    addCallableMembers(declaration.body.body, callables, functionAliases);
    for (const heritage of declaration.extends) inherited.push(heritageName(heritage.expression));
    return;
  }
  const aliased = declaration.typeAnnotation;
  for (const part of aliased.type === "TSIntersectionType" ? aliased.types : [aliased]) {
    if (part.type === "TSTypeReference") inherited.push(heritageName(part.typeName));
    else if (part.type === "TSTypeLiteral") addCallableMembers(part.members, callables, functionAliases);
  }
}

/** A local parent by name; `*` for a qualified or computed one this file cannot resolve. */
function heritageName(name: Node): string {
  return name.type === "Identifier" ? name.name : "*";
}

function addCallableMembers(members: readonly TypeElement[], callables: Set<string>, functionAliases: ReadonlySet<string>): void {
  for (const member of members) {
    if (member.type !== "TSMethodSignature" && member.type !== "TSPropertySignature") continue;
    const name = declaredMemberName(member);
    if (name === null) continue;
    if (member.type === "TSMethodSignature" || isFunctionAnnotation(member.typeAnnotation?.typeAnnotation, functionAliases))
      callables.add(name);
  }
}

/** One fixed-point step: copy each parent's surface into its children; an unknown parent adds `*`. */
function inheritParentSurfaces(interfaces: Map<string, Set<string>>, parents: ReadonlyMap<string, readonly string[]>): boolean {
  let changed = false;
  for (const [name, inherited] of parents) {
    const surface = interfaces.get(name);
    if (surface === undefined) continue;
    for (const parent of inherited) {
      for (const method of interfaces.get(parent) ?? ["*"]) {
        if (!surface.has(method)) {
          surface.add(method);
          changed = true;
        }
      }
    }
  }
  return changed;
}

/** Declared classes preserve their own abstract status and explicit ancestry. */
function localClassDeclarations(program: ESTree.Program): ReadonlyMap<string, ClassNode> {
  const classes = new Map<string, ClassNode>();
  for (const statement of program.body) {
    const declaration =
      statement.type === "ExportNamedDeclaration" || statement.type === "ExportDefaultDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type === "ClassDeclaration" && declaration.id !== null) classes.set(declaration.id.name, declaration);
  }
  return classes;
}

/** The collaborators the first constructor with a body retains, or null when the class has none. */
export function constructorFacts(node: ClassNode, file: ServiceFile): ConstructorFacts | null {
  for (const member of node.body.body) {
    if (member.type !== "MethodDefinition" || member.kind !== "constructor") continue;
    // An overload signature has no body; the implementation follows it.
    const { body } = member.value;
    if (body === null) continue;
    const stored = storedFields(body);
    const typeParameters = typeParameterNames(node.typeParameters, member.value.typeParameters);
    const collaborators = member.value.params.flatMap((parameter) =>
      retainedCollaborators(parameter, stored, file, typeParameters));
    return { collaborators, constructedFields: stored.constructedCount };
  }
  return null;
}

/** What a constructor body writes to instance fields, and from which parameters. */
interface StoredFields {
  /** `this.svc = svc` and `this.slack = deps.slack`: fields by the identifier they come from. */
  readonly fromBinding: Map<string, Set<string>>;
  /** `this.slack = deps.slack`: fields by bag and member name. */
  readonly fromMember: Map<string, Map<string, Set<string>>>;
  /** Fields filled with a `new` expression. */
  readonly constructed: Set<string>;
  readonly written: Set<string>;
  /** Fields written more than once, conditionally, or other than by a top-level `this.x = …;`. */
  readonly unstable: Set<string>;
  readonly localBindings: Set<string>;
  constructedCount: number;
}

function storedFields(body: ESTree.FunctionBody): StoredFields {
  const stored: StoredFields = {
    fromBinding: new Map(),
    fromMember: new Map(),
    constructed: new Set(),
    written: new Set(),
    unstable: new Set(),
    localBindings: new Set(),
    constructedCount: 0,
  };
  const pending: Node[] = [...body.body];
  for (let current = pending.pop(); current !== undefined; current = pending.pop()) {
    if (NESTED_SCOPE_TYPES.has(current.type)) continue;
    if (current.type === "VariableDeclarator" && current.id.type === "Identifier") stored.localBindings.add(current.id.name);
    const field = writtenInstanceField(current);
    if (field !== null) recordFieldWrite(stored, current, field, body);
    forEachOwnAstChild(current, (child) => {
      pending.push(child);
    });
  }
  return stored;
}

/** A field is stable only when the body writes it once, as a top-level `this.x = …;` statement. */
function recordFieldWrite(stored: StoredFields, write: Node, field: string, body: ESTree.FunctionBody): void {
  if (stored.written.has(field)) stored.unstable.add(field);
  stored.written.add(field);
  if (write.type !== "AssignmentExpression") {
    stored.unstable.add(field);
    return;
  }
  const statement = parentOf(write);
  if (write.operator !== "=" || statement?.type !== "ExpressionStatement" || parentOf(statement) !== body)
    stored.unstable.add(field);
  if (STORAGE_ASSIGNMENT_OPERATORS.has(write.operator) && write.left.type === "MemberExpression" &&
    write.left.object.type === "ThisExpression")
    recordFieldSource(stored, field, unwrapExpression(write.right));
}

function recordFieldSource(stored: StoredFields, field: string, source: Node): void {
  if (source.type === "NewExpression") {
    stored.constructedCount += 1;
    stored.constructed.add(field);
  } else if (source.type === "Identifier") {
    // `this.svc = svc`
    addToSetMap(stored.fromBinding, source.name, field);
  } else if (source.type === "MemberExpression" && source.object.type === "Identifier") {
    // `this.slack = deps.slack` — a dependency bag spread onto fields.
    addToSetMap(stored.fromBinding, source.object.name, field);
    const member = staticMemberName(source);
    if (member === null) return;
    let members = stored.fromMember.get(source.object.name);
    if (members === undefined) {
      members = new Map<string, Set<string>>();
      stored.fromMember.set(source.object.name, members);
    }
    addToSetMap(members, member, field);
  }
}

/** The collaborators one constructor parameter contributes that stay retained in stable, injected fields. */
function retainedCollaborators(
  parameter: Parameter,
  stored: StoredFields,
  file: ServiceFile,
  typeParameters: ReadonlySet<string>,
): Collaborator[] {
  const collaborators: Collaborator[] = [];
  for (const reference of parameterCollaborators(parameter, file, stored.fromMember)) {
    if (stored.localBindings.has(reference.name)) continue;
    let fields = reference.fields;
    if (parameter.type === "TSParameterProperty") {
      if (stored.written.has(reference.name)) continue;
      fields = [reference.name];
    } else if (fields.length === 0) fields = [...(stored.fromBinding.get(reference.name) ?? [])];
    const injectedFields = fields.filter((field) => !stored.constructed.has(field) && !stored.unstable.has(field));
    if (injectedFields.length === 0 || isDataReference(reference, typeParameters, file.functionAliases)) continue;
    collaborators.push({ ...reference, fields: injectedFields });
  }
  return collaborators;
}

/** Names bound by `class Foo<T>` / `constructor<T>()` — placeholders, not implementations. */
function typeParameterNames(
  ...declarations: readonly (ESTree.TSTypeParameterDeclaration | null | undefined)[]
): ReadonlySet<string> {
  const names = new Set<string>();
  for (const declaration of declarations) {
    for (const parameter of declaration?.params ?? []) names.add(parameter.name.name);
  }
  return names;
}

/**
 * Configuration, and a bare type reference a port would protect nothing
 * about: a type parameter, a container, a value or a callback alias. Each is
 * the inline shape this rule already rejects wearing a nominal name.
 */
function isDataReference(
  reference: Collaborator,
  typeParameters: ReadonlySet<string>,
  functionAliases: ReadonlySet<string>,
): boolean {
  return (
    CONFIGISH_TYPE_RE.test(reference.typeName) ||
    CONFIGISH_NAME_RE.test(reference.name) ||
    typeParameters.has(reference.typeName) ||
    BUILTIN_CONTAINER_TYPE_RE.test(reference.typeName) ||
    VALUE_TYPE_RE.test(reference.typeName) ||
    functionAliases.has(reference.typeName)
  );
}

/** Every collaborator a single constructor parameter contributes: 0, 1, or (destructured) many. */
function parameterCollaborators(
  parameter: Parameter,
  file: ServiceFile,
  storedMemberFieldsFrom: StoredMemberFields,
): readonly Collaborator[] {
  const pattern = parameter.type === "AssignmentPattern" ? parameter.left : parameter;
  if (pattern.type === "ObjectPattern") return objectPatternCollaborators(pattern, file);
  const target = parameterTarget(parameter);
  if (target.type !== "Identifier") return [];
  const reference = readTypeReference(target.typeAnnotation?.typeAnnotation);
  if (reference !== null && !CONFIGISH_NAME_RE.test(target.name) && !CONFIGISH_TYPE_RE.test(reference.typeName))
    return [{ name: target.name, ...reference, fields: [] }];
  return namedBagCollaborators(target, file, storedMemberFieldsFrom);
}

/** The binding target of a constructor parameter, past a parameter property and a default. */
function parameterTarget(parameter: Parameter): Node {
  let target: Node = parameter;
  if (target.type === "TSParameterProperty") target = target.parameter;
  if (target.type === "AssignmentPattern") target = target.left;
  return target;
}

/** Resolve `this.repo = options.repo` without treating the whole options bag as a service. */
function namedBagCollaborators(
  target: ESTree.BindingIdentifier,
  file: ServiceFile,
  storedMemberFieldsFrom: StoredMemberFields,
): Collaborator[] {
  const members = bagMemberTypes(target.typeAnnotation?.typeAnnotation, file);
  const storedMembers = storedMemberFieldsFrom.get(target.name);
  if (members === null || storedMembers === undefined) return [];
  const collaborators: Collaborator[] = [];
  for (const [name, fields] of storedMembers) {
    if (CONFIGISH_NAME_RE.test(name)) continue;
    const reference = members.get(name);
    if (reference === undefined) continue;
    collaborators.push({ name, ...reference, fields: [...fields] });
  }
  return collaborators;
}

/** Resolve separately stored collaborators from a locally typed constructor bag. */
function objectPatternCollaborators(pattern: ESTree.ObjectPattern, file: ServiceFile): Collaborator[] {
  const members = bagMemberTypes(pattern.typeAnnotation?.typeAnnotation, file);
  if (members === null) return [];
  const collaborators: Collaborator[] = [];
  for (const property of pattern.properties) {
    if (property.type !== "Property" || property.computed) continue;
    if (property.key.type !== "Identifier") continue;
    const key = property.key.name;
    const bound: Node = property.value.type === "AssignmentPattern" ? property.value.left : property.value;
    if (bound.type !== "Identifier") continue;
    // A renamed binding (`{ repo: userRepo }`) offers two names; either one
    // reading as config-ish is enough to drop it, on the same reasoning that
    // drops a config-ish parameter name.
    if (CONFIGISH_NAME_RE.test(key)) continue;
    const reference = members.get(key);
    if (reference === undefined) continue;
    collaborators.push({ name: bound.name, ...reference, fields: [] });
  }
  return collaborators;
}

/**
 * Member types of an options-object parameter's annotation: the annotation's own
 * body when it is written inline, otherwise the declaration it names, resolved
 * in this file only.
 */
function bagMemberTypes(annotation: TypeNode | undefined, file: ServiceFile): MemberTypes | null {
  if (annotation?.type === "TSTypeLiteral") return propertySignatureTypes(annotation.members);
  // A qualified `catalog.Deps` names another module by construction.
  if (annotation?.type !== "TSTypeReference" || annotation.typeName.type !== "Identifier") return null;
  return file.objects.get(annotation.typeName.name) ?? null;
}

/** `this.field`, past optional chains and erased TypeScript wrappers. */
function instanceField(candidate: Node): string | null {
  const node = withoutWrappers(candidate);
  return node.type === "MemberExpression" && node.object.type === "ThisExpression" ? staticMemberName(node) : null;
}

function withoutWrappers(candidate: Node): Node {
  let node = candidate;
  while (node.type === "ChainExpression" || isErasedExpression(node)) node = node.expression;
  return node;
}

/** The instance field a call invokes directly (`this.run()`) or as a receiver (`this.repo.save()`). */
export function invokedInstanceField(call: ESTree.CallExpression): string | null {
  const callee = withoutWrappers(call.callee);
  return instanceField(callee) ?? (callee.type === "MemberExpression" ? instanceField(callee.object) : null);
}

/** Direct instance-field writes shared by constructor retention and operation identity. */
function writtenInstanceField(node: Node): string | null {
  if (node.type === "AssignmentExpression" || node.type === "ForOfStatement" || node.type === "ForInStatement")
    return instanceField(node.left);
  if (node.type === "UpdateExpression") return instanceField(node.argument);
  if (node.type === "UnaryExpression" && node.operator === "delete") return instanceField(node.argument);
  if (node.type === "MemberExpression" && isDestructuredWriteTarget(node)) return instanceField(node);
  return null;
}

/** Pattern values are writes only when their enclosing pattern is an assignment or loop target. */
function isDestructuredWriteTarget(node: ESTree.MemberExpression): boolean {
  const access = outerExpression(node);
  let target: Node = access;
  for (let pattern = enclosingPattern(target); pattern !== null; pattern = enclosingPattern(target)) target = pattern;
  const parent = parentOf(target);
  return (
    target !== access &&
    (parent?.type === "AssignmentExpression" || parent?.type === "ForOfStatement" || parent?.type === "ForInStatement") &&
    parent.left === target
  );
}

/** The destructuring pattern `target` is an element, property value, rest or default target of, if any. */
function enclosingPattern(target: Node): Node | null {
  const parent = parentOf(target);
  if (parent === null) return null;
  if (parent.type === "Property") {
    const pattern = parentOf(parent);
    return parent.value === target && pattern?.type === "ObjectPattern" ? pattern : null;
  }
  const isPatternPart =
    parent.type === "ArrayPattern" ||
    parent.type === "ObjectPattern" ||
    (parent.type === "RestElement" && parent.argument === target) ||
    (parent.type === "AssignmentPattern" && parent.left === target);
  return isPatternPart ? parent : null;
}

export function isPrivateOrProtected(member: { readonly accessibility?: string | null }): boolean {
  return member.accessibility === "private" || member.accessibility === "protected";
}

/** A function type, written inline or through a local callable alias. */
function isFunctionAnnotation(annotation: TypeNode | undefined, functionAliases: ReadonlySet<string>): boolean {
  return (
    annotation?.type === "TSFunctionType" ||
    (annotation?.type === "TSTypeReference" &&
      annotation.typeName.type === "Identifier" &&
      functionAliases.has(annotation.typeName.name))
  );
}

function declaredMemberName(member: { readonly key: Node; readonly computed: boolean }): string | null {
  if (!member.computed && member.key.type === "Identifier") return member.key.name;
  if (member.key.type === "Literal" && typeof member.key.value === "string") return member.key.value;
  return null;
}

/** Public instance methods and function-valued properties; `…` stands for one without a static name. */
export function publicMethodNames(body: ESTree.ClassBody, functionAliases: ReadonlySet<string>): string[] {
  const names: string[] = [];
  for (const member of body.body) {
    if (member.type === "MethodDefinition") {
      if (member.kind === "method" && isPublicInstanceMember(member)) names.push(declaredMemberName(member) ?? "…");
    } else if (member.type === "PropertyDefinition" && isPublicInstanceMember(member) && isFunctionValued(member, functionAliases)) {
      names.push(declaredMemberName(member) ?? "…");
    }
  }
  return names;
}

/**
 * ECMAScript #private members have no TypeScript accessibility modifier, and
 * a function-valued #field is still implementation detail.
 */
function isPublicInstanceMember(member: ESTree.MethodDefinition | ESTree.PropertyDefinition): boolean {
  return !member.static && !isPrivateOrProtected(member) && member.key.type !== "PrivateIdentifier";
}

function isFunctionValued(member: ESTree.PropertyDefinition, functionAliases: ReadonlySet<string>): boolean {
  return (
    member.value?.type === "ArrowFunctionExpression" ||
    member.value?.type === "FunctionExpression" ||
    isFunctionAnnotation(member.typeAnnotation?.typeAnnotation, functionAliases)
  );
}

/** Oxlint types `implements` as optional. */
export function implementsOf(node: ClassNode): readonly ESTree.TSClassImplements[] {
  return node.implements ?? [];
}

/** Public operations that invoke a retained collaborator, directly or through another operation. */
export function serviceOperations(node: ClassNode, file: ServiceFile): readonly string[] {
  const facts = constructorFacts(node, file);
  if (facts === null) return [];
  const retained = new Set(facts.collaborators.flatMap((collaborator) => collaborator.fields));
  if (retained.size === 0) return [];

  const callers = new Map<string, Set<string>>();
  const active = new Set<string>();
  for (const [name, body] of serviceOperationBodies(node)) {
    forEachServiceCall(body, (call) => {
      if (retained.has(invokedInstanceField(call) ?? "")) active.add(name);
      if (call.callee.type === "MemberExpression" && call.callee.object.type === "ThisExpression") {
        const callee = staticMemberName(call.callee);
        if (callee !== null) addToSetMap(callers, callee, name);
      }
    });
  }
  const pending = [...active];
  for (let callee = pending.pop(); callee !== undefined; callee = pending.pop()) {
    for (const caller of callers.get(callee) ?? []) {
      if (active.has(caller)) continue;
      active.add(caller);
      pending.push(caller);
    }
  }
  return publicMethodNames(node.body, file.functionAliases).filter((name) => active.has(name));
}

/** Method and function-property bodies, excluding static or rewritten operations. */
function serviceOperationBodies(node: ClassNode): ReadonlyMap<string, Node> {
  const bodies = new Map<string, Node>();
  const written = writtenInstanceFields(node.body);
  for (const member of node.body.body) {
    if (member.type !== "MethodDefinition" && member.type !== "PropertyDefinition") continue;
    const body = operationBody(member);
    const name = declaredMemberName(member);
    if (body !== null && name !== null && !written.has(name)) bodies.set(name, body);
  }
  return bodies;
}

/** Every instance field written anywhere in the class, nested callbacks included. */
function writtenInstanceFields(body: ESTree.ClassBody): ReadonlySet<string> {
  const written = new Set<string>();
  const pending: Node[] = [body];
  for (let current = pending.pop(); current !== undefined; current = pending.pop()) {
    const name = writtenInstanceField(current);
    if (name !== null) written.add(name);
    forEachOwnAstChild(current, (child) => {
      pending.push(child);
    });
  }
  return written;
}

/** The body of an undecorated instance method or function-valued property. */
function operationBody(member: ESTree.MethodDefinition | ESTree.PropertyDefinition): Node | null {
  if (member.static || member.decorators.length > 0) return null;
  if (member.type === "MethodDefinition" && member.kind !== "method") return null;
  const value = member.value;
  if (value?.type !== "FunctionExpression" && value?.type !== "ArrowFunctionExpression") return null;
  return value.body;
}

/** Calls in the operation itself, without assuming nested callbacks execute. */
function forEachServiceCall(node: Node, onCall: (call: ESTree.CallExpression) => void): void {
  if (NESTED_SCOPE_TYPES.has(node.type)) return;
  if (node.type === "BlockStatement") {
    for (const statement of node.body) {
      forEachServiceCall(statement, onCall);
      if (terminatesOperation(statement)) break;
    }
    return;
  }
  const branch = literalExecutionBranch(node);
  if (branch !== null) {
    forEachServiceCall(branch, onCall);
    return;
  }
  if (node.type === "CallExpression") onCall(node);
  forEachOwnAstChild(node, (child) => {
    forEachServiceCall(child, onCall);
  });
}

/** Boolean literals select a branch without guessing at arbitrary expressions. */
function literalExecutionBranch(node: Node): Node | null {
  if (node.type === "WhileStatement" && node.test.type === "Literal" && node.test.value === false) return node.test;
  if (
    (node.type === "IfStatement" || node.type === "ConditionalExpression") &&
    node.test.type === "Literal" &&
    typeof node.test.value === "boolean"
  ) {
    return node.test.value ? node.consequent : (node.alternate ?? node.test);
  }
  return node.type === "LogicalExpression" ? literalLogicalBranch(node) : null;
}

/** `true && x` runs `x`, `false || x` runs `x`; the other forms stop at the literal. */
function literalLogicalBranch(node: ESTree.LogicalExpression): Node | null {
  if (node.left.type !== "Literal" || typeof node.left.value !== "boolean") return null;
  if (node.operator === "&&") return node.left.value ? node.right : node.left;
  if (node.operator === "||") return node.left.value ? node.left : node.right;
  return node.left;
}

/** Only unconditional exits and selected literal branches stop the operation. */
function terminatesOperation(node: Node): boolean {
  if (node.type === "ReturnStatement" || node.type === "ThrowStatement") return true;
  if (node.type === "BlockStatement") return node.body.some(terminatesOperation);
  if (node.type !== "IfStatement") return false;
  const branch = literalExecutionBranch(node);
  if (branch !== null) return terminatesOperation(branch);
  return node.alternate !== null && terminatesOperation(node.consequent) && terminatesOperation(node.alternate);
}

/**
 * Whether local interfaces and abstract classes the class declares cover
 * `operations`; `null` when a declared contract cannot be resolved by this
 * syntax-only pass.
 */
export function hasDeclaredServiceContract(
  node: ClassNode,
  operations: readonly string[],
  file: ServiceFile,
): boolean | null {
  const covered = new Set<string>();
  const pending = [node];
  const seen = new Set<ClassNode>();

  function addImplementedContracts(current: ClassNode): boolean {
    for (const implementation of implementsOf(current)) {
      if (implementation.expression.type !== "Identifier") return false;
      const name = implementation.expression.name;
      const surface = file.interfaces.get(name);
      const base = file.classes.get(name);
      if (surface === undefined && base === undefined) return false;
      if (surface?.has("*")) return false;
      for (const method of surface ?? []) covered.add(method);
      if (base?.abstract) pending.push(base);
    }
    return true;
  }

  for (let current = pending.pop(); current !== undefined; current = pending.pop()) {
    if (seen.has(current)) continue;
    seen.add(current);
    if (current.decorators.length > 0) return null;
    if (current.abstract) {
      for (const method of abstractContractOperations(current, file.functionAliases)) covered.add(method);
    }
    if (!addImplementedContracts(current)) return null;
    if (current.superClass === null) continue;
    if (current.superClass.type !== "Identifier") return null;
    const base = file.classes.get(current.superClass.name);
    if (base === undefined) return null;
    pending.push(base);
  }
  return operations.every((name) => covered.has(name));
}

/** Public concrete and abstract callable members of an abstract contract. */
function abstractContractOperations(node: ClassNode, functionAliases: ReadonlySet<string>): ReadonlySet<string> {
  const methods = new Set(publicMethodNames(node.body, functionAliases));
  for (const member of node.body.body) {
    if (member.type !== "TSAbstractMethodDefinition" && member.type !== "TSAbstractPropertyDefinition") continue;
    if (member.static || isPrivateOrProtected(member)) continue;
    if (
      member.type === "TSAbstractPropertyDefinition" &&
      !isFunctionAnnotation(member.typeAnnotation?.typeAnnotation, functionAliases)
    )
      continue;
    const name = declaredMemberName(member);
    if (name !== null) methods.add(name);
  }
  return methods;
}

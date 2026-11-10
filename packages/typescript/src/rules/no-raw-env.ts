/**
 * @fileoverview no-raw-env — a raw `process.env` read is untyped and unvalidated, so a missing variable surfaces as `undefined` in business logic.
 *
 * Follow each boundary input to its parser. Raw aliases must not escape
 * alongside the shared parsed settings object.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-raw-env.test.ts
 */

import {
  defineRule,
  tsReference,
  type ESTree,
  type Identifier,
  type Node,
  type SourceCode,
  type TsVariable,
} from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isScriptFile, isTestFile } from "../utils/paths.js";
import { stableValueBinding, typeOnlyReference } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

/** Build / test / tooling config: `vite.config.ts`, `vitest.config.mts`, `playwright.config.ts`. */
const CONFIG_FILE_RE = /(^|[\\/])[\w.-]+\.config\.[cm]?[jt]sx?$/;

/** Recognize validation boundaries; each raw read must still reach a parser. */
const ENV_BOUNDARY_FILE_RE =
  /(^|[\\/])(?:env|settings|client-env|server-env|client-settings|server-settings)\.[cm]?[jt]sx?$/;

const PROCESS_MODULES: readonly string[] = ["node:process", "process"];
const PROCESS_IMPORT_SPECIFIERS: readonly string[] = [
  "ImportDefaultSpecifier",
  "ImportNamespaceSpecifier",
];

// Build-time constants that bundlers (webpack/Vite) statically replace — exempt.
const BUILD_TIME_CONSTANTS: ReadonlySet<string> = new Set([
  "NODE_ENV",
  "MODE",
  "DEV",
  "PROD",
  "SSR",
]);

const PLATFORM_MARKERS: ReadonlySet<string> = new Set([
  "NEXT_RUNTIME",
  "VERCEL",
  "VERCEL_ENV",
  "CI",
]);

/** Resolve the actual native process rather than a same-named injected object. */
function isNativeProcess(node: Node, sourceCode: SourceCode): boolean {
  const receiver = unwrapExpression(node);
  if (receiver.type !== "Identifier") return false;
  const binding = findVariable(sourceCode.getScope(receiver), receiver.name);
  if (binding === null || binding.defs.length === 0) return receiver.name === "process";
  return binding.defs.every((definition) => {
    const parent = definition.parent;
    return (
      definition.type === "ImportBinding" &&
      parent?.type === "ImportDeclaration" &&
      parent.importKind !== "type" &&
      PROCESS_MODULES.includes(parent.source.value) &&
      PROCESS_IMPORT_SPECIFIERS.includes(definition.node.type)
    );
  });
}

/** True for the `process.env` member node (dotted or as the base of `process.env[key]`). */
function isProcessEnv(node: ESTree.MemberExpression, sourceCode: SourceCode): boolean {
  return getPropertyName(node) === "env" && isNativeProcess(node.object, sourceCode);
}

/** True for the `import.meta.env` member node (dotted or as the base of `import.meta.env[key]`). */
function isImportMetaEnv(node: ESTree.MemberExpression): boolean {
  return (
    getPropertyName(node) === "env" &&
    node.object.type === "MetaProperty" &&
    node.object.meta.name === "import" &&
    node.object.property.name === "meta"
  );
}

/** Match named bundler constants and host-owned platform markers. */
function isExemptVariableAccess(node: Node): boolean {
  const parent = parentOf(node);
  if (parent?.type !== "MemberExpression" || parent.object !== node) return false;
  const name = getPropertyName(parent);
  return name !== null && (BUILD_TIME_CONSTANTS.has(name) || PLATFORM_MARKERS.has(name));
}

/** Match assignment and deletion targets, which do not read configuration. */
function isWriteTarget(node: Node): boolean {
  const direct = parentOf(node);
  const access = direct?.type === "MemberExpression" && direct.object === node ? direct : node;
  const parent = parentOf(access);
  if (parent?.type === "AssignmentExpression") {
    return parent.left === access;
  }
  if (parent?.type === "UnaryExpression") {
    return parent.operator === "delete";
  }
  return false;
}

/** Match whole-environment pass-through such as `{ ...process.env }`. */
function isWholeEnvSpread(node: Node): boolean {
  const parent = parentOf(node);
  return parent?.type === "SpreadElement" && parent.argument === node;
}

/** Own the shared counter; return its prior allowance while charging one visit. */
function createValidationBudget(): () => number {
  let remaining = 512;
  return () => remaining--;
}

function reachesValidation(
  node: Node,
  sourceCode: SourceCode,
  seen: ReadonlySet<TsVariable> = new Set(),
  depth = 0,
  budget = createValidationBudget(),
): boolean {
  // Complex flows are deliberately unreported, rather than guessed invalid.
  if (depth >= 24 || budget() <= 0) return true;
  const parent = parentOf(node);
  if (parent === null) return false;
  switch (parent.type) {
    case "CallExpression": {
      const identity = isClosedIdentityAdapter(parent, sourceCode);
      return (
        parent.arguments.some((argument) => argument === node) &&
        ((!identity && isValidationCall(parent, sourceCode)) ||
          ((identity ||
            isScalarCoercion(parent, sourceCode) ||
            (isNativeJsonParse(parent, sourceCode) && parent.arguments.length === 1)) &&
            reachesValidation(parent, sourceCode, seen, depth + 1, budget)))
      );
    }
    case "VariableDeclarator":
      return parent.init === node && validatedAlias(parent, sourceCode, seen, depth, budget);
    case "MemberExpression":
      return (
        parent.object === node && reachesValidation(parent, sourceCode, seen, depth + 1, budget)
      );
    case "Property":
      return (
        parent.value === node &&
        parent.kind === "init" &&
        !parent.method &&
        reachesValidation(parent, sourceCode, seen, depth + 1, budget)
      );
    case "ConditionalExpression":
      return parent.test !== node && reachesValidation(parent, sourceCode, seen, depth + 1, budget);
    case "LogicalExpression":
      return (
        !(parent.operator === "&&" && parent.left === node) &&
        reachesValidation(parent, sourceCode, seen, depth + 1, budget)
      );
    case "ObjectExpression":
    case "ArrayExpression":
    case "SpreadElement":
    case "BinaryExpression":
    case "TemplateLiteral":
    case "TSAsExpression":
    case "TSNonNullExpression":
    case "TSSatisfiesExpression":
    case "TSTypeAssertion":
      return reachesValidation(parent, sourceCode, seen, depth + 1, budget);
    default:
      return false;
  }
}

/** Prove only an exact runtime identity, without interpreting arbitrary loader bodies. */
function identityFunction(node: Node): boolean {
  const value = unwrapExpression(node);
  if (
    value.type !== "ArrowFunctionExpression" &&
    value.type !== "FunctionExpression" &&
    value.type !== "FunctionDeclaration"
  )
    return false;
  if (
    value.async ||
    (value.type !== "ArrowFunctionExpression" && value.generator) ||
    value.params.length !== 1
  )
    return false;
  const [parameter] = value.params;
  if (parameter?.type !== "Identifier" || value.body === null) return false;
  let returned: Node = value.body;
  if (returned.type === "BlockStatement") {
    const [statement] = returned.body;
    if (
      returned.body.length !== 1 ||
      statement?.type !== "ReturnStatement" ||
      statement.argument === null
    )
      return false;
    returned = statement.argument;
  }
  const result = unwrapExpression(returned);
  return result.type === "Identifier" && result.name === parameter.name;
}

/** No alias, mutation, exported receiver or extra method is admitted by this proof. */
function isClosedIdentityAdapter(node: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  const callee = unwrapExpression(node.callee);
  const member = callee.type === "MemberExpression" ? callee : null;
  const receiver = member === null ? callee : unwrapExpression(member.object);
  const method = member === null ? null : getPropertyName(member);
  const output = parentOf(outerExpression(node));
  if (
    node.arguments.length !== 1 ||
    node.arguments[0]?.type === "SpreadElement" ||
    node.optional ||
    member?.optional ||
    output?.type === "AwaitExpression" ||
    output?.type === "ChainExpression"
  )
    return false;
  if (
    receiver.type !== "Identifier" ||
    (member === null ? receiver.name !== "createEnv" : method !== "parse" && method !== "safeParse")
  )
    return false;
  const variable = findVariable(sourceCode.getScope(receiver), receiver.name);
  if (
    variable?.defs.length !== 1 ||
    variable.references.length > 128 ||
    !stableValueBinding(variable)
  )
    return false;
  const value = privateIdentityValue(variable);
  if (value === null) return false;
  const methods = member === null ? null : identityMethods(value);
  if (member !== null && (methods === null || !methods.has(method ?? ""))) return false;
  if (member === null && !identityFunction(value)) return false;
  return identityReferences(variable, methods) && closedIdentityModule(sourceCode);
}

/** Resolve only private const/function definitions outside namespace ownership. */
function privateIdentityValue(variable: TsVariable): Node | null {
  const definition = variable.defs[0]?.node;
  if (definition === undefined) return null;
  let value: Node = definition;
  let declaration = parentOf(definition);
  if (definition.type === "VariableDeclarator") {
    if (
      definition.id.type !== "Identifier" ||
      definition.init === null ||
      declaration?.type !== "VariableDeclaration" ||
      declaration.kind !== "const"
    )
      return null;
    value = unwrapExpression(definition.init);
    declaration = parentOf(declaration);
  } else if (definition.type !== "FunctionDeclaration") return null;
  if (
    declaration?.type === "ExportNamedDeclaration" ||
    declaration?.type === "ExportDefaultDeclaration"
  )
    return null;
  let ancestor: Node | null = declaration;
  let ancestors = 32;
  while (ancestor !== null && ancestor.type !== "Program") {
    if (
      ancestors-- <= 0 ||
      ancestor.type === "TSModuleBlock" ||
      ancestor.type === "TSModuleDeclaration"
    )
      return null;
    ancestor = parentOf(ancestor);
  }
  return value;
}

/** Private bindings cannot be rewritten through a public namespace or direct eval. */
function closedIdentityModule(sourceCode: SourceCode): boolean {
  if (
    !sourceCode.ast.body.some(
      (statement) =>
        statement.type === "ImportDeclaration" ||
        statement.type === "ExportNamedDeclaration" ||
        statement.type === "ExportDefaultDeclaration" ||
        statement.type === "ExportAllDeclaration",
    )
  )
    return false;
  let remaining = 512;
  for (const scope of sourceCode.scopeManager.scopes) {
    for (const reference of scope.references) {
      if (remaining-- <= 0) return false;
      if (reference.identifier.name === "eval" && !typeOnlyReference(tsReference(reference)))
        return false;
    }
  }
  return true;
}

function identityMethods(value: Node): ReadonlySet<string> | null {
  if (
    value.type !== "ObjectExpression" ||
    value.properties.length === 0 ||
    value.properties.length > 2
  )
    return null;
  const methods = new Set<string>();
  for (const property of value.properties) {
    if (
      property.type !== "Property" ||
      property.kind !== "init" ||
      !identityFunction(property.value)
    )
      return null;
    const name = getPropertyName(property);
    if ((name !== "parse" && name !== "safeParse") || methods.has(name)) return null;
    methods.add(name);
  }
  return methods;
}

function identityReferences(variable: TsVariable, methods: ReadonlySet<string> | null): boolean {
  return variable.references.every((reference) => {
    if (reference.init === true || typeOnlyReference(reference)) return true;
    let target = outerExpression(reference.identifier);
    if (methods !== null) {
      const property = parentOf(target);
      if (
        property?.type !== "MemberExpression" ||
        property.object !== target ||
        property.optional ||
        !methods.has(getPropertyName(property) ?? "")
      )
        return false;
      target = outerExpression(property);
    }
    const use = parentOf(target);
    return (
      use?.type === "CallExpression" &&
      use.callee === target &&
      !use.optional &&
      parentOf(use)?.type !== "ChainExpression"
    );
  });
}

/** A declaration elsewhere in a module does not validate this particular read. */
function isValidationCall(node: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  const callee = unwrapExpression(node.callee);
  if (callee.type === "Identifier") {
    // Preserve existing project loaders; prove renamed T3 imports independently.
    if (callee.name === "createEnv") return true;
    const binding = findVariable(sourceCode.getScope(callee), callee.name);
    const definition = binding?.defs.length === 1 ? binding.defs[0] : undefined;
    const declaration = definition?.parent;
    const specifier = definition?.node;
    return (
      definition?.type === "ImportBinding" &&
      declaration?.type === "ImportDeclaration" &&
      declaration.importKind !== "type" &&
      ["@t3-oss/env-core", "@t3-oss/env-nextjs"].includes(declaration.source.value) &&
      specifier?.type === "ImportSpecifier" &&
      specifier.importKind !== "type" &&
      importSpecifierName(specifier) === "createEnv" &&
      binding !== null &&
      stableValueBinding(binding)
    );
  }
  if (callee.type !== "MemberExpression" || isNativeJsonParse(node, sourceCode)) return false;
  const method = getPropertyName(callee);
  if (method === "parse" || method === "safeParse") return true;
  if (method !== "parseAsync" && method !== "safeParseAsync") return false;
  const value = outerExpression(node);
  const parent = parentOf(value);
  return parent?.type === "AwaitExpression" && parent.argument === value;
}

/** JSON decoding alone does not validate the decoded settings contract. */
function isNativeJsonParse(node: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression" || getPropertyName(callee) !== "parse") return false;
  const receiver = unwrapExpression(callee.object);
  if (receiver.type !== "Identifier" || receiver.name !== "JSON") return false;
  const binding = findVariable(sourceCode.getScope(receiver), receiver.name);
  return binding === null || binding.defs.length === 0;
}

/** Keep raw input away from arbitrary effects before its validation call. */
function isScalarCoercion(node: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  const callee = unwrapExpression(node.callee);
  if (
    callee.type !== "Identifier" ||
    !["Number", "String", "Boolean", "BigInt"].includes(callee.name) ||
    node.arguments.length !== 1
  )
    return false;
  const binding = findVariable(sourceCode.getScope(callee), callee.name);
  return binding === null || binding.defs.length === 0;
}

/** Follow only the native whole environment and stable aliases, not raw field values. */
function isWholeEnvironment(
  node: Node,
  sourceCode: SourceCode,
  seen: ReadonlySet<TsVariable> = new Set(),
): boolean {
  const value = unwrapExpression(node);
  if (value.type === "MemberExpression")
    return isProcessEnv(value, sourceCode) || isImportMetaEnv(value);
  if (value.type !== "Identifier" || seen.size >= 16) return false;
  const variable = stableAliasBinding(value, sourceCode, seen);
  const definition = variable?.defs[0];
  if (variable === null || definition === undefined) return false;
  const declaration = definition.parent;
  const binding = definition.node;
  if (definition.type === "ImportBinding") {
    return (
      declaration?.type === "ImportDeclaration" &&
      declaration.importKind !== "type" &&
      PROCESS_MODULES.includes(declaration.source.value) &&
      binding.type === "ImportSpecifier" &&
      binding.importKind !== "type" &&
      importSpecifierName(binding) === "env"
    );
  }
  if (
    binding.type !== "VariableDeclarator" ||
    binding.init === null ||
    declaration?.type !== "VariableDeclaration" ||
    declaration.kind !== "const"
  )
    return false;
  if (binding.id.type === "Identifier")
    return isWholeEnvironment(binding.init, sourceCode, new Set([...seen, variable]));
  return (
    binding.id.type === "ObjectPattern" &&
    isNativeProcess(binding.init, sourceCode) &&
    binding.id.properties.some(
      (property) =>
        property.type === "Property" &&
        getPropertyName(property) === "env" &&
        property.value.type === "Identifier" &&
        property.value.name === value.name,
    )
  );
}

function stableAliasBinding(
  node: Identifier,
  sourceCode: SourceCode,
  seen: ReadonlySet<TsVariable>,
): TsVariable | null {
  const variable = findVariable(sourceCode.getScope(node), node.name);
  return variable !== null &&
    variable.defs.length === 1 &&
    !seen.has(variable) &&
    stableValueBinding(variable)
    ? variable
    : null;
}

/** Follow a stable raw input, or each plainly selected field, through every ordinary use. */
function validatedAlias(
  node: ESTree.VariableDeclarator,
  sourceCode: SourceCode,
  seen: ReadonlySet<TsVariable>,
  depth: number,
  budget: () => number,
): boolean {
  const declaration = parentOf(node);
  if (
    declaration?.type !== "VariableDeclaration" ||
    declaration.kind !== "const" ||
    parentOf(declaration)?.type === "ExportNamedDeclaration"
  )
    return false;
  if (node.id.type === "Identifier") {
    const variable = stableAliasBinding(node.id, sourceCode, seen);
    return variable !== null && validatedBinding(variable, sourceCode, seen, depth, budget);
  }
  if (node.id.type !== "ObjectPattern" || node.id.properties.length === 0 || node.init === null)
    return false;
  if (node.id.properties.length > 128) return true;
  return validatedFields(node.id, node.init, sourceCode, seen, depth, budget);
}

/** Selected field values share the same traversal allowance as their declaration. */
function validatedFields(
  pattern: ESTree.ObjectPattern,
  input: Node,
  sourceCode: SourceCode,
  seen: ReadonlySet<TsVariable>,
  depth: number,
  budget: () => number,
): boolean {
  const wholeEnvironment = isWholeEnvironment(input, sourceCode);
  for (const property of pattern.properties) {
    if (budget() <= 0) return true;
    if (property.type !== "Property" || property.value.type !== "Identifier") return false;
    const name = getPropertyName(property);
    if (name === null) return false;
    const variable = stableAliasBinding(property.value, sourceCode, seen);
    if (variable === null) return false;
    if (wholeEnvironment && (BUILD_TIME_CONSTANTS.has(name) || PLATFORM_MARKERS.has(name)))
      continue;
    if (!validatedBinding(variable, sourceCode, seen, depth, budget)) return false;
  }
  return true;
}

function validatedBinding(
  variable: TsVariable,
  sourceCode: SourceCode,
  seen: ReadonlySet<TsVariable>,
  depth: number,
  budget: () => number,
): boolean {
  const reads = variable.references.filter((ref) => ref.isRead() && !typeOnlyReference(ref));
  const next = new Set([...seen, variable]);
  if (reads.length > 128) return true;
  return (
    reads.length > 0 &&
    reads.every((ref) => reachesValidation(ref.identifier, sourceCode, next, depth + 1, budget))
  );
}

/** Preserve host-marker extraction without exempting arbitrary raw field patterns. */
function isPlatformExtraction(node: Node, sourceCode: SourceCode): boolean {
  const declaration = parentOf(node);
  return (
    declaration?.type === "VariableDeclarator" &&
    declaration.init === node &&
    declaration.id.type === "ObjectPattern" &&
    declaration.id.properties.length > 0 &&
    declaration.id.properties.length <= 128 &&
    declaration.id.properties.every((property) => {
      if (property.type !== "Property" || property.value.type !== "Identifier") return false;
      const name = getPropertyName(property);
      return name !== null && (BUILD_TIME_CONSTANTS.has(name) || PLATFORM_MARKERS.has(name));
    }) &&
    isWholeEnvironment(node, sourceCode) &&
    validatedAlias(declaration, sourceCode, new Set(), 0, createValidationBudget())
  );
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow direct `process.env` and `import.meta.env` reads outside validated boundaries.",
      url: docsUrl("no-raw-env"),
    },
    schema: [],
    messages: {
      noRawEnv:
        "Read one shared settings object validated at startup with Zod (or the existing typed settings loader). Parse required environment values once at the boundary and inject or import the validated result.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let reads: Node[] = [];
    let boundaryFile = false;

    function recordRead(node: Node): void {
      if (
        !isExemptVariableAccess(node) &&
        !isWriteTarget(node) &&
        !isPlatformExtraction(node, sourceCode) &&
        !(isWholeEnvSpread(node) && !boundaryFile)
      )
        reads.push(node);
    }

    function recordAlias(node: Identifier): void {
      const variable = findVariable(sourceCode.getScope(node), node.name);
      if (variable?.defs.length !== 1 || !stableValueBinding(variable)) return;
      for (const reference of variable.references) {
        if (reference.isRead() && !typeOnlyReference(reference)) recordRead(reference.identifier);
      }
    }

    return {
      before() {
        const filename = context.filename;
        const file = { filename, cwd: context.cwd };
        boundaryFile = ENV_BOUNDARY_FILE_RE.test(filename);
        if (
          isTestFile(file) ||
          (isScriptFile(file) && !boundaryFile) ||
          CONFIG_FILE_RE.test(filename)
        ) {
          return false;
        }
        sourceCode = context.sourceCode;
        reads = [];
        return undefined;
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (node.importKind === "type" || !PROCESS_MODULES.includes(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportSpecifier" &&
            specifier.importKind !== "type" &&
            importSpecifierName(specifier) === "env"
          )
            recordAlias(specifier.local);
        }
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        const declaration = parentOf(node);
        if (
          node.id.type !== "ObjectPattern" ||
          node.init === null ||
          declaration?.type !== "VariableDeclaration" ||
          declaration.kind !== "const" ||
          !isNativeProcess(node.init, sourceCode)
        )
          return;
        for (const property of node.id.properties) {
          if (
            property.type === "Property" &&
            getPropertyName(property) === "env" &&
            property.value.type === "Identifier"
          )
            recordAlias(property.value);
        }
      },
      MemberExpression(node: ESTree.MemberExpression): void {
        if (isProcessEnv(node, sourceCode) || isImportMetaEnv(node)) recordRead(node);
      },
      "Program:exit"(): void {
        for (const node of reads) {
          if (!boundaryFile || !reachesValidation(node, sourceCode))
            context.report({ node, messageId: "noRawEnv" });
        }
      },
    };
  },
});

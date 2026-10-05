import {
  resolveVariable,
  unwrapExpression,
  isGlobalReference,
} from "../rules/_scope.ts";

const QUERY_RESULTS = new Set([
  "UseBaseQueryResult",
  "UseQueryResult",
  "UseSuspenseQueryResult",
  "DefinedUseQueryResult",
  "UseInfiniteQueryResult",
  "UseSuspenseInfiniteQueryResult",
  "DefinedUseInfiniteQueryResult",
  "QueryObserverResult",
  "InfiniteQueryObserverResult",
]);
const QUERY_HOOKS = new Set([
  "useQuery",
  "useInfiniteQuery",
  "useSuspenseQuery",
  "useSuspenseInfiniteQuery",
]);

export function returnsVoid(node, sourceCode, visited = new Set()) {
  node = unwrapExpression(node);
  if (visited.has(node)) return false;
  visited.add(node);
  const annotation = functionReturnAnnotation(node, sourceCode);
  if (annotation) return hasVoidType(annotation, sourceCode);
  if (node.type === "Identifier") {
    const declaration = resolveVariable(sourceCode, node)?.defs[0]?.node;
    if (declaration?.type === "VariableDeclarator" && declaration.init)
      return returnsVoid(declaration.init, sourceCode, visited);
    if (declaration?.type === "FunctionDeclaration")
      return returnsVoid(declaration, sourceCode, visited);
    return false;
  }
  if (!isFunction(node) || !node.body) return false;
  if (node.body.type !== "BlockStatement")
    return isVoidValue(node.body, sourceCode, visited);
  const result = blockFlow(node.body, sourceCode, visited);
  return result.voidReturn || (!result.exits && !result.uncertain);
}

function functionReturnAnnotation(node, sourceCode) {
  if (node.returnType) return node.returnType.typeAnnotation;
  if (node.type !== "Identifier") return null;
  const variable = resolveVariable(sourceCode, node);
  const declaration = variable?.defs[0]?.node;
  if (declaration?.returnType) return declaration.returnType.typeAnnotation;
  const annotation =
    variable?.identifiers[0]?.typeAnnotation?.typeAnnotation ??
    declaration?.id?.typeAnnotation?.typeAnnotation;
  return functionTypeReturn(annotation, sourceCode);
}

function functionTypeReturn(node, sourceCode, visited = new Set()) {
  if (!node || visited.has(node)) return null;
  visited.add(node);
  if (node.type === "TSFunctionType") return node.returnType.typeAnnotation;
  if (node.type === "TSParenthesizedType")
    return functionTypeReturn(node.typeAnnotation, sourceCode, visited);
  if (node.type !== "TSTypeReference" || node.typeName.type !== "Identifier")
    return null;
  const declaration = resolveVariable(sourceCode, node.typeName)?.defs[0]?.node;
  return declaration?.type === "TSTypeAliasDeclaration"
    ? functionTypeReturn(declaration.typeAnnotation, sourceCode, visited)
    : null;
}

function hasVoidType(node, sourceCode, visited = new Set()) {
  if (visited.has(node)) return false;
  visited.add(node);
  if (node.type === "TSVoidKeyword" || node.type === "TSUndefinedKeyword")
    return true;
  if (node.type === "TSUnionType")
    return node.types.some((type) => hasVoidType(type, sourceCode, visited));
  if (node.type === "TSParenthesizedType")
    return hasVoidType(node.typeAnnotation, sourceCode, visited);
  if (node.type !== "TSTypeReference" || node.typeName.type !== "Identifier")
    return false;
  const declaration = resolveVariable(sourceCode, node.typeName)?.defs[0]?.node;
  if (declaration?.type === "TSTypeAliasDeclaration")
    return hasVoidType(declaration.typeAnnotation, sourceCode, visited);
  if (declaration) return false;
  if (node.typeName.name !== "Promise" && node.typeName.name !== "PromiseLike")
    return false;
  return (node.typeArguments?.params ?? []).some((type) =>
    hasVoidType(type, sourceCode, visited),
  );
}

function isFunction(node) {
  return (
    node.type === "FunctionDeclaration" ||
    node.type === "TSDeclareFunction" ||
    node.type === "FunctionExpression" ||
    node.type === "ArrowFunctionExpression"
  );
}

function isVoidValue(node, sourceCode, visited) {
  node = unwrapExpression(node);
  if (node.type === "UnaryExpression" && node.operator === "void") return true;
  if (
    node.type === "Identifier" &&
    isGlobalReference(sourceCode, node, "undefined")
  )
    return true;
  if (node.type === "Identifier") {
    const declaration = resolveVariable(sourceCode, node)?.defs[0]?.node;
    if (
      declaration?.type !== "VariableDeclarator" ||
      declaration.parent.kind !== "const" ||
      !declaration.init ||
      visited.has(declaration)
    )
      return false;
    visited.add(declaration);
    return isVoidValue(declaration.init, sourceCode, visited);
  }
  if (node.type === "ConditionalExpression")
    return (
      isVoidValue(node.consequent, sourceCode, visited) ||
      isVoidValue(node.alternate, sourceCode, visited)
    );
  if (node.type === "AwaitExpression")
    return isVoidValue(node.argument, sourceCode, visited);
  if (node.type !== "CallExpression") return false;
  if (node.callee.type === "Identifier")
    return returnsVoid(node.callee, sourceCode, visited);
  if (
    node.callee.type !== "MemberExpression" ||
    node.callee.computed ||
    node.callee.property.type !== "Identifier"
  )
    return false;
  return (
    ["log", "info", "warn", "error", "debug", "trace"].includes(
      node.callee.property.name,
    ) && isGlobalReference(sourceCode, node.callee.object, "console")
  );
}

function blockFlow(block, sourceCode, visited) {
  const result = { exits: false, voidReturn: false, uncertain: false };
  for (const statement of block.body) {
    const next = statementFlow(statement, sourceCode, visited);
    result.voidReturn ||= next.voidReturn;
    result.uncertain ||= next.uncertain;
    if (next.exits) {
      result.exits = true;
      break;
    }
  }
  return result;
}

function statementFlow(node, sourceCode, visited) {
  if (node.type === "ReturnStatement")
    return {
      exits: true,
      voidReturn:
        !node.argument || isVoidValue(node.argument, sourceCode, visited),
      uncertain: false,
    };
  if (node.type === "ThrowStatement")
    return { exits: true, voidReturn: false, uncertain: false };
  if (node.type === "BlockStatement")
    return blockFlow(node, sourceCode, visited);
  if (node.type === "IfStatement") {
    const left = statementFlow(node.consequent, sourceCode, visited);
    const right = node.alternate
      ? statementFlow(node.alternate, sourceCode, visited)
      : { exits: false, voidReturn: false, uncertain: false };
    return {
      exits: left.exits && right.exits,
      voidReturn: left.voidReturn || right.voidReturn,
      uncertain: left.uncertain || right.uncertain,
    };
  }
  if (
    [
      "ForStatement",
      "ForOfStatement",
      "ForInStatement",
      "WhileStatement",
      "DoWhileStatement",
    ].includes(node.type)
  )
    return loopFlow(node, sourceCode, visited);
  if (node.type === "TryStatement") return tryFlow(node, sourceCode, visited);
  if (node.type === "SwitchStatement")
    return switchFlow(node, sourceCode, visited);
  return { exits: false, voidReturn: false, uncertain: false };
}

function loopFlow(node, sourceCode, visited) {
  const body = statementFlow(node.body, sourceCode, visited);
  if (node.type === "DoWhileStatement" && body.exits) return body;
  const mayNeverExit =
    (node.type === "ForStatement" && !node.test) || node.test?.value === true;
  return {
    exits: false,
    voidReturn: body.voidReturn,
    uncertain: body.uncertain || mayNeverExit,
  };
}

function tryFlow(node, sourceCode, visited) {
  const body = blockFlow(node.block, sourceCode, visited);
  const handler = node.handler
    ? blockFlow(node.handler.body, sourceCode, visited)
    : body;
  const finalizer = node.finalizer
    ? blockFlow(node.finalizer, sourceCode, visited)
    : { exits: false, voidReturn: false, uncertain: false };
  if (finalizer.exits) return finalizer;
  return {
    exits: body.exits && handler.exits,
    voidReturn: body.voidReturn || handler.voidReturn || finalizer.voidReturn,
    uncertain: body.uncertain || handler.uncertain || finalizer.uncertain,
  };
}

function switchFlow(node, sourceCode, visited) {
  const branches = node.cases.map((branch) =>
    blockFlow({ body: branch.consequent }, sourceCode, visited),
  );
  const exits =
    node.cases.some((branch) => !branch.test) &&
    branches.every((branch) => branch.exits);
  return {
    exits,
    voidReturn: branches.some((branch) => branch.voidReturn),
    uncertain: !exits || branches.some((branch) => branch.uncertain),
  };
}

export function returnsQueryResult(call, sourceCode, visited = new Set()) {
  const callee = unwrapExpression(call.callee);
  if (callee.type !== "Identifier") return false;
  const declaration = resolveVariable(sourceCode, callee)?.defs[0]?.node;
  if (declaration?.type === "ImportSpecifier") {
    return (
      QUERY_HOOKS.has(declaration.imported.name) && isQueryImport(declaration)
    );
  }
  const fn =
    declaration?.type === "VariableDeclarator" ? declaration.init : declaration;
  if (!fn || !isFunction(fn) || visited.has(fn)) return false;
  visited.add(fn);
  if (hasQueryResultType(fn.returnType?.typeAnnotation, sourceCode))
    return true;
  return functionReturns(fn).some((value) =>
    queryResultValue(value, sourceCode, visited),
  );
}

function hasQueryResultType(node, sourceCode, visited = new Set()) {
  if (!node || visited.has(node)) return false;
  visited.add(node);
  if (node.type === "TSTypeReference" && node.typeName.type === "Identifier") {
    const declaration = resolveVariable(sourceCode, node.typeName)?.defs[0]
      ?.node;
    if (declaration?.type === "TSTypeAliasDeclaration")
      return hasQueryResultType(
        declaration.typeAnnotation,
        sourceCode,
        visited,
      );
    return (
      declaration?.type === "ImportSpecifier" &&
      QUERY_RESULTS.has(declaration.imported.name) &&
      isQueryImport(declaration)
    );
  }
  return (
    node.type === "TSUnionType" &&
    node.types.some((type) => hasQueryResultType(type, sourceCode, visited))
  );
}

function isQueryImport(specifier) {
  return (
    specifier.parent.source.value.startsWith("@tanstack/") &&
    specifier.parent.source.value.endsWith("-query")
  );
}

function functionReturns(fn) {
  if (!fn.body) return [];
  if (fn.body.type !== "BlockStatement") return [fn.body];
  const results = [];
  const visit = (node) => {
    if (isFunction(node)) return;
    if (node.type === "ReturnStatement") {
      if (node.argument) results.push(node.argument);
      return;
    }
    for (const [key, value] of Object.entries(node)) {
      if (key === "parent") continue;
      if (Array.isArray(value)) {
        for (const child of value) if (child?.type) visit(child);
      } else if (value?.type) visit(value);
    }
  };
  visit(fn.body);
  return results;
}

function queryResultValue(node, sourceCode, visited) {
  node = unwrapExpression(node);
  if (visited.has(node)) return false;
  visited.add(node);
  if (node.type === "CallExpression")
    return returnsQueryResult(node, sourceCode, visited);
  if (node.type === "ConditionalExpression")
    return (
      queryResultValue(node.consequent, sourceCode, visited) ||
      queryResultValue(node.alternate, sourceCode, visited)
    );
  if (node.type !== "Identifier") return false;
  const declaration = resolveVariable(sourceCode, node)?.defs[0]?.node;
  return declaration?.type === "VariableDeclarator" && declaration.init
    ? queryResultValue(declaration.init, sourceCode, visited)
    : false;
}

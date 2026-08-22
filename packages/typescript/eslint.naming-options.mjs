export const MODULE_CONSTANT_NAMING_OPTIONS = [
  {
    selector: "variable",
    modifiers: ["const", "global"],
    filter: {
      regex:
        "^(Route|action|clientAction|clientLoader|config|csr|dynamic|dynamicParams|entries|fetchCache|handle|headers|instant|links|loader|maxDuration|meta|metadata|partial|prefetch|preferredRegion|prerender|revalidate|runtime|shouldRevalidate|ssr|trailingSlash|viewport)$",
      match: true,
    },
    format: null,
  },
  {
    selector: "variable",
    modifiers: ["const", "global"],
    types: ["function"],
    format: ["camelCase", "PascalCase", "UPPER_CASE"],
    leadingUnderscore: "allow",
  },
  {
    selector: "variable",
    modifiers: ["const", "global"],
    format: ["UPPER_CASE"],
    leadingUnderscore: "allow",
  },
];
